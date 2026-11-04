"""The Plan tab's pure parts: the hour timeline's geometry, the leave strips,
Argyle's lead, the week strip, the people chips and the chip filter, checked
by RUNNING them under node with no `document` and no `window`.

PWA reimagined slice 5, Task 2 (task-2-brief.md). Every function lives at the
top level of static/pwa_plan.js; a missing one FAILS, never skips. Times are
worded through the shared clock (static/pwa_clock.js, Task 1: `pwaClock`,
`pwaClockSuffix`), whose chunks are prepended to the node script when that
file exists. Missing node prints `  skip`.

FIXTURE DAY  Tuesday 2026-11-03, now = 2026-11-03T15:12 local, hourPx 66.
  rows (the slice-1 `pwaRowsFromDom` shape {kind, start, end, title, place,
  meta, state, primary, secondary, allDay, legId, eventId} plus
  color, cal: [calendarId], drivers: [driverId]):
    1:1 with Dana   event    09:00-09:30  cal [cal-dana]
    Piano practice  session  15:00-15:30  cal [cal-sam]     (a practice window)
    Soccer          event    16:00-17:00  cal [cal-maya]    drivers [d-jeff]  #22c55e
    Piano lesson    event    16:30-17:15  cal [cal-sam]
    Family dinner   event    18:30-19:10  cal []  drivers [] (nobody resolvable)
    Grandma visits  event    all day      allDay true       (an all-day trip)

SCHEDULE EDGES (the REAL shape, services/leave_by.py `stamp()` ~185-208 and
`travel_into()` ~211): every edge map is keyed DRIVER first, then EVENT:
    sched.initial_edges[driverId][eventId]     the drive TO eventId from home
    sched.route_edges[driverId][fromEventId]   the drive from fromEventId to
                                               edge.to_event (leave_by
                                               docstring: "route edges by the
                                               event being driven FROM, found
                                               here by their `to_event`")
    sched.final_edges[driverId][eventId]       the drive home after eventId
  and `stamp()` puts `edge.legs = [{depart: ISO, mins: int, from, to}]` on
  each (`_leg()` ~83: from/to in home|pickup|event|dropoff). There is no
  `driver_id` field on an edge or a leg: the driver is the outer key.
  drivers: {id, name, color_code} (models/schemas.py Driver);
  passengers: {id, name, calendar_ids} (models/schemas.py Passenger);
  events: {id, title, start, end, calendar_ids}.
  A strip's passenger first names are the passengers whose calendar_ids meet
  the event's calendar_ids; none resolved -> the event's title. The fixture
  hands drivers/passengers/events in BOTH `opts` (the brief's interface) and
  `sched` (where the payload has them), so either read works.

RULINGS PINNED HERE
  - hour range: start = min(8, floor(first timed start) - 1), end =
    max(19, ceil(last timed end) + 1), clamped 0..24; `hours` lists h = start
    .. end - 1 (one 66px row per hour), so the fixture day is 8 AM .. 8 PM
    (end 21) and an empty day 8 AM .. 6 PM; all-day rows never move it.
  - 12h hour labels 'h AM' / 'h PM' (0 -> '12 AM', 12 -> '12 PM'); 24h 'HH:00'.
  - block top = (startMins - start*60) * hourPx/60, height = max(22,
    mins * hourPx/60); overlap is a.start < b.end && b.start < a.end, so two
    blocks that only touch (10-11, 11-12) stay one lane each.
  - dim when end < now; the now line only on now's own day.
  - strip label '🚗 Leave <pwaClock time> · <driver first name> drives
    <passenger first names | event title>'; one strip per leg; a leg whose
    depart is not on dateStr is no strip; keepingUp -> []; an empty schedule
    -> []; color = the driver's color_code; for a route edge the strip belongs
    to the driver key, eventId is not pinned (from or to_event).
  - lead: events = timed rows of any kind but drive (sessions and rows
    already past COUNT); drives = strips. The brief's step-1 example "Today is
    two drives and four events." holds for the fixture WITHOUT the practice
    window; the full fixture (five timed non-drive rows) reads "... five
    events." Number words spelled; "one drive and one event" singular.
  - chips: Everyone first, then household members (parent/adult/child,
    status absent or 'active') in the members' order; helpers and disabled
    members excluded; a non-driver's driverId is falsy.
  - filter: rows with neither cal nor drivers (empty or absent) are never
    hidden; order kept.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_pwa_plan.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import STATIC, check, pure_source, run_node  # noqa: E402

WANTED = ['pwaPlanGeometry', 'pwaLeaveStrips', 'pwaPlanLead', 'pwaWeekStrip',
          'pwaPeopleChips', 'pwaPlanFilter']
CLOCK = ['pwaClock', 'pwaClockSuffix', 'pwaNumberWord', 'pwaLocalDay', 'pwaWeekday']

HOURS_12 = ['8 AM', '9 AM', '10 AM', '11 AM', '12 PM', '1 PM', '2 PM', '3 PM',
            '4 PM', '5 PM', '6 PM', '7 PM', '8 PM']
HOURS_24 = ['08:00', '09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00',
            '16:00', '17:00', '18:00', '19:00', '20:00']

PROBE = r"""
const DAY = '2026-11-03';
const NOW = new Date('2026-11-03T15:12:00');
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {},
             ms: {jeff: new Date('2026-11-03T15:40:00').getTime(),
                  lorena: new Date('2026-11-03T19:10:00').getTime(),
                  route1: new Date('2026-11-03T17:00:00').getTime(),
                  route2: new Date('2026-11-03T18:05:00').getTime()}};

