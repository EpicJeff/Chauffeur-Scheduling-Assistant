"""The adult drive screen's words: `pwaDriveView(sheet, ctx)` checked by RUNNING
it under node with no `document` and no `window`.

PWA reimagined slice 6, Task 1 (task-1-brief.md). The pure function lives in
the NEW static/pwa_drive.js; a missing file or function FAILS, never skips.
Times go through the shared clock (static/pwa_clock.js `pwaClock`, prepended
by `clock_source()`): '3:40' in 12-hour, '15:40' with use24h. Missing node
prints `  skip`.

THE SHEET (the REAL /api/drive_sheet/{leg} payload, services/drive_sheet.py
`sheet()` ~192-249; every key is listed so the fixture is not invented):
  leg_id           'leg-soccer-1'
  event_id         the base event id the leg belongs to
  status           'pending' | 'in_progress' | 'completed'  (drive_status row)
  destination      {label, address}  label is 'Home' for a home leg, else the
                   event title or 'Your stop'; address is the event location
                   or null
  eta_ts           epoch SECONDS of the live ETA, null before the drive starts
  eta_label        leave_by.clock_label(eta_ts): '3:58 pm' / '15:58' (the
                   household setting), null with no eta_ts
  toward_waiting   bool, whether the destination is the waiting side
  arrive_by        services/arrive_by.derive() or null:
                   {arrive_at: ISO, arrive_label: '3:58 PM', lead_mins,
                    source, reason, label: 'Arrive 3:58 PM · reason',
                    short_label: 'Arrive 3:58'}   (NOTE short_label carries
                   the word 'Arrive', and is always 12-hour)
  depart_after     the mirror, {depart_at, depart_label, ..., short_label}
  driver_name      the driver's name or null
  passengers       [{member_id, name, is_child, aboard}] aboard is true/false
                   from the roll call, null when never marked
  prep             {items: ['soccer bag', ...] (plain strings), confirmed: bool}
  car              null, or {id, name, icon, image, range, warn}; range is
                   a bare NUMBER (levels.get('range'), no unit, drive_sheet
                   `_car_for` ~132-134) or null; warn is 'Fuel 12%' /
                   'Charge 8%' or null
  next_drive, day_done, messages [{key, icon, label}], audience [names]
                   (not read by the words below)

THE CONTEXT  ctx = {row: {kind, start, end, meta, title, place} | null,
origin, destination, legTitle, now, use24h}. `row` is the day row the sheet
was opened from ('drive' = the viewer's own drive, 'ride' = a passenger's),
start/end are ISO local times, meta reads like '18 min drive · Highlander'.

RULINGS PINNED (fixture below; now 15:12, row 15:40-15:58, 18 min drive)
  leave.time  pwaClock(row.start): '3:40' / '15:40'.
  leave.sub   '<n> min drive · arrive <time> · <car.name>[, <range> mi range][ · ⚠ <car.warn>]'
              -> '18 min drive · arrive 3:58 · Highlander, 210 mi range'.
              n = /(\\d+) min/ of row.meta; time = the arrive_by time, else the
              row's end. The clock is worded through pwaClock (arrive_by.arrive_at
              when the sheet has it, so 24-hour works; the server's short_label
              reads 'Arrive 3:58', so a literal copy would print 'arrive Arrive
              3:58'). Parts absent when their data is: no dangling ' · ', no
              'undefined', no 'null'.
  stops       [{place: origin||'Home', sub: 'Pick up Maya · soccer bag, water',
                done}, {place: destination.label || legTitle, sub: 'Arrive by
                3:58 · Field 2'}]; the address contributes its first
              comma-segment; no prep items -> no ' · items'. done is true on
              the FIRST stop once any passenger is aboard === true.
  arrival     {place: destination label, eta, sub: '<minutes> min · <aboard
              first names> aboard'}: eta is the live ETA as a clock (from eta_ts,
              seconds; falls back to eta_label), minutes = eta - ctx.now rounded;
              with nobody aboard the sub is just '16 min'.
  cover       true for the viewer's own drive row (kind 'drive') while the
              leg is not in progress; false in progress and for a ride row.
  map-only    no sheet: leave null, stops [{place: destination}], arrival
              {place: destination, eta: '', sub: ''}, never a throw.

Run from chauffeur/ with HA_BASE_URL unset:  python tests/test_pwa_drive.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import check, clock_source, pure_source, run_node  # noqa: E402

WANTED = ['pwaDriveView']

PROBE = r"""
const NOW = new Date('2026-11-03T15:12:00');
const ROAD_NOW = new Date('2026-11-03T15:42:00');
const ETA_TS = new Date('2026-11-03T15:58:00').getTime() / 1000;
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};

