"""Waiting on a person's step; shared mission status sets (Projects core spec
§3 "Waiting on a person's step", Task 5).

  * `missions.LIVE`, `missions.RUNNABLE`, `missions.ATTENTION` replace every
    inline status list; `waiting_step` is LIVE, not RUNNABLE, not ATTENTION;
  * a planned mission bound to a project whose next stage is an Argyle step
    that needs an unfinished person step parks in `waiting_step`: the tick
    does not step it, triage does not offer it, the admin list shows it, a
    thread finds it as its live mission, the same goal is not started twice,
    and its subject cannot be retargeted;
  * ticking the person's step resumes it in the same write (no polling);
  * after a restart, reconcile resumes a parked mission whose needs are met.

Run from chauffeur/:  python tests/test_project_waiting.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, triage
from services import agent_tools_v2 as tools
from test_planned_missions import _fresh as _fresh_planned, _planned_mission, _plan_of
from test_mission_subject import _step, _mission, _thread, PROMPTS
from test_subjects import MOM
from test_subject_audience import _as


def _fresh():
    _fresh_planned()
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = lambda: dict(base, missions_enabled=True)


def _parked():
    """A plan whose s1 is left out; s2 (work) is the project's Argyle step after Mom's demo."""
    from services import projects
    _fresh()
    mid = _planned_mission()
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:drop:s1', payload={}, actor=dict(MOM))
    situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{_plan_of(mid)['rev']}:approve", payload={}, actor=dict(MOM))
    pid = projects.create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it',
                           'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']['id']
    storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': pid, 'subject_rev': 1})
    demo = projects.add_step(pid, {'title': 'Demo the old tile', 'owner': 'mom'}, dict(MOM))['step']
    research = projects.add_step(pid, {'title': 'Find a cake bakery', 'owner': 'argyle', 'goal': 'find two bakeries',
                                       'needs': [demo['id']]}, dict(MOM))['step']
    # The planner links a stage-backed step internally (Task 7); the fixture writes the link directly.
    row = storage.get_project(pid)
    for s in row['steps']:
        if s['id'] == research['id']:
            s.update(mission_id=mid, stage_id='s2')
    storage.update_project(pid, {'steps': row['steps']})
    return mid, pid, demo, research


def scenario_b1_the_status_sets():
    check(set(missions.LIVE) == {'running', 'browsing', 'waiting_user', 'waiting_retry', 'waiting_step'}, missions.LIVE)
    check(set(missions.RUNNABLE) == {'running'}, missions.RUNNABLE)
    check(set(missions.ATTENTION) == {'waiting_user'}, missions.ATTENTION)


def scenario_b2_a_plan_waits_for_a_persons_step():
    mid, pid, demo, research = _parked()
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_step', f"parked: {storage.get_mission(mid)['status']}")
    check(_plan_of(mid)['stages'][1]['state'] == 'pending', "the stage is not offered while the demo is still to do")
    before = len(PROMPTS)
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'waiting_step' and len(PROMPTS) == before, "the tick never steps it")
    s = triage.next_for(dict(MOM), 'conv:waiting')
    check(not s or s.get('id') != mid, f"triage does not offer a parked mission: {s}")
    import main
    active = [m['id'] for m in main.missions_admin(request=_as('mom'))['active']]
    check(mid in active, "the admin list shows it as live")
    from services import projects
    res = projects.set_step_state(pid, demo['id'], 'done', dict(MOM))
    check(res['status'] == 'success', f"the demo is ticked: {res}")
    check(storage.get_mission(mid)['status'] == 'running', "the tick of the step resumed it, in the same write")


def scenario_b3_live_everywhere():
    _fresh()
    tid = _thread('Fix the dishwasher')
    mid = _mission(created_by='mom', origin=tid)
    storage.update_mission(mid, {'goal': 'fix the dishwasher', 'status': 'waiting_step'})
    found = situations._thread_mission(storage.get_thread(tid))
    check(found and found['id'] == mid, "the thread finds its parked mission as live")
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'
    res = tools.start_mission_for('fix the dishwasher', acting_member=dict(MOM), focus_key='conv:dedupe')
    check(res.get('mission_id') == mid, f"the same goal is not started twice: {res}")


def scenario_b4_retarget_refused_while_parked():
    mid, pid, demo, research = _parked()
    _step(mid)
    from services import subjects
    res = subjects.retarget('mission', mid, 'trip', 'ev_disney', dict(MOM))
    check(res['status'] != 'success' and storage.get_mission(mid)['subject_id'] == pid,
          f"a parked mission's project cannot be swapped out from under it: {res}")


def scenario_b5_a_restart_resumes_satisfied_waits():
    mid, pid, demo, research = _parked()
    _step(mid)
    row = storage.get_project(pid)
    for s in row['steps']:
        if s['id'] == demo['id']:
            s['state'] = 'done'
    storage.update_project(pid, {'steps': row['steps']})          # ticked while the add-on was down
    check(storage.get_mission(mid)['status'] == 'waiting_step', "still parked before reconcile")
    from services import planned
    planned.reconcile()
    check(storage.get_mission(mid)['status'] == 'running', "reconcile resumed it")


SCENARIOS = [
    scenario_b1_the_status_sets,
    scenario_b2_a_plan_waits_for_a_persons_step,
    scenario_b3_live_everywhere,
    scenario_b4_retarget_refused_while_parked,
    scenario_b5_a_restart_resumes_satisfied_waits,
]

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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