function row(kind, start, end, title, extra) {
  return Object.assign({kind, start, end, title, place: '', meta: '', state: 'upcoming',
                        primary: `open('${title}')`, secondary: '', allDay: false, legId: '', eventId: '',
                        color: '#64748b', cal: [], drivers: []}, extra || {});
}
const ONE_ON_ONE = row('event', '2026-11-03T09:00:00', '2026-11-03T09:30:00', '1:1 with Dana',
  {eventId: 'ev-1on1', color: '#0ea5e9', cal: ['cal-dana']});
const PRACTICE = row('session', '2026-11-03T15:00:00', '2026-11-03T15:30:00', 'Piano practice',
  {eventId: 'pw-piano', color: '#f59e0b', cal: ['cal-sam']});
const SOCCER = row('event', '2026-11-03T16:00:00', '2026-11-03T17:00:00', 'Soccer',
  {eventId: 'ev-soccer', color: '#22c55e', cal: ['cal-maya'], drivers: ['d-jeff'], place: 'North Field'});
const PIANO = row('event', '2026-11-03T16:30:00', '2026-11-03T17:15:00', 'Piano lesson',
  {eventId: 'ev-piano', color: '#f59e0b', cal: ['cal-sam']});
const DINNER = row('event', '2026-11-03T18:30:00', '2026-11-03T19:10:00', 'Family dinner',
  {eventId: 'ev-dinner', color: '#a855f7'});
const TRIP = row('event', '2026-11-03T00:00:00', '2026-11-03T23:59:00', 'Grandma visits',
  {eventId: 'ev-trip', color: '#94a3b8', allDay: true});
const ROWS = [ONE_ON_ONE, PRACTICE, SOCCER, PIANO, DINNER, TRIP];
const SAT_TRIP = row('event', '2026-11-07T00:00:00', '2026-11-07T23:59:00', 'Lake weekend',
  {eventId: 'ev-lake', allDay: true});

function geo(rows, opts) {
  const g = pwaPlanGeometry(rows, Object.assign({date: DAY, now: NOW, hourPx: 66}, opts || {}));
  return {
    hours: (g.hours || []).map(h => ({h: h.h, label: h.label})),
    blocks: (g.blocks || []).map(b => ({title: b.row && b.row.title, top: b.top, height: b.height,
                                        lane: b.lane, lanes: b.lanes, color: b.color, dim: !!b.dim})),
    allDay: (g.allDay || []).map(r => r.title),
    now: g.now === null ? null : (g.now === undefined ? 'undefined' : {top: g.now.top}),
  };
}

const leg = (depart, mins, from, to) => ({depart, mins, from, to});
const DRIVERS = [{id: 'd-jeff', name: 'Jeff Wilson', color_code: '#2563eb'},
                 {id: 'd-lorena', name: 'Lorena Diaz', color_code: '#db2777'}];
const PASSENGERS = [{id: 'p-maya', name: 'Maya Wilson', calendar_ids: ['cal-maya']},
                    {id: 'p-sam', name: 'Sam Wilson', calendar_ids: ['cal-sam', 'cal-sam-school']}];
