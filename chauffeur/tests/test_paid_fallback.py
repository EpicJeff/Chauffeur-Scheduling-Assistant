"""The paid-key fallback for a throttled free tier (design agreed 2026-10-13).

When Google sheds free-tier load (503 "overloaded", per-minute 429s), every
model in the interactive chain cools down and chat answers "overloaded". The
paid key can call the very same lite/flash model ids with priority, so a key
swap on the same chain is the whole fix. Rules:

  * A THROTTLE EVENT is one foreground call (someone waiting: interactive,
    vision, heavy) that exhausts its whole free chain with transient errors.
    Background work never counts and never spends paid money.
  * Events are counted in a rolling 30 minute window and persist in app
    state, so a restart does not forget the morning.
  * At `llm_paid_fallback_failures` events (default 3) the mode decides:
    'auto' switches the fallback on until the household's local midnight and
    tells the parents once; 'ask' tells the parents once per day and changes
    nothing; 'off' is silent. Nothing happens in any mode without a paid key.
  * While active, foreground calls run the same chain on the paid key, each
    counted against `llm_paid_fallback_daily_cap` (default 300). At the cap,
    or at midnight, it switches off. A parent can switch it on or off by hand.
  * Cooldowns are per key class: a model that failed on the free key is
    tried fresh on the paid one.
  * The paid key is still read in one place (test_missions_pins): the
    fallback asks model_pools.api_key_for_pool('pro') for it.

Run from chauffeur/:  python tests/test_paid_fallback.py
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: F401,E402  (temp storage)
from services import model_pools as pools  # noqa: E402
from services import paid_fallback as pf  # noqa: E402
from services import storage  # noqa: E402

FREE, PAID = 'F', 'P'
BASE = {'model_pool_lite': 'gemini-lite-a,gemini-lite-b', 'model_pool_gemma': 'gemma-x',
        'llm_gemini_api_key': FREE, 'llm_gemini_paid_api_key': PAID}
T0 = 1_760_000_000.0   # an ordinary mid-morning


def settings(**kw):
    return {**BASE, 'llm_paid_fallback_mode': 'ask', 'llm_paid_fallback_failures': 3,
            'llm_paid_fallback_daily_cap': 300, **kw}


def overloaded_on_free(*args, **kw):
    """A fake provider: every model is overloaded on the free key, fine on the paid one."""
    key, model = args[2], args[3]
    if key == FREE:
        raise RuntimeError('HTTP Error 503: Service Unavailable')
    return {'ok': True, 'key': key}


class PaidFallbackTests(unittest.TestCase):
    def setUp(self):
        pools.reset_cooldowns()
        pf.reset()
        self.notices = []
        self._notify = patch.object(pf, 'notify_parents', lambda text: self.notices.append(text))
        self._notify.start()

    def tearDown(self):
        self._notify.stop()
        pools.reset_cooldowns()
        pf.reset()

    def call(self, tier='interactive', s=None, **kw):
        return pools.call_pool_json(tier, FREE, 'system', 'user', settings=s or settings(), max_models=10, **kw)

    def keys_seen(self, request):
        seen = []

        def wrapped(*args, **kw):
            seen.append(args[2])
            return request(*args, **kw)
        return seen, wrapped

    # --- counting -----------------------------------------------------------

    def test_one_failure_is_not_a_throttle_worth_acting_on(self):
        seen, req = self.keys_seen(overloaded_on_free)
        with patch('services.llm._call_llm_json', req), patch.object(pools.time, 'time', return_value=T0):
            res = self.call()
        self.assertIn('error', res)
        self.assertNotIn(PAID, seen, 'one failure spent paid money')
        self.assertEqual(self.notices, [], 'one failure interrupted a parent')
        st = pf.status(settings(), now=T0)
        self.assertEqual(st['failures_recent'], 1)
        self.assertFalse(st['active'])

    def test_background_work_never_counts_and_never_spends(self):
        pf.activate(settings(), now=T0, by='parent')
        seen, req = self.keys_seen(overloaded_on_free)
        with patch('services.llm._call_llm_json', req), patch.object(pools.time, 'time', return_value=T0):
            self.call(tier='background', s=settings(model_pool_gemma='gemma-x,gemma-y'))
        self.assertNotIn(PAID, seen, 'background work spent paid money')
        self.assertEqual(pf.status(settings(), now=T0)['failures_recent'], 0, 'a background failure counted as a throttle')

    def test_events_outside_the_window_fall_off(self):
        pf.note_throttle(settings(), now=T0 - 3600)
        pf.note_throttle(settings(), now=T0 - 1700)
        self.assertEqual(pf.status(settings(), now=T0)['failures_recent'], 1)

    def test_events_persist_across_a_restart(self):
        pf.note_throttle(settings(), now=T0)
        pf.reset(memory_only=True)
        self.assertEqual(pf.status(settings(), now=T0 + 60)['failures_recent'], 1)

    # --- the threshold ------------------------------------------------------

    def test_auto_mode_switches_on_at_the_threshold_and_answers_that_very_call(self):
        s = settings(llm_paid_fallback_mode='auto')
        pf.note_throttle(s, now=T0 - 600)
        pf.note_throttle(s, now=T0 - 300)
        seen, req = self.keys_seen(overloaded_on_free)
        with patch('services.llm._call_llm_json', req), patch.object(pools.time, 'time', return_value=T0):
            res = self.call(s=s)
        self.assertTrue(res.get('ok'), f'the third throttle did not get answered on the paid key: {res}')
        self.assertEqual(seen[-1], PAID)
        self.assertTrue(all(k == FREE for k in seen[:-1]), 'the free chain was not tried first')
        st = pf.status(s, now=T0)
        self.assertTrue(st['active'])
        self.assertEqual(st['activated_by'], 'auto')
        self.assertEqual(st['used_today'], 1)
        self.assertEqual(len(self.notices), 1)
        self.assertIn('midnight', self.notices[0].lower())
        self.assertIn('300', self.notices[0])

    def test_ask_mode_tells_the_parents_once_a_day_and_spends_nothing(self):
        s = settings()
        seen, req = self.keys_seen(overloaded_on_free)
        with patch('services.llm._call_llm_json', req):
            for i in range(4):
                with patch.object(pools.time, 'time', return_value=T0 + i * 60):
                    self.call(s=s)
        self.assertNotIn(PAID, seen, 'ask mode spent paid money')
        self.assertEqual(len(self.notices), 1, f'the parents were told {len(self.notices)} times')
        self.assertIn('3 times', self.notices[0])
        self.assertFalse(pf.status(s, now=T0 + 300)['active'])
        self.assertTrue(pf.status(s, now=T0 + 300)['asked_today'])

    def test_off_mode_is_silent(self):
        s = settings(llm_paid_fallback_mode='off')
        for i in range(3):
            pf.note_throttle(s, now=T0 + i)
        self.assertEqual(self.notices, [])
        self.assertFalse(pf.status(s, now=T0 + 3)['active'])

    def test_no_paid_key_means_nothing_happens(self):
        s = settings(llm_paid_fallback_mode='auto', llm_gemini_paid_api_key='')
        for i in range(3):
            pf.note_throttle(s, now=T0 + i)
        self.assertEqual(self.notices, [])
        self.assertFalse(pf.status(s, now=T0 + 3)['active'])
        self.assertFalse(pf.status(s, now=T0 + 3)['configured'])

    def test_the_threshold_is_a_setting(self):
        s = settings(llm_paid_fallback_mode='auto', llm_paid_fallback_failures=5)
        for i in range(4):
            pf.note_throttle(s, now=T0 + i)
        self.assertFalse(pf.status(s, now=T0 + 4)['active'])
        pf.note_throttle(s, now=T0 + 5)
        self.assertTrue(pf.status(s, now=T0 + 5)['active'])

    # --- while active ---------------------------------------------------------

    def test_active_fallback_runs_the_chain_on_the_paid_key_and_counts(self):
        s = settings()
        pf.activate(s, now=T0, by='parent')
        seen, req = self.keys_seen(overloaded_on_free)
        with patch('services.llm._call_llm_json', req), patch.object(pools.time, 'time', return_value=T0 + 1):
            res = self.call(s=s)
        self.assertTrue(res.get('ok'))
        self.assertEqual(seen, [PAID], f'an active fallback should go straight to the paid key: {seen}')
        self.assertEqual(pf.status(s, now=T0 + 1)['used_today'], 1)

    def test_the_cap_switches_it_off(self):
        s = settings(llm_paid_fallback_daily_cap=2)
        pf.activate(s, now=T0, by='parent')
        seen, req = self.keys_seen(overloaded_on_free)
        with patch('services.llm._call_llm_json', req):
            for i in range(3):
                with patch.object(pools.time, 'time', return_value=T0 + 1 + i):
                    res = self.call(s=s)
        self.assertEqual(seen.count(PAID), 2, f'the cap did not hold: {seen}')
        self.assertIn('error', res, 'the third call should have fallen back to the free chain and failed')
        st = pf.status(s, now=T0 + 4)
        self.assertFalse(st['active'])
        self.assertEqual(st['used_today'], 2)
        self.assertIn('cap', (res.get('error') or '').lower())

    def test_cooldowns_are_per_key_class(self):
        s = settings()
        pools.note_failure('gemini-lite-a', 'HTTP Error 503', paid=False)
        with patch.object(pools.time, 'time', return_value=T0):
            self.assertNotEqual(pools.models_for('interactive', s)[0], 'gemini-lite-a')
            self.assertEqual(pools.models_for('interactive', s, paid=True)[0], 'gemini-lite-a')

    def test_it_ends_at_the_households_midnight(self):
        s = settings()
        until = pf.activate(s, now=T0, by='parent')
        local = datetime.datetime.fromtimestamp(T0).astimezone()
        midnight = (local + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        self.assertEqual(int(until), int(midnight.timestamp()))
        self.assertTrue(pf.status(s, now=until - 1)['active'])
        self.assertFalse(pf.status(s, now=until + 1)['active'])

    def test_a_parent_can_switch_it_off_early(self):
        s = settings()
        pf.activate(s, now=T0, by='parent')
        pf.deactivate()
        self.assertFalse(pf.status(s, now=T0 + 1)['active'])

    def test_usage_resets_with_the_day(self):
        s = settings(llm_paid_fallback_daily_cap=1)
        pf.activate(s, now=T0, by='parent')
        self.assertTrue(pf.count_call(s, now=T0 + 1))
        self.assertFalse(pf.count_call(s, now=T0 + 2), 'the cap let a second call through')
        tomorrow = pf.activate(s, now=T0 + 86400, by='parent')
        self.assertGreater(tomorrow, T0 + 86400)
        self.assertEqual(pf.status(s, now=T0 + 86400)['used_today'], 0)

    # --- the router's own loop ------------------------------------------------

    def test_the_chat_router_uses_the_fallback_too(self):
        """call_gemma_with_fallback iterates models_for itself rather than
        going through call_pool_json: the swap has to reach it."""
        from services import agent_router
        s = settings(llm_paid_fallback_mode='auto')
        pf.note_throttle(s, now=T0 - 60)
        pf.note_throttle(s, now=T0 - 30)
        seen = []

        def req(provider, url, key, model, *a, **kw):
            seen.append(key)
            if key == FREE:
                raise RuntimeError('HTTP Error 503: Service Unavailable')
            return {'message': 'hi', 'tool_calls': []}
        with patch.object(agent_router, '_call_llm_json', req), \
                patch('services.storage.get_settings', lambda: s), \
                patch.object(pools.time, 'time', return_value=T0):
            res = agent_router.call_gemma_with_fallback('hello', [], 'sys')
        self.assertEqual(res.get('message'), 'hi', f'the router did not reach the paid key: {res} {seen}')
        self.assertEqual(seen[-1], PAID)
        self.assertTrue(pf.status(s, now=T0)['active'])


class SettingsAndStatusTests(unittest.TestCase):
    def test_the_three_settings_are_declared(self):
        from services import settings_registry
        keys = {e['key']: e for e in settings_registry.ENTRIES}
        for k in ('llm_paid_fallback_mode', 'llm_paid_fallback_failures', 'llm_paid_fallback_daily_cap'):
            self.assertIn(k, keys, f'{k} is not a declared setting')
            self.assertEqual(keys[k]['group'], 'ai')

    def test_status_shape(self):
        pf.reset()
        st = pf.status(settings(), now=T0)
        for k in ('configured', 'mode', 'threshold', 'failures_recent', 'active', 'until',
                  'used_today', 'cap', 'asked_today', 'activated_by'):
            self.assertIn(k, st, f'status lacks {k}')
        self.assertEqual(st['mode'], 'ask')
        self.assertEqual(st['threshold'], 3)
        self.assertEqual(st['cap'], 300)


if __name__ == '__main__':
    unittest.main()
