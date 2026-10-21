"""programs.monitor and remove_session (spec §5.1). Run from chauffeur/: python tests/test_program_monitor.py"""
import datetime, time
from unittest.mock import patch

from program_fixture import add_run, loaded, phase_id  # harness first
from harness import check  # noqa: F401
from services import storage, programs

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}
BASE = {'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': [0, 2, 4]},
        'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'plays a C scale', 'progression': 'one less reminder',
                    'units': [{'title': 'Hands and keys', 'sessions': 1}, {'title': 'Scales', 'sessions': 2}], 'rotation': [{'label': 'A', 'steps': ['r']}, {'label': 'B', 'steps': ['l']}]},
                   {'name': 'Songs', 'weeks': 3, 'steps': ['b'], 'milestone': 'plays Twinkle', 'units': [{'title': 'Twinkle', 'sessions': 2}]}],
        'source': {'origin': 'none', 'reason': 'test'},
        'baseline': {'start_date': '2026-10-01', 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}


def _reset():
    for t in (storage.programs_table, storage.library_programs_table, storage.members_table, storage.protected_commitments_table):
        t.truncate()
    storage.add_member(dict(MOM)); storage.add_member(dict(KID))
    return add_run({'id': 'r1', 'member_id': 'kid', 'title': 'Piano', 'state': 'active', **BASE})


def _lesson_ids(rid):
    return [l['id'] for l in loaded(rid)['lessons']]


def scenario_sessions_carry_ids():
    rid = _reset()
    programs.log_session(rid, minutes=20)
    s = storage.get_program(rid)['sessions'][0]
    check(isinstance(s.get('id'), str) and len(s['id']) == 32, f"a new session has an id: {s}")


def scenario_migration_mints_ids_once():
    rid = _reset()
    storage.set_app_state('program_session_ids_v2499', None)
    storage.update_program(rid, {'sessions': [{'ts': time.time() - 86400, 'minutes': 10, 'source': 'added', 'note': ''}]})
    from services import migrations
    migrations.migrate_program_session_ids_v2499()
    first = storage.get_program(rid)['sessions'][0]['id']
    migrations.migrate_program_session_ids_v2499()
    check(first and storage.get_program(rid)['sessions'][0]['id'] == first, "ids are minted once and kept")


def scenario_monitor_stats_ladder_and_log():
    rid = _reset()
    ids = _lesson_ids(rid)
    actual_today = datetime.date.today()
    today = actual_today - datetime.timedelta(days=actual_today.weekday() + 3)  # last Friday
    monday = today - datetime.timedelta(days=today.weekday())
    programs.log_session(rid, minutes=20, slot_date=monday.isoformat(), lesson_id=ids[0], variant_label='A')          # completes lesson 1
    programs.log_session(rid, minutes=25, slot_date=(monday + datetime.timedelta(days=2)).isoformat(), lesson_id=ids[1], variant_label='B')
    win = [{'program_id': rid, 'date': (today + datetime.timedelta(days=1)).isoformat(), 'time_start': '18:00', 'lesson_id': ids[1], 'variant_label': 'A', 'unit_title': 'Scales', 'logged': False}]
    class MonitorDate(datetime.date):
        @classmethod
        def today(cls):
            return today
    with patch.object(programs, 'practice_windows', lambda *a, **k: win), patch.object(programs.datetime, 'date', MonitorDate):
        m = programs.monitor(loaded(rid), viewer=dict(MOM))
    check(m['sessions_this_week'] == 2 and m['sessions_total'] == 2 and m['minutes_total'] == 45, f"counts, never a fraction: {m}")
    expected_last = datetime.datetime.fromtimestamp(storage.get_program(rid)['sessions'][-1]['ts']).date().isoformat()
    check(m['last_practised'] == expected_last == (monday + datetime.timedelta(days=2)).isoformat(), f"last practised by timestamp date: {m['last_practised']}")
    check(m['next_window'] and m['next_window']['lesson_title'] == 'Scales' and m['next_window']['variant_label'] == 'A', f"next window: {m['next_window']}")
    ph = m['phases'][0]
    check(ph['current'] and ph['progression'] == 'one less reminder' and ph['milestone'] == 'plays a C scale', f"phase: {ph}")
    l1, l2 = ph['lessons']
    check(l1['completed'] and l1['done_sessions'] == 1 and not l1['current'], f"lesson 1 done: {l1}")
    check(l2['current'] and l2['done_sessions'] == 1 and l2['logged_variants'] == ['B'] and l2['next_variant'] == 'A', f"the lit rung knows its variants from the log and the next window: {l2}")
    check(not m['phases'][1]['current'] and m['phases'][1]['lessons'][0]['done_sessions'] == 0, "the second phase waits")
    row = m['log'][0]
    check(set(row) >= {'id', 'when', 'logged_on', 'minutes', 'lesson_title', 'variant_label', 'source'} and row['lesson_title'] == 'Scales', f"log rows: {row}")
    check(all(k not in str(m) for k in ('percent', 'of 12', '1 of 3')), "no completion fraction anywhere")


