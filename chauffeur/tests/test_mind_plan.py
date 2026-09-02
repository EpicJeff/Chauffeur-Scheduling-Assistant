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
    print("test_mind_plan OK")
