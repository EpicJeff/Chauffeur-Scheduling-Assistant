"""A panel belongs to a room and finds its satellite (spec 2026-11-10, Task 4).

A wall panel is a trusted_devices row with kind 'panel'. It gains two optional
fields, set by a parent on its row in Config > Trusted devices:
  - area_id: the Home Assistant area it hangs in;
  - satellite_id: an assist_satellite override, empty = automatic.
panel_talk.satellite_for_panel(device) picks the room's satellite: a still-known
override, else the area's announce pin when that pin is a satellite, else the
first usable assist_satellite in the area. No HA means no satellite, never an
exception.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_panel_room.py
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_panel_room_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from services import storage, ha_api

AREAS = [
    {'id': 'kitchen', 'name': 'Kitchen',
     'entities': ['assist_satellite.kitchen_b', 'assist_satellite.kitchen_a', 'media_player.kitchen_sonos']},
    {'id': 'office', 'name': 'Office', 'entities': ['assist_satellite.office', 'light.office']},
    {'id': 'hall', 'name': 'Hall', 'entities': ['media_player.hall']},
]
STATES = [{'entity_id': e, 'state': 'idle', 'attributes': {'friendly_name': e.split('.')[1].title()}}
          for e in ('assist_satellite.kitchen_a', 'assist_satellite.kitchen_b', 'assist_satellite.office',
                    'media_player.kitchen_sonos', 'media_player.hall', 'light.office')]


class PanelRoomTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.trusted_devices_table,
                      storage.app_state_table):
            table.truncate()
        storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent'})
        storage.add_member({'id': 'kid', 'name': 'Kid', 'role': 'child'})
        self.parent = storage.create_member_token('mum', proof='password')
        self.child = storage.create_member_token('kid', proof='password')
        token = storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')
        self.panel_id = storage.get_device_by_token(token)['device_id']
        storage.trust_device('phone-1', 'Mum phone', by_member='mum', kind='personal')
        self.settings = {}
        base = dict(storage.get_settings() or {})
        p = patch.object(storage, 'get_settings', side_effect=lambda: {**base, **self.settings})
        p.start(); self.addCleanup(p.stop)
        self.ha = True
        for name, value in (('is_available', lambda: self.ha),
                            ('get_area_map', lambda ttl=60: AREAS if self.ha else []),
                            ('get_states', lambda ttl=5: STATES if self.ha else [])):
            p = patch.object(ha_api, name, side_effect=value)
            p.start(); self.addCleanup(p.stop)
        import main
        self.client = TestClient(main.app)

    def device(self, device_id=None):
        return storage.get_trusted_device(device_id or self.panel_id)

    def put(self, body, device_id=None, token=None):
        return self.client.post(f'/api/account/devices/{device_id or self.panel_id}/room', json=body,
                                headers={'X-Member-Token': token or self.parent})

    # --- storage ---------------------------------------------------------------
    def test_set_room_panel_only(self):
        row = storage.set_device_room(self.panel_id, 'kitchen', None)
        self.assertEqual(row['area_id'], 'kitchen')
        self.assertIsNone(row.get('satellite_id'))
        self.assertEqual(self.device()['area_id'], 'kitchen')
        self.assertIsNone(storage.set_device_room('phone-1', 'kitchen', None))
        self.assertNotIn('area_id', self.device('phone-1'))
        self.assertIsNone(storage.set_device_room('nope', 'kitchen', None))

    def test_clearing_room(self):
        storage.set_device_room(self.panel_id, 'kitchen', 'assist_satellite.office')
        row = storage.set_device_room(self.panel_id, None, None)
        self.assertIsNone(row.get('area_id'))
        self.assertIsNone(row.get('satellite_id'))

    # --- routes ----------------------------------------------------------------
    def test_route_sets_room(self):
        r = self.put({'area_id': 'kitchen', 'satellite_id': ''})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['area_id'], 'kitchen')
        self.assertEqual(self.device()['area_id'], 'kitchen')

    def test_route_parent_only(self):
        r = self.put({'area_id': 'kitchen'}, token=self.child)
        self.assertIn(r.status_code, (401, 403))
        self.assertIsNone(self.device().get('area_id'))

    def test_route_validates(self):
        self.assertEqual(self.put({'area_id': 'kitchen', 'satellite_id': 'media_player.kitchen_sonos'}).status_code, 400)
        self.assertEqual(self.put({'area_id': 'kitchen'}, device_id='phone-1').status_code, 400)
        self.assertEqual(self.put({'area_id': 'kitchen'}, device_id='nope').status_code, 404)

    def test_list_returns_room_fields(self):
        storage.set_device_room(self.panel_id, 'kitchen', 'assist_satellite.office')
        rows = self.client.get('/api/account/devices', headers={'X-Member-Token': self.parent}).json()
        panel = next(d for d in rows if d['device_id'] == self.panel_id)
        self.assertEqual((panel['area_id'], panel['satellite_id']), ('kitchen', 'assist_satellite.office'))
        self.assertNotIn('device_token', panel, 'the panel credential never leaves the server')

    def test_rooms_route(self):
        r = self.client.get('/api/account/devices/rooms', headers={'X-Member-Token': self.parent})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual([a['id'] for a in body['areas']], ['kitchen', 'office', 'hall'])
        sats = {s['id']: s for s in body['satellites']}
        self.assertEqual(set(sats), {'assist_satellite.kitchen_a', 'assist_satellite.kitchen_b',
                                     'assist_satellite.office'})
        self.assertEqual(sats['assist_satellite.office']['area_id'], 'office')
        self.assertIn(self.client.get('/api/account/devices/rooms',
                                      headers={'X-Member-Token': self.child}).status_code, (401, 403))

    def test_rooms_without_ha(self):
        self.ha = False
        from services import panel_talk
        self.assertEqual(panel_talk.rooms(), {'areas': [], 'satellites': []})

    # --- which satellite ---------------------------------------------------------
    def sat(self, area_id, satellite_id=None):
        from services import panel_talk
        storage.set_device_room(self.panel_id, area_id, satellite_id)
        return panel_talk.satellite_for_panel(self.device())

    def test_first_area_satellite(self):
        self.assertEqual(self.sat('kitchen'), 'assist_satellite.kitchen_a')

    def test_satellite_override_wins(self):
        self.assertEqual(self.sat('kitchen', 'assist_satellite.office'), 'assist_satellite.office')

    def test_stale_override_falls_back(self):
        self.assertEqual(self.sat('kitchen', 'assist_satellite.gone'), 'assist_satellite.kitchen_a')

    def test_announce_pin_satellite_used(self):
        self.settings['announce_targets'] = {'kitchen': 'assist_satellite.kitchen_b'}
        self.assertEqual(self.sat('kitchen'), 'assist_satellite.kitchen_b')

    def test_announce_pin_media_player_ignored(self):
        self.settings['announce_targets'] = {'kitchen': 'media_player.kitchen_sonos'}
        self.assertEqual(self.sat('kitchen'), 'assist_satellite.kitchen_a')

    def test_unavailable_satellite_skipped(self):
        STATES[0]['state'] = 'unavailable'
        self.addCleanup(STATES[0].__setitem__, 'state', 'idle')
        self.assertEqual(self.sat('kitchen'), 'assist_satellite.kitchen_b')

    def test_room_without_satellite(self):
        self.assertIsNone(self.sat('hall'))

    def test_no_room(self):
        from services import panel_talk
        self.assertIsNone(panel_talk.satellite_for_panel(self.device()))
        self.assertIsNone(panel_talk.satellite_for_panel(None))

    def test_no_ha_none(self):
        storage.set_device_room(self.panel_id, 'kitchen', 'assist_satellite.office')
        self.ha = False
        from services import panel_talk
        self.assertIsNone(panel_talk.satellite_for_panel(self.device()))

    def test_ha_error_none(self):
        from services import panel_talk
        storage.set_device_room(self.panel_id, 'kitchen', None)
        with patch.object(ha_api, 'get_area_map', side_effect=RuntimeError('boom')):
            self.assertIsNone(panel_talk.satellite_for_panel(self.device()))

    # --- the Config row -------------------------------------------------------------
    def test_config_rows_have_room_controls(self):
        """The room and satellite pickers sit on panel rows only (hooks the UI test relies on)."""
        src = (Path(__file__).resolve().parents[1] / 'templates' / 'config.html').read_text(encoding='utf-8')
        start = src.index('x-for="d in trustedDevices"')
        row = src[start:start + 6000]
        self.assertIn("d.kind === 'panel'", row)
        self.assertIn('data-device-room', row)
        self.assertIn('data-device-satellite', row)
        self.assertIn('saveDeviceRoom(d', row)
        self.assertIn("api/account/devices/rooms", src)
        self.assertNotIn("'/api/account/devices/rooms", src, 'never a root-relative URL under ingress')


if __name__ == '__main__':
    unittest.main(verbosity=2)
