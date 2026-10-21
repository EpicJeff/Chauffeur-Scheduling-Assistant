"""programs.replace_schedule: Change the days on an active or paused run in one write;
a child's change goes through proposed; drift reads the change date; the old
reshape offer executes nothing (spec 2026-10-20-programs-brief-and-course §5.3, P8).
Run from chauffeur/: python tests/test_program_schedule.py"""
import datetime
from unittest.mock import patch

from program_fixture import add_run, loaded  # harness first
from harness import check  # noqa: F401
from services import storage, programs

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}
SHAPE = {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': [0, 2]}
BASE = {'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'm',
                    'units': [{'title': 'Scales', 'sessions': 2}]}],
        'source': {'origin': 'none', 'reason': 'test'},
        'baseline': {'start_date': '2026-10-01', 'target_date': None, 'target_event_id': None,
                     'rebaselined_at': None, 'rebaselines': 0}}


def _reset():
    for t in (storage.programs_table, storage.library_programs_table, storage.members_table, storage.protected_commitments_table):
        t.truncate()
    for m in (MOM, AUNT, KID):
        storage.add_member(dict(m))


def _active(member='kid'):
    rid = add_run({'id': 'r1', 'member_id': member, 'title': 'Piano', 'state': 'proposed', 'shape': dict(SHAPE), **BASE})
    res = programs.approve(rid, 'mom', slots=[{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}])
    check(res['status'] == 'success', f"fixture approves: {res}")
    return rid


def _commitments(rid):
    ids = set((storage.get_program(rid).get('emissions') or {}).get('commitment_ids') or [])
    return [pc for pc in storage.get_protected_commitments(member_id=storage.get_program(rid)['member_id']) if pc['id'] in ids]


def scenario_active_replace_claims_new_days():
    _reset(); rid = _active()
    before = {pc['id'] for pc in _commitments(rid)}
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:30'}, {'day': 3, 'time_start': '17:30'}, {'day': 5, 'time_start': '09:00'}], dict(MOM))
    row = storage.get_program(rid)
    now = _commitments(rid)
    check(res['status'] == 'success' and res['state'] == 'active' and res['schedule_dirty'], f"replaced: {res}")
    check({pc['days_of_week'][0] for pc in now} == {1, 3, 5} and not (before & {pc['id'] for pc in now}), "old windows gone, new ones claimed")
    check(row['shape']['slots'] and row['shape']['sessions_per_week'] == 3 and row['shape']['preferred_days'] == [1, 3, 5], f"shape follows the slots: {row['shape']}")
    check(row['baseline']['schedule_changed_on'] == datetime.date.today().isoformat()
          and row['baseline']['schedule_history'][-1]['preferred_days'] == [0, 2], f"the change is dated and the old days kept: {row['baseline']}")


def scenario_empty_slots_let_the_app_pick():
    _reset(); rid = _active()
    res = programs.replace_schedule(rid, [], dict(MOM))
    check(res['status'] == 'success' and len(_commitments(rid)) == 2, f"the app proposed and claimed: {res}")


def scenario_claim_failure_restores_the_old_week():
    _reset(); rid = _active()
    before = sorted(pc['days_of_week'][0] for pc in _commitments(rid))
    snapshot = storage.get_program(rid)
    old_rows = _commitments(rid)
    calls = {'n': 0}
    real = storage.add_protected_commitment
    def flaky(data):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('disk full')
        return real(data)
    with patch.object(storage, 'add_protected_commitment', flaky):
        res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:30'}, {'day': 3, 'time_start': '17:30'}], dict(MOM))
    after = sorted(pc['days_of_week'][0] for pc in _commitments(rid))
    row = storage.get_program(rid)
    check(res['status'] == 'error' and after == before and row['state'] == 'active' and row['shape']['preferred_days'] == [0, 2],
          f"nothing changed on failure: {res} {after}")
    check(storage.get_program(rid) == snapshot and _commitments(rid) == old_rows,
          "rollback preserves exact rows and supplied commitment ids")


