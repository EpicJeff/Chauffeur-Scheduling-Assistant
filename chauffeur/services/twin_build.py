"""Restartable, piece-by-piece house builds from cropped drawing reads.

The lifecycle lock covers publication, never a reader call. A stopped worker
can cache its paid answer, but only the active worker may publish plan changes.
"""
from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import quote
import uuid

from services import (twin_compose, twin_cost, twin_draft, twin_library,
                      twin_place, twin_plan, twin_reads, twin_register, twin_store)

_LOCK = threading.RLock()
_BUILDS = {}
_WORKERS = {}
_ACTIVE = ('running', 'paused', 'checkpoint')
_FULL = [0, 0, 1, 1]
logger = logging.getLogger(__name__)
_LABELS = {'roof': 'Roof sections', 'pitch': 'Roof slopes', 'plot': 'Lot',
           'site': 'Yard', 'compose': 'Plants and beds', 'finishes': 'Colours and finishes'}


class _ReadError(ValueError):
    """An unsuccessful reader reply leaves the step retryable, without a cache."""


def _step(kind, row=None, level=None, pause=None, name=None):
    row = row or {}
    sid = f'{kind}:{level}' if level else kind
    return {'id': sid, 'kind': kind, 'label': name or _LABELS.get(kind, kind.replace('_', ' ').capitalize()),
            'pause': pause, 'source': row.get('source'), 'page': row.get('page'),
            'level': level, 'box': deepcopy(row.get('box')), 'status': 'pending',
            'level_name': row.get('level') or level}


def plan_steps(page_roles, photos, plot, *, part=None, placement=None, has_lot=False, compose=True):
    """Static skeleton; wing steps are inserted only after an accepted read."""
    if part == 'lot':
        steps = [_step('lot', plot[0]) if placement else _step('plot', plot[0], pause='lot_placement'),
                 _step('site', plot[0])]
        if compose:
            steps.append(_step('compose'))
        return steps
    steps = []
    floors = sorted((r for r in page_roles if r['role'] == 'floor'),
                    key=lambda r: (r['page'], r.get('box') or _FULL, r.get('source', '')))
    if part is not None and not floors:
        return [_step('shell')] + ([_step('compose')] if compose else [])
    for index, row in enumerate(floors):
        level = f'L{index + 1}'
        row = {**row, 'level': row.get('level') or f'Floor {index + 1}'}
        kind, pause = ('outline', 'scale_outline') if index == 0 else ('registration', 'level_registration')
        steps.append(_step(kind, row, level, pause, f"{row.get('level') or level} outline"))
        steps.extend(_step(k, row, level, name=f"{row.get('level') or level} {k}")
                     for k in ('openings', 'rooms'))
    roof = next((r for r in page_roles if r['role'] == 'roof'), None)
    if roof:
        steps.append(_step('roof', roof))
        if photos:
            steps.append(_step('pitch'))
    if plot and part is None:
        steps.extend((_step('plot', plot[0], pause='lot_placement'), _step('site', plot[0])))
    if photos:
        steps.append(_step('finishes'))
    if part is not None and has_lot:
        steps.append(_step('fit', pause='lot_placement'))
    if compose:
        steps.append(_step('compose'))
    return steps