const MAYA = {member_id: 'm-maya', name: 'Maya Wilson', is_child: true, aboard: null};
const SAM = {member_id: 'm-sam', name: 'Sam Wilson', is_child: true, aboard: null};
function sheet(over) {
  return Object.assign({
    leg_id: 'leg-soccer-1', event_id: 'soccer', status: 'pending',
    destination: {label: 'Riverside fields', address: 'Field 2, 100 River Rd'},
    eta_ts: null, eta_label: null, toward_waiting: false,
    arrive_by: {arrive_at: '2026-11-03T15:58:00', arrive_label: '3:58 PM', lead_mins: 2, source: 'rule',
                reason: 'Warm-up', label: 'Arrive 3:58 PM · Warm-up', short_label: 'Arrive 3:58'},
    depart_after: null, driver_name: 'Jeff Wilson',
    passengers: [Object.assign({}, MAYA)],
    prep: {items: ['soccer bag', 'water'], confirmed: false},
    car: {id: 'c1', name: 'Highlander', icon: '\u{1F699}', image: null, range: 210, warn: null},
    next_drive: null, day_done: false,
    messages: [{key: 'running_late', icon: '⏰', label: 'Running late'}], audience: ['Maya']}, over || {});
}
const ROAD = () => sheet({status: 'in_progress', eta_ts: ETA_TS, eta_label: '3:58 pm',
                          passengers: [Object.assign({}, MAYA, {aboard: true})]});
function ctx(over) {
  return Object.assign({
    row: {kind: 'drive', start: '2026-11-03T15:40:00', end: '2026-11-03T15:58:00', title: 'Drop-off: Soccer practice',
          place: 'Riverside fields', meta: '18 min drive · Highlander'},
    origin: 'Home', destination: 'Riverside fields', legTitle: 'Drop-off: Soccer practice',
    now: NOW, use24h: false}, over || {});
}
const ROW = (over) => Object.assign({}, ctx().row, over || {});
function dangling(text) {
  return /^\s*·|·\s*$|·\s*·|undefined|null/.test(text || '');
}

