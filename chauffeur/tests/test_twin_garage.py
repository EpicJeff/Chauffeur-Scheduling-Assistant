"""Garage properties, history and the placed-cover live payload, without HA."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / '.tmp-garage').mkdir(exist_ok=True)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(dir=ROOT / '.tmp-garage', prefix='data-')
os.environ.pop('HA_BASE_URL', None)
from test_twin_model_devices import _house, LIVE
from services import twin_objects, twin_model, twin_model_ops as ops, twin_model_bridge as bridge
from services import twin_store as store, twin_edit, storage, ha_api


class GarageTests(unittest.TestCase):
    def test_values_and_refusals_are_atomic(self):
        for style in ('raised', 'flat', 'carriage', 'full_view'):
            for lites in ('none', 'top'):
                model = _house()
                changed, _ = ops.apply(model, {'op': 'set_object', 'building': 'B1', 'id': 'g1',
                    'properties': {'style': style, 'lites': lites}})
                opening = next(o for o in changed['buildings'][0]['openings'] if o['id'] == 'g1')
                self.assertEqual((opening['style'], opening['lites']), (style, lites))
                self.assertNotIn('style', model['buildings'][0]['openings'][3])
        for oid, field, value in [('g1', 'style', 'roller'), ('g1', 'lites', 'all'),
                                 ('d-front', 'style', 'raised'), ('win1', 'lites', 'top')]:
            model = _house()
            before = deepcopy(model)
            for operation in [{'op': 'set_object', 'building': 'B1', 'id': oid, 'properties': {field: value}},
                              {'op': 'set', 'building': 'B1', 'id': oid, 'field': field, 'value': value}]:
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'garage door|valid door style|valid windows'):
                    ops.apply(model, operation)
                self.assertEqual(model, before)

    def test_stored_default_is_not_rewritten_and_generic_set_works(self):
        model = _house()
        old = deepcopy(next(o for o in model['buildings'][0]['openings'] if o['id'] == 'g1'))
        normal, _ = twin_model.normalize(model)
        self.assertEqual(next(o for o in normal['buildings'][0]['openings'] if o['id'] == 'g1'), old)
        changed, _ = twin_edit.apply_model(model, {'op': 'set', 'building': 'B1', 'id': 'g1', 'field': 'style', 'value': 'flat'})
        self.assertEqual(next(o for o in changed['buildings'][0]['openings'] if o['id'] == 'g1')['style'], 'flat')

    def test_add_opening_validates_instead_of_dropping_garage_choices(self):
        model = _house()
        operation = {'op': 'add_opening', 'building': 'B1', 'wall': 'e', 'kind': 'garage',
                     'at': 10, 'width': 8, 'style': 'carriage', 'lites': 'top'}
        changed, _ = twin_edit.apply_model(model, operation)
        added = [o for o in changed['buildings'][0]['openings']
                 if o['id'] not in {p['id'] for p in model['buildings'][0]['openings']}]
        self.assertEqual(len(added), 1)
        self.assertEqual((added[0]['style'], added[0]['lites']), ('carriage', 'top'))
        for changes in ({'style': 'roller'}, {'lites': 'all'}, {'kind': 'window'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                twin_edit.apply_model(model, {**operation, **changes})

    def test_undo_restores_the_stored_opening(self):
        model = _house()
        round_id = store.push_round(bridge.flatten(model), 'build')
        before = deepcopy(next(o for o in store.current_model()['buildings'][0]['openings'] if o['id'] == 'g1'))
        twin_edit.save({'op': 'set_object', 'building': 'B1', 'id': 'g1', 'properties': {'style': 'carriage', 'lites': 'top'}}, 'garage-parent')
        self.assertEqual(next(o for o in store.current_model()['buildings'][0]['openings'] if o['id'] == 'g1')['style'], 'carriage')
        store.revert(round_id)
        self.assertEqual(next(o for o in store.current_model()['buildings'][0]['openings'] if o['id'] == 'g1'), before)

    def test_live_http_payload_carries_host_and_cover_and_degrades_without_ha(self):
        from fastapi.testclient import TestClient
        import main
        storage.add_member({'id': 'garage-parent', 'name': 'Parent', 'role': 'parent'})
        headers = {'X-Member-Token': storage.create_member_token('garage-parent')}
        model, _ = ops.apply(_house(), {'op': 'place_device', 'building': 'B1',
            'device': 'dev_garage_left', 'host': {'opening': 'g1', 'side': 'in'}}, ha_catalogue=LIVE)
        states = [{'entity_id': 'cover.left_garage_door', 'state': 'open', 'attributes': {'device_class': 'garage'}}]
        client = TestClient(main.app)
        with patch.object(main, '_house_ha_context', return_value=(model, deepcopy(LIVE))), \
                patch.object(ha_api, 'get_states', return_value=states):
            response = client.get('/api/house/live', headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            for rows in (body['devices'], body['markers']):
                cover = next(d for d in rows if d['device_id'] == 'dev_garage_left')
                self.assertEqual(cover['host'], {'opening': 'g1', 'side': 'in'})
                self.assertEqual(cover['building'], 'B1')
                self.assertEqual(cover['entity_id'], 'cover.left_garage_door')
            with patch.object(main, '_house_ha_context', return_value=(model, {'available': False, 'areas': [], 'floors': [], 'devices': []})):
                body = client.get('/api/house/live', headers=headers).json()
                self.assertFalse(body['available'])
                self.assertEqual(body['devices'], [])


if __name__ == '__main__':
    unittest.main()
