"""Home drive limits: offline solver, diagnostics, and replay regression tests."""
import datetime
import unittest
from unittest.mock import patch
import harness  # isolate storage and network before application imports
from models.schemas import Driver, Event, ManualOverride
from solver import matcher
from services import solve_pack


class HomeLimitTests(unittest.TestCase):
    def setUp(self):
        self.driver = Driver(id='limited', name='Local driver', color_code='#fff', max_drive_time_from_home=15)
        start = datetime.datetime(2026, 9, 21, 12)
        self.event = Event(id='activity', title='Practice', start=start,
                           end=start + datetime.timedelta(hours=1), location='Field',
                           calendar_ids=['primary'], source_event_ids=['activity'])

    def solve(self, **kw):
        return matcher.solve_schedule([self.event], [self.driver], [],
                                      restriction_home_location='Home', **kw)

    def test_boundary_and_unlimited(self):
        for minutes, allowed in [(14, True), (15, True), (16, False)]:
            with patch.object(matcher, '_raw_get_travel_time_minutes', return_value=minutes):
                self.assertEqual('activity' in self.solve()[0], allowed)
        self.driver.max_drive_time_from_home = None
        with patch.object(matcher, '_raw_get_travel_time_minutes', side_effect=AssertionError('unlimited must not route')):
            self.assertIn('activity', self.solve()[0])

    def test_other_driver_gets_far_activity_and_both_legs_are_limited(self):
        other = Driver(id='other', name='Other', color_code='#fff', priority_index=9)
        for kind in ['dropoff', 'pickup']:
            self.event.event_type = kind
            with patch.object(matcher, '_raw_get_travel_time_minutes', return_value=16):
                assignments, _, _, _ = matcher.solve_schedule([self.event], [self.driver, other], [], restriction_home_location='Home')
                self.assertEqual(assignments['activity'], 'other')

    def test_home_override_and_missing_locations(self):
        self.driver.home_location = 'Driver home'
        with patch.object(matcher, '_raw_get_travel_time_minutes', return_value=15) as route:
            self.assertIsNone(matcher.home_drive_limit_reason(self.event, self.driver, 'Household home'))
            route.assert_called_once_with('Driver home', 'Field')
        self.event.location = None
        self.assertIn('missing', matcher.home_drive_limit_reason(self.event, self.driver, 'Home'))
        self.assertNotIn('activity', self.solve()[0])

    def test_manual_override_warns_but_remains_available(self):
        with patch.object(matcher, '_raw_get_travel_time_minutes', return_value=16):
            reasons = matcher.explain_assignment_conflicts(self.event, self.driver, home_location='Home')
            self.assertTrue(any('limit is 15' in r for r in reasons))
            diagnostics = matcher.compute_diagnostics(['activity'], [self.event], [self.driver], {}, {}, [], [], home_location='Home')
            self.assertEqual(diagnostics['activity']['limited']['type'], 'home_drive_limit')
            self.assertIn('activity', self.solve(overrides=[ManualOverride(event_id='activity', driver_id='limited')])[0])

    def test_replay_carries_household_home(self):
        pack = solve_pack.build('2026-09-21', events=[self.event], drivers=[self.driver], rules=[],
            priority_rules=[], overrides=[], passengers=[], cars=[], driver_events={}, trip_metadata=[],
            driver_passenger_map={}, previous_assignments={}, load_balancing=False,
            load_balancing_metric='occupied_time', protected_rule_index={}, restriction_home_location='Home')
        with patch.object(matcher, '_raw_get_travel_time_minutes', return_value=16) as route:
            self.assertIn('activity', solve_pack.replay(pack)['unassigned'])
            route.assert_any_call('Home', 'Field')

    def test_profile_storage_roundtrip_and_clear(self):
        from services import storage
        storage.add_driver(self.driver.model_dump())
        row = next(d for d in storage.get_all_drivers() if d['id'] == self.driver.id)
        self.assertEqual(Driver(**row).max_drive_time_from_home, 15)
        storage.update_driver_fields(self.driver.id, {'max_drive_time_from_home': None})
        row = next(d for d in storage.get_all_drivers() if d['id'] == self.driver.id)
        self.assertIsNone(Driver(**row).max_drive_time_from_home)

    def test_validation_and_default(self):
        from pydantic import ValidationError
        for value in [0, -1, 1.5, True, 'bad']:
            with self.assertRaises(ValidationError):
                Driver(id='d', name='D', color_code='#fff', max_drive_time_from_home=value)
        self.assertIsNone(Driver(id='d', name='D', color_code='#fff').max_drive_time_from_home)


if __name__ == '__main__':
    unittest.main()
