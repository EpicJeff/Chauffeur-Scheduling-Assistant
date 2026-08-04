"""Tests for geocode cache precision & self-healing (v2.56.4).

The bug these guard against: a single failed street-level geocode used to
cache the CITY-CENTER coordinates under the full home address permanently —
silently relocating home for every downstream feature (solver proximity
bias, car-stop placement, the station picker) with no retry and no signal.

Load-bearing properties: exact hits are final and cost no API calls;
city-fallback entries are marked precision='city', reused same-day, and
retried at street level after a day; legacy pre-precision poisoned rows are
SNIFFED (address starts with a house number the display_name lacks) and
healed on the very next lookup; failures retry daily instead of never; a
stale city hit is never downgraded to a hard failure.

Run from chauffeur/:  python tests/test_geocode_cache.py
"""
import time
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, maps

# Mapbox-canonical 4-part shape: the city/state fallback (last 3 components)
# is then a genuinely different query than the full address.
HOME = "123 Willow Creek Dr, Claybourne, North Carolina 27510, United States"
EXACT = (35.9101, -79.0753, "123 Willow Creek Dr, Claybourne, North Carolina 27510, United States")
CITY = (35.9049, -79.0469, "Claybourne, North Carolina, United States")


def _reset():
    with storage.db_lock:
        storage.geocode_cache_table.truncate()
        storage.settings_table.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}


def scenario_exact_hit_is_final():
    _reset()
    storage.set_cached_geocode(HOME, EXACT[0], EXACT[1], EXACT[2])
    with mock.patch.object(maps, '_geocode_address_api_lookup') as api:
        coords = maps.geocode_address(HOME)
        check(coords == (EXACT[0], EXACT[1]), f"exact cache hit, got {coords}")
        check(api.call_count == 0, "exact hits never touch the API")


def scenario_city_fallback_is_marked_and_healed():
    _reset()
    # street lookup down -> city fallback caches with precision='city'
    with mock.patch.object(maps, '_geocode_address_api_lookup',
                           side_effect=lambda a: CITY if a.startswith("Claybourne") else None):
        coords = maps.geocode_address(HOME)
    check(coords == (CITY[0], CITY[1]), f"city fallback still answers, got {coords}")
    row = storage.get_cached_geocode(HOME)
    check(row and row.get('precision') == 'city',
          f"city coords under the home key are MARKED, got {row}")
    # same day: reused without an API call — no spam
    with mock.patch.object(maps, '_geocode_address_api_lookup') as api:
        check(maps.geocode_address(HOME) == (CITY[0], CITY[1]), "same-day reuse")
        check(api.call_count == 0, "no same-day retry spam")
    # a day later: retried at street level and UPGRADED to exact
    with storage.db_lock:
        storage.geocode_cache_table.update(
            {'ts': time.time() - maps.GEOCODE_RETRY_SECS - 60},
            storage.Query().address == HOME.strip().lower())
    with mock.patch.object(maps, '_geocode_address_api_lookup', return_value=EXACT):
        coords = maps.geocode_address(HOME)
    check(coords == (EXACT[0], EXACT[1]), f"stale city entry retries street level, got {coords}")
    row = storage.get_cached_geocode(maps.extract_street_address(HOME))
    check(row and (row.get('precision') or 'exact') == 'exact', "healed to exact")


def scenario_legacy_poisoned_row_sniffed_and_healed():
    _reset()
    # a pre-precision row: city coords + city display_name under the FULL
    # address (exactly what the old permanent fallback wrote)
    with storage.db_lock:
        storage.geocode_cache_table.upsert(
            {'address': HOME.strip().lower(), 'lat': CITY[0], 'lon': CITY[1],
             'display_name': CITY[2]},
            storage.Query().address == HOME.strip().lower())
        storage.geocode_cache_table.upsert(
            {'address': maps.extract_street_address(HOME).strip().lower(),
             'lat': CITY[0], 'lon': CITY[1], 'display_name': CITY[2]},
            storage.Query().address == maps.extract_street_address(HOME).strip().lower())
    with mock.patch.object(maps, '_geocode_address_api_lookup', return_value=EXACT) as api:
        coords = maps.geocode_address(HOME)
    check(coords == (EXACT[0], EXACT[1]),
          f"legacy poisoned row is sniffed (house number missing from "
          f"display_name) and healed IMMEDIATELY, got {coords}")
    check(api.call_count >= 1, "the heal actually re-queried")
    # legitimate legacy exact rows are untouched: display_name contains the number
    _reset()
    with storage.db_lock:
        storage.geocode_cache_table.upsert(
            {'address': HOME.strip().lower(), 'lat': EXACT[0], 'lon': EXACT[1],
             'display_name': EXACT[2]},
            storage.Query().address == HOME.strip().lower())
    with mock.patch.object(maps, '_geocode_address_api_lookup') as api:
        check(maps.geocode_address(HOME) == (EXACT[0], EXACT[1]), "legacy exact kept")
        check(api.call_count == 0, "no needless re-query of good legacy rows")


