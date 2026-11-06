"""Pure validation and normalization of the twin's source plan, in feet.

Recoverable omissions and invalid items produce English notes. Only unsupported
units or a plan without a usable building prevent normalization altogether.
"""

from copy import deepcopy
from math import hypot, isfinite


SCHEMA = 'chauffeur.twin.plan/1'
CAPS = {'walls': 400, 'openings': 400, 'rooms': 120, 'planting': 300,
        'furniture': 120, 'beds': 60}


def _number(value):
    return (type(value) in (int, float)
            and (isinstance(value, int) or isfinite(value)))


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_number(v) for v in value))


def _items(owner, name, notes):
    items = owner.get(name, [])
    if not isinstance(items, list):
        notes.append(f'Dropped invalid {name} list; expected a list.')
        return []
    cap = CAPS.get(name)
    if cap is not None and len(items) > cap:
        notes.append(f'Dropped {len(items) - cap} items from {name}; the cap is {cap}.')
        return items[:cap]
    return items


def _lookup(items, key):
    return items.get(key) if isinstance(key, str) else None


def _levels(building, notes):
    levels = {}
    for index, level in enumerate(_items(building, 'levels', notes)):
        name = level.get('id', index) if isinstance(level, dict) else index
        if (not isinstance(level, dict)
                or not isinstance(level.get('id'), str) or not level['id']
                or level['id'] in levels
                or not _number(level.get('elevation'))
                or not _number(level.get('ceiling')) or level['ceiling'] <= 0):
            notes.append(f'Dropped level {name}: invalid or duplicate level data.')
            continue
        levels[level['id']] = level
    building['levels'] = sorted(levels.values(), key=lambda level: level['elevation'])
    return levels


def _walls(building, levels, notes):
    walls = {}
    for index, wall in enumerate(_items(building, 'walls', notes)):
        name = wall.get('id', index) if isinstance(wall, dict) else index
        reason = None
        if (not isinstance(wall, dict)
                or not isinstance(wall.get('id'), str) or not wall['id']):
            reason = 'invalid wall data'
        elif wall['id'] in walls:
            reason = 'duplicate wall id'
        elif _lookup(levels, wall.get('level')) is None:
            reason = f"unknown level {wall.get('level')}"
        elif not _point(wall.get('from')) or not _point(wall.get('to')):
            reason = 'invalid endpoints'
        elif wall['from'] == wall['to'] or hypot(
                wall['to'][0] - wall['from'][0], wall['to'][1] - wall['from'][1]) == 0:
            reason = 'zero length'
        elif not _number(wall.get('height')) or wall['height'] <= 0:
            reason = 'invalid height'
        else:
            wall.setdefault('exterior', False)
            wall.setdefault('thickness', 0.5 if wall['exterior'] else 0.33)
            if not _number(wall['thickness']) or wall['thickness'] <= 0:
                reason = 'invalid thickness'
        if reason:
            notes.append(f'Dropped wall {name}: {reason}.')
        else:
            walls[wall['id']] = wall
    building['walls'] = list(walls.values())
    return walls


def _roof(building, notes):
    roof = building.get('roof')
    if not isinstance(roof, dict):
        return {}
    main = roof.get('main')
    if not isinstance(main, dict):
        return {}
    pitch = main.get('pitch')
    if not _number(pitch) or not 0 < pitch <= 24:
        main['pitch'] = max(1, min(24, pitch)) if _number(pitch) else 1
        notes.append(f"Building {building.get('id', 'unnamed')} roof pitch clamped "
                     f"to {main['pitch']}.")
    return main


