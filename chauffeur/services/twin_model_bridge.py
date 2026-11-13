"""Compatibility boundary between flat reads and the connected house model."""

from copy import deepcopy
import math

from services import twin_model, twin_model_graph as graph
from services import twin_model_hosts as hosts, twin_model_roofs as roofs, twin_plan
from services import twin_porches


_EPS = 1e-6
_SEPARATOR = 'I added an invisible wall here to keep two rooms apart; check it.'
_DORMER = 'This dormer lost its roof; place it again.'


def _person(piece):
    return piece.get('src', {}).get('person') is True


def _segments(poly):
    return zip(poly, poly[1:] + poly[:1])


def _line(wall, joints):
    return [joints[j] for j in wall['joints']]


def _flat_wall(wall, joints):
    return {**deepcopy(wall), 'from': list(joints[wall['joints'][0]]),
            'to': list(joints[wall['joints'][1]])}


def _near_wall(a, b):
    return min(max(math.dist(a['from'], b['from']), math.dist(a['to'], b['to'])),
               max(math.dist(a['from'], b['to']), math.dist(a['to'], b['from']))) <= 1


def _wall_overlap(a, b):
    p, q = a['from'], a['to']
    length = math.dist(p, q)
    if length <= _EPS:
        return False
    direction = [(q[i] - p[i]) / length for i in (0, 1)]
    ends = [b['from'], b['to']]
    if any(abs((r[0] - p[0]) * direction[1] - (r[1] - p[1]) * direction[0]) >= 1
           for r in ends):
        return False
    lo, hi = sorted(sum((r[i] - p[i]) * direction[i] for i in (0, 1)) for r in ends)
    return min(length, hi) - max(0, lo) > length / 2


def _proposal(building, kind, piece, against):
    piece = deepcopy(piece)
    piece['id'] = piece['id'].removesuffix(':proposal') + ':proposal'
    piece['state'] = 'proposal'
    proposal = {'id': piece['id'], 'kind': kind, 'against': against['id'], 'piece': piece}
    if proposal not in building['proposals']:
        building['proposals'].append(proposal)


def _wall_slice(wall, lo, hi):
    part = deepcopy(wall)
    for key, t in (('from', lo), ('to', hi)):
        part[key] = [wall['from'][i] + (wall['to'][i] - wall['from'][i]) * t for i in (0, 1)]
    return part


def _walls(building, incoming, previous, replaced):
    old_joints = {j['id']: j['at'] for j in previous.get('joints', [])}
    # A person's piece that arrives still marked as theirs is the caller's own
    # version of it (a build carries it through a new frame or level names):
    # it is pinned as it arrives. Only reads are checked against it.
    mine = [deepcopy(w) for w in incoming if _person(w)]
    ids = {w['id'] for w in mine}
    pinned = mine + [_flat_wall(w, old_joints) for w in previous.get('walls', [])
                     if _person(w) and w['id'] not in ids]
    old_walls = [_flat_wall(w, old_joints) for w in previous.get('walls', [])]
    live = []
    for wall in incoming:
        if _person(wall):
            continue
        old = next((w for w in old_walls if w['id'] == wall['id']), None)
        # Before R37 every migration separator was flagged at creation.
        if old and old.get('kind') == 'separator' and old.get('flagged',
                old.get('src', {}).get('step') == 'migration'):
            wall['flagged'] = True
        same_level = [p for p in pinned if p['level'] == wall['level']]
        exact = next((p for p in same_level if p['id'] == wall['id']), None)
        siblings = [w for w in old_walls if w['level'] == wall['level']
                    and w['id'].split('~')[0] == wall['id'].split('~')[0]]
        if exact and len(siblings) == 1:
            replaced.append(wall)
            if not _near_wall(wall, exact):
                _proposal(building, 'wall', wall, exact)
            continue
        identity = [p for p in same_level if p['id'].split('~')[0] == wall['id'].split('~')[0]]
        if exact:
            identity = [exact] + [p for p in identity if p is not exact]
        if identity:
            length2 = math.dist(wall['from'], wall['to']) ** 2
            cuts = []
            for person in identity:
                ends = sorted(sum((r[i] - wall['from'][i]) * (wall['to'][i] - wall['from'][i])
                                  for i in (0, 1)) / length2 for r in (person['from'], person['to']))
                lo, hi = max(0, ends[0]), min(1, ends[1])
                if hi - lo <= _EPS:
                    continue
                part = _wall_slice(wall, lo, hi)
                replaced.append(part)
                cuts.append((lo, hi))
                if not _near_wall(part, person):
                    _proposal(building, 'wall', part, person)
            end = 0
            for lo, hi in sorted(cuts) + [(1, 1)]:
                if lo - end > _EPS:
                    part = _wall_slice(wall, end, lo)
                    sibling = next((w for w in old_walls if not _person(w) and w['level'] == part['level']
                                    and w['id'].split('~')[0] == part['id'].split('~')[0]
                                    and _near_wall(part, w)), None)
                    if sibling:
                        part['id'] = sibling['id']
                    elif any(p['id'] == part['id'] for p in pinned + live):
                        suffix = 2
                        while any(p['id'] == f"{wall['id']}~{suffix}" for p in pinned + live):
                            suffix += 1
                        part['id'] = f"{wall['id']}~{suffix}"
                    live.append(part)
                end = max(end, hi)
            continue
        if any(_near_wall(wall, p) for p in same_level):
            continue
        against = next((p for p in same_level if _wall_overlap(wall, p)), None)
        if against is not None:
            _proposal(building, 'wall', wall, against)
            replaced.append(wall)
        else:
            live.append(wall)
    walls = pinned + live
    # Reuse closure walls across raw reads, including their migration identities.
    for wall in previous.get('walls', []):
        if wall.get('kind') != 'separator' or any(w['id'] == wall['id'] for w in walls):
            continue
        piece = _flat_wall(wall, old_joints)
        if piece.get('src', {}).get('step') == 'migration':
            piece.setdefault('flagged', True)
        if _coverage(piece['from'], piece['to'], walls, piece['level']):
            walls.append(piece)
    return walls


