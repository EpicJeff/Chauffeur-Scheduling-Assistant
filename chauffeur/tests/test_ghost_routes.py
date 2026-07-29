"""Tests for suggested-driver (ghost) route generation (solver/matcher.py).

solve_ghost_routes must apply the same trip-conflict semantics as
solve_schedule: a ghost driver is never on a trip, so in-window events whose
passengers are away on the trip (hashtag- or calendar-matched) get no
suggested route.

Run from chauffeur/:  python tests/test_ghost_routes.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Event, Passenger
from solver import matcher


def mk_event(i, day_offset=0, hour=9, title=None, calendar_ids=None):
    start = datetime.datetime(2026, 9, 7 + day_offset, hour, 0)
    return Event(id=f"e{i}", title=title or f"Event {i}", start=start,
                 end=start + datetime.timedelta(hours=1),
                 calendar_ids=calendar_ids or ["primary"], source_event_ids=[f"e{i}"])


def mk_trip(day_start, day_end, entities):
    return {
        "id": "trip1",
        "start": datetime.datetime(2026, 9, 7 + day_start, 0, 0),
        "end": datetime.datetime(2026, 9, 7 + day_end, 23, 59),
        "location": "Orlando",
        "entities": set(entities),
    }


def scenario_pax_on_trip_gets_no_ghost():
    # James is on the trip (matched via #james hashtag in the event title, the
    # path the upstream calendar-id filter misses); his event during the trip
    # window must not produce a suggested route.
    pax = Passenger(id="p1", name="James", hashtags=["#james"])
    ev = mk_event(0, day_offset=0, title="Soccer #james")
    trip = mk_trip(0, 3, {"passenger_p1"})

    ga, gd = matcher.solve_ghost_routes([ev], [], [], [pax], trip_metadata=[trip])
    check(ga == {} and gd == [], f"no ghost route for a passenger away on the trip, got {ga}, {gd}")


def scenario_event_outside_trip_window_still_ghosts():
    pax = Passenger(id="p1", name="James", hashtags=["#james"])
    ev = mk_event(0, day_offset=5, title="Soccer #james")  # after the trip ends
    trip = mk_trip(0, 3, {"passenger_p1"})

    ga, gd = matcher.solve_ghost_routes([ev], [], [], [pax], trip_metadata=[trip])
    check(ev.id in ga and len(gd) == 1,
          f"event after the trip window still gets a suggested route, got {ga}, {gd}")


def scenario_pax_not_on_trip_still_ghosts():
    # Sarah stayed home; her in-window event still deserves a suggestion.
    sarah = Passenger(id="p2", name="Sarah", hashtags=["#sarah"])
    ev = mk_event(0, day_offset=1, title="Ballet #sarah")
    trip = mk_trip(0, 3, {"passenger_p1"})  # only James is away

    ga, gd = matcher.solve_ghost_routes([ev], [], [], [sarah], trip_metadata=[trip])
    check(ev.id in ga, f"stay-home passenger's event still gets a suggested route, got {ga}")


def scenario_global_trip_blocks_all_in_window():
    # Whole-family trip: nothing in the window gets a ghost, even untagged events.
    ev_in = mk_event(0, day_offset=1, title="Random Event")
    ev_out = mk_event(1, day_offset=5, title="Random Event After")
    trip = mk_trip(0, 3, {"global"})

    ga, gd = matcher.solve_ghost_routes([ev_in, ev_out], [], [], [], trip_metadata=[trip])
    check(ev_in.id not in ga, f"global trip blocks in-window ghost, got {ga}")
    check(ev_out.id in ga, f"post-trip event still ghosts, got {ga}")


def scenario_calendar_id_match_also_blocked():
    # Passenger matched by calendar id (not hashtag) is equally on the trip.
    pax = Passenger(id="p1", name="James", calendar_ids=["james@cal"])
    ev = mk_event(0, day_offset=1, title="Practice", calendar_ids=["james@cal"])
    trip = mk_trip(0, 3, {"passenger_p1"})

    ga, gd = matcher.solve_ghost_routes([ev], [], [], [pax], trip_metadata=[trip])
    check(ga == {}, f"calendar-id-matched passenger on trip gets no ghost, got {ga}")


def scenario_mixed_passengers_kept():
    # Event carries BOTH an away passenger and a home passenger: not a strict
    # subset of the trip entities, so the home passenger still needs the ride.
    ev = mk_event(0, day_offset=1, title="Practice #james #sarah")
    james = Passenger(id="p1", name="James", hashtags=["#james"])
    sarah = Passenger(id="p2", name="Sarah", hashtags=["#sarah"])
    trip = mk_trip(0, 3, {"passenger_p1"})

    ga, gd = matcher.solve_ghost_routes([ev], [], [], [james, sarah], trip_metadata=[trip])
    check(ev.id in ga, f"event shared with a stay-home passenger still ghosts, got {ga}")


SCENARIOS = [
    scenario_pax_on_trip_gets_no_ghost,
    scenario_event_outside_trip_window_still_ghosts,
    scenario_pax_not_on_trip_still_ghosts,
    scenario_global_trip_blocks_all_in_window,
    scenario_calendar_id_match_also_blocked,
    scenario_mixed_passengers_kept,
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
