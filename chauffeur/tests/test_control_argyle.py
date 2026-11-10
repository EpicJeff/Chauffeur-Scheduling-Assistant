"""Argyle obeys the household's control grid (Task 5 of
docs/superpowers/plans/2026-11-09-ha-control-permissions.md).

The house tool (act and TV app launch), the music tool and Argyle by voice
ask control_rules before Home Assistant is called, so Argyle gives the same
answer as a tile for the same person and the same device. A refusal says what
would make it work: `needs` is 'identify' (find out who), 'pin' (a recognised
voice says its PIN) or None (the household said no). On the wall panel an
'identify' refusal holds the action; the panel's PIN step runs it once, as
the person who entered the PIN, on that panel only. A voice is never held:
the person re-asks.

Carried Task 3 rulings: who_from_agent takes `proven`, and /api/chat passes
proven=False for a panel-minted or house-session token; hold() records the
panel's device id and take_held() refuses another device; held args are
whitelisted to the tool's own parameters.

Stubbed ha_api (and the LLM call where a test needs the real router); the
real services.house, services.music_tool, agent_tools_v2, voice_tools and the
FastAPI app with auth enforcement on.

Run from chauffeur/:  python tests/test_control_argyle.py
"""
import copy
import types
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import (access, agent_router, agent_tools_v2, control_rules as cr,
                      control_scripts as cs, ha_api, house, music_search, storage, voice_tools)

PIN_SENTENCE = 'Say your PIN first, then ask again.'
WHO_SENTENCE = 'Who is this? Say your name and PIN, then ask again.'

TRACK = {'uri': 'spotify://track/1', 'name': 'Hotel California', 'media_type': 'track',
         'artists': [{'name': 'Eagles'}], 'album': None, 'image': None, 'favorite': False,
         'in_library': False, 'providers': ['spotify']}


def _state(eid, st='off', **attrs):
    return {'entity_id': eid, 'state': st, 'last_changed': '2026-11-09T08:00:00+00:00',
            'attributes': attrs}


def _states():
    return [
        _state('light.office_lamp', 'on', friendly_name='Office Lamp'),
        _state('lock.front', 'locked', friendly_name='Front Door'),
        _state('cover.office_shade', 'closed', friendly_name='Office Shade', device_class='shade'),
        _state('valve.sprinkler', 'closed', friendly_name='Sprinkler'),
        _state('script.goodnight', 'off', friendly_name='Goodnight'),
        _state('media_player.kitchen_speaker', 'playing', friendly_name='Kitchen Speaker',
               mass_player_type='player', media_title='Take It Easy', media_artist='Eagles',
               volume_level=0.3),
        _state('remote.office_tv', 'on', friendly_name='Office TV', current_activity='Home',
               activity_list=['Netflix', 'YouTube']),
        _state('media_player.office_tv_2', 'on', friendly_name='Office TV', device_class='tv'),
    ]


REGISTRY = [
    {'entity_id': 'remote.office_tv', 'name': None, 'original_name': 'Office TV', 'aliases': [],
     'area_id': 'office', 'device_id': 'dev_office_tv', 'hidden_by': None, 'disabled_by': None,
     'platform': 'androidtv_remote'},
    {'entity_id': 'media_player.office_tv_2', 'name': None, 'original_name': 'Office TV', 'aliases': [],
     'area_id': 'office', 'device_id': 'dev_office_tv', 'hidden_by': None, 'disabled_by': None,
     'platform': 'androidtv_remote'},
]
AREAS = [
    {'id': 'office', 'name': 'Office', 'entities': ['light.office_lamp', 'cover.office_shade',
                                                    'remote.office_tv', 'media_player.office_tv_2']},
    {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['media_player.kitchen_speaker']},
    {'id': 'hall', 'name': 'Hall', 'entities': ['lock.front']},
]
EXPOSED = {'light.office_lamp': True, 'lock.front': True, 'cover.office_shade': True,
           'valve.sprinkler': True, 'script.goodnight': True, 'remote.office_tv': True,
           'media_player.office_tv_2': True, 'media_player.kitchen_speaker': True}
