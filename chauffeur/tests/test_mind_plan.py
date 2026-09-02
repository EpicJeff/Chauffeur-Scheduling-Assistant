"""Make a plan: one heavy call turns an insight into 2-5 ordered steps
(tool|human), each with a due date; the insight moves to in_hand. Nothing
executes here — binding and approval are separate, later, per-step taps."""
import datetime
from harness import check
from services import storage, mind

CALLS = []
NOON = datetime.datetime(2026, 9, 2, 12, 0)


def _fake_pool(payload):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'system': system, 'prompt': prompt})
        return payload
    return f


def _reset():
    CALLS.clear()
    storage.mind_insights_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k',
                                    'mind_enabled': True}


PARENT = {'id': 'mom', 'role': 'parent', 'name': 'Mom'}


def scenario_plan_attaches_and_state_moves():
    _reset()
    iid = storage.add_mind_insight({'slug': 'margin', 'category': 'overload',
                                    'line': 'Margin is narrowing this week',
                                    'approach': 'find outside coverage'})
    mind._pool_call = _fake_pool({'steps': [
        {'kind': 'tool', 'text': 'Research sitter services nearby',
         'due': '2026-09-04'},
        {'kind': 'human', 'text': 'Call the top option', 'owner': 'Dad',
         'due': '2026-09-06'},
    ]})
    res = mind.make_plan(iid, PARENT, now=NOON)
    check(res['status'] == 'planned', f"got {res}")
    steps = res['plan']['steps']
    check(len(steps) == 2, f"two steps, got {len(steps)}")
    check(steps[0]['kind'] == 'tool' and steps[0]['status'] == 'open'
          and steps[0]['proposal_json'] is None, "tool step open, unbound")
    check(steps[1]['owner_member_id'] == 'dad'
          and steps[1]['owner_name'] == 'Dad',
          f"owner resolved by name, got {steps[1]}")
    check(all(s['id'] for s in steps), "every step has an id")
    row = storage.get_mind_insight_by_slug('margin')
    check(row['state'] == 'in_hand', f"state moved, got {row['state']}")
    check(row['plan_json']['steps'][0]['text'] == steps[0]['text'],
          "plan persisted on the row")
    check(CALLS and CALLS[0]['tier'] == 'heavy', "heavy tier")
    check('Margin is narrowing' in CALLS[0]['prompt']
          and 'find outside coverage' in CALLS[0]['prompt'],
          "insight line and approach reach the planner")


def scenario_second_tap_returns_existing_plan():
    res = mind.make_plan(storage.get_mind_insight_by_slug('margin')['id'],
                         PARENT, now=NOON)
    check(res['status'] == 'planned' and len(res['plan']['steps']) == 2,
          f"idempotent, got {res}")
    check(len(CALLS) == 1, "no second planner call")


def scenario_steps_are_clamped_and_defaulted():
    _reset()
    iid = storage.add_mind_insight({'slug': 'c', 'category': 'c', 'line': 'x'})
    mind._pool_call = _fake_pool({'steps': [
        {'kind': 'weird', 'text': 'no kind given', 'due': 'not-a-date'},
        {'kind': 'tool', 'text': ''},                      # dropped: empty
        {'kind': 'human', 'text': 'unknown owner', 'owner': 'Nobody',
         'due': '2026-09-09'},
        {'kind': 'tool', 'text': 's4', 'due': '2026-09-03'},
        {'kind': 'tool', 'text': 's5', 'due': '2026-09-03'},
        {'kind': 'tool', 'text': 's6', 'due': '2026-09-03'},
        {'kind': 'tool', 'text': 's7 over the cap', 'due': '2026-09-03'},
    ]})
    res = mind.make_plan(iid, PARENT, now=NOON)
    steps = res['plan']['steps']
    check(len(steps) == 5, f"clamped to 5 (empty dropped, cap trims), got {len(steps)}")
    check(steps[0]['kind'] == 'human', "unknown kind becomes human (never executes)")
    check(steps[0]['due'] == '2026-09-05',
          f"bad due defaults to today+3, got {steps[0]['due']}")
    check(steps[1]['owner_member_id'] is None
          and steps[1]['owner_name'] == '',
          "unknown owner stays unresolved, never invented")