const EVENTS = [
  {id: 'ev-soccer', title: 'Soccer', start: '2026-11-03T16:00:00', end: '2026-11-03T17:00:00', calendar_ids: ['cal-maya']},
  {id: 'ev-piano', title: 'Piano lesson', start: '2026-11-03T16:30:00', end: '2026-11-03T17:15:00', calendar_ids: ['cal-sam']},
  {id: 'ev-dinner', title: 'Family dinner', start: '2026-11-03T18:30:00', end: '2026-11-03T19:10:00', calendar_ids: []},
  {id: 'ev-swim-wed', title: 'Swim', start: '2026-11-04T08:00:00', end: '2026-11-04T09:00:00', calendar_ids: ['cal-maya']},
];
function sched(over) {
  return Object.assign({
    events: EVENTS, drivers: DRIVERS, passengers: PASSENGERS,
    initial_edges: {'d-jeff': {
      'ev-soccer': {travel_mins: 18, legs: [leg('2026-11-03T15:40:00', 18, 'home', 'event')]},
      'ev-swim-wed': {travel_mins: 15, legs: [leg('2026-11-04T07:40:00', 15, 'home', 'event')]}}},
    route_edges: {},
    final_edges: {'d-lorena': {
      'ev-dinner': {travel_mins: 12, legs: [leg('2026-11-03T19:10:00', 12, 'event', 'home')]}}},
  }, over || {});
}
const ROUTE = {'d-jeff': {'ev-soccer': {to_event: 'ev-dinner', travel_mins: 25,
  home_waypoint: {to_home_mins: 10, from_home_mins: 15},
  legs: [leg('2026-11-03T17:00:00', 10, 'event', 'home'), leg('2026-11-03T18:05:00', 15, 'home', 'event')]}}};
const STRIP_OPTS = {drivers: DRIVERS, passengers: PASSENGERS, events: EVENTS};
const rawStrips = (s, date, opts) => pwaLeaveStrips(s, date, Object.assign({}, STRIP_OPTS, opts || {}));
function strips(s, date, opts) {
  const got = rawStrips(s, date, opts);
  if (!Array.isArray(got)) return {not_an_array: String(got)};
  return got.map(x => ({label: x.label, driverId: x.driverId, eventId: x.eventId, color: x.color,
                        start_ms: new Date(x.start).getTime(), end_ms: new Date(x.end).getTime()}))
            .sort((a, b) => a.start_ms - b.start_ms);
}

const WEEK = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08'];
function week(opts) {
  return pwaWeekStrip(WEEK, opts).map(d => ({date: d.date, letter: d.letter, day: String(d.day),
    today: !!d.today, selected: !!d.selected, emoji: d.emoji || null, count: d.count || 0, proposed: !!d.proposed}));
}
const WEEK_OPTS = {counts: {'2026-11-03': 6, '2026-11-05': 2, '2026-11-07': 1},
  weather: [{date: '2026-11-03', emoji: '☀️'}, {date: '2026-11-05', emoji: '🌧️'}, {date: '2026-11-20', emoji: '❄️'}],
  proposalDates: new Set(['2026-11-05']), today: '2026-11-03', selected: '2026-11-04'};

const MEMBERS = [
  {id: 'm-jeff', name: 'Jeff Wilson', role: 'parent', color_code: '#2563eb', driver_id: 'd-jeff', passenger_id: null},
  {id: 'm-gma', name: 'Grandma Rose', role: 'helper', color_code: '#9ca3af', driver_id: 'd-gma'},
  {id: 'm-lorena', name: 'Lorena Diaz', role: 'adult', status: 'active', color_code: '#db2777', driver_id: 'd-lorena'},
  {id: 'm-maya', name: 'Maya Wilson', role: 'child', color_code: '#22c55e', passenger_id: 'p-maya'},
  {id: 'm-old', name: 'Old Nanny', role: 'adult', status: 'disabled', color_code: '#000000', driver_id: 'd-old'},
  {id: 'm-sam', name: 'Sam Wilson', role: 'child', color_code: '#f59e0b', passenger_id: 'p-sam'},
];
// A parent's own appointments live on a calendar nobody rides as a
// passenger; the chip also claims every calendar whose metadata summary is
// the member's name or first name (case-insensitive), so Jeff's 1:1 filters
// under Jeff. calendar_metadata is the schedule's {cid: {summary, backgroundColor}}.
const CAL_META = {'cal-jeff': {summary: 'Jeff', backgroundColor: '#2563eb'},
  'cal-maya': {summary: 'Maya Wilson', backgroundColor: '#22c55e'}, 'cal-family': {summary: 'Family', backgroundColor: '#8aa6e8'}};
function chips() {
  return pwaPeopleChips(MEMBERS, {passengers: PASSENGERS, calendar_metadata: CAL_META}).map(c => ({id: c.id, name: c.name,
    color: c.color || null, cal: (c.cal || []).slice().sort(), driverId: c.driverId || null}));
}

const BARE = {kind: 'routine', start: '2026-11-03T20:00:00', end: '2026-11-03T20:15:00', title: 'Feed the cat'};
const titles = (rows) => rows.map(r => r.title);
const filt = (chip) => titles(pwaPlanFilter(ROWS.concat([BARE]), chip));

