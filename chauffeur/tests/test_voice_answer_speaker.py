"""Per-area "Argyle answers through the room speaker" (2026-10-30).

A Voice PE is small and not outdoor-rated; the pool's Sonos is loud. A parent
turns a room on in the Map drawer beside its announce pin, and from then on
every spoken answer in that room goes to the room's speaker through the same
tts.speak path announcements use (HA's announce flag ducks and resumes), while
the satellite is handed blank speech, which HA's pipeline treats as "skip TTS".
Default is off everywhere. Anything missing — toggle off, no usable speaker,
the call refused, a typed request — falls back to the satellite's own voice.

Real main.converse_ha_assist, real voice_identity, real announce; stubbed HA
and model. Run from chauffeur/:  python tests/test_voice_answer_speaker.py
"""
import os
import time
import unittest
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import (agent_router, announce, ha_api, settings_registry, situations, storage,
                      voice_identity as voice)

AREAS = [
    {'id': 'pool_lounge', 'name': 'Pool Lounge',
     'entities': ['assist_satellite.pool', 'media_player.pool_lounge_tv', 'media_player.pool_lounge']},
    {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['assist_satellite.kitchen', 'media_player.family_hub_tv']},
]
ANSWER = 'Practice is at four, and the drive is twenty minutes.'


def _states(**over):
    base = {'assist_satellite.pool': 'idle', 'media_player.pool_lounge_tv': 'off', 'media_player.pool_lounge': 'idle',
            'assist_satellite.kitchen': 'idle', 'media_player.family_hub_tv': 'idle'}
    base.update(over)
    rows = []
    for eid, state in base.items():
        attrs = {'friendly_name': eid.split('.', 1)[1].replace('_', ' ').title()}
        if eid == 'media_player.pool_lounge':
            attrs['mass_player_type'] = 'player'
        rows.append({'entity_id': eid, 'state': state, 'attributes': attrs})
    return rows


class VoiceAnswerSpeakerTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        with voice._lock:
            voice._sessions.clear()
            voice._requests.clear()
            voice._observed.clear()
        self.settings = {'service_token': 'service', 'contact_first_name': 'Jeff',
                         'voice_answer_speakers': {'pool_lounge': True}, 'announce_targets': {}}
        self.states = _states()
        self.calls = []
        self.orig = {}
        tests = self

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)

        def call_service(domain, service, data=None, return_response=False, timeout=None):
            tests.calls.append((domain, service, dict(data or {})))
            return [] if tests.speaker_ok else None
        self.speaker_ok = True
        stub(storage, 'get_settings', lambda: self.settings)
        stub(ha_api, 'get_area_map', lambda ttl=60: AREAS)
        stub(ha_api, 'get_states', lambda ttl=5: tests.states)
        stub(ha_api, 'call_service', call_service)
        stub(ha_api, 'mode', lambda: 'supervisor')
        stub(announce, '_tts_config', lambda: ('tts.piper', 'en', 'amy'))
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.set_member_pin('jeff', '1234')
        voice.configure(True, [
            {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.pool', 'device_id': 'pool-dev', 'enabled': True},
            {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen', 'device_id': 'kitchen-dev', 'enabled': True},
        ], approvals_enabled=True)
        situations.REFRESH_DELAY_S = 0
        for p in (patch.object(situations, '_pool_call', return_value={}),
                  patch.object(agent_router, 'process_agent_request', return_value={'message': ANSWER})):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)

    def metadata(self, satellite='assist_satellite.pool'):
        return {'ha_instance_id': 'ha', 'satellite_id': satellite, 'device_id': f'{satellite.split(".")[1]}-dev',
                'observed_at': time.time(), 'request_id': uuid.uuid4().hex}

    def request(self):
        from starlette.requests import Request
        return Request({'type': 'http', 'headers': [(b'x-service-token', b'service')], 'query_string': b'',
                        'method': 'POST', 'path': '/'})

    def say(self, text, satellite='assist_satellite.pool', conversation_id='c1'):
        import main
        voice_meta = self.metadata(satellite) if satellite else None
        return main.converse_ha_assist(main.ConverseRequest(text=text, conversation_id=conversation_id, voice=voice_meta),
                                       self.request())

    def spoken(self, result):
        return result['response']['speech']['plain']['speech']

    def tts_calls(self):
        return [c for c in self.calls if c[:2] == ('tts', 'speak')]

    # --- the answer path --------------------------------------------------------
    def test_a_room_switched_on_answers_through_its_speaker_and_hands_the_satellite_silence(self):
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ' ', 'the satellite must have nothing to say (a space: '
                         'the pipeline strips it and skips TTS, and a pre-1.6.0 component passes it through)')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge')
        self.assertGreater(result['spoken_on']['seconds'], 1.0)
        self.assertEqual(self.tts_calls(), [('tts', 'speak', {
            'entity_id': 'tts.piper', 'media_player_entity_id': 'media_player.pool_lounge',
            'message': ANSWER, 'language': 'en', 'options': {'voice': 'amy'}})])
        # The written record keeps the words; only the voice moved.
        conv = next(iter(storage.conversations_table.all()))
        self.assertEqual(conv['messages'][-1]['content'], ANSWER)

    def test_a_room_left_on_the_satellite_speaks_as_before(self):
        result = self.say('when is practice', satellite='assist_satellite.kitchen')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.tts_calls(), [])

    def test_a_typed_request_never_touches_a_speaker(self):
        result = self.say('when is practice', satellite=None)
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.tts_calls(), [])

    def test_the_pinned_speaker_wins_and_a_pinned_satellite_is_not_a_speaker(self):
        self.settings['announce_targets'] = {'pool_lounge': 'media_player.pool_lounge_tv'}
        self.states = _states(**{'media_player.pool_lounge_tv': 'on'})
        result = self.say('when is practice')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge_tv')
        # A satellite pin is announce's answer, not a speaker tts.speak can reach.
        self.settings['announce_targets'] = {'pool_lounge': 'assist_satellite.pool'}
        self.calls.clear()
        result = self.say('when is practice')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge')

    def test_an_off_tv_is_not_woken_to_answer_unless_pinned(self):
        """The Cast face of a TV that is off would turn the TV on to speak; a room
        whose only speaker is an off TV stays on the satellite instead."""
        self.states = _states(**{'media_player.pool_lounge': 'unavailable'})
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.tts_calls(), [])
        self.settings['announce_targets'] = {'pool_lounge': 'media_player.pool_lounge_tv'}
        result = self.say('when is practice')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge_tv')

    def test_a_speaker_that_refuses_falls_back_to_the_satellite(self):
        self.speaker_ok = False
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(len(self.tts_calls()), 1, 'the speaker was tried once')

    def test_identity_and_setup_answers_ride_the_same_speaker(self):
        """Every spoken answer in the room, not only the model's: "It's Jeff" is answered
        by voice_identity before any model, and it must come out of the same speaker."""
        result = self.say("It's Jeff")
        self.assertEqual(self.spoken(result), ' ')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge')
        self.assertTrue(self.tts_calls()[0][2]['message'])
        self.assertTrue(result['continue_conversation'] in (True, False))

    def test_speaking_time_grows_with_the_sentence(self):
        short = announce.speaking_seconds('Yes.')
        long = announce.speaking_seconds(' '.join(['word'] * 40))
        self.assertGreaterEqual(short, 1.0)
        self.assertGreater(long, short + 5)
        self.assertLessEqual(long, 30)

    # --- the hand path ----------------------------------------------------------
    def test_the_setting_is_registered_on_the_map_page_beside_the_pins_and_the_model_takes_it(self):
        entry = next(e for e in settings_registry.ENTRIES if e['key'] == 'voice_answer_speakers')
        self.assertEqual((entry['page'], entry['anchor']), ('map', 'announce'))
        self.assertEqual(entry['ui_marker'], 'announce-answer-toggle')
        from models.schemas import Settings
        self.assertEqual(Settings(voice_answer_speakers={'pool_lounge': True}).model_dump(exclude_unset=True),
                         {'voice_answer_speakers': {'pool_lounge': True}})
        page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'templates', 'map.html'), encoding='utf-8').read()
        self.assertIn('announce-answer-toggle', page)
        self.assertIn('voice_answer_speakers', page)

    def test_the_rooms_api_says_which_rooms_answer_through_their_speaker(self):
        import main
        rooms = {r['id']: r for r in main.announce_rooms()}
        self.assertTrue(rooms['pool_lounge']['answers'])
        self.assertFalse(rooms['kitchen']['answers'])


if __name__ == '__main__':
    unittest.main()
