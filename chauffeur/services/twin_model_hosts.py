"""Positions and following rules for pieces on schema 3 surfaces."""

from copy import deepcopy
import math


MIN_CLEAR = 0.5
_EPS = 1e-9


def snapshot(building) -> dict:
    """Copy the surface geometry before an edit, including lost-host locations."""
    joints = {j['id']: j['at'] for j in building.get('joints', [])}
    walls = {}
    for wall in building.get('walls', []):
        ends = wall.get('joints', [])
        if (wall.get('state') != 'ghost' and isinstance(ends, list) and len(ends) == 2
                and all(isinstance(j, str) and j in joints for j in ends)):
            a, b = (joints[j] for j in ends)
            if math.dist(a, b) > _EPS:
                walls[wall['id']] = {'a': list(a), 'b': list(b), 'level': wall.get('level'),
                                     'thickness': wall.get('thickness', 0), 'joints': list(ends)}
    rooms = {}
    for room in building.get('rooms', []):
        polygon = room.get('polygon', [])
        if polygon and room.get('state') != 'ghost':
            rooms[room['id']] = {'level': room.get('level'),
                                 'bounds': [min(p[0] for p in polygon), min(p[1] for p in polygon),
                                            max(p[0] for p in polygon), max(p[1] for p in polygon)]}
    return {'walls': walls, 'rooms': rooms,
            'openings': {o['id']: deepcopy(o) for o in building.get('openings', [])
                         if o.get('state') != 'ghost'},
            'roofs': {r['id']: deepcopy(r) for r in building.get('roofs', [])
                      if r.get('state') != 'ghost'},
            'levels': {l['id']: deepcopy(l) for l in building.get('levels', [])}}


def _surface(geometry, host):
    if 'opening' in host:
        opening = geometry.get('openings', {}).get(host['opening'])
        if opening is not None:
            surface = _surface(geometry, _host(opening, True))
            if surface is not None:
                return {'opening': opening, 'surface': surface, 'level': surface.get('level')}
        return None
    if 'wall' in host:
        return geometry['walls'].get(host['wall'])
    if 'floor' in host or 'ceiling' in host:
        return geometry['rooms'].get(host.get('floor', host.get('ceiling')))
    if 'roof' in host:
        roof = geometry['roofs'].get(host['roof'])
        edge = host.get('edge')
        if (roof is not None and type(edge) is int
                and 0 <= edge < len(roof.get('area', []))):
            return roof
    return None


def _line(geometry, host):
    surface = _surface(geometry, host)
    if surface is None:
        return None
    if 'wall' in host:
        return surface['a'], surface['b']
    if 'roof' in host:
        area, edge = surface['area'], host['edge']
        a, b = area[edge], area[(edge + 1) % len(area)]
        if math.dist(a, b) > _EPS:
            return a, b
    return None


def surface_changed(before, geometry, host, prior_host=None):
    """Whether a piece's surface or its storey's dimensions changed."""
    old = _surface(before, host if prior_host is None else prior_host)
    current = _surface(geometry, host)
    if old != current:
        return True
    if current is None:
        return False
    old_level = before['levels'].get(old.get('level'), {})
    level = geometry['levels'].get(current.get('level'), {})
    return any(old_level.get(key) != level.get(key) for key in ('elevation', 'ceiling'))


