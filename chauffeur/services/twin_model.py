"""Schema 3 validation and room identities over a connected wall network."""

from copy import deepcopy
import math
import re

from services import twin_model_graph as graph
from services import twin_model_hosts as hosts
from services import twin_plan


SCHEMA = 'chauffeur.twin.plan/3'
CAPS = {'walls': 400, 'joints': 800, 'openings': 400, 'rooms': 120,
        'solar_zones': 200, 'roofs': 40, 'anchors': 400, 'items': 600}
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


def derived_room(room) -> bool:
    """A Room the model found between walls that nobody read, drew, named or
    touched: it carries its joint cycle, the default name and no source. It is
    the walls' own record, so it lasts exactly as long as they enclose it."""
    return (isinstance(room, dict) and not room.get('src') and room.get('name', 'Room') == 'Room'
            and room.get('kind', 'room') == 'room' and isinstance(room.get('joints'), list))


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


def opening_spans(joints, walls, openings) -> dict[str, set]:
    """R55: per wall, the joints lying inside a hosted opening's span.

    A persisted T-split never lands inside an opening's span; such a T stays
    derived for that wall, so the opening keeps its whole wall."""
    keep = {}
    hosted = {}
    for opening in openings or []:
        if (isinstance(opening, dict) and isinstance(opening.get('wall'), str)
                and 'gable' not in opening and opening.get('state') != 'ghost'
                and all(type(opening.get(k)) in (int, float) for k in ('at', 'width'))):
            hosted.setdefault(opening['wall'], []).append(opening)
    for wall in walls:
        spans = hosted.get(wall['id'])
        ends = wall.get('joints')
        if not spans or not isinstance(ends, list) or len(ends) != 2 or not all(j in joints for j in ends):
            continue
        a, b = (joints[j] for j in ends)
        length = math.dist(a, b)
        if length <= _EPS:
            continue
        unit = [(b[i] - a[i]) / length for i in (0, 1)]
        for jid, point in joints.items():
            if jid in ends:
                continue
            along = sum((point[i] - a[i]) * unit[i] for i in (0, 1))
            off = abs((point[0] - a[0]) * unit[1] - (point[1] - a[1]) * unit[0])
            if off > 0.05 or not _EPS < along < length - _EPS:
                continue
            if any(o['at'] - o['width'] / 2 - _EPS <= along <= o['at'] + o['width'] / 2 + _EPS
                   for o in spans):
                keep.setdefault(wall['id'], set()).add(jid)
    return keep


def _split_t_junctions(building, joints, walls, notes):
    """Persist only endpoint splits; proper crossings remain a derivation view."""
    before = hosts.snapshot({'joints': building.get('joints', []), 'walls': walls})
    _, split = graph.split_crossings(joints, walls, proper=False,
                                     keep_whole=opening_spans(joints, walls, building.get('openings')))
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


_OUTLINE_ROUNDING = 0.01


def _same_outline(cached, derived):
    """The same corners, each within a reader's rounding (0.01 ft) of one another."""
    if len(cached) != len(derived):
        return False
    close = lambda p, q: math.dist(p[:2], q[:2]) <= _OUTLINE_ROUNDING
    return (all(any(close(p, q) for q in derived) for p in cached)
            and all(any(close(q, p) for p in cached) for q in derived))


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
    # Acknowledging the note must not discard a lost room's name and finishes.
    for flag in building.get('checked_flags', []):
        room = _flag_room(flag) if flag.get('text') == NOT_CLOSED else None
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
        # The joint cycle retains every T-junction for connected edits; the
        # floor outline needs only corners, not collinear wall subdivisions.
        polygon = room['polygon']
        room['polygon'] = [p for i, p in enumerate(polygon)
                           if abs(_cross([p[k] - polygon[i - 1][k] for k in (0, 1)],
                                         [polygon[(i + 1) % len(polygon)][k] - p[k] for k in (0, 1)])) > _EPS]
        # A cached outline that differs from its region only by the reader's
        # rounding stays, so an edit elsewhere never resizes this room.
        if (index in inherited and valid[inherited[index]]
                and _same_outline(stored[inherited[index]]['polygon'], room['polygon'])):
            room['polygon'] = deepcopy(stored[inherited[index]]['polygon'])
        room.setdefault('kind', 'room')
        rooms.append(room)
    # Reserve even lost identities, so a newly discovered Room cannot take one.
    _piece_meta(stored + ghosts + [room for index, room in zip(candidates_kept, rooms)
                         if index not in inherited], 'room', notes)
    # Located read ghosts do not claim floor regions or disappear on an edit.
    building['rooms'] = rooms + ghosts
    if building.get('checked_flags'):
        restored = {room['id'] for room in rooms}
        building['checked_flags'] = [flag for flag in building['checked_flags']
                                    if not (isinstance(_flag_room(flag), dict)
                                            and _flag_room(flag).get('id') in restored)]
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
    filter_checked_flags(building)
    return notes


