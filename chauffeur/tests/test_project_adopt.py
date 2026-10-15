"""Every thread, mission and program belongs to exactly one project
(front door spec §1, slice 1, Tasks 1 and 2).

  * `projects.adopt(kind, record_id, actor, project_id=None)`: an explicit
    project wins; else the project the record already belongs to by binding;
    else a project made from the record (title, goal, owner, audience as §1);
    idempotent, never re-wraps a record whose project was dropped;
  * `missions.launch(..., project_id, subject)` binds BEFORE adopting, so the
    plan route and `projects.advance` make no wrapper project;
  * `threads.create(..., project_id)`, `programs.create_row(data, project_id)`;
  * a thread-origin mission joins its thread's project; `subject_of` unchanged;
  * `projects.adopt_existing()`: the one-time migration over every record,
    closed rows into done or dropped projects, recorded in app state.

Run from chauffeur/:  python tests/test_project_adopt.py
"""
from harness import check  # noqa: F401
from services import storage, missions, threads
from test_mission_subject import _fresh as _fresh_subjects
from test_subjects import MOM


def _fresh():
    _fresh_subjects()
    storage.projects_table.truncate()
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'


def _p():
    from services import projects
    return projects


def scenario_a_thread_created_by_hand_gets_a_project():
    _fresh()
    tid = threads.create(title='Deck permit', owner_member_id='mom', goal='permit approved', kind='project', created_by='mom')
    t = storage.get_thread(tid)
    p = storage.get_project(t['project_id'])
    check(p and p['title'] == 'Deck permit' and p['goal'] == 'permit approved' and p['owner_member_id'] == 'mom'
          and p['audience'] == 'private' and p['state'] == 'active', f"wrapped: {p}")
    check(p['pieces'] == [{'kind': 'thread', 'id': tid}], f"the thread is its first piece: {p['pieces']}")


def scenario_a_childs_record_gets_a_parents_project():
    _fresh()
    from services import programs
    pid_prog = programs.create_row({'member_id': 'kid', 'title': 'Learn guitar', 'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': []},
                                    'phases': [], 'source': {'origin': 'none'}, 'created_by': 'mom'})
    p = storage.get_project(storage.get_program(pid_prog)['project_id'])
    check(p['owner_member_id'] == 'kid' and p['audience'] == 'parents' and p['title'] == 'Learn guitar', f"a kid's program: {p}")


def scenario_a_thread_origin_mission_joins_the_threads_project():
    _fresh()
    tid = threads.create(title='Dishwasher', owner_member_id='mom', goal='fixed', kind='vendor', created_by='mom')
    res = missions.launch('get the dishwasher fixed', origin_kind='thread', origin_ref=tid, created_by='mom')
    m = storage.get_mission(res['mission_id'])
    check(m['project_id'] == storage.get_thread(tid)['project_id'], "one project for the thread and its mission")
    check(len(storage.get_projects()) == 1, f"never a second project: {[p['title'] for p in storage.get_projects()]}")
    check(missions.subject_of(m) == (None, None, 0), "subject_of still reads the thread, unchanged")


def scenario_launch_binds_the_project_before_adopting():
    _fresh()
    proj = _p().create({'title': 'Learn Portuguese', 'goal': 'talk', 'done_when': 'order dinner', 'owner_member_id': 'mom'}, dict(MOM))['project']
    res = missions.launch('plan the next part', created_by='mom', project_id=proj['id'], subject=('project', proj['id']))
    m = storage.get_mission(res['mission_id'])
    check(m['project_id'] == proj['id'] and missions.subject_of(m)[:2] == ('project', proj['id']), f"bound and adopted into the same project: {m}")
    check(len(storage.get_projects()) == 1, "no wrapper project was made first")


def scenario_the_plan_route_and_advance_make_no_wrapper():
    _fresh()
    import main
    from test_subject_audience import _as
    proj = _p().create({'title': 'Bathroom', 'goal': 'done', 'done_when': 'tiled', 'owner_member_id': 'mom'}, dict(MOM))['project']
    out = main.project_plan(proj['id'], request=_as('mom'))
    check(storage.get_mission(out['mission_id'])['project_id'] == proj['id'] and len(storage.get_projects()) == 1, "plan route")
    _p().add_step(proj['id'], {'title': 'Find a tiler', 'owner': 'argyle', 'goal': 'three tilers nearby'}, dict(MOM))
    started = _p().advance(proj['id'])
    mids = [s['mission_id'] for s in storage.get_project(proj['id'])['steps'] if s.get('mission_id')]
    check(started and mids and storage.get_mission(mids[0])['project_id'] == proj['id'] and len(storage.get_projects()) == 1, "advance")


