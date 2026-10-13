"""Personal voice authority, private projection, cancellation and bounded speech."""
import asyncio
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
import wave
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_phone_voice_test_')
from harness import check
from services import storage, app_voice as voice, app_voice_audio as audio, agent_router, model_pools
from starlette.requests import Request
from fastapi import HTTPException
import main


class PhoneTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.chat_channels_table,
                      storage.chat_messages_table, storage.app_state_table, storage.shopping_lists_table,
                      storage.shopping_items_table):
            table.truncate()
        voice._turns.clear()
        storage.get_settings = lambda: {'auth_enforce': False, 'calendar_ids': [], 'missions_enabled': False,
                                       'llm_gemini_api_key': 'fake', 'model_pool_lite': 'gemini-test-flash-lite',
                                       'model_pool_gemma': 'gemma-slow', 'ha_base_url': ''}
        storage.add_member({'id': 'parent', 'name': 'Jeff', 'role': 'parent'})
        storage.add_member({'id': 'kid', 'name': 'Alex', 'role': 'child'})
        self.token = storage.create_member_token('parent')
        self.kid_token = storage.create_member_token('kid')
        storage.set_cached_schedule({'events': []})
        fanout = patch.object(main, '_fanout_message_notifications', return_value=None)
        fanout.start(); self.addCleanup(fanout.stop)

    def request(self, token=None, extra=()):
        return Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                        'headers': [(b'x-member-token', (token or self.token).encode()), *extra]})

    def turn(self, text='What is on the calendar?', token=None):
        token = token or self.token
        member = storage.get_member_by_token(token)
        row = voice.begin(member, token, uuid.uuid4().hex)
        row.text(text)
        return row

    def test_actual_personal_token_required_even_in_audit_mode(self):
        house = storage.create_member_token('parent', house_session=True)
        for token in ('invalid', house):
            with self.assertRaises(HTTPException):
                main.phone_voice_start({'request_id': uuid.uuid4().hex}, self.request(token))
        with self.assertRaises(HTTPException):
            main.phone_voice_start({'request_id': uuid.uuid4().hex},
                                  self.request(extra=((b'x-ingress-path', b'/ingress'),)))
        result = main.phone_voice_start({'request_id': uuid.uuid4().hex, 'member_id': 'parent'}, self.request(self.kid_token))
        self.assertEqual(set(result['channel']['member_ids']), {'kid', 'argyle'})

    def test_another_persons_dm_cannot_supply_context(self):
        channel = storage.get_or_create_dm('kid', 'argyle')
        with self.assertRaises(PermissionError):
            voice.begin(storage.get_member('parent'), self.token, uuid.uuid4().hex, channel['id'])

    def test_private_request_runs_once_and_full_answer_stays_on_screen(self):
        row = self.turn('What are my points?')
        replies = [{'tool_calls': [{'name': 'get_point_balances', 'arguments': {}}]},
                   {'message': 'PRIVATE balance is 17.'}]
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=replies), \
                patch('services.agent_tools_v2.get_point_balances', return_value={'status': 'success', 'message': 'PRIVATE balance is 17.'}) as tool:
            result = main.phone_voice_run(row.id, self.request())
        self.assertEqual(tool.call_count, 1)
        self.assertIn('PRIVATE', result['reply'])
        self.assertEqual(result['speech'], voice.DISPLAY_ONLY)
        stored = storage.get_channel_messages(row.channel['id'])
        self.assertIn('PRIVATE', stored[-1]['body'])
        with patch.object(audio, 'speak', return_value=(b'audio', 'audio/wav')) as synth:
            main.phone_voice_speech(row.id, self.request())
        synth.assert_called_once_with(voice.DISPLAY_ONLY)
        with self.assertRaises(HTTPException): main.phone_voice_run(row.id, self.request())
        with self.assertRaises(ValueError): voice.begin(row.member, self.token, row.id, row.channel['id'])

    def test_shared_result_is_spoken_with_real_typed_actor(self):
        row = self.turn('Calendar please')
        replies = [{'tool_calls': [{'name': 'get_calendar_events', 'arguments': {'start_date': '2026-10-13', 'end_date': '2026-10-13'}}]},
                   {'message': 'Soccer is at four.'}]
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=replies), \
                patch.object(agent_router, 'get_calendar_events', return_value={'status': 'success', 'events': []}):
            result = main.phone_voice_run(row.id, self.request())
        self.assertTrue(result['speech_safe'])
        self.assertEqual(result['speech'], 'Soccer is at four.')
        self.assertEqual(storage.get_channel_messages(row.channel['id'])[0]['sender_member_id'], 'parent')

    def test_whitelisted_typed_calendar_with_private_rows_is_display_only(self):
        storage.set_cached_schedule({'events': [{'id': 'private', 'title': 'Secret', 'visibility': 'private'}]})
        row = self.turn()
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=[
                {'tool_calls': [{'name': 'get_calendar_events', 'arguments': {}}]}, {'message': 'Secret appointment.'}]), \
                patch.object(agent_router, 'get_calendar_events', return_value={'status': 'success', 'events': [{'title': 'Secret'}]}):
            result = main.phone_voice_run(row.id, self.request())
        self.assertEqual(result['speech'], voice.DISPLAY_ONLY)

    def test_private_history_and_no_tool_answer_cannot_become_audible(self):
        row = self.turn('Read that again')
        from services.agent_tools_v2 import _post_chat_message
        _post_chat_message(row.channel, row.member, 'Private earlier text')
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={'message': 'Private earlier text'}):
            result = main.phone_voice_run(row.id, self.request())
        self.assertEqual(result['speech'], voice.DISPLAY_ONLY)

    def test_shared_question_after_private_answer_can_speak_without_private_history(self):
        from services.agent_tools_v2 import _post_chat_message
        row = self.turn('Calendar please')
        _post_chat_message(row.channel, storage.ensure_argyle_member(), 'PRIVATE old answer', phone_speech_safe=False)
        seen = []
        def model(prompt, tools, system):
            seen.append(system)
            if len(seen) == 1:
                return {'tool_calls': [{'name': 'get_calendar_events', 'arguments': {}}]}
            return {'message': 'Shared soccer schedule.'}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=model), \
                patch.object(agent_router, 'get_calendar_events', return_value={'status': 'success', 'events': []}):
            result = main.phone_voice_run(row.id, self.request())
        self.assertEqual(result['speech'], 'Shared soccer schedule.')
        self.assertTrue(all('PRIVATE old answer' not in text for text in seen))

    def test_client_context_cannot_forge_shared_history(self):
        row = self.turn()
        from services.agent_tools_v2 import _post_chat_message
        _post_chat_message(row.channel, row.member, 'Private typed text', context={'phone_speech_safe': True})
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={'message': 'Private typed text'}):
            result = main.phone_voice_run(row.id, self.request())
        self.assertEqual(result['speech'], voice.DISPLAY_ONLY)

    def test_replay_is_rejected_after_transient_turns_are_cleared(self):
        row = self.turn()
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={'message': 'Hello'}):
            main.phone_voice_run(row.id, self.request())
        voice._turns.clear()
        with self.assertRaises(ValueError): voice.begin(row.member, self.token, row.id, row.channel['id'])

    def test_child_model_cannot_dispatch_an_unoffered_admin_action(self):
        row = self.turn('Reassign all drivers', self.kid_token)
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=[
                {'tool_calls': [{'name': 'add_routing_rule', 'arguments': {}}]}, {'message': 'That needs a parent.'}]), \
                patch.object(agent_router, 'execute_tool') as assign:
            result = main.phone_voice_run(row.id, self.request(self.kid_token))
        assign.assert_not_called()
        self.assertEqual(result['speech'], voice.DISPLAY_ONLY)

    def test_credentials_never_reach_worker_or_message_history(self):
        for text in ('My PIN is 1234', 'one two three four', 'My password is secret'):
            row = self.turn(text)
            with patch.object(main, '_run_argyle_mention') as worker:
                result = main.phone_voice_run(row.id, self.request())
            worker.assert_not_called()
            self.assertEqual(row.transcript, '[Credential withheld]')
            self.assertNotIn(text, str(storage.get_channel_messages(row.channel['id'])))
            self.assertNotIn('1234', result['speech'])

    def test_cancel_after_model_before_tool_does_not_mutate(self):
        row = self.turn('Add milk')
        def model(*args):
            main.phone_voice_cancel(row.id, self.request())
            return {'tool_calls': [{'name': 'add_shopping_items', 'arguments': {'items': 'milk'}}]}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=model):
            with self.assertRaises(HTTPException): main.phone_voice_run(row.id, self.request())
        self.assertEqual(storage.shopping_items_table.all(), [])
        with self.assertRaises(HTTPException): main.phone_voice_speech(row.id, self.request())

    def test_revoke_and_new_turn_cancel_before_dispatch(self):
        row = self.turn()
        self.turn('A new question')
        with self.assertRaises(voice.Stopped): row.check()
        active = self.turn()
        storage.update_member('parent', {'status': 'disabled'})
        with self.assertRaises(voice.Stopped): active.check()

    def test_phone_models_are_lite_only_and_bounded_without_changing_text(self):
        row = self.turn(); row.deadline = time.monotonic() + 6
        marker = voice.current.set(row)
        try:
            self.assertEqual(model_pools.models_for('heavy'), ['gemini-test-flash-lite'])
            with patch.object(agent_router, '_call_llm_json', return_value={'message': 'Hello'}) as provider:
                agent_router.call_gemma_with_fallback('Hello', [], 'System')
            self.assertLessEqual(provider.call_args.kwargs['timeout_s'], 4)
            self.assertEqual(provider.call_args.kwargs['transient_retries'], 0)
            from services import llm
            self.assertIn('error', llm._call_llm_json('gemini', '', '', 'gemma-slow', '', ''))
        finally:
            voice.current.reset(marker)
        self.assertIn('gemma-slow', model_pools.models_for('interactive'))