def filter_checked_flags(building):
    """Keep acknowledgements of this exact issue across derivation and saves."""
    checked = building.get('checked_flags', [])
    if checked:
        building['flags'] = [flag for flag in building.get('flags', []) if flag not in checked]


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
    kinds = [key for key in ('wall', 'floor', 'ceiling', 'ground', 'roof', 'opening') if key in host]
    if len(kinds) != 1:
        return 'invalid host'
    kind = kinds[0]
    if kind == 'ground':
        return None if host['ground'] is True and twin_plan._point(host.get('at')) else 'invalid ground host'
    collection = ('walls' if kind == 'wall' else 'roofs' if kind == 'roof'
                  else 'openings' if kind == 'opening' else 'rooms')
    target = next((p for p in building[collection] if p['id'] == host[kind]), None)
    if target is None or target.get('state') == 'ghost':
        return f'unknown {kind} host {host[kind]}'
    if kind == 'opening':
        valid = host.get('side') in ('in', 'out')
    elif kind == 'wall':
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
    from services import twin_solar
    zones = _list(building, 'solar_zones', notes, 'solar_zone')
    for zone in zones:
        for key, value in twin_solar.DEFAULTS.items():
            zone.setdefault(key, value)
        reason = twin_solar.error(building, zone, zones)
        if reason:
            zone['state'] = 'ghost'
            zone['why'] = reason
            _note(zone, 'Solar zone', reason, notes)
    from services import twin_objects
    for opening in building.get('openings', []):
        for field, spec in twin_objects.SCHEMA['opening'].items():
            if field in opening:
                try:
                    twin_objects.validate(field, opening[field], spec)
                except ValueError as exc:
                    _note(opening, 'Opening', str(exc), notes)
    for name, kind in (('anchors', 'anchor'), ('items', 'item')):
        for item in _list(building, name, notes, kind):
            reason = _host_error(item.get('host'), building)
            if name == 'anchors':
                item.setdefault('offset', 0)
                item.setdefault('device', None)
                if item.get('kind') in ('meter', 'electric_panel', 'charger') and (not isinstance(item.get('host'), dict) or 'wall' not in item['host'] or reason):
                    reason = 'Choose a wall for the equipment.'
                    item['state'] = 'ghost'
                if item.get('kind') not in ('light', 'switch', 'outlet', 'fan', 'camera', 'sensor', 'meter', 'electric_panel', 'charger', 'parking'):
                    reason = reason or 'invalid anchor kind'
                reason = reason or equipment_error(item)
                if not twin_plan._number(item['offset']):
                    reason = reason or 'invalid offset'
            else:
                item.setdefault('rotation', 0)
                item.setdefault('scale', 1)
                if (not isinstance(item.get('asset'), str) or not twin_plan._number(item['rotation'])
                        or not twin_plan._number(item['scale']) or item['scale'] <= 0):
                    reason = reason or 'invalid item asset, rotation or scale'
            if name == 'items' or not item.get('device'):
                reason = reason or twin_objects.error(item)
            if reason:
                _note(item, kind.capitalize(), reason, notes)
    devices = []
    for item in _list(building, 'devices', notes):
        device = item.get('device')
        if not isinstance(device, str) or not device.strip():
            notes.append('Dropped device placement with no device id.')
            continue
        item['id'] = f'device:{device}'
        item.setdefault('offset', 0)
        if not isinstance(item.get('src'), dict):
            item['src'] = {}
        reason = _host_error(item.get('host'), building)
        if not twin_plan._number(item['offset']):
            reason = reason or 'invalid offset'
        if reason:
            _note(item, 'Device', reason, notes)
        devices.append(item)
    building['devices'] = devices


