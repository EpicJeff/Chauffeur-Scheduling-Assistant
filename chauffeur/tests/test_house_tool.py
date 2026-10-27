"""The house tool (docs/superpowers/specs/2026-10-27-house-tool-design.md).

Argyle reads and controls Home Assistant devices through one tool, `house`.
Reads are open to anyone; writes respect HA's Assist exposure unless the
household lifts it; locks, alarms and garage doors need a parent or adult
(signed in, admin chat, or a VERIFIED voice). Every act reads the entity
back. Stubbed ha_api, the real services.house and the real tool entry point.

Run from chauffeur/:  python tests/test_house_tool.py
"""
import types
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_tools_v2, ha_api, house, storage

LAMP_TOKEN = 'eyJ-secret-should-never-leave'


def _states():
    return [
        {'entity_id': 'light.office_lamp', 'state': 'on', 'last_changed': '2026-10-27T10:00:00+00:00',
         'attributes': {'friendly_name': 'Office Lamp', 'brightness': 128, 'color_mode': 'brightness',
                        'access_token': LAMP_TOKEN, 'supported_color_modes': ['brightness']}},
        {'entity_id': 'media_player.office_tv_2', 'state': 'on', 'last_changed': '2026-10-27T09:00:00+00:00',
         'attributes': {'friendly_name': 'Office TV', 'access_token': 'tv-token', 'entity_picture': '/api/x'}},
        {'entity_id': 'light.front_porch_column_1', 'state': 'off', 'last_changed': '2026-10-27T08:00:00+00:00',
         'attributes': {'friendly_name': 'Front Porch Column 1'}},
        {'entity_id': 'light.hall', 'state': 'off', 'last_changed': '2026-10-27T08:00:00+00:00',
         'attributes': {'friendly_name': 'Hall Light'}},
        {'entity_id': 'lock.front_door', 'state': 'locked', 'last_changed': '2026-10-27T07:00:00+00:00',
         'attributes': {'friendly_name': 'Front Door'}},
        {'entity_id': 'cover.main_garage', 'state': 'closed', 'last_changed': '2026-10-27T06:00:00+00:00',
         'attributes': {'friendly_name': 'Main Garage', 'device_class': 'garage'}},
        {'entity_id': 'cover.office_blind', 'state': 'open', 'last_changed': '2026-10-27T06:00:00+00:00',
         'attributes': {'friendly_name': 'Office Blind', 'device_class': 'blind'}},
        {'entity_id': 'light.hidden_strip', 'state': 'on', 'last_changed': '2026-10-27T06:00:00+00:00',
         'attributes': {'friendly_name': 'Office Strip'}},
    ]


