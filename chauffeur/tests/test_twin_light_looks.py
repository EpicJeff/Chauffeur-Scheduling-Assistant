"""Light looks routes execute with isolated storage and auth enforcement."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_light_looks_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from services import auth, storage, twin_light_looks as looks
import main

URL = '/api/house/twin/light-looks'


class LightLooksTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.trusted_devices_table,
                      storage.app_state_table, storage.settings_table):
            table.truncate()
        storage.add_member({'id': 'p', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'k', 'name': 'Kid', 'role': 'child'})
        self.parent = {'X-Member-Token': storage.create_member_token('p', proof='password')}
        self.kid = {'X-Member-Token': storage.create_member_token('k', proof='password')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('wall', 'Wall', 'p')}
        self.client = TestClient(main.app)
        self.enforce = patch.object(auth, 'enforcing', return_value=True)
        self.enforce.start()
        self.addCleanup(self.enforce.stop)

    def put(self, entity='light.pool', look=None):
        return self.client.put(URL, headers=self.parent, json={'entity_id': entity, 'look': look})

    def read(self):
        response = self.client.get(URL, headers=self.parent)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_fresh_no_ha_merge_and_clear(self):
        with patch('services.ha_api.get_states', side_effect=AssertionError('No HA read')):
            self.assertEqual(self.read(), {})
            self.assertEqual(self.put(look={'effects': {' Caribbean ': [[0, 200, 255], [0, 255, 120]]}}).status_code, 200)
            self.assertEqual(self.put('switch.rope', {'colour': [0, 80, 255]}).status_code, 200)
            self.assertEqual(self.read()['light.pool'], {'effects': {'caribbean': [[0, 200, 255], [0, 255, 120]]}})
            self.put(look=None)
            self.assertEqual(self.read(), {'switch.rope': {'colour': [0, 80, 255]}})
            for empty in ({}, {'effects': {}}):
                self.put('switch.rope', empty)
                self.assertEqual(self.read(), {})

    def test_every_validation_rejects_without_writing(self):
        invalid = [[], 'red', 1, {'other': []}, {'colour': None}, {'colour': [0, 0]},
                   {'colour': [0, 0, 0, 0]}, {'colour': ['1', 0, 0]}, {'colour': [True, 0, 0]},
                   {'colour': [1.5, 0, 0]}, {'colour': [-1, 0, 0]}, {'colour': [256, 0, 0]},
                   {'effects': []}, {'effects': None}, {'effects': {'': [[0, 0, 0]]}},
                   {'effects': {' ': [[0, 0, 0]]}}, {'effects': {'a' * 81: [[0, 0, 0]]}},
                   {'effects': {'party': []}}, {'effects': {'party': [[0, 0, 0]] * 5}},
                   {'effects': {'party': [[0, 0, '0']]}},
                   {'effects': {'party': [[0, 0, 0]], ' PARTY ': [[1, 1, 1]]}},
                   {'effects': {str(i): [[0, 0, 0]] for i in range(65)}}]
        for look in invalid:
            with self.subTest(look=look):
                self.assertEqual(self.put(look=look).status_code, 422)
                self.assertEqual(self.read(), {})
        for entity in ('', 'light', 'LIGHT.pool', 'light.a/b', 'light.a.b', 12, None):
            self.assertEqual(self.put(entity, {'colour': [1, 2, 3]}).status_code, 422)
            self.assertEqual(self.read(), {})
        for body in ({}, {'entity_id': 'light.pool'}, {'entity_id': 'light.pool', 'look': {}, 'extra': 0}):
            self.assertEqual(self.client.put(URL, headers=self.parent, json=body).status_code, 422)
            self.assertEqual(self.read(), {})
        for value in ('NaN', 'Infinity', '-Infinity'):
            response = self.client.put(URL, headers={**self.parent, 'Content-Type': 'application/json'},
                content='{"entity_id":"light.pool","look":{"colour":[' + value + ',0,0]}}')
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.read(), {})

    def test_caps_accept_boundaries_and_preserve_existing_store(self):
        look = {'effects': {('e' * 80) if i == 0 else str(i): [[0, 255, 0]] * 4 for i in range(64)}}
        self.assertEqual(self.put(look=look).status_code, 200)
        store = {f'light.l{i}': {'colour': [1, 2, 3]} for i in range(256)}
        storage.set_app_state(looks.KEY, store)
        self.assertEqual(self.put('light.extra', {'colour': [0, 0, 0]}).status_code, 422)
        self.assertEqual(self.read(), store)
        self.assertEqual(self.put('light.l0', {'colour': [4, 5, 6]}).status_code, 200)

    def test_auth_tiers(self):
        self.assertEqual(auth.resolve('GET', URL), auth.WALL_OR_SERVICE)
        self.assertEqual(auth.resolve('PUT', URL), auth.PARENTS)
        for headers in (self.kid, self.panel):
            self.assertEqual(self.client.get(URL, headers=headers).status_code, 200)
            self.assertIn(self.client.put(URL, headers=headers, json={'entity_id': 'light.pool', 'look': {}}).status_code, (401, 403))
        self.assertIn(self.client.put(URL, json={'entity_id': 'light.pool', 'look': {}}).status_code, (401, 403))
        self.assertEqual(self.read(), {})

    def test_simultaneous_different_entities_are_merged(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda i: self.put(f'light.l{i}', {'colour': [i, 0, 0]}).status_code, range(16)))
        self.assertEqual(responses, [200] * 16)
        self.assertEqual(len(self.read()), 16)


if __name__ == '__main__':
    unittest.main()