def scenario_replace_with_orphaned_emissions():
    _reset(); rid = _active()
    gone = _commitments(rid)[0]['id']
    storage.delete_protected_commitment(gone)   # someone removed one window by hand
    res = programs.replace_schedule(rid, [{'day': 4, 'time_start': '18:00'}], dict(MOM))
    ids = (storage.get_program(rid).get('emissions') or {}).get('commitment_ids') or []
    check(res['status'] == 'success' and len(ids) == 1 and storage.get_protected_commitment(gone) is None,
          f"an orphan is forgotten, never re-created: {res} {ids}")


def scenario_paused_run_remembers_only():
    _reset(); rid = _active()
    programs.pause(rid)
    res = programs.replace_schedule(rid, [{'day': 6, 'time_start': '10:00'}], dict(MOM))
    row = storage.get_program(rid)
    check(res['status'] == 'success' and res['state'] == 'paused' and not _commitments(rid)
          and row['paused_slots'][0]['day'] == 6 and row['shape']['preferred_days'] == [6], f"paused: remembered, not claimed: {row['paused_slots']}")
    res = programs.resume(rid)
    check(res['status'] == 'success' and {pc['days_of_week'][0] for pc in _commitments(rid)} == {6}, "resume claims the remembered days")


def scenario_child_change_goes_through_proposed():
    _reset(); rid = _active()
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '16:00'}], dict(KID))
    row = storage.get_program(rid)
    check(res['status'] == 'success' and res['state'] == 'proposed' and row['state'] == 'proposed'
          and not _commitments(rid) and row['shape']['slots'][0]['day'] == 1, f"a child's wish waits for approval: {res}")
    check('parent or adult' in res['message'], res['message'])
    res = programs.approve(rid, 'mom')
    check(res['status'] == 'success' and {pc['days_of_week'][0] for pc in _commitments(rid)} == {1}, "approval claims the child's days")


def scenario_adult_may_claim():
    _reset(); rid = _active()
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '16:00'}], dict(AUNT))
    check(res['status'] == 'success' and res['state'] == 'active', f"an adult claims directly (P5): {res}")


def scenario_refusals():
    _reset(); rid = _active()
    programs.finish(rid)
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '16:00'}], dict(MOM))
    check(res['status'] == 'error', f"a finished run has no days to change: {res}")
    check(programs.replace_schedule('nope', [], dict(MOM))['status'] == 'error', "unknown run")


def scenario_drift_reads_the_change_date():
    _reset(); rid = _active()
    # Six weeks of Monday/Wednesday windows missed, then the days change to Tue/Thu today.
    row = storage.get_program(rid)
    storage.update_program(rid, {'baseline': {**row['baseline'], 'start_date': (datetime.date.today() - datetime.timedelta(days=42)).isoformat()}})
    programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:00'}, {'day': 3, 'time_start': '17:00'}], dict(MOM))
    today = datetime.datetime.combine(datetime.date.today(), datetime.time(12))
    short = programs.weekday_shortfall(loaded(rid), now=today)
    check(short is None, f"no shortfall is blamed on days that only started today: {short}")
    short = programs.weekday_shortfall(loaded(rid), now=today + datetime.timedelta(days=28))
    check(short is not None and short['weekdays'] == [1, 3],
          f"four weeks later only the new days can fall short: {short}")


def scenario_watcher_offer_executes_nothing():
    _reset(); rid = _active()
    from services import chat_actions
    before = storage.get_program(rid)['state']
    res = chat_actions._execute('change_program_days', {'program_id': rid})
    check(res['status'] == 'success' and res['open'] == {'kind': 'program', 'id': rid, 'menu': 'change_days'}
          and storage.get_program(rid)['state'] == before and _commitments(rid), f"the offer only opens the editor: {res}")
    res = chat_actions._execute('reshape_program', {'program_id': rid})
    check(res['status'] == 'success' and storage.get_program(rid)['state'] == before and _commitments(rid),
          f"an old stored offer no longer releases time: {res}")
    check(chat_actions.ACTION_LABELS.get('change_program_days') == 'Change the days', "label")


