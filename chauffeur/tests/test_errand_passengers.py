"""An errand's passenger rules are checked on EVERY leg, with the real riders (2026-11-02).

Device report: an errand with a kid marked "cannot be present" was placed on
the drive home from that kid's own activity. Two layers, both verified in
code before this test was written:

  1. `_pax_in_car` read `event.passengers` / `event.passenger_ids`, fields an
     Event never carries (extra='forbid'), so it always answered "nobody":
     the pass never knew who was in the car on any leg. Dead since the
     helper was first written (86658041).
  2. The from-home and to-home shapes never asked. Only the between-stops
     shape checked prohibited passengers, and required passengers forced
     that shape outright, so the drive home from a pickup (the kid is
     unmistakably in the car) was never examined.

Now the pass is handed the passengers, resolves each stop's riders the way
the solver matches a ride to its passengers (calendar ids and hashtags,
`compute_event_trip_entities`), and models the car: a kid rides from home
to their drop-off, is out of the car until their pickup, and rides home
after it; a ride the driver stays at keeps the kid in the car both ways.
Prohibited passengers bar any leg they ride; required passengers accept any
leg they ride, home legs included. Without passengers the pass behaves as
before.

Grid world and helpers from tests/test_errand_routing.py.
Run from chauffeur/:  python tests/test_errand_passengers.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_errand_routing import (  # noqa: E402  (also installs the grid legs on matcher)
    DAYS, NOW, SETTINGS, _driver, _errand, _ev, _only, _world, check)
from models.schemas import Passenger  # noqa: E402
from solver import matcher  # noqa: E402

KATE = Passenger(id='p_kate', name='Kate', calendar_ids=['kate_cal'])
SAM = Passenger(id='p_sam', name='Sam', calendar_ids=['sam_cal'])
PAX = [KATE, SAM]


def _place(base, errands, drivers, passengers=PAX, settings=SETTINGS):
    by_date, notes = matcher.insert_errands_globally(
        base, errands, drivers, trip_metadata=[], driver_events={}, now=NOW, settings=settings,
        passengers=passengers)
    return [(d, r) for d, rs in by_date.items() for r in rs], notes


def _ride(eid, day_idx, h, loc, title, dur, cal):
    """A drop-off-and-run ride the way the refresh hands it to the pass: the
    Dropoff and Pickup halves, each carrying the ride's calendar."""
    whole = _ev(eid, day_idx, h, loc, title, dur=dur).model_copy(update={'calendar_ids': [cal]})
    drop = whole.model_copy(update={'id': f'{eid}_dropoff', 'event_type': 'dropoff', 'title': f'Dropoff: {title}',
                                    'end': whole.start, 'original_event_id': eid})
    pick = whole.model_copy(update={'id': f'{eid}_pickup', 'event_type': 'pickup', 'title': f'Pickup: {title}',
                                    'start': whole.end, 'original_event_id': eid})
    return drop, pick


def scenario_the_car_model():
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 16, 'Soccer', 'Soccer', 60, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    stops = matcher._driver_day_route(datetime.date(2026, 10, 27), 'd1', base[DAYS[1]], {}, [], passengers=PAX)
    check(matcher._pax_in_car(stops, -1) == {'p_kate'}, "Kate rides from home to her drop-off")
    gap = next(i for i in range(len(stops) - 1) if stops[i].start < stops[i + 1].start)
    check(matcher._pax_in_car(stops, gap) == set(), "Kate is at soccer between the drop and the pickup")
    check(matcher._pax_in_car(stops, len(stops) - 1) == {'p_kate'}, "Kate rides home after her pickup")
    # A ride the driver stays at: Kate is in the car on both home legs.
    stay = _ev('recital', 2, 16, 'Piano', 'Recital', dur=60).model_copy(update={'calendar_ids': ['kate_cal']})
    base2 = _world({2: [stay]}, [jeff], {'recital': 'd1'})
    rules = [{'constraint_type': 'attendance', 'attendance_action': 'stay', 'keywords': ['recital'],
              'driver_id': 'd1', 'id': 'r1'}]
    stops2 = matcher._driver_day_route(datetime.date(2026, 10, 28), 'd1', base2[DAYS[2]], {}, rules, passengers=PAX)
    check(len(stops2) == 1 and matcher._pax_in_car(stops2, -1) == {'p_kate'}
          and matcher._pax_in_car(stops2, 0) == {'p_kate'},
          f"a stay ride keeps Kate in the car both ways: {[(s.title, s.start) for s in stops2]}")
    # No passengers handed over: nobody is ever in the car (the old behaviour).
    stops3 = matcher._driver_day_route(datetime.date(2026, 10, 27), 'd1', base[DAYS[1]], {}, [])
    check(matcher._pax_in_car(stops3, len(stops3) - 1) == set(), "without passengers the pass knows nobody")


