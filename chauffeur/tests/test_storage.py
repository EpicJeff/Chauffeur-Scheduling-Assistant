"""Characterization tests for services/storage.py.

Pins the exact observable behavior of the storage layer so the TinyDB -> SQLite
engine swap can prove "no behavior change": the same suite must pass against
both backends (select with CHAUFFEUR_STORAGE=tinydb|sqlite).

Run from chauffeur/:  python tests/test_storage.py
No network, never touches data/ — a temp dir is injected via CHAUFFEUR_DATA_DIR
before services.storage is imported.
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_storage_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from tinydb import Query  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    """Empty every table between scenarios; reset in-process caches."""
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


# --- drivers -----------------------------------------------------------------

def scenario_drivers_crud():
    d1 = storage.add_driver({"name": "Alice", "address": "1 Main St"})
    d2 = storage.add_driver({"name": "Bob", "hashtags": ["#bob"]})
    check(isinstance(d1, int) and isinstance(d2, int), "add_driver must return int doc_id")
    check(d1 != d2, "doc_ids must be unique")

    drivers = storage.get_all_drivers()
    check(len(drivers) == 2, f"expected 2 drivers, got {len(drivers)}")
    alice = next(d for d in drivers if d["name"] == "Alice")
    check(alice["doc_id"] == d1, "doc_id key must match insert return")
    check(alice["hashtags"] == [], "missing hashtags must default to [] in result")
    bob = next(d for d in drivers if d["name"] == "Bob")
    check(bob["hashtags"] == ["#bob"], "existing hashtags preserved")

    # the hashtags default is presentation-only: not persisted to the table
    raw_alice = next(r for r in storage.drivers_table.all() if r["name"] == "Alice")
    check("hashtags" not in raw_alice, "get_all_drivers must not persist the hashtags default")

    storage.delete_driver(d1)
    drivers = storage.get_all_drivers()
    check(len(drivers) == 1 and drivers[0]["name"] == "Bob", "delete_driver removes the right doc")


def scenario_driver_write_invalidates_caches():
    storage.set_cached_schedule({"events": [{"id": "e1"}]})
    storage.save_custom_schedule("2026-01-01", "2026-01-07", {"legs": []}, "h1")
    storage.save_cached_daily_schedule("2026-01-01", {"legs": []}, "h1")
    check(storage.get_cached_schedule() != {}, "precondition: schedule cache set")

    storage.add_driver({"name": "C"})
    check(storage.get_cached_schedule() == {}, "add_driver must clear schedule cache")
    check(storage.get_custom_schedule("2026-01-01", "2026-01-07") is None,
          "add_driver must truncate custom schedules")
    daily = storage.get_cached_daily_schedule("2026-01-01")
    check(daily is not None and daily["events_hash"] == "DIRTY",
          "add_driver must mark daily schedules DIRTY (not delete them)")
    check(daily["schedule"] == {"legs": []}, "dirty-marking must preserve the schedule payload")


# --- passengers --------------------------------------------------------------

def scenario_passengers_crud_and_hashtag_migration():
    p1 = storage.add_passenger({"name": "Kid", "hashtag": "#kid"})
    result = storage.get_all_passengers()
    check(len(result) == 1, "one passenger expected")
    doc = result[0]
    check(doc["hashtags"] == ["#kid"], f"hashtag must migrate to hashtags list, got {doc}")
    check("hashtag" not in doc, "returned doc must not contain legacy 'hashtag' key")
    check(doc["doc_id"] == p1, "doc_id present")

    # actual persisted shape after migration: hashtags list + hashtag None left behind
    raw = storage.get_passengers()[0]
    check(raw.get("hashtags") == ["#kid"], "hashtags persisted")
    check("hashtag" in raw and raw["hashtag"] is None, "legacy key persisted as None (current behavior)")

    # second read is stable (no duplicate hashtag appends)
    doc2 = storage.get_all_passengers()[0]
    check(doc2["hashtags"] == ["#kid"], "migration must be idempotent across reads")

    storage.update_passenger(p1, {"name": "Kid2"})
    check(storage.get_passengers()[0]["name"] == "Kid2", "update_passenger merges fields")
    check(storage.get_passengers()[0].get("hashtags") == ["#kid"], "update must not drop other fields")

    storage.delete_passenger(p1)
    check(storage.get_all_passengers() == [], "delete_passenger removes doc")


# --- rules -------------------------------------------------------------------

def scenario_rules_crud_and_automigration():
    rid = storage.add_rule({"constraint_type": "required", "event_keyword": "soccer",
                            "driver_names": ["Alice"]})
    rules = storage.get_all_rules()
    check(len(rules) == 1, "one rule expected")
    r = rules[0]
    check(r["doc_id"] == rid, "doc_id present")
    check(r["keywords"] == ["soccer"], "event_keyword must migrate into keywords")
    check(r["event_keyword"] is None, "event_keyword nulled after migration")
    check(r["passenger_ids"] == [] and r["days_of_week"] == [], "list defaults added")
    check(r["time_start"] is None and r["time_end"] is None, "time defaults added")

    # migration persists to the table
    raw = storage.rules_table.all()[0]
    check(raw["keywords"] == ["soccer"], "migration persisted")

    # update merges (does not replace whole doc)
    storage.update_rule(rid, {"driver_names": ["Bob"]})
    r = storage.get_all_rules()[0]
    check(r["driver_names"] == ["Bob"], "update applied")
    check(r["keywords"] == ["soccer"], "update must preserve unspecified fields")

    storage.delete_rule(rid)
    check(storage.get_all_rules() == [], "delete_rule removes doc")


def scenario_rules_dedup():
    base = {"constraint_type": "required", "keywords": ["a", "b"], "passenger_ids": [],
            "days_of_week": [], "time_start": None, "time_end": None, "created_at": 111}
    rid = storage.add_rule(dict(base))
    # identical modulo created_at + list order -> deduped, returns existing id
    dup = dict(base, created_at=999, keywords=["b", "a"])
    rid2 = storage.add_rule(dup)
    check(rid2 == rid, "duplicate rule must return existing doc_id")
    check(len(storage.rules_table.all()) == 1, "no second row inserted")

    rid3 = storage.add_rule(dict(base, keywords=["c"]))
    check(rid3 != rid, "different rule inserts a new row")


def scenario_purge_duplicate_rules():
    storage.rules_table.insert({"constraint_type": "x", "keywords": ["k"]})
    storage.rules_table.insert({"constraint_type": "x", "keywords": ["k"]})
    storage.rules_table.insert({"constraint_type": "y", "keywords": []})
    storage.priority_rules_table.insert({"driver_name": "A", "priority": 1})
    storage.priority_rules_table.insert({"driver_name": "A", "priority": 1})
    storage.purge_duplicate_rules()
    check(len(storage.rules_table.all()) == 2, "rules duplicates purged")
    check(len(storage.priority_rules_table.all()) == 1, "priority duplicates purged")


def scenario_migrate_duplicate_rules():
    storage.rules_table.insert({"constraint_type": "mutually_exclusive", "keywords": ["k"]})
    storage.rules_table.insert({"constraint_type": "ignore_mutually_exclusive", "keywords": ["j"]})
    storage.migrate_duplicate_rules()
    rules = {r["keywords"][0]: r for r in storage.rules_table.all()}
    check(rules["k"]["constraint_type"] == "duplicate" and rules["k"]["duplicate_action"] == "schedule_one",
          "mutually_exclusive migrates to duplicate/schedule_one")
    check(rules["j"]["constraint_type"] == "duplicate" and rules["j"]["duplicate_action"] == "schedule_all",
          "ignore_mutually_exclusive migrates to duplicate/schedule_all")


def scenario_migrate_passengers_from_settings():
    storage.update_settings({
        "calendar_ids": [],
        "passenger_calendar_ids": ["cal1"],
        "calendar_metadata": {"cal1": {"summary": "Kid One"}},
    })
    storage.migrate_passengers_from_settings()
    passengers = storage.get_passengers()
    check(len(passengers) == 1, "one passenger migrated")
    p = passengers[0]
    check(p["name"] == "Kid One" and p["hashtag"] == "#kidone" and p["calendar_ids"] == ["cal1"],
          f"migrated passenger shape wrong: {p}")
    # NB: the code pops passenger_calendar_ids then calls update(), but TinyDB
    # update() merges, so the key actually survives in the stored settings.
    # Re-migration is prevented by the already_migrated calendar check instead.
    check(storage.get_settings().get("passenger_calendar_ids") == ["cal1"],
          "passenger_calendar_ids survives in settings (merge-update semantics)")
    # re-running must not duplicate
    storage.migrate_passengers_from_settings()
    check(len(storage.get_passengers()) == 1, "migration idempotent")


# --- priority rules ----------------------------------------------------------

def scenario_priority_rules():
    rid = storage.add_priority_rule({"match_type": "keyword", "match_value": "piano",
                                     "driver_name": "Alice", "priority": 1})
    rules = storage.get_all_priority_rules()
    check(len(rules) == 1, "one priority rule")
    r = rules[0]
    check(r["keywords"] == ["piano"], "keyword match_value migrates into keywords")
    check(r["match_value"] == "piano", "match_value itself is preserved")
    check(r["passenger_ids"] == [] and r["days_of_week"] == [], "defaults added")
    check(r["time_start"] is None and r["time_end"] is None, "time defaults added")

    storage.update_priority_rule(rid, {"priority": 5})
    r = storage.get_all_priority_rules()[0]
    check(r["priority"] == 5 and r["driver_name"] == "Alice", "update merges")

    storage.delete_priority_rule(rid)
    check(storage.get_all_priority_rules() == [], "deleted")


# --- errand rules / themes / overrides ----------------------------------------

def scenario_errand_rules():
    rid = storage.add_errand_rule({"name": "groceries", "max_per_day": 2})
    rules = storage.get_all_errand_rules()
    check(len(rules) == 1 and rules[0]["doc_id"] == rid, "errand rule inserted")
    storage.update_errand_rule(rid, {"max_per_day": 3})
    check(storage.get_all_errand_rules()[0]["max_per_day"] == 3, "errand rule updated")
    check(storage.get_all_errand_rules()[0]["name"] == "groceries", "update merges")
    storage.delete_errand_rule(rid)
    check(storage.get_all_errand_rules() == [], "errand rule deleted")


def scenario_themes():
    tid = storage.add_theme({"name": "default", "primary_driver_bonus_multiplier": 1.0})
    themes = storage.get_all_themes()
    check(len(themes) == 1 and themes[0]["doc_id"] == tid, "theme inserted")
    storage.update_theme(tid, {"name": "fast"})
    t = storage.get_all_themes()[0]
    check(t["name"] == "fast" and t["primary_driver_bonus_multiplier"] == 1.0, "theme update merges")
    storage.delete_theme(tid)
    check(storage.get_all_themes() == [], "theme deleted")


def scenario_overrides():
    oid = storage.add_override({"event_id": "ev1", "driver_name": "Alice"})
    check(len(storage.get_all_overrides()) == 1, "override added")
    # overrides are unique per event_id: adding again replaces
    oid2 = storage.add_override({"event_id": "ev1", "driver_name": "Bob"})
    overrides = storage.get_all_overrides()
    check(len(overrides) == 1 and overrides[0]["driver_name"] == "Bob",
          "second add_override for same event replaces the first")
    check(oid2 != oid or len(overrides) == 1, "replacement produced a single row")

    storage.delete_override(overrides[0]["doc_id"])
    check(storage.get_all_overrides() == [], "delete_override by doc_id")

    # prefix deletion: matches exact id and id + '_' suffixes, not other prefixes
    storage.add_override({"event_id": "ev1", "driver_name": "A"})
    storage.add_override({"event_id": "ev1_20260101", "driver_name": "B"})
    storage.add_override({"event_id": "ev12", "driver_name": "C"})
    storage.delete_override_by_event("ev1")
    remaining = storage.get_all_overrides()
    check(len(remaining) == 1 and remaining[0]["event_id"] == "ev12",
          f"delete_override_by_event must remove exact + underscore-suffixed ids only, left {remaining}")


# --- conversations -----------------------------------------------------------

def scenario_conversations():
    now = time.time()
    storage.create_conversation({"id": "c1", "title": "Chat", "messages": [], "updated_at": now})
    conv = storage.get_conversation("c1")
    check(conv is not None and conv["title"] == "Chat", "get_conversation by id")
    check(storage.get_conversation("nope") is None, "missing conversation -> None")

    storage.add_message_to_conversation("c1", {"role": "user", "content": "hi"})
    conv = storage.get_conversation("c1")
    check(conv["messages"] == [{"role": "user", "content": "hi"}], "message appended")
    check(conv["updated_at"] >= now, "updated_at bumped")

    storage.add_message_to_conversation("ghost", {"role": "user", "content": "x"})
    check(storage.get_conversation("ghost") is None, "message to unknown conv is a silent no-op")

    storage.update_conversation_title("c1", "Renamed")
    check(storage.get_conversation("c1")["title"] == "Renamed", "title updated")

    storage.update_conversation("c1", {"pinned": True})
    conv = storage.get_conversation("c1")
    check(conv.get("pinned") is True and conv["title"] == "Renamed", "update_conversation merges")

    # 30-day retention: old conversations are pruned on read
    storage.create_conversation({"id": "old", "updated_at": now - 31 * 86400})
    storage.create_conversation({"id": "ageless"})  # no updated_at -> must survive
    all_convs = storage.get_all_conversations()
    ids = {c["id"] for c in all_convs}
    check("old" not in ids, "31-day-old conversation pruned by get_all_conversations")
    check("c1" in ids and "ageless" in ids,
          "recent + missing-updated_at conversations survive pruning")

    storage.delete_conversation("c1")
    check(storage.get_conversation("c1") is None, "delete_conversation")
    storage.clear_chat_history()
    check(storage.get_all_conversations() == [], "clear_chat_history empties table")


# --- telemetry ---------------------------------------------------------------

def scenario_telemetry():
    for i in range(205):
        storage.add_telemetry_event({"timestamp": i, "event": f"e{i}"})
    events = storage.get_telemetry_events(limit=300)
    check(len(events) == 200, f"telemetry capped at 200, got {len(events)}")
    check(events[0]["timestamp"] == 204 and events[-1]["timestamp"] == 5,
          "oldest events evicted; results sorted desc by timestamp")
    top = storage.get_telemetry_events(limit=3)
    check([e["timestamp"] for e in top] == [204, 203, 202], "limit + desc order")

    storage.clear_telemetry_events()
    check(storage.get_telemetry_events() == [], "cleared")
    new_id = storage.add_telemetry_event({"timestamp": 1})
    check(new_id == 1, "doc_id counter resets after truncate (TinyDB semantics)")


# --- geocode cache -----------------------------------------------------------

def scenario_geocode_cache():
    storage.set_cached_geocode("  123 Main ST ", 40.1, -75.2, "123 Main St")
    rec = storage.get_cached_geocode("123 main st")
    check(rec is not None and rec["lat"] == 40.1 and rec["lon"] == -75.2,
          "geocode roundtrip with strip/lower normalization")
    check(rec["address"] == "123 main st", "address stored normalized")

    storage.set_cached_geocode("123 Main St", 41.0, -76.0)
    check(len(storage.geocode_cache_table.all()) == 1, "set_cached_geocode upserts (no duplicate rows)")
    check(storage.get_cached_geocode("123 main st")["lat"] == 41.0, "upsert updated in place")

    storage.set_cached_geocode("bad place", "not-a-number", 1.0)
    check(storage.get_cached_geocode("bad place") is None, "invalid coordinates refused")

    # corrupt row is deleted on read
    storage.geocode_cache_table.insert({"address": "corrupt", "lat": "abc", "lon": 1.0})
    check(storage.get_cached_geocode("corrupt") is None, "corrupt entry returns None")
    check(storage.geocode_cache_table.search(Query().address == "corrupt") == [],
          "corrupt entry deleted on read")

    check(storage.get_cached_geocode("never seen") is None, "miss -> None")


# --- distance cache ----------------------------------------------------------

def scenario_distance_cache():
    storage.set_cached_travel_time(" Home ", " School ", 15)
    check(storage.get_cached_travel_time("home", "school") == 15, "roundtrip, normalized keys")
    check(storage.get_cached_travel_time("school", "home") is None, "direction matters")
    check(storage.get_cached_travel_time("", "school") is None, "empty origin -> None")
    check(storage.get_cached_travel_time("home", None) is None, "empty destination -> None")

    storage.set_cached_travel_time("home", "school", 18)
    check(len(storage.distance_cache_table.all()) == 1, "set_cached_travel_time upserts")
    check(storage.get_cached_travel_time("home", "school") == 18, "upsert updated value")

    # age handling
    old = time.time() - 3600
    with mock.patch("time.time", return_value=old):
        storage.set_cached_travel_time("a", "b", 22)
    check(storage.get_cached_travel_time("a", "b", max_age_mins=10) is None, "stale entry -> None")
    check(storage.get_cached_travel_time("a", "b", max_age_mins=120) == 22, "within max_age -> hit")
    check(storage.get_cached_travel_time("a", "b", ignore_age=True) == 22, "ignore_age -> hit")

    # unroutable sentinel: served fresh even on default max_age, expires after TTL always
    storage.set_cached_travel_time("x", "y", storage.UNROUTABLE)
    check(storage.get_cached_travel_time("x", "y") == storage.UNROUTABLE,
          "fresh unroutable served despite default max_age")
    expired = time.time() - (storage.UNROUTABLE_TTL_MINS * 60 + 60)
    with mock.patch("time.time", return_value=expired):
        storage.set_cached_travel_time("p", "q", storage.UNROUTABLE)
    check(storage.get_cached_travel_time("p", "q", ignore_age=True) is None,
          "expired unroutable -> None even with ignore_age")

    # legacy rows carry 'minutes' instead of 'duration_mins'
    storage.distance_cache_table.insert(
        {"origin": "l1", "destination": "l2", "minutes": 12, "timestamp": time.time()})
    storage._distance_mem_cache = None
    check(storage.get_cached_travel_time("l1", "l2") == 12, "legacy 'minutes' field honored")


def scenario_distance_cache_bulk():
    entries = [{"origin": "A", "destination": "B", "duration_mins": 10},
               {"origin": "C", "destination": "D", "duration_mins": 20},
               {"origin": "", "destination": "D", "duration_mins": 5}]
    storage.set_cached_travel_times_bulk(entries)
    check(len(storage.distance_cache_table.all()) == 2, "bulk skips empty keys, inserts rest")
    check(storage.get_cached_travel_time("a", "b") == 10, "bulk entries readable (normalized)")

    # bulk is insert-not-upsert by design: duplicate rows accumulate,
    # and a fresh mem-cache init must serve the newest row for a key
    storage.set_cached_travel_times_bulk([{"origin": "A", "destination": "B", "duration_mins": 99}])
    rows = [r for r in storage.distance_cache_table.all()
            if r.get("origin") == "a" and r.get("destination") == "b"]
    check(len(rows) == 2, "bulk writes append duplicate rows (current behavior)")
    storage._distance_mem_cache = None
    check(storage.get_cached_travel_time("a", "b") == 99,
          "newest duplicate wins on mem-cache rebuild (table order dependency)")

    storage.set_cached_travel_times_bulk([])  # no-op, must not raise


# --- route geometry ----------------------------------------------------------

def scenario_route_geometry():
    geo = {"coords": [[1.0, 2.0], [3.0, 4.0]], "distance_m": 1234}
    storage.set_cached_route_geometry(" Home ", " School ", "driving", geo)
    check(storage.get_cached_route_geometry("home", "school", "driving") == geo,
          "route geometry roundtrip returns the data payload")
    check(storage.get_cached_route_geometry("home", "school", "walking") is None,
          "profile is part of the key")
    check(storage.get_cached_route_geometry("nowhere", "school", "driving") is None, "miss -> None")
    check(storage.get_cached_route_geometry("", "school", "driving") is None, "empty origin -> None")

    storage.set_cached_route_geometry("home", "school", "driving", {"coords": []})
    check(len(storage.route_geometry_cache_table.all()) == 1, "route geometry upserts")
    check(storage.get_cached_route_geometry("home", "school", "driving") == {"coords": []},
          "upsert updated payload")

    # expiry: stale row returns None and is deleted
    old = time.time() - 8 * 24 * 3600
    with mock.patch("time.time", return_value=old):
        storage.set_cached_route_geometry("far", "away", "driving", geo)
    check(storage.get_cached_route_geometry("far", "away", "driving") is None,
          "expired (default 7d) -> None")
    check(storage.route_geometry_cache_table.search(Query().origin == "far") == [],
          "expired row deleted on read")


# --- schedule caches ---------------------------------------------------------

def scenario_schedule_cache():
    check(storage.get_cached_schedule() == {}, "empty cache -> {}")
    storage.set_cached_schedule({"events": [1, 2], "generated_at": 5})
    check(storage.get_cached_schedule()["events"] == [1, 2], "roundtrip")
    storage.set_cached_schedule({"events": [3]})
    check(storage.get_cached_schedule() == {"events": [3]}, "set replaces entirely (single row)")
    check(len(storage.cache_table.all()) == 1, "cache table holds exactly one row")


def scenario_custom_schedules():
    check(storage.get_custom_schedule("2026-01-01", "2026-01-07") is None, "miss -> None")
    storage.save_custom_schedule("2026-01-01", "2026-01-07", {"days": [1]}, "h1")
    got = storage.get_custom_schedule("2026-01-01", "2026-01-07")
    check(got["schedule"] == {"days": [1]} and got["events_hash"] == "h1", "roundtrip")

    storage.save_custom_schedule("2026-01-01", "2026-01-07", {"days": [2]}, "h2")
    check(len(storage.custom_schedules_table.all()) == 1, "same range upserts")
    check(storage.get_custom_schedule("2026-01-01", "2026-01-07")["events_hash"] == "h2", "updated")

    storage.save_custom_schedule("2026-02-01", "2026-02-07", {"days": []}, "h3")
    keys = storage.get_all_custom_schedule_keys()
    check({(k["start_date"], k["end_date"]) for k in keys} ==
          {("2026-01-01", "2026-01-07"), ("2026-02-01", "2026-02-07")}, "keys listing")

    storage.save_cached_daily_schedule("2026-01-01", {"legs": []}, "hx")
    storage.clear_custom_schedules()
    check(storage.get_all_custom_schedule_keys() == [], "custom schedules cleared")
    check(storage.get_cached_daily_schedule("2026-01-01") is None,
          "clear_custom_schedules also truncates daily schedules")


def scenario_daily_schedules():
    check(storage.get_cached_daily_schedule("2026-03-01") is None, "miss -> None")
    storage.save_cached_daily_schedule(
        "2026-03-01", {"legs": [1]}, "h1",
        options=[{"o": 1}], ai_status="done", selected_index=1, llm_reasoning="because")
    d = storage.get_cached_daily_schedule("2026-03-01")
    check(d["schedule"] == {"legs": [1]} and d["options"] == [{"o": 1}]
          and d["ai_status"] == "done" and d["selected_index"] == 1
          and d["llm_reasoning"] == "because", f"full roundtrip, got {d}")

    # same hash + defaulted args: existing options/ai fields are preserved
    storage.save_cached_daily_schedule("2026-03-01", {"legs": [2]}, "h1")
    d = storage.get_cached_daily_schedule("2026-03-01")
    check(d["schedule"] == {"legs": [2]}, "schedule payload updated")
    check(d["options"] == [{"o": 1}] and d["ai_status"] == "done" and d["selected_index"] == 1
          and d["llm_reasoning"] == "because", "same-hash save preserves options and AI verdict")

    # different hash: options/ai state reset
    storage.save_cached_daily_schedule("2026-03-01", {"legs": [3]}, "h2")
    d = storage.get_cached_daily_schedule("2026-03-01")
    check(d["options"] == [] and d["ai_status"] == "evaluating" and d["selected_index"] == 0
          and d["llm_reasoning"] == "", "new-hash save resets AI state")
    check(len(storage.daily_schedules_table.all()) == 1, "per-date upsert")

    # saving a daily schedule invalidates custom range caches
    storage.save_custom_schedule("2026-03-01", "2026-03-07", {"days": []}, "hc")
    storage.save_cached_daily_schedule("2026-03-02", {"legs": []}, "h9")
    check(storage.get_all_custom_schedule_keys() == [], "daily save truncates custom schedules")

    storage.save_cached_daily_schedule(
        "2026-03-03", {"legs": [], "scheduled_errands": [{"id": "er1", "start": "2026-03-03T10:00:00"}]},
        "h3")
    errands = storage.get_all_scheduled_errands()
    check(errands == {"er1": "2026-03-03T10:00:00"}, f"scheduled errands aggregated, got {errands}")

    storage.mark_all_daily_schedules_dirty()
    for row in storage.daily_schedules_table.all():
        check(row["events_hash"] == "DIRTY", "all dirty")
        check("schedule" in row, "dirty-marking preserves other fields")


def scenario_invalidate_daily_for_event():
    def seed_daily(dates):
        for ds in dates:
            storage.save_cached_daily_schedule(ds, {"legs": []}, "CLEAN")

    # (a) no cached master schedule -> everything marked dirty
    seed_daily(["2026-07-01", "2026-07-02"])
    storage.save_custom_schedule("2026-07-01", "2026-07-02", {}, "h")
    storage.invalidate_daily_schedule_cache_for_event("evX")
    for ds in ["2026-07-01", "2026-07-02"]:
        check(storage.get_cached_daily_schedule(ds)["events_hash"] == "DIRTY",
              "no master cache -> all daily dirty")
    check(storage.get_all_custom_schedule_keys() == [], "custom schedules truncated")

    # (b) master cache contains the event -> only its dates marked dirty
    reset_db()
    seed_daily(["2026-07-01", "2026-07-02", "2026-07-03"])
    storage.set_cached_schedule({"events": [
        {"id": "ev1", "start": "2026-07-01T10:00:00", "end": "2026-07-02T11:00:00"},
        {"id": "ev2", "start": "2026-07-03T10:00:00", "end": "2026-07-03T11:00:00"},
    ]})
    storage.invalidate_daily_schedule_cache_for_event("ev1")
    check(storage.get_cached_daily_schedule("2026-07-01")["events_hash"] == "DIRTY", "day 1 dirty")
    check(storage.get_cached_daily_schedule("2026-07-02")["events_hash"] == "DIRTY",
          "multi-day event dirties every spanned day")
    check(storage.get_cached_daily_schedule("2026-07-03")["events_hash"] == "CLEAN",
          "unrelated day untouched")

    # (c) event matched via original_event_id / recurring_event_id
    reset_db()
    seed_daily(["2026-07-04"])
    storage.set_cached_schedule({"events": [
        {"id": "inst_1", "recurring_event_id": "recur9",
         "start": "2026-07-04T09:00:00", "end": "2026-07-04T10:00:00"},
    ]})
    storage.invalidate_daily_schedule_cache_for_event("recur9")
    check(storage.get_cached_daily_schedule("2026-07-04")["events_hash"] == "DIRTY",
          "recurring_event_id match dirties instance dates")

    # (d) event not present in master cache -> everything dirty
    reset_db()
    seed_daily(["2026-07-05"])
    storage.set_cached_schedule({"events": [
        {"id": "other", "start": "2026-07-06T09:00:00", "end": "2026-07-06T10:00:00"}]})
    storage.invalidate_daily_schedule_cache_for_event("missing")
    check(storage.get_cached_daily_schedule("2026-07-05")["events_hash"] == "DIRTY",
          "unknown event -> all daily dirty")


# --- settings ----------------------------------------------------------------

def scenario_settings():
    check(storage.get_settings() == {"calendar_ids": []}, "empty settings default")
    storage.update_settings({"calendar_ids": ["primary"], "theme": "dark"})
    s = storage.get_settings()
    check(s["calendar_ids"] == ["primary"] and s["theme"] == "dark", "roundtrip")

    storage.update_settings({"calendar_ids": ["primary"]})
    s = storage.get_settings()
    check("theme" not in s, "update_settings replaces the whole settings doc (truncate+insert)")
    check(len(storage.settings_table.all()) == 1, "single settings row")

    # settings writes invalidate schedule caches
    storage.save_custom_schedule("2026-01-01", "2026-01-02", {}, "h")
    storage.save_cached_daily_schedule("2026-01-01", {}, "CLEAN")
    storage.update_settings({"calendar_ids": []})
    check(storage.get_all_custom_schedule_keys() == [], "custom truncated on settings change")
    check(storage.get_cached_daily_schedule("2026-01-01")["events_hash"] == "DIRTY",
          "daily dirty on settings change")


# --- api usage ---------------------------------------------------------------

def scenario_api_usage():
    check(storage.get_mapbox_usage("2026-07", "directions") == 0, "default 0")
    storage.increment_mapbox_usage("2026-07", "directions")
    storage.increment_mapbox_usage("2026-07", "directions", amount=5)
    check(storage.get_mapbox_usage("2026-07", "directions") == 6, "increments accumulate")
    storage.increment_mapbox_usage("2026-07", "geocode")
    check(storage.get_mapbox_usage("2026-07", "geocode") == 1, "endpoints tracked separately")
    check(storage.get_mapbox_usage("2026-08", "directions") == 0, "months tracked separately")


def scenario_api_request_log():
    now = time.time()
    storage.api_requests_log_table.insert(
        {"timestamp": now - 4 * 24 * 3600, "endpoint": "directions", "count": 7})
    storage.log_api_request("directions", 2)
    storage.log_api_request("directions")
    storage.log_api_request("geocode", 4)
    rows = storage.api_requests_log_table.all()
    check(all(r["timestamp"] > now - 3.5 * 24 * 3600 for r in rows),
          "log_api_request prunes entries older than 3 days")
    check(storage.get_rolling_usage("directions", 3600) == 3, "rolling sum within window")
    check(storage.get_rolling_usage("geocode", 3600) == 4, "per-endpoint rolling sum")
    check(storage.get_rolling_usage("directions", 1) in (0, 3),
          "tiny window (timing-dependent, just must not raise)")


# --- push subscriptions / drive status / notifications ------------------------

def scenario_push_subscriptions():
    storage.save_push_subscription("d1", {"endpoint": "https://a"})
    storage.save_push_subscription("d1", {"endpoint": "https://b"})
    storage.save_push_subscription("d2", {"endpoint": "https://c"})
    check(len(storage.push_subscriptions_table.all()) == 2, "upsert per driver")
    subs = storage.get_push_subscriptions("d1")
    check(len(subs) == 1 and subs[0]["subscription"] == {"endpoint": "https://b"},
          "get by driver returns latest")
    check(len(storage.get_push_subscriptions()) == 2, "get all")


def scenario_drive_status():
    storage.mark_drive_status("leg1", "completed")
    storage.mark_drive_status("leg2", "in_progress")
    storage.mark_drive_status("leg3", "completed")
    storage.mark_drive_status("leg1", "in_progress")  # upsert flips status
    check(set(storage.get_completed_drives()) == {"leg3"}, "completed set")
    check(set(storage.get_in_progress_drives()) == {"leg1", "leg2"}, "in-progress set")


def scenario_pending_notifications():
    storage.save_pending_notifications([{"notif_id": "n1"}, {"notif_id": "n2"}])
    check(len(storage.get_pending_notifications()) == 2, "saved")
    storage.mark_notification_fired("n1")
    fired = {n["notif_id"]: n.get("fired") for n in storage.get_pending_notifications()}
    check(fired == {"n1": True, "n2": None}, "fired flag set on the right doc")
    storage.save_pending_notifications([{"notif_id": "n3"}])
    check([n["notif_id"] for n in storage.get_pending_notifications()] == ["n3"],
          "save replaces the whole set")
    storage.save_pending_notifications([])
    check(storage.get_pending_notifications() == [], "empty save clears")


# --- event configs / trip metadata / errands -----------------------------------

def scenario_event_configs():
    check(storage.get_event_config("g1") is None, "miss -> None")
    storage.set_event_config("g1", {"needs_driver": True, "buffer": 10})
    cfg = storage.get_event_config("g1")
    check(cfg["needs_driver"] is True and cfg["google_id"] == "g1", "roundtrip + key injected")

    # upsert merges: keys absent from the second write survive
    storage.set_event_config("g1", {"needs_driver": False})
    cfg = storage.get_event_config("g1")
    check(cfg["needs_driver"] is False and cfg["buffer"] == 10,
          "set_event_config merges into existing config (TinyDB upsert semantics)")
    check(len(storage.event_configs_table.all()) == 1, "one row per google_id")

    storage.delete_event_config("g1")
    check(storage.get_event_config("g1") is None, "deleted")


def scenario_trip_metadata():
    check(storage.get_trip_metadata("ev1") is None, "miss -> None")
    storage.set_trip_metadata("ev1", {"title": "Beach", "pois": [{"id": "p1"}]})
    md = storage.get_trip_metadata("ev1")
    check(md["title"] == "Beach" and md["event_id"] == "ev1", "roundtrip + event_id injected")

    storage.set_trip_metadata("ev1", {"title": "Beach 2"})
    md = storage.get_trip_metadata("ev1")
    check(md["title"] == "Beach 2" and md["pois"] == [{"id": "p1"}],
          "set_trip_metadata merges (TinyDB upsert semantics)")
    check(len(storage.trip_metadata_table.all()) == 1, "one row per event")

    storage.delete_trip_metadata("ev1")
    check(storage.get_trip_metadata("ev1") is None, "deleted")


def scenario_errands():
    eid = storage.add_errand({"title": "Pharmacy", "duration_mins": 20})
    errands = storage.get_all_errands()
    check(len(errands) == 1 and errands[0]["doc_id"] == eid, "errand inserted")
    storage.update_errand(eid, {"duration_mins": 30})
    e = storage.get_all_errands()[0]
    check(e["duration_mins"] == 30 and e["title"] == "Pharmacy", "update merges")
    storage.delete_errand(eid)
    check(storage.get_all_errands() == [], "deleted")


def scenario_ai_feedback():
    with mock.patch("time.time", side_effect=[100.0, 200.0, 300.0]):
        storage.add_ai_feedback("first")
        storage.add_ai_feedback("second")
        storage.add_ai_feedback("third")
    fb = storage.get_recent_ai_feedback(limit=2)
    check([f["context"] for f in fb] == ["third", "second"], "desc order + limit")
    check(len(storage.get_recent_ai_feedback()) == 3, "default limit returns all three")


# --- cache maintenance helpers -------------------------------------------------

def scenario_cache_maintenance():
    storage.set_cached_travel_time("a", "b", 10)
    storage.set_cached_geocode("addr", 1.0, 2.0)
    storage.set_cached_schedule({"events": []})
    storage.save_custom_schedule("2026-01-01", "2026-01-02", {}, "h")
    storage.save_cached_daily_schedule("2026-01-01", {}, "h")
    storage.clear_schedule_caches()
    for tbl in (storage.custom_schedules_table, storage.daily_schedules_table,
                storage.cache_table, storage.distance_cache_table, storage.geocode_cache_table):
        check(tbl.all() == [], "clear_schedule_caches truncates all schedule + geo caches")
    check(storage.get_cached_travel_time("a", "b") is None, "mem cache reset too")

    # purge_poisoned_caches: only the poisoned rows
    storage.distance_cache_table.insert({"origin": "a", "destination": "b", "minutes": 15})
    storage.distance_cache_table.insert({"origin": "c", "destination": "d", "minutes": 30})
    storage.geocode_cache_table.insert({"address": "zero", "lat": 0.0, "lon": 5.0})
    storage.geocode_cache_table.insert({"address": "fine", "lat": 9.0, "lon": 5.0})
    storage.purge_poisoned_caches()
    check([r["minutes"] for r in storage.distance_cache_table.all()] == [30],
          "minutes==15 rows purged, others kept")
    check([r["address"] for r in storage.geocode_cache_table.all()] == ["fine"],
          "lat==0.0 geocodes purged, others kept")

    # cleanup_corrupted_travel_times: minutes >= 120
    storage.distance_cache_table.insert({"origin": "e", "destination": "f", "minutes": 999})
    storage.cleanup_corrupted_travel_times()
    check(all(r.get("minutes", 0) < 120 for r in storage.distance_cache_table.all()),
          "minutes>=120 rows removed")


def scenario_fix_corrupted_db():
    p = os.path.join(_TMP, "corrupt_test.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"_default": {}}{"trailing": "garbage"}')
    storage.fix_corrupted_db(p)
    import json
    with open(p, "r", encoding="utf-8") as f:
        check(json.load(f) == {"_default": {}}, "extra-data corruption repaired to first object")

    with open(p, "w", encoding="utf-8") as f:
        f.write("")
    storage.fix_corrupted_db(p)  # empty file: no-op, no raise
    storage.fix_corrupted_db(os.path.join(_TMP, "does_not_exist.json"))  # no raise


# --- direct table API contract (used by main.py) -------------------------------

def scenario_table_api_contract():
    t = storage.rules_table

    i1 = t.insert({"kind": "a", "n": 1})
    i2 = t.insert({"kind": "b", "n": 2})
    ids = t.insert_multiple([{"kind": "c", "n": 3}, {"kind": "c", "n": 4}])
    check(isinstance(i1, int) and ids == [i2 + 1, i2 + 2], "insert ids are sequential ints")

    docs = t.all()
    check(len(docs) == 4, "all() returns everything")
    check(docs[0].doc_id == i1 and docs[0] == {"kind": "a", "n": 1},
          "docs expose .doc_id attr and compare equal to plain dicts")

    q = Query()
    check([d["n"] for d in t.search(q.kind == "c")] == [3, 4], "search equality")
    check(t.search(q.kind == "zzz") == [], "search no match -> []")
    check(t.search(q.missing_field == 1) == [], "missing field never matches")
    check([d["n"] for d in t.search((q.kind == "c") & (q.n == 4))] == [4], "AND query")
    check(len(t.search((q.kind == "a") | (q.kind == "b"))) == 2, "OR query")
    check([d["n"] for d in t.search(q.n >= 3)] == [3, 4], ">= comparison")
    check([d["n"] for d in t.search(q.n < 2)] == [1], "< comparison")
    check([d["n"] for d in t.search(q.kind.test(lambda v: v in ("a", "b")))] == [1, 2],
          "test() with callable predicate")

    check(t.get(q.kind == "c")["n"] == 3, "get(cond) returns first match")
    check(t.get(q.kind == "zzz") is None, "get(cond) miss -> None")
    check(t.get(doc_id=i2)["kind"] == "b", "get(doc_id=)")
    check(t.get(doc_id=99999) is None, "get missing doc_id -> None")

    # update merges fields; by cond, by doc_ids, and unconditional
    t.update({"flag": True}, q.kind == "c")
    check(all(d.get("flag") for d in t.search(q.kind == "c")), "update by cond")
    check(t.get(doc_id=i1).get("flag") is None, "update by cond leaves others alone")
    t.update({"n": 10}, doc_ids=[i1])
    check(t.get(doc_id=i1) == {"kind": "a", "n": 10}, "update by doc_ids merges")
    t.update({"seen": 1})
    check(all(d.get("seen") == 1 for d in t.all()), "update with no cond hits every row")

    try:
        t.update({"x": 1}, doc_ids=[99999])
        raised = False
    except KeyError:
        raised = True
    check(raised, "update with missing doc_id raises KeyError")

    # upsert: merge when matched, insert when not
    t.upsert({"kind": "a", "extra": 1}, q.kind == "a")
    check(t.get(doc_id=i1)["extra"] == 1 and t.get(doc_id=i1)["n"] == 10, "upsert merges on match")
    before = len(t.all())
    t.upsert({"kind": "new", "n": 99}, q.kind == "new")
    check(len(t.all()) == before + 1, "upsert inserts on no match")

    # remove: by cond, by doc_ids; missing doc_id raises
    t.remove(q.kind == "c")
    check(t.search(q.kind == "c") == [], "remove by cond")
    t.remove(doc_ids=[i1])
    check(t.get(doc_id=i1) is None, "remove by doc_ids")
    try:
        t.remove(doc_ids=[99999])
        raised = False
    except KeyError:
        raised = True
    check(raised, "remove with missing doc_id raises KeyError")

    t.truncate()
    check(t.all() == [] and t.insert({"z": 1}) == 1, "truncate empties and resets doc_id counter")


SCENARIOS = [
    scenario_drivers_crud,
    scenario_driver_write_invalidates_caches,
    scenario_passengers_crud_and_hashtag_migration,
    scenario_rules_crud_and_automigration,
    scenario_rules_dedup,
    scenario_purge_duplicate_rules,
    scenario_migrate_duplicate_rules,
    scenario_migrate_passengers_from_settings,
    scenario_priority_rules,
    scenario_errand_rules,
    scenario_themes,
    scenario_overrides,
    scenario_conversations,
    scenario_telemetry,
    scenario_geocode_cache,
    scenario_distance_cache,
    scenario_distance_cache_bulk,
    scenario_route_geometry,
    scenario_schedule_cache,
    scenario_custom_schedules,
    scenario_daily_schedules,
    scenario_invalidate_daily_for_event,
    scenario_settings,
    scenario_api_usage,
    scenario_api_request_log,
    scenario_push_subscriptions,
    scenario_drive_status,
    scenario_pending_notifications,
    scenario_event_configs,
    scenario_trip_metadata,
    scenario_errands,
    scenario_ai_feedback,
    scenario_cache_maintenance,
    scenario_fix_corrupted_db,
    scenario_table_api_contract,
]

if __name__ == "__main__":
    import traceback

    # With no explicit backend, run the whole suite once per backend in
    # subprocesses — green on both is the migration's "no behavior change" bar.
    if "CHAUFFEUR_STORAGE" not in os.environ:
        import subprocess
        worst = 0
        for be in ("tinydb", "sqlite"):
            env = dict(os.environ, CHAUFFEUR_STORAGE=be)
            print(f"=== backend: {be} ===")
            rc = subprocess.call([sys.executable, os.path.abspath(__file__)], env=env)
            worst = max(worst, rc)
        raise SystemExit(worst)

    backend = getattr(storage, "BACKEND", "tinydb")
    print(f"storage backend: {backend}  (data dir: {_TMP})")
    failed = 0
    for fn in SCENARIOS:
        try:
            reset_db()
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
