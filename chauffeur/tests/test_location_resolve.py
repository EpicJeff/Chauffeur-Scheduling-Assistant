"""Tests for resolve_routable_location: agent-created events/errands carry
bare venue names ("Mills Park Middle School") that the solver can't route to;
creation paths now resolve them to full addresses via the geocoder
(cache-backed, Mapbox/Nominatim mocked here).

Run from chauffeur/:  python tests/test_location_resolve.py
"""
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import maps, storage


VENUE = "Mills Park Middle School"
ADDRESS = "Mills Park Middle School, 441 Mills Park Dr, Cary, North Carolina 27519, United States"


def _clear_cache():
    with storage.db_lock:
        storage.geocode_cache_table.truncate()


def scenario_resolves_venue_to_address():
    _clear_cache()
    with mock.patch.object(maps, '_geocode_address_api_lookup',
                           return_value=(35.78, -78.88, ADDRESS)) as api:
        out = maps.resolve_routable_location(VENUE)
        check(out == ADDRESS, f"venue resolved to the geocoder display name, got {out}")
        check(api.call_count == 1, "one API lookup")
        # second call hits the geocode cache, no new API request
        out2 = maps.resolve_routable_location(VENUE)
        check(out2 == ADDRESS and api.call_count == 1,
              "second resolve served from the geocode cache")


def scenario_prepends_name_when_display_lacks_it():
    _clear_cache()
    with mock.patch.object(maps, '_geocode_address_api_lookup',
                           return_value=(35.78, -78.88, "441 Mills Park Dr, Cary, NC")):
        out = maps.resolve_routable_location(VENUE)
        check(out == f"{VENUE}, 441 Mills Park Dr, Cary, NC",
              f"venue name kept when the display name lacks it, got {out}")


def scenario_passthroughs():
    _clear_cache()
    with mock.patch.object(maps, '_geocode_address_api_lookup') as api:
        check(maps.resolve_routable_location("441 Mills Park Dr, Cary NC") == "441 Mills Park Dr, Cary NC",
              "anything with a digit (street number) passes through untouched")
        check(maps.resolve_routable_location("Field 3") == "Field 3",
              "ambiguous venue-with-digit passes through untouched")
        check(maps.resolve_routable_location(None) is None, "None preserved")
        check(maps.resolve_routable_location("") == "", "empty preserved")
        check(api.call_count == 0, "no API calls for passthroughs")
    # geocoder failure -> original string, never an error
    with mock.patch.object(maps, '_geocode_address_api_lookup', return_value=None):
        check(maps.resolve_routable_location("Narnia Community Center") == "Narnia Community Center",
              "unresolvable location passes through unchanged")


def scenario_chat_create_event_resolves_location():
    from services import chat_actions
    from services import calendar as gcal
    _clear_cache()
    bodies = []

    def fake_insert(cal_id, body):
        bodies.append(body)
        return "gid123"

    orig_settings = storage.get_settings
    storage.get_settings = lambda: {"default_calendar_id": "fam@cal"}
    try:
        with mock.patch.object(gcal, 'insert_event', side_effect=fake_insert), \
             mock.patch.object(gcal, 'get_calendar_timezone', return_value="America/New_York"), \
             mock.patch.object(maps, '_geocode_address_api_lookup',
                               return_value=(35.78, -78.88, ADDRESS)):
            res = chat_actions._create_event({
                "title": "Band Concert",
                "start": "2026-08-10T18:00:00", "end": "2026-08-10T19:00:00",
                "location": VENUE,
            })
        check(res.get("status") == "success", f"event created, got {res}")
        check(bodies and bodies[0]["location"] == ADDRESS,
              f"chat-created event stored the resolved address, got {bodies[0].get('location')}")
    finally:
        storage.get_settings = orig_settings


def scenario_agent_errand_resolves_location():
    from services import agent_tools
    _clear_cache()
    with storage.db_lock:
        storage.errands_table.truncate()
    with mock.patch.object(maps, '_geocode_address_api_lookup',
                           return_value=(35.78, -78.88, ADDRESS)):
        res = agent_tools.handle_add_errand({"title": "Drop off forms", "location": VENUE})
    check(res.get("status") == "success", f"errand added, got {res}")
    errands = storage.get_all_errands()
    check(errands and errands[0]["location"] == ADDRESS,
          f"agent errand stored the resolved address, got {errands[0].get('location')}")
    with storage.db_lock:
        storage.errands_table.truncate()


SCENARIOS = [
    scenario_resolves_venue_to_address,
    scenario_prepends_name_when_display_lacks_it,
    scenario_passthroughs,
    scenario_chat_create_event_resolves_location,
    scenario_agent_errand_resolves_location,
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
