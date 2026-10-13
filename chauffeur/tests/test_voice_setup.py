"""The spoken enrollment dialog on a satellite, driven through the real converse
endpoint with a scripted fingerprint. Spec: 2026-10-13-voice-enrollment-design.md."""
import os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_setup_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_setup
from starlette.requests import Request
import main

KEY = ('ha', 'assist_satellite.kitchen')


def vector(index=0):
    return fp.normalized([float(i == index) for i in range(256)])


class SatelliteDialogTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear(); voice_setup._dialogs.clear()
        fp._save([])
        storage.get_settings = lambda: {'service_token': 'service', 'auth_enforce': False, 'calendar_ids': []}
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'}); storage.set_member_pin('jeff', '1234')
        storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device', 'enabled': True}])
        patch.object(fp, 'model_ready', return_value=True).start()
        self.addCleanup(patch.stopall)
        self.voices = []          # the fingerprint each next utterance carries
        self.conversation = 'conv-1'

        def consume(ctx, metadata, text=''):
            v = self.voices.pop(0) if self.voices else None
            pending = fp._enrollments.get(KEY) or {}
            return None if v is None else {'vector': v, 'seconds': 8, 'enrollment_id': pending.get('id')}
        patch.object(fp, 'consume', consume).start()

    def say(self, text, voice_vector=vector(0), conversation=None):
        self.voices.append(voice_vector)
        req = main.ConverseRequest(text=text, language='en', conversation_id=conversation or self.conversation,
                                   voice={'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                          'request_id': uuid.uuid4().hex, 'observed_at': time.time()})
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        out = main.converse_ha_assist(req, request)
        return out['response']['speech']['plain']['speech'], out['continue_conversation']

    def test_an_adult_enrolls_in_one_conversation_and_turns_recognition_on(self):
        speech, cont = self.say('set up my voice')
        self.assertIn('Who is this for', speech); self.assertTrue(cont)
        speech, cont = self.say("it's Jeff")
        self.assertIn('PIN', speech); self.assertTrue(cont)
        speech, cont = self.say('my PIN is one two three four')
        self.assertIn(fp.QUESTIONS[0], speech); self.assertTrue(cont)
        for q in fp.QUESTIONS[1:]:
            speech, cont = self.say('well today I did some things and then some more things')
            self.assertIn(q, speech); self.assertTrue(cont)
        speech, cont = self.say('and finally I am looking forward to the weekend')
        self.assertIn('saved here', speech.lower()); self.assertIn('Turn on voice recognition', speech); self.assertTrue(cont)
        speech, cont = self.say('yes')
        self.assertIn('on', speech.lower()); self.assertFalse(cont)
        self.assertTrue(next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == KEY[1])['recognition_enabled'])
        self.assertEqual([r['member_id'] for r in fp.profiles()], ['jeff'])
        self.assertFalse(voice_setup._dialogs)

    def test_a_child_is_enrolled_with_a_parents_pin_and_yes(self):
        self.say('set up my voice')
        speech, _ = self.say('for Lily')
        self.assertIn("parent's PIN", speech)
        speech, cont = self.say('my PIN is one two three four', vector(0))     # Jeff speaks
        self.assertIn(fp.QUESTIONS[0], speech); self.assertTrue(cont)
        for _ in range(5):
            speech, cont = self.say('I had cereal and then I went to school and played', vector(3))  # Lily speaks
        self.assertIn('Was that Lily', speech); self.assertTrue(cont)
        speech, cont = self.say('yes', vector(0))
        self.assertIn('Turn on voice recognition for Lily', speech)
        self.say('yes', vector(0))
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['consent_actor']), ('lily', 'jeff'))
        self.assertIsNone(voice._sessions.get(KEY, {}).get('member_id') if voice._sessions.get(KEY, {}).get('level') == 'verified' else None,
                          'the parent consent left a verified parent session')

    def test_the_parent_answering_for_the_child_ends_it(self):
        self.say('set up my voice'); self.say('for Lily'); self.say('my PIN is one two three four', vector(0))
        speech, cont = self.say('I will answer for her', vector(0))
        self.assertIn('parent', speech.lower()); self.assertFalse(cont)
        self.assertNotIn(KEY, fp._enrollments)

    def test_unrelated_speech_during_setup_never_reaches_the_agent(self):
        self.say('set up my voice'); self.say("it's Jeff"); self.say('my PIN is one two three four')
        with patch('services.agent_router.process_agent_request', side_effect=AssertionError('the agent ran')) as agent:
            speech, cont = self.say('cancel voice setup')
        self.assertEqual(speech, 'Voice setup cancelled.'); self.assertFalse(cont)
        self.assertFalse(agent.called)

    def test_continued_turn_with_unknown_conversation_id_is_still_admitted(self):
        self.say('set up my voice'); self.say("it's Jeff")
        speech, _ = self.say('my PIN is one two three four')
        self.assertIn(fp.QUESTIONS[0], speech)
        speech, cont = self.say('today I walked the dog and made breakfast for everyone', conversation=None)
        self.assertIn(fp.QUESTIONS[1], speech, 'an answer with no conversation id was refused')
        speech, cont = self.say('today I walked the dog and made breakfast for everyone', conversation='another-room')
        self.assertNotIn(fp.QUESTIONS[2], speech, 'an answer from a different known conversation was admitted')

    def test_check_my_voice_accepts_a_phone_template_here(self):
        fp._save([{'member_id': 'jeff', 'key': ['phone', 'jeff'], 'vector': vector(0), 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': {}, 'calibrated': False,
                   'provenance': 'phone', 'device_id': 'phone'}])
        speech, cont = self.say('check my voice')
        self.assertIn('name', speech); self.assertTrue(cont)
        speech, cont = self.say("it's Jeff")
        self.assertIn('PIN', speech); self.assertTrue(cont)
        speech, cont = self.say('my PIN is one two three four')
        self.assertIn(fp.CHECK_QUESTION, speech); self.assertTrue(cont)
        speech, cont = self.say('this morning I made coffee and read the news for a while')
        self.assertIn('works here', speech.lower()); self.assertIn('Turn on voice recognition', speech)
        self.assertTrue(fp.checked_on(fp.profiles()[0], KEY))

    def test_check_my_voice_that_misses_offers_setup_here_keeping_the_answer(self):
        fp._save([{'member_id': 'jeff', 'key': ['phone', 'jeff'], 'vector': vector(9), 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': {}, 'calibrated': False,
                   'provenance': 'phone', 'device_id': 'phone'}])
        self.say('check my voice'); self.say("it's Jeff"); self.say('my PIN is one two three four')
        speech, cont = self.say('this morning I made coffee and read the news for a while')
        self.assertIn('does not match', speech.lower()); self.assertIn('set up your voice here', speech.lower()); self.assertTrue(cont)
        speech, cont = self.say('yes')
        self.assertIn(fp.QUESTIONS[1], speech, 'the check answer was not kept as sample 1')
        self.assertEqual(len(fp._enrollments[KEY]['samples']), 1)

    def test_an_enrollment_started_from_config_is_adopted_by_the_first_utterance(self):
        """The Config page's Enroll button opens an enrollment with no dialog
        and no question. The first thing said to that satellite earns question
        1, and the flow continues by voice from there."""
        fp.begin(voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                'request_id': 'r', 'observed_at': time.time()}, True), 'jeff', 'jeff')
        speech, cont = self.say("I'm ready")
        self.assertIn(fp.QUESTIONS[0], speech); self.assertTrue(cont)
        for q in fp.QUESTIONS[1:]:
            speech, cont = self.say('today I did a few things around the house and then rested')
            self.assertIn(q, speech)
        speech, cont = self.say('I am looking forward to the weekend quite a lot')
        self.assertIn('saved here', speech.lower())
        self.assertIn('Turn on voice recognition', speech, 'the consenting parent was not offered the switch')

    def test_an_open_dialog_admits_satellite_audio_before_any_enrollment_exists(self):
        """The PIN turn's fingerprint is the enrollment's anchor and the
        check's answer is scored against the phone template: both arrive
        before an enrollment exists and while recognition is off, so the
        observation gate must admit them while a dialog is open."""
        import asyncio
        self.say('check my voice')
        ctx = voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                             'request_id': 'r-open', 'observed_at': time.time()}, True)
        with patch.object(fp, 'extract', return_value=(vector(0), 6.0)):
            result = asyncio.run(fp.observe(b'audio', {'run_id': 'run', 'utterance_id': 'r-open', 'device_id': 'device'}, ctx))
        self.assertIn('observation_id', result)
        voice_setup._dialogs.clear()
        with self.assertRaises(ValueError):
            asyncio.run(fp.observe(b'audio', {'run_id': 'run2', 'utterance_id': 'r-closed', 'device_id': 'device'},
                                   voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                                  'request_id': 'r-closed', 'observed_at': time.time()}, True)))

    def test_turn_on_recognition_by_name_is_a_parent_act(self):
        fp.begin(voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                'request_id': 'r', 'observed_at': time.time()}, True), 'lily', 'jeff', exclude=vector(0))
        for _ in range(5):
            a = fp.ask(KEY); fp.answer(KEY, {'vector': vector(3), 'seconds': 8, 'enrollment_id': fp._enrollments[KEY]['id']}, token=a['token'])
        fp.confirm(KEY, True)
        speech, cont = self.say('turn on voice recognition for Lily here')
        self.assertIn('PIN', speech)
        self.say("it's Jeff")
        speech, cont = self.say('my PIN is one two three four')
        self.assertIn('on', speech.lower())
        self.assertTrue(next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == KEY[1])['recognition_enabled'])


if __name__ == '__main__':
    unittest.main()
