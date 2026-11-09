"""Pure validation and normalization of the twin's source plan, in feet.

Recoverable omissions and invalid items produce English notes. Only unsupported
units or a plan without a usable building or lot prevent normalization altogether.
"""

from copy import deepcopy
from math import hypot, isfinite
import re


SCHEMA = 'chauffeur.twin.plan/2'
CAPS = {'walls': 400, 'openings': 400, 'rooms': 120, 'planting': 300,
        'furniture': 120, 'beds': 60, 'roof_sections': 40, 'terraces': 40}


def porches(building: dict) -> list[dict]:
    """All porch pieces, collection first in conflicts with the legacy alias.

    Identity wins when both pieces have ids; otherwise compare polygons.
    Return the original pieces so provenance and person edits stay attached.
    """
    result = []
    collection = building.get('porches') or []
    for index, porch in enumerate([*collection, building.get('porch')]):
        if not porch or any(
                (p['id'] == porch['id'] if p.get('id') and porch.get('id')
                 else p.get('polygon') == porch.get('polygon')) for p in result):
            continue
        if index == len(collection):
            result.insert(0, porch)
        else:
            result.append(porch)
    return result


def _number(value):
    return (type(value) in (int, float)
            and (isinstance(value, int) or isfinite(value)))


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_number(v) for v in value))


def _roof_entries(roof, key):
    """Keep usable geometry-keyed roof choices and review flags."""
    entries = roof.get(key, [])
    rect_key = 'block_rect' if key == 'flags' else 'rect'
    return [entry for entry in entries if isinstance(entry, dict)
            and isinstance(entry.get(rect_key), (list, tuple)) and len(entry[rect_key]) == 4
            and all(_number(v) for v in entry[rect_key])
            and (key != 'flags' or isinstance(entry.get('text'), str))] if isinstance(entries, list) else []


def _polygon(value):
    return isinstance(value, list) and len(value) >= 3 and all(_point(p) for p in value)


def _numeric_fields(item, names):
    return all(name not in item or _number(item[name]) for name in names)


def _items(owner, name, notes, cap_name=None):
    items = owner.get(name, [])
    if not isinstance(items, list):
        notes.append(f'Dropped invalid {name} list; expected a list.')
        return []
    cap = CAPS.get(cap_name or name)
    if cap is not None and len(items) > cap:
        notes.append(f'Dropped {len(items) - cap} items from {name}; the cap is {cap}.')
        return items[:cap]
    return items


def _lookup(items, key):
    return items.get(key) if isinstance(key, str) else None


def _piece_meta(items, kind, notes):
    """Reserve supplied identities before silently filling gaps, per kind."""
    def valid_id(value):
        return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:~-]{1,64}', value)

    pieces = [item for item in items if isinstance(item, dict)]
    reserved = {item['id'] for item in pieces if valid_id(item.get('id'))}
    used = set()
    n = 1
    for item in pieces:
        item_id = item.get('id')
        if not valid_id(item_id) or item_id in used:
            while f'{kind}-{n}' in reserved or f'{kind}-{n}' in used:
                n += 1
            item_id = item['id'] = f'{kind}-{n}'
        used.add(item_id)
        # An absent state means settled; do not turn an unchanged save into edits.
        if 'state' in item and item['state'] not in ('ghost', 'settled'):
            notes.append(f'{kind} {item_id}: dropped invalid state; absent means settled.')
            del item['state']
        if 'src' in item:
            src = item.pop('src')
            if isinstance(src, dict) and src.get('person') is True:
                item['src'] = {'person': True}
                for key, value_type in (('sheet', str), ('page', int)):
                    if type(src.get(key)) is value_type:
                        item['src'][key] = src[key]
                if src != item['src']:
                    notes.append(f'{kind} {item_id}: dropped invalid or unsupported src fields.')
            elif (isinstance(src, dict) and isinstance(src.get('sheet'), str)
                  and type(src.get('page')) is int and isinstance(src.get('step'), str)):
                item['src'] = {key: src[key] for key in ('sheet', 'page', 'step')}
            else:
                notes.append(f'{kind} {item_id}: dropped invalid src.')
        if 'confidence' in item and (not _number(item['confidence'])
                                        or not 0 <= item['confidence'] <= 1):
            del item['confidence']
            notes.append(f'{kind} {item_id}: dropped invalid confidence.')
        if 'why' in item:
            if not isinstance(item['why'], str):
                del item['why']
                notes.append(f'{kind} {item_id}: dropped invalid why.')
            elif len(item['why']) > 200:
                item['why'] = item['why'][:200]
                notes.append(f'{kind} {item_id}: shortened why to 200 characters.')


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
        # Half-storeys keep the same outline, slab and wall data as any level.
        # An absent flag means false; preserve that absence on existing plans.
        if 'half' in level and type(level['half']) is not bool:
            del level['half']
            notes.append(f'Level {name}: dropped invalid half flag; absent means false.')
        levels[level['id']] = level
    building['levels'] = sorted(levels.values(), key=lambda level: level['elevation'])
    return levels


