"""Fire finishes through normalization, authored operations/history and HTTP live layout."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
DATA = tempfile.TemporaryDirectory(prefix='chauffeur_fire_', ignore_cleanup_errors=True)
os.environ['CHAUFFEUR_DATA_DIR'] = DATA.name
from services import twin_model_bridge as bridge, twin_model_ops as ops, twin_store, twin_plan, twin_site_shapes as shapes


def run():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(fixture)[0]
    legacy = {'id': 'old', 'shape': 'round', 'at': [20, 20], 'radius': 2}
    model['site']['fire_pit'] = copy.deepcopy(legacy)
    assert twin_plan.normalize(bridge.flatten(model))[0]['site']['fire_pit'] == legacy
    assert shapes.fire_properties(legacy) == {'fuel': 'wood', 'body': 'stone', 'top': 'none', 'height_in': 16.8}
    assert shapes.fire_properties({'fuel': 'gas'}) == {'fuel': 'gas', 'body': 'stone', 'top': 'granite', 'height_in': 18, 'glass': 'amber'}
    new, _ = ops.apply(model, {'op': 'add_site_shape', 'list': 'fire_pit', 'at': [15, 15]})
    assert new['site']['fire_pit'][-1]['fuel'] == 'wood', 'new wood pits opt into logs; legacy appearance stays unchanged'
    for shape in ('round', 'square', 'rect', 'outline'):
        add = {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': shape, 'fuel': 'gas', 'body': 'brick',
               'top': 'concrete', 'height_in': 24, 'glass': 'blue', 'entity': 'switch.fire'}
        add.update(polygon=[[0, 0], [4, 0], [4, 4], [0, 4]] if shape == 'outline' else None)
        if shape != 'outline':
            add.pop('polygon')
            add['at'] = [20, 20]
        changed, _ = ops.apply(model, add)
        pit = changed['site']['fire_pit'][-1]
        assert all(pit[k] == add[k] for k in shapes.FIRE_FIELDS)
        assert bridge.assemble(bridge.flatten(changed))[0]['site']['fire_pit'] == changed['site']['fire_pit']
        wood, _ = ops.apply(changed, {'op': 'update_site_shape', 'list': 'fire_pit', 'id': pit['id'], 'fuel': 'wood', 'rotation': 15})
        assert 'glass' not in wood['site']['fire_pit'][-1]
    print('Passed: defaults, unchanged legacy, round/drawn addition and bridge round trips, fuel changes')
    invalid = [{'fuel': 'oil'}, {'body': 'metal'}, {'top': 'wood'}, {'height_in': 5.9}, {'height_in': 30.1},
               {'height_in': True}, {'height_in': float('nan')}, {'glass': 'blue'}, {'fuel': 'gas', 'glass': 'red'},
               {'entity': ''}, {'entity': 'sensor.fire'}, {'entity': 'switch.bad name'}, {'entity': 12}]
    for change in invalid:
        try:
            ops.apply(model, {'op': 'update_site_shape', 'list': 'fire_pit', 'index': 0, **change})
        except ops.Refused:
            pass
        else:
            raise AssertionError(change)
        flat = bridge.flatten(model)
        flat['site']['fire_pit'] = {**legacy, **change}
        assert twin_plan.normalize(flat)[0]['site']['fire_pit'] is None, change
    for eid in ('switch.fire', 'light.fire', 'input_boolean.fire', 'fan.fire'):
        shapes.fire_properties({'entity': eid})
    twin_store.push_round(bridge.flatten(model), 'build')
    before = twin_store.current_id()
    after = twin_store.update_model(lambda m: ops.apply(m, {'op': 'update_site_shape', 'list': 'fire_pit', 'index': 0,
        'fuel': 'gas', 'glass': 'clear', 'entity': 'switch.fire'})[0])
    assert twin_store.current_model()['site']['fire_pit']['entity'] == 'switch.fire'
    twin_store.revert(before)
    assert twin_store.current_model()['site']['fire_pit'] == legacy
    twin_store.revert(after)
    linked = twin_store.current_model()
    cleared, _ = ops.apply(linked, {'op': 'update_site_shape', 'list': 'fire_pit', 'index': 0, 'entity': None})
    assert 'entity' not in cleared['site']['fire_pit']
    print('Passed: bad values refused/dropped, unlink and real store undo/redo')
    from test_twin_model_ops_more import _client, _people, _enforced
    from services import ha_api, control_rules, twin_energy, twin_glance
    import main
    tokens, client = _people(), _client()
    catalogue = {'available': True, 'areas': [], 'devices': []}
    with patch.object(main, '_house_ha_context', return_value=(linked, catalogue)), \
            patch.object(ha_api, 'get_states', return_value=[]), \
            patch.object(twin_energy, 'entities', return_value=set()), \
            patch.object(twin_glance, 'entities', return_value=set()), \
            patch.object(control_rules, 'offered', return_value=False) as offered:
        assert 'switch.fire' in main._house_stream_entities()
        assert 'switch.fire' not in main._house_stream_entities('area')
        with _enforced():
            response = client.get('/api/house/live', headers=tokens['parent'])
            assert response.status_code == 200, response.text
        row = response.json()['markers'][-1]
        assert row['entity_id'] == 'switch.fire' and row['fire_pit'] and not row['offered']
        assert row['at'] == [20, 20, 1.5]
        assert row['device_id'] == 'fire_pit:old'
        assert any(call.args[1] == 'switch.fire' for call in offered.call_args_list)
        # The singleton and list forms both feed the stream and marker path.
        linked['site']['fire_pit'] = [linked['site']['fire_pit']]
        assert 'switch.fire' in main._house_stream_entities()
        catalogue['available'] = False
        assert main._house_stream_entities() == set()
        with _enforced():
            assert client.get('/api/house/live', headers=tokens['parent']).json()['markers'] == []
    print('Passed: singleton/list live entities, HTTP marker, permission gate and HA-absent fallback')


if __name__ == '__main__':
    try:
        run()
    finally:
        from services import storage
        storage.db.close()
        DATA.cleanup()
