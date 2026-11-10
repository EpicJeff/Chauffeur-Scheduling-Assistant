"""Who is asking, and the wall panel's one-use grant (Task 3 of
docs/superpowers/plans/2026-11-09-ha-control-permissions.md).

A request becomes a `Who`: a proven member, a member the system only thinks
it knows, a place with no known person (the wall panel, an unknown voice), or
the admin page. Where a token came from matters: only a token minted on a
personal device by a password or a PIN proves the person. A token minted on
the panel, or for a member with no PIN, never proves anyone, with or without
the device header. On the panel, "Ask who" mints a grant that covers one
action, on that panel, for sixty seconds.

Run from chauffeur/:  python tests/test_control_identity.py
"""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import access, control_rules as cr, house, storage

PASSWORD = 'correct horse battery'


def _member(mid, role, pin=None, email=None):
    if not storage.get_member(mid):
        storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active',
                            **({'email': email} if email else {})})
    if pin:
        storage.set_member_pin(mid, pin)
    if email:
        storage.set_member_password(mid, PASSWORD)
    return storage.get_member(mid)


def voice(level='unknown', member_id=None, recognized=False, paired=True):
    return SimpleNamespace(level=level, member_id=member_id, recognized_this_turn=recognized,
                           paired=paired, verified_member=lambda: storage.get_member(member_id)
                           if level == 'verified' and member_id else None)


