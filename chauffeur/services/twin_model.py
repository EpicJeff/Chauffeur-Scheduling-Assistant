"""Schema 3 validation and room identities over a connected wall network."""

from copy import deepcopy
import math
import re

from services import twin_model_graph as graph
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


def _overlap(left, right):
    """Integrate shared vertical intervals, including concave or angled rooms.

    Between vertices and edge crossings, interval ends are linear in x, so
    the midpoint rule gives the exact area of each strip.
    """
    if not twin_plan._polygon(left) or not twin_plan._polygon(right):
        return 0
    lo = max(min(p[0] for p in left), min(p[0] for p in right))
    hi = min(max(p[0] for p in left), max(p[0] for p in right))
    if hi <= lo:
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


def _list(owner, name, notes, kind=None):
    items = owner.get(name, [])
    if not isinstance(items, list):
        notes.append(f'Dropped invalid {name} list; expected a list.')
        items = []
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


def _derive(building, notes):
    stored = list(building.get('rooms', []))
    seen = {room.get('id') for room in stored}
    flags = []
    for flag in building.get('flags', []):
        if flag.get('text') != NOT_CLOSED:
            flags.append(flag)
            continue
        room = _flag_room(flag)
        if isinstance(room, dict) and room.get('id') not in seen:
            if twin_plan._polygon(room.get('polygon')):
                stored.append(deepcopy(room))
                seen.add(room.get('id'))
            else:
                notes.append('Dropped room flag with an invalid cached polygon.')
    _piece_meta(stored, 'room', notes)

    candidates, ends = [], []
    used_joints = {joint['id'] for joint in building.get('joints', [])}
    for level in building.get('levels', []):
        lid = level['id']
        joints = {j['id']: j['at'] for j in building.get('joints', []) if j.get('level') == lid}
        walls = [w for w in building.get('walls', []) if w.get('level') == lid
                 and w.get('state') != 'ghost' and len(w.get('joints', [])) == 2
                 and all(j in joints for j in w['joints'])]
        # Use a split view for faces; original walls retain their host identities.
        split_joints, split_walls = graph.split_crossings(joints, walls)
        rename = {}
        for jid, point in split_joints.items():
            if jid in joints:
                continue
            new_id = jid
            suffix = 1
            while new_id in used_joints:
                new_id = f'{jid}:{suffix}'
                suffix += 1
            if len(used_joints) >= CAPS['joints']:
                notes.append('Dropped derived joints; the cap is 800.')
                continue
            used_joints.add(new_id)
            rename[jid] = new_id
            building.setdefault('joints', []).append({'id': new_id, 'level': lid, 'at': point})
        for region in graph.regions(split_joints, split_walls):
            if any(j not in joints and j not in rename for j in region['joints']):
                continue
            region['joints'] = [rename.get(j, j) for j in region['joints']]
            region['level'] = lid
            candidates.append(region)
        ends.extend((lid, point) for point in graph.open_ends(split_joints, split_walls))

    # A region chooses its best match first; a contested identity goes to the
    # larger region, rather than being copied to both sides of a new partition.
    claims = {}
    for index, region in enumerate(candidates):
        overlaps = [(_overlap(region['polygon'], room.get('polygon')), -_area(room['polygon']), i)
                    for i, room in enumerate(stored) if room.get('level') == region['level']]
        if overlaps:
            # Equal overlap favours the more specific cache. This lets a
            # swallowed room return when its partition is put back (R7).
            overlap, _, owner = max(overlaps, key=lambda pair: pair[:2])
            if overlap + _EPS >= region['area'] * 0.25:
                claims[index] = owner
    winners = {}
    for index, owner in claims.items():
        if owner not in winners or candidates[index]['area'] > candidates[winners[owner]]['area']:
            winners[owner] = index
    candidates_kept = _cap(list(range(len(candidates))), 'rooms', notes)
    inherited = {index: owner for owner, index in winners.items() if index in candidates_kept}
    rooms = []
    for index in candidates_kept:
        region = candidates[index]
        room = deepcopy(stored[inherited[index]]) if index in inherited else {'name': 'Room', 'kind': 'room'}
        room.update({key: region[key] for key in ('level', 'polygon', 'joints')})
        room.setdefault('kind', 'room')
        rooms.append(room)
    # Reserve even lost identities, so a newly discovered Room cannot take one.
    _piece_meta(stored + [room for index, room in zip(candidates_kept, rooms)
                         if index not in inherited], 'room', notes)
    building['rooms'] = rooms
    for owner, room in enumerate(stored):
        if owner not in inherited.values():
            flags.append({'level': room.get('level'), 'at': _centroid(room.get('polygon', [])),
                          'text': NOT_CLOSED, 'piece': {'room': deepcopy(room)}})
    for lid, point in ends:
        if not any(f.get('text') == NOT_CLOSED and f.get('level') == lid
                   and math.dist(point, f['at']) <= 1 for f in flags):
            flags.append({'level': lid, 'at': point, 'text': NOT_CLOSED})
    building['flags'] = flags
    return building


