"""The router routes goals to start_project and nothing else (front door §1, Task 4).

Run from chauffeur/:  python tests/test_front_door_router.py
"""
from harness import check  # noqa: F401
from services import storage, agent_router, voice_tools
from services import agent_tools_v2 as tools
from test_front_door_chat import _fresh
from test_subjects import MOM


def _route(text, reply_tool, args, **kw):
    """One model round that calls `reply_tool`, then a concluding round."""
    orig = agent_router.call_gemma_with_fallback
    seen = {}

    def fake(prompt, tools_, system):
        seen.setdefault('declared', {t['name'] for t in tools_})
        seen.setdefault('system', system)
        if 'n' in seen:
            return {'tool_calls': [], 'message': 'done'}
        seen['n'] = 1
        return {'tool_calls': [{'name': reply_tool, 'arguments': args}], 'message': ''}
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request(text, **kw)
    finally:
        agent_router.call_gemma_with_fallback = orig
    return res, seen


def scenario_the_declared_set():
    declared = {t['name'] for t in tools.get_available_tools()}
    check('start_project' in declared, "start_project is declared to chat")
    for name in ('start_mission_for', 'propose_program', 'create_thread'):
        check(name not in declared, f"{name} left the chat declaration")
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} still reaches the registry for plans")
    check('start_project' in tools.TOOL_HANDLERS and 'start_project' in tools.TOOL_SCHEMAS, "registered")
    desc = next(t for t in tools.get_available_tools() if t['name'] == 'start_project')['description']
    for phrase in ('learn', 'fixed', 'pricing', 'enter'):
        check(phrase in desc.lower(), f"the description names the case: {phrase}")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"start_project"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal")
    check('start_mission_for' not in src.split('ARGYLE ACTS IN THE WORLD')[1].split('SHARED SPEAKER')[0],
          "the acts-in-the-world paragraph names start_project, not the old tool")
    check('start_project' in voice_tools.TOOLS and 'start_mission_for' not in voice_tools.TOOLS, "voice allowlist")


def scenario_portuguese_through_the_router():
    _fresh()
    res, seen = _route('I want to learn Brazilian Portuguese', 'start_project', {'goal': 'I want to learn Brazilian Portuguese'},
                       source='pwa', acting_member=dict(MOM), focus_key='channel:dm1')
    check('propose_program' not in seen['declared'] and 'start_project' in seen['declared'], f"the model saw one door: {sorted(seen['declared'])[:5]}")
    rows = storage.get_projects()
    check(len(rows) == 1 and rows[0]['goal'] == 'I want to learn Brazilian Portuguese', f"a project, not a program: {rows}")
    check(res['message'].startswith('Started a project'), f"terminal reply: {res['message']}")


def scenario_a_direct_action_stays_direct():
    _fresh()
    res, seen = _route('assign Grandma to drive Barney to soccer tomorrow', 'propose_family_action',
                       {'summary': 'Assign Grandma to drive Barney to soccer tomorrow', 'action_type': 'reassign_driver', 'payload': {}},
                       source='pwa', acting_member=dict(MOM))
    check(storage.get_projects() == [], "no project for a direct action")
    check('start_project' in seen['system'] and 'propose_family_action' in seen['system'], "the guidance names both doors")


def scenario_voice_starts_a_household_project_as_the_parent_of_record():
    _fresh()
    res, seen = _route('get the dishwasher fixed', 'start_project', {'goal': 'get the dishwasher fixed'}, focus_key='voice:9')
    rows = storage.get_projects()
    check(len(rows) == 1 and rows[0]['audience'] == 'household' and rows[0]['owner_member_id'] == 'mom', f"voice: {rows}")
    check(res['message'].startswith('Started a project'), f"spoken reply: {res['message']}")


SCENARIOS = [scenario_the_declared_set, scenario_portuguese_through_the_router, scenario_a_direct_action_stays_direct,
             scenario_voice_starts_a_household_project_as_the_parent_of_record]

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
    raise SystemExit(1 if failed else 0)
