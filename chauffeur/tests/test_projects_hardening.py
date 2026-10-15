"""Projects core, whole-branch review fixes (Codex adversarial review,
2026-10-15). Task 13. One scenario per finding:

  1. project write tools in a channel some member may not see are refused and
     carry no project words (set_project_state used to return the full view);
  2. a thread whose mission PROPOSES a private project carries none of its
     words to someone outside it (forwarded options, notes);
  3. a driver's hold blocks every event that OVERLAPS it (partly or spanning),
     not only events inside it; an adjacent event is free;
  4. confirming or clearing a driver's hold marks the schedule dirty and says
     so (`schedule_dirty`), so the solver re-runs;
  5. pausing and resuming a project keeps a mission that was waiting on the
     person waiting, with its question still answerable;
  6. a plan whose stage needs a person's step that needs a LATER stage is
     refused when proposed (it could only ever park);
  7. reopening a finished standalone Argyle step starts a new attempt (a new
     mission, the old one kept in the step's history); reopening a
     stage-backed one is refused with a plain reason.

Ruling recorded with this file: in chat, a person's own command to add a
step, attach a record or change a project's state runs directly (as every
chat write tool does); "proposable" in the spec means inside missions/plans.

Run from chauffeur/:  python tests/test_projects_hardening.py
"""
import datetime

from harness import check  # noqa: F401
from services import storage, missions, situations, triage
from services import agent_tools_v2 as tools
from test_planned_missions import _fresh as _fresh_planned, _interviewed, _plan_of
from test_mission_subject import _plan, _step, _mission, _thread
from test_subject_audience import _as
from test_subjects import MOM, DAD, AUNT

SECRET = 'Get down to 185 lbs'


def _fresh():
    _fresh_planned(step_cap=200)
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = lambda: dict(base, missions_enabled=True)
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'


def _pj():
    from services import projects
    return projects


def _private():
    return _pj().create({'title': SECRET, 'goal': 'hikes', 'done_when': 'the scale says 185', 'owner_member_id': 'mom'},
                        dict(MOM))['project']


def scenario_1_project_writes_in_a_mixed_channel_say_nothing():
    _fresh()
    p = _private()
    _pj().add_step(p['id'], {'title': 'Weigh in on Sundays', 'owner': 'mom'}, dict(MOM))
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    fk = f"channel:{mixed['id']}"
    for name, args in (('set_project_state', {'project_id': p['id'], 'state': 'paused'}),
                       ('add_project_step', {'project_id': p['id'], 'title': 'Buy a scale', 'owner': 'mom'}),
                       ('add_to_project', {'project_id': p['id'], 'kind': 'list', 'id': 'l1'})):
        res = getattr(tools, name)(**args, acting_member=dict(MOM), focus_key=fk)
        blob = repr(res)
        check(res['status'] == 'error' and SECRET not in blob and 'Weigh in' not in blob and 'scale says' not in blob,
              f"{name} in a channel the aunt is in: refused with no words: {blob[:200]}")
    row = storage.get_project(p['id'])
    check(row['state'] == 'active' and len(row['steps']) == 1 and row['pieces'] == [], "and nothing changed")
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')
    res = tools.set_project_state(project_id=p['id'], state='paused', acting_member=dict(MOM), focus_key=f"channel:{dm['id']}")
    check(res['status'] == 'success', f"in her own Argyle chat it works: {res}")


def scenario_2_a_thread_carries_no_words_of_a_proposed_private_project():
    _fresh()
    from services import planned
    tid = _thread('Getting fit', owner='mom')
    mid = _interviewed(_mission(created_by='mom', origin=tid), template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan',
           'project': {'title': SECRET, 'goal': 'hikes', 'done_when': 'the scale says 185', 'owner': 'mom', 'audience': 'private'},
           'steps': [],
           'stages': [{'id': 's1', 'kind': 'work', 'title': 'Weigh-in schedule', 'why': 'x', 'goal': 'a weekly weigh-in', 'step_budget': 3,
                       'makes': ['a weigh-in plan']}]})
    _step(mid)
    check(_plan_of(mid)['state'] == 'proposed', "the plan waits")
    v = situations.view('thread', tid, dict(DAD))
    blob = repr(v)
    check(SECRET not in blob and 'Weigh-in schedule' not in blob and 'scale says' not in blob,
          f"Dad's view of the thread carries no words of Mom's private proposal: {blob[:300]}")
    mine = situations.view('thread', tid, dict(MOM))
    check('Weigh-in schedule' in repr(mine), "Mom's view still has the plan's options")