const CASES = {
  geo_day: () => geo(ROWS),
  geo_six_am: () => geo(ROWS.concat([row('event', '2026-11-03T06:00:00', '2026-11-03T06:30:00', 'Swim practice')])),
  geo_clamped: () => geo([row('event', '2026-11-03T00:30:00', '2026-11-03T01:00:00', 'Red-eye'),
                          row('event', '2026-11-03T22:30:00', '2026-11-03T23:30:00', 'Late show')]),
  geo_empty: () => geo([]),
  geo_only_all_day: () => geo([TRIP]),
  geo_fifteen: () => geo([row('event', '2026-11-03T10:00:00', '2026-11-03T10:15:00', 'Quick call')]),
  geo_adjacent: () => geo([row('event', '2026-11-03T10:00:00', '2026-11-03T11:00:00', 'A'),
                           row('event', '2026-11-03T11:00:00', '2026-11-03T12:00:00', 'B')]),
  geo_now_as_ms: () => geo(ROWS, {now: NOW.getTime()}),
  geo_viewed_from_monday: () => geo(ROWS, {now: new Date('2026-11-02T15:12:00')}),
  geo_24h: () => geo(ROWS, {use24h: true}),
  // A leave strip that overlaps a block in time takes a lane beside it (it
  // never draws over a block): Robin leaves 16:05 while soccer (16:00-17:00)
  // and piano (16:30-17:15) are on. Strips come back from the geometry with
  // their own top/height/lane/lanes; blocks and strips share one lane sweep,
  // each sized by its DRAWN end (max(end, start + 22px of minutes)).
  geo_strips_lanes: () => {
    const g = pwaPlanGeometry(ROWS, {date: DAY, now: NOW, hourPx: 66, strips: [
      {start: '2026-11-03T16:05:00', end: '2026-11-03T16:23:00', label: 'Leave 4:05 · Robin drives Sam', driverId: 'd-lorena'}]});
    return {blocks: (g.blocks || []).map(b => ({title: b.row && b.row.title, lane: b.lane, lanes: b.lanes})),
            strips: (g.strips || []).map(x => ({label: x.label, top: x.top, height: x.height, lane: x.lane, lanes: x.lanes}))};
  },
  // Two short rows that touch in time but would overlap at the 22px minimum
  // height take separate lanes (the drawn end decides, not the time end).
  geo_short_touching: () => geo([row('event', '2026-11-03T10:00:00', '2026-11-03T10:05:00', 'Tiny A'),
    row('event', '2026-11-03T10:05:00', '2026-11-03T10:10:00', 'Tiny B')]),
  strips_day: () => strips(sched(), DAY),
  strips_keeping_up: () => strips(sched(), DAY, {keepingUp: true}),
  strips_other_day: () => strips(sched(), '2026-11-05'),
  strips_empty_schedule: () => strips({}, DAY),
  strips_route_legs: () => strips(sched({initial_edges: {}, final_edges: {}, route_edges: ROUTE}), DAY),
  strips_24h: () => strips(sched(), DAY, {use24h: true}),
  // A ghost driver (main.py merges ghost_assignments before the edges are
  // computed) is not a person: its edges never become strips.
  strips_ghost_ignored: () => strips(sched({initial_edges: {
    'd-jeff': sched().initial_edges['d-jeff'],
    'ghost_d1': {'ev-piano': {travel_mins: 9, legs: [leg('2026-11-03T16:10:00', 9, 'home', 'event')]}}}}), DAY),
  // Waypoints fold: a leg that leaves a pickup or a dropoff continues the
  // strip before it (one departure, one strip); the strip ends when the last
  // folded leg arrives. A strip that leaves an event and ends at home "heads home".
  strips_waypoints_fold: () => strips(sched({
    initial_edges: {'d-jeff': {'ev-soccer': {travel_mins: 30, legs: [
      leg('2026-11-03T15:28:00', 12, 'home', 'pickup'), leg('2026-11-03T15:40:00', 18, 'pickup', 'event')]}}},
    final_edges: {'d-jeff': {'ev-soccer': {travel_mins: 18, legs: [
      leg('2026-11-03T17:05:00', 10, 'event', 'dropoff'), leg('2026-11-03T17:15:00', 8, 'dropoff', 'home')]}}}}), DAY),
  lead_waypoints_fold: () => pwaPlanLead(ROWS, rawStrips(sched({
    initial_edges: {'d-jeff': {'ev-soccer': {travel_mins: 30, legs: [
      leg('2026-11-03T15:28:00', 12, 'home', 'pickup'), leg('2026-11-03T15:40:00', 18, 'pickup', 'event')]}}},
    final_edges: {}}), DAY), DAY, NOW),
  lead_today_full: () => pwaPlanLead(ROWS, rawStrips(sched(), DAY), DAY, NOW),
  lead_today_four: () => pwaPlanLead([ONE_ON_ONE, SOCCER, PIANO, DINNER, TRIP], rawStrips(sched(), DAY), DAY, NOW),
  lead_tuesday_from_monday: () => pwaPlanLead([SOCCER, PIANO, DINNER], rawStrips(sched(), DAY), DAY,
                                              new Date('2026-11-02T20:00:00')),
  lead_one_and_one: () => pwaPlanLead([SOCCER], rawStrips(sched(), DAY).slice(0, 1), DAY, NOW),
  lead_wednesday_quiet: () => pwaPlanLead([], [], '2026-11-04', NOW),
  lead_saturday_all_day: () => pwaPlanLead([SAT_TRIP], [], '2026-11-07', NOW),
  week_strip: () => week(WEEK_OPTS),
  week_strip_no_weather: () => week(Object.assign({}, WEEK_OPTS, {weather: []})),
  people_chips: () => chips(),
  filter_everyone: () => filt({id: 'everyone', name: 'Everyone'}),
  filter_maya: () => filt({id: 'm-maya', name: 'Maya', cal: ['cal-maya'], driverId: null}),
  filter_sam: () => filt({id: 'm-sam', name: 'Sam', cal: ['cal-sam', 'cal-sam-school'], driverId: null}),
  filter_jeff: () => filt({id: 'm-jeff', name: 'Jeff', cal: [], driverId: 'd-jeff'}),
  filter_lorena: () => filt({id: 'm-lorena', name: 'Lorena', cal: [], driverId: 'd-lorena'}),
  // A row on a calendar NO chip claims (the Family calendar, a shared one, a
  // parent's primary named by email) is unresolved: no person chip hides it.
  // pwaPlanFilter(rows, chip, chips) takes every chip to know what is claimed.
  filter_unclaimed_calendar: () => titles(pwaPlanFilter([
    row('event', '2026-11-03T18:30:00', '2026-11-03T19:10:00', 'Shared dinner', {cal: ['cal-family']}),
    row('event', '2026-11-03T16:00:00', '2026-11-03T17:00:00', 'Sam swim', {cal: ['cal-sam']})],
    {id: 'm-maya', name: 'Maya', cal: ['cal-maya'], driverId: null},
    [{id: 'everyone'}, {id: 'm-maya', cal: ['cal-maya'], driverId: null}, {id: 'm-sam', cal: ['cal-sam'], driverId: null}])),
};
for (const [name, fn] of Object.entries(CASES)) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String((e && e.stack) || e)}; }
}
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _script():
    clock = ''
    if os.path.exists(os.path.join(STATIC, 'pwa_clock.js')):
        clock = pure_source('pwa_clock.js', CLOCK) + '\n'
    return clock + pure_source('pwa_plan.js', WANTED) + '\n' + PROBE


