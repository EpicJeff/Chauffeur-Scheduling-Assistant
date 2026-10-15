"""The project record, its audience and lifecycle (Projects core spec §1, Task 3).

  * `projects.create(fields, actor) -> {'status', 'project'|'message'}`; a parent
    may create a project for anyone, anyone else only for themselves;
  * audience defaults: an adult's project `private`, a child's `parents`; a
    child's project is never private from their parents;
  * `projects.can_see` / `projects.can_act` (a child acts only on their own);
  * `projects.update`, `projects.set_state` (active/paused/done/dropped) by
    `can_act` only; `projects.view(project, viewer)` is the viewer's projection;
  * the routes act as the AUTHENTICATED member, never a `member_id` in the body;
    a project the viewer may not see answers 404 (its existence is not leaked);
  * `project` is a registered subject kind.

Route handlers (main.py): projects_list(request), projects_create(body, request),
project_detail(project_id, request), project_update(project_id, body, request),
project_set_state(project_id, body, request).

Run from chauffeur/:  python tests/test_projects.py
"""
from fastapi import HTTPException

from harness import check  # noqa: F401
from services import storage, subjects
from test_subjects import _fresh as _fresh_subjects, MOM, DAD, AUNT, KID
from test_subject_audience import _as


def _fresh():
    _fresh_subjects()
    storage.projects_table.truncate()


def _p():
    from services import projects
    return projects


def _make(owner, actor, **fields):
    res = _p().create({'title': fields.pop('title', 'Learn Portuguese'), 'goal': 'hold a conversation',
                       'done_when': 'order dinner in Lisbon in Portuguese', 'owner_member_id': owner, **fields}, dict(actor))
    check(res['status'] == 'success', f"created: {res}")
    return res['project']


