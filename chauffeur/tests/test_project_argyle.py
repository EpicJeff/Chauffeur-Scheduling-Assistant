"""Argyle's steps: they start themselves, finish with their stage, and can be
skipped or stopped (Projects core spec §2 "Argyle's steps", "Cancelling running
work"; Decision 5). Task 6.

  * a work stage of an approved plan starts itself (no "Go do this part"); a
    running work stage offers Skip and Stop; a build stage still asks "Do this";
  * a stage-backed step is `doing` while its stage runs and `done` when its
    stage is done, carrying what was found; research → a person's demo → more
    research completes without deadlock;
  * a standalone Argyle step starts a mission bound to the project with the
    step's goal, and is done when that mission finishes;
  * a failed row marks the step `blocked` with the reason; a question shows on
    the step;
  * Skip on a running work stage: its queued follow-up rows dismissed, its ask
    settled, the step `skipped` (satisfying what follows); Stop stops the plan
    and leaves the step `blocked`;
  * dropping the project mid-browse: the late result is dropped, no card;
  * a build stage stopped mid-row finishes that row and runs no more.

Run from chauffeur/:  python tests/test_project_argyle.py
"""
import threading
import time

from harness import check  # noqa: F401
from services import storage, missions, situations, chat_actions
from test_planned_missions import _fresh as _fresh_planned, _planned_mission, _approved, _plan_of, _ask_names, _opts
from test_mission_subject import _plan, _step, _steps
from test_subjects import MOM, AUNT

WORK2 = [{'id': 's1', 'kind': 'work', 'title': 'Find tile', 'why': 'x', 'goal': 'three tiles under $5', 'step_budget': 4, 'makes': []},
         {'id': 's2', 'kind': 'work', 'title': 'Find grout', 'why': 'x', 'goal': 'matching grout', 'step_budget': 4, 'makes': []}]


def _fresh():
    _fresh_planned()
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = lambda: dict(base, missions_enabled=True)
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'


def _pj():
    from services import projects
    return projects


def _project(mid=None):
    pid = _pj().create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it',
                        'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']['id']
    if mid:
        storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': pid, 'subject_rev': 1})
    return pid


def _add(pid, actor=MOM, **step):
    res = _pj().add_step(pid, step, dict(actor))
    check(res['status'] == 'success', f"step: {res}")
    return res['step']['id']


def _link(pid, sid, mid, stage_id):
    row = storage.get_project(pid)
    for s in row['steps']:
        if s['id'] == sid:
            s.update(mission_id=mid, stage_id=stage_id)
    storage.update_project(pid, {'steps': row['steps']})


def _st(pid, sid):
    return next(s for s in storage.get_project(pid)['steps'] if s['id'] == sid)