def _walls(building, levels, notes):
    walls = {}
    items = _items(building, 'walls', notes)
    _piece_meta(items, 'wall', notes)
    for index, wall in enumerate(items):
        name = wall.get('id', index) if isinstance(wall, dict) else index
        reason = None
        if (not isinstance(wall, dict)
                or not isinstance(wall.get('id'), str) or not wall['id']):
            reason = 'invalid wall data'
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
            if wall.get('kind') == 'separator':
                wall['thickness'] = 0
            elif not _number(wall['thickness']) or wall['thickness'] <= 0:
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
        building['roof'] = {'sections': [], 'extensions': []}
        return {}
    if not isinstance(roof, dict):
        building['roof'] = {'sections': [], 'extensions': []}
        notes.append('Dropped invalid roof; expected an object.')
        return {}
    migrating = 'sections' not in roof and 'main' in roof
    if migrating:
        main = roof['main']
        roof['sections'] = ([{
            'id': 'roof-main', 'kind': 'gable',
            'rect': [main.get(k) for k in ('x0', 'y0', 'x1', 'y1')],
            'ridge': main.get('ridge_axis') if main.get('ridge_axis') in ('x', 'y') else 'y',
            'pitch': main.get('pitch'),
            'plate': main.get('plate'), 'overhang': main.get('overhang', 1),
            'pitch_source': 'drawn',
        }] if isinstance(main, dict) else [])
        if not isinstance(main, dict):
            notes.append('Dropped invalid roof main and extensions.')
        # P0 always drew a gable; missing/invalid ridge metadata means y.
        # Gable coordinates and extension geometry stay unchanged.
        openings = building.get('openings', [])
        if isinstance(openings, list):
            for opening in openings:
                if isinstance(opening, dict) and 'gable' in opening:
                    opening['section'] = 'roof-main'

    def pitch_value(value, name):
        if not _number(value) or not 1 <= value <= 24:
            value = max(1, min(24, value)) if _number(value) else 1
            notes.append(f'Roof section {name}: pitch clamped to {value}.')
        return value

    sections = {}
    items = _items(roof, 'sections', notes, 'roof_sections')
    _piece_meta(items, 'roof', notes)
    sides = ('x0', 'x1', 'y0', 'y1')
    for index, section in enumerate(items):
        name = section.get('id', index) if isinstance(section, dict) else index
        rect = section.get('rect') if isinstance(section, dict) else None
        if (not isinstance(section, dict)
                or not isinstance(rect, (list, tuple)) or len(rect) != 4
                or not all(_number(v) for v in rect)
                or rect[0] >= rect[2] or rect[1] >= rect[3]
                or not _number(section.get('plate')) or section['plate'] <= 0
                or section.get('kind') not in ('hip', 'gable', 'shed', 'flat')
                or (section['kind'] in ('hip', 'gable') and section.get('ridge') not in ('x', 'y'))
                or (section['kind'] == 'shed' and section.get('low_side') not in sides)):
            notes.append(f'Dropped roof section {name}: invalid bounds, kind, direction or plate.')
            continue
        section['pitch'] = 0 if section['kind'] == 'flat' else pitch_value(section.get('pitch'), name)
        if 'ends' in section:
            ends = section.pop('ends')
            if isinstance(ends, dict) and section['kind'] in ('gable', 'hip'):
                allowed = (f"{section['ridge']}0", f"{section['ridge']}1")
                section['ends'] = {end: style for end, style in ends.items()
                                   if end in allowed and style in ('gable', 'hip', 'clip')}
                for end, style in ends.items():
                    if end not in section['ends']:
                        words = {'x0': 'the left end', 'x1': 'the right end',
                                 'y0': 'the front end', 'y1': 'the back end'}.get(end, 'an unknown end')
                        notes.append(f'Roof section {name}: dropped invalid end style on {words}.')
            else:
                notes.append(f'Roof section {name}: dropped invalid ends.')
        if 'pitches' in section:
            pitches = section.pop('pitches')
            if isinstance(pitches, dict):
                section['pitches'] = {side: (0 if section['kind'] == 'flat'
                                           else pitch_value(value, f'{name}.{side}'))
                                      for side, value in pitches.items() if side in sides}
                if any(side not in sides for side in pitches):
                    notes.append(f'Roof section {name}: dropped unknown pitch sides.')
            else:
                notes.append(f'Roof section {name}: dropped invalid pitches.')
        overhang = section.get('overhang', 1)
        if not _number(overhang) or not 0 <= overhang <= 4:
            overhang = max(0, min(4, overhang)) if _number(overhang) else 1
            notes.append(f'Roof section {name}: overhang clamped to {overhang}.')
        section['overhang'] = overhang
        if section.get('pitch_source', 'default') not in ('drawn', 'photos', 'person', 'card', 'default'):
            notes.append(f'Roof section {name}: defaulted invalid pitch_source.')
            section['pitch_source'] = 'default'
        section.setdefault('pitch_source', 'default')
        section['rect'] = list(rect)
        sections[section['id']] = section
    extensions = []
    for index, extension in enumerate(_items(roof, 'extensions', notes)):
        if migrating and isinstance(extension, dict):
            extension['section'] = 'roof-main'
        section = _lookup(sections, extension.get('section')) if isinstance(extension, dict) else None
        if (isinstance(extension, dict) and section is None and extension.get('state') == 'ghost'
                and extension.get('why') and _point(extension.get('position'))
                and extension.get('kind') == 'awning'
                and all(_number(extension.get(k)) for k in ('x0', 'x1', 'depth', 'pitch', 'eave'))
                and extension['x0'] < extension['x1'] and extension['depth'] > 0
                and 0 < extension['pitch'] <= 24):
            extensions.append(extension)
            continue
        valid = section is not None
        if valid and extension.get('kind') == 'shed_continuation':
            valid = (all(_number(extension.get(k)) for k in ('to_x', 'pitch'))
                     and extension['to_x'] > section['rect'][2]
                     and _numeric_fields(extension, ('overhang',)))
        elif valid and extension.get('kind') == 'awning':
            valid = (all(_number(extension.get(k)) for k in ('x0', 'x1', 'depth', 'pitch', 'eave'))
                     and extension['x0'] < extension['x1'] and extension['depth'] > 0
                     and _numeric_fields(extension, ('brackets',)))
            if 'wall' in extension and (not isinstance(extension['wall'], str)
                                        or not any(w['id'] == extension['wall'] for w in building['walls'])):
                notes.append(f'Roof extension {index}: dropped invalid or unknown wall reference; kept the awning.')
                del extension['wall']
        else:
            valid = False
        if valid and 0 < extension['pitch'] <= 24:
            extensions.append(extension)
        else:
            notes.append(f'Dropped roof extension {index}: malformed extension.')
    building['roof'] = {'sections': list(sections.values()), 'extensions': extensions}
    if isinstance(roof.get('choices'), list):
        building['roof']['choices'] = deepcopy(_roof_entries(roof, 'choices'))
    if isinstance(roof.get('flags'), list):
        building['roof']['flags'] = deepcopy(_roof_entries(roof, 'flags'))
    return sections