def _coverage(a, b, walls, level):
    """Intervals along a stored edge covered by the union of nearby walls."""
    length = math.dist(a, b)
    if length <= _EPS:
        return []
    d = [(b[i] - a[i]) / length for i in (0, 1)]
    intervals = []
    for wall in walls:
        if wall['level'] != level or wall.get('state') == 'ghost':
            continue
        p, q = wall['from'], wall['to']
        if any(abs((r[0] - a[0]) * d[1] - (r[1] - a[1]) * d[0]) > 1 for r in (p, q)):
            continue
        lo, hi = sorted(sum((r[i] - a[i]) * d[i] for i in (0, 1)) for r in (p, q))
        if hi > 0 and lo < length:
            intervals.append((max(0, lo), min(length, hi)))
    uncovered, end = [], 0
    for lo, hi in sorted(intervals):
        if lo - end > _EPS:
            uncovered.append((end, lo))
        end = max(end, hi)
    if length - end > _EPS:
        uncovered.append((end, length))
    # An end gap shorter than the weld tolerance is already within a foot of
    # the covering segment. A wholly uncovered short edge still needs a wall.
    return [(lo, hi) for lo, hi in uncovered
            if hi - lo > _EPS and (hi - lo >= 1 or not intervals)]


def _displace_derived(rooms):
    """A read or person room laid over a Room the model only derived takes
    that region: the derived record would otherwise claim it by its joint
    cycle and park the named room in an unclosed flag."""
    named = [r for r in rooms if not twin_model.derived_room(r)
             and r.get('state') not in ('ghost', 'proposal') and twin_plan._polygon(r.get('polygon'))]
    kept = []
    for room in rooms:
        if twin_model.derived_room(room) and twin_plan._polygon(room.get('polygon')):
            area = twin_model._area(room['polygon'])
            if any(other.get('level') == room.get('level')
                   and twin_model._overlap(room['polygon'], other['polygon']) > area / 2
                   for other in named):
                continue
        kept.append(room)
    return kept


def _separators(building, walls, rooms, *, migration, replaced=()):
    rooms = [r for r in rooms if r.get('state') not in ('ghost', 'proposal')
             and twin_plan._polygon(r.get('polygon'))]
    boundaries = [{'level': r['level'], 'from': a, 'to': b}
                  for r in rooms for a, b in _segments(r['polygon'])]
    # Old automatic closures have no purpose once their read rooms disappear.
    walls[:] = [w for w in walls if w.get('kind') != 'separator'
                or _person(w) or w.get('src', {}).get('step') not in ('rooms', 'migration', 'porch')
                or not _coverage(w['from'], w['to'], boundaries, w['level'])]
    ids = {w['id'] for w in walls}
    added = {}
    for room in rooms:
        if twin_model.derived_room(room):
            # Invisible walls keep read and named rooms; a Room the model only
            # derived goes with the walls that made it.
            continue
        for a, b in _segments(room['polygon']):
            length = math.dist(a, b)
            for lo, hi in _coverage(a, b, walls + list(replaced), room['level']):
                ends = [[a[i] + (b[i] - a[i]) * t / length for i in (0, 1)] for t in (lo, hi)]
                wid = f'separator-{len(ids) + 1}'
                while wid in ids:
                    wid += ':'
                ids.add(wid)
                wall = {'id': wid, 'level': room['level'], 'from': ends[0], 'to': ends[1],
                        'kind': 'separator', 'thickness': 0, 'exterior': False,
                        'src': {'sheet': '', 'page': 0,
                                'step': 'porch' if room.get('kind') == 'porch' else 'migration' if migration else 'rooms'},
                        'height': next(l['ceiling'] for l in building['levels'] if l['id'] == room['level'])}
                walls.append(wall)
                if room.get('kind') != 'porch':
                    neighbours = [r for r in rooms if r is not room and r['level'] == room['level']
                                  and any(not _coverage(*ends, [{'level': room['level'], 'from': p, 'to': q}],
                                                        room['level']) for p, q in _segments(r['polygon']))]
                    names = [room.get('name', 'Room'), neighbours[0].get('name', 'Room') if neighbours else 'Room']
                    text = (_SEPARATOR if 'Room' in names else
                            f'I added an invisible wall here to keep the {names[0]} and the {names[1]} apart; check it.')
                    wall['flagged'] = True
                    added.setdefault(room['level'], []).append((wall, text))
    for lid, pieces in added.items():
        wall, text = pieces[0]
        if len(pieces) > 1:
            name = next(l['name'] for l in building['levels'] if l['id'] == lid)
            text = f'I added {len(pieces)} invisible walls on the {name} to keep rooms apart; check them.'
        building['flags'].append({'level': lid, 'at': [(a + b) / 2 for a, b in zip(wall['from'], wall['to'])],
                                  'text': text, 'piece': wall['id'],
                                  'separators': [w['id'] for w, _ in pieces]})


def _meets(p, q, a, b):
    """Segments pq and ab touch or cross."""
    def side(o, s, t):
        value = (s[0] - o[0]) * (t[1] - o[1]) - (s[1] - o[1]) * (t[0] - o[0])
        return 0 if abs(value) <= _EPS else (1 if value > 0 else -1)
    def within(o, s, t):
        return all(min(o[i], s[i]) - _EPS <= t[i] <= max(o[i], s[i]) + _EPS for i in (0, 1))
    d1, d2, d3, d4 = side(a, b, p), side(a, b, q), side(p, q, a), side(p, q, b)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return ((d1 == 0 and within(a, b, p)) or (d2 == 0 and within(a, b, q))
            or (d3 == 0 and within(p, q, a)) or (d4 == 0 and within(p, q, b)))