def scenario_monitor_all_judged():
    rid = _reset()
    for i in range(2):
        programs.mark_milestone(rid, phase_id=phase_id(rid, i))
    m = programs.monitor(loaded(rid), viewer=dict(MOM))
    check(len(m['phases']) == 2 and all(p['milestone_hit_at'] for p in m['phases']) and m['next_window'] is None, f"a judged-out run still renders: {m}")


def scenario_remove_session_reverses_its_credit():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, minutes=20, lesson_id=ids[0])
    row = storage.get_program(rid)
    check(row['progress']['current'] == ids[1], "the bookmark moved on")
    sid = row['sessions'][0]['id']
    res = programs.remove_session(rid, sid)
    row = storage.get_program(rid)
    check(res['status'] == 'success' and not row['sessions'] and row['progress']['current'] == ids[0]
          and not row['progress']['lessons'].get(ids[0], {}).get('completed_at'), f"the removed session's credit is reversed: {row['progress']}")
    check(programs.remove_session(rid, 'nope')['status'] == 'error', "unknown session")


def scenario_remove_keeps_a_judged_phase():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, minutes=20, lesson_id=ids[0])
    programs.mark_milestone(rid, phase_id=phase_id(rid, 0))
    sid = storage.get_program(rid)['sessions'][0]['id']
    programs.remove_session(rid, sid)
    p = storage.get_program(rid)['progress']
    check(p['phases'][phase_id(rid, 0)]['milestone_hit_at'] and p['current'] == ids[2], f"a person's judgement outlives a removed session: {p}")


def scenario_http():
    rid = _reset()
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    tok = {'X-Member-Token': storage.create_member_token('mom')}
    programs.log_session(rid, minutes=20)
    r = c.get(f'/api/programs/{rid}/monitor', headers=tok)
    check(r.status_code == 200 and r.json()['sessions_total'] == 1, f"monitor route: {r.text}")
    sid = storage.get_program(rid)['sessions'][0]['id']
    r = c.delete(f'/api/programs/{rid}/sessions/{sid}', headers=tok)
    check(r.status_code == 200 and not storage.get_program(rid)['sessions'], f"delete route: {r.text}")
    kid = {'X-Member-Token': storage.create_member_token('kid')}
    programs.log_session(rid, minutes=20)
    sid = storage.get_program(rid)['sessions'][0]['id']
    r = c.delete(f'/api/programs/{rid}/sessions/{sid}', headers=kid)
    check(r.status_code == 200 and not storage.get_program(rid)['sessions'], "the run's own keeper may remove their session")