def _root(bid):
    if not isinstance(bid, str) or not re.fullmatch(r'[a-f0-9]{32}', bid):
        raise KeyError(bid)
    return Path(twin_store.DATA_DIR) / 'builds' / bid


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            json.dump(value, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _get(bid):
    if bid not in _BUILDS:
        try:
            _BUILDS[bid] = json.loads((_root(bid) / 'state.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise KeyError(bid) from None
    build = _BUILDS[bid]
    if build['generation'] != twin_store.generation():
        _BUILDS.pop(bid, None)
        raise twin_store.StaleGeneration('The house was started over.')
    return build


def _save(build):
    if build['generation'] != twin_store.generation():
        raise twin_store.StaleGeneration('The house was started over.')
    _atomic(_root(build['id']) / 'state.json', build)


def _event(build, event_type, **fields):
    build['seq'] += 1
    build['events'].append({'seq': build['seq'], 'type': event_type, **deepcopy(fields)})


def _live(build, ticket):
    return (_BUILDS.get(build['id']) is build and build['state'] == 'running'
            and _WORKERS.get(build['id'], {}).get('ticket') == ticket
            and build['generation'] == twin_store.generation())


def running():
    with _LOCK:
        return any(b['state'] in _ACTIVE for b in _BUILDS.values())


def stop_for_start_over():
    """Called under LIFECYCLE: paused and checkpoint builds stop; a running one
    must be stopped first. A stopped read still in flight is let go, since its
    late answer is refused by the generation check."""
    with _LOCK:
        if any(b['state'] == 'running' for b in _BUILDS.values()):
            raise ValueError('Stop the build before starting over.')
        for build in _BUILDS.values():
            if build['state'] in ('paused', 'checkpoint'):
                build['state'] = 'stopped'
                _save(build)


def latest():
    """Return the current generation's most recently saved build id, if any."""
    with twin_store.LIFECYCLE, _LOCK:
        generation = twin_store.generation()
        saved = []
        for bid, build in _BUILDS.items():
            if build['generation'] != generation:
                continue
            try:
                modified = (_root(bid) / 'state.json').stat().st_mtime_ns
            except FileNotFoundError:
                continue
            saved.append((modified, bid))
        return max(saved)[1] if saved else None


def status(build_id, since=0):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        return deepcopy({'part': build['inputs'].get('part'), 'next': build.get('next'),
                         **{key: ([e for e in build[key] if e['seq'] > since]
                               if key == 'events' else build[key])
                         for key in ('id', 'state', 'steps', 'events', 'seq', 'pause', 'cost')}})


def _launch(build, reader, inline):
    ticket = uuid.uuid4().hex
    _WORKERS[build['id']] = {'reader': reader, 'inline': inline, 'ticket': ticket, 'busy': True}
    build['state'] = 'running'
    _save(build)
    return ticket


def _dispatch(build, ticket, reader, inline):
    if inline:
        _run(build, ticket, reader)
    else:
        threading.Thread(target=_run, args=(build, ticket, reader), daemon=True,
                         name=f"twin-build-{build['id'][:8]}").start()


def start(inputs, *, reader=None, inline=False):
    reader = reader or twin_reads.read
    with twin_store.LIFECYCLE, _LOCK:
        if running() or any(worker.get('busy') for worker in _WORKERS.values()):
            raise ValueError('A build is already running.')
        inputs = deepcopy(inputs)
        # Chaining and composition are engine decisions, never caller options.
        inputs.update(compose=True, then=[])
        skipped = []
        if inputs.get('part') == 'place':
            place = twin_store.place()
            pages = twin_store.page_roles()
            parts = ['lot'] if any(r['role'] == 'plot' and r.get('building') == 'lot'
                                  for r in pages) else []
            drawings, shells = [], []
            for building in place['buildings']:
                if any(r['role'] == 'floor' and r.get('building') == building['id'] for r in pages):
                    drawings.append(building['id'])
                elif building.get('footprint'):
                    shells.append(building['id'])
                else:
                    skipped.append(f"Skipped {building['name']}: it has no footprint yet.")
            parts.extend(drawings + shells)
            if not parts:
                raise ValueError('Add a building with drawings or a footprint first.')
            inputs.update(part=parts[0], then=parts[1:], compose=len(parts) == 1)
        build = _create(inputs)
        for message in skipped:
            _event(build, 'log', text=message)
        ticket = _launch(build, reader, inline)
    _dispatch(build, ticket, reader, inline)
    return build['id']


def _create(inputs):
    """Create one part under LIFECYCLE then _LOCK; caller saves and dispatches."""
    inputs = deepcopy(inputs)
    inputs.pop('shell', None)
    part = inputs.get('part')
    place = twin_store.place() if part is not None else None
    pages = twin_store.page_roles()
    plot = [r for r in pages if r['role'] == 'plot'
            and (part is None or r.get('building') == 'lot')]
    placement = None
    if part == 'lot':
        inputs.pop('building', None)
        inputs['photos'] = []
        roles = []
        if not plot:
            raise ValueError('Add a plot plan to the lot first.')
        candidate = place['lot'].get('placement') or {}
        if candidate.get('confirmed') and all(candidate.get(k) == plot[0].get(k) for k in ('source', 'page', 'box')):
            placement = deepcopy(candidate)
    else:
        if part is not None:
            part_building = next((b for b in place['buildings'] if b['id'] == part), None)
            if part_building is None:
                raise ValueError('Choose a building in your place.')
            inputs['building'] = {k: part_building[k] for k in ('id', 'name', 'kind')}
            inputs['photos'] = twin_store.photos_for(part)
        building = inputs['building']
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', building['id']):
            raise ValueError('A building needs a valid id.')
        roles = [r for r in pages if r.get('building', 'house') == building['id']]
        if not any(r['role'] == 'floor' for r in roles):
            if part is None:
                raise ValueError('Confirm floor page roles for this building before building.')
            inputs['shell'] = twin_place.shell_building(part_building, 'shell')
    photos = {s['id'] for s in twin_store.sources() if s['kind'] == 'photo'}
    photo_ids = inputs.get('photos', [])
    if (not isinstance(photo_ids, list)
            or any(not isinstance(source, str) or source not in photos for source in photo_ids)):
        raise ValueError('Every photo id must name an existing photo source.')
    bid = uuid.uuid4().hex
    current = twin_store.current()
    has_lot = bool((current or {}).get('site', {}).get('lot')
                   or (place and ((place['lot'].get('placement') or {}).get('outline')
                                  or (place['lot'].get('read') or {}).get('lot'))))
    build = {'id': bid, 'inputs': deepcopy(inputs), 'generation': twin_store.generation(),
             'state': 'running', 'steps': plan_steps(roles, inputs.get('photos', []), plot,
                 part=part, placement=placement, has_lot=has_lot, compose=inputs['compose']),
             'placement': placement, 'next': None,
             'events': [], 'seq': 0, 'pause': None, 'cost': 0,
             'existing': bool(part != 'lot' and current
                              and any(b['id'] == building['id'] for b in current['buildings']))}
    _BUILDS[bid] = build
    return build


def _chain(build):
    """Save a stopped successor and its handoff while both locks are held.

    The reverse link lets recovery reuse a successor saved just before a crash
    that prevented saving its predecessor's next pointer.
    """
    if (build['generation'] != twin_store.generation() or build['state'] != 'done'
            or build.get('next') or not build['inputs'].get('then')):
        return None
    remaining = build['inputs']['then']
    successor = next((b for b in _BUILDS.values()
                      if b.get('previous') == build['id'] and b['generation'] == build['generation']), None)
    if successor is None:
        successor = _create({'part': remaining[0], 'then': remaining[1:], 'compose': len(remaining) == 1})
        successor.update(state='stopped', previous=build['id'])
        _save(successor)
    build['next'] = successor['id']
    _event(build, 'next', id=successor['id'])
    _save(build)
    return successor


def stop(build_id):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        if build['state'] != 'done':
            build['state'] = 'stopped'
            _save(build)
    return status(build_id)


def resume(build_id, *, reader=None, inline=None):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        if build['state'] in ('running', 'done'):
            return status(build_id)
        if any(b['id'] != build_id and b['state'] in _ACTIVE for b in _BUILDS.values()):
            raise ValueError('A build is already running.')
        runtime = _WORKERS.get(build_id, {})
        if runtime.get('busy'):
            raise ValueError('The build is still stopping; wait for its read to return.')
        reader = reader or runtime.get('reader') or twin_reads.read
        inline = runtime.get('inline', False) if inline is None else inline
        ticket = _launch(build, reader, inline)
    _dispatch(build, ticket, reader, inline)
    return status(build_id)


def recover():
    with twin_store.LIFECYCLE, _LOCK:
        recovered = []
        for path in (Path(twin_store.DATA_DIR) / 'builds').glob('*/state.json'):
            try:
                build = _get(path.parent.name)
                if (build['id'] != path.parent.name or build['state'] not in (*_ACTIVE, 'stopped', 'done', 'failed')
                        or not isinstance(build['steps'], list) or not isinstance(build['events'], list)
                        or not isinstance(build['inputs'].get('part') or build['inputs'].get('building', {}).get('id'), str)
                        or not isinstance(build['seq'], int) or 'pause' not in build or 'cost' not in build):
                    raise ValueError('Incomplete build state')
                if (any(not isinstance(s, dict) or not {'id', 'kind', 'label', 'status', 'level', 'source', 'page', 'box', 'pause'} <= s.keys()
                        for s in build['steps'])
                        or any(not isinstance(e, dict) or not {'seq', 'type'} <= e.keys() for e in build['events'])
                        or (build['state'] == 'paused' and (not isinstance(build['pause'], dict)
                            or not {'kind', 'step', 'registration'} <= build['pause'].keys()))):
                    raise ValueError('Incomplete build steps or pause')
                if build['state'] == 'running':
                    build['state'] = 'stopped'
                    _save(build)
                recovered.append(build)
            except twin_store.StaleGeneration:
                continue
            except (ValueError, KeyError, TypeError, OSError):
                _BUILDS.pop(path.parent.name, None)
                logger.warning('Skipping unreadable twin build %s', path.parent.name, exc_info=True)
                continue
        # Load every saved successor before reconciling a missing forward link.
        # Recovered successors wait for Resume rather than starting paid reads.
        for build in recovered:
            try:
                _chain(build)
            except (ValueError, KeyError, TypeError, OSError):
                logger.warning('Could not recover twin build chain %s', build['id'], exc_info=True)


def _forget():
    """Test seam: forget process-local readers, tickets and state."""
    with twin_store.LIFECYCLE, _LOCK:
        _BUILDS.clear()
        _WORKERS.clear()


def _cache_path(build, step):
    return _root(build['id']) / 'steps' / (quote(step['id'], safe='') + '.json')


def _house(plan, build):
    if build['inputs'].get('part') == 'lot':
        return None
    return next(b for b in plan['buildings'] if b['id'] == build['inputs']['building']['id'])


def _base(plan, build, lot=None):
    plan = deepcopy(plan) if plan else {'units': 'ft', 'buildings': [], 'site': {}, 'materials': {}}
    if build['inputs'].get('part') == 'lot':
        if lot is not None:
            plan['site']['lot'] = deepcopy(lot)
        return twin_plan.normalize(plan)[0]
    bid = build['inputs']['building']['id']
    levels = [{'id': s['level'], 'name': s['level_name'], 'elevation': i * 9, 'ceiling': 9}
              for i, s in enumerate(s for s in build['steps'] if s['kind'] in ('outline', 'registration'))]
    if 'shell' in build['inputs']:
        levels = deepcopy(build['inputs']['shell']['levels'])
    if not levels:
        raise ValueError('No floor sheets are confirmed for this building.')
    if not any(b['id'] == bid for b in plan['buildings']):
        plan['buildings'].append({**deepcopy(build['inputs']['building']), 'levels': levels,
                                  'position': [0, 0], 'rotation': 0, 'walls': [], 'openings': [],
                                  'rooms': [], 'roof': {'sections': []}})
    else:
        house = _house(plan, build)
        if build['inputs'].get('part') is not None:
            house.update(deepcopy(build['inputs']['building']))
        house['levels'].extend(l for l in levels if not any(old['id'] == l['id'] for old in house['levels']))
    return twin_plan.normalize(plan)[0]


def _outline(plan, build, level=None):
    house = _house(plan, build)
    return next(l.get('outline', []) for l in house['levels'] if level is None or l['id'] == level)


def _map(crop, reg, point):
    return twin_register.apply(reg, twin_store.crop_to_master(crop, point))


def _dimension(crop, dim):
    return twin_register.from_dimension(twin_store.crop_to_master(crop, dim['a']),
                                        twin_store.crop_to_master(crop, dim['b']), dim['feet'])


def _fit(reg, moving, fixed):
    move, rms = twin_register.fit_outline(moving, fixed)
    # A rigid fit lives in feet; compose it after the sheet registration.
    offset = twin_register.to_world({'position': move['offset'], 'rotation': move['angle']}, reg['offset'])
    return twin_register.make(reg['scale'], reg['angle'] + move['angle'], reg['origin_px'], offset), rms


def _bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def _corners(box):
    x0, y0, x1, y1 = box
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _grow(poly, amount):
    """Offset each footprint edge outward and intersect adjoining edges."""
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))
    edges = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length:
            sign = 1 if area > 0 else -1
            edges.append(([a[0] + sign * dy / length * amount,
                           a[1] - sign * dx / length * amount], [dx, dy]))
    grown = []
    for (a, u), (b, v) in zip(edges[-1:] + edges[:-1], edges):
        cross = u[0] * v[1] - u[1] * v[0]
        t = ((b[0] - a[0]) * v[1] - (b[1] - a[1]) * v[0]) / cross if abs(cross) > 1e-12 else 0
        grown.append([a[0] + t * u[0], a[1] + t * u[1]])
    return grown


def _nearest(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2)) if length2 else 0
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy), t * math.sqrt(length2)


