"""Tests for services/ha_api.py (Home Assistant REST client), HTTP mocked.

Run from chauffeur/:  python tests/test_ha_api.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_ha_api_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ha_api, storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset():
    for var in ("SUPERVISOR_TOKEN", "HA_BASE_URL", "HA_TOKEN"):
        os.environ.pop(var, None)
    with ha_api._cache_lock:
        ha_api._states_cache['ts'] = 0.0
        ha_api._states_cache['data'] = None
    with storage.db_lock:
        storage.settings_table.truncate()


def fake_response(payload, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.text = "x" if payload is not None else ""
    resp.json.return_value = payload
    return resp


def scenario_unconfigured_degrades():
    check(ha_api.mode() == 'unconfigured', "no token/settings -> unconfigured")
    check(ha_api._base_and_token() == (None, None), "no base/token")
    check(ha_api.get_states() == [], "get_states -> [] when unconfigured")
    check(ha_api.get_state('person.x') is None, "get_state -> None")
    check(ha_api.get_entities('person') == [], "get_entities -> []")
    check(ha_api.list_notify_services() == [], "notify services -> []")
    check(ha_api.call_service('notify', 'x') is None, "call_service -> None")
    check(ha_api.is_available() is False, "is_available -> False")


def scenario_supervisor_resolution():
    os.environ["SUPERVISOR_TOKEN"] = "sup-token"
    base, token = ha_api._base_and_token()
    check(base == 'http://supervisor/core/api' and token == 'sup-token',
          "supervisor proxy wins")
    check(ha_api.mode() == 'supervisor', "mode supervisor")


def scenario_settings_fallback_and_normalization():
    with storage.db_lock:
        storage.settings_table.insert({
            "ha_base_url": "http://homeassistant.local:8123/",
            "ha_token": "llat",
        })
    base, token = ha_api._base_and_token()
    check(base == 'http://homeassistant.local:8123/api', f"base normalized to /api, got {base}")
    check(token == 'llat', "settings token used")
    check(ha_api.mode() == 'external', "mode external")
    os.environ["SUPERVISOR_TOKEN"] = "sup"
    check(ha_api._base_and_token()[0] == 'http://supervisor/core/api',
          "supervisor still wins over settings")


def scenario_states_cache_and_stale_fallback():
    os.environ["SUPERVISOR_TOKEN"] = "t"
    states = [{"entity_id": "person.jeff", "state": "home", "attributes": {}}]
    with mock.patch.object(ha_api.requests, 'request',
                           return_value=fake_response(states)) as req:
        first = ha_api.get_states(ttl=60)
        second = ha_api.get_states(ttl=60)
        check(first == states and second == states, "states returned")
        check(req.call_count == 1, f"TTL cache must dedupe calls, got {req.call_count}")
    # HA goes down: serve the stale copy instead of []
    with ha_api._cache_lock:
        ha_api._states_cache['ts'] = 0.0  # expire TTL, keep data
    with mock.patch.object(ha_api.requests, 'request',
                           side_effect=Exception("down")):
        check(ha_api.get_states(ttl=60) == states, "stale copy served on failure")
        check(ha_api.get_state('person.jeff')['state'] == 'home', "get_state via stale cache")


def scenario_get_entities_filters_and_sorts():
    os.environ["SUPERVISOR_TOKEN"] = "t"
    states = [
        {"entity_id": "person.zed", "state": "home", "attributes": {"friendly_name": "Zed"}},
        {"entity_id": "person.amy", "state": "away", "attributes": {"friendly_name": "Amy"}},
        {"entity_id": "media_player.kitchen", "state": "idle", "attributes": {"friendly_name": "Kitchen"}},
        {"entity_id": "personal.not_a_person", "state": "x", "attributes": {}},
    ]
    with mock.patch.object(ha_api.requests, 'request', return_value=fake_response(states)):
        persons = ha_api.get_entities('person')
        check([p['entity_id'] for p in persons] == ['person.amy', 'person.zed'],
              f"person domain filtered exactly + sorted by name, got {persons}")
        players = ha_api.get_entities('media_player')
        check(len(players) == 1 and players[0]['name'] == 'Kitchen', "media_player filtered")


def scenario_notify_services_parsing():
    os.environ["SUPERVISOR_TOKEN"] = "t"
    services = [
        {"domain": "light", "services": {"turn_on": {}}},
        {"domain": "notify", "services": {"mobile_app_b": {}, "mobile_app_a": {}}},
    ]
    with mock.patch.object(ha_api.requests, 'request', return_value=fake_response(services)):
        check(ha_api.list_notify_services() == ['mobile_app_a', 'mobile_app_b'],
              "notify services sorted")
        check(ha_api.has_service('notify', 'mobile_app_a'), "has_service true")
        check(not ha_api.has_service('notify', 'nope'), "has_service false")


def scenario_call_service_payload():
    os.environ["SUPERVISOR_TOKEN"] = "sup-token"
    with mock.patch.object(ha_api.requests, 'request',
                           return_value=fake_response({"ok": True})) as req:
        result = ha_api.call_service('notify', 'mobile_app_x',
                                     {"message": "hi"})
        check(result == {"ok": True}, "service result returned")
        args, kwargs = req.call_args
        check(args == ('POST', 'http://supervisor/core/api/services/notify/mobile_app_x'),
              f"service URL, got {args}")
        check(kwargs['json'] == {"message": "hi"}, "payload passed")
        check(kwargs['params'] is None, "no return_response param by default")
        check(kwargs['headers']['Authorization'] == 'Bearer sup-token', "bearer token")

        ha_api.call_service('music_assistant', 'search', {"name": "abba"},
                            return_response=True)
        _, kwargs = req.call_args
        check(kwargs['params'] == {'return_response': 'true'}, "return_response param set")


def scenario_http_error_returns_none():
    os.environ["SUPERVISOR_TOKEN"] = "t"
    with mock.patch.object(ha_api.requests, 'request',
                           return_value=fake_response({"error": "x"}, status=401)):
        check(ha_api.call_service('notify', 'x') is None, "4xx -> None")
        check(ha_api.is_available() is False, "is_available False on 4xx")


SCENARIOS = [
    scenario_unconfigured_degrades,
    scenario_supervisor_resolution,
    scenario_settings_fallback_and_normalization,
    scenario_states_cache_and_stale_fallback,
    scenario_get_entities_filters_and_sorts,
    scenario_notify_services_parsing,
    scenario_call_service_payload,
    scenario_http_error_returns_none,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            reset()
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    reset()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
