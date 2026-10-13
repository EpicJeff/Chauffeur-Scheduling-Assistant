"""Phone enrollment: five taps through the shipped recorder, no transcript, no agent."""
import io, os, sys, tempfile, time, unittest, uuid, wave
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_phone_enroll_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_setup, app_voice_audio
from starlette.requests import Request
from fastapi import HTTPException
import main


def vector(index=0):
    return fp.normalized([float(i == index) for i in range(256)])


def wav(seconds=8):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\x10\x00' * 16000 * seconds)
    return buf.getvalue()


class PhoneEnrollmentTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.chat_channels_table, storage.chat_messages_table):
            table.truncate()
        fp._enrollments.clear(); fp._save([]); voice_setup._dialogs.clear()
        storage.get_settings = lambda: {'auth_enforce': False, 'calendar_ids': [], 'service_token': 'service'}
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'}); storage.set_member_pin('jeff', '1234')
        storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
        self.jeff = storage.create_member_token('jeff'); self.lily = storage.create_member_token('lily')
        patch.object(fp, 'model_ready', return_value=True).start()
        self.voices = [vector(0)] * 10
        patch.object(fp, 'extract', lambda audio, metadata, enrollment=False: (self.voices.pop(0), 8.0)).start()
        patch.object(app_voice_audio, 'speak', lambda text: (b'ID3fake', 'audio/mpeg')).start()
        self.addCleanup(patch.stopall)

    def request(self, token, body=b'', content_type='audio/wav'):
        return Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                        'headers': [(b'x-member-token', token.encode()), (b'content-type', content_type.encode())]})

    def test_an_adult_enrolls_in_five_uploads_with_no_transcript_and_no_agent(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        self.assertEqual((start['step'], start['total']), (1, 5)); self.assertEqual(start['question'], fp.QUESTIONS[0])
        token = start['token']
        with patch('services.agent_router.process_agent_request', side_effect=AssertionError('agent ran')), \
                patch.object(app_voice_audio, 'transcribe', side_effect=AssertionError('transcribed')):
            for step in range(5):
                out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], token, wav(), 'audio/wav')
                if step < 4:
                    self.assertEqual(out['status'], 'accepted', out); self.assertEqual(out['step'], step + 2); token = out['token']
        self.assertEqual(out['status'], 'done'); self.assertIn('check my voice', out['message'])
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['provenance']), ('jeff', 'phone'))
        self.assertEqual(storage.chat_messages_table.all(), [], 'an enrollment answer landed in chat')

    def test_a_reused_step_token_is_refused(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        first = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'], wav(), 'audio/wav')
        self.assertEqual(first['status'], 'accepted')
        again = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'], wav(), 'audio/wav')
        self.assertEqual(again['status'], 'retry'); self.assertEqual(again['token'], first['token'])
        self.assertEqual(fp._enrollments[('phone', 'jeff')]['step'], 1)

    def test_a_child_needs_a_parents_pin_entered_on_their_screen(self):
        with self.assertRaises(HTTPException) as caught:
            main.phone_enroll_start({}, self.request(self.lily))
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            main.phone_enroll_start({'parent_id': 'jeff', 'parent_pin': '0000'}, self.request(self.lily))
        start = main.phone_enroll_start({'parent_id': 'jeff', 'parent_pin': '1234'}, self.request(self.lily))
        self.assertEqual(start['step'], 1)
        self.assertEqual(fp._enrollments[('phone', 'lily')]['consent_actor'], 'jeff')
        self.assertEqual(voice._sessions, {}, 'a parent session was created by phone consent')

    def test_a_short_answer_asks_again_and_a_different_voice_ends_it(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        with patch.object(fp, 'extract', lambda *a, **k: (vector(0), 2.0)):
            out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'], wav(2), 'audio/wav')
        self.assertEqual(out['status'], 'retry'); self.assertIn('longer', out['message'].lower()); self.assertEqual(out['step'], 1)
        out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], out['token'], wav(), 'audio/wav')
        self.assertEqual(out['status'], 'accepted')
        self.voices[0] = vector(7)
        out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], out['token'], wav(), 'audio/wav')
        self.assertEqual(out['status'], 'ended')

    def test_the_question_can_be_heard_and_the_flow_cancelled(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        res = main.phone_enroll_speech(start['enrollment_id'], self.request(self.jeff))
        self.assertEqual(res.media_type, 'audio/mpeg')
        self.assertEqual(main.phone_enroll_cancel(self.request(self.jeff))['status'], 'ended')
        self.assertNotIn(('phone', 'jeff'), fp._enrollments)

    def test_a_member_deletes_their_own_voice(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        for _ in range(5):
            out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'] if _ == 0 else out['token'], wav(), 'audio/wav')
        self.assertEqual(len(fp.profiles()), 1)
        self.assertEqual(main.phone_voice_profile_delete(self.request(self.jeff))['status'], 'deleted')
        self.assertEqual(fp.profiles(), [])
        with self.assertRaises(HTTPException):
            main.phone_voice_profile_delete(self.request(storage.create_member_token('jeff', house_session=True)))

    def test_only_a_personal_session_may_enroll(self):
        house = storage.create_member_token('jeff', house_session=True)
        with self.assertRaises(HTTPException):
            main.phone_enroll_start({}, self.request(house))

    def test_the_routes_are_classified(self):
        from services import auth
        for m, p in (('POST', '/api/app-voice/enroll'), ('GET', '/api/app-voice/enroll'), ('DELETE', '/api/app-voice/enroll'),
                     ('POST', '/api/app-voice/enroll/{enrollment_id}/audio'), ('GET', '/api/app-voice/enroll/{enrollment_id}/speech')):
            self.assertEqual(auth.resolve(m, p), auth.SIGNED_IN, f'{m} {p}')


if __name__ == '__main__':
    unittest.main()
