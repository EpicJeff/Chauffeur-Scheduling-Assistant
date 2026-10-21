"""One-pass setup (spec §4): activate lands active for a parent/adult, proposed for a child,
proposed with a message when there is no time, and nothing is kept when activation fails.
Run from chauffeur/: python tests/test_program_setup.py"""
from unittest.mock import patch

from program_fixture import add_run  # harness first
from harness import check  # noqa: F401
from fastapi.testclient import TestClient
from services import storage, programs, library, library_scripts, programs_curate

CURATED = {'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'm',
                       'units': [{'title': 'Scales', 'sessions': 2}]}],
           'source': {'origin': 'cited', 'plan_name': 'Piano Adventures', 'url': 'https://x', 'facts': []}}
SCRIPT_JOBS = []
REFRESHES = []


def _write(library_id, actor):
    # This is the real request thread and SQLite connection. A second connection
    # must see the run and library row before a job can be started.
    import json
    import sqlite3
    check(not storage.db.connection().in_transaction, 'scripts start outside the transaction')
    with sqlite3.connect(storage.db.path) as conn:
        runs = [json.loads(r[0]) for r in conn.execute('SELECT data FROM programs')]
        libs = [json.loads(r[0]) for r in conn.execute('SELECT data FROM library_programs')]
    check(any(r['library_id'] == library_id for r in runs), 'the run is committed before scripts start')
    check(any(r['id'] == library_id for r in libs), 'the library row is committed before scripts start')
    SCRIPT_JOBS.append(library_id)
    return {'status': 'ok', 'job': None}

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}


def _reset():
    import copy
    import main
    SCRIPT_JOBS.clear()
    REFRESHES.clear()
    def refresh(*a, **k):
        check(not storage.db.connection().in_transaction, 'refresh runs after commit')
        REFRESHES.append(True)
    main.trigger_background_refresh = refresh
    library_scripts.write = _write
    programs_curate.curate = lambda *a, **k: copy.deepcopy(CURATED)
    for t in (storage.programs_table, storage.library_programs_table, storage.members_table, storage.protected_commitments_table, storage.projects_table):
        t.truncate()
    for m in (MOM, AUNT, KID):
        storage.add_member(dict(m))
    from services import projects
    p = projects.create({'title': 'Piano for Kate', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'kid', 'audience': 'household'}, dict(MOM))['project']
    lib = storage.add_library_program(library.from_curated('Learn piano', {'age_band': 'any', 'minutes': 20, 'sessions_per_week': 2, 'assumes': ''},
        {'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'm', 'units': [{'title': 'Scales', 'sessions': 2}]}],
         'source': {'origin': 'cited', 'plan_name': 'Piano Adventures', 'url': 'https://x', 'facts': []}}, 'mom'))
    return p['id'], lib


def _c():
    import main
    return TestClient(main.app)


def _h(who):
    return {'X-Member-Token': storage.create_member_token(who)}


def _runs():
    return storage.get_programs(include_finished=True)


def scenario_parent_activate_lands_active():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True,
                                                           'slots': [{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}], 'minutes': 20})
    check(r.status_code == 200 and r.json()['status'] == 'success' and r.json()['program']['state'] == 'active', f"active at once: {r.text}")
    run = _runs()[0]
    ids = run['emissions']['commitment_ids']
    check(len(ids) == 2 and run['approved_by'] == 'mom' and run['baseline']['start_date'], f"claimed exactly as approve claims: {run['emissions']} {run['baseline']}")
    check(run['shape']['minutes'] == 20 and run['shape']['sessions_per_week'] == 2, f"one duration per run: {run['shape']}")
    check(REFRESHES == [True], 'activation refreshes the schedule after commit')


def scenario_adult_activates_too():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('aunt'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True})
    check(r.status_code == 200 and r.json()['program']['state'] == 'active', f"an adult may start it (P5): {r.text}")


