"""Tests for LLM transient-error handling (Gemini 503 retry + honest agent replies).

Regression for: Gemini returning 503 ("model is currently experiencing high
demand") caused the agent to answer "I have processed your request." with
status success. Now: the call layer retries with backoff, the router falls
back to the secondary model, and a final failure produces an honest
try-again-later message with status "error".

Run from chauffeur/:  python tests/test_agent_llm_errors.py
"""
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from unittest import mock

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_llmerr_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import agent_router  # noqa: E402
from services.llm import _call_llm_json  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


GEMINI_503_BODY = json.dumps({"error": {
    "code": 503,
    "message": "This model is currently experiencing high demand. Spikes in demand "
               "are usually temporary. Please try again later.",
    "status": "UNAVAILABLE"}}).encode()


def http_error(code, body=GEMINI_503_BODY):
    return urllib.error.HTTPError("https://example", code, "Service Unavailable",
                                  {}, io.BytesIO(body))


class FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def gemini_success(inner):
    return FakeResponse({"candidates": [{"content": {"parts": [
        {"text": json.dumps(inner)}]}}]})


def scenario_retries_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise http_error(503)
        return gemini_success({"message": "hi", "tool_calls": []})

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
         mock.patch("time.sleep", sleeps.append):
        res = _call_llm_json("gemini", "", "key", "gemma-4-31b-it", "sys", "user")
    check(res.get("message") == "hi", f"third attempt succeeds, got {res}")
    check(calls["n"] == 3, f"expected 3 attempts, got {calls['n']}")
    check(sleeps == [2, 4], f"expected 2s/4s backoff, got {sleeps}")


def scenario_retries_exhausted_raises():
    sleeps = []
    with mock.patch.object(urllib.request, "urlopen",
                           lambda req, timeout=None: (_ for _ in ()).throw(http_error(503))), \
         mock.patch("time.sleep", sleeps.append):
        try:
            _call_llm_json("gemini", "", "key", "gemma-4-31b-it", "sys", "user")
            raised = False
        except RuntimeError as e:
            raised = "503" in str(e)
    check(raised, "exhausted retries raise a RuntimeError mentioning 503")
    check(len(sleeps) == 2, f"only 2 backoff sleeps before giving up, got {sleeps}")


def scenario_429_no_retry():
    sleeps = []
    with mock.patch.object(urllib.request, "urlopen",
                           lambda req, timeout=None: (_ for _ in ()).throw(
                               http_error(429, b'{"error": "quota"}'))), \
         mock.patch("time.sleep", sleeps.append):
        res = _call_llm_json("gemini", "", "key", "gemma-4-31b-it", "sys", "user")
    check("429" in str(res.get("error")), "429 returns an error dict for model fallback")
    check(sleeps == [], "429 must not burn retry backoff (router handles model fallback)")


def scenario_router_falls_back_on_503():
    calls = []

    def fake_call(provider, url, api_key, model, system_prompt, prompt, **kw):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("Gemini API request failed: HTTP Error 503: Service Unavailable")
        return {"message": "done via fallback", "tool_calls": []}

    with mock.patch.object(agent_router, "_call_llm_json", fake_call):
        res = agent_router.call_gemma_with_fallback("do it", [], "sys")
    check(res.get("message") == "done via fallback", f"fallback result returned, got {res}")
    check(calls == ["gemma-4-31b-it", "gemma-4-26b-it"],
          f"primary then fallback model, got {calls}")


def scenario_router_reports_transient_failure_honestly():
    def fake_call(*a, **kw):
        raise RuntimeError("Gemini API request failed: HTTP Error 503: Service Unavailable")

    with mock.patch.object(agent_router, "_call_llm_json", fake_call):
        res = agent_router.process_agent_request("assign a driver")
    check(res["status"] == "error", f"status must be error, got {res['status']}")
    check("processed your request" not in res["message"].lower(),
          f"must not fake success, got: {res['message']}")
    check("overloaded" in res["message"].lower() and "try again" in res["message"].lower(),
          f"transient failure should say overloaded + try again, got: {res['message']}")


def scenario_router_reports_hard_failure_honestly():
    def fake_call(*a, **kw):
        raise RuntimeError("Gemini request failed: something exploded")

    with mock.patch.object(agent_router, "_call_llm_json", fake_call):
        res = agent_router.process_agent_request("assign a driver")
    check(res["status"] == "error", "status must be error")
    check("processed your request" not in res["message"].lower(), "must not fake success")
    check("try again" in res["message"].lower(),
          f"hard failure still tells the user to retry, got: {res['message']}")


SCENARIOS = [
    scenario_retries_then_succeeds,
    scenario_retries_exhausted_raises,
    scenario_429_no_retry,
    scenario_router_falls_back_on_503,
    scenario_router_reports_transient_failure_honestly,
    scenario_router_reports_hard_failure_honestly,
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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