class Identity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mum = _member('mum', 'parent', pin='4321', email='mum@example.com')
        cls.kid = _member('kid', 'child', pin='1111')
        cls.nopin = _member('dad', 'parent')
        cls.panel = storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')
        cls.panel2 = storage.enrol_device_token('panel-2', 'Hall panel', by_member='mum')

    def setUp(self):
        self.settings = patch.object(storage, 'get_settings',
                                     return_value={**storage.get_settings(), 'auth_enforce': True})
        self.settings.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.settings.stop()

    def grant(self, member_id, pin, device=None):
        headers = {'X-Device-Token': device or self.panel}
        return self.client.post('/api/ha/control/grant', json={'member_id': member_id, 'pin': pin},
                                headers=headers)

    # --- the grant route -------------------------------------------------

    def test_grant_requires_panel_and_pin(self):
        r = self.client.post('/api/ha/control/grant', json={'member_id': 'mum', 'pin': '4321'})
        self.assertEqual(r.status_code, 403, r.text)
        r = self.grant('dad', '')
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn('Set a PIN', r.text)
        r = self.grant('mum', '0000')
        self.assertEqual(r.status_code, 403, r.text)
        r = self.grant('mum', '4321')
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body['grant'])
        self.assertEqual(body['expires_in'], 60)

    def test_grant_with_a_member_token_on_the_panel(self):
        # The panel stamps every request with its device token, and a child who
        # just opened the avatar overlay sends their member token too. The grant
        # step must still work from that panel.
        kid_token = self.client.post('/api/members/kid/auth', json={'pin': '1111'},
                                     headers={'X-Device-Token': self.panel}).json()['token']
        r = self.client.post('/api/ha/control/grant', json={'member_id': 'mum', 'pin': '4321'},
                             headers={'X-Device-Token': self.panel, 'X-Member-Token': kid_token})
        self.assertEqual(r.status_code, 200, r.text)
        held = cr.hold('house', {'action': 'read', 'entity_id': 'light.a'}, device_id='panel-1')
        real = house.house
        house.house = lambda **kw: {'status': 'success', 'by': kw['acting_member']['id']}
        try:
            r2 = self.client.post(f'/api/ha/control/held/{held}',
                                  headers={'X-Device-Token': self.panel, 'X-Member-Token': kid_token,
                                           'X-Control-Grant': r.json()['grant']})
        finally:
            house.house = real
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()['by'], 'mum')

    def test_grant_refused_to_a_phone(self):
        phone = self.client.post('/api/account/login',
                                 json={'email': 'mum@example.com', 'password': PASSWORD}).json()['token']
        r = self.client.post('/api/ha/control/grant', json={'member_id': 'mum', 'pin': '4321'},
                             headers={'X-Member-Token': phone})
        self.assertEqual(r.status_code, 403, r.text)

    def test_grant_one_use(self):
        g = self.grant('mum', '4321').json()['grant']
        headers = {'x-device-token': self.panel, 'x-control-grant': g}
        who = cr.who_from_request(headers, {})
        self.assertEqual((who.role, who.member_id, who.proven, who.place), ('parent', 'mum', True, None))
        again = cr.who_from_request(headers, {})
        self.assertEqual(again.place, 'panel')
        self.assertFalse(again.proven)

    def test_grant_bound_to_device(self):
        g = self.grant('mum', '4321').json()['grant']
        who = cr.who_from_request({'x-device-token': self.panel2, 'x-control-grant': g}, {})
        self.assertEqual(who.place, 'panel')

    def test_grant_expires(self):
        g = self.grant('mum', '4321').json()['grant']
        later = time.time() + 61
        with patch('time.time', return_value=later):
            who = cr.who_from_request({'x-device-token': self.panel, 'x-control-grant': g}, {})
        self.assertEqual(who.place, 'panel')

    def test_forged_grant(self):
        who = cr.who_from_request({'x-device-token': self.panel, 'x-control-grant': 'made-up'}, {})
        self.assertEqual(who.place, 'panel')

    # --- tokens and where they came from ----------------------------------

    def test_phone_member_is_proven(self):
        r = self.client.post('/api/account/login', json={'email': 'mum@example.com', 'password': PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)
        who = cr.who_from_request({'x-member-token': r.json()['token']}, {})
        self.assertEqual((who.role, who.member_id, who.proven, who.place), ('parent', 'mum', True, None))

    def test_member_token_on_panel_is_panel(self):
        # The avatar/critter PIN step on the wall: an ordinary member token
        # arriving WITH the panel's device token is a person at a place.
        r = self.client.post('/api/members/kid/auth', json={'pin': '1111'},
                             headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()['token']
        who = cr.who_from_request({'x-device-token': self.panel, 'x-member-token': token}, {})
        self.assertEqual(who.place, 'panel')
        self.assertFalse(who.proven)

    def test_panel_token_without_header(self):
        # Codex review: dropping the device header must not upgrade it.
        r = self.client.post('/api/members/mum/auth', json={'pin': '4321'},
                             headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        who = cr.who_from_request({'x-member-token': r.json()['token']}, {})
        self.assertEqual(who.place, 'panel')
        self.assertFalse(who.proven)

    def test_pinless_token_not_proof(self):
        r = self.client.post('/api/members/dad/auth', json={},
                             headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        who = cr.who_from_request({'x-member-token': r.json()['token']}, {})
        self.assertEqual(who.place, 'panel')

    def test_token_rows_record_provenance(self):
        token = storage.create_member_token('mum', proof='pin', minted_on='personal')
        from tinydb import Query
        row = storage.member_tokens_table.get(Query().token == token)
        self.assertEqual((row.get('proof'), row.get('minted_on')), ('pin', 'personal'))

    def test_legacy_token_counts_as_personal(self):
        token = storage.create_member_token('mum')
        from tinydb import Query
        storage.member_tokens_table.update(
            lambda row: (row.pop('proof', None), row.pop('minted_on', None)), Query().token == token)
        who = cr.who_from_request({'x-member-token': token}, {})
        self.assertTrue(who.proven)
        self.assertEqual(who.member_id, 'mum')

    def test_house_session_is_panel(self):
        token = storage.create_member_token('mum', house_session=True)
        who = cr.who_from_request({'x-member-token': token}, {})
        self.assertEqual(who.place, 'panel')

    def test_device_alone_and_nothing_are_panel(self):
        self.assertEqual(cr.who_from_request({'x-device-token': self.panel}, {}).place, 'panel')
        self.assertEqual(cr.who_from_request({'cf-connecting-ip': '203.0.113.7'}, {}).place, 'panel')

    # --- Argyle -----------------------------------------------------------

    def test_who_from_agent(self):
        verified = cr.who_from_agent(None, voice('verified', 'mum'), 'voice')
        self.assertEqual((verified.role, verified.proven), ('parent', True))
        recognised = cr.who_from_agent(None, voice('named', 'mum', recognized=True), 'voice')
        self.assertEqual((recognised.role, recognised.member_id, recognised.proven), ('parent', 'mum', False))
        claimed = cr.who_from_agent(None, voice('named', 'mum', recognized=False), 'voice')
        self.assertEqual(claimed.place, 'unknown_voice')
        stranger = cr.who_from_agent(None, voice(), 'voice')
        self.assertEqual((stranger.place, stranger.voice_id), ('unknown_voice', True))
        unpaired = cr.who_from_agent(None, voice(paired=False), 'voice')
        self.assertFalse(unpaired.voice_id)
        self.assertEqual(cr.who_from_agent(access.HOUSE, None, 'pwa').place, 'panel')
        self.assertEqual(cr.who_from_agent(access.HOUSE_PARENT, None, 'pwa').place, 'panel')
        self.assertTrue(cr.who_from_agent(None, None, 'admin').admin)
        kid = cr.who_from_agent(self.kid, None, 'pwa')
        self.assertEqual((kid.role, kid.proven), ('child', True))

    # --- held Argyle actions ---------------------------------------------

    def test_held_runs_once_as_the_grant(self):
        calls = []
        real = house.house

        def fake(**kwargs):
            calls.append(kwargs)
            return {'status': 'success', 'message': 'Front door is unlocked.'}
        house.house = fake
        try:
            held = cr.hold('house', {'action': 'act', 'entity_id': 'lock.front', 'service': 'unlock'}, device_id='panel-1')
            g = self.grant('mum', '4321').json()['grant']
            headers = {'X-Device-Token': self.panel, 'X-Control-Grant': g}
            r = self.client.post(f'/api/ha/control/held/{held}', headers=headers)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['status'], 'success')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['acting_member']['id'], 'mum')
            self.assertEqual(calls[0]['entity_id'], 'lock.front')
            g2 = self.grant('mum', '4321').json()['grant']
            r = self.client.post(f'/api/ha/control/held/{held}',
                                 headers={'X-Device-Token': self.panel, 'X-Control-Grant': g2})
            self.assertEqual(r.status_code, 404, r.text)
            self.assertEqual(len(calls), 1)
        finally:
            house.house = real

    def test_held_needs_a_grant(self):
        held = cr.hold('house', {'action': 'act', 'entity_id': 'lock.front', 'service': 'unlock'})
        r = self.client.post(f'/api/ha/control/held/{held}', headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 403, r.text)

    def test_held_expires(self):
        held = cr.hold('house', {'action': 'act', 'entity_id': 'lock.front', 'service': 'unlock'})
        with patch('time.time', return_value=time.time() + 121):
            self.assertIsNone(cr.take_held(held))

    # --- "unproven" and "at the panel" are different facts (Task 5 round 2) --

    def _phone_device(self):
        """A trusted device that is NOT a panel (a family phone)."""
        from tinydb import Query
        token = storage.enrol_device_token('phone-1', "Dad's phone", by_member='dad')
        with storage.db_lock:
            storage.trusted_devices_table.update({'kind': 'phone'}, Query().device_id == 'phone-1')
        return token

    def test_pinless_personal_token_is_the_member(self):
        pinless = storage.create_member_token('dad')  # proof 'none', minted on a personal device
        password = storage.create_member_token('mum', proof='password', minted_on='personal')
        # At the panel stays the Wall panel card, whoever's token rides along:
        for label, headers, query in (
                ('PIN-less token + panel header', {'x-member-token': pinless, 'x-device-token': self.panel}, {}),
                ('PIN-less token + panel query', {'x-member-token': pinless}, {'device_token': self.panel}),
                ('password token + panel header', {'x-member-token': password, 'x-device-token': self.panel}, {}),
                ('panel-minted, no header', {'x-member-token': storage.create_member_token(
                    'dad', minted_on='panel')}, {}),
                ('house session', {'x-member-token': storage.create_member_token('mum', house_session=True)}, {})):
            who = cr.who_from_request(headers, query)
            self.assertEqual((who.place, who.member_id, who.proven), ('panel', None, False), label)
        # On their own device a PIN-less member is THAT member, unproven.
        for label, headers in (('alone', {'x-member-token': pinless}),
                               ('with a phone device', {'x-member-token': pinless,
                                                        'x-device-token': self._phone_device()})):
            who = cr.who_from_request(headers, {})
            self.assertEqual((who.role, who.member_id, who.place, who.proven), ('parent', 'dad', None, False),
                             f'PIN-less personal token {label}')
        # Their own row decides: a proof kind asks for the PIN, never the panel's no.
        decision = cr.decide(cr.who_from_request({'x-member-token': pinless}, {}), ('locks',), cr.default_rules({}))
        self.assertEqual((decision.allowed, decision.needs), (False, 'pin'))

    # --- Task 5 final wave --------------------------------------------------

    def test_request_facts_fail_toward_the_panel(self):
        token = storage.create_member_token('mum', proof='password', minted_on='personal')
        headers = {'x-member-token': token}
        # The control: a readable personal password row is a proven person, not a panel.
        self.assertEqual(cr.request_facts(headers, {}), (True, False))
        # The token validated, then its row read came back empty or raised.
        for label, effect in (('row read returned None', lambda *a, **kw: None),
                              ('row read raised', RuntimeError('database is locked'))):
            with patch.object(storage.member_tokens_table, 'get', side_effect=effect):
                self.assertEqual(cr.request_facts(headers, {}), (False, True),
                                 f'{label}: expected (proven=False, at_panel=True)')
                who = cr.who_from_request(headers, {})
                self.assertEqual((who.place, who.member_id, who.proven), ('panel', None, False), label)

    def test_pin_minted_with_a_panel_device_id_is_panel_minted(self):
        # The panel's PIN step identifies itself by X-Device-Id alone (no device token).
        r = self.client.post('/api/members/kid/auth', json={'pin': '1111'},
                             headers={'X-Device-Id': 'panel-1'})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()['token']
        from tinydb import Query
        row = storage.member_tokens_table.get(Query().token == token)
        self.assertEqual(row.get('minted_on'), 'panel',
                         'a token minted at an enrolled panel (named by X-Device-Id) must record minted_on=panel')
        who = cr.who_from_request({'x-member-token': token}, {})
        self.assertEqual(who.place, 'panel')


if __name__ == '__main__':
    unittest.main()
