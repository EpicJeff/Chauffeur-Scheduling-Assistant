"""Solver tests for the Car dimension (solver/matcher.py, docs/car_entity_design.md).

Cars are time-shared tokens: allowed drivers, seat capacity, car-seat passenger
restrictions, availability windows, home handoffs between drivers, and a swap
penalty keeping cars with their default drivers. The whole dimension must be
inert when no cars are configured, and drivers listed on no car keep an
implicit personal car.

Run from chauffeur/:  python tests/test_cars.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event, Passenger, Car
from solver import matcher


def mk_driver(i, priority_index=1, **kw):
    return Driver(id=f"d{i}", name=f"Driver {i}", color_code="#fff",
                  group="primary", priority_index=priority_index, **kw)


def mk_event(i, start_hour, duration_mins=60, location=None, cal_ids=None, start_min=0, day_offset=0):
    day = datetime.datetime(2026, 9, 7) + datetime.timedelta(days=day_offset)
    start = day.replace(hour=start_hour, minute=start_min)
    return Event(id=f"e{i}", title=f"Event {i}", start=start,
                 end=start + datetime.timedelta(minutes=duration_mins),
                 location=location,
                 calendar_ids=cal_ids or ["primary"], source_event_ids=[f"e{i}"])


def mk_pax(i, **kw):
    return Passenger(id=f"p{i}", name=f"Kid {i}", calendar_ids=[f"kidcal{i}"], **kw)


def pax_cals(*idx):
    return ["primary"] + [f"kidcal{i}" for i in idx]


def scenario_zero_cars_inert():
    # No cars: 4th return value is empty and assignment matches pre-car behavior.
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    events = [mk_event(i, 8 + i * 3) for i in range(3)]
    a, un, _, ca = matcher.solve_schedule(events, drivers, [])
    check(not un, "all assigned with no cars")
    check(ca == {}, f"no cars -> empty car_assignments, got {ca}")
    check(all(d == "d1" for d in a.values()), f"priority driver still wins, got {a}")

    a2, un2, _, ca2 = matcher.solve_schedule(events, drivers, [], cars=[])
    check(a == a2 and un == un2 and ca2 == {}, "cars=[] identical to no cars")


def scenario_implicit_personal_car():
    # d1 is pooled onto a tiny car; d2 is on no car and must be untouched:
    # an event too big for d1's car falls to d2's implicit personal car.
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    pax = [mk_pax(1), mk_pax(2), mk_pax(3)]
    car = Car(id="c_small", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1"])
    ev = mk_event(1, 9, cal_ids=pax_cals(1, 2, 3))
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], passengers=pax, cars=[car])
    check(a.get(ev.id) == "d2", f"unpooled driver takes the event, got {a}")
    check(ev.id not in ca, f"implicit personal car never appears in car_assignments, got {ca}")


def scenario_capacity_ban_and_fit():
    # Sole driver's only car seats 1; a 2-kid event is unassignable until the
    # car grows.
    drivers = [mk_driver(1)]
    pax = [mk_pax(1), mk_pax(2)]
    ev = mk_event(1, 9, cal_ids=pax_cals(1, 2))

    small = Car(id="c1", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1"])
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], passengers=pax, cars=[small])
    check(ev.id in un, f"2 kids don't fit a 1-seat car, got {a}")

    van = Car(id="c1", name="Van", seat_capacity=4, allowed_driver_ids=["d1"])
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], passengers=pax, cars=[van])
    check(a.get(ev.id) == "d1", f"kids fit the van, got un={un}")
    check(ca.get(ev.id) == "c1", f"van recorded in car_assignments, got {ca}")


def scenario_car_seat_restriction():
    # The sedan has no booster for Kid 2.
    drivers = [mk_driver(1)]
    pax = [mk_pax(1), mk_pax(2)]
    sedan = Car(id="c1", name="Sedan", seat_capacity=4, allowed_driver_ids=["d1"],
                allowed_passenger_ids=["p1"])

    ok = mk_event(1, 9, cal_ids=pax_cals(1))
    bad = mk_event(2, 13, cal_ids=pax_cals(2))
    a, un, _, ca = matcher.solve_schedule([ok, bad], drivers, [], passengers=pax, cars=[sedan])
    check(a.get(ok.id) == "d1" and ca.get(ok.id) == "c1", f"belted kid rides, got {a} {ca}")
    check(bad.id in un, f"kid without a car seat can't ride, got {a}")


def scenario_one_car_two_drivers_contention():
    # Two pooled drivers, one car, overlapping stay-at events at different
    # places (attendance blocks one driver covering both via drop-off
    # profiles): only one event can run. With a wide gap, the home handoff
    # works and both run.
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    pax = [mk_pax(1, requires_attendance=True), mk_pax(2, requires_attendance=True)]
    car = Car(id="c1", name="Van", seat_capacity=4, allowed_driver_ids=["d1", "d2"])
    e1 = mk_event(1, 9, location="A", cal_ids=pax_cals(1))
    e2 = mk_event(2, 9, start_min=30, location="B", cal_ids=pax_cals(2))
    a, un, _, ca = matcher.solve_schedule([e1, e2], drivers, [], passengers=pax, cars=[car])
    check(len(un) == 1, f"one car can't cover overlapping events, got a={a} un={un}")
    # Sanity: two cars -> both run on different drivers.
    car2 = Car(id="c2", name="Sedan", seat_capacity=4, allowed_driver_ids=["d1", "d2"])
    a, un, _, ca = matcher.solve_schedule([e1, e2], drivers, [], passengers=pax, cars=[car, car2])
    check(not un, f"second car unlocks both events, got un={un}")
    check({a[e1.id], a[e2.id]} == {"d1", "d2"} and {ca[e1.id], ca[e2.id]} == {"c1", "c2"},
          f"one driver+car per event, got a={a} ca={ca}")

    e3 = mk_event(3, 8, location="A", cal_ids=pax_cals(1))
    e4 = mk_event(4, 12, location="B", cal_ids=pax_cals(2))
    a, un, _, ca = matcher.solve_schedule([e3, e4], drivers, [], passengers=pax, cars=[car])
    check(not un, f"sequential events share the car via home handoff, got un={un}")
    check(ca.get(e3.id) == "c1" and ca.get(e4.id) == "c1", f"both used the one car, got {ca}")


def scenario_chain_keeps_same_car():
    # A driver chaining back-to-back events cannot swap cars mid-chain.
    drivers = [mk_driver(1)]
    pax = [mk_pax(1), mk_pax(2)]
    coupe = Car(id="c_coupe", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1"])
    van = Car(id="c_van", name="Van", seat_capacity=4, allowed_driver_ids=["d1"])
    # e1 fits either car; e2 (2 kids, 5 min later at another location — gap too
    # small to detour anywhere and swap) fits only the van: chain continuity
    # must force the van for BOTH. The shared kid keeps the tight chain legal
    # (arrive-late semantics) for the driver.
    e1 = mk_event(1, 9, duration_mins=60, location="A", cal_ids=pax_cals(1))
    e2 = mk_event(2, 10, start_min=5, duration_mins=60, location="B", cal_ids=pax_cals(1, 2))
    a, un, _, ca = matcher.solve_schedule([e1, e2], drivers, [], passengers=[mk_pax(1), mk_pax(2)], cars=[coupe, van])
    check(not un, f"both events run, got un={un}")
    check(ca.get(e1.id) == "c_van" and ca.get(e2.id) == "c_van",
          f"chain forces the van for both legs, got {ca}")


def scenario_default_driver_no_churn():
    # Both parents may drive both cars; simultaneous events: each keeps their
    # default car rather than swapping.
    drivers = [mk_driver(1, 1), mk_driver(2, 1)]
    car_a = Car(id="c_a", name="Car A", seat_capacity=4, allowed_driver_ids=["d1", "d2"], default_driver_id="d1")
    car_b = Car(id="c_b", name="Car B", seat_capacity=4, allowed_driver_ids=["d1", "d2"], default_driver_id="d2")
    e1 = mk_event(1, 9, location="A")
    e2 = mk_event(2, 9, location="B")
    a, un, _, ca = matcher.solve_schedule([e1, e2], drivers, [], cars=[car_a, car_b])
    check(not un, f"both run, got un={un}")
    by_driver = {a[e.id]: ca.get(e.id) for e in (e1, e2)}
    check(by_driver.get("d1") == "c_a" and by_driver.get("d2") == "c_b",
          f"each driver keeps their default car, got a={a} ca={ca}")


def scenario_unavailable_range():
    # The van is loaned out on the event's date; the only driver is pooled -> unassigned.
    drivers = [mk_driver(1)]
    van = Car(id="c1", name="Van", seat_capacity=4, allowed_driver_ids=["d1"],
              unavailable_ranges=[{"start": "2026-09-07", "end": "2026-09-09", "reason": "loaned to Aunt Sarah"}])
    ev = mk_event(1, 9)
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], cars=[van])
    check(ev.id in un, f"loaned-out car blocks the only driver, got {a}")

    later = mk_event(2, 9, day_offset=5)
    a, un, _, ca = matcher.solve_schedule([later], drivers, [], cars=[van])
    check(a.get(later.id) == "d1", f"car back home after the loan, got un={un}")


def scenario_override_beats_car_ban():
    # A manual override wins over a capacity ban, like every other hard ban.
    drivers = [mk_driver(1)]
    pax = [mk_pax(1), mk_pax(2)]
    small = Car(id="c1", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1"])
    ev = mk_event(1, 9, cal_ids=pax_cals(1, 2))
    ovr = [{"event_id": ev.id, "driver_id": "d1", "created_at": 1750000000}]
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], overrides=ovr, passengers=pax, cars=[small])
    check(a.get(ev.id) == "d1", f"override beats the car capacity ban, got un={un}")


def scenario_driver_max_passengers():
    # Teen driver capped at 1 passenger; the 2-kid run goes to the parent.
    teen = mk_driver(1, 1, max_passengers=1)
    parent = mk_driver(2, 4)
    pax = [mk_pax(1), mk_pax(2)]
    ev = mk_event(1, 9, cal_ids=pax_cals(1, 2))
    a, un, _, ca = matcher.solve_schedule([ev], [teen, parent], [], passengers=pax)
    check(a.get(ev.id) == "d2", f"passenger cap sends the run to the parent, got {a}")

    solo = mk_event(2, 13, cal_ids=pax_cals(1))
    a, un, _, ca = matcher.solve_schedule([solo], [teen, parent], [], passengers=pax)
    check(a.get(solo.id) == "d1", f"teen may still drive one kid, got {a}")


def scenario_disabled_car_ignored():
    # A disabled car neither pools its driver nor constrains anything.
    drivers = [mk_driver(1)]
    pax = [mk_pax(1), mk_pax(2)]
    small = Car(id="c1", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1"], is_disabled=True)
    ev = mk_event(1, 9, cal_ids=pax_cals(1, 2))
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], passengers=pax, cars=[small])
    check(a.get(ev.id) == "d1", f"disabled car is inert, got un={un}")
    check(ca == {}, f"disabled car never assigned, got {ca}")


SCENARIOS = [
    scenario_zero_cars_inert,
    scenario_implicit_personal_car,
    scenario_capacity_ban_and_fit,
    scenario_car_seat_restriction,
    scenario_one_car_two_drivers_contention,
    scenario_chain_keeps_same_car,
    scenario_default_driver_no_churn,
    scenario_unavailable_range,
    scenario_override_beats_car_ban,
    scenario_driver_max_passengers,
    scenario_disabled_car_ignored,
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
