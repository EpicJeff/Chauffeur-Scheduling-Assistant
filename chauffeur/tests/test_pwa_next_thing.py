"""My Day's hero: `pwaNextThing` picks the next thing of ANY kind from the rows
"Your day" draws, and `pwaHeroNext` turns that row into the HeroCard shape.
Checked by RUNNING both under node with no `document` and no `window`.

PWA reimagined slice 1, Task 2. Every row the day draws stamps a dataset
(`data-kind` drive|event|ride|session|routine|task, start, end, title, place,
meta, state, primary, secondary, leg id, event id) so the hero and the list
cannot disagree; `pwaRowsFromDom` reads it back and the two pure functions
never touch the page. Rows here are the plain objects that adapter returns.

Rules under test (task-2-brief.md):
- drop rows whose end is before now or whose state is completed|done|past;
- a row underway (start <= now <= end) wins, first by start; else the
  earliest start >= now; ties by kind order drive, ride, event, session,
  routine, task; nothing left -> null;
- a drive hero leaves at the leg start ('Leave at 3:40 PM'), has two
  actions 'Start drive' (the row's primary) and 'Ask for cover' (its
  secondary), and reads travel_mins from the meta line; every other kind
  has one action, the row's own tap, labelled ride/event 'Details',
  session 'Open the session', routine 'Done', task 'Open'.

Plus a source scenario: the six row builders stamp `data-kind` with their
literal value, and `pwaDriveRow` stamps the fields the hero reads.

Review fixes pinned (2026-11-03): an all-day row (`allDay`, from
`data-all-day="1"`) is never next; `pwaRowsFromDom` (run under jsdom when it
resolves, else `  skip`) returns only the six day kinds and maps
`data-all-day`; `pwaDriveRow` (run under node) stamps `data-state` 'past'
only once the leg's end is behind now, `data-next` unchanged.

The functions live in static/pwa_myday.js; a missing one FAILS, never skips.
Missing node prints `  skip`.

Run from chauffeur/:  python tests/test_pwa_next_thing.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import (STATIC, TEMPLATES, check, clock_source, function_body,  # noqa: E402
                      pure_source, read, run_node)

WANTED = ['pwaNextThing', 'pwaHeroNext', 'pwaRowsFromDom']

PROBE = r"""
const NOW = new Date('2026-11-03T15:12:00');
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};

function row(kind, start, end, title, extra) {
  return Object.assign({kind, start, end, title, place: '', meta: '', state: 'upcoming',
                        primary: `open('${title}')`, secondary: '', legId: '', eventId: ''}, extra || {});
}
const DRIVE = row('drive', '2026-11-03T15:40:00', '2026-11-03T15:58:00', 'Drop-off: Swim', {
  place: 'Aquatic Center', meta: '18 min drive · the Highlander',
  primary: "openActionSheet('leg-swim-1')", secondary: "openEventModal('ev%7Bswim%7D')",
  legId: 'leg-swim-1', eventId: 'ev-swim'});
const EVENT_1600 = row('event', '2026-11-03T16:00:00', '2026-11-03T17:00:00', 'Dentist',
  {place: 'Main St Dental', meta: 'Until 5:00 PM', primary: "openEventModal('ev%7Bdentist%7D')", eventId: 'ev-dentist'});