def _point(geometry, host, offset=0):
    if host.get('ground') is True:
        return [*host['at'], offset]
    surface = _surface(geometry, host)
    if surface is None:
        raise ValueError('The host surface is missing.')
    level = geometry['levels'].get(surface.get('level'), {})
    elevation = level.get('elevation', 0)
    if 'opening' in host:
        opening = surface['opening']
        opening_host = deepcopy(_host(opening, True))
        height = opening.get('sill', 0) + 1 if opening.get('kind') == 'window' else 3.5
        opening_host.update(side='left' if host.get('side') == 'in' else 'right',
                            sill=height, z=height)
        return _point(geometry, opening_host, offset)
    if 'floor' in host or 'ceiling' in host:
        x0, y0, x1, y1 = surface['bounds']
        z = (elevation + level.get('ceiling', 0) - offset
             if 'ceiling' in host else elevation + offset)
        return [x0 + host['u'] * (x1 - x0), y0 + host['v'] * (y1 - y0), z]
    line = _line(geometry, host)
    if line is None:
        raise ValueError('The host surface has no length.')
    a, b = line
    length = math.dist(a, b)
    dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    x, y = a[0] + dx * host['at'], a[1] + dy * host['at']
    if 'wall' in host:
        side = host.get('side')
        distance = surface['thickness'] / 2 + offset
        if side in ('left', 'right'):
            sign = 1 if side == 'left' else -1
            x, y = x - sign * dy * distance, y + sign * dx * distance
        return [x, y, elevation + host.get('sill', host.get('z', 0))]
    # Roof hosts record a distance along an area edge, at its plate.
    return [x, y, surface.get('plate', 0) + host.get('z', 0) + offset]


def world_point(building, host, offset=0) -> list[float]:
    """Resolve a host in building-local feet (x, y, then height)."""
    return _point(snapshot(building), host, offset)


def _host(piece, opening):
    if not opening:
        return piece.get('host', {})
    if 'gable' in piece:
        return {**piece['gable'], 'at': piece['at'], 'z': piece.get('sill', 0)}
    return piece


def _available(geometry, host, gable=False):
    if host.get('ground') is True:
        return True
    surface = _surface(geometry, host)
    if surface is None:
        return False
    if 'roof' in host:
        if _line(geometry, host) is None:
            return False
        if gable:
            edges = surface.get('edges', [])
            return host['edge'] < len(edges) and edges[host['edge']].get('setting') in ('gable', 'clip', 'clipped')
    return True


def _at(host, old_line, new_line, width):
    a, b = new_line
    length = math.dist(a, b)
    at = host['at']
    if old_line is not None:
        old_a, old_b = old_line
        old_length = math.dist(old_a, old_b)
        da, db = [a[i] - old_a[i] for i in (0, 1)], [b[i] - old_b[i] for i in (0, 1)]
        if math.dist(da, db) <= _EPS or math.dist(a, old_a) <= _EPS:
            pass
        elif math.dist(b, old_b) <= _EPS:
            at += length - old_length
        else:
            at *= length / old_length
    lo, hi = MIN_CLEAR + width / 2, length - MIN_CLEAR - width / 2
    if lo > hi + _EPS:
        raise ValueError('The hosted piece does not fit with half a foot clear on each side.')
    return max(lo, min(hi, at))


def carry_split(building, before):
    """Rehost split-wall pieces at their old centres; return carried host identities."""
    current = snapshot({'joints': building.get('joints', []),
                        'walls': building.get('walls', [])})['walls']
    splits = {}
    for wid, old in before['walls'].items():
        wall = current.get(wid)
        if wall is None or not set(wall['joints']) - set(old.get('joints', [])):
            continue
        candidates = [(pid, part) for pid, part in current.items()
                      if pid == wid or (pid not in before['walls'] and pid.startswith(wid + '~')
                                        and pid[len(wid) + 1:].isdigit())]
        length = math.dist(old['a'], old['b'])
        direction = [(old['b'][i] - old['a'][i]) / length for i in (0, 1)]
        parts = []
        for pid, part in candidates:
            if part['level'] != old['level']:
                continue
            positions = [sum((point[i] - old['a'][i]) * direction[i] for i in (0, 1))
                         for point in (part['a'], part['b'])]
            if all(-_EPS <= at <= length + _EPS
                   and math.dist(point, [old['a'][i] + at * direction[i] for i in (0, 1)]) <= 0.05 + _EPS
                   for point, at in zip((part['a'], part['b']), positions)):
                parts.append((pid, part, positions))
        if any(pid == wid for pid, _, _ in parts) and len(parts) > 1:
            splits[wid] = parts
    carried = set()
    for name in ('openings', 'anchors', 'items', 'devices'):
        pieces = building.get(name, [])
        if not isinstance(pieces, list):
            continue
        for piece in pieces:
            if not isinstance(piece, dict):
                continue
            host = piece if name == 'openings' else piece.get('host', {})
            if (not isinstance(host, dict) or type(host.get('at')) not in (int, float)
                    or not math.isfinite(host['at'])):
                continue
            for pid, part, (start, end) in splits.get(host.get('wall'), []):
                if min(start, end) - _EPS <= host['at'] <= max(start, end) + _EPS:
                    old = before['walls'][host['wall']]
                    length = math.dist(old['a'], old['b'])
                    point = [old['a'][i] + host['at'] * (old['b'][i] - old['a'][i]) / length
                             for i in (0, 1)]
                    part_length = math.dist(part['a'], part['b'])
                    at = sum((point[i] - part['a'][i]) * (part['b'][i] - part['a'][i])
                             for i in (0, 1)) / part_length
                    host.update(wall=pid, at=at)
                    carried.add(id(host))
                    break
    return carried