def _inside(point, polygon):
    """Building-local feet, including points on the boundary."""
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if _nearest(point, a, b)[0] < 1e-7:
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return inside


def _supported_walls(walls, anchors):
    # Prune unsupported ends before finding anchored components. Looking only
    # at already-settled walls deadlocks mutually supporting T junctions.
    candidates = list(walls)
    while candidates:
        supported = [w for w in candidates if all(
            any(_nearest(p, a, b)[0] <= 2 for a, b in anchors)
            or any(other is not w and _nearest(p, other['from'], other['to'])[0] <= 2
                   for other in candidates) for p in (w['from'], w['to']))]
        if len(supported) == len(candidates):
            break
        candidates = supported
    reached = []
    while candidates:
        ready = [w for w in candidates if any(
            _nearest(p, a, b)[0] <= 2 for p in (w['from'], w['to']) for a, b in anchors)]
        if not ready:
            break
        for wall in ready:
            reached.append(wall)
            anchors.append((wall['from'], wall['to']))
            candidates.remove(wall)
    return reached


def _piece(build, step, piece_kind, index, **fields):
    identity = f'{piece_kind}:{uuid.uuid4().hex}'
    return {'id': identity, 'state': 'ghost', 'src': {'sheet': step['source'] or '',
            'page': step['page'] or 1, 'step': step['id']}, **fields}


def _geometry(piece, kind, house):
    if kind == 'opening':
        wall = next((w for w in house['walls'] if w['id'] == piece.get('wall')), None)
        if wall:
            length = math.dist(wall['from'], wall['to'])
            if piece.get('state') == 'ghost' and 'position' in piece:
                center = piece['position']
                return {key: [center[i] + (wall['to'][i] - wall['from'][i]) / length * d for i in (0, 1)]
                        for key, d in (('from', -piece['width'] / 2), ('to', piece['width'] / 2))}
            return {key: [wall['from'][i] + (wall['to'][i] - wall['from'][i]) / length * d for i in (0, 1)]
                    for key, d in (('from', piece['at'] - piece['width'] / 2), ('to', piece['at'] + piece['width'] / 2))}
    return {key: piece[key] for key in ('from', 'to', 'polygon', 'rect', 'position', 'at', 'points', 'polyline') if key in piece}


def _near_geometry(a, b, kind=None):
    if a.keys() != b.keys() or not a:
        return False
    if kind == 'opening' and 'from' in a:
        return math.dist([(a['from'][i] + a['to'][i]) / 2 for i in (0, 1)],
                         [(b['from'][i] + b['to'][i]) / 2 for i in (0, 1)]) <= 1
    if kind == 'room' and 'polygon' in a:
        return math.dist(_centroid(a['polygon']), _centroid(b['polygon'])) <= 1
    if kind == 'roof' and 'rect' in a:
        return all(math.dist(x, y) <= 1 for x, y in zip(_corners(a['rect']), _corners(b['rect'])))
    if 'from' in a:
        return all(_nearest(a[key], b['from'], b['to'])[0] <= 1 for key in ('from', 'to'))
    if 'at' in a or 'position' in a:
        return all(math.dist(a[key], b[key]) <= 1 for key in a)
    def points(g):
        if 'rect' in g:
            return _corners(g['rect'])
        return next(g[key] for key in ('polygon', 'points', 'polyline') if key in g)
    aa, bb = points(a), points(b)
    closed = 'rect' in b or 'polygon' in b
    edges = list(zip(bb, bb[1:] + (bb[:1] if closed else [])))
    return bool(edges) and all(min(_nearest(p, x, y)[0] for x, y in edges) <= 1 for p in aa)


def _deleted(piece, kind, house, build):
    level = piece.get('level')
    if kind == 'opening':
        level = next((w['level'] for w in house['walls'] if w['id'] == piece.get('wall')), None)
    src = piece.get('src', {})
    return any(t['kind'] == kind and t['level'] == level
               and (t.get('building') is None or t['building'] == (house or {}).get('id'))
               and t['src'].get('sheet') == src.get('sheet')
               and t['src'].get('page') == src.get('page')
               and any(_near_geometry(_geometry(piece, kind, house), geometry, kind)
                       for geometry in (t['geometry'], t.get('read_geometry') or {}))
               for t in twin_store.tombstones())


def _centroid(points):
    edges = list(zip(points, points[1:] + points[:1]))
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    if abs(area2) < 1e-9:
        return [sum(p[i] for p in points) / len(points) for i in (0, 1)]
    return [sum((a[i] + b[i]) * (a[0] * b[1] - b[0] * a[1])
                for a, b in edges) / (3 * area2) for i in (0, 1)]


def _matches(a, b, kind, house, *, original=False):
    def level(p):
        if kind == 'opening':
            return next((w['level'] for w in house['walls'] if w['id'] == p.get('wall')), None)
        return p.get('level')
    if level(a) != level(b) or (kind == 'site' and a.get('kind') != b.get('kind')):
        return False
    ga, gb = _geometry(a, kind, house), _geometry(b, kind, house)
    if original:
        gb = b.get('read_geometry') or gb
    if kind == 'wall':
        return any(math.dist(ga['from'], x) <= 1 and math.dist(ga['to'], y) <= 1
                   for x, y in ((gb['from'], gb['to']), (gb['to'], gb['from'])))
    if kind == 'opening':
        if 'from' not in ga or 'from' not in gb:
            return False
        return math.dist([(ga['from'][i] + ga['to'][i]) / 2 for i in (0, 1)],
                         [(gb['from'][i] + gb['to'][i]) / 2 for i in (0, 1)]) <= 1
    if kind == 'room':
        return math.dist(_centroid(ga['polygon']), _centroid(gb['polygon'])) <= 1
    if kind == 'roof':
        return all(math.dist(x, y) <= 1 for x, y in zip(_corners(ga['rect']), _corners(gb['rect'])))
    return _near_geometry(ga, gb)


