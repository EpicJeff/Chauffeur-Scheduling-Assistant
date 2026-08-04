"""Tests for school-bus support (bus arc B1).

Load-bearing properties: the bus launch line appears only for opted-in kids
on weekdays and yields to any morning car ride; live HCTB estimates only
apply for TODAY while the bus is actually out, and lateness is reported only
beyond the jitter threshold; the dismissal push says "bus home" only for
bus-configured kids (silence stands for everyone else); the kid digest leads
with the bus line even when the day has no car rides.

Run from chauffeur/:  python tests/test_bus.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import bus, storage

TODAY = datetime.date.today()
# A guaranteed weekday relative to today (for date-shape tests use Monday).
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
SATURDAY = MONDAY + datetime.timedelta(days=5)

KID = {"id": "kid1", "name": "Addison Smith", "role": "child",
       "school_hours_start": "08:00", "school_hours_end": "15:00",
       "bus_am_stop_time": "07:22", "bus_walk_mins": 5}


def scenario_static_morning_launch():
    with mock.patch.object(bus, 'bus_active', return_value=False):
        launch = bus.morning_launch(dict(KID), MONDAY.isoformat())
    check(launch is not None, "opted-in kid gets a bus launch on a weekday")
    check(launch['bus'] is True and launch['driver'] is None, "bus launch shape")
    check(launch['leave_label'] == '7:17 AM', f"leave = stop − walk ({launch['leave_label']})")
    check(launch['bus_stop_label'] == '7:22 AM', "stop label from static time")
    check(launch['bus_live'] is False and launch['bus_late_mins'] is None,
          "no live claims without HCTB")

    check(bus.morning_launch(dict(KID), SATURDAY.isoformat()) is None,
          "no bus line on weekends")
    no_bus = {**KID, "bus_am_stop_time": None}
    check(bus.morning_launch(no_bus, MONDAY.isoformat()) is None,
          "no config -> no bus line (opt-in)")


def scenario_car_ride_wins_the_morning():
    morning_ride = {"start": datetime.datetime.combine(MONDAY, datetime.time(7, 40)).isoformat()}
    afternoon_ride = {"start": datetime.datetime.combine(MONDAY, datetime.time(16, 0)).isoformat()}
    with mock.patch.object(bus, 'bus_active', return_value=False):
        check(bus.morning_launch(dict(KID), MONDAY.isoformat(), [morning_ride]) is None,
              "a morning car ride suppresses the bus line")
        check(bus.morning_launch(dict(KID), MONDAY.isoformat(), [afternoon_ride]) is not None,
              "an afternoon ride does not")


def scenario_live_estimate_only_today_and_active():
    live_t = datetime.time(7, 29)
    with mock.patch.object(bus, 'bus_active', return_value=True), \
         mock.patch.object(bus, 'live_stop_time', return_value=live_t):
        launch = bus.morning_launch(dict(KID), TODAY.isoformat())
        if TODAY.weekday() < 5:
            check(launch['bus_live'] is True, "live estimate used while bus is out today")
            check(launch['bus_late_mins'] == 7, "7 min beyond schedule reported as late")
            check(launch['bus_stop_label'] == '7:29 AM', "live time shown")
        future = MONDAY + datetime.timedelta(days=7)
        launch2 = bus.morning_launch(dict(KID), future.isoformat())
        check(launch2['bus_live'] is False, "live never applies to a future date")
    # Jitter below the threshold is not "late"
    with mock.patch.object(bus, 'bus_active', return_value=True), \
         mock.patch.object(bus, 'live_stop_time', return_value=datetime.time(7, 24)):
        launch = bus.morning_launch(dict(KID), TODAY.isoformat())
        if TODAY.weekday() < 5:
            check(launch['bus_late_mins'] is None, "2-min wobble is not news")


def scenario_digest_line_wording():
    with mock.patch.object(bus, 'bus_active', return_value=False):
        launch = bus.morning_launch(dict(KID), MONDAY.isoformat())
    line = bus.digest_line(launch)
    check(line == "🚌 Bus at 7:22 AM — out the door by 7:17 AM", f"digest wording ({line})")
    launch['bus_late_mins'] = 6
    check("no rush" in bus.digest_line(launch), "lateness framed as permission to relax")


def scenario_dismissal_line():
    check(bus.dismissal_line({"name": "NoBus Kid"}) is None,
          "no bus config -> dismissal silence stands")
    with mock.patch.object(bus, 'bus_active', return_value=False):
        am_only = bus.dismissal_line(dict(KID))
        check(am_only == "You're riding the bus home today.", "am-only config reassures")
        with_pm = bus.dismissal_line({**KID, "bus_pm_stop_time": "15:45"})
        check("3:45 PM" in with_pm, "static PM drop time named")
    with mock.patch.object(bus, 'bus_active', return_value=True), \
         mock.patch.object(bus, 'live_stop_time', return_value=datetime.time(15, 51)):
        live = bus.dismissal_line({**KID, "bus_pm_stop_time": "15:45"})
        check("3:51 PM" in live, "live PM estimate wins while the bus is out")


def scenario_dismissal_push_bus_branch():
    import main
    for t in (storage.members_table, storage.cache_table, storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member(dict(KID, is_child=True))
    kid = storage.get_member("kid1")
    dismissal = datetime.datetime.combine(TODAY, datetime.time(15, 0))
    empty_day = {"rides": [], "due_soon": [], "launch": None}
    with mock.patch.object(main, 'member_day', return_value=empty_day), \
         mock.patch.object(bus, 'bus_active', return_value=False), \
         mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid, now=dismissal)
        check(sent is True and lanes.call_count == 1, "bus kid gets a dismissal push with no car ride")
        check(lanes.call_args[0][1] == "🚌 Bus home today", "bus dismissal title")
    storage.members_table.truncate()
    storage.add_member({"id": "kid2", "name": "Carless Kid", "role": "child",
                        "is_child": True, "school_hours_end": "15:00"})
    kid2 = storage.get_member("kid2")
    with mock.patch.object(main, 'member_day', return_value=empty_day), \
         mock.patch.object(main, '_notify_member_lanes') as lanes:
        sent = main._send_school_end_push(kid2, now=dismissal)
        check(sent is False and lanes.call_count == 0,
              "non-bus kid with no ride stays silent (original rule)")


SCENARIOS = [
    scenario_static_morning_launch,
    scenario_car_ride_wins_the_morning,
    scenario_live_estimate_only_today_and_active,
    scenario_digest_line_wording,
    scenario_dismissal_line,
    scenario_dismissal_push_bus_branch,
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