def scenario_watcher_finding_names_the_new_action():
    _reset(); rid = _active()
    from services import watchers
    for pc in _commitments(rid):
        storage.delete_protected_commitment(pc['id'])
    findings = watchers._program_findings(datetime.datetime.now())
    drift = next((f for f in findings if f.kind == 'program_drift'), None)
    check(drift is not None and drift.action['action_type'] == 'change_program_days' and drift.action['label'] == 'Change the days'
          and 'Re-shape' not in drift.line, f"drift offers Change the days: {drift}")


def scenario_http_patch_schedule_and_no_reshape_route():
    _reset(); rid = _active()
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    paths = {r.path for r in main.app.routes}
    check('/api/programs/{program_id}/reshape' not in paths and '/api/programs/{program_id}/schedule' in paths, f"routes: reshape gone, schedule present")
    tok = storage.create_member_token('mom')
    r = c.patch(f'/api/programs/{rid}/schedule', json={'slots': [{'day': 4, 'time_start': '18:00'}]}, headers={'X-Member-Token': tok})
    check(r.status_code == 200 and r.json()['status'] == 'success', f"PATCH schedule: {r.text}")
    tok = storage.create_member_token('kid')
    r = c.patch(f'/api/programs/{rid}/schedule', json={'slots': [{'day': 5, 'time_start': '18:00'}]}, headers={'X-Member-Token': tok})
    check(r.status_code == 200 and r.json()['state'] == 'proposed', f"a child's PATCH lands proposed: {r.text}")


def scenario_release_failure_restores_the_snapshot():
    _reset(); rid = _active()
    snapshot = storage.get_program(rid)
    old_rows = _commitments(rid)
    real = storage.delete_protected_commitment
    def flaky(cid):
        if cid == old_rows[1]['id']:
            raise RuntimeError('cannot remove second window')
        return real(cid)
    with patch.object(storage, 'delete_protected_commitment', flaky):
        res = programs.replace_schedule(rid, [{'day': 5, 'time_start': '09:00'}], dict(MOM))
    check(res['status'] == 'error' and storage.get_program(rid) == snapshot
          and sorted(_commitments(rid), key=lambda pc: pc['id']) == sorted(old_rows, key=lambda pc: pc['id']),
          f"partial release restores the exact old week: {res}")


def scenario_unrelated_emissions_stay_put():
    _reset(); rid = _active()
    storage.add_protected_commitment({'id': 'other', 'member_id': 'kid', 'active': True,
        'days_of_week': [6], 'time_start': '08:00', 'time_end': '08:20'})
    row = storage.get_program(rid)
    emissions = {**row['emissions'], 'thread_ids': ['kit'], 'event_ids': ['target']}
    storage.update_program(rid, {'emissions': emissions})
    res = programs.replace_schedule(rid, [{'day': 4, 'time_start': '18:00'}], dict(MOM))
    kept = storage.get_program(rid)['emissions']
    check(res['status'] == 'success' and kept['thread_ids'] == ['kit']
          and kept['event_ids'] == ['target'] and storage.get_protected_commitment('other'),
          f"other time, kit and target survive: {res} {kept}")


def scenario_snapshot_restore_failure_names_the_ids():
    _reset(); rid = _active()
    old_ids = {pc['id'] for pc in _commitments(rid)}
    with patch.object(storage, 'add_protected_commitment', side_effect=RuntimeError('disk full')):
        res = programs.replace_schedule(rid, [{'day': 4, 'time_start': '18:00'}], dict(MOM))
    check(res['status'] == 'error' and all(cid in res['message'] for cid in old_ids),
          f"failed restores name every affected id: {res}")


def scenario_http_schedule_respects_access_and_refreshes_after_commit():
    _reset(); rid = _active()
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    seen = []
    def refreshed(*args):
        seen.append((storage.get_program(rid)['shape']['preferred_days'],
                     storage.db.connection().in_transaction))
    with patch.object(main, 'trigger_background_refresh', side_effect=refreshed):
        r = c.patch(f'/api/programs/{rid}/schedule', json={'slots': [{'day': 4, 'time_start': '18:00'}]},
                    headers={'X-Member-Token': storage.create_member_token('aunt')})
    check(r.status_code == 200 and r.json()['status'] == 'success' and seen == [([4], False)],
          f"adult HTTP change refreshes the committed schedule: {r.text} {seen}")
    storage.add_member({'id': 'sibling', 'name': 'Sibling', 'role': 'child'})
    snapshot = storage.get_program(rid)
    r = c.patch(f'/api/programs/{rid}/schedule', json={'slots': [], 'member_id': 'mom'},
                headers={'X-Member-Token': storage.create_member_token('sibling')})
    check(r.status_code in (403, 404) and storage.get_program(rid) == snapshot,
          f"a child cannot change a sibling's times by claiming another actor: {r.text}")