def _opening_error(opening, walls, sections):
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
        section = _lookup(sections, opening.get('section'))
        if section is None or section['kind'] not in ('gable', 'hip'):
            return 'unknown gable section'
        end = f"{section['ridge']}{0 if opening['gable'] == 'front' else 1}"
        if section.get('ends', {}).get(end, section['kind']) not in ('gable', 'clip'):
            return 'unknown gable section'
        axis = 1 if section['ridge'] == 'x' else 0
        centre = opening.get('y' if axis else 'x')
        lo, hi = section['rect'][axis], section['rect'][axis + 2]
        if (not all(_number(value) for value in (centre, lo, hi))
                or lo >= hi or centre - width / 2 < lo - 1e-6
                or centre + width / 2 > hi + 1e-6):
            return 'outside the roof gable span'
        if section.get('ends', {}).get(end) == 'clip':
            across = ('y0', 'y1') if axis else ('x0', 'x1')
            pitches = section.get('pitches') or {}
            a, b = (pitches.get(side, section['pitch']) / 12 for side in across)
            rise = (hi - lo) * a * b / (a + b)
            if head > rise * 2 / 3 + 1e-6:
                return 'head is above the clipped gable height'
    return None


def _openings(building, walls, sections, notes):
    openings = []
    for index, opening in enumerate(_items(building, 'openings', notes)):
        if (isinstance(opening, dict) and opening.get('kind') in ('door', 'slider', 'passage')
                and 'sill' not in opening):
            opening['sill'] = 0
            notes.append(f'Opening {index}: defaulted missing sill to 0 feet.')
        reason = _opening_error(opening, walls, sections)
        if (reason in ('unknown wall', 'outside the wall span', 'head is above the wall height',
                       'unknown gable (expected front or rear)', 'unknown gable section',
                       'outside the roof gable span', 'head is above the clipped gable height')
                and isinstance(opening, dict) and opening.get('state') == 'ghost'
                and opening.get('why') and _point(opening.get('position'))
                and any(f.get('piece') == opening.get('id')
                        for f in building.get('flags', []) if isinstance(f, dict))):
            # The connected bridge retains located failures for hand repair.
            reason = None
        if (reason in ('unknown gable section', 'outside the roof gable span', 'head is above the clipped gable height')
                and opening.get('state') == 'ghost' and opening.get('why')
                and _point(opening.get('position'))):
            # A replaced roof may leave an opening without a matching end.
            # Keep its located diagnostic for a person to place, not a hole.
            reason = None
        if (reason in ('outside the wall span', 'head is above the wall height')
                and opening.get('state') == 'ghost' and opening.get('why')
                and opening.get('src', {}).get('step') == 'draft'):
            # Draft checks retain readable, referenced failures for hand repair.
            # The generator displays them clamped to their carrier as ghost
            # outlines, excluding them from wall holes and opening frames.
            reason = None
        if reason:
            name = (opening.get('wall', opening.get('gable', index))
                    if isinstance(opening, dict) else index)
            notes.append(f'Dropped opening on {name}: {reason}.')
        else:
            openings.append(opening)
    _piece_meta(openings, 'opening', notes)
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
    _piece_meta(rooms, 'room', notes)
    building['rooms'] = rooms


