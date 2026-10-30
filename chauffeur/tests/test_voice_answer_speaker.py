"""Per-satellite "Argyle answers through" a room speaker (2026-10-30).

A Voice PE is small and not outdoor-rated; the pool's Sonos is loud. On each
satellite's row in Config › Voice identity a parent picks the speaker Argyle
answers through (default: the satellite itself). From then on every spoken
answer to that satellite goes to that speaker through the same tts.speak path
announcements use (HA's announce flag ducks and resumes), while the satellite
is handed blank speech, which HA's pipeline treats as "skip TTS". Anything
missing — no speaker chosen, speaker unavailable, the call refused, a typed
request — falls back to the satellite's own voice.

First cut (v2.499.736) put this on the Map page as a per-room toggle beside the
announce pins; the user's verdict the same day: it is an Argyle voice setting
and has nothing to do with announcements, so it lives with the voice settings.

Real main.converse_ha_assist, real voice_identity, real announce; stubbed HA
and model. Run from chauffeur/:  python tests/test_voice_answer_speaker.py
"""
import os
import time
import unittest
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, announce, ha_api, situations, storage, voice_identity as voice

AREAS = [
    {'id': 'pool_lounge', 'name': 'Pool Lounge',
     'entities': ['assist_satellite.pool', 'media_player.pool_lounge_tv', 'media_player.pool_lounge']},
    {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['assist_satellite.kitchen', 'media_player.family_hub_tv']},
]
ANSWER = 'Practice is at four, and the drive is twenty minutes.'