def scenario_migration_covers_finished_and_legacy_and_preserves_existing_ids():
    rid = _reset()
    storage.set_app_state('program_session_ids_v2499', None)
    original = {'id': 'a' * 32, 'ts': 10, 'minutes': 5, 'note': 'keep me'}
    storage.update_program(rid, {'state': 'done', 'sessions': [original, {'ts': 20, 'minutes': 8}]})
    legacy = storage.add_program({'id': 'legacy', 'member_id': 'kid', 'state': 'dropped',
                                  'phases': [], 'sessions': [{'ts': 30, 'minutes': 9}]})
    from services import migrations
    migrations.migrate_program_session_ids_v2499()
    sessions = storage.get_program(rid)['sessions']
    check(sessions[0] == original and len(sessions[1]['id']) == 32, 'existing ids and session fields survive')
    check(len(storage.get_program(legacy)['sessions'][0]['id']) == 32, 'finished legacy runs migrate too')
    # Per-row idempotence even when startup is retried before its gate was saved.
    storage.set_app_state('program_session_ids_v2499', None)
    migrations.migrate_program_session_ids_v2499()
    check(storage.get_program(rid)['sessions'] == sessions, 'a gate-free retry keeps every minted id')
    with patch.object(storage, 'get_programs', side_effect=AssertionError('gate ignored')):
        migrations.migrate_program_session_ids_v2499()


def scenario_migration_startup_order_and_error_isolation():
    import asyncio
    import inspect
    from contextlib import ExitStack
    from unittest.mock import AsyncMock
    from services import migrations
    calls = []
    with ExitStack() as stack:
        for name, fn in vars(migrations).items():
            if name.startswith('migrate_') and callable(fn):
                replacement = AsyncMock() if inspect.iscoroutinefunction(fn) else (lambda: None)
                stack.enter_context(patch.object(migrations, name, replacement))
        stack.enter_context(patch.object(migrations.asyncio, 'sleep', AsyncMock()))
        stack.enter_context(patch.object(migrations, 'migrate_library_scripts_v2499',
                                        side_effect=lambda: calls.append('scripts')))
        def ids():
            calls.append('ids')
            raise RuntimeError('test migration error')
        stack.enter_context(patch.object(migrations, 'migrate_program_session_ids_v2499', side_effect=ids))
        logger = stack.enter_context(patch.object(migrations.logger, 'error'))
        asyncio.run(migrations.run_all_migrations())
        check(calls == ['scripts', 'ids'], 'the id migration runs after library scripts')
        check(any('test migration error' in str(c) for c in logger.call_args_list), 'startup logs the failure and continues')


def scenario_reconcile_rebuilt_lessons_keeps_judgements_and_selects_current():
    rid = _reset()
    raw = storage.get_program(rid)
    curriculum = storage.get_library_program(raw['library_id'])
    ids = _lesson_ids(rid)
    phases = {phase_id(rid, 0): {'milestone_hit_at': 123, 'weeks': 2}}
    rebuilt = {'lessons': {}, 'phases': phases, 'current': None}
    result = programs.reconcile_progress({**raw, 'progress': rebuilt}, curriculum)
    check(result['phases'] == phases and result['current'] == ids[2], 'judgement survives and the bookmark skips the judged phase')
    check(result['lessons'][ids[0]]['completed_at'] == 123, 'judgement still completes lessons, independent of the log')
    check(rebuilt['lessons'] == {}, 'reconciliation does not mutate its input')


def scenario_remove_decrements_its_lesson_and_ignores_removed_lessons():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, minutes=20, lesson_id=ids[0])
    programs.log_session(rid, minutes=25, lesson_id=ids[1])
    programs.log_session(rid, minutes=30, lesson_id=ids[1])
    row = storage.get_program(rid)
    sid = row['sessions'][-1]['id']
    storage.update_program(rid, {'sessions': row['sessions'] + [{'id': 'retired', 'lesson_id': 'gone', 'ts': 1}]})
    programs.remove_session(rid, sid)
    row = storage.get_program(rid)
    count = row['progress']['lessons'][ids[1]]
    check(count['done_sessions'] == 1 and not count['completed_at'] and row['progress']['current'] == ids[1], 'only the removed credit is reversed')
    check('gone' not in row['progress']['lessons'] and row['sessions'][-1]['id'] == 'retired', 'removed lesson history stays without becoming progress')