def _merge_list(existing, incoming, kind, house, build, step=None):
    protected_walls = {o.get('wall') for o in (house or {}).get('openings', []) if o.get('src', {}).get('person')}
    def protected(p):
        return p.get('src', {}).get('person') or (kind == 'wall' and p['id'] in protected_walls)
    merged = list(existing)
    kept = set()
    for piece in incoming:
        if _deleted(piece, kind, house, build):
            continue
        old = next((p for p in sorted(merged, key=lambda p: not protected(p))
                    if (_matches(piece, p, kind, house)
                        or (protected(p) and _matches(piece, p, kind, house, original=True)))), None)
        # Keep the extraction geometry when a later hand edit moves a piece.
        # A reread must not duplicate it back at its former location.
        piece['read_geometry'] = _geometry(piece, kind, house)
        if old:
            piece['id'] = old['id']
            kept.add(old['id'])
            if not protected(old):
                merged[merged.index(old)] = deepcopy(piece)
        else:
            # UUIDs also avoid IDs of removed pieces and tombstones.
            used = {p['id'] for p in merged}
            while piece['id'] in used:
                piece['id'] = f'{kind}:{uuid.uuid4().hex}'
            kept.add(piece['id'])
            merged.append(deepcopy(piece))
    if step and (step.get('reread') or build.get('existing')):
        removed = {step['id'], *step.get('removed_steps', [])}
        merged = [p for p in merged if protected(p) or p['id'] in kept
                  or p.get('src', {}).get('step') not in removed]
    return merged


def _ghost(build, step, piece, why=''):
    geometry = {k: deepcopy(piece[k]) for k in
                ('id', 'level', 'from', 'to', 'wall', 'at', 'position', 'polygon', 'rect', 'outline', 'lot') if k in piece}
    if piece.get('state') == 'ghost' and 'position' in geometry:
        geometry.pop('wall', None)
        geometry.pop('at', None)
    _event(build, 'ghost', step=step['id'], piece=geometry, why=why)


def _reattach(house, old_house, ghosts):
    for opening in house['openings']:
        if opening.get('src', {}).get('person'):
            continue
        old_wall = next((w for w in old_house['walls'] if w['id'] == opening.get('wall')), None)
        if old_wall is None:
            continue
        wall = next((w for w in house['walls'] if w['id'] == old_wall['id']), None)
        if wall and wall['from'] == old_wall['from'] and wall['to'] == old_wall['to']:
            continue
        geometry = _geometry(opening, 'opening', old_house)
        point = [(geometry['from'][i] + geometry['to'][i]) / 2 for i in (0, 1)]
        walls = [w for w in house['walls'] if w['level'] == old_wall['level']]
        hit = min(((*_nearest(point, w['from'], w['to']), w) for w in walls),
                  key=lambda h: h[0], default=None)
        reasons = []
        if hit:
            distance, at, wall = hit
            # Ghosts also need a valid carrier or normalize drops them. Retain
            # the original centre separately when the carrier needs checking.
            length = math.dist(wall['from'], wall['to'])
            clamped = max(opening['width'] / 2, min(length - opening['width'] / 2, at))
            opening.update(wall=wall['id'], at=clamped)
            if distance > 1:
                reasons.append('No replacement wall is within 1 ft of this opening.')
            if clamped != at:
                reasons.append('The opening was clamped to the replacement wall span.')
            if wall.get('state') == 'ghost':
                reasons.append('The nearest wall is still a ghost.')
        else:
            reasons.append('There is no replacement wall on this floor.')
        if reasons:
            opening.update(state='ghost', why=' '.join(reasons), position=point)
            ghosts.append(opening)


def _spend(build):
    build['cost'] = math.fsum(e['usd'] for e in twin_cost.entries() if e.get('run') == build['id'])
    _event(build, 'cost', cost=build['cost'])


def _images_context(build, step):
    context = {'level': step['level'],
               'box': deepcopy(step['box'] or _FULL)}
    if 'building' in build['inputs']:
        context['building'] = deepcopy(build['inputs']['building'])
    plan = twin_store.current()
    if plan and build['inputs'].get('part') != 'lot':
        house = _house(_base(plan, build), build)
        context['settled'] = {'outline': deepcopy(next((l.get('outline', []) for l in house['levels']
                                                       if l['id'] == step['level']), []))}
        sections = house['roof']['sections']
        if sections:
            bounds = _bounds([p for s in sections for p in _corners(s['rect'])])
            def where(s):
                x, y = _centroid(_corners(s['rect']))
                def band(v, lo, hi):
                    return (v - lo) / (hi - lo) if hi > lo else .5
                horizontal = 'left' if band(x, bounds[0], bounds[2]) < 1/3 else 'right' if band(x, bounds[0], bounds[2]) > 2/3 else ''
                depth = 'front' if band(y, bounds[1], bounds[3]) < 1/3 else 'rear' if band(y, bounds[1], bounds[3]) > 2/3 else ''
                return '-'.join(filter(None, (depth, horizontal))) or 'middle'
            context['sections'] = [{'id': s['id'], 'kind': s['kind'], 'ridge': s['ridge'],
                                    'size_ft': [s['rect'][2] - s['rect'][0], s['rect'][3] - s['rect'][1]],
                                    'where': where(s)} for s in sections]
        else:
            context['sections'] = []
    if step['kind'] in ('pitch', 'finishes'):
        images = [image for source in build['inputs'].get('photos', []) for image in twin_store.source_images(source)]
        return images, context, None
    crop = twin_store.crop(step['source'], step['page'], context['box'])
    context['box'] = crop['box']
    return [{'mime': crop['mime'], 'b64': crop['b64']}], context, {k: crop[k] for k in ('box', 'size', 'master')}


def _obtain(build, step, reader, ticket):
    path = _cache_path(build, step)
    if path.is_file():
        result = json.loads(path.read_text(encoding='utf-8'))
        if not result.get('error'):
            return result
        # Older builds may have cached an unsuccessful reply. Resume retries it.
        path.unlink()
    if step['kind'] == 'shell':
        shell = deepcopy(build['inputs']['shell'])
        for piece in [*shell['walls'], *shell['openings'], *shell['roof']['sections']]:
            piece['src']['step'] = step['id']
        result = {'fragment': shell, 'problems': []}
    elif step['kind'] in ('compose', 'lot'):
        result = {'fragment': {}, 'problems': []}
    elif step['kind'] == 'fit':
        result = {'fragment': _building_fit(build), 'problems': []}
    else:
        images, context, crop = _images_context(build, step)
        twin_cost.require_clear()
        raw = reader(step['kind'], images, context, run=build['id'], step=step['id'])
        if isinstance(raw, dict) and raw.get('error'):
            raise _ReadError(raw['error'])
        fragment, problems = twin_reads.parse(step['kind'], raw)
        if isinstance(raw, dict):
            problems = list(raw.get('problems') or []) + problems
        result = {'fragment': fragment, 'problems': problems, 'crop': crop,
                  'error': raw.get('error') if isinstance(raw, dict) else None}
        if step['kind'] == 'walls' and isinstance(raw, dict) and isinstance(raw.get('walls'), list):
            result['wall_count'] = len(raw['walls'])
    with twin_store.LIFECYCLE, _LOCK:
        # A stop does not throw away a paid read. Resume waits until this
        # worker exits; only a new generation or worker can invalidate it.
        if (build['generation'] != twin_store.generation()
                or _BUILDS.get(build['id']) is not build
                or _WORKERS.get(build['id'], {}).get('ticket') != ticket):
            return None
        _atomic(path, result)
    return result


def _registration(build, step, result, plan):
    fragment, crop = result['fragment'], result['crop']
    scale = _dimension(crop, fragment['dimension'])
    pixels = [twin_store.crop_to_master(crop, p) for p in fragment['outline']]
    reg = twin_register.make(scale, origin_px=[min(p[0] for p in pixels), max(p[1] for p in pixels)])
    rms = 0.0
    if step['kind'] == 'registration':
        below = f"L{int(step['level'][1:]) - 1}"
        if fragment.get('lower_outline'):
            reg, rms = _fit(reg, [_map(crop, reg, p) for p in fragment['lower_outline']], _outline(plan, build, below))
        else:
            # Keep the dimension's scale; an unlocated bonus needs a person.
            fixed = _bounds(_outline(plan, build, below))
            moving = _bounds([_map(crop, reg, p) for p in fragment['outline']])
            reg['offset'] = [fixed[0] - moving[0], fixed[1] - moving[1]]
    return reg, rms