def scenario_failure_retries_daily_and_city_survives_outage():
    _reset()
    with mock.patch.object(maps, '_geocode_address_api_lookup', return_value=None) as api:
        check(maps.geocode_address("Nowhere Special") is None, "total failure -> None")
        first_calls = api.call_count
    with mock.patch.object(maps, '_geocode_address_api_lookup') as api:
        check(maps.geocode_address("Nowhere Special") is None, "failure cached")
        check(api.call_count == 0, "no same-day failure spam")
    with storage.db_lock:
        storage.geocode_cache_table.update(
            {'ts': time.time() - maps.GEOCODE_RETRY_SECS - 60},
            storage.Query().address == "nowhere special")
    with mock.patch.object(maps, '_geocode_address_api_lookup',
                           return_value=(1.0, 2.0, "Nowhere Special, Found")) as api:
        check(maps.geocode_address("Nowhere Special") == (1.0, 2.0),
              "a day later the failure is retried and can recover")
    # stale city entry + full outage: keep the city coords, never hard-fail
    _reset()
    storage.set_cached_geocode(HOME, CITY[0], CITY[1], CITY[2], precision='city')
    with storage.db_lock:
        storage.geocode_cache_table.update(
            {'ts': time.time() - maps.GEOCODE_RETRY_SECS - 60},
            storage.Query().address == HOME.strip().lower())
    with mock.patch.object(maps, '_geocode_address_api_lookup', return_value=None):
        check(maps.geocode_address(HOME) == (CITY[0], CITY[1]),
              "outage during a retry keeps the stale city coords (beats None)")


def scenario_settings_save_purges_suspect_home():
    _reset()
    import main
    from models.schemas import Settings
    from fastapi import BackgroundTasks
    # home unchanged across the save — the purge must hinge on precision
    storage.get_settings = lambda: {"calendar_ids": ["primary"], "home_location": HOME}
    storage.set_cached_geocode(HOME, CITY[0], CITY[1], CITY[2], precision='city')
    with mock.patch.object(main, 'trigger_background_refresh'):
        main.update_settings(Settings(calendar_ids=["primary"], home_location=HOME),
                             BackgroundTasks())
    check(storage.get_cached_geocode(HOME) is None,
          "re-saving settings purges a non-exact home geocode (the fresh-lookup lever)")
    # an exact home entry survives a plain settings save
    storage.get_settings = lambda: {"calendar_ids": ["primary"], "home_location": HOME}
    storage.set_cached_geocode(HOME, EXACT[0], EXACT[1], EXACT[2])
    with mock.patch.object(main, 'trigger_background_refresh'):
        main.update_settings(Settings(calendar_ids=["primary"], home_location=HOME),
                             BackgroundTasks())
    check(storage.get_cached_geocode(HOME) is not None,
          "an exact home entry is NOT purged on ordinary saves")


def scenario_extract_street_address_keeps_leading_house_number():
    """THE root cause of home-at-city-center: a Mapbox-canonical address is
    4 comma parts, and the old >3-parts heuristic dropped the first part as
    a 'business name' — amputating the street line itself."""
    e = maps.extract_street_address
    check(e("123 Willow Creek Dr, Claybourne, North Carolina 27510, United States")
          == "123 Willow Creek Dr, Claybourne, North Carolina 27510, United States",
          "Mapbox-canonical home address keeps its street line")
    check(e("123 Main St, Claybourne, NC 27510") == "123 Main St, Claybourne, NC 27510",
          "3-part addresses unchanged")
    check(e("Fun Palace, 123 Main St, Claybourne, NC 27510")
          == "123 Main St, Claybourne, NC 27510",
          "business-name prefix is still stripped")
    check(e("Willow Apartments, Building C, Claybourne, NC, USA")
          == "Building C, Claybourne, NC, USA",
          "digit-less >3-part addresses keep the old drop-first behavior")


