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
    if type(value) not in (int, float) or not -1e5 <= value <= 1e5 or not math.isfinite(value):
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
    if kind == 'solid' and any(w.get('kind') == 'separator' and w['level'] == level
            and _collinear_overlap(a['at'], b['at'], *(positions[j] for j in w['joints'])) is not None
            for w in building['walls']):
        # Split first so a short drawn wall converts only its own separator span.
        _split_drawing(building, actor)
    for wall in building['walls']:
        if wall['level'] != level or wall.get('state') == 'ghost':
            continue
        c, d = (positions[j] for j in wall['joints'])
        overlap = _collinear_overlap(a['at'], b['at'], c, d)
        if overlap is None:
            continue
        if kind == 'solid' and wall.get('kind') == 'separator':
            wall.update(kind='solid', thickness=0.5 if exterior else 0.33,
                        exterior=bool(exterior), state='settled')
            wall['src'] = {'person': True} if actor == 'person' else {}
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


def _promote_crossings(building, op, actor):
    kind = op['op']
    if kind == 'move_room':
        piece = _find(building, 'rooms', op.get('room'))
        moved = set(piece['joints'])
        level = piece['level']
    elif kind == 'move_wall':
        piece = _find(building, 'walls', op.get('wall'))
        moved = set(piece['joints'])
        level = piece['level']
    else:
        moved = {op.get('joint')}
        joint = next((j for j in building['joints'] if j['id'] in moved), None)
        # Room caches can expose a derived crossing as a draggable joint.
        room = next((r for r in building['rooms'] if moved.intersection(r['joints'])), None)
        if joint is None and room is None:
            raise Refused('That joint is missing.')
        level = (joint or room)['level']
    positions = _positions(building, level)
    walls = [w for w in building['walls'] if w['level'] == level and w.get('state') != 'ghost']
    derived, _ = graph.split_crossings(positions, walls)
    affected = [w for w in walls if moved.intersection(w['joints'])]
    replacements = {}
    wall_points = []
    for jid, point in derived.items():
        if jid in positions:
            continue
        incident = [w for w in affected if graph._interior_parameter(
            point, *(positions[j] for j in w['joints'])) is not None]
        if jid not in moved and not incident:
            continue
        replacements[jid] = _joint(building, level, point)['id']
        if kind == 'move_wall' and piece in incident:
            wall_points.append(replacements[jid])
    if not replacements:
        return None
    for room in building['rooms']:
        if room['level'] == level:
            room['joints'] = [replacements.get(j, j) for j in room['joints']]
    if kind == 'move_joint':
        op['joint'] = replacements.get(op['joint'], op['joint'])
    _split_drawing(building, actor)
    referenced = {j for wall in building['walls'] for j in wall['joints']}
    building['joints'] = [j for j in building['joints'] if j['id'] in referenced]
    # A perpendicular wall drag carries every promoted point on that wall,
    # including the shared endpoint of a discarded read overshoot (R15/R38).
    if kind == 'move_wall':
        return [j for j in [*piece['joints'], *moved, *wall_points] if j in referenced]
    return []


def _move(building, op, before, wall_ids=None):
    kind = op['op']
    if kind == 'move_joint':
        joint = _find(building, 'joints', op.get('joint'))
        destinations = {joint['id']: _point(op.get('to'))}
    else:
        if kind == 'move_wall':
            wall = _find(building, 'walls', op.get('wall'))
            ids = wall_ids or wall['joints']
            positions = _positions(building)
            a, b = (positions[j] for j in wall['joints'])
            length = math.dist(a, b)
            if length < 1 - _EPS:
                raise Refused(_SHORT)
            if isinstance(op.get('by'), (list, tuple)):
                delta = _point(op['by'])
            else:
                by = _number(op.get('by'))
                delta = [-(b[1] - a[1]) * by / length, (b[0] - a[0]) * by / length]
        else:
            room = _find(building, 'rooms', op.get('room'))
            ids = room['joints']
            delta = _point(op.get('by'))
            positions = _positions(building)
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


