"""Additional runtime checks for release retries and mission-step ask copies."""
import traceback
import uuid
import os
import time
from unittest.mock import patch

from harness import check
from test_deletion_core import build, finish, start_ok, http
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
    adhoc = os.path.join(os.path.dirname(storage.DB_PATH), 'browse', 'adhoc')
    os.makedirs(adhoc, exist_ok=True)
    with open(os.path.join(adhoc, 'keep.png'), 'wb') as handle:
        handle.write(b'adhoc browse')
    with open(os.path.join(folder, 'partial.png'), 'wb') as handle:
        handle.write(b'partial')
    storage.set_app_state('watcher_notified', {f'pc_cover:{orphan}:drive': 1,
                                              f'erosion:{orphan}:drive': 1,
                                              'chore_verify:unrelated:123': 1})
    from services import deletion
    out = deletion.maintain(force_orphans=True)
    check(out['orphans'] >= 2, 'orphan files and markers are counted')
    check(not os.path.exists(folder), 'a thread folder without its parent is removed')
    check(os.path.isfile(os.path.join(adhoc, 'keep.png')), 'the non-mission adhoc browse folder survives')
    check(storage.get_app_state('watcher_notified') == {'chore_verify:unrelated:123': 1},
          'only known orphan parent markers are removed')


def scenario_idle_ticks_do_not_scan_or_write_tables():
    from services import deletion, storage_sqlite
    build()
    with patch.object(deletion, '_orphan_checked_at', 1000), \
            patch.object(deletion.time, 'monotonic', return_value=1001), \
            patch.object(storage_sqlite.SqliteTable, 'all', side_effect=AssertionError('idle table scan')), \
            patch.object(storage_sqlite.SqliteTable, 'remove', side_effect=AssertionError('idle write')), \
            patch.object(deletion.os, 'listdir', side_effect=AssertionError('idle directory scan')):
        check(deletion.maintain() == {'finished': 0, 'waiting': 0, 'orphans': 0}, 'idle tick is cheap')


def scenario_orphan_sweeps_are_due_on_startup_completion_hourly_and_force():
    from services import deletion
    fx = build()
    with patch.object(deletion, '_orphan_checked_at', None), \
            patch.object(deletion.time, 'monotonic', return_value=1000) as clock, \
            patch.object(deletion, '_orphans', return_value=0) as sweep:
        deletion.maintain()
        check(sweep.call_count == 1, 'first pass sweeps at startup')
        clock.return_value = 1000 + 3599
        deletion.maintain()
        check(sweep.call_count == 1, 'no extra sweep before an hour')
        clock.return_value = 1000 + 3600
        deletion.maintain()
        check(sweep.call_count == 2, 'an hour makes the sweep due')
        deletion.maintain(force_orphans=True)
        check(sweep.call_count == 3, 'an explicit caller can force a sweep')
        start_ok('mission', fx.ids['GM2'], dict(MOM))
        check(deletion.maintain()['finished'] == 1, 'the idle mission is deleted')
        check(sweep.call_count == 4, 'finishing a deletion sweeps even within the hour')


def scenario_orphan_removals_use_only_nonempty_doc_ids():
    from services import deletion, storage_sqlite
    build()
    orphan = uuid.uuid4().hex
    storage.mission_steps_table.insert({'id': uuid.uuid4().hex, 'mission_id': orphan})
    real = storage_sqlite.SqliteTable.remove
    calls = []

    def checked(table, cond=None, doc_ids=None):
        check(cond is None and doc_ids, f'orphan writes name nonempty document ids: {table.name}')
        calls.append(table.name)
        return real(table, doc_ids=doc_ids)

    with patch.object(storage_sqlite.SqliteTable, 'remove', checked):
        deletion.maintain(force_orphans=True)
        check('mission_steps' in calls, 'the injected orphan was removed')
        calls.clear()
        deletion.maintain(force_orphans=True)
        check(not calls, 'a clean orphan pass opens no remove transactions')


