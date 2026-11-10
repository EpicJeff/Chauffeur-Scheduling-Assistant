"""Restartable, piece-by-piece house builds from cropped drawing reads.

The lifecycle lock covers publication, never a reader call. A stopped worker
can cache its paid answer, but only the active worker may publish plan changes.
"""
from copy import deepcopy
import base64
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import quote
import uuid

from services import (twin_blocks, twin_compose, twin_cost, twin_draft, twin_library,
                      twin_joints, twin_place, twin_plan, twin_reads, twin_register,
                      twin_model, twin_roof_derive, twin_roof_issues, twin_store)

_LOCK = threading.RLock()
_BUILDS = {}
_WORKERS = {}
_ACTIVE = ('running', 'paused', 'checkpoint')
_FULL = [0, 0, 1, 1]
_clock = time.monotonic
_REAL_READER = twin_reads.read
logger = logging.getLogger(__name__)
_LABELS = {'roof': 'Roof sections', 'pitch': 'Roof slopes', 'plot': 'Lot',
           'draft': 'Reading the drawings', 'draft_rooms': 'Rooms',
           'site': 'Yard', 'compose': 'Plants and beds', 'finishes': 'Colours and finishes'}
STREAM_PATHS = {'building.levels': 'outline', 'building.walls': 'walls',
                'building.openings': 'doors and windows', 'building.fixtures': 'fixtures',
                'building.roof.sections': 'roofs', 'rooms': 'rooms', 'walls': 'walls'}


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
    if part is not None:
        return ([_step('draft'), _step('draft_rooms')]
                + ([_step('finishes')] if photos else [])
                + ([_step('fit', pause='lot_placement')] if has_lot else [])
                + ([_step('compose')] if compose else []))
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
                         'roof_flags': [flag for step in build['steps'] for flag in step.get('roof_flags', [])],
                         **{key: ([e for e in build[key] if e['seq'] > since]
                               if key == 'events' else build[key])
                         for key in ('id', 'state', 'steps', 'events', 'seq', 'pause', 'cost')}})


def _launch(build, reader, inline):
    ticket = uuid.uuid4().hex
    previous_state = build['state']
    build['state'] = 'running'
    try:
        _save(build)
    except Exception:
        build['state'] = previous_state
        raise
    _WORKERS[build['id']] = {'reader': reader, 'inline': inline, 'ticket': ticket, 'busy': True}
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
        if inputs.get('then'):
            build['chain_names'] = {b['id']: b['name'] for b in twin_store.place()['buildings']}
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
    plot_read = None
    if part == 'lot':
        inputs.pop('building', None)
        inputs['photos'] = []
        roles = []
        if not plot:
            raise ValueError('Add a plot plan to the lot first.')
        candidate = place['lot'].get('placement') or {}
        if candidate.get('confirmed') and all(candidate.get(k) == plot[0].get(k) for k in ('source', 'page', 'box')):
            placement = deepcopy(candidate)
        candidate_read = place['lot'].get('read') or {}
        if all(candidate_read.get(k) == plot[0].get(k) for k in ('source', 'page', 'box')):
            plot_read = deepcopy(candidate_read)
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
             'placement': placement, 'plot_read': plot_read, 'next': None,
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
            or build.get('next') or build.get('chain_error') or not build['inputs'].get('then')):
        return None
    # A pause may last indefinitely. Only hand off parts still buildable now;
    # new parts are left for the person's next whole-place Build.
    buildings = {b['id']: b for b in twin_store.place()['buildings']}
    pages = twin_store.page_roles()
    remaining = []
    for part in build['inputs']['then']:
        building = buildings.get(part)
        reason = None
        if building is None:
            reason = 'it is no longer part of your place.'
        elif not building.get('footprint') and not any(
                r['role'] == 'floor' and r.get('building') == part for r in pages):
            reason = 'it has no footprint yet.'
        if reason:
            name = (building or {}).get('name') or build.get('chain_names', {}).get(part) or part.replace('_', ' ').capitalize()
            _event(build, 'log', text=f'Skipped {name}: {reason}')
        else:
            remaining.append(part)
    build['inputs']['then'] = remaining
    if not remaining:
        # Reuse the ordinary composition path, with no paid reads or new build.
        build['inputs']['compose'] = True
        step = _step('compose')
        build['steps'].append(step)
        step['status'] = 'running'
        _event(build, 'stage', step=step['id'], label=step['label'])
        _settle(build, step, {'fragment': {}, 'problems': []})
        step['status'] = 'done'
        _save(build)
        return None
    successor = next((b for b in _BUILDS.values()
                      if b.get('previous') == build['id'] and b['generation'] == build['generation']
                      and b['inputs'].get('part') == remaining[0]), None)
    if successor is None:
        successor = _create({'part': remaining[0], 'then': remaining[1:], 'compose': len(remaining) == 1})
        successor.update(state='stopped', previous=build['id'], chain_names=deepcopy(build.get('chain_names', {})))
        _save(successor)
    build['next'] = successor['id']
    _event(build, 'next', id=successor['id'])
    _save(build)
    return successor


def _chain_failed(build):
    """A failed handoff is visible and terminal, including during recovery."""
    logger.exception('This build could not continue to the next building.')
    build['chain_error'] = True
    _event(build, 'error', text='The next part could not be built. Try building the remaining parts again.')
    _save(build)


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
                logger.warning('Skipped a build record that could not be read.', exc_info=True)
                continue
        # Load every saved successor before reconciling a missing forward link.
        # Recovered successors wait for Resume rather than starting paid reads.
        for build in recovered:
            try:
                _chain(build)
            except twin_store.StaleGeneration:
                continue
            except Exception:
                _chain_failed(build)


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
    identity = deepcopy(build['inputs']['building'])
    if build['inputs'].get('part') is not None:
        current = next((b for b in twin_store.place()['buildings'] if b['id'] == bid), None)
        if current is not None:
            identity = {k: current[k] for k in ('id', 'name', 'kind')}
    levels = [{'id': s['level'], 'name': s['level_name'], 'elevation': i * 9, 'ceiling': 9}
              for i, s in enumerate(s for s in build['steps'] if s['kind'] in ('outline', 'registration'))]
    if 'shell' in build['inputs']:
        levels = deepcopy(build['inputs']['shell']['levels'])
    if any(s['kind'] == 'draft' for s in build['steps']):
        levels = [{'id': f'L{i + 1}', 'name': r.get('level') or f'Floor {i + 1}',
                   'elevation': i * 9, 'ceiling': 9}
                  for i, r in enumerate(_draft_pages(build, floors_only=True))]
    if not levels:
        raise ValueError('No floor sheets are confirmed for this building.')
    if not any(b['id'] == bid for b in plan['buildings']):
        others = [twin_register.to_world(b, p) for b in plan['buildings']
                  for level in b['levels'] for p in level.get('outline', [])]
        position = [_bounds(others)[2] + 10, 0] if others else [0, 0]
        plan['buildings'].append({**identity, 'levels': levels,
                                  'position': position, 'rotation': 0, 'walls': [], 'openings': [],
                                  'rooms': [], 'roof': {'sections': []}})
    else:
        house = _house(plan, build)
        if build['inputs'].get('part') is not None:
            house.update(identity)
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


def _shape_mismatch(moving, fixed):
    """Check size after rigid alignment, independently of the edge-fit RMS."""
    def area(points):
        return abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(points, points[1:] + points[:1]))) / 2
    a, b = _bounds(moving), _bounds(fixed)
    return (abs(area(moving) - area(fixed)) > .1 * area(fixed) + 1e-6
            or any(abs((a[i + 2] - a[i]) - (b[i + 2] - b[i])) > 2 + 1e-6 for i in (0, 1)))


def _roof_registration(build, result, plan):
    first = next(s for s in build['steps'] if s['kind'] == 'outline')
    floor_reg = twin_store.registration(first['source'], first['page'], first['level'])
    reg = twin_register.make(floor_reg['scale'])
    enclosed = _outline(plan, build)
    eaves = _grow(enclosed, 1)
    crop, fragment = result['crop'], result['fragment']
    moving = [_map(crop, reg, p) for p in fragment['outline']]
    # New answers trace enclosed walls. Cached reads may trace one-foot eaves;
    # retain that allowance without fitting an enclosed outline to a larger one.
    trial, trial_rms = _fit(reg, moving, enclosed)
    matches_enclosed = not _shape_mismatch([_map(crop, trial, p) for p in fragment['outline']], enclosed)
    fixed = enclosed if matches_enclosed else eaves
    reg, rms = (trial, trial_rms) if matches_enclosed else _fit(reg, moving, fixed)
    mismatch = _shape_mismatch([_map(crop, reg, p) for p in fragment['outline']], fixed)
    return reg, rms, mismatch


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
        section = next((s for s in house['roof']['sections'] if s['id'] == piece.get('section')), None)
        if section and 'gable' in piece:
            axis = 1 if section['ridge'] == 'x' else 0
            edge = section['rect'][1 - axis + (0 if piece['gable'] == 'front' else 2)]
            center = piece.get('y' if axis else 'x')
            if center is None:
                # Normalize will explain/drop an unreadable gable opening;
                # identity matching must not abort the rest of the draft.
                return {}
            return {key: ([edge, d] if axis else [d, edge])
                    for key, d in (('from', center - piece['width'] / 2),
                                   ('to', center + piece['width'] / 2))}
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


def _deleted(piece, kind, house, build, tombstones=None):
    level = piece.get('level')
    if kind == 'opening':
        level = next((w['level'] for w in house['walls'] if w['id'] == piece.get('wall')), None)
        if 'gable' in piece:
            level = next((s.get('level') for s in house['roof']['sections']
                          if s['id'] == piece.get('section')), None)
    src = piece.get('src', {})
    return any(t['kind'] == kind and t['level'] == level
               and (t.get('building') is None or t['building'] == (house or {}).get('id'))
               and t['src'].get('sheet') == src.get('sheet')
               and t['src'].get('page') == src.get('page')
               and _near_geometry(_match_geometry(piece, kind, house),
                                  t.get('read_geometry') or t['geometry'], kind)
               or (kind == 'wall' and t['kind'] == kind and t['level'] == level
                   and t.get('building') in (None, house.get('id'))
                   and _near_geometry(_geometry(piece, kind, house), t['geometry'], kind))
               for t in (twin_store.tombstones() if tombstones is None else tombstones))


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
            if 'wall' in p:
                return next((w['level'] for w in house['walls'] if w['id'] == p['wall']), None)
            return next((s.get('level') for s in house['roof']['sections']
                         if s['id'] == p.get('section')), None)
        return p.get('level')
    if level(a) != level(b) or (kind == 'site' and a.get('kind') != b.get('kind')):
        return False
    if kind == 'fixture' and any(a.get(k) != b.get(k) for k in ('kind', 'surface')):
        return False
    ga = _match_geometry(a, kind, house)
    gb = (_geometry(b, kind, house) if kind == 'wall' and not original
          else _match_geometry(b, kind, house))
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