def derive(building: dict) -> dict:
    """Rebuild room caches and unclosed flags in place, preserving identities."""
    return _derive(building, [])


def _ghost(piece, kind, reason, notes):
    piece['state'] = 'ghost'
    piece['why'] = reason
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
            _ghost(wall, 'Wall', 'invalid joints, level or dimensions', notes)


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
        valid = (type(host.get('edge')) is int and 0 <= host['edge'] < len(target['area'])
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
                or not all(isinstance(e, dict) and e.get('setting') in ('sloped', 'gable', 'clipped')
                           and twin_plan._numeric_fields(e, ('pitch', 'clip')) for e in edges)
                or not all(twin_plan._number(roof.get(k)) for k in ('plate', 'overhang'))):
            _ghost(roof, 'Roof', 'invalid area, edges or dimensions', notes)
    walls = {w['id']: w for w in building['walls']}
    roof_ids = {r['id']: r for r in roofs}
    for opening in _list(building, 'openings', notes, 'opening'):
        reason = None
        if 'gable' in opening:
            gable = opening['gable']
            roof = twin_plan._lookup(roof_ids, gable.get('roof')) if isinstance(gable, dict) else None
            if (roof is None or roof.get('state') == 'ghost' or type(gable.get('edge')) is not int
                    or not 0 <= gable['edge'] < len(roof['area'])):
                reason = 'unknown gable host'
        else:
            wall = twin_plan._lookup(walls, opening.get('wall'))
            if wall is None or wall.get('state') == 'ghost':
                reason = f"unknown wall {opening.get('wall')}"
        if not reason and (not all(twin_plan._number(opening.get(k)) for k in ('at', 'width', 'sill', 'head'))
                           or opening['width'] <= 0 or opening['head'] <= opening['sill']):
            reason = 'invalid opening dimensions'
        if reason:
            _ghost(opening, 'Opening', reason, notes)
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
                _ghost(item, kind.capitalize(), reason, notes)


def normalize(model: dict) -> tuple[dict, list[str]]:
    """Copy and validate a feet-based model, then derive every room from walls."""
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
        rooms = _list(building, 'rooms', notes, 'room')
        building['rooms'] = [room for room in rooms if twin_plan._polygon(room.get('polygon'))]
        if len(building['rooms']) != len(rooms):
            notes.append('Dropped rooms with invalid cached polygons.')
        for name in ('dormers', 'extensions', 'stairs', 'proposals', 'flags'):
            _list(building, name, notes)
        flags = building['flags']
        building['flags'] = [f for f in flags if isinstance(f.get('text'), str)
                             and twin_plan._point(f.get('at'))]
        if len(building['flags']) != len(flags):
            notes.append('Dropped flags with invalid text or position.')
        _derive(building, notes)
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
