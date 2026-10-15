"""Planned missions, whole-branch review fixes (Codex adversarial review of
slice 2, 2026-10-14). Task 14. Each scenario pins one finding:

  1. a work stage cannot write a thread draft on its own: the legacy `draft`
     action is refused while a plan is live (drafts go through a follow-up
     build as `draft_thread_message`);
  2. a thread KEEPER (an adult who owns a thread a parent linked to a
     parents-only record) sees no plan words through the thread card's
     forwarded options;
  3. a keeper's mission projection is an allowlist: the planner's summary,
     status note and error never reach them;
  4. in a channel some member may not see, the situation tools (explain,
     list) carry no plan words into the model's prompt or the reply; in the
     person's own Argyle DM they still explain it;
  5. every action a work stage runs (research here) runs under the budget
     guard, and running out pauses the stage with Carry on;
  6. a flight row cannot point at another trip through its nested fields;
  7. after a restart a person can carry on: the lost row stays uncertain and
     is never re-run, its proposal leaves 'executing', its dependents are
     skipped, untouched rows run on a fresh approval, and the finish names
     the row to check.

Run from chauffeur/:  python tests/test_planned_hardening.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, triage, chat_actions, threads, web, budget_guard
from services import agent_tools_v2 as tools
from test_planned_missions import _fresh, _plan_of, _ask_names, _opts, _staged, ROWS
from test_mission_subject import _plan, _step, _steps, _mission, _thread
from test_subject_audience import _as
from test_subjects import MOM, AUNT

SECRET_Q = 'What is the ring budget?'
SECRET_ROW = 'Order the engraved ring'
STAGES = [{'id': 's1', 'kind': 'build', 'title': 'Buy the surprise gift', 'why': 'x', 'makes': ['the engraved ring']}]


def _secrets(blob):
    return [s for s in (SECRET_Q, SECRET_ROW, 'Buy the surprise gift', 'the engraved ring') if s in blob]


def _planned(mid):
    from services import planned
    _plan({'action': 'interview', 'questions': [{'key': 'ring_budget', 'ask': SECRET_Q, 'kind': 'number'}]})
    _step(mid)
    keys = [q['key'] for q in _plan_of(mid)['questions']]
    planned.answer_plan(mid, {k: (250 if k == 'ring_budget' else 'you_decide') for k in keys}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    check(_plan_of(mid).get('state') == 'proposed', f"the plan waits: {_plan_of(mid)}")
    return mid


def scenario_1_a_work_stage_cannot_draft_on_its_own():
    from test_planned_work import _work_proposed, _go
    mid, _ = _work_proposed()
    _go(mid)
    tid = _thread('Bakery chat')
    before = len(storage.get_thread(tid).get('history') or [])
    drafted = []
    orig = threads.draft_message
    threads.draft_message = lambda thread_id, intent=None, **k: drafted.append(thread_id) or {'status': 'ok', 'body': 'Hi'}
    try:
        _plan({'action': 'draft', 'thread_title': 'Bakery chat', 'intent': 'ask about a cake'})
        _step(mid)
    finally:
        threads.draft_message = orig
    check(not drafted and len(storage.get_thread(tid).get('history') or []) == before,
          f"no draft written outside the follow-up build: {drafted}")
    check(_steps(mid, 'refused'), "the draft is refused with a note")


def scenario_2_a_thread_keeper_sees_no_plan_words():
    _fresh()
    tid = _thread('Ring errand', owner='aunt', subject_kind='occasion', subject_id='o1', subject_rev=1)
    _planned(_mission(created_by='aunt', origin=tid))
    v = situations.view('thread', tid, dict(AUNT))
    check(v is not None and not _secrets(repr(v)), f"the keeper's thread card: {_secrets(repr(v))}")
    check(not [o for o in v.get('options') or [] if o['verb'] in ('approve_plan', 'run_stage')], "and nothing to approve")
    full = situations.view('thread', tid, dict(MOM))
    check('Buy the surprise gift' in repr(full), "a parent still gets the plan's options on the thread")


def scenario_3_a_keepers_projection_carries_no_summary_note_or_error():
    from test_planned_missions_audience import _planned_by
    _fresh()
    mid = _planned_by('aunt', link=('occasion', 'o1'))
    storage.update_mission(mid, {'summary': f'Done: {SECRET_ROW}', 'status_note': f'Waiting on {SECRET_Q}', 'error': SECRET_ROW})
    import main
    detail = main.missions_detail(mid, request=_as('aunt'))
    check(not _secrets(repr(detail)), f"the keeper's detail: {_secrets(repr(detail))}")
    admin = main.missions_admin(request=_as('aunt'))
    rows = [m for m in (admin.get('active') or []) + (admin.get('history') or []) if m['id'] == mid]
    check(rows and not _secrets(repr(rows)), f"the keeper's admin list: {_secrets(repr(rows))}")
    check(SECRET_ROW in repr(main.missions_detail(mid, request=_as('mom'))), "a parent reads the summary")


def scenario_4_situation_tools_in_a_mixed_channel_carry_no_plan_words():
    _fresh()
    from services import agent_router
    tid = _thread('Kate party planning', subject_kind='occasion', subject_id='o1', subject_rev=1)
    mid = _planned(_mission(created_by='mom', origin=tid))
    mixed = storage.get_or_create_group(['mom', 'aunt'], 'Mom and Jo')
    fk = f"channel:{mixed['id']}"
    for name, args in (('explain_situation', {}), ('list_situations', {}), ('explain_situation', {'ref': 'Kate party planning'})):
        triage.set_focus(fk, 'thread', tid, 'Kate party planning')
        seen, replies = [], [{'tool_calls': [{'name': name, 'arguments': args}]}, {'message': 'ok', 'tool_calls': []}]
        orig = agent_router.call_gemma_with_fallback
        agent_router.call_gemma_with_fallback = lambda *a, **k: seen.append(repr(a) + repr(k)) or replies.pop(0)
        try:
            out = agent_router.process_agent_request('what is going on with it?', source='family', acting_member=dict(MOM), focus_key=fk)
        finally:
            agent_router.call_gemma_with_fallback = orig
        blob = ''.join(seen) + repr(out)
        check(len(seen) == 2, f"{name} ran and its result went back to the model: {len(seen)} calls")
        check(not _secrets(blob), f"{name} in a channel the party excludes someone from: {_secrets(blob)}")
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')
    triage.set_focus(f"channel:{dm['id']}", 'mission', mid, 'Plan')
    res = tools.explain_situation(acting_member=dict(MOM), focus_key=f"channel:{dm['id']}")
    check(res['status'] == 'success' and 'Buy the surprise gift' in res['message'], f"her own Argyle DM still explains it: {res}")


def scenario_5_a_work_stage_action_runs_under_the_budget_guard():
    from test_planned_work import _work_proposed, _go, _work
    mid, _ = _work_proposed()
    _go(mid)
    seen = []

    def research(question, read_pages=None, api_key=None):
        seen.append(budget_guard.active())
        if budget_guard.active():
            raise budget_guard.BudgetExhausted("the day's limit")
        return {'status': 'success', 'answer': 'Two bakeries', 'facts': [], 'sources': []}
    orig = web.research
    web.research = research
    try:
        _plan({'action': 'research', 'question': 'bakeries near home'})
        _step(mid)
    finally:
        web.research = orig
    check(seen == [True], f"research inside a work stage runs under the guard: {seen}")
    st = _work(mid)
    check(st['state'] == 'partial', f"running out pauses the stage: {st}")
    check(storage.get_mission(mid)['status'] == 'waiting_user' and 'Carry on' in [o['label'] for o in _opts(mid, 'run_stage')],
          f"with Carry on: {[o['label'] for o in _opts(mid, 'run_stage')]}")


def scenario_6_a_flight_row_cannot_point_at_another_trip():
    from services import planned
    _fresh()
    storage.set_trip_metadata('ev_other', {'event_id': 'ev_other', 'pois': [], 'accommodations': [],
                                           'flights': [{'id': 'f1', 'flight_number': 'DL100', 'origin': 'ATL', 'destination': 'MCO'}]})
    args = {'trip_id': 'ev_disney', 'action': 'delete', 'flight': {'event_id': 'ev_other', 'flight_id': 'f1'}}
    check(planned.check_row({'id': 'r1', 'tool': 'manage_trip_flights', 'args': args, 'summary': 'x'}),
          "a nested trip id is refused at proposal")
    tools.execute_tool('manage_trip_flights', args, actor=dict(MOM))
    check(len(storage.get_trip_metadata('ev_other')['flights']) == 1, "and the handler never touches the other trip")


def scenario_7_after_a_restart_a_person_can_carry_on():
    from services import planned
    _fresh()
    rows = ROWS + [{'id': 'r3', 'tool': 'draft_message', 'args': {'to': 'Grandma', 'words': 'Save the date'}, 'summary': 'Tell Grandma'}]
    mid, st = _staged(rows)
    plan = _plan_of(mid)
    plan['stages'][0]['state'] = 'running'
    plan['stages'][0]['rows'][0]['state'] = 'running'
    pid = plan['stages'][0]['rows'][0]['proposal_id']
    storage.update_mission(mid, {'plan': plan, 'status': 'running'})
    storage.update_action_proposal(pid, {'status': 'executing'})
    planned.reconcile()
    labels = {o['label']: o for o in _opts(mid, 'run_stage')}
    check({'Carry on', 'Not this one', 'Stop'} <= set(labels), f"the check offers a way on: {sorted(labels)}")
    check(storage.get_action_proposal(pid)['status'] != 'executing', "the lost claim's proposal is settled")
    ran = []
    orig = chat_actions.run_row
    chat_actions.run_row = lambda proposal_id, actor, idem=None: ran.append(proposal_id) or orig(proposal_id, actor, idem)
    try:
        res = situations.act('mission', mid, 'run_stage', option_id=labels['Carry on']['id'], payload={}, actor=dict(MOM))
        check(res['status'] == 'success', f"carry on: {res}")
        st = _plan_of(mid)['stages'][0]
        check(st['state'] == 'proposed' and _ask_names(mid)[-1] == 'stage', f"the rest waits for a fresh Do this: {st}")
        res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
        check(res['status'] == 'success', f"approved: {res}")
    finally:
        chat_actions.run_row = orig
    st = _plan_of(mid)['stages'][0]
    states = {r['id']: r['state'] for r in st['rows']}
    check(states == {'r1': 'uncertain', 'r2': 'skipped', 'r3': 'done'} and st['state'] == 'done',
          f"the lost row is never re-run, its dependent skipped, the rest done: {states} {st['state']}")
    check(pid not in ran, "the uncertain row never ran again")
    card = missions._done_card(storage.get_mission(mid))
    check(any("Make Kate's 10th birthday" in o for o in card['open']), f"the finish names the row to check: {card['open']}")


SCENARIOS = [
    scenario_1_a_work_stage_cannot_draft_on_its_own,
    scenario_2_a_thread_keeper_sees_no_plan_words,
    scenario_3_a_keepers_projection_carries_no_summary_note_or_error,
    scenario_4_situation_tools_in_a_mixed_channel_carry_no_plan_words,
    scenario_5_a_work_stage_action_runs_under_the_budget_guard,
    scenario_6_a_flight_row_cannot_point_at_another_trip,
    scenario_7_after_a_restart_a_person_can_carry_on,
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