def _opening_error(opening, walls, main):
    if not isinstance(opening, dict):
        return 'invalid opening data'
    width, sill, head = (opening.get(key) for key in ('width', 'sill', 'head'))
    if not all(_number(value) for value in (width, sill, head)):
        return 'width, sill and head must be finite numbers'
    if sill < 0:
        return 'sill must not be negative'
    if width <= 0 or sill >= head:
        return 'width must be positive and sill must be below head'
    if ('wall' in opening) == ('gable' in opening):
        return 'reference exactly one wall or gable'
    if 'wall' in opening:
        wall = _lookup(walls, opening['wall'])
        if wall is None:
            return 'unknown wall'
        at = opening.get('at')
        length = hypot(wall['to'][0] - wall['from'][0],
                       wall['to'][1] - wall['from'][1])
        if not _number(at) or at - width / 2 < -1e-6 or at + width / 2 > length + 1e-6:
            return 'outside the wall span'
        if head > wall['height'] + 1e-6:
            return 'head is above the wall height'
    else:
        if opening['gable'] not in ('front', 'rear'):
            return 'unknown gable (expected front or rear)'
        x, x0, x1 = opening.get('x'), main.get('x0'), main.get('x1')
        if (not all(_number(value) for value in (x, x0, x1))
                or x0 >= x1 or x - width / 2 < x0 - 1e-6
                or x + width / 2 > x1 + 1e-6):
            return 'outside the roof gable span'
    return None


def _openings(building, walls, main, notes):
    openings = []
    for index, opening in enumerate(_items(building, 'openings', notes)):
        reason = _opening_error(opening, walls, main)
        if reason:
            name = (opening.get('wall', opening.get('gable', index))
                    if isinstance(opening, dict) else index)
            notes.append(f'Dropped opening on {name}: {reason}.')
        else:
            openings.append(opening)
    building['openings'] = openings


def _rooms(building, levels, notes):
    rooms = []
    for index, room in enumerate(_items(building, 'rooms', notes)):
        name = room.get('name', index) if isinstance(room, dict) else index
        reason = None
        if not isinstance(room, dict):
            reason = 'invalid room data'
        elif _lookup(levels, room.get('level')) is None:
            reason = f"unknown level {room.get('level')}"
        else:
            polygon = room.get('polygon')
            if (not isinstance(polygon, list) or len(polygon) < 3
                    or not all(_point(point) for point in polygon)):
                reason = 'polygon needs at least three valid points'
        if reason:
            notes.append(f'Dropped room {name}: {reason}.')
        else:
            rooms.append(room)
    building['rooms'] = rooms


def normalize(raw: dict) -> tuple[dict, list[str]]:
    """Copy a plan, default optional lists, and drop invalid geometry with notes.

    Caps retain the first entries, with one aggregate note per truncated list.
    Gable coordinates use plan x; wall offsets and opening heights are local to
    the referenced wall, regardless of its level's elevation.
    """
    raw = deepcopy(raw)
    if not isinstance(raw, dict) or raw.get('units') != 'ft':
        raise ValueError('Twin plan units must be ft.')
    notes = []
    buildings = []
    for index, building in enumerate(_items(raw, 'buildings', notes)):
        if not isinstance(building, dict):
            notes.append(f'Dropped building {index}: invalid building data.')
            continue
        levels = _levels(building, notes)
        if not levels:
            notes.append(f"Dropped building {building.get('id', index)}: no valid levels.")
            continue
        walls = _walls(building, levels, notes)
        main = _roof(building, notes)
        _openings(building, walls, main, notes)
        _rooms(building, levels, notes)
        for name in ('stairs', 'fixtures', 'lights'):
            building[name] = _items(building, name, notes)
        buildings.append(building)
    if not buildings:
        raise ValueError('Twin plan must contain at least one usable building.')
    site = raw.get('site')
    if 'site' in raw and not isinstance(site, dict):
        notes.append('Coerced invalid site to an empty object.')
    site = site if isinstance(site, dict) else {}
    for name in ('beds', 'planting', 'furniture', 'edges', 'hardscape'):
        items = _items(site, name, notes)
        site[name] = []
        for index, item in enumerate(items):
            if isinstance(item, dict):
                site[name].append(item)
            else:
                notes.append(f'Dropped invalid {name} entry {index}; expected an object.')
    site.setdefault('fence', None)
    site['compose_overrides'] = _compose_overrides(site.get('compose_overrides'), notes)
    materials = raw.get('materials', {})
    if not isinstance(materials, dict):
        notes.append('Coerced invalid materials to an empty object.')
        materials = {}
    return {'schema': SCHEMA, 'units': 'ft', 'materials': materials,
            'buildings': buildings, 'site': site}, notes


