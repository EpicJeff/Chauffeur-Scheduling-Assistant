"""From a plan to a project (Projects core spec §3, Task 7).

  * the planner's plan action carries `project` {title, goal, done_when, owner,
    audience, target_date} and the person's `steps` [{id, title, owner, needs,
    due_date}]; a stage may name `needs` (step or stage ids); the plan card
    shows the project and the person's steps beside the stages;
  * approving writes the project and every step once (Argyle's stages become
    steps linked to their stage), binds the mission, sets origin_mission_id;
    two concurrent approvals write once; a crash between the project write and
    the binding leaves the plan `approving` and `planned.reconcile()` completes
    it with the same ids;
  * a thread-origin plan binds the THREAD; its earlier subject becomes the
    first piece and stays in `subject_history`; `subject_rev` bumps; a sibling
    mission on the thread reads the project;
  * planning inside an existing project appends steps and creates no project;
  * a record a build stage creates attaches as a piece.

Run from chauffeur/:  python tests/test_project_planning.py
"""
import threading

from harness import check  # noqa: F401
from services import storage, missions, situations
from test_planned_missions import _fresh as _fresh_planned, _interviewed, _plan_of
from test_mission_subject import _plan, _step, _mission, _thread
from test_subjects import MOM

PROJECT = {'title': 'Learn Portuguese', 'goal': 'hold a conversation', 'done_when': 'order dinner in Lisbon in Portuguese',
           'owner': 'mom', 'audience': 'household', 'target_date': '2027-06-01'}
STEPS = [{'id': 'p1', 'title': 'Attend a first class', 'owner': 'mom', 'needs': ['s1']},
         {'id': 'p2', 'title': 'Book flights to Lisbon', 'owner': 'mom', 'needs': ['p1'], 'due_date': '2027-03-01'}]
STAGES = [{'id': 's1', 'kind': 'build', 'title': 'A study list', 'why': 'x', 'makes': ['a Portuguese list']},
          {'id': 's2', 'kind': 'work', 'title': 'Find meetups', 'why': 'x', 'goal': 'three Portuguese meetups nearby',
           'step_budget': 4, 'makes': ['three meetups'], 'needs': ['p1']}]


def _fresh():
    _fresh_planned()
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = lambda: dict(base, missions_enabled=True)


def _pj():
    from services import projects
    return projects


def _planned(mid=None, project=PROJECT, steps=STEPS, stages=STAGES):
    from services import planned
    mid = _interviewed(mid, template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    action = {'action': 'plan', 'stages': stages, 'steps': steps}
    if project is not None:
        action['project'] = project
    _plan(action)
    _step(mid)
    check(_plan_of(mid).get('state') == 'proposed', f"the plan waits: {_plan_of(mid)}")
    return mid


def _approve(mid):
    return situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{_plan_of(mid)['rev']}:approve",
                          payload={}, actor=dict(MOM))


def scenario_the_preview_carries_the_project_and_your_steps():
    _fresh()
    mid = _planned()
    card = missions.ask_card(storage.get_mission(mid))
    check(card and card['project']['title'] == 'Learn Portuguese' and card['project']['done_when'].startswith('order dinner'),
          f"the card shows the project: {card and card.get('project')}")
    check([s['title'] for s in card['steps']] == ['Attend a first class', 'Book flights to Lisbon'], f"and your steps: {card.get('steps')}")
    check(not storage.get_projects(), "nothing is written before the tap")


def scenario_approving_writes_the_project_and_steps_once():
    _fresh()
    mid = _planned()
    res = _approve(mid)
    check(res['status'] == 'success', f"approved: {res}")
    rows = storage.get_projects()
    check(len(rows) == 1, f"one project: {rows}")
    p = rows[0]
    check(p['title'] == 'Learn Portuguese' and p['owner_member_id'] == 'mom' and p['audience'] == 'household'
          and p['origin_mission_id'] == mid and p['target_date'] == '2027-06-01', f"the project as previewed: {p}")
    titles = {s['title']: s for s in p['steps']}
    check(set(titles) == {'Attend a first class', 'Book flights to Lisbon', 'A study list', 'Find meetups'}, f"steps: {sorted(titles)}")
    check(titles['A study list']['owner'] == 'argyle' and titles['A study list']['mission_id'] == mid
          and titles['A study list']['stage_id'] == 's1', "a stage becomes an Argyle step linked to it")
    ids = {s['title']: s['id'] for s in p['steps']}
    check(titles['Attend a first class']['needs'] == [ids['A study list']]
          and titles['Find meetups']['needs'] == [ids['Attend a first class']]
          and titles['Book flights to Lisbon']['needs'] == [ids['Attend a first class']], "needs translated to step ids")
    check(missions.subject_of(storage.get_mission(mid))[:2] == ('project', p['id']), "the mission is bound to it")
    check(_plan_of(mid)['state'] == 'approved', "approved")


