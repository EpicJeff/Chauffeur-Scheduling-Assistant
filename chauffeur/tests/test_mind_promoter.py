"""Promoter: only high-urgency unconsumed noticings, one lite call, sets flag."""
from harness import check
from services import storage, mind

CALLS = []

def _fake_pool(think_now):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append(tier)
        return {'think_now': think_now}
    return f

def _reset(urgency='high'):
    CALLS.clear()
    storage.mind_noticings_table.truncate()
    storage.set_app_state('mind_think_requested', False)
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k'}
    storage.add_mind_noticing({'line': 'x', 'source': 'chat', 'urgency': urgency})

def scenario_high_urgency_promotes():
    _reset('high')
    mind._pool_call = _fake_pool(True)
    res = mind.maybe_promote()
    check(res['status'] == 'promoted', f"got {res}")
    check(CALLS == ['interactive'], "one lite-first call")
    check(storage.get_app_state('mind_think_requested') is True, "flag set")

def scenario_low_urgency_never_calls():
    _reset('low')
    mind._pool_call = _fake_pool(True)
    res = mind.maybe_promote()
    check(res['status'] == 'nothing' and not CALLS, "low urgency waits for the hour")

def scenario_holds_when_llm_says_wait():
    _reset('high')
    mind._pool_call = _fake_pool(False)
    res = mind.maybe_promote()
    check(res['status'] == 'held', "LLM veto holds the think")
    check(storage.get_app_state('mind_think_requested') is not True, "no flag")

if __name__ == '__main__':
    scenario_high_urgency_promotes()
    scenario_low_urgency_never_calls()
    scenario_holds_when_llm_says_wait()
    print("test_mind_promoter OK")