def scenario_failed_undo_keeps_new_ids_tracked_and_reports_them():
    _reset(); rid = _active()
    old_ids = {pc['id'] for pc in _commitments(rid)}
    real_add = storage.add_protected_commitment
    real_delete = storage.delete_protected_commitment
    made = []
    def flaky_add(data):
        if data['id'] not in old_ids:
            if made:
                raise RuntimeError('second insert failed')
            made.append(data['id'])
        return real_add(data)
    def flaky_delete(cid):
        if cid in made:
            raise RuntimeError('undo failed')
        return real_delete(cid)
    with patch.object(storage, 'add_protected_commitment', flaky_add), \
            patch.object(storage, 'delete_protected_commitment', flaky_delete):
        res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:30'}, {'day': 3, 'time_start': '17:30'}], dict(MOM))
    ids = storage.get_program(rid)['emissions']['commitment_ids']
    check(res['status'] == 'error' and res.get('schedule_dirty') and made[0] in res['message']
          and set(ids) == old_ids | set(made), f"failed cleanup remains tracked and explicit: {res} {ids}")


def scenario_child_paused_change_still_needs_approval():
    _reset(); rid = _active()
    paused = programs.pause(rid)  # The keeper may pause their own program.
    check(paused['status'] == 'success' and not _commitments(rid), f"paused: {paused}")
    with patch.object(programs, 'release_commitments', wraps=programs.release_commitments) as release:
        res = programs.replace_schedule(rid, [{'day': 6, 'time_start': '10:00'}], dict(KID))
    row = storage.get_program(rid)
    check(res['status'] == 'success' and res['state'] == row['state'] == 'proposed'
          and res['schedule_dirty'] is False and not release.called
          and row['shape']['slots'][0]['day'] == 6
          and row['paused_at'] is None and row['paused_slots'] == []
          and 'a parent or adult puts them on the calendar' in res['message'],
          f"a paused child's new times wait for approval: {res} {row}")
    resumed = programs.resume(rid)
    check(resumed['status'] == 'error' and not _commitments(rid)
          and storage.get_program(rid)['state'] == 'proposed',
          f"resume cannot put the child's unapproved times on the calendar: {resumed}")


def scenario_child_partial_release_rolls_back():
    _reset(); rid = _active()
    snapshot = storage.get_program(rid)
    old_rows = _commitments(rid)
    real = storage.delete_protected_commitment
    def flaky(cid):
        if cid == old_rows[1]['id']:
            raise RuntimeError('cannot remove second window')
        return real(cid)
    with patch.object(storage, 'delete_protected_commitment', flaky):
        res = programs.replace_schedule(rid, [{'day': 5, 'time_start': '09:00'}], dict(KID))
    check(res == {'status': 'error', 'message': programs.RELEASE_ERROR}
          and storage.get_program(rid) == snapshot and _commitments(rid) == old_rows,
          f"a child's partial release rolls back the whole operation: {res}")


def scenario_non_claimer_must_be_the_keeper():
    for paused in (False, True):
        for actor in ({'id': 'sibling', 'role': 'child'}, {}, None):
            _reset(); rid = _active()
            if paused:
                programs.pause(rid)
            snapshot = storage.get_program(rid)
            old_rows = _commitments(rid)
            res = programs.replace_schedule(rid, [{'day': 5, 'time_start': '09:00'}], actor)
            check(res['status'] == 'error' and res.get('code') == 403
                  and storage.get_program(rid) == snapshot and _commitments(rid) == old_rows,
                  f"only the keeper may submit a child's change, paused={paused}, actor={actor}: {res}")


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
