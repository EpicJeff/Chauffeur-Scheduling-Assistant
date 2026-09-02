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


if __name__ == '__main__':
    scenario_plan_attaches_and_state_moves()
    scenario_second_tap_returns_existing_plan()
    scenario_steps_are_clamped_and_defaulted()
    scenario_empty_plan_is_honest()
    scenario_defaults_exist_on_new_rows()
    print("test_mind_plan OK")
