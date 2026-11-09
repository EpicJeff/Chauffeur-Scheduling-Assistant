"""Atomic edits to the connected house model's walls, joints and rooms."""

from copy import deepcopy
import math

from services import twin_model, twin_model_graph as graph
from services import twin_model_hosts as hosts, twin_model_roofs as roofs


_EPS = 1e-9
_CROSS = 'That would cross another wall.'
_SHORT = 'A wall must be at least 1 ft long.'
_NARROW = 'That would leave the door narrower than its wall.'


class Refused(ValueError):
    """An edit that cannot preserve the model's invariants."""


def _find(building, collection, pid):
    piece = next((p for p in building.get(collection, []) if p['id'] == pid), None)
    if piece is None:
        raise Refused(f'That {collection.rstrip("s")} is missing.')
    return piece


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise Refused('Enter a finite distance in feet.')
    return value


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise Refused('Choose a point with two coordinates in feet.')
    return [_number(v) for v in value]


def _id(building, prefix):
    used = {p['id'] for pieces in building.values() if isinstance(pieces, list)
            for p in pieces if isinstance(p, dict) and 'id' in p}
    index = 1
    while f'{prefix}:{index}' in used:
        index += 1
    return f'{prefix}:{index}'


def _positions(building, level=None):
    return {j['id']: j['at'] for j in building['joints']
            if level is None or j['level'] == level}


def _person(piece):
    piece.setdefault('src', {})['person'] = True


def _roof_offsets(building, before):
    # A wall reference alone is also an attachment. Capture its existing
    # offset before editing; never discover or replace attachments here (R23).
    for roof in building.get('roofs', []):
        area = roof['area']
        for i, edge in enumerate(roof['edges']):
            wall = before['walls'].get(edge.get('wall'))
            if wall is None or 'wall_offset' in edge:
                continue
            a, b = area[i], area[(i + 1) % len(area)]
            axis = 0 if abs(a[0] - b[0]) <= _EPS else 1
            if abs(wall['a'][axis] - wall['b'][axis]) <= _EPS:
                edge['wall_offset'] = a[axis] - wall['a'][axis]


def _joint(building, level, point, *, snap=False, exclude=()):
    candidates = [j for j in building['joints'] if j['level'] == level
                  and j['id'] not in exclude
                  and math.dist(j['at'], point) < (1 if snap else _EPS)]
    if candidates:
        return min(candidates, key=lambda j: math.dist(j['at'], point))
    if snap:
        positions = _positions(building, level)
        projections = []
        for wall in building['walls']:
            if wall['level'] != level or wall.get('state') == 'ghost':
                continue
            a, b = (positions[j] for j in wall['joints'])
            vector = graph._delta(a, b)
            length2 = sum(v * v for v in vector)
            if length2 <= _EPS:
                continue
            t = sum((point[i] - a[i]) * vector[i] for i in (0, 1)) / length2
            projected = [a[i] + t * vector[i] for i in (0, 1)]
            distance = math.dist(point, projected)
            if 0 < t < 1 and distance < 1:
                projections.append((distance, projected))
        if projections:
            point = min(projections, key=lambda row: row[0])[1]
            candidates = [j for j in building['joints'] if j['level'] == level
                          and j['id'] not in exclude and math.dist(j['at'], point) < 1]
            if candidates:
                return min(candidates, key=lambda j: math.dist(j['at'], point))
    # Keep persisted ids distinct from the graph's temporary j:N crossings.
    joint = {'id': _id(building, 'joint'), 'level': level, 'at': list(point)}
    building['joints'].append(joint)
    return joint


def _intersection(a, b, c, d):
    vector, other = graph._delta(a, b), graph._delta(c, d)
    denominator = graph._cross(vector, other)
    if abs(denominator) <= _EPS:
        return None
    between = graph._delta(a, c)
    t = graph._cross(between, other) / denominator
    u = graph._cross(between, vector) / denominator
    if _EPS < t < 1 - _EPS and _EPS < u < 1 - _EPS:
        return [a[i] + t * vector[i] for i in (0, 1)]
    return None