def _compose_overrides(value, notes):
    if value is None:
        return {'removed': [], 'moved': {}}
    if not isinstance(value, dict):
        notes.append('Coerced invalid compose_overrides to an empty object.')
        return {'removed': [], 'moved': {}}
    removed, moved = value.get('removed', []), value.get('moved', {})
    valid_removed = []
    if isinstance(removed, list):
        for item_id in removed:
            if isinstance(item_id, str) and item_id not in valid_removed:
                valid_removed.append(item_id)
    valid_moved = {key: list(at) for key, at in moved.items()
                   if isinstance(key, str) and _point(at)} if isinstance(moved, dict) else {}
    if removed != valid_removed or moved != valid_moved:
        notes.append('Dropped invalid or duplicate compose_overrides entries.')
    return {'removed': valid_removed, 'moved': valid_moved}


def record_compose_overrides(before: dict, after: dict) -> dict:
    """Copy an edit and remember removed and repositioned compose items.

    Existing overrides from either snapshot survive subsequent edits. Geometry
    without an ``at`` (beds and edges) supports deletion, but not translation.
    """
    if (not isinstance(before, dict) or not isinstance(after, dict)
            or not isinstance(before.get('site', {}), dict)
            or not isinstance(after.get('site', {}), dict)):
        return after
    result = deepcopy(after)
    site = result.setdefault('site', {})
    overrides = _compose_overrides(before.get('site', {}).get('compose_overrides'), [])
    latest = _compose_overrides(site.get('compose_overrides'), [])
    for item_id in latest['removed']:
        if item_id not in overrides['removed']:
            overrides['removed'].append(item_id)
    overrides['moved'].update(latest['moved'])

    def composed(plan):
        return {item['id']: item for name in ('beds', 'planting', 'edges')
                for item in plan.get('site', {}).get(name, [])
                if isinstance(item, dict) and item.get('by') == 'compose'
                and isinstance(item.get('id'), str)}

    old, new = composed(before), composed(result)
    for item_id, item in old.items():
        if item_id not in new:
            if item_id not in overrides['removed']:
                overrides['removed'].append(item_id)
            overrides['moved'].pop(item_id, None)
        elif _point(new[item_id].get('at')) and new[item_id]['at'] != item.get('at'):
            overrides['moved'][item_id] = list(new[item_id]['at'])
    site['compose_overrides'] = overrides
    return result


def merge_director(plan: dict, revised: dict) -> tuple[dict, list[str]]:
    """Apply the director's site and materials only, then normalize a copy."""
    merged = deepcopy(plan)
    for name in ('site', 'materials'):
        if name in revised:
            merged[name] = deepcopy(revised[name])
    return normalize(merged)


def diff_paths(a: dict, b: dict) -> list[str]:
    """Return sorted changed leaf paths, including added and removed leaves."""
    missing = object()
    paths = set()

    def leaves(value, path):
        if isinstance(value, dict) and value:
            for key, child in value.items():
                leaves(child, f'{path}.{key}' if path else key)
        elif isinstance(value, list) and value:
            for index, child in enumerate(value):
                leaves(child, f'{path}[{index}]')
        elif value is not missing:
            paths.add(path)

    def walk(left, right, path):
        if isinstance(left, dict) and isinstance(right, dict):
            for key in left.keys() | right.keys():
                walk(left.get(key, missing), right.get(key, missing),
                     f'{path}.{key}' if path else key)
        elif isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                walk(left[index] if index < len(left) else missing,
                     right[index] if index < len(right) else missing,
                     f'{path}[{index}]')
        elif type(left) is not type(right) or left != right:
            leaves(left, path)
            leaves(right, path)

    walk(a, b, '')
    return sorted(paths)
