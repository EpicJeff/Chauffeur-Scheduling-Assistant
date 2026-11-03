"""Errand habits: how each person runs errands, in the solver pass (2026-11-02).

Spec: docs/superpowers/specs/2026-11-02-errand-habits-design.md §2, §3.

Three facts per person, read from storage.get_errand_habits() once per run:
errand hours (days, start, end; strict or preferred), separate trips (the
household number, a personal one, or never) and the kinds they run together.
Errand hours are not driving hours, and a passing leg obeys them too. For a
kind someone runs together the constrained errand is placed first and the free
ones chain beside it on the route.

Grid world and helpers from tests/test_errand_routing.py; the split-ride
helper from tests/test_errand_dedicated_gap.py.
Run from chauffeur/:  python tests/test_errand_habits.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_errand_routing import (  # noqa: E402  (installs the grid legs on matcher)
    DAYS, NOW, SETTINGS, _driver, _errand, _ev, _only, _place, _world, check)
from test_errand_dedicated_gap import _ride, _t  # noqa: E402
from services import storage  # noqa: E402
from solver import matcher  # noqa: E402

WEEKDAYS = [0, 1, 2, 3, 4]


def _habits(by_driver):
    """The pass reads storage.get_errand_habits() once per run."""
    storage.get_errand_habits = lambda: dict(by_driver)


def _hours(days, start, end, strict=True, **more):
    h = {'hours': [{'days': list(days), 'start': start, 'end': end}], 'hours_strict': strict}
    h.update(more)
    return h


def _soccer_tuesday(driver_id):
    drop, pick = _ride('soccer', 1, 16, 0, 'Soccer', 'Soccer', 60, 'lily_cal')
    return _world({1: [drop, pick]}, [], {'soccer_dropoff': driver_id, 'soccer_pickup': driver_id})


def scenario_strict_hours_shape_every_candidate():
    # Jeff runs errands 13:00-15:00 on weekdays, strictly. Tuesday he drives
    # Soccer (drop 16:00, pickup 17:00). Store (10,10) errand, Tuesday only,
    # no window of its own.
    jeff = _driver('d1', 'Jeff')
    base = _soccer_tuesday('d1')
    _habits({'d1': _hours(WEEKDAYS, '13:00', '15:00')})
    rows, notes = _place(base, [_errand(valid_days_of_week=[1])], [jeff])
    d, r = _only(rows)
    # The leg on the way to the drop-off fits inside the hours (latest start
    # 14:30 so the errand ends by 15:00) and beats a trip from home.
    check(r['why']['kind'] == 'on_the_way' and r['why']['leg'] == {'from': 'Home', 'to': 'Dropoff: Soccer'}
          and _t(r) == '14:30', f"the passing leg inside the hours: {r['why']} {_t(r)}")
    check(r['why'].get('hours') == 'inside' and r['why']['text'].endswith(", in Jeff's errand hours"),
          f"the why says the hours shaped it: {r['why']}")
    # Groceries ride home: the drive home from Soccer leaves 17:20, outside the
    # hours, so strict excludes it and the trip from home moves to 13:00 (the
    # person's hours, not the 09:00 band).
    rows, notes = _place(base, [_errand(valid_days_of_week=[1], home_bound=True)], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and _t(r) == '13:00' and r['why'].get('hours') == 'inside',
          f"a trip from home inside the hours: {r['why']} {_t(r)}")
    check(r['why']['text'] == "a trip from home, 20 min each way, in Jeff's errand hours", f"{r['why']['text']}")
    # Control: with no habit the drive home wins as it did (detour 20 < 40 + 25).
    _habits({})
    rows, notes = _place(base, [_errand(valid_days_of_week=[1], home_bound=True)], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Pickup: Soccer', 'to': 'Home'} and _t(r) == '17:20'
          and 'hours' not in r['why'] and 'errand hours' not in r['why']['text'],
          f"no habit, no change and no words: {r['why']} {_t(r)}")


def scenario_a_day_with_no_hours_row_is_outside_and_the_note_names_the_person():
    jeff = _driver('d1', 'Jeff')
    lorena = _driver('d2', 'Lorena')
    base = _world({}, [], {})
    _habits({'d1': _hours(WEEKDAYS, '13:00', '15:00')})
    # Saturday only, Jeff the only driver: outside his errand hours, nothing lands.
    rows, notes = _place(base, [_errand(valid_days_of_week=[5])], [jeff])
    check(not rows and notes.get('er1', {}).get('reason') == 'errand_hours'
          and notes['er1']['text'] == "outside Jeff's errand hours", f"{rows} {notes}")
    # Lorena has no habits: she runs it, Saturday in the weekend band.
    rows, notes = _place(base, [_errand(valid_days_of_week=[5])], [jeff, lorena])
    d, r = _only(rows)
    check(r['driver']['id'] == 'd2' and d == DAYS[5] and _t(r) == '10:00' and 'hours' not in r['why'],
          f"Lorena takes it: {d} {_t(r)} {r['why']}")
    check(notes == {}, f"{notes}")


def scenario_preferred_hours_cost_a_leg_outside_and_a_personal_penalty_breaks_the_tie():
    jeff = _driver('d1', 'Jeff')
    base = _soccer_tuesday('d1')
    # Preferred, not strict: the drive home (detour 20) costs 20 more for being
    # outside the hours (40) and still beats the trip from home (40 + 25 = 65).
    _habits({'d1': _hours(WEEKDAYS, '13:00', '15:00', strict=False)})
    rows, notes = _place(base, [_errand(valid_days_of_week=[1], home_bound=True)], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Pickup: Soccer', 'to': 'Home'} and _t(r) == '17:20', f"{r['why']} {_t(r)}")
    check(r['why'].get('hours') == 'outside' and r['why']['text'] == "on Jeff's way home from Pickup: Soccer, +20 min, outside Jeff's errand hours",
          f"the why says it is outside: {r['why']}")
    # Jeff would rather make a separate trip than detour (personal penalty 0):
    # 40 ties the leg's 40 and the earlier start inside his hours wins.
    _habits({'d1': _hours(WEEKDAYS, '13:00', '15:00', strict=False, separate_trip_mins=0)})
    rows, notes = _place(base, [_errand(valid_days_of_week=[1], home_bound=True)], [jeff])
    d, r = _only(rows)
    check(r['why']['kind'] == 'from_home' and _t(r) == '13:00' and r['why'].get('hours') == 'inside',
          f"the personal penalty makes the trip from home win: {r['why']} {_t(r)}")


def scenario_preferred_hours_with_no_row_that_day_keep_the_band():
    jeff = _driver('d1', 'Jeff')
    _habits({'d1': _hours(WEEKDAYS, '13:00', '15:00', strict=False)})
    # Saturday only, no row for Saturday, preferred: the trip from home keeps
    # the weekend band (10:00, not 08:00) and the row says it is outside.
    rows, notes = _place(_world({}, [], {}), [_errand(valid_days_of_week=[5])], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and _t(r) == '10:00' and r['why'].get('hours') == 'outside'
          and r['why']['text'] == "a trip from home, 20 min each way, outside Jeff's errand hours", f"{d} {_t(r)} {r['why']}")


def scenario_the_same_place_on_another_leg_is_not_one_outing():
    # Lorena groups groceries. The Kroger run (Store) is Saturday only; Lily's
    # Saturday soccer gets her a drive home at 17:20 past the Store. The free
    # Costco run is ALSO at the Store. Beside the Kroger run it rides for
    # free; the drive home past the same Store is a second outing and earns
    # nothing, so the free one still lands beside its sibling.
    lorena = _driver('d2', 'Lorena')
    drop, pick = _ride('soccer', 5, 16, 0, 'Soccer', 'Soccer', 60, 'lily_cal')
    base = _world({5: [drop, pick]}, [], {'soccer_dropoff': 'd2', 'soccer_pickup': 'd2'})
    a = _errand(id='erA', doc_id=2, title='Kroger run', location='Store', valid_days_of_week=[5],
                time_window_start='09:00', time_window_end='12:00', home_bound=True)
    b = _errand(id='erB', doc_id=3, title='Costco run', location='Store', priority=1)
    _habits({'d2': {'together_kinds': ['groceries']}})
    rows, notes = _place(base, [a, b], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(da == DAYS[5] and _t(ra) == '09:00' and ra['why']['kind'] == 'from_home', f"the anchor in its window: {da} {_t(ra)} {ra['why']}")
    check(db == DAYS[5] and rb['why'].get('together') == 'Kroger run' and rb['why']['detour_mins'] == 0
          and 'erA' in (rb['inserted_after_event_id'], rb['inserted_before_event_id']),
          f"beside the sibling, same place, no detour: {rb['why']} {rb}")
    # Now bar B from the morning: its window opens at 17:00. The only
    # Saturday candidate is the drive home past the Store, which is not the
    # Kroger outing: no together words, plain detour.
    b2 = dict(b, time_window_start='17:00', time_window_end='20:00')
    rows, notes = _place(base, [a, b2], [lorena])
    db, rb = _only(rows, 'erB')
    check(db == DAYS[5] and _t(rb) == '17:20' and 'together' not in rb['why'] and 'with the' not in rb['why']['text'],
          f"the same place on another leg earns nothing: {_t(rb)} {rb['why']}")


def scenario_never_a_separate_trip():
    lorena = _driver('d2', 'Lorena')
    _habits({'d2': {'no_separate_trips': True}})
    # An empty week: no leg to ride, and never a trip from home for her.
    rows, notes = _place(_world({}, [], {}), [_errand()], [lorena])
    check(not rows and notes.get('er1', {}).get('reason') == 'no_slot', f"{rows} {notes}")
    # A drive on Tuesday: the errand rides it.
    rows, notes = _place(_soccer_tuesday('d2'), [_errand()], [lorena])
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['kind'] in ('on_the_way', 'inside_stop'), f"{d} {r['why']}")
    check(notes == {}, f"{notes}")


def scenario_a_personal_penalty_picks_the_person_who_minds_less():
    jeff = _driver('d1', 'Jeff')
    lorena = _driver('d2', 'Lorena')
    base = _world({}, [], {})
    # Nobody drives anywhere this week. With no habits the tie goes to the
    # lower driver id (Jeff); Lorena at penalty 0 costs 40 against his 65.
    _habits({})
    rows, _ = _place(base, [_errand()], [jeff, lorena])
    d, r = _only(rows)
    check(r['driver']['id'] == 'd1', f"the shipped tie: {r['driver']}")
    _habits({'d2': {'separate_trip_mins': 0}})
    rows, _ = _place(base, [_errand()], [jeff, lorena])
    d, r = _only(rows)
    check(r['driver']['id'] == 'd2' and r['why']['kind'] == 'from_home', f"Lorena minds a trip less: {r['driver']} {r['why']}")


def _two_groceries():
    # A: Kroger run at the Store (10,10), Saturdays only, priority 2.
    # B: Costco run at the Shop (-4,-4), no restriction, priority 1.
    a = _errand(id='erA', doc_id=2, title='Kroger run', location='Store', valid_days_of_week=[5])
    b = _errand(id='erB', doc_id=3, title='Costco run', location='Shop', priority=1)
    return a, b


def scenario_together_places_the_constrained_one_first_and_chains_the_free_one():
    lorena = _driver('d2', 'Lorena')
    base = _world({}, [], {})
    a, b = _two_groceries()
    # Without the habit: B (priority 1) goes first and lands Monday 09:00 from
    # home; A lands Saturday on its own. Two outings.
    _habits({})
    rows, notes = _place(base, [a, b], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(db == DAYS[0] and _t(rb) == '09:00' and da == DAYS[5], f"shipped order: B {db} {_t(rb)}, A {da}")
    # Lorena runs groceries together: A is placed first (Saturday only is the
    # tighter one), then B chains onto A's outing: on the way to the Kroger
    # run, leaving 09:02 so the Shop is done before the Store at 10:00.
    _habits({'d2': {'together_kinds': ['groceries']}})
    rows, notes = _place(base, [a, b], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(da == DAYS[5] and _t(ra) == '10:00' and ra['why']['kind'] == 'from_home' and 'together' not in ra['why'],
          f"the anchor is placed on its own merits: {da} {_t(ra)} {ra['why']}")
    check(db == DAYS[5] and rb['why'].get('together') == 'Kroger run', f"B rides with A: {db} {rb['why']}")
    check(rb['inserted_before_event_id'] == 'erA' and rb['why']['leg'] == {'from': 'Home', 'to': 'Kroger run'}
          and rb['why']['detour_mins'] == 16 and _t(rb) == '09:02',
          f"beside the sibling on the route: {rb}")
    check(rb['why']['text'] == "on Lorena's way to Kroger run, +16 min, with the Kroger run", f"{rb['why']['text']}")
    check(notes == {}, f"{notes}")


def scenario_together_is_one_outing_not_one_day_and_only_for_that_person():
    jeff = _driver('d1', 'Jeff')
    lorena = _driver('d2', 'Lorena')
    a, b = _two_groceries()
    # Jeff does not group; Lorena does but may not run these (Jeff required).
    # Both land, with no together bonus and no words about it.
    _habits({'d2': {'together_kinds': ['groceries']}})
    a2 = dict(a, required_drivers=['d1'])
    b2 = dict(b, required_drivers=['d1'])
    rows, notes = _place(_world({}, [], {}), [a2, b2], [jeff, lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(ra['driver']['id'] == 'd1' and rb['driver']['id'] == 'd1' and 'together' not in rb['why'] and 'with the' not in rb['why']['text'],
          f"someone else's habit never applies: {ra['why']} {rb['why']}")
    # The free one, placed after the anchor in the batched order, rides beside
    # it on Jeff's own merits (a 16-min leg beats a 41-min round trip), with no
    # bonus and no words about grouping.
    check(db == DAYS[5] and rb['why']['detour_mins'] == 16, f"{db} {rb['why']}")


def scenario_a_kind_nobody_batches_keeps_the_shipped_order():
    lorena = _driver('d2', 'Lorena')
    _habits({'d2': {'together_kinds': ['groceries']}})
    # Two returns: priority 1 free, priority 2 Saturdays only. Returns are not
    # batched, so the shipped order holds: the free one first, Monday.
    a = _errand(id='erA', doc_id=2, title='UPS drop off', location='Store', valid_days_of_week=[5])
    b = _errand(id='erB', doc_id=3, title='UPS return', location='Shop', priority=1)
    rows, notes = _place(_world({}, [], {}), [a, b], [lorena])
    da, ra = _only(rows, 'erA')
    db, rb = _only(rows, 'erB')
    check(db == DAYS[0] and da == DAYS[5] and 'together' not in rb['why'], f"B {db}, A {da}: {rb['why']}")


def scenario_the_primer_sees_the_sibling_location():
    lorena = _driver('d2', 'Lorena')
    a, b = _two_groceries()
    _habits({'d2': {'together_kinds': ['groceries']}})
    seen = []
    real = matcher._prime_errand_pairs

    def spy(loc, places, *args, **kw):
        seen.append((loc, set(places)))
        return 0
    matcher._prime_errand_pairs = spy
    try:
        _place(_world({}, [], {}), [a, b], [lorena])
    finally:
        matcher._prime_errand_pairs = real
    by_loc = {loc: places for loc, places in seen}
    check(set(by_loc) == {'Store', 'Shop'} and seen[0][0] == 'Store', f"the anchor primes first: {seen}")
    check('Store' in by_loc['Shop'], f"the second errand's primer includes the placed sibling's place: {by_loc['Shop']}")


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('scenario_'):
            print(name)
            fn()
    print("errand-habits scenarios passed")
