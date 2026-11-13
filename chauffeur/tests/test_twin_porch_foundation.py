"""Porch foundations: migration, validation, immutable ops and HTTP history."""
import copy
import os
import tempfile

os.environ.pop('HA_BASE_URL', None)
_data = tempfile.mkdtemp(prefix='chauffeur_porch_foundation_')
os.environ['CHAUFFEUR_DATA_DIR'] = _data
from test_twin_model_ops_more import _house, _b, _people, _client, _enforced
from services import twin_model, twin_model_bridge as bridge, twin_model_ops as ops, twin_plan, twin_store, twin_porches, twin_library

def canonical_foundation(value):
    value = copy.deepcopy(value)
    assert twin_porches.foundation_error(value) is None
    return value


def run():
    flat = bridge.flatten(_house())
    room = _b(flat)['rooms'][1]
    room['kind'] = 'porch'
    _b(flat)['porch'] = {'id': room['id'], 'floor': 0, 'polygon': copy.deepcopy(room['polygon']), 'columns': []}
    normalized, _ = twin_plan.normalize(flat)
    assert 'foundation' not in _b(normalized)['porch']
    model = bridge.assemble(normalized)[0]
    bid, rid = _b(model)['id'], room['id']
    porch = lambda m: next(r for r in _b(m)['rooms'] if r['id'] == rid)
    assert porch(model)['foundation']['type'] == 'posts'
    raw = copy.deepcopy(model)
    del porch(raw)['foundation']
    assert porch(twin_model.normalize(raw)[0])['foundation']['type'] == 'posts'
    change = {'op': 'set_porch_foundation', 'building': bid, 'id': rid}
    valid = dict(copy.deepcopy(twin_porches.DEFAULT), type='solid')
    canonical = canonical_foundation
    for kind in ('posts', 'enclosed', 'solid'):
        for material in ('stone', 'brick', 'concrete'):
            for lip in (0, .25, 1, 4):
                value = {'type': kind, 'material': material, 'lip_in': lip}
                expected = canonical(value)
                changed = ops.apply(model, dict(change, foundation=value))[0]
                assert porch(changed)['foundation'] == expected
                assert porch(model)['foundation']['type'] == 'posts'
                rendered = bridge.flatten(changed)
                assert next(p for p in _b(rendered)['porches'] if p['id'] == rid)['foundation'] == expected
                assert porch(bridge.assemble(rendered)[0])['foundation'] == expected
    invalid = [None, [], 'solid', {}, dict(valid, type='slab'), dict(valid, type=True),
               dict(valid, material='wood'), dict(valid, material=None)]
    invalid += [dict(valid, lip_in=v) for v in (-.01, 4.01, True, None, '1', [], float('nan'), float('inf'))]
    for value in invalid:
        try:
            ops.apply(model, dict(change, foundation=value))
        except ops.Refused:
            pass
        else:
            raise AssertionError(f'Accepted invalid foundation: {value}')
        raw = copy.deepcopy(model)
        porch(raw)['foundation'] = value
        result, notes = twin_model.normalize(raw)
        assert porch(result)['foundation']['type'] == 'posts' and any('porch foundation' in n for n in notes)
        raw = copy.deepcopy(flat)
        _b(raw)['porch']['foundation'] = value
        result, notes = twin_plan.normalize(raw)
        assert _b(result)['porch']['foundation']['type'] == 'posts' and any('porch foundation' in n for n in notes)
    defaults = ops.apply(model, dict(change, foundation={'type': 'solid'}))[0]
    assert porch(defaults)['foundation'] == valid
    # Every slot shares set_material's validator, with null meaning default.
    assert twin_library.material_slot_error(None) is None
    assert twin_library.normalize_material_slot(None) is None
    for ref in ({'id': 'trim'}, {'id': 'painted_trim'}, {'id': 'wood_planks', 'color': '#123abc'}, {'id': 'trim', 'color': 'white'}, {'id': 'trim', 'color': '#abc'}):
        assert twin_library.material_slot_error(ref) is None
        assert twin_library.normalize_material_slot(ref) == ref
    for ref in ({'id': 'not-a-material'}, {'id': 'modern_farmhouse'}, {'id': 'trim', 'color': ''}, {'id': 'trim', 'color': None}, {}, [], 'trim'):
        assert twin_library.material_slot_error(ref), ref
    for entry in twin_library.material_choices():
        assert twin_library.material_slot_error({'id': entry['id'], 'color': entry['color']}) is None
    assert 'Unknown material id' in twin_library.material_slot_error({'id': 'not-a-material'})
    for kind in ('posts', 'enclosed', 'solid'):
        for shape in ('square', 'round'):
            for skirt in ('lattice', 'panel'):
                for width, spacing in ((4, 4), (6, 8), (16, 12)):
                    foundation = canonical(dict(valid, type=kind, post_shape=shape, skirt=skirt, post_in=width, spacing_ft=spacing,
                        materials={'posts': {'id': 'trim'}, 'skirt': {'id': 'wood_planks', 'color': '#abcdef'}, 'solid': None}))
                    changed = ops.apply(model, dict(change, foundation=foundation))[0]
                    assert porch(changed)['foundation'] == foundation
    for key, values in {'post_in': (3.9, 16.1, True, '6', None, float('nan')),
                        'spacing_ft': (3.9, 12.1, True, None, float('inf')),
                        'post_shape': ('triangle', None, []), 'skirt': ('screen', None),
                        'materials': ([], None, {'other': None}, {'posts': {'id': 'unknown'}})}.items():
        for value in values:
            try:
                ops.apply(model, dict(change, foundation=dict(valid, **{key: value})))
            except ops.Refused:
                pass
            else:
                raise AssertionError((key, value))
    for ref in (None, {'id': 'trim'}, {'id': 'painted_trim', 'color': 'white'}):
        changed = ops.apply(model, {'op': 'set_material', 'building': bid, 'target': {'room': rid, 'surface': 'floor'}, 'material': ref})[0]
        assert porch(changed).get('floor_material') == ref
    # Shared validation also applies on the existing material op.
    try:
        ops.apply(model, {'op': 'set_material', 'building': bid, 'target': {'room': rid, 'surface': 'floor'}, 'material': {'id': 'unknown'}})
    except ops.Refused as error:
        assert 'Unknown material id' in str(error)
    else:
        raise AssertionError('set_material accepted an unknown id')
    for material, role in twin_porches.LEGACY_ROLES.items():
        legacy = {'foundation': {'type': 'solid', 'material': material}}
        twin_porches.normalize_foundation(legacy, [])
        assert legacy['foundation']['materials']['solid'] == {'id': role}
        assert 'material' not in legacy['foundation']
    # A later reader cannot overwrite the person's shelf choice.
    preserved = bridge.assemble(normalized, previous=defaults)[0]
    assert porch(preserved)['foundation'] == valid and porch(preserved)['src']['person']
    try:
        ops.apply(model, dict(change, id=_b(model)['rooms'][0]['id'], foundation=valid))
    except ops.Refused:
        pass
    else:
        raise AssertionError('A normal room acquired a porch foundation')
    valid = canonical(dict(valid, type='enclosed', post_in=10, post_shape='round', spacing_ft=5, skirt='panel', materials={'posts': {'id': 'trim'}, 'skirt': {'id': 'siding', 'color': '#ccddff'}}))
    base = twin_store.push_round(normalized, 'build')
    with _enforced():
        response = _client().post('/api/house/editor/op', headers=_people()['parent'], json={'op': dict(change, foundation=valid)})
        assert response.status_code == 200, response.text
        bad = _client().post('/api/house/editor/op', headers=_people()['parent'], json={'op': dict(change, foundation=dict(valid, lip_in=5))})
        assert bad.status_code == 400, bad.text
    after = response.json()['round']
    assert porch(twin_store.current_model())['foundation'] == valid
    twin_store.revert(base)
    assert porch(twin_store.current_model())['foundation']['type'] == 'posts'
    twin_store.revert(after)
    assert porch(twin_store.current_model())['foundation'] == valid
    print('Passed: porch defaults/migration, validation, ops, bridge, person preservation, HTTP, undo and redo')

if __name__ == '__main__':
    try:
        run()
    finally:
        from services import storage
        storage.db.close()