function pick(rows, now) {
  const r = pwaNextThing(rows, now ? new Date(now) : NOW);
  return r === null ? null : (r === undefined ? 'undefined' : {kind: r.kind, title: r.title});
}
function hero(r) {
  const h = pwaHeroNext(r, NOW);
  return {
    kind: h.kind, title: h.title, location: h.location,
    leave_label: h.leave_label === undefined ? 'undefined' : h.leave_label,
    leave_at_ms: h.leave_at == null ? null : new Date(h.leave_at).getTime(),
    start_ms: h.start == null ? null : new Date(h.start).getTime(),
    travel_mins: h.travel_mins === undefined ? 'undefined' : h.travel_mins,
    minutes_until: h.minutes_until,
    actions: (h.actions || []).map(a => ({label: a.label, run: a.run})),
  };
}
const CASES = {
  picks_the_earliest_upcoming: () => pick([EVENT_1600, DRIVE]),
  underway_outranks_later: () => pick([
    DRIVE,
    row('event', '2026-11-03T14:00:00', '2026-11-03T17:00:00', 'Robotics open house', {state: 'active'})]),
  passed_rows_never_next: () => pick([
    row('drive', '2026-11-03T13:40:00', '2026-11-03T14:00:00', 'Pick-up: Lunch club'),
    row('ride', '2026-11-03T16:00:00', '2026-11-03T16:00:00', 'Sam drives you to piano')]),
  completed_state_is_skipped: () => pick([
    row('drive', '2026-11-03T15:30:00', '2026-11-03T15:48:00', 'Drop-off: Chess', {state: 'completed'}),
    EVENT_1600]),
  nothing_left_means_no_hero: () => pick([
    row('drive', '2026-11-03T07:40:00', '2026-11-03T08:00:00', 'Drop-off: School'),
    row('event', '2026-11-03T09:00:00', '2026-11-03T10:00:00', 'Standup', {state: 'past'}),
    row('routine', '2026-11-03T18:00:00', '2026-11-03T18:30:00', 'Feed the cat', {state: 'done'})]),
  kind_breaks_ties: () => pick([
    row('ride', '2026-11-03T15:40:00', '2026-11-03T15:40:00', 'Lorena drives you'),
    row('drive', '2026-11-03T15:40:00', '2026-11-03T15:58:00', 'Drop-off: Swim')]),
  keeping_up_rows_have_no_drive: () => pick([
    row('task', '2026-11-03T23:59:00', '2026-11-03T23:59:00', 'Math worksheet'),
    row('routine', '2026-11-03T18:00:00', '2026-11-03T18:30:00', 'Brush teeth'),
    row('session', '2026-11-03T17:00:00', '2026-11-03T17:30:00', 'Piano practice'),
    EVENT_1600,
    row('ride', '2026-11-03T15:40:00', '2026-11-03T15:40:00', 'Sam drives you to piano')]),
  drive_hero: () => Object.assign(hero(DRIVE), {expect_leave_ms: new Date(DRIVE.start).getTime()}),
  routine_hero: () => hero(row('routine', '2026-11-03T18:00:00', '2026-11-03T18:30:00', 'Brush teeth',
    {primary: "toggleRoutine('r-teeth', true)"})),
  // slice 5 task 1: the trailing opts argument carries the 24-hour setting
  drive_hero_24h: () => {
    const at1630 = row('drive', '2026-11-03T16:30:00', '2026-11-03T16:48:00', 'Drop-off: Piano',
      {place: 'Music School', meta: '18 min drive'});
    const at0905 = row('drive', '2026-11-04T09:05:00', '2026-11-04T09:20:00', 'Drop-off: School');
    return {
      h24: pwaHeroNext(at1630, NOW, {use24h: true}).leave_label,
      morning_h24: pwaHeroNext(at0905, NOW, {use24h: true}).leave_label,
      h12_explicit: pwaHeroNext(at1630, NOW, {use24h: false}).leave_label,
      h12_empty: pwaHeroNext(at1630, NOW, {}).leave_label,
      h12_absent: pwaHeroNext(at1630, NOW).leave_label,
    };
  },
  kind_labels: () => {
    const labels = {};
    for (const kind of ['ride', 'event', 'session', 'routine', 'task']) {
      const h = pwaHeroNext(row(kind, '2026-11-03T16:00:00', '2026-11-03T16:30:00', 'X ' + kind,
        {primary: `tap('${kind}')`}), NOW);
      labels[kind] = (h.actions || []).map(a => ({label: a.label, run: a.run}));
    }
    return labels;
  },
  // slice 6 task 1: a ride row's own buttons (parsed from data-actions) are the hero's actions
  ride_hero_with_actions: () => {
    const acts = [{label: 'Where?', run: "pwaWhere('d1')"}, {label: 'Message', run: "messageMember('d1')"},
                  {label: 'Add a moment', run: "openEventThread('soccer')"}];
    const r = row('ride', '2026-11-03T16:00:00', '2026-11-03T16:00:00', 'Sam drives you to soccer',
      {primary: "openEventModal('soccer')", actions: acts});
    const h = pwaHeroNext(r, NOW);
    return {kind: h.kind, actions: h.actions.map(a => ({label: a.label, run: a.run}))};
  },
  ride_hero_without_actions: () => {
    const plain = row('ride', '2026-11-03T16:00:00', '2026-11-03T16:00:00', 'Sam drives you to piano',
      {primary: "openEventModal('piano')"});
    const thread = row('ride', '2026-11-03T16:00:00', '2026-11-03T16:00:00', 'Sam drives you to piano',
      {primary: "openEventThread('piano')"});
    const empty = row('ride', '2026-11-03T16:00:00', '2026-11-03T16:00:00', 'Sam drives you to piano',
      {primary: "openEventModal('piano')", actions: []});
    const acts = h => h.actions.map(a => ({label: a.label, run: a.run}));
    return {absent: acts(pwaHeroNext(plain, NOW)), thread: acts(pwaHeroNext(thread, NOW)),
            empty: acts(pwaHeroNext(empty, NOW))};
  },
  all_day_rows_are_never_next: () => pick([
    row('event', '2026-11-03T00:00:00', '2026-11-03T23:59:00', 'Teacher workday', {allDay: true}),
    row('drive', '2026-11-03T16:00:00', '2026-11-03T16:18:00', 'Drop-off: Piano')]),
  late_drive_stays_next_until_it_ends: () => pick([
    row('event', '2026-11-03T16:00:00', '2026-11-03T17:00:00', 'Dentist'),
    row('drive', '2026-11-03T15:40:00', '2026-11-03T16:00:00', 'Drop-off: Swim')], '2026-11-03T15:45:00'),
  rows_from_dom_reads_only_known_kinds: () => {
    const doc = domDoc('<div id="day">'
      + '<div class="pwa-agenda-row" data-kind="drive" data-start="2026-11-03T15:40:00" data-end="2026-11-03T15:58:00"'
      + ' data-title="Drop-off: Swim" data-state="upcoming"></div>'
      + '<article class="mind-situation" data-kind="finding" data-start="2026-11-03T15:00:00" data-end="2026-11-03T18:00:00"'
      + ' data-title="Thursday has no driver"></article></div>');
    if (!doc) return {skip: 'jsdom not resolvable'};
    return pwaRowsFromDom(doc.getElementById('day')).map(r => ({kind: r.kind, title: r.title}));
  },
  rows_from_dom_maps_all_day: () => {
    const doc = domDoc('<div id="day">'
      + '<div data-kind="event" data-all-day="1" data-start="2026-11-03T00:00:00" data-end="2026-11-03T23:59:00"'
      + ' data-title="Teacher workday"></div>'
      + '<div data-kind="event" data-start="2026-11-03T16:00:00" data-end="2026-11-03T17:00:00"'
      + ' data-title="Dentist"></div></div>');
    if (!doc) return {skip: 'jsdom not resolvable'};
    return pwaRowsFromDom(doc.getElementById('day')).map(r => ({title: r.title, allDay: !!r.allDay}));
  },
};
function domDoc(html) {
  let JSDOM;
  try { ({JSDOM} = require('jsdom')); } catch (e) { return null; }
  // the page stays out of the globals: only this local document exists
  return new JSDOM('<!doctype html><html><body>' + html + '</body></html>').window.document;
}
for (const [name, fn] of Object.entries(CASES)) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String((e && e.stack) || e)}; }
}
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _out():
    if 'out' not in _CACHE:
        _CACHE['out'] = run_node(clock_source() + pure_source('pwa_myday.js', WANTED) + '\n' + PROBE)
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None, False
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value'], True


