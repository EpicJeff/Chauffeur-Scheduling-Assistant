"""A project's words follow its audience everywhere (Projects core spec §5),
Task 10. For `private`, `parents` and `household`:

  * the list and detail routes, the "Part of" route;
  * the Mind's snapshot never carries a private project's words, nor those of a
    mission or plan bound to it;
  * a speaker never speaks a private or parents project (list_projects by voice
    returns only household ones);
  * in a channel some member may not see, situation tools refuse a mission
    bound to the project (own Argyle chat) and list_projects leaves it out;
  * a keeper (an adult whose mission a parent later bound to a project they
    may not see) keeps the row and Stop, never the project's words;
  * a planned mission that PROPOSES a private project is private to its creator
    from the moment the plan is proposed (routed from Task 7's review): another
    adult's Missions page, mission detail and situation card carry none of it.

Run from chauffeur/:  python tests/test_projects_audience.py
"""
from fastapi import HTTPException

from harness import check  # noqa: F401
from services import storage, missions, situations, triage
from services import agent_tools_v2 as tools
from test_projects import _p, _make
from test_planned_missions import _fresh as _fresh_planned, _interviewed, _plan_of
from test_mission_subject import _plan, _step, _mission, _thread
from test_subject_audience import _as
from test_subjects import MOM, DAD, AUNT, KID

SECRET = 'Get down to 185 lbs'


def _fresh():
    _fresh_planned()
    storage.projects_table.truncate()


def _three():
    private = _make('mom', MOM, title=SECRET)
    parents = _make('kid', MOM, title='Learn to ride a bike')
    house = _make('mom', MOM, audience='household', title='Garage clear-out')
    return private, parents, house


def scenario_routes_and_part_of():
    _fresh()
    import main
    private, parents, house = _three()
    for p in (private, parents, house):
        _p().add_piece(p['id'], 'list', 'l1', dict(MOM))
    expect = {'mom': {SECRET, 'Learn to ride a bike', 'Garage clear-out'}, 'dad': {'Learn to ride a bike', 'Garage clear-out'},
              'aunt': {'Garage clear-out'}, 'kid': {'Learn to ride a bike', 'Garage clear-out'}}
    for who, titles in expect.items():
        got = {x['title'] for x in main.projects_list(request=_as(who))['projects']}
        check(got == titles, f"{who}'s list: {got}")
        part = {x['title'] for x in main.subject_projects('list', 'l1', request=_as(who))['projects']}
        check(part <= titles and SECRET not in part or who == 'mom', f"{who}'s Part of: {part}")
    try:
        main.project_detail(private['id'], request=_as('dad'))
        check(False, "Dad cannot read the private one")
    except HTTPException as e:
        check(e.status_code == 404, "404")


def scenario_the_mind_never_carries_a_private_projects_words():
    _fresh()
    private, parents, house = _three()
    _p().add_step(private['id'], {'title': 'Weigh in on Sundays', 'owner': 'mom'}, dict(MOM))
    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': private['id'], 'subject_rev': 1,
                                 'goal': 'plan the 185 lbs goal'})
    from services import mind
    snap = mind.snapshot()
    for words in (SECRET, 'Weigh in on Sundays', '185'):
        check(words not in snap, f"the Mind's snapshot carries none of the private project: {words!r}")


def scenario_speakers_hear_only_household_projects():
    _fresh()
    private, parents, house = _three()
    res = tools.list_projects(acting_member=dict(MOM), spoken=True)
    check('Garage clear-out' in res['message'] and SECRET not in res['message'] and 'ride a bike' not in res['message'],
          f"by voice, only the household project: {res['message']}")


def scenario_a_mixed_channel_gets_nothing_of_a_parents_project():
    _fresh()
    private, parents, house = _three()
    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': parents['id'], 'subject_rev': 1})
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    fk = f"channel:{mixed['id']}"
    triage.set_focus(fk, 'mission', mid, 'Plan')
    res = tools.explain_situation(acting_member=dict(MOM), focus_key=fk)
    check(res['status'] == 'error' and 'ride a bike' not in res['message'], f"refused in a channel the aunt is in: {res}")
    listed = tools.list_projects(acting_member=dict(MOM), focus_key=fk)
    check('ride a bike' not in listed['message'] and 'Garage clear-out' in listed['message'], f"and left out of the list: {listed['message']}")


def scenario_a_keeper_keeps_the_row_and_stop():
    _fresh()
    import main
    private, parents, house = _three()
    mid = _mission(created_by='aunt')
    storage.update_mission(mid, {'subject_kind': 'project', 'subject_id': parents['id'], 'subject_rev': 1,
                                 'goal': 'help with the bike', 'summary': 'Learn to ride a bike: two parks found'})
    detail = main.missions_detail(mid, request=_as('aunt'))
    check('ride a bike' not in repr(detail), f"the keeper reads no project words: {repr(detail)[:300]}")
    v = situations.view('mission', mid, dict(AUNT))
    check(v and 'ride a bike' not in repr(v), "nor on the card")
    check(any(o['label'] in ('Stop', 'Done with it') or o['verb'] in ('close',) for o in v.get('options') or []),
          f"but keeps a way to stop it: {[o['label'] for o in v.get('options') or []]}")


def scenario_a_plan_proposing_a_private_project_is_private_from_the_start():
    _fresh()
    import main
    from services import planned
    mid = _interviewed(template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan',
           'project': {'title': SECRET, 'goal': 'feel better on hikes', 'done_when': 'the scale says 185', 'owner': 'mom',
                       'audience': 'private'},
           'steps': [{'id': 'p1', 'title': 'Weigh in on Sundays', 'owner': 'mom', 'needs': []}],
           'stages': [{'id': 's1', 'kind': 'work', 'title': 'Find a walking group', 'why': 'x', 'goal': 'a walking group nearby',
                       'step_budget': 3, 'makes': []}]})
    _step(mid)
    check(_plan_of(mid)['state'] == 'proposed', "the plan waits")
    admin = main.missions_admin(request=_as('dad'))
    rows = [m for m in (admin.get('active') or []) + (admin.get('history') or []) if m['id'] == mid]
    check(not rows or (SECRET not in repr(rows) and 'Weigh in' not in repr(rows)), f"Dad's Missions page: {repr(rows)[:300]}")
    try:
        detail = main.missions_detail(mid, request=_as('dad'))
        check(SECRET not in repr(detail) and 'Weigh in' not in repr(detail), f"Dad's detail: {repr(detail)[:300]}")
    except HTTPException:
        pass
    v = situations.view('mission', mid, dict(DAD))
    check(v is None or (SECRET not in repr(v) and 'Weigh in' not in repr(v)), f"Dad's card: {repr(v)[:300]}")
    mine = main.missions_detail(mid, request=_as('mom'))
    check(SECRET in repr(mine), "Mom sees her own plan")


SCENARIOS = [
    scenario_routes_and_part_of,
    scenario_the_mind_never_carries_a_private_projects_words,
    scenario_speakers_hear_only_household_projects,
    scenario_a_mixed_channel_gets_nothing_of_a_parents_project,
    scenario_a_keeper_keeps_the_row_and_stop,
    scenario_a_plan_proposing_a_private_project_is_private_from_the_start,
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