def _texts(piece):
    kind = 'device' if 'device' in piece and 'kind' not in piece else piece.get('kind', piece.get('asset', 'item'))
    return (f'This {kind} lost its wall; place it again.',
            f'This {kind} lost its surface; place it again.',
            f'This {kind} no longer fits on its wall; place it again.',
            f'This {kind} no longer fits on its surface; place it again.')


def _clear_ghost(piece):
    owner = piece.get('ghost_by')
    if owner in ('hosts', 'normalize'):
        piece['state'] = 'settled'
        piece.pop('ghost_by')
        why = piece.pop('hosts_why' if owner == 'hosts' else 'normalize_why', None)
        if why is not None and piece.get('why') == why:
            piece.pop('why', None)


def _clear_flags(building, piece, *, checked=True):
    texts = _texts(piece)
    for name in ('flags', 'checked_flags') if checked else ('flags',):
        if name in building:
            building[name] = [f for f in building[name]
                              if not (f.get('piece') == piece['id'] and f.get('text') in texts)]


def _lost(building, piece, host, before, notes, *, fits=True):
    texts = _texts(piece)
    text = texts[(0 if 'wall' in host else 1) + (0 if fits else 2)]
    flags = building.setdefault('flags', [])
    if not any(f.get('piece') == piece['id'] and f.get('text') == text for f in flags):
        previous = next((f for f in flags if f.get('piece') == piece['id'] and f.get('text') in texts), None)
        if previous is not None and previous.get('level') is not None:
            at, level = previous['at'], previous.get('level')
        else:
            at, level = last_position(building, piece, host, before)
        _clear_flags(building, piece, checked=False)
        building['flags'].append({'level': level, 'at': list(at), 'text': text, 'piece': piece['id']})
        if 'device' in piece and 'kind' not in piece:
            piece.update(position=list(at), level=level)
        notes.append(text)
    # A reader's ghost and explanation belong to the reader. A normalize ghost
    # is temporary; surface loss transfers that responsibility to this module.
    if piece.get('state') != 'ghost' or piece.get('ghost_by') == 'normalize':
        _clear_ghost(piece)
        piece['state'], piece['ghost_by'] = 'ghost', 'hosts'
        if 'why' not in piece:
            piece['why'] = piece['hosts_why'] = text


def _xy(value):
    return (isinstance(value, (list, tuple)) and len(value) >= 2
            and all(type(v) in (int, float) and math.isfinite(v) for v in value[:2]))