def _expect_pick(name, kind, title):
    value, ran = _case(name)
    if not ran:
        return
    check(value is not None and value != 'undefined',
          f"{name}: pwaNextThing returned {value!r}, expected the {kind} {title!r}")
    check(value == {'kind': kind, 'title': title},
          f"{name}: pwaNextThing picked {value!r}, expected the {kind} {title!r}")


def scenario_is_pure():
    """pwaNextThing and pwaHeroNext never reach for the page: node defines
    neither `document` nor `window`, so a single touch throws."""
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_picks_the_earliest_upcoming():
    _expect_pick('picks_the_earliest_upcoming', 'drive', 'Drop-off: Swim')


def scenario_underway_outranks_later():
    _expect_pick('underway_outranks_later', 'event', 'Robotics open house')


def scenario_passed_rows_never_next():
    """The drive's end (14:00) is before now even though its state still
    says upcoming: the clock drops it."""
    _expect_pick('passed_rows_never_next', 'ride', 'Sam drives you to piano')


def scenario_completed_state_is_skipped():
    """The drive starts after now (15:30) but is completed: the state drops it."""
    _expect_pick('completed_state_is_skipped', 'event', 'Dentist')


def scenario_nothing_left_means_no_hero():
    value, ran = _case('nothing_left_means_no_hero')
    if ran:
        check(value is None, f"only past/done rows, pwaNextThing must return null, got {value!r}")