const CASES = {
  leave_card_words: () => {
    const v = pwaDriveView(sheet(), ctx());
    return {leave: v.leave, keys: Object.keys(v).sort()};
  },
  leave_sub_pieces: () => {
    const sub = (s, c) => pwaDriveView(s, c || ctx()).leave.sub;
    return {
      warn: sub(sheet({car: {id: 'c1', name: 'Highlander', icon: 'x', range: 210, warn: 'Fuel 12%'}})),
      warn_no_range: sub(sheet({car: {id: 'c1', name: 'Highlander', icon: 'x', range: null, warn: 'Fuel 12%'}})),
      no_range: sub(sheet({car: {id: 'c1', name: 'Highlander', icon: 'x', range: null, warn: null}})),
      no_car: sub(sheet({car: null})),
      no_arrive_by: sub(sheet({arrive_by: null})),
      no_minutes: sub(sheet(), ctx({row: ROW({meta: ''})})),
      only_row_end: sub(sheet({car: null, arrive_by: null}), ctx({row: ROW({meta: ''})})),
      nothing: sub(sheet({car: null, arrive_by: null}), ctx({row: ROW({meta: '', end: ''})})),
    };
  },
  leave_arrive_from_short_label_only: () => {
    // the server's own short label, no arrive_at to re-word: must not print 'arrive Arrive 3:58'
    const s = sheet({arrive_by: {short_label: 'Arrive 3:58', label: 'Arrive 3:58 PM'}});
    return pwaDriveView(s, ctx()).leave.sub;
  },
  stops_line: () => pwaDriveView(sheet(), ctx()).stops,
  stops_pieces: () => {
    const stops = (s, c) => pwaDriveView(s, c || ctx()).stops;
    return {
      no_prep: stops(sheet({prep: {items: [], confirmed: false}})),
      no_address: stops(sheet({destination: {label: 'Riverside fields', address: null}})),
      label_falls_back_to_leg_title: stops(sheet({destination: {label: '', address: null}}),
        ctx({destination: ''})),
      origin_defaults_home: stops(sheet(), ctx({origin: ''})),
      origin_given: stops(sheet(), ctx({origin: 'Grandma’s'})),
      two_riders: stops(sheet({passengers: [Object.assign({}, MAYA), Object.assign({}, SAM)]})),
    };
  },
  first_stop_done_when_aboard: () => {
    const done = (passengers) => pwaDriveView(sheet({passengers}), ctx()).stops.map(s => !!s.done);
    return {
      nobody: done([Object.assign({}, MAYA)]),
      aboard: done([Object.assign({}, MAYA, {aboard: true})]),
      false_flag: done([Object.assign({}, MAYA, {aboard: false})]),
      one_of_two: done([Object.assign({}, MAYA, {aboard: true}), Object.assign({}, SAM)]),
      no_riders: done([]),
    };
  },
  arrival_card: () => {
    const v = pwaDriveView(ROAD(), ctx({now: ROAD_NOW}));
    const nobody = pwaDriveView(sheet({status: 'in_progress', eta_ts: ETA_TS, eta_label: '3:58 pm'}),
      ctx({now: ROAD_NOW}));
    const label_only = pwaDriveView(sheet({status: 'in_progress', eta_label: '3:58 pm'}), ctx({now: ROAD_NOW}));
    return {arrival: v.arrival, nobody: nobody.arrival, label_only_eta: label_only.arrival.eta};
  },
  // ETA after arrive-by: the old brief's amber "⚠ Arrive by" warning. The view
  // carries `late: true` and the arrival card names the arrive-by it misses.
  late_case: () => {
    const late = pwaDriveView(sheet({status: 'in_progress', eta_ts: Date.parse('2026-11-03T16:05:00') / 1000, eta_label: '4:05 pm'}),
      ctx({now: ROAD_NOW}));
    const ontime = pwaDriveView(ROAD(), ctx({now: ROAD_NOW}));
    return {late: late.late, lateArrival: late.arrival, ontime: ontime.late, ontimeArrival: ontime.arrival};
  },
  cover_flag: () => ({
    pending_drive: pwaDriveView(sheet(), ctx()).cover,
    in_progress_drive: pwaDriveView(ROAD(), ctx({now: ROAD_NOW})).cover,
    ride_row: pwaDriveView(sheet(), ctx({row: ROW({kind: 'ride'})})).cover,
  }),
  map_only: () => {
    const v = pwaDriveView(null, ctx());
    const u = pwaDriveView(undefined, ctx({row: null}));
    return {v, u_leave: u.leave, u_stops: u.stops, u_arrival: u.arrival,
            no_ctx: (() => { try { const w = pwaDriveView(null, {}); return {leave: w.leave, arrival: w.arrival}; }
                             catch (e) { return {threw: String(e)}; } })()};
  },
  twenty_four_hour: () => {
    const v = pwaDriveView(sheet(), ctx({use24h: true}));
    const road = pwaDriveView(ROAD(), ctx({now: ROAD_NOW, use24h: true}));
    return {leave: v.leave, stops: v.stops, eta: road.arrival.eta, arrival_sub: road.arrival.sub,
            explicit_false: pwaDriveView(sheet(), ctx({use24h: false})).leave.time};
  },
  clean_words: () => {
    const v = pwaDriveView(sheet({car: {id: 'c1', name: 'Highlander', icon: 'x', range: 210, warn: 'Fuel 12%'}}), ctx());
    const r = pwaDriveView(ROAD(), ctx({now: ROAD_NOW}));
    const texts = [v.leave.sub, ...v.stops.map(s => s.sub), r.arrival.sub, r.arrival.eta];
    return texts.filter(dangling);
  },
};
for (const [name, fn] of Object.entries(CASES)) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String((e && e.stack) || e)}; }
}
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _out():
    if 'out' not in _CACHE:
        _CACHE['out'] = run_node(clock_source() + pure_source('pwa_drive.js', WANTED) + '\n' + PROBE)
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value']


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_leave_card_words():
    got = _case('leave_card_words')
    if got is None:
        return
    check(got['keys'] == ['arrival', 'cover', 'late', 'leave', 'stops'],
          f"pwaDriveView returns {{leave, stops, arrival, cover, late}}, got keys {got['keys']!r}")
    check(got['leave']['time'] == '3:40', f"leave.time {got['leave']['time']!r}, expected '3:40'")
    want = '18 min drive · arrive 3:58 · Highlander, 210 mi range'
    check(got['leave']['sub'] == want, f"leave.sub {got['leave']['sub']!r}, expected {want!r}")


