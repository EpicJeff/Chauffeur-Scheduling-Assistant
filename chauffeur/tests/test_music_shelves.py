"""Tests for services/music_shelves.py — MA shelves + playlist writes.

Run from chauffeur/:  python tests/test_music_shelves.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_music_shelves_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ma_api, music_shelves as ms  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _track(name, uri):
    return {'name': name, 'uri': uri, 'media_type': 'track',
            'provider': 'library', 'artists': [{'name': 'A'}],
            'provider_mappings': [], 'metadata': {'images': []}}


def scenario_no_ma_means_absent_never_error():
    with mock.patch.object(ma_api, 'available', return_value=False):
        out = ms.shelves()
        check(out == {'available': False, 'recently_played': [],
                      'recommendations': []}, f"absent, quietly: {out}")
        check(ms.editable_playlists() == [], "no playlists to offer")
        ok, detail = ms.add_to_playlist('1', 'u')
        check(not ok and 'token' in detail.lower(),
              "the refusal names the missing piece")


def scenario_shelves_parse_both_recommendation_shapes():
    """MA's recommendations shape has moved between versions: folders with
    items, or bare items. Both draw; garbage is dropped."""
    def fake_command(name, **kw):
        if name == 'music/recently_played_items':
            return [_track('R1', 'r1')]
        if name == 'music/recommendations':
            return [{'name': 'Because you played X', 'items': [_track('T', 't1')]},
                    _track('Bare', 'b1'),
                    'garbage']
        return []

    with mock.patch.object(ma_api, 'available', return_value=True), \
            mock.patch.object(ma_api, 'command', side_effect=fake_command), \
            mock.patch.object(ma_api, 'resolve_base', return_value='http://ma:8095'):
        out = ms.shelves()
    check(out['available'] is True, "available")
    check([r['name'] for r in out['recently_played']] == ['R1'], "recent rows")
    check(out['recommendations'][0]['name'] == 'Because you played X'
          and out['recommendations'][0]['items'][0]['name'] == 'T',
          "folder-shaped recommendation kept its name")
    check(out['recommendations'][1]['name'] == 'For the house'
          and out['recommendations'][1]['items'][0]['name'] == 'Bare',
          "bare items collect under a generic shelf")


def scenario_only_editable_playlists_are_offered():
    def fake_command(name, **kw):
        if name == 'music/playlists/library_items':
            return [{'item_id': '1', 'name': 'Road trip', 'is_editable': True},
                    {'item_id': '2', 'name': 'Spotify: Weekly', 'is_editable': False}]
        return []

    with mock.patch.object(ma_api, 'available', return_value=True), \
            mock.patch.object(ma_api, 'command', side_effect=fake_command):
        out = ms.editable_playlists()
    check(out == [{'item_id': '1', 'name': 'Road trip'}],
          f"a read-only playlist offered as a target: {out}")


def scenario_playlist_writes_map_to_ma_verbs():
    calls = []

    # First param named `cmd` on purpose — create_playlist's own argument is
    # literally `name`, and a first parameter called `name` makes that
    # command IMPOSSIBLE to send (TypeError: multiple values). This mock's
    # signature pins ma_api.command's.
    def fake_command(cmd, **kw):
        calls.append((cmd, kw))
        if cmd == 'music/playlists/create_playlist':
            return {'item_id': '9', 'name': kw['name']}
        return {}

    with mock.patch.object(ma_api, 'available', return_value=True), \
            mock.patch.object(ma_api, 'command', side_effect=fake_command):
        ok, _ = ms.add_to_playlist('1', 'lib://t/5')
        check(ok, "add ok")
        check(calls[-1] == ('music/playlists/add_playlist_tracks',
                            {'db_playlist_id': '1', 'uris': ['lib://t/5']}),
              f"add maps: {calls[-1]}")
        ok, _, playlist = ms.create_playlist('Road trip', uri='lib://t/5')
        check(ok and playlist == {'item_id': '9', 'name': 'Road trip'}, "created")
        check(calls[-1][0] == 'music/playlists/add_playlist_tracks'
              and calls[-1][1]['db_playlist_id'] == '9',
              "the seeding track landed in the NEW list")


SCENARIOS = [
    scenario_no_ma_means_absent_never_error,
    scenario_shelves_parse_both_recommendation_shapes,
    scenario_only_editable_playlists_are_offered,
    scenario_playlist_writes_map_to_ma_verbs,
]


if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    sys.exit(1 if failed else 0)
