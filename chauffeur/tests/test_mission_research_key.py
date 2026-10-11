"""A mission's research bills the paid key and shrugs off the free key's
per-minute cap: the paid project has its own quotas, so the free key's model
cooldowns do not apply, and a per-minute 429 parks the mission for two
minutes instead of recording a failed step. gemini-3.7-flash is retired."""
import io
import json
import time
from datetime import date

from harness import check  # noqa: F401
from services import storage, missions, web, model_pools, llm_budget

PAID = {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'free',
        'web_research_enabled': True, 'web_research_via': 'model'}


def _reset(settings=None):
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    storage.set_app_state('web_search_cache', {})
    storage.set_app_state('web_research_calls', {})
    storage.get_settings = lambda: dict(settings or PAID)


def _mission():
    return storage.add_mission({'goal': 'find a magician', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})


def scenario_a_missions_research_bills_the_paid_key():
    _reset()
    seen = []
    orig = web.research
    web.research = lambda q, **kw: seen.append(kw) or {'status': 'ok', 'answer': 'x', 'facts': [], 'sources': []}
    missions._llm = lambda m, s, u, st: {'action': 'research', 'question': 'best local magician'}
    try:
        missions.step(storage.get_mission(_mission()))
        check(seen and seen[0].get('api_key') == 'paid', f"the paid key rides the research: {seen}")
        _reset({**PAID, 'llm_gemini_paid_api_key': ''})
        seen.clear()
        missions.step(storage.get_mission(_mission()))
        check(seen and not seen[0].get('api_key'), f"no paid key: the free key as before: {seen}")
    finally:
        web.research = orig


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def scenario_paid_research_ignores_the_free_keys_cooldowns():
    """The free key's 429 parks a model for everybody who shares the key; the
    paid project is a different quota, so paid research tries flash anyway."""
    _reset()
    for m in model_pools.DEFAULT_POOLS['flash'][:3]:
        model_pools.note_failure(m, '429 rate limited')
    urls = []
    orig = llm_budget.urlopen

    def fake(req, timeout=60):
        urls.append(req.full_url)
        return _Resp({'candidates': [{'content': {'parts': [{'text': 'Ace Pools, 919-555-0100'}]},
                                      'groundingMetadata': {'groundingChunks': [{'web': {'uri': 'https://acepools.example/', 'title': 'Ace'}}]}}]})
    llm_budget.urlopen = fake
    web._resolve_url = lambda u: u
    try:
        out = web.research('pool cover installer near Cary', api_key='paid')
        check(out['status'] == 'ok' and 'Ace Pools' in out['answer'], f"paid research answers: {out}")
        check(urls and 'key=paid' in urls[0] and 'gemini-3.8-flash' in urls[0], f"flash on the paid key, cooldown or not: {urls}")
    finally:
        llm_budget.urlopen = orig
        model_pools._cooldowns.clear()


def scenario_a_per_minute_429_parks_the_mission_and_retries():
    _reset()
    orig = web.research
    web.research = lambda q, **kw: {'status': 'error', 'message': 'Gemini couldn\'t search the web: 429 {"error": {"code": 429, "message": "You exceeded your current quota"}}'}
    missions._llm = lambda m, s, u, st: {'action': 'research', 'question': 'best local magician'}
    try:
        mid = _mission()
        row = missions.step(storage.get_mission(mid))
        check(row['status'] == 'waiting_retry' and 100 <= (row['retry_at'] or 0) - time.time() <= 130, f"parked two minutes: {row['status']} {row.get('retry_at')}")
        steps = storage.get_mission_steps(mid)
        check(not [s for s in steps if s['kind'] == 'tool'] and steps[-1]['kind'] == 'note' and 'rate limit' in steps[-1]['result_json']['note'].lower(),
              f"no failed tool step; a note says why: {steps[-1]}")
        # A per-day cap is not a two-minute matter: the step records the error and the planner reads it.
        web.research = lambda q, **kw: {'status': 'error', 'message': '429 quota per day exhausted'}
        mid = _mission()
        row = missions.step(storage.get_mission(mid))
        check(row['status'] == 'running' and storage.get_mission_steps(mid)[-1]['kind'] == 'tool', "a daily cap is a recorded step")
    finally:
        web.research = orig


def scenario_search_errors_are_said_plainly():
    """A chat reply must never be a JSON dump: a 429 says rate limited, a 404
    says a model is gone, nothing carries braces."""
    import urllib.error
    _reset()
    orig = llm_budget.urlopen

    def failing(code, body):
        def f(req, timeout=60):
            raise urllib.error.HTTPError(req.full_url, code, 'x', {}, io.BytesIO(body.encode()))
        return f
    try:
        llm_budget.urlopen = failing(429, '{"error": {"code": 429, "message": "You exceeded your current quota"}}')
        out = web.research('q one', api_key='paid')
        check(out['status'] == 'error' and 'rate limit' in out['message'].lower() and '{' not in out['message'], f"429: {out}")
        llm_budget.urlopen = failing(404, '{"error": {"code": 404, "message": "models/gemini-3-flash is not found"}}')
        out = web.research('q two', api_key='paid')
        check(out['status'] == 'error' and 'model' in out['message'].lower() and '{' not in out['message'] and len(out['message']) < 200, f"404: {out}")
    finally:
        llm_budget.urlopen = orig
        model_pools._cooldowns.clear()


def scenario_gemini_3_7_flash_is_retired():
    for gone in ('gemini-3.7-flash', 'gemini-3-flash'):
        check(gone in model_pools.RETIRED_MODELS, f"{gone} named as retired (404 from the API, 2026-10-11)")
        for pool, models in model_pools.DEFAULT_POOLS.items():
            check(gone not in models, f"{gone} still in the {pool} pool")


SCENARIOS = [scenario_a_missions_research_bills_the_paid_key, scenario_paid_research_ignores_the_free_keys_cooldowns,
             scenario_search_errors_are_said_plainly,
             scenario_a_per_minute_429_parks_the_mission_and_retries, scenario_gemini_3_7_flash_is_retired]

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
