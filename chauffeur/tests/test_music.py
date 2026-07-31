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
                        "entity_picture": "/api/media/x", "supported_features": 12345,
                        "mass_player_type": "player"}},
        {"entity_id": "media_player.attic", "state": "idle",
         "attributes": {"friendly_name": "Attic", "mass_player_type": "player"}},
        {"entity_id": "media_player.random_tv", "state": "off",
         "attributes": {"friendly_name": "Random TV", "device_class": "tv"}},
        {"entity_id": "person.jeff", "state": "home", "attributes": {}},
    ]
    with mock.patch.object(ha_api, 'get_states', return_value=states):
        players = main.ha_media_players()
        check([p['entity_id'] for p in players] == ['media_player.attic', 'media_player.kitchen'],
              "default: only MA players (mass_player_type), sorted by name")
        everything = main.ha_media_players(ma_only=False)
        check(len(everything) == 3 and everything[2]['device_class'] == 'tv',
              "ma_only=false returns all with device_class")
    kitchen = players[1]
    check(kitchen['media_title'] == 'Song A' and kitchen['volume_level'] == 0.4,
          "now-playing attributes surfaced")
    check(kitchen['is_ma_player'] is True, "MA marker surfaced")

    # No MA players at all -> graceful fallback to the full list
    no_ma = [{"entity_id": "media_player.tv", "state": "off",
              "attributes": {"friendly_name": "TV"}}]
    with mock.patch.object(ha_api, 'get_states', return_value=no_ma):
        players = main.ha_media_players()
    check(len(players) == 1, "fallback to all players when MA has none")


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


def scenario_image_proxy():
    import main
    from fastapi import HTTPException
    with mock.patch.object(ha_api, 'fetch_binary',
                           return_value=(b'\x89PNG', 'image/png')) as fetch:
        resp = main.ha_image(path='/api/media_player_proxy/media_player.kitchen?token=x')
        check(resp.body == b'\x89PNG' and resp.media_type == 'image/png',
              "artwork bytes + content type proxied")
        check(fetch.call_args.args[0].startswith('/api/media_player_proxy/'),
              "path passed through")
    for bad in ('/api/states', '/api/media_player_proxy/../states', 'http://evil'):
        try:
            main.ha_image(path=bad)
            check(False, f"expected 400 for {bad}")
        except HTTPException as e:
            check(e.status_code == 400, f"allowlist rejects {bad}")
    with mock.patch.object(ha_api, 'fetch_binary', return_value=None):
        try:
            main.ha_image(path='/api/image_proxy/x')
            check(False, "expected 502")
        except HTTPException as e:
            check(e.status_code == 502, "HA failure -> 502")


def scenario_image64_roundtrip():
    import base64
    import main
    from fastapi import HTTPException
    path = '/api/media_player_proxy/media_player.kitchen?token=abc123=='
    encoded = base64.urlsafe_b64encode(path.encode()).decode().rstrip('=')
    req = mock.Mock()
    req.headers = {}
    with mock.patch.object(ha_api, 'fetch_binary',
                           return_value=(b'img', 'image/png')) as fetch:
        resp = main.ha_image64(encoded, req)
        check(resp.body == b'img', "decoded path fetches")
        check(fetch.call_args.args[0] == path, "base64url round-trips incl. padding")
    try:
        main.ha_image64('!!!not-base64!!!', req)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "bad encoding -> 400")
    # allowlist still applies after decode
    bad = base64.urlsafe_b64encode(b'/api/states').decode().rstrip('=')
    try:
        main.ha_image64(bad, req)
        check(False, "expected 400 for disallowed decoded path")
    except HTTPException as e:
        check(e.status_code == 400, "allowlist enforced post-decode")


def scenario_fetch_binary_url():
    os.environ["SUPERVISOR_TOKEN"] = "t"
    resp = mock.Mock(status_code=200, content=b'img',
                     headers={'Content-Type': 'image/jpeg'})
    with mock.patch.object(ha_api.requests, 'get', return_value=resp) as req:
        result = ha_api.fetch_binary('/api/media_player_proxy/x')
        check(result == (b'img', 'image/jpeg'), "content + type returned")
        check(req.call_args.args[0] == 'http://supervisor/core/api/media_player_proxy/x',
              f"'/api' base collapses against the api-prefixed path, got {req.call_args.args[0]}")
    os.environ.pop("SUPERVISOR_TOKEN", None)


SCENARIOS = [
    scenario_media_players_listing,
    scenario_image_proxy,
    scenario_image64_roundtrip,
    scenario_fetch_binary_url,
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
