"""Tests for services/music_search.py — grouped search over either path.

Run from chauffeur/:  python tests/test_music_search.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_music_search_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ma_api, music_search as ms  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset():
    ms._providers_cache['ts'] = 0.0
    ms._providers_cache['data'] = None


def _ma_track(name, uri, providers=('spotify',), favorite=False,
              provider='library', images=None):
    return {
        'name': name, 'uri': uri, 'media_type': 'track', 'provider': provider,
        'favorite': favorite,
        'artists': [{'name': 'Artist'}], 'album': {'name': 'Album'},
        'provider_mappings': [{'provider_domain': d, 'provider_instance': d + '1'}
                              for d in providers],
        'metadata': {'images': images or []},
    }


def scenario_ma_answer_stays_grouped_and_normalized():
    """The whole point of the overhaul: groups survive, in the fixed order,
    and every row is the one shape both surfaces draw."""
    result = {'tracks': [_ma_track('T1', 'lib://t/1', favorite=True)],
              'albums': [dict(_ma_track('A1', 'lib://a/1'), media_type='album')],
              'artists': [], 'playlists': [], 'radio': [],
              'audiobooks': [], 'podcasts': []}
    def fake_command(name, **kw):
        return result if name == 'music/search' else []

    with mock.patch.object(ma_api, 'command', side_effect=fake_command), \
            mock.patch.object(ma_api, 'resolve_base',
                              return_value='http://ma:8095'):
        out = ms.search('queen')
    check(out['source'] == 'ma', "MA path taken")
    check([g['type'] for g in out['groups']] == ['track', 'album'],
          f"groups in display order, empties dropped: {[g['type'] for g in out['groups']]}")
    row = out['groups'][0]['items'][0]
    check(row['favorite'] is True and row['in_library'] is True,
          "favourite + library flags carried (this is what the HA path lacks)")
    check(row['providers'] == ['spotify'], f"provider domains: {row['providers']}")
    check(row['artists'] == [{'name': 'Artist'}]
          and row['album'] == {'name': 'Album'},
          "subtitle fields shaped as subtitleOf reads them")


def scenario_provider_chips_and_filter():
    """Chips are counted BEFORE the filter, so every real choice stays
    offered; the filter itself narrows rows to that provider."""
    result = {'tracks': [_ma_track('S', 's1', providers=('spotify',)),
                         _ma_track('Y', 'y1', providers=('ytmusic',)),
                         _ma_track('B', 'b1', providers=('spotify', 'ytmusic'))],
              'albums': [], 'artists': [], 'playlists': [], 'radio': [],
              'audiobooks': [], 'podcasts': []}

    def fake_command(name, **kw):
        if name == 'config/providers':
            return [{'domain': 'spotify', 'name': 'Spotify'},
                    {'domain': 'ytmusic', 'name': 'YouTube Music'}]
        return result

    with mock.patch.object(ma_api, 'command', side_effect=fake_command), \
            mock.patch.object(ma_api, 'resolve_base',
                              return_value='http://ma:8095'):
        out = ms.search('x', provider='ytmusic')
    chips = {p['domain']: p for p in out['providers']}
    check(set(chips) == {'spotify', 'ytmusic'},
          f"chips offer every provider in the UNFILTERED set: {set(chips)}")
    check(chips['spotify']['name'] == 'Spotify', "display name from config")
    check(chips['spotify']['count'] == 2 and chips['ytmusic']['count'] == 2,
          "counts are per result, before the filter")
    names = [r['name'] for r in out['groups'][0]['items']]
    check(names == ['Y', 'B'], f"rows narrowed to the provider: {names}")


def scenario_artwork_urls_choose_their_route():
    """https + remotely accessible passes through; a proxy_id builds the
    opaque form; anything else the legacy double-encoded form. All http://
    results are the browser-side image64 proxy's problem, not ours."""
    remote = {'type': 'thumb', 'path': 'https://cdn/x.jpg',
              'remotely_accessible': True}
    opaque = {'type': 'thumb', 'path': 'spotify://img', 'proxy_id': 'ab12',
              'remotely_accessible': False}
    legacy = {'type': 'thumb', 'path': 'a b/c', 'provider': 'spotify',
              'remotely_accessible': False}
    base = 'http://ma:8095'
    check(ms._image_url({'metadata': {'images': [remote]}}, base)
          == 'https://cdn/x.jpg', "remote https used as-is")
    check(ms._image_url({'metadata': {'images': [opaque]}}, base)
          == 'http://ma:8095/imageproxy/ab12?size=256', "proxy_id form")
    got = ms._image_url({'metadata': {'images': [legacy]}}, base)
    check(got == 'http://ma:8095/imageproxy?path=a%2520b%252Fc&provider=spotify',
          f"legacy form double-encodes the path: {got}")
    check(ms._image_url({'metadata': {'images': []}}, base) is None,
          "no image, no URL")