def _plot_registration(crop, fragment):
    from services import twin_place
    return twin_place.plot_registration(crop, fragment)


def _building_fit(build):
    plan = _base(twin_store.current(), build)
    house = _house(plan, build)
    if house.get('src', {}).get('person'):
        return {'transform': {'position': deepcopy(house['position']), 'rotation': house['rotation']}, 'why': ''}
    outline = min(house['levels'], key=lambda level: level['elevation']).get('outline', [])
    target = next((b for b in twin_store.place()['buildings'] if b['id'] == house['id']), {})
    footprint = target.get('footprint')
    transform = {'position': deepcopy(house['position']), 'rotation': house['rotation']}
    if footprint:
        move, rms = twin_register.fit_outline(outline, footprint)
        transform = {'position': move['offset'], 'rotation': move['angle']}
        def area(points):
            return abs(sum(a[0] * b[1] - b[0] * a[1]
                           for a, b in zip(points, points[1:] + points[:1]))) / 2
        good = rms <= 2 and abs(area(outline) - area(footprint)) <= .2 * area(footprint)
        why = '' if good else "The drawings and the plot plan disagree about this building's shape. Check where it sits."
    else:
        others = [twin_register.to_world(b, p) for b in plan['buildings'] if b['id'] != house['id']
                  for level in b['levels'] for p in level.get('outline', [])]
        if others:
            transform = {'position': [_bounds(others)[2] + 10, 0], 'rotation': 0}
        why = 'This building has no footprint on the lot yet. Drag it into place.'
    return {'transform': transform, 'why': why}


def _check_lot_page(step):
    page = next((r for r in twin_store.page_roles() if r['role'] == 'plot' and r.get('building') == 'lot'), None)
    if page is None or any(page.get(k) != step.get(k) for k in ('source', 'page', 'box')):
        raise ValueError('The plot plan changed while it was being read. Read it again.')


def _pause(build, step, result):
    fragment = result['fragment']
    is_lot = build['inputs'].get('part') == 'lot'
    plan = None if is_lot else _base(twin_store.current(), build)
    pause = {'kind': step['pause'], 'step': step['id'], 'why': fragment.get('why', ''),
             'confidence': fragment.get('confidence', 0)}
    if step['kind'] in ('outline', 'registration'):
        pause['registration'], pause['rms'] = _registration(build, step, result, plan)
        bounds = _bounds([_map(result['crop'], pause['registration'], p) for p in fragment['outline']])
        pause.update(dimension_ft=fragment['dimension']['feet'],
                     size_ft=[bounds[2] - bounds[0], bounds[3] - bounds[1]])
        if step['kind'] == 'registration' and not fragment.get('lower_outline'):
            pause['why'] = (pause['why'] + ' The floor below is not shown. Scale comes from the dimension; check this outline against the floor below.').strip()
    elif step['kind'] == 'fit':
        pause.update(registration=twin_register.make(1), transform=deepcopy(fragment['transform']))
    else:
        if is_lot:
            _check_lot_page(step)
            from services import twin_place_reads
            page = {k: step[k] for k in ('source', 'page', 'box')}
            reg = twin_place_reads.plot_read_record(page, result['crop'], fragment)['registration']
        else:
            reg = _plot_registration(result['crop'], fragment)
        if not fragment.get('street_edge'):
            pause['why'] = (pause['why'] + ' The street edge was guessed from the longest lot edge.').strip()
        house = _house(plan, build) if plan else None
        transform = {'position': house['position'], 'rotation': house['rotation']} if house else None
        if house and not build['existing']:
            match = next((b for b in fragment.get('buildings', [])
                          if b['name'].lower() in (house['id'].lower(), house.get('name', '').lower())), None)
            if match is None:
                def area(points):
                    return abs(sum(a[0] * b[1] - b[0] * a[1]
                                   for a, b in zip(points, points[1:] + points[:1]))) / 2
                choices = [b for b in fragment.get('buildings', []) if 'pool' not in b['name'].lower()]
                match = min(choices, key=lambda b: abs(area([_map(result['crop'], reg, p) for p in b['outline']])
                                                       - area(_outline(plan, build))), default=None)
            if match:
                move, _ = twin_register.fit_outline(_outline(plan, build), [_map(result['crop'], reg, p) for p in match['outline']])
                transform = {'position': move['offset'], 'rotation': move['angle']}
            elif len(plan['buildings']) > 1:
                others = [twin_register.to_world(b, p) for b in plan['buildings'] if b is not house
                          for l in b['levels'] for p in l.get('outline', [])]
                if others:
                    transform = {'position': [_bounds(others)[2] + 10, 0], 'rotation': 0}
        pause['registration'] = reg
        if transform is not None:
            pause['transform'] = transform
    build['pause'] = pause
    build['state'] = 'paused'
    step['status'] = 'paused'
    if step['kind'] != 'fit':
        reg = pause['registration']
        key = 'outline' if step['level'] else 'lot'
        _ghost(build, step, {'id': step['level'] or step['id'], key:
                             [_map(result['crop'], reg, p) for p in fragment[key]]}, pause['why'])
    _event(build, 'pause', **pause)


def _expand(build, step, result):
    if step.get('expanded'):
        return
    parent = result['crop']['box']
    wings = result['fragment'].get('wings') or [{'name': 'main', 'box': _FULL}]
    previous = {s.get('wing_id', s['id']): s for s in build['steps']
                if s['kind'] == 'walls' and s['level'] == step['level']}
    children, used = [], set()
    for index, wing in enumerate(wings):
        name = re.sub(r'[^A-Za-z0-9_.-]', '-', wing['name'])[:24] or 'main'
        if name in used:
            name = f'{name}-{index + 1}'
        used.add(name)
        box = wing['box']
        master_box = [parent[0] + box[0] * (parent[2] - parent[0]),
                      parent[1] + box[1] * (parent[3] - parent[1]),
                      parent[0] + box[2] * (parent[2] - parent[0]),
                      parent[1] + box[3] * (parent[3] - parent[1])]
        child = _step('walls', {**step, 'box': master_box, 'level': step['level_name']}, step['level'],
                      name=f"{step['level_name']} {wing['name']} walls")
        child['id'] += ':' + name
        if child['id'] in previous:
            old = previous[child['id']]
            child['wing_id'] = child['id']
            child['id'] = old['id']
            if old.get('removed_steps'):
                child['removed_steps'] = list(old['removed_steps'])
            path = _cache_path(build, old)
            cached = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            crop = cached.get('crop') if not cached.get('error') else None
            if crop:
                reg = twin_store.registration(step['source'], step['page'], step['level'])
                shift = max(math.hypot((a[0] - b[0]) * crop['master'][0],
                                       (a[1] - b[1]) * crop['master'][1]) * reg['scale']
                            for a, b in zip(_corners(crop['box']), _corners(master_box)))
                if shift > 1:
                    # This is a different read, with its own cache and provenance.
                    child['id'] = f"{child['wing_id']}:{uuid.uuid4().hex[:8]}"
                    child['removed_steps'] = [old['id'], *old.get('removed_steps', [])]
                    _event(build, 'log', step=child['id'],
                           text=f"{child['label']}: crop changed by {twin_register.feet_inches(shift)}; reading again.")
                else:
                    child.update(box=deepcopy(crop['box']), replay=True)
            child['reread'] = True
        if build.get('existing'):
            child['reread'] = True
        children.append(child)
    previous_ids = {s['id'] for s in previous.values()}
    build['steps'][:] = [s for s in build['steps'] if s['id'] not in previous_ids]
    obsolete = previous_ids - {s['id'] for s in children}
    if obsolete:
        children[-1].update(reread=True, removed_steps=sorted(obsolete | set(children[-1].get('removed_steps', []))))
    index = build['steps'].index(step)
    build['steps'][index + 1:index + 1] = children
    step['expanded'] = True


