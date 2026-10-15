"""The budget guard (planned missions spec §8, Codex H4 and F12).

A planned mission charges the day's paid allowance (`mission_cap_pro_calls`,
the counter missions already keep in app_state `mission_calls:<day>`) for
EVERY model call a stage row makes, nested ones included: the program curator
alone runs research, a shaping call, a retry and a generated fallback.

Pinned here:

Task 2 (block A):
  * with no guard active nothing is charged (every existing caller unchanged);
  * inside `budget_guard.guard()` each `llm.call_model` and each `web.research`
    that reaches a model is charged BEFORE it runs; a cache hit is free;
  * at the limit `BudgetExhausted` is raised before the call and it passes
    through the pool chain's fallbacks and the curator's own excepts.

Task 8 appends block B (the guard inside the stage runner).

Run from chauffeur/:  python tests/test_planned_budget.py
"""
import datetime

from harness import check  # noqa: F401
from services import storage

TODAY_KEY = f"mission_calls:{datetime.date.today().isoformat()}"
CALLS = []


def _reset(cap=10, used=0):
    storage.app_state_table.truncate()
    storage.set_app_state(TODAY_KEY, {'pro': used})
    storage.get_settings = lambda: {'mission_cap_pro_calls': cap, 'web_research_enabled': True, 'web_research_via': 'model',
                                    'llm_gemini_api_key': 'free', 'llm_gemini_paid_api_key': 'paid', 'calendar_ids': ['primary']}
    CALLS.clear()
    from services import llm, web
    llm._call_llm_json = lambda *a, **k: CALLS.append('model') or {'phases': [], 'text': 'ok'}
    web._gemini_grounded = lambda question, api_key, model=None: CALLS.append('research') or {
        'answer': 'Beginner piano: scales, simple pieces.', 'sources': [{'title': 'Piano basics', 'url': 'https://example.com/piano'}],
        'facts': [{'claim': 'Piano basics', 'url': 'https://example.com/piano'}]}
    web._cache_get = lambda key: None
    web._cache_put = lambda *a, **k: None
    web._month_count = lambda bump=False: 0


def _used():
    return int((storage.get_app_state(TODAY_KEY) or {}).get('pro', 0))


def scenario_no_guard_charges_nothing():
    _reset()
    from services import llm, web
    llm.call_model('gemini-3.8-flash', 'k', 'sys', 'user')
    web.research('how to start piano')
    check(CALLS == ['model', 'research'], f"both calls ran: {CALLS}")
    check(_used() == 0, f"nothing charged without a guard: {_used()}")


def scenario_a_guard_charges_each_call_before_it_runs():
    _reset(cap=10, used=3)
    from services import llm, web, budget_guard
    with budget_guard.guard():
        check(budget_guard.active(), "the guard is active inside")
        llm.call_model('gemini-3.8-flash', 'k', 'sys', 'user')
        web.research('how to start piano')
    check(_used() == 5, f"two calls charged: {_used()}")
    check(not budget_guard.active(), "and inactive after")
    web._cache_get = lambda key: {'status': 'success', 'answer': 'cached'}
    with budget_guard.guard():
        web.research('how to start piano')
    check(_used() == 5, "a cache hit is free")


def scenario_the_limit_stops_the_call_before_it_runs():
    _reset(cap=4, used=3)
    from services import llm, budget_guard
    raised = None
    with budget_guard.guard():
        llm.call_model('gemini-3.8-flash', 'k', 'sys', 'user')
        try:
            llm.call_model('gemini-3.8-flash', 'k', 'sys', 'user')
        except budget_guard.BudgetExhausted as e:
            raised = e
    check(raised is not None, "the second call is refused at the limit")
    check(CALLS == ['model'], f"and never reaches the model: {CALLS}")
    check(_used() == 4, f"the counter stops at the cap: {_used()}")


def scenario_exhaustion_passes_through_the_pool_chain_and_the_curator():
    from services import model_pools, programs_curate, budget_guard
    _reset(cap=4, used=3)
    raised = None
    with budget_guard.guard():
        try:
            model_pools.call_pool_json('heavy', 'k', 'sys', 'user')
            model_pools.call_pool_json('heavy', 'k', 'sys', 'user')
        except budget_guard.BudgetExhausted as e:
            raised = e
    check(raised is not None, "the pool chain does not swallow it by trying the next model")
    _reset(cap=5, used=3)
    raised = None
    with budget_guard.guard():
        try:
            programs_curate.curate('Learn piano', {'sessions_per_week': 3, 'minutes': 20}, member_name='Kate')
        except budget_guard.BudgetExhausted as e:
            raised = e
    check(raised is not None, f"the curator's research, shaping and retry are each charged; the third is refused: {CALLS}")
    check(CALLS[:2] == ['research', 'model'] and len(CALLS) == 2, f"research, then one shaping call, then the stop: {CALLS}")



# --- Task 8 (block B): the guard inside the stage runner, and carrying on ---------

def _budget_stubs(cap, used):
    """The mission fixture plus the model/research fakes and the day's counter."""
    from services import llm, web
    storage.set_app_state(TODAY_KEY, {'pro': used})
    base = storage.get_settings()
    storage.get_settings = (lambda s: (lambda: dict(s, mission_cap_pro_calls=cap, web_research_enabled=True, web_research_via='model',
                                                    llm_gemini_api_key='free')))(base)
    CALLS.clear()
    llm._call_llm_json = lambda *a, **k: CALLS.append('model') or {'phases': [], 'text': 'ok'}
    web._gemini_grounded = lambda question, api_key, model=None: CALLS.append('research') or {
        'answer': 'Beginner piano.', 'sources': [{'title': 'Piano', 'url': 'https://example.com/p'}],
        'facts': [{'claim': 'Piano', 'url': 'https://example.com/p'}]}
    web._cache_get = lambda key: None
    web._cache_put = lambda *a, **k: None
    web._month_count = lambda bump=False: 0