def _network(building, walls, previous):
    """Weld per storey, reserving previous identities and all pinned positions."""
    previous_joints = previous.get('joints', [])
    pinned = {j for w in previous.get('walls', []) if _person(w) for j in w['joints']}
    pinned.update(j['id'] for j in previous_joints if _person(j))
    used = {j['id'] for j in previous_joints}
    building['joints'], building['walls'] = [], []
    counter = 0
    for level in building['levels']:
        lid = level['id']
        group = [w for w in walls if w['level'] == lid]

        def nearest(point, wall, *, short_only=False):
            hits = []
            for other in group:
                if other is wall or other.get('kind') == 'separator' or other.get('state') == 'ghost':
                    continue
                a, b = other['from'], other['to']
                if short_only and _meets(wall['from'], wall['to'], a, b):
                    continue  # an overshoot already crosses it (R15)
                length2 = sum((b[t] - a[t]) ** 2 for t in (0, 1))
                if length2 <= _EPS:
                    continue
                at = max(0, min(1, sum((point[t] - a[t]) * (b[t] - a[t]) for t in (0, 1)) / length2))
                q = [a[t] + at * (b[t] - a[t]) for t in (0, 1)]
                if math.dist(point, q) <= 1 + _EPS:
                    hits.append((math.dist(point, q), q))
            return min(hits) if hits else None

        # Separator ends on the interior of an existing wall need a T-joint,
        # rather than a second, almost parallel room boundary.
        for wall in group:
            if wall.get('kind') != 'separator':
                continue
            ends = [wall['from'], wall['to']]
            for k in (0, 1):
                hit = nearest(ends[k], wall)
                if hit:
                    ends[k] = hit[1]
            if math.dist(*ends) > _EPS:
                wall['from'], wall['to'] = ends
        # A read wall's open end on a stored room's outline, within the foot
        # that counts that room's edge as walled (R1), is joined to the wall it
        # nearly meets by an invisible connector: the room closes and the read
        # wall stays as read. A connector stays while it still joins the two.
        def on_wall(point, *, ends_only):
            return any(math.dist(point, other[end]) <= .05 for other in group
                       if other.get('kind') != 'separator' and other.get('state') != 'ghost'
                       for end in ('from', 'to')) or (not ends_only and any(
                graph._interior_parameter(point, other['from'], other['to']) is not None
                for other in group if other.get('kind') != 'separator' and other.get('state') != 'ghost'))

        outlines = [r['polygon'] for r in building.get('rooms', []) if r.get('level') == lid
                    and r.get('state') not in ('ghost', 'proposal') and not twin_model.derived_room(r)
                    and twin_plan._polygon(r.get('polygon'))]

        def on_outline(point):
            return any(math.dist(point, a) <= .05 or graph._interior_parameter(point, a, b) is not None
                       for polygon in outlines for a, b in _segments(polygon))

        group = [w for w in group if w.get('src', {}).get('step') != 'joint'
                 or (on_wall(w['from'], ends_only=True) and on_wall(w['to'], ends_only=False))]
        connectors = []
        for wall in group:
            if wall.get('kind') == 'separator' or _person(wall) or wall.get('state') == 'ghost':
                continue
            for k, key in enumerate(('from', 'to')):
                point = wall[key]
                if any(math.dist(point, other[end]) < 1 for other in group
                       if other is not wall and other.get('state') != 'ghost' for end in ('from', 'to')):
                    continue
                hit = nearest(point, wall, short_only=True) if on_outline(point) else None
                if hit and hit[0] > .05:
                    connectors.append({'id': f"{wall['id']}:joint-{k + 1}", 'level': lid,
                                       'from': list(point), 'to': hit[1], 'kind': 'separator',
                                       'thickness': 0, 'exterior': False, 'height': wall.get('height'),
                                       'src': {'sheet': '', 'page': 0, 'step': 'joint'}})
        group.extend(connectors)
        points = [w[key] for w in group for key in ('from', 'to')]
        positions, indices = graph.weld(points, separate=[(i, i + 1) for i in range(0, len(points), 2)])
        ids, claimed = [], set()
        for index, point in enumerate(positions):
            members = [points[i] for i, owner in enumerate(indices) if owner == index]
            candidates = [j for j in previous_joints if j.get('level') == lid and j['id'] not in claimed
                          and any(math.dist(j['at'], p) < 1 for p in members)]
            if candidates:
                old = min(candidates, key=lambda j: (j['id'] not in pinned, math.dist(j['at'], point), j['id']))
                jid, point = old['id'], list(old['at'])
                claimed.add(jid)
                joint = dict(deepcopy(old), at=point)
                joint.pop('derived', None)
            else:
                counter += 1
                jid = f'joint-{counter}'
                while jid in used:
                    counter += 1
                    jid = f'joint-{counter}'
                joint = {'id': jid, 'level': lid, 'at': point}
            used.add(jid)
            ids.append(jid)
            building['joints'].append(joint)
        for i, wall in enumerate(group):
            piece = {k: deepcopy(v) for k, v in wall.items() if k not in ('from', 'to', 'footprint')}
            piece['joints'] = [ids[indices[2 * i]], ids[indices[2 * i + 1]]]
            piece.setdefault('kind', 'solid')
            piece.setdefault('thickness', .5 if piece.get('exterior') else .33)
            if piece['kind'] == 'separator':
                piece['thickness'] = 0
            building['walls'].append(piece)


def _bearing_level(building, plate):
    candidates = [l for l in building['levels']
                  if l['elevation'] + .5 < plate <= l['elevation'] + l.get('ceiling', 9) + 2]
    return max(candidates, key=lambda l: l['elevation'])['id'] if candidates else None


def _roof_form(roof):
    return [(s['rect'], s['kind'], s.get('ridge'), s.get('ends'), s.get('pitches'),
             s['pitch'], s['plate'], s['overhang']) for s in roofs.to_sections(roof)]


def _dormer_sections(dormer, parent):
    edge = dormer.get('edge')
    if (parent is None or type(edge) is not int or not 0 <= edge < len(parent['area'])
            or not twin_plan._number(dormer.get('at'))
            or not 0 <= dormer['at'] <= math.dist(parent['area'][edge], parent['area'][(edge + 1) % len(parent['area'])])):
        return []
    return roofs.dormer_sections(dormer, parent)