def _settle(build, step, result, decision=None):
    """Merge against the latest round while LIFECYCLE and the module lock are held."""
    fragment, crop = result['fragment'], result.get('crop')
    kind = step['kind']
    notes, settled, ghosts = [], [], []
    decision = decision or {}
    is_lot = build['inputs'].get('part') == 'lot'
    lot_state = None
    lot_outline = None
    if is_lot and kind in ('lot', 'plot', 'site'):
        _check_lot_page(step)
    if is_lot and kind == 'lot':
        lot_outline = build['placement']['outline']
    elif is_lot and kind == 'plot':
        from services import twin_place_reads
        reg = build['pause']['registration']
        page = {k: deepcopy(step[k]) for k in ('source', 'page', 'box')}
        record = twin_place_reads.plot_read_record(
            page, crop, fragment, registration=reg,
            cost=math.fsum(e['usd'] for e in twin_cost.entries()
                           if e.get('run') == build['id'] and e.get('stage') == 'step:plot'))
        lot_outline = record['lot']
        lot_state = deepcopy(twin_store.place()['lot'])
        lot_state['placement'] = {**page, 'outline': lot_outline, 'street_edge': record['street_edge'],
                                  'registration': reg, 'confirmed': True}
        lot_state['read'] = record

    def mutate(current):
        plan = _base(current, build, lot_outline)
        house = _house(plan, build)
        level = next((l for l in (house or {}).get('levels', []) if l['id'] == step['level']), None)
        reg = twin_store.registration(step['source'], step['page'], step['level']) if crop else None
        if kind == 'shell':
            shell = deepcopy(fragment)
            for incoming_level in shell['levels']:
                old_level = next(l for l in house['levels'] if l['id'] == incoming_level['id'])
                if not old_level.get('src', {}).get('person'):
                    old_level.update(incoming_level)
            # _merge_list assigns the retained wall ids back to incoming walls.
            # The door must reference those ids, including a wall moved by hand.
            wall_ids = [w['id'] for w in shell['walls']]
            house['walls'] = _merge_list(house['walls'], shell['walls'], 'wall', house, build, step)
            remap = dict(zip(wall_ids, (w['id'] for w in shell['walls'])))
            live_walls = {w['id'] for w in house['walls']}
            incoming = []
            for opening in shell['openings']:
                opening['wall'] = remap[opening['wall']]
                if opening['wall'] in live_walls:
                    incoming.append(opening)
            house['openings'] = _merge_list(house['openings'], incoming, 'opening', house, build, step)
            house['roof']['sections'] = _merge_list(
                house['roof']['sections'], shell['roof']['sections'], 'roof', house, build, step)
        elif kind in ('outline', 'registration'):
            reg = decision.get('registration', build['pause']['registration'])
            if not level.get('src', {}).get('person'):
                level['outline'] = [_map(crop, reg, p) for p in fragment['outline']]
                level.update(state='settled', src={'sheet': step['source'], 'page': step['page'], 'step': step['id']})
            bounds = _bounds(level['outline'])
            notes.append(f"{level['name']} outline: {twin_register.feet_inches(bounds[2] - bounds[0])} by {twin_register.feet_inches(bounds[3] - bounds[1])}")
        elif kind == 'walls':
            incoming = [_piece(build, step, 'wall', i, level=step['level'],
                               **{'from': _map(crop, reg, w['from']), 'to': _map(crop, reg, w['to'])},
                               height=level['ceiling'], thickness=w.get('thickness_in', 6 if w['exterior'] else 4) / 12,
                               exterior=w['exterior']) for i, w in enumerate(fragment.get('walls', []))]
            outline = level.get('outline', [])
            anchors = list(zip(outline, outline[1:] + outline[:1]))
            replaced = {step['id'], *step.get('removed_steps', [])}
            anchors.extend((w['from'], w['to']) for w in house['walls']
                           if w['level'] == step['level'] and w.get('state') != 'ghost'
                           and w.get('src', {}).get('step') not in replaced)
            ready = _supported_walls(incoming, anchors)
            for wall in ready:
                wall['state'] = 'settled'
            pending = [w for w in incoming if w not in ready]
            for wall in pending:
                wall['why'] = 'Wall ends do not form a supported connection to the outline or a settled wall.'
                ghosts.append(wall)
            old_house = deepcopy(house)
            house['walls'] = _merge_list(house['walls'], incoming, 'wall', house, build, step)
            _reattach(house, old_house, ghosts)
        elif kind == 'openings':
            incoming = []
            walls = [w for w in house['walls'] if w['level'] == step['level']]
            for i, opening in enumerate(fragment.get('openings', [])):
                point = _map(crop, reg, opening['at'])
                if not walls:
                    ghosts.append(_piece(build, step, 'opening', i, at=point,
                                         why='There is no wall on this floor.'))
                    continue
                distance, at, wall = min(((*_nearest(point, w['from'], w['to']), w) for w in walls), key=lambda hit: hit[0])
                piece = _piece(build, step, 'opening', i, kind=opening['kind'], wall=wall['id'], at=at,
                               width=opening['width_ft'], sill=opening['sill_ft'], head=opening['head_ft'])
                settled_distance = min((_nearest(point, w['from'], w['to'])[0] for w in walls
                                        if w.get('state') != 'ghost'), default=math.inf)
                if distance > 2 or settled_distance > 2:
                    piece['why'] = 'This opening is more than 2 ft from any settled wall.'
                    # Keep the read centre; it has not been snapped to this wall.
                    piece['position'] = point
                elif wall.get('state') == 'ghost':
                    piece['why'] = 'The nearest wall is still a ghost.'
                else:
                    piece['state'] = 'settled'
                reason = twin_plan._opening_error(piece, {w['id']: w for w in walls}, {})
                if reason:
                    piece.update(state='ghost', why=piece.get('why') or f'This opening needs checking: {reason}.')
                if piece['state'] == 'ghost':
                    piece['position'] = point
                    # The plan format requires a valid wall reference even for
                    # ghosts. Keep the unsnapped centre in position; wall/at
                    # are only a valid carrier until a person resolves it.
                    if reason:
                        carriers = [w for w in walls if math.dist(w['from'], w['to']) >= piece['width']
                                    and w['height'] >= piece['head']]
                        if carriers:
                            _, at, carrier = min(((*_nearest(point, w['from'], w['to']), w) for w in carriers),
                                                 key=lambda hit: hit[0])
                            piece.update(wall=carrier['id'], at=max(piece['width'] / 2,
                                         min(math.dist(carrier['from'], carrier['to']) - piece['width'] / 2, at)))
                    ghosts.append(piece)
                incoming.append(piece)
            house['openings'] = _merge_list(house['openings'], incoming, 'opening', house, build, step)
        elif kind == 'rooms':
            incoming = [_piece(build, step, 'room', i, level=step['level'], name=r['name'] or f"{level['name']} room {i + 1}",
                               polygon=[_map(crop, reg, p) for p in r['polygon']], state='settled')
                        for i, r in enumerate(fragment.get('rooms', []))]
            house['rooms'] = _merge_list(house['rooms'], incoming, 'room', house, build, step)
            notes.append(f"{level['name']}: {sum(w['level'] == step['level'] for w in house['walls'])} walls, "
                         f"{sum(o.get('wall') in {w['id'] for w in house['walls'] if w['level'] == step['level']} for o in house['openings'])} openings, "
                         f"{sum(r['level'] == step['level'] for r in house['rooms'])} rooms")
        elif kind == 'roof':
            first = next(s for s in build['steps'] if s['kind'] == 'outline')
            floor_reg = twin_store.registration(first['source'], first['page'], first['level'])
            reg = twin_register.make(floor_reg['scale'])
            reg, rms = _fit(reg, [_map(crop, reg, p) for p in fragment['outline']], _grow(_outline(plan, build), 1))
            if rms > 1.5:
                _event(build, 'question', step=step['id'], text=f'Roof outline fit differs by {twin_register.feet_inches(rms)}. Please check it.')
            incoming = []
            for i, section in enumerate(fragment.get('sections', [])):
                points = [_map(crop, reg, p) for p in _corners(section['box'])]
                turn = round(reg['angle'] / 90) % 4
                ridge = section['ridge'] if turn % 2 == 0 else ('y' if section['ridge'] == 'x' else 'x')
                side = section.get('low_side')
                if side:
                    center = [(section['box'][0] + section['box'][2]) / 2, (section['box'][1] + section['box'][3]) / 2]
                    edge = center[:]
                    edge[0 if side[0] == 'x' else 1] = section['box'][{'x0': 0, 'y0': 1, 'x1': 2, 'y1': 3}[side]]
                    a, b = _map(crop, reg, center), _map(crop, reg, edge)
                    axis = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
                    side = ('x' if axis == 0 else 'y') + ('1' if b[axis] > a[axis] else '0')
                incoming.append(_piece(build, step, 'roof', i, kind=section['kind'], rect=_bounds(points), ridge=ridge,
                                       low_side=side, plate=max((l['elevation'] + l['ceiling'] for l in house['levels']
                                           if _inside(_centroid(points), l.get('outline', []))),
                                           default=min(l['elevation'] + l['ceiling'] for l in house['levels'])),
                                       overhang=0, pitch=6, pitch_source='default', state='settled'))
            house['roof']['sections'] = _merge_list(house['roof']['sections'], incoming, 'roof', house, build, step)
        elif kind == 'pitch':
            for pitch in fragment.get('pitches', []):
                for section in house['roof']['sections']:
                    if section['id'] == pitch['section'] and not section.get('src', {}).get('person'):
                        section.update(pitch=pitch['pitch'], pitch_source='photos')
            notes.append(f"Roof: {len(house['roof']['sections'])} sections, pitches estimated from photos")
        elif kind == 'plot':
            reg = build['pause']['registration']
            plan['site']['lot'] = [_map(crop, reg, p) for p in fragment['lot']]
            if house is not None:
                transform = decision.get('transform', build['pause']['transform'])
                if not house.get('src', {}).get('person'):
                    house.update(deepcopy(transform))
                notes.append(f"Placed {house.get('name', house['id'])} on the lot, turned {house['rotation']:g}\N{DEGREE SIGN}")
        elif kind == 'fit':
            if not house.get('src', {}).get('person'):
                house.update(deepcopy(decision.get('transform', fragment['transform'])))
            else:
                notes.append('Kept the building where you placed it.')
        elif kind == 'site':
            reg = ((twin_store.place()['lot'].get('placement') or build.get('placement'))['registration']
                   if is_lot else twin_store.registration(step['source'], step['page'], None))
            site = plan['site']
            for name in ('pool', 'fire_pit'):
                old = site.get(name)
                if name in fragment:
                    raw = fragment[name]
                    fields = ({'polygon': [_map(crop, reg, p) for p in raw['polygon']], 'depth': raw.get('depth_ft', 5)}
                              if name == 'pool' else {'at': _map(crop, reg, raw['at']), 'radius': raw['radius_ft']})
                    piece = _piece(build, step, 'site', name, **fields, state='settled')
                    if not (old or {}).get('src', {}).get('person'):
                        pieces = _merge_list([old] if old else [], [piece], 'site', house, build, step)
                        site[name] = pieces[-1] if pieces else None
                elif ((step.get('reread') or build.get('existing')) and old and not old.get('src', {}).get('person')
                      and old.get('src', {}).get('step') == step['id']):
                    site[name] = None
            incoming = [_piece(build, step, 'site', i, kind=h['kind'], polygon=[_map(crop, reg, p) for p in h['polygon']], state='settled')
                        for i, h in enumerate(fragment.get('hardscape', []))]
            site['hardscape'] = _merge_list(site['hardscape'], incoming, 'site', house, build, step)
            incoming = [_piece(build, step, 'site', f'edge-{i}', points=[_map(crop, reg, w[p]) for p in ('from', 'to')],
                               height=w['height_ft'], state='settled') for i, w in enumerate(fragment.get('retaining_walls', []))]
            site['edges'] = _merge_list(site['edges'], incoming, 'site', house, build, step)
        elif kind == 'finishes':
            kit = twin_library.kit('modern_farmhouse')
            if build['inputs'].get('part') is not None:
                materials = {}
                for role, value in fragment.get('materials', {}).items():
                    problems = []
                    validated = twin_draft._materials({'materials': {role: value}}, kit, problems)
                    notes.extend(problems)
                    if not problems:
                        materials[role] = validated[role]
                target_materials = house.setdefault('materials', {})
            else:
                materials = twin_draft._materials({'materials': fragment.get('materials', {})}, kit, notes)
                target_materials = plan['materials']
            target_materials.update({k: v for k, v in materials.items()
                                     if not (isinstance(target_materials.get(k), dict)
                                             and target_materials[k].get('src', {}).get('person'))})
        elif kind == 'compose':
            protected = {name: [p for p in plan['site'][name] if p.get('src', {}).get('person')]
                         for name in ('beds', 'planting', 'edges')}
            plan, compose_notes = twin_compose.compose(plan, twin_library.kit('modern_farmhouse'), seed=1)
            notes.extend(compose_notes)
            for name, people in protected.items():
                for piece in plan['site'][name]:
                    if piece.get('by') == 'compose' and not piece.get('src', {}).get('person'):
                        piece['src'] = {'sheet': '', 'page': 1, 'step': step['id']}
                plan['site'][name] = _merge_list(
                    people, [p for p in plan['site'][name] if not p.get('src', {}).get('person')],
                    'site', house, build)
        collections = [house['walls'], house['openings'], house['rooms'], house['roof']['sections']] if house else []
        generated = [p for pieces in collections for p in pieces if p.get('src', {}).get('step') == step['id']]
        for piece in generated:
            if 'confidence' in fragment:
                if not piece.get('src', {}).get('person'):
                    piece['confidence'] = fragment['confidence']
            if not piece.get('src', {}).get('person'):
                ghosts.append(piece)
        normalized, problems = twin_plan.normalize(plan)
        if problems:
            logger.warning('Twin build %s step %s validation: %s', build['id'], step['id'], problems)
            notes.append('Some pieces need checking against the drawing.')
        target = _house(normalized, build)
        target_collections = [target['walls'], target['openings'], target['rooms'], target['roof']['sections']] if target else []
        if kind == 'walls' and result.get('wall_count', len(incoming)):
            settled_ids = {w['id'] for w in target['walls'] if w.get('state') != 'ghost'}
            if sum(w['id'] in settled_ids for w in incoming) < result.get('wall_count', len(incoming)) / 2:
                _event(build, 'question', step=step['id'], text='Fewer than half of these walls could settle. Please check the walls.')
        for collection in target_collections:
            settled.extend(p for p in collection if p.get('src', {}).get('step') == step['id'] and p.get('state') != 'ghost')
        kept = {p['id'] for collection in target_collections for p in collection}
        for piece in generated:
            if piece['id'] not in kept:
                ghosts.append({**piece, 'state': 'ghost', 'why': 'This piece needs checking against the drawing.'})
        if kind in ('outline', 'registration'):
            settled.append(next(l for l in target['levels'] if l['id'] == step['level']))
        for name in ('hardscape', 'edges', 'planting', 'beds', 'furniture'):
            settled.extend(p for p in normalized['site'][name] if p.get('src', {}).get('step') == step['id'])
        settled.extend(p for name in ('pool', 'fire_pit') if isinstance((p := normalized['site'].get(name)), dict)
                       and p.get('src', {}).get('step') == step['id'])
        return normalized

    def publish_lot(row):
        row['place']['lot'] = deepcopy(lot_state)
        twin_store._set_registration(row, step['source'], step['page'], None, build['pause']['registration'])

    twin_store.update_current(mutate, kind='build', step={'id': step['id'], 'label': step['label']},
                              generation=build['generation'], cost=build['cost'],
                              state_mutator=publish_lot if lot_state is not None else None)
    if kind in ('outline', 'registration', 'plot') and not is_lot:
        reg = decision.get('registration', build['pause']['registration']) if kind != 'plot' else build['pause']['registration']
        twin_store.set_registration(step['source'], step['page'], step['level'], reg)
    if kind in ('outline', 'registration'):
        _expand(build, step, result)
    step.pop('reread', None)
    step.pop('replay', None)
    step.pop('removed_steps', None)
    for note in notes:
        _event(build, 'log', step=step['id'], text=note)
    for ghost in {p['id']: p for p in ghosts}.values():
        _ghost(build, step, ghost, ghost.get('why', ''))
        if ghost.get('why'):
            _event(build, 'log', step=step['id'], text=ghost['why'])
    _event(build, 'settled', step=step['id'], pieces=settled)


