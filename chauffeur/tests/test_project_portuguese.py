"""Acceptance: "I want to learn Portuguese" becomes a project (Projects core
spec §6, Task 12). Real registry; the model and research are faked.

  1. an interview, then a plan that shows the project, a program build stage,
     the person's step "Attend a first class" and an Argyle step "Find meetups";
  2. one tap: the project exists, bound to the mission, with all four steps;
  3. the program stage asks "Do this"; approved, the program is created (a
     proposal on the Programs page) and is a piece of the project;
  4. "Find meetups" starts by itself, researches, and attaches what it found;
  5. "Attend a first class" gets a calendar hold.

Run from chauffeur/:  python tests/test_project_portuguese.py
"""
import datetime

from harness import check  # noqa: F401
from services import storage, missions, situations, web
from test_planned_missions import _fresh as _fresh_planned, _plan_of
from test_mission_subject import _plan, _step, _mission
from test_subjects import MOM


def _fresh():
    _fresh_planned(step_cap=200)
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = lambda: dict(base, missions_enabled=True)
    from services import model_pools, programs_curate
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'
    programs_curate.curate = lambda *a, **k: {'phases': [], 'source': {'origin': 'none', 'reason': 'test', 'plan_name': '', 'url': ''}}
    web.research = lambda question, read_pages=None, api_key=None: {
        'status': 'success', 'answer': 'Lisbon Club meets Tuesdays; Portuguese Corner meets Saturdays.', 'facts': [], 'sources': []}


def _stage(mid, sid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def scenario_learning_portuguese():
    from services import planned, projects
    _fresh()
    # Front door slice 1: the sentence goes through start_project; the project exists before the interview.
    from services import agent_tools_v2 as tools
    started = tools.start_project('I want to learn Portuguese', acting_member=dict(MOM))
    check(started['status'] == 'success' and started['mission_id'], f"the project card first, then planning: {started}")
    mid, pid = started['mission_id'], started['project_id']
    _plan({'action': 'interview', 'questions': [{'key': 'level', 'ask': 'Where are you starting?', 'kind': 'text'},
                                                 {'key': 'minutes', 'ask': 'Minutes a session?', 'kind': 'number'}]})
    _step(mid)
    planned.answer_plan(mid, {'level': 'never studied', 'minutes': 20}, dict(MOM))
    _plan({'action': 'plan',
           'steps': [{'id': 'p1', 'title': 'Attend a first class', 'owner': 'mom', 'needs': ['s1']}],
           'stages': [{'id': 's1', 'kind': 'build', 'title': 'The program', 'why': 'a weekly plan', 'makes': ['a Portuguese program']},
                      {'id': 's2', 'kind': 'work', 'title': 'Find meetups', 'why': 'practice with people', 'goal': 'three Portuguese meetups nearby',
                       'step_budget': 4, 'makes': ['three meetups'], 'needs': ['s1']}]})
    _step(mid)
    card = missions.ask_card(storage.get_mission(mid))
    check(card['project']['id'] == pid and [s['title'] for s in card['steps']] == ['Attend a first class'],
          f"the plan names the existing project and your step: {card.get('project')} {card.get('steps')}")
    res = situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{_plan_of(mid)['rev']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"one tap: {res}")
    rows = storage.get_projects()
    check(len(rows) == 1 and rows[0]['id'] == pid and missions.subject_of(storage.get_mission(mid))[:2] == ('project', pid),
          "one project, the one started in chat, bound")
    check({s['title'] for s in rows[0]['steps']} == {'Attend a first class', 'The program', 'Find meetups'}, "its steps")

    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [
        {'id': 'r1', 'tool': 'propose_program', 'args': {'title': 'Portuguese basics', 'for_member_name': 'Mom', 'sessions_per_week': 3,
                                                         'minutes': 20, 'starting_point': 'never studied'}, 'summary': 'A Portuguese program'}]})
    _step(mid)
    st = _stage(mid, 's1')
    check(st['state'] == 'proposed' and 'Do this' in [o['label'] for o in situations.options_for('mission', situations.load('mission', mid))],
          "the program stage asks Do this")
    situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    pieces = storage.get_project(pid)['pieces']
    progs = [p for p in pieces if p['kind'] == 'program']
    check(progs and storage.get_program(progs[0]['id'])['state'] == 'proposed', f"the program is a proposal and a piece: {pieces}")

    _step(mid)
    check(_stage(mid, 's2')['state'] == 'running', "Find meetups starts by itself")
    _plan({'action': 'research', 'question': 'Portuguese conversation meetups near home'},
          {'action': 'stage_done', 'stage_id': 's2', 'summary': 'Two meetups', 'found': {'meetups': ['Lisbon Club (Tue)', 'Portuguese Corner (Sat)']}})
    _step(mid)
    _step(mid)
    meet = next(s for s in storage.get_project(pid)['steps'] if s['title'] == 'Find meetups')
    check(meet['state'] == 'done' and 'Lisbon Club (Tue)' in str(meet['found']), f"what it found is on the step: {meet}")

    first = next(s for s in storage.get_project(pid)['steps'] if s['title'] == 'Attend a first class')
    by = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
    w = projects.find_window('mom', 60, by)
    check(w, "a free hour is found")
    res = projects.confirm_hold(pid, first['id'], w, dict(MOM))
    check(res['status'] == 'success' and next(s for s in storage.get_project(pid)['steps'] if s['id'] == first['id'])['hold'],
          f"the first class is held on the calendar: {res}")


SCENARIOS = [scenario_learning_portuguese]

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