def _merge_joint(building, joint, before):
    pid = joint['id']
    walls = [w for w in building['walls'] if pid in w['joints']]
    text = 'Only a straight joint between two walls can be removed.'
    if len(walls) != 2 or any(w.get('state') == 'ghost' for w in walls):
        raise Refused(text)
    positions = _positions(building)
    ends = [next(j for j in w['joints'] if j != pid) for w in walls]
    vectors = [graph._delta(joint['at'], positions[j]) for j in ends]
    lengths = [math.hypot(*v) for v in vectors]
    dot = sum(a * b for a, b in zip(*vectors))
    if min(lengths) <= _EPS or dot > -math.cos(math.radians(3)) * math.prod(lengths):
        raise Refused(text)
    keep, removed = walls
    keep['joints'] = [ends[1] if j == pid else j for j in keep['joints']]
    building['walls'].remove(removed)
    building['joints'].remove(joint)
    geometry = hosts.snapshot(building)
    line = geometry['walls'][keep['id']]
    length = math.dist(line['a'], line['b'])
    for name in ('openings', 'anchors', 'items'):
        for piece in building.get(name, []):
            host = hosts._host(piece, name == 'openings')
            if host.get('wall') not in (keep['id'], removed['id']):
                continue
            point = hosts._point(before, host)
            at = sum((point[i] - line['a'][i]) * (line['b'][i] - line['a'][i])
                     for i in (0, 1)) / length
            hosts.rehost(building, piece['id'], {**host, 'wall': keep['id'], 'at': at})
    for roof in building.get('roofs', []):
        for edge in roof['edges']:
            if edge.get('wall') == removed['id']:
                edge['wall'] = keep['id']
    # Hosts have already been placed on the merged line, so follow must not
    # apply the wall's change in length to their distances a second time.
    before['walls'][keep['id']] = line


def _bounds_wall(room, wall, positions):
    if room['level'] != wall['level'] or room.get('state') == 'ghost':
        return False
    a, b = (positions[j] for j in wall['joints'])
    polygon = room['polygon']
    return any(_collinear_overlap(a, b, c, d) is not None
               for c, d in zip(polygon, polygon[1:] + polygon[:1]))


def _delete(building, pid, before):
    wall = next((w for w in building['walls'] if w['id'] == pid), None)
    if wall is not None:
        building['walls'].remove(wall)
        _forget_merged_rooms(building)
        return
    joint = next((j for j in building['joints'] if j['id'] == pid), None)
    if joint is not None:
        _merge_joint(building, joint, before)
        return
    room = next((r for r in building['rooms'] if r['id'] == pid), None)
    if room is not None:
        # Keep boundaries shared with a neighbour, so deleting one room does
        # not open that neighbour as a side effect.
        positions = _positions(building)
        exclusive = [w for w in building['walls'] if _bounds_wall(room, w, positions)
                     and not any(_bounds_wall(other, w, positions)
                                 for other in building['rooms'] if other is not room)]
        if not exclusive:
            raise Refused('This room shares every wall; delete a wall to merge it.')
        building['walls'] = [w for w in building['walls'] if w not in exclusive]
        building['rooms'].remove(room)
        return f"Deleted the {room['name']}."
    for name in ('openings', 'anchors', 'items', 'roofs', 'dormers', 'extensions', 'stairs'):
        piece = next((p for p in building.get(name, []) if p['id'] == pid), None)
        if piece is not None:
            building[name].remove(piece)
            if name == 'roofs':
                _follow_dormers(building, before)
            return
    raise Refused('That piece is missing.')


def _mark_touched(building, previous, op):
    old_geometry, geometry = hosts.snapshot(previous), hosts.snapshot(building)
    for name in ('joints', 'walls', 'rooms', 'openings', 'anchors', 'items', 'roofs', 'dormers', 'levels'):
        old = {p['id']: p for p in previous.get(name, [])}
        for piece in building.get(name, []):
            prior = old.get(piece['id'])
            changed = prior != piece
            if prior is not None and name in ('openings', 'anchors', 'items'):
                host = hosts._host(piece, name == 'openings')
                prior_host = hosts._host(prior, name == 'openings')
                changed = (piece['id'] == op.get('id') or
                           hosts.surface_changed(old_geometry, geometry, host, prior_host))
            if prior is not None and name == 'walls':
                changed |= geometry['walls'].get(piece['id']) != old_geometry['walls'].get(piece['id'])
            if changed:
                _person(piece)


