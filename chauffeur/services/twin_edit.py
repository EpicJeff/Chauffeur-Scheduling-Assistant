"""Shared, pure house edits and their append-only storage boundary."""

from copy import deepcopy
import math
import uuid

from services import twin_plan, twin_register


EDITABLE = {
    'wall': ('height', 'thickness', 'exterior'),
    'opening': ('width', 'sill', 'head', 'kind', 'panels', 'at'),
    'room': ('name', 'ha_area'),
    'roof': ('kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side'),
    'building': ('name', 'position', 'rotation', 'base'),
    'level': ('name', 'elevation', 'ceiling'),
}
_OPENING_KINDS = ('window', 'door', 'slider', 'bifold', 'passage', 'garage')


def _number(value, label, minimum=None, maximum=None, positive=False):
    # Check the bound before isfinite, which converts ints to float and can
    # overflow on an LLM's arbitrarily large integer.
    if (type(value) not in (int, float) or not -1e5 <= value <= 1e5
            or not math.isfinite(value)
            or (positive and value <= 0)
            or (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)):
        raise ValueError(f'Invalid {label}.')
    return value


def _point(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f'{label} needs two coordinates.')
    return [_number(v, label) for v in value]


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text.')
    return value


def _entries(plan):
    """Yield kind, piece, building and containing list, without global id maps."""
    for building in plan['buildings']:
        yield 'building', building, building, plan['buildings']
        for name, kind in (('levels', 'level'), ('walls', 'wall'),
                           ('openings', 'opening'), ('rooms', 'room'),
                           ('stairs', 'stair'), ('fixtures', 'fixture'),
                           ('lights', 'light')):
            for piece in building.get(name, []):
                yield kind, piece, building, building[name]
        for piece in building['roof']['sections']:
            yield 'roof', piece, building, building['roof']['sections']


def _find(plan, piece_id, building=None, kind=None):
    _text(piece_id, 'Piece id')
    if building is not None:
        _text(building, 'Building id')
    matches = [entry for entry in _entries(plan)
               if entry[1].get('id') == piece_id
               and (building is None or entry[2].get('id') == building)
               and (kind is None or entry[0] == kind)]
    if not matches:
        raise ValueError(f'Unknown piece {piece_id}.')
    if len(matches) != 1:
        raise ValueError(f'Piece {piece_id} is ambiguous; name its building.')
    return matches[0]


def _mark(piece):
    src = piece.get('src') or {}
    piece['src'] = {'person': True, **{k: src[k] for k in ('sheet', 'page') if k in src}}


FIELD_LABELS = {
    'ha_area': 'Home Assistant area', 'low_side': 'Low side', 'at': 'Distance along the wall',
    'sill': 'Height above floor', 'head': 'Top of opening', 'plate': 'Wall height under the roof',
    'base': 'Height above ground', 'elevation': 'Height above ground',
}


def _floor_name(level, building):
    if level.get('name'):
        return level['name']
    levels = sorted(building.get('levels', []), key=lambda row: row.get('elevation', 0))
    return f'Floor {levels.index(level) + 1}' if level in levels else 'floor'


