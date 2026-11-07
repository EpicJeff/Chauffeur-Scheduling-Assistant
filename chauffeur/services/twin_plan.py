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


def _polygon(value):
    return isinstance(value, list) and len(value) >= 3 and all(_point(p) for p in value)


def _numeric_fields(item, names):
    return all(name not in item or _number(item[name]) for name in names)


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
        if isinstance(level, dict) and 'ceiling' not in level:
            level['ceiling'] = 9
            notes.append(f'Level {name}: defaulted missing ceiling to 9 feet.')
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
    if roof is None:
        return {}
    main = roof.get('main') if isinstance(roof, dict) else None
    if (not isinstance(main, dict)
            or not all(_number(main.get(k)) for k in ('x0', 'x1', 'y0', 'y1', 'plate', 'overhang'))
            or main['x0'] >= main['x1'] or main['y0'] >= main['y1']):
        building['roof'] = None
        notes.append('Dropped roof main and extensions: invalid roof bounds, plate or overhang.')
        return {}
    pitch = main.get('pitch')
    if not _number(pitch) or not 0 < pitch <= 24:
        main['pitch'] = max(1, min(24, pitch)) if _number(pitch) else 1
        notes.append(f"Building {building.get('id', 'unnamed')} roof pitch clamped "
                     f"to {main['pitch']}.")
    extensions = []
    for index, extension in enumerate(_items(roof, 'extensions', notes)):
        valid = isinstance(extension, dict)
        if valid and extension.get('kind') == 'shed_continuation':
            valid = (all(_number(extension.get(k)) for k in ('to_x', 'pitch'))
                     and extension['to_x'] > main['x1']
                     and _numeric_fields(extension, ('overhang',)))
        elif valid and extension.get('kind') == 'awning':
            valid = (all(_number(extension.get(k)) for k in ('x0', 'x1', 'depth', 'pitch', 'eave'))
                     and extension['x0'] < extension['x1'] and extension['depth'] > 0
                     and _numeric_fields(extension, ('brackets',)))
        else:
            valid = False
        if valid and 0 < extension['pitch'] <= 24:
            extensions.append(extension)
        else:
            notes.append(f'Dropped roof extension {index}: malformed extension.')
    roof['extensions'] = extensions
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
        if (isinstance(opening, dict) and opening.get('kind') in ('door', 'slider', 'passage')
                and 'sill' not in opening):
            opening['sill'] = 0
            notes.append(f'Opening {index}: defaulted missing sill to 0 feet.')
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


def _details(building, levels, notes):
    porch = building.get('porch')
    if porch is not None:
        if (not isinstance(porch, dict) or not _polygon(porch.get('polygon'))
                or not _numeric_fields(porch, ('floor',))):
            building['porch'] = None
            notes.append('Dropped porch: invalid polygon or floor.')
        else:
            porch.setdefault('floor', 0)
            columns = []
            for index, column in enumerate(_items(porch, 'columns', notes)):
                if (isinstance(column, dict) and _point(column.get('at'))
                        and _number(column.get('size')) and column['size'] > 0):
                    columns.append(column)
                else:
                    notes.append(f'Dropped porch column {index}: invalid at or size.')
            porch['columns'] = columns
    for name in ('stairs', 'fixtures', 'lights'):
        valid_items = []
        for index, item in enumerate(_items(building, name, notes)):
            valid = isinstance(item, dict)
            if valid and name == 'stairs':
                valid = (_point(item.get('from')) and _point(item.get('to'))
                         and all(_number(item.get(k)) and item[k] > 0 for k in ('width', 'risers'))
                         and _number(item.get('rise_to'))
                         and _lookup(levels, item.get('level')) is not None)
            elif valid and name == 'lights':
                valid = _point(item.get('at')) and _lookup(levels, item.get('level')) is not None
            elif valid:
                rect = item.get('rect')
                valid = (isinstance(rect, (list, tuple)) and len(rect) == 4
                         and all(_number(v) for v in rect)
                         and _lookup(levels, item.get('level')) is not None
                         and _numeric_fields(item, ('height', 'z0')))
            if valid:
                valid_items.append(item)
            else:
                notes.append(f'Dropped {name} entry {index}: invalid coordinates, dimensions or level.')
        building[name] = valid_items


