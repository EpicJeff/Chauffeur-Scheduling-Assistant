"""Every HTTP control endpoint obeys the household grid (Task 4 of
docs/superpowers/plans/2026-11-09-ha-control-permissions.md).

Board tiles, hosted HA cards, the climate card, the media and music cards,
and the Sendspin player relay all ask control_rules before Home Assistant is
called. The answer follows the person (by role), the panel (as a place), the
household switch, the per-kind proof checkbox, and the person's own scope.
A refusal is a 403 whose detail says what would make it work.

Stubbed ha_api; the real FastAPI app with auth enforcement on.

Run from chauffeur/:  python tests/test_control_endpoints.py
"""
import asyncio
import copy
import json
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import control_rules as cr, control_scripts as cs, ha_api, home_board, storage


def state(eid, st='off', **attrs):
    return {'entity_id': eid, 'state': st, 'attributes': attrs}


STATES = [
    state('light.a'), state('light.kitchen'),
    state('lock.front', 'locked'),
    state('cover.office_shade', 'closed', device_class='shade'),
    state('cover.garage_door', 'closed', device_class='garage'),
    state('climate.hall', 'heat', temperature=68, target_temp_step=1, min_temp=45, max_temp=95),
    state('climate.range', 'heat_cool', target_temp_low=66, target_temp_high=74, min_temp=45, max_temp=95),
    state('input_number.target', '21'),
    state('media_player.kitchen', 'playing'),
    state('valve.sprinkler', 'closed'),
    state('script.open_garage', friendly_name='Open garage'),
]
AREAS = [{'id': 'kitchen', 'name': 'Kitchen', 'entities': ['light.kitchen', 'lock.front']}]


def _member(mid, role, **extra):
    if not storage.get_member(mid):
        storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active', **extra})
    return storage.get_member(mid)