MORE_OPS = ('add_opening', 'move_hosted', 'resize_opening', 'add_anchor', 'add_item',
            'draw_roof', 'roof_over', 'set_roof_edge', 'move_roof_edge', 'add_dormer',
            'move_dormer', 'add_level', 'move_building', 'rotate_building', 'set',
            'set_material', 'accept_proposal', 'dismiss_proposal',
            'move_site_item', 'delete_site_item', 'add_site_item')


def _positive(value):
    value = _number(value)
    if value <= 0:
        raise Refused('Enter a distance greater than zero.')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise Refused('Enter a name.')
    return value


def _piece(building, pid):
    if pid == building['id']:
        return 'building', building
    for collection, kind in (('walls', 'wall'), ('rooms', 'room'), ('roofs', 'roof'),
                             ('openings', 'opening'), ('levels', 'level'),
                             ('anchors', 'anchor'), ('items', 'item'), ('dormers', 'dormer')):
        for piece in building.get(collection, []):
            if piece['id'] == pid:
                return kind, piece
    raise Refused('That piece is missing.')


def _opening(building, piece):
    from services import twin_plan, twin_model_bridge
    flat = twin_model_bridge.flatten({'buildings': [building]})['buildings'][0]
    opening = next(o for o in flat['openings'] if o['id'] == piece['id'])
    reason = twin_plan._opening_error(opening, {w['id']: w for w in flat['walls']},
                                      {r['id']: r for r in flat['roof']['sections']})
    if reason:
        raise Refused(f'Invalid opening: {reason}.')


def _rehost(building, piece, host, opening=False):
    host = deepcopy(host)
    if not isinstance(host, dict):
        raise Refused('Choose a host surface.')
    if opening:
        host.setdefault('sill', piece.get('sill', 0))
    else:
        reason = twin_model._host_error(host, building)
        if reason:
            raise Refused(reason)
    try:
        hosts.rehost(building, piece['id'], host)
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused('Choose a host surface where this piece fits.') from exc
    if opening:
        _opening(building, piece)


def _edge_index(roof, edge):
    if type(edge) is not int or not 0 <= edge < len(roof['edges']):
        raise Refused('Choose a roof edge.')
    return edge


def _roof_area(area):
    if not isinstance(area, list) or len(area) < 4:
        raise Refused('Roof areas must have square corners.')
    area = [_point(p) for p in area]
    if area[0] == area[-1]:
        area.pop()
    try:
        rects = roofs._rectangles(area)
    except ValueError as exc:
        raise Refused(str(exc)) from exc
    # Also reject self intersections, reversals, and zero-area outlines.
    if (not rects or len({tuple(p) for p in area}) != len(area)
            or abs(sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)) <= _EPS
            or any(_intersection(a, b, c, d) is not None
                   for i, (a, b) in enumerate(roofs._segments(area))
                   for c, d in roofs._segments(area)[i + 1:])):
        raise Refused('Roof areas must have square corners.')
    return area