def scenario_a_prohibited_kid_bars_the_drive_home_from_her_own_pickup():
    # Tuesday: Jeff drops Kate at Soccer (20,0) 16:00 and picks her up 17:00.
    # The Store (10,10) is on the way: detour 0 on either home leg, 0 inside.
    # The errand window is 17:00-20:00, so the only route legs are the drive
    # home after Kate's pickup. Kate cannot be present.
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 16, 'Soccer', 'Soccer', 60, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    errand = _errand(time_window_start='17:00', time_window_end='20:00', valid_days_of_week=[1],
                     prohibited_passengers=['p_kate'])
    rows, notes = _place(base, [errand], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and r['inserted_after_event_id'] == 'soccer_pickup',
          f"Kate is in the car on the way home, so the errand is a separate trip after she is home: {r['why']} {notes}")
    # The same errand with no prohibition rides home with her, as it did.
    rows, _ = _place(base, [_errand(time_window_start='17:00', time_window_end='20:00', valid_days_of_week=[1])], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Pickup: Soccer', 'to': 'Home'}, f"the drive home is the leg: {r['why']}")
    # Prohibiting SAM, who is not on the ride, changes nothing.
    rows, _ = _place(base, [_errand(time_window_start='17:00', time_window_end='20:00', valid_days_of_week=[1],
                                    prohibited_passengers=['p_sam'])], [jeff])
    _only(rows)


def scenario_a_prohibited_kid_bars_the_drive_from_home_and_leaves_the_inside_slot():
    # Soccer 16:00-18:00. Window 15:00-18:00: the from-home leg (Kate aboard,
    # detour 20) and the drop-to-pickup gap (Kate at soccer, detour 40). With
    # nobody barred the cheaper from-home leg wins; Kate barred means the
    # errand lands INSIDE the ride, the one leg she is not in the car.
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 16, 'Soccer', 'Soccer', 120, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    rows, _ = _place(base, [_errand(time_window_start='15:00', time_window_end='18:00', valid_days_of_week=[1])], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Home', 'to': 'Dropoff: Soccer'}, f"unbarred, the from-home leg wins: {r['why']}")
    errand = _errand(time_window_start='15:00', time_window_end='18:00', valid_days_of_week=[1],
                     prohibited_passengers=['p_kate'])
    rows, notes = _place(base, [errand], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'inside_stop', f"during soccer, Kate out of the car: {r['why']}")
    st = datetime.datetime.fromisoformat(r['start_time'])
    check(st >= drop.start, f"never before the drop-off (Kate rides from home): {st}")


def scenario_a_required_kid_may_ride_home():
    # Kate must be present. Window 17:00-20:00: the drive home after her
    # pickup is exactly the leg she is in the car. Before this fix a required
    # passenger forced the between-stops shape and this errand went unplaced.
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 16, 'Soccer', 'Soccer', 60, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    errand = _errand(time_window_start='17:00', time_window_end='20:00', valid_days_of_week=[1],
                     required_passengers=['p_kate'])
    rows, notes = _place(base, [errand], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Pickup: Soccer', 'to': 'Home'}, f"home with Kate: {r['why']} {notes}")
    # Required Kate, window inside soccer only: she is at soccer, nothing fits.
    errand = _errand(time_window_start='16:00', time_window_end='17:00', valid_days_of_week=[1],
                     required_passengers=['p_kate'])
    rows, notes = _place(base, [errand], [jeff])
    check(not rows and notes.get('er1', {}).get('reason') == 'no_slot',
          f"required Kate is at soccer during the window: {rows} {notes}")
    # A required kid never rides a dedicated trip from an empty day.
    errand = _errand(valid_days_of_week=[0], required_passengers=['p_kate'])
    rows, notes = _place(base, [errand], [jeff])
    check(not rows, f"no ride Monday, so no leg carries Kate: {rows}")


def scenario_the_refresh_hands_the_passengers_over():
    import os as _os
    src = open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'main.py'),
               encoding='utf-8').read()
    i = src.index('matcher.insert_errands_globally(')
    call = src[i:i + 400]
    check('passengers=passengers' in call, f"the refresh passes the passengers to the errand pass: {call[:200]}")


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('scenario_'):
            print(name)
            fn()
    print("errand-passenger scenarios passed")