def _match_geometry(piece, kind, house):
    if piece.get('src', {}).get('person') and piece.get('read_geometry'):
        return piece['read_geometry']
    return _geometry(piece, kind, house)


def _merge_list(existing, incoming, kind, house, build, step=None, *, tombstones=None):
    protected_walls = {o.get('wall') for o in (house or {}).get('openings', []) if o.get('src', {}).get('person')}
    protected_sections = {o.get('section') for o in (house or {}).get('openings', [])
                          if o.get('src', {}).get('person')}
    def protected(p):
        return (p.get('src', {}).get('person') or (kind == 'wall' and p['id'] in protected_walls)
                or (kind == 'roof' and p['id'] in protected_sections))
    def length(p):
        geometry = _match_geometry(p, kind, house)
        return math.dist(geometry['from'], geometry['to'])
    merged = list(existing)
    kept = set()

    def keep_run(wall):
        # The connected model splits a read wall at its T joints into parts
        # id, id~2, id~3. A read of the whole wall matched to the person's
        # part is the same wall, so its other parts stay too.
        base = wall['id'].split('~')[0]
        kept.update(p['id'] for p in merged if p.get('level') == wall.get('level')
                    and p['id'].split('~')[0] == base)

    for piece in incoming:
        if _deleted(piece, kind, house, build, tombstones):
            continue
        if kind == 'wall':
            # A zoomed read can split a wall the whole-floor read already saw.
            # Retain the longer carrier and its provenance, so openings, hand
            # edits and later rereads still refer to the same wall.
            covering = next((p for p in merged if p.get('level') == piece.get('level')
                             and p.get('src', {}).get('step') != piece.get('src', {}).get('step')
                             and length(p) >= length(piece)
                             and _near_geometry(_geometry(piece, kind, house),
                                                _match_geometry(p, kind, house), kind)), None)
            if covering:
                piece['id'] = covering['id']
                kept.add(covering['id'])
                if protected(covering):
                    keep_run(covering)
                if covering.get('src', {}).get('person') and not covering.get('read_geometry'):
                    covering['read_geometry'] = deepcopy(_geometry(covering, kind, house))
                if not protected(covering) and piece.get('state') == 'settled':
                    covering['state'] = 'settled'
                    covering.pop('why', None)
                continue
        old = next((p for p in sorted(merged, key=lambda p: not protected(p))
                    if (_matches(piece, p, kind, house)
                        or (kind == 'wall' and not protected(p) and p.get('level') == piece.get('level')
                            and p.get('src', {}).get('step') != piece.get('src', {}).get('step')
                            and _near_geometry(_geometry(p, kind, house), _geometry(piece, kind, house), kind))
                        or (protected(p) and _matches(piece, p, kind, house, original=True)))), None)
        # Keep the extraction geometry when a later hand edit moves a piece.
        # A reread must not duplicate it back at its former location.
        piece['read_geometry'] = _geometry(piece, kind, house)
        if old:
            piece['id'] = old['id']
            kept.add(old['id'])
            if kind == 'wall' and protected(old):
                keep_run(old)
            if old.get('src', {}).get('person') and not old.get('read_geometry'):
                old['read_geometry'] = deepcopy(piece['read_geometry'])
            if not protected(old):
                merged[merged.index(old)] = deepcopy(piece)
                if kind == 'wall':
                    # A wider read can cover several earlier fragments.
                    merged = [p for p in merged if p['id'] == piece['id'] or protected(p)
                              or p.get('level') != piece.get('level')
                              or p.get('src', {}).get('step') == piece.get('src', {}).get('step')
                              or not _near_geometry(_geometry(p, kind, house),
                                                    _geometry(piece, kind, house), kind)]
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


def _draft_pages(build, *, floors_only=False):
    roles = ('floor',) if floors_only else ('floor', 'roof', 'elevation', 'other')
    return sorted((r for r in twin_store.page_roles()
                   if r.get('building') == build['inputs']['building']['id'] and r['role'] in roles),
                  key=lambda r: (r['page'], r.get('box') or _FULL, r['source']))


def _migrate_crop_draft(house, draft, step, tombstones, notes):
    before, stones, old_notes = deepcopy(house), deepcopy(tombstones), list(notes)
    try:
        _migrate_crop_draft_frame(house, draft, step, tombstones, notes)
    except Exception:
        logger.info('Crop-frame migration could not fit the drawings', exc_info=True)
        house.clear()
        house.update(before)
        tombstones[:] = stones
        notes[:] = old_notes
        _crop_draft_poor_fit(house, step, notes)


def _crop_draft_poor_fit(house, step, notes):
    line = 'Some of your changes may need moving: the new reading of the drawings sits differently.'
    if line not in notes:
        notes.append(line)
    levels = sorted((l for l in house.get('levels', []) if l.get('outline')),
                    key=lambda l: l['elevation'])
    remap = {level['id']: f'L{i + 1}' for i, level in enumerate(levels)}
    collections = [house.get(key, []) for key in
                   ('walls', 'openings', 'rooms', 'stairs', 'fixtures', 'lights')]
    collections += [house['roof'].get('sections', []), house['roof'].get('extensions', []),
                    twin_plan.porches(house), levels]
    for collection in collections:
        for piece in collection:
            if 'level' in piece:
                piece['level'] = remap.get(piece['level'], piece['level'])
            if not piece.get('src', {}).get('person') and piece.get('src', {}).get('step'):
                piece['src'] = {'sheet': '', 'page': 1, 'step': step['id']}
    for level in levels:
        level['id'] = remap[level['id']]
    house['levels'] = levels


def _migrate_crop_draft_frame(house, draft, step, tombstones, notes):
    """Change the old read frame once, alongside publication of the draft."""
    steps = {(w.get('src') or {}).get('step', '') for w in house['walls']}
    if 'draft' in steps or not any(s.startswith(('walls:', 'outline:')) for s in steps):
        return
    old_levels = sorted((l for l in house['levels'] if l.get('outline')),
                        key=lambda l: l['elevation'])
    new_levels = sorted(draft.get('levels', []), key=lambda l: l['elevation'])
    if not new_levels:
        return
    try:
        move, rms = twin_register.fit_outline(old_levels[0]['outline'], new_levels[0]['outline'])
    except (IndexError, ValueError):
        move, rms = None, math.inf
    good = rms <= 2 and abs(move['angle']) <= 1
    if not good:
        _crop_draft_poor_fit(house, step, notes)
        return
    level_ids = {level['id']: f'L{i + 1}' for i, level in enumerate(old_levels)}

    def point(p):
        return twin_register.to_world({'position': move['offset'], 'rotation': move['angle']}, p)

    def direction(side):
        vectors = {'x0': [-1, 0], 'x1': [1, 0], 'y0': [0, -1], 'y1': [0, 1]}
        vector = twin_register._rotate(vectors[side], move['angle'])
        return min(vectors, key=lambda key: math.dist(vector, vectors[key]))

    def geometry(piece):
        for key in ('from', 'to', 'position', 'at'):
            if isinstance(piece.get(key), (list, tuple)):
                piece[key] = point(piece[key])
        for key in ('outline', 'polygon', 'points', 'polyline'):
            if key in piece:
                piece[key] = [point(p) for p in piece[key]]
        if 'rect' in piece:
            corners = [point(p) for p in _corners(piece['rect'])]
            piece['rect'] = _bounds(corners)
        for column in piece.get('columns', []):
            geometry(column)
        if piece.get('read_geometry'):
            geometry(piece['read_geometry'])

    gables = {o['id']: _geometry(o, 'opening', house) for o in house['openings'] if 'gable' in o}
    porch_alias = house.get('porch')
    house['porches'] = twin_plan.porches(house)
    if porch_alias:
        house['porch'] = next(p for p in house['porches'] if p['id'] == porch_alias['id'])
    collections = [house.get(key, []) for key in
                   ('levels', 'walls', 'openings', 'rooms', 'stairs', 'fixtures', 'lights')]
    collections += [house['roof']['sections'], house['roof'].get('extensions', []), house['porches']]
    seen = set()
    for collection in collections:
        for piece in collection:
            if id(piece) in seen:
                continue
            seen.add(id(piece))
            if good:
                geometry(piece)
                if piece.get('ridge') in ('x', 'y'):
                    piece['ridge'] = direction(piece['ridge'] + '1')[0]
                if piece.get('low_side') in ('x0', 'x1', 'y0', 'y1'):
                    piece['low_side'] = direction(piece['low_side'])
                if piece.get('pitches'):
                    piece['pitches'] = {direction(side): pitch for side, pitch in piece['pitches'].items()}
            if 'level' in piece:
                piece['level'] = level_ids.get(piece['level'], piece['level'])
            if not piece.get('src', {}).get('person') and piece.get('src', {}).get('step'):
                # Retire every crop read in this draft merge, even if its
                # geometry has no match. Retained carriers keep stable ids.
                piece['src'] = {'sheet': '', 'page': 1, 'step': step['id']}
    for level in old_levels:
        level['id'] = level_ids[level['id']]
    house['levels'] = old_levels
    if good:
        for opening in house['openings']:
            if opening['id'] not in gables:
                continue
            endpoints = [point(p) for p in gables[opening['id']].values()]
            section = next(s for s in house['roof']['sections'] if s['id'] == opening['section'])
            axis = 1 if section['ridge'] == 'x' else 0
            center = [(endpoints[0][i] + endpoints[1][i]) / 2 for i in (0, 1)]
            opening.pop('x' if axis else 'y', None)
            opening['y' if axis else 'x'] = center[axis]
            opening['gable'] = min(('front', 'rear'), key=lambda side:
                abs(center[1 - axis] - section['rect'][1 - axis + (0 if side == 'front' else 2)]))
        for stone in tombstones:
            if stone.get('building') != house['id']:
                continue
            geometry(stone['geometry'])
            if stone.get('read_geometry'):
                geometry(stone['read_geometry'])
            stone['level'] = level_ids.get(stone['level'], stone['level'])
            stone['src'] = {'sheet': '', 'page': 1, 'step': step['id']}
        if house.get('position_from') == 'person':
            # new = Rfit * old + offset. Compose the inverse fit with the
            # old lot transform so every migrated point stays put on the lot.
            house['rotation'] = (house['rotation'] - move['angle']) % 360
            delta = twin_register._rotate(move['offset'], house['rotation'])
            house['position'] = [house['position'][i] - delta[i] for i in (0, 1)]