class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _member('mum', 'parent')
        _member('kid', 'child')
        _member('visitor', 'guest')
        storage.set_member_pin('mum', '4321')
        cls.panel = storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')
        cls.mum = storage.create_member_token('mum', proof='password', minted_on='personal')
        cls.kid = storage.create_member_token('kid', proof='pin', minted_on='personal')
        cls.visitor = storage.create_member_token('visitor', proof='password', minted_on='personal')

    def setUp(self):
        self.calls = []
        self.extra = {}
        self.orig = {n: getattr(ha_api, n) for n in (
            'mode', 'is_available', 'get_states', 'get_state', 'call_service', 'get_area_map',
            'get_entity_registry', 'get_device_registry', 'ws_command', 'get_script_config')}
        ha_api.mode = lambda: 'direct'
        ha_api.is_available = lambda: True
        ha_api.get_states = lambda ttl=5: copy.deepcopy(STATES)
        ha_api.get_state = lambda eid: next((copy.deepcopy(s) for s in STATES if s['entity_id'] == eid), None)
        ha_api.get_area_map = lambda ttl=60: copy.deepcopy(AREAS)
        ha_api.get_entity_registry = lambda ttl=300: []
        ha_api.get_device_registry = lambda ttl=300: []
        ha_api.get_script_config = lambda object_id: None

        def ws(command, timeout=8, **fields):
            if command == 'search/related':
                return {'entity': ['cover.garage_door']} if fields.get('item_id') == 'script.open_garage' else {}
            if command == 'script/config' and fields.get('entity_id') == 'script.open_garage':
                return {'config': {'sequence': [
                    {'action': 'cover.open_cover', 'target': {'entity_id': 'cover.garage_door'}}]}}
            return None
        ha_api.ws_command = ws

        def call(domain, service, data=None, **kw):
            self.calls.append((domain, service, data))
            return []
        ha_api.call_service = call
        cs.clear_cache()
        self.base_settings = dict(storage.get_settings() or {})
        self.base_settings.pop('ha_control', None)
        self.base_settings.pop('panel_allow_unsafe_controls', None)
        self.patch = patch.object(storage, 'get_settings', side_effect=lambda: {
            **self.base_settings, 'auth_enforce': True, **self.extra})
        self.patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.patch.stop()
        for n, fn in self.orig.items():
            setattr(ha_api, n, fn)
        cs.clear_cache()

    # --- helpers -----------------------------------------------------------

    def toggle(self, eid, **headers):
        return self.client.post('/api/ha/toggle', json={'entity_id': eid}, headers=headers)

    def service(self, domain, service, data, **headers):
        return self.client.post('/api/ha/card/service',
                                json={'domain': domain, 'service': service, 'data': data}, headers=headers)

    def grant(self):
        r = self.client.post('/api/ha/control/grant', json={'member_id': 'mum', 'pin': '4321'},
                             headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['grant']

    def refused(self, r, needs=None):
        self.assertEqual(r.status_code, 403, r.text)
        detail = r.json()['detail']
        self.assertEqual(detail['needs'], needs, detail)
        self.assertTrue(detail['message'].strip())
        return detail

    # --- tiles -------------------------------------------------------------

    def test_toggle_panel_lock_switch_off(self):
        self.refused(self.toggle('lock.front', **{'X-Device-Token': self.panel}))
        self.assertEqual(self.calls, [])

    def test_toggle_panel_lock_switch_on(self):
        self.extra = {'panel_allow_unsafe_controls': True}
        self.refused(self.toggle('lock.front', **{'X-Device-Token': self.panel}), needs='identify')
        self.assertEqual(self.calls, [])
        r = self.toggle('lock.front', **{'X-Device-Token': self.panel, 'X-Control-Grant': self.grant()})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.calls), 1)

    def test_toggle_panel_light_and_kept_blinds(self):
        self.assertEqual(self.toggle('light.a', **{'X-Device-Token': self.panel}).status_code, 200)
        self.assertEqual(self.toggle('cover.office_shade', **{'X-Device-Token': self.panel}).status_code, 200)

    def test_toggle_phone_child_lock(self):
        self.extra = {'panel_allow_unsafe_controls': True}
        self.refused(self.toggle('lock.front', **{'X-Member-Token': self.kid}))

    def test_toggle_phone_parent_lock(self):
        r = self.toggle('lock.front', **{'X-Member-Token': self.mum})
        self.assertEqual(r.status_code, 200, r.text)

    def test_disabled_switch(self):
        rules = cr.default_rules({})
        rules['enabled'] = False
        self.extra = {'ha_control': rules}
        detail = self.refused(self.toggle('light.a', **{'X-Member-Token': self.mum}))
        self.assertIn('turned off', detail['message'])

    # --- hosted card service ---------------------------------------------

    def test_card_service_list_with_lock(self):
        self.refused(self.service('light', 'turn_on', {'entity_id': ['light.a', 'lock.front']},
                                  **{'X-Device-Token': self.panel}))
        self.assertEqual(self.calls, [])

    def test_card_service_area_filtered_to_domain(self):
        # The kitchen holds a lock, but turning on the kitchen's LIGHTS is a light action.
        r = self.service('light', 'turn_on', {'area_id': 'kitchen'}, **{'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        self.refused(self.service('lock', 'unlock', {'area_id': 'kitchen'}, **{'X-Device-Token': self.panel}))

    def test_card_service_csv_ids(self):
        self.refused(self.service('light', 'turn_on', {'entity_id': 'light.a, lock.front'},
                                  **{'X-Member-Token': self.kid}))

    def test_named_script_forged_payload(self):
        self.refused(self.service('script', 'open_garage', {'entity_id': 'light.a'},
                                  **{'X-Member-Token': self.kid}))
        self.assertEqual(self.calls, [])

    def test_card_service_never_domains(self):
        for domain, service in (('homeassistant', 'restart'), ('hassio', 'addon_stop'),
                                ('automation', 'turn_off'), ('backup', 'create')):
            r = self.service(domain, service, {}, **{'X-Member-Token': self.mum})
            self.assertEqual(r.status_code, 400, (domain, r.text))
        self.assertEqual(self.calls, [])

    def test_card_service_no_target(self):
        r = self.service('light', 'turn_on', {}, **{'X-Member-Token': self.mum})
        self.assertEqual(r.status_code, 400, r.text)

    def test_card_service_label_target_refused(self):
        r = self.service('light', 'turn_on', {'label_id': 'doors'}, **{'X-Member-Token': self.mum})
        self.assertIn(r.status_code, (400, 403), r.text)
        self.assertEqual(self.calls, [])

    def test_card_service_malformed_ids_fail_closed(self):
        r = self.service('light', 'turn_on', {'entity_id': ['', None]}, **{'X-Member-Token': self.mum})
        self.assertIn(r.status_code, (400, 403), r.text)

    # --- climate and media ------------------------------------------------

    def test_climate_and_media_guarded(self):
        rules = cr.default_rules({})
        rules['people']['child']['climate'] = 'no'
        rules['places']['panel']['media'] = 'no'
        self.extra = {'ha_control': rules}
        r = self.client.post('/api/ha/card/climate', json={'entity_id': 'climate.hall', 'step': 1},
                             headers={'X-Member-Token': self.kid})
        self.refused(r)
        r = self.client.post('/api/ha/media_players/media_player.kitchen/command', json={'command': 'pause'},
                             headers={'X-Device-Token': self.panel})
        self.refused(r)
        r = self.client.post('/api/music/play', json={'entity_id': 'media_player.kitchen', 'media_id': 'x'},
                             headers={'X-Device-Token': self.panel})
        self.refused(r)
        r = self.client.post('/api/music/queue/command',
                             json={'entity_id': 'media_player.kitchen', 'action': 'clear'},
                             headers={'X-Device-Token': self.panel})
        self.refused(r)
        self.assertEqual([c for c in self.calls if c[0] in ('climate', 'media_player', 'music_assistant')], [])

    def test_media_scope_every_lane(self):
        # A guest whose own access has no music, with the grid's guest media Yes.
        storage.update_member('visitor', {'scope': {'overrides': {'music': 'none'}}})
        try:
            r = self.service('media_player', 'media_pause', {'entity_id': 'media_player.kitchen'},
                             **{'X-Member-Token': self.visitor})
            self.assertEqual(r.status_code, 403, r.text)
            r = self.client.post('/api/ha/media_players/media_player.kitchen/command',
                                 json={'command': 'pause'}, headers={'X-Member-Token': self.visitor})
            self.assertEqual(r.status_code, 403, r.text)
            r = self.client.post('/api/music/play', json={'entity_id': 'media_player.kitchen', 'media_id': 'x'},
                                 headers={'X-Member-Token': self.visitor})
            self.assertEqual(r.status_code, 403, r.text)
            self.assertEqual(self.calls, [])
        finally:
            storage.update_member('visitor', {'scope': {'overrides': {'music': 'all'}}})

    def test_toggle_refuses_non_toggle_domains(self):
        # Permission is not capability: a toggle sent to a thermostat turns the heating off.
        for eid in ('climate.hall', 'input_number.target', 'media_player.kitchen'):
            r = self.toggle(eid, **{'X-Member-Token': self.mum})
            self.assertEqual(r.status_code, 400, (eid, r.text))
        self.assertEqual(self.calls, [])

    def test_grant_survives_a_refused_validation(self):
        # The PIN is spent only on a tap that reaches Home Assistant.
        rules = cr.default_rules({})
        rules['places']['panel']['climate'] = 'ask'
        self.extra = {'ha_control': rules}
        g = self.grant()
        headers = {'X-Device-Token': self.panel, 'X-Control-Grant': g}
        r = self.client.post('/api/ha/card/climate', json={'entity_id': 'climate.range', 'step': 1}, headers=headers)
        self.assertEqual(r.status_code, 400, r.text)
        r = self.client.post('/api/ha/card/climate', json={'entity_id': 'climate.hall', 'step': 1}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)

    def test_media_scope_through_a_grant(self):
        _member('visitor2', 'guest', scope={'overrides': {'music': 'none'}})
        storage.set_member_pin('visitor2', '2468')
        rules = cr.default_rules({})
        rules['places']['panel']['media'] = 'ask'
        self.extra = {'ha_control': rules}
        r = self.client.post('/api/ha/control/grant', json={'member_id': 'visitor2', 'pin': '2468'},
                             headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.service('media_player', 'media_pause', {'entity_id': 'media_player.kitchen'},
                         **{'X-Device-Token': self.panel, 'X-Control-Grant': r.json()['grant']})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(self.calls, [])

    def test_no_ha(self):
        ha_api.mode = lambda: 'unconfigured'
        ha_api.is_available = lambda: False
        r = self.toggle('light.a', **{'X-Member-Token': self.mum})
        self.assertIn(r.status_code, (503,), r.text)

    # --- tiles say what a tap will do ------------------------------------

    def test_tile_toggleable(self):
        config = {'entities': ['light.a', 'lock.front', 'cover.office_shade'], 'interactive': True}
        rows = {r['entity_id']: r for r in home_board._tile_ha(None, config=config, settings={})['rows']}
        self.assertTrue(rows['light.a']['toggleable'])
        self.assertFalse(rows['lock.front']['toggleable'])
        self.assertTrue(rows['cover.office_shade']['toggleable'])
        on = {'panel_allow_unsafe_controls': True}
        self.extra = on
        rows = {r['entity_id']: r for r in home_board._tile_ha(None, config=config, settings=on)['rows']}
        self.assertTrue(rows['lock.front']['toggleable'])   # askable: the tap asks who


class Sendspin(unittest.TestCase):
    """The PWA's player relay: controller commands operate shared Music
    Assistant players and are media control; the stream itself is not."""

    @classmethod
    def setUpClass(cls):
        _member('mum', 'parent')
        cls.panel = storage.enrol_device_token('panel-ss', 'Sendspin panel', by_member='mum')

    def setUp(self):
        self.sent = []
        self.extra = {}
        test = self

        class Upstream:
            close_code, close_reason = 1000, ''

            async def send(self, message):
                test.sent.append(message)

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(3600)
                raise StopAsyncIteration

            async def close(self):
                pass

        async def resolve():
            return 'ws://music-assistant/sendspin'

        async def connect(*a, **k):
            return Upstream()
        self.patches = [
            patch.object(main, '_resolve_ma_ws_url', resolve),
            patch('websockets.connect', connect),
            patch.object(storage, 'get_settings', side_effect=lambda: {'auth_enforce': True, **self.extra}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def frames(self, *messages):
        client = TestClient(main.app)
        with client.websocket_connect('/api/sendspin/ws', headers={'X-Device-Token': self.panel}) as ws:
            for m in messages:
                ws.send_text(json.dumps(m))
            ws.send_text(json.dumps({'type': 'client/time', 'payload': {'client_transmitted': 1}}))
            for _ in range(50):
                if any('client/time' in s for s in self.sent):
                    break
                import time
                time.sleep(0.02)

    COMMAND = {'type': 'client/command', 'payload': {'controller': {'command': 'next'}}}
    HELLO = {'type': 'client/hello', 'payload': {'client_id': 'panel'}}

    def test_commands_forwarded_when_allowed(self):
        self.frames(self.HELLO, self.COMMAND)
        self.assertTrue(any('client/command' in s for s in self.sent), self.sent)

    def test_commands_dropped_when_media_refused(self):
        rules = cr.default_rules({})
        rules['places']['panel']['media'] = 'no'
        self.extra = {'ha_control': rules}
        self.frames(self.HELLO, self.COMMAND)
        self.assertTrue(any('client/hello' in s for s in self.sent), self.sent)   # the stream still works
        self.assertFalse(any('client/command' in s for s in self.sent), self.sent)

    def test_commands_dropped_when_switch_off(self):
        rules = cr.default_rules({})
        rules['enabled'] = False
        self.extra = {'ha_control': rules}
        self.frames(self.COMMAND)
        self.assertFalse(any('client/command' in s for s in self.sent), self.sent)

    def test_rules_change_mid_connection(self):
        client = TestClient(main.app)
        nxt = {'type': 'client/command', 'payload': {'controller': {'command': 'next'}}}
        prev = {'type': 'client/command', 'payload': {'controller': {'command': 'previous'}}}
        with client.websocket_connect('/api/sendspin/ws', headers={'X-Device-Token': self.panel}) as ws:
            ws.send_text(json.dumps(nxt))
            ws.send_bytes(b'\x00\x01audio')
            self._wait(lambda: any('next' in str(m) for m in self.sent))
            rules = cr.default_rules({})
            rules['places']['panel']['media'] = 'no'
            self.extra = {'ha_control': rules}
            ws.send_text(json.dumps(prev))
            ws.send_text(json.dumps({'type': 'client/time', 'payload': {}}))
            self._wait(lambda: any('client/time' in str(m) for m in self.sent))
        self.assertTrue(any('next' in str(m) for m in self.sent), self.sent)
        self.assertIn(b'\x00\x01audio', self.sent)
        self.assertFalse(any('previous' in str(m) for m in self.sent), self.sent)

    @staticmethod
    def _wait(cond):
        import time
        for _ in range(100):
            if cond():
                return
            time.sleep(0.02)

    def test_check_kind_helper(self):
        who = cr.Who(role=None, member_id=None, place='panel', proven=False)
        rules = cr.default_rules({})
        self.assertTrue(cr.check_kind(who, 'media', {'ha_control': rules}).allowed)
        rules['places']['panel']['media'] = 'no'
        self.assertFalse(cr.check_kind(who, 'media', {'ha_control': rules}).allowed)


if __name__ == '__main__':
    unittest.main()
