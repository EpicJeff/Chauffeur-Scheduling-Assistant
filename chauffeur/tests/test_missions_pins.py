"""Structural fences: paid key unreachable outside the pro resolver, mailer
unreachable from missions, the engine runs end-to-end without executing."""
import os
import re
from harness import check
from services import storage, missions


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sources():
    for root, _dirs, files in os.walk(os.path.join(SRC, 'services')):
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(root, f)


def scenario_paid_key_is_read_in_one_place():
    allowed = {'model_pools.py', 'settings_registry.py'}
    offenders = []
    for path in _sources():
        if os.path.basename(path) in allowed:
            continue
        text = open(path, encoding='utf-8').read()
        if 'llm_gemini_paid_api_key' in text:
            offenders.append(os.path.basename(path))
    check(not offenders,
          f"paid key read only via api_key_for_pool, offenders: {offenders}")
    # main.py too — endpoints must not shortcut the resolver
    text = open(os.path.join(SRC, 'main.py'), encoding='utf-8').read()
    check('llm_gemini_paid_api_key' not in text, "main.py never touches the paid key")


def scenario_missions_cannot_reach_the_mailer():
    text = open(os.path.join(SRC, 'services', 'missions.py'), encoding='utf-8').read()
    for banned in ('mailer', 'send_drafted', 'smtplib'):
        check(banned not in text, f"missions.py never references {banned}")


def scenario_mission_tier_never_serves_free_models():
    from services import model_pools
    for m in model_pools.models_for('mission', {}):
        check('pro' in m, f"mission tier serves pro models only, got {m}")


def scenario_end_to_end_runthrough_executes_nothing():
    """RUNS the loop (source-reading tests miss runtime breaks): launch →
    research → read → propose → finish → finding → approve executes exactly
    once, via the rail."""
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    import datetime as _dt
    storage.set_app_state(f"mission_calls:{_dt.date.today().isoformat()}", {})
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P'}
    executed = []
    from services import agent_tools, chat_actions, web
    orig_exec, orig_research = agent_tools.execute_tool, web.research
    agent_tools.execute_tool = lambda n, a: executed.append((n, a)) or {'status': 'ok', 'echo': n}
    web.research = lambda q, read_pages=6: {'status': 'ok', 'answer': 'three vendors',
                                            'facts': [], 'sources': []}
    script = [
        {'action': 'research', 'question': 'magicians near us'},
        {'action': 'tool', 'tool': 'get_current_state', 'args': {}},
        {'action': 'propose', 'tool': 'add_errand',
         'args': {'name': 'call the magician'}, 'summary': 'Call the magician',
         'why': 'top result'},
        {'action': 'finish', 'summary': '1 proposal ready'},
    ]
    missions._llm = lambda m, s, u, st: script.pop(0)
    try:
        mid = missions.launch('book party entertainment', created_by='mom')['mission_id']
        for _ in range(4):
            missions.tick()
        row = storage.get_mission(mid)
        check(row['status'] == 'done', f"mission finished, got {row['status']}")
        reads = [e for e in executed if e[0] == 'get_current_state']
        check(len(reads) == 1 and len(executed) == 1,
              f"only the read executed during the run, got {executed}")
        from services import watchers
        found = [f for f in watchers._mission_states(_dt.datetime.now())
                 if f.subject_id == str(mid)]
        check(found and found[0].kind == 'mission_done', "the finding raised")
        prop_step = [s for s in storage.get_mission_steps(mid)
                     if s['kind'] == 'proposal'][0]
        pid = prop_step['result_json']['proposal_id']
        res = chat_actions.act_on_proposal(pid, 'approve',
                                           {'id': 'mom', 'name': 'Mom', 'role': 'parent'})
        check(res.get('status') == 'success', f"approve rides the rail, got {res}")
        check(len(executed) == 2 and executed[-1][0] == 'add_errand',
              "approval executed the write exactly once")
    finally:
        agent_tools.execute_tool, web.research = orig_exec, orig_research


if __name__ == '__main__':
    scenario_paid_key_is_read_in_one_place()
    scenario_missions_cannot_reach_the_mailer()
    scenario_mission_tier_never_serves_free_models()
    scenario_end_to_end_runthrough_executes_nothing()
    print("test_missions_pins OK")
