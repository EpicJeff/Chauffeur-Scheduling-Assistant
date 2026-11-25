"""Surface kinds shared with the browser table (parity tested)."""

KINDS = [
    {'kind': 'trim', 'label': 'Trim', 'scope': 'building', 'fallback': {'role': 'trim'}, 'item': None},
    {'kind': 'fascia', 'label': 'Fascia', 'scope': 'building', 'fallback': {'role': 'trim'}, 'item': None},
    {'kind': 'gutter', 'label': 'Gutters', 'scope': 'building', 'fallback': {'role': 'trim'}, 'item': None},
    {'kind': 'casing', 'label': 'Casing', 'scope': 'building', 'fallback': {'role': 'trim'}, 'item': 'opening'},
    {'kind': 'window_frame', 'label': 'Window frames', 'scope': 'building', 'fallback': {'role': 'window_frame'}, 'item': 'opening'},
    {'kind': 'pane', 'label': 'Panes', 'scope': 'building', 'fallback': {'builtin': 'glass'}, 'item': 'opening'},
    {'kind': 'door', 'label': 'Doors', 'scope': 'building', 'fallback': {'role': 'door'}, 'item': 'opening'},
    {'kind': 'garage_door', 'label': 'Garage door', 'scope': 'building', 'fallback': {'role': 'door'}, 'item': 'opening'},
    {'kind': 'support', 'label': 'Supports', 'scope': 'building', 'fallback': {'role': 'trim'}, 'item': 'roof'},
    {'kind': 'column', 'label': 'Columns', 'scope': 'building', 'fallback': {'role': 'trim'}, 'item': 'porch'},
    {'kind': 'screen', 'label': 'Screens', 'scope': 'building', 'fallback': {'builtin': 'screen'}, 'item': 'porch'},
    {'kind': 'soffit', 'label': 'Soffit', 'scope': 'building', 'fallback': {'role': 'porch_ceiling'}, 'item': None},
    {'kind': 'base', 'label': 'Foundation', 'scope': 'building', 'fallback': {'role': 'base'}, 'item': None},
    {'kind': 'stair_tread', 'label': 'Stair treads', 'scope': 'building', 'fallback': {'role': 'floor'}, 'item': 'stair'},
    {'kind': 'stair_rail', 'label': 'Stair rails', 'scope': 'building', 'fallback': {'role': 'porch_ceiling'}, 'item': 'stair'},
    {'kind': 'ceiling', 'label': 'Ceilings', 'scope': 'building', 'fallback': {'look': 'ceiling'}, 'item': 'room'},
    {'kind': 'roof', 'label': 'Roof', 'scope': 'building', 'fallback': {'role': 'roof'}, 'item': 'roof'},
    {'kind': 'cabinet', 'label': 'Cabinets', 'scope': 'building', 'fallback': {'look': 'cabinet'}, 'item': 'fixture'},
    {'kind': 'counter', 'label': 'Counters', 'scope': 'building', 'fallback': {'look': 'counter'}, 'item': 'fixture'},
    {'kind': 'shower_tile', 'label': 'Shower tile', 'scope': 'building', 'fallback': {'look': 'ceramic'}, 'item': 'fixture'},
    {'kind': 'shower_glass', 'label': 'Shower glass', 'scope': 'building', 'fallback': {'builtin': 'glass'}, 'item': 'fixture'},
    {'kind': 'lawn', 'label': 'Lawn', 'scope': 'site', 'fallback': {'role': 'lawn'}, 'item': None},
    {'kind': 'water', 'label': 'Water', 'scope': 'site', 'fallback': {'builtin': 'water'}, 'item': 'pool'},
]
PANEL_ROLES = ['siding', 'interior_wall', 'floor']
ITEM_PARTS = {
    'opening': ('casing', 'window_frame', 'pane', 'door', 'garage_door'),
    'porch': ('column', 'screen'),
    'roof': ('support',),
    'stair': ('stair_tread', 'stair_rail'),
    'fixture': ('cabinet', 'counter', 'shower_tile', 'shower_glass'),
    'pool': ('water',), 'spa': ('water',),
}
BUILTIN_LOOKS = {
    'glass': {'color': '#b9d7db', 'transparent': True, 'opacity': 0.26, 'roughness': 0.1, 'depthWrite': False},
    'screen': {'color': '#59615d', 'transparent': True, 'opacity': 0.3, 'depthWrite': False, 'doubleSide': True},
    'water': {'color': '#7fd0e6', 'transparent': True, 'opacity': 0.65, 'roughness': 0.12, 'depthWrite': False},
    'chain_link': {'color': '#9da5a8', 'opacity': 1, 'roughness': 0.45, 'metalness': 0.65, 'alphaTest': 0.5, 'doubleSide': True},
    # Powder coat is a paint film over the metal, so it shades as a dielectric.
    'black_metal': {'color': '#1b1c1e', 'opacity': 1, 'roughness': 0.42, 'metalness': 0},
}
BUILTIN_NAMES = {'chain_link': 'Chain link', 'black_metal': 'Black metal'}


def builtin_alpha_mode(look):
    return 'cutout' if look.get('alphaTest') else 'blend' if look.get('transparent') else 'opaque'


def label(kind):
    return next((row['label'] for row in KINDS if row['kind'] == kind), kind.replace('_', ' ').capitalize())


def clean_slots(materials, allowed, notes, owner, *, validate_id=True):
    """Repair each bad reference independently, retaining arbitrary legacy roles."""
    from services.twin_library import normalize_material_slot
    if not isinstance(materials, dict):
        notes.append(f'{owner}: reset invalid materials; expected an object.')
        return {}
    result = {}
    for kind, value in materials.items():
        if allowed is not None and kind not in allowed:
            continue
        try:
            slot = normalize_material_slot(value, validate_id=validate_id)
        except ValueError:
            notes.append(f'{owner}: reset invalid {label(kind).lower()} material.')
        else:
            if slot is not None:
                result[kind] = slot
    return result