def scenario_heal_migration_purges_poison_and_resets_caches():
    _reset()
    q = storage.Query()
    with storage.db_lock:
        # poisoned: digit-leading address, display_name lacks the number
        storage.geocode_cache_table.upsert(
            {'address': HOME.strip().lower(), 'lat': CITY[0], 'lon': CITY[1],
             'display_name': CITY[2]}, q.address == HOME.strip().lower())
        # healthy exact row must survive
        storage.geocode_cache_table.upsert(
            {'address': '456 oak ln, claybourne, nc', 'lat': 35.9, 'lon': -79.1,
             'display_name': '456 Oak Ln, Claybourne, NC'},
            q.address == '456 oak ln, claybourne, nc')
        # non-street rows (city queries) survive too
        storage.geocode_cache_table.upsert(
            {'address': 'claybourne, nc', 'lat': CITY[0], 'lon': CITY[1],
             'display_name': CITY[2]}, q.address == 'claybourne, nc')
        storage.distance_cache_table.insert(
            {'origin': 'x', 'destination': 'y', 'duration': 12})
    removed = storage.heal_amputated_geocodes()
    check(removed == 1, f"exactly the poisoned street row is purged, got {removed}")
    with storage.db_lock:
        left = {r.get('address') for r in storage.geocode_cache_table.all()}
        check(left == {'456 oak ln, claybourne, nc', 'claybourne, nc'},
              f"healthy + city rows survive, got {left}")
        check(len(storage.distance_cache_table.all()) == 0,
              "travel-time cache reset — durations re-derive from healed coords")


def scenario_debug_travel_forensics():
    _reset()
    import main
    storage.get_settings = lambda: {"calendar_ids": ["primary"], "home_location": HOME}
    storage.set_cached_geocode(HOME, EXACT[0], EXACT[1], EXACT[2])
    dest = "Music Studio, 9 Elm St, Claybourne, NC"
    storage.set_cached_geocode(maps.extract_street_address(dest), 35.95, -79.10,
                               "9 Elm St, Claybourne, NC")
    storage.set_cached_schedule({
        "events": [{"id": "g", "title": "Guitar Lesson", "location": dest,
                    "start": "2026-08-04T15:00:00", "end": "2026-08-04T15:30:00"}],
        "assignments": {}, "matched_rules": {}, "scheduled_errands": []})
    with mock.patch.object(storage, 'get_cached_travel_time', return_value=9):
        out = main.debug_travel(event="guitar")
    check(out["event"] == "Guitar Lesson" and out["destination"]["raw"] == dest,
          f"?event= resolves the destination from the schedule, got {out['event']}")
    check(out["origin"]["resolved_to"] == EXACT[2]
          and out["destination"]["resolved_to"] == "9 Elm St, Claybourne, NC",
          "both sides show what they RESOLVED to")
    check(out["cached_matrix_mins"] == 9 and out["straight_line_km"] is not None,
          f"cached duration + straight-line sanity number, got {out}")
    # an event with no location says so instead of pretending
    storage.set_cached_schedule({
        "events": [{"id": "g", "title": "Guitar Lesson", "location": "",
                    "start": "2026-08-04T15:00:00", "end": "2026-08-04T15:30:00"}],
        "assignments": {}, "matched_rules": {}, "scheduled_errands": []})
    out = main.debug_travel(event="guitar")
    check("NO location" in out.get("problem", ""),
          "location-less events are named as the problem, not routed anyway")


SCENARIOS = [
    scenario_extract_street_address_keeps_leading_house_number,
    scenario_heal_migration_purges_poison_and_resets_caches,
    scenario_debug_travel_forensics,
    scenario_exact_hit_is_final,
    scenario_city_fallback_is_marked_and_healed,
    scenario_legacy_poisoned_row_sniffed_and_healed,
    scenario_failure_retries_daily_and_city_survives_outage,
    scenario_settings_save_purges_suspect_home,
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