class AudioTests(unittest.TestCase):
    def wav(self, seconds=1):
        out = io.BytesIO()
        with wave.open(out, 'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
            handle.writeframes(b'\x01\x00' * int(16000 * seconds))
        return out.getvalue()

    def test_raw_wav_and_limits(self):
        self.assertEqual(len(audio.pcm(self.wav(), 'audio/wav')), 32000)
        for content, mime in ((self.wav(16), 'audio/wav'), (b'x', 'text/plain'), (b'x' * (audio.MAX_UPLOAD + 1), 'audio/mp4')):
            with self.assertRaises(ValueError): audio.pcm(content, mime)

    def test_decoder_uses_pipes_and_no_network_protocol(self):
        from types import SimpleNamespace
        with patch.object(audio.shutil, 'which', return_value='ffmpeg'), \
                patch.object(audio.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'\0\0' * 16000)) as decode:
            audio.pcm(b'encoded', 'audio/mp4')
        args = decode.call_args.args[0]
        self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'pipe')
        self.assertEqual(decode.call_args.kwargs['input'], b'encoded')

    def test_tts_uses_server_owned_text_and_rejects_external_path(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.json.return_value = {'path': 'https://evil.example/private'}
        with patch.object(audio, 'pipeline', return_value={'tts_engine': 'tts.cloud', 'language': 'en'}), \
                patch.object(audio, '_request', return_value=response) as request:
            with self.assertRaises(ValueError): audio.speak(voice.DISPLAY_ONLY)
        self.assertEqual(request.call_args.kwargs['json']['message'], voice.DISPLAY_ONLY)
        self.assertFalse(request.call_args.kwargs['json']['cache'])

    def test_transcription_uses_actual_ha_contract_without_a_fake_satellite(self):
        from unittest.mock import MagicMock
        def response(data):
            value = MagicMock(); value.__enter__.return_value = value; value.json.return_value = data
            return value
        support = {'formats': ['wav'], 'codecs': ['pcm'], 'sample_rates': [16000], 'bit_rates': [16], 'channels': [1]}
        with patch.object(audio, 'pipeline', return_value={'stt_engine': 'stt.chauffeur_voice_recognition', 'stt_language': 'en-US'}), \
                patch.object(audio, '_request', side_effect=[response(support), response({'result': 'success', 'text': 'Calendar please'})]) as request:
            self.assertEqual(audio.transcribe(self.wav(), 'audio/wav'), 'Calendar please')
        posted = request.call_args
        self.assertEqual(posted.args, ('POST', '/stt/stt.chauffeur_voice_recognition'))
        self.assertEqual(len(posted.kwargs['data']), 32000)
        self.assertIn('language=en-US', posted.kwargs['headers']['X-Speech-Content'])
        self.assertNotIn('satellite', str(posted.kwargs['headers']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