def _roofs(building, flat_roof, previous, cached_dormers, notes, *, migration=False):
    pinned = [deepcopy(r) for r in previous.get('roofs', []) if _person(r)]
    building['roofs'] = list(pinned)
    sections = deepcopy(flat_roof.get('sections', []))
    old_dormers = {d['id']: d for d in previous.get('dormers', [])}
    old_roofs = {r['id']: r for r in previous.get('roofs', [])}
    for section in sections:
        dormer = old_dormers.get(section['id'])
        parent = old_roofs.get(dormer.get('roof')) if dormer else None
        if parent is not None:
            # Older edits labelled a dormer with its parent's block instead.
            section.setdefault('dormer_of', list(twin_model._bounds(parent['area'])))
            section.pop('block', None)
    for section in sections:
        if section.get('dormer_of') or section.get('state') == 'proposal':
            continue
        choice = next((c for c in flat_roof.get('choices', [])
                       if all(abs(a - b) <= 1 for a, b in zip(section['rect'], c['rect']))), None)
        if choice is not None and not migration:
            # A person's block choice that arrives in the flat plan is applied
            # to its section. On migration the section already holds it (R14).
            for key in ('kind', 'ridge', 'ends', 'pitch', 'pitches', 'plate', 'overhang', 'low_side'):
                if key in choice:
                    section[key] = deepcopy(choice[key])
        roof = roofs.from_section(section)
        roof.setdefault('overhang', 1)
        if not roof.get('level'):
            roof['level'] = _bearing_level(building, roof['plate'])
        if choice is not None:
            roof['src'] = {**roof.get('src', {}), 'person': True}
        against = next((p for p in pinned if p['id'] == roof['id'] or twin_model._overlap(p['area'], roof['area'])
                        >= twin_model._area(roof['area']) * .5), None)
        if against is not None:
            if choice is None or migration or _roof_form(roof) == _roof_form(against):
                if _roof_form(roof) != _roof_form(against):
                    _proposal(building, 'roof', roof, against)
                continue
            # The person's new choice replaces their earlier roof there.
            building['roofs'].remove(against)
        old = next((r for r in previous.get('roofs', []) if r['id'] == roof['id']), None)
        if old is None:
            roof = roofs.attach_edges(roof, building['walls'], building['joints'])
        else:
            # A detached edge stays detached through a flat build write (R23).
            for edge, was in zip(roof['edges'], old['edges']):
                for key in ('wall', 'wall_offset'):
                    if key in was:
                        edge[key] = was[key]
        building['roofs'].append(roof)
    building['dormers'] = [deepcopy(d) for d in previous.get('dormers', []) if _person(d)]
    # A lost dormer has no drawable section, but its record still crosses the
    # flat boundary so it can be placed again on a later save.
    section_ids = {s['id'] for s in sections if s.get('dormer_of')}
    building['dormers'].extend(deepcopy(d) for d in cached_dormers
                               if d['id'] not in section_ids
                               and not any(p['id'] == d['id'] for p in building['dormers']))
    for section in sections:
        if not section.get('dormer_of') or any(d['id'] == section['id'] for d in building['dormers']):
            continue
        target = section['dormer_of']
        # The dormer's own roof first; else the roof whose outline its label
        # names, within the foot a build's snap may move a roof edge.
        known = old_dormers.get(section['id'], {}).get('roof')
        parent = next((r for r in building['roofs'] if r['id'] == known), None)
        if parent is None:
            gaps = [(max(abs(a - b) for a, b in zip(twin_model._bounds(r['area']), target)), r['id'], r)
                    for r in building['roofs']]
            parent = min((g for g in gaps if g[0] <= 1), default=(None, None, None), key=lambda g: g[:2])[2]
        if parent is not None:
            try:
                building['dormers'].append(roofs.dormer_from_section(section, parent))
                continue
            except ValueError:
                pass
        # Retain the complete failed read so placing it again loses no data.
        building['dormers'].append(dict(deepcopy(section), state='ghost'))
    by_id = {r['id']: r for r in building['roofs']}
    for dormer in building['dormers']:
        parent = by_id.get(dormer.get('roof'))
        if _dormer_sections(dormer, parent):
            continue
        dormer['state'], dormer['why'] = 'ghost', _DORMER
        at = twin_model._centroid(parent['area']) if parent else [0, 0]
        flag = {'text': _DORMER, 'at': at, 'piece': dormer['id'],
                'level': parent.get('level') if parent else dormer.get('level')}
        if flag not in building['flags']:
            building['flags'].append(flag)
            notes.append(_DORMER)
    for flag in flat_roof.get('flags', []):
        x0, y0, x1, y1 = flag['block_rect']
        converted = {**deepcopy(flag), 'at': [(x0 + x1) / 2, (y0 + y1) / 2]}
        existing = next((f for f in building['flags'] if f.get('text') == converted['text'] and f.get('at') == converted['at']), None)
        if existing is None:
            building['flags'].append(converted)
        else:
            existing['block_rect'] = deepcopy(flag['block_rect'])


def _openings(building, incoming, previous, read_walls):
    current_geometry, previous_geometry = hosts.snapshot(building), hosts.snapshot(previous)
    read_geometry = deepcopy(current_geometry)
    for wall in read_walls:
        if wall.get('state') != 'ghost':
            read_geometry['walls'][wall['id']] = {'a': wall['from'], 'b': wall['to'],
                                                 'level': wall['level'], 'thickness': wall.get('thickness', 0)}
    roof_ids = {r['id']: r for r in building['roofs']}
    pieces = [_flat_opening(o, roof_ids) for o in incoming]
    # As with walls, a person's opening that arrives still marked as theirs is
    # the caller's version (a build carries it onto a replacement carrier).
    mine = [p for p in pieces if _person(p)]
    ids = {p['id'] for p in mine}
    pinned = mine + [deepcopy(o) for o in previous.get('openings', []) if _person(o) and o['id'] not in ids]
    building['openings'] = list(pinned)

    def where(p):
        geometry = read_geometry if p['id'] in ids else previous_geometry
        return hosts._point(geometry, hosts._host(p, True))

    for piece in pieces:
        if _person(piece):
            continue
        identity = next((p for p in pinned if p['id'].split('~')[0] == piece['id'].split('~')[0]), None)

        def distance(p):
            try:
                return math.dist(hosts._point(read_geometry, hosts._host(piece, True)), where(p))
            except ValueError:
                return math.inf

        if identity is not None:
            if distance(identity) >= 1:
                _proposal(building, 'opening', piece, identity)
            continue

        def same_host(p):
            return ((piece.get('wall') is not None and piece.get('wall') == p.get('wall'))
                    or (piece.get('gable') is not None and piece.get('gable') == p.get('gable')))
        if any(distance(p) < 1 for p in pinned):
            continue
        against = next((p for p in pinned if same_host(p)
                        and min(piece['at'] + piece['width'] / 2, p['at'] + p['width'] / 2)
                        - max(piece['at'] - piece['width'] / 2, p['at'] - p['width'] / 2)
                        > piece['width'] / 2), None)
        if against is not None:
            _proposal(building, 'opening', piece, against)
        else:
            building['openings'].append(piece)