def scenario_leave_sub_drops_absent_parts_cleanly():
    got = _case('leave_sub_pieces')
    if got is None:
        return
    dot = ' · '
    want = {
        'warn': f'18 min drive{dot}arrive 3:58{dot}Highlander, 210 mi range{dot}⚠ Fuel 12%',
        'warn_no_range': f'18 min drive{dot}arrive 3:58{dot}Highlander{dot}⚠ Fuel 12%',
        'no_range': f'18 min drive{dot}arrive 3:58{dot}Highlander',
        'no_car': f'18 min drive{dot}arrive 3:58',
        'no_arrive_by': f'18 min drive{dot}arrive 3:58{dot}Highlander, 210 mi range',   # the row's end
        'no_minutes': f'arrive 3:58{dot}Highlander, 210 mi range',
        'only_row_end': 'arrive 3:58',
        'nothing': '',
    }
    for key, expected in want.items():
        check(got[key] == expected, f"leave.sub {key}: {got[key]!r}, expected {expected!r}")


def scenario_leave_arrive_time_is_not_doubled():
    got = _case('leave_arrive_from_short_label_only')
    if got is None:
        return
    check(got == '18 min drive · arrive 3:58 · Highlander, 210 mi range',
          f"the server's short_label 'Arrive 3:58' must read 'arrive 3:58', never 'arrive Arrive 3:58': {got!r}")


def scenario_stops_line():
    got = _case('stops_line')
    if got is None:
        return
    check(len(got) == 2, f"two stops expected, got {got!r}")
    check((got[0]['place'], got[0]['sub']) == ('Home', 'Pick up Maya · soccer bag, water'),
          f"first stop {got[0]!r}, expected Home / 'Pick up Maya · soccer bag, water'")
    check((got[1]['place'], got[1]['sub']) == ('Riverside fields', 'Arrive by 3:58 · Warm-up · Field 2, 100 River Rd'),
          f"second stop {got[1]!r}, expected 'Riverside fields' / 'Arrive by 3:58 · Warm-up · Field 2, 100 River Rd' "
          f"(the server's arrive-by reason and the FULL address: nothing the old brief showed is lost)")
    check(not got[0].get('done') and not got[1].get('done'), f"nobody is aboard, nothing is done: {got!r}")


def scenario_stops_drop_absent_parts():
    got = _case('stops_pieces')
    if got is None:
        return
    check(got['no_prep'][0]['sub'] == 'Pick up Maya', f"no prep items: {got['no_prep'][0]['sub']!r}, expected 'Pick up Maya'")
    check(got['no_address'][1]['sub'] == 'Arrive by 3:58 · Warm-up',
          f"no address: the reason stays, the address drops cleanly: {got['no_address'][1]['sub']!r}")
    check(got['label_falls_back_to_leg_title'][1]['place'] == 'Drop-off: Soccer practice',
          f"no destination label falls back to legTitle: {got['label_falls_back_to_leg_title'][1]!r}")
    check(got['origin_defaults_home'][0]['place'] == 'Home', f"origin defaults to Home: {got['origin_defaults_home'][0]!r}")
    check(got['origin_given'][0]['place'] == 'Grandma’s', f"origin is used: {got['origin_given'][0]!r}")
    two = got['two_riders'][0]['sub']
    check('Maya' in two and 'Sam' in two and 'Wilson' not in two and two.startswith('Pick up '),
          f"two riders: both first names, no surnames: {two!r}")


def scenario_first_stop_done_when_aboard():
    got = _case('first_stop_done_when_aboard')
    if got is None:
        return
    check(got['nobody'] == [False, False], f"nobody marked: {got['nobody']!r}")
    check(got['aboard'] == [True, False], f"Maya aboard marks the pickup done, not the destination: {got['aboard']!r}")
    check(got['false_flag'] == [False, False], f"aboard === false is not aboard: {got['false_flag']!r}")
    check(got['one_of_two'] == [True, False], f"any passenger aboard marks it done: {got['one_of_two']!r}")
    check(got['no_riders'] == [False, False], f"no riders, nothing done: {got['no_riders']!r}")