def _out():
    if 'out' not in _CACHE:
        _CACHE['out'] = run_node(_script())
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value']


def _near(a, b):
    return isinstance(a, (int, float)) and abs(a - b) < 1e-6


def _blocks(g):
    return {b['title']: b for b in g['blocks']}


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_hour_range_covers_the_day():
    g = _case('geo_day')
    if g is None:
        return
    hs = [h['h'] for h in g['hours']]
    check(hs == list(range(8, 21)),
          f"the fixture day (9:00 first, 19:10 last) runs 8 AM .. 8 PM: min(8, 9-1)=8, max(19, ceil(19:10)+1)=21, "
          f"one row per hour 8..20, got {hs!r}")
    check([h['label'] for h in g['hours']] == HOURS_12, f"12-hour labels {[h['label'] for h in g['hours']]!r}")
    six = _case('geo_six_am')
    check(six['hours'][0] == {'h': 5, 'label': '5 AM'},
          f"a 6 AM row opens the range an hour before it (floor(6)-1 = 5): {six['hours'][:2]!r}")
    check(six['hours'][-1]['h'] == 20, f"the end is unchanged by an early row: {six['hours'][-1]!r}")
    clamped = _case('geo_clamped')
    check(clamped['hours'][0] == {'h': 0, 'label': '12 AM'},
          f"a 00:30 row clamps the start to 0 (floor(0.5)-1 = -1), labelled '12 AM': {clamped['hours'][:1]!r}")
    check(clamped['hours'][-1] == {'h': 23, 'label': '11 PM'} and len(clamped['hours']) == 24,
          f"a 23:30 end clamps the end to 24 (ceil(23.5)+1 = 25): last {clamped['hours'][-1:]!r}, "
          f"{len(clamped['hours'])} rows")
    empty = _case('geo_empty')
    check([h['h'] for h in empty['hours']] == list(range(8, 19)),
          f"an empty day is the floor range 8 .. 19 (rows 8 AM .. 6 PM): {[h['h'] for h in empty['hours']]!r}")
    check(empty['blocks'] == [] and empty['allDay'] == [], f"an empty day has no blocks and no band: {empty!r}")
    only = _case('geo_only_all_day')
    check([h['h'] for h in only['hours']] == list(range(8, 19)),
          f"an all-day row never moves the range (its 00:00 start is not a timed start): "
          f"{[h['h'] for h in only['hours']]!r}")