def answer(build_id, step_id, decision):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        if build['state'] != 'paused' or build['pause']['step'] != step_id:
            raise ValueError('This step is not waiting for an answer.')
        step = next(s for s in build['steps'] if s['id'] == step_id)
        if not isinstance(decision, dict) or len(decision) != 1:
            raise ValueError('Accept the step or provide its registration or placement.')
        decision = deepcopy(decision)
        if 'registration' in decision:
            if step['kind'] not in ('outline', 'registration'):
                raise ValueError('This step needs a placement decision.')
            try:
                reg = decision['registration']
                if not isinstance(reg, dict):
                    raise ValueError()
                origin, offset = reg.get('origin_px', [0, 0]), reg.get('offset', [0, 0])
                if (not isinstance(origin, (list, tuple)) or len(origin) != 2
                        or not isinstance(offset, (list, tuple)) or len(offset) != 2
                        or not all(type(v) in (int, float) and math.isfinite(v)
                                   for v in [reg['scale'], reg.get('angle', 0), *origin, *offset])):
                    raise ValueError()
                decision['registration'] = twin_register.make(reg['scale'], reg.get('angle', 0), origin, offset)
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ValueError('Registration needs a positive scale, angle and two-number origin and offset.') from None
        elif 'transform' in decision:
            transform = decision['transform']
            if (step['kind'] not in ('plot', 'fit') or build['inputs'].get('part') == 'lot' or not isinstance(transform, dict)
                    or not isinstance(transform.get('position'), (list, tuple)) or len(transform['position']) != 2
                    or not all(type(v) in (int, float) and -1e308 <= v <= 1e308
                               for v in [*transform['position'], transform.get('rotation')])):
                raise ValueError('Placement needs a position and rotation.')
            decision['transform'] = {'position': list(transform['position']), 'rotation': transform['rotation']}
        elif decision.get('accept') is not True:
            raise ValueError('Accept the step or provide its registration or placement.')
        try:
            result = json.loads(_cache_path(build, step).read_text(encoding='utf-8'))
            _settle(build, step, result, decision)
        except twin_store.StaleGeneration:
            raise
        except Exception as exc:
            logger.exception('Twin build %s could not accept %s', build_id, step['id'])
            _event(build, 'question', step=step['id'], text='This step needs checking. Adjust it or read it again.')
            _save(build)
            return status(build_id)
        step['status'] = 'done'
        build['pause'] = None
        runtime = _WORKERS.get(build_id, {})
        reader = runtime.get('reader') or twin_reads.read
        inline = runtime.get('inline', False)
        ticket = _launch(build, reader, inline)
    _dispatch(build, ticket, reader, inline)
    return status(build_id)


