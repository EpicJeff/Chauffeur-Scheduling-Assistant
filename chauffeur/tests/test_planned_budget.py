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


SCENARIOS = [
    scenario_no_guard_charges_nothing,
    scenario_a_guard_charges_each_call_before_it_runs,
    scenario_the_limit_stops_the_call_before_it_runs,
    scenario_exhaustion_passes_through_the_pool_chain_and_the_curator,
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