def scenario_two_approvals_at_once_write_once():
    _fresh()
    mid = _planned()
    out = []
    ts = [threading.Thread(target=lambda: out.append(_approve(mid))) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check(len(storage.get_projects()) == 1 and len(storage.get_projects()[0]['steps']) == 4, f"one project, four steps: {out}")


def scenario_a_crash_mid_approval_is_completed_by_reconcile():
    _fresh()
    mid = _planned()
    real = storage.update_mission
    state = {'raised': False}

    def flaky(mission_id, fields):
        if not state['raised'] and fields.get('subject_kind') == 'project':
            state['raised'] = True
            raise RuntimeError('power cut')
        return real(mission_id, fields)
    storage.update_mission = flaky
    try:
        try:
            _approve(mid)
        except RuntimeError:
            pass
    finally:
        storage.update_mission = real
    check(state['raised'], "the crash happened at the binding")
    check(_plan_of(mid)['state'] == 'approving', f"left approving: {_plan_of(mid).get('state')}")
    first = [p['id'] for p in storage.get_projects()]
    from services import planned
    planned.reconcile()
    rows = storage.get_projects()
    check([p['id'] for p in rows] == first and len(rows) == 1 and len(rows[0]['steps']) == 4,
          f"completed with the same ids, nothing doubled: {rows}")
    check(_plan_of(mid)['state'] == 'approved' and missions.subject_of(storage.get_mission(mid))[:2] == ('project', rows[0]['id']),
          "approved and bound")


def scenario_a_thread_plan_binds_the_thread():
    _fresh()
    tid = _thread('Portuguese', subject_kind='trip', subject_id='ev_disney', subject_rev=1)
    storage.update_thread(tid, {'subject_history': []})
    mid = _planned(_mission(created_by='mom', origin=tid))
    sibling = _mission(created_by='mom', origin=tid)
    _approve(mid)
    p = storage.get_projects()[0]
    t = storage.get_thread(tid)
    check(t['subject_kind'] == 'project' and t['subject_id'] == p['id'] and int(t['subject_rev']) > 1, f"the thread is bound: {t}")
    check({'kind': 'trip', 'id': 'ev_disney'} in [{'kind': h.get('kind'), 'id': h.get('id')} for h in t.get('subject_history') or []],
          f"the earlier subject stays in the history: {t.get('subject_history')}")
    check({'kind': 'trip', 'id': 'ev_disney'} in [{'kind': x['kind'], 'id': x['id']} for x in p['pieces']], f"and is the first piece: {p['pieces']}")
    check(missions.subject_of(storage.get_mission(sibling))[:2] == ('project', p['id']), "a sibling mission reads the project")


def scenario_planning_inside_an_existing_project_appends():
    _fresh()
    existing = _pj().create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it',
                             'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']
    keep = _pj().add_step(existing['id'], {'title': 'Pick a vanity', 'owner': 'mom'}, dict(MOM))['step']
    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': existing['id'], 'subject_rev': 1})
    mid = _planned(mid, project=None, steps=[{'id': 'p1', 'title': 'Demo the old tile', 'owner': 'mom', 'needs': []}],
                   stages=[STAGES[1] | {'needs': ['p1']}])
    card = missions.ask_card(storage.get_mission(mid))
    check((card.get('project') or {}).get('id') == existing['id'], f"the card names the existing project: {card.get('project')}")
    _approve(mid)
    rows = storage.get_projects()
    check(len(rows) == 1, "no second project")
    titles = [s['title'] for s in rows[0]['steps']]
    check(titles[0] == 'Pick a vanity' and set(titles) == {'Pick a vanity', 'Demo the old tile', 'Find meetups'},
          f"steps appended, the old one kept first: {titles}")
    check(len({s['id'] for s in rows[0]['steps']}) == 3 and keep['id'] in {s['id'] for s in rows[0]['steps']}, "fresh ids")


def scenario_a_record_a_stage_creates_becomes_a_piece():
    _fresh()
    mid = _planned()
    _approve(mid)
    pid = storage.get_projects()[0]['id']
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [
        {'id': 'r1', 'tool': 'create_list', 'args': {'name': 'Portuguese words'}, 'summary': 'A study list'}]})
    _step(mid)
    st = next(s for s in _plan_of(mid)['stages'] if s['id'] == 's1')
    situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    lists = [l for l in storage.get_shopping_lists() if l['name'] == 'Portuguese words']
    pieces = storage.get_project(pid)['pieces']
    check(lists and {'kind': 'list', 'id': lists[0]['id']} in [{'kind': x['kind'], 'id': x['id']} for x in pieces],
          f"the list is a piece: {pieces}")
    step = next(s for s in storage.get_project(pid)['steps'] if s.get('stage_id') == 's1')
    check(step['state'] == 'done', "and its step is done")


SCENARIOS = [
    scenario_the_preview_carries_the_project_and_your_steps,
    scenario_approving_writes_the_project_and_steps_once,
    scenario_two_approvals_at_once_write_once,
    scenario_a_crash_mid_approval_is_completed_by_reconcile,
    scenario_a_thread_plan_binds_the_thread,
    scenario_planning_inside_an_existing_project_appends,
    scenario_a_record_a_stage_creates_becomes_a_piece,
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