def scenario_adopt_is_idempotent_and_never_rewraps():
    _fresh()
    tid = threads.create(title='Deck permit', owner_member_id='mom', created_by='mom')
    first = storage.get_thread(tid)['project_id']
    check(_p().adopt('thread', tid, dict(MOM)) == first and len(storage.get_projects()) == 1, "a second adopt changes nothing")
    _p().set_state(first, 'dropped', dict(MOM))
    check(_p().adopt('thread', tid, dict(MOM)) == first and len(storage.get_projects()) == 1,
          "a record whose project was dropped is NOT re-wrapped by adopt")
    check(_p().adopt('thread', 'nope', dict(MOM)) is None, "a missing record adopts to nothing")


def scenario_a_planner_row_inside_a_project_joins_it():
    _fresh()
    proj = _p().create({'title': 'Learn Portuguese', 'goal': 'talk', 'done_when': 'order dinner', 'owner_member_id': 'mom'}, dict(MOM))['project']
    tid = threads.create(title='Teacher', owner_member_id='mom', created_by='mom', project_id=proj['id'])
    check(storage.get_thread(tid)['project_id'] == proj['id'] and len(storage.get_projects()) == 1, "an explicit project wins")
    check({'kind': 'thread', 'id': tid} in storage.get_project(proj['id'])['pieces'], "and the thread is a piece")


# --- Task 2: the migration ---------------------------------------------------

def scenario_migration_wraps_every_record_once():
    _fresh()
    storage.set_app_state('projects_adopted_rev', 0)
    tid = storage.add_thread({'title': 'Pest control', 'kind': 'vendor', 'state': 'waiting', 'owner_member_id': 'mom', 'created_by': 'mom'})
    live = storage.add_mission({'goal': 'get a quote', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    closed = storage.add_thread({'title': 'Old permit', 'kind': 'project', 'state': 'done', 'owner_member_id': 'dad', 'created_by': 'dad'})
    ended = storage.add_mission({'goal': 'book the dentist', 'created_by': 'mom', 'tier': 'mission', 'status': 'done'})
    prog = storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'shape': {'sessions_per_week': 2, 'minutes': 15, 'preferred_days': []},
                                'phases': [], 'source': {'origin': 'none'}, 'created_by': 'mom', 'state': 'active'})
    out = _p().adopt_existing()
    check(out == {'threads': 2, 'missions': 2, 'programs': 1, 'skipped': False}, f"counted: {out}")
    pid = storage.get_thread(tid)['project_id']
    check(storage.get_mission(live)['project_id'] == pid, "a thread and its live mission are one project")
    check(storage.get_project(pid)['state'] == 'active', "an open thread is an active project")
    check(storage.get_project(storage.get_thread(closed)['project_id'])['state'] == 'done', "a done thread is a done project")
    check(storage.get_project(storage.get_mission(ended)['project_id'])['state'] == 'done', "an ended mission is a done project")
    kp = storage.get_project(storage.get_program(prog)['project_id'])
    check(kp['owner_member_id'] == 'kid' and kp['audience'] == 'parents', f"a kid's program is a parents project: {kp}")
    check(len(storage.get_projects()) == 4, f"four projects: {[p['title'] for p in storage.get_projects()]}")
    again = _p().adopt_existing()
    check(again['skipped'] is True and len(storage.get_projects()) == 4, "a second run does nothing")
    check(storage.get_app_state('projects_adopted_rev') == 1, "recorded")


def scenario_migration_handles_a_missing_owner():
    _fresh()
    storage.set_app_state('projects_adopted_rev', 0)
    tid = storage.add_thread({'title': 'Gutters', 'kind': 'vendor', 'state': 'open', 'owner_member_id': 'gone', 'created_by': 'gone'})
    _p().adopt_existing()
    p = storage.get_project(storage.get_thread(tid)['project_id'])
    check(p['owner_member_id'] in ('mom', 'dad') and p['audience'] == 'private', f"the parent of record stands in: {p}")


SCENARIOS = [scenario_a_thread_created_by_hand_gets_a_project, scenario_a_childs_record_gets_a_parents_project,
             scenario_a_thread_origin_mission_joins_the_threads_project, scenario_launch_binds_the_project_before_adopting,
             scenario_the_plan_route_and_advance_make_no_wrapper, scenario_adopt_is_idempotent_and_never_rewraps,
             scenario_a_planner_row_inside_a_project_joins_it,
             scenario_migration_wraps_every_record_once, scenario_migration_handles_a_missing_owner]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
