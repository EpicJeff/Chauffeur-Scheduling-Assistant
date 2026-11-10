"""Mixed TV selection and Apple TV permission/read-back regressions.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_house_apple_tv_edges.py
"""
import unittest
from unittest.mock import patch

import test_house_apple_tv as base
from services import control_rules, ha_api


class AppleTvEdges(unittest.TestCase):
    setUp = base.AppleTvApps.setUp
    atv = base.AppleTvApps.atv
    open = base.AppleTvApps.open
    run_tool = base.AppleTvApps.run_tool

    def test_room_with_both_tv_kinds_is_ambiguous_and_sends_nothing(self):
        result = self.open('ESPN', query='living room')
        self.assertEqual(result['status'], 'ambiguous', result)
        self.assertEqual({r['entity_id'] for r in result['candidates']},
                         {base.ATV, 'remote.living_room_tv'})
        self.assertEqual(self.calls, [])

    def test_exact_android_name_wins_over_the_apple_tv_in_the_same_room(self):
        result = self.open('Netflix', query='living room tv')
        self.assertEqual(result['status'], 'refused', result)  # Android is unexposed
        self.assertIn('Living Room TV is not exposed', result['message'])
        self.assertEqual(self.calls, [])

    def test_direct_apple_tv_id_uses_select_source(self):
        result = self.run_tool(action='app', entity_id=base.ATV, app='ESPN')
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(self.calls, [('media_player', 'select_source',
                                      {'entity_id': base.ATV, 'source': 'ESPN'})])

    def test_unknown_and_unavailable_without_apps_still_report_offline(self):
        del self.atv()['attributes']['source_list']
        for state in ('unknown', 'unavailable'):
            self.atv()['state'] = state
            result = self.open('ESPN')
            self.assertEqual(result['status'], 'error', result)
            self.assertIn('offline', result['message'])
        self.assertEqual(self.calls, [])

    def test_errors_offer_the_apple_tv_too(self):
        result = self.open('ESPN', query='office lamp')
        self.assertEqual(result['status'], 'error', result)
        self.assertIn('TVs that can open apps:', result['message'])
        self.assertIn('Living Room Apple TV', result['message'])

    def test_android_known_apps_are_not_an_apple_tv_allowlist(self):
        self.atv()['attributes']['source_list'] = ['ESPN']
        for app in ('Netflix', 'com.netflix.ninja', 'https://www.netflix.com/browse'):
            result = self.open(app)
            self.assertEqual(result['status'], 'error', result)
        self.assertEqual(self.calls, [])

    def test_rulebook_refuses_before_waking_an_off_tv(self):
        self.atv()['state'] = 'off'
        rules = control_rules.default_rules({})
        rules['people']['child']['media'] = 'no'
        self.settings['ha_control'] = rules
        result = self.open('ESPN', acting_member={'id': 'm_lily', 'role': 'child'})
        self.assertEqual(result['status'], 'refused', result)
        self.assertEqual(self.calls, [])

    def test_already_on_the_app_does_not_claim_a_new_landing(self):
        self.atv()['attributes']['app_name'] = 'ESPN'
        result = self.open('ESPN')
        self.assertEqual(result['status'], 'success', result)
        self.assertFalse(result['landed'])
        self.assertTrue(result['already'])
        self.assertIn('already', result['message'])

    def test_source_alone_can_confirm_the_launch(self):
        inner = ha_api.call_service

        def call(*args, **kwargs):
            result = inner(*args, **kwargs)
            self.atv()['attributes'].pop('app_name', None)
            return result

        with patch.object(ha_api, 'call_service', side_effect=call):
            result = self.open('ESPN')
        self.assertTrue(result['landed'], result)

    def test_failed_service_reports_error(self):
        with patch.object(ha_api, 'call_service', return_value=None):
            result = self.open('ESPN')
        self.assertEqual(result['status'], 'error', result)
        self.assertIn('could not reach', result['message'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
