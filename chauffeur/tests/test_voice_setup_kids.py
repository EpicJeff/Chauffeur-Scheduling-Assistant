"""A child's voice set up by talking: the parent's PIN, quick questions pooled
into samples, "Is that Lily talking?", the parent's PIN again at the end.
Driven through the real converse endpoint with scripted fingerprints and
per-utterance voiced seconds. Spec: 2026-10-13-kid-voice-enrollment-design.md."""
import os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_kids_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_setup
from starlette.requests import Request
import main

KEY = ('ha', 'assist_satellite.kitchen')


def vector(index=0):
    return fp.normalized([float(i == index) for i in range(256)])


JEFF, LILY, SAM = vector(0), vector(3), vector(5)
PIN = 'my PIN is one two three four'


class KidDialogTests(unittest.TestCase):
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
        self.evidence = []        # (vector or None, voiced seconds) for each next utterance
        self.conversation = 'conv-1'

        def consume(ctx, metadata, text=''):
            v, seconds = self.evidence.pop(0) if self.evidence else (None, 0)
            pending = fp._enrollments.get(KEY) or {}
            return None if v is None else {'vector': v, 'seconds': seconds, 'enrollment_id': pending.get('id')}
        patch.object(fp, 'consume', consume).start()

    def say(self, text, v=JEFF, seconds=3, conversation=None):
        self.evidence.append((v, seconds))
        req = main.ConverseRequest(text=text, language='en', conversation_id=conversation or self.conversation,
                                   voice={'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                          'request_id': uuid.uuid4().hex, 'observed_at': time.time()})
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        out = main.converse_ha_assist(req, request)
        return out['response']['speech']['plain']['speech'], out['continue_conversation']

    def start_lily(self):
        speech, cont = self.say("set up Lily's voice")
        self.assertIn("parent's PIN", speech); self.assertTrue(cont)
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertIn("Hi Lily. I'm going to ask you some questions. Just answer out loud.", speech)
        self.assertIn(fp.kid_question(0), speech); self.assertTrue(cont)
        return speech

    def pool(self, v=LILY, seconds=1.5, count=3):
        speech = cont = None
        for _ in range(count):
            speech, cont = self.say('blue because it is the sky', v, seconds)
        return speech, cont

    def test_a_child_is_set_up_with_quick_questions_and_the_parents_pin_twice(self):
        self.start_lily()
        speech, cont = self.say('blue because it is the sky', LILY, 1.5)
        self.assertTrue(speech.startswith('Nice. ')); self.assertIn(fp.kid_question(1), speech); self.assertTrue(cont)
        speech, cont = self.say('pizza', LILY, 1.5)
        self.assertIn(fp.kid_question(2), speech)
        speech, cont = self.say('the swings', LILY, 1.5)
        self.assertEqual(speech, 'Is that Lily talking? Say yes.'); self.assertTrue(cont)
        speech, cont = self.say('yes', JEFF, .5)
        self.assertTrue(speech.startswith('Great. ')); self.assertIn(fp.kid_question(3), speech); self.assertTrue(cont)
        for pool in range(3):                  # pools 2, 3, 4
            speech, cont = self.pool()
            self.assertTrue(cont)
        self.assertTrue(speech.startswith('Almost done! '), speech)
        speech, cont = self.pool()             # pool 5
        self.assertEqual(speech, 'All done! If that was Lily, say your PIN.'); self.assertTrue(cont)
        self.assertEqual(fp.profiles(), [])
        speech, cont = self.say('yes', JEFF, .5)
        self.assertEqual(speech, 'Say your PIN.'); self.assertTrue(cont)
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertIn('saved', speech.lower()); self.assertIn('Turn on voice recognition for Lily', speech); self.assertTrue(cont)
        speech, cont = self.say('yes', JEFF, .5)
        self.assertEqual(speech, 'Voice recognition is on.'); self.assertFalse(cont)
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['consent_actor'], row['pooled']), ('lily', 'jeff', True))
        self.assertFalse(voice_setup._dialogs)
        session = voice._sessions.get(KEY, {})
        self.assertFalse(session.get('level') == 'verified' and session.get('member_id') == 'jeff', 'the closing PIN left a parent session')

    def test_follow_ups_are_asked_once_the_list_is_spent(self):
        self.start_lily()
        self.pool(seconds=1.0, count=4)
        self.say('yes', JEFF, .5)
        for _ in range(2):
            self.pool(seconds=1.0, count=4)
        speech, _ = self.pool(seconds=1.0, count=3)   # the 15th admitted answer
        self.assertIn(fp.kid_question(15), speech)
        self.assertIn('Tell me more about your favorite color.', speech)

    def test_the_closing_pin_must_be_the_consenting_parents_voice(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say(PIN, LILY, 3)
        self.assertEqual(speech, 'That did not sound like the parent who gave consent. If that was Lily, say your PIN.'); self.assertTrue(cont)
        self.assertEqual(fp.profiles(), [])
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertIn('saved', speech.lower())

    def test_a_wrong_closing_pin_gets_one_more_try_then_nothing_is_saved(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say('my PIN is nine nine nine nine', JEFF, 3)
        self.assertIn('did not match', speech); self.assertIn('say your PIN', speech); self.assertTrue(cont)
        speech, cont = self.say('my PIN is nine nine nine nine', JEFF, 3)
        self.assertIn('Not saved', speech); self.assertFalse(cont)
        self.assertEqual(fp.profiles(), []); self.assertNotIn(KEY, fp._enrollments); self.assertFalse(voice_setup._dialogs)

    def test_a_parents_no_at_the_closing_question_saves_nothing(self):
        """Codex review of the dialog diff: requiring a PIN to approve must not
        remove the rejection path a parent had with "no"."""
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say('no, that was Sam', JEFF, 1.5)
        self.assertIn('Not saved', speech); self.assertFalse(cont)
        self.assertEqual(fp.profiles(), []); self.assertNotIn(KEY, fp._enrollments); self.assertFalse(voice_setup._dialogs)

    def test_the_closing_pin_and_the_activation_yes_answer_the_conversation_that_asked(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say(PIN, JEFF, 3, conversation='another-room')
        self.assertEqual(speech, 'If that was Lily, say your PIN.'); self.assertTrue(cont)
        self.assertEqual(fp.profiles(), [])
        speech, cont = self.say(PIN, JEFF, 3, conversation='another-room')   # the re-ask bound it here
        self.assertIn('Turn on voice recognition for Lily', speech)
        speech, cont = self.say('yes', JEFF, .5, conversation='conv-1')
        self.assertIn('Turn on voice recognition for Lily', speech); self.assertTrue(cont)
        speech, cont = self.say('yes', JEFF, .5, conversation='conv-1')
        self.assertEqual(speech, 'Voice recognition is on.')

    def test_a_pin_turn_without_a_fingerprint_asks_for_a_consent_line_first(self):
        self.say("set up Lily's voice")
        speech, cont = self.say(PIN, None)
        self.assertEqual(speech, "I need to hear your voice first. Say: I'm giving consent for Lily to set up a voice."); self.assertTrue(cont)
        self.assertNotIn(KEY, fp._enrollments, 'the enrollment started with no exclusion fingerprint')
        speech, cont = self.say("I'm giving consent for Lily to set up a voice", JEFF, 3)
        self.assertIn('Hi Lily', speech)
        self.assertEqual(fp.score(fp._enrollments[KEY]['exclude'], JEFF), 1.0)

    def test_three_consent_lines_without_a_fingerprint_end_it(self):
        self.say("set up Lily's voice"); self.say(PIN, None)
        self.say('consent', None); self.say('consent', None)
        speech, cont = self.say('consent', None)
        self.assertIn("couldn't hear you well enough", speech); self.assertFalse(cont)
        self.assertFalse(voice_setup._dialogs); self.assertNotIn(KEY, fp._enrollments)

    def test_a_sibling_answering_first_is_caught_by_the_parents_no(self):
        self.start_lily()
        speech, _ = self.pool(SAM)
        self.assertEqual(speech, 'Is that Lily talking? Say yes.')
        speech, cont = self.say('no', JEFF, .5)
        self.assertEqual(speech, "Not saved. Try again when it's just Lily."); self.assertFalse(cont)
        self.assertEqual(fp.profiles(), []); self.assertFalse(voice_setup._dialogs)

    def test_a_sibling_chiming_in_after_the_anchor_is_dropped(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        speech, cont = self.say('I want to answer too', SAM, 1.5)
        self.assertTrue(speech.startswith("Let's try another one. ")); self.assertIn(fp.kid_question(4), speech); self.assertTrue(cont)

    def test_chatter_at_is_that_lily_is_re_asked_and_never_pooled(self):
        self.start_lily(); self.pool()
        speech, cont = self.say('and I like purple too', LILY, 1.5)
        self.assertEqual(speech, 'Is that Lily talking? Yes or no?'); self.assertTrue(cont)
        pending = fp._enrollments[KEY]
        self.assertEqual((pending['pool'], pending['turns'], pending['step']), ([], 3, 1))
        speech, cont = self.say('and green', LILY, 1.5)
        self.assertEqual(speech, 'Is that Lily talking? Yes or no?')
        speech, cont = self.say('and yellow', LILY, 1.5)
        self.assertIn('Not saved', speech); self.assertFalse(cont)

    def test_stop_inside_a_sentence_is_an_answer(self):
        self.start_lily()
        speech, cont = self.say('I like to stop at the park', LILY, 1.5)
        self.assertIn(fp.kid_question(1), speech); self.assertTrue(cont)
        speech, cont = self.say("we're done", JEFF, .5)
        self.assertEqual(speech, 'Voice setup cancelled.'); self.assertFalse(cont)
        self.assertNotIn(KEY, fp._enrollments)

    def test_an_adult_can_ask_for_the_short_questions(self):
        speech, cont = self.say('set up my voice with the short questions')
        self.assertIn('Who is this for', speech)
        self.say("it's Jeff")
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertEqual(speech, f'Thanks. {fp.kid_question(0)}'); self.assertTrue(cont)
        speech, cont = self.pool(JEFF)
        self.assertTrue(speech.startswith('Good one. '), 'the PIN voice is the anchor; nobody is asked to name it')
        speech, cont = self.say('me too', SAM, 1.5)
        self.assertTrue(speech.startswith("Let's try another one. "))

    def test_a_config_started_child_enrollment_is_pooled_and_closes_with_the_pin(self):
        ctx = voice.VoiceContext('ha', KEY[1], '', '', service_revision=voice._revision(), paired=True)
        with patch.object(main, '_voice_parent', return_value=storage.get_member('jeff')):
            main.voice_recognition_enroll({'consent': True, 'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'member_id': 'lily'},
                                          Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'', 'headers': []}))
        self.assertTrue(fp._enrollments[KEY]['pooled'])
        speech, cont = self.say('hello', LILY, 1.5)
        self.assertIn(fp.kid_question(0), speech)
        self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say(PIN, JEFF, 3)    # no exclusion fingerprint: the PIN alone verifies the parent
        self.assertIn('saved', speech.lower())
        self.assertEqual(fp.profiles()[0]['member_id'], 'lily')


if __name__ == '__main__':
    unittest.main()