def _union(polygons):
    from services import twin_blocks
    # Connected joints average near-coincident measurements. Align those
    # sub-tolerance differences for the new roof only; keep the rooms intact.
    maps = []
    for axis in (0, 1):
        groups = []
        for value in sorted({p[axis] for polygon in polygons for p in polygon}):
            if not groups or value - groups[-1][0] > graph._TOL:
                groups.append([value])
            else:
                groups[-1].append(value)
        maps.append({v: (group[0] + group[-1]) / 2 for group in groups for v in group})
    polygons = [[[maps[i][p[i]] for i in (0, 1)] for p in polygon] for polygon in polygons]
    for polygon in polygons:
        _roof_area(polygon)
    xs = sorted({p[0] for polygon in polygons for p in polygon})
    ys = sorted({p[1] for polygon in polygons for p in polygon})
    cells = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1)
             if any(twin_blocks._inside(polygon, (xs[i] + xs[i + 1]) / 2,
                                      (ys[j] + ys[j + 1]) / 2) for polygon in polygons)}
    boundary = []
    for i, j in sorted(cells):
        points = [(xs[i], ys[j]), (xs[i + 1], ys[j]),
                  (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1])]
        for neighbour, a, b in zip(((i, j - 1), (i + 1, j), (i, j + 1), (i - 1, j)),
                                    points, points[1:] + points[:1]):
            if neighbour not in cells:
                boundary.append((a, b))
    if not boundary:
        raise Refused('Choose rooms with an enclosed area.')
    following = dict(boundary)
    start = boundary[0][0]
    polygon, point = [], start
    while point not in polygon and point in following:
        polygon.append(point)
        point = following[point]
    if point != start or len(polygon) != len(boundary):
        raise Refused('Choose rooms that form one area without holes.')
    polygon = [list(p) for i, p in enumerate(polygon)
               if abs(graph._cross(graph._delta(polygon[i - 1], p),
                                   graph._delta(p, polygon[(i + 1) % len(polygon)]))) > _EPS]
    return _roof_area(polygon)


def _follow_dormers(building, before):
    text = 'This dormer lost its roof; place it again.'
    for dormer in building.get('dormers', []):
        roof = next((r for r in building['roofs'] if r['id'] == dormer.get('roof')), None)
        if roof is not None:
            edge = _edge_index(roof, dormer.get('edge'))
            length = math.dist(roof['area'][edge], roof['area'][(edge + 1) % len(roof['area'])])
            dormer['at'] = max(0, min(length, dormer['at']))
            continue
        old = before['roofs'].get(dormer.get('roof'))
        at = [0, 0]
        if old is not None:
            a, b = roofs._segments(old['area'])[dormer['edge']]
            length = math.dist(a, b)
            at = [a[i] + (b[i] - a[i]) * dormer['at'] / length for i in (0, 1)]
        dormer.update(state='ghost', why=text)
        if not any(f.get('piece') == dormer['id'] and f.get('text') == text for f in building['flags']):
            building['flags'].append({'level': old.get('level') if old else None,
                                      'at': at, 'piece': dormer['id'], 'text': text})


def _set_field(building, op):
    from services import twin_edit, twin_model_bridge
    if op.get('field') == 'flag_ok':
        value = op.get('value')
        flags = building.get('flags', [])
        index = value.get('index') if isinstance(value, dict) else None
        text = value.get('text') if isinstance(value, dict) else None
        if (type(index) is not int or not 0 <= index < len(flags)
                or not isinstance(text, str) or flags[index].get('text') != text
                or 'flag' in value and value['flag'] != flags[index]):
            raise Refused('That check has changed. Open it again.')
        flag = flags.pop(index)
        piece = next((p for name in ('openings', 'anchors', 'items', 'dormers')
                      for p in building.get(name, []) if p['id'] == flag.get('piece')), None)
        if (text == twin_model.NOT_CLOSED or piece is not None
                and text in (*hosts._texts(piece), 'This dormer lost its roof; place it again.')):
            if flag not in building.setdefault('checked_flags', []):
                building['checked_flags'].append(deepcopy(flag))
        return
    kind, piece = _piece(building, op.get('id'))
    if kind == 'roof':
        # Reuse the established field validation and window-bearing gable guard,
        # then translate the section's changed planes back to its area edges.
        flat = twin_model_bridge.flatten({'buildings': [building]})['buildings'][0]
        sections = roofs.to_sections(piece)
        if len(sections) != 1:
            raise Refused('Choose an edge to change this roof.')
        section = next(s for s in flat['roof']['sections'] if s['id'] == sections[0]['id'])
        twin_edit._set(kind, section, flat, op.get('field'), op.get('value'))
        updated = roofs.from_section(section)
        for key in ('kind', 'pitch', 'ridge', 'low_side', 'pitch_source', 'plate', 'overhang'):
            if key in updated:
                piece[key] = updated[key]
            else:
                piece.pop(key, None)
        for old, new in zip(piece['edges'], updated['edges']):
            old.update(new)
        return
    flat = twin_model_bridge.flatten({'buildings': [building]})['buildings'][0]
    collection = {'wall': 'walls', 'opening': 'openings', 'room': 'rooms', 'level': 'levels'}.get(kind)
    checked = next((p for p in flat.get(collection, []) if p['id'] == piece['id']), None) if collection else flat
    if checked is None:
        raise Refused('That piece is missing.')
    twin_edit._set(kind, checked, flat, op.get('field'), op.get('value'))
    piece[op['field']] = deepcopy(checked[op['field']])
    if kind == 'building' and op['field'] in ('position', 'rotation'):
        piece['position_from'] = 'person'
    if kind == 'opening':
        _opening(building, piece)


