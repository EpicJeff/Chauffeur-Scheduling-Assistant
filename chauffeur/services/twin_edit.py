"""Shared, pure house edits and their append-only storage boundary."""

from copy import deepcopy
import math
import re

from services.twin_timing import timed as _edit_timed
from services import twin_joints, twin_plan, twin_register


EDITABLE = {
    'wall': ('height', 'thickness', 'exterior'),
    'opening': ('width', 'sill', 'head', 'kind', 'panels', 'at'),
    'room': ('name', 'ha_area', 'floor_offset_ft'),
    'roof': ('kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side', 'ends'),
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
                if name == 'lights' and piece.get('surface'):
                    continue  # The anchor below owns this read fixture's tombstone.
                yield kind, piece, building, building[name]
        for piece in building.get('anchors', []):
            if piece.get('surface'):
                yield 'fixture', piece, building, building['anchors']
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
    from services.twin_floors import opening_reference
    wall = next((w for w in building['walls'] if w['id'] == piece.get('wall')), None)
    reference = opening_reference(building, wall, piece['at'])[0] if wall else 0
    reason = twin_plan._opening_error(
        piece, {w['id']: w for w in building['walls']},
        {s['id']: s for s in building['roof']['sections']}, reference)
    if reason:
        raise ValueError(f'Invalid opening: {reason}.')


def _ha_area(value, ha_catalogue=None):
    from services import twin_ha
    if not isinstance(value, str):
        raise ValueError('ha_area must be text.')
    if not value:
        return ''
    areas = (ha_catalogue if ha_catalogue is not None else twin_ha.safe_catalogue()).get('areas', [])
    if not areas:
        return value
    resolved = twin_ha.resolve_area(value, areas)
    if resolved is None:
        raise ValueError('Pick an area from Home Assistant.')
    return resolved


def _set(kind, piece, building, field, value, ha_catalogue=None):
    if kind not in EDITABLE or field not in EDITABLE[kind]:
        raise ValueError(f'Cannot set {field} on a {kind}.')
    if field == 'ha_area':
        value = _ha_area(value, ha_catalogue)
    elif field == 'floor_offset_ft':
        from services.twin_floors import offset_error
        reason = offset_error(value)
        if reason:
            raise ValueError(reason)
    elif field == 'name':
        if not isinstance(value, str):
            raise ValueError(f'{field} must be text.')
    elif field == 'position':
        value = _point(value, field)
    elif field == 'exterior':
        if type(value) is not bool:
            raise ValueError('exterior must be true or false.')
    elif field == 'ends':
        allowed = (f"{piece.get('ridge')}0", f"{piece.get('ridge')}1")
        if (piece['kind'] not in ('gable', 'hip') or not isinstance(value, dict)
                or any(end not in allowed or style not in ('gable', 'hip', 'clip')
                       for end, style in value.items())):
            raise ValueError('Roof ends must be gable, hip or clipped gable on the ridge ends.')
        for opening in building['openings']:
            if opening.get('section') == piece['id'] and 'gable' in opening:
                end = f"{piece['ridge']}{0 if opening['gable'] == 'front' else 1}"
                if value.get(end, piece['kind']) == 'hip':
                    raise ValueError('A window sits in that gable; move or delete it first.')
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
    if piece.get(field) == value and field != 'ha_area':
        raise ValueError('Nothing changed')
    old_roof = deepcopy(piece) if kind == 'roof' and field == 'kind' else None
    piece[field] = deepcopy(value)
    if kind == 'roof':
        if field == 'ridge' and piece.get('ends'):
            piece['ends'] = {f'{value}{end[-1]}': style for end, style in piece['ends'].items()}
        if field == 'pitch':
            piece['pitch_source'] = 'person'
            piece.pop('pitches', None)
        # A kind switch needs usable directions without an intermediate bad roof.
        if field == 'kind':
            if value in ('shed', 'flat') or (value == 'hip' and piece.get('ends')
                                           and all(end == 'gable' for end in piece['ends'].values())):
                piece.pop('ends', None)
            if value in ('hip', 'gable'):
                piece.setdefault('ridge', 'y')
            elif value == 'shed':
                piece.setdefault('low_side', 'x0')
            piece['pitch'] = 0 if value == 'flat' else max(1, piece['pitch'])
            # Kinds and individual ends use the same window-bearing gable rule.
            for opening in building['openings']:
                if opening.get('section') != piece['id'] or 'gable' not in opening:
                    continue
                end = f"{old_roof.get('ridge')}{0 if opening['gable'] == 'front' else 1}"
                if (old_roof.get('ends', {}).get(end, old_roof['kind']) in ('gable', 'clip')
                        and (value in ('shed', 'flat') or piece.get('ends', {}).get(end, value) == 'hip')):
                    raise ValueError('A window sits in that gable; move or delete it first.')
        _choose_roof(building, piece)
    if kind == 'opening':
        _opening_valid(building, piece)
    elif kind == 'wall':
        for opening in building['openings']:
            if opening.get('wall') == piece['id']:
                _opening_valid(building, opening)
    _mark(piece)
    if kind == 'building' and field in ('position', 'rotation'):
        piece['position_from'] = 'person'


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
    field = 'y' if section['ridge'] == 'x' else 'x'
    delta = section['rect'][axis] - old_rect[axis]
    for opening in building['openings']:
        if 'gable' in opening and opening.get('section') == section['id'] and delta:
            opening[field] = _number(opening[field] + delta, f'Gable opening {field}')
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
    if field == 'ends':
        sides = {'x0': 'left', 'x1': 'right', 'y0': 'front', 'y1': 'back'}
        styles = {'gable': 'gable', 'hip': 'hip', 'clip': 'clipped gable'}
        return ', '.join(f'{sides[end]} {styles[style]}' for end, style in value.items()) or 'the roof defaults'
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


def _choose_roof(building, piece):
    block = piece.get('block')
    if (not block or piece.get('dormer_of')
            or max(abs(a - b) for a, b in zip(piece['rect'], block)) > 1
            or not (piece.get('src', {}).get('step') == 'roof_blocks'
                    or piece.get('src', {}).get('person'))):
        return False
    roof = building['roof']
    choice = {k: deepcopy(piece[k]) for k in
              ('kind', 'ridge', 'ends', 'pitch', 'plate', 'overhang', 'low_side') if k in piece}
    choice.update(rect=deepcopy(block), src={'person': True})
    def same_rect(rect):
        return bool(rect and len(rect) == 4
                    and max(abs(a - b) for a, b in zip(rect, block)) <= 1)
    roof['choices'] = [c for c in twin_plan._roof_entries(roof, 'choices') if not same_rect(c['rect'])] + [choice]
    roof['flags'] = [f for f in twin_plan._roof_entries(roof, 'flags') if not same_rect(f['block_rect'])]
    return True


def _apply_legacy(plan, edit, ha_catalogue=None):
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
            kind, piece, building, _ = _find(result, pid, scope)
            if kind == 'roof':
                _choose_roof(building, piece)
            if kind == 'opening':
                reason = twin_plan._opening_error(piece, {w['id']: w for w in building['walls']},
                                                  {s['id']: s for s in building['roof']['sections']})
                if reason:
                    noun = {'window': 'window', 'door': 'door', 'slider': 'sliding door',
                            'garage_door': 'garage door', 'passage': 'passage'}.get(piece.get('kind'), 'opening')
                    detail = {
                        'outside the wall span': 'does not fit on its wall. Move it onto the wall or delete it.',
                        'head is above the wall height': 'is taller than its wall. Lower its top or delete it.',
                        'outside the roof gable span': 'does not fit on its gable. Move it onto the gable or delete it.',
                    }.get(reason, 'could not be accepted. Adjust it or delete it.')
                    raise ValueError(f'This {noun} {detail}')
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
        name = {'slider': 'sliding door', 'bifold': 'folding door', 'garage': 'garage door', 'passage': 'passage'}.get(kind, kind)
        if twin_plan._opening_error(piece, {w['id']: w for w in building['walls']}, {}) == 'outside the wall span':
            raise ValueError(f'The {name} does not fit on that wall there. Pick a longer stretch of wall.')
        _opening_valid(building, piece)
        building['openings'].append(piece)
        if len(building['openings']) > twin_plan.CAPS['openings']:
            raise ValueError('The building has too many openings.')
        summary = f'Added a {name} to {_label("wall", wall, building)}'
    elif op in ('set', 'move', 'rotate', 'delete'):
        pid = scope if op == 'rotate' else edit.get('piece')
        kind, piece, building, owner = _find(result, pid, scope,
                                             'building' if op == 'rotate' else None)
        label = _label(kind, piece, building)
        if op == 'set':
            field = edit.get('field')
            _set(kind, piece, building, field, edit.get('value'), ha_catalogue)
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
            if kind == 'building':
                piece['position_from'] = 'person'
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
    # Compare buildings after the edit, rather than relying on optional scope:
    # accept and registration may edit more than one building, and a deletion
    # may have removed the very piece used to find the owning building.
    originals = {b['id']: b for b in before['buildings']}
    for edited_building in normalized['buildings']:
        if edited_building != originals.get(edited_building['id']):
            twin_joints.snap(edited_building)
    return normalized, summary


@_edit_timed('apply')
def apply_model(model, edit, validated=None, ha_catalogue=None, *, _normalized=None):
    """Translate the old editor vocabulary at the connected-model boundary."""
    from services import twin_model_ops as ops, twin_model_bridge as bridge
    from services import twin_model_hosts as hosts, twin_model_roofs as roofs, twin_model

    if not isinstance(edit, dict):
        raise ValueError('An edit must be an object.')
    op = edit.get('op')
    if (op == 'set' and edit.get('field') == 'ha_area' or op == 'place_device'
            or edit.get('list') == 'yard_rooms' and 'ha_area' in edit) and ha_catalogue is None:
        from services import twin_ha
        ha_catalogue = twin_ha.safe_catalogue()
    if op == 'delete' and 'piece' in edit:
        anchors = [(b, a) for b in model['buildings'] for a in b.get('anchors', [])
                   if a['id'] == edit['piece'] and (not edit.get('building') or b['id'] == edit['building'])]
        if len(anchors) == 1:
            return ops.apply(model, {**edit, 'building': anchors[0][0]['id'], 'id': edit['piece']}, _normalized=_normalized)
    # A flag_ok set names a building's check, not a piece, so it carries no id.
    if (op in ops.MORE_OPS and (op not in ('set', 'add_opening') or 'id' in edit
                                or op == 'set' and edit.get('field') == 'flag_ok'
                                or op == 'add_opening' and 'model' in edit)
            or op in ('move_joint', 'move_wall', 'move_room', 'split_wall', 'draw_room', 'split_room')
            or op == 'delete' and 'id' in edit):
        return ops.apply(model, edit, ha_catalogue=ha_catalogue, _normalized=_normalized)

    flat = bridge.flatten(model)
    checked = deepcopy(edit)
    if op == 'add_opening':
        checked.setdefault('width', 3)
    legacy, summary = validated[:2] if validated is not None else _apply_legacy(flat, checked, ha_catalogue)
    comparison = validated[2] if validated is not None else flat
    scope = edit.get('building')
    if op in ('move', 'set', 'delete', 'rotate', 'add_wall', 'add_opening'):
        pid = (scope if op == 'rotate' else edit.get('level') if op == 'add_wall'
               else edit.get('wall') if op == 'add_opening' else edit.get('piece'))
        kind, piece, flat_building, _ = _find(flat, pid, scope)
        bid = flat_building['id']
        translated = {**checked, 'building': bid, 'id': pid}
        if op == 'move' and kind in ('wall', 'room', 'building', 'opening'):
            by = _point(edit.get('by'), 'by')
            if kind == 'building':
                translated.update(op='move_building', to=[piece['position'][i] + by[i] for i in (0, 1)])
            elif kind == 'opening':
                _, moved, _, _ = _find(legacy, pid, bid)
                translated.update(op='move_hosted', at=moved['at'])
            else:
                translated.update(op='move_' + kind)
                translated[kind] = pid
            result, _ = ops.apply(model, translated, _normalized=_normalized)
            return result, summary
        if op == 'rotate':
            translated.update(op='rotate_building', rotation=edit.get('to'))
            if 'about' in edit:
                translated['about'] = twin_register.to_world(flat_building, edit['about'])
            result, _ = ops.apply(model, translated, _normalized=_normalized)
            return result, summary
        if op in ('add_wall', 'add_opening') or op == 'set' and kind != 'roof':
            result, _ = ops.apply(model, translated, ha_catalogue=ha_catalogue, _normalized=_normalized)
            return result, summary
        if op == 'delete' and kind in ('wall', 'room', 'opening', 'roof'):
            # The legacy delete explicitly removes its dependants. New model
            # deletes retain lost hosts as ghosts, preserving the new UI's path.
            result, _ = ops.apply(model, translated, _normalized=_normalized)
            building = next(b for b in result['buildings'] if b['id'] == bid)
            removed = {p['id'] for _, p, b in _removed(flat, legacy) if b['id'] == bid}
            for anchor in building.get('anchors', []):
                if anchor['id'] in removed:
                    ops.release_anchor_device(building, anchor, hosts.snapshot(building))
            for name in ('openings', 'anchors', 'items', 'dormers', 'stairs'):
                building[name] = [p for p in building.get(name, []) if p['id'] not in removed]
            building['flags'] = [f for f in building['flags'] if not isinstance(f.get('piece'), str)
                                 or f['piece'] not in removed]
            return result, summary

    # Registration and legacy section operations already have validated geometry.
    # Apply only their changed pieces; never re-read over person-owned geometry.
    result = deepcopy(model)
    rebuilt, _ = bridge.assemble(legacy)
    remaining_buildings = {b['id'] for b in legacy['buildings']}
    result['buildings'] = [b for b in result['buildings'] if b['id'] in remaining_buildings]
    for building in result['buildings']:
        old_flat = next(b for b in comparison['buildings'] if b['id'] == building['id'])
        new_flat = next(b for b in legacy['buildings'] if b['id'] == building['id'])
        fresh = next(b for b in rebuilt['buildings'] if b['id'] == building['id'])
        before = hosts.snapshot(building)
        placed_hosts = []
        if op == 'delete':
            removed = {p['id'] for _, p, b in _removed(comparison, legacy)
                       if b['id'] == building['id'] and 'id' in p}
            for anchor in building.get('anchors', []):
                if anchor['id'] in removed:
                    ops.release_anchor_device(building, anchor, before)
            for name in ('walls', 'rooms', 'roofs', 'dormers', 'openings', 'anchors', 'items', 'levels', 'stairs'):
                building[name] = [p for p in building.get(name, []) if p['id'] not in removed]
        remaining_flags = new_flat['roof'].get('flags', [])
        building['flags'] = [f for f in building['flags'] if 'block_rect' not in f
                             or any(g.get('block_rect') == f['block_rect'] for g in remaining_flags)]
        changed_roofs = {p['id'] for p in new_flat['roof']['sections']
                         if p != next((q for q in old_flat['roof']['sections'] if q['id'] == p['id']), None)}
        for name in ('roofs', 'dormers'):
            for piece in building.get(name, []):
                if piece['id'] not in changed_roofs:
                    continue
                replacement = next((p for p in fresh[name] if p['id'] == piece['id']), None)
                if replacement is not None:
                    if name == 'roofs':
                        for edge, old_edge, (a, b), (c, d) in zip(replacement['edges'], piece['edges'],
                                roofs._segments(replacement['area']), roofs._segments(piece['area'])):
                            axis = 0 if abs(a[0] - b[0]) < 1e-9 else 1
                            if 'wall' in old_edge:
                                edge.update(wall=old_edge['wall'],
                                            wall_offset=old_edge.get('wall_offset', 0) + a[axis] - c[axis])
                    piece.clear()
                    piece.update(deepcopy(replacement))
                    _mark(piece)
        for name, source_name in (('openings', 'openings'), ('rooms', 'rooms'), ('levels', 'levels'),
                                   ('anchors', 'lights'), ('items', 'fixtures'), ('stairs', 'stairs')):
            old = {p.get('id', i): p for i, p in enumerate(old_flat.get(source_name, []))}
            changed = {p.get('id', i) for i, p in enumerate(new_flat.get(source_name, []))
                       if p != old.get(p.get('id', i))}
            for index, piece in enumerate(building.get(name, [])):
                if piece['id'] in changed or index in changed:
                    replacement = next((p for p in fresh.get(name, []) if p['id'] == piece['id']), None)
                    if replacement is not None:
                        if name in ('openings', 'anchors', 'items'):
                            placed_hosts.append((piece, replacement))
                        else:
                            piece.update(deepcopy(replacement))
                            _mark(piece)
        if op == 'registration':
            points = {j['id']: j for j in building['joints']}
            old_walls = {w['id']: w for w in old_flat['walls']}
            for wall in new_flat['walls']:
                if wall != old_walls.get(wall['id']):
                    connected = next((w for w in building['walls'] if w['id'] == wall['id']), None)
                    if connected:
                        for jid, key in zip(connected['joints'], ('from', 'to')):
                            points[jid]['at'] = deepcopy(wall[key])
                        _mark(connected)
        notes = twin_model.derive(building)
        notes.extend(hosts.follow(building, before))
        # Explicitly registered hosts already use the new sheet coordinates;
        # following their old surface as well would apply its scale twice.
        for piece, replacement in placed_hosts:
            piece.update(deepcopy(replacement))
            _mark(piece)
        if op == 'accept':
            for pid in edit['pieces']:
                if scope is not None and scope != building['id']:
                    continue
                try:
                    kind, piece = ops._piece(building, pid)
                except ops.Refused:
                    continue
                if kind == 'opening':
                    hosts.rehost(building, pid, hosts._host(piece, True))
                piece['state'] = 'settled'
                _mark(piece)
        ops._follow_dormers(building, before)
        prior = next(b for b in model['buildings'] if b['id'] == building['id'])
        ops.solar_clear(building, prior)
    return result, summary


def _legacy_flat(model, original):
    """Project migration-only splits back into an older flat caller's wall ids."""
    from services import twin_model_bridge as bridge
    flat = bridge.flatten(model)
    for building in flat['buildings']:
        source = next(b for b in original['buildings'] if b['id'] == building['id'])
        if 'joints' in source:
            continue
        old_ids = {w['id'] for w in source['walls']}
        hidden = {w['id'] for w in building['walls'] if w.get('kind') == 'separator'
                  and w.get('src', {}).get('step') == 'migration' and w['id'] not in old_ids}
        building['walls'] = [w for w in building['walls'] if w['id'] not in hidden]
        for old in source['walls']:
            parts = [w for w in building['walls'] if w['id'] == old['id']
                     or w['id'] not in old_ids and w['id'].startswith(old['id'] + '~')]
            if len(parts) < 2:
                continue
            unit, _ = _wall_vector(old)
            parts.sort(key=lambda w: sum((w['from'][i] - old['from'][i]) * unit[i] for i in (0, 1)))
            a, b = parts[0]['from'], parts[-1]['to']
            length = math.dist(a, b)
            if length == 0 or any(abs((p[0] - a[0]) * (b[1] - a[1]) -
                                     (p[1] - a[1]) * (b[0] - a[0])) > 1e-6
                                  for part in parts for p in (part['from'], part['to'])):
                continue
            merged = deepcopy(parts[0])
            merged.update(id=old['id'], **{'from': a, 'to': b})
            for key in ('joints', 'footprint'):
                merged.pop(key, None)
            if any(p.get('src', {}).get('person') for p in parts):
                _mark(merged)
            by_id = {p['id']: p for p in parts}
            for opening in building['openings']:
                part = by_id.get(opening.get('wall'))
                if part is not None:
                    direction, _ = _wall_vector(part)
                    point = [part['from'][i] + direction[i] * opening['at'] for i in (0, 1)]
                    opening.update(wall=old['id'], at=sum((point[i] - a[i]) * (b[i] - a[i])
                                                        for i in (0, 1)) / length)
            building['walls'] = [w for w in building['walls'] if w['id'] not in by_id] + [merged]
        source_walls = {w['id']: w for w in source['walls']}
        order = {w['id']: i for i, w in enumerate(source['walls'])}
        for wall in building['walls']:
            old = source_walls.get(wall['id'], {})
            for key in ('joints', 'footprint', 'kind'):
                if key not in old:
                    wall.pop(key, None)
        building['walls'].sort(key=lambda w: order.get(w['id'], len(order)))
        # This projection is for callers that still own flat geometry. Model
        # saves retain the full joint graph and separator flags.
        building.pop('joints', None)
    return flat


def apply(plan, edit):
    """Edit through the model, returning the caller's schema and plain words."""
    from services import twin_model_bridge as bridge, twin_model
    if not isinstance(edit, dict):
        raise ValueError('An edit must be an object.')
    if plan.get('schema') == twin_model.SCHEMA:
        return apply_model(plan, edit)
    legacy = None
    if edit.get('op') in ('move', 'rotate', 'registration', 'accept', 'add_wall', 'add_opening') or (
            edit.get('op') in ('set', 'delete') and 'piece' in edit):
        checked = deepcopy(edit)
        if checked.get('op') == 'add_opening':
            checked.setdefault('width', 3)
        legacy = (*_apply_legacy(plan, checked), plan)
    model, _ = bridge.assemble(plan)
    result, summary = apply_model(model, edit, validated=legacy)
    flat = _legacy_flat(result, plan)
    # Old callers still display the legacy roof-choice cards. Choices here are
    # a compatibility projection; the model keeps ownership on the roof itself.
    if (edit.get('op') == 'set' and 'piece' in edit) or edit.get('op') == 'accept':
        legacy, _ = _apply_legacy(plan, edit)
        for building in flat['buildings']:
            old = next(b for b in legacy['buildings'] if b['id'] == building['id'])
            if 'choices' in old['roof']:
                building['roof']['choices'] = deepcopy(old['roof']['choices'])
    return flat, summary


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
            field = 'y' if section['ridge'] == 'x' else 'x'
            edge = section['rect'][(1 - axis) + (0 if piece['gable'] == 'front' else 2)]
            geometry = {key: ([distance, edge] if axis == 0 else [edge, distance])
                        for key, distance in (('from', piece[field] - piece['width'] / 2),
                                              ('to', piece[field] + piece['width'] / 2))}
            level = section.get('level')
    return {'kind': kind, 'level': level, 'geometry': geometry,
            'building': building['id'],
            'read_geometry': deepcopy(piece.get('read_geometry') or geometry),
            'src': deepcopy(piece.get('src') or {})}


# Caches the model derives from walls and joints (a person never edits them),
# and provenance marks (who owns a piece is not a reader's error).
_DERIVED_PATH = re.compile(r'(^|\.)(rooms\[[^\]]+\]\.(polygon|joints)|joints|walls\[[^\]]+\]\.footprint|src)(\[|\.|$)')


def _derived_path(path):
    return bool(_DERIVED_PATH.search(path))


def save(edit, actor_id, reason=''):
    """Edit the latest round, preserving provenance, history and P0 fix kinds."""
    from services import twin_store

    if not isinstance(reason, str):
        raise ValueError('The reason must be text.')
    if not isinstance(edit, dict):
        raise ValueError('An edit must be an object.')
    edit = deepcopy(edit)
    ha_catalogue = None
    if (edit.get('op') == 'set' and edit.get('field') == 'ha_area' or edit.get('op') == 'place_device'
            or edit.get('list') == 'yard_rooms' and 'ha_area' in edit):
        from services import twin_ha
        ha_catalogue = twin_ha.safe_catalogue()
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
        from services import twin_model, twin_model_bridge
        current = twin_store.current_model()
        normalized = twin_model.normalize(current)
        model, summary = apply_model(current, edit, ha_catalogue=ha_catalogue, _normalized=normalized)
        after = twin_model_bridge.flatten(model)
        # The fix log compares against the house as every op sees it (normalized),
        # so a pass's own re-derive is never logged as the person's fix.
        logged_before = twin_model_bridge.flatten(normalized[0])
        place_row = None
        if edit.get('op') == 'set' and edit.get('field') == 'name':
            kind, piece, building, _ = _find(after, edit.get('piece', edit.get('id')), edit.get('building'))
            if kind == 'building':
                # Validate the registry name before publishing, and carry the
                # private snapshot into this same edit's metadata save.
                place_row = twin_store._state()
                record = twin_store._update_place_building(place_row, building['id'], {'name': piece['name']})
                piece['name'] = record['name']
                old_name = next(b['name'] for b in before['buildings'] if b['id'] == building['id'])
                summary = f'Renamed {old_name} to {piece["name"]}'
        deletion_after = (_apply_legacy(before, edit)[0]
                          if edit.get('op') == 'delete' and 'piece' in edit else after)
        tombstones = ([_tombstone(*entry) for entry in _removed(before, deletion_after)]
                      if edit.get('op') == 'delete' else [])
        changes = [{'path': path, 'kind': twin_store._fix_kind(path),
                    'before': twin_store._leaf(logged_before, path), 'after': twin_store._leaf(after, path),
                    'reason': reason.strip() or summary, 'actor_id': actor_id}
                   for path in twin_plan.diff_paths(logged_before, after)
                   if twin_store._fix_kind(path) is not None and not _derived_path(path)]
        def metadata(row):
            if place_row is not None:
                row['place'], row['page_roles'] = place_row['place'], place_row['page_roles']
                row['sources'] = place_row['sources']
        round_id = twin_store.update_model(
            lambda current: model, 'edit', note=summary, changes=changes, state_mutator=metadata)
        for tombstone in tombstones:
            twin_store.add_tombstone({**tombstone, 'round': round_id})
        if edit.get('op') == 'registration':
            edit['reg']['source'] = 'person'
            twin_store.set_registration(edit['source'], edit['page'], edit['level'], edit['reg'])
        return {'round': round_id, 'summary': summary}