def _collinear_overlap(a, b, c, d):
    length = math.dist(a, b)
    if length <= _EPS:
        return None
    vector = [(b[i] - a[i]) / length for i in (0, 1)]
    if any(abs(graph._cross(vector, graph._delta(a, p))) > _EPS for p in (c, d)):
        return None
    lo, hi = sorted(sum((p[i] - a[i]) * vector[i] for i in (0, 1)) for p in (c, d))
    lo, hi = max(0, lo), min(length, hi)
    return (lo, hi) if hi - lo > _EPS else None


def _draw(building, level, start, end, kind, exterior, actor):
    ceiling = _find(building, 'levels', level)['ceiling']
    if kind not in ('solid', 'separator'):
        raise Refused('Choose a solid wall or a separator.')
    start, end = _point(start), _point(end)
    if math.dist(start, end) < 1 - _EPS:
        raise Refused(_SHORT)
    a = _joint(building, level, start, snap=True)
    b = _joint(building, level, end, snap=True, exclude=(a['id'],))
    length = math.dist(a['at'], b['at'])
    if length < 1 - _EPS:
        raise Refused(_SHORT)
    vector = [(b['at'][i] - a['at'][i]) / length for i in (0, 1)]
    uncovered = [(0, length)]
    positions = _positions(building, level)
    for wall in building['walls']:
        if wall['level'] != level or wall.get('state') == 'ghost':
            continue
        c, d = (positions[j] for j in wall['joints'])
        overlap = _collinear_overlap(a['at'], b['at'], c, d)
        if overlap is None:
            continue
        if actor == 'person':
            _person(wall)
        lo, hi = overlap
        remaining = []
        for start, end in uncovered:
            if hi <= start or lo >= end:
                remaining.append((start, end))
            else:
                if start < lo - _EPS:
                    remaining.append((start, lo))
                if end > hi + _EPS:
                    remaining.append((hi, end))
        uncovered = remaining
    added = []
    for start, end in uncovered:
        ids = [_joint(building, level, [a['at'][i] + at * vector[i] for i in (0, 1)])['id']
               for at in (start, end)]
        wall = {'id': _id(building, 'wall'), 'level': level, 'joints': ids,
                'kind': kind, 'exterior': bool(exterior), 'height': ceiling,
                'thickness': 0 if kind == 'separator' else 0.5 if exterior else 0.33}
        if actor == 'person':
            _person(wall)
        building['walls'].append(wall)
        added.append(wall)
    # Only crossings involving the drawing become stored joints. Existing
    # proper crossings remain a derived view (R20).
    positions = _positions(building, level)
    for wall in added:
        a, b = (positions[j] for j in wall['joints'])
        for other in building['walls']:
            if other is wall or other['level'] != level or other.get('state') == 'ghost':
                continue
            c, d = (positions[j] for j in other['joints'])
            point = _intersection(a, b, c, d)
            if point is not None:
                _joint(building, level, point)


def _split_drawing(building, actor):
    for level in building['levels']:
        lid = level['id']
        walls = [w for w in building['walls'] if w['level'] == lid and w.get('state') != 'ghost']
        _, split = graph.split_crossings(_positions(building, lid), walls, proper=False)
        source = None
        originals = {w['id']: w for w in walls}
        for part in split:
            if part['id'] in originals:
                source = originals[part['id']]
            if actor == 'person' and part['joints'] != source['joints']:
                _person(part)
        building['walls'] = [w for w in building['walls'] if w not in walls] + split


def _validate_move(building, before):
    current = hosts.snapshot(building)['walls']
    for wid, wall in current.items():
        old = before['walls'].get(wid)
        if wall == old:
            continue
        length = math.dist(wall['a'], wall['b'])
        if length < 1 - _EPS:
            raise Refused(_SHORT)
        if old and length < math.dist(old['a'], old['b']) - _EPS:
            widths = [p.get('width', 0) for name in ('openings', 'anchors', 'items')
                      for p in building.get(name, [])
                      if (p if name == 'openings' else p.get('host', {})).get('wall') == wid]
            if widths and length < max(widths) + 2 * hosts.MIN_CLEAR - _EPS:
                raise Refused(_NARROW)
    # snapshot omits zero-length walls; those must also be refused.
    for wall in building['walls']:
        if (wall.get('state') != 'ghost' and wall['id'] in before['walls']
                and wall['id'] not in current):
            raise Refused(_SHORT)
    lines = list(current.items())
    for i, (wid, wall) in enumerate(lines):
        for oid, other in lines[:i]:
            if wall['level'] != other['level']:
                continue
            crosses = _intersection(wall['a'], wall['b'], other['a'], other['b'])
            overlaps = _collinear_overlap(wall['a'], wall['b'], other['a'], other['b'])
            if crosses is None and overlaps is None:
                continue
            old, prior = before['walls'].get(wid), before['walls'].get(oid)
            if not old or not prior or (
                    _intersection(old['a'], old['b'], prior['a'], prior['b']) is None
                    and _collinear_overlap(old['a'], old['b'], prior['a'], prior['b']) is None):
                raise Refused(_CROSS)