def _flat_opening(opening, roof_ids):
    piece = deepcopy(opening)
    if isinstance(piece.get('gable'), str):
        roof = roof_ids.get(piece.get('section'))
        if roof:
            # Section ends run from the lower to the higher ridge coordinate.
            axis = 0 if roof.get('ridge') == 'x' else 1
            value = min(p[axis] for p in roof['area']) if piece['gable'] == 'front' else max(p[axis] for p in roof['area'])
            edge = next(i for i, (a, b) in enumerate(_segments(roof['area']))
                        if abs(a[axis] - value) < _EPS and abs(b[axis] - value) < _EPS)
            a, b = list(_segments(roof['area']))[edge]
            centre = piece.get('y' if axis == 0 else 'x', (a[1 - axis] + b[1 - axis]) / 2)
            piece['at'] = abs(centre - a[1 - axis])
            piece['gable'] = {'roof': roof['id'], 'edge': edge}
        else:
            piece['gable'] = {'roof': piece.get('section'), 'edge': 0}
            piece.setdefault('at', 0)
    return piece


def _surface_host(building, point, level, kind):
    for room in building['rooms']:
        if room['level'] != level or room.get('state') in ('ghost', 'proposal'):
            continue
        # A tiny square also counts boundary points without another polygon API.
        x, y = point
        sample = [[x - _EPS, y - _EPS], [x + _EPS, y - _EPS],
                  [x + _EPS, y + _EPS], [x - _EPS, y + _EPS]]
        if twin_model._overlap(room['polygon'], sample) > 0:
            x0, y0, x1, y1 = twin_model._bounds(room['polygon'])
            return {kind: room['id'], 'u': (x - x0) / (x1 - x0), 'v': (y - y0) / (y1 - y0)}
    return None


def _fixture_host(building, piece, geometry=None):
    point, level, surface = piece['at'], piece['level'], piece['surface']
    if surface in ('ceiling', 'floor'):
        return _surface_host(building, point, level, surface)
    if surface != 'wall':
        return None
    geometry = geometry if geometry is not None else hosts.snapshot(building)
    candidates, named = [], []
    room_host = _surface_host(building, point, level, 'floor')
    room = geometry['rooms'].get((room_host or {}).get('floor'))
    for wid, wall in geometry['walls'].items():
        if wall['level'] != level:
            continue
        a, b = wall['a'], wall['b']
        length = math.dist(a, b)
        dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        at = max(0, min(length, (point[0] - a[0]) * dx + (point[1] - a[1]) * dy))
        side = 'left' if (point[1] - a[1]) * dx - (point[0] - a[0]) * dy >= 0 else 'right'
        host = {'wall': wid, 'side': side, 'at': at, 'z': 3.5}
        projected = [a[0] + dx * at, a[1] + dy * at]
        gap = math.dist(projected, point)
        if gap > 2:
            continue
        if wid == piece.get('wall') or wid.split('~')[0] == piece.get('wall'):
            named.append((gap, wid, host))
        if room and any(not _coverage(a, b, [{'from': c, 'to': d, 'level': level}], level)
                        for c, d in _segments(room['polygon'])):
            candidates.append((gap, wid, host))
    return min(named or candidates, default=(None, None, None), key=lambda c: c[:2])[2]


def _read_fixtures(building, fixtures):
    geometry = hosts.snapshot(building)
    person_spots = []
    for anchor in building['anchors']:
        if _person(anchor) and twin_model._host_error(anchor.get('host'), building) is None:
            surface = hosts._surface(geometry, anchor['host'])
            if surface:
                person_spots.append((surface.get('level'), hosts._point(geometry, anchor['host'])[:2]))
    # A rooms read can replace the draft's derived room. Recover generated
    # anchors from their read coordinates; a person's chosen host stays theirs.
    lost = [p for p in building['anchors'] if not _person(p) and 'surface' in p and 'at' in p
            and twin_model._host_error(p.get('host'), building) is not None]
    lost_ids = {p['id'] for p in lost}
    building['anchors'] = [p for p in building['anchors'] if p['id'] not in lost_ids]
    for index, detail in enumerate([*fixtures, *lost]):
        piece = deepcopy(detail)
        piece.setdefault('id', f'fixtures-{index + 1}')
        building['flags'] = [f for f in building['flags']
                             if not (isinstance(f.get('piece'), dict)
                                     and f['piece'].get('fixture', {}).get('id') == piece['id'])]
        if any(p['id'] == piece['id'] for p in building['anchors']):
            continue
        piece['src'] = piece.get('src') or {'sheet': '', 'page': 0, 'step': 'draft'}
        piece['kind'] = twin_plan.fixture_kind(piece['kind'])
        host = _fixture_host(building, piece, geometry)
        if (host is None or twin_model._host_error(host, building) is not None
                or piece['kind'] not in ('light', 'switch', 'outlet', 'fan', 'camera', 'sensor')):
            text = (f"This fixture has an unknown kind ({detail['kind']}); choose its kind."
                    if piece['kind'] not in ('light', 'switch', 'outlet', 'fan', 'camera', 'sensor')
                    else f"This {detail['kind']} has no valid surface; place it again.")
            flag = {'level': piece['level'], 'at': list(piece['at']), 'text': text,
                    'piece': {'fixture': piece}}
            if flag not in building['flags']:
                building['flags'].append(flag)
            continue
        point = hosts._point(geometry, host)
        occupied = any(level == piece['level'] and math.dist(point[:2], spot) <= .5
                       for level, spot in person_spots)
        if not occupied:
            piece['host'] = host
            piece.setdefault('offset', 0)
            piece.setdefault('device', None)
            building['anchors'].append(piece)