def scenario_overlaps_take_lanes():
    g = _case('geo_day')
    if g is None:
        return
    b = _blocks(g)
    soccer, piano = b.get('Soccer'), b.get('Piano lesson')
    check(soccer and piano, f"soccer and piano are blocks: {list(b)!r}")
    check(soccer['lanes'] == 2 and piano['lanes'] == 2,
          f"soccer 16:00-17:00 and piano 16:30-17:15 overlap: lanes 2 each, got {soccer['lanes']!r}/{piano['lanes']!r}")
    check({soccer['lane'], piano['lane']} == {0, 1}, f"side by side in lanes 0 and 1: {soccer['lane']!r}/{piano['lane']!r}")
    for title in ('1:1 with Dana', 'Piano practice', 'Family dinner'):
        check(b[title]['lanes'] == 1 and b[title]['lane'] == 0,
              f"{title} overlaps nothing: lane 0 of 1, got {b[title]['lane']!r}/{b[title]['lanes']!r}")
    sl = _case('geo_strips_lanes')
    check(sl is not None and len(sl['strips']) == 1, f"the geometry returns the strip it was given: {sl!r}")
    strip = sl['strips'][0]
    sb = {b['title']: b for b in sl['blocks']}
    check(strip['lanes'] >= 2 and strip['lane'] != sb['Soccer']['lane'],
          f"Robin's 16:05 strip overlaps soccer in time, so it takes its own lane beside it: strip {strip!r} soccer {sb['Soccer']!r}")
    check(strip['top'] == 66 * 8 + 5 * 66 / 60 and strip['height'] == 22,
          f"the strip is placed at 16:05 (8 AM range) with the 22px minimum height: {strip!r}")
    tiny = _blocks(_case('geo_short_touching'))
    check(tiny['Tiny A']['lanes'] == 2 and tiny['Tiny A']['lane'] != tiny['Tiny B']['lane'],
          f"5-minute rows drawn 22px tall would overlap, so they take two lanes: {tiny!r}")
    adj = _blocks(_case('geo_adjacent'))
    check(adj['A']['lanes'] == 1 and adj['B']['lanes'] == 1,
          f"10-11 and 11-12 only touch (start < other end fails), one lane each: {adj!r}")


def scenario_block_geometry():
    g = _case('geo_day')
    if g is None:
        return
    b = _blocks(g)
    check(len(g['blocks']) == 5, f"five timed rows make five blocks: {list(b)!r}")
    want = {  # title: (top, height) at 66 px/hour from 8 AM
        '1:1 with Dana': (66, 33),
        'Piano practice': (462, 33),
        'Soccer': (528, 66),
        'Piano lesson': (561, 49.5),
        'Family dinner': (693, 44),
    }
    for title, (top, height) in want.items():
        check(_near(b[title]['top'], top) and _near(b[title]['height'], height),
              f"{title}: top {b[title]['top']!r} height {b[title]['height']!r}, expected {top} / {height}")
    check(b['Soccer']['color'] == '#22c55e', f"a block wears its row's colour: {b['Soccer']['color']!r}")
    q = _blocks(_case('geo_fifteen'))['Quick call']
    check(_near(q['height'], 22), f"a 15-minute row is max(22, 16.5) = 22 tall, got {q['height']!r}")
    check(_near(q['top'], 132), f"10:00 from 8 AM is 120 min * 1.1 = 132, got {q['top']!r}")


def scenario_all_day_band():
    g = _case('geo_day')
    if g is None:
        return
    check(g['allDay'] == ['Grandma visits'], f"the all-day trip goes to the band: {g['allDay']!r}")
    check('Grandma visits' not in _blocks(g), "an all-day row is never a timed block")


def scenario_now_line_today_only():
    g = _case('geo_day')
    if g is None:
        return
    check(isinstance(g['now'], dict) and _near(g['now']['top'], 475.2),
          f"15:12 from 8 AM is 432 min * 1.1 = 475.2, got {g['now']!r}")
    ms = _case('geo_now_as_ms')
    check(isinstance(ms['now'], dict) and _near(ms['now']['top'], 475.2), f"now as ms works the same: {ms['now']!r}")
    monday = _case('geo_viewed_from_monday')
    check(monday['now'] is None, f"viewed on Monday, Tuesday's timeline has no now line (null): {monday['now']!r}")


def scenario_past_blocks_dim():
    g = _case('geo_day')
    if g is None:
        return
    b = _blocks(g)
    check(b['1:1 with Dana']['dim'], "the 9:00 1:1 ended before 15:12: dim")
    check(not b['Piano practice']['dim'], "the 15:00-15:30 practice is underway at 15:12: not dim")
    for title in ('Soccer', 'Piano lesson', 'Family dinner'):
        check(not b[title]['dim'], f"{title} is still ahead: not dim")
    monday = _blocks(_case('geo_viewed_from_monday'))
    check(not any(x['dim'] for x in monday.values()), f"from Monday nothing on Tuesday is past: {monday!r}")


