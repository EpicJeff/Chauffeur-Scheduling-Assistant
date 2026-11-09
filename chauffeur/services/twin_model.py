"""Schema 3 validation and room identities over a connected wall network."""

from copy import deepcopy
import math
import re

from services import twin_model_graph as graph
from services import twin_model_hosts as hosts
from services import twin_plan


SCHEMA = 'chauffeur.twin.plan/3'
CAPS = {'walls': 400, 'joints': 800, 'openings': 400, 'rooms': 120,
        'roofs': 40, 'anchors': 400, 'items': 600}
NOT_CLOSED = "This room isn't closed: a wall is missing here."
_EPS = 1e-9


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _area(polygon):
    return abs(sum(_cross(a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2


def _piece_meta(items, kind, notes):
    # The graph's split ids contain '~', which schema 2's metadata helper
    # predates. Alias them only while reusing its provenance validation.
    reserved = {p.get('id') for p in items if isinstance(p.get('id'), str)}
    aliases, originals = {}, {}
    for piece in items:
        pid = piece.get('id')
        if isinstance(pid, str) and '~' in pid and re.fullmatch(r'[A-Za-z0-9_.:~-]{1,64}', pid):
            if pid not in aliases:
                alias = f'meta-{len(aliases) + 1}'
                while alias in reserved:
                    alias += ':'
                reserved.add(alias)
                aliases[pid], originals[alias] = alias, pid
            piece['id'] = aliases[pid]
    twin_plan._piece_meta(items, kind, notes)
    for piece in items:
        piece['id'] = originals.get(piece['id'], piece['id'])


def _centroid(polygon):
    pairs = list(zip(polygon, polygon[1:] + polygon[:1]))
    area2 = sum(_cross(a, b) for a, b in pairs)
    if abs(area2) <= _EPS:
        return [sum(p[i] for p in polygon) / len(polygon) for i in (0, 1)] if polygon else [0, 0]
    return [sum((a[i] + b[i]) * _cross(a, b) for a, b in pairs) / (3 * area2)
            for i in (0, 1)]


def _bounds(polygon):
    return (min(p[0] for p in polygon), min(p[1] for p in polygon),
            max(p[0] for p in polygon), max(p[1] for p in polygon))


def _overlap(left, right, left_bounds=None, right_bounds=None):
    """Integrate shared vertical intervals, including concave or angled rooms.

    Between vertices and edge crossings, interval ends are linear in x, so
    the midpoint rule gives the exact area of each strip.
    """
    lb, rb = left_bounds or _bounds(left), right_bounds or _bounds(right)
    lo, hi = max(lb[0], rb[0]), min(lb[2], rb[2])
    if hi <= lo or min(lb[3], rb[3]) <= max(lb[1], rb[1]):
        return 0
    edges = [list(zip(poly, poly[1:] + poly[:1])) for poly in (left, right)]
    cuts = {lo, hi, *(p[0] for poly in (left, right) for p in poly if lo < p[0] < hi)}
    for a, b in edges[0]:
        for c, d in edges[1]:
            v, w = [b[i] - a[i] for i in (0, 1)], [d[i] - c[i] for i in (0, 1)]
            denominator = _cross(v, w)
            if abs(denominator) <= _EPS:
                continue
            delta = [c[i] - a[i] for i in (0, 1)]
            t, u = _cross(delta, w) / denominator, _cross(delta, v) / denominator
            if 0 < t < 1 and 0 < u < 1:
                x = a[0] + t * v[0]
                if lo < x < hi:
                    cuts.add(x)
    area = 0
    ordered = sorted(cuts)
    for x0, x1 in zip(ordered, ordered[1:]):
        x = (x0 + x1) / 2
        intervals = []
        for boundary in edges:
            ys = sorted(a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
                        for a, b in boundary if min(a[0], b[0]) < x < max(a[0], b[0]))
            intervals.append(list(zip(ys[::2], ys[1::2])))
        area += (x1 - x0) * sum(max(0, min(b, d) - max(a, c))
                               for a, b in intervals[0] for c, d in intervals[1])
    return area


def _cap(items, name, notes):
    cap = CAPS.get(name)
    if cap is not None and len(items) > cap:
        notes.append(f'Dropped {len(items) - cap} items from {name}; the cap is {cap}.')
        return items[:cap]
    return items


def _list(owner, name, notes, kind=None, *, capped=True):
    items = owner.get(name, [])
    if not isinstance(items, list):
        notes.append(f'Dropped invalid {name} list; expected a list.')
        items = []
    if capped:
        items = _cap(items, name, notes)
    kept = [item for item in items if isinstance(item, dict)]
    if len(kept) != len(items):
        notes.append(f'Dropped invalid {name} entries; expected objects.')
    if kind:
        _piece_meta(kept, kind, notes)
    owner[name] = kept
    return kept


def _flag_room(flag):
    piece = flag.get('piece')
    return piece.get('room') if isinstance(piece, dict) else None


def _room_position(room, valid):
    polygon = room.get('polygon')
    if valid:
        return _centroid(polygon)
    if isinstance(polygon, list):
        return next((list(p) for p in polygon if twin_plan._point(p)), [0, 0])
    return [0, 0]


def _joint_references(walls):
    return {j for w in walls if isinstance(w.get('joints'), list)
            for j in w['joints'] if isinstance(j, str)}


def _split_t_junctions(building, joints, walls, notes):
    """Persist only endpoint splits; proper crossings remain a derivation view."""
    before = hosts.snapshot({'joints': building.get('joints', []), 'walls': walls})
    _, split = graph.split_crossings(joints, walls, proper=False)
    old = {w['id']: w for w in walls}
    # split_crossings emits each wall's segments consecutively, first with its
    # original id.
    segments, source = {}, None
    for wall in split:
        if wall['id'] in old:
            source = wall['id']
        segments.setdefault(source, []).append(wall)
    building['walls'] = _cap([part for w in building.get('walls', [])
                              for part in segments.get(w['id'], [w])], 'walls', notes)
    hosts.carry_split(building, before)
    kept = {w['id'] for w in building['walls']}
    return [w for w in split if w['id'] in kept]


def _derive(building, notes, *, persist_t_splits=True):
    ghosts = [room for room in building.get('rooms', []) if room.get('state') == 'ghost']
    stored = [room for room in building.get('rooms', []) if room.get('state') != 'ghost']
    seen = {room.get('id') for room in stored + ghosts}
    flags = []
    for flag in building.get('flags', []):
        if flag.get('text') != NOT_CLOSED:
            flags.append(flag)
            continue
        room = _flag_room(flag)
        if isinstance(room, dict) and room.get('id') not in seen:
            stored.append(deepcopy(room))
            seen.add(room.get('id'))
    _piece_meta(stored + ghosts, 'room', notes)
    valid = [twin_plan._polygon(room.get('polygon')) for room in stored]
    bounds = [_bounds(room['polygon']) if ok else None for room, ok in zip(stored, valid)]
    areas = [_area(room['polygon']) if ok else 0 for room, ok in zip(stored, valid)]
    room_cap_notes = []
    stored_kept = _cap(list(range(len(stored))), 'rooms', room_cap_notes)
    for room, ok in zip(stored, valid):
        if not ok:
            notes.append(f"Room {room['id']}: invalid cached polygon; kept in an unclosed flag.")

    candidates, ends = [], []
    referenced = _joint_references(building.get('walls', []))
    building['joints'] = [j for j in building.get('joints', []) if j['id'] in referenced]
    for level in building.get('levels', []):
        lid = level['id']
        joints = {j['id']: j['at'] for j in building.get('joints', []) if j.get('level') == lid}
        walls = [w for w in building.get('walls', []) if w.get('level') == lid
                 and w.get('state') != 'ghost' and isinstance(w.get('joints'), list)
                 and len(w['joints']) == 2
                 and all(isinstance(j, str) and j in joints for j in w['joints'])
                 and math.dist(*(joints[j] for j in w['joints'])) > _EPS]
        if persist_t_splits:
            walls = _split_t_junctions(building, joints, walls, notes)
        # Use a split view for faces; original walls retain their host identities.
        split_joints, split_walls = graph.split_crossings(joints, walls)
        for region in graph.regions(split_joints, split_walls):
            if not twin_plan._polygon(region['polygon']):
                continue
            # Temporary crossing ids may be reused at another crossing after a
            # drag. Only stored joint identities are safe identity evidence.
            region['identity_joints'] = {j for j in region['joints'] if j in joints}
            region['level'] = lid
            candidates.append(region)
        ends.extend((lid, point) for point in graph.open_ends(split_joints, split_walls))

    inherited, owners = {}, set()
    joint_pairs = []
    for index, region in enumerate(candidates):
        cycle = region['identity_joints']
        stored_ids = {j['id'] for j in building['joints'] if j.get('level') == region['level']}
        for owner in stored_kept:
            room = stored[owner]
            if not valid[owner] or room.get('level') != region['level']:
                continue
            cached = room.get('joints', [])
            if not isinstance(cached, list):
                cached = []
            cached = {j for j in cached if isinstance(j, str) and j in stored_ids}
            union = cycle | cached
            score = len(cycle & cached) / len(union) if union else 0
            if score >= 0.5:
                joint_pairs.append((score, region['area'], index, owner))
    for _, _, index, owner in sorted(joint_pairs, reverse=True):
        if index not in inherited and owner not in owners:
            inherited[index] = owner
            owners.add(owner)

    overlap_pairs = []
    for index, region in enumerate(candidates):
        if index in inherited:
            continue
        rb = _bounds(region['polygon'])
        for owner in stored_kept:
            room = stored[owner]
            if owner in owners or not valid[owner] or areas[owner] <= _EPS or room.get('level') != region['level']:
                continue
            overlap = _overlap(region['polygon'], room['polygon'], rb, bounds[owner])
            if overlap + _EPS >= region['area'] * 0.25:
                overlap_pairs.append((overlap / areas[owner], overlap, region['area'], index, owner))
    for _, _, _, index, owner in sorted(overlap_pairs, reverse=True):
        if index not in inherited and owner not in owners:
            inherited[index] = owner
            owners.add(owner)
    candidates_kept = _cap(list(range(len(candidates))), 'rooms', room_cap_notes)
    notes.extend(room_cap_notes[:1])
    inherited = {index: owner for index, owner in inherited.items() if index in candidates_kept}
    rooms = []
    for index in candidates_kept:
        region = candidates[index]
        room = deepcopy(stored[inherited[index]]) if index in inherited else {'name': 'Room', 'kind': 'room'}
        room.update({key: region[key] for key in ('level', 'polygon', 'joints')})
        room.setdefault('kind', 'room')
        rooms.append(room)
    # Reserve even lost identities, so a newly discovered Room cannot take one.
    _piece_meta(stored + ghosts + [room for index, room in zip(candidates_kept, rooms)
                         if index not in inherited], 'room', notes)
    # Located read ghosts do not claim floor regions or disappear on an edit.
    building['rooms'] = rooms + ghosts
    for owner, room in enumerate(stored):
        if owner not in inherited.values():
            flags.append({'level': room.get('level'),
                          'at': _room_position(room, valid[owner] and owner in stored_kept),
                          'text': NOT_CLOSED, 'piece': {'room': deepcopy(room)}})
    for lid, point in ends:
        if not any(f.get('text') == NOT_CLOSED and f.get('level') == lid
                   and math.dist(point, f['at']) <= 1 for f in flags):
            flags.append({'level': lid, 'at': point, 'text': NOT_CLOSED})
    building['flags'] = flags
    referenced = _joint_references(building.get('walls', []))
    building['joints'] = [j for j in building['joints'] if j['id'] in referenced]
    return building


def derive(building: dict, *, persist_t_splits=True) -> list[str]:
    """Rebuild room caches; flat-read assembly can keep T-splits derived (R31)."""
    notes = []
    _derive(building, notes, persist_t_splits=persist_t_splits)
    return notes


def _note(piece, kind, reason, notes):
    notes.append(f"{kind} {piece['id']}: {reason}.")


def _network(building, levels, notes):
    joints = {}
    for joint in _list(building, 'joints', notes, 'joint'):
        if twin_plan._lookup(levels, joint.get('level')) is None or not twin_plan._point(joint.get('at')):
            notes.append(f"Dropped joint {joint['id']}: invalid position or level.")
        else:
            joints[joint['id']] = joint
    building['joints'] = list(joints.values())
    walls = _list(building, 'walls', notes, 'wall')
    for wall in walls:
        wall.setdefault('kind', 'solid')
        wall.setdefault('exterior', False)
        wall.setdefault('thickness', 0.5 if wall['exterior'] else 0.33)
        if wall['kind'] == 'separator':
            wall['thickness'] = 0
        endpoints = wall.get('joints')
        if (twin_plan._lookup(levels, wall.get('level')) is None or wall['kind'] not in ('solid', 'separator')
                or not isinstance(endpoints, list) or len(endpoints) != 2
                or any(not isinstance(j, str) or j not in joints
                       or joints[j]['level'] != wall.get('level') for j in endpoints)
                or math.dist(*(joints[j]['at'] for j in endpoints)) <= _EPS
                or not twin_plan._number(wall['thickness']) or wall['thickness'] < 0
                or (wall['kind'] == 'solid' and wall['thickness'] == 0)
                or ('height' in wall and (not twin_plan._number(wall['height']) or wall['height'] <= 0))):
            _note(wall, 'Wall', 'invalid joints, level or dimensions', notes)


def _host_error(host, building):
    if not isinstance(host, dict):
        return 'missing host'
    kinds = [key for key in ('wall', 'floor', 'ceiling', 'ground', 'roof') if key in host]
    if len(kinds) != 1:
        return 'invalid host'
    kind = kinds[0]
    if kind == 'ground':
        return None if host['ground'] is True and twin_plan._point(host.get('at')) else 'invalid ground host'
    collection = 'walls' if kind == 'wall' else 'roofs' if kind == 'roof' else 'rooms'
    target = next((p for p in building[collection] if p['id'] == host[kind]), None)
    if target is None or target.get('state') == 'ghost':
        return f'unknown {kind} host {host[kind]}'
    if kind == 'wall':
        valid = host.get('side') in ('left', 'right') and all(twin_plan._number(host.get(k)) for k in ('at', 'z'))
    elif kind == 'roof':
        valid = (isinstance(target.get('area'), list) and type(host.get('edge')) is int
                 and 0 <= host['edge'] < len(target['area'])
                 and twin_plan._number(host.get('at')))
    else:
        valid = all(twin_plan._number(host.get(k)) and 0 <= host[k] <= 1 for k in ('u', 'v'))
    return None if valid else f'invalid {kind} host coordinates'


def _pieces(building, notes):
    roofs = _list(building, 'roofs', notes, 'roof')
    for roof in roofs:
        edges = roof.get('edges')
        if (not twin_plan._polygon(roof.get('area')) or not isinstance(edges, list)
                or len(edges) != len(roof['area'])
                or not all(isinstance(e, dict) and e.get('setting') in ('sloped', 'gable', 'clip')
                           and twin_plan._numeric_fields(e, ('pitch', 'clip')) for e in edges)
                or not all(twin_plan._number(roof.get(k)) for k in ('plate', 'overhang'))):
            _note(roof, 'Roof', 'invalid area, edges or dimensions', notes)
    walls = {w['id']: w for w in building['walls']}
    roof_ids = {r['id']: r for r in roofs}
    for opening in _list(building, 'openings', notes, 'opening'):
        reason = None
        if 'gable' in opening:
            gable = opening['gable']
            roof = twin_plan._lookup(roof_ids, gable.get('roof')) if isinstance(gable, dict) else None
            if (roof is None or roof.get('state') == 'ghost' or not isinstance(roof.get('area'), list)
                    or type(gable.get('edge')) is not int
                    or not 0 <= gable['edge'] < len(roof['area'])):
                reason = 'unknown gable host'
        else:
            wall = twin_plan._lookup(walls, opening.get('wall'))
            if wall is None:
                reason = f"unknown wall {opening.get('wall')}"
                if opening.get('state') != 'ghost' or opening.get('ghost_by') == 'normalize':
                    opening['state'] = 'ghost'
                    opening['ghost_by'] = 'normalize'
                    if 'why' not in opening:
                        opening['why'] = reason
                        opening['normalize_why'] = reason
            elif opening.get('ghost_by') == 'normalize':
                opening['state'] = 'settled'
                del opening['ghost_by']
                own_why = opening.pop('normalize_why', None)
                if own_why is not None and opening.get('why') == own_why:
                    opening.pop('why', None)
        if not reason and (not all(twin_plan._number(opening.get(k)) for k in ('at', 'width', 'sill', 'head'))
                           or opening['width'] <= 0 or opening['head'] <= opening['sill']):
            reason = 'invalid opening dimensions'
        if reason:
            _note(opening, 'Opening', reason, notes)
    for name, kind in (('anchors', 'anchor'), ('items', 'item')):
        for item in _list(building, name, notes, kind):
            reason = _host_error(item.get('host'), building)
            if name == 'anchors':
                item.setdefault('offset', 0)
                item.setdefault('device', None)
                if item.get('kind') not in ('light', 'switch', 'outlet', 'fan', 'camera', 'sensor'):
                    reason = reason or 'invalid anchor kind'
                if not twin_plan._number(item['offset']):
                    reason = reason or 'invalid offset'
            else:
                item.setdefault('rotation', 0)
                item.setdefault('scale', 1)
                if (not isinstance(item.get('asset'), str) or not twin_plan._number(item['rotation'])
                        or not twin_plan._number(item['scale']) or item['scale'] <= 0):
                    reason = reason or 'invalid item asset, rotation or scale'
            if reason:
                _note(item, kind.capitalize(), reason, notes)


def normalize(model: dict, *, persist_t_splits=True) -> tuple[dict, list[str]]:
    """Validate and derive rooms, optionally retaining whole flat-read walls."""
    model = deepcopy(model)
    if not isinstance(model, dict) or model.get('units') != 'ft':
        raise ValueError('Twin plan units must be ft.')
    notes, buildings = [], []
    for building in _list(model, 'buildings', notes, 'building'):
        levels = twin_plan._levels(building, notes)
        if not levels:
            notes.append(f"Dropped building {building['id']}: no valid levels.")
            continue
        if not twin_plan._point(building.get('position', [0, 0])):
            notes.append(f"Building {building['id']}: defaulted invalid position to [0, 0].")
            building['position'] = [0, 0]
        building.setdefault('position', [0, 0])
        for key in ('rotation', 'base'):
            if not twin_plan._number(building.get(key, 0)):
                notes.append(f"Building {building['id']}: defaulted invalid {key} to 0.")
                building[key] = 0
            building.setdefault(key, 0)
        building['rotation'] %= 360
        building.setdefault('materials', {})
        _network(building, levels, notes)
        _list(building, 'rooms', notes, 'room', capped=False)
        for name in ('dormers', 'extensions', 'stairs', 'proposals', 'flags'):
            _list(building, name, notes)
        flags = building['flags']
        building['flags'] = [f for f in flags if isinstance(f.get('text'), str)
                             and twin_plan._point(f.get('at'))]
        if len(building['flags']) != len(flags):
            notes.append('Dropped flags with invalid text or position.')
        _derive(building, notes, persist_t_splits=persist_t_splits)
        _pieces(building, notes)
        buildings.append(building)
    site = model.get('site', {})
    if not isinstance(site, dict):
        site = {}
        notes.append('Coerced invalid site to an empty object.')
    twin_plan._site(site, notes)
    site.setdefault('fence', None)
    site['compose_overrides'] = twin_plan._compose_overrides(site.get('compose_overrides'), notes)
    if not buildings and not twin_plan._polygon(site.get('lot')):
        raise ValueError('Twin plan must contain at least one usable building.')
    materials = model.get('materials', {})
    if not isinstance(materials, dict):
        materials = {}
        notes.append('Coerced invalid materials to an empty object.')
    return {'schema': SCHEMA, 'units': 'ft', 'materials': materials,
            'buildings': buildings, 'site': site}, notes