def _states(**over):
    base = {'assist_satellite.pool': 'idle', 'media_player.pool_lounge_tv': 'off', 'media_player.pool_lounge': 'idle',
            'assist_satellite.kitchen': 'idle', 'media_player.family_hub_tv': 'idle',
            'media_player.office_tv': 'unavailable'}
    base.update(over)
    rows = []
    for eid, state in base.items():
        attrs = {'friendly_name': eid.split('.', 1)[1].replace('_', ' ').title()}
        if eid.startswith('media_player.'):
            # HA's MediaPlayerEntityFeature: PLAY_MEDIA = 512, MEDIA_ANNOUNCE = 1048576. A TV's
            # remote face can PLAY (it swaps the source) but cannot ANNOUNCE.
            attrs['supported_features'] = 512 if eid == 'media_player.pool_lounge_tv' else 512 | 1048576
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
        self.settings = {'service_token': 'service', 'contact_first_name': 'Jeff'}
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
        self.configure()
        situations.REFRESH_DELAY_S = 0
        for p in (patch.object(situations, '_pool_call', return_value={}),
                  patch.object(agent_router, 'process_agent_request', return_value={'message': ANSWER})):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)

    def configure(self, pool_speaker='media_player.pool_lounge'):
        voice.configure(True, [
            {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.pool', 'device_id': 'pool-dev', 'enabled': True,
             'answer_speaker': pool_speaker},
            {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen', 'device_id': 'kitchen-dev', 'enabled': True},
        ], approvals_enabled=True)

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
    def test_a_satellite_with_a_chosen_speaker_answers_through_it_and_is_handed_silence(self):
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ' ', 'the satellite must have nothing to say (a space: the '
                         'pipeline strips it and skips TTS, and a pre-1.6.0 component passes it through)')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge')
        self.assertEqual(result['spoken_on']['area'], 'Pool Lounge')
        self.assertGreater(result['spoken_on']['seconds'], 1.0)
        self.assertEqual(self.tts_calls(), [('tts', 'speak', {
            'entity_id': 'tts.piper', 'media_player_entity_id': 'media_player.pool_lounge',
            'message': ANSWER, 'language': 'en', 'options': {'voice': 'amy'}})])
        # The written record keeps the words; only the voice moved.
        conv = next(iter(storage.conversations_table.all()))
        self.assertEqual(conv['messages'][-1]['content'], ANSWER)

    def test_a_satellite_with_no_speaker_chosen_speaks_as_before(self):
        result = self.say('when is practice', satellite='assist_satellite.kitchen')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.tts_calls(), [])

    def test_a_typed_request_never_touches_a_speaker(self):
        result = self.say('when is practice', satellite=None)
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.tts_calls(), [])

    def test_a_chosen_speaker_that_is_unavailable_falls_back_to_the_satellite(self):
        self.states = _states(**{'media_player.pool_lounge': 'unavailable'})
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.tts_calls(), [])

    def test_a_speaker_that_refuses_falls_back_to_the_satellite(self):
        self.speaker_ok = False
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(len(self.tts_calls()), 1, 'the speaker was tried once')

    def test_identity_and_setup_answers_ride_the_same_speaker(self):
        """Every spoken answer on the satellite, not only the model's: "It's Jeff" is
        answered by voice_identity before any model, and it must come out of the same
        speaker."""
        result = self.say("It's Jeff")
        self.assertEqual(self.spoken(result), ' ')
        self.assertEqual(result['spoken_on']['entity_id'], 'media_player.pool_lounge')
        self.assertTrue(self.tts_calls()[0][2]['message'])
        self.assertIn(result['continue_conversation'], (True, False))

    def test_a_player_that_cannot_announce_is_never_offered_and_never_tried(self):
        """Device 2026-10-30: the Office Voice PE set to answer over the Office TV's
        Google TV face stopped what the TV was showing, said nothing, and the answer
        came from the satellite after all. That face takes play_media (it swaps the
        source) but has no MEDIA_ANNOUNCE. Such a player is not in the list, and if
        one is chosen anyway (a stale row, a player that lost the flag) it is not
        touched: the satellite answers and the TV keeps playing."""
        choices = {s['entity_id'] for s in voice.admin_state()['speakers']}
        self.assertNotIn('media_player.pool_lounge_tv', choices)
        self.assertIn('media_player.pool_lounge', choices)
        self.configure(pool_speaker='media_player.pool_lounge_tv')
        self.states = _states(**{'media_player.pool_lounge_tv': 'playing'})
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ANSWER)
        self.assertNotIn('spoken_on', result)
        self.assertEqual(self.calls, [], 'the TV was never asked to do anything')

    def test_speaking_time_grows_with_the_sentence(self):
        short = announce.speaking_seconds('Yes.')
        long = announce.speaking_seconds(' '.join(['word'] * 40))
        self.assertGreaterEqual(short, 1.0)
        self.assertGreater(long, short + 5)
        self.assertLessEqual(long, 30)

    # --- the hand path: Config › Voice identity, the satellite's own row -----------
    def test_the_choice_is_kept_on_the_satellites_row_and_only_a_media_player_counts(self):
        rows = {r['satellite_id']: r for r in voice.configuration()['satellites']}
        self.assertEqual(rows['assist_satellite.pool']['answer_speaker'], 'media_player.pool_lounge')
        self.assertEqual(rows['assist_satellite.kitchen']['answer_speaker'], '')
        # A satellite or anything else is not a speaker tts.speak can reach.
        self.configure(pool_speaker='assist_satellite.pool')
        self.assertEqual({r['satellite_id']: r['answer_speaker'] for r in voice.configuration()['satellites']}
                         ['assist_satellite.pool'], '')
        result = self.say('when is practice')
        self.assertEqual(self.spoken(result), ANSWER)
        # A satellite that joins by itself starts on its own voice.
        with voice._lock:
            voice._observed.clear()
        voice.context(self.metadata('assist_satellite.office'), True)
        office = next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == 'assist_satellite.office')
        self.assertEqual(office.get('answer_speaker', ''), '')

    def test_the_admin_state_offers_every_usable_player_with_its_room_and_the_rows_choice(self):
        state = voice.admin_state()
        choices = {s['entity_id']: s for s in state['speakers']}
        self.assertEqual(choices['media_player.pool_lounge'], {'entity_id': 'media_player.pool_lounge',
                                                               'name': 'Pool Lounge', 'area': 'Pool Lounge'})
        self.assertEqual(choices['media_player.family_hub_tv']['area'], 'Kitchen')
        self.assertNotIn('media_player.office_tv', choices, 'an unavailable player is not offered')
        self.assertNotIn('assist_satellite.pool', choices)
        row = next(s for s in state['satellites'] if s['satellite_id'] == 'assist_satellite.pool')
        self.assertEqual(row['answer_speaker'], 'media_player.pool_lounge')
        # The row knows its room, so the select lists that room's players first.
        self.assertEqual(row['area'], 'Pool Lounge')
        self.assertEqual(next(s for s in state['satellites'] if s['satellite_id'] == 'assist_satellite.kitchen')['area'],
                         'Kitchen')
        # No Home Assistant: the list is empty, the page still renders.
        setattr(ha_api, 'get_states', lambda ttl=5: [])
        self.assertEqual(voice.admin_state()['speakers'], [])

    def test_the_select_sits_on_the_satellite_row_in_config_and_the_map_page_no_longer_carries_it(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
        config = open(os.path.join(base, 'config.html'), encoding='utf-8').read()
        self.assertIn('voice-answer-speaker', config)
        self.assertIn('x-model="s.answer_speaker"', config)
        self.assertIn('voiceState.speakers', config)
        # The satellite's own room first, then a divider, then the rest of the house.
        self.assertIn('<optgroup label="In this room"', config)
        self.assertIn('<optgroup label="Elsewhere">', config)
        self.assertIn('sp.area === s.area', config)
        page = open(os.path.join(base, 'map.html'), encoding='utf-8').read()
        self.assertNotIn('announce-answer-toggle', page)
        self.assertNotIn('voice_answer_speakers', page)


if __name__ == '__main__':
    unittest.main()
