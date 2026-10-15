"""Pieces and Argyle's project tools (Projects core spec §1 "Pieces", §4 "Argyle"),
Task 8.

  * `projects.add_piece(project_id, kind, sid, actor)` / `remove_piece(...)`:
    only onto a project the actor can act on, and only a record the actor may
    see; no duplicates; the view lists only pieces the viewer may see; a
    deleted record is left out and the project still loads;
  * "Part of": `GET /api/subjects/{kind}/{sid}/projects` (main.subject_projects)
    lists the projects holding that record that the viewer may see;
  * routes: POST /api/projects/{id}/pieces (main.project_add_piece) and
    POST /api/projects/{id}/pieces/remove (main.project_remove_piece), body {kind, id};
  * tools: `list_projects`, `get_project` (reads, through `projects.can_see`, and
    in a channel through `situations.channel_visible`); `add_project_step`,
    `add_to_project`, `set_project_state`, `set_step_state` (writes, with the
    tap's checks) — reachable through `execute_tool` and the chat router;
    registered and declared (registry parity holds).

Run from chauffeur/:  python tests/test_projects_tools.py
"""
from fastapi import HTTPException

from harness import check  # noqa: F401
from services import storage
from services import agent_tools_v2 as tools
from test_projects import _fresh, _p, _make
from test_subjects import MOM, DAD, AUNT, KID
from test_subject_audience import _as


def scenario_pieces_by_hand():
    _fresh()
    house = _make('mom', MOM, audience='household', title='Garage')
    check(_p().add_piece(house['id'], 'list', 'l1', dict(MOM))['status'] == 'success', "Mom attaches the groceries list")
    check(_p().add_piece(house['id'], 'list', 'l1', dict(MOM))['status'] == 'success'
          and len(storage.get_project(house['id'])['pieces']) == 1, "no duplicate")
    check(_p().add_piece(house['id'], 'list', 'l2', dict(AUNT))['status'] == 'error', "nobody attaches a record they cannot see")
    check(_p().add_piece(house['id'], 'list', 'l1', dict(KID))['status'] == 'error', "nor onto a project they cannot act on")
    check(_p().add_piece(house['id'], 'list', 'l2', dict(MOM))['status'] == 'success', "Mom attaches the private gift list")
    mine = [x['id'] for x in _p().view(storage.get_project(house['id']), dict(MOM))['pieces']]
    dads = [x['id'] for x in _p().view(storage.get_project(house['id']), dict(DAD))['pieces']]
    check(set(mine) == {'l1', 'l2'} and dads == ['l1'], f"each sees only what they may: mom {mine}, dad {dads}")
    check(_p().remove_piece(house['id'], 'list', 'l2', dict(MOM))['status'] == 'success'
          and [x['id'] for x in storage.get_project(house['id'])['pieces']] == ['l1'], "removed")


def scenario_a_deleted_piece_is_left_out():
    _fresh()
    p = _make('mom', MOM, audience='household', title='Garage')
    _p().add_piece(p['id'], 'list', 'l1', dict(MOM))
    storage.delete_shopping_list('l1')
    v = _p().view(storage.get_project(p['id']), dict(MOM))
    check(v['pieces'] == [] and v['title'] == 'Garage', f"left out, the project loads: {v['pieces']}")


def scenario_part_of_and_the_routes():
    _fresh()
    import main
    private = _make('mom', MOM, title='Learn Portuguese')
    main.project_add_piece(private['id'], {'kind': 'list', 'id': 'l1'}, request=_as('mom'))
    check(storage.get_project(private['id'])['pieces'][0]['id'] == 'l1', "attached by route")
    part = main.subject_projects('list', 'l1', request=_as('mom'))
    check([x['title'] for x in part['projects']] == ['Learn Portuguese'], f"Part of, for Mom: {part}")
    check(main.subject_projects('list', 'l1', request=_as('dad'))['projects'] == [], "nothing for Dad: the project is private")
    try:
        main.project_add_piece(private['id'], {'kind': 'list', 'id': 'l1'}, request=_as('dad'))
        check(False, "Dad cannot attach to Mom's private project")
    except HTTPException as e:
        check(e.status_code == 404, f"404: {e.status_code}")
    main.project_remove_piece(private['id'], {'kind': 'list', 'id': 'l1'}, request=_as('mom'))
    check(storage.get_project(private['id'])['pieces'] == [], "removed by route")


