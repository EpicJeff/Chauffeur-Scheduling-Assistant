"""House slab slots through real normalization, ops, Library lifecycle and HTTP history."""
import copy
import os
import sys
import tempfile
import traceback

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_foundation_material_')
from test_twin_model_ops_more import _house, _b, _people, _client, _enforced
from services import storage, twin_model, twin_model_bridge as bridge, twin_model_ops as ops
from services import twin_plan, twin_store, twin_terrain, twin_materials

REF = {'id': 'red_brick_03', 'color': '#aa3322'}


def test_agent_generic_edit_passes_slot_without_schema_changes():
    from services.agent_tools_v2 import HouseDesignTool, handle_house_design
    model = _house()
    twin_store.push_round(bridge.flatten(model), 'build')
    value = dict(_b(model)['foundation'], materials={'slab': REF})
    args = {'action': 'edit', 'building': _b(model)['id'],
            'edit': {'op': 'set_foundation', 'foundation': value}}
    assert HouseDesignTool.model_validate(args).edit['foundation'] == value
    _people()
    result = handle_house_design(args, actor={'id': 'p1', 'role': 'parent'})
    assert result['status'] == 'ok', result
    assert _b(twin_store.current_model())['foundation'] == value


def test_legacy_roundtrip_does_not_invent_materials():
    model = _house()
    expected = copy.deepcopy(_b(model)['foundation'])
    assert 'materials' not in expected
    for result in (twin_model.normalize(model)[0], bridge.assemble(bridge.flatten(model))[0]):
        assert _b(result)['foundation'] == expected
    flat = bridge.flatten(model)
    assert _b(twin_plan.normalize(flat)[0])['foundation'] == expected
    twin_store.push_round(flat, 'build')
    assert _b(twin_store.current_model())['foundation'] == expected


def test_valid_and_invalid_saved_slots_preserve_geometry():
    for ref in (REF, {'id': 'trim'}, None):
        building = {'foundation': {'mode': 'auto', 'offset_ft': 3, 'thickness_ft': 2, 'materials': {'slab': ref}}}
        notes = []
        twin_terrain.normalize_foundation(building, notes)
        assert not notes
        assert building['foundation'].get('materials', {}).get('slab') == ref
    for bad in ({'slab': {'id': 'missing-material'}}, {'slab': {'id': 'trim', 'extra': 1}},
                {'slab': []}, {'side': REF}, [], None):
        for normalize in (twin_model.normalize, lambda m: twin_plan.normalize(bridge.flatten(m))):
            model = _house()
            expected = {'mode': 'auto', 'offset_ft': 3, 'thickness_ft': 2}
            _b(model)['foundation'] = dict(expected, materials=copy.deepcopy(bad))
            result, notes = normalize(model)
            assert _b(result)['foundation'] == expected, _b(result)['foundation']
            assert any('foundation' in n.lower() and 'material' in n.lower() for n in notes), notes


def test_existing_op_validates_and_clears_without_input_mutation():
    model = _house()
    before = copy.deepcopy(model)
    value = dict(_b(model)['foundation'], materials={'slab': REF})
    op = {'op': 'set_foundation', 'building': _b(model)['id'], 'foundation': value}
    changed, _ = ops.apply(model, op)
    assert _b(changed)['foundation'] == value
    assert _b(bridge.assemble(bridge.flatten(changed))[0])['foundation'] == value
    assert model == before
    for bad in ({'slab': {'id': 'missing-material'}}, {'top': REF}, [], {'slab': 'trim'}):
        try:
            ops.apply(changed, dict(op, foundation=dict(value, materials=bad)))
        except ops.Refused:
            pass
        else:
            raise AssertionError(f'Accepted invalid slab slot: {bad}')
    cleared, _ = ops.apply(changed, dict(op, foundation=dict(value, materials={'slab': None})))
    assert 'materials' not in _b(cleared)['foundation']
    assert _b(changed)['foundation'] == value


def test_parent_http_one_history_step_pick_clear_and_undo():
    model = _house()
    twin_store.push_round(bridge.flatten(model), 'build')
    tokens, client = _people(), _client()
    value = dict(_b(model)['foundation'], materials={'slab': REF})
    op = {'op': 'set_foundation', 'building': _b(model)['id'], 'foundation': value}
    before, count = twin_store.current_id(), len(twin_store.rounds())
    with _enforced():
        assert client.post('/api/house/editor/op', headers=tokens['child'], json={'op': op}).status_code == 403
        bad = dict(op, foundation=dict(value, materials={'slab': {'id': 'missing-material'}}))
        assert client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': bad}).status_code == 400
        assert twin_store.current_id() == before
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
        assert response.status_code == 200, response.text
        assert len(twin_store.rounds()) == count + 1
        assert _b(response.json()['plan'])['foundation'] == value
        picked = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['parent'],
                               json={'op': dict(op, foundation=_b(model)['foundation'])})
        assert response.status_code == 200, response.text
        assert len(twin_store.rounds()) == count + 2
        assert 'materials' not in _b(twin_store.current_model())['foundation']
    twin_store.revert(picked)
    assert _b(twin_store.current_model())['foundation'] == value
    twin_store.revert(before)
    assert 'materials' not in _b(twin_store.current_model())['foundation']


def test_library_count_rename_delete_refusal_and_history_archive():
    row = twin_materials.create({'name': 'Slab stone'}, 'parent')
    ref = {'id': row['id']}
    model = _house()
    _b(model)['foundation']['materials'] = {'slab': ref}
    twin_store.push_round(bridge.flatten(model), 'build')
    use = twin_materials.uses(row['id'])
    assert len(use['current']) == 1 and 'foundation' in use['current'][0], use
    twin_materials.update(row['id'], {'name': 'Renamed slab stone'}, 'parent')
    assert twin_materials.get(row['id'])['name'] == 'Renamed slab stone'
    assert _b(twin_store.current_model())['foundation']['materials']['slab'] == ref
    assert twin_materials.uses(row['id'])['current'] == use['current']
    try:
        twin_materials.delete(row['id'], 'parent')
    except ValueError as error:
        assert 'Used on 1 surfaces' in str(error) and 'foundation' in str(error)
    else:
        raise AssertionError('Deleted material in use on the house slab')
    with _enforced():
        response = _client().delete(f"/api/house/materials/{row['id']}", headers=_people()['parent'])
        assert response.status_code == 400 and 'Used on 1 surfaces' in response.text, response.text
    twin_store.push_round(bridge.flatten(_house()), 'edit')
    assert twin_materials.uses(row['id']) == {'current': [], 'history': True}
    assert twin_materials.delete(row['id'], 'parent') == {'archived': True}
    assert twin_materials.get(row['id'])['archived']
    loaded, notes = twin_model.normalize(model)
    assert _b(loaded)['foundation']['materials']['slab'] == ref, notes


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    try:
        for test in tests:
            try:
                storage.patch_settings({'house_twin': None})
                test()
                passed += 1
                print('ok  ', test.__name__)
            except Exception:
                print('FAIL', test.__name__)
                traceback.print_exc(limit=6)
    finally:
        storage.db.close()
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
