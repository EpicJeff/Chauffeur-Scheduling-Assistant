"""Conversation mode on voice satellites (2026-11-04, approved in chat).

After a wake word the satellite keeps listening after every Argyle answer.
What closes the mic:
  - silence (HA's own no-speech timeout; nothing here),
  - an utterance that is ONLY a sign-off ("thanks", "that's all", "stop"...),
  - the cap: CAP (2) unrecognized turns in a row.
A turn is recognized when this utterance's voice matched a family member, or
when it was too short to identify and the satellite session still holds a
voice-recognized speaker that no longer sample contradicted. A long sample
that matches nobody counts toward the cap even when it does not clear the
session. A recognized turn resets the count; so does closing the mic and a
gap of GAP_SECONDS between turns (the next turn came from a new wake word).
A satellite without recognition counts every turn toward the cap (a PIN alone
never keeps the mic open: only a voice can break it). The household switch
settings.voice_conversation_mode (default on) turns the whole thing off.
Identity prompts (PIN, name, readback) keep reopening the mic exactly as
before, whatever the switch says.

Every scenario runs the real endpoint, main.converse_ha_assist; only the model
is stubbed.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_voice_conversation_mode.py
"""
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_conversation_mode_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp

KITCHEN = 'assist_satellite.kitchen'
BEDROOM = 'assist_satellite.bedroom'
SIGN_OFFS = ('thanks', 'Thanks.', 'thank you', 'Thank you!', "that's all", 'goodbye', 'bye',
             'never mind', 'Stop.', 'cancel',
             # Heard on the office satellite, 2026-11-04, and their close cousins: a
             # sign-off is every part of the utterance closing or filler.
             "That's all for now.", "No, I need you to stop. Don't listen anymore.",
             'Stop listening.', 'You can stop listening now.', "Okay, that's it.", "I'm done, thanks.",
             'No thanks.', 'No, thank you.', 'Thank you, Argyle.', 'Thanks so much!', 'Go to sleep.',
             "We're done here.", 'Nothing else.', "That'll be all.", 'Alright, goodbye.',
             'Good night, Argyle.', "Yes, that's all, thank you.")
NOT_SIGN_OFFS = ('thanks, and also add milk to the list', 'stop the music in the kitchen',
                 'cancel my dentist appointment on friday', "I'm done with the dishes, what's next?",
                 "that's all the milk we have?", "don't listen to him, add eggs",
                 'no, I said Tuesday', 'thank you for the reminder, what about Friday?')


def vector(index=0):
    return [float(i == index) for i in range(256)]


def uncertain():
    """A voice near Jeff's but not him: above DIFFERENT, below THRESHOLD."""
    a = 0.55
    v = [0.0] * 256
    v[0], v[1] = a, math.sqrt(1 - a * a)
    return v


class ConversationModeTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear()
        fp._save([])
        self.settings = {'service_token': 'service'}
        settings_patch = patch.object(storage, 'get_settings', side_effect=lambda: dict(self.settings))
        settings_patch.start(); self.addCleanup(settings_patch.stop)
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.set_member_pin('jeff', '1234')
        self.reply = 'Done.'
        agent = patch('services.agent_router.process_agent_request',
                      side_effect=lambda *a, **k: {'message': self.reply})
        self.agent = agent.start(); self.addCleanup(agent.stop)
        self.speaker = patch('services.announce.answer_through_speaker', return_value=None)
        self.speaker.start(); self.addCleanup(self.speaker.stop)
        from services import voice_conversation
        self.vc = voice_conversation
        voice_conversation._turns.clear()
        self.addCleanup(setattr, voice_conversation, 'GAP_SECONDS', voice_conversation.GAP_SECONDS)
        self.assertEqual(voice_conversation.CAP, 2)
        score = fp.score(uncertain(), vector(0))
        self.assertTrue(fp.DIFFERENT < score < fp.THRESHOLD, score)

    # --- fixtures ---------------------------------------------------------
    def satellite(self, satellite=KITCHEN, recognition=True):
        return {'ha_instance_id': 'ha', 'satellite_id': satellite, 'device_id': 'device-' + satellite,
                'enabled': True, 'recognition_enabled': recognition}

    def enroll(self, recognition=True, identity=True, satellites=(KITCHEN,)):
        if recognition:
            fp._save([{'member_id': 'jeff', 'key': ['ha', s], 'vector': vector(0), 'revision': fp.REVISION,
                       'consent_actor': 'jeff', 'created_at': time.time(), 'checks': 2, 'calibrated': True}
                      for s in satellites])
        voice.configure(identity, [self.satellite(s, recognition) for s in satellites])

    def say(self, text, voiceprint=None, seconds=6.0, satellite=KITCHEN, conversation='conv-1'):
        """One utterance through the real endpoint. voiceprint=None sends no
        audio evidence at all (an older component, or recognition off)."""
        import main
        from starlette.requests import Request
        request_id = uuid.uuid4().hex
        metadata = {'ha_instance_id': 'ha', 'satellite_id': satellite, 'device_id': 'device-' + satellite,
                    'request_id': request_id, 'utterance_id': request_id, 'run_id': 'run-' + request_id,
                    'observed_at': time.time()}
        if voiceprint is not None:
            ctx = voice.context(dict(metadata), True)
            oid = 'obs-' + request_id
            fp._observations[oid] = {'key': ('ha', satellite, 'device-' + satellite, 'run-' + request_id, request_id),
                                     'revision': ctx.service_revision, 'vector': voiceprint, 'seconds': seconds,
                                     'expires': time.time() + 60}
            metadata['observation_id'] = oid
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        result = main.converse_ha_assist(main.ConverseRequest(text=text, voice=metadata,
                                                              conversation_id=conversation), request)
        self.assertIn('continue_conversation', result)
        return result['continue_conversation']

    JEFF = vector(0)
    TV = vector(1)

    # --- a recognized voice -----------------------------------------------
    def test_a_recognized_voice_keeps_the_mic_open_past_the_cap(self):
        self.enroll()
        for turn in range(6):
            self.assertTrue(self.say('what is on the calendar tomorrow afternoon', self.JEFF), turn)
        self.assertEqual(self.agent.call_count, 6)

    def test_a_short_reply_inherits_the_recognized_speaker(self):
        self.enroll()
        self.assertTrue(self.say('add milk to the shopping list please', self.JEFF))
        for turn in range(5):
            self.assertTrue(self.say('yes', self.TV, seconds=0.4), turn)
        # A short reply sent with no audio evidence at all inherits too.
        self.assertTrue(self.say('the second one'))
        self.assertTrue(self.say('and the third'))

    # --- the TV -----------------------------------------------------------
    def test_a_voice_nobody_owns_closes_at_the_cap_and_a_known_voice_resets_it(self):
        self.enroll()
        self.assertTrue(self.say('what time is practice', self.JEFF))
        self.assertTrue(self.say('and now back to our regular programming', self.TV))
        self.assertFalse(self.say('stay tuned for the weather after the break', self.TV))
        # The mic closed; a new wake word starts a fresh count.
        self.assertTrue(self.say('coming up next on the evening news', self.TV))
        self.assertTrue(self.say('who is driving tomorrow', self.JEFF))
        self.assertTrue(self.say('tonight a storm rolls across the valley', self.TV))
        self.assertFalse(self.say('more on that story at eleven tonight', self.TV))

    def test_a_short_turn_after_the_tv_does_not_inherit(self):
        self.enroll()
        self.assertTrue(self.say('what time is practice', self.JEFF))
        self.assertTrue(self.say('and now back to our regular programming', self.TV))
        self.assertFalse(self.say('yes', self.TV, seconds=0.4))

    def test_a_short_first_turn_has_nobody_to_inherit(self):
        self.enroll()
        self.assertTrue(self.say('hello', self.TV, seconds=0.4))
        self.assertFalse(self.say('yes', self.TV, seconds=0.4))

    def test_an_uncertain_long_sample_counts_toward_the_cap(self):
        self.enroll()
        self.assertTrue(self.say('what time is practice', self.JEFF))
        self.assertTrue(self.say('somebody talking in the next room about dinner', uncertain()))
        self.assertFalse(self.say('somebody else answering them about the dishes', uncertain()))

    def test_a_gap_between_turns_starts_a_fresh_count(self):
        self.enroll()
        self.assertTrue(self.say('and now back to our regular programming', self.TV))
        self.vc.GAP_SECONDS = 0     # every turn now arrives after the gap
        self.assertTrue(self.say('stay tuned for the weather after the break', self.TV))
        self.assertTrue(self.say('coming up next on the evening news', self.TV))

    def test_each_satellite_keeps_its_own_count(self):
        self.enroll(recognition=False, satellites=(KITCHEN, BEDROOM))
        self.assertTrue(self.say('what is for dinner tonight', satellite=KITCHEN))
        self.assertTrue(self.say('what is for dinner tonight', satellite=BEDROOM))
        self.assertFalse(self.say('and what about tomorrow night', satellite=KITCHEN))
        self.assertFalse(self.say('and what about tomorrow night', satellite=BEDROOM))

    # --- sign-offs --------------------------------------------------------
    def test_a_sign_off_closes_the_mic_after_argyle_answers(self):
        self.enroll()
        for phrase in SIGN_OFFS:
            self.assertTrue(self.say('what time is practice', self.JEFF), phrase)
            calls = self.agent.call_count
            self.assertFalse(self.say(phrase, self.JEFF), phrase)
            if phrase != 'cancel':      # a bare cancel is the approval guard's ("Nothing was approved.")
                self.assertEqual(self.agent.call_count, calls + 1, 'Argyle still answers ' + phrase)

    def test_a_sign_off_inside_a_longer_request_keeps_going(self):
        self.enroll()
        for phrase in NOT_SIGN_OFFS:
            self.assertTrue(self.say(phrase, self.JEFF), phrase)

    def test_ordinary_sentences_that_start_like_a_name_reach_argyle(self):
        # "I'm done...", "it's raining" were name introductions ("Which family
        # member?") before 2026-11-04; only a family member's name is one.
        self.enroll()
        for phrase in ("I'm done with the dishes, what's next?", "It's raining, should we leave early?",
                       'This is great, add it to the list', "I'm running late for practice"):
            calls = self.agent.call_count
            self.assertTrue(self.say(phrase, self.JEFF), phrase)
            self.assertEqual(self.agent.call_count, calls + 1, 'Argyle answers ' + phrase)
        self.enroll(recognition=False, identity=False)
        calls = self.agent.call_count
        self.say("I'm hungry, what's for dinner?")
        self.assertEqual(self.agent.call_count, calls + 1, 'identity off: still an ordinary sentence')

    def test_a_real_name_is_still_an_introduction(self):
        self.enroll(recognition=False)
        calls = self.agent.call_count
        self.assertTrue(self.say("It's Jeff"))
        self.assertEqual(self.agent.call_count, calls, 'a name introduction is identity, not the model')

    # --- no recognition ---------------------------------------------------
    def test_a_satellite_without_recognition_always_uses_the_cap(self):
        self.enroll(recognition=False)
        self.assertTrue(self.say('what is on the calendar tomorrow'))
        self.assertFalse(self.say('and the day after that'))

    def test_voice_identity_off_still_has_conversation_mode_with_the_cap(self):
        self.enroll(recognition=False, identity=False)
        self.assertTrue(self.say('what is on the calendar tomorrow'))
        self.assertFalse(self.say('and the day after that'))

    def test_a_pin_without_recognition_does_not_lift_the_cap(self):
        self.enroll(recognition=False)
        self.say("It's Jeff")
        self.say('My PIN is 1234')
        ctx = voice.context({'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                             'request_id': uuid.uuid4().hex, 'observed_at': time.time()}, True)
        self.assertEqual(ctx.level, 'verified')
        # The PIN dialog's own turns never spend the count.
        self.assertTrue(self.say('what is on the calendar tomorrow'))
        self.assertFalse(self.say('and the day after that'))

    # --- the household switch and what stays as it was --------------------
    def test_the_household_switch_turns_it_off(self):
        self.enroll()
        self.settings['voice_conversation_mode'] = False
        self.assertFalse(self.say('what is on the calendar tomorrow afternoon', self.JEFF))
        self.settings['voice_conversation_mode'] = True
        self.assertTrue(self.say('what is on the calendar tomorrow afternoon', self.JEFF))

    def test_identity_prompts_still_reopen_the_mic_with_the_switch_off(self):
        self.enroll(recognition=False)
        self.settings['voice_conversation_mode'] = False
        self.assertTrue(self.say("It's Jeff"))      # the PIN question still wants an answer

    def test_a_request_from_no_satellite_never_keeps_listening(self):
        import main
        result = main.converse_ha_assist(main.ConverseRequest(text='what is on the calendar', voice=None,
                                                              conversation_id='typed'), None)
        self.assertFalse(result['continue_conversation'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
