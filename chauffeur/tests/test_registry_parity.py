"""Registry parity (planned missions spec §2, Codex H1 and H2).

Every tool Argyle may use in chat is reachable from the registry missions use,
with the same actor rules chat uses, and nothing more is opened anywhere else.

Pinned here (Task 1):

  * every tool `get_available_tools()` declares has a registry handler, except
    a named list where each exception says why (private DMs, room speech, the
    voice controller, chat's own proposal wrapper, research that missions do
    through their `research` action, and chat tools whose registry equivalent
    is a differently named write);
  * the new reads are mission READ tools; the new writes are proposable and
    never READ tools;
  * a handler never takes its actor from the model's arguments: a registry
    call passes `actor=` and the handler uses it;
  * a mission's READ runs as the transcript's audience, never as a person: an
    unbound mission as the id-less adult, a parents-only-bound one as the
    id-less parent;
  * an approved write runs as the approving parent (not the parent of record);
  * nothing else opens: the Mind's propose-only rail still refuses
    draft_thread_message and propose_program, and the satellite still refuses
    every tool outside voice_tools.TOOLS.

Run from chauffeur/:  python tests/test_registry_parity.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations
from services import agent_tools_v2 as tools
from test_mission_subject import _fresh, _plan, _mission, _step, _steps, _thread
from test_subjects import MOM, DAD, AUNT

NEW_READS = {'get_calendar_events', 'get_household_tasks', 'get_household_load', 'get_requests',
             'get_assist_coverage', 'list_threads', 'program_progress'}
NEW_WRITES = {'add_household_task', 'claim_household_task', 'complete_household_task', 'add_thread_note',
              'close_thread', 'update_thread_action', 'draft_thread_message', 'answer_request', 'make_request',
              'ask_deal', 'cover_with_assist', 'clear_trip_itinerary', 'manage_trip_flights', 'manage_trip_rules',
              'log_program_session', 'propose_program'}


def scenario_every_declared_tool_has_a_registry_handler_or_a_reason():
    _fresh()
    declared = {t['name'] for t in tools.get_available_tools()}
    exceptions = getattr(tools, 'REGISTRY_EXCEPTIONS', None)
    check(isinstance(exceptions, dict) and all(isinstance(v, str) and v.strip() for v in exceptions.values()),
          "a named exception list, each with its reason in words")
    check({'send_direct_message', 'announce_to_room', 'prepare_voice_approval'} <= set(exceptions),
          f"the spec's three are there: {sorted(exceptions)}")
    missing = declared - set(tools.TOOL_HANDLERS) - set(exceptions)
    check(not missing, f"every declared tool reaches the registry: missing {sorted(missing)}")
    stray = set(exceptions) & set(tools.TOOL_HANDLERS)
    check(not stray, f"an exception is not also registered: {sorted(stray)}")
    for name in NEW_READS | NEW_WRITES:
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} registered with a schema")


def scenario_reads_are_reads_and_writes_are_proposals():
    _fresh()
    check(NEW_READS <= missions.READ_TOOLS, f"reads join the planner's READ list: {sorted(NEW_READS - missions.READ_TOOLS)}")
    prop = missions.proposable_tools()
    check(NEW_WRITES <= prop, f"writes are proposable: {sorted(NEW_WRITES - prop)}")
    check(not (NEW_WRITES & missions.READ_TOOLS), "and never READ tools")


def scenario_a_handler_never_takes_its_actor_from_the_model():
    _fresh()
    hidden = _thread('Kate surprise party', subject_kind='occasion', subject_id='o1', subject_rev=1)
    out = tools.execute_tool('list_threads', {'acting_member': dict(MOM), 'include_closed': True},
                             actor={'id': None, 'role': 'adult'})
    check('surprise' not in (out.get('message') or ''), f"the model's acting_member is ignored; the caller's actor is used: {out}")
    out = tools.execute_tool('list_threads', {'include_closed': True}, actor=dict(MOM))
    check('surprise' in (out.get('message') or ''), f"a parent actor sees it: {out}")


def scenario_a_missions_reads_run_as_its_audience_never_a_person():
    _fresh()
    _thread('Kate surprise party', subject_kind='occasion', subject_id='o1', subject_rev=1)
    _thread('Gift for Kate', subject_kind='list', subject_id='l2', subject_rev=1)
    check(missions.read_viewer(storage.get_mission(_mission(created_by='mom'))) == {'id': None, 'role': 'adult'},
          "an unbound mission reads as any adult")
    bound = _mission(created_by='mom', subject_kind='occasion', subject_id='o1', subject_rev=1)
    check(missions.read_viewer(storage.get_mission(bound)) == {'id': None, 'role': 'parent'},
          "a mission about a parents-only occasion reads as any parent")
    house = _mission(created_by='mom', subject_kind='occasion', subject_id='o2', subject_rev=1)
    check(missions.read_viewer(storage.get_mission(house)) == {'id': None, 'role': 'adult'}, "a household subject reads as any adult")
    mid = _mission(created_by='mom')
    _plan({'action': 'tool', 'tool': 'list_threads', 'args': {}}, {'action': 'ask_user', 'question': 'ok?'})
    _step(mid)
    stored = repr(_steps(mid, 'list_threads')[0]['result_json'])
    check('surprise' not in stored and 'Gift for Kate' not in stored,
          f"an unbound mission's read stores nothing an adult may not read: {stored[:300]}")
    _plan({'action': 'tool', 'tool': 'list_threads', 'args': {}}, {'action': 'ask_user', 'question': 'ok?'})
    _step(bound)
    stored = repr(_steps(bound, 'list_threads')[0]['result_json'])
    check('surprise' in stored, f"the parents-bound mission reads the parents' thread: {stored[:300]}")
    check('Gift for Kate' not in stored, "never a thread about a list private to a named person")


def scenario_an_approved_write_runs_as_the_approver():
    _fresh()
    from services import chat_actions
    mid = _mission(created_by='mom')
    _plan({'action': 'propose', 'tool': 'add_household_task', 'args': {'title': 'Renew the passports'},
           'summary': 'Add a task: renew the passports', 'why': 'trip'})
    _step(mid)
    prop = [s for s in _steps(mid) if s['kind'] == 'proposal']
    check(prop and prop[0]['result_json'].get('proposal_id'), f"proposed: {[s['name'] for s in _steps(mid)]}")
    res = chat_actions.act_on_proposal(prop[0]['result_json']['proposal_id'], 'approve', dict(DAD))
    check(res['status'] == 'success', f"approved: {res}")
    rows = [t for t in storage.get_household_tasks(include_done=True) if t.get('title') == 'Renew the passports']
    check(rows and rows[0].get('created_by') == 'dad', f"written as the parent who approved it, not the parent of record: {rows}")


def scenario_nothing_else_opens():
    _fresh()
    from services import agent_router, voice_tools
    from services import voice_identity as voice
    for name in ('draft_thread_message', 'propose_program'):
        check(name not in agent_router.PROPOSE_ONLY_TOOLS, f"{name} stays off the Mind's propose-only rail")
    calls = [{'name': 'draft_thread_message', 'arguments': {'thread_title': 'Pest control'}},
             {'name': 'propose_program', 'arguments': {'title': 'Piano'}}]
    replies = [{'message': '', 'tool_calls': calls}, {'message': 'done', 'tool_calls': []}]
    ran = []
    orig = {n: getattr(tools, n) for n in ('draft_thread_message', 'propose_program')}
    for n in orig:
        setattr(tools, n, (lambda name: (lambda *a, **k: ran.append(name) or {'status': 'success'}))(n))
    orig_call = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = lambda prompt, tools_, system_prompt: replies.pop(0) if replies else {'message': 'ok', 'tool_calls': []}
    try:
        agent_router.process_agent_request('handle it', source='admin', acting_member=dict(MOM), propose_only=True)
    finally:
        agent_router.call_gemma_with_fallback = orig_call
        for n, f in orig.items():
            setattr(tools, n, f)
    check(ran == [], f"the Mind's bind rail ran neither: {ran}")
    ctx = voice.VoiceContext('ha', 'assist_satellite.kitchen', 'r', 'g', service_revision=voice._revision(), paired=True)
    out = voice_tools.dispatch('propose_program', {'title': 'Piano'}, ctx)
    check(out.get('status') == 'refused', f"the satellite still refuses what it refused: {out}")


SCENARIOS = [
    scenario_every_declared_tool_has_a_registry_handler_or_a_reason,
    scenario_reads_are_reads_and_writes_are_proposals,
    scenario_a_handler_never_takes_its_actor_from_the_model,
    scenario_a_missions_reads_run_as_its_audience_never_a_person,
    scenario_an_approved_write_runs_as_the_approver,
    scenario_nothing_else_opens,
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
