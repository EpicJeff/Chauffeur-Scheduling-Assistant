"""A separate trip from home is a candidate on a day with drives too (2026-11-02).

The user's case, from the Errands page: "the only drive with room would get
Lily home after bedtime", and the errand sat unplaced. Why: the round trip
from home existed only on an EMPTY day; on a day with drives the pass looked
at the legs of those drives and nothing else, so once bedtime (or a barred
kid) ruled the one leg out it gave up. A separate trip from home is always
possible in any gap where the driver is home: before the first drive, between
two drives with time to get home and back out, after the last drive. It
carries nobody, so prohibited riders and bedtime never bite, and it keeps the
dedicated-trip penalty so a passing leg still wins whenever one exists.
Required riders still force a leg they ride. The "only drive with room" note
now fires only when even the round trip does not fit.

Grid world and helpers from tests/test_errand_routing.py.
Run from chauffeur/:  python tests/test_errand_dedicated_gap.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_errand_routing import (  # noqa: E402  (installs the grid legs on matcher)
    DAYS, NOW, SETTINGS, _driver, _errand, _ev, _only, _world, check)
from models.schemas import Passenger  # noqa: E402
from solver import matcher  # noqa: E402

LILY = Passenger(id='p_lily', name='Lily', calendar_ids=['lily_cal'])
PAX = [LILY]


def _place(base, errands, drivers, settings=SETTINGS, passengers=PAX):
    by_date, notes = matcher.insert_errands_globally(
        base, errands, drivers, trip_metadata=[], driver_events={}, now=NOW, settings=settings,
        passengers=passengers)
    return [(d, r) for d, rs in by_date.items() for r in rs], notes


def _ride(eid, day_idx, h, m, loc, title, dur, cal):
    whole = _ev(eid, day_idx, h, loc, title, m=m, dur=dur).model_copy(update={'calendar_ids': [cal]})
    drop = whole.model_copy(update={'id': f'{eid}_dropoff', 'event_type': 'dropoff', 'title': f'Dropoff: {title}',
                                    'end': whole.start, 'original_event_id': eid})
    pick = whole.model_copy(update={'id': f'{eid}_pickup', 'event_type': 'pickup', 'title': f'Pickup: {title}',
                                    'start': whole.end, 'original_event_id': eid})
    return drop, pick


def _t(r, key='start_time'):
    return datetime.datetime.fromisoformat(r[key]).strftime('%H:%M')


def scenario_after_the_last_drive_a_trip_from_home_is_proposed():
    # Tuesday: Jeff brings Lily home from Soccer (20,0) at 17:00. Lily may not
    # be present for the Store (10,10) run, so the drive home is out. Home by
    # 17:20, out again at 17:40 (Home -> Store 20), 30 min at the Store, home
    # by 18:30. Window 17:00-20:00, Tuesday only.
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 16, 0, 'Soccer', 'Soccer', 60, 'lily_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    errand = _errand(time_window_start='17:00', time_window_end='20:00', valid_days_of_week=[1],
                     prohibited_passengers=['p_lily'])
    rows, notes = _place(base, [errand], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and r['why']['detour_mins'] == 40
          and r['why']['text'] == 'a trip from home, 20 min each way', f"a separate trip from home: {r['why']}")
    check(_t(r) == '17:40', f"leaves after Lily is home: {_t(r)}")
    check(r['inserted_after_event_id'] == 'soccer_pickup' and r['inserted_before_event_id'] is None,
          f"the row sits after the pickup on the timeline: {r}")
    check(notes == {}, f"{notes}")
    # With no one barred the drive home itself is cheaper (detour 0 vs 40 + 25) and still wins.
    rows, _ = _place(base, [_errand(time_window_start='17:00', time_window_end='20:00', valid_days_of_week=[1])], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Pickup: Soccer', 'to': 'Home'}, f"the passing leg wins when it may: {r['why']}")


def scenario_before_the_first_drive_and_between_two():
    jeff = _driver('d1', 'Jeff')
    # Before: Lily rides from home to a 16:00 drop-off, barred from the Store.
    # The trip from home runs at the window's start (a standing window
    # overrides the 09:00 band) and is back long before the drive to soccer.
    drop, pick = _ride('soccer', 1, 16, 0, 'Soccer', 'Soccer', 60, 'lily_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    errand = _errand(time_window_start='08:00', time_window_end='12:00', valid_days_of_week=[1],
                     prohibited_passengers=['p_lily'])
    rows, notes = _place(base, [errand], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and _t(r) == '08:00', f"a morning trip from home: {r['why']} {_t(r)}")
    check(r['inserted_after_event_id'] is None and r['inserted_before_event_id'] == 'soccer_dropoff', f"{r}")
    # Between: Lorena's work 09:00-12:00 at (0,30), then Lily's soccer drop at
    # 16:00. Home from work by 12:30, out again 12:50 for the Pharmacy (0,20):
    # but Work -> Pharmacy -> Soccer is on the way (detour 10+30-50 = -10 -> 0),
    # so the passing leg wins over 40 + 25. Bar Lily and the between leg (Lily
    # not aboard: she boards at home for the drop-off... she rides from home,
    # so the leg from Work to the drop-off carries her) is out, and the trip
    # from home between the two is what remains.
    lorena = _driver('d2', 'Lorena')
    work = _ev('work', 1, 9, 'Work', 'Work', dur=180)
    base = _world({1: [drop, pick]}, [lorena], {'soccer_dropoff': 'd2', 'soccer_pickup': 'd2'})
    errand = _errand(location='Pharmacy', time_window_start='12:00', time_window_end='15:00', valid_days_of_week=[1])
    by_date, _ = matcher.insert_errands_globally(base, [errand], [lorena], trip_metadata=[], driver_events={'d2': [work]},
                                                 now=NOW, settings=SETTINGS, passengers=PAX)
    rows = [(d, x) for d, xs in by_date.items() for x in xs]
    d, r = _only(rows)
    check(r['why']['kind'] == 'on_the_way' and r['why']['leg'] == {'from': 'Work', 'to': 'Dropoff: Soccer'},
          f"the passing leg from work to soccer wins: {r['why']}")
    errand = _errand(location='Pharmacy', time_window_start='12:00', time_window_end='15:00', valid_days_of_week=[1],
                     prohibited_passengers=['p_lily'])
    by_date, notes = matcher.insert_errands_globally(base, [errand], [lorena], trip_metadata=[], driver_events={'d2': [work]},
                                                     now=NOW, settings=SETTINGS, passengers=PAX)
    rows = [(d, x) for d, xs in by_date.items() for x in xs]
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and r['why']['detour_mins'] == 40, f"a trip from home between work and soccer: {r['why']}")
    check(_t(r) >= '12:50', f"out again only after getting home from work (12:30) and driving there (20): {_t(r)}")
    check(r['inserted_after_event_id'] == 'work' and r['inserted_before_event_id'] == 'soccer_dropoff', f"{r}")


def scenario_required_riders_and_too_short_gaps():
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 16, 0, 'Soccer', 'Soccer', 60, 'lily_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    # Lily required: a trip from home carries nobody, so it is never her leg.
    errand = _errand(time_window_start='16:00', time_window_end='17:00', valid_days_of_week=[1],
                     required_passengers=['p_lily'])
    rows, notes = _place(base, [errand], [jeff])
    check(not rows and notes.get('er1', {}).get('reason') == 'no_slot', f"{rows} {notes}")
    # A gap too short for the round trip: barred Lily, window 17:00-17:30 (the
    # trip needs 17:40 at the earliest).
    errand = _errand(time_window_start='17:00', time_window_end='17:30', valid_days_of_week=[1],
                     prohibited_passengers=['p_lily'])
    rows, notes = _place(base, [errand], [jeff])
    check(not rows and notes.get('er1', {}).get('reason') == 'no_slot', f"{rows} {notes}")


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('scenario_'):
            print(name)
            fn()
    print("errand-dedicated-gap scenarios passed")
