"""Interactive timeout recovery, cooldowns and bounded voice fallback."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness import storage
from services import agent_router, app_voice, model_pools

SETTINGS = {'llm_gemini_api_key': 'offline',
            'model_pool_lite': 'gemini-a-flash-lite,gemini-b-flash-lite,gemini-c-flash-lite',
            'model_pool_gemma': 'gemma-slow'}


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        model_pools.reset_cooldowns()
        settings = patch.object(storage, 'get_settings', return_value=SETTINGS)
        settings.start()
        self.addCleanup(settings.stop)
        self.addCleanup(model_pools.reset_cooldowns)

    def call(self):
        return agent_router.call_gemma_with_fallback('Hello', [], 'System')

    def test_timeout_rotates_and_next_turn_skips_sick_model(self):
        seen = []
        def provider(*args, **kwargs):
            seen.append(args[3])
            if args[3] == 'gemini-a-flash-lite':
                raise RuntimeError('Gemini request failed: The read operation timed out')
            return {'message': 'Hello'}
        with patch.object(agent_router, '_call_llm_json', provider):
            self.assertEqual(self.call()['message'], 'Hello')
            self.assertEqual(self.call()['message'], 'Hello')
        self.assertEqual(seen, ['gemini-a-flash-lite', 'gemini-b-flash-lite', 'gemini-b-flash-lite'])

    def test_phone_respects_cooldown_without_slow_fallback(self):
        model_pools.note_failure('gemini-a-flash-lite', 'HTTP 503')
        marker = app_voice.current.set(SimpleNamespace(remaining=lambda: 30))
        self.addCleanup(app_voice.current.reset, marker)
        with patch.object(agent_router, '_call_llm_json', return_value={'message': 'Hello'}) as provider:
            self.call()
        self.assertEqual(provider.call_args.args[3], 'gemini-b-flash-lite')
        self.assertLessEqual(provider.call_args.kwargs['timeout_s'], 10)
        self.assertEqual(provider.call_args.kwargs['transient_retries'], 0)
        self.assertNotIn('gemma-slow', model_pools.models_for('interactive'))

    def test_standard_retry_is_bounded_without_repeating_provider_backoff(self):
        clock = [0]
        timeouts = []
        def provider(*args, **kwargs):
            timeouts.append(kwargs['timeout_s'])
            self.assertEqual(kwargs['transient_retries'], 0)
            clock[0] += kwargs['timeout_s']
            raise RuntimeError('The read operation timed out')
        with patch.object(agent_router, '_call_llm_json', provider), \
                patch('services.agent_router.time.monotonic', lambda: clock[0]):
            result = self.call()
        self.assertTrue(result['transient'])
        self.assertEqual(timeouts, [60, 40])

    def test_returned_timeout_recovers_but_credentials_do_not_retry(self):
        with patch.object(agent_router, '_call_llm_json', side_effect=[
                {'error': 'Request timeout'}, {'message': 'Recovered'}]) as provider:
            self.assertEqual(self.call()['message'], 'Recovered')
            self.assertEqual(provider.call_count, 2)
        with patch.object(agent_router, '_call_llm_json', side_effect=RuntimeError('HTTP 401 invalid API key')) as provider:
            self.assertIn('401', self.call()['error'])
            self.assertEqual(provider.call_count, 1)

    def test_cancelled_phone_never_launches_another_attempt(self):
        def stopped():
            raise app_voice.Stopped('Cancelled')
        marker = app_voice.current.set(SimpleNamespace(remaining=stopped))
        self.addCleanup(app_voice.current.reset, marker)
        with patch.object(agent_router, '_call_llm_json') as provider:
            with self.assertRaises(app_voice.Stopped):
                self.call()
            provider.assert_not_called()

    def test_exhausted_timeouts_report_temporary_failure_in_chat(self):
        with patch.object(agent_router, '_call_llm_json', side_effect=RuntimeError('The read operation timed out')):
            result = agent_router.process_agent_request('What is on the calendar?', source='family')
        self.assertEqual(result['status'], 'error')
        self.assertIn('overloaded', result['message'])
        self.assertIn('try again', result['message'].lower())
        self.assertNotIn('server logs', result['message'])

    def test_timeout_cooldown_expires_and_preserves_longer_quota_cooldown(self):
        with patch.object(model_pools.time, 'time', return_value=1000):
            model_pools.note_failure('gemini-a-flash-lite', 'The read operation timed out')
            self.assertEqual(model_pools.models_for('interactive')[0], 'gemini-b-flash-lite')
            model_pools.note_failure('gemini-b-flash-lite', '429 daily quota')
            until = model_pools._cooldowns['gemini-b-flash-lite']
            model_pools.note_failure('gemini-b-flash-lite', 'Request timeout')
            self.assertEqual(model_pools._cooldowns['gemini-b-flash-lite'], until)
        with patch.object(model_pools.time, 'time', return_value=1121):
            self.assertEqual(model_pools.models_for('interactive')[0], 'gemini-a-flash-lite')


if __name__ == '__main__':
    unittest.main()