def _merge_draft(build, step, fragment, house, *, tombstones=None, notes=None):
    """The read already uses building feet. Merge identities before references."""
    draft = deepcopy(fragment.get('building', {}) if step['kind'] == 'draft' else fragment)
    pages = _draft_pages(build, floors_only=True)
    if step['kind'] == 'draft':
        all_pages = _draft_pages(build)
        names = {p['level']: all_pages[p['image']].get('level')
                 for p in fragment.get('pages', [])
                 if 0 <= p['image'] < len(all_pages) and all_pages[p['image']]['role'] == 'floor'}
        levels = sorted(draft.get('levels', []), key=lambda l: l['elevation'])
        remap = {l['id']: f'L{i + 1}' for i, l in enumerate(levels)}
        for i, level in enumerate(levels):
            name = names.get(level['id']) or (pages[i].get('level') if i < len(pages) else None)
            level['id'] = remap[level['id']]
            level['name'] = name or level['name']
            level.update(state='settled', src={'sheet': '', 'page': 1, 'step': step['id']})
            old = next((l for l in house['levels'] if l['id'] == level['id']), None)
            if old and old.get('src', {}).get('person'):
                level.update(deepcopy(old))
        if not levels:
            return
        house['levels'] = levels + [l for l in house['levels']
            if l['id'] not in remap.values() and l.get('src', {}).get('person')]
        for key in ('walls', 'rooms', 'stairs', 'fixtures'):
            for piece in draft.get(key, []):
                piece['level'] = remap.get(piece.get('level'), piece.get('level'))

    def pieces(key, kind, values=None):
        return [_piece(build, step, kind, i, **{'state': 'settled', **{k: v for k, v in p.items() if k != 'id'}})
                for i, p in enumerate(draft.get(key, []) if values is None else values)]

    walls = pieces('walls', 'wall')
    old_ids = [w.get('id') for w in draft.get('walls', [])]
    # A rooms partition may continue inward from a short exterior jog. It
    # must not replace that carrier or change the settled outside walls.
    exterior = [w for w in house['walls'] if w.get('exterior')] if step['kind'] == 'draft_rooms' else []
    existing = [w for w in house['walls'] if not w.get('exterior')] if exterior else house['walls']
    house['walls'] = exterior + _merge_list(existing, walls, 'wall', house, build, step, tombstones=tombstones)
    wall_ids = dict(zip(old_ids, (w['id'] for w in walls)))
    if step['kind'] == 'draft':
        incoming_ids = set(wall_ids.values())
        retired = set()
        for carrier in house['walls']:
            if carrier['id'] in incoming_ids or carrier.get('src', {}).get('person'):
                continue
            source_step = carrier.get('src', {}).get('step', '')
            if source_step != 'draft' and not source_step.startswith(('walls:', 'outline:')):
                continue
            vector = [carrier['to'][i] - carrier['from'][i] for i in (0, 1)]
            carrier_length = math.hypot(*vector)
            def parallel(wall):
                direction = [wall['to'][i] - wall['from'][i] for i in (0, 1)]
                return carrier_length > 0 and abs(sum(a * b for a, b in zip(vector, direction))) >= (
                    math.cos(math.radians(10)) * carrier_length * math.hypot(*direction))
            openings = [o for o in house['openings'] if o.get('wall') == carrier['id']
                        and o.get('src', {}).get('person')]
            if not openings:
                continue
            replacements = []
            for opening in openings:
                geometry = _geometry(opening, 'opening', house)
                center = [(geometry['from'][i] + geometry['to'][i]) / 2 for i in (0, 1)]
                hit = min(((*_nearest(center, w['from'], w['to']), w) for w in house['walls']
                           if w['id'] in incoming_ids and w['level'] == carrier['level']
                           and parallel(w)
                           and math.dist(w['from'], w['to']) >= opening['width']),
                          key=lambda h: h[0], default=None)
                if hit is None or hit[0] > 2:
                    break
                _, at, wall = hit
                length = math.dist(wall['from'], wall['to'])
                replacements.append((opening, wall['id'], max(opening['width'] / 2,
                    min(length - opening['width'] / 2, at))))
            if len(replacements) == len(openings):
                for opening, wall_id, at in replacements:
                    opening.update(wall=wall_id, at=at)
                retired.add(carrier['id'])
            elif notes is not None:
                line = 'Kept an earlier wall because your opening has no replacement wall within 2 ft.'
                if line not in notes:
                    notes.append(line)
        house['walls'] = [w for w in house['walls'] if w['id'] not in retired]
    rooms = pieces('rooms', 'room')
    house['rooms'] = _merge_list(house['rooms'], rooms, 'room', house, build, step, tombstones=tombstones)
    if step['kind'] != 'draft':
        return
    roof = draft.get('roof', {})
    current_choices = twin_plan._roof_entries(house['roof'], 'choices')
    choices = [c for c in twin_plan._roof_entries(roof, 'choices') if not any(
        max(abs(a - b) for a, b in zip(c['rect'], current['rect'])) <= 1
        for current in current_choices)] + current_choices
    house['roof']['choices'] = deepcopy(choices)
    flags = twin_plan._roof_entries(roof if 'flags' in roof else house['roof'], 'flags')
    house['roof']['flags'] = [deepcopy(f) for f in flags if not any(
        max(abs(a - b) for a, b in zip(f['block_rect'], c['rect'])) <= 1 for c in choices)]
    sections = pieces('', 'roof', roof.get('sections', []))
    old_sections = [s['id'] for s in roof.get('sections', [])]
    # A person's gable window protects its old carrier in _merge_list. Move
    # the window first so the first block rebuild can retire that old roof.
    replaced = [s for s in house['roof']['sections'] if not s.get('src', {}).get('person')
                and any(t.get('block') and _roof_overlap(s['rect'], t['rect']) > 0 for t in sections)
                and not any(_matches(t, s, 'roof', house) for t in sections)]
    incoming_ids = [s['id'] for s in sections]
    _remap_roof_attachments(house['openings'], house['roof'].get('extensions', []), replaced, sections)
    house['roof']['sections'] = [s for s in house['roof']['sections'] if s not in replaced]
    roof_step = {**step, 'removed_steps': [*step.get('removed_steps', []), 'roof_blocks']}
    house['roof']['sections'] = _merge_list(house['roof']['sections'], sections, 'roof', house, build, roof_step,
                                            tombstones=tombstones)
    merged_ids = dict(zip(incoming_ids, (s['id'] for s in sections)))
    for attachment in [*house['openings'], *house['roof'].get('extensions', [])]:
        if attachment.get('section') in merged_ids:
            attachment['section'] = merged_ids[attachment['section']]
    section_ids = dict(zip(old_sections, (s['id'] for s in sections)))
    openings = pieces('openings', 'opening')
    for opening in openings:
        if 'wall' in opening:
            opening['wall'] = wall_ids.get(opening['wall'], opening['wall'])
        if 'section' in opening:
            opening['section'] = section_ids.get(opening['section'], opening['section'])
        # Keep readable geometry through normalize so the post-snap check can
        # show an invalid opening as a ghost instead of losing it.
        reason = twin_plan._opening_error(opening, {w['id']: w for w in house['walls']},
                                          {s['id']: s for s in house['roof']['sections']})
        if reason in ('outside the wall span', 'head is above the wall height'):
            opening.update(state='ghost', why='This opening extends beyond its wall span or height.')
    house['openings'] = _merge_list(house['openings'], openings, 'opening', house, build, step,
                                   tombstones=tombstones)
    extensions = pieces('', 'extension', roof.get('extensions', []))
    for extension in extensions:
        extension['section'] = section_ids.get(extension['section'], extension['section'])
    house['roof']['extensions'] = _merge_list(house['roof'].get('extensions', []), extensions,
                                             'extension', house, build, step, tombstones=tombstones)
    # Keep the legacy field as an alias when that is what the read supplied.
    # Merge the complete collection through the usual person-edit protections.
    legacy = house.get('porch')
    house['porches'] = _merge_list(twin_plan.porches(house), pieces('', 'porch', twin_plan.porches(draft)),
                                  'porch', house, build, step, tombstones=tombstones)
    if not (legacy or {}).get('src', {}).get('person'):
        house['porch'] = (next((p for p in house['porches']
                               if p['polygon'] == draft['porch']['polygon']), None)
                          if draft.get('porch') else None)
    house['stairs'] = _merge_list(house.get('stairs', []), pieces('stairs', 'stair'),
                                  'stair', house, build, step, tombstones=tombstones)
    if 'fixtures' in draft:
        fixtures = pieces('fixtures', 'fixture')
        for fixture in fixtures:
            if 'wall' in fixture:
                fixture['wall'] = wall_ids.get(fixture['wall'], fixture['wall'])
        # Flat output keeps anchors for the renderer. Only a new fixture read
        # converts generated anchors back to read pieces for identity merging.
        anchors = [p for p in house.get('anchors', []) if 'surface' in p]
        ids = {p['id'] for p in anchors if not p.get('src', {}).get('person')}
        existing = house.get('fixtures', []) + anchors
        house['anchors'] = [p for p in house.get('anchors', []) if p['id'] not in ids]
        house['lights'] = [p for p in house.get('lights', []) if p['id'] not in ids]
        house['fixtures'] = [p for p in existing if 'rect' in p] + _merge_list(
            [p for p in existing if 'rect' not in p], fixtures, 'fixture', house, build, step,
            tombstones=tombstones)


def _check_draft(house):
    """Check the snapped building, keeping failures visible and explainable."""
    def ghost(piece, why):
        if not piece.get('src', {}).get('person'):
            piece.update(state='ghost', why=why)

    def area(poly):
        return abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(poly, poly[1:] + poly[:1]))) / 2

    def boundary(poly):
        points = list(poly)
        for a, b in zip(poly, poly[1:] + poly[:1]):
            count = max(1, math.ceil(math.dist(a, b) * 2))
            points.extend([[a[j] + (b[j] - a[j]) * k / count for j in (0, 1)]
                           for k in range(1, count)])
        return points

    def within(point, poly, margin):
        return bool(poly) and (_inside(point, poly) or min(
            _nearest(point, a, b)[0] for a, b in zip(poly, poly[1:] + poly[:1])) <= margin + 1e-6)

    levels = sorted(house['levels'], key=lambda l: l['elevation'])
    first_failed = False
    for i, level in enumerate(levels):
        outline = level.get('outline', [])
        level_walls = [w for w in house['walls'] if w['level'] == level['id']]
        walls = [w for w in level_walls if w.get('exterior')]
        # Boundary knee walls also close exterior-wall runs under the roof.
        # A half storey may have only these runs, with gable ends left open.
        knee_walls = [w for w in level_walls if not w.get('exterior')
                      and outline and all(min(_nearest(p, a, b)[0]
                          for a, b in zip(outline, outline[1:] + outline[:1])) <= .1 + 1e-6
                          for p in boundary([w['from'], w['to']]))]
        closing = walls + knee_walls
        if level.get('half'):
            walls = closing = level_walls
        open_walls = [w for w in walls if any(not any(
            other is not w and _nearest(p, other['from'], other['to'])[0] <= .1 + 1e-6
            for other in closing) and not (level.get('half') and not w.get('exterior')
                and any(math.dist(p, corner) <= .1 + 1e-6 for corner in outline))
            for p in (w['from'], w['to']))]
        failing = open_walls
        why = ''
        level_failed = not walls and not level.get('half')
        if level_failed or open_walls:
            why = "This floor's exterior walls do not close."
        if i:
            below = levels[i - 1].get('outline', [])
            outline = level.get('outline', [])
            # Vertices alone miss an edge crossing a recess in an L-shaped
            # floor below. Check the boundary at half-foot intervals too.
            if below and any(not within(p, below, 2) for p in boundary(outline)):
                why = 'The upper floor extends more than 2 ft beyond the floor below.'
                failing = walls
                level_failed = True
            elif below and area(outline) < .2 * area(below):
                why = 'The upper floor is less than a fifth of the floor below.'
                failing = walls
                level_failed = True
        if why:
            if level_failed:
                ghost(level, why)
            for wall in failing:
                ghost(wall, why)
        if i == 0:
            first_failed = level_failed or (bool(walls) and all(w.get('state') == 'ghost' for w in walls))
    for section in house['roof']['sections']:
        bearing = [l for l in levels if l['elevation'] + .5 < section['plate']
                   <= l['elevation'] + l['ceiling'] + 2]
        corners = _corners(section['rect'])
        # Inner edges can join other roof sections over the house interior.
        if any(all(within(p, l.get('outline', []), 3) for p in boundary(corners)) for l in bearing):
            continue
        if twin_joints.section_outside_outline(house, section):
            if not twin_joints.porch_supports_section(house, section):
                ghost(section, 'This porch roof has no porch or columns beneath it.')
        else:
            ghost(section, 'This roof section does not meet its bearing walls within 3 ft.')
    walls = {w['id']: w for w in house['walls']}
    sections = {s['id']: s for s in house['roof']['sections']}
    for opening in house['openings']:
        if opening.get('state') == 'ghost' and opening.get('position') and opening.get('why') and 'section' in opening:
            continue
        reason = twin_plan._opening_error(opening, walls, sections)
        if reason:
            ghost(opening, 'This opening extends beyond its wall span or height.')
        elif opening.get('src', {}).get('step') == 'draft' and not opening.get('src', {}).get('person'):
            opening['state'] = 'settled'
            opening.pop('why', None)
    return first_failed


