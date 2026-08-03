"""Tests for the kid pickup-clarity pushes (kid-support arc K2).

Load-bearing properties: the on-the-way push fires once per event per day
(later legs stay quiet), driver-change pushes are GAINS-ONLY and near-term
(48h), kid quiet hours skip rather than defer, and both use the same
passenger binding as My Day.

Run from chauffeur/:  python tests/test_kid_pushes.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()
NOON = datetime.datetime.combine(TODAY, datetime.time(12, 0))
NIGHT = datetime.datetime.combine(TODAY, datetime.time(22, 0))


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.passengers_table, storage.cache_table,
              storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "dadm", "name": "Dad", "role": "parent", "driver_id": "d1"})
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent", "driver_id": "d2"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child",
                        "is_child": True, "passenger_id": "p1"})
    with storage.db_lock:
        storage.passengers_table.insert({"id": "p1", "name": "Addison",
                                         "calendar_ids": ["cal1"], "hashtags": []})
    storage.set_cached_schedule({
        "events": [{"id": "swim", "title": "Swim Practice",
                    "start": f"{TODAY.isoformat()}T16:00:00",
                    "end": f"{TODAY.isoformat()}T17:00:00", "calendar_ids": ["cal1"]},
                   {"id": "adult_ev", "title": "Gym",
                    "start": f"{TODAY.isoformat()}T18:00:00",
                    "end": f"{TODAY.isoformat()}T19:00:00", "calendar_ids": ["other"]}],
        "assignments": {"swim": "d1"},
        "ghost_assignments": {},
        "matched_rules": {},
        "scheduled_errands": [],
    })


def scenario_on_the_way_once_per_day():
    _reset()
    import main
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_kids_ride_started("swim", now=NOON)
        check(lanes.call_count == 1, "one push to the bound kid")
        kid, title, body = lanes.call_args.args[:3]
        check(kid["id"] == "kid1", "push goes to the child member")
        check(title == "🚗 Dad is on the way!" and body == "Swim Practice",
              f"driver-named reassurance, got {title} / {body}")
        main._notify_kids_ride_started("swim", now=NOON)
        check(lanes.call_count == 1, "second leg start of the same event stays quiet")
        main._notify_kids_ride_started("adult_ev", now=NOON)
        check(lanes.call_count == 1, "events with no bound kids push nothing")
        main._notify_kids_ride_started("ghost-event", now=NOON)
        check(lanes.call_count == 1, "unknown event id is a silent no-op")


def scenario_quiet_hours_skip_not_defer():
    _reset()
    import main
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_kids_ride_started("swim", now=NIGHT)
        check(lanes.call_count == 0, "22:00 is inside default kid quiet hours")
        # quiet skip must NOT consume the once-per-day marker
        main._notify_kids_ride_started("swim", now=NOON)
        check(lanes.call_count == 1, "the same ride can still notify outside quiet hours")


def scenario_driver_change_gains_only_near_term():
    _reset()
    import main
    tomorrow = TODAY + datetime.timedelta(days=1)
    far = TODAY + datetime.timedelta(days=5)
    ev = lambda day, h: {"title": "Swim Practice", "calendar_ids": ["cal1"],
                         "start": f"{day.isoformat()}T{h:02d}:00:00"}
    buffered = {
        "swim": {"first_old": "d1", "last_new": "d2", "ev": ev(tomorrow, 16)},   # gain -> push
        "lost": {"first_old": "d1", "last_new": None, "ev": ev(tomorrow, 9)},    # loss -> silent
        "ghost": {"first_old": None, "last_new": "ghost_1", "ev": ev(tomorrow, 10)},  # ghost -> silent
        "far": {"first_old": "d1", "last_new": "d2", "ev": ev(far, 16)},         # >48h -> silent
        "same": {"first_old": "d2", "last_new": "d2", "ev": ev(tomorrow, 11)},   # churn -> silent
    }
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_kids_driver_changes(buffered, now=NOON)
        check(lanes.call_count == 1, f"only the near-term gain pushes, got {lanes.call_count}")
        kid, title, body = lanes.call_args.args[:3]
        check(kid["id"] == "kid1" and title == "Ride update", "kid-addressed ride update")
        check(body == "Mom is taking you to Swim Practice tomorrow at 4:00 PM 🚗",
              f"calm, concrete wording — got {body}")
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_kids_driver_changes(buffered, now=NIGHT)
        check(lanes.call_count == 0, "kid quiet hours silence driver-change pushes")


SCENARIOS = [
    scenario_on_the_way_once_per_day,
    scenario_quiet_hours_skip_not_defer,
    scenario_driver_change_gains_only_near_term,
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
