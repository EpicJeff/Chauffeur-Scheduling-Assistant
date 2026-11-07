"""Restartable, piece-by-piece house builds from cropped drawing reads.

The lifecycle lock covers publication, never a reader call. Every publication
checks both the house generation and the worker ticket, including cache writes.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import quote
import uuid

from services import (twin_compose, twin_cost, twin_draft, twin_library,
                      twin_plan, twin_reads, twin_register, twin_store)

_LOCK = threading.RLock()
_BUILDS = {}
_WORKERS = {}
_ACTIVE = ('running', 'paused', 'checkpoint')
_FULL = [0, 0, 1, 1]


def _step(kind, row=None, level=None, pause=None, name=None):
    row = row or {}
    sid = f'{kind}:{level}' if level else kind
    return {'id': sid, 'kind': kind, 'label': name or kind.replace('_', ' ').capitalize(),
            'pause': pause, 'source': row.get('source'), 'page': row.get('page'),
            'level': level, 'box': deepcopy(row.get('box')), 'status': 'pending',
            'level_name': row.get('level') or level}


def plan_steps(page_roles, photos, plot):
    """Static skeleton; wing steps are inserted only after an accepted read."""
    steps = []
    if not page_roles:
        return [_step('sheet_roles')]
    floors = [r for r in page_roles if r['role'] == 'floor']
    for index, row in enumerate(floors):
        level = f'L{index + 1}'
        kind, pause = ('outline', 'scale_outline') if index == 0 else ('registration', 'level_registration')
        steps.append(_step(kind, row, level, pause, f"{row.get('level') or level} outline"))
        steps.extend(_step(k, row, level, name=f"{row.get('level') or level} {k}")
                     for k in ('openings', 'rooms'))
    roof = next((r for r in page_roles if r['role'] == 'roof'), None)
    if roof:
        steps.append(_step('roof', roof))
        if photos:
            steps.append(_step('pitch'))
    if plot:
        steps.extend((_step('plot', plot[0], pause='lot_placement'), _step('site', plot[0])))
    if photos:
        steps.append(_step('finishes'))
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
        raise twin_store.StaleGeneration('The house was started over.')
    return build


def _save(build):
    if build['generation'] != twin_store.generation():
        raise twin_store.StaleGeneration('The house was started over.')
    _atomic(_root(build['id']) / 'state.json', build)


def _event(build, kind, **fields):
    build['seq'] += 1
    build['events'].append({'seq': build['seq'], 'type': kind, **deepcopy(fields)})


def _live(build, ticket):
    return (_BUILDS.get(build['id']) is build and build['state'] == 'running'
            and _WORKERS.get(build['id'], {}).get('ticket') == ticket
            and build['generation'] == twin_store.generation())


def running():
    with _LOCK:
        return any(b['state'] in _ACTIVE for b in _BUILDS.values())


def status(build_id, since=0):
    with twin_store.LIFECYCLE, _LOCK:
        build = deepcopy(_get(build_id))
    return {key: ([e for e in build[key] if e['seq'] > since] if key == 'events' else build[key])
            for key in ('id', 'state', 'steps', 'events', 'seq', 'pause', 'cost')}


def _launch(build, reader, inline):
    ticket = uuid.uuid4().hex
    _WORKERS[build['id']] = {'reader': reader, 'inline': inline, 'ticket': ticket}
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
        if running():
            raise ValueError('A build is already running.')
        building = deepcopy(inputs['building'])
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', building['id']):
            raise ValueError('A building needs a valid id.')
        roles = [r for r in twin_store.page_roles() if r.get('building', 'house') == building['id']]
        plot = [r for r in twin_store.page_roles() if r['role'] == 'plot']
        bid = uuid.uuid4().hex
        current = twin_store.current()
        build = {'id': bid, 'inputs': deepcopy(inputs), 'generation': twin_store.generation(),
                 'state': 'running', 'steps': plan_steps(roles, inputs.get('photos', []), plot),
                 'events': [], 'seq': 0, 'pause': None, 'cost': 0,
                 'existing': bool(current and any(b['id'] == building['id'] for b in current['buildings']))}
        _BUILDS[bid] = build
        ticket = _launch(build, reader, inline)
    _dispatch(build, ticket, reader, inline)
    return bid


def stop(build_id):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        if build_id in _WORKERS:
            _WORKERS[build_id]['ticket'] = None
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
        reader = reader or runtime.get('reader') or twin_reads.read
        inline = runtime.get('inline', False) if inline is None else inline
        ticket = _launch(build, reader, inline)
    _dispatch(build, ticket, reader, inline)
    return status(build_id)


def recover():
    with twin_store.LIFECYCLE, _LOCK:
        for path in (Path(twin_store.DATA_DIR) / 'builds').glob('*/state.json'):
            build = _get(path.parent.name)
            if build['state'] == 'running':
                build['state'] = 'stopped'
                _save(build)


def _forget():
    """Test seam: forget process-local readers, tickets and state."""
    with twin_store.LIFECYCLE, _LOCK:
        _BUILDS.clear()
        _WORKERS.clear()


def _cache_path(build, step):
    return _root(build['id']) / 'steps' / (quote(step['id'], safe='') + '.json')


def _house(plan, build):
    return next(b for b in plan['buildings'] if b['id'] == build['inputs']['building']['id'])


def _base(plan, build):
    plan = deepcopy(plan) if plan else {'units': 'ft', 'buildings': [], 'site': {}, 'materials': {}}
    bid = build['inputs']['building']['id']
    levels = [{'id': s['level'], 'name': s['level_name'], 'elevation': i * 9, 'ceiling': 9}
              for i, s in enumerate(s for s in build['steps'] if s['kind'] in ('outline', 'registration'))]
    if not levels:
        raise ValueError('No floor sheets are confirmed for this building.')
    if not any(b['id'] == bid for b in plan['buildings']):
        plan['buildings'].append({**deepcopy(build['inputs']['building']), 'levels': levels,
                                  'position': [0, 0], 'rotation': 0, 'walls': [], 'openings': [],
                                  'rooms': [], 'roof': {'sections': []}})
    else:
        house = _house(plan, build)
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


def _piece(build, step, piece_kind, index, **fields):
    identity = f"{piece_kind}:{step['id']}:{index}"
    if len(identity) > 64:
        identity = f"{piece_kind}:{hashlib.sha256(identity.encode()).hexdigest()[:48]}"
    return {'id': identity, 'state': 'ghost', 'src': {'sheet': step['source'] or '',
            'page': step['page'] or 1, 'step': step['id']}, **fields}


def _geometry(piece, kind, house):
    if kind == 'opening':
        wall = next((w for w in house['walls'] if w['id'] == piece.get('wall')), None)
        if wall:
            length = math.dist(wall['from'], wall['to'])
            return {key: [wall['from'][i] + (wall['to'][i] - wall['from'][i]) / length * d for i in (0, 1)]
                    for key, d in (('from', piece['at'] - piece['width'] / 2), ('to', piece['at'] + piece['width'] / 2))}
    return {key: piece[key] for key in ('from', 'to', 'polygon', 'rect', 'position', 'at', 'points', 'polyline') if key in piece}


def _near_geometry(a, b):
    if a.keys() != b.keys() or not a:
        return False
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
               and (t['src'].get('step') == src.get('step')
                    or (t['src'].get('person') and t['src'].get('sheet') == src.get('sheet')))
               and _near_geometry(_geometry(piece, kind, house), t['geometry']) for t in twin_store.tombstones())


def _merge_list(existing, incoming, kind, house, build):
    by_id = {p['id']: p for p in existing}
    for piece in incoming:
        old = by_id.get(piece['id'])
        if old and old.get('src', {}).get('person'):
            continue
        if not _deleted(piece, kind, house, build):
            by_id[piece['id']] = deepcopy(piece)
    return list(by_id.values())


def _spend(build):
    build['cost'] = math.fsum(e['usd'] for e in twin_cost.entries() if e.get('run') == build['id'])
    _event(build, 'cost', cost=build['cost'])


def _images_context(build, step):
    context = {'building': deepcopy(build['inputs']['building']), 'level': step['level'],
               'box': deepcopy(step['box'] or _FULL)}
    plan = twin_store.current()
    if plan:
        house = _house(_base(plan, build), build)
        context['settled'] = deepcopy(house)
        context['sections'] = [s['id'] for s in house['roof']['sections']]
    if step['kind'] in ('pitch', 'finishes'):
        images = [image for source in build['inputs'].get('photos', []) for image in twin_store.source_images(source)]
        return images, context, None
    crop = twin_store.crop(step['source'], step['page'], context['box'])
    context['box'] = crop['box']
    return [{'mime': crop['mime'], 'b64': crop['b64']}], context, {k: crop[k] for k in ('box', 'size', 'master')}


def _obtain(build, step, reader, ticket):
    path = _cache_path(build, step)
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    if step['kind'] == 'sheet_roles':
        rows, all_problems = [], []
        for source in twin_store.sources():
            if source['kind'] != 'drawing':
                continue
            substep = {**step, 'id': f"sheet_roles:{source['id']}"}
            subpath = _cache_path(build, substep)
            if subpath.is_file():
                result = json.loads(subpath.read_text(encoding='utf-8'))
            else:
                twin_cost.require_clear()
                raw = reader('sheet_roles', twin_store.source_images(source['id']),
                             {'source': source['id'], 'box': _FULL}, run=build['id'], step=substep['id'])
                fragment, problems = twin_reads.parse('sheet_roles', raw)
                if isinstance(raw, dict):
                    problems = list(raw.get('problems') or []) + problems
                if isinstance(raw, dict) and raw.get('error'):
                    raise ValueError(raw['error'])
                result = {'fragment': fragment, 'problems': problems}
                with twin_store.LIFECYCLE, _LOCK:
                    if not _live(build, ticket):
                        return None
                    _atomic(subpath, result)
            rows.extend({**r, 'source': source['id'], 'building': build['inputs']['building']['id']}
                        for r in result['fragment'].get('pages', []))
            all_problems.extend(result['problems'])
        result = {'fragment': {'roles': rows}, 'problems': all_problems}
    elif step['kind'] == 'compose':
        result = {'fragment': {}, 'problems': []}
    else:
        images, context, crop = _images_context(build, step)
        twin_cost.require_clear()
        raw = reader(step['kind'], images, context, run=build['id'], step=step['id'])
        fragment, problems = twin_reads.parse(step['kind'], raw)
        if isinstance(raw, dict):
            problems = list(raw.get('problems') or []) + problems
            if raw.get('error'):
                raise ValueError(raw['error'])
        result = {'fragment': fragment, 'problems': problems, 'crop': crop}
    with twin_store.LIFECYCLE, _LOCK:
        if not _live(build, ticket):
            return None
        _atomic(path, result)
    return result


def _registration(build, step, result, plan):
    fragment, crop = result['fragment'], result['crop']
    scale = _dimension(crop, fragment['dimension'])
    pixels = [twin_store.crop_to_master(crop, p) for p in fragment['outline']]
    reg = twin_register.make(scale, origin_px=[min(p[0] for p in pixels), max(p[1] for p in pixels)])
    if step['kind'] == 'registration':
        below = f"L{int(step['level'][1:]) - 1}"
        reg, _ = _fit(reg, [_map(crop, reg, p) for p in fragment['lower_outline']], _outline(plan, build, below))
    return reg


def _plot_registration(crop, fragment):
    scale = _dimension(crop, fragment['scale'])
    a, b = (twin_store.crop_to_master(crop, fragment['lot'][i]) for i in fragment['street_edge'])
    return twin_register.from_two_points(a, b, [0, 0], [math.dist(a, b) * scale, 0])


def _pause(build, step, result):
    fragment = result['fragment']
    plan = _base(twin_store.current(), build)
    pause = {'kind': step['pause'], 'step': step['id'], 'why': fragment.get('why', ''),
             'confidence': fragment.get('confidence', 0)}
    if step['kind'] in ('outline', 'registration'):
        pause['registration'] = _registration(build, step, result, plan)
    else:
        reg = _plot_registration(result['crop'], fragment)
        house = _house(plan, build)
        transform = {'position': house['position'], 'rotation': house['rotation']}
        if not build['existing']:
            match = next((b for b in fragment.get('buildings', [])
                          if b['name'].lower() in (house['id'].lower(), house.get('name', '').lower())), None)
            if match:
                move, _ = twin_register.fit_outline(_outline(plan, build), [_map(result['crop'], reg, p) for p in match['outline']])
                transform = {'position': move['offset'], 'rotation': move['angle']}
            elif len(plan['buildings']) > 1:
                others = [twin_register.to_world(b, p) for b in plan['buildings'] if b is not house
                          for l in b['levels'] for p in l.get('outline', [])]
                if others:
                    transform = {'position': [_bounds(others)[2] + 10, 0], 'rotation': 0}
        pause.update(registration=reg, transform=transform)
    build['pause'] = pause
    build['state'] = 'paused'
    step['status'] = 'paused'
    _event(build, 'pause', **pause)


def _expand(build, step, result):
    if step.get('expanded'):
        return
    parent = result['crop']['box']
    wings = result['fragment'].get('wings') or [{'name': 'main', 'box': _FULL}]
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
        children.append(child)
    index = build['steps'].index(step)
    build['steps'][index + 1:index + 1] = children
    step['expanded'] = True


def _settle(build, step, result, decision=None):
    """Merge against the latest round while LIFECYCLE and the module lock are held."""
    fragment, crop = result['fragment'], result.get('crop')
    kind = step['kind']
    if kind == 'sheet_roles':
        rows = fragment['roles']
        if not any(r['role'] == 'floor' for r in rows):
            raise ValueError('No floor sheets were identified. Confirm the drawing roles first.')
        twin_store.set_page_roles(twin_store.page_roles() + rows)
        build['steps'].extend(plan_steps(rows, build['inputs'].get('photos', []), [r for r in rows if r['role'] == 'plot']))
        return
    notes, settled, ghosts = [], [], []

    def mutate(current):
        plan = _base(current, build)
        house = _house(plan, build)
        if step.get('reread'):
            # Replace atomically with the new pieces: removing walls in a
            # separate round would also discard a person's dependent openings.
            removed_steps = set(step.get('removed_steps', [])) | {step['id']}
            collections = [house[k] for k in ('walls', 'openings', 'rooms')]
            collections += [house['roof']['sections']]
            collections += [plan['site'][k] for k in ('hardscape', 'edges', 'planting', 'beds', 'furniture')]
            for pieces in collections:
                pieces[:] = [p for p in pieces if p.get('src', {}).get('person')
                             or p.get('src', {}).get('step') not in removed_steps]
            for name in ('pool', 'fire_pit'):
                if (plan['site'].get(name) or {}).get('src', {}).get('step') in removed_steps:
                    plan['site'][name] = None
        level = next((l for l in house['levels'] if l['id'] == step['level']), None)
        reg = twin_store.registration(step['source'], step['page'], step['level']) if crop else None
        if kind in ('outline', 'registration'):
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
            anchors.extend((w['from'], w['to']) for w in house['walls']
                           if w['level'] == step['level'] and w.get('state') != 'ghost'
                           and w.get('src', {}).get('step') != step['id'])
            pending = incoming[:]
            while pending:
                ready = [w for w in pending if all(any(_nearest(p, a, b)[0] <= 2 for a, b in anchors)
                                                    for p in (w['from'], w['to']))]
                if not ready:
                    break
                for wall in ready:
                    wall['state'] = 'settled'
                    anchors.append((wall['from'], wall['to']))
                    pending.remove(wall)
            for wall in pending:
                wall['why'] = ('; '.join(result['problems']) + '; ' if result['problems'] else '') + 'Wall ends are more than 2 ft from the outline or a settled wall.'
                ghosts.append(wall)
            house['walls'] = _merge_list(house['walls'], incoming, 'wall', house, build)
        elif kind == 'openings':
            incoming = []
            walls = [w for w in house['walls'] if w['level'] == step['level'] and w.get('state') != 'ghost']
            for i, opening in enumerate(fragment.get('openings', [])):
                if not walls:
                    notes.append('Opening stays a ghost: no settled wall on this floor.')
                    continue
                point = _map(crop, reg, opening['at'])
                distance, at, wall = min(((*_nearest(point, w['from'], w['to']), w) for w in walls), key=lambda hit: hit[0])
                incoming.append(_piece(build, step, 'opening', i, kind=opening['kind'], wall=wall['id'], at=at,
                                       width=opening['width_ft'], sill=opening['sill_ft'], head=opening['head_ft'], state='settled'))
            house['openings'] = _merge_list(house['openings'], incoming, 'opening', house, build)
        elif kind == 'rooms':
            incoming = [_piece(build, step, 'room', i, level=step['level'], name=r['name'] or f"{level['name']} room {i + 1}",
                               polygon=[_map(crop, reg, p) for p in r['polygon']], state='settled')
                        for i, r in enumerate(fragment.get('rooms', []))]
            house['rooms'] = _merge_list(house['rooms'], incoming, 'room', house, build)
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
                                       low_side=side, plate=max(l['elevation'] + l['ceiling'] for l in house['levels']),
                                       pitch=6, pitch_source='default', state='settled'))
            house['roof']['sections'] = _merge_list(house['roof']['sections'], incoming, 'roof', house, build)
        elif kind == 'pitch':
            for pitch in fragment.get('pitches', []):
                for section in house['roof']['sections']:
                    if section['id'] == pitch['section'] and not section.get('src', {}).get('person'):
                        section.update(pitch=pitch['pitch'], pitch_source='photos')
            notes.append(f"Roof: {len(house['roof']['sections'])} sections, pitches estimated from photos")
        elif kind == 'plot':
            reg = build['pause']['registration']
            plan['site']['lot'] = [_map(crop, reg, p) for p in fragment['lot']]
            transform = decision.get('transform', build['pause']['transform'])
            if not house.get('src', {}).get('person'):
                house.update(deepcopy(transform))
            notes.append(f"Placed {house.get('name', house['id'])} on the lot, turned {house['rotation']:g}\N{DEGREE SIGN}")
        elif kind == 'site':
            reg = twin_store.registration(step['source'], step['page'], None)
            site = plan['site']
            for name in ('pool', 'fire_pit'):
                if name in fragment:
                    raw = fragment[name]
                    fields = ({'polygon': [_map(crop, reg, p) for p in raw['polygon']], 'depth': raw.get('depth_ft', 5)}
                              if name == 'pool' else {'at': _map(crop, reg, raw['at']), 'radius': raw['radius_ft']})
                    piece = _piece(build, step, 'site', name, **fields, state='settled')
                    if not (site.get(name) or {}).get('src', {}).get('person') and not _deleted(piece, 'site', house, build):
                        site[name] = piece
            incoming = [_piece(build, step, 'site', i, kind=h['kind'], polygon=[_map(crop, reg, p) for p in h['polygon']], state='settled')
                        for i, h in enumerate(fragment.get('hardscape', []))]
            site['hardscape'] = _merge_list(site['hardscape'], incoming, 'site', house, build)
            incoming = [_piece(build, step, 'site', f'edge-{i}', points=[_map(crop, reg, w[p]) for p in ('from', 'to')],
                               height=w['height_ft'], state='settled') for i, w in enumerate(fragment.get('retaining_walls', []))]
            site['edges'] = _merge_list(site['edges'], incoming, 'site', house, build)
        elif kind == 'finishes':
            materials = twin_draft._materials({'materials': fragment.get('materials', {})}, twin_library.kit('modern_farmhouse'), notes)
            plan['materials'].update({k: v for k, v in materials.items()
                                      if not (isinstance(plan['materials'].get(k), dict)
                                              and plan['materials'][k].get('src', {}).get('person'))})
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
        collections = [house['walls'], house['openings'], house['rooms'], house['roof']['sections']]
        generated = [p for pieces in collections for p in pieces if p.get('src', {}).get('step') == step['id']]
        for piece in generated:
            if 'confidence' in fragment:
                piece['confidence'] = fragment['confidence']
        normalized, problems = twin_plan.normalize(plan)
        notes.extend(problems)
        target = _house(normalized, build)
        for collection in (target['walls'], target['openings'], target['rooms'], target['roof']['sections']):
            settled.extend(p for p in collection if p.get('src', {}).get('step') == step['id'] and p.get('state') != 'ghost')
        kept = {p['id'] for collection in (target['walls'], target['openings'], target['rooms'], target['roof']['sections']) for p in collection}
        for piece in generated:
            if piece['id'] not in kept:
                ghosts.append({**piece, 'state': 'ghost', 'why': '; '.join(problems) or 'The piece could not be validated.'})
        if kind in ('outline', 'registration'):
            settled.append(next(l for l in target['levels'] if l['id'] == step['level']))
        for name in ('hardscape', 'edges', 'planting', 'beds', 'furniture'):
            settled.extend(p for p in normalized['site'][name] if p.get('src', {}).get('step') == step['id'])
        settled.extend(p for name in ('pool', 'fire_pit') if isinstance((p := normalized['site'].get(name)), dict)
                       and p.get('src', {}).get('step') == step['id'])
        return normalized

    twin_store.update_current(mutate, kind='build', step={'id': step['id'], 'label': step['label']},
                              generation=build['generation'], cost=build['cost'])
    if kind in ('outline', 'registration', 'plot'):
        reg = decision.get('registration', build['pause']['registration']) if kind != 'plot' else build['pause']['registration']
        twin_store.set_registration(step['source'], step['page'], step['level'], reg)
    if kind in ('outline', 'registration'):
        _expand(build, step, result)
    step.pop('reread', None)
    step.pop('removed_steps', None)
    for note in notes:
        _event(build, 'log', step=step['id'], text=note)
    for ghost in ghosts:
        _event(build, 'ghost', step=step['id'], piece=ghost, why=ghost['why'])
        _event(build, 'log', step=step['id'], text=ghost['why'])
    _event(build, 'settled', step=step['id'], pieces=settled)


def answer(build_id, step_id, decision):
    with twin_store.LIFECYCLE, _LOCK:
        build = _get(build_id)
        if build['state'] != 'paused' or build['pause']['step'] != step_id:
            raise ValueError('This step is not waiting for an answer.')
        step = next(s for s in build['steps'] if s['id'] == step_id)
        decision = deepcopy(decision)
        if 'registration' in decision:
            if step['kind'] not in ('outline', 'registration'):
                raise ValueError('This step needs a placement decision.')
            reg = decision['registration']
            twin_register.make(reg['scale'], reg['angle'], reg['origin_px'], reg['offset'])
            if not all(math.isfinite(v) for v in [reg['angle'], *reg['origin_px'], *reg['offset']]):
                raise ValueError('Registration must be finite.')
        elif 'transform' in decision:
            transform = decision['transform']
            if (step['kind'] != 'plot' or len(transform['position']) != 2
                    or not all(type(v) in (int, float) and math.isfinite(v) for v in [*transform['position'], transform['rotation']])):
                raise ValueError('Placement needs a position and rotation.')
        elif decision.get('accept') is not True:
            raise ValueError('Accept the step or provide its registration or placement.')
        result = json.loads(_cache_path(build, step).read_text(encoding='utf-8'))
        _settle(build, step, result, decision)
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
        step['reread'] = True
        if step['kind'] in ('outline', 'registration'):
            children = [s for s in build['steps'] if s['kind'] == 'walls' and s['level'] == step['level']]
            step['removed_steps'] = [s['id'] for s in children]
            for child in children:
                _cache_path(build, child).unlink(missing_ok=True)
                build['steps'].remove(child)
            step.pop('expanded', None)
        _cache_path(build, step).unlink(missing_ok=True)
        step['status'] = 'pending'
        build['pause'] = None
        build['state'] = 'stopped'
        _save(build)
    return resume(build_id, reader=reader, inline=inline)


def _run(build, ticket, reader):
    try:
        while True:
            with twin_store.LIFECYCLE, _LOCK:
                if not _live(build, ticket):
                    return
                step = next((s for s in build['steps'] if s['status'] != 'done'), None)
                if step is None:
                    build['state'] = 'done'
                    _event(build, 'done')
                    _save(build)
                    return
                step['status'] = 'running'
                _event(build, 'stage', step=step['id'], label=step['label'])
                _save(build)
            result = _obtain(build, step, reader, ticket)
            with twin_store.LIFECYCLE, _LOCK:
                if not _live(build, ticket) or result is None:
                    return
                _spend(build)
                for problem in result['problems']:
                    _event(build, 'log', step=step['id'], text=problem)
                _event(build, 'ghost', step=step['id'], fragment=result['fragment'], why='; '.join(result['problems']))
                if step['pause']:
                    _pause(build, step, result)
                    _save(build)
                    return
                _settle(build, step, result)
                step['status'] = 'done'
                _save(build)
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
    except Exception as exc:
        with twin_store.LIFECYCLE, _LOCK:
            if _live(build, ticket):
                _spend(build)
                build['state'] = 'failed'
                _event(build, 'error', step=step['id'], text=str(exc))
                _save(build)


twin_store.build_running = running