def _details(building, flat, previous):
    for name in ('anchors', 'items', 'stairs'):
        pinned = [deepcopy(p) for p in previous.get(name, []) if _person(p)]
        ids = {p['id'] for p in pinned}
        building[name] = pinned + [deepcopy(p) for p in flat.get(name, []) if p.get('id') not in ids]
    pinned = {p['id']: deepcopy(p) for p in previous.get('devices', []) if _person(p)}
    building['devices'] = [pinned.pop(p['id'], deepcopy(p))
                           for p in flat.get('devices', previous.get('devices', []))]
    building['devices'].extend(pinned.values())
    _read_fixtures(building, [p for p in flat.get('fixtures', []) if 'rect' not in p])
    for name, target, surface in (('lights', 'anchors', 'ceiling'), ('fixtures', 'items', 'floor')):
        for index, detail in enumerate(flat.get(name, [])):
            if name == 'fixtures' and 'rect' not in detail:
                continue
            piece = deepcopy(detail)
            piece.setdefault('id', f'{name}-{index + 1}')
            if any(p['id'] == piece['id'] for p in building[target]):
                continue
            if name == 'lights':
                point = piece['at']
                piece.update(kind='light', offset=0, device=None)
            else:
                x0, y0, x1, y1 = piece['rect']
                point = [(x0 + x1) / 2, (y0 + y1) / 2]
                piece.setdefault('asset', piece.get('kind', 'fixture'))
                piece.setdefault('rotation', 0)
                piece.setdefault('scale', piece.get('size', max(x1 - x0, y1 - y0)))
            host = _surface_host(building, point, piece['level'], surface)
            if host is not None:
                piece['host'] = host
            else:
                piece.update(host={}, state='ghost', position=list(point))
                text = f"This {piece.get('kind', piece.get('asset', 'item'))} lost its surface; place it again."
                piece['why'] = text
                building['flags'].append({'level': piece['level'], 'at': list(point),
                                          'text': text, 'piece': piece['id']})
            building[target].append(piece)


_RESTORE_OVERLAP = 0.5  # sq ft; rounding slivers between neighbours stay below it


def _restore_polygons(building, stored, replaced):
    derived = {}
    for room in building['rooms']:
        polygon = stored.get(room['id'])
        # A derived Room's outline is only the walls' cache: never an older one.
        if not twin_plan._polygon(polygon) or twin_model.derived_room(room):
            continue
        # A reread's cached boundary cannot undo a person's moved partition.
        moved_boundary = any(w['level'] == room['level'] and
                             not _coverage(a, b, [w], room['level'])
                             for a, b in _segments(polygon) for w in replaced)
        if (not moved_boundary and twin_model._overlap(polygon, room['polygon']) + _EPS
                >= twin_model._area(room['polygon']) * .25):
            derived[room['id']] = room['polygon']
            room['polygon'] = deepcopy(polygon)
    # A stored outline that lies over a neighbour would draw two floors on one
    # patch; that room shows its derived region, the one every edit keeps.
    # Rooms over a derived neighbour yield first (until nothing changes), so a
    # room that only touched such a stored outline keeps its own.
    def over(room, others):
        return any(other is not room and other['level'] == room['level']
                   and twin_plan._polygon(other.get('polygon'))
                   and twin_model._overlap(room['polygon'], other['polygon']) > _RESTORE_OVERLAP
                   for other in others)

    while True:
        changed = True
        while changed:
            changed = False
            fixed = [r for r in building['rooms'] if r['id'] not in derived]
            for room in building['rooms']:
                if room['id'] in derived and over(room, fixed):
                    room['polygon'] = derived.pop(room['id'])
                    changed = True
        # Two stored outlines over each other: both show their regions.
        stored_over = [r for r in building['rooms'] if r['id'] in derived and over(r, building['rooms'])]
        if not stored_over:
            break
        for room in stored_over:
            room['polygon'] = derived.pop(room['id'])


def _separator_flags(building):
    flags = [f for f in building['flags'] if f.get('text', '').startswith('I added ')
             and 'invisible wall' in f.get('text', '')]
    building['flags'] = [f for f in building['flags'] if f not in flags]
    joints = {j['id']: j['at'] for j in building['joints']}
    separators = [w for w in building['walls'] if w.get('kind') == 'separator'
                  and w.get('src', {}).get('step') in ('migration', 'rooms')]
    for old in flags:
        members = old.get('separators')
        pieces = [w for w in separators if w['level'] == old.get('level')
                  and (any(w['id'] == wid or w['id'].startswith(wid + '~') for wid in members)
                       if members is not None else w.get('src', {}).get('step') == 'migration')]
        if not pieces:
            continue
        for wall in pieces:
            wall['flagged'] = True
        text = _SEPARATOR if ' invisible walls on the ' in old['text'] else old['text']
        if len(pieces) > 1:
            level = next(l for l in building['levels'] if l['id'] == old['level'])
            text = f"I added {len(pieces)} invisible walls on the {level['name']} to keep rooms apart; check them."
        a, b = _line(pieces[0], joints)
        building['flags'].append({**old, 'at': [(x + y) / 2 for x, y in zip(a, b)],
                                  'text': text, 'piece': pieces[0]['id'],
                                  'separators': [w['id'] for w in pieces]})
    for level in building['levels']:
        pieces = [w for w in separators if w['level'] == level['id'] and not w.get('flagged')]
        if not pieces:
            continue
        for wall in pieces:
            wall['flagged'] = True
        text = (_SEPARATOR if len(pieces) == 1 else
                f"I added {len(pieces)} invisible walls on the {level['name']} to keep rooms apart; check them.")
        a, b = _line(pieces[0], joints)
        building['flags'].append({'level': level['id'], 'at': [(x + y) / 2 for x, y in zip(a, b)],
                                  'text': text, 'piece': pieces[0]['id'],
                                  'separators': [w['id'] for w in pieces]})