def scenario_remove_keeps_out_of_order_judgement_and_done_state():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, lesson_id=ids[0])
    programs.mark_milestone(rid, phase_id=phase_id(rid, 1))
    row = storage.get_program(rid)
    phases = row['progress']['phases']
    programs.remove_session(rid, row['sessions'][0]['id'])
    row = storage.get_program(rid)
    check(row['progress']['phases'] == phases and row['progress']['current'] == ids[0], 'a later-phase judgement survives removal exactly (P2)')
    programs.log_session(rid, lesson_id=ids[0])
    programs.mark_milestone(rid, phase_id=phase_id(rid, 0))
    row = storage.get_program(rid)
    phases = row['progress']['phases']
    programs.remove_session(rid, row['sessions'][0]['id'])
    row = storage.get_program(rid)
    check(row['state'] == 'done' and row['progress']['phases'] == phases and row['progress']['current'] is None, 'removal does not undo any judgement or reopen a finished run')


def scenario_remove_legacy_only_drops_the_session_and_errors_do_not_write():
    _reset()
    rid = storage.add_program({'id': 'legacy', 'member_id': 'kid', 'phases': BASE['phases'],
                               'progress': {'current': 'old', 'phases': {'old': {'milestone_hit_at': 123}}},
                               'sessions': [{'id': 'one', 'ts': 1}, {'id': 'two', 'ts': 2}]})
    before = storage.get_program(rid)
    check(programs.remove_session(rid, 'one')['status'] == 'success', 'legacy removal succeeds')
    after = storage.get_program(rid)
    check(after == {**before, 'sessions': [before['sessions'][1]]}, 'legacy progress and phase data are untouched')
    check(programs.remove_session(rid, 'unknown')['code'] == 404 and storage.get_program(rid) == after, 'unknown session writes nothing')
    check(programs.remove_session('unknown', 'two')['code'] == 404, 'unknown run is reported')


def scenario_remove_is_atomic():
    rid = _reset()
    programs.log_session(rid)
    before = storage.get_program(rid)
    original = storage.update_program
    def fail_after_update(*a, **k):
        original(*a, **k)
        raise RuntimeError('test write failure')
    with patch.object(storage, 'update_program', fail_after_update):
        try:
            programs.remove_session(rid, before['sessions'][0]['id'])
            raise AssertionError('the write should have failed')
        except RuntimeError:
            pass
    check(storage.get_program(rid) == before, 'both the log and progress roll back')


def scenario_monitor_empty_paused_and_unresolved_and_slot_dates():
    rid = _reset()
    storage.update_program(rid, {'state': 'paused'})
    with patch.object(programs, 'practice_windows', side_effect=AssertionError('paused run queried windows')):
        m = programs.monitor(loaded(rid), viewer=MOM)
    check(m['last_practised'] is None and m['sessions_this_week'] == 0 and m['next_window'] is None and m['log'] == [], 'empty paused run renders')
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    stamp = datetime.datetime.combine(monday, datetime.time(12)).timestamp()
    storage.update_program(rid, {'sessions': [{'id': 'old', 'ts': stamp, 'slot_date': (monday - datetime.timedelta(days=1)).isoformat(), 'minutes': 12},
                                              {'id': 'new', 'ts': stamp + 1, 'minutes': 8}]})
    m = programs.monitor(loaded(rid), viewer=MOM)
    check(m['sessions_this_week'] == 1 and m['minutes_total'] == 20, 'slot date takes precedence for the weekly count')
    check(m['log'][1]['when'] != m['log'][1]['logged_on'], 'the log distinguishes the slot and timestamp dates')
    storage.delete_library_program(storage.get_program(rid)['library_id'])
    m = programs.monitor(storage.get_program(rid), viewer=MOM)
    check(m['phases'] == [] and m['sessions_total'] == 2, 'an unresolved run retains its history')


def scenario_storage_mints_unique_ids_and_keeps_supplied_ids_and_key_guard():
    rid = _reset()
    storage.append_program_session(rid, {'id': 'f' * 32})
    storage.append_program_session(rid, {})
    storage.append_program_session(rid, {})
    rows = storage.get_program(rid)['sessions']
    check(rows[0]['id'] == 'f' * 32 and len({s['id'] for s in rows}) == 3, 'stable supplied ids and unique generated ids')
    try:
        storage.append_program_session(rid, {'completion_pct': 50})
        raise AssertionError('banned keys must still be refused')
    except ValueError:
        pass
    check(len(storage.get_program(rid)['sessions']) == 3, 'a refused write leaves no session')


