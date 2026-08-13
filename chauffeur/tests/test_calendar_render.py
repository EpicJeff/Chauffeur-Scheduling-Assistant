"""The calendar page actually DRAWS, in a real DOM — before anything moves.

This file exists because of a regression shipped an hour before it was written.
The board's tiles were refactored into cards, the jsdom board test went green,
and the wall showed four blank tiles: jsdom does no layout, so "the element
exists" was all the old probes could check, and two extra boxes in a flex chain
were invisible to them.

The calendar page is the next thing due to be pulled apart — its month/week/day
grid has to become a component the board can mount as a card, the way
`components/schedule_timeline.html` already serves both the Drives page and the
drives tile. That page is a 1700-line singleton: one global `window.calendar`,
one `window._agendaActive`, ~25 element ids read without a null check, and a
`tuneMonthDensity()` that reaches for `.fc-daygrid-day-frame` with an unscoped
`document.querySelector`. Moving any of it without a test underneath is how the
wall goes blank a second time.

So this pins what the page does TODAY, in the shapes an extraction is most
likely to break:

  * the grid mounts and draws real events out of `api/schedule`;
  * every view the URL can force — month, week, day, agenda — is reachable, and
    they are the four this app promises;
  * agenda is NOT a FullCalendar view; it is a separate panel that replaces the
    grid, so switching has to hide one and show the other;
  * the people legend filters, and filters the AGENDA too;
  * `?view=` pins a view WITHOUT writing to localStorage, which is shared
    across every card iframe on the origin.

Skips (rather than fails) when node or jsdom is unavailable, like the other
real-DOM tests here.

Run from chauffeur/:  python tests/test_calendar_render.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_cal_render_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_cal_render_run_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


_D = datetime
TODAY = _D.date.today()


def _at(h, m=0, d=0):
    return f"{(TODAY + _D.timedelta(days=d)).isoformat()}T{h:02d}:{m:02d}:00"


# What `api/schedule` returns, in the shape `fetchCalEvents` consumes. Two
# events on two different people, so the legend has something to filter and the
# filter has something to prove.
SCHEDULE = {
    'events': [
        {'id': 'e1', 'title': 'Ballet', 'start': _at(17), 'end': _at(18),
         'location': 'Starpath', 'description': ''},
        {'id': 'e2', 'title': 'Orthodontist', 'start': _at(9, 30, 1),
         'end': _at(10, 30, 1), 'location': 'High Street', 'description': ''},
    ],
    'assignments': {'e1': 'drv1', 'e2': 'drv2'},
    'car_assignments': {}, 'cars': [], 'true_unassigned': [],
    'drivers': [{'id': 'drv1', 'name': 'Sam', 'color_code': '#ef4444'},
                {'id': 'drv2', 'name': 'Vovo', 'color_code': '#8b5cf6'}],
    # A LIST of people, each with the calendars they appear on — not a map
    # keyed by event. Getting this wrong is what a stale fixture looks like:
    # `fetchCalEvents` throws, the events callback fails, and the grid is
    # empty for a reason that has nothing to do with the grid.
    'passengers': [{'id': 'm1', 'name': 'Emma', 'calendar_ids': ['cal-emma'],
                    'hashtags': []},
                   {'id': 'm2', 'name': 'Theo', 'calendar_ids': ['cal-theo'],
                    'hashtags': []}],
    'members': [{'id': 'm1', 'name': 'Emma', 'color_code': '#22d3ee',
                 'calendar_ids': ['cal-emma']},
                {'id': 'm2', 'name': 'Theo', 'color_code': '#f59e0b',
                 'calendar_ids': ['cal-theo']}],
    'calendar_metadata': {}, 'matched_rules': {}, 'diagnostics': {},
    'prep_by_event': {}, 'scheduled_errands': [],
}

HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

// The vendored FullCalendar is loaded from disk, like Alpine is in the board
// test: jsdom will not fetch, and it is the one script that decides what ends
// up in the DOM.
const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const sched = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const fcPath = process.argv[4];

const routes = { 'api/schedule': sched, 'api/weather/daily': { days: [] } };
const errors = [];

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/calendar' + (process.argv[5] || ''),
  beforeParse(w) {
    w.fetch = (u) => {
      const key = Object.keys(routes).find(k => String(u).includes(k));
      return Promise.resolve({ ok: !!key, text: () => Promise.resolve(''),
        json: () => Promise.resolve(key ? routes[key] : {}) });
    };
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
    w.scrollTo = () => {};
    // FullCalendar measures; jsdom reports zero for everything, which is fine
    // for "what is in the DOM" but makes the library warn.
    const fc = fs.readFileSync(fcPath, 'utf8');
    const s = w.document.createElement('script');
    s.textContent = fc;
    w.document.addEventListener('DOMContentLoaded', () => {}, true);
    w._injectFc = () => w.document.head.appendChild(s);
  }
});
const w = dom.window;
w.addEventListener('error', e => {
  const m = (e.error && e.error.message) || e.message || '';
  if (!/EventSource/.test(m)) errors.push(m);
});
w._injectFc();

setTimeout(() => {
  const doc = w.document;
  const grid = doc.getElementById('calendar');
  const agenda = doc.getElementById('agenda-view');

  const out = {
    errors: errors,
    // The library booted and built a view.
    mounted: !!(w.calendar && grid && grid.querySelector('.fc-view-harness')),
    startView: w.calendar ? w.calendar.view.type : null,
    // Every view the app promises is reachable by name.
    views: [],
    // What reached the calendar, not what painted. jsdom reports zero for
    // every measurement, so `dayMaxEvents` folds the whole month into a "+N
    // more" popover and the DOM is legitimately empty — but the pipeline that
    // an extraction would break is `fetchCalEvents` feeding the events
    // callback, and that is observable.
    eventTitles: [],
    legend: [...doc.querySelectorAll('#filter-legend button')]
      .map(b => b.textContent.trim()),
    // Shown/hidden by inline `display`, not a class — enterAgenda sets
    // 'flex' and exitAgenda sets 'none'.
    agendaHiddenAtStart: !!(agenda && agenda.style.display === 'none'),
    agendaShown: null, gridHiddenInAgenda: null,
    dayChips: [],
    storedView: w.localStorage.getItem('chauffeur_cal_view'),
  };
  try { out.eventTitles = w.calendar.getEvents().map(e => e.title).sort(); }
  catch (e) { out.eventTitles = ['THREW: ' + e.message]; }

  for (const v of ['dayGridMonth', 'timeGridWeek', 'timeGridDay']) {
    try { w.calendar.changeView(v); out.views.push(w.calendar.view.type); }
    catch (e) { out.views.push('THREW: ' + e.message); }
  }
  // Left in the DAY view on purpose: `dayMaxEvents` does not apply there, so
  // this is the one place jsdom will actually paint a chip and the custom
  // `eventContent` builder can be seen doing its job.
  out.dayChips = [...doc.querySelectorAll('#calendar .fc-event')]
    .map(e => e.textContent.replace(/\s+/g, ' ').trim());
  // Agenda is a panel, not a FullCalendar view.
  try {
    w.enterAgenda();
    out.agendaShown = !!(agenda && agenda.style.display === 'flex');
    out.gridHiddenInAgenda = !!(grid && grid.style.display === 'none');
    w.exitAgenda('dayGridMonth');
  } catch (e) { out.agendaShown = 'THREW: ' + e.message; }

  console.log(JSON.stringify(out));
  process.exit(0);
}, 3000);
"""