def scenario_kind_breaks_ties():
    _expect_pick('kind_breaks_ties', 'drive', 'Drop-off: Swim')


def scenario_keeping_up_rows_have_no_drive():
    value, ran = _case('keeping_up_rows_have_no_drive')
    if not ran:
        return
    check(isinstance(value, dict), f"a keeping-up day with rows still has a hero, got {value!r}")
    check(value['kind'] != 'drive', f"no drive rows, yet the hero is a drive: {value!r}")
    check(value == {'kind': 'ride', 'title': 'Sam drives you to piano'},
          f"the earliest upcoming row is the 15:40 ride, got {value!r}")


def scenario_drive_hero_has_two_actions():
    h, ran = _case('drive_hero')
    if not ran:
        return
    check(h['kind'] == 'drive', f"hero kind {h['kind']!r}, expected 'drive'")
    check(h['title'] == 'Drop-off: Swim', f"hero title {h['title']!r}")
    check([a['label'] for a in h['actions']] == ['Start drive', 'Ask for cover'],
          f"drive hero actions {h['actions']!r}, expected ['Start drive', 'Ask for cover']")
    check(h['actions'][0]['run'] == "openActionSheet('leg-swim-1')",
          f"'Start drive' must run the row's primary, got {h['actions'][0]['run']!r}")
    check(h['actions'][1]['run'] == "openEventModal('ev%7Bswim%7D')",
          f"'Ask for cover' must run the row's secondary, got {h['actions'][1]['run']!r}")
    check(h['leave_label'] == 'Leave at 3:40 PM', f"leave_label {h['leave_label']!r}, expected 'Leave at 3:40 PM'")
    check(h['leave_at_ms'] == h['expect_leave_ms'], "leave_at must be the leg start (15:40)")
    check(h['location'] == 'Aquatic Center', f"location {h['location']!r}, expected the row's place")
    check(h['travel_mins'] == 18, f"travel_mins {h['travel_mins']!r}, expected 18 from '18 min drive · the Highlander'")
    check(h['minutes_until'] == 28, f"minutes_until {h['minutes_until']!r}, 15:12 to 15:40 is 28")


def scenario_drive_hero_honours_use24h():
    """pwaHeroNext(row, now, {use24h: true}) words the leave time 'Leave at
    16:30' (and '09:05'); false, {} or no opts keeps '4:30 PM'."""
    got, ran = _case('drive_hero_24h')
    if not ran:
        return
    check(got['h24'] == 'Leave at 16:30', f"use24h leave_label {got['h24']!r}, expected 'Leave at 16:30'")
    check(got['morning_h24'] == 'Leave at 09:05', f"use24h morning leave_label {got['morning_h24']!r}, expected 'Leave at 09:05'")
    for key in ('h12_explicit', 'h12_empty', 'h12_absent'):
        check(got[key] == 'Leave at 4:30 PM', f"{key} leave_label {got[key]!r}, expected 'Leave at 4:30 PM'")


def scenario_routine_hero_has_one_action():
    h, ran = _case('routine_hero')
    if not ran:
        return
    check(h['kind'] == 'routine', f"hero kind {h['kind']!r}")
    check(h['actions'] == [{'label': 'Done', 'run': "toggleRoutine('r-teeth', true)"}],
          f"routine hero actions {h['actions']!r}, expected one 'Done' running the row's primary")
    check(h['leave_label'] is None, f"only a drive has a leave label, got {h['leave_label']!r}")