def assemble(flat: dict, previous: dict | None = None) -> tuple[dict, list[str]]:
    """Migrate a flat read, preserving person-owned pieces from the last model."""
    flat = deepcopy(flat)
    if flat.get('units') != 'ft':
        raise ValueError('Twin plan units must be ft.')
    notes = []
    room_reads = {}
    flat['solar_source_building'] = (previous or {}).get('solar_source_building', flat.get('solar_source_building'))
    flat['solar_source_roof'] = (previous or {}).get('solar_source_roof', flat.get('solar_source_roof'))
    old_buildings = {b['id']: b for b in (previous or {}).get('buildings', [])}
    for building in flat.get('buildings', []):
        old = old_buildings.get(building['id'], {})
        source = deepcopy(building)
        if old.get('foundation_src', {}).get('person'):
            building['foundation'] = deepcopy(old['foundation'])
            building['foundation_src'] = deepcopy(old['foundation_src'])
        building['solar_zones'] = deepcopy(old.get('solar_zones', source.get('solar_zones', [])))
        building['proposals'] = deepcopy(old.get('proposals', source.get('proposals', [])))
        for proposal in building['proposals']:
            proposal['id'] = proposal['piece']['id']
        building['flags'] = deepcopy(source.get('flags', old.get('flags', [])))
        building['checked_flags'] = deepcopy(old.get('checked_flags', source.get('checked_flags', [])))
        building['rooms'] = deepcopy(source.get('rooms', []))
        mine = {r['id'] for r in building['rooms'] if _person(r)}
        for room in old.get('rooms', []):
            if _person(room) and room['id'] not in mine:
                building['rooms'] = [r for r in building['rooms'] if r['id'] != room['id']] + [deepcopy(room)]
        porches = deepcopy(twin_plan.porches(source))
        building['porches_detail'] = porches
        for index, porch in enumerate(porches):
            porch.setdefault('id', f'porch-{index + 1}')
            room = {k: deepcopy(v) for k, v in porch.items() if k in ('id', 'polygon', 'src', 'state')}
            room.update(kind='porch', name=porch.get('name', 'Porch'),
                        level=porch.get('level', building['levels'][0]['id']))
            room['foundation'] = deepcopy(porch.get('foundation', twin_porches.DEFAULT))
            if not any(r['id'] == room['id'] for r in building['rooms']):
                building['rooms'].append(room)
            else:
                existing = next(r for r in building['rooms'] if r['id'] == room['id'])
                existing.setdefault('foundation', room['foundation'])
        building['rooms'] = _displace_derived(building['rooms'])
        replaced = []
        walls = _walls(building, source.get('walls', []), old, replaced)
        # Only displaced reads suppress closure; an unchanged person's wall
        # already covers the boundary itself.
        replaced = [w for w in replaced if _coverage(w['from'], w['to'], walls, w['level'])]
        _separators(building, walls, building['rooms'], migration=previous is None, replaced=replaced)
        _network(building, walls, old)
        _roofs(building, source.get('roof', {}), old, source.get('dormers', []), notes,
               migration=previous is None)
        building['extensions'] = deepcopy(source.get('roof', {}).get('extensions', []))
        _openings(building, source.get('openings', []), old, source.get('walls', []))
        building['anchors'], building['items'] = [], []
        before = hosts.snapshot(building)
        ghosts = [r for r in building['rooms'] if r.get('state') == 'ghost']
        building['rooms'] = [r for r in building['rooms'] if r.get('state') != 'ghost']
        stored_polygons = {r['id']: r.get('polygon') for r in building['rooms']}
        room_reads[building['id']] = (ghosts, replaced)
        notes.extend(twin_model.derive(building))
        # A derived Room whose walls were replaced leaves no unclosed-room flag:
        # no wall is missing, the walls changed.
        building['flags'] = [f for f in building['flags'] if f.get('text') != twin_model.NOT_CLOSED
                             or not twin_model.derived_room(twin_model._flag_room(f))]
        _restore_polygons(building, stored_polygons, replaced)
        _details(building, source, old)
        # Keep an invalid read at its location rather than invoking the editing clamp.
        geometry = hosts.snapshot(building)
        for opening in building['openings']:
            host = hosts._host(opening, True)
            available = hosts._available(geometry, host, 'gable' in opening)
            line = hosts._line(geometry, host) if available else None
            fits = line is not None and (opening['at'] - opening['width'] / 2 >= -_EPS
                                         and opening['at'] + opening['width'] / 2 <= math.dist(*line) + _EPS)
            if not available or not fits:
                hosts._lost(building, opening, host, before, notes, fits=not available)
                opening.setdefault('position', next(f['at'] for f in building['flags']
                                                     if f.get('piece') == opening['id']))
        for key in ('roof', 'lights', 'fixtures', 'porch', 'porches'):
            building.pop(key, None)
        building.setdefault('stairs', [])
    normalized, validation_notes = twin_model.normalize(flat)
    sources = {b['id']: b for b in flat['buildings']}
    for building in normalized['buildings']:
        source = sources[building['id']]
        ghosts, replaced = room_reads[building['id']]
        polygons = {r['id']: r.get('polygon') for r in source['rooms']}
        _restore_polygons(building, polygons, replaced)
        building['rooms'].extend(deepcopy(ghosts))
        _separator_flags(building)
        live_ids = {p['id'] for name in ('walls', 'rooms', 'roofs', 'dormers', 'openings', 'anchors', 'items', 'devices')
                    for p in building.get(name, [])}
        building['flags'] = [f for f in building['flags'] if not isinstance(f.get('piece'), str)
                             or f['piece'] in live_ids]
    # The bridge must not rewrite site facts while changing the building schema.
    normalized['site'] = deepcopy(flat.get('site', {}))
    fire = normalized['site'].get('fire_pit')
    for pit in fire if isinstance(fire, list) else [fire] if isinstance(fire, dict) else []:
        if isinstance(pit, dict):
            pit.setdefault('shape', 'round')
    return normalized, notes + validation_notes