def reread(build_id, step_id, *, reader=None, inline=None):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        step = next((s for s in build['steps'] if s['id'] == step_id), None)
        if step is None:
            raise ValueError('Unknown build step.')
        if build['state'] == 'running':
            raise ValueError('Stop the build before rereading a step.')
        if _WORKERS.get(build_id, {}).get('busy'):
            raise ValueError('The build is still stopping; wait for its read to return.')
        step['reread'] = True
        if step['kind'] in ('outline', 'registration'):
            # Reproject cached coordinates through the accepted registration,
            # keeping each answer's original crop.
            # Higher registrations depend on the outline immediately below them.
            first = int(step['level'][1:])
            for dependent in build['steps']:
                if dependent['level'] and int(dependent['level'][1:]) >= first:
                    dependent.update(status='pending', reread=True, replay=True)
                    if dependent['kind'] in ('outline', 'registration'):
                        dependent.pop('expanded', None)
        _cache_path(build, step).unlink(missing_ok=True)
        step['status'] = 'pending'
        build['pause'] = None
        build['state'] = 'stopped'
        _save(build)
    return resume(build_id, reader=reader, inline=inline)


def _idle(build, ticket):
    """Clear the worker's busy flag in the same lock that publishes its last
    state, so a tap right after a pause never sees a build still stopping."""
    runtime = _WORKERS.get(build['id'], {})
    if runtime.get('ticket') == ticket:
        runtime['busy'] = False


def _run(build, ticket, reader):
    try:
        while True:
            result = None
            with twin_store.LIFECYCLE, _LOCK:
                if not _live(build, ticket):
                    return
                step = next((s for s in build['steps'] if s['status'] != 'done'), None)
                if step is None:
                    first_done = not any(e['type'] == 'done' for e in build['events'])
                    build['state'] = 'done'
                    _event(build, 'done')
                    _save(build)
                    _idle(build, ticket)
                    successor = _chain(build) if first_done else None
                    if successor is not None:
                        inline = _WORKERS[build['id']]['inline']
                        next_ticket = _launch(successor, reader, inline)
                    break
                step['status'] = 'running'
                _event(build, 'stage', step=step['id'], label=step['label'])
                _save(build)
            result = _obtain(build, step, reader, ticket)
            with twin_store.LIFECYCLE, _LOCK:
                if not _live(build, ticket) or result is None:
                    return
                _spend(build)
                if result['problems']:
                    logger.warning('Twin build %s step %s read validation: %s', build['id'], step['id'], result['problems'])
                    _event(build, 'log', step=step['id'], text='Some parts of this drawing need checking.')
                if result.get('error'):
                    raise ValueError(result['error'])
                if step['pause'] and (step['kind'] != 'fit' or result['fragment'].get('why')):
                    _pause(build, step, result)
                    _save(build)
                    _idle(build, ticket)
                    return
                _settle(build, step, result)
                step['status'] = 'done'
                _save(build)
        if successor is not None:
            _dispatch(successor, next_ticket, reader, inline)
    except twin_store.StaleGeneration:
        return
    except twin_cost.CheckpointReached as exc:
        with twin_store.LIFECYCLE, _LOCK:
            if _live(build, ticket):
                _spend(build)
                build['state'] = 'checkpoint'
                step['status'] = 'pending'
                _event(build, 'checkpoint', step=step['id'], checkpoint=exc.checkpoint, total=exc.total)
                _save(build)
                _idle(build, ticket)
    except Exception as exc:
        with twin_store.LIFECYCLE, _LOCK:
            if _live(build, ticket):
                _spend(build)
                cached = _cache_path(build, step).is_file()
                retryable = cached or isinstance(exc, _ReadError)
                build['state'] = 'stopped' if retryable else 'failed'
                step['status'] = 'pending'
                logger.exception('Twin build %s step %s failed', build['id'], step['id'])
                _event(build, 'question' if retryable else 'error', step=step['id'],
                       text='This drawing could not be read. Check the page and try reading it again.')
                if cached and step['pause'] and isinstance(result, dict) and not result.get('error'):
                    try:
                        _pause(build, step, result)
                    except Exception:
                        pass
                _save(build)
                _idle(build, ticket)
    finally:
        with twin_store.LIFECYCLE, _LOCK:
            _idle(build, ticket)


twin_store.build_running = running
twin_store.stop_builds_for_start_over = stop_for_start_over