def scenario_failed_orphan_sweeps_do_not_rescan_every_tick():
    from services import deletion
    build()
    with patch.object(deletion, '_orphan_checked_at', None), \
            patch.object(deletion.time, 'monotonic', return_value=1000) as clock, \
            patch.object(deletion, '_orphans', side_effect=OSError('unavailable archive')) as sweep:
        try:
            deletion.maintain()
        except OSError:
            pass
        else:
            check(False, 'the sweep failure is reported to the loop')
        clock.return_value = 1120
        deletion.maintain()
        check(sweep.call_count == 1, 'a failed sweep does not trigger a scan at the next idle tick')


def scenario_legacy_photo_cleanup_never_regenerates_a_poster():
    from test_deletion_cleanup import PNG
    fx = build()
    tid = fx.ids['GT1']
    # The .jpg suffix is essential: only a missing JPEG invokes poster repair.
    media = storage.save_photo_bytes(PNG, 'image/jpeg')
    storage.append_thread_history(tid, {'kind': 'photo', 'media_id': media['id'], 'ts': time.time()})
    clip = storage.media_write_path(media['id'].split('.')[0] + '.mp4')
    with open(clip, 'wb') as handle:
        handle.write(b'unrelated clip with the same stem')
    start_ok('thread', tid, dict(MOM))
    with patch.object(storage, 'generate_poster', side_effect=AssertionError('cleanup regenerated a poster')):
        finish()
    check(storage.media_read_path(media['id']) is None, 'the legacy photo is removed')
    check(os.path.isfile(clip), 'lookup did not regenerate a poster from this clip')


def scenario_cleanup_resolves_shared_message_refs_once():
    from services import deletion
    from models.schemas import ChatMessage
    fx = build()
    survivor = fx.ids['R5t']
    argyle = storage.ensure_argyle_member()['id']
    dm = storage.get_or_create_dm(argyle, 'mom')
    for _ in range(10):
        message = ChatMessage(channel_id=dm['id'], sender_member_id=argyle, body='Keep').model_dump()
        message['refs'] = [{'kind': 'thread', 'id': survivor}]
        storage.add_chat_message(message)
    start_ok('mission', fx.ids['GM2'], dict(MOM))
    real = storage.get_thread
    loads = []

    def counted(tid):
        if tid == survivor:
            loads.append(tid)
        return real(tid)

    with patch.object(storage, 'get_thread', counted):
        deletion.maintain()
    check(len(loads) == 1, f'ten messages share one resolved reference: {loads}')


def scenario_hand_program_actions_report_release_failure_without_a_500():
    for verb in ('pause', 'resume', 'reshape', 'finish', 'milestone', 'drop'):
        fx = build()
        pid = fx.ids['GP1']
        cid = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': 'kid',
            'title': 'Practice', 'days_of_week': [1], 'time_start': '17:00', 'time_end': '17:30',
            'source': {'kind': 'program', 'id': pid}})
        state = 'paused' if verb == 'resume' else 'active'
        storage.update_program(pid, {'state': state, 'phases': [{'name': 'Last', 'milestone_hit_at': None}],
                                     'emissions': {'commitment_ids': [cid], 'thread_ids': []}})
        with patch.object(storage, 'delete_protected_commitment', side_effect=OSError('locked')):
            response = http('mom', 'POST', f'/api/programs/{pid}/{verb}', json={'phase_name': 'Last'})
        result = response.json()
        check(response.status_code == 200 and result.get('status') == 'error' and result.get('message'),
              f'{verb} reports the failure by hand: {response.status_code} {result}')
        row = storage.get_program(pid)
        check(row['state'] == state and row['emissions']['commitment_ids'] == [cid],
              f'{verb} retains the failed claim and its prior state for retry')
        if verb == 'milestone':
            check(not row['phases'][0]['milestone_hit_at'], 'a failed final milestone is still retryable')
            response = http('mom', 'POST', f'/api/programs/{pid}/{verb}', json={'phase_name': 'Last'})
            check(response.json()['status'] == 'success' and storage.get_program(pid)['state'] == 'done',
                  'the same milestone succeeds after release recovers')


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