def _material(building, op):
    target, material = op.get('target'), op.get('material')
    if not isinstance(target, dict):
        raise Refused('Choose a surface for the material.')
    if material is not None and (not isinstance(material, dict)
            or any(not isinstance(material.get(k), str) or not material[k] for k in ('id', 'color'))):
        raise Refused('Choose a material with an id and color.')
    if 'wall' in target and target.get('side') in ('left', 'right'):
        owner = _find(building, 'walls', target['wall'])
        container, key = owner.setdefault('faces', {}), target['side']
    elif 'room' in target and target.get('surface') in ('floor', 'ceiling', 'walls'):
        owner = _find(building, 'rooms', target['room'])
        container = owner
        key = {'floor': 'floor_material', 'ceiling': 'ceiling_material',
               'walls': 'wall_material'}[target['surface']]
    elif 'roof' in target:
        owner = _find(building, 'roofs', target['roof'])
        container, key = owner, 'material'
    elif ('level' in target or target.get('building') == building['id']) and target.get('role'):
        owner = _find(building, 'levels', target['level']) if 'level' in target else building
        container, key = owner.setdefault('materials', {}), _text(target['role'])
    else:
        raise Refused('Choose a surface for the material.')
    if material is None:
        container.pop(key, None)
    else:
        container[key] = deepcopy(material)


def _proposal(building, op):
    proposal = _find(building, 'proposals', op.get('id'))
    if op['op'] == 'accept_proposal':
        collection = {'wall': 'walls', 'opening': 'openings', 'roof': 'roofs',
                      'room': 'rooms', 'anchor': 'anchors', 'item': 'items',
                      'dormer': 'dormers'}.get(proposal.get('kind'))
        if collection is None:
            raise Refused('This proposal cannot be accepted.')
        piece = deepcopy(proposal['piece'])
        # Retain the live identity so its hosted pieces keep their references.
        piece.update(id=proposal['against'], state='settled')
        _person(piece)
        if collection == 'walls' and 'from' in piece and 'to' in piece:
            piece['joints'] = [_joint(building, piece['level'], piece[key])['id'] for key in ('from', 'to')]
            piece.pop('from', None)
            piece.pop('to', None)
        building[collection] = [p for p in building[collection] if p['id'] != proposal['against']] + [piece]
    building['proposals'].remove(proposal)


