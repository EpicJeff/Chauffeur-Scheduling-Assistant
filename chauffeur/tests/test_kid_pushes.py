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
        # The ride-status slice: the same start also tells the parents —
        # minus the driver, who presumably knows they are driving.
        check(lanes.call_count == 2, "one push to the bound kid, one to Mom")
        kid, title, body = lanes.call_args_list[0].args[:3]
        check(kid["id"] == "kid1", "push goes to the child member")
        check(title == "🚗 Dad is on the way!" and body == "Swim Practice",
              f"driver-named reassurance, got {title} / {body}")
        parent, ptitle, pbody = lanes.call_args_list[1].args[:3]
        check(parent["id"] == "momm", "the other parent is told; Dad is not")
        check(ptitle == "🚗 Dad is driving to Swim Practice" and pbody == "Addison",
              f"parents get driver, destination and who is aboard: {ptitle} / {pbody}")
        main._notify_kids_ride_started("swim", now=NOON)
        check(lanes.call_count == 2, "second leg start of the same event stays quiet")
        main._notify_kids_ride_started("adult_ev", now=NOON)
        check(lanes.call_count == 2, "events with no bound kids push nothing")
        main._notify_kids_ride_started("ghost-event", now=NOON)
        check(lanes.call_count == 2, "unknown event id is a silent no-op")


def scenario_the_push_carries_the_eta_when_the_start_priced_one():
    """The ride-status slice: 'on the way' grew a time. The ETA computed at
    the Start Drive tap rides the leg row; when it exists the push says
    'arriving about 3:58 pm', and when it does not the push stays exactly
    what it was — a push that says nothing beats one that guesses."""
    _reset()
    import main
    eta = datetime.datetime.combine(TODAY, datetime.time(15, 58)).timestamp()
    storage.mark_drive_status('init_swim', 'in_progress', eta_ts=eta)
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_kids_ride_started("swim", now=NOON, leg_id='init_swim')
        _, title, body = lanes.call_args_list[0].args[:3]
        check(body == "Swim Practice · arriving about 3:58 pm",
              f"the kid push carries the promised time: {body}")
        _, _, pbody = lanes.call_args_list[1].args[:3]
        check(pbody == "Addison · arriving about 3:58 pm",
              f"and so does the parent push: {pbody}")
    # 24-hour households read a 24-hour clock.
    storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                    "time_format_24h": True}
    check(main._clock_label(eta) == "15:58",
          "the clock label honours time_format_24h")
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}


def scenario_a_new_time_is_shared_only_on_the_drivers_say_so():
    """share_eta: the parked ETA becomes the real one, the check-in nudge
    re-arms for it, and the same audience hears — but only because the
    driver tapped. No pending time = 404, never a silent no-op push."""
    _reset()
    import main
    from fastapi import BackgroundTasks, HTTPException
    from main import DriveStatus as DS
    eta = datetime.datetime.combine(TODAY, datetime.time(16, 12)).timestamp()
    storage.mark_drive_status('init_swim', 'in_progress',
                              eta_ts=eta - 600, pending_eta_ts=eta,
                              arrival_nudged_ts=123.0)
    main.drive_share_eta(DS(leg_id='init_swim', status='in_progress'),
                         BackgroundTasks())
    row = storage.get_drive_status('init_swim')
    check(row.get('eta_ts') == eta and not row.get('pending_eta_ts'),
          f"the parked time became the leg's real ETA: {row}")
    check(not row.get('arrival_nudged_ts'),
          "the check-in nudge re-arms for the new time")
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_ride_eta_update("swim", 'init_swim', now=NOON)
        check(lanes.call_count == 2, "kid and the other parent both hear")
        _, title, body = lanes.call_args_list[0].args[:3]
        check(title == "🚗 New time from Dad"
              and body == "Swim Practice · arriving about 4:12 pm",
              f"the update names the driver and the new time: {title} / {body}")
    try:
        main.drive_share_eta(DS(leg_id='route_nothing', status='in_progress'),
                             BackgroundTasks())
        check(False, "sharing with no parked time should refuse")
    except HTTPException as e:
        check(e.status_code == 404, f"expected 404, got {e.status_code}")


def scenario_quiet_hours_skip_not_defer():
    _reset()
    import main
    with mock.patch.object(main, '_notify_member_lanes') as lanes:
        main._notify_kids_ride_started("swim", now=NIGHT)
        check(lanes.call_count == 0, "22:00 is inside default kid quiet hours")
        # quiet skip must NOT consume the once-per-day marker
        main._notify_kids_ride_started("swim", now=NOON)
        check(lanes.call_count == 2,   # kid + the other parent
              "the same ride can still notify outside quiet hours")


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
    scenario_the_push_carries_the_eta_when_the_start_priced_one,
    scenario_a_new_time_is_shared_only_on_the_drivers_say_so,
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
