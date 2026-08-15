"""Tests for services/music_queue.py — the queue as a visible, editable list.

Run from chauffeur/:  python tests/test_music_queue.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_music_queue_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ha_api, ma_api, music_queue as mq  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


STATE = {'entity_id': 'media_player.kitchen', 'state': 'playing',
         'attributes': {'mass_player_id': 'ma-player-1'}}


def _ma_item(i, name):
    return {'queue_item_id': f'qi{i}', 'name': name,
            'media_item': {'name': name, 'media_type': 'track',
                           'artists': [{'name': 'A'}],
                           'album': {'name': 'Al'},
                           'metadata': {'images': []}}}


def scenario_ma_path_is_the_whole_editable_list():
    def fake_command(name, **kw):
        if name == 'player_queues/get_active_queue':
            return {'queue_id': 'q1', 'current_index': 2, 'items': 40}
        if name == 'player_queues/items':
            check(kw['offset'] == 2, f"windowed from the playing item: {kw}")
            return [_ma_item(2, 'Now'), _ma_item(3, 'Next'), _ma_item(4, 'Then')]
        return {}

    with mock.patch.object(ha_api, 'get_state', return_value=STATE), \
            mock.patch.object(ma_api, 'available', return_value=True), \
            mock.patch.object(ma_api, 'command', side_effect=fake_command), \
            mock.patch.object(ma_api, 'resolve_base', return_value='http://ma:8095'):
        out = mq.get_queue('media_player.kitchen')
    check(out['source'] == 'ma' and out['can_edit'] is True, "editable MA queue")
    check([r['name'] for r in out['items']] == ['Now', 'Next', 'Then'], "rows")
    check(out['items'][0]['current'] is True and out['items'][1]['current'] is False,
          "the playing row is marked")
    check(out['items'][1]['id'] == 'qi3', "stable ids for the edit verbs")
    check(out['items'][1]['subtitle'] == 'A · Al', "subtitle shaped for the row")


def scenario_ha_path_is_a_two_row_peek():
    """No mass_player_id (or no token): the HA bridge sees current+next only,
    and can_edit says so — the surfaces hide the verbs instead of offering
    buttons that fail on press."""
    resp = {'service_response': {'media_player.kitchen': {
        'current_item': {'media_title': 'Now', 'media_artist': 'A'},
        'next_item': {'media_title': 'Next', 'media_artist': 'B'},
    }}}
    bare = {'entity_id': 'media_player.kitchen', 'attributes': {}}
    with mock.patch.object(ha_api, 'get_state', return_value=bare), \
            mock.patch.object(ha_api, 'call_service', return_value=resp):
        out = mq.get_queue('media_player.kitchen')
    check(out['source'] == 'ha' and out['can_edit'] is False, "read-only peek")
    check([r['name'] for r in out['items']] == ['Now', 'Next'], "two rows")
    check(out['items'][0]['current'] is True, "current marked on the peek too")


def scenario_edits_map_to_ma_verbs():
    calls = []

    def fake_command(name, **kw):
        calls.append((name, kw))
        if name == 'player_queues/get_active_queue':
            return {'queue_id': 'q1'}
        return {}   # void success

    with mock.patch.object(ha_api, 'get_state', return_value=STATE), \
            mock.patch.object(ma_api, 'available', return_value=True), \
            mock.patch.object(ma_api, 'command', side_effect=fake_command):
        ok, _ = mq.command('media_player.kitchen', 'move_up', queue_item_id='qi3')
        check(ok, "move_up ok")
        check(('player_queues/move_item',
               {'queue_id': 'q1', 'queue_item_id': 'qi3', 'pos_shift': -1}) in calls,
              f"move_up is pos_shift -1: {calls}")
        ok, _ = mq.command('media_player.kitchen', 'remove', queue_item_id='qi3')
        check(ok and calls[-1][0] == 'player_queues/delete_item', "remove maps")
        ok, _ = mq.command('media_player.kitchen', 'play_index', index=4)
        check(ok and calls[-1] == ('player_queues/play_index',
                                   {'queue_id': 'q1', 'index': 4}), "play_index maps")
        ok, _ = mq.command('media_player.kitchen', 'clear')
        check(ok and calls[-1][0] == 'player_queues/clear', "clear maps")
        ok, detail = mq.command('media_player.kitchen', 'explode')
        check(not ok and 'explode' in detail, "unknown action refused by name")


def scenario_edits_without_the_token_explain_themselves():
    with mock.patch.object(ha_api, 'get_state', return_value=STATE), \
            mock.patch.object(ma_api, 'available', return_value=False):
        ok, detail = mq.command('media_player.kitchen', 'clear')
    check(not ok, "no MA, no edit")
    check('token' in detail.lower(),
          f"the refusal names the missing piece: {detail}")


def scenario_void_ma_results_read_as_success():
    """MA answers queue edits with result: null. ma_api must hand back {} —
    None is its failure value, and a successful clear that reports failure
    teaches people the queue is broken."""
    resp = mock.Mock(status_code=200, text='x')
    resp.json.return_value = {'message_id': '1', 'result': None}
    from services import storage
    with storage.db_lock:
        storage.settings_table.truncate()
        storage.settings_table.insert({'ma_token': 't', 'ma_server_url': '10.0.0.5'})
    ma_api.reset()
    try:
        with mock.patch.object(ma_api.requests, 'get',
                               return_value=mock.Mock(status_code=200, text='x',
                                                      json=lambda: {'server_version': '2.7'})), \
                mock.patch.object(ma_api.requests, 'post', return_value=resp):
            out = ma_api.command('player_queues/clear', queue_id='q1')
        check(out == {}, f"null result -> {{}}, got {out!r}")
    finally:
        with storage.db_lock:
            storage.settings_table.truncate()
        ma_api.reset()


SCENARIOS = [
    scenario_ma_path_is_the_whole_editable_list,
    scenario_ha_path_is_a_two_row_peek,
    scenario_edits_map_to_ma_verbs,
    scenario_edits_without_the_token_explain_themselves,
    scenario_void_ma_results_read_as_success,
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