def scenario_every_other_kind_has_its_label():
    labels, ran = _case('kind_labels')
    if not ran:
        return
    want = {'ride': 'Details', 'event': 'Details', 'session': 'Open the session',
            'routine': 'Done', 'task': 'Open'}
    for kind, label in want.items():
        check(labels[kind] == [{'label': label, 'run': f"tap('{kind}')"}],
              f"{kind} hero actions {labels[kind]!r}, expected one {label!r} running the row's primary")


def scenario_ride_hero_takes_the_rows_buttons():
    """Slice 6 task 1: a ride row carrying `actions` ([{label, run}], up to
    three, parsed from data-actions) makes those the hero's actions, exactly
    and in order, replacing the single Details/Discuss button."""
    got, ran = _case('ride_hero_with_actions')
    if not ran:
        return
    want = [{'label': 'Where?', 'run': "pwaWhere('d1')"},
            {'label': 'Message', 'run': "messageMember('d1')"},
            {'label': 'Add a moment', 'run': "openEventThread('soccer')"}]
    check(got['kind'] == 'ride', f"hero kind {got['kind']!r}")
    check(got['actions'] == want, f"ride hero actions {got['actions']!r}, expected the row's three buttons {want!r}")


def scenario_ride_hero_without_actions_unchanged():
    """No `actions` (absent or empty): today's one button, 'Details' running
    the primary, or 'Discuss' when the primary is openEventThread(...)."""
    got, ran = _case('ride_hero_without_actions')
    if not ran:
        return
    check(got['absent'] == [{'label': 'Details', 'run': "openEventModal('piano')"}], f"absent actions: {got['absent']!r}")
    check(got['empty'] == [{'label': 'Details', 'run': "openEventModal('piano')"}], f"empty actions: {got['empty']!r}")
    check(got['thread'] == [{'label': 'Discuss', 'run': "openEventThread('piano')"}], f"thread primary: {got['thread']!r}")


def scenario_all_day_rows_are_never_next():
    """An all-day event (00:00-23:59, `allDay: true`) is underway at 15:12 by
    the clock, but it is the day's backdrop, not the next thing: the 16:00
    drive is. Plain rows only; `pwaRowsFromDom` plays no part here."""
    _expect_pick('all_day_rows_are_never_next', 'drive', 'Drop-off: Piano')


def scenario_late_drive_stays_next_until_it_ends():
    """15:45, the drive was to leave at 15:40 and ends at 16:00: it is still
    the next thing, ahead of the 16:00 event (regression pin)."""
    _expect_pick('late_drive_stays_next_until_it_ends', 'drive', 'Drop-off: Swim')


def _dom_case(name):
    value, ran = _case(name)
    if not ran:
        return None
    if isinstance(value, dict) and value.get('skip'):
        print(f"  skip  {name}: {value['skip']}")
        return None
    return value


def scenario_rows_from_dom_reads_only_known_kinds():
    """Run under jsdom: a situations card that also carries `data-kind`
    ('finding') is not a day row; only drive|ride|event|session|routine|task
    come back."""
    value = _dom_case('rows_from_dom_reads_only_known_kinds')
    if value is None:
        return
    check(value == [{'kind': 'drive', 'title': 'Drop-off: Swim'}],
          f"pwaRowsFromDom must return only the drive row, got {value!r}")


def scenario_rows_from_dom_maps_all_day():
    """Run under jsdom: `data-all-day="1"` reaches the row as a truthy
    `allDay`, a timed row's stays falsy; and pwaEventRow stamps it."""
    value = _dom_case('rows_from_dom_maps_all_day')
    if value is not None:
        check(value == [{'title': 'Teacher workday', 'allDay': True}, {'title': 'Dentist', 'allDay': False}],
              f"pwaRowsFromDom must map data-all-day=\"1\" to allDay, got {value!r}")
    body = function_body(read(STATIC, 'pwa_shell.js'), 'pwaEventRow')
    check('data-all-day' in body, "pwaEventRow() does not stamp data-all-day, so the hero cannot skip all-day rows")


# --- source: every row the day draws says what it is ------------------------

BUILDERS = [
    ('pwa_shell.js', 'pwaDriveRow', 'drive'),
    ('pwa_shell.js', 'pwaEventRow', 'event'),
    ('app.html', 'renderMyDayCard', 'ride'),
    ('app.html', 'myDayProgramRow', 'session'),
    ('app.html', 'renderRoutineSection', 'routine'),
    ('app.html', 'renderDueSoonRow', 'task'),
]