def scenario_empty_plan_is_honest():
    _reset()
    iid = storage.add_mind_insight({'slug': 'e', 'category': 'c', 'line': 'x'})
    mind._pool_call = _fake_pool({'steps': []})
    res = mind.make_plan(iid, PARENT, now=NOON)
    check(res['status'] == 'no_plan', f"got {res}")
    row = storage.get_mind_insight_by_slug('e')
    check(row['state'] == 'active' and not row.get('plan_json'),
          "no plan written, state untouched")


def scenario_defaults_exist_on_new_rows():
    _reset()
    storage.add_mind_insight({'slug': 'd', 'category': 'c', 'line': 'x'})
    row = storage.get_mind_insight_by_slug('d')
    check(row['approach'] == '' and row['snoozed_until'] is None
          and row['plan_json'] is None,
          f"new-row defaults present, got {row}")


AGENT_CALLS = []


def _fake_agent(result):
    def f(prompt, actor):
        AGENT_CALLS.append({'prompt': prompt, 'actor': actor})
        return result
    return f


def _planned_insight(steps):
    """Row already in hand with the given steps (bypasses the planner)."""
    iid = storage.add_mind_insight({'slug': 'p', 'category': 'c',
                                    'line': 'needs handling'})
    storage.update_mind_insight(iid, {
        'state': 'in_hand',
        'plan_json': {'created_ts': 1.0, 'steps': steps}})
    return iid


def _step(i, kind='tool', **kw):
    return {'id': f's{i}', 'kind': kind, 'text': f'step {i}',
            'owner_member_id': None, 'owner_name': '', 'due': '2026-09-02',
            'status': 'open', 'proposal_json': None, **kw}


def scenario_bind_attaches_proposal_to_the_step():
    _reset()
    AGENT_CALLS.clear()
    iid = _planned_insight([_step(1), _step(2, kind='human')])
    mind._agent_request = _fake_agent({
        'message': 'I can ask the Hendersons.',
        'card': {'proposal_id': 'pr1', 'title': 'Ask Hendersons to cover Tue'}})
    res = mind.bind_step(iid, 's1', PARENT, now=NOON)
    check(res['status'] == 'proposed' and res['proposal_id'] == 'pr1',
          f"got {res}")
    row = storage.get_mind_insight_by_slug('p')
    s1 = row['plan_json']['steps'][0]
    check(s1['proposal_json'] == {'proposal_id': 'pr1',
                                  'summary': 'Ask Hendersons to cover Tue'},
          f"proposal stored on the step, got {s1}")
    check(s1['status'] == 'open', "binding never closes the step")
    check('step 1' in AGENT_CALLS[0]['prompt']
          and 'needs handling' in AGENT_CALLS[0]['prompt'],
          "step text and insight line reach the agent")
    res2 = mind.bind_step(iid, 's1', PARENT, now=NOON)
    check(res2['status'] == 'proposed' and len(AGENT_CALLS) == 1,
          "second bind returns the stored proposal, no second call")


def scenario_bind_refuses_human_and_closed_steps():
    _reset()
    iid = _planned_insight([_step(1, kind='human'),
                            _step(2, status='done')])
    check(mind.bind_step(iid, 's1', PARENT)['status'] == 'not_found',
          "human step never binds")
    check(mind.bind_step(iid, 's2', PARENT)['status'] == 'not_found',
          "closed step never binds")


def scenario_bind_no_move_keeps_step_open_with_note():
    _reset()
    iid = _planned_insight([_step(1)])
    mind._agent_request = _fake_agent({'message': 'Found: three sitters, from $18/h.',
                                       'card': None})
    res = mind.bind_step(iid, 's1', PARENT, now=NOON)
    check(res['status'] == 'no_move' and 'sitters' in res['note'], f"got {res}")
    s1 = storage.get_mind_insight_by_slug('p')['plan_json']['steps'][0]
    check(s1['status'] == 'open' and 'sitters' in (s1.get('note') or ''),
          "the answer is kept on the step for the family to read")