def _details(building, levels, notes):
    def porch_detail(porch):
        if (not isinstance(porch, dict) or not _polygon(porch.get('polygon'))
                or not _numeric_fields(porch, ('floor',))):
            notes.append('Dropped porch: invalid polygon or floor.')
            return None
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
            if 'screened' in porch and type(porch['screened']) is not bool:
                del porch['screened']
            return porch

    if building.get('porch') is not None:
        building['porch'] = porch_detail(building['porch'])
    if 'porches' in building:
        porches = [p for item in _items(building, 'porches', notes)
                   if (p := porch_detail(item)) is not None]
        _piece_meta(porches, 'porch', notes)
        building['porches'] = porches
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
        if name == 'stairs':
            _piece_meta(valid_items, 'stair', notes)
        building[name] = valid_items


def _site(site, notes):
    if site.get('lot') is not None and not _polygon(site['lot']):
        site['lot'] = None
        notes.append('Dropped site lot: invalid polygon.')
    pool = site.get('pool')
    if pool is not None and (not isinstance(pool, dict) or not _polygon(pool.get('polygon'))
                             or not _numeric_fields(pool, ('depth', 'coping', 'elevation'))):
        site['pool'] = None
        notes.append('Dropped site pool: invalid polygon or dimensions.')
    fire = site.get('fire_pit')
    if fire is not None and (not isinstance(fire, dict) or not _point(fire.get('at'))
                             or not _number(fire.get('radius')) or fire['radius'] <= 0
                             or not _numeric_fields(fire, ('elevation',))):
        site['fire_pit'] = None
        notes.append('Dropped site fire_pit: invalid at, radius or elevation.')
    for name in ('beds', 'planting', 'furniture', 'edges', 'hardscape', 'terraces'):
        kept = []
        for index, item in enumerate(_items(site, name, notes)):
            valid = isinstance(item, dict)
            if valid and name == 'terraces':
                valid = (_polygon(item.get('polygon')) and _number(item.get('height'))
                         and -50 <= item['height'] <= 50 and _numeric_fields(item, ('elevation',)))
            elif valid and name in ('beds', 'hardscape'):
                valid = _polygon(item.get('polygon')) and _numeric_fields(item, ('height', 'elevation'))
            elif valid and name == 'edges':
                points = item.get('points', item.get('polyline'))
                valid = (isinstance(points, list) and len(points) >= 2 and all(_point(p) for p in points)
                         and _numeric_fields(item, ('elevation',)))
            elif valid:
                valid = (_point(item.get('at'))
                         and _numeric_fields(item, ('height', 'rotation', 'scale', 'elevation', 'seed')))
            if valid:
                kept.append(item)
            else:
                label = item.get('id', index) if isinstance(item, dict) else index
                notes.append(f'Dropped {name} entry {label}: invalid coordinates or dimensions.')
        site[name] = kept
    pieces = [item for name in ('pool', 'fire_pit', 'fence')
              if isinstance((item := site.get(name)), dict)]
    pieces.extend(item for name in ('beds', 'planting', 'furniture', 'edges', 'hardscape', 'terraces')
                  for item in site[name])
    _piece_meta(pieces, 'site', notes)