def _more(building, op):
    kind = op['op']
    if kind == 'add_opening':
        from services.twin_edit import _OPENING_KINDS
        wall = _find(building, 'walls', op.get('wall'))
        if op.get('kind') not in _OPENING_KINDS or wall.get('kind') == 'separator':
            raise Refused('Choose an opening kind and a solid wall.')
        height = wall.get('height', _find(building, 'levels', wall['level'])['ceiling'])
        piece = {'id': _id(building, 'opening'), 'wall': wall['id'], 'kind': op['kind'],
                 'at': _number(op.get('at')), 'width': _positive(op.get('width', 3)),
                 'sill': _number(op.get('sill', min(2, height / 3) if op['kind'] == 'window' else 0)),
                 'head': _positive(op.get('head', min(7, height))), 'state': 'settled'}
        building['openings'].append(piece)
        _rehost(building, piece, piece, True)
    elif kind in ('add_anchor', 'add_item'):
        collection = 'anchors' if kind == 'add_anchor' else 'items'
        piece = {'id': _id(building, collection[:-1]), 'state': 'settled'}
        if kind == 'add_anchor':
            if op.get('kind') not in ('light', 'switch', 'outlet', 'fan', 'camera', 'sensor'):
                raise Refused('Choose an anchor kind.')
            piece.update(kind=op['kind'], offset=0, device=None)
        else:
            piece.update(asset=_text(op.get('asset')), rotation=_number(op.get('rotation', 0)) % 360,
                         scale=_positive(op.get('scale', 1)))
        building[collection].append(piece)
        _rehost(building, piece, op.get('host'))
    elif kind in ('move_hosted', 'resize_opening'):
        piece_kind, piece = _piece(building, op.get('id'))
        if piece_kind not in ('opening', 'anchor', 'item') or (kind == 'resize_opening' and piece_kind != 'opening'):
            raise Refused('Choose a hosted piece.')
        opening = piece_kind == 'opening'
        host = deepcopy(op.get('host', hosts._host(piece, opening)))
        if not isinstance(host, dict):
            raise Refused('Choose a host surface.')
        for field in ('at', 'z'):
            if field in op:
                host[field] = _number(op[field])
        for field in (('width', 'sill', 'head') if opening else ('offset',)):
            if field in op:
                piece[field] = _positive(op[field]) if field in ('width', 'head') else _number(op[field])
        _rehost(building, piece, host, opening)
    elif kind in ('draw_roof', 'roof_over'):
        level = max(building['levels'], key=lambda l: l['elevation'])
        if kind == 'roof_over':
            ids = op.get('rooms')
            if ids is None:
                polygons = [r['polygon'] for r in building['rooms']
                            if r['level'] == level['id'] and r.get('state') != 'ghost']
                area = _union(polygons)
            else:
                if not isinstance(ids, list) or not ids:
                    raise Refused('Choose rooms to roof over.')
                rooms = [_find(building, 'rooms', pid) for pid in ids]
                if len({r['level'] for r in rooms}) != 1:
                    raise Refused('Choose rooms on one floor.')
                level = _find(building, 'levels', rooms[0]['level'])
                area = _union([r['polygon'] for r in rooms])
        else:
            area = op.get('area')
            if 'level' in op:
                level = _find(building, 'levels', op['level'])
            elif 'plate' in op:
                plate = _number(op['plate'])
                candidates = [l for l in building['levels']
                              if l['elevation'] + .5 < plate <= l['elevation'] + l['ceiling'] + 2]
                if candidates:
                    level = max(candidates, key=lambda l: l['elevation'])
        pitch = _number(op.get('pitch', 6))
        if not 0 <= pitch <= 24:
            raise Refused('Choose a pitch from 0 to 24 in 12.')
        overhang = _number(op.get('overhang', 1))
        if not 0 <= overhang <= 4:
            raise Refused('Choose an overhang from 0 to 4 ft.')
        area = _roof_area(area)
        roof = {'id': _id(building, 'roof'), 'level': level['id'], 'area': area,
                'plate': _positive(op.get('plate', level['elevation'] + level['ceiling'])),
                'pitch': pitch, 'overhang': overhang, 'state': 'settled',
                'edges': [{'setting': 'sloped', 'pitch': pitch} for _ in area]}
        building['roofs'].append(roofs.attach_edges(roof, building['walls'], building['joints']))
    elif kind in ('set_roof_edge', 'move_roof_edge'):
        roof = _find(building, 'roofs', op.get('roof'))
        index = _edge_index(roof, op.get('edge'))
        edge = roof['edges'][index]
        if kind == 'set_roof_edge':
            if op.get('setting') not in ('sloped', 'gable', 'clip'):
                raise Refused('Choose a sloped, gable or clipped edge.')
            if op['setting'] == 'sloped' and any(o.get('gable') == {'roof': roof['id'], 'edge': index}
                                                for o in building['openings']):
                raise Refused('A window sits in that gable; move or delete it first.')
            edge['setting'] = op['setting']
            for field in ('pitch', 'clip'):
                if field in op:
                    value = _number(op[field])
                    if value < 0 or (field == 'pitch' and value > 24):
                        raise Refused('Choose a valid roof pitch or clip height.')
                    edge[field] = value
        else:
            a, b = roofs._segments(roof['area'])[index]
            length = math.dist(a, b)
            orientation = sum(graph._cross(p, q) for p, q in roofs._segments(roof['area']))
            sign = 1 if orientation > 0 else -1
            by = _number(op.get('by'))
            delta = [sign * (b[1] - a[1]) / length * by, -sign * (b[0] - a[0]) / length * by]
            for point in (a, b):
                point[:] = [point[i] + delta[i] for i in (0, 1)]
            _roof_area(roof['area'])
            if op.get('detach'):
                edge.pop('wall', None)
                edge.pop('wall_offset', None)
            elif 'wall_offset' in edge:
                axis = 0 if abs(a[0] - b[0]) <= _EPS else 1
                edge['wall_offset'] += delta[axis]
    elif kind in ('add_dormer', 'move_dormer'):
        if kind == 'add_dormer':
            roof = _find(building, 'roofs', op.get('roof'))
            edge = _edge_index(roof, op.get('edge'))
            if roof['edges'][edge]['setting'] != 'sloped':
                raise Refused('Place the dormer on a sloping roof edge.')
            dormer = {'id': _id(building, 'dormer'), 'roof': roof['id'], 'edge': edge,
                      'at': _number(op.get('at')), 'width': _positive(op.get('width')),
                      'pitch': _positive(op.get('pitch')), 'state': 'settled'}
            if dormer['pitch'] > 24:
                raise Refused('Choose a pitch from 1 to 24 in 12.')
            building['dormers'].append(dormer)
        else:
            dormer = _find(building, 'dormers', op.get('id'))
            _find(building, 'roofs', dormer.get('roof'))
            for field in ('at', 'width'):
                if field in op:
                    dormer[field] = _positive(op[field]) if field == 'width' else _number(op[field])
    elif kind == 'add_level':
        building['levels'].append({'id': _id(building, 'level'), 'name': _text(op.get('name')),
                                    'elevation': _number(op.get('elevation')),
                                    'ceiling': _positive(op.get('ceiling')), 'state': 'settled'})
    elif kind == 'move_building':
        building['position'] = _point(op.get('to'))
        building['position_from'] = 'person'
    elif kind == 'rotate_building':
        rotation = _number(op.get('rotation')) % 360
        if 'about' in op:
            about = _point(op['about'])
            angle = math.radians(rotation - building['rotation'])
            vector = [building['position'][i] - about[i] for i in (0, 1)]
            building['position'] = [about[0] + vector[0] * math.cos(angle) - vector[1] * math.sin(angle),
                                    about[1] + vector[0] * math.sin(angle) + vector[1] * math.cos(angle)]
        building['rotation'] = rotation
        building['position_from'] = 'person'
    elif kind == 'set':
        _set_field(building, op)
    elif kind == 'set_material':
        _material(building, op)
    elif kind in ('accept_proposal', 'dismiss_proposal'):
        _proposal(building, op)
    return {'add_opening': 'Added the opening.', 'move_hosted': 'Moved the piece.',
            'resize_opening': 'Resized the opening.', 'add_anchor': 'Added the anchor.',
            'add_item': 'Added the item.', 'draw_roof': 'Drew the roof.', 'roof_over': 'Added the roof.',
            'set_roof_edge': 'Changed the roof edge.', 'move_roof_edge': 'Moved the roof edge.',
            'add_dormer': 'Added the dormer.', 'move_dormer': 'Moved the dormer.',
            'add_level': 'Added the floor.', 'move_building': 'Moved the building.',
            'rotate_building': 'Turned the building.', 'set': 'Changed the piece.',
            'set_material': 'Changed the material.', 'accept_proposal': 'Accepted the proposal.',
            'dismiss_proposal': 'Dismissed the proposal.'}[kind]