def scenario_http_refuses_sibling_and_missing_ids():
    rid = _reset()
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    storage.add_member({'id': 'sibling', 'name': 'Sibling', 'role': 'child', 'is_child': True})
    programs.log_session(rid)
    before = storage.get_program(rid)
    sid = before['sessions'][0]['id']
    headers = {'X-Member-Token': storage.create_member_token('sibling')}
    check(c.get(f'/api/programs/{rid}/monitor', headers=headers).status_code == 404, 'sibling cannot read the monitor')
    check(c.delete(f'/api/programs/{rid}/sessions/{sid}', headers=headers).status_code == 404, 'sibling cannot remove a session')
    check(storage.get_program(rid) == before, 'denied writes leave the run untouched')
    headers = {'X-Member-Token': storage.create_member_token('mom')}
    check(c.get('/api/programs/unknown/monitor', headers=headers).status_code == 404, 'missing run read')
    check(c.delete(f'/api/programs/{rid}/sessions/unknown', headers=headers).status_code == 404, 'missing session delete')


def scenario_remove_unattributed_migrated_session_keeps_all_credit():
    rid = _reset()
    raw = storage.get_program(rid)
    curriculum = storage.get_library_program(raw['library_id'])
    ids = _lesson_ids(rid)
    # Three rungs in one phase, including the migration's legal -1 offset.
    curriculum['lessons'][2]['phase_id'] = curriculum['phases'][0]['id']
    storage.update_library_program(raw['library_id'], {'lessons': curriculum['lessons']})
    progress = {**raw['progress'], 'current': ids[2], 'lessons': {
        ids[0]: {'done_sessions': 1, 'completed_at': 100},
        ids[1]: {'done_sessions': 2, 'completed_at': 200},
        ids[2]: {'done_sessions': -1, 'completed_at': None}}}
    sessions = [{'id': 'legacy-one', 'ts': 10, 'minutes': 20}, {'id': 'legacy-two', 'ts': 20, 'minutes': 20}]
    storage.update_program(rid, {'progress': progress, 'sessions': sessions})
    programs.remove_session(rid, 'legacy-one')
    row = storage.get_program(rid)
    check(row['progress'] == progress and row['sessions'] == sessions[1:], 'unattributed legacy history cannot erase migrated credit or its bookmark')


def scenario_remove_partial_credit_keeps_a_persons_move_on():
    rid = _reset()
    raw = storage.get_program(rid)
    curriculum = storage.get_library_program(raw['library_id'])
    curriculum['lessons'][0]['sessions'] = 3
    storage.update_library_program(raw['library_id'], {'lessons': curriculum['lessons']})
    ids = _lesson_ids(rid)
    programs.log_session(rid, lesson_id=ids[0])
    sid = storage.get_program(rid)['sessions'][0]['id']
    programs.step_bookmark(rid, 'next')
    programs.remove_session(rid, sid)
    p = storage.get_program(rid)['progress']
    check(p['current'] == ids[1] and p['lessons'][ids[0]]['done_sessions'] == 0,
          'removing partial credit does not undo a person choosing Move on')


def scenario_remove_keeps_untouched_completion_stamp_and_back_bookmark():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, lesson_id=ids[0])
    programs.log_session(rid, lesson_id=ids[1])
    programs.log_session(rid, lesson_id=ids[1])
    row = storage.get_program(rid)
    p = row['progress']
    p['lessons'][ids[0]]['completed_at'] = 12345
    storage.update_program(rid, {'progress': p})
    programs.step_bookmark(rid, 'back')
    programs.remove_session(rid, row['sessions'][-1]['id'])
    p = storage.get_program(rid)['progress']
    check(p['lessons'][ids[0]] == {'done_sessions': 1, 'completed_at': 12345}, 'untouched completion timestamps never drift')
    check(p['current'] == ids[0] and not p['lessons'][ids[1]]['completed_at'], 'a reopened later lesson does not undo Another session on this')


