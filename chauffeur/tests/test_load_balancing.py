"""Solver tests for the optional load-balancing mode (solver/matcher.py).

Default mode fills the highest-scoring driver first; with load_balancing=True
a quadratic occupied-minutes penalty spreads events across the roster while
attendee assignments still dominate.

Run from chauffeur/:  python tests/test_load_balancing.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event
from solver import matcher


def mk_driver(i, priority_index):
    return Driver(id=f"d{i}", name=f"Driver {i}", color_code="#fff",
                  group="primary", priority_index=priority_index)


def mk_event(i, start_hour, duration_mins=60):
    day = datetime.datetime(2026, 9, 7)
    start = day.replace(hour=start_hour)
    return Event(id=f"e{i}", title=f"Event {i}", start=start,
                 end=start + datetime.timedelta(minutes=duration_mins),
                 calendar_ids=["primary"], source_event_ids=[f"e{i}"])


def scenario_bucket_fill_default():
    # Default mode: the priority-1 driver wins every event; the rest sit idle.
    drivers = [mk_driver(1, 1), mk_driver(2, 4), mk_driver(3, 4), mk_driver(4, 4)]
    events = [mk_event(i, 8 + i * 2) for i in range(4)]

    assignments, unassigned, _ = matcher.solve_schedule(events, drivers, [])
    check(not unassigned, "all events assigned")
    check(all(d == "d1" for d in assignments.values()),
          f"default mode stacks everything on the priority driver, got {assignments}")


def scenario_load_balancing_spreads():
    # Same setup with the toggle on: the ~450-point priority edge loses to the
    # quadratic occupied-time penalty, so each driver gets exactly one event.
    drivers = [mk_driver(1, 1), mk_driver(2, 4), mk_driver(3, 4), mk_driver(4, 4)]
    events = [mk_event(i, 8 + i * 2) for i in range(4)]

    assignments, unassigned, _ = matcher.solve_schedule(events, drivers, [], load_balancing=True)
    check(not unassigned, "all events assigned")
    loads = {}
    for d_id in assignments.values():
        loads[d_id] = loads.get(d_id, 0) + 1
    check(len(loads) == 4 and all(v == 1 for v in loads.values()),
          f"balanced mode gives each driver one event, got {assignments}")


def scenario_attendee_still_wins():
    # A driver attending an event keeps it even when balancing would prefer
    # someone idle: the +50M attendee bonus dwarfs the quadratic penalty.
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    events = [mk_event(i, 8 + i * 2) for i in range(3)]
    driver_events = {"d1": [events[0], events[1]]}  # d1 attends e0 and e1

    assignments, unassigned, _ = matcher.solve_schedule(
        events, drivers, [], driver_events=driver_events, load_balancing=True)
    check(not unassigned, "all events assigned")
    check(assignments["e0"] == "d1" and assignments["e1"] == "d1",
          f"attendee keeps own events under balancing, got {assignments}")
    check(assignments["e2"] == "d2",
          f"balancing pushes the remaining event to the idle driver, got {assignments}")


SCENARIOS = [
    scenario_bucket_fill_default,
    scenario_load_balancing_spreads,
    scenario_attendee_still_wins,
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