def equipment_error(piece):
    """Same field constraints for model reads and editor writes."""
    kind = piece.get('kind')
    if kind not in ('charger', 'parking'):
        return None
    if kind == 'parking':
        host = piece.get('host') or {}
        if not isinstance(host, dict):
            return 'Choose a floor or the ground for the parking spot.'
        if 'floor' not in host and not host.get('ground'):
            return 'Choose a floor or the ground for the parking spot.'
        for key, default in (('width', 9), ('depth', 18), ('rotation', 0)):
            piece.setdefault(key, default)
            if not twin_plan._number(piece[key]) or key != 'rotation' and not 1 <= piece[key] <= 100:
                return 'Choose a parking size from 1 to 100 feet and a finite rotation.'
    if 'name' in piece and (not isinstance(piece['name'], str) or not 1 <= len(piece['name']) <= 100):
        return 'Choose an equipment name.'
    if piece.get('car') is not None and (not isinstance(piece['car'], str) or not 1 <= len(piece['car']) <= 100):
        return 'Choose a car id.'
    if kind == 'charger' and piece.get('power') is not None:
        import re
        if not isinstance(piece['power'], str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', piece['power']):
            return 'Choose a Home Assistant power entity.'
    return None


def _unique_devices(buildings, notes):
    seen = set()
    # Anchors own their device; duplicate imported references cannot also place it.
    for building in buildings:
        for anchor in building.get('anchors', []):
            device = anchor.get('device')
            if not device:
                continue
            if not isinstance(device, str) or device in seen:
                anchor['device'] = None
                notes.append('Cleared a duplicate or invalid anchor device.')
            else:
                seen.add(device)
    for building in buildings:
        kept = []
        for item in building['devices']:
            if item['device'] in seen:
                notes.append(f"Dropped duplicate placement for device {item['device']}.")
            else:
                seen.add(item['device'])
                kept.append(item)
        building['devices'] = kept


def _ha_display(value, notes):
    """House-only HA presentation (Show as, Hide); invalid settings fall back to defaults."""
    from services import twin_display
    try:
        return twin_display.validate(value)
    except ValueError:
        notes.append('Reset invalid house display settings.')
        return twin_display.validate()


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
        from services import twin_terrain
        twin_terrain.normalize_foundation(building, notes)
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
        from services import twin_floors
        from services import twin_porches
        for room in building['rooms']:
            if room.get('kind') == 'porch':
                twin_porches.normalize_foundation(room, notes)
            value = room.get('floor_offset_ft', 0)
            if twin_floors.offset_error(value):
                notes.append(f"Room {room['id']}: defaulted invalid floor_offset_ft to 0.")
                value = 0
            room['floor_offset_ft'] = value
        _pieces(building, notes)
        twin_floors.derive_openings(building)
        filter_checked_flags(building)
        buildings.append(building)
    _unique_devices(buildings, notes)
    site = model.get('site', {})
    if not isinstance(site, dict):
        site = {}
        notes.append('Coerced invalid site to an empty object.')
    twin_plan._site(site, notes)
    from services import twin_terrain
    twin_terrain.validate_reads(buildings, site, notes)
    site.setdefault('fence', None)
    site['compose_overrides'] = twin_plan._compose_overrides(site.get('compose_overrides'), notes)
    if not buildings and not twin_plan._polygon(site.get('lot')):
        raise ValueError('Twin plan must contain at least one usable building.')
    materials = model.get('materials', {})
    if not isinstance(materials, dict):
        materials = {}
        notes.append('Coerced invalid materials to an empty object.')
    return {'schema': SCHEMA, 'units': 'ft', 'materials': materials,
            'buildings': buildings, 'site': site,
            'ha_display': _ha_display(model.get('ha_display'), notes),
            'solar_source_building': model.get('solar_source_building'),
            'solar_source_roof': model.get('solar_source_roof') if any(
                r['id'] == model.get('solar_source_roof') for b in buildings for r in b.get('roofs', [])) else None}, notes