def _weld_move(building, moved):
    replacements = {}
    for joint in building['joints']:
        if joint['id'] not in moved:
            continue
        # A short incident wall must be refused, never collapsed by welding.
        neighbours = {jid for wall in building['walls'] if joint['id'] in wall['joints']
                      for jid in wall['joints']}
        targets = [j for j in building['joints'] if j['level'] == joint['level']
                   and j['id'] not in moved and j['id'] not in neighbours
                   and math.dist(j['at'], joint['at']) < 1]
        if targets:
            target = min(targets, key=lambda j: math.dist(j['at'], joint['at']))
            replacements[joint['id']] = target['id']
    if replacements:
        for name in ('walls', 'rooms'):
            for piece in building[name]:
                piece['joints'] = [replacements.get(j, j) for j in piece['joints']]
        building['joints'] = [j for j in building['joints'] if j['id'] not in replacements]


def _move(building, op, before):
    kind = op['op']
    if kind == 'move_joint':
        joint = _find(building, 'joints', op.get('joint'))
        destinations = {joint['id']: _point(op.get('to'))}
    else:
        if kind == 'move_wall':
            wall = _find(building, 'walls', op.get('wall'))
            ids = wall['joints']
            positions = _positions(building)
            a, b = (positions[j] for j in ids)
            length = math.dist(a, b)
            if length < 1 - _EPS:
                raise Refused(_SHORT)
            by = _number(op.get('by'))
            delta = [-(b[1] - a[1]) * by / length, (b[0] - a[0]) * by / length]
        else:
            room = _find(building, 'rooms', op.get('room'))
            ids = room['joints']
            delta = _point(op.get('by'))
            positions = _positions(building)
            if any(j not in positions for j in ids):
                raise Refused('Split the crossing walls before moving this room.')
        destinations = {j: [positions[j][i] + delta[i] for i in (0, 1)] for j in ids}
    for joint in building['joints']:
        if joint['id'] in destinations:
            joint['at'] = destinations[joint['id']]
    _weld_move(building, destinations)
    _validate_move(building, before)


def _forget_merged_rooms(building):
    removed = set()
    for level in building['levels']:
        lid = level['id']
        walls = [w for w in building['walls'] if w['level'] == lid and w.get('state') != 'ghost']
        joints, split = graph.split_crossings(_positions(building, lid), walls)
        for region in graph.regions(joints, split):
            contained = [r for r in building['rooms'] if r['level'] == lid
                         and twin_model._overlap(r['polygon'], region['polygon'])
                         >= twin_model._area(r['polygon']) - _EPS]
            if len(contained) > 1:
                keep = max(contained, key=lambda r: twin_model._area(r['polygon']))
                removed.update(r['id'] for r in contained if r is not keep)
    building['rooms'] = [r for r in building['rooms'] if r['id'] not in removed]


def _delete(building, pid):
    wall = next((w for w in building['walls'] if w['id'] == pid), None)
    if wall is not None:
        building['walls'].remove(wall)
        _forget_merged_rooms(building)
        return
    joint = next((j for j in building['joints'] if j['id'] == pid), None)
    if joint is not None:
        building['walls'] = [w for w in building['walls'] if pid not in w['joints']]
        building['joints'].remove(joint)
        _forget_merged_rooms(building)
        return
    room = next((r for r in building['rooms'] if r['id'] == pid), None)
    if room is not None:
        # Keep boundaries shared with a neighbour, so deleting one room does
        # not open that neighbour as a side effect.
        ids = set(room['joints'])
        shared = {j for r in building['rooms'] if r is not room for j in r['joints']}
        building['walls'] = [w for w in building['walls']
                             if not (set(w['joints']) <= ids and not set(w['joints']) <= shared)]
        building['rooms'].remove(room)
        return
    for name in ('openings', 'anchors', 'items', 'roofs', 'dormers', 'extensions', 'stairs'):
        piece = next((p for p in building.get(name, []) if p['id'] == pid), None)
        if piece is not None:
            building[name].remove(piece)
            return
    raise Refused('That piece is missing.')