def _site_op(model, op, actor):
    from services import twin_plan
    before = deepcopy(model)
    name = op.get('list')
    if name not in ('planting', 'furniture'):
        raise Refused('Choose plants or furniture.')
    pieces = model['site'].setdefault(name, [])
    if op['op'] == 'add_site_item':
        asset = _text(op.get('asset'))
        piece = {'id': _id(model['site'], name), 'asset': asset, 'at': _point(op.get('at'))}
        if name == 'planting':
            from services import twin_library
            kit = twin_library.kit('modern_farmhouse')
            if asset in kit['shrubs']:
                piece.update(preset=asset, kind='shrub', height=4, seed=1)
            elif asset in kit['backdrop_trees'] + kit['specimen_trees']:
                piece.update(preset=asset, kind='tree', height=25, seed=1)
            else:
                raise Refused('Choose a plant from the library.')
        if actor == 'person':
            piece['src'] = {'person': True}
        pieces.append(piece)
    else:
        index = op.get('index')
        if type(index) is not int or not 0 <= index < len(pieces):
            raise Refused('That site item is missing.')
        if op['op'] == 'move_site_item':
            pieces[index]['at'] = _point(op.get('at'))
            if actor == 'person':
                pieces[index].setdefault('src', {})['person'] = True
        else:
            pieces.pop(index)
    return twin_plan.record_compose_overrides(before, model), 'Changed the site item.'