def scenario_remove_unresolved_only_drops_entry():
    rid = _reset()
    programs.log_session(rid)
    before = storage.get_program(rid)
    storage.delete_library_program(before['library_id'])
    programs.remove_session(rid, before['sessions'][0]['id'])
    check(storage.get_program(rid) == {**before, 'sessions': []}, 'an unresolved run retains its complete stored progress')


def scenario_credit_roundtrip_keeps_negative_migration_offset():
    rid = _reset()
    row = storage.get_program(rid)
    lid = row['progress']['current']
    row['progress']['lessons'][lid] = {'done_sessions': -1, 'completed_at': None}
    storage.update_program(rid, {'progress': row['progress']})
    programs.log_session(rid)
    after_log = storage.get_program(rid)
    check(after_log['progress']['lessons'][lid]['done_sessions'] == 0, 'logging preserves migrated offset arithmetic')
    programs.remove_session(rid, after_log['sessions'][0]['id'])
    check(storage.get_program(rid)['progress'] == row['progress'], 'removal exactly reverses the credit, including a negative offset')


def scenario_remove_judged_lesson_decrements_without_reopening():
    rid = _reset()
    programs.log_session(rid)
    programs.mark_milestone(rid, phase_id=phase_id(rid, 0))
    row = storage.get_program(rid)
    lid = row['sessions'][0]['lesson_id']
    old = row['progress']
    programs.remove_session(rid, row['sessions'][0]['id'])
    p = storage.get_program(rid)['progress']
    check(p['lessons'][lid]['done_sessions'] == old['lessons'][lid]['done_sessions'] - 1, 'the judged lesson loses exactly one session credit')
    check(p['lessons'][lid]['completed_at'] == old['lessons'][lid]['completed_at'] and p['phases'] == old['phases'] and p['current'] == old['current'], 'the judgement keeps completion and the later bookmark')


def scenario_monitor_skips_ended_windows_today():
    rid = _reset()
    today = datetime.date.today()
    now = datetime.datetime.combine(today, datetime.time(21))
    class MonitorDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    def window(day, start, end, title):
        return {'program_id': rid, 'date': day.isoformat(), 'time_start': start, 'time_end': end,
                'unit_title': title, 'logged': False}
    expired = window(today, '16:30', '17:00', 'Expired')
    ongoing = window(today, '20:45', '21:15', 'Ongoing')
    tomorrow = window(today + datetime.timedelta(days=1), '09:00', '09:20', 'Tomorrow')
    with patch.object(programs.datetime, 'datetime', MonitorDateTime), patch.object(programs, 'practice_windows', return_value=[expired, ongoing, tomorrow]):
        m = programs.monitor(loaded(rid), viewer=MOM)
    check(m['next_window']['lesson_title'] == 'Ongoing', 'an ongoing window remains eligible after an earlier one ended')
    with patch.object(programs.datetime, 'datetime', MonitorDateTime), patch.object(programs, 'practice_windows', return_value=[expired, tomorrow]):
        m = programs.monitor(loaded(rid), viewer=MOM)
    check(m['next_window']['lesson_title'] == 'Tomorrow', 'ended windows today cannot hide the next dated window')


def scenario_monitor_last_practised_uses_ts_when_practising_ahead():
    rid = _reset()
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    programs.log_session(rid, slot_date=tomorrow.isoformat())
    storage.update_program(rid, {'state': 'paused'})
    m = programs.monitor(loaded(rid), viewer=MOM)
    check(m['last_practised'] == today.isoformat(), 'practising tomorrow\'s window today reads today')
    check(m['log'][0]['when'] == tomorrow.isoformat() and m['log'][0]['logged_on'] == today.isoformat(), 'the log keeps its distinct slot and timestamp dates')
    check(m['sessions_this_week'] == (0 if today.weekday() == 6 else 1), 'weekly counts still use slot_date')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
