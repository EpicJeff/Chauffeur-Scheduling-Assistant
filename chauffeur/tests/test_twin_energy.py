"""TestClient proof for mapping storage, permission tiers and isolated saves."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_energy_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from services import auth, storage, twin_energy, settings_registry
import main


class EnergyTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.trusted_devices_table,
                      storage.app_state_table, storage.cars_table):
            table.truncate()
        storage.add_member({'id': 'parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'kid', 'name': 'Kid', 'role': 'child'})
        self.parent = {'X-Member-Token': storage.create_member_token('parent', proof='password')}
        self.kid = {'X-Member-Token': storage.create_member_token('kid', proof='password')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('kitchen', 'Kitchen', 'parent')}
        self.client = TestClient(main.app)
        self.url = '/api/house/twin/energy'

    def test_empty_without_ha(self):
        with patch('services.ha_api.get_states', return_value=[]):
            body = self.client.get(self.url, headers=self.panel).json()
        self.assertEqual(body['mapping'], {})
        self.assertEqual(body['cars'], [])
        self.assertFalse(body['can_edit'])

    def test_save_read_signs_cars_panels_without_dirtying_schedules(self):
        mapping = {'solar_power': 'sensor.pv', 'battery_positive': 'charge', 'grid_positive': 'export',
                   'panels': {'visible': False, 'plane': 'house:roof-plane'},
                   'cars': [{'id': 'ev', 'name': 'EV', 'charge_power': 'sensor.ev_power',
                             'battery_level': 'sensor.ev_soc', 'location': 'device_tracker.ev'}]}
        with patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
            self.assertEqual(self.client.put(self.url, headers=self.parent, json=mapping).status_code, 200)
            dirty.assert_not_called()
        self.assertEqual(self.client.get(self.url, headers=self.panel).json()['mapping'], mapping)
        self.assertEqual(storage.get_app_state(twin_energy.KEY), mapping)

    def test_write_tier_and_read_tier(self):
        with patch.object(auth, 'enforcing', return_value=True):
            for headers in (self.kid, self.panel, {}):
                self.assertIn(self.client.put(self.url, headers=headers, json={}).status_code, (401, 403))
            for headers in (self.kid, self.panel, self.parent):
                self.assertEqual(self.client.get(self.url, headers=headers).status_code, 200)
            with patch.object(storage, 'get_settings', return_value={'service_token': 'energy-service-test'}):
                headers = {'X-Service-Token': 'energy-service-test'}
                self.assertEqual(self.client.get(self.url, headers=headers).status_code, 200)
                self.assertEqual(self.client.put(self.url, headers=headers, json={}).status_code, 403)
        self.assertEqual(auth.resolve('GET', self.url), auth.WALL_OR_SERVICE)
        self.assertEqual(auth.resolve('PUT', self.url), auth.PARENTS)

    def test_validation(self):
        for body in ({'solar_power': 'bad'}, {'grid_positive': 'guess'}, {'battery_positive': 'guess'},
                     {'panels': {'visible': 'yes'}}, {'cars': [{}]}, {'cars': [{'id': 'x', 'name': 'X'}] * 2}):
            self.assertEqual(self.client.put(self.url, headers=self.parent, json=body).status_code, 422)

    def test_reset_and_explicit_none(self):
        for mapping in ({'solar_power': None, 'cars': []}, {}):
            self.assertEqual(self.client.put(self.url, headers=self.parent, json=mapping).status_code, 200)
            self.assertEqual(self.client.get(self.url, headers=self.parent).json()['mapping'], mapping)

    def test_fleet_bindings_and_stream_scope(self):
        fleet = [{'id': 'family', 'name': 'Family car', 'ha_battery_entity': 'sensor.weird_soc', 'ha_device_tracker': 'device_tracker.family'}]
        catalogue = {'available': True, 'areas': [], 'devices': []}
        with patch.object(storage, 'get_all_cars', return_value=fleet), patch.object(main, '_house_ha_context', return_value=({'buildings': []}, catalogue)), patch('services.ha_api.get_states', return_value=[]):
            cars = self.client.get(self.url, headers=self.panel).json()['cars']
            self.assertEqual(cars[0]['battery_level'], 'sensor.weird_soc')
            twin_energy.save({'house_power': 'sensor.unusual'})
            self.assertEqual(main._house_stream_entities(), {'sensor.unusual', 'sensor.weird_soc', 'device_tracker.family'})
            self.assertEqual(main._house_stream_entities('kitchen'), set())

    def test_zone_sensor_is_scoped_and_invalid_hosts_are_not_energy_locations(self):
        catalogue={'available':True,'areas':[],'devices':[]}
        model={'buildings':[{'solar_zones':[{'entity':'sensor.unusual_zone'},{'entity':'sensor.ghost_zone','state':'ghost'}]}]}
        twin_energy.save({'cars':[]})
        with patch.object(main,'_house_ha_context',return_value=(model,catalogue)),patch('services.ha_api.get_states',return_value=[]):
            self.assertEqual(main._house_stream_entities(),{'sensor.unusual_zone'})
        from services import twin_model_hosts
        b={'id':'b','position':[0,0],'levels':[{'id':'L1','elevation':0,'ceiling':9}],
           'joints':[],'walls':[],'rooms':[],'devices':[{'id':'device:bat','device':'bat','state':'ghost','host':{'wall':'missing','at':3,'z':4}}],
           'flags':[{'piece':'device:bat','at':[2,3],'level':'L1'}]}
        spot=main._house_ha_placed_spot(b,'bat',{'kind':'device'},twin_model_hosts.snapshot(b))
        self.assertFalse(spot['location_valid'])

    def test_home_includes_chargers_mapping_roundtrip_and_validation(self):
        for value in (True,False):
            response=self.client.put(self.url,headers=self.parent,json={'home_includes_chargers':value})
            self.assertEqual(response.status_code,200,response.text)
            self.assertIs(self.client.get(self.url,headers=self.panel).json()['mapping']['home_includes_chargers'],value)
        for value in ('true',1,None,[]):
            self.assertEqual(self.client.put(self.url,headers=self.parent,json={'home_includes_chargers':value}).status_code,422)

    def test_settings_and_page(self):
        entry = settings_registry.BY_KEY['house_twin_energy']
        self.assertEqual((entry['page'], entry['anchor']), ('house/twin', 'twin-energy-settings'))
        self.assertEqual(settings_registry.audit(), {'missing': [], 'stale': []})
        self.assertEqual([e for e in settings_registry.audit_ui()['unreachable'] if e['key'] == 'house_twin_energy'], [])
        page = self.client.get('/house/twin', headers=self.parent)
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="twin-energy-fields"', page.text)
        wall = self.client.get('/house/twin?panel=true&kiosk=true', headers=self.panel)
        self.assertNotIn('id="twin-energy-fields"', wall.text)

    def test_live_camera_facing_survives_building_rotation(self):
        building = {'id': 'house', 'position': [0, 0], 'rotation': 90, 'base': 0,
                    'levels': [{'id': 'L1', 'elevation': 0, 'ceiling': 9}],
                    'rooms': [{'id': 'k', 'name': 'Kitchen', 'level': 'L1', 'ha_area': 'k',
                               'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]]}],
                    'walls': [], 'anchors': [], 'devices': [{'id': 'device:camera', 'device': 'camera',
                    'host': {'floor': 'k', 'u': .2, 'v': .3}, 'offset': 5, 'facing_deg': 30}]}
        device = {'device_id': 'camera', 'name': 'Camera', 'kind': 'camera',
                  'entity_id': 'camera.k', 'entities': ['camera.k'], 'area_id': 'k'}
        catalogue = {'available': True, 'areas': [{'area_id': 'k'}], 'devices': [device]}
        with patch.object(main, '_house_ha_context', return_value=({'buildings': [building]}, catalogue)), patch('services.ha_api.get_states', return_value=[]):
            response = self.client.get('/api/house/live', headers=self.panel)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['markers'][0]['facing_deg'], 120)


if __name__ == '__main__':
    unittest.main(verbosity=2)
