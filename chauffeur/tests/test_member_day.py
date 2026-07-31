"""Tests for the passenger day view (main.member_day).

Run from chauffeur/:  python tests/test_member_day.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="chauffeur_member_day_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def _seed():
    storage.drivers_table.insert({"id": "jeff", "name": "Jeff", "color_code": "#f00"})
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben",
                                     "calendar_ids": ["ben@cal"], "hashtags": ["#ben"]})
    storage.ensure_members()
    storage.set_cached_schedule({
        "events": [
            {"id": "soccer", "title": "Soccer", "event_type": "standard",
             "start": "2026-07-31T15:00:00", "end": "2026-07-31T16:00:00",
             "location": "Field 3", "calendar_ids": ["ben@cal"]},
            {"id": "piano_dropoff", "title": "Piano", "event_type": "dropoff",
             "start": "2026-07-31T09:00:00", "end": "2026-07-31T09:00:00",
             "location": "Studio", "calendar_ids": ["ben@cal"]},
            {"id": "tagged", "title": "Playdate #ben", "event_type": "standard",
             "start": "2026-07-31T11:00:00", "end": "2026-07-31T12:00:00",
             "location": None, "calendar_ids": ["other@cal"]},
            {"id": "not_bens", "title": "Mom yoga", "event_type": "standard",
             "start": "2026-07-31T10:00:00", "end": "2026-07-31T11:00:00",
             "location": None, "calendar_ids": ["mom@cal"]},
            {"id": "errand1", "title": "Groceries", "event_type": "errand",
             "start": "2026-07-31T13:00:00", "end": "2026-07-31T13:30:00",
             "location": None, "calendar_ids": ["ben@cal"]},
            {"id": "otherday", "title": "Soccer", "event_type": "standard",
             "start": "2026-08-01T15:00:00", "end": "2026-08-01T16:00:00",
             "location": None, "calendar_ids": ["ben@cal"]},
        ],
        "assignments": {"soccer": "jeff"},
        "ghost_assignments": {"piano_dropoff": "jeff"},
    })
    return storage.get_member_by_passenger_id("p-ben")


def scenario_day_assembly():
    import main
    ben = _seed()
    storage.mark_drive_status("route_soccer_1", "in_progress")

    day = main.member_day(ben["id"], date="2026-07-31")
    ids = [r["id"] for r in day["rides"]]
    check(ids == ["piano_dropoff", "tagged", "soccer"],
          f"calendar + hashtag matches, sorted by start, errands/other-day excluded; got {ids}")

    soccer = next(r for r in day["rides"] if r["id"] == "soccer")
    check(soccer["driver"] and soccer["driver"]["name"] == "Jeff",
          "assigned driver resolved to member")
    check(soccer["driver"]["member_id"] == storage.get_member_by_driver_id("jeff")["id"],
          "driver member id present for map/DM deep links")
    check(soccer["status"] == "in_progress", "in-progress leg surfaces as status")

    piano = next(r for r in day["rides"] if r["id"] == "piano_dropoff")
    check(piano["driver"] and piano["driver"]["name"] == "Jeff",
          "ghost assignment also resolves")

    tagged = next(r for r in day["rides"] if r["id"] == "tagged")
    check(tagged["driver"] is None and tagged["status"] is None,
          "unassigned ride has null driver/status")


def scenario_member_without_passenger_link():
    import main
    storage.drivers_table.insert({"id": "amy", "name": "Amy", "color_code": "#0f0"})
    storage.ensure_members()
    amy = storage.get_member_by_driver_id("amy")
    day = main.member_day(amy["id"], date="2026-07-31")
    check(day["rides"] == [], "driver-only member has an empty passenger day")


def scenario_unknown_member_404():
    import main
    from fastapi import HTTPException
    try:
        main.member_day("ghost", date="2026-07-31")
        check(False, "expected 404")
    except HTTPException as e:
        check(e.status_code == 404, "404 for unknown member")


SCENARIOS = [
    scenario_day_assembly,
    scenario_member_without_passenger_link,
    scenario_unknown_member_404,
]

if __name__ == "__main__":
    import traceback
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
