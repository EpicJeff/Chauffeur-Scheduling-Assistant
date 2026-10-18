"""Additional runtime checks for release retries and mission-step ask copies."""
import traceback
import uuid
import os
from unittest.mock import patch

from harness import check
from test_deletion_core import build, finish, start_ok
from test_subjects import MOM
from services import programs, storage


def scenario_release_keeps_failed_ids_and_reports_failure():
    fx = build()
    pid = fx.ids['GP1']
    ids = [storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': 'kid', 'title': 'Practice',
            'source': {'kind': 'program', 'id': pid}}) for _ in range(2)]
    storage.update_program(pid, {'emissions': {'commitment_ids': ids, 'thread_ids': [fx.ids['GK1']]}})
    real = storage.delete_protected_commitment

    def fail_one(cid):
        if cid == ids[0]:
            raise OSError('locked')
        real(cid)

    with patch.object(storage, 'delete_protected_commitment', fail_one):
        try:
            programs.release_commitments(pid)
        except RuntimeError:
            pass
        else:
            check(False, 'a failed release reports failure to its caller')
    em = storage.get_program(pid)['emissions']
    check(em['commitment_ids'] == [ids[0]], 'only failed ids remain available to retry')
    check(em['thread_ids'] == [fx.ids['GK1']], 'other emissions remain intact')
    check(storage.get_protected_commitment(ids[1]) is None, 'successful releases stay released')
    check(programs.release_commitments(pid) == 1, 'the retry releases the remaining commitment')
    check(storage.get_program(pid)['emissions']['commitment_ids'] == [], 'nothing remains to retry')


def scenario_a_card_naming_only_a_mission_step_ask_is_removed():
    fx = build()
    mid = fx.ids['GM2']
    aid = storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question',
                                        'result_json': {'question': 'Which one?'}})
    argyle = storage.ensure_argyle_member()['id']
    dm = storage.get_or_create_dm(argyle, 'mom')
    from models.schemas import ChatMessage
    message = ChatMessage(channel_id=dm['id'], sender_member_id=argyle,
                          body='Which one?', card={'kind': 'ask', 'ask_id': aid}).model_dump()
    storage.add_chat_message(message)
    start_ok('mission', mid, dict(MOM))
    finish()
    check(storage.get_chat_message(message['id']) is None, 'step ask copies go before their ledger')
    check(storage.get_thread(fx.ids['GT1']), 'unrelated work survives')


def scenario_orphan_thread_files_and_commitment_notice_markers_go():
    build()
    orphan = uuid.uuid4().hex
    folder = os.path.join(os.path.dirname(storage.DB_PATH), 'threads', orphan)
    os.makedirs(folder)
    with open(os.path.join(folder, 'partial.png'), 'wb') as handle:
        handle.write(b'partial')
    storage.set_app_state('watcher_notified', {f'pc_cover:{orphan}:drive': 1,
                                              f'erosion:{orphan}:drive': 1,
                                              'chore_verify:unrelated:123': 1})
    from services import deletion
    out = deletion.maintain()
    check(out['orphans'] >= 2, 'orphan files and markers are counted')
    check(not os.path.exists(folder), 'a thread folder without its parent is removed')
    check(storage.get_app_state('watcher_notified') == {'chore_verify:unrelated:123': 1},
          'only known orphan parent markers are removed')


if __name__ == '__main__':
    scenarios = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
    failed = 0
    for scenario in scenarios:
        try:
            scenario()
            print(f'PASS {scenario.__name__}')
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'{len(scenarios) - failed}/{len(scenarios)} scenarios passed')
    raise SystemExit(bool(failed))