def scenario_child_lands_proposed():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('kid'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True})
    check(r.status_code == 200 and r.json()['program']['state'] == 'proposed' and not _runs()[0]['emissions'].get('commitment_ids'),
          f"a child never claims time: {r.text}")


def scenario_no_time_keeps_a_proposal_and_says_so():
    pid, lib = _reset()
    with patch.object(programs, 'propose_slots', lambda *a, **k: []):
        r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True, 'slots': []})
    body = r.json()
    check(r.status_code == 200 and body['status'] == 'success' and body['program']['state'] == 'proposed'
          and 'no free time' in body['message'], f"proposed with the message: {r.text}")


def scenario_activation_failure_keeps_nothing():
    pid, lib = _reset()
    before_libs = len(storage.get_library_programs())
    def boom(data):
        raise RuntimeError('calendar down')
    with patch.object(storage, 'add_protected_commitment', boom), \
         patch.object(storage, 'delete_program', side_effect=RuntimeError('delete must not mask activation error')), \
         patch.object(storage, 'delete_library_program', side_effect=RuntimeError('delete must not mask activation error')):
        r = _c().post('/api/programs', headers=_h('mom'), json={'title': 'Learn drums', 'for_member_id': 'kid', 'project_id': pid, 'activate': True,
                                                               'slots': [{'day': 0, 'time_start': '18:00'}]})
    check(r.status_code == 200 and r.json()['status'] == 'error', f"the error is reported: {r.text}")
    check(not _runs() and len(storage.get_library_programs()) == before_libs, "no run and no new library row survive a failed activation")
    check(not storage.get_protected_commitments(), 'no commitments survive failure')
    check(not SCRIPT_JOBS, 'activation failure starts no script job')
    check(not REFRESHES, 'activation failure schedules no refresh')


def scenario_make_new_starts_scripts_after_commit():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('mom'), json={'title': 'Learn drums', 'for_member_id': 'kid',
                   'project_id': pid, 'activate': True, 'slots': [{'day': 0, 'time_start': '18:00'}]})
    body = r.json()
    check(r.status_code == 200 and body['program']['state'] == 'active', f'made and active: {r.text}')
    check(SCRIPT_JOBS == [body['program']['library_id']], 'one job starts after successful commit')


def scenario_picker_activation_failure_keeps_existing_library():
    pid, lib = _reset()
    with patch.object(storage, 'add_protected_commitment', side_effect=RuntimeError('calendar down')):
        r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid',
                       'project_id': pid, 'activate': True, 'slots': [{'day': 0, 'time_start': '18:00'}]})
    check(r.status_code == 200 and r.json()['status'] == 'error', f'picker failure reported: {r.text}')
    check(not _runs() and storage.get_library_program(lib), 'only the new run is removed')
    check(not SCRIPT_JOBS, 'picker failure starts no job')


def scenario_partial_emission_failure_leaves_no_rows():
    pid, lib = _reset()
    original = storage.add_protected_commitment
    made = []
    def emit(data):
        if made:
            raise RuntimeError('second window failed')
        made.append(original(data))
        return made[-1]
    with patch.object(storage, 'add_protected_commitment', emit):
        r = _c().post('/api/programs', headers=_h('mom'), json={'title': 'Learn drums', 'for_member_id': 'kid',
                       'project_id': pid, 'activate': True,
                       'slots': [{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}]})
    check(r.json() == {'status': 'error', 'message': 'second window failed'}, f'original error: {r.text}')
    check(made and not _runs() and not storage.get_protected_commitments(), 'even the first window is removed')
    check(len(storage.get_library_programs()) == 1 and storage.get_library_program(lib), 'only the existing library stays')
    check(not storage.get_project(pid)['pieces'], 'project adoption rolls back too')
    check(not SCRIPT_JOBS and not REFRESHES, 'failed creation queues no work')


