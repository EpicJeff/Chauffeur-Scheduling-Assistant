"""Kids aboard an errand leg must be home by their bedtime bound (2026-11-02).

The user's case: an errand may allow a kid to be present, but the parent
would not run it on the way home from an activity that ends at 8pm, because
the kid needs to get to bed. No new errand field: the house already holds the
fact. A kid's bound on a day is the START of their timed bedtime routine
(the first bedtime item with a time), else the household kid quiet hours
start (default 20:30) minus `errand_kids_home_margin_mins` (default 30).
Adults have no bound. Only the drive-home leg is checked: on the way to a
drop-off the kid is headed to the activity, and a between-stops leg is
bounded by the next stop already.

When the only drives with room would get a kid home after their bound, the
errand is reported with reason `kids_bedtime`, naming the kid, so a card
that vanished does not read as a solver whim. The steer sheet remains the
hand path to override it.

Grid world and helpers from tests/test_errand_routing.py.
Run from chauffeur/:  python tests/test_errand_bedtime.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_errand_routing import (  # noqa: E402  (installs the grid legs on matcher)
    DAYS, MON, NOW, _driver, _errand, _ev, _only, _world, check)
from models.schemas import Passenger, Settings  # noqa: E402
from services import settings_registry, storage  # noqa: E402
from solver import matcher  # noqa: E402

KATE = Passenger(id='p_kate', name='Kate', calendar_ids=['kate_cal'])
DAD = Passenger(id='p_dad', name='Jeff', calendar_ids=['dad_cal'])
PAX = [KATE, DAD]
TUE = MON + datetime.timedelta(days=1)


def _reset(kate_bedtime=None, kate_role='child'):
    for t in (storage.members_table, storage.routines_table, storage.routine_checks_table):
        t.truncate()
    storage.add_member({'id': 'm_kate', 'name': 'Kate', 'role': kate_role, 'passenger_id': 'p_kate'})
    storage.add_member({'id': 'm_dad', 'name': 'Jeff', 'role': 'parent', 'passenger_id': 'p_dad'})
    if kate_bedtime:
        storage.add_routine({'id': 'r_bed', 'member_id': 'm_kate', 'title': 'Bath', 'runway': 'bedtime',
                             'time_of_day': kate_bedtime, 'days_of_week': []})
        storage.add_routine({'id': 'r_lights', 'member_id': 'm_kate', 'title': 'Lights out', 'runway': 'bedtime',
                             'time_of_day': '21:30', 'days_of_week': []})


def _place(base, errands, drivers, settings=None, passengers=PAX):
    settings = {'errand_dedicated_trip_mins': 25, **(settings or {})}
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


def _hm(dt):
    return dt.astimezone().strftime('%H:%M') if dt else None


def _t(r, key='start_time'):
    return datetime.datetime.fromisoformat(r[key]).strftime('%H:%M')


def scenario_the_bound():
    _reset()
    s = {'kid_quiet_start': '20:30'}
    check(_hm(matcher.kid_home_bound('p_kate', TUE, s)) == '20:00',
          "no bedtime item: quiet hours start minus the 30 min default margin")
    check(_hm(matcher.kid_home_bound('p_kate', TUE, {**s, 'errand_kids_home_margin_mins': 45})) == '19:45',
          "the margin is the setting")
    check(matcher.kid_home_bound('p_dad', TUE, s) is None, "an adult has no bound")
    check(matcher.kid_home_bound('p_nobody', TUE, s) is None, "an unknown rider has no bound")
    check(matcher.kid_home_bound('p_kate', TUE, {'kid_quiet_start': '20:30', 'kid_quiet_end': '20:30'}) is None,
          "quiet hours disabled (start == end) and no item: no bound")
    _reset(kate_bedtime='19:30')
    check(_hm(matcher.kid_home_bound('p_kate', TUE, s)) == '19:30',
          "with a timed bedtime routine the bound is its START, no margin")
    _reset(kate_role='adult')
    check(matcher.kid_home_bound('p_kate', TUE, s) is None, "a grown-up Kate has no bound")


def scenario_the_drive_home_past_bedtime_is_not_an_errand_leg():
    # Tuesday: Soccer 18:30-19:30 at (20,0), Kate aboard home. The Store (10,10)
    # is on the way (detour 0): errand 19:50-20:20, then 20 min home = 20:40,
    # past Kate's 20:00 bound. Window 19:00-21:00, Tuesday only: the drive from
    # home (Kate aboard, but headed TO soccer) ends before the window, so the
    # drive home is the only leg.
    _reset()
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 18, 30, 'Soccer', 'Soccer', 60, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    errand = _errand(time_window_start='19:00', time_window_end='21:00', valid_days_of_week=[1])
    rows, notes = _place(base, [errand], [jeff], settings={'kid_quiet_start': '20:30'})
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and _t(r) == '20:10' and r['inserted_after_event_id'] == 'soccer_pickup',
          f"not on the drive home: a separate trip once Kate is in (19:50), out again 20:10: {r['why']} {_t(r)}")
    # Window closing at 20:30: the separate trip (20:10-20:40) does not fit
    # either, and the note says why the one drive with room was no good.
    errand = _errand(time_window_start='19:00', time_window_end='20:30', valid_days_of_week=[1])
    rows, notes = _place(base, [errand], [jeff], settings={'kid_quiet_start': '20:30'})
    check(not rows and notes.get('er1', {}).get('reason') == 'kids_bedtime',
          f"not placed, and the reason says why: {rows} {notes}")
    check('Kate' in notes['er1']['text'] and 'bedtime' in notes['er1']['text'], f"names the kid: {notes['er1']}")
    errand = _errand(time_window_start='19:00', time_window_end='21:00', valid_days_of_week=[1])
    # Her bedtime routine starting at 21:00 moves the bound: now it fits.
    _reset(kate_bedtime='21:00')
    rows, notes = _place(base, [errand], [jeff], settings={'kid_quiet_start': '20:30'})
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Pickup: Soccer', 'to': 'Home'}, f"home with Kate before her bath: {r['why']}")
    # Same ride earlier in the day: the errand runs 19:00-19:30 on the way
    # home, Kate in by 19:50, inside the bound.
    _reset()
    drop, pick = _ride('soccer', 1, 16, 0, 'Soccer', 'Soccer', 60, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    rows, _ = _place(base, [errand], [jeff], settings={'kid_quiet_start': '20:30'})
    _only(rows)
    # The 18:30 ride without Kate aboard (dad's own calendar): no kid, no bound.
    drop, pick = _ride('late', 1, 18, 30, 'Soccer', 'Late thing', 60, 'dad_cal')
    base = _world({1: [drop, pick]}, [jeff], {'late_dropoff': 'd1', 'late_pickup': 'd1'})
    rows, _ = _place(base, [errand], [jeff], settings={'kid_quiet_start': '20:30'})
    _only(rows)


def scenario_a_kid_already_late_is_not_made_later():
    # Soccer ends 19:45, Kate home 20:05, already past her 20:00 bound without
    # the errand. Still no errand on that leg: later is worse, not irrelevant.
    # Jeff goes out again alone at 20:25 instead.
    _reset()
    jeff = _driver('d1', 'Jeff')
    drop, pick = _ride('soccer', 1, 19, 0, 'Soccer', 'Soccer', 45, 'kate_cal')
    base = _world({1: [drop, pick]}, [jeff], {'soccer_dropoff': 'd1', 'soccer_pickup': 'd1'})
    errand = _errand(time_window_start='19:00', time_window_end='21:00', valid_days_of_week=[1])
    rows, notes = _place(base, [errand], [jeff], settings={'kid_quiet_start': '20:30'})
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and _t(r) == '20:25', f"{r['why']} {_t(r)} {notes}")


def scenario_the_setting_has_its_home():
    check(Settings().errand_kids_home_margin_mins == 30, "model default 30")
    entry = next((e for e in settings_registry.ENTRIES if e['key'] == 'errand_kids_home_margin_mins'), None)
    check(entry and entry['page'].startswith('errands') and entry['anchor'] == 'errand-settings',
          f"registered on the Errands drawer: {entry}")
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'errands.html')
    page = open(tpl, encoding='utf-8').read()
    check('errand_kids_home_margin_mins' in page and 'errand-kids-home-margin-mins' in page,
          "the drawer carries the input")
    check('kids_bedtime' in matcher.ERRAND_UNPLACED_TEXT, "the note has a default text")


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('scenario_'):
            print(name)
            fn()
    print("errand-bedtime scenarios passed")
