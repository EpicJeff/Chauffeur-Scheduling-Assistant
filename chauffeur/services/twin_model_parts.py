"""Shared contract for Library Models mode; mirrors static/twin/model_parts.js.

Part keys, override resolution and the validators the model record and
placed copies use. Validators raise ValueError with a person-readable message.
"""
from __future__ import annotations

DEFAULT_LOD_PERCENT = (100, 25, 5)
TURNS = (0, 90, 180, 270)
MAX_FIX_M = 30
MAX_TILES = 100


def part_keys(names):
    seen: dict[str, int] = {}
    keys = []
    for raw in names:
        name = raw if isinstance(raw, str) and raw.strip() else 'unnamed'
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else f'{name}~{seen[name]}')
    return keys


def resolve_part(part, model_materials=None, copy_materials=None):
    copy = (copy_materials or {}).get(part['key'])
    model = (model_materials or {}).get(part['key'])
    entry = copy or model
    if not entry:
        return {'source': 'original', 'material': None, 'texture': 'real', 'tiles': 1}
    source = 'copy' if copy else 'model'
    if entry.get('material') == 'original':
        return {'source': source, 'material': None, 'texture': 'real', 'tiles': 1}
    texture = 'model' if part.get('has_uv') and entry.get('texture') == 'model' else 'real'
    tiles = entry.get('tiles') if texture == 'model' and _positive(entry.get('tiles')) else 1
    return {'source': source, 'material': entry['material'], 'texture': texture, 'tiles': tiles}


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def validate_lod_percent(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)):
        raise ValueError('Detail levels need three whole percentages: full, mid and far.')
    full, mid, far = value
    if not (100 >= full >= mid >= far >= 1):
        raise ValueError('Detail levels must run from 1 to 100, with full at least mid and mid at least far.')
    return [full, mid, far]


def validate_fix(value):
    if not isinstance(value, dict) or set(value) - {'turn', 'height_m', 'width_m'}:
        raise ValueError('A size fix takes only turn, height_m or width_m.')
    if 'height_m' in value and 'width_m' in value:
        raise ValueError('Set the real height or the real width, not both.')
    turn = value.get('turn', 0)
    if turn not in TURNS or isinstance(turn, bool):
        raise ValueError('Turn must be 0, 90, 180 or 270 degrees.')
    out = {'turn': turn}
    for key in ('height_m', 'width_m'):
        if key in value:
            if not _positive(value[key]) or value[key] > MAX_FIX_M:
                raise ValueError(f'The real {"height" if key == "height_m" else "width"} must be above 0 and at most {MAX_FIX_M} m.')
            out[key] = float(value[key])
    return out


def validate_model_materials(value, parts, library_ids, *, per_copy):
    """Validate a model default map (per_copy=False) or a copy's model_materials map."""
    if not isinstance(value, dict):
        raise ValueError('Part materials must be a map of part to material.')
    known = {p['key']: p for p in parts or []}
    out = {}
    for key, entry in value.items():
        if key not in known:
            raise ValueError(f'Unknown part: {key}')
        if not isinstance(entry, dict) or set(entry) - {'material', 'texture', 'tiles'} or 'material' not in entry:
            raise ValueError(f'Part {key} needs a material, and may set texture and tiles.')
        material = entry['material']
        if material == 'original':
            if not per_copy:
                raise ValueError('Only a placed copy can return a part to its original material.')
            if set(entry) != {'material'}:
                raise ValueError(f'Part {key}: the original material takes no texture settings.')
            out[key] = {'material': 'original'}
            continue
        if material not in library_ids:
            raise ValueError(f'Part {key}: unknown library material {material}.')
        texture = entry.get('texture', 'real')
        if texture not in ('real', 'model'):
            raise ValueError(f'Part {key}: texture is Real size or Model\'s own.')
        if texture == 'model' and not known[key].get('has_uv'):
            raise ValueError(f'Part {key} has no UVs, so it can only use Real size.')
        clean = {'material': material, 'texture': texture}
        if 'tiles' in entry:
            if texture != 'model':
                raise ValueError(f'Part {key}: tiles apply only to Model\'s own.')
            if not _positive(entry['tiles']) or entry['tiles'] > MAX_TILES:
                raise ValueError(f'Part {key}: tiles must be above 0 and at most {MAX_TILES}.')
            clean['tiles'] = entry['tiles']
        out[key] = clean
    return out