def scenario_close_math_any_done_is_acted():
    _reset()
    iid = _planned_insight([_step(1), _step(2, kind='human')])
    r1 = mind.close_step(iid, 's1', 'done')
    check(r1['status'] == 'success' and r1['insight_state'] == 'in_hand',
          f"one open step left, got {r1}")
    r2 = mind.close_step(iid, 's2', 'skipped')
    check(r2['insight_state'] == 'retired', f"got {r2}")
    row = storage.get_mind_insight_by_slug('p')
    check(row['state'] == 'retired' and row['outcome'] == 'acted'
          and row['resolved_ts'], "any done => acted")


def scenario_close_math_all_skipped_is_dismissed():
    _reset()
    iid = _planned_insight([_step(1), _step(2)])
    mind.close_step(iid, 's1', 'skipped')
    mind.close_step(iid, 's2', 'skipped')
    row = storage.get_mind_insight_by_slug('p')
    check(row['outcome'] == 'dismissed', "all skipped => the family said no")
    check(mind.close_step(iid, 's1', 'done')['status'] == 'not_found',
          "closed step refuses a second close")
    check(mind.close_step(iid, 's2', 'bogus')['status'] == 'bad_status',
          "unknown status refused")


def scenario_steps_due():
    _reset()
    row = {'plan_json': {'steps': [
        _step(1, due='2026-09-01'),                 # overdue
        _step(2, due='2026-09-02'),                 # due today
        _step(3, due='2026-09-09'),                 # future
        _step(4, due='2026-09-01', status='done'),  # closed
        _step(5, due='garbled'),                    # unparseable counts due
    ]}}
    due = mind.steps_due(row, today=datetime.date(2026, 9, 2))
    check([s['id'] for s in due] == ['s1', 's2', 's5'], f"got {[s['id'] for s in due]}")
    check(mind.steps_due({'plan_json': None}) == [], "no plan, nothing due")


def scenario_lane_visibility():
    _reset()
    # snoozed_until is anchored to NOON (the `now` passed to visible_insights
    # below), never to the real wall clock -- a real-time anchor would make
    # this test's pass/fail depend on what time of day it happens to run.
    storage.add_mind_insight({'slug': 'plain', 'category': 'c', 'line': 'a'})
    snoozed = storage.add_mind_insight({'slug': 'parked', 'category': 'c',
                                        'line': 'b'})
    storage.update_mind_insight(snoozed,
                                {'snoozed_until': NOON.timestamp() + 86400})
    woken = storage.add_mind_insight({'slug': 'woken', 'category': 'c',
                                      'line': 'c'})
    storage.update_mind_insight(woken,
                                {'snoozed_until': NOON.timestamp() - 60})
    _planned_insight([_step(1, due='2026-09-09')])       # in hand, nothing due
    quiet = storage.get_mind_insight_by_slug('p')
    storage.update_mind_insight(quiet['id'], {'slug': 'quiet-hand'})
    iid2 = storage.add_mind_insight({'slug': 'due-hand', 'category': 'c',
                                     'line': 'e'})
    storage.update_mind_insight(iid2, {
        'state': 'in_hand',
        'plan_json': {'created_ts': 1.0, 'steps': [_step(9, due='2026-09-01')]}})
    lane = mind.visible_insights({'id': 'mom', 'role': 'parent'}, now=NOON)
    slugs = {r['slug'] for r in lane}
    check(slugs == {'plain', 'woken', 'due-hand'}, f"got {slugs}")
    due_row = next(r for r in lane if r['slug'] == 'due-hand')
    check(due_row.get('due_step_count') == 1,
          "in-hand row says how many steps are due")


def scenario_sensitive_gate_still_holds():
    _reset()
    storage.add_mind_insight({'slug': 's', 'category': 'c', 'line': 'x',
                              'sensitivity': 'sensitive'})
    check(len(mind.visible_insights({'id': 'k', 'role': 'child'}, now=NOON)) == 0,
          "sensitive stays parents-only through the new path")
    check(len(mind.visible_insights({'id': 'mom', 'role': 'parent'}, now=NOON)) == 1,
          "parent still sees it")