def scenario_leave_strips_from_edges():
    got = _case('strips_day')
    if got is None:
        return
    ms = _out()['ms']
    check(isinstance(got, list), f"pwaLeaveStrips did not return an array: {got!r}")
    check(len(got) == 2, f"two legs depart on Tuesday (the Wednesday swim leg is ignored): {got!r}")
    jeff, lorena = got
    check(jeff['label'] == '🚗 Leave 3:40 · Jeff drives Maya', f"Jeff's strip label {jeff['label']!r}")
    check(jeff['driverId'] == 'd-jeff' and jeff['eventId'] == 'ev-soccer' and jeff['color'] == '#2563eb',
          f"Jeff's strip carries his id, the event and his colour: {jeff!r}")
    check(jeff['start_ms'] == ms['jeff'] and jeff['end_ms'] == ms['jeff'] + 18 * 60000,
          f"start = depart 15:40, end = depart + 18 min: {jeff!r}")
    check(lorena['label'] == '🚗 Leave 7:10 · Lorena heads home',
          f"a final edge leaves the event for home: every return strip 'heads home': {lorena['label']!r}")
    check(lorena['driverId'] == 'd-lorena' and lorena['color'] == '#db2777' and lorena['eventId'] == 'ev-dinner',
          f"a final edge's strip: {lorena!r}")
    check(lorena['start_ms'] == ms['lorena'] and lorena['end_ms'] == ms['lorena'] + 12 * 60000,
          f"final leg 19:10 + 12 min: {lorena!r}")
    check(_case('strips_keeping_up') == [], "keepingUp sees no leave strips")
    check(_case('strips_other_day') == [], "a day with no departures has no strips")
    check(_case('strips_empty_schedule') == [], "an empty schedule (never built, no HA) has no strips")
    route = _case('strips_route_legs')
    check(isinstance(route, list) and len(route) == 2, f"a route edge with two legs makes two strips: {route!r}")
    check([r['start_ms'] for r in route] == [ms['route1'], ms['route2']], f"one strip per leg at its depart: {route!r}")
    check(route[0]['label'] == '🚗 Leave 5:00 · Jeff heads home'
          and route[1]['label'].startswith('🚗 Leave 6:05 · Jeff drives '),
          f"the layover's first leg heads home, the second drives to the next event: {[r['label'] for r in route]!r}")
    check(all(r['driverId'] == 'd-jeff' and r['color'] == '#2563eb' for r in route), f"route strips' driver: {route!r}")
    ghost = _case('strips_ghost_ignored')
    check(ghost is not None and all(r['driverId'] != 'ghost_d1' for r in ghost) and len(ghost) == 2,
          f"a ghost driver's edges never become strips (the two real ones stay): {ghost!r}")
    fold = _case('strips_waypoints_fold')
    check(isinstance(fold, list) and len(fold) == 2,
          f"home→pickup→event is ONE departure and event→dropoff→home is one: {fold!r}")
    out, back = fold
    check(out['label'] == '🚗 Leave 3:28 · Jeff drives Maya' and out['end_ms'] == out['start_ms'] + 30 * 60000,
          f"the folded outbound strip starts at the first leg and ends when the last leg arrives: {out!r}")
    check(back['label'] == '🚗 Leave 5:05 · Jeff heads home' and back['end_ms'] == back['start_ms'] + 18 * 60000,
          f"a strip that leaves an event and ends at home heads home: {back!r}")
    check(_case('lead_waypoints_fold') == 'Today is one drive and five events.',
          f"the lead counts departures, not legs: {_case('lead_waypoints_fold')!r}")


def scenario_lead_sentences():
    exp = {
        'lead_today_four': 'Today is two drives and four events.',
        'lead_today_full': 'Today is two drives and five events.',
        'lead_tuesday_from_monday': 'Tuesday is two drives and three events.',
        'lead_one_and_one': 'Today is one drive and one event.',
        'lead_wednesday_quiet': 'Wednesday is quiet.',
        'lead_saturday_all_day': 'Saturday is one all-day thing.',
    }
    for name, want in exp.items():
        got = _case(name)
        if got is None:
            return
        check(got == want, f"{name}: got {got!r}, expected {want!r}")


