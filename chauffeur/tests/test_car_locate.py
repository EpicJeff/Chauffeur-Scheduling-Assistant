"""`manage_car locate`: "where is the van?" answers from the car's HA tracker,
with the zone HA knows (home, not_home, a named zone), the coordinates and a
reverse-geocoded place when the car is away. A car with no tracker says so.
Stubbed ha_api and maps.reverse_geocode, the real tool handler.

Run from chauffeur/:  python tests/test_car_locate.py
"""
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_tools_v2, ha_api, maps, storage


class CarLocateTests(unittest.TestCase):
    def setUp(self):
        self.orig = {(ha_api, 'get_states'): ha_api.get_states,
                     (maps, 'reverse_geocode'): getattr(maps, 'reverse_geocode', None)}
        self.states = [
            {'entity_id': 'device_tracker.van', 'state': 'not_home', 'last_updated': '2026-10-27T15:00:00+00:00',
             'attributes': {'latitude': 35.79, 'longitude': -78.78, 'gps_accuracy': 12, 'friendly_name': 'Van'}},
            {'entity_id': 'device_tracker.suv', 'state': 'home', 'last_updated': '2026-10-27T15:00:00+00:00',
             'attributes': {'latitude': 35.70, 'longitude': -78.70, 'friendly_name': 'SUV'}},
        ]
        ha_api.get_states = lambda ttl=5: self.states
        self.geocoded = []

        def reverse(lat, lon):
            self.geocoded.append((lat, lon))
            return 'Target, 12 Elm St, Cary'
        maps.reverse_geocode = reverse
        with storage.db_lock:
            storage.cars_table.truncate()
        storage.add_car({'id': 'van', 'name': 'Van', 'ha_device_tracker': 'device_tracker.van'})
        storage.add_car({'id': 'suv', 'name': 'SUV', 'ha_device_tracker': 'device_tracker.suv'})
        storage.add_car({'id': 'old', 'name': 'Old Truck'})

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            if value is None:
                if hasattr(mod, name):
                    delattr(mod, name)
            else:
                setattr(mod, name, value)
        with storage.db_lock:
            storage.cars_table.truncate()

    def test_an_away_car_names_its_place(self):
        res = agent_tools_v2.handle_manage_car({'action': 'locate', 'car_id': 'Van'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['car'], 'Van')
        self.assertEqual(res['zone'], 'not_home')
        self.assertEqual(res['place'], 'Target, 12 Elm St, Cary')
        self.assertEqual((res['latitude'], res['longitude']), (35.79, -78.78))
        self.assertEqual(res['last_updated'], '2026-10-27T15:00:00+00:00')
        self.assertEqual(self.geocoded, [(35.79, -78.78)])
        self.assertIn('Target', res['message'])

    def test_a_car_at_home_is_not_geocoded(self):
        res = agent_tools_v2.handle_manage_car({'action': 'locate', 'car_id': 'suv'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['zone'], 'home')
        self.assertEqual(self.geocoded, [])
        self.assertIn('home', res['message'].lower())

    def test_a_car_without_a_tracker_says_so(self):
        res = agent_tools_v2.handle_manage_car({'action': 'locate', 'car_id': 'Old Truck'})
        self.assertEqual(res['status'], 'error')
        self.assertIn('tracker', res['message'])

    def test_a_tracker_that_cannot_answer_is_unknown_never_home(self):
        self.states[0]['state'] = 'unavailable'
        res = agent_tools_v2.handle_manage_car({'action': 'locate', 'car_id': 'Van'})
        self.assertEqual(res['status'], 'error')
        self.assertNotIn('home', res['message'].lower())

    def test_locate_is_offered_in_the_tool_description(self):
        schema = agent_tools_v2.TOOL_SCHEMAS['manage_car']
        self.assertIn('locate', repr(schema))


if __name__ == '__main__':
    unittest.main()