def scenario_3_a_drivers_hold_blocks_every_overlapping_event():
    _fresh()
    storage.update_member('dad', {'driver_id': 'd_dad'})
    p = _pj().create({'title': 'Bathroom', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'},
                     dict(MOM))['project']
    tile = _pj().add_step(p['id'], {'title': 'Tile the floor', 'owner': 'dad'}, dict(MOM))['step']
    day = (datetime.date.today() + datetime.timedelta(days=3))
    storage.set_cached_schedule({'events': [], 'assignments': {}, 'unassigned': []})
    res = _pj().confirm_hold(p['id'], tile['id'], {'date': day.isoformat(), 'start': '13:00', 'end': '14:00'}, dict(MOM))
    check(res['status'] == 'success', f"held: {res}")
    rules = _pj().driver_hold_rules(day, day)
    from solver import matcher
    from test_override_conflicts import mk_driver
    from models.schemas import Event

    def at(h1, m1, h2, m2):
        s = datetime.datetime.combine(day, datetime.time(h1, m1))
        e = datetime.datetime.combine(day, datetime.time(h2, m2))
        return Event(id='e1', title='Soccer', start=s, end=e, location='Field', calendar_ids=['primary'], source_event_ids=['e1'])
    dad = mk_driver('d_dad', 'Dad')
    for ev, why in ((at(12, 30, 13, 30), 'starts before, ends inside'), (at(13, 30, 14, 30), 'starts inside, ends after'),
                    (at(12, 30, 14, 30), 'spans it'), (at(13, 15, 13, 45), 'inside')):
        check(any('unavailable' in r for r in matcher.explain_assignment_conflicts(ev, dad, rules)), f"blocked: {why}")
    check(not any('unavailable' in r for r in matcher.explain_assignment_conflicts(at(14, 0, 15, 0), dad, rules)),
          "an event right after the hold is free")


def scenario_4_a_drivers_hold_marks_the_schedule_dirty():
    _fresh()
    storage.update_member('dad', {'driver_id': 'd_dad'})
    p = _pj().create({'title': 'Bathroom', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'},
                     dict(MOM))['project']
    tile = _pj().add_step(p['id'], {'title': 'Tile the floor', 'owner': 'dad'}, dict(MOM))['step']
    marks = []
    real = storage.mark_all_daily_schedules_dirty
    storage.mark_all_daily_schedules_dirty = lambda *a, **k: marks.append(1) or real(*a, **k)
    try:
        day = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        res = _pj().confirm_hold(p['id'], tile['id'], {'date': day, 'start': '13:00', 'end': '14:00'}, dict(MOM))
        check(res['status'] == 'success' and res.get('schedule_dirty') is True and marks, f"confirming re-solves: {res}")
        marks.clear()
        res = _pj().clear_hold(p['id'], tile['id'], dict(MOM))
        check(res.get('schedule_dirty') is True and marks, f"clearing re-solves too: {res}")
    finally:
        storage.mark_all_daily_schedules_dirty = real


def scenario_5_pause_and_resume_keep_a_question_waiting():
    _fresh()
    from test_project_argyle import _running_work
    mid, pid, a, p = _running_work()
    _plan({'action': 'ask_user', 'question': 'Chocolate or vanilla?'})
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_user', "waiting on Mom's answer")
    _pj().set_state(pid, 'paused', dict(MOM))
    _pj().set_state(pid, 'active', dict(MOM))
    check(storage.get_mission(mid)['status'] == 'waiting_user', f"still waiting after resume: {storage.get_mission(mid)['status']}")
    res = missions.answer(mid, 'Chocolate', dict(MOM))
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', f"and the answer is taken: {res}")


def scenario_6_a_plan_that_could_only_park_is_refused():
    _fresh()
    from services import planned
    mid = _interviewed(template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan',
           'project': {'title': 'Garage', 'goal': 'x', 'done_when': 'x', 'owner': 'mom', 'audience': 'household'},
           'steps': [{'id': 'p1', 'title': 'Clear the shelves', 'owner': 'mom', 'needs': ['b']}],
           'stages': [{'id': 'a', 'kind': 'work', 'title': 'Find a skip', 'why': 'x', 'goal': 'a skip', 'step_budget': 3, 'makes': [],
                       'needs': ['p1']},
                      {'id': 'b', 'kind': 'work', 'title': 'Find a mover', 'why': 'x', 'goal': 'a mover', 'step_budget': 3, 'makes': []}]})
    _step(mid)
    check(_plan_of(mid).get('state') != 'proposed' and [s for s in storage.get_mission_steps(mid) if s.get('name') == 'refused'],
          f"refused when proposed: stage a needs a step that needs the later stage b: {_plan_of(mid).get('state')}")


def scenario_7_reopening_argyle_work():
    _fresh()
    p = _pj().create({'title': 'Portuguese', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'},
                     dict(MOM))['project']
    sid = _pj().add_step(p['id'], {'title': 'Find meetups', 'owner': 'argyle', 'goal': 'three meetups'}, dict(MOM))['step']['id']
    first = next(s for s in storage.get_project(p['id'])['steps'] if s['id'] == sid)['mission_id']
    _plan({'action': 'finish', 'summary': 'Three meetups', 'next_action': 'pick one'})
    _step(first)
    check(next(s for s in storage.get_project(p['id'])['steps'] if s['id'] == sid)['state'] == 'done', "done")
    res = _pj().set_step_state(p['id'], sid, 'todo', dict(MOM))
    step = next(s for s in storage.get_project(p['id'])['steps'] if s['id'] == sid)
    check(res['status'] == 'success' and step['mission_id'] and step['mission_id'] != first and step['state'] == 'doing',
          f"reopening starts a new attempt: {step}")
    check(first in [h.get('mission_id') for h in step.get('attempts') or []], f"the old attempt is kept: {step.get('attempts')}")
    from test_project_argyle import _running_work
    mid, pid, a, q = _running_work()
    _plan({'action': 'stage_done', 'stage_id': 's2', 'summary': 'Two bakeries', 'found': {'bakeries': ['A', 'B']}})
    _step(mid)
    res = _pj().set_step_state(pid, a, 'todo', dict(MOM))
    check(res['status'] == 'error' and 'plan' in res['message'].lower(), f"a stage-backed step is not reopened by a tick: {res}")

def scenario_8_steering_a_stage_while_paused_waits_for_resume():
    """Scoped re-review: a steer on a waiting stage while the project is paused must not run it or strand it."""
    _fresh()
    from test_planned_missions import _approved, ROWS
    mid = _approved()
    pid = _pj().create({'title': 'Party', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'},
                       dict(MOM))['project']['id']
    storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': pid, 'subject_rev': 1})
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': ROWS})
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_user', "the build stage waits for Do this")
    _pj().set_state(pid, 'paused', dict(MOM))
    res = missions.answer(mid, 'make it pizza instead', dict(MOM))
    check(res['status'] == 'success', f"the steer is taken: {res}")
    row = storage.get_mission(mid)
    check(row['status'] not in missions.RUNNABLE, f"still parked while paused: {row['status']}")
    missions.tick()
    check(storage.get_mission(mid)['status'] not in missions.RUNNABLE, "the tick does not run it")
    _pj().set_state(pid, 'active', dict(MOM))
    check(storage.get_mission(mid)['status'] == 'running', f"resume runs the steered stage again: {storage.get_mission(mid)['status']}")


def scenario_9_reopening_stopped_argyle_work():
    """Scoped re-review: a STOPPED (blocked) Argyle step reopens like a finished one."""
    _fresh()
    import main
    p = _pj().create({'title': 'Portuguese', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'},
                     dict(MOM))['project']
    sid = _pj().add_step(p['id'], {'title': 'Find meetups', 'owner': 'argyle', 'goal': 'three meetups'}, dict(MOM))['step']['id']
    first = next(s for s in storage.get_project(p['id'])['steps'] if s['id'] == sid)['mission_id']
    main.project_step_cancel(p['id'], sid, {'outcome': 'stop'}, request=_as('mom'))
    step = next(s for s in storage.get_project(p['id'])['steps'] if s['id'] == sid)
    check(step['state'] == 'blocked' and storage.get_mission(first)['status'] in missions.TERMINAL, f"stopped: {step}")
    res = _pj().set_step_state(p['id'], sid, 'todo', dict(MOM))
    step = next(s for s in storage.get_project(p['id'])['steps'] if s['id'] == sid)
    check(res['status'] == 'success' and step['mission_id'] and step['mission_id'] != first and step['state'] == 'doing'
          and first in [h.get('mission_id') for h in step.get('attempts') or []], f"a new attempt with history: {step}")
    from test_project_argyle import _running_work
    mid, pid, a, q = _running_work()
    main.project_step_cancel(pid, a, {'outcome': 'stop'}, request=_as('mom'))
    res = _pj().set_step_state(pid, a, 'todo', dict(MOM))
    check(res['status'] == 'error' and 'plan' in res['message'].lower(), f"a stopped stage-backed step is not reopened by a tick: {res}")


SCENARIOS = [
    scenario_1_project_writes_in_a_mixed_channel_say_nothing,
    scenario_2_a_thread_carries_no_words_of_a_proposed_private_project,
    scenario_3_a_drivers_hold_blocks_every_overlapping_event,
    scenario_4_a_drivers_hold_marks_the_schedule_dirty,
    scenario_5_pause_and_resume_keep_a_question_waiting,
    scenario_6_a_plan_that_could_only_park_is_refused,
    scenario_7_reopening_argyle_work,
    scenario_8_steering_a_stage_while_paused_waits_for_resume,
    scenario_9_reopening_stopped_argyle_work,
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