def scenario_every_row_builder_stamps_its_kind():
    """The brief names one literal kind per builder; none of them takes its
    kind from a variable, so the literal is required everywhere."""
    missing = []
    for filename, name, kind in BUILDERS:
        src = read(STATIC if filename.endswith('.js') else TEMPLATES, filename)
        body = function_body(src, name)
        if f'data-kind="{kind}"' not in body:
            missing.append(f'{name}() in {filename} -> data-kind="{kind}"')
    check(not missing, "these row builders do not stamp their kind, so the hero cannot see "
                       "their rows: " + '; '.join(missing))


def scenario_drive_row_stamps_what_the_hero_reads():
    body = function_body(read(STATIC, 'pwa_shell.js'), 'pwaDriveRow')
    missing = [attr for attr in ('data-start', 'data-end', 'data-primary', 'data-secondary',
                                 'data-state', 'data-next')
               if not re.search(re.escape(attr) + r'="', body)]
    check(not missing, f"pwaDriveRow() does not stamp {', '.join(missing)}")


DRIVE_ROW_PROBE = r"""
const mfEscape = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
const formatDuration = m => m + ' min';
function d(over) {
  return Object.assign({isPast: false, isCompleted: false, isInProgress: false, timeStr: '3:40 PM',
    colorTheme: 'blue', title: 'Swim', mins: 18, delayMins: 0, lateMins: 0, subtitleHtml: '',
    actionArgs: "'a','b'", eventKey: 'ev-swim', location: 'Aquatic Center', legId: 'leg-swim-1',
    eventId: 'ev-swim', start: '2099-11-03T15:40:00', end: '2099-11-03T16:00:00'}, over || {});
}
function attrs(html) {
  const get = name => { const m = new RegExp(name + '="([^"]*)"').exec(html); return m ? m[1] : null; };
  return {state: get('data-state'), next: get('data-next')};
}
console.log(JSON.stringify({
  late_but_not_over: attrs(pwaDriveRow(d({isPast: true}))),
  over: attrs(pwaDriveRow(d({isPast: true, start: '2020-11-03T15:40:00', end: '2020-11-03T16:00:00'}))),
  completed: attrs(pwaDriveRow(d({isCompleted: true, isPast: true}))),
  active: attrs(pwaDriveRow(d({isInProgress: true}))),
  upcoming: attrs(pwaDriveRow(d())),
}));
"""


def scenario_drive_row_state_waits_for_the_end():
    """`isPast` turns true once the leave time passes, but a late drive is
    not over until its end: `data-state` (what the hero reads) says 'past'
    only when end < now; `data-next` keeps its old meaning (other code reads
    it). Run under node: pwaDriveRow + pwaAgendaRow sliced from
    static/pwa_shell.js, mfEscape/formatDuration stubbed; the function reads
    the real clock, so 'not over' ends in 2099 and 'over' in 2020."""
    src = read(STATIC, 'pwa_shell.js')
    out = run_node(function_body(src, 'pwaAgendaRow') + '\n' + function_body(src, 'pwaDriveRow')
                   + '\n' + DRIVE_ROW_PROBE)
    if out is None:
        print("  skip  node is not installed")
        return
    late = out['late_but_not_over']
    check(late['state'] not in ('past', 'completed'),
          f"a drive past its leave time whose end (2099) is still ahead stamps data-state={late['state']!r}; "
          "the hero drops it as passed. data-state is 'past' only when end < now")
    check(late['next'] == 'past', f"data-next must keep its meaning ('past' once isPast), got {late['next']!r}")
    check(out['over']['state'] == 'past', f"a drive whose end (2020) is behind now stamps data-state={out['over']['state']!r}, expected 'past'")
    check(out['completed']['state'] == 'completed', f"a completed drive stamps data-state={out['completed']['state']!r}")
    check(out['active']['state'] == 'active', f"an in-progress drive stamps data-state={out['active']['state']!r}")
    check(out['upcoming']['state'] == 'upcoming', f"an upcoming drive stamps data-state={out['upcoming']['state']!r}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa next-thing scenarios passed")
    sys.exit(1 if failed else 0)