def _stage(mid, sid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def _approve_plan(mid, drop=()):
    for sid in drop:
        situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{_plan_of(mid)['rev']}:drop:{sid}", payload={}, actor=dict(MOM))
    res = situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{_plan_of(mid)['rev']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"plan approved: {res}")


def _running_work(owner_of_next='aunt'):
    """A bound plan whose single work stage s2 is the project's Argyle step a, then a person's step p after it."""
    _fresh()
    mid = _planned_mission()
    pid = _project(mid)
    a = _add(pid, title='Find a bakery', owner='argyle', goal='find two bakeries')
    p = _add(pid, title='Pick one', owner=owner_of_next, needs=[a])
    _link(pid, a, mid, 's2')
    _approve_plan(mid, drop=('s1',))
    _step(mid)
    return mid, pid, a, p


def scenario_c1_a_work_stage_starts_itself():
    mid, pid, a, p = _running_work()
    check(_stage(mid, 's2')['state'] == 'running', f"started with no tap: {_stage(mid, 's2')}")
    check(_st(pid, a)['state'] == 'doing' and _st(pid, a)['mission_id'] == mid, f"its step is doing: {_st(pid, a)}")
    labels = [o['label'] for o in _opts(mid, 'run_stage')]
    check('Go do this part' not in labels and {'Skip', 'Stop'} <= set(labels), f"Skip and Stop, no Go: {labels}")


def scenario_c2_a_build_stage_still_asks():
    _fresh()
    from test_planned_missions import _staged
    mid, st = _staged()
    check(st['state'] == 'proposed' and _ask_names(mid)[-1] == 'stage', "a build stage waits for its tap")
    check('Do this' in [o['label'] for o in _opts(mid, 'run_stage')], "with Do this")


def scenario_c3_research_then_a_person_then_research_completes():
    _fresh()
    mid = _planned_mission(WORK2)
    pid = _project(mid)
    a1 = _add(pid, title='Find tile', owner='argyle', goal='three tiles under $5')
    p1 = _add(pid, title='Demo the old tile', owner='aunt', needs=[a1])
    a2 = _add(pid, title='Find grout', owner='argyle', goal='matching grout', needs=[p1])
    _link(pid, a1, mid, 's1')
    _link(pid, a2, mid, 's2')
    _approve_plan(mid)
    _step(mid)
    check(_stage(mid, 's1')['state'] == 'running' and _st(pid, a1)['state'] == 'doing', "the first research runs")
    _plan({'action': 'stage_done', 'stage_id': 's1', 'summary': 'Two tiles', 'found': {'tiles': ['Ivory', 'Slate']}})
    _step(mid)
    check(_st(pid, a1)['state'] == 'done' and _st(pid, a1)['found'] == {'tiles': ['Ivory', 'Slate']},
          f"the step is done with its stage, carrying what was found: {_st(pid, a1)}")
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_step', "then it waits for the demo")
    res = _pj().set_step_state(pid, p1, 'done', dict(AUNT))
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', f"the demo resumes it: {res}")
    _step(mid)
    check(_stage(mid, 's2')['state'] == 'running' and _st(pid, a2)['state'] == 'doing', "the second research runs")
    _plan({'action': 'stage_done', 'stage_id': 's2', 'summary': 'Grout found', 'found': {'grout': 'Bright white'}})
    _step(mid)
    check(_st(pid, a2)['state'] == 'done', "no deadlock: all three done")


def scenario_c4_a_standalone_argyle_step_runs_its_own_mission():
    _fresh()
    pid = _project()
    a = _add(pid, title='Find meetups', owner='argyle', goal='find three Portuguese meetups nearby')
    st = _st(pid, a)          # adding a ready Argyle step starts it at once
    m = storage.get_mission(st.get('mission_id') or '')
    check(m and st['state'] == 'doing' and m['goal'] == 'find three Portuguese meetups nearby'
          and missions.subject_of(m)[:2] == ('project', pid), f"a mission bound to the project with the step's goal: {st} {m}")
    check(_pj().advance(pid) == [], "advancing again starts nothing twice")
    _plan({'action': 'finish', 'summary': 'Three meetups found', 'next_action': 'pick one'})
    _step(m['id'])
    st = _st(pid, a)
    check(st['state'] == 'done' and 'Three meetups found' in str(st.get('found')), f"done when its mission finishes: {st}")


def scenario_c5_a_failed_row_blocks_the_step_and_a_question_shows():
    _fresh()
    mid = _approved()
    pid = _project(mid)
    a = _add(pid, title='Make the party', owner='argyle', goal='create the occasion')
    _link(pid, a, mid, 's1')
    from test_planned_missions import ROWS
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': ROWS})
    _step(mid)
    orig = chat_actions.run_row
    chat_actions.run_row = lambda *args, **kw: {'status': 'error', 'message': 'the occasions page is down', 'created': []}
    try:
        st = _stage(mid, 's1')
        situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    finally:
        chat_actions.run_row = orig
    step = _st(pid, a)
    check(step['state'] == 'blocked' and 'the occasions page is down' in (step.get('question') or ''),
          f"blocked with the reason: {step}")
    mid2, pid2, a2, _ = _running_work()
    _plan({'action': 'ask_user', 'question': 'Chocolate or vanilla?'})
    _step(mid2)
    check(_st(pid2, a2).get('question') == 'Chocolate or vanilla?', f"the question shows on the step: {_st(pid2, a2)}")


def _opt(mid, label):
    return next(o for o in _opts(mid, 'run_stage') if o['label'] == label)


def scenario_c6_skip_dismisses_its_work_and_lets_the_next_step_go():
    mid, pid, a, p = _running_work()
    _plan({'action': 'propose', 'tool': 'create_list', 'args': {'name': 'Bakeries'}, 'summary': 'A list', 'why': 'x'})
    _step(mid)
    res = situations.act('mission', mid, 'run_stage', option_id=_opt(mid, 'Skip')['id'], payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"skipped: {res}")
    check(_stage(mid, 's2')['state'] == 'skipped', f"the stage is skipped: {_stage(mid, 's2')}")
    follow = [s for s in _plan_of(mid)['stages'] if s.get('parent') == 's2']
    check(not follow or all(r.get('state') in ('excluded', 'skipped', 'withdrawn') for f in follow for r in f.get('rows', []))
          or all(f.get('state') == 'skipped' for f in follow), f"its queued writes are dismissed: {follow}")
    check(_st(pid, a)['state'] == 'skipped', "the step is skipped")
    check(_pj().set_step_state(pid, p, 'done', dict(AUNT))['status'] == 'success', "and the next step can go")


def scenario_c7_stop_stops_the_plan_and_blocks_the_step():
    mid, pid, a, p = _running_work()
    res = situations.act('mission', mid, 'run_stage', option_id=_opt(mid, 'Stop')['id'], payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"stopped: {res}")
    check(_plan_of(mid)['state'] == 'stopped' and _st(pid, a)['state'] == 'blocked', f"plan stopped, step blocked: {_st(pid, a)}")


def scenario_c8_dropping_the_project_mid_browse_drops_the_late_result():
    mid, pid, a, p = _running_work()
    missions._browse_async = True          # this scenario needs the browse on its own thread
    gate = threading.Event()
    missions._browse = lambda **kw: (gate.wait(15), {
        'outcome': 'done', 'text': 'Found two bakeries.', 'learned': {}, 'stopped_at': 'https://example.com', 'wanted_fields': [],
        'turns': 2, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}})[1]
    sent = []
    missions._post = lambda dm, argyle, body, card=None: sent.append(body) or {'id': f'm{len(sent)}'}
    _plan({'action': 'browse', 'goal': 'find bakeries', 'site': 'example.com'})
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'browsing', "browsing")
    asks_before = len(_ask_names(mid))
    _pj().set_state(pid, 'dropped', dict(MOM))
    gate.set()
    deadline = time.time() + 15
    while time.time() < deadline and not [s for s in _steps(mid) if s.get('kind') == 'browse' and s.get('result_json')]:
        time.sleep(0.2)
    time.sleep(0.5)
    check(storage.get_mission(mid)['status'] in missions.TERMINAL, f"the mission ended with the project: {storage.get_mission(mid)['status']}")
    check(len(_ask_names(mid)) == asks_before and not sent, f"the late result brought no card: {sent}")


