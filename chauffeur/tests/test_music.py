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
    """The HA fallback path of the grouped search (no ma_token in these
    tests, so the MA path answers None and the bridge runs)."""
    import main
    from fastapi import HTTPException
    with mock.patch.object(ha_api, 'get_config_entry_id', return_value='entry42'), \
         mock.patch.object(ha_api, 'call_service',
                           return_value={'service_response': {'tracks': [{'name': 'X', 'uri': 'u1'}]}}) as call:
        result = main.music_search(q='abba', media_type='track', limit=5)
        check(result['source'] == 'ha', "HA path taken without an MA token")
        check(result['groups'] == [{'type': 'track', 'items': [{
            'uri': 'u1', 'name': 'X', 'media_type': 'track', 'artists': [],
            'album': None, 'owner': None, 'image': None, 'favorite': None,
            'in_library': None, 'providers': []}]}],
              f"grouped + normalized, got {result['groups']}")
        check(result['providers'] == [], "HA path offers no provider chips")
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


def scenario_queue_verbs_map_to_ha_services():
    """Shuffle, repeat and stop were always one service call away — they are
    plain media_player services, no MA API needed. Radio mode and enqueue are
    fields play_media already accepted and nothing ever sent."""
    import main
    from fastapi import HTTPException
    with mock.patch.object(ha_api, 'call_service', return_value={}) as call:
        main.ha_media_command('media_player.k', main.MediaCommandRequest(command='stop'))
        check(call.call_args.args[1] == 'media_stop', "stop maps")

        main.ha_media_command('media_player.k',
                              main.MediaCommandRequest(command='shuffle_set', shuffle=True))
        check(call.call_args.args[1] == 'shuffle_set'
              and call.call_args.args[2]['shuffle'] is True, "shuffle payload")

        main.ha_media_command('media_player.k',
                              main.MediaCommandRequest(command='repeat_set', repeat='one'))
        check(call.call_args.args[2]['repeat'] == 'one', "repeat payload")

        main.music_play(main.MusicPlayRequest(
            entity_id='media_player.k', media_id='lib://t/1',
            media_type='track', enqueue='add'))
        check(call.call_args.args[2]['enqueue'] == 'add', "enqueue rides along")

        main.music_play(main.MusicPlayRequest(
            entity_id='media_player.k', media_id='lib://t/1', radio_mode=True))
        check(call.call_args.args[2]['radio_mode'] is True, "radio_mode rides along")
        check('enqueue' not in call.call_args.args[2],
              "absent options stay absent — MA validates its schemas")

    try:
        main.ha_media_command('media_player.k',
                              main.MediaCommandRequest(command='repeat_set', repeat='forever'))
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "bad repeat mode -> 400")

    # A refused radio start must say WHY — it is the one refusal a person
    # can act on (pick a provider that does radio), and the generic 502
    # reads as "music is broken".
    with mock.patch.object(ha_api, 'call_service', return_value=None):
        try:
            main.music_play(main.MusicPlayRequest(
                entity_id='media_player.k', media_id='x', radio_mode=True))
            check(False, "expected 502")
        except HTTPException as e:
            check('adio mode' in e.detail, f"radio refusal explains itself: {e.detail}")


def scenario_media_players_carry_queue_state():
    """Shuffle/repeat buttons draw the player's answer, and radio-from-this
    needs the playing uri — all three must survive the listing."""
    import main
    states = [{"entity_id": "media_player.k", "state": "playing",
               "attributes": {"friendly_name": "K", "mass_player_type": "player",
                              "shuffle": True, "repeat": "all",
                              "media_content_id": "spotify://track/42"}}]
    with mock.patch.object(ha_api, 'get_states', return_value=states):
        p = main.ha_media_players()[0]
    check(p['shuffle'] is True and p['repeat'] == 'all', "queue switches surfaced")
    check(p['media_content_id'] == 'spotify://track/42', "playing uri surfaced")


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


def scenario_absolute_url_artwork():
    import base64
    import main
    from fastapi import HTTPException
    req = mock.Mock()
    req.headers = {}

    def enc(u):
        return base64.urlsafe_b64encode(u.encode()).decode().rstrip('=')

    with mock.patch.object(ha_api, 'fetch_binary',
                           return_value=(b'img', 'image/png')) as fetch:
        for ok_url in ('http://192.168.1.5:8095/imageproxy/x',
                       'http://homeassistant.local:8095/imageproxy/x',
                       'http://127.0.0.1:8095/x'):
            resp = main.ha_image64(enc(ok_url), req)
            check(resp.body == b'img', f"LAN absolute url allowed: {ok_url}")
        check(fetch.call_args.args[0] == 'http://127.0.0.1:8095/x', "url passed verbatim")

    for bad_url in ('http://evil.example.com/x', 'http://8.8.8.8/x'):
        try:
            main.ha_image64(enc(bad_url), req)
            check(False, f"expected 400 for {bad_url}")
        except HTTPException as e:
            check(e.status_code == 400, f"non-LAN host rejected: {bad_url}")

    # absolute fetch must NOT carry the HA token
    os.environ["SUPERVISOR_TOKEN"] = "secret"
    resp = mock.Mock(status_code=200, content=b'x', headers={'Content-Type': 'image/png'})
    with mock.patch.object(ha_api.requests, 'get', return_value=resp) as get:
        ha_api.fetch_binary('http://192.168.1.5:8095/imageproxy/x')
        check('headers' not in get.call_args.kwargs
              or 'Authorization' not in (get.call_args.kwargs.get('headers') or {}),
              "HA token never sent to non-HA hosts")
    os.environ.pop("SUPERVISOR_TOKEN", None)


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


def scenario_sendspin_relay_setup():
    import main
    from services import storage

    def set_settings(doc):
        with storage.db_lock:
            storage.settings_table.truncate()
            if doc:
                storage.settings_table.insert(doc)

    try:
        set_settings({"ma_server_url": "http://192.168.1.50"})
        cands = main._ma_ws_candidates()
        check(cands[0] == 'ws://192.168.1.50:8927/sendspin',
              f"configured URL normalized (scheme/port/path), got {cands[0]}")
        check('ws://d5369777-music-assistant:8927/sendspin' in cands,
              "official MA add-on hostname candidate present")

        set_settings({"ma_server_url": "ws://ma.example:9999/sendspin"})
        check(main._ma_ws_candidates()[0] == 'ws://ma.example:9999/sendspin',
              "explicit port + path preserved")

        set_settings({"ha_base_url": "http://192.168.1.7:8123"})
        check('ws://192.168.1.7:8927/sendspin' in main._ma_ws_candidates(),
              "HA host derives a candidate")

        check(any(getattr(r, 'path', '') == '/api/sendspin/ws' for r in main.app.routes),
              "websocket relay route registered")
    finally:
        set_settings(None)
        main._MA_WS_CACHE['url'] = None


SCENARIOS = [
    scenario_sendspin_relay_setup,
    scenario_media_players_listing,
    scenario_queue_verbs_map_to_ha_services,
    scenario_media_players_carry_queue_state,
    scenario_image_proxy,
    scenario_image64_roundtrip,
    scenario_absolute_url_artwork,
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
