"""A goodbye ends the speaker; short replies inherit only inside one conversation
(spec docs/superpowers/specs/2026-11-10-voice-acts-and-panel-talk-design.md, Task 1).

Before this, a recognised speaker stayed on the satellite for the whole
10-minute session: a short "yes" after a new wake word, minutes later, from
somebody else, still counted as them. Now:
  - a short (or audio-less) reply inherits the recognised speaker only while
    the conversation is still open: the previous turn left the mic open
    (continue_conversation true) less than GAP_SECONDS ago;
  - a sign-off still gets Argyle's answer and closes the mic, and it also
    ends the identity session (level unknown, new generation);
  - a long sample in the next conversation is fingerprinted as before.

Every scenario runs the real endpoint, main.converse_ha_assist; only the model
is stubbed.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_voice_session_end.py
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_session_end_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp

KITCHEN = 'assist_satellite.kitchen'
KEY = ('ha', KITCHEN)


def vector(index=0):
    return [float(i == index) for i in range(256)]


JEFF = vector(0)
TV = vector(1)


class SessionEndTests(unittest.TestCase):
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
        agent = patch('services.agent_router.process_agent_request',
                      side_effect=lambda *a, **k: {'message': 'Done.'})
        self.agent = agent.start(); self.addCleanup(agent.stop)
        speaker = patch('services.announce.answer_through_speaker', return_value=None)
        speaker.start(); self.addCleanup(speaker.stop)
        from services import voice_conversation
        self.vc = voice_conversation
        voice_conversation._turns.clear()
        self.addCleanup(setattr, voice_conversation, 'GAP_SECONDS', voice_conversation.GAP_SECONDS)
        fp._save([{'member_id': 'jeff', 'key': ['ha', KITCHEN], 'vector': JEFF, 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': 2, 'calibrated': True}])
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                                'enabled': True, 'recognition_enabled': True}])

    def say(self, text, voiceprint=None, seconds=6.0, conversation='conv-1'):
        """One utterance through the real endpoint; returns HA's whole reply."""
        import main
        from starlette.requests import Request
        request_id = uuid.uuid4().hex
        metadata = {'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                    'request_id': request_id, 'utterance_id': request_id, 'run_id': 'run-' + request_id,
                    'observed_at': time.time()}
        if voiceprint is not None:
            ctx = voice.context(dict(metadata), True)
            oid = 'obs-' + request_id
            fp._observations[oid] = {'key': ('ha', KITCHEN, 'device-' + KITCHEN, 'run-' + request_id, request_id),
                                     'revision': ctx.service_revision, 'vector': voiceprint, 'seconds': seconds,
                                     'expires': time.time() + 60}
            metadata['observation_id'] = oid
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        return main.converse_ha_assist(main.ConverseRequest(text=text, voice=metadata,
                                                            conversation_id=conversation), request)

    @staticmethod
    def speech(result):
        return result['response']['speech']['plain']['speech']

    def last_ctx(self):
        return self.agent.call_args.kwargs['voice_context']

    # --- inheritance inside one conversation --------------------------------
    def test_short_reply_inherits_inside_conversation(self):
        self.assertTrue(self.say('what is on the calendar tomorrow', JEFF)['continue_conversation'])
        self.assertTrue(self.last_ctx().recognized_this_turn)
        self.say('yes', JEFF, seconds=0.4)
        self.assertTrue(self.last_ctx().recognized_this_turn)
        self.say('and the next one')            # no audio evidence at all
        self.assertTrue(self.last_ctx().recognized_this_turn)

    def test_in_conversation_reads_the_previous_turn(self):
        ctx = voice.context({'ha_instance_id': 'ha', 'satellite_id': KITCHEN, 'device_id': 'device-' + KITCHEN,
                             'request_id': 'r', 'observed_at': time.time()}, True)
        self.assertFalse(self.vc.in_conversation(ctx))
        self.say('what is on the calendar tomorrow', JEFF)
        self.assertTrue(self.vc.in_conversation(ctx))
        self.vc.GAP_SECONDS = 0
        self.assertFalse(self.vc.in_conversation(ctx))

    # --- a new conversation does not inherit --------------------------------
    def test_gap_ends_conversation(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.vc.GAP_SECONDS = 0     # the next turn arrives after the gap: a new wake word
        self.say('yes', JEFF, seconds=0.4)
        self.assertFalse(self.last_ctx().recognized_this_turn)
        # The session itself was not ended by the gap: Jeff is still the lens.
        self.assertEqual(voice._sessions[KEY]['member_id'], 'jeff')

    def test_closed_mic_ends_conversation(self):
        self.settings['voice_conversation_mode'] = False    # every answer closes the mic
        self.assertFalse(self.say('what is on the calendar tomorrow', JEFF)['continue_conversation'])
        self.say('yes')
        self.assertFalse(self.last_ctx().recognized_this_turn)

    def test_short_first_turn_after_sign_off_not_inherited(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.assertFalse(self.say("thanks, that's all", JEFF)['continue_conversation'])
        self.say('yes', JEFF, seconds=0.4)
        self.assertFalse(self.last_ctx().recognized_this_turn)
        self.assertIsNone(self.last_ctx().member_id)

    # --- goodbye ends the session -------------------------------------------
    def test_sign_off_ends_session(self):
        self.say('what is on the calendar tomorrow', JEFF)
        before = voice._sessions[KEY]['generation']
        self.assertEqual(voice._sessions[KEY]['member_id'], 'jeff')
        calls = self.agent.call_count
        result = self.say("thanks, that's all", JEFF)
        self.assertEqual(self.agent.call_count, calls + 1, 'Argyle still answers the sign-off')
        self.assertEqual(self.speech(result), 'Done.')
        self.assertFalse(result['continue_conversation'])
        row = voice._sessions[KEY]
        self.assertEqual(row['level'], 'unknown')
        self.assertIsNone(row['member_id'])
        self.assertNotEqual(row['generation'], before)
        self.assertFalse(row.get('recognized'))

    def test_sign_off_ends_verified_session(self):
        self.say("It's Jeff")
        self.say('my PIN is 1234')
        self.assertEqual(voice._sessions[KEY]['level'], 'verified')
        self.say('goodbye')
        self.assertEqual(voice._sessions[KEY]['level'], 'unknown')
        self.assertIsNone(voice._sessions[KEY]['member_id'])

    def test_end_session_without_session_is_noop(self):
        voice._sessions.clear()
        voice.end_session('ha', KITCHEN)
        self.assertNotIn(KEY, voice._sessions)

    def test_not_a_sign_off_keeps_session(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.say('thanks, and also add milk to the list', JEFF)
        self.assertEqual(voice._sessions[KEY]['member_id'], 'jeff')

    def test_long_new_conversation_still_fingerprints(self):
        self.say('what is on the calendar tomorrow', JEFF)
        self.say('goodbye', JEFF)
        result = self.say('who is driving to practice tomorrow', JEFF, conversation='conv-2')
        self.assertTrue(self.speech(result).startswith('Hi Jeff.'), self.speech(result))
        self.assertTrue(self.last_ctx().recognized_this_turn)


if __name__ == '__main__':
    unittest.main(verbosity=2)