def last_position(building, piece, host, before):
    """Where a lost piece last stood, on its level: never the building origin.

    The surface before the edit wins, then the surface as it stands now (a
    split part the snapshot predates), then the piece's own recorded position,
    then the middle of its level's walls."""
    for geometry in (before, snapshot(building)):
        if not _available(geometry, host):
            continue
        try:
            point = _point(geometry, host, piece.get('offset', 0))
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            continue
        surface = _surface(geometry, host) or {}
        level = surface.get('level', piece.get('level'))
        if _xy(point) and level is not None:
            return list(point[:2]), level
    level = piece.get('level')
    walls = before.get('walls', {})
    wall = walls.get(host.get('wall')) if isinstance(host, dict) else None
    if level is None and wall is not None:
        level = wall.get('level')
    levels = [l['id'] for l in building.get('levels', []) if isinstance(l, dict) and 'id' in l]
    if level is None and levels:
        level = levels[0]
    if wall is not None and type(host.get('at')) in (int, float):
        a, b = wall['a'], wall['b']
        length = math.dist(a, b)
        if length > _EPS:
            t = host['at'] / length
            return [a[i] + t * (b[i] - a[i]) for i in (0, 1)], level
    for key in ('position', 'at'):
        if _xy(piece.get(key)):
            return list(piece[key][:2]), level
    joints = [j['at'] for j in building.get('joints', [])
              if isinstance(j, dict) and j.get('level') == level and _xy(j.get('at'))]
    if not joints:
        joints = [j['at'] for j in building.get('joints', []) if isinstance(j, dict) and _xy(j.get('at'))]
    if joints:
        return [sum(p[i] for p in joints) / len(joints) for i in (0, 1)], level
    return [0, 0], level


def follow(building, before: dict) -> list[str]:
    """Carry hosted pieces after an edit; retain and flag pieces that lose a host."""
    carried = carry_split(building, before)
    geometry, notes = snapshot(building), []
    for collection in ('openings', 'anchors', 'items', 'devices'):
        # Opening centres may have been clamped while their wall changed.
        if collection != 'openings':
            geometry = snapshot(building)
        opening = collection == 'openings'
        for piece in building.get(collection, []):
            host = _host(piece, opening)
            if id(host) not in carried and not surface_changed(before, geometry, host):
                continue
            if not _available(geometry, host, opening and 'gable' in piece):
                _lost(building, piece, host, before, notes)
                continue
            line = _line(geometry, host)
            if line is not None:
                try:
                    old_line = None if id(host) in carried else _line(before, host)
                    at = _at(host, old_line, line, piece.get('width', 0))
                except ValueError:
                    _lost(building, piece, host, before, notes, fits=False)
                    continue
                (piece if opening else host)['at'] = at
            _clear_flags(building, piece)
            _clear_ghost(piece)
    return notes


def rehost(building, piece_id, host: dict) -> None:
    """Place an existing piece on another surface, clearing its unhosted flag."""
    for collection in ('openings', 'anchors', 'items', 'devices'):
        piece = next((p for p in building.get(collection, []) if p['id'] == piece_id), None)
        if piece is None:
            continue
        host = deepcopy(host)
        if 'gable' in host:
            host = {**host['gable'], 'at': host['at']}
        opening = collection == 'openings'
        if opening and not ('wall' in host or 'roof' in host):
            raise ValueError('An opening needs a wall or gable host.')
        geometry = snapshot(building)
        if not _available(geometry, host, opening and 'roof' in host):
            raise ValueError('The host surface is missing.')
        # Resolve coordinates and clearance before changing the piece.
        _point(geometry, host)
        line = _line(geometry, host)
        if line is not None:
            host['at'] = _at(host, None, line, piece.get('width', 0))
        if opening:
            piece.pop('wall', None)
            piece.pop('gable', None)
            if 'wall' in host:
                piece['wall'] = host['wall']
            else:
                piece['gable'] = {'roof': host['roof'], 'edge': host['edge']}
            piece['at'] = host['at']
        else:
            piece['host'] = host
        _clear_flags(building, piece)
        _clear_ghost(piece)
        return
    raise ValueError(f'Unknown hosted piece: {piece_id}.')