def _check_draft_rooms(house, step):
    """Contain complete edges, including crossings of a concave outline."""
    outlines = {l['id']: l.get('outline', []) for l in house['levels']}
    anchors = {lid: list(zip(poly, poly[1:] + poly[:1])) for lid, poly in outlines.items()}
    wall_lines = {}
    for wall in house['walls']:
        if wall.get('exterior') and wall.get('state') != 'ghost':
            wall_lines.setdefault(wall['level'], []).append((wall['from'], wall['to']))

    def snap(point, lid):
        candidates = []
        for a, b in anchors.get(lid, []):
            distance, along = _nearest(point, a, b)
            length = math.dist(a, b)
            target = [a[i] + (b[i] - a[i]) * along / length for i in (0, 1)] if length else list(a)
            candidates.append((distance, target))
        for a, b in wall_lines.get(lid, []):
            length2 = sum((b[i] - a[i]) ** 2 for i in (0, 1))
            if not length2 or _nearest(point, a, b)[0] > .5 + 1e-6:
                continue
            t = sum((point[i] - a[i]) * (b[i] - a[i]) for i in (0, 1)) / length2
            target = [a[i] + t * (b[i] - a[i]) for i in (0, 1)]
            # Use the nearby wall's line past a corner only into the floor.
            # Clamping an interior vertex to that corner distorts shared
            # room edges; extending outward would keep an overshoot outside.
            if _inside(target, outlines.get(lid, [])):
                candidates.append((math.dist(point, target), target))
        nearest = min(candidates, key=lambda row: row[0], default=None)
        return nearest[1] if nearest and nearest[0] <= .5 + 1e-6 else list(point)

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def contained(points, outline):
        if not outline:
            return False
        edges = list(zip(outline, outline[1:] + outline[:1]))

        def inside(p):
            return _inside(p, outline) or any(_nearest(p, a, b)[0] <= .25 + 1e-6 for a, b in edges)

        if not all(inside(p) for p in points):
            return False
        for a, b in zip(points, points[1:]):
            direction = [b[i] - a[i] for i in (0, 1)]
            cuts = [0, 1]
            for c, d in edges:
                edge = [d[i] - c[i] for i in (0, 1)]
                offset = [c[i] - a[i] for i in (0, 1)]
                denominator = cross(direction, edge)
                if abs(denominator) <= 1e-12:
                    continue
                t, u = cross(offset, edge) / denominator, cross(offset, direction) / denominator
                if 0 <= t <= 1 and 0 <= u <= 1:
                    cuts.append(t)
            cuts.sort()
            if any(not inside([a[i] + direction[i] * (lo + hi) / 2 for i in (0, 1)])
                   for lo, hi in zip(cuts, cuts[1:])):
                return False
        return True

    for key, noun in (('rooms', 'room'), ('walls', 'interior wall')):
        for piece in house[key]:
            if piece.get('src', {}).get('step') != step['id'] or piece.get('src', {}).get('person'):
                continue
            if key == 'rooms':
                piece['polygon'] = [snap(p, piece['level']) for p in piece['polygon']]
            else:
                for end in ('from', 'to'):
                    piece[end] = snap(piece[end], piece['level'])
            points = (piece['polygon'] + piece['polygon'][:1] if key == 'rooms'
                      else [piece['from'], piece['to']])
            if not contained(points, outlines.get(piece['level'], [])):
                piece.update(state='ghost', why=f"This {noun} extends outside its floor's outline.")


def _pause_draft(build, step):
    build['pause'] = {'kind': 'draft', 'step': step['id'], 'registration': None,
                      'why': 'The drawings could not be read as one building.'}
    build['state'] = 'paused'
    step['status'] = 'paused'
    _event(build, 'question', step=step['id'], text=build['pause']['why'])


def _images_context(build, step, sheets=None):
    context = {'level': step['level'],
               'box': deepcopy(step['box'] or _FULL)}
    if 'building' in build['inputs']:
        context['building'] = deepcopy(build['inputs']['building'])
    if step['kind'] in ('draft', 'draft_rooms'):
        images, pages = [], []
        for row in _draft_pages(build, floors_only=step['kind'] == 'draft_rooms'):
            crop = twin_store.crop(row['source'], row['page'], row.get('box') or _FULL, max_side=2576)
            if sheets is not None:
                sheets.append({**deepcopy(row), 'image': len(images),
                               'crop': {k: crop[k] for k in ('box', 'size', 'master')}})
            pages.append({'image': len(images), 'role': row['role'], 'level_name': row.get('level')})
            images.append({'mime': crop['mime'], 'b64': crop['b64']})
        context['pages'] = pages
        if step['kind'] == 'draft':
            images.extend(image for source in build['inputs'].get('photos', [])[:4]
                          for image in twin_store.source_images(source))
        else:
            house = _house(twin_store.current(), build)
            context['settled'] = {key: deepcopy([p for p in house[key]
                if p.get('state') != 'ghost' and (key != 'walls' or p.get('exterior'))])
                for key in ('levels', 'walls', 'openings')}
        return images, context, None
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
            context['sections'] = [{'id': s['id'], 'kind': s['kind'], 'ridge': s.get('ridge'),
                                    'size_ft': [s['rect'][2] - s['rect'][0], s['rect'][3] - s['rect'][1]],
                                    'where': where(s)} for s in sections]
        else:
            context['sections'] = []
    if step['kind'] in ('pitch', 'finishes'):
        if step['kind'] == 'finishes':
            kit = twin_library.kit('modern_farmhouse')
            context['kit_materials'] = deepcopy(kit['materials'])
            context['allowed_asset_ids'] = sorted({v['asset'] for v in kit['materials'].values()})
        images = [image for source in build['inputs'].get('photos', []) for image in twin_store.source_images(source)]
        return images, context, None
    crop = twin_store.crop(step['source'], step['page'], context['box'])
    context['box'] = crop['box']
    return [{'mime': crop['mime'], 'b64': crop['b64']}], context, {k: crop[k] for k in ('box', 'size', 'master')}


def _start_draft_heartbeat(build, step, ticket, context, finished, mode, *, started=None):
    clock = _clock

    def heartbeat(started):
        due = 15
        while not finished.wait(0.1):
            try:
                elapsed = max(0, int(clock() - started))
                if elapsed < due:
                    continue
                with twin_store.LIFECYCLE, _LOCK:
                    if finished.is_set() or not _live(build, ticket):
                        return
                    name = context['building']['name']
                    text = ('Checking the roofs against the photos, ' if mode == 'roof_observe'
                            else f'Reading the rooms of the {name} drawings, ' if step['kind'] == 'draft_rooms'
                            else f'Reading the {name} drawings {mode}, ')
                    _event(build, 'log', step=step['id'],
                           text=text + f'{elapsed // 60}:{elapsed % 60:02d} so far.')
                    _save(build)
                due = elapsed + 15
            except Exception:
                logger.info('Draft heartbeat stopped', exc_info=True)
                return

    pulse = threading.Thread(target=heartbeat, args=(clock() if started is None else started,), daemon=True,
                             name=f"twin-heartbeat-{build['id'][:8]}")
    pulse.start()
    return pulse


def _read_draft(build, step, reader, ticket, images, context, sheets):
    """Run the paid pair together; only the draft can publish plan geometry."""
    finished = threading.Event()

    def read(kind, read_images, read_context):
        options = {'checkpoint_checked': True} if reader is _REAL_READER else {}
        return reader(kind, read_images, read_context, run=build['id'], step=step['id'], **options)

    def outline():
        try:
            sheet = next(s for s in sheets if s['role'] == 'floor')
            crop = sheet['crop']
            raw = read('outline', [images[sheet['image']]],
                       {'level': 'L1', 'box': crop['box'], 'building': context['building']})
            if isinstance(raw, dict) and raw.get('error'):
                raise _ReadError(raw['error'])
            fragment, _ = twin_reads.parse('outline', raw)
            reg, _ = _registration(build, _step('outline', sheet, 'L1'),
                                   {'fragment': fragment, 'crop': crop}, None)
            points = [_map(crop, reg, p) for p in fragment['outline']]
            with twin_store.LIFECYCLE, _LOCK:
                if not finished.is_set() and _live(build, ticket):
                    for i, (a, b) in enumerate(zip(points, points[1:] + points[:1])):
                        _ghost(build, step, {'id': f'draft-outline:{i}', 'level': 'L1', 'from': a, 'to': b,
                                             'outline': points},
                               'First look at the outline while the drawings are read.')
                    _save(build)
        except Exception:
            # A first look is disposable, including unusable geometry.
            logger.info('First-look outline dropped', exc_info=True)
        finally:
            with twin_store.LIFECYCLE, _LOCK:
                if (_BUILDS.get(build['id']) is build
                        and build['generation'] == twin_store.generation()
                        and _WORKERS.get(build['id'], {}).get('ticket') == ticket):
                    _spend(build)
                    _save(build)

    threading.Thread(target=outline, daemon=True, name=f"twin-outline-{build['id'][:8]}").start()
    pulse = _start_draft_heartbeat(build, step, ticket, context, finished, 'as one set')
    try:
        return read('draft', images, context)
    finally:
        finished.set()
        pulse.join()


