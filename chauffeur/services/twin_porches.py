"""Porch foundation validation shared by flat reads and connected operations."""
from copy import deepcopy
import math
from services.twin_library import normalize_material_slot

DEFAULT = {'type': 'posts', 'lip_in': 1, 'post_in': 6, 'post_shape': 'square',
           'spacing_ft': 8, 'materials': {'posts': None, 'skirt': None, 'solid': None}}
LEGACY_ROLES = {'stone': 'base', 'brick': 'porch_brick', 'concrete': 'patio_concrete'}


def foundation_error(value):
    if not isinstance(value, dict) or value.get('type') not in ('posts', 'enclosed', 'solid'):
        return 'Choose Posts, Enclosed or Solid for the porch foundation.'
    if 'skirt' in value:
        legacy_skirt = value.pop('skirt')
        if legacy_skirt not in ('lattice', 'panel'):
            return 'Unknown legacy porch skirt. Choose its material from the Library.'
        if not isinstance(value.setdefault('materials', {}), dict):
            return 'Choose porch foundation material slots.'
        if value['materials'].get('skirt') is None:
            value['materials']['skirt'] = {'id': 'siding' if legacy_skirt == 'panel' else 'lattice'}
    if 'material' in value:
        if not isinstance(value['material'], str) or value['material'] not in LEGACY_ROLES:
            return 'Choose Stone, Brick or Concrete for the legacy porch foundation.'
        legacy = value.pop('material')
        if not isinstance(value.setdefault('materials', {}), dict):
            return 'Choose porch foundation material slots.'
        value['materials'].setdefault('solid', {'id': LEGACY_ROLES[legacy]})
    for key, default in DEFAULT.items():
        value.setdefault(key, deepcopy(default))
    for key, low, high, label in [('lip_in', 0, 4, 'lip in inches'),
                                   ('post_in', 4, 16, 'post width in inches'),
                                   ('spacing_ft', 4, 12, 'post spacing in feet')]:
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            return f'Choose a porch foundation {label} from {low} to {high}.'
    if value['post_shape'] not in ('square', 'round'):
        return 'Choose Square or Round for the foundation posts.'
    materials = value['materials']
    if not isinstance(materials, dict) or set(materials) - {'posts', 'skirt', 'solid'}:
        return 'Choose porch foundation posts, skirt and solid material slots.'
    for key in ('posts', 'skirt', 'solid'):
        materials.setdefault(key, None)
        try:
            materials[key] = normalize_material_slot(materials[key])
        except ValueError as error:
            return f'Porch {key} material: {error}'
    return None


def normalize_foundation(porch, notes):
    value = porch.setdefault('foundation', deepcopy(DEFAULT))
    error = foundation_error(value)
    if error:
        porch['foundation'] = deepcopy(DEFAULT)
        notes.append('Defaulted invalid porch foundation: ' + error)