def scenario_tools_through_execute_tool():
    _fresh()
    p = _make('mom', MOM, audience='household', title='Bathroom')
    listed = tools.execute_tool('list_projects', {}, actor=dict(MOM))
    check(listed['status'] == 'success' and 'Bathroom' in listed['message'], f"list: {listed}")
    added = tools.execute_tool('add_project_step', {'project_id': p['id'], 'title': 'Demo the old tile', 'owner': 'mom'}, actor=dict(MOM))
    check(added['status'] == 'success', f"step added: {added}")
    got = tools.execute_tool('get_project', {'project_id': p['id']}, actor=dict(MOM))
    sid = got['project']['steps'][0]['id']
    check('Demo the old tile' in got['message'] and sid in got['message'], f"get shows steps with their ids: {got['message']}")
    check(tools.execute_tool('set_step_state', {'project_id': p['id'], 'step_id': sid, 'state': 'done'}, actor=dict(KID))['status'] == 'error',
          "a child cannot tick Mom's step by words either")
    done = tools.execute_tool('set_step_state', {'project_id': p['id'], 'step_id': sid, 'state': 'done'}, actor=dict(MOM))
    check(done['status'] == 'success' and storage.get_project(p['id'])['steps'][0]['state'] == 'done', f"ticked: {done}")
    check(tools.execute_tool('add_to_project', {'project_id': p['id'], 'kind': 'list', 'id': 'l1'}, actor=dict(MOM))['status'] == 'success',
          "attach by tool")
    check(tools.execute_tool('set_project_state', {'project_id': p['id'], 'state': 'paused'}, actor=dict(MOM))['status'] == 'success'
          and storage.get_project(p['id'])['state'] == 'paused', "pause by tool")
    secret = _make('mom', MOM, title='Get down to 185 lbs')
    check('185' not in tools.execute_tool('list_projects', {}, actor=dict(DAD))['message'], "Dad's list omits Mom's private goal")
    check(tools.execute_tool('get_project', {'project_id': secret['id']}, actor=dict(DAD))['status'] == 'error', "and get refuses it")


def scenario_tools_through_the_router():
    _fresh()
    from services import agent_router
    p = _make('mom', MOM, audience='household', title='Bathroom')
    sid = _p().add_step(p['id'], {'title': 'Demo the old tile', 'owner': 'mom'}, dict(MOM))['step']['id']
    replies = [{'tool_calls': [{'name': 'set_step_state', 'arguments': {'project_id': p['id'], 'step_id': sid, 'state': 'done'}}]},
               {'message': 'Ticked.', 'tool_calls': []}]
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda *a, **k: replies.pop(0)
    try:
        agent_router.process_agent_request('tick off demo', source='family', acting_member=dict(MOM), focus_key='conv:proj')
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(storage.get_project(p['id'])['steps'][0]['state'] == 'done', "'tick off demo' through the router")
    kids = _make('kid', MOM, title='Learn to ride a bike')
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    seen = []
    replies = [{'tool_calls': [{'name': 'list_projects', 'arguments': {}}]}, {'message': 'ok', 'tool_calls': []}]
    agent_router.call_gemma_with_fallback = lambda *a, **k: seen.append(repr(a) + repr(k)) or replies.pop(0)
    try:
        agent_router.process_agent_request('what projects are going?', source='family', acting_member=dict(MOM),
                                           focus_key=f"channel:{mixed['id']}")
    finally:
        agent_router.call_gemma_with_fallback = orig
    blob = ''.join(seen)
    check(len(seen) == 2 and 'Bathroom' in blob and 'ride a bike' not in blob,
          f"in a channel with the aunt, the kid's parents-only project is left out: {len(seen)} calls")


SCENARIOS = [
    scenario_pieces_by_hand,
    scenario_a_deleted_piece_is_left_out,
    scenario_part_of_and_the_routes,
    scenario_tools_through_execute_tool,
    scenario_tools_through_the_router,
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