def _register_draft(result):
    """Fit each drawn floor's sheet to the same remapped levels as the draft."""
    fragment = result['fragment']
    levels = sorted(fragment['building'].get('levels', []), key=lambda l: l['elevation'])
    remap = {level['id']: f'L{i + 1}' for i, level in enumerate(levels)}
    sheets = {s['image']: s for s in result.get('sheets', []) if s['role'] == 'floor'}
    anchored = set()
    def person(reg):
        return reg and (reg.get('source') == 'person'
                        or reg.get('src', {}).get('person'))
    for page in fragment.get('pages', []):
        sheet = sheets.get(page['image'])
        level = remap.get(page['level'])
        if sheet is None or level is None:
            continue
        try:
            key = (sheet['source'], sheet['page'], level)
            if person(twin_store.registration(*key)):
                anchored.add(key)
                continue
            anchors = page['anchors']
            reg, _ = twin_register.from_points(
                [twin_store.crop_to_master(sheet['crop'], a['px']) for a in anchors],
                [a['at'] for a in anchors])
            reg['source'] = 'draft'
            twin_store.set_registration(*key, reg)
            anchored.add(key)
        except Exception:
            logger.info('Draft sheet could not be lined up', exc_info=True)
            continue
    drawn = {(s['source'], s['page']) for s in sheets.values()}
    for row in twin_store.registrations():
        key = (row['source'], row['page'], row['level'])
        if key[:2] in drawn and key not in anchored and not person(row['reg']):
            try:
                twin_store.clear_registration(*key)
            except Exception:
                logger.info('Old draft sheet placement could not be cleared', exc_info=True)


def _draft_preview(build, step, fragment):
    """Check a fresh read without publishing it or reusing a previous draft."""
    plan = _base(None, build)
    _merge_draft(build, step, fragment, _house(plan, build))
    plan, _ = twin_plan.normalize(plan)
    house = _house(plan, build)
    twin_joints.snap(house)
    failed = _check_draft(house)
    return house, failed


def _cache_result(build, step, ticket, result):
    with twin_store.LIFECYCLE, _LOCK:
        # A stop keeps paid replies. Only a new generation or worker discards them.
        if (build['generation'] != twin_store.generation()
                or _BUILDS.get(build['id']) is not build
                or _WORKERS.get(build['id'], {}).get('ticket') != ticket):
            return None
        _atomic(_cache_path(build, step), result)
    return result


def _read_draft_levels(build, step, reader, ticket, images, context, progress):
    started = _clock()
    fragment = {'building': {'levels': [], 'walls': [], 'openings': [], 'rooms': [],
                             'roof': {'sections': [], 'extensions': []}, 'porches': [], 'stairs': []},
                'pages': [], 'checks': {}, 'notes': []}
    problems, reads = [], progress['level_reads']
    settled = {'levels': [], 'walls': [], 'openings': []}
    floors = [page for page in context['pages'] if page['role'] == 'floor']
    scopes = [(f'L{i + 1}', page.get('level_name')) for i, page in enumerate(floors)] + [('roof', None)]
    with twin_store.LIFECYCLE, _LOCK:
        if not _live(build, ticket):
            return None
        sentence = 'The drawings were read one floor at a time.'
        if not any(e['type'] == 'log' and e.get('step') == step['id'] and e.get('text') == sentence
                   for e in build['events']):
            _event(build, 'log', step=step['id'], text=sentence)
            _save(build)
    for index, (scope, name) in enumerate(scopes):
        with twin_store.LIFECYCLE, _LOCK:
            if not _live(build, ticket):
                return None
        read_context = {**deepcopy(context), 'level': scope, 'level_name': name,
                        'settled': deepcopy(settled)}
        if index < len(reads):
            part, issues = reads[index]['fragment'], reads[index]['problems']
        else:
            twin_cost.require_clear()
            options = {'checkpoint_checked': True} if reader is _REAL_READER else {}
            finished = threading.Event()
            pulse = _start_draft_heartbeat(build, step, ticket, context, finished, 'one floor at a time',
                                            started=started)
            try:
                raw = reader('draft_level', images, read_context, run=build['id'], step=step['id'], **options)
            finally:
                finished.set()
                pulse.join()
            if isinstance(raw, dict) and raw.get('error'):
                raise _ReadError(raw['error'])
            part, issues = twin_reads.parse('draft_level', raw)
            if isinstance(raw, dict):
                issues = list(raw.get('problems') or []) + issues
            reads.append({'context': read_context, 'fragment': part, 'problems': issues})
            if _cache_result(build, step, ticket, progress) is None:
                return None
        problems.extend(issues)
        incoming = deepcopy(part.get('building', {}))
        if scope == 'roof':
            usable = bool(incoming.get('roof', {}).get('sections')) and not incoming.get('levels')
        else:
            usable = (len(incoming.get('levels', [])) == 1
                      and incoming['levels'][0]['id'] == scope)
        if not usable:
            return fragment, problems, reads, True
        if scope != 'roof':
            # Separate replies may both call their first wall w1. Keep their
            # references distinct and never revise a settled lower floor.
            incoming['walls'] = [w for w in incoming.get('walls', []) if w['level'] == scope]
            wall_ids = {w['id']: f"{scope}:{w['id']}" for w in incoming['walls'] if 'id' in w}
            for wall in incoming['walls']:
                if 'id' in wall:
                    wall['id'] = wall_ids[wall['id']]
            incoming['openings'] = [{**o, 'wall': wall_ids[o['wall']]}
                                    for o in incoming.get('openings', []) if o.get('wall') in wall_ids]
            for key in ('rooms', 'stairs', 'fixtures'):
                incoming[key] = [p for p in incoming.get(key, []) if p['level'] == scope]
            for fixture in incoming['fixtures']:
                if 'wall' in fixture:
                    fixture['wall'] = wall_ids.get(fixture['wall'], fixture['wall'])
            incoming.pop('roof', None)
        else:
            for key in ('walls', 'rooms', 'stairs', 'fixtures'):
                incoming.pop(key, None)
            incoming['openings'] = [o for o in incoming.get('openings', []) if 'gable' in o]
            # Floor reads own their porches, including columns. A roof read
            # may add a distinct porch, but cannot replace a nearby floor one.
            incoming['porches'] = [p for p in twin_plan.porches(incoming) if not any(
                _matches(p, floor, 'porch', {}) for floor in twin_plan.porches(fragment['building']))]
            incoming.pop('porch', None)
        for key in ('levels', 'walls', 'openings', 'rooms', 'porches', 'stairs'):
            fragment['building'][key].extend(deepcopy(incoming.get(key, [])))
        if 'fixtures' in incoming:
            fragment['building'].setdefault('fixtures', []).extend(deepcopy(incoming['fixtures']))
        if incoming.get('porch'):
            fragment['building']['porches'].append(deepcopy(incoming['porch']))
            fragment['building'].setdefault('porch', deepcopy(incoming['porch']))
        for key in ('sections', 'extensions'):
            fragment['building']['roof'][key].extend(deepcopy(incoming.get('roof', {}).get(key, [])))
        fragment['pages'].extend(deepcopy(part.get('pages', [])))
        fragment['checks'].update(deepcopy(part.get('checks', {})))
        fragment['notes'].extend(part.get('notes', []))
        house, first_failed = _draft_preview(build, step, fragment)
        level = next((l for l in house['levels'] if l['id'] == scope), None)
        if first_failed or (scope != 'roof' and level is None):
            return fragment, problems, reads, True
        settled = {key: deepcopy([p for p in house[key] if p.get('state') != 'ghost'
                                  and (key != 'walls' or p.get('exterior'))])
                   for key in settled}
        with twin_store.LIFECYCLE, _LOCK:
            if _live(build, ticket):
                _spend(build)
                _save(build)
    return fragment, problems, reads, False


def _draft_roof_issues(draft):
    # Normalize a private copy, retaining read ids for located warnings.
    try:
        plan, _ = twin_plan.normalize({'units': 'ft', 'buildings': [draft]})
        return twin_roof_issues.roof_issues(plan['buildings'][0])
    except Exception:
        # Advisory warnings must never prevent the roof read or settlement.
        return []


def _roof_overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _remap_roof_attachments(openings, extensions, sources, targets):
    """Move attachments by their physical edge, never by roof area alone."""
    sources = {s['id']: s for s in sources}
    target_ids = {s['id'] for s in targets}
    for opening in openings:
        source = sources.get(opening.get('section'))
        if not source or (source['id'] in target_ids and source.get('state') != 'ghost') or 'gable' not in opening:
            continue
        along = 0 if source['ridge'] == 'x' else 1
        across = 1 - along
        point = [0, 0]
        point[along] = source['rect'][along + (0 if opening['gable'] == 'front' else 2)]
        # Older draft replies used x even for the span of a ridge-x gable.
        # Read that coordinate before rewriting it to the canonical axis.
        point[across] = opening.get('y' if across else 'x', opening.get('x' if across else 'y'))
        if point[across] is None:
            continue
        matches = []
        for target in targets:
            if (_roof_overlap(source['rect'], target['rect']) <= 0
                    or target.get('state') == 'ghost'
                    or target['kind'] not in ('gable', 'hip')):
                continue
            axis = 0 if target['ridge'] == 'x' else 1
            span = 1 - axis
            for end in (0, 1):
                style = target.get('ends', {}).get(f'{target["ridge"]}{end}', target['kind'])
                distance = abs(point[axis] - target['rect'][axis + 2 * end])
                if (style in ('gable', 'clip') and distance <= 1 + 1e-6
                        and point[span] - opening['width'] / 2 >= target['rect'][span] - 1e-6
                        and point[span] + opening['width'] / 2 <= target['rect'][span + 2] + 1e-6):
                    candidate = {**opening, 'section': target['id'], 'gable': 'rear' if end else 'front'}
                    candidate.pop('x' if span else 'y', None)
                    candidate['y' if span else 'x'] = point[span]
                    if twin_plan._opening_error(candidate, {}, {target['id']: target}) is None:
                        matches.append((distance, abs(source['plate'] - target['plate']), target['id'], candidate))
        if matches:
            candidate = min(matches, key=lambda m: m[:3])[3]
            opening.pop('x' if 'y' in candidate else 'y', None)
            opening.update(candidate)
        else:
            opening.update(state='ghost', position=point,
                           why='This window has no matching gable on the new roof; please place it.')
    for extension in extensions:
        source = sources.get(extension.get('section'))
        if not source or (source['id'] in target_ids and source.get('state') != 'ghost'):
            continue
        candidates = [s for s in targets if s.get('state') != 'ghost'
                      and _roof_overlap(source['rect'], s['rect']) > 0]
        if extension.get('kind') == 'awning':
            # The read awning hangs on this section's front edge. A carrier
            # must cover its complete span on that same edge.
            candidates = [s for s in candidates if abs(s['rect'][1] - source['rect'][1]) <= 1
                          and s['rect'][0] <= extension['x0'] and s['rect'][2] >= extension['x1']]
        if candidates:
            target = max(candidates, key=lambda s: _roof_overlap(source['rect'], s['rect']))
            extension['section'] = target['id']
        else:
            extension.update(state='ghost', position=[(source['rect'][0] + source['rect'][2]) / 2,
                                                       source['rect'][1]],
                             why='This roof extension has no matching roof edge; please place it.')