def _mark_touched(building, previous):
    old_geometry, geometry = hosts.snapshot(previous), hosts.snapshot(building)
    for name in ('joints', 'walls', 'rooms', 'openings', 'anchors', 'items', 'roofs'):
        old = {p['id']: p for p in previous.get(name, [])}
        for piece in building.get(name, []):
            prior = old.get(piece['id'])
            changed = prior != piece
            if prior is not None and name in ('openings', 'anchors', 'items'):
                host = piece if name == 'openings' else piece.get('host', {})
                prior_host = prior if name == 'openings' else prior.get('host', {})
                try:
                    changed |= hosts._point(geometry, host) != hosts._point(old_geometry, prior_host)
                except (ValueError, KeyError):
                    pass
            if prior is not None and name == 'walls':
                changed |= geometry['walls'].get(piece['id']) != old_geometry['walls'].get(piece['id'])
            if changed:
                _person(piece)


def apply(model, op: dict, actor: str = 'person') -> tuple[dict, str]:
    """Return an edited model and plain words, leaving the input untouched."""
    if not isinstance(op, dict):
        raise Refused('Choose an operation.')
    kind = op.get('op')
    if kind not in ('move_joint', 'move_wall', 'move_room', 'add_wall',
                    'split_wall', 'draw_room', 'split_room', 'delete'):
        raise Refused('That operation is not available.')
    model, notes = twin_model.normalize(model)
    building = _find(model, 'buildings', op.get('building'))
    before = hosts.snapshot(building)
    _roof_offsets(building, before)
    previous = deepcopy(building)
    if kind in ('move_joint', 'move_wall', 'move_room'):
        _move(building, op, before)
    elif kind == 'delete':
        _delete(building, op.get('id'))
    else:
        if kind == 'split_wall':
            wall = _find(building, 'walls', op.get('wall'))
            a, b = (_positions(building)[j] for j in wall['joints'])
            length, at = math.dist(a, b), _number(op.get('at'))
            if at < 1 - _EPS or length - at < 1 - _EPS:
                raise Refused(_SHORT)
            _joint(building, wall['level'], [a[i] + at * (b[i] - a[i]) / length for i in (0, 1)])
        elif kind == 'draw_room':
            polygon = op.get('polygon')
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise Refused('Draw a closed room with at least three corners.')
            polygon = [_point(p) for p in polygon]
            if polygon[0] == polygon[-1]:
                polygon.pop()
            if len(polygon) < 3 or twin_model._area(polygon) <= _EPS:
                raise Refused('Draw a closed room with at least three corners.')
            for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                _draw(building, op.get('level'), a, b, 'solid', op.get('exterior', False), actor)
        else:
            level = (_find(building, 'rooms', op.get('room'))['level']
                     if kind == 'split_room' else op.get('level'))
            _draw(building, level, op.get('from'), op.get('to'),
                  'separator' if kind == 'split_room' else op.get('kind', 'solid'),
                  op.get('exterior', False), actor)
        _split_drawing(building, actor)
        hosts.carry_split(building, before)
    notes.extend(twin_model.derive(building))
    if kind == 'draw_room' and op.get('name'):
        old_ids = {r['id'] for r in previous['rooms']}
        candidates = [r for r in building['rooms'] if r['id'] not in old_ids]
        if candidates:
            max(candidates, key=lambda r: twin_model._overlap(r['polygon'], polygon))['name'] = op['name']
    notes.extend(hosts.follow(building, before))
    building['roofs'] = [roofs.follow_walls(r, building['walls'], building['joints'])
                         for r in building.get('roofs', [])]
    if actor == 'person':
        _mark_touched(building, previous)
    words = {'move_joint': 'Moved the corner.', 'move_wall': 'Moved the wall.',
             'move_room': 'Moved the room.', 'add_wall': 'Added the wall.',
             'split_wall': 'Split the wall.', 'draw_room': 'Drew the room.',
             'split_room': 'Split the room.', 'delete': 'Deleted the piece.'}[kind]
    return model, ' '.join(dict.fromkeys([words, *notes]))
