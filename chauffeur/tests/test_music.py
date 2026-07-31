"""Tests for the Music Assistant bridge endpoints (main.py), HA mocked.

Run from chauffeur/:  python tests/test_music.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_music_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ha_api  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset():
    import main
    main._MA_CONFIG_ENTRY['id'] = None
    main._MA_CONFIG_ENTRY['checked'] = False


def scenario_media_players_listing():
    import main
    states = [
        {"entity_id": "media_player.kitchen", "state": "playing",
         "attributes": {"friendly_name": "Kitchen", "media_title": "Song A",
                        "media_artist": "Artist", "volume_level": 0.4,
                        "entity_picture": "/api/media/x", "supported_features": 12345}},
        {"entity_id": "media_player.attic", "state": "idle",
         "attributes": {"friendly_name": "Attic"}},
        {"entity_id": "person.jeff", "state": "home", "attributes": {}},
    ]
    with mock.patch.object(ha_api, 'get_states', return_value=states):
        players = main.ha_media_players()
    check([p['entity_id'] for p in players] == ['media_player.attic', 'media_player.kitchen'],
          "media_player domain only, sorted by name")
    kitchen = players[1]
    check(kitchen['media_title'] == 'Song A' and kitchen['volume_level'] == 0.4,
          "now-playing attributes surfaced")


def scenario_command_mapping():
    import main
    from fastapi import HTTPException
    with mock.patch.object(ha_api, 'call_service', return_value={}) as call:
        main.ha_media_command('media_player.kitchen', main.MediaCommandRequest(command='pause'))
        check(call.call_args.args[:2] == ('media_player', 'media_pause'), "pause maps")
        check(call.call_args.args[2] == {'entity_id': 'media_player.kitchen'}, "entity targeted")

        main.ha_media_command('media_player.kitchen',
                              main.MediaCommandRequest(command='volume_set', volume=0.55))
        check(call.call_args.args[1] == 'volume_set'
              and call.call_args.args[2]['volume_level'] == 0.55, "volume_set payload")

        main.ha_media_command('media_player.kitchen',
                              main.MediaCommandRequest(command='next'))
        check(call.call_args.args[1] == 'media_next_track', "next maps")

    for bad, expect in [
        (main.MediaCommandRequest(command='explode'), 400),
        (main.MediaCommandRequest(command='volume_set'), 400),
    ]:
        try:
            main.ha_media_command('media_player.kitchen', bad)
            check(False, f"expected {expect}")
        except HTTPException as e:
            check(e.status_code == expect, f"expected {expect}, got {e.status_code}")

    with mock.patch.object(ha_api, 'call_service', return_value=None):
        try:
            main.ha_media_command('media_player.kitchen', main.MediaCommandRequest(command='play'))
            check(False, "expected 502")
        except HTTPException as e:
            check(e.status_code == 502, "HA failure -> 502")


def scenario_search_uses_config_entry_and_unwraps():
    import main
    from fastapi import HTTPException
    with mock.patch.object(ha_api, 'get_config_entry_id', return_value='entry42'), \
         mock.patch.object(ha_api, 'call_service',
                           return_value={'service_response': {'tracks': [{'name': 'X'}]}}) as call:
        result = main.music_search(q='abba', media_type='track', limit=5)
        check(result == {'tracks': [{'name': 'X'}]}, "service_response unwrapped")
        args, kwargs = call.call_args
        check(args[0] == 'music_assistant' and args[1] == 'search', "MA search called")
        check(args[2] == {'config_entry_id': 'entry42', 'name': 'abba',
                          'limit': 5, 'media_type': ['track']}, f"payload, got {args[2]}")
        check(kwargs.get('return_response') is True, "return_response set")
        # cached: second call must not re-fetch the entry id
        main.music_search(q='again')
    reset()
    with mock.patch.object(ha_api, 'get_config_entry_id', return_value=None):
        try:
            main.music_search(q='abba')
            check(False, "expected 503")
        except HTTPException as e:
            check(e.status_code == 503, "no MA integration -> 503")


def scenario_favorites_and_play():
    import main
    with mock.patch.object(ha_api, 'get_config_entry_id', return_value='entry42'), \
         mock.patch.object(ha_api, 'call_service',
                           return_value={'service_response': {'items': []}}) as call:
        main.music_favorites(media_type='playlist')
        args, _ = call.call_args
        check(args[1] == 'get_library' and args[2]['favorite'] is True
              and args[2]['media_type'] == 'playlist', "favorites payload")

        main.music_play(main.MusicPlayRequest(
            entity_id='media_player.kitchen', media_id='library://track/1', media_type='track'))
        args, kwargs = call.call_args
        check(args[1] == 'play_media'
              and args[2] == {'entity_id': 'media_player.kitchen',
                              'media_id': 'library://track/1', 'media_type': 'track'},
              f"play payload, got {args[2]}")
        check(not kwargs.get('return_response'), "play_media needs no response")


SCENARIOS = [
    scenario_media_players_listing,
    scenario_command_mapping,
    scenario_search_uses_config_entry_and_unwraps,
    scenario_favorites_and_play,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            reset()
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
