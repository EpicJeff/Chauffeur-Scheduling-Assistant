"""Tests for school hours (K4c) + morning launch (K5).

Load-bearing properties: the dismissal push names the next ride's driver and
stays SILENT when there's no ride or no known driver; the morning-launch
leave-by time is start − travel − buffer, only when the solver's initial
edge exists for a real (non-ghost) driver; the kid digest leads with the
launch line.

Run from chauffeur/:  python tests/test_kid_school_hours.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, family_digest

TODAY = datetime.date.today()
DISMISSAL = datetime.datetime.combine(TODAY, datetime.time(15, 0))


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.passengers_table, storage.cache_table,
              storage.kid_tasks_table, storage.routines_table,
              storage.routine_checks_table, storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "dadm", "name": "Dad", "role": "parent", "driver_id": "d1"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child",
                        "is_child": True, "passenger_id": "p1",
                        "school_hours_start": "08:00", "school_hours_end": "15:00"})
    with storage.db_lock:
        storage.passengers_table.insert({"id": "p1", "name": "Addison",
                                         "calendar_ids": ["cal1"], "hashtags": []})


def _cache(events, assignments, initial_edges=None):
    storage.set_cached_schedule({
        "events": events, "assignments": assignments, "ghost_assignments": {},
        "matched_rules": {}, "scheduled_errands": [],
        "initial_edges": initial_edges or {},
    })


def _ev(eid, title, hh, mm=0, day=TODAY):
    start = datetime.datetime.combine(day, datetime.time(hh, mm))
    return {"id": eid, "title": title, "start": start.isoformat(),
            "end": (start + datetime.timedelta(hours=1)).isoformat(),
            "calendar_ids": ["cal1"]}


def scenario_school_end_push_names_the_driver():
    _reset()
    import main
    kid = storage.get_member("kid1")
    _cache([_ev("swim", "Swim Practice", 16)], {"swim": "d1"})
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid, now=DISMISSAL)
        check(sent and lanes.call_count == 1, "push fires at dismissal")
        m, title, body = lanes.call_args.args[:3]
        check(m["id"] == "kid1" and title == "🚗 Dad has you after school"
              and body == "Swim Practice at 4:00 PM",
              f"driver-named reassurance, got {title} / {body}")


def scenario_school_end_silence_rules():
    _reset()
    import main
    kid = storage.get_member("kid1")
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        _cache([], {})
        check(not main._send_school_end_push(kid, now=DISMISSAL), "no rides -> silent")
        _cache([_ev("late", "Evening thing", 20)], {"late": "d1"})
        check(not main._send_school_end_push(kid, now=DISMISSAL),
              "ride beyond the 3h horizon -> silent")
        _cache([_ev("swim", "Swim Practice", 16)], {})
        check(not main._send_school_end_push(kid, now=DISMISSAL),
              "unknown driver -> silent, never alarming")
        check(lanes.call_count == 0, "no pushes in any silent case")


def scenario_morning_launch_math():
    _reset()
    import main
    _cache([_ev("school", "School Dropoff", 8)], {"school": "d1"},
           {"d1": {"school": {"travel_mins": 20, "buffer_before_mins": 5}}})
    day = main.member_day("kid1", TODAY.isoformat())
    l = day["launch"]
    check(l and l["leave_label"] == "7:35 AM" and l["driver"]["name"] == "Dad",
          f"leave-by = start − travel − buffer, got {l}")
    # no initial edge -> no line (the ride card already shows its time)
    _cache([_ev("school", "School Dropoff", 8)], {"school": "d1"})
    check(main.member_day("kid1", TODAY.isoformat())["launch"] is None,
          "no edge -> no launch line")
    # ghost suggestion -> never a committed leave-by
    _cache([_ev("school", "School Dropoff", 8)], {"school": "ghost_1"},
           {"ghost_1": {"school": {"travel_mins": 20}}})
    check(main.member_day("kid1", TODAY.isoformat())["launch"] is None,
          "ghost drivers never produce a launch line")


def scenario_split_ride_launch_and_digest_line():
    _reset()
    import main
    base = _ev("school", "School Dropoff", 8, day=TODAY + datetime.timedelta(days=1))
    drop = dict(_ev("school_dropoff", "School Dropoff", 8,
                    day=TODAY + datetime.timedelta(days=1)), event_type="dropoff")
    _cache([base, drop], {"school_dropoff": "d1"},
           {"d1": {"school_dropoff": {"travel_mins": 10}}})
    day = main.member_day("kid1", (TODAY + datetime.timedelta(days=1)).isoformat())
    check(day["launch"] and day["launch"]["leave_label"] == "7:50 AM",
          f"split ride resolves the dropoff leg's edge, got {day['launch']}")
    with mock.patch.object(family_digest, 'weather_line', return_value=None):
        digest = main._build_kid_digests()
    lines = digest["kids"]["kid1"]["lines"]
    check(lines[0] == "🚀 Leave by 7:50 AM with Dad",
          f"digest leads with the launch line, got {lines}")


def scenario_config_bound_event_binds_kid():
    """Event-config attendance: the solver replaces a matched event's cached
    calendar_ids with the RESOLVED passenger ids (no rule involved, not the
    kid's own calendar). My Day and the kid digest must still bind the kid —
    regression: config-attached kids showed 'No rides — free day' on the
    kiosk (user screenshot 2026-08-03)."""
    _reset()
    import main
    ev = _ev("camp", "Camp Kesem", 9)
    ev["calendar_ids"] = ["p1"]  # resolved passenger id, not a calendar id
    _cache([ev], {"camp": "d1"})
    day = main.member_day("kid1", TODAY.isoformat())
    check(len(day["rides"]) == 1 and day["rides"][0]["title"] == "Camp Kesem",
          "config-bound event appears on My Day")
    digests = main._build_kid_digests(TODAY)
    lines = digests["kids"].get("kid1", {}).get("lines") or []
    check(any("Camp Kesem" in ln for ln in lines), "and in the kid digest")


SCENARIOS = [
    scenario_school_end_push_names_the_driver,
    scenario_school_end_silence_rules,
    scenario_morning_launch_math,
    scenario_split_ride_launch_and_digest_line,
    scenario_config_bound_event_binds_kid,
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
