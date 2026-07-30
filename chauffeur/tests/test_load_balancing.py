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


def mk_event(i, start_hour, duration_mins=60, location=None):
    day = datetime.datetime(2026, 9, 7)
    start = day.replace(hour=start_hour)
    return Event(id=f"e{i}", title=f"Event {i}", start=start,
                 end=start + datetime.timedelta(minutes=duration_mins),
                 location=location,
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


def scenario_metric_events_vs_occupied():
    # Durations [120, 40, 40, 40]: by count the fair split is 2/2, by occupied
    # time it is the 120-min event alone vs the three 40-min ones (120/120).
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    durations = [120, 40, 40, 40]
    events = [mk_event(i, 8 + i * 3, duration_mins=durations[i]) for i in range(4)]

    a_ev, un_ev, _ = matcher.solve_schedule(events, drivers, [],
                                            load_balancing=True, load_balancing_metric='events')
    check(not un_ev, "all events assigned (events metric)")
    counts = {}
    for d_id in a_ev.values():
        counts[d_id] = counts.get(d_id, 0) + 1
    check(sorted(counts.values()) == [2, 2],
          f"events metric splits 2/2 regardless of duration, got {a_ev}")

    a_oc, un_oc, _ = matcher.solve_schedule(events, drivers, [],
                                            load_balancing=True, load_balancing_metric='occupied_time')
    check(not un_oc, "all events assigned (occupied metric)")
    mins = {}
    for e in events:
        d_id = a_oc[e.id]
        mins[d_id] = mins.get(d_id, 0) + int((e.end - e.start).total_seconds() // 60)
    check(sorted(mins.values()) == [120, 120],
          f"occupied metric isolates the long event (120/120 split), got {a_oc}")


def scenario_metric_driving_time_spreads():
    # All events at the same venue, both drivers living at Home: each event is
    # the same round trip, so driving-time balancing splits them 2/2 even
    # though d1 outranks d2 on priority.
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    for d in drivers:
        d.home_location = "Home"
    events = [mk_event(i, 8 + i * 3, location="Venue") for i in range(4)]

    assignments, unassigned, _ = matcher.solve_schedule(
        events, drivers, [], load_balancing=True, load_balancing_metric='driving_time')
    check(not unassigned, "all events assigned")
    counts = {}
    for d_id in assignments.values():
        counts[d_id] = counts.get(d_id, 0) + 1
    check(sorted(counts.values()) == [2, 2],
          f"driving-time metric splits equal round trips 2/2, got {assignments}")


def scenario_metric_driving_time_prefers_local():
    # d2 lives at the venue: their round trips cost 0 driving, so every event
    # goes to them despite d1's higher priority — no driving burden to balance.
    d1 = mk_driver(1, 1); d1.home_location = "Home"
    d2 = mk_driver(2, 4); d2.home_location = "Venue"
    events = [mk_event(i, 8 + i * 3, location="Venue") for i in range(4)]

    assignments, unassigned, _ = matcher.solve_schedule(
        events, [d1, d2], [], load_balancing=True, load_balancing_metric='driving_time')
    check(not unassigned, "all events assigned")
    check(all(d_id == "d2" for d_id in assignments.values()),
          f"zero-drive local driver takes everything under driving-time metric, got {assignments}")


def scenario_overrides_beat_balancing():
    # Manual overrides pin all four events to d1 even with balancing on: the
    # override bonus (~1.9e9) dwarfs the saturated balancing penalty (<=1.44M).
    drivers = [mk_driver(1, 1), mk_driver(2, 4), mk_driver(3, 4), mk_driver(4, 4)]
    events = [mk_event(i, 8 + i * 2) for i in range(4)]
    overrides = [{"event_id": e.id, "driver_id": "d1", "created_at": 1750000000 + i}
                 for i, e in enumerate(events)]

    for metric in ("events", "driving_time", "occupied_time"):
        assignments, unassigned, _ = matcher.solve_schedule(
            events, drivers, [], overrides=overrides,
            load_balancing=True, load_balancing_metric=metric)
        check(not unassigned and all(d == "d1" for d in assignments.values()),
              f"overrides pin everything to d1 under '{metric}' balancing, got {assignments}")


def scenario_boundary_day_dropoff_assignable():
    # Departure-day logistics need no override at all: the trip ban does not
    # apply on the trip's first/last calendar day, so the camp-bus drop-off is
    # assignable to a stay-home driver like any normal event.
    import datetime as dt
    from models.schemas import Passenger
    drivers = [mk_driver(2, 1)]
    pax = Passenger(id="p1", name="James", hashtags=["#james"])
    ev = mk_event(0, 8)
    ev.title = "Bus Drop off #james"
    trip = {"id": "t1", "start": ev.start.replace(hour=0), "end": ev.start.replace(hour=0) + dt.timedelta(days=4),
            "location": None, "entities": {"passenger_p1"}}

    assignments, unassigned, _ = matcher.solve_schedule([ev], drivers, [], passengers=[pax], trip_metadata=[trip])
    check(assignments.get(ev.id) == "d2",
          f"departure-day drop-off assigns normally without an override, got {assignments}, {unassigned}")


def scenario_override_beats_trip_ban():
    # d2 is NOT on the trip and the event's passenger IS: normally hard-banned
    # for d2 (event goes unassigned) — but a manual override must still win.
    import datetime as dt
    from models.schemas import Passenger
    drivers = [mk_driver(2, 1)]
    pax = Passenger(id="p1", name="James", hashtags=["#james"])
    ev = mk_event(0, 9)
    ev.title = "Soccer #james"
    trip = {"id": "t1", "start": ev.start - dt.timedelta(days=1), "end": ev.end + dt.timedelta(days=1),
            "location": None, "entities": {"passenger_p1"}}

    a_no, un_no, _ = matcher.solve_schedule([ev], drivers, [], passengers=[pax], trip_metadata=[trip])
    check(ev.id in un_no, f"without an override the trip ban leaves it unassigned, got {a_no}")

    ovr = [{"event_id": ev.id, "driver_id": "d2", "created_at": 1750000000}]
    a_ovr, un_ovr, _ = matcher.solve_schedule([ev], drivers, [], overrides=ovr,
                                              passengers=[pax], trip_metadata=[trip])
    check(a_ovr.get(ev.id) == "d2", f"override onto the trip-banned driver wins, got {a_ovr}")


SCENARIOS = [
    scenario_bucket_fill_default,
    scenario_load_balancing_spreads,
    scenario_attendee_still_wins,
    scenario_metric_events_vs_occupied,
    scenario_metric_driving_time_spreads,
    scenario_metric_driving_time_prefers_local,
    scenario_overrides_beat_balancing,
    scenario_boundary_day_dropoff_assignable,
    scenario_override_beats_trip_ban,
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