def _label(kind, piece, building=None):
    """Plain identity shared by edit summaries and the editor's About prompt."""
    if piece.get('name'):
        return f'the {piece["name"]}'
    building = building or {}
    if kind == 'level':
        return f'the {_floor_name(piece, building)}'
    level_id = piece.get('level')
    if kind == 'opening':
        wall = next((w for w in building.get('walls', []) if w['id'] == piece.get('wall')), {})
        section = next((s for s in building.get('roof', {}).get('sections', []) if s['id'] == piece.get('section')), {})
        level_id = wall.get('level', section.get('level', level_id))
    level = next((l for l in building.get('levels', []) if l['id'] == level_id), {})
    floor = _floor_name(level, building)
    if kind == 'wall':
        points = [p for w in building.get('walls', []) for p in (w['from'], w['to'])]
        if piece.get('exterior') and points:
            x0, y0 = [min(p[i] for p in points) for i in (0, 1)]
            x1, y1 = [max(p[i] for p in points) for i in (0, 1)]
            a, b = piece['from'], piece['to']
            side = ('front' if max(abs(p[1] - y0) for p in (a, b)) < .1 else
                    'back' if max(abs(p[1] - y1) for p in (a, b)) < .1 else
                    'left' if max(abs(p[0] - x0) for p in (a, b)) < .1 else
                    'right' if max(abs(p[0] - x1) for p in (a, b)) < .1 else None)
            if side:
                return f'the {floor} {side} wall'
        return f'a {floor} wall'
    if kind == 'opening':
        name = {'slider': 'sliding door', 'bifold': 'folding door', 'garage': 'garage door',
                'passage': 'open passage'}.get(piece.get('kind'), piece.get('kind', 'opening'))
        return f'a {floor} {name}'
    return {'roof': 'a roof section', 'building': 'the house', 'level': 'the floor',
            'room': 'a room', 'stair': 'a staircase', 'fixture': 'a fixture', 'light': 'a light'}.get(kind, 'a piece')


def _wall(building, opening):
    wall = next((w for w in building['walls'] if w['id'] == opening.get('wall')), None)
    if wall is None:
        raise ValueError('This opening must reference a wall to slide along it.')
    return wall


def _wall_vector(wall):
    dx, dy = [wall['to'][i] - wall['from'][i] for i in (0, 1)]
    length = math.hypot(dx, dy)
    return [dx / length, dy / length], length


def _opening_valid(building, piece):
    reason = twin_plan._opening_error(
        piece, {w['id']: w for w in building['walls']},
        {s['id']: s for s in building['roof']['sections']})
    if reason:
        raise ValueError(f'Invalid opening: {reason}.')


def _set(kind, piece, building, field, value):
    if kind not in EDITABLE or field not in EDITABLE[kind]:
        raise ValueError(f'Cannot set {field} on a {kind}.')
    if field in ('name', 'ha_area'):
        if not isinstance(value, str):
            raise ValueError(f'{field} must be text.')
    elif field == 'position':
        value = _point(value, field)
    elif field == 'exterior':
        if type(value) is not bool:
            raise ValueError('exterior must be true or false.')
    elif field in ('kind', 'ridge', 'low_side'):
        choices = (_OPENING_KINDS if kind == 'opening' else
                   ('hip', 'gable', 'shed', 'flat') if field == 'kind' else
                   ('x', 'y') if field == 'ridge' else ('x0', 'x1', 'y0', 'y1'))
        if value not in choices:
            raise ValueError(f'Invalid {field}.')
    elif field == 'panels':
        _number(value, field, positive=True)
        if type(value) is not int or value < 1:
            raise ValueError('panels must be a positive integer.')
    else:
        _number(value, field)
        if field in ('height', 'thickness', 'width', 'head', 'plate', 'ceiling'):
            _number(value, field, positive=True)
        elif field in ('at', 'sill', 'overhang'):
            _number(value, field, minimum=0, maximum=4 if field == 'overhang' else None)
        elif field == 'pitch':
            _number(value, field, minimum=0 if piece['kind'] == 'flat' else 1,
                    maximum=0 if piece['kind'] == 'flat' else 24)
        elif field == 'base':
            _number(value, field, minimum=-50, maximum=50)
        elif field == 'rotation':
            value %= 360
            value = 0 if value == 360 else value
    if piece.get(field) == value:
        raise ValueError('Nothing changed')
    piece[field] = deepcopy(value)
    if kind == 'roof':
        if field == 'pitch':
            piece['pitch_source'] = 'person'
        # A kind switch needs usable directions without an intermediate bad roof.
        if field == 'kind':
            if value in ('hip', 'gable'):
                piece.setdefault('ridge', 'y')
            elif value == 'shed':
                piece.setdefault('low_side', 'x0')
            piece['pitch'] = 0 if value == 'flat' else max(1, piece['pitch'])
    if kind == 'opening':
        _opening_valid(building, piece)
    elif kind == 'wall':
        for opening in building['openings']:
            if opening.get('wall') == piece['id']:
                _opening_valid(building, opening)
    _mark(piece)