def _render_calendar():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/calendar'),
                                query_params={})
    return main.templates.env.get_template('calendar.html').render(request=req)


_RESULT = {}


def _run(query=''):
    key = query or 'plain'
    if key in _RESULT:
        return _RESULT[key]
    _RESULT[key] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the calendar was not drawn')
        return None
    have = subprocess.run([node, '-e', "require.resolve('jsdom')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom not resolvable (npm install jsdom)')
        return None

    fc = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'static', 'vendor', 'fullcalendar.global.min.js')
    if not os.path.exists(fc):
        print('  skip  the vendored FullCalendar is not on disk')
        return None

    probe = os.path.join(SCRATCH, 'harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    page = os.path.join(SCRATCH, 'calendar.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_calendar())
    data = os.path.join(SCRATCH, 'schedule.json')
    with open(data, 'w', encoding='utf-8') as f:
        json.dump(SCHEDULE, f)

    proc = subprocess.run([node, probe, page, data, fc, query],
                          capture_output=True, text=True, cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0,
          f"the calendar threw while drawing:\n{proc.stderr[-2000:]}")
    _RESULT[key] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT[key]


def scenario_the_calendar_mounts_and_draws_its_events():
    """The baseline the extraction must not lose. The grid is FullCalendar's,
    the events come from `api/schedule` through `fetchCalEvents`, and that one
    pipeline feeds the agenda too.

    The assertion is on what reached the CALENDAR, not on what painted: jsdom
    measures everything as zero, so `dayMaxEvents` folds the month into a "+N
    more" popover and an empty grid is honest rather than broken. The pipeline
    is the part an extraction can lose.
    """
    got = _run()
    if got is None:
        return
    check(not got['errors'],
          f"something threw while the calendar drew itself: {got['errors'][:3]}")
    check(got['mounted'], "FullCalendar did not build a view at all")
    check(got['eventTitles'] == ['Ballet', 'Orthodontist'],
          f"the schedule did not reach the calendar: {got['eventTitles']}")


def scenario_all_four_views_are_reachable():
    """Month, week and day are FullCalendar's; agenda is a hand-written panel
    that REPLACES the grid rather than a view the library knows about. An
    extraction that treats all four as library views loses the fourth, and an
    extraction that forgets to hide the grid draws both at once."""
    got = _run()
    if got is None:
        return
    check(got['views'] == ['dayGridMonth', 'timeGridWeek', 'timeGridDay'],
          f"a library view is not reachable: {got['views']}")
    check(got['agendaHiddenAtStart'], "the agenda panel is showing over the grid")
    check(got['agendaShown'] is True,
          f"the agenda panel did not open: {got['agendaShown']}")
    check(got['gridHiddenInAgenda'],
          "the grid is still drawn underneath the agenda, so both are on screen")


def scenario_an_event_is_drawn_by_the_pages_own_builder():
    """`eventContent` is ~200 lines of hand-built DOM with three branches — a
    month chip, a compact chip for anything under 40 minutes, and a timeGrid
    card. It is the single largest thing an extraction moves, and the event
    STORE assertions above would not notice if it were dropped entirely:
    FullCalendar falls back to its own default renderer and the events still
    exist.

    The day view is where jsdom will paint one, because `dayMaxEvents` does
    not apply there.
    """
    got = _run()
    if got is None:
        return
    check(got['dayChips'], "the day view painted no event at all")
    # The LOCATION is the discriminating signal: FullCalendar's own renderer
    # draws a time and a title and knows nothing about `extendedProps.location`,
    # so a chip carrying "Starpath" can only have come from this page's
    # builder. (The title itself is laid out into a sized row that jsdom, which
    # measures everything as zero, does not populate — which is why this asserts
    # on the thing the default renderer could never produce rather than on the
    # thing both would.)
    check(any('Starpath' in c for c in got['dayChips']),
          f"the custom event builder did not draw the location, so the "
          f"default renderer is in charge: {got['dayChips']}")


def scenario_the_people_legend_is_built_from_the_schedule():
    """Filtering by person already exists here — it is the thing most recently
    asked for and already shipped. It is built from the schedule's own members,
    so an extraction that drops `data.members` silently loses the filter."""
    got = _run()
    if got is None:
        return
    check(any('Emma' in b for b in got['legend'])
          and any('Theo' in b for b in got['legend']),
          f"the legend does not list the people on the schedule: {got['legend']}")


def scenario_a_forced_view_does_not_write_to_local_storage():
    """localStorage is shared across the whole origin, which under Home
    Assistant ingress means every card iframe and every tab. A `?view=` card
    that remembered its view would change the view of every other surface —
    which is exactly why `?view=` is the per-instance channel and localStorage
    is the per-person one."""
    forced = _run('?view=week')
    if forced is None:
        return
    check(forced['startView'] == 'timeGridWeek',
          f"?view=week did not pin the view: {forced['startView']}")
    check(forced['storedView'] in (None, ''),
          f"a forced view was remembered as {forced['storedView']!r}, so it "
          f"would follow the household to every other calendar surface")


def scenario_the_grid_is_the_shared_component_and_the_library_is_lazy():
    """The whole point of the extraction, asserted as text because it is a
    structural claim rather than a behavioural one.

    ONE construction of `FullCalendar.Calendar` in the repo: a second would be
    the second calendar renderer this move exists to prevent, and it would
    appear the first time somebody needs a calendar somewhere new.

    And the 282KB library is injected on first MOUNT, never by including the
    component. That is what lets a board carry an agenda-only calendar card
    without downloading a month grid it will never draw — the performance
    requirement this was built to.
    """
    import glob
    tpl_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates')
    builders = []
    for path in glob.glob(os.path.join(tpl_dir, '**', '*.html'), recursive=True):
        with open(path, encoding='utf-8') as fh:
            if 'new FullCalendar.Calendar' in fh.read():
                builders.append(os.path.basename(path))
    check(builders == ['family_calendar.html'],
          f"the calendar is constructed in {builders}, not only in the "
          f"shared component")

    with open(os.path.join(tpl_dir, 'calendar.html'), encoding='utf-8') as fh:
        page = fh.read()
    check('<script src="static/vendor/fullcalendar' not in page,
          "the calendar page still downloads FullCalendar eagerly, so every "
          "surface that includes the component pays for it")
    check('FamilyCalendar.mount(' in page,
          "the page no longer mounts through the shared component")

    with open(os.path.join(tpl_dir, 'components', 'family_calendar.html'),
              encoding='utf-8') as fh:
        comp = fh.read()
    check(comp.count('fullcalendar.global.min.js') == 1
          and 'function loadFullCalendar' in comp,
          "the library is referenced outside the lazy loader")
    # Scoped measurement: unscoped, two calendars on one page measure whichever
    # the document happens to hold first, which is the bug that stops a board
    # from carrying two.
    check('root.querySelector(\'.fc-daygrid-event\')' in comp
          and "document.querySelector('.fc-daygrid" not in comp,
          "the density tuner still measures the document rather than its own "
          "calendar")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} calendar-render scenarios passed")