REGISTRY = [
    {'entity_id': 'light.office_lamp', 'name': None, 'original_name': 'Office Lamp', 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'hue'},
    {'entity_id': 'media_player.office_tv_2', 'name': 'Office TV', 'original_name': None, 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'androidtv_remote'},
    {'entity_id': 'light.front_porch_column_1', 'name': None, 'original_name': 'Front Porch Column 1',
     'aliases': ['front porch column one'], 'area_id': 'front_yard', 'device_id': None,
     'hidden_by': None, 'disabled_by': None, 'platform': 'hue'},
    {'entity_id': 'light.hall', 'name': None, 'original_name': 'Hall Light', 'aliases': [],
     'area_id': 'hall', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'hue'},
    {'entity_id': 'lock.front_door', 'name': None, 'original_name': 'Front Door', 'aliases': [],
     'area_id': 'hall', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'august'},
    {'entity_id': 'cover.main_garage', 'name': None, 'original_name': 'Main Garage', 'aliases': [],
     'area_id': 'garage', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'myq'},
    {'entity_id': 'cover.office_blind', 'name': None, 'original_name': 'Office Blind', 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': None, 'disabled_by': None, 'platform': 'somfy'},
    {'entity_id': 'light.hidden_strip', 'name': None, 'original_name': 'Office Strip', 'aliases': [],
     'area_id': 'office', 'device_id': None, 'hidden_by': 'user', 'disabled_by': None, 'platform': 'wled'},
]

AREAS = [
    {'id': 'office', 'name': 'Office', 'entities': ['light.office_lamp', 'media_player.office_tv_2',
                                                    'cover.office_blind', 'light.hidden_strip']},
    {'id': 'front_yard', 'name': 'Front Yard', 'entities': ['light.front_porch_column_1']},
    {'id': 'hall', 'name': 'Hall', 'entities': ['light.hall', 'lock.front_door']},
    {'id': 'garage', 'name': 'Garage', 'entities': ['cover.main_garage']},
]

EXPOSED = {'light.office_lamp': True, 'media_player.office_tv_2': True, 'light.front_porch_column_1': True,
           'lock.front_door': True, 'cover.main_garage': True, 'cover.office_blind': True, 'light.hall': False}

SERVICES = {'light': {'turn_on', 'turn_off', 'toggle'}, 'lock': {'lock', 'unlock'},
            'cover': {'open_cover', 'close_cover'}, 'media_player': {'turn_off', 'turn_on'}}


def voice(level, member=None):
    return types.SimpleNamespace(level=level, member=lambda: member,
                                 verified_member=lambda: member if level == 'verified' else None)


class HouseToolTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.states = _states()
        self.settings = {}
        self.orig = {}

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)
        tests = self

        def call_service(domain, service, data=None, return_response=False, timeout=None):
            tests.calls.append((domain, service, dict(data or {})))
            eid = (data or {}).get('entity_id')
            after = {('light', 'turn_on'): 'on', ('light', 'turn_off'): 'off', ('lock', 'unlock'): 'unlocked',
                     ('lock', 'lock'): 'locked', ('cover', 'open_cover'): 'open', ('media_player', 'turn_off'): 'off'}
            for s in tests.states:
                if s['entity_id'] == eid and (domain, service) in after:
                    s['state'] = after[(domain, service)]
                    if (domain, service) == ('light', 'turn_on') and 'brightness_pct' in (data or {}):
                        s['attributes']['brightness'] = round(data['brightness_pct'] * 255 / 100)
            return []
        stub(ha_api, 'get_states', lambda ttl=5: tests.states)
        stub(ha_api, 'get_entity_registry', lambda ttl=300: REGISTRY)
        stub(ha_api, 'get_area_map', lambda ttl=60: AREAS)
        stub(ha_api, 'get_exposed', lambda ttl=60: dict(EXPOSED))
        stub(ha_api, 'call_service', call_service)
        stub(ha_api, 'has_service', lambda d, s: s in SERVICES.get(d, set()))
        stub(ha_api, 'get_history', lambda entity_id, hours=24: tests.history(entity_id, hours))
        stub(ha_api, 'mode', lambda: 'supervisor')
        stub(storage, 'get_settings', lambda: dict(tests.settings))
        stub(house, '_settle', lambda: None)  # no 0.6 s sleep in tests
        self.history_rows = []

    def history(self, entity_id, hours):
        return self.history_rows

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)

    def run_tool(self, **kw):
        return agent_tools_v2.house(**kw)

    # --- find ---------------------------------------------------------------
    def test_find_ranks_the_named_device_first_and_matches_aliases(self):
        res = self.run_tool(action='find', query='office lamp')
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['candidates'][0]['entity_id'], 'light.office_lamp')
        self.assertEqual(res['candidates'][0]['area'], 'Office')
        ids = [c['entity_id'] for c in self.run_tool(action='find', query='front porch column one')['candidates']]
        self.assertEqual(ids[0], 'light.front_porch_column_1', 'the registry alias did not match')

    def test_find_skips_hidden_entities_and_filters_by_domain(self):
        ids = [c['entity_id'] for c in self.run_tool(action='find', query='office')['candidates']]
        self.assertNotIn('light.hidden_strip', ids)
        ids = [c['entity_id'] for c in self.run_tool(action='find', query='office', domain='light')['candidates']]
        self.assertEqual(ids, ['light.office_lamp'])

    def test_find_by_area_lists_the_rooms_devices(self):
        ids = {c['entity_id'] for c in self.run_tool(action='find', query='garage')['candidates']}
        self.assertIn('cover.main_garage', ids)

    # --- read ---------------------------------------------------------------
    def test_read_gives_brightness_as_percent_and_never_a_token(self):
        res = self.run_tool(action='read', entity_id='light.office_lamp')
        self.assertEqual(res['status'], 'success')
        ent = res['entity']
        self.assertEqual(ent['state'], 'on')
        self.assertEqual(ent['brightness_pct'], 50)
        self.assertNotIn('access_token', ent['attributes'])
        self.assertNotIn(LAMP_TOKEN, repr(res))
        self.assertTrue(ent['exposed'])
        tv = self.run_tool(action='read', query='office tv')['entity']
        self.assertNotIn('entity_picture', tv['attributes'])
        self.assertNotIn('tv-token', repr(tv))

    def test_read_of_an_unexposed_entity_is_still_a_read(self):
        res = self.run_tool(action='read', entity_id='light.hall', acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success')
        self.assertFalse(res['entity']['exposed'])

    def test_an_ambiguous_query_returns_candidates_and_touches_nothing(self):
        res = self.run_tool(action='act', query='office', service='turn_off',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'ambiguous')
        self.assertGreater(len(res['candidates']), 1)
        self.assertEqual(self.calls, [])

    # --- history ------------------------------------------------------------
    def test_history_is_thinned_and_counts_changes(self):
        self.history_rows = [(f'2026-10-27T00:{i % 60:02d}:00+00:00', 'on' if i % 2 else 'off') for i in range(500)]
        res = self.run_tool(action='history', entity_id='light.office_lamp', hours=24)
        self.assertEqual(res['status'], 'success')
        self.assertLessEqual(len(res['points']), 50)
        self.assertEqual(res['changes'], 499)
        self.assertEqual(res['points'][0]['state'], 'off')
        self.assertEqual(res['points'][-1]['state'], 'on')

    # --- act ----------------------------------------------------------------
    def test_a_kid_can_turn_off_an_exposed_lamp_and_hears_the_state_after(self):
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])
        self.assertEqual(res['state_after'], 'off')

    def test_brightness_rides_the_call_as_given(self):
        res = self.run_tool(action='act', query='office lamp', service='light.turn_on', data={'brightness_pct': 20},
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[0], ('light', 'turn_on', {'entity_id': 'light.office_lamp', 'brightness_pct': 20}))
        self.assertEqual(res['brightness_pct'], 20)

    def test_entity_id_in_data_never_overrides_the_resolved_entity(self):
        self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                      data={'entity_id': 'lock.front_door'}, acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])

    def test_an_unexposed_light_is_refused_until_the_household_allows_it(self):
        res = self.run_tool(action='act', entity_id='light.hall', service='turn_on',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'refused')
        self.assertIn('not exposed', res['message'])
        self.assertIn('Config', res['message'])
        self.assertEqual(self.calls, [])
        self.settings['house_control_unexposed'] = True
        res = self.run_tool(action='act', entity_id='light.hall', service='turn_on',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['state_after'], 'on')

    def test_a_lock_needs_a_verified_parent_voice(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            voice_context=voice('named', {'id': 'p1', 'role': 'parent'}), source='voice')
        self.assertEqual(res['status'], 'refused')
        self.assertIn('parent', res['message'])
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            voice_context=voice('verified', {'id': 'p1', 'role': 'parent'}), source='voice')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['state_after'], 'unlocked')

    def test_a_verified_kid_voice_still_cannot_unlock(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            voice_context=voice('verified', {'id': 'k1', 'role': 'kid'}), source='voice')
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_a_garage_door_needs_a_parent_but_a_blind_does_not(self):
        res = self.run_tool(action='act', entity_id='cover.main_garage', service='open_cover',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='act', entity_id='cover.office_blind', service='open_cover',
                            acting_member={'id': 'k1', 'role': 'kid'})
        self.assertEqual(res['status'], 'success', res)
        res = self.run_tool(action='act', entity_id='cover.main_garage', service='open_cover',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['state_after'], 'open')

    def test_the_admin_chat_counts_as_a_trusted_hand(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='lock', source='admin')
        self.assertEqual(res['status'], 'success', res)

    def test_nobody_in_particular_is_not_a_trusted_hand(self):
        res = self.run_tool(action='act', entity_id='lock.front_door', service='lock')
        self.assertEqual(res['status'], 'refused')
        self.assertEqual(self.calls, [])

    def test_the_wall_panel_may_switch_a_light_but_never_unlock_the_door(self):
        from services import access
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                            acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'success', res)
        res = self.run_tool(action='act', entity_id='lock.front_door', service='unlock',
                            acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'refused', 'the wall panel reads as an adult but is a room anyone can walk into')
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])
        res = self.run_tool(action='act', entity_id='cover.main_garage', service='open_cover',
                            acting_member=access.HOUSE_PARENT, source='panel')
        self.assertEqual(res['status'], 'refused')

    def test_an_unknown_voice_may_still_switch_a_light(self):
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='turn_off',
                            voice_context=voice('unknown'), source='voice')
        self.assertEqual(res['status'], 'success', res)

    def test_a_service_the_entity_does_not_have_is_an_error_and_calls_nothing(self):
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='unlock',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'error')
        self.assertEqual(self.calls, [])
        res = self.run_tool(action='act', entity_id='light.office_lamp', service='lock.turn_off',
                            acting_member={'id': 'p1', 'role': 'parent'})
        self.assertEqual(res['status'], 'error', 'a service from another domain was accepted')
        self.assertEqual(self.calls, [])

    # --- degradation --------------------------------------------------------
    def test_no_home_assistant_means_a_plain_error_for_every_action(self):
        setattr(ha_api, 'mode', lambda: 'unconfigured')
        for action in ('find', 'read', 'history', 'act'):
            res = self.run_tool(action=action, query='office lamp', entity_id='light.office_lamp', service='turn_off',
                                acting_member={'id': 'p1', 'role': 'parent'})
            self.assertEqual(res['status'], 'error', action)
            self.assertIn('not connected', res['message'])
        self.assertEqual(self.calls, [])

    def test_an_unknown_action_is_an_error(self):
        self.assertEqual(self.run_tool(action='dance', query='x')['status'], 'error')

    # --- wiring -------------------------------------------------------------
    def test_the_tool_is_declared_once_and_runs_through_execute_tool(self):
        names = [t['name'] for t in agent_tools_v2.get_available_tools()]
        self.assertEqual(names.count('house'), 1)
        res = agent_tools_v2.execute_tool('house', {'action': 'read', 'entity_id': 'light.office_lamp',
                                                    'acting_member': {'id': 'x', 'role': 'parent'}})
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['entity']['brightness_pct'], 50)

    def test_voice_dispatch_reaches_the_tool_and_records_the_act(self):
        from services import voice_tools
        self.assertIn('house', voice_tools.TOOLS)
        recorded = []
        self.orig[(voice_tools, 'record_action')] = voice_tools.record_action
        voice_tools.record_action = lambda ctx, name, principal=None, details=None, provenance=None: recorded.append(name)
        ctx = voice('unknown')
        ctx.ha_instance_id, ctx.service_revision = '', ''
        ctx.provenance = lambda: {}
        res = voice_tools.dispatch('house', {'action': 'act', 'entity_id': 'light.office_lamp', 'service': 'turn_off'}, ctx)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(recorded, ['house'])
        res = voice_tools.dispatch('house', {'action': 'read', 'entity_id': 'light.office_lamp'}, ctx)
        self.assertEqual(res['status'], 'success', res)


if __name__ == '__main__':
    unittest.main()