def _roof_observations(raw, context):
    """Combine per-photo side reports before deriving any roof form.

    Ordinary sides are single reports. A side seen differently in multiple
    photos can carry a list; validate each report through the shipped parser.
    """
    answer = deepcopy(raw)
    if not isinstance(answer, dict) or not isinstance(answer.get('blocks'), dict):
        return twin_reads.parse('roof_observe', answer, context)
    conflicts = []
    for bid, block in answer.get('blocks', {}).items():
        if not isinstance(block, dict) or not isinstance(block.get('sides'), dict):
            continue
        for side, reports in block.get('sides', {}).items():
            if not isinstance(reports, list):
                continue
            valid = []
            for report in reports:
                parsed, _ = twin_reads.parse('roof_observe', {
                    'blocks': {bid: {'sides': {side: report}}}}, context)
                value = parsed.get('blocks', {}).get(bid, {}).get('sides', {}).get(side)
                if value:
                    valid.append(value)
            seen = [r for r in valid if r['kind'] != 'hidden']
            if len({r['kind'] for r in seen}) > 1:
                conflicts.append((bid, side))
            block['sides'][side] = (seen or valid or [{'kind': 'hidden'}])[0]
    parsed, problems = twin_reads.parse('roof_observe', answer, context)
    if not twin_reads._usable('roof_observe', parsed, problems):
        return parsed, problems
    for bid, side in conflicts:
        parsed.setdefault('blocks', {}).setdefault(bid, {}).setdefault('sides', {})[side] = {'kind': 'conflict'}
    for block in context.get('blocks', []):
        parsed.setdefault('blocks', {}).setdefault(block['id'], {'sides': {}})
    return parsed, problems


def _roof_photo_selection(mapped, limit=8):
    """Greedily cover new block sides, with stable ties and unrelated photos last."""
    if len(mapped) <= limit:
        return list(range(len(mapped)))
    remaining, chosen, covered = set(range(len(mapped))), [], set()
    coverage = [{(b['id'], side) for b in item['fragment'].get('blocks', []) for side in b['sides']}
                if item['fragment'].get('from_side') != 'none' else set()
                for item in mapped]
    while remaining and len(chosen) < limit:
        index = min(remaining, key=lambda i: (-len(coverage[i] - covered), -len(coverage[i]), i))
        chosen.append(index)
        covered.update(coverage[index])
        remaining.remove(index)
    return sorted(chosen)


def _read_roof_blocks(build, step, reader, ticket, result):
    """Cache paid observations separately; publish only the complete derived roof."""
    context = result['context']
    draft = result['fragment'].get('building', {})
    progress = result.setdefault('roof_blocks', {'maps': []})
    result['roof_blocks_pending'] = True
    if _cache_result(build, step, ticket, result) is None:
        return None
    try:
        house = _house(_base(twin_store.current(), build), build)
        _migrate_crop_draft(house, draft, step, [], [])
        _merge_draft(build, step, result['fragment'], house)
        normalized, _ = twin_plan.normalize({'units': 'ft', 'buildings': [house]})
        house = normalized['buildings'][0]
        twin_joints.snap(house)
        _check_draft(house)
        blocks = twin_blocks.blocks(house)
        read_context = {'building': deepcopy(context['building']), 'blocks': blocks}
        photos = [image for source in build['inputs'].get('photos', [])
                  for image in twin_store.source_images(source)]
        diagram = ({'mime': 'image/png', 'b64': base64.b64encode(
            twin_blocks.block_diagram(house, blocks)).decode('ascii')} if photos else None)

        def read(kind, read_images, ctx):
            with twin_store.LIFECYCLE, _LOCK:
                if not _live(build, ticket):
                    return None
            twin_cost.require_clear()
            finished = threading.Event()
            pulse = _start_draft_heartbeat(build, step, ticket, context, finished, 'roof_observe')
            try:
                options = {'checkpoint_checked': True} if reader is _REAL_READER else {}
                raw = reader(kind, read_images, ctx, run=build['id'], step=step['id'], **options)
                if isinstance(raw, dict) and raw.get('error'):
                    raise _ReadError(raw['error'])
                fragment, problems = (_roof_observations(raw, ctx) if kind == 'roof_observe'
                                      else twin_reads.parse(kind, raw, ctx))
                if not twin_reads._usable(kind, fragment, problems):
                    raise _ReadError('No usable photo observations.')
                return {'fragment': fragment, 'problems': problems, 'reply': raw}
            finally:
                finished.set()
                pulse.join()

        observations = {}
        try:
            for photo in photos[len(progress['maps']):]:
                reply = read('photo_map', [diagram, photo], read_context)
                if reply is None:
                    return None
                progress['maps'].append(reply)
                if _cache_result(build, step, ticket, result) is None:
                    return None
            selected = [j for j in _roof_photo_selection(progress['maps'])
                        if progress['maps'][j]['fragment'].get('from_side') != 'none'
                        and progress['maps'][j]['fragment'].get('blocks')]
            if photos:
                photo_map = {i: progress['maps'][j]['fragment'] for i, j in enumerate(selected)}
                if 'observe' not in progress:
                    progress['observe'] = read('roof_observe', [diagram, *[photos[j] for j in selected]],
                                               {**read_context, 'photo_map': photo_map})
                    if progress['observe'] is None or _cache_result(build, step, ticket, result) is None:
                        return None
                observations = progress['observe']['fragment'].get('blocks', {})
        except twin_cost.CheckpointReached:
            raise
        except Exception as exc:
            progress['error'] = str(exc)
            observations = {}

        roof = deepcopy(draft.get('roof', {}))
        sections = roof.get('sections', [])

        def porch_roof(section):
            r = section['rect']
            centre = [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2]
            return any(_inside(centre, p['polygon']) and section['plate'] <= p.get('floor', 0) + 12
                       for p in twin_plan.porches(draft))

        evidence = {}
        for block in blocks:
            source = max((s for s in sections if not porch_roof(s)
                          and _roof_overlap(block['rect'], s['rect']) > 0),
                         key=lambda s: _roof_overlap(block['rect'], s['rect']), default=None)
            plan = {k: deepcopy(source[k]) for k in ('ridge', 'pitch') if k in source} if source else {}
            plan['dormers'] = deepcopy(source.get('dormers', [])) if source else []
            # Cross gables already drawn on this roof carry their plan position.
            for section in sections:
                if (source and section is not source and section.get('kind') == 'gable'
                        and not porch_roof(section)
                        and section.get('ridge') != source.get('ridge')
                        and abs(section['plate'] - source['plate']) < .5
                        # A cross gable sits on this block. A neighbouring wing
                        # touching its edge is not evidence of a dormer.
                        and _roof_overlap(block['rect'], section['rect']) >=
                            _roof_overlap(section['rect'], section['rect']) / 2
                        and _roof_overlap(block['rect'], section['rect']) < _roof_overlap(block['rect'], source['rect']) / 2):
                    r, b = section['rect'], block['rect']
                    axis = 0 if source.get('ridge') == 'x' else 1
                    side = ('front' if (r[1] + r[3]) / 2 < (b[1] + b[3]) / 2 else 'rear') if axis == 0 else (
                        'left' if (r[0] + r[2]) / 2 < (b[0] + b[2]) / 2 else 'right')
                    plan['dormers'].append({'side': side, 'centre': (r[axis] + r[axis + 2]) / 2,
                                            'width': r[axis + 2] - r[axis]})
            evidence[block['id']] = plan
        choices = deepcopy(twin_plan._roof_entries(house['roof'], 'choices'))
        protected = [s for s in house['roof']['sections'] if s.get('src', {}).get('person')]
        legacy_coverage = []
        for section in protected:
            block_rect = section.get('block')
            if (section.get('dormer_of') or (block_rect and
                    max(abs(a - b) for a, b in zip(section['rect'], block_rect)) > 1)):
                continue
            if not block_rect and not section.get('read_geometry'):
                continue  # Only a legacy read section can migrate to a choice.
            rect = block_rect or section.get('read_geometry', {}).get('rect') or section['rect']
            block = next((b for b in blocks if max(abs(a - v) for a, v in zip(rect, b['rect'])) <= 1), None)
            if block is None and not block_rect:
                covered = [b for b in blocks if _roof_overlap(section['rect'], b['rect']) >=
                           _roof_overlap(b['rect'], b['rect']) / 2]
                block = max(covered, key=lambda b: (_roof_overlap(section['rect'], b['rect']), b['id']), default=None)
                if block:
                    legacy_coverage.extend(b['rect'] for b in covered)
                    place = twin_roof_derive._place(block, blocks)[4:-5]
                    line = f'Kept your earlier roof over the {place}; please check it.'
                    progress.setdefault('legacy_lines', [])
                    if line not in progress['legacy_lines']:
                        progress['legacy_lines'].append(line)
            if block is None or any(max(abs(a - v) for a, v in zip(c['rect'], block['rect'])) <= 1
                                    for c in choices):
                continue
            choices.append({**{k: deepcopy(section[k]) for k in
                              ('kind', 'ridge', 'ends', 'pitch', 'plate', 'overhang', 'low_side') if k in section},
                            'rect': deepcopy(block['rect']), 'src': {'person': True}})
        derived, flags = twin_roof_derive.derive_roof(blocks, observations, evidence, choices)

        protected_sources = [s for s in sections if any(
            _near_geometry({'rect': s['rect']}, p.get('read_geometry') or {'rect': p['rect']}, 'roof')
            for p in protected)]
        # Invalid read pieces remain visible as diagnostic ghosts. They must
        # not supply a footprint for new, apparently settled roofs.
        failed_sources = [s for s in sections if any(
            p.get('state') == 'ghost' and _near_geometry(
                {'rect': s['rect']}, p.get('read_geometry') or {'rect': p['rect']}, 'roof')
            for p in house['roof']['sections'])]
        for source in failed_sources:
            source.update(state='ghost', why='This roof section does not meet its bearing walls within 3 ft.')
        kept = [s for s in sections if s.get('src', {}).get('person') or s in protected_sources
                or s in failed_sources or porch_roof(s)]
        # Use the person's carrier, including its level and form. Keeping the
        # raw draft carrier here can create a second roof beside a block roof
        # whose level was assigned during derivation.
        kept = [deepcopy(next(p for p in protected if _near_geometry(
                    {'rect': s['rect']}, p.get('read_geometry') or {'rect': p['rect']}, 'roof')))
                if s in protected_sources else s for s in kept]
        carriers = derived[:len(blocks)]
        legacy_ids = {s['id']: old['id'] for s in carriers for old in protected_sources
                      if _near_geometry({'rect': s['rect']}, {'rect': old['rect']}, 'roof')}
        dropped_blocks = [s['rect'] for s in carriers if s['id'] in legacy_ids or s['rect'] in legacy_coverage]
        derived = [s for s in derived if s['rect'] not in dropped_blocks
                   and s.get('dormer_of') not in dropped_blocks]
        roof['sections'] = kept + derived
        _remap_roof_attachments(draft.get('openings', []), roof.get('extensions', []),
                               sections, roof['sections'])
        draft['roof'] = roof
        rects = {b['id']: b['rect'] for b in blocks}
        progress['flags'] = [{**f, 'block_rect': deepcopy(rects[f['block']])} for f in flags]
        roof['choices'] = choices
        roof['flags'] = deepcopy(progress['flags'])
    except twin_cost.CheckpointReached:
        raise
    except Exception as exc:
        # Derivation is advisory too: retain the unmodified draft on an internal failure.
        progress['derive_error'] = str(exc)
    progress['issues'] = _draft_roof_issues(draft)
    result.pop('roof_blocks_pending', None)
    result.pop('roof_check_pending', None)
    return _cache_result(build, step, ticket, result)