def scenario_week_strip_words():
    got = _case('week_strip')
    if got is None:
        return
    check([d['date'] for d in got] == ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05',
                                        '2026-11-06', '2026-11-07', '2026-11-08'], f"dates kept in order: {got!r}")
    check([d['letter'] for d in got] == ['M', 'T', 'W', 'T', 'F', 'S', 'S'], f"weekday letters {[d['letter'] for d in got]!r}")
    check([d['day'] for d in got] == ['2', '3', '4', '5', '6', '7', '8'], f"day of month {[d['day'] for d in got]!r}")
    check([d['count'] for d in got] == [0, 6, 0, 2, 0, 1, 0], f"counts from opts.counts: {[d['count'] for d in got]!r}")
    check([d['emoji'] for d in got] == [None, '☀️', None, '🌧️', None, None, None],
          f"emoji only where the weather has that date: {[d['emoji'] for d in got]!r}")
    check([d['proposed'] for d in got] == [False, False, False, True, False, False, False],
          f"proposed from proposalDates: {[d['proposed'] for d in got]!r}")
    check([d['today'] for d in got] == [False, True, False, False, False, False, False], f"today: {got!r}")
    check([d['selected'] for d in got] == [False, False, True, False, False, False, False], f"selected: {got!r}")
    bare = _case('week_strip_no_weather')
    check(all(d['emoji'] is None for d in bare), f"no weather (no HA) means no glyphs at all: {bare!r}")


def scenario_people_chips():
    got = _case('people_chips')
    if got is None:
        return
    check([c['id'] for c in got] == ['everyone', 'm-jeff', 'm-lorena', 'm-maya', 'm-sam'],
          f"Everyone first, then household members in order; the helper and the disabled adult are out: "
          f"{[c['id'] for c in got]!r}")
    check(got[0]['name'] == 'Everyone', f"the first chip is 'Everyone': {got[0]!r}")
    by = {c['id']: c for c in got}
    check([by[i]['name'] for i in ('m-jeff', 'm-lorena', 'm-maya', 'm-sam')] == ['Jeff', 'Lorena', 'Maya', 'Sam'],
          f"first names: {[c['name'] for c in got]!r}")
    check(by['m-jeff']['color'] == '#2563eb' and by['m-maya']['color'] == '#22c55e', f"colour = color_code: {got!r}")
    check(by['m-maya']['cal'] == ['cal-maya'] and by['m-sam']['cal'] == ['cal-sam', 'cal-sam-school'],
          f"cal from sched.passengers by passenger_id: {by['m-maya']!r} {by['m-sam']!r}")
    check(by['m-jeff']['cal'] == ['cal-jeff'] and by['m-jeff']['driverId'] == 'd-jeff',
          f"Jeff drives and has no passenger record, but the calendar whose summary is his name is his: {by['m-jeff']!r}")
    check('cal-family' not in by['m-jeff']['cal'] and 'cal-family' not in by['m-lorena']['cal'],
          f"the Family calendar matches nobody's chip by name: {by['m-jeff']!r}")
    check(by['m-lorena']['driverId'] == 'd-lorena', f"Lorena's driverId: {by['m-lorena']!r}")
    check(by['m-maya']['driverId'] is None, f"a child who does not drive has no driverId: {by['m-maya']!r}")


def scenario_filter_keeps_unresolved_rows():
    un = _case('filter_unclaimed_calendar')
    check(un == ['Shared dinner'],
          f"a row whose calendar no chip claims stays under every chip; Sam's swim hides under Maya: {un!r}")
    every = _case('filter_everyone')
    if every is None:
        return
    allrows = ['1:1 with Dana', 'Piano practice', 'Soccer', 'Piano lesson', 'Family dinner', 'Grandma visits',
               'Feed the cat']
    check(every == allrows, f"'everyone' keeps every row in order: {every!r}")
    exp = {
        'filter_maya': ['Soccer', 'Family dinner', 'Grandma visits', 'Feed the cat'],
        'filter_sam': ['Piano practice', 'Piano lesson', 'Family dinner', 'Grandma visits', 'Feed the cat'],
        'filter_jeff': ['Soccer', 'Family dinner', 'Grandma visits', 'Feed the cat'],
        'filter_lorena': ['Family dinner', 'Grandma visits', 'Feed the cat'],
    }
    for name, want in exp.items():
        got = _case(name)
        check(got == want,
              f"{name}: got {got!r}, expected {want!r} (cal meets chip.cal or drivers holds chip.driverId; rows with "
              f"no cal and no drivers, empty or absent, are never hidden)")


def scenario_twenty_four_hour_labels():
    g = _case('geo_24h')
    if g is None:
        return
    check([h['label'] for h in g['hours']] == HOURS_24, f"24-hour labels {[h['label'] for h in g['hours']]!r}")
    s = _case('strips_24h')
    check([x['label'] for x in s] == ['🚗 Leave 15:40 · Jeff drives Maya', '🚗 Leave 19:10 · Lorena heads home'],
          f"24-hour strip labels {[x['label'] for x in s]!r}")


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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa plan scenarios passed")
    sys.exit(1 if failed else 0)
