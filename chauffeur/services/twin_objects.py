"""Placed-object properties. The JSON schema is also supplied to the editor.

Site lists and building.items retain their identities and host coordinates.
Defaults are read-only: an old planting's height/seed/scale is never rewritten.
New lot-structure kinds can add their properties in the same schema.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'static/twin/object_schema.json').read_text(encoding='utf-8'))


def kind(piece, collection=None):
    return piece.get('object_kind', 'plant' if collection == 'planting' or piece.get('kind') in ('tree', 'shrub') else 'furniture')


def fields(piece, collection=None):
    name = kind(piece, collection)
    return {**SCHEMA['common'], **SCHEMA['kinds'].get(name if isinstance(name, str) else '', {})}


def defaults(piece, collection=None):
    return {**{k: deepcopy(v['default']) for k, v in fields(piece, collection).items()}, **deepcopy(piece)}


def validate(field, value, spec):
    number = lambda v: type(v) in (int, float) and math.isfinite(v)
    t = spec['type']
    valid = False
    if t == 'text':
        valid = isinstance(value, str) and len(value) <= spec['max']
    elif t == 'number':
        valid = number(value) and spec['min'] <= value <= spec['max']
    elif t == 'angle':
        valid = number(value)
    elif t == 'axes':
        valid = isinstance(value, list) and len(value) == 3 and all(number(v) and spec['min'] <= v <= spec['max'] for v in value)
    elif t == 'color':
        valid = value is None or isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)
    elif t == 'boolean':
        valid = type(value) is bool
    elif t == 'visibility':
        valid = isinstance(value, list) and len(value) == len(set(str(v) for v in value)) and all(v in ('viewer', 'editor') for v in value)
    elif t == 'light':
        valid = value is None or isinstance(value, str) and re.fullmatch(r'light\.[a-z0-9_]+', value)
    elif t == 'choice':
        valid = value in spec['choices']
    elif t == 'model':
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError('Choose a library model.')
        from services import twin_imports, twin_library
        asset = twin_imports.get(value) if value.startswith('import-') else twin_library.manifest().get(value)
        valid = asset is not None and (value.startswith('import-') or asset.get('kind') == 'model')
    if not valid:
        # Words a person can act on, matching the card ops' own size refusal.
        if field == 'scale' and 'min' in spec:
            raise ValueError(f"Choose a size from {round(spec['min'] * 100)}% to {round(spec['max'] * 100)}%.")
        name = field.replace('_', ' ')
        raise ValueError(f"Choose a {name} from {spec['min']} to {spec['max']}." if 'min' in spec else f'Choose a valid {name}.')
    return deepcopy(value)


def update(piece, changes, collection=None, *, opening=False):
    if not isinstance(changes, dict) or not changes:
        raise ValueError('Choose object properties to change.')
    candidate = deepcopy(piece)
    if 'object_kind' in changes:
        if not isinstance(changes['object_kind'], str) or changes['object_kind'] not in SCHEMA['kinds']:
            raise ValueError('Choose an object kind.')
        candidate['object_kind'] = changes['object_kind']
    schema = SCHEMA['opening'] if opening else fields(candidate, collection)
    for field, value in changes.items():
        if field == 'object_kind' and not opening:
            continue
        if field not in schema:
            raise ValueError(f'Unknown property: {field}.')
        if field in ('pitch', 'roll') and candidate.get('host'):
            raise ValueError('Pitch and roll belong to free objects.')
        candidate[field] = validate(field, value, schema[field])
        if field == 'rotation':
            candidate[field] %= 360
    if opening and isinstance(candidate.get('model'), str) and candidate['model'].startswith('import-'):
        from services import twin_imports
        expected = 'window' if candidate['kind'] == 'window' else 'door'
        if twin_imports.get(candidate['model'])['kind'] != expected:
            raise ValueError(f'Choose a {expected} model.')
    piece.clear()
    piece.update(candidate)


def error(piece, collection=None):
    try:
        if not isinstance(kind(piece, collection), str) or kind(piece, collection) not in SCHEMA['kinds']:
            return 'invalid object kind'
        schema = fields(piece, collection)
        for field, spec in schema.items():
            if field in piece:
                validate(field, piece[field], spec)
    except ValueError as exc:
        return str(exc)
    return None


def placements(model, asset_id):
    found = []
    for building in (model or {}).get('buildings', []):
        for name in ('items', 'openings'):
            for piece in building.get(name, []):
                if piece.get('asset') == asset_id or piece.get('model') == asset_id:
                    found.append(f"{building.get('name', building['id'])}: {piece.get('name') or piece['id']}")
    for name in ('planting', 'furniture'):
        for i, piece in enumerate((model or {}).get('site', {}).get(name, [])):
            if piece.get('asset') == asset_id:
                found.append(f"Yard: {piece.get('name') or piece.get('id', str(i + 1))}")
    return found