def scenario_arrival_card():
    got = _case('arrival_card')
    if got is None:
        return
    a = got['arrival']
    check(a == {'place': 'Riverside fields', 'eta': '3:58', 'arriveBy': 'Arrive by 3:58',
                'detail': 'Warm-up · Field 2, 100 River Rd', 'sub': '16 min · Maya aboard'},
          f"arrival {a!r}, expected Riverside fields / '3:58' / 'Arrive by 3:58' / the reason and the full address / '16 min · Maya aboard'")
    check(got['nobody']['sub'] == '16 min', f"nobody aboard: sub {got['nobody']['sub']!r}, expected '16 min'")
    check(got['label_only_eta'] == '3:58 pm', f"no eta_ts: eta falls back to eta_label, got {got['label_only_eta']!r}")


def scenario_late_and_arrive_by_on_the_road():
    got = _case('late_case')
    if got is None:
        return
    check(got.get('late') is True and got.get('ontime') is False,
          f"late = the ETA is after arrive_by.arrive_at (the old amber warning): {got.get('late')!r}/{got.get('ontime')!r}")
    check((got.get('lateArrival') or {}).get('arriveBy') == '⚠ Arrive by 3:58',
          f"on the road the arrival card names the arrive-by it misses: {got['lateArrival']!r}")
    check((got.get('ontimeArrival') or {}).get('arriveBy') == 'Arrive by 3:58',
          f"on time it still names the arrive-by: {got['ontimeArrival']!r}")


def scenario_cover_flag():
    got = _case('cover_flag')
    if got is None:
        return
    check(got['pending_drive'] is True, f"the viewer's own pending drive offers cover: {got['pending_drive']!r}")
    check(got['in_progress_drive'] is False, f"no cover once the drive is in progress: {got['in_progress_drive']!r}")
    check(got['ride_row'] is False, f"a passenger's ride row never offers cover: {got['ride_row']!r}")


def scenario_map_only():
    got = _case('map_only')
    if got is None:
        return
    v = got['v']
    check(v['leave'] is None, f"no sheet, no leave card: {v['leave']!r}")
    check([s['place'] for s in v['stops']] == ['Riverside fields'] and len(v['stops']) == 1,
          f"no sheet: stops [{{place: destination}}], got {v['stops']!r}")
    check(v['arrival'] == {'place': 'Riverside fields', 'eta': '', 'sub': ''},
          f"no sheet arrival {v['arrival']!r}, expected the destination with empty eta and sub")
    check(not v.get('cover'), f"no sheet, no cover: {v.get('cover')!r}")
    check(got['u_leave'] is None and len(got['u_stops']) == 1 and got['u_arrival']['eta'] == '',
          f"no sheet and no row still answers: {got!r}")
    check('threw' not in got['no_ctx'] and got['no_ctx']['leave'] is None,
          f"no sheet and an empty ctx must not throw: {got['no_ctx']!r}")


def scenario_twenty_four_hour():
    got = _case('twenty_four_hour')
    if got is None:
        return
    check(got['leave']['time'] == '15:40', f"use24h leave.time {got['leave']['time']!r}, expected '15:40'")
    check(got['leave']['sub'] == '18 min drive · arrive 15:58 · Highlander, 210 mi range',
          f"use24h leave.sub {got['leave']['sub']!r}")
    check(got['stops'][1]['sub'] == 'Arrive by 15:58 · Warm-up · Field 2, 100 River Rd', f"use24h destination stop {got['stops'][1]!r}")
    check(got['eta'] == '15:58', f"use24h arrival eta {got['eta']!r}, expected '15:58'")
    check(got['arrival_sub'] == '16 min · Maya aboard', f"arrival sub keeps minutes in 24h: {got['arrival_sub']!r}")
    check(got['explicit_false'] == '3:40', f"use24h false keeps '3:40': {got['explicit_false']!r}")


def scenario_no_dangling_separators():
    got = _case('clean_words')
    if got is None:
        return
    check(got == [], f"words with a dangling ' · ', or 'undefined'/'null': {got!r}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors='backslashreplace')
    except Exception:
        pass
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa drive scenarios passed")
    sys.exit(1 if failed else 0)
