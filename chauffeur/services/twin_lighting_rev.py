"""Conservative, content-based lighting identity for saved house rounds."""
import hashlib
import marshal


# Scope presentation metadata to authored records. A material map can have a
# role named 'name'; unknown extensions retain even their display-looking keys.
_PIECES = frozenset(('levels', 'joints', 'walls', 'rooms', 'openings', 'roofs',
                     'dormers', 'extensions', 'stairs', 'anchors', 'items',
                     'devices', 'porches_detail', 'solar_zones', 'lights',
                     'fixtures', 'porches', 'sections', 'terraces', 'beds',
                     'planting', 'furniture', 'hardscape', 'edges', 'yard_rooms'))
_SINGLE = frozenset(('roof', 'porch', 'pool', 'fire_pit', 'fence'))
# twin_generator.js builds groups using ids and structural fields, never these
# display strings. geometry_key.js also removes name/label/notes; reach.js reads
# positions, dimensions and physical materials, not display text.
_DISPLAY = frozenset(('name', 'label', 'notes'))
# hidden/locked are deliberately NOT excluded. Editor hide/lock lives in
# localStorage (editor/visibility.js) and never reaches a round, so excluding
# them guards nothing today; a future model flag of that name could remove
# geometry, and then a silent exclusion would say "up to date" wrongly.
# Do NOT drop ha_display either: hiding a HA light can change the live lights.
# src is drafting/person provenance. flatten() uses src.person to mirror roof
# choices for legacy cards; active sections supply geometry, and atlas authored
# identity explicitly excludes those mirrored choices. Neither generator nor
# reach reads src. A rename also marks its record person-owned via twin_edit.
_NEUTRAL = _DISPLAY | {'src'}
_CHILDREN = _PIECES | _SINGLE
_CONTEXTS = {
    'model': {'buildings': 'building', 'site': 'site'},
    **{kind: {**dict.fromkeys(_CHILDREN, 'piece'), 'columns': 'column'} for kind in ('building', 'site', 'piece')},
}


def _canonical(value, context='unknown'):
    # Normalization may write 37.0 where a reader wrote 37. Keep integral
    # values equal without rounding coordinates or losing large integer bits.
    if type(value) is list:
        return [int(v) if type(v) is float and v.is_integer() else
                _canonical(v, context) if type(v) in (dict, list) else v for v in value]
    if type(value) is not dict:
        return value
    neutral = _NEUTRAL if context in ('piece', 'building') else ('id',) if context == 'column' else ('camera_views',) if context == 'model' else ()
    children = _CONTEXTS.get(context, {})
    result = {}
    for key, item in sorted(value.items()):
        # camera_views is consumed by camera preview/facing UI only. Fixture
        # facing/emitters remain relevant and are NOT removed here.
        if key in neutral:
            continue
        if type(item) in (dict, list):
            item = _canonical(item, children.get(key, 'unknown'))
        elif type(item) is float and item.is_integer():
            item = int(item)
        result[key] = item
    return result


def lighting_fingerprint(model) -> str:
    """Hash all content except proven presentation metadata; never mutate it.

    Fixed marshal v2 encodes the sorted JSON tree without reference memoization
    (shared and copied subtrees hash equally), avoiding the cost of formatting
    thousands of floats as JSON on every save.
    Reference sheets/underlays live in store registrations, not in the model;
    moving those overlays needs no model deny-list entry. Registration edits
    that actually move house geometry still change this fingerprint.
    """
    content = marshal.dumps(_canonical(model, 'model'), 2)
    return hashlib.sha256(b'twin-lighting-1\0' + content).hexdigest()[:32]
