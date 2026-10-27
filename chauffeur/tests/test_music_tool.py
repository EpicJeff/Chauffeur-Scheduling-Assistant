"""The `music` agent tool: "play Hotel California on the office TV" from any
Argyle surface. Search through the music arc's own grouped search, pick the
room's Music Assistant player the way the wall does (announce.pick_music_player),
play through HA's music_assistant.play_media, control through media_player
services. Stubbed ha_api, music_search and MA; the real services.music_tool and
the real tool entry points.

Run from chauffeur/:  python tests/test_music_tool.py
"""
import types
import unittest

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_tools_v2, announce, ha_api, music_search, music_tool, storage

TRACK = {'uri': 'spotify://track/1', 'name': 'Hotel California', 'media_type': 'track',
         'artists': [{'name': 'Eagles'}], 'album': {'name': 'Hotel California'}, 'image': None,
         'favorite': False, 'in_library': False, 'providers': ['spotify']}
ALBUM = {'uri': 'spotify://album/9', 'name': 'Hotel California', 'media_type': 'album',
         'artists': [{'name': 'Eagles'}], 'album': None, 'image': None, 'favorite': False,
         'in_library': False, 'providers': ['spotify']}
ARTIST = {'uri': 'spotify://artist/3', 'name': 'Eagles', 'media_type': 'artist', 'artists': [],
          'album': None, 'image': None, 'favorite': False, 'in_library': False, 'providers': ['spotify']}

AREAS = [
    {'id': 'office', 'name': 'Office', 'entities': ['media_player.office_tv_2', 'media_player.office_tv_4',
                                                    'media_player.googletv1645_2']},
    {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['assist_satellite.kitchen', 'media_player.kitchen_speaker']},
    {'id': 'garage', 'name': 'Garage', 'entities': ['media_player.garage_cast']},
    {'id': 'hall', 'name': 'Hall', 'entities': []},
]


def _states():
    return [
        {'entity_id': 'media_player.office_tv_2', 'state': 'on', 'attributes': {'friendly_name': 'Office TV'}},
        {'entity_id': 'media_player.office_tv_4', 'state': 'idle',
         'attributes': {'friendly_name': 'Office TV', 'mass_player_type': 'player'}},
        {'entity_id': 'media_player.googletv1645_2', 'state': 'idle', 'attributes': {'friendly_name': 'Office TV'}},
        {'entity_id': 'media_player.kitchen_speaker', 'state': 'playing',
         'attributes': {'friendly_name': 'Kitchen Speaker', 'mass_player_type': 'player',
                        'media_title': 'Take It Easy', 'media_artist': 'Eagles', 'volume_level': 0.3}},
        {'entity_id': 'assist_satellite.kitchen', 'state': 'idle', 'attributes': {'friendly_name': 'Kitchen Voice'}},
        {'entity_id': 'media_player.garage_cast', 'state': 'idle', 'attributes': {'friendly_name': 'Garage Cast'}},
    ]


def voice(satellite_id='assist_satellite.kitchen'):
    return types.SimpleNamespace(level='unknown', satellite_id=satellite_id, ha_instance_id='', service_revision='',
                                 member=lambda: None, verified_member=lambda: None, provenance=lambda: {})


class MusicToolTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.searches = [], []
        self.states = _states()
        self.results = {'track': [TRACK], 'album': [ALBUM], 'artist': [ARTIST]}
        self.orig = {}
        tests = self

        def stub(mod, name, value):
            self.orig[(mod, name)] = getattr(mod, name)
            setattr(mod, name, value)

        def search(q, media_types=None, limit=20, library_only=False, provider=None):
            tests.searches.append({'q': q, 'media_types': list(media_types or [])})
            wanted = [t for t in (media_types or []) if t in tests.results] or list(tests.results)
            groups = [{'type': t, 'items': list(tests.results[t])} for t in wanted if tests.results.get(t)]
            return {'source': 'ma', 'query': q, 'groups': groups, 'providers': [],
                    'total': sum(len(g['items']) for g in groups)}

        def call_service(domain, service, data=None, return_response=False, timeout=None):
            tests.calls.append((domain, service, dict(data or {})))
            return []
        stub(music_search, 'search', search)
        stub(ha_api, 'get_states', lambda ttl=5: tests.states)
        stub(ha_api, 'get_area_map', lambda ttl=60: AREAS)
        stub(ha_api, 'resolve_area_id', lambda name: {'the office': 'office', 'office': 'office'}.get(
            (name or '').strip().lower()))
        stub(ha_api, 'call_service', call_service)
        stub(ha_api, 'mode', lambda: 'supervisor')
        stub(storage, 'get_settings', lambda: {})

    def tearDown(self):
        for (mod, name), value in self.orig.items():
            setattr(mod, name, value)

    def run_tool(self, **kw):
        return agent_tools_v2.music(**kw)

    # --- play --------------------------------------------------------------
    def test_play_a_song_in_a_room_goes_to_that_rooms_music_assistant_player(self):
        res = self.run_tool(action='play', query='Hotel California', room='the office')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.searches, [{'q': 'Hotel California', 'media_types': []}])
        self.assertEqual(self.calls, [('music_assistant', 'play_media', {
            'entity_id': 'media_player.office_tv_4', 'media_id': 'spotify://track/1', 'media_type': 'track'})])
        self.assertEqual(res['entity_id'], 'media_player.office_tv_4')
        self.assertEqual(res['item']['name'], 'Hotel California')
        self.assertIn('Hotel California', res['message'])
        self.assertIn('Eagles', res['message'])
        self.assertIn('Office', res['message'])

    def test_a_track_wins_over_an_album_unless_a_type_is_asked_for(self):
        res = self.run_tool(action='play', query='Hotel California', room='office', media_type='album')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.searches[-1]['media_types'], ['album'])
        self.assertEqual(self.calls[-1][2]['media_id'], 'spotify://album/9')
        self.assertEqual(self.calls[-1][2]['media_type'], 'album')

    def test_an_artist_request_plays_the_artist(self):
        res = self.run_tool(action='play', query='Eagles', room='office', media_type='artist')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['media_id'], 'spotify://artist/3')

    def test_enqueue_and_radio_ride_the_call(self):
        self.run_tool(action='play', query='Hotel California', room='office', mode='next')
        self.assertEqual(self.calls[-1][2]['enqueue'], 'next')
        self.run_tool(action='play', query='Hotel California', room='office', mode='radio')
        self.assertTrue(self.calls[-1][2].get('radio_mode'))
        self.assertNotIn('enqueue', self.calls[-1][2])

    def test_a_voice_request_without_a_room_plays_where_the_voice_was_heard(self):
        res = self.run_tool(action='play', query='Hotel California', voice_context=voice(), source='voice')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.kitchen_speaker')
        self.assertIn('Kitchen', res['message'])

    def test_no_room_and_no_voice_plays_where_music_already_is(self):
        res = self.run_tool(action='play', query='Hotel California')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.kitchen_speaker', 'the playing player')

    def test_naming_a_player_beats_the_room(self):
        res = self.run_tool(action='play', query='Hotel California', player='kitchen speaker', room='office')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.kitchen_speaker')

    def test_naming_a_tv_with_twins_picks_its_music_assistant_twin(self):
        """Device run 2026-10-27: "play ... on the office TV" was told the Office TV
        is not in Music Assistant. Four entities are called Office TV; the MA one is
        "Office TV Media Player", and the exact-name Android TV remote outscored it."""
        self.states = [
            {'entity_id': 'media_player.office_tv', 'state': 'unavailable', 'attributes': {'friendly_name': 'Office TV'}},
            {'entity_id': 'media_player.office_tv_2', 'state': 'off',
             'attributes': {'friendly_name': 'Office TV', 'device_class': 'tv'}},
            {'entity_id': 'media_player.googletv1645_2', 'state': 'idle', 'attributes': {'friendly_name': 'Office TV'}},
            {'entity_id': 'media_player.office_tv_4', 'state': 'idle',
             'attributes': {'friendly_name': 'Office TV Media Player', 'mass_player_type': 'player'}},
            {'entity_id': 'media_player.kitchen_speaker', 'state': 'playing',
             'attributes': {'friendly_name': 'Kitchen Speaker', 'mass_player_type': 'player'}},
        ]
        res = self.run_tool(action='play', query='Hotel California', player='office tv')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.office_tv_4')
        self.assertIn('Office', res['message'])
        # Controls still go to the twin that is actually making sound.
        self.states[2]['state'] = 'playing'
        self.calls.clear()
        res = self.run_tool(action='pause', player='office tv')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.googletv1645_2')

    def test_a_room_with_no_music_assistant_player_says_which_player_and_why(self):
        res = self.run_tool(action='play', query='Hotel California', room='garage')
        self.assertEqual(res['status'], 'error')
        self.assertIn('Garage Cast', res['message'])
        self.assertIn('Music Assistant', res['message'])
        self.assertEqual(self.calls, [])

    def test_an_unknown_room_asks_rather_than_guessing(self):
        res = self.run_tool(action='play', query='Hotel California', room='the moon')
        self.assertEqual(res['status'], 'error')
        self.assertIn('moon', res['message'])
        self.assertEqual(self.calls, [])

    def test_nothing_found_is_said_plainly(self):
        self.results = {}
        res = self.run_tool(action='play', query='zzzz', room='office')
        self.assertEqual(res['status'], 'error')
        self.assertIn('zzzz', res['message'])
        self.assertEqual(self.calls, [])

    def test_a_refused_play_is_reported_not_claimed(self):
        setattr(ha_api, 'call_service', lambda *a, **k: None)
        res = self.run_tool(action='play', query='Hotel California', room='office')
        self.assertEqual(res['status'], 'error')
        self.assertIn('Music Assistant', res['message'])

    # --- control ------------------------------------------------------------
    def test_pause_resume_skip_and_stop_target_the_rooms_player(self):
        for action, service in (('pause', 'media_pause'), ('resume', 'media_play'), ('next', 'media_next_track'),
                                ('previous', 'media_previous_track'), ('stop', 'media_stop')):
            self.calls.clear()
            res = self.run_tool(action=action, room='kitchen')
            self.assertEqual(res['status'], 'success', (action, res))
            self.assertEqual(self.calls, [('media_player', service, {'entity_id': 'media_player.kitchen_speaker'})])

    def test_pause_with_no_room_pauses_what_is_playing(self):
        res = self.run_tool(action='pause')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1], ('media_player', 'media_pause', {'entity_id': 'media_player.kitchen_speaker'}))

    def test_volume_is_a_percent(self):
        res = self.run_tool(action='volume', room='kitchen', level=40)
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1], ('media_player', 'volume_set',
                                          {'entity_id': 'media_player.kitchen_speaker', 'volume_level': 0.4}))
        res = self.run_tool(action='volume', room='kitchen', level=140)
        self.assertEqual(res['status'], 'error')

    def test_now_playing_reads_the_rooms_player(self):
        res = self.run_tool(action='now', room='kitchen')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['title'], 'Take It Easy')
        self.assertEqual(res['artist'], 'Eagles')
        self.assertEqual(res['state'], 'playing')
        self.assertIn('Take It Easy', res['message'])

    # --- degradation + wiring -----------------------------------------------
    def test_no_home_assistant_is_a_plain_error(self):
        setattr(ha_api, 'mode', lambda: 'unconfigured')
        res = self.run_tool(action='play', query='Hotel California', room='office')
        self.assertEqual(res['status'], 'error')
        self.assertIn('not connected', res['message'])
        self.assertEqual(self.calls, [])

    def test_the_tool_is_declared_once_runs_through_execute_tool_and_voice(self):
        names = [t['name'] for t in agent_tools_v2.get_available_tools()]
        self.assertEqual(names.count('music'), 1)
        res = agent_tools_v2.execute_tool('music', {'action': 'play', 'query': 'Hotel California', 'room': 'office'})
        self.assertEqual(res['status'], 'success', res)
        from services import voice_tools
        self.assertIn('music', voice_tools.TOOLS)
        res = voice_tools.dispatch('music', {'action': 'play', 'query': 'Hotel California'}, voice())
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.kitchen_speaker')
        from services import missions
        self.assertIn('music', missions.EXCLUDED_TOOLS)


if __name__ == '__main__':
    unittest.main()
