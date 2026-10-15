"""Acceptance: an adult's private body goal (Projects core spec §6, Task 12;
the user's 2026-10-15 change to the body-goal lock).

Mom's "Get down to 185 lbs" is allowed and private. Dad sees nothing of it on
any surface: the list, the detail, "Part of", the Mind's snapshot, Argyle's
words, and the calendar (where its hold reads "Busy"). Widening its audience
is refused.

Run from chauffeur/:  python tests/test_project_private.py
"""
import datetime

from fastapi import HTTPException

from harness import check  # noqa: F401
from services import storage
from services import agent_tools_v2 as tools
from test_projects import _fresh
from test_subject_audience import _as
from test_subjects import MOM, DAD

GOAL = 'Get down to 185 lbs'


def scenario_moms_private_goal():
    from services import projects, mind
    import main
    _fresh()
    made = main.projects_create({'title': GOAL, 'goal': 'feel good on hikes', 'done_when': 'the scale says 185',
                                 'owner_member_id': 'mom'}, request=_as('mom'))
    p = made['project']
    check(p['body_goal'] is True and p['audience'] == 'private', f"allowed, private: {p}")
    step = main.project_add_step(p['id'], {'title': 'Long walk with weigh-in', 'owner': 'mom'}, request=_as('mom'))['step']
    day = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    projects.confirm_hold(p['id'], step['id'], {'date': day, 'start': '07:00', 'end': '08:00'}, dict(MOM))
    projects.add_piece(p['id'], 'list', 'l1', dict(MOM))
    check(GOAL not in [x['title'] for x in main.projects_list(request=_as('dad'))['projects']], "not in Dad's list")
    try:
        main.project_detail(p['id'], request=_as('dad'))
        check(False, "Dad cannot open it")
    except HTTPException as e:
        check(e.status_code == 404, "404")
    check(main.subject_projects('list', 'l1', request=_as('dad'))['projects'] == [], "no Part of for Dad")
    check('185' not in tools.list_projects(acting_member=dict(DAD))['message'], "not in Argyle's words to Dad")
    check(GOAL not in mind.snapshot() and 'weigh-in' not in mind.snapshot(), "not in the Mind's snapshot")
    start = datetime.date.today()
    dads = projects.calendar_holds(start, start + datetime.timedelta(days=7), dict(DAD))
    check([h['title'] for h in dads] == ['Busy'], f"the calendar shows Dad only Busy: {dads}")
    check(projects.update(p['id'], {'audience': 'household'}, dict(MOM))['status'] == 'error', "it cannot be widened")


SCENARIOS = [scenario_moms_private_goal]

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
