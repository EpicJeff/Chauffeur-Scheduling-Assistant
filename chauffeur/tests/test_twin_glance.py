"""TestClient proof for display preferences, auth, panel isolation and HA push scope."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_glance_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from services import auth, storage, twin_glance
import main


class GlanceTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.trusted_devices_table,
                      storage.app_state_table):
            table.truncate()
        storage.add_member({'id': 'parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'kid', 'name': 'Kid', 'role': 'child'})
        self.parent = {'X-Member-Token': storage.create_member_token('parent', proof='password')}
        self.kid = {'X-Member-Token': storage.create_member_token('kid', proof='password')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('kitchen', 'Kitchen', 'parent')}
        self.other = {'X-Device-Token': storage.enrol_device_token('hall', 'Hall', 'parent')}
        self.client = TestClient(main.app)
        self.url = '/api/house/twin/glance'

    def save(self, **body):
        return self.client.put(self.url, headers=self.parent, json=body)

    def read(self, headers=None, suffix=''):
        response = self.client.get(self.url + suffix, headers=headers or self.parent)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_defaults_and_no_ha(self):
        with patch('services.ha_api.get_states', return_value=[]):
            self.assertIsNone(self.read()['entities'])
            self.assertFalse(self.read()['idle_enabled'])
            self.assertTrue(self.read(self.panel)['idle_enabled'])

    def test_household_save_read_order_and_no_schedule_invalidation(self):
        with patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
            self.assertEqual(self.save(entities=['sensor.grid', 'sensor.battery'], idle_enabled=True).status_code, 200)
            dirty.assert_not_called()
        self.assertEqual(self.read()['entities'], ['sensor.grid', 'sensor.battery'])
        self.assertEqual(self.read(self.panel)['entities'], ['sensor.grid', 'sensor.battery'])
        self.assertEqual(storage.get_app_state(twin_glance.KEY)['entities'], ['sensor.grid', 'sensor.battery'])

    def test_panel_override_lives_on_enrolled_device(self):
        self.save(entities=['sensor.grid'])
        r = self.save(panel_id='kitchen', entities=['sensor.car', 'sensor.solar'], idle_enabled=False)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.read(self.panel)['entities'], ['sensor.car', 'sensor.solar'])
        self.assertFalse(self.read(self.panel)['idle_enabled'])
        self.assertEqual(self.read(self.other)['entities'], ['sensor.grid'])
        self.assertEqual(storage.get_trusted_device('kitchen')[twin_glance.KEY]['entities'], ['sensor.car', 'sensor.solar'])

    def test_return_to_household_and_explicit_empty_list(self):
        self.save(entities=['sensor.grid'])
        self.save(panel_id='kitchen', entities=[])
        self.assertEqual(self.read(self.panel)['entities'], [])
        self.save(panel_id='kitchen', entities=None)
        self.assertEqual(self.read(self.panel)['entities'], ['sensor.grid'])

    def test_parent_can_select_enrolled_panel(self):
        body = self.read(suffix='?panel_id=kitchen')
        self.assertEqual(body['panel_id'], 'kitchen')
        self.assertEqual({d['device_id'] for d in body['panels']}, {'kitchen', 'hall'})
        self.assertEqual(self.save(panel_id='missing', entities=[]).status_code, 404)

    def test_kid_and_panel_cannot_write(self):
        with patch.object(auth, 'enforcing', return_value=True):
            for headers in (self.kid, self.panel, {}):
                self.assertIn(self.client.put(self.url, headers=headers, json={'entities': []}).status_code, (401, 403))
        self.assertFalse(self.read(self.kid)['can_edit'])
        self.assertFalse(self.read(self.panel)['can_edit'])

    def test_panel_cannot_select_or_spoof_another_panel(self):
        self.assertEqual(self.client.get(self.url + '?panel_id=hall', headers=self.panel).status_code, 403)
        headers = {**self.panel, 'X-Device-Id': 'hall'}
        self.assertEqual(self.read(headers)['panel_id'], 'kitchen')
        self.assertNotIn('panels', self.read(self.panel))

    def test_list_validation(self):
        for ids in (['bad'], ['sensor.a', 'sensor.a'], ['sensor.' + str(i) for i in range(13)], ['sensor.x/../../file']):
            self.assertEqual(self.save(entities=ids).status_code, 422)

    def test_settings_registry_and_actual_page_render(self):
        from services import settings_registry
        for key in ('house_twin_glance', 'house_twin_idle_enabled'):
            entry = settings_registry.BY_KEY[key]
            self.assertEqual(entry['page'], 'house/twin')
            self.assertEqual(entry['anchor'], 'twin-glance-settings')
        self.assertEqual(settings_registry.audit(), {'missing': [], 'stale': []})
        self.assertEqual([e for e in settings_registry.audit_ui()['unreachable']
                          if e['key'].startswith('house_twin_')], [])
        page = self.client.get('/house/twin', headers=self.parent)
        self.assertEqual(page.status_code, 200)
        for text in ('id="twin-glance-home"', 'data-settings-for="twin"', 'house_twin_idle_enabled', 'twin-glance-selected'):
            self.assertIn(text, page.text)
        wall = self.client.get('/house/twin?panel=true', headers=self.panel)
        self.assertIn('data-twin-wall', wall.text)
        self.assertNotIn('data-settings-for="twin"', wall.text)

    def test_stream_includes_secondary_readings_and_default_energy_weather(self):
        catalogue = {'available': True, 'areas': [{'area_id': 'kitchen'}], 'devices': [
            {'entity_id': 'climate.k', 'entities': ['climate.k', 'sensor.temp'], 'area_id': 'kitchen'}]}
        states = [{'entity_id': 'weather.home', 'attributes': {}},
                  {'entity_id': 'sensor.grid', 'attributes': {'device_class': 'power'}}]
        with patch.object(main, '_house_ha_context', return_value=({'buildings': []}, catalogue)), patch('services.ha_api.get_states', return_value=states):
            self.assertEqual(main._house_stream_entities(), {'climate.k', 'sensor.temp', 'weather.home', 'sensor.grid'})
            self.assertEqual(main._house_stream_entities('kitchen'), {'climate.k', 'sensor.temp'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
