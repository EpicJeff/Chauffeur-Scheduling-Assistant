"""The hand path's routes for Argyle's style (Task 4 of docs/superpowers/plans/2026-11-11-argyle-style.md).

Anyone signed in reads and sets their OWN style (kids included), and only their
own: the member comes from the token, never the body. Parents set the household
style, list everyone whose style differs, and reset a person back to Same as the
household; they never pick a style for someone else.

Run from chauffeur/:  python tests/test_argyle_style_routes.py
"""
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import argyle_style, auth, storage

PARENT = {'id': 'm_mom', 'name': 'Lorena', 'role': 'parent', 'status': 'active'}
KID = {'id': 'm_lily', 'name': 'Lily', 'role': 'child', 'status': 'active'}


class StyleRoutes(unittest.TestCase):
    def setUp(self):
        self.settings = {**(storage.get_settings() or {}), 'auth_enforce': True}
        self.settings.pop('argyle_style', None)
        self.settings.pop('argyle_style_custom', None)
        tests = self
        self.patches = [
            patch.object(storage, 'get_settings', side_effect=lambda: dict(tests.settings)),
            patch.object(storage, 'patch_settings', side_effect=lambda data: tests.settings.update(data)),
        ]
        for p in self.patches:
            p.start()
        with storage.db_lock:
            storage.members_table.truncate()
        storage.add_member(dict(PARENT))
        storage.add_member(dict(KID))
        self.parent = {'X-Member-Token': storage.create_member_token('m_mom')}
        self.kid = {'X-Member-Token': storage.create_member_token('m_lily')}
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        with storage.db_lock:
            storage.members_table.truncate()

    def test_a_kid_reads_and_sets_their_own(self):
        r = self.client.get('/api/argyle/style/me', headers=self.kid)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body['style'], body['custom']), ('household', ''))
        self.assertEqual(body['household'], {'style': 'warm', 'custom': ''})
        self.assertEqual(body['labels'], argyle_style.LABELS)
        r = self.client.post('/api/argyle/style/me', headers=self.kid,
                             json={'style': 'custom', 'custom': 'a cheerful pirate', 'member_id': 'm_mom'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(argyle_style.get_member_style('m_lily'), {'style': 'custom', 'custom': 'a cheerful pirate'})
        self.assertEqual(argyle_style.get_member_style('m_mom')['style'], 'household',
                         'the body never names whose style changes')

    def test_bad_input(self):
        r = self.client.post('/api/argyle/style/me', headers=self.kid, json={'style': 'loud'})
        self.assertEqual(r.status_code, 400, r.text)
        r = self.client.post('/api/argyle/style', headers=self.parent, json={'style': 'household'})
        self.assertEqual(r.status_code, 400, r.text)
        r = self.client.get('/api/argyle/style/me')
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_a_kid_cannot_touch_the_household_or_anyone_else(self):
        r = self.client.get('/api/argyle/style', headers=self.kid)
        self.assertIn(r.status_code, (401, 403), r.text)
        r = self.client.post('/api/argyle/style', headers=self.kid, json={'style': 'plain'})
        self.assertIn(r.status_code, (401, 403), r.text)
        argyle_style.set_member_style('m_mom', 'plain')
        r = self.client.post('/api/argyle/style/reset/m_mom', headers=self.kid)
        self.assertIn(r.status_code, (401, 403), r.text)
        self.assertEqual(argyle_style.get_member_style('m_mom')['style'], 'plain')
        self.assertEqual(argyle_style.household(), ('warm', ''))

    def test_a_parent_sets_the_household_lists_and_resets(self):
        argyle_style.set_member_style('m_lily', 'custom', 'a cheerful pirate')
        r = self.client.post('/api/argyle/style', headers=self.parent, json={'style': 'custom',
                                                                              'custom': 'a calm butler'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(argyle_style.household(), ('custom', 'a calm butler'))
        r = self.client.get('/api/argyle/style', headers=self.parent)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['household'], {'style': 'custom', 'custom': 'a calm butler'})
        self.assertEqual([(p['id'], p['style'], p['custom']) for p in body['people']],
                         [('m_lily', 'custom', 'a cheerful pirate')],
                         'everyone whose style differs, custom text in full; Same as the household is not listed')
        r = self.client.post('/api/argyle/style/reset/m_lily', headers=self.parent)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(argyle_style.get_member_style('m_lily')['style'], 'household')

    def test_a_kid_is_refused_even_with_enforcement_off(self):
        self.settings['auth_enforce'] = False
        argyle_style.set_member_style('m_mom', 'plain')
        r = self.client.get('/api/argyle/style', headers=self.kid)
        self.assertEqual(r.status_code, 403, r.text)
        r = self.client.post('/api/argyle/style', headers=self.kid, json={'style': 'playful'})
        self.assertEqual(r.status_code, 403, r.text)
        r = self.client.post('/api/argyle/style/reset/m_mom', headers=self.kid)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(argyle_style.household(), ('warm', ''))
        self.assertEqual(argyle_style.get_member_style('m_mom')['style'], 'plain')
        r = self.client.post('/api/argyle/style', headers=self.parent, json={'style': 'playful'})
        self.assertEqual(r.status_code, 200, r.text)

    def test_every_route_has_a_tier(self):
        for method, path in (('GET', '/api/argyle/style/me'), ('POST', '/api/argyle/style/me'),
                             ('GET', '/api/argyle/style'), ('POST', '/api/argyle/style'),
                             ('POST', '/api/argyle/style/reset/m_lily')):
            self.assertIsNotNone(auth.resolve(method, path), f'{method} {path} has no rule')


if __name__ == '__main__':
    unittest.main()