def apply(model, op: dict, actor: str = 'person') -> tuple[dict, str]:
    """Return an edited model and plain words, leaving the input untouched."""
    if not isinstance(op, dict):
        raise Refused('Choose an operation.')
    kind = op.get('op')
    if kind not in MORE_OPS + ('move_joint', 'move_wall', 'move_room', 'add_wall',
                    'split_wall', 'draw_room', 'split_room', 'delete'):
        raise Refused('That operation is not available.')
    op = deepcopy(op)
    model, notes = twin_model.normalize(model)
    if kind in ('move_site_item', 'delete_site_item', 'add_site_item'):
        return _site_op(model, op, actor)
    building = _find(model, 'buildings', op.get('building'))
    before = hosts.snapshot(building)
    _roof_offsets(building, before)
    previous = deepcopy(building)
    deleted_words = None
    if kind in MORE_OPS:
        try:
            deleted_words = _more(building, op)
        except ValueError as exc:
            raise Refused(str(exc)) from exc
    elif kind in ('move_joint', 'move_wall', 'move_room'):
        wall_ids = _promote_crossings(building, op, actor)
        if wall_ids is not None:
            notes.extend(hosts.follow(building, before))
            before = hosts.snapshot(building)
        _move(building, op, before, wall_ids)
    elif kind == 'delete':
        deleted_words = _delete(building, op.get('id'), before)
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
            if kind == 'split_room':
                # This is a deliberate split: overlap, not the number of old
                # corners on each side, decides which part keeps the name.
                _find(building, 'rooms', op.get('room'))['joints'] = []
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
    building['roofs'] = [roofs.follow_walls(r, building['walls'], building['joints'])
                         for r in building.get('roofs', [])]
    notes.extend(hosts.follow(building, before))
    _follow_dormers(building, before)
    twin_model.filter_checked_flags(building)
    if actor == 'person':
        _mark_touched(building, previous, op)
    words = {'move_joint': 'Moved the corner.', 'move_wall': 'Moved the wall.',
             'move_room': 'Moved the room.', 'add_wall': 'Added the wall.',
             'split_wall': 'Split the wall.', 'draw_room': 'Drew the room.',
             'split_room': 'Split the room.', 'delete': 'Deleted the piece.'}.get(kind, deleted_words)
    words = deleted_words or words
    return model, ' '.join(dict.fromkeys([words, *notes]))
