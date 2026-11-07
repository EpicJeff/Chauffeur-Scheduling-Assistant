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
    if (type(value) not in (int, float) or not math.isfinite(value)
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


def _label(kind, piece):
    return piece.get('name') or (piece.get('kind', 'opening') if kind == 'opening'
                                 else piece.get('id', kind))


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
    for field in ('from', 'to', 'position'):
        if field in piece:
            piece[field] = transform(piece[field])
    if isinstance(piece.get('at'), (list, tuple)):
        piece['at'] = transform(piece['at'])
    for field in ('polygon', 'points', 'polyline'):
        if field in piece:
            piece[field] = [transform(p) for p in piece[field]]
    if 'rect' in piece:
        x0, y0, x1, y1 = piece['rect']
        points = [transform(p) for p in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        piece['rect'] = [min(p[0] for p in points), min(p[1] for p in points),
                         max(p[0] for p in points), max(p[1] for p in points)]


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
    if type(page) is not int or page < 1:
        raise ValueError('Page must be a positive integer.')
    level = _text(edit.get('level'), 'Level')
    old, new = _registration(edit.get('from_reg')), _registration(edit.get('reg'))
    scale = new['scale'] / old['scale']

    def transform(point):
        return twin_register.apply(new, twin_register.invert(old, point))

    selected = []
    for kind, piece, building, _ in _entries(plan):
        if edit.get('building') is not None and building.get('id') != edit['building']:
            continue
        src = piece.get('src') or {}
        piece_level = piece.get('level')
        if kind == 'opening' and 'wall' in piece:
            piece_level = _wall(building, piece)['level']
        if src.get('sheet') == source and src.get('page') == page and piece_level == level:
            selected.append((kind, piece, building))
    # Capture centres before transforming walls; an opening may have different provenance.
    centres = {}
    for kind, piece, building in selected:
        if kind == 'opening' and 'wall' in piece:
            wall = _wall(building, piece)
            unit, _ = _wall_vector(wall)
            centres[id(piece)] = transform([wall['from'][i] + unit[i] * piece['at']
                                             for i in (0, 1)])
        elif kind == 'opening' and 'gable' in piece:
            section = next(s for s in building['roof']['sections'] if s['id'] == piece['section'])
            y = section['rect'][1 if piece['gable'] == 'front' else 3]
            centres[id(piece)] = transform([piece['x'], y])
    for kind, piece, _ in selected:
        if kind != 'opening':
            _transform(piece, transform)
        _mark(piece)
    for kind, piece, building in selected:
        if kind == 'opening':
            if 'wall' in piece:
                wall = _wall(building, piece)
                unit, _ = _wall_vector(wall)
                piece['at'] = sum((centres[id(piece)][i] - wall['from'][i]) * unit[i]
                                  for i in (0, 1))
            elif 'x' in piece:
                piece['x'] = centres[id(piece)][0]
            piece['width'] *= scale
            _opening_valid(building, piece)
    return f'Updated registration for {source} page {page} on {level}'


def _value_words(field, value):
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
            piece['state'] = 'settled'
            _mark(piece)
        summary = f'Accepted {len(ids)} piece' + ('' if len(ids) == 1 else 's')
    elif op == 'add_wall':
        _, level, building, _ = _find(result, edit.get('level'), scope, 'level')
        start, end = _point(edit.get('from'), 'from'), _point(edit.get('to'), 'to')
        if start == end:
            raise ValueError('A wall must have positive length.')
        building['walls'].append({'level': level['id'], 'from': start, 'to': end,
                                  'height': level['ceiling'], 'thickness': 0.33,
                                  'exterior': False, 'state': 'settled', 'src': {'person': True}})
        if len(building['walls']) > twin_plan.CAPS['walls']:
            raise ValueError('The building has too many walls.')
        summary = f'Added a wall on {level.get("name", level["id"])}'
    elif op == 'add_opening':
        _, wall, building, _ = _find(result, edit.get('wall'), scope, 'wall')
        kind = edit.get('kind')
        if kind not in _OPENING_KINDS:
            raise ValueError('Invalid opening kind.')
        piece = {'wall': wall['id'], 'kind': kind,
                 'at': _number(edit.get('at'), 'at', minimum=0),
                 'width': _number(edit.get('width'), 'width', positive=True),
                 'sill': min(2, wall['height'] / 3) if kind == 'window' else 0,
                 'head': min(7, wall['height']), 'state': 'settled', 'src': {'person': True}}
        _opening_valid(building, piece)
        building['openings'].append(piece)
        if len(building['openings']) > twin_plan.CAPS['openings']:
            raise ValueError('The building has too many openings.')
        summary = f'Added a {kind} to {wall["id"]}'
    elif op in ('set', 'move', 'rotate', 'delete'):
        pid = scope if op == 'rotate' else edit.get('piece')
        kind, piece, building, owner = _find(result, pid, scope,
                                             'building' if op == 'rotate' else None)
        label = _label(kind, piece)
        if op == 'set':
            field = edit.get('field')
            _set(kind, piece, building, field, edit.get('value'))
            summary = f'Set the {label} {field} to {_value_words(field, piece[field])}'
        elif op == 'rotate':
            _set(kind, piece, building, 'rotation', edit.get('to'))
            summary = f'Turned {label} to {piece["rotation"]:g}°'
        elif op == 'delete':
            owner.remove(piece)
            summary = f'Removed {label}'
        else:
            dx, dy = _point(edit.get('by'), 'by')
            if kind == 'opening':
                wall = _wall(building, piece)
                unit, length = _wall_vector(wall)
                at = max(piece['width'] / 2, min(length - piece['width'] / 2,
                         piece['at'] + dx * unit[0] + dy * unit[1]))
                dx, dy = [(at - piece['at']) * v for v in unit]
                piece['at'] = at
            elif kind in ('wall', 'room', 'roof', 'building', 'stair', 'fixture', 'light'):
                _transform(piece, lambda p: [p[0] + dx, p[1] + dy])
            else:
                raise ValueError(f'Cannot move a {kind}.')
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
    return normalized, summary


def _tombstone(plan, edit):
    kind, piece, building, _ = _find(plan, edit.get('piece'), edit.get('building'))
    geometry = {k: deepcopy(piece[k]) for k in ('from', 'to', 'polygon', 'rect') if k in piece}
    level = piece.get('level')
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
            y = section['rect'][1 if piece['gable'] == 'front' else 3]
            geometry = {'from': [piece['x'] - piece['width'] / 2, y],
                        'to': [piece['x'] + piece['width'] / 2, y]}
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
            twin_store._source_page(twin_store._state(), edit.get('source'), edit.get('page'))
        after, summary = apply(before, edit)
        tombstone = _tombstone(before, edit) if edit.get('op') == 'delete' else None
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
        if tombstone is not None:
            twin_store.add_tombstone(tombstone)
        if edit.get('op') == 'registration':
            twin_store.set_registration(edit['source'], edit['page'], edit['level'], edit['reg'])
        return {'round': round_id, 'summary': summary}
