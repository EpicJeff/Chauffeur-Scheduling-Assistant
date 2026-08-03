"""Tests for prep kits (services/prep_kits.py).

Kits are rule-filtered packing lists: matching delegates to the solver's
does_event_match_rule, so the scenarios verify routing-rule semantics
(keywords any/all, passenger resolution via calendar ids, days of week,
time/date windows, location), item dedup across kits, storage CRUD, and the
suggest normalization layer (LLM mocked).

Run from chauffeur/:  python tests/test_prep_kits.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import prep_kits, storage


def _ev(**kw):
    base = {"title": "Addison Soccer Practice", "start": "2026-08-05T16:00:00",
            "end": "2026-08-05T17:00:00", "location": "City Fields",
            "calendar_ids": ["addison@cal"]}
    base.update(kw)
    return base


def _kit(**kw):
    base = {"id": "k1", "name": "Soccer", "enabled": True,
            "items": ["Cleats", "Shin Guards", "Water Bottle"], "keywords": ["soccer"]}
    base.update(kw)
    return base


def scenario_keyword_matching():
    kits = [_kit(), _kit(id="k2", name="Swim", keywords=["swim", "pool"],
                  items=["Goggles", "Towel", "Water Bottle"]),
            _kit(id="k3", name="Old", items=["Ancient Boots"], enabled=False)]
    m = prep_kits.match_kits_for_event(_ev(), kits)
    check([k["id"] for k in m] == ["k1"],
          "case-insensitive substring match; disabled kit skipped")
    check(prep_kits.match_kits_for_event(_ev(title="Piano Lesson"), kits) == [],
          "no keyword hit = no kits")
    check([k["id"] for k in prep_kits.match_kits_for_event(_ev(title="POOL PARTY"), kits)] == ["k2"],
          "any-keyword (second keyword) matches, case folded both ways")
    # match-all keywords: routing-rule AND semantics
    both = [_kit(keywords=["soccer", "game"], keywords_match_all=True)]
    check(prep_kits.match_kits_for_event(_ev(title="Soccer practice"), both) == [],
          "match-all needs every keyword")
    check(len(prep_kits.match_kits_for_event(_ev(title="Soccer GAME"), both)) == 1,
          "match-all satisfied by every keyword present")


def scenario_rule_filters():
    # Days of week (2026-08-05 is a Wednesday = 2)
    wed = [_kit(days_of_week=[2])]
    check(len(prep_kits.match_kits_for_event(_ev(), wed)) == 1, "day-of-week hit")
    check(prep_kits.match_kits_for_event(_ev(start="2026-08-06T16:00:00", end="2026-08-06T17:00:00"),
                                         wed) == [], "Thursday event misses a Wed-only kit")
    # Time window: event must start at/after time_start and end at/before time_end
    tw = [_kit(time_start="15:00", time_end="18:00")]
    check(len(prep_kits.match_kits_for_event(_ev(), tw)) == 1, "inside time window")
    check(prep_kits.match_kits_for_event(_ev(start="2026-08-05T08:00:00", end="2026-08-05T09:00:00"),
                                         tw) == [], "morning event misses an afternoon window")
    # Location substring
    loc = [_kit(location="city fields")]
    check(len(prep_kits.match_kits_for_event(_ev(), loc)) == 1, "location substring hit")
    check(prep_kits.match_kits_for_event(_ev(location="School Gym"), loc) == [], "location miss")
    # Date window (seasonal gear)
    win = [_kit(start_date="2026-08-01", end_date="2026-08-31")]
    check(len(prep_kits.match_kits_for_event(_ev(), win)) == 1, "inside date window")
    check(prep_kits.match_kits_for_event(_ev(start="2026-09-05T16:00:00", end="2026-09-05T17:00:00"),
                                         win) == [], "outside date window")
    # AND across criteria types: keyword hits but day misses -> no match
    both = [_kit(days_of_week=[0])]
    check(prep_kits.match_kits_for_event(_ev(), both) == [],
          "criteria types AND together, exactly like rules")


def scenario_passenger_filter():
    with storage.db_lock:
        storage.passengers_table.truncate()
        storage.passengers_table.insert({"id": "p_add", "name": "Addison",
                                         "calendar_ids": ["addison@cal"], "hashtags": []})
        storage.passengers_table.insert({"id": "p_ben", "name": "Ben",
                                         "calendar_ids": ["ben@cal"], "hashtags": []})
    pax = prep_kits.passenger_objs()
    kits = [_kit(keywords=[], passenger_ids=["p_add"])]
    check(len(prep_kits.match_kits_for_event(_ev(), kits, pax)) == 1,
          "passenger id resolves through their calendar id")
    check(prep_kits.match_kits_for_event(_ev(calendar_ids=["ben@cal"]), kits, pax) == [],
          "other kid's event misses Addison's kit")
    with storage.db_lock:
        storage.passengers_table.truncate()


def scenario_items_dedupe_across_kits():
    kits = [_kit(), _kit(id="k2", name="Swim", keywords=["swim"],
                  items=["Goggles", "Towel", "Water Bottle"])]
    items = prep_kits.items_for_event(_ev(title="Soccer then swim meet"), kits)
    check(items == ["Cleats", "Shin Guards", "Water Bottle", "Goggles", "Towel"],
          f"items merge in kit order, 'Water Bottle' deduped case-insensitively, got {items}")
    check(prep_kits.items_for_event({"title": "Soccer", "start": "garbage"}, kits) == [],
          "unparseable event start matches nothing (never crashes)")


def scenario_storage_crud():
    storage.prep_kits_table.truncate()
    storage.add_prep_kit(_kit())
    check(len(storage.get_prep_kits()) == 1, "add + get")
    check(storage.update_prep_kit("k1", {"enabled": False}), "update by id returns True")
    check(storage.get_prep_kits()[0]["enabled"] is False, "update persisted")
    check(not storage.update_prep_kit("nope", {"enabled": True}), "unknown id returns False")
    storage.delete_prep_kit("k1")
    check(storage.get_prep_kits() == [], "delete removes the kit")


def scenario_suggest_normalization():
    from services import llm
    orig_llm, orig_settings = llm._call_llm_json, storage.get_settings
    storage.get_settings = lambda: {"calendar_ids": ["p"], "llm_gemini_api_key": "test-key"}
    llm._call_llm_json = lambda *a, **kw: {"kits": [
        {"name": "Soccer", "keywords": ["soccer", "quidditch"], "items": ["Cleats", "  Ball  "]},
        {"name": "Fencing", "keywords": ["fencing"], "items": ["Foil"]},
        {"name": "Swimming", "keywords": ["swim"], "items": ["Goggles"]},
        {"name": "", "keywords": ["soccer"], "items": ["X"]},
        "not-a-dict",
    ]}
    try:
        out = prep_kits.suggest_kits(
            ["Addison Soccer Practice", "Ben Swim Meet"],
            existing_kits=[{"name": "Swim", "keywords": ["swim"], "items": ["Towel"]}])
        check(len(out) == 1 and out[0]["name"] == "Soccer", f"only the grounded, novel kit survives, got {out}")
        check(out[0]["keywords"] == ["soccer"], "ungrounded keyword pruned from a surviving kit")
        check(out[0]["items"] == ["Cleats", "Ball"], "items whitespace-trimmed")
    finally:
        llm._call_llm_json, storage.get_settings = orig_llm, orig_settings


def scenario_prep_status_checkoff():
    storage.prep_status_table.truncate()
    storage.set_prep_confirmed("ev1_unrolled_20260805", True, member_id="mom")
    storage.set_prep_confirmed("ev2", True)
    check(sorted(storage.get_confirmed_preps()) == ["ev1_unrolled_20260805", "ev2"],
          "confirmations recorded per parent event instance")
    storage.set_prep_confirmed("ev1_unrolled_20260805", True, member_id="dad")
    check(len(storage.get_confirmed_preps()) == 2, "re-confirm upserts, no duplicate row")
    storage.set_prep_confirmed("ev2", False)
    check(storage.get_confirmed_preps() == ["ev1_unrolled_20260805"],
          "unconfirming removes the row")
    storage.prep_status_table.truncate()


def scenario_schedule_payload_prep_map():
    import main
    storage.prep_kits_table.truncate()
    storage.add_prep_kit(_kit())
    events = [
        _ev(id="ev1"),
        _ev(id="ev1_dropoff", title="Dropoff: Addison Soccer Practice"),
        _ev(id="er1", title="Soccer ball pickup", event_type="errand"),
        _ev(id="t1", title="Soccer trip", event_type="background_trip"),
        _ev(id="ev2", title="Piano Lesson"),
    ]
    m = main._prep_by_event(events)
    check(sorted(m.keys()) == ["ev1", "ev1_dropoff"],
          f"kit items keyed per matching event (legs too), errands/trips skipped, got {sorted(m.keys())}")
    check(m["ev1"] == ["Cleats", "Shin Guards", "Water Bottle"], "items from the matching kit")
    storage.prep_kits_table.truncate()
    check(main._prep_by_event(events) == {}, "no enabled kits -> empty map")


def scenario_suggest_requires_key():
    orig = storage.get_settings
    storage.get_settings = lambda: {"calendar_ids": ["p"]}
    try:
        try:
            prep_kits.suggest_kits(["Soccer Practice"])
            check(False, "missing LLM key should raise")
        except RuntimeError:
            check(True, "missing LLM key raises RuntimeError")
    finally:
        storage.get_settings = orig


SCENARIOS = [
    scenario_keyword_matching,
    scenario_rule_filters,
    scenario_passenger_filter,
    scenario_items_dedupe_across_kits,
    scenario_storage_crud,
    scenario_prep_status_checkoff,
    scenario_schedule_payload_prep_map,
    scenario_suggest_normalization,
    scenario_suggest_requires_key,
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
