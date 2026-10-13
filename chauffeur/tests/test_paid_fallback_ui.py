"""The paid fallback's hand path and its parent notice (design 2026-10-13).

The detector and the key swap live in services/paid_fallback.py and
services/model_pools.py (tests/test_paid_fallback.py). This file covers what
a PERSON sees and does: the status endpoint the AI drawer reads, the parent's
own switch (on until midnight, or off early), and the one DM parents get
when the threshold is reached. The switch is a signed-in parent's act on an
admin page; there is deliberately no agent tool for it, so the chat model
can never turn paid spending on by itself.

Run from chauffeur/:  python tests/test_paid_fallback_ui.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: F401,E402  (temp storage)
from services import storage  # noqa: E402
from services import paid_fallback as pf  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
SETTINGS = {'llm_gemini_api_key': 'F', 'llm_gemini_paid_api_key': 'P', 'llm_paid_fallback_mode': 'ask',
            'llm_paid_fallback_failures': 3, 'llm_paid_fallback_daily_cap': 300, 'calendar_ids': ['primary']}


def _client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def _parent(mid='p1', name='Pat'):
    storage.add_member({'id': mid, 'name': name, 'role': 'parent'})
    return storage.create_member_token(mid)


class PaidFallbackHandPathTests(unittest.TestCase):
    def setUp(self):
        pf.reset()
        storage.members_table.truncate()
        storage.get_settings = lambda: dict(SETTINGS)

    def tearDown(self):
        pf.reset()

    def test_the_drawer_can_read_the_status(self):
        r = _client().get('/api/ai/paid-fallback')
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for k in ('configured', 'mode', 'active', 'until', 'used_today', 'cap', 'failures_recent', 'threshold'):
            self.assertIn(k, body, f'status lacks {k}')
        self.assertTrue(body['configured'])
        self.assertFalse(body['active'])

    def test_a_parent_switches_it_on_until_midnight_and_off_again(self):
        token = _parent()
        c = _client()
        r = c.post('/api/ai/paid-fallback', json={'active': True}, headers={'X-Member-Token': token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['active'])
        self.assertGreater(r.json()['until'], 0)
        self.assertEqual(r.json()['activated_by'], 'parent')
        self.assertTrue(pf.status(SETTINGS)['active'])
        r = c.post('/api/ai/paid-fallback', json={'active': False}, headers={'X-Member-Token': token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()['active'])
        self.assertFalse(pf.status(SETTINGS)['active'])

    def test_only_a_parent_may_switch_it(self):
        storage.add_member({'id': 'k1', 'name': 'Kid', 'role': 'child'})
        token = storage.create_member_token('k1')
        r = _client().post('/api/ai/paid-fallback', json={'active': True}, headers={'X-Member-Token': token})
        self.assertIn(r.status_code, (401, 403), r.text)
        self.assertFalse(pf.status(SETTINGS)['active'])
        r = _client().post('/api/ai/paid-fallback', json={'active': True})
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_the_routes_are_classified_for_parents(self):
        from services import auth
        self.assertEqual(auth.resolve('GET', '/api/ai/paid-fallback'), auth.PARENTS)
        self.assertEqual(auth.resolve('POST', '/api/ai/paid-fallback'), auth.PARENTS)

    def test_the_notice_is_a_dm_from_argyle_to_every_parent(self):
        _parent('p1', 'Pat')
        _parent('p2', 'Sam')
        storage.add_member({'id': 'k1', 'name': 'Kid', 'role': 'child'})
        pf.notify_parents("Argyle's free tier has failed 3 times in the last 30 minutes.")
        argyle = storage.ensure_argyle_member()
        for pid in ('p1', 'p2'):
            dm = storage.get_or_create_dm(argyle['id'], pid)
            msgs = storage.get_channel_messages(dm['id'])
            self.assertTrue(any('3 times' in (m.get('body') or '') for m in msgs), f'{pid} got no notice: {msgs}')
        dm = storage.get_or_create_dm(argyle['id'], 'k1')
        self.assertEqual(storage.get_channel_messages(dm['id']), [], 'a child was told about paid spending')


class DrawerMarkupTests(unittest.TestCase):
    def test_the_ai_drawer_carries_the_controls(self):
        src = open(os.path.join(TPL, 'config.html'), encoding='utf-8').read()
        for binding in ('llmPaidFallbackMode', 'llmPaidFallbackFailures', 'llmPaidFallbackDailyCap'):
            self.assertIn(f'x-model="{binding}"', src, f'the AI drawer has no control bound to {binding}')
        self.assertIn('api/ai/paid-fallback', src, 'the drawer never reads the fallback status')
        self.assertIn('Use paid key until midnight', src, 'the parent has no button to switch it on')
        self.assertIn('Switch off now', src, 'the parent has no button to switch it off early')


if __name__ == '__main__':
    unittest.main()
