"""Errands ride the route — the solver pass, run on a grid.

Spec: docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md
§1 (legs, candidate timing), §2 (score, ties, finalization), §3 (why).

Places are points on a grid; drive minutes are Manhattan distance. A place
not on the grid has NO drive time (None), which is what an unresolved
address looks like to the pass.

Run from chauffeur/:  python tests/test_errand_routing.py
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_route_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from models.schemas import Driver, Event  # noqa: E402
from solver import matcher  # noqa: E402

GRID = {'Home': (0, 0), 'Soccer': (20, 0), 'Store': (10, 10), 'Work': (0, 30),
        'Pharmacy': (0, 20), 'Piano': (-30, 0), 'Far': (80, 80), 'Shop': (-4, -4)}


def _leg(a, b):
    if not a or not b:
        return None
    if a == b:
        return 0
    if a not in GRID or b not in GRID:
        return None
    (x1, y1), (x2, y2) = GRID[a], GRID[b]
    return abs(x1 - x2) + abs(y1 - y2)


matcher.errand_leg_minutes = _leg

MON = datetime.date(2026, 10, 26)
DAYS = [str(MON + datetime.timedelta(days=i)) for i in range(7)]   # Mon..Sun
NOW = datetime.datetime(2026, 10, 25, 20, 0).astimezone()           # Sunday evening
SETTINGS = {'errand_dedicated_trip_mins': 25}


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
            'pinned_end': None, 'once_driver_id': None}
    base.update(over)
    return base


def _world(events_by_day, drivers, assignments):
    """base_schedules for DAYS: events on each day, assignments {eid: did}."""
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


def scenario_near_a_route_beats_earlier_from_home_and_did_not_before():
    # Tuesday: Jeff drives Kate to Soccer (Home 0,0 -> Soccer 20,0). The Shop
    # sits behind home at (-4,-4): the leg detour (8 + 28 - 20 = 16) equals the
    # round trip from home (16), the exact tie the old code broke by taking
    # the first slot scanned: Monday, empty, from home. New rule: the round
    # trip costs 16 + 25 = 41 and Tuesday's leg costs 16.
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 1, 16, 'Soccer', 'Soccer practice')
    base = _world({1: [soccer]}, [jeff], {'soccer': 'd1'})
    rows, _ = _place(base, [_errand(location='Shop')], [jeff], settings={'errand_dedicated_trip_mins': 0})
    d, r = _only(rows)
    check(d == DAYS[0] and r['why']['kind'] == 'from_home'
          and r['why']['text'] == 'a trip from home, 8 min each way',
          f"with no penalty the old answer stands (Monday from home): {d} {r['why']}")
    rows, notes = _place(base, [_errand(location='Shop')], [jeff])
    d, r = _only(rows)
    check(d == DAYS[1], f"lands Tuesday, got {d}")
    check(r['driver']['id'] == 'd1' and r['why']['kind'] == 'on_the_way'
          and r['why']['detour_mins'] == 16 and r['why']['leg'] == {'from': 'Home', 'to': 'Soccer practice'},
          f"on Jeff's leg to soccer: {r['why']}")
    check(r['why']['text'] == "on Jeff's way to Soccer practice, +16 min", f"text: {r['why']['text']!r}")
    check(r['inserted_before_event_id'] == 'soccer' and r['inserted_after_event_id'] is None
          and r['travel_to_mins'] == 8 and r['travel_from_mins'] == 28, f"neighbours and legs: {r}")
    end = datetime.datetime.fromisoformat(r['end_time'])
    check(end + datetime.timedelta(minutes=28) <= soccer.start, "arrives at soccer on time")
    check(notes == {}, f"nothing unplaced: {notes}")


def scenario_a_drivers_own_event_is_a_leg_not_a_window():
    # Lorena's work day Wednesday (Home 0,0 -> Work 0,30). The Pharmacy (0,20)
    # is ON that line: detour 0. It must land before work, never inside it.
    lorena = _driver('d2', 'Lorena')
    work = _ev('work', 2, 9, 'Work', 'Work', dur=8 * 60)
    base = _world({}, [lorena], {})
    rows, _ = _place(base, [_errand(location='Pharmacy')], [lorena], driver_events={'d2': [work]})
    d, r = _only(rows)
    check(d == DAYS[2] and r['why']['kind'] == 'on_the_way' and r['why']['detour_mins'] == 0
          and r['why']['leg']['to'] == 'Work', f"on her way to work: {d} {r['why']}")
    end = datetime.datetime.fromisoformat(r['end_time'])
    check(end + datetime.timedelta(minutes=10) <= work.start, "done before work starts")


def scenario_from_home_when_nothing_passes_near():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})                 # nobody drives anywhere this week
    rows, _ = _place(base, [_errand()], [jeff])
    d, r = _only(rows)
    check(d == DAYS[0] and r['why']['kind'] == 'from_home', f"earliest day, from home: {d} {r['why']}")
    check(r['why']['text'] == 'a trip from home, 20 min each way', f"text: {r['why']['text']!r}")
    check(datetime.datetime.fromisoformat(r['start_time']).time() == datetime.time(8, 0),
          "an empty day starts at the day's start")


def scenario_weekday_filter_applies_to_candidate_days():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(valid_days_of_week=[1])], [jeff])   # Tuesday only
    d, r = _only(rows)
    check(d == DAYS[1], f"a Tuesday-only errand lands Tuesday, not {d}")


def scenario_finalization_uses_the_winners_own_day_and_driver():
    # Winner is Monday with d1 (Soccer Monday). d2 has a Friday ride that is
    # scanned later; the old code read Friday's schedule and d2's home when it
    # wrote the row.
    jeff, lorena = _driver('d1', 'Jeff'), _driver('d2', 'Lorena')
    soccer = _ev('soccer', 0, 16, 'Soccer')
    piano = _ev('piano', 4, 16, 'Piano')
    base = _world({0: [soccer], 4: [piano]}, [jeff, lorena], {'soccer': 'd1', 'piano': 'd2'})
    rows, _ = _place(base, [_errand()], [jeff, lorena])
    d, r = _only(rows)
    check(d == DAYS[0] and r['driver']['id'] == 'd1' and r['inserted_before_event_id'] == 'soccer',
          f"Monday, Jeff, before soccer: {d} {r}")


def scenario_order_never_decides():
    jeff, lorena = _driver('d1', 'Jeff'), _driver('d2', 'Lorena')
    soccer = _ev('soccer', 1, 16, 'Soccer')
    piano = _ev('piano', 3, 16, 'Piano')
    base = _world({1: [soccer], 3: [piano]}, [jeff, lorena], {'soccer': 'd1', 'piano': 'd2'})
    a = _only(_place(base, [_errand()], [jeff, lorena])[0])
    reversed_base = dict(reversed(list(base.items())))
    b = _only(_place(reversed_base, [_errand()], [lorena, jeff])[0])
    check(a[0] == b[0] and a[1]['driver']['id'] == b[1]['driver']['id']
          and a[1]['start_time'] == b[1]['start_time'], f"same answer either way: {a} vs {b}")
    # Two identical drivers on identical legs: the lower id wins, deterministically.
    twin = _driver('d0', 'Twin')
    s2 = _ev('soccer2', 1, 16, 'Soccer')
    base2 = _world({1: [soccer, s2]}, [jeff, twin], {'soccer': 'd1', 'soccer2': 'd0'})
    c = _only(_place(base2, [_errand()], [jeff, twin])[0])
    e = _only(_place(base2, [_errand()], [twin, jeff])[0])
    check(c[1]['driver']['id'] == 'd0' == e[1]['driver']['id'], "ties go to the lower driver id")


def scenario_candidate_timing_fits_windows():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    rows, _ = _place(base, [_errand(time_window_start='10:00', time_window_end='11:00')], [jeff])
    d, r = _only(rows)
    check(datetime.datetime.fromisoformat(r['start_time']).time() == datetime.time(10, 0)
          and datetime.datetime.fromisoformat(r['end_time']).time() == datetime.time(10, 30),
          f"an empty day honours a 10-11 window: {r['start_time']}")
    morning = _ev('m', 0, 9, 'Soccer', dur=60)
    base = _world({0: [morning]}, [jeff], {'m': 'd1'})
    rows, _ = _place(base, [_errand(time_window_start='14:00', time_window_end='17:00')], [jeff])
    d, r = _only(rows)
    st = datetime.datetime.fromisoformat(r['start_time'])
    check(d == DAYS[0] and st.time() >= datetime.time(14, 0) and r['why']['kind'] == 'on_the_way',
          f"an afternoon window lands after the morning ride, on the way home: {st} {r['why']}")
    rows, notes = _place(base, [_errand(time_window_start='22:00', time_window_end='23:00')], [jeff])
    check(not rows and notes.get('er1', {}).get('reason') == 'no_slot',
          f"a window outside the day is a no_slot note: {rows} {notes}")


def scenario_a_long_errand_that_fits_nowhere_is_a_no_slot_note():
    # Jeff's OWN days are packed (work 8-14, a course 15-21, every day): own
    # events are stops, never drop-off windows (R1), so a 3-hour errand has no
    # gap anywhere and must say so rather than overlap something.
    jeff = _driver('d1', 'Jeff')
    own = [e for i in range(7) for e in (_ev(f'a{i}', i, 8, 'Work', dur=6 * 60), _ev(f'b{i}', i, 15, 'Piano', dur=6 * 60))]
    base = _world({}, [jeff], {})
    rows, notes = _place(base, [_errand(duration_mins=180)], [jeff], driver_events={'d1': own})
    check(not rows and notes['er1']['reason'] == 'no_slot', f"{rows} {notes}")


def scenario_a_ride_the_driver_also_attends_is_one_stop():
    jeff = _driver('d1', 'Jeff')
    dentist = _ev('dentist', 1, 10, 'Soccer', 'Dentist', dur=60)
    base = _world({1: [dentist]}, [jeff], {'dentist': 'd1'})
    rows, _ = _place(base, [_errand()], [jeff], driver_events={'d1': [dentist]})
    d, r = _only(rows)
    check(d == DAYS[1] and r['why']['kind'] in ('on_the_way', 'inside_stop'),
          f"one stop, placed once around it: {r['why']}")
    seen = sum(1 for dd, rr in rows if rr['id'] == 'er1')
    check(seen == 1, "never two stops for one event")


def scenario_now_clamps_or_drops_todays_slot():
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 0, 16, 'Soccer')
    base = _world({0: [soccer]}, [jeff], {'soccer': 'd1'})
    late_now = datetime.datetime.combine(MON, datetime.time(15, 50)).astimezone()
    rows, _ = _place(base, [_errand()], [jeff], now=late_now)
    d, r = _only(rows)
    check(datetime.datetime.fromisoformat(r['start_time']) >= late_now, "never placed in the past")
    check(r['why']['kind'] != 'on_the_way' or r['inserted_before_event_id'] != 'soccer',
          f"the leg to soccer is already too late (needs 20+30+20 min before 16:00): {r}")


def scenario_text_for_every_kind():
    t = matcher.errand_why_text
    cases = [
        ({'kind': 'on_the_way', 'driver_name': 'Jeff', 'detour_mins': 6, 'leg': {'from': 'Home', 'to': 'Soccer'}},
         "on Jeff's way to Soccer, +6 min"),
        ({'kind': 'on_the_way', 'driver_name': 'Jeff', 'detour_mins': 6, 'leg': {'from': 'Soccer', 'to': 'Home'}},
         "on Jeff's way home from Soccer, +6 min"),
        ({'kind': 'inside_stop', 'driver_name': 'Kate', 'detour_mins': 9, 'leg': {'from': 'Piano', 'to': 'Piano'}},
         "during Piano, +9 min"),
        ({'kind': 'from_home', 'driver_name': 'Jeff', 'detour_mins': 24}, 'a trip from home, 12 min each way'),
        ({'kind': 'pinned', 'driver_name': 'Jeff', 'detour_mins': 4, 'leg': {'from': 'Home', 'to': 'Work'}},
         "the day you picked, on Jeff's way to Work, +4 min"),
        ({'kind': 'unknown_travel', 'driver_name': 'Jeff'}, 'drive time unknown, check the address'),
    ]
    for why, want in cases:
        check(t(why) == want, f"{why['kind']}: {t(why)!r} != {want!r}")

def _no_overlap(rows, stops):
    """No placed errand overlaps a stop or another errand (both inclusive of travel-free bounds)."""
    spans = [(datetime.datetime.fromisoformat(r['start_time']), datetime.datetime.fromisoformat(r['end_time']), r['id']) for _, r in rows]
    for s1, e1, i1 in spans:
        for s2, e2, i2 in spans:
            if i1 < i2:
                check(e1 <= s2 or e2 <= s1, f"errands {i1} and {i2} overlap: {s1}-{e1} vs {s2}-{e2}")
        for st in stops:
            check(e1 <= st.start or st.end <= s1, f"errand {i1} {s1}-{e1} runs across {st.title} {st.start}-{st.end}")


def scenario_the_from_home_leg_sits_just_before_leaving():
    # Rev 2.1: the before-first shape takes the LATEST start, so the errand is
    # part of the drive to the stop rather than a dawn trip eight hours early.
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 1, 16, 'Soccer', 'Soccer practice')
    base = _world({1: [soccer]}, [jeff], {'soccer': 'd1'})
    d, r = _only(_place(base, [_errand(location='Shop')], [jeff])[0])
    st = datetime.datetime.fromisoformat(r['start_time'])
    check(st == soccer.start - datetime.timedelta(minutes=28 + 30), f"starts at 15:02, the latest fit: {st}")


def scenario_both_halves_of_a_split_ride_stay_on_the_route():
    # main.py unrolls a ride into X_dropoff and X_pickup sharing original_event_id.
    # Deduping rides on that key dropped the pickup, and an errand ran across it.
    jeff = _driver('d1', 'Jeff')
    drop = _ev('sch_dropoff', 1, 9, 'Soccer', 'Dropoff: School', dur=15, original_event_id='sch')
    pick = _ev('sch_pickup', 1, 15, 'Soccer', 'Pickup: School', dur=15, original_event_id='sch')
    base = _world({1: [drop, pick]}, [jeff], {'sch_dropoff': 'd1', 'sch_pickup': 'd1'})
    rows, notes = _place(base, [_errand(duration_mins=300)], [jeff])
    _no_overlap(rows, [drop, pick])
    # A midday window forces the gap between the halves (after the pickup is
    # the cheaper detour otherwise, and that is fine too).
    rows, _ = _place(base, [_errand(duration_mins=60, time_window_start='10:00', time_window_end='14:00')], [jeff])
    d, r = _only(rows)
    _no_overlap(rows, [drop, pick])
    check(r['inserted_after_event_id'] == 'sch_dropoff' and r['inserted_before_event_id'] == 'sch_pickup',
          f"between the two halves: {r}")


def scenario_an_own_stop_inside_a_ride_clips_the_gap():
    # School ride 08:00-15:00 (drop-off-and-run) with Jeff's own Work 09:00-12:00
    # inside it: a 90-minute errand must not overlap Work and must be back for
    # the 15:00 pickup.
    jeff = _driver('d1', 'Jeff')
    school = _ev('school', 1, 8, 'Soccer', 'School', dur=7 * 60)
    work = _ev('work', 1, 9, 'Work', 'Work', dur=3 * 60)
    base = _world({1: [school]}, [jeff], {'school': 'd1'})
    rows, notes = _place(base, [_errand(duration_mins=90)], [jeff], driver_events={'d1': [work]})
    d, r = _only(rows)
    st, en = datetime.datetime.fromisoformat(r['start_time']), datetime.datetime.fromisoformat(r['end_time'])
    check(en <= work.start or st >= work.end, f"never across Work: {st}-{en}")
    check(en + datetime.timedelta(minutes=20) <= school.end or st >= school.end + datetime.timedelta(minutes=20),
          f"back for the pickup or after it: {st}-{en}")


class _Pick:
    """The pickup anchor of a drop-off-and-run ride, as a stop-shaped object."""
    def __init__(self, ev):
        self.start = ev.end
        self.end = ev.end
        self.title = 'Pickup: ' + ev.title


def scenario_a_second_errand_sees_the_first_and_neither_crosses_a_pickup():
    jeff = _driver('d1', 'Jeff')
    soccer = _ev('soccer', 1, 8, 'Soccer', dur=4 * 60)           # drop 08:00, pickup 12:00
    base = _world({1: [soccer]}, [jeff], {'soccer': 'd1'})
    e1 = _errand(id='er1', doc_id=1, duration_mins=60, window_days=2)
    e2 = _errand(id='er2', doc_id=2, duration_mins=60, window_days=2)
    rows, _ = _place(base, [e1, e2], [jeff])
    check(len(rows) == 2, f"both placed: {rows}")
    _no_overlap(rows, [_Pick(soccer)])
    for _, r in rows:
        st, en = datetime.datetime.fromisoformat(r['start_time']), datetime.datetime.fromisoformat(r['end_time'])
        check(not (st < soccer.start < en) and not (st < soccer.end < en),
              f"an errand runs across the drop or the pickup: {st}-{en}")


def scenario_allowed_drivers_apply_only_without_required_drivers():
    jeff, lorena = _driver('d1', 'Jeff'), _driver('d2', 'Lorena')
    base = _world({}, [jeff, lorena], {})
    d, r = _only(_place(base, [_errand(required_drivers=['d1'], allowed_drivers=['d2'])], [jeff, lorena])[0])
    check(r['driver']['id'] == 'd1', f"required wins and allowed is ignored, as today: {r['driver']['id']}")


def scenario_a_window_beyond_the_range_is_waiting_not_a_note():
    jeff = _driver('d1', 'Jeff')
    base = _world({}, [jeff], {})
    far = (NOW + datetime.timedelta(days=30)).timestamp()
    rows, notes = _place(base, [_errand(starts_on=far, window_days=3)], [jeff])
    check(not rows and notes == {}, f"nothing placed and nothing reported: {rows} {notes}")
    rows, notes = _place(base, [_errand(valid_days_of_week=[6], window_days=5)], [jeff])   # Sunday only, window Sun..Thu
    check(not rows and notes == {}, f"a weekday never in the window is waiting too: {rows} {notes}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand routing scenarios passed")
