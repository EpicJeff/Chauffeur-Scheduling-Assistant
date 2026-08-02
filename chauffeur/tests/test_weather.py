"""Tests for the HA weather forecast helper (services/ha_api.py).

The load-bearing property is graceful degradation: any HA failure returns []
so the digest line silently drops instead of breaking the push loop.

Run from chauffeur/:  python tests/test_weather.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import ha_api


FORECAST = [{"datetime": "2026-08-03T06:00:00+00:00", "condition": "rainy",
             "temperature": 78.4, "templow": 61.2, "precipitation_probability": 60}]


def scenario_unwraps_service_response():
    orig = ha_api.call_service
    ha_api.call_service = lambda *a, **kw: {
        "changed_states": [],
        "service_response": {"weather.home": {"forecast": FORECAST}}}
    try:
        out = ha_api.get_weather_forecast("weather.home")
        check(out == FORECAST, f"forecast list unwrapped from the wrapper, got {out}")
    finally:
        ha_api.call_service = orig


def scenario_auto_detects_first_weather_entity():
    orig_call, orig_ents = ha_api.call_service, ha_api.get_entities
    seen = {}
    ha_api.get_entities = lambda d: [{"entity_id": "weather.forecast_home", "name": "Home", "state": "sunny"}]
    def fake_call(domain, service, data=None, return_response=False):
        seen.update(data or {})
        return {"service_response": {"weather.forecast_home": {"forecast": FORECAST}}}
    ha_api.call_service = fake_call
    try:
        out = ha_api.get_weather_forecast(None)
        check(seen.get("entity_id") == "weather.forecast_home", "auto-detected entity is requested")
        check(out == FORECAST, "auto-detected entity's forecast returned")
    finally:
        ha_api.call_service, ha_api.get_entities = orig_call, orig_ents


def scenario_degrades_to_empty():
    orig_call, orig_ents = ha_api.call_service, ha_api.get_entities
    try:
        ha_api.get_entities = lambda d: []
        check(ha_api.get_weather_forecast(None) == [], "no weather entities -> []")
        ha_api.call_service = lambda *a, **kw: None
        check(ha_api.get_weather_forecast("weather.home") == [], "HA unreachable -> []")
        ha_api.call_service = lambda *a, **kw: {"service_response": {}}
        check(ha_api.get_weather_forecast("weather.home") == [], "entity missing from response -> []")
        ha_api.call_service = lambda *a, **kw: (_ for _ in ()).throw(ValueError("boom"))
        check(ha_api.get_weather_forecast("weather.home") == [], "exception swallowed -> []")
    finally:
        ha_api.call_service, ha_api.get_entities = orig_call, orig_ents


SCENARIOS = [
    scenario_unwraps_service_response,
    scenario_auto_detects_first_weather_entity,
    scenario_degrades_to_empty,
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
