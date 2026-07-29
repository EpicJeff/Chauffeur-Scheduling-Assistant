"""Tests for explain_assignment_conflicts (solver/matcher.py) — the dry-run
behind the drag-and-drop confirmation dialog. It reports why the solver would
normally refuse an (event, driver) pair; overrides still win regardless.

Run from chauffeur/:  python tests/test_override_conflicts.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event, Passenger, Rule
from solver import matcher


def mk_event(ev_id="e1", hour=9, title="Soccer Practice", location="Field"):
    start = datetime.datetime(2026, 9, 7, hour, 0)
    return Event(id=ev_id, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location=location, calendar_ids=["primary"], source_event_ids=[ev_id])


def mk_driver(d_id="d1", name="Tom & Wanda", **kw):
    return Driver(id=d_id, name=name, color_code="#fff", **kw)


def mk_trip(entities, title="Beach Trip", location="Orlando"):
    return {"id": "t1", "title": title, "location": location,
            "start": datetime.datetime(2026, 9, 6), "end": datetime.datetime(2026, 9, 10),
            "entities": set(entities)}


def scenario_clean_pair_no_reasons():
    reasons = matcher.explain_assignment_conflicts(mk_event(), mk_driver())
    check(reasons == [], f"clean pair has no conflicts, got {reasons}")


def scenario_pax_on_trip_reason():
    pax = Passenger(id="p1", name="James", hashtags=["#james"])
    ev = mk_event(title="Soccer #james")
    reasons = matcher.explain_assignment_conflicts(
        ev, mk_driver(), passengers=[pax], trip_metadata=[mk_trip({"passenger_p1"})])
    check(len(reasons) == 1 and "away on 'Beach Trip'" in reasons[0],
          f"passengers-away reason produced, got {reasons}")


def scenario_driver_on_trip_far_event():
    # Driver is on the trip; harness mock returns 10 min between differing
    # locations, so patch the travel lookup to make the event genuinely far.
    orig = matcher._raw_get_travel_time_minutes
    matcher._raw_get_travel_time_minutes = lambda a, b, *args, **kw: 90
    try:
        reasons = matcher.explain_assignment_conflicts(
            mk_event(), mk_driver(), trip_metadata=[mk_trip({"driver_d1"})])
    finally:
        matcher._raw_get_travel_time_minutes = orig
    check(len(reasons) == 1 and "is away on 'Beach Trip'" in reasons[0] and "90 minutes" in reasons[0],
          f"driver-on-trip far-event reason produced, got {reasons}")


def scenario_rule_reasons():
    ev = mk_event()
    unavailable = Rule(driver_id="d1", constraint_type="unavailable", keywords=["soccer"])
    required_other = Rule(driver_id="d9", constraint_type="required", keywords=["soccer"])
    unrelated = Rule(driver_id="d1", constraint_type="unavailable", keywords=["piano"])
    reasons = matcher.explain_assignment_conflicts(
        ev, mk_driver(), rules=[unavailable, required_other, unrelated])
    check(len(reasons) == 2, f"two matching rule reasons, got {reasons}")
    check(any("unavailable" in r for r in reasons) and any("requires a different driver" in r for r in reasons),
          f"both rule flavors explained, got {reasons}")


def scenario_own_event_overlap_but_not_attendee():
    ev = mk_event()
    own_conflict = mk_event(ev_id="own1", hour=9, title="Dentist")
    attendee_copy = mk_event(ev_id="cal_copy", hour=9, title="Soccer Practice")  # same time+title = attending
    reasons = matcher.explain_assignment_conflicts(
        ev, mk_driver(), driver_events=[own_conflict, attendee_copy])
    check(len(reasons) == 1 and "Dentist" in reasons[0],
          f"own-event overlap flagged but attendee copy skipped, got {reasons}")


def scenario_preferred_hours_reason():
    d = mk_driver(preferred_start="10:00", preferred_end="17:00")
    reasons = matcher.explain_assignment_conflicts(mk_event(hour=8), d)
    check(len(reasons) == 1 and "preferred driving hours" in reasons[0],
          f"preferred-hours reason produced, got {reasons}")


SCENARIOS = [
    scenario_clean_pair_no_reasons,
    scenario_pax_on_trip_reason,
    scenario_driver_on_trip_far_event,
    scenario_rule_reasons,
    scenario_own_event_overlap_but_not_attendee,
    scenario_preferred_hours_reason,
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