def _obtain(build, step, reader, ticket):
    path = _cache_path(build, step)
    progress = None
    if path.is_file():
        result = json.loads(path.read_text(encoding='utf-8'))
        if result.get('roof_blocks_pending') or result.get('roof_check_pending'):
            return _read_roof_blocks(build, step, reader, ticket, result)
        if result.get('fallback_pending'):
            progress = result
        elif not result.get('error'):
            return result
        else:
            # Older builds may have cached an unsuccessful reply. Resume retries it.
            path.unlink()
    if step['kind'] == 'plot' and build.get('plot_read') and not step.get('reread'):
        stored = build['plot_read']
        result = {'fragment': deepcopy(stored['fragment']), 'crop': deepcopy(stored['crop']),
                  'plot_read': deepcopy(stored), 'problems': []}
    elif step['kind'] == 'shell':
        shell = deepcopy(build['inputs']['shell'])
        for piece in [*shell['walls'], *shell['openings'], *shell['roof']['sections']]:
            piece['src']['step'] = step['id']
        result = {'fragment': shell, 'problems': []}
    elif step['kind'] in ('compose', 'lot'):
        result = {'fragment': {}, 'problems': []}
    elif step['kind'] == 'fit':
        result = {'fragment': _building_fit(build), 'problems': []}
    else:
        sheets = []
        images, context, crop = _images_context(build, step, sheets)
        if step['kind'] == 'draft':
            with twin_store.LIFECYCLE, _LOCK:
                photos = sum(twin_store.source_image_count(source) for source in build['inputs'].get('photos', []))
                step['estimate'] = (twin_cost.estimate('draft', len(images)) + twin_cost.estimate('outline', 1)
                                    + photos * twin_cost.estimate('photo_map', 2)
                                    + (twin_cost.estimate('roof_observe', 1 + min(8, photos)) if photos else 0))
                _save(build)
        if progress is not None:
            raw = progress['whole_draft']['reply']
            context, sheets = progress['context'], progress['sheets']
        else:
            twin_cost.require_clear()
            if step['kind'] == 'draft':
                raw = _read_draft(build, step, reader, ticket, images, context, sheets)
            elif step['kind'] == 'draft_rooms':
                finished = threading.Event()
                pulse = _start_draft_heartbeat(build, step, ticket, context, finished, '')
                try:
                    raw = reader(step['kind'], images, context, run=build['id'], step=step['id'])
                finally:
                    finished.set()
                    pulse.join()
            else:
                raw = reader(step['kind'], images, context, run=build['id'], step=step['id'])
        truncated = step['kind'] == 'draft' and isinstance(raw, dict) and raw.get('truncated')
        if isinstance(raw, dict) and raw.get('error') and not truncated:
            raise _ReadError(raw['error'])
        fragment, problems = twin_reads.parse(step['kind'], raw) if not truncated else ({}, [])
        if isinstance(raw, dict) and not truncated:
            problems = list(raw.get('problems') or []) + problems
        fallback = step['kind'] == 'draft' and (progress is not None or truncated
            or not fragment.get('building', {}).get('levels') or _draft_preview(build, step, fragment)[1])
        if fallback:
            original = (progress['whole_draft'] if progress is not None else
                        {'fragment': fragment, 'problems': problems, 'reply': raw})
            if progress is None:
                progress = {'fallback_pending': True, 'whole_draft': original, 'level_reads': [],
                            'context': context, 'sheets': sheets, 'fragment': {}, 'problems': []}
                if _cache_result(build, step, ticket, progress) is None:
                    return None
            outcome = _read_draft_levels(build, step, reader, ticket, images, context, progress)
            if outcome is None:
                return None
            fragment, problems, reads, failed = outcome
        result = {'fragment': fragment, 'problems': problems, 'crop': crop,
                  'error': raw.get('error') if isinstance(raw, dict) and not fallback else None}
        if fallback:
            result.update(whole_draft=original, level_reads=reads, fallback_failed=failed)
        if step['kind'] in ('draft', 'draft_rooms'):
            result['context'] = context
        if step['kind'] == 'draft':
            result['sheets'] = sheets
            if fragment.get('building', {}).get('levels') and not result.get('fallback_failed'):
                return _read_roof_blocks(build, step, reader, ticket, result)
        if step['kind'] == 'walls' and isinstance(raw, dict) and isinstance(raw.get('walls'), list):
            result['wall_count'] = len(raw['walls'])
    return _cache_result(build, step, ticket, result)


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
    if house.get('position_from') == 'person':
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
        elif step['kind'] == 'registration':
            below = f"L{int(step['level'][1:]) - 1}"
            moving = [_map(result['crop'], pause['registration'], p) for p in fragment['lower_outline']]
            if _shape_mismatch(moving, _outline(plan, build, below)):
                pause['why'] = (pause['why'] + ' The floor outlines do not match in size. Check that both trace enclosed walls without open porches or decks.').strip()
    elif step['kind'] == 'roof':
        reg, rms, _ = _roof_registration(build, result, plan)
        pause.update(kind='level_registration', registration=reg, rms=rms,
                     why='The roof and floor outlines do not match in size. Check that both trace enclosed walls without open porches or decks.')
    elif step['kind'] == 'fit':
        pause.update(registration=twin_register.make(1), transform=deepcopy(fragment['transform']))
    else:
        if is_lot:
            _check_lot_page(step)
            from services import twin_place_reads
            page = {k: step[k] for k in ('source', 'page', 'box')}
            reg = (result['plot_read']['registration'] if result.get('plot_read') else
                   twin_place_reads.plot_read_record(page, result['crop'], fragment)['registration'])
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
        key = 'outline' if step['level'] or step['kind'] == 'roof' else 'lot'
        _ghost(build, step, {'id': step['level'] or step['id'], key:
                             [_map(result['crop'], reg, p) for p in fragment[key]]}, pause['why'])
    _event(build, 'pause', **pause)