def scenario_create_by_hand_with_defaults():
    _fresh()
    p = _make('mom', MOM)
    check(p['audience'] == 'private' and p['state'] == 'active' and p['created_by'] == 'mom' and p['steps'] == []
          and p['pieces'] == [] and p['body_goal'] is False, f"an adult's project defaults to private: {p}")
    k = _make('kid', MOM, title='Learn to ride a bike')
    check(k['audience'] == 'parents', f"a child's project defaults to parents: {k}")
    own = _make('kid', KID, title='Learn guitar')
    check(own['owner_member_id'] == 'kid' and own['created_by'] == 'kid', "a child creates their own")
    for actor, owner in ((KID, 'mom'), (AUNT, 'kid'), (AUNT, 'mom')):
        res = _p().create({'title': 'x', 'goal': 'x', 'done_when': 'x', 'owner_member_id': owner}, dict(actor))
        check(res['status'] == 'error', f"{actor['id']} may not create a project for {owner}: {res}")
    check(_p().create({'title': '', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['status'] == 'error',
          "a title is required")


def scenario_who_sees_and_who_acts():
    _fresh()
    private = _make('mom', MOM)
    kids = _make('kid', MOM, title='Learn to ride a bike')
    kid_private = _make('kid', KID, title='Diary club', audience='private')
    house = _make('mom', MOM, title='Garage clear-out', audience='household')
    can_see, can_act = _p().can_see, _p().can_act
    check([can_see(private, m) for m in (MOM, DAD, AUNT, KID)] == [True, False, False, False], "private: the owner only")
    check([can_see(kids, m) for m in (MOM, DAD, AUNT, KID)] == [True, True, False, True], "a child's: the child and the parents")
    check(can_see(kid_private, MOM) and can_see(kid_private, DAD), "a child's project is never private from their parents")
    check(all(can_see(house, m) for m in (MOM, DAD, AUNT, KID)), "household: everyone")
    check(can_act(kids, KID) and can_act(kids, MOM) and not can_act(kids, AUNT), "the owner and a parent act on a child's")
    check(can_act(house, AUNT) and not can_act(house, KID), "an adult who can see it acts; a child only on their own")


def scenario_lifecycle_taps():
    _fresh()
    p = _make('mom', MOM, audience='household')
    for state in ('paused', 'active', 'done', 'active', 'dropped'):
        res = _p().set_state(p['id'], state, dict(MOM))
        check(res['status'] == 'success' and storage.get_project(p['id'])['state'] == state, f"{state}: {res}")
    check(_p().set_state(p['id'], 'exploded', dict(MOM))['status'] == 'error', "an unknown state is refused")
    check(_p().set_state(p['id'], 'paused', dict(KID))['status'] == 'error', "a child may not change another's project")
    res = _p().update(p['id'], {'title': 'Garage, finally'}, dict(DAD))
    check(res['status'] == 'success' and storage.get_project(p['id'])['title'] == 'Garage, finally'
          and storage.get_project(p['id'])['rev'] > p['rev'], f"an adult who can act edits it: {res}")


def scenario_the_view_is_the_viewers():
    _fresh()
    p = _make('mom', MOM, audience='household')
    v = _p().view(storage.get_project(p['id']), dict(KID))
    for key in ('id', 'title', 'goal', 'done_when', 'owner_member_id', 'audience', 'state', 'target_date',
                'steps', 'pieces', 'next_step', 'steps_done', 'steps_total'):
        check(key in v, f"the view carries {key}: {sorted(v)}")
    check(v['steps_done'] == 0 and v['steps_total'] == 0 and v['next_step'] is None, "an empty checklist")


def scenario_routes_act_as_the_signed_in_member():
    _fresh()
    import main
    mine = _make('mom', MOM)
    listed = main.projects_list(request=_as('dad'))
    check(mine['id'] not in [x['id'] for x in listed['projects']], "Dad's list omits Mom's private project")
    try:
        main.project_detail(mine['id'], request=_as('dad'))
        check(False, "Dad cannot read it")
    except HTTPException as e:
        check(e.status_code == 404, f"a hidden project answers 404, not 403: {e.status_code}")
    try:
        main.project_update(mine['id'], {'title': 'hijacked', 'member_id': 'mom'}, request=_as('dad'))
        check(False, "a member_id in the body never acts")
    except HTTPException as e:
        check(e.status_code in (403, 404), f"refused: {e.status_code}")
    check(storage.get_project(mine['id'])['title'] == 'Learn Portuguese', "nothing changed")
    made = main.projects_create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it',
                                 'owner_member_id': 'dad'}, request=_as('dad'))
    check(made['project']['created_by'] == 'dad', f"created as the signed-in member: {made}")
    out = main.project_set_state(made['project']['id'], {'state': 'paused'}, request=_as('dad'))
    check(out['status'] == 'success', f"state by route: {out}")
    check(main.project_detail(made['project']['id'], request=_as('dad'))['project']['state'] == 'paused', "read back")


def scenario_project_is_a_subject_kind():
    _fresh()
    p = _make('kid', MOM, title='Learn to ride a bike')
    check('project' in subjects.KINDS, "registered")
    row = subjects.load('project', p['id'])
    check(row and subjects.title_of('project', row) == 'Learn to ride a bike', "loads and titles")
    check(subjects.visible('project', row, MOM) and not subjects.visible('project', row, AUNT), "its audience")
    check(subjects.visible('project', row, MOM, spoken=True) is False, "a parents project is never spoken")
    ctx = subjects.context('project', p['id'], MOM) or ''
    check('Learn to ride a bike' in ctx and 'hold a conversation' in ctx, f"context carries the goal: {ctx}")
    check(subjects.context('project', p['id'], AUNT) is None, "not past its audience")
    check(subjects.link('project', p['id']) == f"projects?id={p['id']}", subjects.link('project', p['id']))


SCENARIOS = [
    scenario_create_by_hand_with_defaults,
    scenario_who_sees_and_who_acts,
    scenario_lifecycle_taps,
    scenario_the_view_is_the_viewers,
    scenario_routes_act_as_the_signed_in_member,
    scenario_project_is_a_subject_kind,
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