def normalize(raw: dict) -> tuple[dict, list[str]]:
    """Copy a plan, default optional lists, and drop invalid geometry with notes.

    Caps retain the first entries, with one aggregate note per truncated list.
    Gable coordinates use plan x; wall offsets and opening heights are local to
    the referenced wall, regardless of its level's elevation.
    Connected-model extras (joints, footprints, faces, hosts, materials,
    proposals and flags) remain on the copied records without filtering.
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
        building.setdefault('position', [0, 0])
        rotation = building.get('rotation', 0)
        if not _number(rotation):
            rotation = 0
            notes.append(f"Building {building.get('id', index)}: defaulted invalid rotation to 0.")
        rotation %= 360
        # Tiny negative floats can round up to 360 during modulo.
        building['rotation'] = 0 if rotation == 360 else rotation
        base = building.get('base', 0)
        if not _number(base) or not -50 <= base <= 50:
            base = 0
            notes.append(f"Building {building.get('id', index)}: defaulted invalid base to 0.")
        building['base'] = base
        walls = _walls(building, levels, notes)
        sections = _roof(building, notes)
        _openings(building, walls, sections, notes)
        _rooms(building, levels, notes)
        _details(building, levels, notes)
        buildings.append(building)
    site = raw.get('site')
    if 'site' in raw and not isinstance(site, dict):
        notes.append('Coerced invalid site to an empty object.')
    site = site if isinstance(site, dict) else {}
    _site(site, notes)
    if not buildings and not _polygon(site.get('lot')):
        raise ValueError('Twin plan must contain at least one usable building.')
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