# --- C1: the bind tap must be structurally unable to ACT --------------------
# Before this, "Do it" ran the same rail chat runs, and the rail EXECUTES: a
# step reading "DM Lorena about Tuesday" sent the DM at bind time, left the
# step open, and sent it again on the next tap. Per-step approval was a
# promise the code did not keep. Two tests, because the invariant has two
# halves: the Mind has to ask for the proposal-only rail, and the rail has to
# really refuse. `_REAL_AGENT_REQUEST` is captured at import, before any
# scenario above swaps that attribute out for a stub.

_REAL_AGENT_REQUEST = mind._agent_request


def _fake_llm(name, args=None, box=None):
    """One canned tool call, no network. `box` collects what the router put in
    front of the model, so a test can assert on the offered tool list."""
    def f(prompt, tools, system_prompt):
        if box is not None:
            box['tools'] = [t.get('name') for t in tools]
            box['system'] = system_prompt
        return {'message': '', 'tool_calls': [{'name': name,
                                               'arguments': args or {}}]}
    return f


def scenario_both_mind_taps_ask_for_the_proposal_only_rail():
    _reset()
    from services import agent_router
    seen = {}

    def fake_router(prompt, **kw):
        seen.clear()
        seen.update(kw)
        return {'message': 'noted', 'card': None}

    orig_router, orig_req = agent_router.process_agent_request, mind._agent_request
    try:
        agent_router.process_agent_request = fake_router
        mind._agent_request = _REAL_AGENT_REQUEST
        iid = _planned_insight([_step(1)])
        mind.bind_step(iid, 's1', PARENT, now=NOON)
        check(seen.get('propose_only') is True,
              f"bind_step must run the rail proposal-only, got {seen}")
        # propose_fix is the same rail with the same hole and it predates
        # plans: fixing one and leaving the other is half a fix.
        legacy = storage.add_mind_insight({'slug': 'legacy', 'category': 'c',
                                           'line': 'older path'})
        mind.propose_fix(legacy, PARENT, now=NOON)
        check(seen.get('propose_only') is True,
              f"propose_fix must too, got {seen}")
    finally:
        agent_router.process_agent_request = orig_router
        mind._agent_request = orig_req


def scenario_the_rail_refuses_to_act_when_asked_only_to_propose():
    _reset()
    from services import agent_router, agent_tools_v2
    sent, box = [], {}
    orig_llm = agent_router.call_gemma_with_fallback
    orig_dm = agent_tools_v2.send_direct_message
    try:
        agent_tools_v2.send_direct_message = lambda *a, **kw: (
            sent.append(a) or {'status': 'success', 'message': 'sent'})
        agent_router.call_gemma_with_fallback = _fake_llm(
            'send_direct_message',
            {'recipient_name': 'Dad', 'message_text': 'hi'}, box)

        res = agent_router.process_agent_request('do the step', propose_only=True)
        check(not sent, "no DM may be sent on the proposal-only rail")
        check(res.get('card') is None, "and nothing was proposed either")
        check('send_direct_message' not in (box.get('tools') or []),
              "the acting tool is not even offered to the model")
        check('processed your request' not in (res.get('message') or ''),
              f"the note kept on the step must be honest, got {res.get('message')}")

        # The control. Without it a broken stub -- one that never reaches
        # dispatch at all -- would look exactly like a working refusal.
        agent_router.process_agent_request('do the step')
        check(len(sent) == 1, f"the unflagged chat rail still acts, got {sent}")
    finally:
        agent_router.call_gemma_with_fallback = orig_llm
        agent_tools_v2.send_direct_message = orig_dm


