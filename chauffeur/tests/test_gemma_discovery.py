"""Gemma pool discovery: the key's own model list decides the Gemma pool.

Device log 2026-10-05: gemma-4-26b-it (a pool default) answered 404, so the
background fall-through had no second model. Load-bearing properties: the
list is read from the API (generate-capable Gemmas, >= 12B, largest first),
defaults that exist keep their order, a `model_pool_gemma` setting still
wins, a Gemma 404 forces a fresh look, a failed look keeps the old list and
retries in an hour, and the look happens at most once while fresh.

Run from chauffeur/:  python tests/test_gemma_discovery.py
"""
import io
import json
import time
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import model_pools as pools, storage

LISTING = {'models': [
    {'name': 'models/gemma-4-31b-it', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemma-4-26b-a4b-it', 'supportedGenerationMethods': ['generateContent', 'countTokens']},
    {'name': 'models/gemma-3-27b-it', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemma-3-12b-it', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemma-3n-e4b-it', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemma-3-1b-it', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemma-embed-300m', 'supportedGenerationMethods': ['embedContent']},
    {'name': 'models/gemini-3.5-flash-lite', 'supportedGenerationMethods': ['generateContent']},
]}


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _reset():
    import main  # noqa: F401
    storage.app_state_table.truncate()
    pools.reset_cooldowns()


def _listing(calls):
    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        check(req.get_header('X-goog-api-key') == 'k', "the key goes in the header, never the URL")
        return _Resp(json.dumps(LISTING).encode())
    return urlopen


def scenario_discovery_builds_the_pool():
    _reset()
    check(pools._pool('gemma', {}) == pools.DEFAULT_POOLS['gemma'], "before discovery: the defaults")
    calls = []
    with mock.patch('urllib.request.urlopen', _listing(calls)):
        found = pools.refresh_gemma_models('k')
    check(found == ['gemma-4-31b-it', 'gemma-3-27b-it', 'gemma-4-26b-a4b-it', 'gemma-3-12b-it'],
          f"generate-capable Gemmas >= 12B, largest first: {found}")
    check('key=' not in calls[0], "no key in the URL")
    pool = pools._pool('gemma', {})
    check(pool == ['gemma-4-31b-it', 'gemma-3-27b-it', 'gemma-4-26b-a4b-it'],
          f"existing defaults first (the stale one dropped), then the largest others, three in all: {pool}")
    check(pools._pool('gemma', {'model_pool_gemma': 'gemma-x, gemma-y'}) == ['gemma-x', 'gemma-y'],
          "a model_pool_gemma setting still wins")
    check(pools.models_for('background', {})[:2] == ['gemma-4-31b-it', 'gemma-3-27b-it'],
          "background work now has a real second Gemma")


def scenario_discovery_runs_when_due_only():
    _reset()
    calls = []
    with mock.patch('urllib.request.urlopen', _listing(calls)):
        pools._maybe_discover('background', 'k', {}, wait=True)
        pools._maybe_discover('background', 'k', {}, wait=True)
        pools._maybe_discover('interactive', 'k', {}, wait=True)
        check(len(calls) == 1, f"one look while the list is fresh: {len(calls)}")
        pools._maybe_discover('vision', 'k', {}, wait=True)
        check(len(calls) == 1, "tiers without Gemma never look")
        pools._maybe_discover('background', 'k', {'model_pool_gemma': 'gemma-x'}, wait=True)
        check(len(calls) == 1, "a manual Gemma list is never second-guessed")
        pools.note_failure('gemma-4-26b-it', 'HTTP Error 404: Not Found')
        check(pools.gemma_discovery_due(), "a Gemma 404 makes the list stale at once")
        pools._maybe_discover('background', 'k', {}, wait=True)
        check(len(calls) == 2, "and the next call looks again")
        pools.note_failure('gemini-3.5-flash-lite', 'HTTP Error 404: Not Found')
        check(not pools.gemma_discovery_due(), "a non-Gemma 404 does not")


def scenario_a_failed_look_keeps_the_list():
    _reset()
    with mock.patch('urllib.request.urlopen', _listing([])):
        pools.refresh_gemma_models('k')
    before = pools._pool('gemma', {})
    pools.mark_gemma_discovery_stale()
    with mock.patch('urllib.request.urlopen', side_effect=OSError('network down')):
        found = pools.refresh_gemma_models('k')
    check(found and pools._pool('gemma', {}) == before, "a failed look keeps the last good list")
    check(not pools.gemma_discovery_due(), "and does not retry on every call")
    with mock.patch.object(pools.time, 'time', return_value=time.time() + 3700):
        check(pools.gemma_discovery_due(), "it retries after an hour")


SCENARIOS = [
    scenario_discovery_builds_the_pool,
    scenario_discovery_runs_when_due_only,
    scenario_a_failed_look_keeps_the_list,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
