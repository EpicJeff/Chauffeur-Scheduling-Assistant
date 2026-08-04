"""Tests for resolve_passenger_double_bookings (solver/matcher.py).

A kid double-booked between their SOLO event and a co-attended event used to
knock the co-attended event fully off the schedule (constraint 2b makes the
pair mutually exclusive as wholes). The resolver drops the kid from the
co-attended event so both events can schedule; every ambiguous or non-biting
case must be left untouched.

Run from chauffeur/:  python tests/test_pax_conflict_drop.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event, Passenger
from solver import matcher


def mk_event(ev_id, cids, hour=17, end_hour=None, location="Gym A",
             all_day=False, **kw):
    start = datetime.datetime(2026, 9, 8, hour, 0)  # a Tuesday
    end = datetime.datetime(2026, 9, 8, end_hour or hour + 1, 0)
    return Event(id=ev_id, title=ev_id, start=start, end=end,
                 location=location, all_day=all_day,
                 calendar_ids=list(cids), source_event_ids=[ev_id], **kw)


PAX = [Passenger(id="a", name="Ann"),
       Passenger(id="b", name="Ben"),
       Passenger(id="c", name="Cal", calendar_ids=["cal_c@group"])]


def scenario_solo_wins_multi_drops():
    multi = mk_event("shared_practice", ["a", "b"], location="Gym A")
    solo = mk_event("tuesday_class", ["a"], location="Studio B")
    drops = matcher.resolve_passenger_double_bookings([multi, solo], PAX)
    check(drops == {"shared_practice": ["a"]}, f"solo kid dropped from co-attended event, got {drops}")
    check(multi.calendar_ids == ["b"], f"co-attended event keeps the other kid, got {multi.calendar_ids}")
    check(solo.calendar_ids == ["a"], "solo event untouched")


def scenario_both_solo_untouched():
    e1 = mk_event("e1", ["a"], location="Gym A")
    e2 = mk_event("e2", ["a"], location="Studio B")
    drops = matcher.resolve_passenger_double_bookings([e1, e2], PAX)
    check(drops == {} and e1.calendar_ids == ["a"] and e2.calendar_ids == ["a"],
          f"two solo events stay a real conflict, got {drops}")


def scenario_both_multi_untouched():
    e1 = mk_event("e1", ["a", "b"], location="Gym A")
    e2 = mk_event("e2", ["a", "c"], location="Studio B")
    drops = matcher.resolve_passenger_double_bookings([e1, e2], PAX)
    check(drops == {}, f"two co-attended events stay a manual decision, got {drops}")


def scenario_same_location_untouched():
    e1 = mk_event("e1", ["a", "b"], location="Gym A")
    e2 = mk_event("e2", ["a"], location="gym a  ")
    drops = matcher.resolve_passenger_double_bookings([e1, e2], PAX)
    check(drops == {}, f"same-location overlap never conflicted, got {drops}")


def scenario_no_overlap_untouched():
    e1 = mk_event("e1", ["a", "b"], hour=15, location="Gym A")
    e2 = mk_event("e2", ["a"], hour=17, location="Studio B")
    drops = matcher.resolve_passenger_double_bookings([e1, e2], PAX)
    check(drops == {}, f"non-overlapping events untouched, got {drops}")


def scenario_all_day_ignored():
    allday = mk_event("birthday", ["a"], all_day=True, location="Party Hall")
    multi = mk_event("shared_practice", ["a", "b"], location="Gym A")
    drops = matcher.resolve_passenger_double_bookings([allday, multi], PAX)
    check(drops == {}, f"all-day presence is not physical occupation, got {drops}")


def scenario_raw_calendar_id_resolved():
    # Cal is bound to the shared event via his RAW Google calendar id; the
    # drop must remove that cid, not look for the passenger id.
    multi = mk_event("shared_practice", ["cal_c@group", "b"], location="Gym A")
    solo = mk_event("tuesday_class", ["c"], location="Studio B")
    drops = matcher.resolve_passenger_double_bookings([multi, solo], PAX)
    check(drops == {"shared_practice": ["c"]}, f"raw-cid kid resolved and dropped, got {drops}")
    check(multi.calendar_ids == ["b"], f"raw cid removed, got {multi.calendar_ids}")


def scenario_solver_schedules_both_after_drop():
    multi = mk_event("shared_practice", ["a", "b"], location="Gym A")
    solo = mk_event("tuesday_class", ["a"], location="Studio B")
    events = [multi, solo]
    matcher.resolve_passenger_double_bookings(events, PAX)
    drivers = [Driver(id="d1", name="Mom", color_code="#fff"),
               Driver(id="d2", name="Dad", color_code="#000")]
    assignments, unassigned, _, _ = matcher.solve_schedule(events, drivers, [], [], passengers=PAX)
    check(len(assignments) == 2 and not unassigned,
          f"both events schedule after the drop, got assignments={assignments} unassigned={unassigned}")


SCENARIOS = [
    scenario_solo_wins_multi_drops,
    scenario_both_solo_untouched,
    scenario_both_multi_untouched,
    scenario_same_location_untouched,
    scenario_no_overlap_untouched,
    scenario_all_day_ignored,
    scenario_raw_calendar_id_resolved,
    scenario_solver_schedules_both_after_drop,
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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
