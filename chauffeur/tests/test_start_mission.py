"""'Get the dishwasher fixed': one tool opens the thread and the mission and
holds the thread as focus. Spec 2026-10-10 browse missions §4."""
from harness import check  # noqa: F401
from services import storage, threads, missions, triage, situations, agent_tools_v2 as tools, agent_router

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child'}


def _reset():
    for t in (storage.threads_table, storage.missions_table, storage.mission_steps_table, storage.members_table,
              storage.app_state_table, storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7}
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def scenario_opens_thread_and_mission_and_focus():
    _reset()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    check(res['status'] == 'success' and res['thread_id'] and res['mission_id'], f"opened: {res}")
    t = storage.get_thread(res['thread_id'])
    check(t['title'] == 'get the dishwasher fixed' and t['owner_member_id'] == 'mom' and t['goal'] == 'get the dishwasher fixed', f"the thread: {t}")
    m = storage.get_mission(res['mission_id'])
    check(m['origin_kind'] == 'thread' and m['origin_ref'] == res['thread_id'] and m['created_by'] == 'mom' and m['status'] == 'running', f"the mission: {m}")
    f = triage.get_focus('voice:1')
    check(f and f['kind'] == 'thread' and f['id'] == res['thread_id'], "the thread is the focus")
    check(res['message'].startswith('On it.'), f"the reply: {res['message']}")
    res = tools.start_mission_for('fix the fence', title='Back fence', acting_member=MOM, focus_key='voice:1')
    check(storage.get_thread(res['thread_id'])['title'] == 'Back fence', "a given title is used")


def scenario_a_running_mission_is_not_duplicated():
    _reset()
    first = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    again = tools.start_mission_for('get the dishwasher fixed please', acting_member=MOM, focus_key='voice:2')
    check(again['status'] == 'success' and again.get('mission_id') == first['mission_id'] and 'already' in again['message'].lower(), f"named, not duplicated: {again}")
    check(len(storage.get_missions()) == 1 and len(storage.get_threads()) == 1, "one of each")
    check(triage.get_focus('voice:2')['id'] == first['thread_id'], "the second conversation's focus is the same thread")


def scenario_gates():
    _reset()
    check(tools.start_mission_for('x', acting_member=KID)['status'] == 'error', "a child is refused")
    check(tools.start_mission_for('x', acting_member=None)['status'] == 'error', "no actor is refused")
    storage.get_settings = lambda: {'missions_enabled': False, 'thread_stall_days': 7}
    res = tools.start_mission_for('x', acting_member=MOM)
    check(res['status'] == 'error' and 'off' in res['message'].lower() and not storage.get_threads(), "missions off: no thread opened either")


def scenario_declared_dispatched_terminal():
    decl = {t['name'] for t in tools.get_available_tools()}
    check('start_mission_for' in decl and 'start_mission_for' in tools.TOOL_HANDLERS and 'start_mission_for' in tools.TOOL_SCHEMAS, "registry")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"start_mission_for"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal")
    _reset()
    orig = agent_router.call_gemma_with_fallback
    n = {'i': 0}

    def fake(prompt, tools_, system):
        n['i'] += 1
        return {'tool_calls': [{'name': 'start_mission_for', 'arguments': {'goal': 'get the dishwasher fixed'}}], 'message': ''} if n['i'] == 1 else {'tool_calls': [], 'message': ''}
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request('get the dishwasher fixed', focus_key='voice:9')
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(res['message'].startswith('On it.') and storage.get_missions()[0]['created_by'] == 'mom', f"voice opens it as the parent of record: {res}")


SCENARIOS = [scenario_opens_thread_and_mission_and_focus, scenario_a_running_mission_is_not_duplicated, scenario_gates,
             scenario_declared_dispatched_terminal]

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