def scenario_c9_a_build_stage_stopped_mid_row_runs_no_more_rows():
    _fresh()
    mid = _approved()
    rows = [{'id': f'r{i}', 'tool': 'draft_message', 'args': {'to': 'x', 'words': str(i)}, 'summary': f'd{i}'} for i in range(3)]
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': rows})
    _step(mid)
    from services import planned
    calls = []
    st = _stage(mid, 's1')
    real_resolve = planned._resolve_refs

    def resolve(args, completed):
        calls.append(1)
        if len(calls) == 1:
            res = planned.stop_plan(mid, dict(MOM))
            check(res['status'] == 'success', f"stop accepted mid-row: {res}")
        return real_resolve(args, completed)
    planned._resolve_refs = resolve
    try:
        situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    finally:
        planned._resolve_refs = real_resolve
    states = [r['state'] for r in _stage(mid, 's1')['rows']]
    check(len(calls) == 1 and states[0] == 'done' and states[1:] != ['done', 'done'],
          f"the row in flight finished, no more ran: {states} after {len(calls)} row(s)")

def scenario_c10_pausing_parks_the_work_and_resuming_continues_it():
    """Pausing starts nothing new until resumed (spec §1) -- it must not end the plan."""
    mid, pid, a, p = _running_work()
    standalone = _add(pid, title='Find meetups', owner='argyle', goal='find three meetups nearby')
    smid = _st(pid, standalone)['mission_id']
    check(smid and storage.get_mission(smid)['status'] == 'running', "a standalone step is running too")
    res = _pj().set_state(pid, 'paused', dict(MOM))
    check(res['status'] == 'success', f"paused: {res}")
    for m in (mid, smid):
        row = storage.get_mission(m)
        check(row['status'] not in missions.RUNNABLE and row['status'] not in missions.TERMINAL,
              f"parked, not ended: {row['status']}")
    check(_plan_of(mid)['state'] == 'approved', f"the plan is not stopped: {_plan_of(mid)['state']}")
    check(_st(pid, a)['state'] not in ('blocked', 'skipped', 'done'), f"its step is not blocked: {_st(pid, a)}")
    missions.tick()
    check(storage.get_mission(mid)['status'] not in missions.RUNNABLE, "nothing runs while paused")
    res = _pj().set_state(pid, 'active', dict(MOM))
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'running'
          and storage.get_mission(smid)['status'] == 'running', "resuming continues both")
    _step(mid)
    check(_stage(mid, 's2')['state'] == 'running', f"the work stage runs again: {_stage(mid, 's2')}")


SCENARIOS = [
    scenario_c1_a_work_stage_starts_itself,
    scenario_c2_a_build_stage_still_asks,
    scenario_c3_research_then_a_person_then_research_completes,
    scenario_c4_a_standalone_argyle_step_runs_its_own_mission,
    scenario_c5_a_failed_row_blocks_the_step_and_a_question_shows,
    scenario_c6_skip_dismisses_its_work_and_lets_the_next_step_go,
    scenario_c7_stop_stops_the_plan_and_blocks_the_step,
    scenario_c8_dropping_the_project_mid_browse_drops_the_late_result,
    scenario_c9_a_build_stage_stopped_mid_row_runs_no_more_rows,
    scenario_c10_pausing_parks_the_work_and_resuming_continues_it,
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