def scenario_make_new_no_time_still_commits_proposal_and_scripts():
    pid, lib = _reset()
    with patch.object(programs, 'propose_slots', return_value=[]):
        r = _c().post('/api/programs', headers=_h('mom'), json={'title': 'Learn drums', 'for_member_id': 'kid',
                       'project_id': pid, 'activate': True, 'slots': []})
    body = r.json()
    check(body['status'] == 'success' and body['state'] == body['program']['state'] == 'proposed'
          and body['message'] == 'Made it, but found no free time this week; pick times to start it.',
          f'no-time contract: {r.text}')
    check(len(_runs()) == 1 and len(storage.get_library_programs()) == 2, 'proposal and library are kept')
    check(SCRIPT_JOBS == [body['program']['library_id']] and not REFRESHES, 'committed proposal writes scripts only')


def scenario_commit_failure_starts_no_scripts():
    pid, lib = _reset()
    from contextlib import contextmanager
    original = storage.db.transaction
    @contextmanager
    def fail_commit():
        with original() as conn:
            outermost = storage.db._local.txn_depth == 1
            yield conn
            if outermost and _runs():
                raise RuntimeError('commit failed')
    with patch.object(storage.db, 'transaction', fail_commit):
        r = TestClient(__import__('main').app, raise_server_exceptions=False).post('/api/programs', headers=_h('mom'),
            json={'title': 'Learn drums', 'for_member_id': 'kid', 'project_id': pid, 'activate': True,
                  'slots': [{'day': 0, 'time_start': '18:00'}]})
    check(r.status_code == 500, f'commit failure is surfaced: {r.text}')
    check(not _runs() and len(storage.get_library_programs()) == 1, 'failed commit rolls back creation')
    check(not storage.get_protected_commitments() and not SCRIPT_JOBS and not REFRESHES, 'failed commit queues nothing')


def scenario_without_activate_today_behaviour_stands():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid})
    check(r.status_code == 200 and r.json()['program']['state'] == 'proposed', f"no activate = proposed, as today: {r.text}")


def scenario_preview_slots():
    pid, lib = _reset()
    r = _c().post('/api/programs/preview-slots', headers=_h('mom'), json={'member_id': 'kid', 'library_id': lib})
    check(r.status_code == 200 and len(r.json()['slots']) == 2 and r.json()['minutes'] == 20, f"a preview from the library profile: {r.text}")
    r = _c().post('/api/programs/preview-slots', headers=_h('kid'), json={'member_id': 'mom'})
    check(r.status_code == 403, f"a child previews only their own week: {r.status_code}")
    r = _c().post('/api/programs/preview-slots', headers=_h('kid'), json={'member_id': 'kid', 'sessions_per_week': 3, 'minutes': 15, 'preferred_days': [1, 3, 5]})
    check(r.status_code == 200 and [s['day'] for s in r.json()['slots']] == [1, 3, 5], f"preferred days respected: {r.text}")


def scenario_preview_permissions_and_overrides():
    pid, lib = _reset()
    r = _c().post('/api/programs/preview-slots', headers=_h('aunt'),
                  json={'member_id': 'kid', 'library_id': lib, 'minutes': 15, 'sessions_per_week': 1, 'preferred_days': [4]})
    check(r.status_code == 200 and r.json()['minutes'] == 15 and len(r.json()['slots']) == 1
          and r.json()['slots'][0]['day'] == 4, f'adult and explicit shape overrides: {r.text}')
    r = _c().post('/api/programs/preview-slots', headers=_h('kid'), json={})
    check(r.status_code == 200, f'default member is self: {r.text}')
    r = _c().post('/api/programs/preview-slots', headers=_h('mom'), json={'member_id': 'missing'})
    check(r.status_code == 404, f'no such member: {r.text}')
    r = _c().post('/api/programs/preview-slots', json={'member_id': 'kid'})
    check(r.status_code == 401, f'preview always requires a person: {r.text}')
    check(not _runs() and not storage.get_protected_commitments() and not SCRIPT_JOBS, 'preview writes nothing')


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
