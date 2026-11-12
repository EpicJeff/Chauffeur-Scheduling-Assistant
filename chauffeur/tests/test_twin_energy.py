"""TestClient proof for mapping storage, permission tiers and isolated saves."""
import os
import copy
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
                              'battery_level': 'sensor.ev_soc', 'location': 'device_tracker.ev'}], 'chargers': []}
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

    def test_chargers_validate_limit_unique_ids_entities_and_locations(self):
        chargers = [{'id': 'charger-' + str(i), 'name': 'Charger ' + str(i),
                     'power': 'sensor.charger_' + str(i), 'car': None,
                     'anchor': {'type': 'device', 'id': 'wallbox-' + str(i)}} for i in range(8)]
        chargers[1]['anchor'] = {'type': 'object', 'id': 'anchor:charger', 'building': 'garage'}
        mapping = {'chargers': chargers}
        response = self.client.put(self.url, headers=self.parent, json=mapping)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(self.url, headers=self.panel).json()['mapping'], mapping)
        invalid = [chargers + [{'id': 'ninth', 'name': 'Ninth'}], chargers[:1] * 2, {}, [None],
                   [{'id': 'x', 'name': 'X', 'power': 'bad'}],
                   [{'id': 'x', 'name': 'X', 'power': 7000}],
                   [{'id': 'x', 'name': 'X', 'car': 1}]]
        invalid += [[{'id': 'x', 'name': 'X', 'anchor': anchor}] for anchor in (
            'garage', {}, {'type': 'device', 'id': ''}, {'type': 'guess', 'id': 'x'},
            {'type': 'object', 'id': 'x'}, {'type': 'object', 'id': 'x', 'building': 5})]
        for chargers in invalid:
            with self.subTest(chargers=chargers):
                self.assertEqual(self.client.put(self.url, headers=self.parent, json={'chargers': chargers}).status_code, 422)
                self.assertEqual(storage.get_app_state(twin_energy.KEY), mapping)

    def test_legacy_migration_reads_without_writes_and_first_save_is_new_shape(self):
        legacy = {'cars': [
            {'id': 'both', 'name': 'Both', 'charge_power': 'sensor.both_power',
             'anchor': {'type': 'device', 'id': 'wallbox'}},
            {'id': 'anchor', 'name': 'Anchor only', 'anchor': {'type': 'object', 'id': 'anchor:1', 'building': 'b'}},
            {'id': 'power', 'name': 'Power only', 'charge_power': 'sensor.power'},
            {'id': 'none', 'name': 'No legacy charger'}]}
        original = copy.deepcopy(legacy)
        storage.set_app_state(twin_energy.KEY, legacy)
        with patch.object(storage, 'set_app_state') as write:
            migrated = self.client.get(self.url, headers=self.panel).json()['mapping']
            self.assertEqual(twin_energy.read(), migrated)
            write.assert_not_called()
        self.assertEqual(storage.get_app_state(twin_energy.KEY), original)
        self.assertEqual(legacy, original)
        self.assertEqual(migrated['chargers'], [
            {'id': 'charger-both', 'name': 'Both charger', 'power': 'sensor.both_power',
             'anchor': {'type': 'device', 'id': 'wallbox'}, 'car': 'both'},
            {'id': 'charger-anchor', 'name': 'Anchor only charger', 'power': None,
             'anchor': {'type': 'object', 'id': 'anchor:1', 'building': 'b'}, 'car': 'anchor'},
            {'id': 'charger-power', 'name': 'Power only charger', 'power': 'sensor.power', 'anchor': None, 'car': 'power'}])
        for car in migrated['cars'][:3]:
            self.assertIsNone(car['charge_power'])
            self.assertIsNone(car['anchor'])
        self.assertEqual(migrated['cars'][3], original['cars'][3])
        response = self.client.put(self.url, headers=self.parent, json=migrated)
        self.assertEqual(response.status_code, 200, response.text)
        expected = copy.deepcopy(migrated)
        for car in expected['cars']:
            for field in ('charge_power', 'battery_level', 'location'):
                car.setdefault(field, None)
        self.assertEqual(storage.get_app_state(twin_energy.KEY), expected)
        self.assertEqual(self.client.get(self.url, headers=self.panel).json()['mapping'], expected)

    def test_explicit_chargers_preserve_car_own_reading_and_new_bindings(self):
        mapping = {'chargers': [], 'cars': [{'id': 'ev', 'name': 'EV', 'charge_power': 'sensor.ev_power',
                   'battery_level': 'sensor.ev_soc', 'location': 'device_tracker.ev',
                   'charging': 'binary_sensor.ev_charging', 'parking': 'anchor:parking'}]}
        response = self.client.put(self.url, headers=self.parent, json=mapping)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(self.url, headers=self.panel).json()['mapping'], mapping)
        for field, bad in (('charging', 'charging'), ('parking', 5), ('parking', '')):
            invalid = copy.deepcopy(mapping)
            invalid['cars'][0][field] = bad
            self.assertEqual(self.client.put(self.url, headers=self.parent, json=invalid).status_code, 422)
        legacy_too_many = {'cars': [{'id': str(i), 'name': 'EV ' + str(i), 'charge_power': 'sensor.ev_' + str(i)} for i in range(9)]}
        self.assertEqual(self.client.put(self.url, headers=self.parent, json=legacy_too_many).status_code, 422)

    def test_long_legacy_car_name_migrates_and_first_save_succeeds(self):
        name = 'Family EV ' + 'x' * 90
        self.assertEqual(len(name), 100)
        legacy = {'cars': [{'id': 'long', 'name': name, 'charge_power': 'sensor.long_power'}]}
        storage.set_app_state(twin_energy.KEY, legacy)
        migrated = self.client.get(self.url, headers=self.panel).json()['mapping']
        self.assertEqual(migrated['cars'][0]['name'], name)
        self.assertEqual(migrated['chargers'][0]['name'], name[:92] + ' charger')
        self.assertEqual(len(migrated['chargers'][0]['name']), 100)
        self.assertEqual(storage.get_app_state(twin_energy.KEY), legacy)
        response = self.client.put(self.url, headers=self.parent, json=migrated)
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.get(self.url, headers=self.panel).json()['mapping']
        self.assertEqual(saved, twin_energy.validate(migrated))
        self.assertEqual(saved['cars'][0]['name'], name)
        self.assertEqual(saved['chargers'][0]['name'], name[:92] + ' charger')

    def test_unsaved_charging_sensor_and_placed_charger_power_are_streamed(self):
        catalogue = {'available': True, 'areas': [], 'devices': []}
        model = {'buildings': [{'anchors': [
            {'id': 'wall', 'kind': 'charger', 'power': 'sensor.unusual_evse_reading', 'state': 'settled'},
            {'id': 'ghost', 'kind': 'charger', 'power': 'sensor.ghost_charger_reading', 'state': 'ghost'}]}]}
        states = [{'entity_id': 'binary_sensor.my_ev_charging', 'state': 'off', 'attributes': {}},
                  {'entity_id': 'binary_sensor.unrelated', 'state': 'off', 'attributes': {}}]
        self.assertEqual(twin_energy.read(), {})
        with patch.object(storage, 'get_all_cars', return_value=[]), \
             patch.object(main, '_house_ha_context', return_value=(model, catalogue)), \
             patch('services.ha_api.get_states', return_value=states):
            self.assertEqual(main._house_stream_entities(),
                             {'binary_sensor.my_ev_charging', 'sensor.unusual_evse_reading'})
            self.assertEqual(main._house_stream_entities('garage'), set())
        self.assertEqual(twin_energy.read(), {})

    def test_fleet_bindings_and_stream_scope(self):
        fleet = [{'id': 'family', 'name': 'Family car', 'ha_battery_entity': 'sensor.weird_soc',
                  'ha_device_tracker': 'device_tracker.family', 'ha_range_entity': 'sensor.family_range', 'color_code': '#123456'}]
        catalogue = {'available': True, 'areas': [], 'devices': []}
        with patch.object(storage, 'get_all_cars', return_value=fleet), patch.object(main, '_house_ha_context', return_value=({'buildings': []}, catalogue)), patch('services.ha_api.get_states', return_value=[]):
            cars = self.client.get(self.url, headers=self.panel).json()['cars']
            self.assertEqual(cars[0]['battery_level'], 'sensor.weird_soc')
            self.assertEqual(cars[0]['range_entity'], 'sensor.family_range')
            self.assertEqual(cars[0]['color'], '#123456')
            self.assertEqual(cars[0]['battery_warn_pct'], 30)
            twin_energy.save({'house_power': 'sensor.unusual'})
            self.assertEqual(main._house_stream_entities(), {'sensor.unusual', 'sensor.weird_soc', 'device_tracker.family', 'sensor.family_range'})
            twin_energy.save({'house_power': 'sensor.unusual',
                             'chargers': [{'id': 'wall', 'name': 'Wallbox', 'power': 'sensor.wallbox_power'}],
                             'cars': [{'id': 'family', 'name': 'Family car', 'charge_power': 'sensor.family_power',
                                       'charging': 'binary_sensor.family_charging', 'battery_level': 'sensor.weird_soc',
                                       'location': 'device_tracker.family', 'parking': 'anchor:spot'}]})
            expected = {'sensor.unusual', 'sensor.weird_soc', 'device_tracker.family', 'sensor.family_range',
                        'sensor.wallbox_power', 'sensor.family_power', 'binary_sensor.family_charging'}
            self.assertEqual(twin_energy.entities(), expected)
            self.assertEqual(main._house_stream_entities(), expected)
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