def scenario_the_proposal_only_rail_still_proposes_and_still_reads():
    _reset()
    from services import agent_router, agent_tools_v2
    asked = []
    orig_llm = agent_router.call_gemma_with_fallback
    orig_rq = agent_tools_v2.research_question
    try:
        agent_router.call_gemma_with_fallback = _fake_llm(
            'propose_family_action',
            {'action_type': 'reassign_driver',
             'summary': 'Give Tuesday soccer to Lorena',
             'payload': {'event_name': 'Soccer', 'driver_name': 'Lorena',
                         'target_date': '2026-09-08'}})
        res = agent_router.process_agent_request('do the step', propose_only=True)
        check((res.get('card') or {}).get('proposal_id'),
              f"a card a parent still has to tap is the whole point, got {res}")

        agent_tools_v2.research_question = lambda q: (
            asked.append(q) or {'status': 'success',
                                'message': 'three sitters, from $18/h'})
        agent_router.call_gemma_with_fallback = _fake_llm(
            'research_question', {'question': 'what does a sitter cost here'})
        agent_router.process_agent_request('go find out', propose_only=True)
        check(asked, "a read still runs -- its answer IS the step's note")
    finally:
        agent_router.call_gemma_with_fallback = orig_llm
        agent_tools_v2.research_question = orig_rq


def scenario_a_late_bind_does_not_undo_a_skip():
    """I4: bind holds the plan across a long agent call. The family kept using
    the card meanwhile; the write-back must not roll them back."""
    _reset()
    iid = _planned_insight([_step(1), _step(2)])

    def slow_agent(prompt, actor):
        # what a person does while the agent is thinking
        mind.close_step(iid, 's2', 'skipped')
        return {'message': 'ok', 'card': {'proposal_id': 'pr9', 'title': 'T'}}

    mind._agent_request = slow_agent
    mind.bind_step(iid, 's1', PARENT, now=NOON)
    by_id = {s['id']: s for s
             in storage.get_mind_insight_by_slug('p')['plan_json']['steps']}
    check(by_id['s2']['status'] == 'skipped',
          f"the skip taken mid-bind survives, got {by_id['s2']}")
    check(by_id['s1']['proposal_json']['proposal_id'] == 'pr9',
          "and the bind still landed on its own step")


def scenario_parse_steps_survives_a_model_answering_in_numbers():
    """I7: a numeric due or a non-string text used to raise AttributeError --
    a 500 on the card with the day's cap already spent."""
    _reset()
    iid = storage.add_mind_insight({'slug': 'n', 'category': 'c', 'line': 'x'})
    mind._pool_call = _fake_pool({'steps': [
        {'kind': 'tool', 'text': 'Ask the school', 'due': 20260904},
        {'kind': 'human', 'text': 12345, 'owner': 'Dad', 'due': '2026-09-06'},
        {'kind': 'tool', 'text': 'Third', 'due': None},
    ]})
    res = mind.make_plan(iid, PARENT, now=NOON)
    check(res['status'] == 'planned', f"no exception, a plan, got {res}")
    steps = res['plan']['steps']
    check(steps[0]['due'] == '2026-09-04',
          f"a numeric ISO due is coerced and normalised, got {steps[0]['due']}")
    check(steps[1]['text'] == '12345', f"numeric text is coerced, got {steps[1]}")
    check(steps[2]['due'] == '2026-09-05', "a missing due still defaults")


if __name__ == '__main__':
    scenario_plan_attaches_and_state_moves()
    scenario_second_tap_returns_existing_plan()
    scenario_steps_are_clamped_and_defaulted()
    scenario_empty_plan_is_honest()
    scenario_defaults_exist_on_new_rows()
    scenario_bind_attaches_proposal_to_the_step()
    scenario_bind_refuses_human_and_closed_steps()
    scenario_bind_no_move_keeps_step_open_with_note()
    scenario_close_math_any_done_is_acted()
    scenario_close_math_all_skipped_is_dismissed()
    scenario_steps_due()
    scenario_lane_visibility()
    scenario_sensitive_gate_still_holds()
    scenario_both_mind_taps_ask_for_the_proposal_only_rail()
    scenario_the_rail_refuses_to_act_when_asked_only_to_propose()
    scenario_the_proposal_only_rail_still_proposes_and_still_reads()
    scenario_a_late_bind_does_not_undo_a_skip()
    scenario_parse_steps_survives_a_model_answering_in_numbers()
    print("test_mind_plan OK")
