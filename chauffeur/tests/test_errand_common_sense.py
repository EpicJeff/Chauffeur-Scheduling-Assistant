"""Errands with common sense — kinds, defaults, estimates, what a steer teaches.

Spec: docs/superpowers/specs/2026-10-22-errands-common-sense-design.md
§1 (kind inference), §2 (defaults per kind), §3 (estimated legs),
§4 (the preference store, what a steer teaches, scoring).

Same grid as test_errand_routing.py: places are points, drive minutes are
Manhattan distance, a place off the grid has no cached minutes (None).
`matcher.errand_leg_estimate` is stubbed too so the estimate path is exact.

Run from chauffeur/:  python tests/test_errand_common_sense.py
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_cs_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from models.schemas import Driver, Event  # noqa: E402
from services import errand_prefs, maps, storage  # noqa: E402
from solver import matcher  # noqa: E402

maps.prime_matrix_cache = lambda locations, ignore_age=False: None

GRID = {'Home': (0, 0), 'Soccer': (20, 0), 'Store': (10, 10), 'Work': (0, 30),
        'Pharmacy': (0, 20), 'Dentist': (30, 0), 'Shop': (-4, -4),
        'Clinic': (0, 10), 'Piano': (-30, 0), 'Lab': (-4, -20)}
# Places with coordinates but NO cached pairs: the estimate path sees them.
ESTIMATE_ONLY = {'Plaza': (12, 0), 'Gym': (24, 0)}


def _leg(a, b):
    if not a or not b:
        return None
    if a == b:
        return 0
    if a not in GRID or b not in GRID:
        return None
    (x1, y1), (x2, y2) = GRID[a], GRID[b]
    return abs(x1 - x2) + abs(y1 - y2)


def _estimate(a, b):
    pts = dict(GRID, **ESTIMATE_ONLY)
    if not a or not b or a not in pts or b not in pts:
        return None
    if a == b:
        return 2
    (x1, y1), (x2, y2) = pts[a], pts[b]
    return abs(x1 - x2) + abs(y1 - y2) + 2


matcher.errand_leg_minutes = _leg
matcher.errand_leg_estimate = _estimate

MON = datetime.date(2026, 10, 26)
DAYS = [str(MON + datetime.timedelta(days=i)) for i in range(7)]   # Mon..Sun
NOW = datetime.datetime(2026, 10, 25, 20, 0).astimezone()           # Sunday evening
SETTINGS = {'errand_dedicated_trip_mins': 25}


def _fresh():
    with storage.db_lock:
        storage.app_state_table.truncate()


def _at(day_idx, h, m=0, dur=60):
    s = datetime.datetime.combine(MON + datetime.timedelta(days=day_idx), datetime.time(h, m)).astimezone()
    return s, s + datetime.timedelta(minutes=dur)


def _ev(eid, day_idx, h, loc, title=None, m=0, dur=60, **kw):
    s, e = _at(day_idx, h, m, dur)
    return Event(id=eid, title=title or loc, start=s, end=e, location=loc,
                 calendar_ids=['c'], source_event_ids=[eid], **kw)


def _driver(did, name):
    return Driver(id=did, name=name, home_location='Home', color_code='#000')


def _errand(**over):
    base = {'id': 'er1', 'doc_id': 1, 'title': 'Costco run', 'duration_mins': 30,
            'location': 'Store', 'priority': 2, 'is_completed': False, 'status': 'pending',
            'created_at': NOW.timestamp(), 'starts_on': None, 'recurrence_rule': None,
            'window_days': 7, 'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
            'pinned_end': None, 'once_driver_id': None, 'tags': [], 'kind': None,
            'home_bound': None}
    base.update(over)
    return base


def _world(events_by_day, drivers, assignments):
    out = {}
    for i, d in enumerate(DAYS):
        evs = events_by_day.get(i, [])
        out[d] = {'assignments': {e.id: assignments[e.id] for e in evs if e.id in assignments},
                  'events': evs}
    return out


def _place(base, errands, drivers, driver_events=None, settings=SETTINGS, now=NOW):
    by_date, notes = matcher.insert_errands_globally(
        base, errands, drivers, trip_metadata=[], driver_events=driver_events or {},
        now=now, settings=settings)
    rows = [(d, r) for d, rs in by_date.items() for r in rs]
    return rows, notes


def _only(rows, errand_id='er1'):
    mine = [(d, r) for d, r in rows if r['id'] == errand_id]
    check(len(mine) == 1, f"placed exactly once, got {mine}")
    return mine[0]


def _start(row):
    return datetime.datetime.fromisoformat(row['start_time']).astimezone().time()


# ---------------------------------------------------------------- §1 kinds

def scenario_the_kind_table_reads_tags_then_title_then_the_override():
    k = errand_prefs.errand_kind
    check(k(_errand(title='Costco run'), lists=[]) == 'groceries', "Costco is groceries")
    check(k(_errand(title='Weekly shop at Kroger'), lists=[]) == 'groceries', "Kroger is groceries")
    check(k(_errand(title='Pick up groceries'), lists=[]) == 'groceries', "pick up groceries is groceries, not a pickup")
    check(k(_errand(title='Walgreens'), lists=[]) == 'pharmacy', "Walgreens is a pharmacy")
    check(k(_errand(title='Return library books'), lists=[]) == 'return', "a return")
    check(k(_errand(title='Drop off the dry cleaning'), lists=[]) == 'return', "drop off is a return")
    check(k(_errand(title='Pick up the dry cleaning'), lists=[]) == 'pickup', "a pickup")
    check(k(_errand(title='Haircut'), lists=[]) == 'service', "a service")
    check(k(_errand(title='Oil change'), lists=[]) == 'service', "a service")
    check(k(_errand(title='Mystery'), lists=[]) == 'other', "nothing matched: other")
    check(k(_errand(title='Mystery', tags=['groceries']), lists=[]) == 'groceries', "a tag decides")
    check(k(_errand(title='Costco run', kind='service'), lists=[]) == 'service', "the override wins over the title")
    check(k(_errand(title='Mystery'), lists=[{'id': 'l1', 'name': 'Groceries'}]) == 'groceries',
          "a bound shopping list means groceries")
    check(k(_errand(title='Costco', tags=['pharmacy']), lists=[]) == 'pharmacy',
          "tags are read before the title")
    check(k(_errand(title='Grocer'), lists=[]) == 'other', "word boundaries: 'grocer' is not 'grocery'")


def scenario_the_kind_table_is_walked_in_order():
    check(errand_prefs.errand_kind(_errand(title='Pick up the prescription'), lists=[]) == 'pharmacy',
          "pharmacy is checked before pickup")
    check(errand_prefs.errand_kind(_errand(title='Return the Costco order'), lists=[]) == 'groceries',
          "groceries is checked before return")


def scenario_home_bound_follows_the_kind_unless_overridden():
    hb = errand_prefs.is_home_bound
    check(hb(_errand(title='Costco run'), 'groceries') is True, "groceries ride home")
    check(hb(_errand(title='CVS'), 'pharmacy') is True, "pharmacy rides home")
    check(hb(_errand(title='Haircut'), 'service') is False, "a service rides any leg")
    check(hb(_errand(title='Costco run', home_bound=False), 'groceries') is False, "False overrides")
    check(hb(_errand(title='Haircut', home_bound=True), 'service') is True, "True overrides")


def scenario_the_errand_model_validates_kind_and_home_bound():
    from models.schemas import Errand, ErrandRule, ERRAND_ROUTING_FIELDS, ERRAND_KINDS
    e = Errand(**_errand(kind='Groceries', home_bound=True))
    check(e.kind == 'groceries' and e.home_bound is True, "kind lower-cased, home_bound kept")
    check(Errand(**_errand(kind='')).kind is None, "empty kind is None")
    rejected = False
    try:
        Errand(**_errand(kind='snacks'))
    except Exception:
        rejected = True
    check(rejected, "an unknown kind is rejected")
    rejected = False
    try:
        ErrandRule(title='Snack runs', keywords=['snack'], kind='snacks')
    except Exception:
        rejected = True
    check(rejected, "a rule's unknown kind is rejected too")
    check('kind' in ERRAND_ROUTING_FIELDS and 'home_bound' in ERRAND_ROUTING_FIELDS,
          "both forget placements when changed")
    check(ERRAND_KINDS == ('groceries', 'pharmacy', 'return', 'pickup', 'service', 'other'), f"{ERRAND_KINDS}")
    r = ErrandRule(title='Grocery runs', keywords=['grocer'], kind='groceries', home_bound=True)
    check(r.kind == 'groceries' and r.home_bound is True, "a rule carries both")


# ---------------------------------------------------------------- §4.2 bands

def scenario_bands_match_exactly_or_by_midpoint():
    b = errand_prefs.band_for
    check(b('17:00', '20:00') == 'evening', "an exact band")
    check(b('08:00', '12:00') == 'morning', "an exact band")
    check(b('15:00', '16:00') == 'afternoon', "a window inside a band takes that band")
    check(b('19:30', None) == 'evening', "start alone is the midpoint")
    check(b(None, '09:00') == 'morning', "end alone is the midpoint")
    check(b(None, None) is None, "no pin, no band")
    check(b('06:00', '07:00') == 'morning', "before every band: morning")
    check(b('21:00', '22:00') == 'evening', "after every band: evening")


def scenario_a_pin_that_fits_no_band_exactly_takes_its_midpoint():
    check(errand_prefs.band_for('10:00', '13:00') == 'morning',
          "midpoint 11:30 is in morning (08-12) and midday (11-14); the first band in order wins")


# ---------------------------------------------------------------- §4 store

def scenario_upsert_grows_weight_and_delete_and_clear_work():
    _fresh()
    row = {'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
           'polarity': 'avoid', 'source': 'steer'}
    a = storage.upsert_errand_preference(dict(row), now=1_000_000.0)
    check(a['id'] and a['weight'] == 1.0 and a['last_seen'] == 1_000_000.0, f"first write: {a}")
    b = storage.upsert_errand_preference(dict(row), now=1_000_100.0)
    check(b['id'] == a['id'] and b['weight'] == 2.0 and b['last_seen'] == 1_000_100.0, f"same row grows: {b}")
    for _ in range(10):
        b = storage.upsert_errand_preference(dict(row), now=1_000_200.0)
    check(b['weight'] == errand_prefs.PREF_MAX_WEIGHT, f"weight caps at {errand_prefs.PREF_MAX_WEIGHT}: {b}")
    other = storage.upsert_errand_preference(dict(row, polarity='prefer'), now=1_000_000.0)
    check(other['id'] != a['id'] and len(storage.get_errand_preferences()) == 2, "polarity is part of the key")
    check(storage.delete_errand_preference(other['id']) is True and len(storage.get_errand_preferences()) == 1, "delete one")
    check(storage.delete_errand_preference('nope') is False, "deleting a missing id is False")
    check(storage.clear_errand_preferences() == 1 and storage.get_errand_preferences() == [], "clear all")


def scenario_weight_decays_with_a_90_day_half_life_and_stale_rows_prune():
    _fresh()
    now = 2_000_000_000.0
    row = {'id': 'p1', 'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
           'polarity': 'avoid', 'weight': 2.0, 'last_seen': now - 90 * 86400, 'source': 'steer'}
    check(abs(errand_prefs.effective_weight(row, now) - 1.0) < 1e-6, "half after 90 days")
    check(abs(errand_prefs.effective_weight(dict(row, last_seen=now), now) - 2.0) < 1e-6, "full when fresh")
    stale = dict(row, id='p2', weight=1.0, last_seen=now - 200 * 86400)   # 0.21 effective
    storage.set_app_state('errand_preferences', [row, stale])
    storage.upsert_errand_preference({'scope': '*', 'kind': 'other', 'dimension': 'driver', 'value': 'd2',
                                      'polarity': 'prefer', 'source': 'steer'}, now=now)
    ids = {r['id'] for r in storage.get_errand_preferences()}
    check('p1' in ids and 'p2' not in ids, f"a write prunes rows under {errand_prefs.PREF_PRUNE_BELOW}: {ids}")


def scenario_preference_cost_is_soft_scoped_and_clamped():
    now = NOW.timestamp()
    sat = MON + datetime.timedelta(days=5)
    start = datetime.datetime.combine(sat, datetime.time(10, 0)).astimezone()
    rows = [
        {'id': 'a', 'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
         'polarity': 'avoid', 'weight': 2.0, 'last_seen': now, 'source': 'steer'},
        {'id': 'b', 'scope': '*', 'kind': '*', 'dimension': 'time_band', 'value': 'morning',
         'polarity': 'prefer', 'weight': 1.0, 'last_seen': now, 'source': 'steer'},
        {'id': 'c', 'scope': '*', 'kind': 'groceries', 'dimension': 'driver', 'value': 'd2',
         'polarity': 'prefer', 'weight': 1.0, 'last_seen': now, 'source': 'steer'},
        {'id': 'd', 'scope': 'd2', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
         'polarity': 'avoid', 'weight': 6.0, 'last_seen': now, 'source': 'steer'},
    ]
    cost, hit = errand_prefs.preference_cost(rows, 'd1', 'groceries', sat, start, now)
    check(cost == 10 - 5 and sorted(hit) == ['a', 'b'], f"avoid 2×5 minus prefer 1×5, scoped to d1: {cost} {hit}")
    cost, hit = errand_prefs.preference_cost(rows, 'd2', 'groceries', sat, start, now)
    check(cost == 20 and sorted(hit) == ['b', 'c', 'd'], f"d2: avoid 6×5=30 minus prefer 5+5: {cost} {hit}")
    cost, hit = errand_prefs.preference_cost(rows, 'd1', 'service', sat, start, now)
    check(cost == -5 and hit == ['b'], f"only the any-kind band row matches a service: {cost} {hit}")
    mon_start = datetime.datetime.combine(MON, datetime.time(15, 0)).astimezone()
    cost, hit = errand_prefs.preference_cost(rows, 'd1', 'groceries', MON, mon_start, now)
    check(cost == 0 and hit == [], "Monday afternoon matches nothing")
    heavy = [dict(rows[0], id=f'h{i}', value='5') for i in range(8)]
    cost, _ = errand_prefs.preference_cost(heavy, 'd1', 'groceries', sat, start, now)
    check(cost == errand_prefs.PREF_CAP_MINS, f"clamped at {errand_prefs.PREF_CAP_MINS}: {cost}")


def scenario_describe_speaks_plainly():
    people = {'d1': 'Jeff', 'd2': 'Lorena'}
    d = errand_prefs.describe
    check(d({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5', 'polarity': 'avoid',
             'weight': 2.0}, people) == 'Jeff: groceries not on Saturdays (learned from 2 steers)', "avoid weekday")
    check(d({'scope': '*', 'kind': 'pharmacy', 'dimension': 'time_band', 'value': 'evening', 'polarity': 'prefer',
             'weight': 1.0}, people) == 'Anyone: pharmacy runs in the evening (learned from 1 steer)', "band")
    check(d({'scope': '*', 'kind': 'return', 'dimension': 'driver', 'value': 'd2', 'polarity': 'prefer',
             'weight': 3.0}, people) == 'Lorena runs returns (learned from 3 steers)', "driver")
    check(d({'scope': 'd1', 'kind': 'other', 'dimension': 'weekday', 'value': '0', 'polarity': 'prefer',
             'weight': 1.0}, people) == 'Jeff: errands on Mondays (learned from 1 steer)', "other = errands")
    check(d({'scope': 'dX', 'kind': 'service', 'dimension': 'time_band', 'value': 'midday', 'polarity': 'avoid',
             'weight': 1.4}, people) == 'Someone: appointments not at midday (learned from 1 steer)',
          "an unknown driver reads as Someone; weight rounds")


# ---------------------------------------------------------------- §2 defaults

def scenario_groceries_ride_home_not_to_the_appointment():
    # Jeff: Dentist (30,0) 10:00-11:00, Work (0,30) 14:00-17:00, both own events.
    # Store (10,10): on the way TO the dentist detour 20 (Home->Store 20,
    # Store->Dentist 30, Home->Dentist 30); BETWEEN dentist and work detour 0
    # (Dentist->Store 30, Store->Work 30, Dentist->Work 60); on the way HOME
    # from work detour 20 (Work->Store 30, Store->Home 20, Work->Home 30).
    # Pure cost takes the free gap at 11:00, two hours before anyone is home.
    # Groceries must take the leg home.
    jeff = _driver('d1', 'Jeff')
    dentist = _ev('dentist', 1, 10, 'Dentist', 'Dentist')
    work = _ev('work', 1, 14, 'Work', 'Work', dur=180)
    base = _world({}, [jeff], {})
    rows, notes = _place(base, [_errand(title='Costco run')], [jeff], driver_events={'d1': [dentist, work]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['leg'] == {'from': 'Work', 'to': 'Home'},
          f"groceries ride the leg home: {d} {r['why']}")
    check(r['why']['text'] == "on Jeff's way home from Work, +20 min", f"{r['why']['text']!r}")
    check(r['kind'] == 'groceries', f"the row says its kind: {r.get('kind')}")
    # The same geometry with home_bound=False takes the morning leg.
    rows, _ = _place(base, [_errand(title='Costco run', home_bound=False)], [jeff], driver_events={'d1': [dentist, work]})
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Dentist', 'to': 'Work'} and r['why']['detour_mins'] == 0,
          f"home_bound=False rides any leg, here the free gap: {r['why']}")
    # A return with the same geometry takes the free gap too.
    rows, _ = _place(base, [_errand(title='Return the lamp')], [jeff], driver_events={'d1': [dentist, work]})
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Dentist', 'to': 'Work'} and r['kind'] == 'return',
          f"a return rides any leg: {r['why']} {r.get('kind')}")


def scenario_groceries_never_sit_inside_a_drop_off_and_run_ride():
    # Saturday: Jeff drops Kate at Soccer 10:00-12:00 (drop-off-and-run). The
    # Store is 40 off the drop->pickup gap (Soccer->Store 20, Store->Soccer 20,
    # gap 0), 20 off the way to soccer and 20 off the way home after pickup.
    # Groceries: after the pickup, never before it.
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 5, 10, 'Soccer', 'Soccer practice', dur=120)
    base = _world({5: [soccer]}, [jeff], {'soccer': 'd1'})
    rows, _ = _place(base, [_errand(title='Costco run')], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and r['why']['leg'] == {'from': 'Soccer practice', 'to': 'Home'}, f"after pickup: {r['why']}")
    check(datetime.datetime.fromisoformat(r['start_time']) >= soccer.end, "never before the pickup")
    rows, _ = _place(base, [_errand(title='Return the lamp')], [jeff])
    d, r = _only(rows)
    check(r['why']['leg'] == {'from': 'Home', 'to': 'Soccer practice'}, f"a return rides the first leg: {r['why']}")


def scenario_a_dedicated_trip_keeps_human_hours():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    # Window = Saturday only (one-off starting Saturday, one day).
    sat_ts = datetime.datetime.combine(MON + datetime.timedelta(days=5), datetime.time(0, 0)).astimezone().timestamp()
    rows, _ = _place(base, [_errand(title='Costco run', starts_on=sat_ts, window_days=1)], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and _start(r) == datetime.time(10, 0), f"Saturday from home starts at 10:00, got {_start(r)}")
    tue_ts = datetime.datetime.combine(MON + datetime.timedelta(days=1), datetime.time(0, 0)).astimezone().timestamp()
    rows, _ = _place(base, [_errand(title='Costco run', starts_on=tue_ts, window_days=1)], [jeff])
    d, r = _only(rows)
    check(d == DAYS[1] and _start(r) == datetime.time(9, 0), f"a weekday from home starts at 09:00, got {_start(r)}")
    rows, _ = _place(base, [_errand(title='Costco run', starts_on=sat_ts, window_days=1,
                                    time_window_start='08:00', time_window_end='09:00')], [jeff])
    d, r = _only(rows)
    check(_start(r) == datetime.time(8, 0), f"the person's own window wins over the band: {_start(r)}")
    rows, _ = _place(base, [_errand(title='Costco run', pinned_date=DAYS[5], pinned_start='17:00', pinned_end='20:00')], [jeff])
    d, r = _only(rows)
    check(d == DAYS[5] and _start(r) == datetime.time(17, 0), f"an Evening pin places at 17:00: {d} {_start(r)}")
    # A 9-hour trip has no 09:00-17:00 fit: the ladder keeps the 09:00 start and
    # lets it run to the day's end rather than reporting no_slot or going to 08:00.
    rows, notes = _place(base, [_errand(title='Costco run', starts_on=tue_ts, window_days=1, duration_mins=540)], [jeff])
    d, r = _only(rows)
    check(_start(r) == datetime.time(9, 0) and notes == {}, f"a trip longer than the band still lands: {_start(r)} {notes}")


def scenario_a_day_someone_already_leaves_beats_a_blank_day_for_groceries():
    # Monday blank (round trip from home: Store 20 each way = 40 + 25 penalty = 65).
    # Tuesday Jeff works (Work 0,30; Work->Store 30, Store->Home 20, Work->Home 30: detour 20).
    jeff = _driver('d1', 'Jeff')
    work = _ev('work', 1, 9, 'Work', 'Work', dur=480)
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(title='Costco run')], [jeff], driver_events={'d1': [work]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['leg'] == {'from': 'Work', 'to': 'Home'}, f"Tuesday on the way home: {d} {r['why']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} common-sense scenarios passed")