PIANO_ROWS = [{'id': 'r1', 'tool': 'propose_program',
               'args': {'title': 'Learn piano', 'for_member_name': 'Kate', 'sessions_per_week': 3, 'minutes': 20},
               'summary': 'Propose a piano program for Kate'}]


def _staged_rows(rows):
    from test_planned_missions import _fresh, _staged
    _fresh()
    return _staged(rows)


def _stage(mid):
    return (storage.get_mission(mid).get('plan') or {})['stages'][0]


def scenario_b1_a_model_row_stops_at_the_days_limit_and_carries_on_tomorrow():
    from services import planned, situations
    from test_subjects import MOM
    mid, st = _staged_rows(PIANO_ROWS)
    programs_before = len(storage.get_programs(include_finished=True))
    _budget_stubs(cap=1, used=0)
    planned.run_stage(mid, 's1', st['snapshot'], dict(MOM))
    st = _stage(mid)
    row = st['rows'][0]
    check(row['state'] == 'failed' and "limit" in (row['result'].get('message') or '') and row['result'].get('budget') is True,
          f"the curator's research was charged, its shaping call refused: {row}")
    check(st['state'] == 'partial', f"the stage is partial: {st['state']}")
    check(len(storage.get_programs(include_finished=True)) == programs_before, "no half-made program")
    opts = [o for o in situations.options_for('mission', situations.load('mission', mid)) if o['verb'] == 'run_stage']
    resume = [o for o in opts if o['id'].endswith(':resume')]
    check(resume and resume[0]['label'] == 'Carry on', f"a Carry on button: {[o['id'] for o in opts]}")
    storage.set_app_state(TODAY_KEY, {'pro': 0})                       # tomorrow: a fresh allowance
    storage.get_settings = (lambda s: (lambda: dict(s, mission_cap_pro_calls=50)))(storage.get_settings())
    res = situations.act('mission', mid, 'run_stage', option_id=resume[0]['id'], payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"carry on: {res}")
    st = _stage(mid)
    check(st['state'] == 'proposed' and st['rows'][0]['state'] == 'proposed', f"the budget-stopped row is offered again: {st}")
    planned.run_stage(mid, 's1', st['snapshot'], dict(MOM))
    st = _stage(mid)
    check(st['rows'][0]['state'] == 'done' and st['state'] == 'done', f"and runs: {st['rows'][0]}")


def scenario_b2_a_row_that_calls_no_model_never_charges():
    from services import planned
    from test_subjects import MOM
    rows = [{'id': 'r1', 'tool': 'add_occasion_guests', 'args': {'occasion_id': 'o2', 'who': 'The Lees', 'headcount': 2}, 'summary': 'guests'},
            {'id': 'r2', 'tool': 'draft_message', 'args': {'to': 'Grandma', 'words': 'Come!'}, 'summary': 'a draft'}]
    mid, st = _staged_rows(rows)
    _budget_stubs(cap=5, used=2)
    planned.run_stage(mid, 's1', st['snapshot'], dict(MOM))
    check(_stage(mid)['state'] == 'done', "ran")
    check(_used() == 2 and CALLS == [], f"nothing charged: {_used()} {CALLS}")


def scenario_b3_a_stage_stopped_by_the_time_bound_carries_on():
    from services import planned, situations
    from test_subjects import MOM
    rows = [{'id': f'r{i}', 'tool': 'draft_message', 'args': {'to': 'x', 'words': str(i)}, 'summary': f'd{i}'} for i in range(3)]
    mid, st = _staged_rows(rows)
    ticks = iter([0.0, 0.0, 500.0, 500.0, 500.0, 500.0])
    orig = planned._clock
    planned._clock = lambda: next(ticks, 500.0)
    try:
        planned.run_stage(mid, 's1', st['snapshot'], dict(MOM))
    finally:
        planned._clock = orig
    resume = [o for o in situations.options_for('mission', situations.load('mission', mid)) if o['id'].endswith(':resume')]
    check(resume, "Carry on is offered")
    situations.act('mission', mid, 'run_stage', option_id=resume[0]['id'], payload={}, actor=dict(MOM))
    st = _stage(mid)
    check([r['state'] for r in st['rows']] == ['done', 'proposed', 'proposed'], f"done rows stay done; the rest are offered: {st['rows']}")
    planned.run_stage(mid, 's1', st['snapshot'], dict(MOM))
    check([r['state'] for r in _stage(mid)['rows']] == ['done', 'done', 'done'], "and finish")


SCENARIOS = [
    scenario_no_guard_charges_nothing,
    scenario_a_guard_charges_each_call_before_it_runs,
    scenario_the_limit_stops_the_call_before_it_runs,
    scenario_exhaustion_passes_through_the_pool_chain_and_the_curator,
    scenario_b1_a_model_row_stops_at_the_days_limit_and_carries_on_tomorrow,
    scenario_b2_a_row_that_calls_no_model_never_charges,
    scenario_b3_a_stage_stopped_by_the_time_bound_carries_on,
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