SERVICES = {'light': {'turn_on', 'turn_off', 'toggle'}, 'lock': {'lock', 'unlock'},
            'cover': {'open_cover', 'close_cover'}, 'valve': {'open_valve', 'close_valve'},
            'script': {'turn_on', 'turn_off'}, 'remote': {'turn_on', 'turn_off'},
            'media_player': {'media_pause', 'media_play', 'volume_set', 'turn_off'}}
AFTER = {('light', 'turn_on'): 'on', ('light', 'turn_off'): 'off', ('lock', 'unlock'): 'unlocked',
         ('lock', 'lock'): 'locked', ('cover', 'open_cover'): 'open', ('valve', 'open_valve'): 'open',
         ('script', 'turn_on'): 'on'}


def _member(mid, role, pin=None):
    if not storage.get_member(mid):
        storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active'})
        if pin:
            storage.set_member_pin(mid, pin)
    return storage.get_member(mid)


def voice(level='unknown', member_id=None, recognized=False, paired=True):
    """A VoiceContext as the voice pipeline hands it to dispatch."""
    def member():
        return storage.get_member(member_id) if member_id and level in ('named', 'verified') else None
    return types.SimpleNamespace(
        level=level, member_id=member_id, recognized_this_turn=recognized, paired=paired,
        ha_instance_id='', service_revision='', satellite_id='assist_satellite.kitchen',
        request_id='r1', generation='g1', member=member,
        verified_member=lambda: member() if level == 'verified' else None,
        provenance=lambda: {})


class ArgyleObeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _member('mum', 'parent', pin='4321')
        cls.panel = storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')
        cls.panel2 = storage.enrol_device_token('panel-2', 'Hall panel', by_member='mum')
        cls.panel_id = storage.get_device_by_token(cls.panel)['device_id']
        cls.panel2_id = storage.get_device_by_token(cls.panel2)['device_id']

    def setUp(self):
        # test_house_tool's own setUp/tearDown truncates the members table
        # (test_private_location_unchanged runs it), so members are re-made here.
        self.mum = _member('mum', 'parent', pin='4321')
        self.kid = _member('kid', 'child', pin='1111')
        self.calls = []
        self.states = _states()
        self.extra = {}
        self.orig = {}
        tests = self

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)

        def call_service(domain, service, data=None, return_response=False, timeout=None, **kw):
            tests.calls.append((domain, service, dict(data or {})))
            eid = (data or {}).get('entity_id')
            for s in tests.states:
                if s['entity_id'] == eid:
                    if (domain, service) in AFTER:
                        s['state'] = AFTER[(domain, service)]
                    if (domain, service) == ('remote', 'turn_on'):
                        s['attributes']['current_activity'] = 'Netflix'
            return []

        def ws(command, timeout=8, **fields):
            if command == 'search/related':
                return {'entity': ['lock.front']} if fields.get('item_id') == 'script.goodnight' else {}
            if command == 'script/config' and fields.get('entity_id') == 'script.goodnight':
                return {'config': {'sequence': [
                    {'action': 'light.turn_off', 'target': {'entity_id': 'light.office_lamp'}},
                    {'action': 'lock.lock', 'target': {'entity_id': 'lock.front'}}]}}
            return None

        def search(q, media_types=None, limit=20, library_only=False, provider=None):
            return {'source': 'ma', 'query': q, 'groups': [{'type': 'track', 'items': [dict(TRACK)]}],
                    'providers': [], 'total': 1}

        stub(ha_api, 'mode', lambda: 'supervisor')
        stub(ha_api, 'is_available', lambda: True)
        stub(ha_api, 'get_states', lambda ttl=5: tests.states)
        stub(ha_api, 'get_state', lambda eid: next((s for s in tests.states if s['entity_id'] == eid), None))
        stub(ha_api, 'get_entity_registry', lambda ttl=300: copy.deepcopy(REGISTRY))
        stub(ha_api, 'get_device_registry', lambda ttl=300: [{'id': 'dev_office_tv', 'name': 'Office TV',
                                                               'area_id': 'office'}])
        stub(ha_api, 'get_area_map', lambda ttl=60: copy.deepcopy(AREAS))
        stub(ha_api, 'get_exposed', lambda ttl=60: dict(EXPOSED))
        stub(ha_api, 'has_service', lambda d, s: s in SERVICES.get(d, set()))
        stub(ha_api, 'call_service', call_service)
        stub(ha_api, 'ws_command', ws)
        stub(ha_api, 'get_script_config', lambda object_id: None)
        stub(music_search, 'search', search)
        stub(house, '_settle', lambda: None)
        stub(voice_tools, 'record_action', lambda *a, **kw: None)
        cs.clear_cache()
        self.base_settings = dict(storage.get_settings() or {})
        for key in ('ha_control', 'panel_allow_unsafe_controls', 'house_control_unexposed'):
            self.base_settings.pop(key, None)
        self.settings_patch = patch.object(storage, 'get_settings', side_effect=lambda: {
            **self.base_settings, 'auth_enforce': True, **self.extra})
        self.settings_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.settings_patch.stop()
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)
        cs.clear_cache()

    # --- helpers -----------------------------------------------------------

    def grid(self, **changes):
        """The default grid with cells changed: grid(people_child_media='no')."""
        rules = cr.default_rules({})
        for key, value in changes.items():
            section, row, kind = key.split('_', 2)
            rules[section][row][kind] = value
        self.extra['ha_control'] = rules
        return rules

    def house(self, **kw):
        return agent_tools_v2.house(**kw)

    def device_calls(self, domain=None):
        return [c for c in self.calls if domain is None or c[0] == domain]

    def say(self, ctx, **args):
        return voice_tools.dispatch('house', args, ctx)

    def chat(self, headers, call, body=None, query=''):
        """POST /api/chat with the real router; the model asks for one tool call."""
        def fake_llm(prompt, tools, system_prompt):
            if 'Tool Result' in prompt:
                return {'message': '', 'tool_calls': []}
            return {'message': '', 'tool_calls': [call]}
        payload = {'message': 'please', **(body or {})}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=fake_llm), \
                patch('services.llm.auto_name_conversation', lambda *a, **kw: None):
            return self.client.post('/api/chat' + query, json=payload, headers=headers)

    def panel_chat(self, call, device=None):
        return self.chat({'X-Device-Token': device or self.panel}, call,
                         body={'context': {'search': '?panel=true'}})

    def grant(self, device=None, member_id='mum', pin='4321'):
        r = self.client.post('/api/ha/control/grant', json={'member_id': member_id, 'pin': pin},
                             headers={'X-Device-Token': device or self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['grant']

    UNLOCK = {'name': 'house', 'arguments': {'action': 'act', 'entity_id': 'lock.front', 'service': 'unlock'}}

    # --- carried Task 3 rulings ----------------------------------------------

    def test_who_from_agent_takes_proven(self):
        signed_in = cr.who_from_agent(self.mum, None, 'pwa')
        self.assertEqual((signed_in.role, signed_in.member_id, signed_in.proven), ('parent', 'mum', True))
        unproven = cr.who_from_agent(self.mum, None, 'pwa', proven=False)
        self.assertEqual((unproven.role, unproven.member_id, unproven.place, unproven.proven),
                         ('parent', 'mum', None, False))
        # proven never upgrades a place.
        self.assertEqual(cr.who_from_agent(access.HOUSE, None, 'panel', proven=True).place, 'panel')

    def test_chat_with_panel_minted_token_is_not_proof(self):
        # The avatar/critter PIN step on the wall mints an ordinary member token;
        # carried to /api/chat as a phone would send it, it must not unlock.
        r = self.client.post('/api/members/mum/auth', json={'pin': '4321'},
                             headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        panel_minted = r.json()['token']
        house_session = storage.create_member_token('mum', house_session=True)
        for token in (panel_minted, house_session):
            r = self.chat({'X-Member-Token': token}, self.UNLOCK, body={'source': 'pwa'})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.device_calls('lock'), [], f'unlocked with a token that proves nobody: {r.text}')
        personal = storage.create_member_token('mum', proof='password', minted_on='personal')
        r = self.chat({'X-Member-Token': personal}, self.UNLOCK, body={'source': 'pwa'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.device_calls('lock'), [('lock', 'unlock', {'entity_id': 'lock.front'})])

    def test_held_bound_to_device(self):
        args = {'action': 'act', 'entity_id': 'lock.front', 'service': 'unlock'}
        held = cr.hold('house', args, self.panel_id)
        self.assertIsNone(cr.take_held(held, self.panel2_id), 'another panel took the held action')
        mine = cr.hold('house', args, self.panel_id)
        row = cr.take_held(mine, self.panel_id)
        self.assertEqual(row['tool'], 'house')
        self.assertEqual(row['args'], args)
        self.assertIsNone(cr.take_held(mine, self.panel_id), 'a held action runs once')

    def test_held_args_whitelisted(self):
        held = cr.hold('house', {'action': 'act', 'entity_id': 'light.office_lamp', 'service': 'turn_off',
                                 'bogus': 1}, self.panel_id)
        row = cr.take_held(held, self.panel_id)
        self.assertNotIn('bogus', row['args'])
        self.assertEqual(row['args']['entity_id'], 'light.office_lamp')
        music = cr.hold('music', {'action': 'pause', 'player': 'Kitchen Speaker', 'app': 'netflix'},
                        self.panel_id)
        self.assertNotIn('app', cr.take_held(music, self.panel_id)['args'], 'app is a house parameter, not music')
        # Through the route: an unknown key is dropped, never a TypeError/500.
        held = cr.hold('house', {'action': 'act', 'entity_id': 'light.office_lamp', 'service': 'turn_off',
                                 'bogus': 1}, self.panel_id)
        r = self.client.post(f'/api/ha/control/held/{held}',
                             headers={'X-Device-Token': self.panel, 'X-Control-Grant': self.grant()})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['status'], 'success', r.text)
        self.assertEqual(self.device_calls('light'), [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])

    # --- the brief's tests ---------------------------------------------------

    def test_private_location_unchanged(self):
        import test_house_tool
        name = 'test_a_child_who_keeps_location_private_is_hidden_from_everyone_but_a_parent'
        self.assertTrue(hasattr(test_house_tool.HouseToolTests, name),
                        'the private child-location test in test_house_tool.py was renamed or removed')
        self.settings_patch.stop()
        try:
            result = unittest.TestResult()
            test_house_tool.HouseToolTests(name).run(result)
        finally:
            self.settings_patch.start()
        self.assertEqual((result.errors, result.failures), ([], []))
        self.assertEqual(result.testsRun, 1)

    def test_panel_chat_blinds_kept(self):
        for eid, service in (('cover.office_shade', 'open_cover'), ('valve.sprinkler', 'open_valve')):
            res = self.house(action='act', entity_id=eid, service=service,
                             acting_member=access.HOUSE, source='panel')
            self.assertEqual(res['status'], 'success', (eid, res))
        self.assertEqual([c[:2] for c in self.calls], [('cover', 'open_cover'), ('valve', 'open_valve')])
        # The household's grid decides, not a fixed list in the tool.
        self.grid(places_panel_blinds='no', places_panel_other='no')
        for eid, service in (('cover.office_shade', 'close_cover'), ('valve.sprinkler', 'close_valve')):
            res = self.house(action='act', entity_id=eid, service=service,
                             acting_member=access.HOUSE, source='panel')
            self.assertEqual(res['status'], 'refused', (eid, res))
            self.assertIsNone(res.get('needs', 'missing'), res)
        self.assertEqual(len(self.calls), 2)

    def test_panel_chat_lock_defaults(self):
        res = self.house(action='act', entity_id='lock.front', service='unlock',
                         acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'refused', res)
        self.assertIn('needs', res, 'a refusal says what would make it work')
        self.assertIsNone(res['needs'])
        self.assertNotIn('control_held', res)
        self.extra['panel_allow_unsafe_controls'] = True
        res = self.house(action='act', entity_id='lock.front', service='unlock',
                         acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'refused', res)
        self.assertEqual(res.get('needs'), 'identify', res)
        held = res.get('control_held') or {}
        self.assertTrue(isinstance(held.get('id'), str) and held['id'], res)
        self.assertEqual(held.get('message'), "Who's asking?")
        self.assertEqual(self.device_calls('lock'), [])

    def test_held_unlock_runs_as_parent(self):
        # The whole panel round trip: typed Argyle asks who, the PIN step runs it
        # once as the parent, and the next unlock asks again.
        self.extra['panel_allow_unsafe_controls'] = True
        r = self.panel_chat(self.UNLOCK)
        self.assertEqual(r.status_code, 200, r.text)
        held = (r.json().get('control_held') or {}).get('id')
        self.assertTrue(held, r.text)
        self.assertEqual(self.device_calls('lock'), [])
        r = self.client.post(f'/api/ha/control/held/{held}',
                             headers={'X-Device-Token': self.panel, 'X-Control-Grant': self.grant()})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['status'], 'success', r.text)
        self.assertEqual(self.device_calls('lock'), [('lock', 'unlock', {'entity_id': 'lock.front'})])
        r = self.panel_chat(self.UNLOCK)
        self.assertTrue((r.json().get('control_held') or {}).get('id'), 'the next unlock must ask again')
        self.assertEqual(len(self.device_calls('lock')), 1)

    def test_held_refused_on_another_panel(self):
        self.extra['panel_allow_unsafe_controls'] = True
        r = self.panel_chat(self.UNLOCK)
        held = (r.json().get('control_held') or {}).get('id')
        self.assertTrue(held, r.text)
        r = self.client.post(f'/api/ha/control/held/{held}',
                             headers={'X-Device-Token': self.panel2, 'X-Control-Grant': self.grant(self.panel2)})
        self.assertIn(r.status_code, (403, 404), r.text)
        self.assertEqual(self.device_calls('lock'), [])

    def test_voice_recognised_parent(self):
        ctx = voice('named', 'mum', recognized=True)
        res = self.say(ctx, action='act', entity_id='light.office_lamp', service='turn_off')
        self.assertEqual(res['status'], 'success', res)
        res = self.say(ctx, action='act', entity_id='lock.front', service='unlock')
        self.assertEqual(res['status'], 'refused', res)
        self.assertEqual(res.get('needs'), 'pin', res)
        self.assertEqual(res['message'], PIN_SENTENCE)
        self.assertNotIn('control_held', res, 'a voice is never held; the person re-asks')
        self.assertEqual(self.device_calls('lock'), [])

    def test_voice_verified_parent_lock(self):
        ctx = voice('verified', 'mum', recognized=True)
        res = self.say(ctx, action='act', entity_id='lock.front', service='unlock')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.device_calls('lock'), [('lock', 'unlock', {'entity_id': 'lock.front'})])
        # A PIN proves the person; the household's grid still decides what they may do.
        self.grid(people_parent_locks='no')
        res = self.say(ctx, action='act', entity_id='lock.front', service='lock')
        self.assertEqual(res['status'], 'refused', res)
        self.assertIsNone(res.get('needs', 'missing'), res)
        self.assertEqual(len(self.device_calls('lock')), 1)

    def test_voice_inherited_yes_cannot_unlock(self):
        # A short reply ("yes") inherits the recognised speaker: still only `named`.
        ctx = voice('named', 'mum', recognized=True)
        self.say(ctx, action='read', entity_id='lock.front')
        res = self.say(ctx, action='act', entity_id='lock.front', service='unlock')
        self.assertEqual(res['status'], 'refused', res)
        self.assertEqual(res.get('needs'), 'pin', res)
        self.assertEqual(res['message'], PIN_SENTENCE)
        self.assertEqual(self.device_calls('lock'), [])

    def test_voice_claimed_name(self):
        # "It's Mum" with no fingerprint is the Unknown voice card.
        ctx = voice('named', 'mum', recognized=False)
        res = self.say(ctx, action='act', entity_id='lock.front', service='unlock')
        self.assertEqual(res['status'], 'refused', res)
        self.assertEqual(res.get('needs'), 'identify', res)
        self.assertEqual(res['message'], WHO_SENTENCE)
        self.assertNotIn('control_held', res)
        res = self.say(ctx, action='act', entity_id='light.office_lamp', service='turn_off')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.device_calls('lock'), [])

    def test_child_signed_in(self):
        res = self.house(action='act', entity_id='lock.front', service='unlock',
                         acting_member=self.kid, source='pwa')
        self.assertEqual(res['status'], 'refused', res)
        self.assertIn('needs', res, 'a refusal says what would make it work')
        self.assertIsNone(res['needs'], 'a child is refused outright, never asked for a PIN')
        self.assertNotIn('control_held', res)
        res = self.house(action='act', entity_id='light.office_lamp', service='turn_off',
                         acting_member=self.kid, source='pwa')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('light', 'turn_off', {'entity_id': 'light.office_lamp'})])

    def test_script_goodnight(self):
        res = self.house(action='act', entity_id='script.goodnight', service='turn_on',
                         acting_member=self.kid, source='pwa')
        self.assertEqual(res['status'], 'refused', res)
        self.assertIsNone(res.get('needs', 'missing'), res)
        self.assertEqual(self.calls, [], 'a script that locks the door is a lock action')
        res = self.house(action='act', entity_id='script.goodnight', service='turn_on',
                         acting_member=self.mum, source='pwa')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('script', 'turn_on', {'entity_id': 'script.goodnight'})])

    def test_music_tool_guard(self):
        self.grid(people_child_media='no')
        for kw in ({'action': 'play', 'query': 'Hotel California'}, {'action': 'pause'},
                   {'action': 'volume', 'level': 40}):
            res = agent_tools_v2.music(player='Kitchen Speaker', acting_member=self.kid, source='pwa', **kw)
            self.assertEqual(res['status'], 'refused', (kw, res))
            self.assertIsNone(res.get('needs', 'missing'), res)
        self.assertEqual(self.calls, [])
        res = agent_tools_v2.music(action='now', player='Kitchen Speaker', acting_member=self.kid, source='pwa')
        self.assertEqual(res['status'], 'success', 'reading what is playing stays open')
        res = agent_tools_v2.music(action='play', query='Hotel California', player='Kitchen Speaker',
                                   acting_member=self.mum, source='pwa')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls, [('music_assistant', 'play_media', {
            'entity_id': 'media_player.kitchen_speaker', 'media_id': 'spotify://track/1', 'media_type': 'track'})])

    def test_open_app_guard(self):
        self.grid(places_panel_media='no')
        res = self.house(action='app', entity_id='remote.office_tv', app='netflix',
                         acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'refused', res)
        self.assertIsNone(res.get('needs', 'missing'), res)
        self.assertEqual(self.device_calls('remote'), [])
        self.extra.pop('ha_control')
        res = self.house(action='app', entity_id='remote.office_tv', app='netflix',
                         acting_member=access.HOUSE, source='panel')
        self.assertEqual(res['status'], 'success', res)
        self.assertTrue(self.device_calls('remote'))

    def test_chat_reply_carries_held(self):
        held = {'id': 'held-123', 'message': "Who's asking?"}
        seen = []

        def router(*a, **kw):
            seen.append(kw)
            return {'status': 'refused', 'message': "Who's asking?", 'control_held': held}
        with patch.object(agent_router, 'process_agent_request', side_effect=router), \
                patch('services.llm.auto_name_conversation', lambda *a, **kw: None):
            r = self.client.post('/api/chat', json={'message': 'unlock the front door',
                                                    'context': {'search': '?panel=true'}},
                                 headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(seen[-1]['source'], 'panel')
        self.assertEqual((r.json().get('control_held') or {}).get('id'), 'held-123', r.text)
        with patch.object(agent_router, 'process_agent_request',
                          side_effect=lambda *a, **kw: {'status': 'success', 'message': 'ok'}), \
                patch('services.llm.auto_name_conversation', lambda *a, **kw: None):
            r = self.client.post('/api/chat', json={'message': 'hello', 'context': {'search': '?panel=true'}},
                                 headers={'X-Device-Token': self.panel})
        self.assertNotIn('control_held', r.json(), 'absent when nothing is held')

    def test_router_surfaces_control_held(self):
        self.extra['panel_allow_unsafe_controls'] = True

        def fake_llm(prompt, tools, system_prompt):
            if 'Tool Result' in prompt:
                return {'message': '', 'tool_calls': []}
            return {'message': '', 'tool_calls': [self.UNLOCK]}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=fake_llm):
            res = agent_router.process_agent_request('unlock the front door', source='panel',
                                                     acting_member=access.HOUSE)
        self.assertTrue((res.get('control_held') or {}).get('id'), res)
        self.assertEqual(self.device_calls('lock'), [])


if __name__ == '__main__':
    unittest.main()
