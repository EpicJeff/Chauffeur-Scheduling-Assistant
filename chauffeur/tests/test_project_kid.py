"""Acceptance: Kate's own project (Projects core spec §6, Task 12).

Kate creates "Learn to ride a bike" by hand; both parents see it; Kate adds
and ticks her own step; Aunt Jo does not see it anywhere.

Run from chauffeur/:  python tests/test_project_kid.py
"""
from harness import check  # noqa: F401
from services import storage
from services import agent_tools_v2 as tools
from test_projects import _fresh
from test_subject_audience import _as
from test_subjects import KID, MOM, AUNT


def scenario_kates_bike():
    from services import projects
    import main
    _fresh()
    made = main.projects_create({'title': 'Learn to ride a bike', 'goal': 'ride to school', 'done_when': 'no training wheels',
                                 'owner_member_id': 'kid'}, request=_as('kid'))
    pid = made['project']['id']
    check(made['project']['audience'] == 'parents', "a child's project is for her parents too")
    for parent in ('mom', 'dad'):
        titles = [p['title'] for p in main.projects_list(request=_as(parent))['projects']]
        check('Learn to ride a bike' in titles, f"{parent} sees it")
    check('Learn to ride a bike' not in [p['title'] for p in main.projects_list(request=_as('aunt'))['projects']], "Aunt Jo does not")
    check('ride a bike' not in tools.list_projects(acting_member=dict(AUNT))['message'], "not by words either")
    step = main.project_add_step(pid, {'title': 'Practise in the park', 'owner': 'kid'}, request=_as('kid'))['step']
    out = main.project_step_state(pid, step['id'], {'state': 'done'}, request=_as('kid'))
    check(out['status'] == 'success' and storage.get_project(pid)['steps'][0]['done_by'] == 'kid', "Kate ticks her own step")
    v = projects.view(storage.get_project(pid), dict(MOM))
    check(v['steps_done'] == 1, "Mom sees the progress, counting up")


SCENARIOS = [scenario_kates_bike]

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
