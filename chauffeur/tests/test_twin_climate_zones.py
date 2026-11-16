"""Entity-owned climate zones through real authenticated editor requests."""
import copy
import sys
import traceback
from unittest.mock import patch

from test_twin_fixtures import Ctx, LIVE, post, seed, ts, twin_model
from services import twin_model_bridge as bridge

ENTITY = 'climate.hall'


def operation(**values):
    return {'op': 'set_climate_zone', 'entity': ENTITY, 'scope': 'house',
            'rooms': [], 'except': [], **values}


def test_roundtrip_layout_validation_clear_and_parent_gate():
    seed()
    with Ctx() as c:
        m = post(c, operation(scope='rooms', rooms=['kitchen', 'kitchen', 'removed'], **{'except': ['yard', 'yard']}))
        expected = {'scope': 'rooms', 'rooms': ['kitchen'], 'except': ['yard']}
        assert m['climate_zones'] == {ENTITY: expected}
        assert twin_model.normalize(m)[0]['climate_zones'] == m['climate_zones']
        assert c.client.get(LIVE, headers=c.mum).json()['climate_zones'] == m['climate_zones']
        for change in ({'entity': 'light.hall'}, {'entity': 'climate.'}, {'entity': 3},
                       {'scope': 'building'}, {'scope': []}, {'rooms': 'kitchen'},
                       {'rooms': [3]}, {'except': [False]}, {'rooms': ['kitchen'] * 65},
                       {'except': ['yard'] * 65}):
            post(c, operation(**change), 400)
        post(c, operation(), 403, c.kid)
        post(c, {'op': 'set_climate_zone', 'entity': ENTITY}, 400)
        m = post(c, operation(scope=None))
        assert m['climate_zones'] == {}
        assert c.client.get(LIVE, headers=c.mum).json()['climate_zones'] == {}


def test_marker_move_flat_read_undo_and_removed_room():
    seed()
    with Ctx() as c:
        catalogue = {'available': True, 'areas': [{'area_id': 'kitchen'}], 'devices': [
            {'device_id': 'dev-climate', 'kind': 'climate', 'name': 'Hall', 'entity_id': ENTITY,
             'entities': [ENTITY], 'area_id': 'kitchen'}]}
        with patch('services.twin_ha.safe_catalogue', return_value=catalogue):
            post(c, {'op': 'place_device', 'device': 'dev-climate', 'building': 'B1',
                     'host': {'floor': 'kitchen', 'u': .2, 'v': .3}})
            m = post(c, operation(scope='floor', **{'except': ['yard']}))
            saved = copy.deepcopy(m['climate_zones'])
            post(c, {'op': 'unplace_device', 'device': 'dev-climate'})
            m = post(c, {'op': 'place_device', 'device': 'dev-climate', 'building': 'B1',
                         'host': {'floor': 'kitchen', 'u': .7, 'v': .6}})
            assert m['climate_zones'] == saved
            assert c.client.get(LIVE, headers=c.mum).json()['climate_zones'] == saved
        flat = bridge.flatten(m)
        flat.pop('climate_zones', None)
        restored, _ = bridge.assemble(flat, m)
        assert restored['climate_zones'] == saved
        restored['site']['yard_rooms'] = []
        normalized, _ = twin_model.normalize(restored)
        assert normalized['climate_zones'][ENTITY]['except'] == []
        original = ts.current_id()
        post(c, operation(scope=None))
        response = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': original})
        assert response.status_code == 200, response.text
        assert ts.current_model()['climate_zones'] == saved


def test_defaults_are_never_written_and_invalid_maps_degrade():
    seed()
    m = ts.current_model()
    assert 'climate_zones' not in m
    assert 'climate_zones' not in twin_model.normalize(m)[0]
    for raw in ([], {ENTITY: {'scope': 'bad'}}, {'light.a': {'scope': 'house'}}):
        normalized, notes = twin_model.normalize({**m, 'climate_zones': raw})
        assert normalized['climate_zones'] == {} and notes


if __name__ == '__main__':
    tests = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print('  ok ' + test.__name__)
        except Exception:
            failed += 1
            print('  FAIL ' + test.__name__)
            traceback.print_exc()
    print(f'{len(tests) - failed}/{len(tests)} climate model checks passed')
    sys.exit(bool(failed))