def _transform(piece, transform):
    def point(value):
        return _point(transform(value), 'Transformed point')

    for field in ('from', 'to', 'position'):
        if field in piece:
            piece[field] = point(piece[field])
    if isinstance(piece.get('at'), (list, tuple)):
        piece['at'] = point(piece['at'])
    for field in ('polygon', 'points', 'polyline'):
        if field in piece:
            piece[field] = [point(p) for p in piece[field]]
    if 'rect' in piece:
        x0, y0, x1, y1 = piece['rect']
        points = [point(p) for p in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        piece['rect'] = [min(p[0] for p in points), min(p[1] for p in points),
                         max(p[0] for p in points), max(p[1] for p in points)]


def _shift_gables(building, section, old_rect):
    axis = 0 if section['ridge'] == 'y' else 1
    delta = section['rect'][axis] - old_rect[axis]
    for opening in building['openings']:
        if 'gable' in opening and opening.get('section') == section['id'] and delta:
            opening['x'] = _number(opening['x'] + delta, 'Gable opening x')
            _mark(opening)


def _removed(before, after):
    identities = {(b['id'], kind, p['id']) for kind, p, b, _ in _entries(after) if 'id' in p}
    # Legacy fixtures and lights need not have ids. Match those by value so a
    # level deletion still records each one, including identical instances.
    unkeyed = [(b['id'], kind, p) for kind, p, b, _ in _entries(after) if 'id' not in p]
    removed = []
    for kind, piece, building, _ in _entries(before):
        if 'id' in piece:
            if (building['id'], kind, piece['id']) in identities:
                continue
        elif (building['id'], kind, piece) in unkeyed:
            unkeyed.remove((building['id'], kind, piece))
            continue
        removed.append((kind, piece, building))
    return removed


def _new_id(plan, building, kind):
    used = {p['id'] for k, p, b, _ in _entries(plan) if k == kind and b is building}
    n = 1
    while f'{kind}-{n}' in used:
        n += 1
    return f'{kind}-{n}'


def _wall_length(wall):
    length = math.dist(wall['from'], wall['to'])
    if not 0.5 <= length <= 1e4:
        raise ValueError('A wall must be between 0.5 and 10000 feet long.')


def _registration(value):
    if not isinstance(value, dict):
        raise ValueError('A registration must be an object.')
    return twin_register.make(_number(value.get('scale'), 'scale', positive=True),
                              _number(value.get('angle'), 'angle'),
                              _point(value.get('origin_px'), 'origin_px'),
                              _point(value.get('offset'), 'offset'))


def _register(plan, edit):
    source = _text(edit.get('source'), 'Source')
    page = edit.get('page')
    _number(page, 'Page', positive=True)
    if type(page) is not int or page < 1:
        raise ValueError('Page must be a positive integer.')
    level = _text(edit.get('level'), 'Level')
    if edit.get('from_reg') is None:
        raise ValueError('No registration on file for this sheet yet')
    old, new = _registration(edit.get('from_reg')), _registration(edit.get('reg'))
    if old == new:
        raise ValueError('Nothing changed')
    scale = _number(new['scale'] / old['scale'], 'Registration scale ratio', positive=True)

    def transform(point):
        return _point(twin_register.apply(new, twin_register.invert(old, point)),
                      'Registered point')

    selected = []
    for kind, piece, building, _ in _entries(plan):
        if edit.get('building') is not None and building.get('id') != edit['building']:
            continue
        src = piece.get('src') or {}
        piece_level = piece.get('level')
        if kind == 'opening' and 'wall' in piece:
            piece_level = _wall(building, piece)['level']
        elif kind == 'opening' and 'gable' in piece:
            section = next(s for s in building['roof']['sections'] if s['id'] == piece['section'])
            piece_level = section.get('level')
        if src.get('sheet') == source and src.get('page') == page and piece_level == level:
            selected.append((kind, piece, building))
    # Capture centres before transforming walls; an opening may have different provenance.
    centres = {}
    moved_openings = set()
    for kind, piece, building in selected:
        if kind == 'opening' and 'wall' in piece:
            wall = _wall(building, piece)
            unit, _ = _wall_vector(wall)
            centre = [wall['from'][i] + unit[i] * piece['at'] for i in (0, 1)]
            centres[id(piece)] = transform(centre)
            if centres[id(piece)] != centre:
                moved_openings.add(id(piece))
    for kind, piece, building in selected:
        if kind != 'opening':
            original = deepcopy(piece)
            _transform(piece, transform)
            if kind == 'roof' and piece.get('ridge') in ('x', 'y'):
                _shift_gables(building, piece, original['rect'])
            if piece != original:
                _mark(piece)
    for kind, piece, building in selected:
        if kind == 'opening':
            original = deepcopy(piece)
            if 'wall' in piece:
                wall = _wall(building, piece)
                unit, _ = _wall_vector(wall)
                piece['at'] = _number(sum((centres[id(piece)][i] - wall['from'][i]) * unit[i]
                                         for i in (0, 1)), 'Opening at')
            piece['width'] = _number(piece['width'] * scale, 'Opening width', positive=True)
            _opening_valid(building, piece)
            if piece != original or id(piece) in moved_openings:
                _mark(piece)
    floor = next((l for b in plan['buildings'] if edit.get('building') in (None, b['id'])
                  for l in b['levels'] if l['id'] == level), {})
    return f'Lined up the drawing for {floor.get("name") or "the floor"}'


def _value_words(field, value):
    if field == 'ridge':
        return {'x': 'left to right', 'y': 'front to back'}.get(value, value)
    if field == 'low_side':
        return {'x0': 'left', 'x1': 'right', 'y0': 'front', 'y1': 'back'}.get(value, value)
    if field == 'kind':
        return {'slider': 'sliding door', 'bifold': 'folding door', 'passage': 'open passage',
                'garage': 'garage door', 'shed': 'one slope'}.get(value, value)
    if field == 'rotation':
        return f'{value:g}°'
    if field == 'pitch':
        return f'{value:g} in 12'
    if field == 'position':
        return ', '.join(twin_register.feet_inches(v) for v in value)
    if type(value) is bool:
        return 'yes' if value else 'no'
    if field in ('panels',):
        return str(value)
    if type(value) in (int, float):
        return twin_register.feet_inches(value)
    return value


def apply(plan, edit):
    """Return an edited, normalized copy and plain summary; never write storage."""
    if not isinstance(edit, dict):
        raise ValueError('An edit must be an object.')
    result, _ = twin_plan.normalize(plan)
    before = deepcopy(result)
    added = None
    op, scope = edit.get('op'), edit.get('building')
    if scope is not None:
        _find(result, scope, kind='building')
    if op == 'registration':
        summary = _register(result, edit)
    elif op == 'accept':
        ids = edit.get('pieces')
        if not isinstance(ids, list) or not ids:
            raise ValueError('Accept needs a list of piece ids.')
        for pid in ids:
            _, piece, _, _ = _find(result, pid, scope)
            if piece.get('state', 'settled') != 'settled':
                piece['state'] = 'settled'
                _mark(piece)
        summary = f'Accepted {len(ids)} piece' + ('' if len(ids) == 1 else 's')
    elif op == 'add_wall':
        _, level, building, _ = _find(result, edit.get('level'), scope, 'level')
        start, end = _point(edit.get('from'), 'from'), _point(edit.get('to'), 'to')
        _wall_length({'from': start, 'to': end})
        added = ('wall', _new_id(result, building, 'wall'), building['id'])
        building['walls'].append({'id': added[1], 'level': level['id'], 'from': start, 'to': end,
                                  'height': level['ceiling'], 'thickness': 0.33,
                                  'exterior': False, 'state': 'settled', 'src': {'person': True}})
        if len(building['walls']) > twin_plan.CAPS['walls']:
            raise ValueError('The building has too many walls.')
        summary = f'Added a wall on {_floor_name(level, building)}'
    elif op == 'add_opening':
        _, wall, building, _ = _find(result, edit.get('wall'), scope, 'wall')
        _wall_length(wall)
        kind = edit.get('kind')
        if kind not in _OPENING_KINDS:
            raise ValueError('Invalid opening kind.')
        added = ('opening', _new_id(result, building, 'opening'), building['id'])
        piece = {'id': added[1], 'wall': wall['id'], 'kind': kind,
                 'at': _number(edit.get('at'), 'at', minimum=0),
                 'width': _number(edit.get('width'), 'width', positive=True),
                 'sill': min(2, wall['height'] / 3) if kind == 'window' else 0,
                 'head': min(7, wall['height']), 'state': 'settled', 'src': {'person': True}}
        _opening_valid(building, piece)
        building['openings'].append(piece)
        if len(building['openings']) > twin_plan.CAPS['openings']:
            raise ValueError('The building has too many openings.')
        name = {'slider': 'sliding door', 'bifold': 'folding door', 'garage': 'garage door', 'passage': 'passage'}.get(kind, kind)
        summary = f'Added a {name} to {_label("wall", wall, building)}'
    elif op in ('set', 'move', 'rotate', 'delete'):
        pid = scope if op == 'rotate' else edit.get('piece')
        kind, piece, building, owner = _find(result, pid, scope,
                                             'building' if op == 'rotate' else None)
        label = _label(kind, piece, building)
        if op == 'set':
            field = edit.get('field')
            _set(kind, piece, building, field, edit.get('value'))
            field_label = FIELD_LABELS.get(field, field.capitalize()).lower()
            summary = f'Set {label}\'s {field_label} to {_value_words(field, piece[field])}'
        elif op == 'rotate':
            about = _point(edit['about'], 'about') if 'about' in edit else None
            fixed = twin_register.to_world(building, about) if about is not None else None
            _set(kind, piece, building, 'rotation', edit.get('to'))
            if about is not None:
                turned = twin_register.to_world(building, about)
                piece['position'] = _point([piece['position'][i] + fixed[i] - turned[i]
                                             for i in (0, 1)], 'position')
            summary = f'Turned {label} to {piece["rotation"]:g}°'
        elif op == 'delete':
            owner.remove(piece)
            summary = f'Removed {label}'
        else:
            dx, dy = _point(edit.get('by'), 'by')
            original = deepcopy(piece)
            if kind == 'opening':
                wall = _wall(building, piece)
                unit, length = _wall_vector(wall)
                at = max(piece['width'] / 2, min(length - piece['width'] / 2,
                         piece['at'] + dx * unit[0] + dy * unit[1]))
                dx, dy = [(at - piece['at']) * v for v in unit]
                piece['at'] = at
            elif kind in ('wall', 'room', 'roof', 'building', 'stair', 'fixture', 'light'):
                old_rect = deepcopy(piece.get('rect'))
                _transform(piece, lambda p: [p[0] + dx, p[1] + dy])
                if kind == 'roof' and piece.get('ridge') in ('x', 'y'):
                    _shift_gables(building, piece, old_rect)
            else:
                raise ValueError(f'Cannot move a {kind}.')
            if piece == original:
                raise ValueError('Nothing changed')
            _mark(piece)
            direction = ('toward the rear' if dy >= 0 else 'toward the front') if abs(dy) >= abs(dx) else (
                'to the right' if dx >= 0 else 'to the left')
            summary = f'Moved {label} {twin_register.feet_inches(math.hypot(dx, dy))} {direction}'
    else:
        raise ValueError(f'Unknown edit operation {op}.')
    normalized, _ = twin_plan.normalize(result)
    # Edits must never silently discard a piece as a side effect of bad input.
    if op not in ('delete', 'add_wall', 'add_opening') and twin_plan.diff_paths(result, normalized):
        raise ValueError('The edit would create invalid geometry or dimensions.')
    if added is not None:
        added_kind, added_id, added_building = added
        if not any(k == added_kind and p['id'] == added_id and b['id'] == added_building
                   for k, p, b, _ in _entries(normalized)):
            raise ValueError('The added piece did not survive normalization.')
    if not twin_plan.diff_paths(before, normalized):
        raise ValueError('Nothing changed')
    if op == 'delete':
        counts = {}
        for removed_kind, removed_piece, removed_building in _removed(before, normalized):
            if (removed_kind, removed_piece.get('id'), removed_building['id']) == (kind, piece['id'], building['id']):
                continue
            counts[removed_kind] = counts.get(removed_kind, 0) + 1
        if counts:
            summary += ' and ' + ', '.join(
                f'{count} {name}' + ('' if count == 1 else 's') for name, count in counts.items())
            summary += ' on it' if kind in ('wall', 'roof') else ' in it'
    return normalized, summary


def _tombstone(kind, piece, building):
    geometry = {k: deepcopy(piece[k]) for k in
                ('from', 'to', 'polygon', 'rect', 'position', 'at', 'points', 'polyline') if k in piece}
    level = piece['id'] if kind == 'level' else piece.get('level')
    if kind == 'opening':
        if 'wall' in piece:
            wall = _wall(building, piece)
            unit, _ = _wall_vector(wall)
            geometry = {key: [wall['from'][i] + unit[i] * distance for i in (0, 1)]
                        for key, distance in (('from', piece['at'] - piece['width'] / 2),
                                              ('to', piece['at'] + piece['width'] / 2))}
            level = wall['level']
        else:
            section = next(s for s in building['roof']['sections'] if s['id'] == piece['section'])
            axis = 0 if section['ridge'] == 'y' else 1
            edge = section['rect'][(1 - axis) + (0 if piece['gable'] == 'front' else 2)]
            geometry = {key: ([distance, edge] if axis == 0 else [edge, distance])
                        for key, distance in (('from', piece['x'] - piece['width'] / 2),
                                              ('to', piece['x'] + piece['width'] / 2))}
            level = section.get('level')
    return {'kind': kind, 'level': level, 'geometry': geometry,
            'src': deepcopy(piece.get('src') or {})}


def save(edit, actor_id, reason=''):
    """Edit the latest round, preserving provenance, history and P0 fix kinds."""
    from services import twin_store

    if not isinstance(reason, str):
        raise ValueError('The reason must be text.')
    if not isinstance(edit, dict):
        raise ValueError('An edit must be an object.')
    edit = deepcopy(edit)
    # Same lock order as update_current/start_over. Keep the snapshot, new round,
    # fixes and ancillary metadata together against other readers and writers.
    with twin_store.LIFECYCLE, twin_store._LOCK:
        before = twin_store.current()
        if before is None:
            raise ValueError('Build a house before editing it.')
        if edit.get('op') == 'registration':
            edit['from_reg'] = twin_store.registration(edit.get('source'), edit.get('page'), edit.get('level'))
            if edit['from_reg'] is None:
                raise ValueError('No registration on file for this sheet yet')
            edit['reg'] = _registration(edit.get('reg'))
            twin_store._source_page(twin_store._state(), edit.get('source'), edit.get('page'))
        after, summary = apply(before, edit)
        tombstones = ([_tombstone(*entry) for entry in _removed(before, after)]
                      if edit.get('op') == 'delete' else [])
        changes = [{'path': path, 'kind': twin_store._fix_kind(path),
                    'before': twin_store._leaf(before, path), 'after': twin_store._leaf(after, path),
                    'reason': reason.strip() or summary, 'actor_id': actor_id}
                   for path in twin_plan.diff_paths(before, after)
                   if twin_store._fix_kind(path) is not None]
        round_id = twin_store.update_current(
            lambda current: after, 'edit', note=summary,
            step={'id': f'edit:{uuid.uuid4().hex}', 'label': summary})
        row = twin_store._state()
        at = next(r['created'] for r in row['rounds'] if r['id'] == round_id)
        row['fixes'].extend({**change, 'round': round_id, 'at': at} for change in changes)
        twin_store._save(row)
        for tombstone in tombstones:
            twin_store.add_tombstone(tombstone)
        if edit.get('op') == 'registration':
            twin_store.set_registration(edit['source'], edit['page'], edit['level'], edit['reg'])
        return {'round': round_id, 'summary': summary}