def scenario_falls_back_to_ha_when_ma_is_silent():
    import main
    main._MA_CONFIG_ENTRY['id'] = 'e1'
    main._MA_CONFIG_ENTRY['checked'] = True
    from services import ha_api
    try:
        with mock.patch.object(ma_api, 'command', return_value=None), \
                mock.patch.object(ha_api, 'call_service',
                                  return_value={'service_response': {
                                      'tracks': [{'name': 'X', 'uri': 'u',
                                                  'artists': ['A'],
                                                  'album': 'Al'}]}}):
            out = ms.search('x')
        check(out['source'] == 'ha', "fell back")
        row = out['groups'][0]['items'][0]
        check(row['artists'] == [{'name': 'A'}] and row['album'] == {'name': 'Al'},
              f"HA string artists/album lifted to dicts: {row}")
        check(row['favorite'] is None and row['in_library'] is None,
              "unknown stays None on the HA path — not False")
        check(out['providers'] == [], "no chips without provider data")
    finally:
        main._MA_CONFIG_ENTRY['id'] = None
        main._MA_CONFIG_ENTRY['checked'] = False


def scenario_media_type_narrows_both_paths():
    result = {'tracks': [_ma_track('T', 't1')],
              'albums': [dict(_ma_track('A', 'a1'), media_type='album')],
              'artists': [], 'playlists': [], 'radio': [],
              'audiobooks': [], 'podcasts': []}
    def fake_command(name, **kw):
        return result if name == 'music/search' else []

    with mock.patch.object(ma_api, 'command', side_effect=fake_command) as cmd, \
            mock.patch.object(ma_api, 'resolve_base',
                              return_value='http://ma:8095'):
        out = ms.search('x', media_types=['album'])
        check([g['type'] for g in out['groups']] == ['album'],
              "only the asked-for group returns, even if MA answers wider")
        search_call = next(c for c in cmd.call_args_list
                           if c.args[0] == 'music/search')
        check(search_call.kwargs['media_types'] == ['album'],
              "the narrowing also went to MA")
    check(ms.search.__defaults__ is not None, "sanity")


def scenario_no_path_at_all_is_a_503():
    import main
    main._MA_CONFIG_ENTRY['id'] = None
    main._MA_CONFIG_ENTRY['checked'] = True
    try:
        with mock.patch.object(ma_api, 'command', return_value=None):
            try:
                ms.search('x')
                check(False, "expected MusicSearchError")
            except ms.MusicSearchError as e:
                check(e.status == 503, f"503, got {e.status}")
    finally:
        main._MA_CONFIG_ENTRY['checked'] = False


SCENARIOS = [
    scenario_ma_answer_stays_grouped_and_normalized,
    scenario_provider_chips_and_filter,
    scenario_artwork_urls_choose_their_route,
    scenario_falls_back_to_ha_when_ma_is_silent,
    scenario_media_type_narrows_both_paths,
    scenario_no_path_at_all_is_a_503,
]


if __name__ == '__main__':
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
    sys.exit(1 if failed else 0)
