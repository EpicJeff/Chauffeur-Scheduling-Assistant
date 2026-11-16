"""One marker per thing: a fire pit only carries a marker when its entity has no other."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = tempfile.TemporaryDirectory(prefix='chauffeur_pit_marker_', ignore_cleanup_errors=True)
os.environ['CHAUFFEUR_DATA_DIR'] = DATA.name
os.environ.pop('HA_BASE_URL', None)
from test_twin_model_devices import _house, LIVE
from services import twin_model_ops as ops, storage, ha_api


class FirePitMarkerTests(unittest.TestCase):
    def test_pit_marker_only_when_the_entity_has_no_other_marker(self):
        from fastapi.testclient import TestClient
        import main
        storage.add_member({'id': 'pit-parent', 'name': 'Parent', 'role': 'parent'})
        headers = {'X-Member-Token': storage.create_member_token('pit-parent')}
        model, _ = ops.apply(_house(), {'op': 'place_device', 'building': 'B1',
            'device': 'dev_garage_left', 'host': {'opening': 'g1', 'side': 'in'}}, ha_catalogue=LIVE)
        client = TestClient(main.app)

        def live(entity, catalogue=LIVE):
            linked = deepcopy(model)
            linked.setdefault('site', {})['fire_pit'] = {'id': 'pit', 'shape': 'round', 'at': [20, 20],
                                                         'radius': 2, 'entity': entity}
            with patch.object(main, '_house_ha_context', return_value=(linked, deepcopy(catalogue))), \
                    patch.object(ha_api, 'get_states', return_value=[]):
                response = client.get('/api/house/live', headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        # The linked entity already shows as the placed garage cover: no second marker.
        body = live('cover.left_garage_door')
        carrying = [m for m in body['markers'] if 'cover.left_garage_door' in [m['entity_id'], *m['entities']]]
        self.assertEqual([m['device_id'] for m in carrying], ['dev_garage_left'])
        for rows in (body['markers'], body['devices']):
            self.assertFalse([r for r in rows if r.get('fire_pit')])

        # No marker anywhere carries the entity: the pit keeps its own hand path.
        body = live('switch.fire_only_on_the_pit')
        for rows in (body['markers'], body['devices']):
            pit = [r for r in rows if r.get('fire_pit')]
            self.assertEqual([r['device_id'] for r in pit], ['fire_pit:pit'])
            self.assertEqual(pit[0]['entity_id'], 'switch.fire_only_on_the_pit')
        self.assertTrue(any(m['device_id'] == 'dev_garage_left' for m in body['markers']))

        # No Home Assistant: nothing to mark, nothing breaks.
        body = live('cover.left_garage_door', {'available': False, 'areas': [], 'floors': [], 'devices': []})
        self.assertFalse(body['available'])
        self.assertEqual(body['markers'], [])


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        DATA.cleanup()
