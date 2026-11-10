"""Tap to talk on the wall panel (spec 2026-11-10, Task 6).

A panel with a room whose satellite Chauffeur can find shows a plain mic
button (the user, 2026-11-10: no speaker name, "it adds nothing"). A tap asks
Home Assistant to start a conversation on that satellite
(assist_satellite.start_conversation, preannounce on): the satellite chimes and
listens, and from then on it is an ordinary satellite conversation. The panel
adds no identity of its own.

Server, services/panel_talk.py + main.py:
  GET  /api/panel/talk -> {available, state}; available false for a caller that
       is not a paired panel, a panel without a room, a room without a usable
       satellite, or no HA; state is the satellite entity's HA state.
  POST /api/panel/talk -> 200 {ok: true} after the HA call; 403 for a caller that
       is not a panel; 409 {message} when there is no satellite; 429 when this
       panel started one under 5 s ago; 502 {message: 'The <Area> speaker is
       offline.'} when HA's call fails.

Page, templates/components/control_center.html, window.chfPanelTalk:
  check() -> Promise<bool>: GET chfBase + 'api/panel/talk' with X-Device-Token
       (localStorage chauffeur_device_token); shows #chat-talk-btn (removes
       class 'hidden') when available, hides it (adds 'hidden') otherwise.
  The user, 2026-11-10: "I don't want the one-tap microphone next to the orb.
  The orb should be the way into Argyle and then there is a mic button on the
  chat box if you want to have a voice conversation." No second orb.
  start() -> Promise: POST the same URL; on a refusal showGlobalAlert(message);
       on success state 'listening', then GET once a second (at most 120 s) and
       follow the satellite: listening / processing / responding, back to
       'idle' when HA says idle. window.chfPanelTalk.state holds it.
  nav.html keeps the panel's X-Device-Token on api/panel/talk during a house
  session (chfIsControlUrl), like the HA control URLs.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_panel_talk.py
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_panel_talk_')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from fastapi.testclient import TestClient
from services import storage, ha_api
import test_control_grant_js as js

KITCHEN_SAT = 'assist_satellite.kitchen_a'
AREAS = [{'id': 'kitchen', 'name': 'Kitchen', 'entities': [KITCHEN_SAT, 'media_player.kitchen_sonos']},
         {'id': 'hall', 'name': 'Hall', 'entities': ['media_player.hall']}]


class PanelTalkServer(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.trusted_devices_table,
                      storage.app_state_table):
            table.truncate()
        storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent'})
        self.member = storage.create_member_token('mum', proof='password')
        self.panel = storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')
        self.panel2 = storage.enrol_device_token('panel-2', 'Hall panel', by_member='mum')
        storage.set_device_room('panel-1', 'kitchen', None)
        storage.set_device_room('panel-2', 'hall', None)
        self.states = {KITCHEN_SAT: 'idle', 'media_player.kitchen_sonos': 'idle', 'media_player.hall': 'idle'}
        self.ha = True
        self.calls = []
        self.call_result = {}
        base = dict(storage.get_settings() or {})
        p = patch.object(storage, 'get_settings', side_effect=lambda: {**base, 'auth_enforce': True})
        p.start(); self.addCleanup(p.stop)

        def states(ttl=5):
            return [{'entity_id': e, 'state': s, 'attributes': {}} for e, s in self.states.items()] if self.ha else []

        def call_service(domain, service, data=None, return_response=False, timeout=None, **kw):
            self.calls.append((domain, service, dict(data or {})))
            return self.call_result
        for name, value in (('is_available', lambda: self.ha),
                            ('get_area_map', lambda ttl=60: AREAS if self.ha else []),
                            ('get_states', states),
                            ('get_state', lambda eid: ({'entity_id': eid, 'state': self.states[eid], 'attributes': {}}
                                                       if self.ha and eid in self.states else None)),
                            ('call_service', call_service)):
            p = patch.object(ha_api, name, side_effect=value)
            p.start(); self.addCleanup(p.stop)
        from services import panel_talk
        panel_talk._last_start.clear()
        import main
        self.client = TestClient(main.app)

    def get(self, token=None, header='X-Device-Token'):
        return self.client.get('/api/panel/talk', headers={header: token or self.panel})

    def post(self, token=None, header='X-Device-Token'):
        return self.client.post('/api/panel/talk', headers={header: token or self.panel})

    # --- availability --------------------------------------------------------
    def test_get_available_with_state(self):
        self.states[KITCHEN_SAT] = 'listening'
        r = self.get()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {'available': True, 'state': 'listening'})

    def test_get_unavailable_no_satellite_in_room(self):
        self.assertEqual(self.get(self.panel2).json()['available'], False)

    def test_get_unavailable_no_room(self):
        storage.set_device_room('panel-1', None, None)
        self.assertEqual(self.get().json()['available'], False)

    def test_get_unavailable_non_panel(self):
        r = self.get(self.member, header='X-Member-Token')
        self.assertIn(r.status_code, (200, 401, 403))
        if r.status_code == 200:
            self.assertEqual(r.json()['available'], False)

    def test_get_no_ha(self):
        self.ha = False
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['available'], False)

    # --- starting a conversation -----------------------------------------------
    def test_post_calls_start_conversation(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(len(self.calls), 1)
        domain, service, data = self.calls[0]
        self.assertEqual((domain, service), ('assist_satellite', 'start_conversation'))
        self.assertEqual(data['entity_id'], KITCHEN_SAT)
        self.assertIs(data['preannounce'], True)
        self.assertLessEqual(set(data), {'entity_id', 'preannounce', 'start_message'})

    def test_post_non_panel_403(self):
        r = self.post(self.member, header='X-Member-Token')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_post_no_satellite_409(self):
        r = self.post(self.panel2)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json().get('message'))
        self.assertEqual(self.calls, [])

    def test_post_rate_limited_429(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 429)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.post(self.panel2).status_code, 409, 'the limit is per panel')

    def test_post_after_five_seconds_ok(self):
        from services import panel_talk
        self.assertEqual(self.post().status_code, 200)
        for key in list(panel_talk._last_start):
            panel_talk._last_start[key] -= 6
        self.assertEqual(self.post().status_code, 200)

    def test_post_offline_502(self):
        self.call_result = None             # ha_api.call_service returns None on failure
        r = self.post()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['message'], 'The Kitchen speaker is offline.')

    def test_post_no_ha_409(self):
        self.ha = False
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.calls, [])


TALK_SCENARIO_ROUTES = 'api/panel/talk'


class PanelTalkPage(unittest.TestCase):
    def run_page(self, scenario, routes, **opts):
        out = js.run_node(js.CC_HARNESS, {
            'base': js.BASE, 'blocks': js._cc_blocks(), 'scenario': scenario,
            'routes': routes, 'choices': [], 'pins': [], **opts})
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['forbidden'], [], 'alert/confirm/prompt are banned')
        return out

    def talk_calls(self, out):
        return [c for c in out['calls'] if 'api/panel/talk' in c['url']]

    def test_button_hidden_when_unavailable(self):
        out = self.run_page("""
            out.ok = await window.chfPanelTalk.check();
            out.bar = byId['chat-talk-btn'].classList.contains('hidden');
        """, [[TALK_SCENARIO_ROUTES, [js.ok({'available': False, 'state': None})]]])
        self.assertIs(out['ok'], False)
        self.assertTrue(out['bar'])

    def test_button_shown_when_available(self):
        out = self.run_page("""
            out.ok = await window.chfPanelTalk.check();
            out.bar = byId['chat-talk-btn'].classList.contains('hidden');
        """, [[TALK_SCENARIO_ROUTES, [js.ok({'available': True, 'state': 'idle'})]]])
        self.assertIs(out['ok'], True)
        self.assertFalse(out['bar'])
        call = self.talk_calls(out)[0]
        self.assertEqual(call['url'], js.BASE + 'api/panel/talk', 'never a root-relative URL under ingress')
        self.assertEqual(call['headers'].get('x-device-token'), 'dev-tok')

    def test_tap_posts_and_follows_the_satellite(self):
        out = self.run_page("""
            await window.chfPanelTalk.start();
            out.after_start = window.chfPanelTalk.state;
            await advance(1000); out.s1 = window.chfPanelTalk.state;
            await advance(1000); out.s2 = window.chfPanelTalk.state;
            await advance(1000); out.s3 = window.chfPanelTalk.state;
        """, [[TALK_SCENARIO_ROUTES, [js.ok({'ok': True}),
                                      js.ok({'available': True, 'state': 'processing'}),
                                      js.ok({'available': True, 'state': 'responding'}),
                                      js.ok({'available': True, 'state': 'idle'})]]], fakeTimers=True)
        calls = self.talk_calls(out)
        self.assertEqual(calls[0]['method'], 'POST')
        self.assertEqual(calls[0]['url'], js.BASE + 'api/panel/talk')
        self.assertEqual(calls[0]['headers'].get('x-device-token'), 'dev-tok')
        self.assertEqual(out['after_start'], 'listening')
        self.assertEqual((out['s1'], out['s2'], out['s3']), ('processing', 'responding', 'idle'))
        polls = len(calls)
        self.assertLessEqual(polls, 4, 'polling stops once the satellite is idle')

    def test_polling_stops_after_two_minutes(self):
        out = self.run_page("""
            await window.chfPanelTalk.start();
            await advance(125000);
            out.state = window.chfPanelTalk.state;
        """, [[TALK_SCENARIO_ROUTES, [js.ok({'ok': True}), js.ok({'available': True, 'state': 'listening'})]]],
            fakeTimers=True)
        self.assertLessEqual(len(self.talk_calls(out)), 1 + 121)
        self.assertEqual(out['state'], 'idle')

    def test_error_uses_global_alert(self):
        out = self.run_page("""
            await window.chfPanelTalk.start();
            out.state = window.chfPanelTalk.state;
        """, [[TALK_SCENARIO_ROUTES, [{'status': 502, 'body': {'message': 'The Kitchen speaker is offline.'}}]]])
        self.assertIn('The Kitchen speaker is offline.', out['alerts'])
        self.assertEqual(out['state'], 'idle')

    def test_network_error_uses_global_alert(self):
        out = self.run_page("""
            await window.chfPanelTalk.start();
        """, [[TALK_SCENARIO_ROUTES, [{'throw': True}]]])
        self.assertEqual(len(out['alerts']), 1)

    def test_orb_is_the_only_way_in(self):
        src = (HERE.parent / 'templates' / 'components' / 'control_center.html').read_text(encoding='utf-8')
        self.assertNotIn('panel-talk-orb', src, 'no one-tap mic beside the orb (user, 2026-11-10)')
        self.assertIn('chat-talk-btn', src)

    def test_nav_keeps_device_token_on_panel_talk(self):
        url = js.BASE + 'api/panel/talk'
        out = js.run_node(js.WRAP_HARNESS, {'nav': js._iife(js.NAV, 'attachDeviceToken'), 'gate': None,
                                            'house': True, 'admin': False,
                                            'requests': [{'url': url, 'headers': {}}]})
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['seen'][0]['headers'].get('x-device-token'), 'dev-tok')


if __name__ == '__main__':
    unittest.main(verbosity=2)