def flatten(model: dict) -> dict:
    """Return renderer-compatible schema 2 geometry and connected-model extras."""
    flat = deepcopy(model)
    flat['schema'] = twin_plan.SCHEMA
    for building in flat.get('buildings', []):
        building['walls'] = [w for w in building.get('walls', []) if w.get('state') != 'proposal']
        points = {j['id']: j['at'] for j in building.get('joints', [])}
        for level in building['levels']:
            joints = {j['id']: j['at'] for j in building['joints'] if j['level'] == level['id']}
            walls = [w for w in building['walls'] if w['level'] == level['id']]
            derived, split = graph.split_crossings(joints, [w for w in walls if w.get('state') != 'ghost'])
            for jid, at in derived.items():
                if jid not in joints:
                    building['joints'].append({'id': jid, 'level': level['id'], 'at': at, 'derived': True})
            footprints = graph.footprints(joints, walls)
            split_footprints = graph.footprints(derived, split)
            # T-junctions affect the faces even though the read's wall stays whole.
            runs, owner = {}, None
            wall_ids = {w['id'] for w in walls}
            for part in split:
                if part['id'] in wall_ids:
                    owner = part['id']
                if part['id'] in split_footprints:
                    runs.setdefault(owner, []).append(split_footprints[part['id']])
            for wid, parts in runs.items():
                footprints[wid] = [parts[0][0], parts[-1][1], parts[-1][2], parts[0][3]]
            for wall in walls:
                wall.update({'from': list(points[wall['joints'][0]]), 'to': list(points[wall['joints'][1]])})
                if wall['id'] in footprints:
                    wall['footprint'] = footprints[wall['id']]
        roof_by_id = {r['id']: r for r in building.get('roofs', []) if r.get('state') != 'proposal'}
        sections = [s for roof in roof_by_id.values() for s in roofs.to_sections(roof)]
        for dormer in building.get('dormers', []):
            if dormer.get('state') not in ('ghost', 'proposal') and dormer.get('roof') in roof_by_id:
                sections.extend(_dormer_sections(dormer, roof_by_id[dormer['roof']]))
        for section in sections:
            if section.get('ends') and all(style == section['kind'] for style in section['ends'].values()):
                section.pop('ends')
        building['roof'] = {'sections': sections, 'extensions': deepcopy(building.get('extensions', [])),
                            'flags': [{k: deepcopy(v) for k, v in f.items() if k != 'at'}
                                      for f in building.get('flags', []) if 'block_rect' in f]}
        choices = [{**{k: deepcopy(s[k]) for k in ('kind', 'ridge', 'ends', 'pitch', 'plate',
                                                    'overhang', 'low_side') if k in s},
                    'rect': deepcopy(s['block']), 'src': {'person': True}}
                   for s in sections if s.get('src', {}).get('person') and s.get('block')
                   and not s.get('dormer_of')
                   and max(abs(a - b) for a, b in zip(s['rect'], s['block'])) <= 1]
        if choices:
            # Legacy cards read choices; ownership remains the schema-3 truth.
            building['roof']['choices'] = choices
        openings = []
        for opening in building.get('openings', []):
            if opening.get('state') == 'proposal':
                continue
            wall = next((w for w in walls if w['id'] == opening.get('wall')), None)
            if wall is not None and twin_plan._number(opening.get('at')):
                from services.twin_floors import opening_reference
                reference, step = opening_reference(building, wall, opening['at'])
                if reference:
                    opening['floor_reference_ft'] = reference
                else:
                    opening.pop('floor_reference_ft', None)
                if step:
                    opening['step_down_ft'] = step
                else:
                    opening.pop('step_down_ft', None)
            if isinstance(opening.get('gable'), dict):
                host = opening['gable']
                roof = roof_by_id.get(host.get('roof'))
                if roof is not None and type(host.get('edge')) is int and 0 <= host['edge'] < len(roof['area']):
                    a, b = list(_segments(roof['area']))[host['edge']]
                    length = math.dist(a, b)
                    axis = 0 if abs(a[0] - b[0]) < _EPS else 1
                    point = [a[i] + (b[i] - a[i]) * opening['at'] / length for i in (0, 1)]
                    section = next((s for s in sections if s.get('roof') == roof['id']
                                    and all(s['rect'][i] - _EPS <= point[i] <= s['rect'][i + 2] + _EPS for i in (0, 1))), None)
                    opening.update(gable='front' if a[axis] == min(p[axis] for p in roof['area']) else 'rear',
                                   section=section['id'] if section else roof['id'])
                    opening['y' if axis == 0 else 'x'] = point[1 - axis]
            openings.append(opening)
        building['openings'] = openings
        building['lights'], building['fixtures'] = [], []
        geometry = hosts.snapshot(building)
        for name, target in (('anchors', 'lights'), ('items', 'fixtures')):
            for piece in building.get(name, []):
                if name == 'anchors' and piece.get('kind') != 'light':
                    continue
                if name == 'items' and 'rect' not in piece:
                    continue
                detail = deepcopy(piece)
                surface = hosts._surface(geometry, piece.get('host', {}))
                if surface is not None:
                    detail['level'] = surface.get('level')
                try:
                    point = hosts.world_point(building, piece['host'], piece.get('offset', 0))[:2]
                except ValueError:
                    point = piece.get('position', piece.get('at'))
                if point is None:
                    continue
                if name == 'anchors':
                    detail['at'] = list(point)
                else:
                    x0, y0, x1, y1 = detail['rect']
                    width, depth = x1 - x0, y1 - y0
                    detail['rect'] = [point[0] - width / 2, point[1] - depth / 2,
                                      point[0] + width / 2, point[1] + depth / 2]
                building[target].append(detail)
        building['porches'] = deepcopy(building.get('porches_detail', []))
        # The room owns person edits; the detail supplies the read columns and
        # deck height. Never let a stale detail undo a foundation shelf edit.
        for room in building['rooms']:
            if room.get('kind') != 'porch' or room.get('state') == 'ghost' or not twin_plan._polygon(room.get('polygon')):
                continue
            porch = next((p for p in building['porches'] if p.get('id') == room['id']), None)
            if porch is None:
                if room.get('foundation', {}).get('type') != 'solid':
                    continue
                porch = {'id': room['id'], 'floor': next(l['elevation'] for l in building['levels'] if l['id'] == room['level']), 'columns': []}
                building['porches'].append(porch)
            porch['foundation'] = deepcopy(room.get('foundation', twin_porches.DEFAULT))
            if porch['foundation']['type'] == 'solid':
                porch.update(polygon=deepcopy(room['polygon']), level=room['level'])
    return flat