def _expand(build, step, result):
    if step.get('expanded'):
        return
    parent = result['crop']['box']
    wings = [{'name': 'main', 'box': _FULL}] + [
        w for w in (result['fragment'].get('wings') or []) if w['name'] != 'main']
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
    def from_step(piece):
        source = piece.get('src', {}).get('step')
        return source == step['id'] or (kind == 'draft' and source == 'roof_blocks')

    roof_blocks = result.get('roof_blocks', {})
    if kind == 'draft':
        step['roof_flags'] = deepcopy(roof_blocks.get('flags', []))
        if not roof_blocks.get('logged'):
            if 'error' in roof_blocks:
                _event(build, 'log', step=step['id'], text=
                       'The roofs could not be checked against the photos; they follow the drawings.')
            if 'derive_error' in roof_blocks:
                _event(build, 'log', step=step['id'], text=
                       'The roofs could not be built from the walls; they are shown as first read.')
            for text in dict.fromkeys(f['text'] for f in step['roof_flags']):
                _event(build, 'log', step=step['id'], text=text)
            for text in roof_blocks.get('legacy_lines', []):
                _event(build, 'log', step=step['id'], text=text)
            roof_blocks['logged'] = True
            _atomic(_cache_path(build, step), result)
    if kind == 'draft' and roof_blocks.get('issues') and not roof_blocks.get('issues_logged'):
        sections = {s['id']: s for s in fragment.get('building', {}).get('roof', {}).get('sections', [])}
        logged = set()
        for issue in roof_blocks['issues']:
            section = sections.get(issue.get('section'))
            area = 'the upper floor'
            text = issue['text']
            if issue.get('section'):
                text = text.replace(f"Section {issue['section']}", 'This section')
            if section:
                x0, y0, x1, y1 = section['rect']
                area = f'x {x0:g} to {x1:g} ft, y {y0:g} to {y1:g} ft'
            if not text.startswith(("The upper floor's wall", 'The roof over ')):
                text = f'The roof over {area} still needs checking: {text}'
            if text not in logged:
                _event(build, 'log', step=step['id'], text=text)
                logged.add(text)
        roof_blocks['issues_logged'] = True
        _atomic(_cache_path(build, step), result)
    if kind == 'draft' and not fragment.get('building', {}).get('levels'):
        _pause_draft(build, step)
        return
    notes, settled, ghosts = [], [], []
    decision = decision or {}
    is_lot = build['inputs'].get('part') == 'lot'
    lot_state = None
    lot_outline = None
    draft_tombstones = None
    if is_lot and kind in ('lot', 'plot', 'site'):
        _check_lot_page(step)
    if is_lot and kind == 'lot':
        lot_outline = build['placement']['outline']
    elif is_lot and kind == 'plot':
        from services import twin_place_reads
        reg = build['pause']['registration']
        page = {k: deepcopy(step[k]) for k in ('source', 'page', 'box')}
        lot_state = deepcopy(twin_store.place()['lot'])
        if result.get('plot_read'):
            record = lot_state.get('read')
            if (not record or record['id'] != result['plot_read']['id']
                    or record['registration'] != reg):
                raise ValueError('This plot plan read is out of date. Read it again.')
        else:
            record = twin_place_reads.plot_read_record(
                page, crop, fragment, registration=reg,
                cost=math.fsum(e['usd'] for e in twin_cost.entries()
                               if e.get('run') == build['id'] and e.get('stage') == 'step:plot'))
        lot_outline = record['lot']
        lot_state['placement'] = {**page, 'outline': lot_outline, 'street_edge': record['street_edge'],
                                  'registration': reg, 'confirmed': True}
        lot_state['read'] = record

    def mutate(current):
        nonlocal draft_tombstones
        if kind == 'draft':
            draft_tombstones = twin_store.tombstones()
        plan = _base(current, build, lot_outline)
        house = _house(plan, build)
        level = next((l for l in (house or {}).get('levels', []) if l['id'] == step['level']), None)
        reg = twin_store.registration(step['source'], step['page'], step['level']) if crop else None
        if kind in ('draft', 'draft_rooms'):
            if kind == 'draft':
                _migrate_crop_draft(house, fragment.get('building', {}), step, draft_tombstones, notes)
            _merge_draft(build, step, fragment, house, tombstones=draft_tombstones, notes=notes)
        elif kind == 'shell':
            shell = deepcopy(fragment)
            generated_levels = {w['level'] for w in house['walls']
                                if w.get('src', {}).get('step') == step['id']}
            if house.get('position_from') != 'person':
                house.update(position=[0, 0], rotation=0)
            for incoming_level in shell['levels']:
                old_level = next(l for l in house['levels'] if l['id'] == incoming_level['id'])
                if not old_level.get('src', {}).get('person'):
                    old_level.update(incoming_level)
                    old_level['src'] = {'sheet': '', 'page': 1, 'step': step['id']}
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
            incoming_ids = {l['id'] for l in shell['levels']}
            # A Room the model derived from the generated walls is not content
            # of its own: it neither keeps a level nor outlives it.
            occupied = {p.get('level') for key in ('walls', 'rooms', 'stairs', 'fixtures', 'lights')
                        for p in house.get(key, []) if not twin_model.derived_room(p)}
            house['levels'] = [l for l in house['levels'] if l['id'] in incoming_ids
                               or l.get('src', {}).get('person') or l['id'] in occupied
                               or (l.get('src', {}).get('step') != step['id'] and l['id'] not in generated_levels)]
            kept_levels = {l['id'] for l in house['levels']}
            house['rooms'] = [r for r in house.get('rooms', [])
                              if r.get('level') in kept_levels or not twin_model.derived_room(r)]
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
            reg, rms, _ = _roof_registration(build, result, plan)
            if (build.get('pause') or {}).get('step') == step['id']:
                reg = decision.get('registration', build['pause']['registration'])
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
                if house.get('position_from') != 'person':
                    house.update(deepcopy(transform))
                    if 'transform' in decision:
                        house['position_from'] = 'person'
                notes.append(f"Placed {house.get('name', house['id'])} on the lot, turned {house['rotation']:g}\N{DEGREE SIGN}")
        elif kind == 'fit':
            if house.get('position_from') != 'person':
                house.update(deepcopy(decision.get('transform', fragment['transform'])))
                if 'transform' in decision:
                    house['position_from'] = 'person'
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
                allowed = {v['asset'] for v in kit['materials'].values()}
                for role, value in fragment.get('materials', {}).items():
                    problems = []
                    validated = twin_draft._materials({'materials': {role: value}}, kit, problems)
                    if role not in kit['materials']:
                        notes.append('A finish outside the kit was left out.')
                    elif not problems or value.get('id') not in allowed:
                        materials[role] = validated[role]
                        if problems:
                            notes.append(f"Used the kit default for the {role.replace('_', ' ')} finish.")
                    else:
                        notes.append(f"The {role.replace('_', ' ')} finish had an invalid colour and was left out.")
                target_materials = house.setdefault('materials', {})
            else:
                problems = []
                materials = twin_draft._materials({'materials': fragment.get('materials', {})}, kit, problems)
                if problems:
                    notes.append('Some finishes used the kit defaults.')
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
        generated = [p for pieces in collections for p in pieces if from_step(p)]
        for piece in generated:
            if 'confidence' in fragment:
                if not piece.get('src', {}).get('person'):
                    piece['confidence'] = fragment['confidence']
            if kind not in ('draft', 'draft_rooms') and not piece.get('src', {}).get('person'):
                ghosts.append(piece)
        normalized, problems = twin_plan.normalize(plan)
        if problems:
            logger.warning('%s: some pieces need checking against the drawing.', step['label'])
        target = _house(normalized, build)
        if target is not None:
            notes.extend(twin_joints.snap(target))
            if kind == 'draft':
                if _check_draft(target) or result.get('fallback_failed'):
                    _pause_draft(build, step)
            elif kind == 'draft_rooms':
                _check_draft_rooms(target, step)
            # fit/compose publish placement and landscaping, rather than reads
            # of this building. Check its joints with its last settled read.
            reads = [s for s in build['steps'] if s['kind'] not in
                     ('fit', 'compose', 'plot', 'site', 'lot')]
            if reads and step is reads[-1]:
                notes.extend(twin_joints.report(target))
        target_collections = [target['walls'], target['openings'], target['rooms'], target['roof']['sections']] if target else []
        if kind in ('draft', 'draft_rooms'):
            extra = target['levels'] + target['roof'].get('extensions', []) + target.get('stairs', [])
            extra.extend(twin_plan.porches(target))
            ghosts.extend(p for p in [*extra, *(p for c in target_collections for p in c)]
                          if from_step(p) and p.get('state') == 'ghost')
            settled.extend(p for p in extra if p.get('src', {}).get('step') == step['id']
                           and p.get('state') != 'ghost')
        if kind == 'walls' and result.get('wall_count', len(incoming)):
            settled_ids = {w['id'] for w in target['walls'] if w.get('state') != 'ghost'}
            if sum(w['id'] in settled_ids for w in incoming) < result.get('wall_count', len(incoming)) / 2:
                _event(build, 'question', step=step['id'], text='Fewer than half of these walls could settle. Please check the walls.')
        for collection in target_collections:
            settled.extend(p for p in collection if from_step(p) and p.get('state') != 'ghost')
        checked = list(zip(collections, target_collections,
                           ('wall', 'opening', 'room', 'roof section'),
                           ('walls', 'openings', 'rooms', 'roof sections')))
        for name, singular, plural in (
                ('hardscape', 'paved area', 'paved areas'), ('edges', 'yard edge', 'yard edges'),
                ('beds', 'planting bed', 'planting beds'), ('planting', 'plant', 'plants'),
                ('furniture', 'furnishing', 'furnishings'), ('terraces', 'terrace', 'terraces')):
            checked.append((plan['site'].get(name, []), normalized['site'][name], singular, plural))
        for name, noun in (('pool', 'pool'), ('fire_pit', 'fire pit')):
            before, after = plan['site'].get(name), normalized['site'].get(name)
            checked.append(([before] if before else [], [after] if after else [], noun, noun + 's'))
        dropped = set()
        summaries = []
        for pieces, kept_pieces, singular, plural in checked:
            kept_ids = {p.get('id') for p in kept_pieces}
            missing = [p for p in pieces if p.get('id') not in kept_ids]
            if not missing:
                continue
            dropped.update(p.get('id') for p in missing)
            count = len(missing)
            verb = 'was' if count == 1 else 'were'
            noun = singular if count == 1 else plural
            if singular == 'opening' and all(
                    twin_plan._opening_error(p, {w['id']: w for w in house['walls']}, {}) == 'outside the wall span'
                    for p in missing):
                reason = 'outside its wall' if count == 1 else 'outside their walls'
            else:
                reason = 'invalid after checking the drawing'
            summaries.append(f'{count} {noun} {verb} {reason} and {verb} left out')
        if dropped:
            notes.append('; '.join(summaries) + '.')
            ghosts[:] = [p for p in ghosts if p['id'] not in dropped]
        elif problems:
            notes.append('Some pieces need checking against the drawing.')
        if kind in ('outline', 'registration'):
            settled.append(next(l for l in target['levels'] if l['id'] == step['level']))
        for name in ('hardscape', 'edges', 'planting', 'beds', 'furniture'):
            settled.extend(p for p in normalized['site'][name] if p.get('src', {}).get('step') == step['id'])
        settled.extend(p for name in ('pool', 'fire_pit') if isinstance((p := normalized['site'].get(name)), dict)
                       and p.get('src', {}).get('step') == step['id'])
        return normalized

    def publish_state(row):
        if draft_tombstones is not None:
            row['tombstones'] = deepcopy(draft_tombstones)
        if lot_state is not None:
            row['place']['lot'] = deepcopy(lot_state)
            twin_store._set_registration(row, step['source'], step['page'], None, build['pause']['registration'])

    twin_store.update_current(mutate, kind='build', step={'id': step['id'], 'label': step['label']},
                              generation=build['generation'], cost=build['cost'],
                              state_mutator=publish_state)
    if kind == 'draft':
        _register_draft(result)
    if kind in ('outline', 'registration', 'plot') and not is_lot:
        reg = decision.get('registration', build['pause']['registration']) if kind != 'plot' else build['pause']['registration']
        if 'registration' in decision:
            reg = {**reg, 'source': 'person'}
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
        if step['kind'] == 'draft':
            raise ValueError('The drawings could not be read as one building. Try again.')
        if 'registration' in decision:
            if step['kind'] not in ('outline', 'registration', 'roof'):
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
            logger.exception('%s could not be accepted.', step['label'])
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
        if step['kind'] == 'draft':
            # Rooms use this exact settled geometry, and placement uses its
            # outline. A new draft invalidates their cached answers too.
            for dependent in build['steps'][build['steps'].index(step) + 1:]:
                dependent.update(status='pending', reread=True)
                _cache_path(build, dependent).unlink(missing_ok=True)
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
    successor = next_ticket = None
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
                    logger.warning('%s: some parts of this drawing need checking.', step['label'])
                    _event(build, 'log', step=step['id'], text='Some parts of this drawing need checking.')
                if result.get('error'):
                    raise ValueError(result['error'])
                if step['kind'] == 'roof' and _roof_registration(build, result, _base(twin_store.current(), build))[2]:
                    _pause(build, step, result)
                    _save(build)
                    _idle(build, ticket)
                    return
                if step['pause'] and (step['kind'] != 'fit' or result['fragment'].get('why')):
                    _pause(build, step, result)
                    _save(build)
                    _idle(build, ticket)
                    return
                _settle(build, step, result)
                if build['state'] == 'paused':
                    _save(build)
                    _idle(build, ticket)
                    return
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
                logger.exception('%s could not finish.', step['label'])
                _event(build, 'question' if retryable else 'error', step=step['id'],
                       text=('The drawings could not be read.' if step['kind'] == 'draft' else
                             'This drawing could not be read. Check the page and try reading it again.'))
                if cached and step['pause'] and isinstance(result, dict) and not result.get('error'):
                    try:
                        _pause(build, step, result)
                    except Exception:
                        pass
                _save(build)
                _idle(build, ticket)
            elif (_BUILDS.get(build['id']) is build and build['state'] == 'done'
                  and _WORKERS.get(build['id'], {}).get('ticket') == ticket
                  and build['generation'] == twin_store.generation()):
                _chain_failed(build)
                if successor is not None and next_ticket is not None:
                    _idle(successor, next_ticket)
                    successor['state'] = 'stopped'
                    _save(successor)
    finally:
        with twin_store.LIFECYCLE, _LOCK:
            _idle(build, ticket)


twin_store.build_running = running
twin_store.stop_builds_for_start_over = stop_for_start_over
