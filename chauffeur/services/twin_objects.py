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
    return {**SCHEMA['common'], **SCHEMA['kinds'].get(name if isinstance(name, str) else '', {}),
            **(SCHEMA['kinds']['plant'] if collection == 'planting' else {})}


def defaults(piece, collection=None):
    return {**{k: deepcopy(v['default']) for k, v in fields(piece, collection).items()}, **deepcopy(piece)}


def validate_model_materials_shape(value):
    """Safe to load even with stale references; never resolve parts or IDs here."""
    if not isinstance(value, dict):
        raise ValueError('Part materials must be a map of part to material.')
    for key, entry in value.items():
        if (not isinstance(entry, dict) or 'material' not in entry
                or set(entry) - {'material', 'texture', 'tiles'}
                or not isinstance(entry['material'], str)
                or 'texture' in entry and entry['texture'] not in ('real', 'model')):
            raise ValueError(f'Part {key} needs a material string and may set texture (real or model) and tiles.')


def validate_plan_model_materials(plan):
    """Refuse malformed overrides before a whole-plan save or normalization."""
    owners = []
    buildings = plan.get('buildings', [])
    for building in buildings if isinstance(buildings, list) else []:
        if isinstance(building, dict):
            for name in ('items', 'openings', 'anchors'):
                pieces = building.get(name, [])
                if isinstance(pieces, list):
                    owners.extend(pieces)
    site = plan.get('site', {})
    if isinstance(site, dict):
        for name in ('planting', 'furniture'):
            if isinstance(site.get(name), list):
                owners.extend(site[name])
    for piece in owners:
        if isinstance(piece, dict) and 'model_materials' in piece:
            validate_model_materials_shape(piece['model_materials'])


def validate(field, value, spec):
    number = lambda v: type(v) in (int, float) and math.isfinite(v)
    t = spec['type']
    valid = False
    if t == 'text':
        valid = isinstance(value, str) and len(value) <= spec['max']
    elif t == 'number':
        valid = number(value) and spec['min'] <= value <= spec['max'] and (not spec.get('positive') or value > 0)
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
    elif t == 'object':
        valid = isinstance(value, dict)
        if field == 'model_materials':
            validate_model_materials_shape(value)
    elif t == 'model':
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError('Choose a library model.')
        from services import twin_model_records
        try:
            twin_model_records.get(value)
            valid = True
        except KeyError:
            valid = False
    if not valid:
        # Words a person can act on, matching the card ops' own size refusal.
        if field == 'scale' and 'min' in spec:
            raise ValueError(f"Choose a size from {round(spec['min'] * 100)}% to {round(spec['max'] * 100)}%.")
        name = spec.get('label', field.replace('_', ' ')).lower()
        raise ValueError(f"Choose a {name} from {spec['min']} to {spec['max']}." if 'min' in spec else f'Choose a valid {name}.')
    return deepcopy(value)


def update(piece, changes, collection=None, *, opening=False, new_copy=False):
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
        if spec_kind := schema[field].get('kind'):
            if candidate.get('kind') != spec_kind:
                raise ValueError(f"{schema[field]['label']} belongs to a garage door.")
        if field in ('pitch', 'roll') and candidate.get('host'):
            raise ValueError('Pitch and roll belong to free objects.')
        candidate[field] = validate(field, value, schema[field])
        if field in ('mirror_x', 'mirror_y') and not value:
            candidate.pop(field, None)
        if field == 'rotation':
            candidate[field] %= 360
    if opening and isinstance(candidate.get('model'), str):
        from services import twin_imports, twin_model_records
        asset_id = twin_model_records.canonical_asset_id(candidate['model'])
        if asset_id.startswith('import-'):
            expected = 'window' if candidate['kind'] == 'window' else 'door'
            if twin_imports.get(asset_id)['kind'] != expected:
                raise ValueError(f'Choose a {expected} model.')
    if 'model_materials' in candidate and ('model_materials' in changes or 'model' in changes):
        identity = 'model' if opening else 'asset'
        candidate['model_materials'] = model_materials(candidate, opening=opening,
            previous=piece.get('model_materials'), model_changed=new_copy or candidate.get(identity) != piece.get(identity),
            allow_archived=new_copy)
    piece.clear()
    piece.update(candidate)


def model_materials(piece, *, opening=False, previous=None, model_changed=False, allow_archived=False):
    from services import twin_model_records
    asset_id = piece.get('model') if opening else piece.get('asset')
    try:
        parts = twin_model_records.get(asset_id)['parts'] if asset_id else []
    except KeyError as exc:
        raise ValueError('Choose a library model before setting its part materials.') from exc
    value = piece['model_materials']
    validate_model_materials_shape(value)
    if model_changed:
        keys = {part['key'] for part in parts}
        value = {key: entry for key, entry in value.items() if key in keys}
    return twin_model_records.validate_materials(value, parts, per_copy=True, previous=previous,
                                                allow_archived=allow_archived)


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
    from services.twin_model_records import canonical_asset_id
    asset_id = canonical_asset_id(asset_id)
    found = []
    for building in (model or {}).get('buildings', []):
        for name in ('items', 'openings'):
            for piece in building.get(name, []):
                if canonical_asset_id(piece.get('asset')) == asset_id or canonical_asset_id(piece.get('model')) == asset_id:
                    found.append(f"{building.get('name', building['id'])}: {piece.get('name') or piece['id']}")
    for name in ('planting', 'furniture'):
        for i, piece in enumerate((model or {}).get('site', {}).get(name, [])):
            if canonical_asset_id(piece.get('asset')) == asset_id:
                found.append(f"Yard: {piece.get('name') or piece.get('id', str(i + 1))}")
    return found
