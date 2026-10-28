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
    {'id': 'office', 'name': 'Office', 'entities': ['media_player.office_tv_2', 'media_player.office_tv_4']},
    {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['assist_satellite.kitchen', 'media_player.kitchen_speaker']},
    {'id': 'garage', 'name': 'Garage', 'entities': ['media_player.garage_cast']},
    {'id': 'hall', 'name': 'Hall', 'entities': []},
]


def _states():
    return [
        {'entity_id': 'media_player.office_tv_2', 'state': 'on', 'attributes': {'friendly_name': 'Office TV'}},
        {'entity_id': 'media_player.office_tv_4', 'state': 'idle',
         'attributes': {'friendly_name': 'Office TV', 'mass_player_type': 'player'}},
        {'entity_id': 'media_player.googletv1645_2', 'state': 'idle',
         'attributes': {'friendly_name': 'Office Google TV Media Player'}},
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
        # The model copies the words as spoken: an article and a full stop ride along.
        for spoken in ('the office TV', 'office TV.', 'the Office TV.', 'my office tv'):
            self.calls.clear()
            res = self.run_tool(action='play', query='Hotel California', player=spoken)
            self.assertEqual(res['status'], 'success', (spoken, res))
            self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.office_tv_4', spoken)
        # Controls still go to the twin that is actually making sound.
        self.states[2]['state'] = 'playing'
        self.calls.clear()
        res = self.run_tool(action='pause', player='office tv')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.googletv1645_2')

    def test_a_room_whose_music_assistant_twin_has_no_area_still_plays_on_it(self):
        """Device run 2026-10-27, typed: "in the office" found only the remote, the
        Echo and a cast target, because Music Assistant's "Office TV Media Player"
        is assigned to no HA area. The twin is found by name instead."""
        self.states = [
            {'entity_id': 'media_player.office_tv_2', 'state': 'off',
             'attributes': {'friendly_name': 'Office TV', 'device_class': 'tv'}},
            {'entity_id': 'media_player.jeff_s_echo_dot', 'state': 'idle', 'attributes': {'friendly_name': "Jeff's Echo Dot"}},
            {'entity_id': 'media_player.office', 'state': 'idle', 'attributes': {'friendly_name': 'Office'}},
            {'entity_id': 'media_player.office_tv_4', 'state': 'idle',
             'attributes': {'friendly_name': 'Office TV Media Player', 'mass_player_type': 'player'}},
            {'entity_id': 'media_player.kitchen_speaker', 'state': 'playing',
             'attributes': {'friendly_name': 'Kitchen Speaker', 'mass_player_type': 'player'}},
        ]
        setattr(ha_api, 'get_area_map', lambda ttl=60: [
            {'id': 'office', 'name': 'Office', 'entities': ['media_player.office_tv_2', 'media_player.jeff_s_echo_dot',
                                                            'media_player.office']},
            {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['media_player.kitchen_speaker']}])
        res = self.run_tool(action='play', query='Hotel California', room='the office')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.office_tv_4')
        self.assertIn('Office', res['message'])
        # Controls in that room still go to a player that is making sound there.
        self.states[2]['state'] = 'playing'
        self.calls.clear()
        res = self.run_tool(action='pause', room='office')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.office')

    def test_any_branch_that_lands_on_a_non_ma_player_redirects_to_its_twin(self):
        """Device run 2026-10-27, fourth report: whichever path the model takes,
        a non-MA pick with an MA twin by name must play on the twin."""
        self.states = [
            {'entity_id': 'media_player.office_tv_2', 'state': 'playing',
             'attributes': {'friendly_name': 'Office TV', 'device_class': 'tv'}},
            {'entity_id': 'media_player.office_tv_4', 'state': 'off',
             'attributes': {'friendly_name': 'Office TV Media Player', 'mass_player_type': 'player'}},
        ]
        setattr(ha_api, 'get_area_map', lambda ttl=60: [])
        # No room, no player: the playing TV would be picked, and it cannot play.
        res = self.run_tool(action='play', query='Hotel California')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.office_tv_4')

    def test_a_refusal_names_the_entity_it_chose_and_the_players_that_could(self):
        self.states = [
            {'entity_id': 'media_player.garage_cast', 'state': 'idle', 'attributes': {'friendly_name': 'Garage Cast'}},
            {'entity_id': 'media_player.kitchen_speaker', 'state': 'idle',
             'attributes': {'friendly_name': 'Kitchen Speaker', 'mass_player_type': 'player'}},
            {'entity_id': 'media_player.office_tv_4', 'state': 'idle',
             'attributes': {'friendly_name': 'Office TV Media Player', 'mass_player_type': 'player'}},
        ]
        res = self.run_tool(action='play', query='Hotel California', player='garage cast')
        self.assertEqual(res['status'], 'error')
        self.assertIn('media_player.garage_cast', res['message'])
        self.assertIn('Kitchen Speaker', res['message'])
        self.assertIn('Office TV Media Player', res['message'])
        self.assertEqual(self.calls, [])

    def test_what_is_playing_and_controls_follow_the_twin_that_is_actually_playing(self):
        """Device run 2026-10-27 by voice: "What's playing on the office TV?" answered
        "Nothing is currently playing" while the Music Assistant twin was playing
        Mayonaise. The exact-name remote (on, no title) outscored the twin."""
        self.states = [
            {'entity_id': 'media_player.office_tv', 'state': 'unavailable', 'attributes': {'friendly_name': 'Office TV'}},
            {'entity_id': 'media_player.office_tv_2', 'state': 'on',
             'attributes': {'friendly_name': 'Office TV', 'device_class': 'tv', 'app_id': 'com.tcl.tv'}},
            {'entity_id': 'media_player.googletv1645_2', 'state': 'idle',
             'attributes': {'friendly_name': 'Office TV', 'app_name': 'Spotify'}},
            {'entity_id': 'media_player.office_tv_4', 'state': 'playing',
             'attributes': {'friendly_name': 'Office TV Media Player', 'mass_player_type': 'player',
                            'media_title': 'Mayonaise (2011 Remaster)', 'media_artist': 'The Smashing Pumpkins',
                            'volume_level': 0.5}},
        ]
        setattr(ha_api, 'get_area_map', lambda ttl=60: [
            {'id': 'office', 'name': 'Office', 'entities': ['media_player.office_tv_2', 'media_player.googletv1645_2']}])
        for how in ({'player': 'the office TV'}, {'room': 'the office'}):
            res = self.run_tool(action='now', **how)
            self.assertEqual(res['status'], 'success', (how, res))
            self.assertEqual(res['entity_id'], 'media_player.office_tv_4', how)
            self.assertEqual(res['title'], 'Mayonaise (2011 Remaster)', how)
            self.assertIn('Mayonaise', res['message'], how)
            self.calls.clear()
            res = self.run_tool(action='pause', **how)
            self.assertEqual(res['status'], 'success', (how, res))
            self.assertEqual(self.calls, [('media_player', 'media_pause', {'entity_id': 'media_player.office_tv_4'})], how)
            self.calls.clear()
            res = self.run_tool(action='volume', level=30, **how)
            self.assertEqual(self.calls[-1][2]['entity_id'], 'media_player.office_tv_4', how)

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

    def _youtube_on_the_office_tv(self, cast_playing=True):
        """Device 2026-10-28: Peppa Pig on YouTube on the Office TV. The remote says YouTube, the
        Android TV twin says YouTube, the Cast face carries the title, Music Assistant says idle."""
        self.states.append({'entity_id': 'remote.office_tv', 'state': 'on',
                            'attributes': {'friendly_name': 'Office TV', 'current_activity': 'YouTube'}})
        for s in self.states:
            if s['entity_id'] == 'media_player.office_tv_2':
                s['attributes'].update(app_id='com.google.android.youtube.tv', app_name='YouTube')
            if s['entity_id'] == 'media_player.googletv1645_2' and cast_playing:
                s['state'] = 'playing'
                s['attributes'].update(app_name='YouTube', media_content_type='video',
                                       media_title='Supermarket Food Dispensers | Peppa Pig Tales Full Episodes',
                                       media_artist='Peppa Pig Stories & Cartoons', media_position=209.7,
                                       media_duration=1994.6)

    def test_now_on_a_tv_reports_the_app_and_the_video_when_music_assistant_is_idle(self):
        """Device 2026-10-28: "what's playing on the office TV" answered idle while YouTube played
        Peppa Pig; the tool had asked only the Music Assistant face of the TV."""
        self._youtube_on_the_office_tv()
        for kw in ({'room': 'office'}, {'player': 'the office TV'}):
            res = self.run_tool(action='now', **kw)
            self.assertEqual(res['status'], 'success', res)
            self.assertEqual(res['state'], 'playing', res)
            self.assertEqual(res['app'], 'YouTube')
            self.assertIn('Peppa Pig', res['title'])
            self.assertIn('Office TV', res['message'])
            self.assertIn('YouTube', res['message'])
            self.assertIn('Peppa Pig', res['message'])
            self.assertIn('3 min', res['message'])
            self.assertIn('33 min', res['message'])
            self.assertNotIn('idle', res['message'].lower())
            self.assertNotIn('nothing', res['message'].lower())

    def test_now_on_a_tv_with_an_app_but_no_title_names_the_app(self):
        self._youtube_on_the_office_tv(cast_playing=False)
        res = self.run_tool(action='now', room='office')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['app'], 'YouTube')
        self.assertIsNone(res['title'])
        self.assertIn('Office TV is on YouTube', res['message'])
        self.assertNotIn('nothing', res['message'].lower())

    def test_now_still_prefers_music_assistant_when_it_is_the_one_playing(self):
        self._youtube_on_the_office_tv(cast_playing=False)
        for s in self.states:
            if s['entity_id'] == 'media_player.office_tv_4':
                s['state'] = 'playing'
                s['attributes'].update(media_title='Hotel California', media_artist='Eagles')
        res = self.run_tool(action='now', room='office')
        self.assertEqual(res['title'], 'Hotel California')
        self.assertIn('Hotel California', res['message'])

    def test_now_in_a_room_with_nothing_on_still_says_nothing(self):
        res = self.run_tool(action='now', room='office')
        self.assertEqual(res['status'], 'success', res)
        self.assertIn('Nothing is playing', res['message'])

    # --- degradation + wiring -----------------------------------------------
    def test_the_prompt_forbids_answering_from_an_earlier_refusal(self):
        """Device run 2026-10-27, v2.499.702 confirmed installed: the reply "the
        Office TV still isn't set up as a Music Assistant player" carried none of
        the tool's wording (no entity id, no player list). The model answered from
        its own earlier refusals in the conversation history without calling the
        tool. The prompt must say the tools are the only source of truth."""
        import inspect
        from services import agent_router
        prompt_src = inspect.getsource(agent_router.process_agent_request)
        self.assertIn('ONLY source of truth for what a device or player can do', prompt_src)
        self.assertIn('even when an earlier assistant message in this conversation said', prompt_src)

    def test_no_home_assistant_is_a_plain_error(self):
        setattr(ha_api, 'mode', lambda: 'unconfigured')
        res = self.run_tool(action='play', query='Hotel California', room='office')
        self.assertEqual(res['status'], 'error')
        self.assertIn('not connected', res['message'])
        self.assertEqual(self.calls, [])

    def test_the_tool_tells_the_model_now_covers_what_a_tv_is_showing(self):
        tool = next(t for t in agent_tools_v2.get_available_tools() if t['name'] == 'music')
        self.assertIn('TV', tool['description'])
        self.assertIn('app', tool['description'])

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
