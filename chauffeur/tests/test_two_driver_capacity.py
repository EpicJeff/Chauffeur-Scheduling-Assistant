"""Solver tests for per-driver seat math (riding_passengers): a driver's own
passenger record holds the wheel instead of a passenger seat, and a co-driver
ATTENDING the event self-transports in a car of their own — so a family
outing bigger than any single car splits across the drivers who are going
anyway, instead of the whole event going unassigned.

Run from chauffeur/:  python tests/test_two_driver_capacity.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event, Passenger, Car
from solver import matcher


def mk_driver(i, priority_index=1, **kw):
    return Driver(id=f"d{i}", name=f"Driver {i}", color_code="#fff",
                  group="primary", priority_index=priority_index, **kw)


def mk_event(i, start_hour=9, duration_mins=60, cal_ids=None):
    day = datetime.datetime(2026, 9, 7)
    start = day.replace(hour=start_hour)
    return Event(id=f"e{i}", title=f"Event {i}", start=start,
                 end=start + datetime.timedelta(minutes=duration_mins),
                 location=None, calendar_ids=cal_ids or ["primary"],
                 source_event_ids=[f"e{i}"])


def kid(i):
    return Passenger(id=f"p{i}", name=f"Kid {i}", calendar_ids=[f"kidcal{i}"])


def adult_pax(i):
    # A parent's own passenger record (dual-role member), bound via their cal.
    return Passenger(id=f"pd{i}", name=f"Driver {i}", calendar_ids=[f"dcal{i}"])


DPM = {"d1": "pd1", "d2": "pd2"}


def family_outing(kids=3):
    """Everyone goes: 2 drivers (as attendees AND as passenger records) plus
    `kids` kids, all bound onto one event."""
    cals = ["primary", "dcal1", "dcal2"] + [f"kidcal{i}" for i in range(1, kids + 1)]
    ev = mk_event(1, cal_ids=cals)
    drivers = [mk_driver(1, 1), mk_driver(2, 4)]
    pax = [adult_pax(1), adult_pax(2)] + [kid(i) for i in range(1, kids + 1)]
    d_events = {"d1": [ev], "d2": [ev]}  # both drivers attend
    return ev, drivers, pax, d_events


def scenario_two_attending_drivers_split_cars():
    # The reported gap: 2 drivers + 3 kids = 5 heads; best car seats 4
    # passengers. Old math: 5 pax > 4 seats in every car -> unassigned.
    # New math for the assigned driver: own record drives (not cargo) and the
    # co-attending driver self-drives the second car -> 3 kids ride, fits.
    ev, drivers, pax, d_events = family_outing(kids=3)
    cars = [Car(id="van", name="Van", seat_capacity=4, allowed_driver_ids=["d1", "d2"]),
            Car(id="coupe", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1", "d2"])]
    a, un, _, ca = matcher.solve_schedule([ev], drivers, [], driver_events=d_events,
                                          passengers=pax, cars=cars,
                                          driver_passenger_map=DPM)
    check(not un, f"two attending drivers split cars — event must assign, got unassigned={un}")
    check(a.get("e1") in ("d1", "d2"), f"one of the attending drivers drives, got {a}")
    check(ca.get("e1") == "van", f"the kids need the van, got {ca}")


def scenario_driver_own_seat_never_counts():
    # One driver attending, their own passenger record among the pax: 1 adult
    # record + 4 kids = 5, van seats 4. The adult drives -> 4 ride -> fits.
    cals = ["primary", "dcal1"] + [f"kidcal{i}" for i in range(1, 5)]
    ev = mk_event(1, cal_ids=cals)
    drivers = [mk_driver(1)]
    pax = [adult_pax(1)] + [kid(i) for i in range(1, 5)]
    cars = [Car(id="van", name="Van", seat_capacity=4, allowed_driver_ids=["d1"])]
    a, un, _, _ = matcher.solve_schedule([ev], drivers, [], driver_events={"d1": [ev]},
                                         passengers=pax, cars=cars,
                                         driver_passenger_map=DPM)
    check(not un and a.get("e1") == "d1",
          f"driver's own record sits behind the wheel, not in a seat: {a}, {un}")


def scenario_non_attending_driver_is_cargo():
    # d2's passenger record rides along but d2 is not driving today (not in
    # the solve) and not attending: their record is cargo like anyone else.
    # riding for d1 = pd2 + 4 kids = 5 > 4 van seats -> unassigned.
    cals = ["primary", "dcal1", "dcal2"] + [f"kidcal{i}" for i in range(1, 5)]
    ev = mk_event(1, cal_ids=cals)
    drivers = [mk_driver(1)]
    pax = [adult_pax(1), adult_pax(2)] + [kid(i) for i in range(1, 5)]
    cars = [Car(id="van", name="Van", seat_capacity=4, allowed_driver_ids=["d1"])]
    a, un, _, _ = matcher.solve_schedule([ev], drivers, [], driver_events={"d1": [ev]},
                                         passengers=pax, cars=cars,
                                         driver_passenger_map=DPM)
    check(un == ["e1"],
          f"a non-attending absent driver's record is cargo like anyone else, got {a}, {un}")


def scenario_one_car_fleet_cannot_split():
    # Both drivers attend but the family owns ONE car: the co-driver has no
    # second car to self-transport in, so the honest answer stays unassigned.
    ev, drivers, pax, d_events = family_outing(kids=4)  # 2 adults + 4 kids
    cars = [Car(id="van", name="Van", seat_capacity=4, allowed_driver_ids=["d1", "d2"])]
    a, un, _, _ = matcher.solve_schedule([ev], drivers, [], driver_events=d_events,
                                         passengers=pax, cars=cars,
                                         driver_passenger_map=DPM)
    check(un == ["e1"],
          f"one car can't split — co-driver can't self-transport, got {a}, {un}")


def scenario_implicit_personal_car_codriver():
    # No cars configured at all, but d1 has a graduated-licensing cap of 3.
    # 2 adult records + 3 kids: with d2 attending (implicit personal car),
    # d1 carries only the 3 kids -> under the cap -> assigns.
    ev, drivers, pax, d_events = family_outing(kids=3)
    drivers[0].max_passengers = 3
    drivers[1].max_passengers = 0  # d2 can't take anyone; d1 must drive
    a, un, _, _ = matcher.solve_schedule([ev], drivers, [], driver_events=d_events,
                                         passengers=pax,
                                         driver_passenger_map=DPM)
    check(not un and a.get("e1") == "d1",
          f"co-driver on implicit personal car frees d1's cap, got {a}, {un}")


def scenario_no_map_is_the_old_behavior():
    # Without the driver->passenger link the solver can't know who holds a
    # wheel: everything counts as cargo, exactly as before.
    ev, drivers, pax, d_events = family_outing(kids=3)
    cars = [Car(id="van", name="Van", seat_capacity=4, allowed_driver_ids=["d1", "d2"]),
            Car(id="coupe", name="Coupe", seat_capacity=1, allowed_driver_ids=["d1", "d2"])]
    a, un, _, _ = matcher.solve_schedule([ev], drivers, [], driver_events=d_events,
                                         passengers=pax, cars=cars)
    check(un == ["e1"], f"no link map -> unchanged legacy behavior, got {a}, {un}")


def scenario_diagnostics_mirror_seat_math():
    # The one-car family that can't split: the reason must speak in RIDING
    # counts (4 kids after the drivers' records are excluded), not raw heads.
    ev, drivers, pax, d_events = family_outing(kids=4)
    cars = [Car(id="van", name="Van", seat_capacity=3, allowed_driver_ids=["d1", "d2"])]
    diags = matcher.compute_diagnostics(["e1"], [ev], drivers, d_events, {}, [], [],
                                        passengers=pax, cars=cars,
                                        driver_passenger_map=DPM)
    texts = str(diags.get("e1") or "")
    check("seats 3" in texts, f"capacity reason survives, got {texts}")


if __name__ == "__main__":
    import traceback
    scenarios = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]
    failed = 0
    for fn in scenarios:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(scenarios) - failed}/{len(scenarios)} scenarios passed")
    raise SystemExit(1 if failed else 0)