def _site(site, notes):
    if site.get('lot') is not None and not _polygon(site['lot']):
        site['lot'] = None
        notes.append('Dropped site lot: invalid polygon.')
    pool = site.get('pool')
    if pool is not None and (not isinstance(pool, dict) or not _polygon(pool.get('polygon'))
                             or not _numeric_fields(pool, ('depth', 'coping'))):
        site['pool'] = None
        notes.append('Dropped site pool: invalid polygon or dimensions.')
    fire = site.get('fire_pit')
    if fire is not None and (not isinstance(fire, dict) or not _point(fire.get('at'))
                             or not _number(fire.get('radius')) or fire['radius'] <= 0):
        site['fire_pit'] = None
        notes.append('Dropped site fire_pit: invalid at or radius.')
    for name in ('beds', 'planting', 'furniture', 'edges', 'hardscape'):
        kept = []
        for index, item in enumerate(_items(site, name, notes)):
            valid = isinstance(item, dict)
            if valid and name in ('beds', 'hardscape'):
                valid = _polygon(item.get('polygon')) and _numeric_fields(item, ('height', 'elevation'))
            elif valid and name == 'edges':
                points = item.get('points', item.get('polyline'))
                valid = isinstance(points, list) and len(points) >= 2 and all(_point(p) for p in points)
            elif valid:
                valid = (_point(item.get('at'))
                         and _numeric_fields(item, ('height', 'rotation', 'scale', 'elevation', 'seed')))
            if valid:
                kept.append(item)
            else:
                notes.append(f'Dropped {name} entry {index}: invalid coordinates or dimensions.')
        site[name] = kept


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
        if 'position' in building and not _point(building['position']):
            building['position'] = [0, 0]
            notes.append(f"Building {building.get('id', index)}: defaulted invalid position to [0, 0].")
        walls = _walls(building, levels, notes)
        main = _roof(building, notes)
        _openings(building, walls, main, notes)
        _rooms(building, levels, notes)
        _details(building, levels, notes)
        buildings.append(building)
    if not buildings:
        raise ValueError('Twin plan must contain at least one usable building.')
    site = raw.get('site')
    if 'site' in raw and not isinstance(site, dict):
        notes.append('Coerced invalid site to an empty object.')
    site = site if isinstance(site, dict) else {}
    _site(site, notes)
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
    if any(not isinstance(plan.get('site', {}).get(name, []), list)
           for plan in (before, after) for name in ('planting', 'beds', 'edges')):
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


def overlay_director(plan: dict, revised: dict) -> tuple[dict, list[str]]:
    """Overlay explicit edits; omissions preserve the household's current work."""
    merged = deepcopy(plan)
    notes = []
    for name in ('site', 'materials'):
        if name not in revised:
            notes.append(f'Kept omitted {name} unchanged.')
            continue
        value = revised[name]
        if value is None or value == []:
            notes.append(f'Kept empty top-level {name} unchanged.')
        elif isinstance(value, dict):
            for key in plan.get(name, {}):
                if key not in value:
                    notes.append(f'Kept omitted {name}.{key} unchanged.')
            for key, item in value.items():
                if name == 'site' and key in ('lot', 'pool'):
                    if item != plan.get('site', {}).get(key):
                        notes.append(f'Kept site.{key} unchanged; the director cannot change plot-plan facts.')
                else:
                    merged[name][key] = deepcopy(item)
        else:
            notes.append(f'Kept invalid {name} unchanged; expected an object or null.')
    # Normalize explicit list deletions before recording compose removals.
    for name in ('beds', 'planting', 'furniture', 'edges', 'hardscape'):
        if merged['site'].get(name) is None:
            merged['site'][name] = []
    merged['materials'] = {role: value for role, value in merged['materials'].items()
                           if value is not None and value != []}
    return merged, notes


def merge_director(plan: dict, revised: dict) -> tuple[dict, list[str]]:
    """Apply the director's site and materials only, then normalize a copy."""
    merged, notes = overlay_director(plan, revised)
    normalized, normalized_notes = normalize(record_compose_overrides(plan, merged))
    return normalized, notes + normalized_notes


def diff_paths(a: dict, b: dict) -> list[str]:
    """Return changed leaves using stable list identities and numeric values."""
    missing = object()
    paths = set()

    def indexed(items):
        result = {}
        for index, item in enumerate(items):
            field = next((k for k in ('id', 'name') if isinstance(item, dict) and k in item), None)
            key = f'{field}={item[field]}' if field else str(index)
            result[key] = item
        return result

    def walk(left, right, path):
        if isinstance(left, dict) and isinstance(right, dict):
            for key in left.keys() | right.keys():
                walk(left.get(key, missing), right.get(key, missing),
                     f'{path}.{key}' if path else key)
        elif isinstance(left, list) and isinstance(right, list):
            old, new = indexed(left), indexed(right)
            for key in old.keys() | new.keys():
                walk(old.get(key, missing), new.get(key, missing), f'{path}[{key}]')
        elif not (_number(left) and _number(right) and left == right):
            if type(left) is not type(right) or left != right:
                paths.add(path)

    walk(a, b, '')
    return sorted(paths)
