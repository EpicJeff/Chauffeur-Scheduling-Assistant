"""Mission endpoints: role gates, launch, answer resumes, approve rides the rail."""
from harness import check
from services import storage, missions


def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    storage.members_table.truncate()
    storage.threads_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import datetime as _dt
    storage.set_app_state(f"mission_calls:{_dt.date.today().isoformat()}", {})
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P'}


class _TokenReq:
    """What auth.acting_member actually reads (mirrors test_study_state.py's
    sibling gate scenario) — driven through the real token path rather than
    a stubbed resolver, since a stub only proves it returns what it's told."""
    def __init__(self, token):
        self.headers = {'x-member-token': token}
        self.query_params = {}


def _as(member_id):
    return _TokenReq(storage.create_member_token(member_id))


def scenario_child_cannot_launch():
    _reset()
    import main
    from fastapi import HTTPException
    try:
        main.missions_launch(body={'goal': 'x', 'member_id': 'kid'}, request=None)
        check(False, "child launch must raise")
    except HTTPException as e:
        check(e.status_code == 403, "child refused with 403")


def scenario_parent_launches_and_answers():
    _reset()
    import main
    res = main.missions_launch(body={'goal': 'plan picnic', 'member_id': 'mom'},
                               request=None)
    check(res['status'] == 'launched', "parent launches")
    mid = res['mission_id']
    storage.update_mission(mid, {'status': 'waiting_user'})
    out = main.missions_answer(mid, body={'text': 'budget is $50',
                                          'member_id': 'mom'}, request=None)
    row = storage.get_mission(mid)
    check(row['status'] == 'running', "an answer resumes the mission")
    notes = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'note']
    check(any('$50' in str(s.get('result_json')) for s in notes),
          "the answer lands on the transcript")


def scenario_admin_payload_shape():
    _reset()
    import main
    mid = missions.launch('g', created_by='mom')['mission_id']
    out = main.missions_admin(request=_as('mom'))
    check(out['active'][0]['id'] == mid and 'steps' in out['active'][0],
          "active missions arrive with their transcript")
    check('history' in out, "history lane present")


def scenario_admin_refuses_a_child():
    """Review finding: GET /api/missions/admin sits under a bare SIGNED_IN
    route rule (`/api/missions/*`), same shape as `/api/study/state` — any
    signed-in member, a child included, could read every mission's full
    transcript. The role decision has to live in the handler via
    `_mind_actor`, exactly as `study_state` does."""
    _reset()
    import main
    from fastapi import HTTPException
    mid = missions.launch('g', created_by='mom')['mission_id']
    try:
        main.missions_admin(request=_as('kid'))
        check(False, "a signed-in child must not read the missions admin lane")
    except HTTPException as e:
        check(e.status_code == 403, f"403 for a child, got {e.status_code}")
    out = main.missions_admin(request=_as('mom'))
    check(out['active'][0]['id'] == mid,
          "the same door still opens for a signed-in parent")


def scenario_proposal_act_requires_a_real_mission():
    """Review finding: the route wrote its transcript note unconditionally,
    with no check that mission_id names anything real — matching the 404
    guard the answer/drop/ack routes already carry."""
    _reset()
    import main
    from fastapi import HTTPException
    try:
        main.missions_proposal_act('no-such-mission', 'no-such-proposal',
                                   body={'member_id': 'mom', 'act': 'approve'},
                                   request=None)
        check(False, "acting on a nonexistent mission must raise")
    except HTTPException as e:
        check(e.status_code == 404, f"404 for a missing mission, got {e.status_code}")


def scenario_ack_and_drop():
    _reset()
    import main
    mid = missions.launch('g', created_by='mom')['mission_id']
    main.missions_drop(mid, body={'member_id': 'mom'}, request=None)
    check(storage.get_mission(mid)['status'] == 'dropped', "drop drops")
    main.missions_ack(mid, body={'member_id': 'mom'}, request=None)
    check(storage.get_mission(mid)['acknowledged_at'], "ack quiets the finding")


def scenario_page_route_serves_template():
    import main, os
    tpl = os.path.join(os.path.dirname(main.__file__), 'templates', 'missions.html')
    check(os.path.exists(tpl), "missions.html exists")
    html = open(tpl, encoding='utf-8').read()
    for needle in ('/api/missions/admin', '/api/missions/launch', 'waiting_user'):
        check(needle in html, f"page wires {needle}")
    for banned in ('alert(', 'confirm(', 'prompt('):
        check(banned not in html, f"no browser dialogs ({banned})")


# --- Task 8: Doorways — thread button and chat tool in both stacks --------

def scenario_chat_tool_wired_into_both_stacks():
    from services import agent_tools, agent_tools_v2
    check('launch_mission' in agent_tools.TOOL_SCHEMAS
          and 'launch_mission' in agent_tools.TOOL_HANDLERS, "v1 wired")
    decls = agent_tools_v2.get_available_tools()   # match the real signature
    check(any(d.get('name') == 'launch_mission' for d in decls), "v2 declared")
    # If get_available_tools takes arguments (settings/actor), pass what its
    # existing callers pass — keep the assertion, adjust only the call.
    import inspect
    src = inspect.getsource(__import__('services.agent_router', fromlist=['x']))
    check('launch_mission' in src, "router dispatches it")


def scenario_chat_launch_respects_allowlist_and_thread_origin():
    _reset()
    from services import agent_tools_v2, threads as _threads
    tid = storage.add_thread({'title': 'Pool guy', 'goal': 'get him back',
                              'kind': 'vendor', 'state': 'open'})
    res = agent_tools_v2.launch_mission('get the pool serviced', 'Pool guy',
                                        {'id': 'mom', 'role': 'parent'})
    check(res.get('status') == 'launched', f"parent launches via chat, got {res}")
    row = storage.get_mission(res['mission_id'])
    check(row['origin_kind'] == 'thread' and row['origin_ref'] == tid,
          "fuzzy thread title pins the origin")
    res2 = agent_tools_v2.launch_mission('x', None, {'id': 'kid', 'role': 'child'})
    check(res2.get('status') != 'launched', "child refused")
    res3 = agent_tools_v2.launch_mission('x', None, None)
    check(res3.get('status') != 'launched', "anonymous wall refused (allowlist)")


def scenario_threads_page_has_the_button():
    import main, os
    tpl = os.path.join(os.path.dirname(main.__file__), 'templates', 'threads.html')
    html = open(tpl, encoding='utf-8').read()
    check('/api/missions/launch' in html, "Work-this button posts a launch")


if __name__ == '__main__':
    scenario_child_cannot_launch()
    scenario_parent_launches_and_answers()
    scenario_admin_payload_shape()
    scenario_admin_refuses_a_child()
    scenario_proposal_act_requires_a_real_mission()
    scenario_ack_and_drop()
    scenario_page_route_serves_template()
    scenario_chat_tool_wired_into_both_stacks()
    scenario_chat_launch_respects_allowlist_and_thread_origin()
    scenario_threads_page_has_the_button()
    print("test_missions_endpoints OK")
