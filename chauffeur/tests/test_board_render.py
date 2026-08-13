"""The home board actually DRAWS, in a real DOM.

Everything else about the board can be true while the wall shows an empty box.
`test_home_board.py` proves the payload is right; `test_home_board_runtime.py`
proves the arithmetic is right; neither notices that the drives tile threw
during render and left a blank card — which is exactly what happened the first
time the tile was pointed at the Drives page's own renderer. That renderer
touches `#inbox-container`, which belongs to the Drives PAGE, and
`null.classList` took the whole render down. Silently: the tile is an `<a>`
with a heading, so a wall panel showed the words "THE REST OF THE DAY" over
nothing at all.

So this loads the real rendered page into jsdom, runs Alpine against a stubbed
`/api/home_board`, and looks at what is on the screen.

**Skips** (rather than fails) when node or jsdom is unavailable, in the same
spirit as test_nav_runtime's node check. jsdom is not a dependency of this
project — it is a nicety for the machine doing the refactor. Install it with
`npm install jsdom alpinejs` anywhere node will resolve it from.

Run from chauffeur/:  python tests/test_board_render.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_board_render_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# One ordinary weekday evening, in the shapes the three tiles actually receive.
_D = __import__('datetime')
TODAY = _D.date.today().isoformat()
TOMORROW = (_D.date.today() + _D.timedelta(days=1)).isoformat()
DAY_AFTER_NEXT = (_D.date.today() + _D.timedelta(days=2)).isoformat()
# Relative to the machine's real clock, because the panel re-checks the hero
# against the browser's own time between polls — a fixture pinned to a wall
# time would test nothing after midnight.
_NOW = _D.datetime.now()
UNDERWAY_START = (_NOW - _D.timedelta(minutes=53)).isoformat()
UNDERWAY_END = (_NOW + _D.timedelta(minutes=7)).isoformat()
# The upcoming case: 2 hr 26 min until it starts, 1 hr 46 min until you have to
# be out of the door. The exact numbers from the request.
#
# The extra 30 seconds are load-bearing: `_NOW` is stamped at import, but the
# countdown is computed by jsdom at render time — after this file is written,
# node is spawned and the page boots. On a whole-minute offset any of that
# drift crosses a boundary and the pill reads 1 hr 45 min, so the assertion
# failed at random. Landing mid-minute makes the floor stable for any setup
# under half a minute, and keeps the exact wording pinned.
SOON_START = (_NOW + _D.timedelta(minutes=146, seconds=30)).isoformat()
SOON_END = (_NOW + _D.timedelta(minutes=206, seconds=30)).isoformat()
SOON_LEAVE = (_NOW + _D.timedelta(minutes=106, seconds=30)).isoformat()


def _builtin(t):
    """A built-in tile as the server now ships it: a LOCKED container holding
    exactly one card of its own type, the card carrying the tile's own id.

    Written as a wrapper rather than spelled out per tile because that is
    precisely the claim — nothing about a built-in tile changed when cards
    arrived, so the fixture should not have to say it four times.
    """
    return dict(t, locked=True, config=t.get('config', {}),
                cards=[dict(t, cols=12, rows=0, config=t.get('config', {}))])


def _board(hero=None):
    # `d` is days from today, so a fixture can reach into the range a
    # multi-day tile is configured for.
    at = lambda h, m=0, d=0: (
        f"{(_D.date.today() + _D.timedelta(days=d)).isoformat()}"
        f"T{h:02d}:{m:02d}:00")
    return {
        'now': at(15, 20), 'date_label': 'Saturday, August 8', 'weather': None,
        'temp_now': 71, 'condition': 'sunny', 'condition_emoji': '☀️',
        'background': None, 'statuses': [], 'widgets': ['drives', 'calendar', 'map'],
        'row_height': 240, 'columns': 12,
        'spans': {'calendar': {'cols': 12}, 'drives': {'cols': 6, 'rows': 2}},
        # A hero that is ON: it started before `now` and has not ended. This is
        # the state photographed off the wall as "NEXT UP · 53 min ago".
        'hero': hero or {'remaining': 1, 'later': [], 'all_done': False, 'kids': [],
                 'next': {'id': 'e1', 'kind': 'event', 'title': 'Pre Jazz/Ballet',
                          'location': 'Starpath Dance Academy', 'at': '1:00 PM',
                          'start': UNDERWAY_START, 'end': UNDERWAY_END,
                          'driver': 'Vovo', 'color': '#8b5cf6', 'driver_id': 'drv2',
                          'done': False, 'live': False, 'underway': True,
                          'over': False, 'minutes_until': -53, 'minutes_left': 7}},
        'tiles': [_builtin(t) for t in [
            # The hero band, a TILE since v2.209 — bare (it draws its own
            # rounded card) and reading the payload's top-level `hero`, so
            # its fixture data is just the always-truthy marker.
            {'id': 'hero', 'type': 'hero', 'icon': '🚦', 'label': '',
             'bare': True, 'data': {'ok': True}},
            {'id': 'drives', 'type': 'drives', 'icon': '🚗', 'label': 'The rest of the day', 'data': {
                'count': 2, 'next_event_id': 'e1',
                # The RANGE the tile was configured for. renderSchedule seeds
                # its day map from these and draws one timeline section per
                # day; `days` is what tells the client to withhold dateFilter,
                # the option that narrows that loop back to one.
                'days': 3, 'start_date': TODAY, 'end_date': DAY_AFTER_NEXT,
                'schedule': {
                    'date': TODAY,
                    'events': [
                        {'id': 'e1', 'title': 'Dribble and Swish', 'start': at(16),
                         'end': at(17, 30), 'location': 'Academy'},
                        {'id': 'e2', 'title': 'Pickup', 'start': at(17, 45),
                         'end': at(18, 15), 'location': 'Academy'},
                        {'id': 'e3', 'title': 'Orthodontist', 'start': at(9, 0, 2),
                         'end': at(10, 0, 2), 'location': 'High Street'},
                    ],
                    'assignments': {'e1': 'drv1', 'e2': 'drv2', 'e3': 'drv1'},
                    'ghost_assignments': {}, 'ghost_drivers': [], 'car_assignments': {},
                    'unassigned': [], 'no_location': [], 'overridden_events': [],
                    'lateness_warnings': [], 'scheduled_errands': [],
                    'route_edges': {}, 'initial_edges': {}, 'final_edges': {},
                    'driver_events': {}, 'calendar_metadata': {}, 'home_location': '',
                    'drivers': [{'id': 'drv1', 'name': 'Sam', 'color_code': '#ef4444'},
                                {'id': 'drv2', 'name': 'Vovo', 'color_code': '#8b5cf6'}],
                    'cars': [], 'completed_drives': [], 'in_progress_drives': [],
                }}},
            # The calendar tile is a component MOUNT since v2.207: the
            # agenda is components/family_calendar.html's own drawing, fetched
            # by the component itself, and nothing rides in the payload.
            {'id': 'calendar', 'type': 'calendar', 'icon': '📅',
             'label': "What's coming",
             'data': {'grid': {'view': 'agenda', 'toolbar': False,
                               'days': 3, 'only': []}}},
            # A built-in tile with nothing to say. Its message must be drawn
            # ONCE — a tile's data is its card's data, so anything rendering
            # both draws it twice.
            {'id': 'meals', 'type': 'meals', 'icon': '🍽️', 'label': "Tonight's plate",
             'data': {'empty': 'Nothing pinned for tonight yet.'}},
            {'id': 'map', 'type': 'map', 'icon': '🗺️', 'label': 'Where everyone is', 'data': {
                'mapped': 1,
                'people': [{'member_id': 'm1', 'name': 'Sam', 'color_code': '#ef4444',
                            'avatar': None, 'image': None, 'state': 'not_home',
                            'latitude': 41.5, 'longitude': -81.6, 'is_car': False,
                            'driving': {'leg_title': 'Practice'}}]}},
        ]] + [
            # A CUSTOM tile, last on purpose: its cards draw the same bodies
            # the built-in tiles above draw, so a probe reaching for
            # `.agenda-cards` must still find the calendar TILE's card rather
            # than this one's.
            {'id': 'mine', 'type': 'custom', 'icon': '🧩', 'label': 'Mornings',
             'locked': False, 'bare': True,
             'config': {'title': 'Mornings', 'bare': True}, 'cards': [
                 # A LIST card — the one calendar view still drawn from the
                 # payload since v2.207 (agenda/month/week/day are component
                 # mounts, probed elsewhere).
                 {'id': 'mine-calendar', 'type': 'calendar', 'icon': '📅',
                  'label': "Emma's week", 'title': "Emma's week",
                  'cols': 6, 'rows': 0, 'config': {},
                  'data': {'view': 'list', 'total': 1, 'more': 0, 'rows': [
                      {'title': 'Ballet', 'at': '5:00 PM', 'day': 'Today',
                       'end_at': '6:00 PM', 'all_day': False,
                       'start': at(17), 'driver': 'Vovo',
                       'needs_driver': False, 'color': '#8b5cf6',
                       'kind': 'event', 'past': False}]}},
                 # A calendar card asking for the MONTH grid. Nothing is
                 # drawn from this payload: the element is a mount point and
                 # the shared component fetches its own events.
                 {'id': 'mine-month', 'type': 'calendar', 'icon': '📅',
                  'label': 'Month', 'title': '', 'cols': 12, 'rows': 6,
                  'config': {}, 'data': {'grid': {'view': 'dayGridMonth',
                                                  'toolbar': False,
                                                  'only': []}}},
                 # No title typed, so no heading and no row for one.
                 {'id': 'mine-intake', 'type': 'intake', 'icon': '📥',
                  'label': 'Waiting', 'title': '', 'cols': 6, 'rows': 3,
                  'config': {}, 'data': {'pending': 2}},
             ]},
        ],
    }


HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  // The CDN scripts (Tailwind, Alpine, Leaflet) are not fetched: jsdom would
  // need the network, and none of them decide what is IN the DOM. Alpine is
  // injected from disk below, because it is the one that does.
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const board = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const routes = {
  'api/home_board/catalog': { widgets: [], widget_defaults: [], tabs: [], tab_defaults: [] },
  'api/home_board': board,
  'api/panel/profile': { theme: 'dark', tabs: [], widgets: [], backgrounds: {}, idle_seconds: 180 },
  // The calendar CARD fetches its own month; nothing is shipped in the board
  // payload for it, which is the point of the grid views.
  'api/schedule': { events: [], assignments: {}, drivers: [], passengers: [],
                    members: [], calendar_metadata: {}, scheduled_errands: [],
                    car_assignments: {}, cars: [], true_unassigned: [],
                    matched_rules: {}, diagnostics: {}, prep_by_event: {} },
  'api/settings': { panel_widgets: [], panel_tabs: [], panel_agenda_days: 5 },
};

const errors = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/home',
  beforeParse(w) {
    w.fetch = (u) => {
      const key = Object.keys(routes).find(k => String(u).includes(k));
      return Promise.resolve({ ok: !!key, text: () => Promise.resolve(''),
        json: () => Promise.resolve(key ? routes[key] : []) });
    };
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
    // The board injects FullCalendar lazily via a <script src>, which jsdom
    // will not fetch. Putting it on the window makes `loadFullCalendar()`
    // short-circuit — the laziness itself is asserted structurally over in
    // test_calendar_render.py.
    const fc = process.env.CHF_FULLCALENDAR;
    if (fc) {
      const s = w.document.createElement('script');
      s.textContent = require('fs').readFileSync(fc, 'utf8');
      w.document.addEventListener('DOMContentLoaded', () => w.document.head.appendChild(s));
    }
  }
});
const w = dom.window;
w.addEventListener('error', e => {
  const m = (e.error && e.error.message) || e.message || '';
  // EventSource belongs to the chat bar, which this harness does not stub in
  // time; it has nothing to do with the board.
  if (!/EventSource/.test(m)) errors.push(m);
});
w.console.warn = (...a) => errors.push(a.join(' '));

w.document.addEventListener('DOMContentLoaded', () => {
  const s = w.document.createElement('script');
  s.textContent = fs.readFileSync(require.resolve('alpinejs/dist/cdn.js'), 'utf8');
  w.document.head.appendChild(s);
});

setTimeout(() => {
  const doc = w.document;
  // Mount points carry the INSTANCE id now, so two driving tiles are two
  // elements rather than two claims on one.
  const tl = doc.getElementById('board-timeline-drives');
  console.log(JSON.stringify({
    errors: errors,
    tiles: [...doc.querySelectorAll('#tile-grid > a')]
      .map(a => (a.querySelector('.panel-label') || {}).textContent),
    timeline: {
      mounted: !!tl,
      blocks: tl ? tl.querySelectorAll('[id^="event-"]').length : 0,
      draggable: tl ? tl.querySelectorAll('[draggable="true"]').length : 0,
      // One per DAY SECTION. renderSchedule draws a complete timeline per day
      // in its range, and this is the heading each one carries.
      dayTitles: tl ? [...tl.querySelectorAll('.schedule-date-title')]
        .map(h => h.textContent.replace(/\s+/g, ' ').trim()) : [],
      text: tl ? tl.textContent.replace(/\s+/g, ' ').trim() : ''
    },
    agenda: (() => {
      // The component's agenda, mounted inside the built-in calendar tile.
      const host = doc.getElementById('board-calendar-calendar');
      if (!host) return null;
      const panel = host.querySelector('.cal-agenda');
      return {
        shown: !!(panel && panel.style.display === 'flex'),
        dayCards: host.querySelectorAll('.agenda-day').length,
        // A pinned card draws no view switcher.
        toolbar: !!host.querySelector('[data-ag="view"]'),
        text: panel ? panel.textContent.replace(/\s+/g, ' ').trim() : '',
      };
    })(),
    hero: {
      label: (doc.querySelector('.panel-card .panel-label') || {}).textContent,
      pill: (() => {
        const l = doc.querySelector('.panel-card .panel-label');
        return l && l.nextElementSibling ? l.nextElementSibling.textContent.trim() : '';
      })(),
      title: (doc.querySelector('.panel-card .text-2xl') || {}).textContent,
      right: (() => {
        const t = doc.querySelector('.panel-card .text-right');
        return t ? t.textContent.replace(/\s+/g, ' ').trim() : '';
      })()
    },
    map: { mounted: !!doc.getElementById('board-map-map'),
           listRows: doc.querySelectorAll('.panel-chip').length },
    builtin: (() => {
      const el = doc.querySelector('[data-tile-id="drives"]');
      if (!el) return null;
      return { cells: el.querySelectorAll('.nc-cell').length,
               grids: el.querySelectorAll('.nc-stack-grid').length,
               // The timeline's mount must still be a descendant of the tile
               // with nothing flex-breaking in between.
               depth: (() => {
                 let n = doc.getElementById('board-timeline-drives'), d = 0;
                 while (n && n !== el) { n = n.parentElement; d++; }
                 return n ? d : -1;
               })() };
    })(),
    monthCard: (() => {
      const el = doc.getElementById('board-calendar-mine-month');
      if (!el) return null;
      return { mounted: !!el.querySelector('.fc-view-harness'),
               // A card pinned to a view wants no bar of buttons offering to
               // un-pin it.
               toolbar: !!el.querySelector('.fc-toolbar') };
    })(),
    quiet: (() => {
      const el = doc.querySelector('[data-tile-id="meals"]');
      const txt = el ? el.textContent : '';
      return (txt.match(/Nothing pinned for tonight yet\./g) || []).length;
    })(),
    bareTile: (() => {
      const a = doc.querySelector('[data-tile-id="mine"]');
      const b = doc.querySelector('[data-tile-id="drives"]');
      return { custom: a ? /panel-card/.test(a.className) : null,
               builtin: b ? /panel-card/.test(b.className) : null };
    })(),
    group: (() => {
      const g = doc.querySelector('[data-tile-id="mine"] .nc-stack-grid');
      if (!g) return null;
      return {
        free: /nc-free/.test(g.className),
        cells: [...g.children].filter(c => c.tagName !== 'TEMPLATE').map(c => ({
          style: c.getAttribute('style') || '',
          // `|| ''` because JSON.stringify DROPS an undefined value, so a
          // cell with no heading would arrive with no key at all.
          label: ((c.querySelector('.panel-label') || {}).textContent || ''),
          headings: c.querySelectorAll('.panel-label').length,
          text: c.textContent.replace(/\s+/g, ' ').trim(),
        })),
      };
    })()
  }));
  process.exit(0);
}, 2500);
"""


# The other half of the extraction. The renderer's first home is the Drives
# page, and moving 1300 lines out of it is exactly the kind of change that
# leaves the board working and the page blank. Same plumbing, so it lives here
# rather than in a second file that installs jsdom all over again.
DASH_HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const slice = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
  .tiles.find(t => t.type === 'drives').data.schedule;

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/dashboard_v2',
  beforeParse(w) {
    // Lists where the page's loaders expect lists; this harness is about the
    // renderer, not about what the page fetches.
    w.fetch = (u) => Promise.resolve({ ok: true, text: () => Promise.resolve(''),
      json: () => Promise.resolve(/settings|schedule/.test(String(u)) ? {} : []) });
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
    // The board injects FullCalendar lazily via a <script src>, which jsdom
    // will not fetch. Putting it on the window makes `loadFullCalendar()`
    // short-circuit — the laziness itself is asserted structurally over in
    // test_calendar_render.py.
    const fc = process.env.CHF_FULLCALENDAR;
    if (fc) {
      const s = w.document.createElement('script');
      s.textContent = require('fs').readFileSync(fc, 'utf8');
      w.document.addEventListener('DOMContentLoaded', () => w.document.head.appendChild(s));
    }
  }
});
const w = dom.window;
const errors = [];
w.addEventListener('error', e => errors.push((e.error && e.error.message) || e.message));

setTimeout(() => {
  const doc = w.document;
  // Fill the page's own state the way its loader does, then draw.
  w.__slice = slice;
  w.eval(`currentData = window.__slice;
          initialEdges = currentData.initial_edges; finalEdges = currentData.final_edges;
          currentStartDate = new Date(currentData.date + 'T00:00:00');
          currentEndDate = new Date(currentData.date + 'T00:00:00');
          driversMap = {}; (currentData.drivers || []).forEach(d => driversMap[d.id] = d);
          window.showErrands = true;
          renderSchedule(currentData, { dateFilter: currentData.date });`);
  const c = doc.getElementById('schedule-container');
  console.log(JSON.stringify({
    errors: errors,
    hasRenderer: typeof w.renderSchedule,
    blocks: c.querySelectorAll('[id^="event-"]').length,
    draggable: c.querySelectorAll('[draggable="true"]').length,
    text: c.textContent.replace(/\s+/g, ' ').trim()
  }));
  process.exit(0);
}, 2000);
"""


def _render_dashboard():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/dashboard_v2'),
                                query_params={})
    return main.templates.env.get_template('dashboard.html').render(request=req)


def _render_home():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/home'), query_params={})
    return main.templates.env.get_template('home.html').render(request=req)


_RESULT = {}
_DASH = {}


def _jsdom_ready(node):
    have = subprocess.run([node, '-e', "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print("  skip  jsdom/alpinejs not resolvable — nothing was drawn "
              "(npm install jsdom alpinejs)")
        return False
    return True


def _board_json():
    data = os.path.join(SCRATCH, 'board.json')
    if not os.path.exists(data):
        with open(data, 'w', encoding='utf-8') as f:
            json.dump(_board(), f)
    return data


# The same board, with a hero that has not started yet and knows its departure.
LEAVING = {'remaining': 1, 'later': [], 'all_done': False, 'unbuilt': False,
           'kids': [],
           'next': {'id': 'e1', 'kind': 'event', 'title': 'Pre Jazz/Ballet',
                    'location': 'Starpath Dance Academy', 'at': '5:00 PM',
                    'start': SOON_START, 'end': SOON_END,
                    'leave_at': SOON_LEAVE, 'leave_label': '4:20 PM',
                    'travel_mins': 26, 'from_home': True,
                    'driver': 'Vovo', 'color': '#8b5cf6', 'driver_id': 'drv2',
                    'done': False, 'live': False, 'underway': False,
                    'over': False, 'minutes_until': 146, 'minutes_to_leave': 106}}
_LEAVING = {}


def _run_leaving():
    if _LEAVING:
        return _LEAVING.get('data')
    _LEAVING['data'] = None
    node = shutil.which('node')
    if not node or not _jsdom_ready(node):
        print("  skip  node/jsdom unavailable — the hero was not drawn")
        return None
    probe = os.path.join(SCRATCH, 'harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    page = os.path.join(SCRATCH, 'home.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_home())
    data = os.path.join(SCRATCH, 'board_leaving.json')
    with open(data, 'w', encoding='utf-8') as f:
        json.dump(_board(hero=LEAVING), f)
    proc = subprocess.run([node, probe, page, data], capture_output=True,
                          text=True, cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the board threw:\n{proc.stderr[:1500]}")
    _LEAVING['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _LEAVING['data']


def _run_dashboard():
    if _DASH:
        return _DASH.get('data')
    _DASH['data'] = None
    node = shutil.which('node')
    if not node:
        print("  skip  node is not installed — the Drives page was not drawn")
        return None
    if not _jsdom_ready(node):
        return None
    probe = os.path.join(SCRATCH, 'dash_harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(DASH_HARNESS)
    page = os.path.join(SCRATCH, 'dashboard.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_dashboard())
    proc = subprocess.run([node, probe, page, _board_json()], capture_output=True,
                          text=True, cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0,
          f"the Drives page threw while drawing:\n{proc.stderr[:2000]}")
    _DASH['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _DASH['data']


def _run():
    if _RESULT:
        return _RESULT.get('data')
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print("  skip  node is not installed — the board was not drawn")
        return None
    probe = os.path.join(SCRATCH, 'harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    if not _jsdom_ready(node):
        return None

    page = os.path.join(SCRATCH, 'home.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_home())

    env = dict(os.environ)
    fc = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'static', 'vendor', 'fullcalendar.global.min.js')
    if os.path.exists(fc):
        env['CHF_FULLCALENDAR'] = fc
    proc = subprocess.run([node, probe, page, _board_json()], capture_output=True, text=True,
                          cwd=SCRATCH, timeout=180, env=env)
    check(proc.returncode == 0, f"the board threw while drawing:\n{proc.stderr[:2000]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def scenario_the_board_draws_without_throwing():
    got = _run()
    if got is None:
        return
    check(not got['errors'],
          f"something threw while the board drew itself: {got['errors']}")
    # The hero tile's own heading row is suppressed (bare && locked), so the
    # label its <a> answers with is the one INSIDE the band — hero_card.html's
    # "Happening now" — which is itself the proof the band drew.
    check(got['tiles'] == ['Happening now', 'The rest of the day', "What's coming",
                           "Tonight's plate", 'Where everyone is', 'Mornings'],
          f"the tiles that came back: {got['tiles']}")


def scenario_a_built_in_tile_puts_no_box_between_its_content_and_itself():
    """The regression this exists to stop, photographed off a real wall: every
    mosaic, map and camera tile collapsed to nothing.

    A mosaic, a map and a camera are laid out INTO their tile with `flex-1`.
    Wrapping a built-in tile's card in a grid and a flex cell — which is what
    "a tile is a container of cards" looks like if applied literally — put two
    boxes between the content and the height it was claiming, and every one of
    them became zero pixels tall. Nothing threw. The tiles just went blank.

    So a built-in tile renders its card with no grid, no cell, and a wrapper
    that is `display: contents`: present for Alpine, absent from layout.
    """
    got = _run()
    if got is None:
        return
    b = got['builtin']
    check(b, "the drives tile is not on the board at all")
    check(b['cells'] == 0 and b['grids'] == 0,
          f"a built-in tile wrapped its content in {b['grids']} grid(s) and "
          f"{b['cells']} cell(s); every drawn tile will collapse")
    check(b['depth'] > 0, "the timeline no longer mounts inside its tile")


def scenario_a_card_with_no_title_takes_no_room_for_one():
    """Two panels and two headings around one card is the clutter this
    answers. A card already draws what it is; a heading over it reading "A Home
    Assistant card" is a second label in a box that had one, and the row it
    sits in is space the card wanted.

    So blank means blank — no heading, no row. Type a title to get one. The
    editor still calls the card something in its list, because a row in a list
    of five cards has to be distinguishable; that is a different question from
    what gets drawn on the wall.
    """
    got = _run()
    if got is None:
        return
    cells = got['group']['cells']
    check(cells[0]['headings'] == 1 and cells[0]['label'] == "Emma's week",
          f"a titled card lost its heading: {cells[0]}")
    check(cells[1]['headings'] == 0,
          f"an untitled card still drew a heading: {cells[1]['label']!r}")


def scenario_a_custom_tile_can_drop_its_panel():
    """A card draws its own surface, so a tile drawing another behind it is a
    box inside a box. Bare, the cards float on the board. Built-in tiles keep
    theirs — their card wears no surface of its own, so the tile's IS the
    surface and removing it would leave content on the wallpaper."""
    got = _run()
    if got is None:
        return
    check(got['bareTile']['custom'] is False,
          "a bare custom tile is still drawing a panel behind its cards")
    check(got['bareTile']['builtin'] is True,
          "a built-in tile lost the panel that IS its surface")


def scenario_a_calendar_card_mounts_the_pages_own_grid():
    """The month, week and day views asked for on the board — and they are the
    calendar PAGE's grid, mounted from the shared component, not a smaller copy
    of it. Nothing is shipped in the board payload for one: a month of events
    is not something to put inside a response five other cards are waiting on,
    so the card fetches its own.

    The toolbar is off because the card was pinned to a view, and a bar of
    buttons offering three other views is three ways to un-pin it from the
    wall.
    """
    got = _run()
    if got is None:
        return
    m = got['monthCard']
    check(m, "a calendar card asking for a month grid has no mount point")
    check(m['mounted'], "the shared component did not build a grid in the card")
    check(not m['toolbar'],
          "a card pinned to one view is drawing the view switcher anyway")


def scenario_a_quiet_tile_says_so_once():
    """A tile's data IS its card's data — that is what a built-in tile is — so
    anything that renders the empty message at both levels prints it twice.
    Which is exactly what shipped, and what the wall showed."""
    got = _run()
    if got is None:
        return
    check(got['quiet'] == 1,
          f"a quiet tile said so {got['quiet']} times")


def scenario_a_custom_tile_draws_its_cards_as_the_content_they_are():
    """The claim the whole group rests on: a card IS the tile, filtered. The
    calendar card below draws the calendar tile's own body out of the same
    included file, which is why there is one calendar renderer in this app and
    not two — and the day two exist is the day they start disagreeing about
    what an all-day event looks like.

    Sizes come with it. Each card is spans of TWELFTHS OF ITS GROUP, and a card
    given a height stops the cells stretching so it does not drag its
    neighbour's height to match — the same rule, and the same reason, as a
    stack of Home Assistant cards.
    """
    got = _run()
    if got is None:
        return
    g = got['group']
    check(g, "a custom tile drew no grid at all")
    # calendar (6 cols), month grid (12), intake (6, three rows tall)
    check(len(g['cells']) == 3, f"a tile of three cards drew {len(g['cells'])} cells")
    # Only the card that was given a title wears one; see the scenario about
    # blank meaning blank.
    check(g['cells'][0]['label'] == "Emma's week",
          f"a titled card is not labelled as itself: {g['cells'][0]['label']!r}")
    # The bodies really are the tiles' bodies, not a smaller drawing of them.
    check('Ballet' in g['cells'][0]['text'],
          f"the calendar card drew no calendar: {g['cells'][0]['text'][:200]}")
    check('waiting for a parent' in g['cells'][2]['text'],
          f"the intake card drew no intake: {g['cells'][2]['text'][:200]}")
    check('span 6' in g['cells'][0]['style'] and 'span 6' in g['cells'][2]['style'],
          f"a card's width did not reach the grid: {[c['style'] for c in g['cells']]}")
    check('height' not in g['cells'][0]['style'],
          f"an unsized card was given a height: {g['cells'][0]['style']}")
    check('calc(3 * var(--nc-row))' in g['cells'][2]['style'],
          f"a sized card did not get its height: {g['cells'][2]['style']}")
    check(g['free'],
          "a tile holding a sized card still stretches its cells, so that "
          "card's height would drag its neighbour's to match")


def scenario_the_drives_tile_draws_the_real_timeline():
    """The whole point of the shared renderer. If this passes with zero blocks,
    the tile is a heading over an empty card — which is precisely how the first
    version shipped, and it looks identical to a quiet day."""
    got = _run()
    if got is None:
        return
    tl = got['timeline']
    check(tl['mounted'], "the timeline has nowhere to mount")
    # Three across the fixture's three-day range: two today and one two days
    # out. The count is every drive the tile was SENT, drawn across however
    # many day sections the range produced.
    check(tl['blocks'] == 3,
          f"three drives were sent and {tl['blocks']} were drawn — an empty "
          "tile reads exactly like a quiet evening")
    for want in ('Dribble and Swish', 'Sam', 'Vovo', '4:00 PM'):
        check(want in tl['text'],
              f"the timeline drew without {want!r}: {tl['text'][:200]}")
    check(tl['draggable'] == 0,
          "the board's chips are draggable — a wall panel must not reassign a "
          "drive by being leaned against")


def scenario_the_calendar_tile_is_the_components_own_agenda():
    """The last of the three agenda drawings died in v2.207: the board's
    calendar tile now MOUNTS components/family_calendar.html and shows the
    same hand-drawn agenda the calendar page shows — fetched by the component
    itself, since the board payload no longer carries anything for it.

    What the old server-drawn day cards promised, the component's must still
    deliver: a card per day whether or not anything is on it (a quiet day
    saying so is the reason the agenda is day cards rather than a list), and
    no view switcher on a card nobody asked to be switchable.
    """
    got = _run()
    if got is None:
        return
    ag = got['agenda']
    check(ag, "the calendar tile has no component mount at all")
    check(ag['shown'], "the component agenda is not showing inside the tile")
    check(ag['dayCards'] == 3,
          f"a card per configured day, got {ag['dayCards']} for days=3")
    check('Nothing scheduled' in ag['text'],
          "a quiet day has to say so — a card that renders empty is the reason "
          "the agenda is day cards rather than a list")
    check(not ag['toolbar'],
          "a pinned calendar card is drawing the view switcher anyway")


def scenario_the_hero_leads_with_the_leave_time():
    """*"The leave time is the more important of the two pieces of
    information."* So the pill counts down to the departure and the big number
    is the departure; the start time stays, smaller, because it is still true
    and still the thing everyone else is expecting."""
    got = _run_leaving()
    if got is None:
        return
    hero = got['hero']
    check(hero['pill'] == 'leave in 1 hr 46 min',
          f"the pill counts down to the wrong thing: {hero['pill']!r}")
    check('4:20 PM' in (hero['right'] or ''),
          f"the departure is not the big number: {hero['right']!r}")
    check('for 5:00 PM' in (hero['right'] or '') and '26 min drive' in (hero['right'] or ''),
          f"the start time and the drive have to survive as support: {hero['right']!r}")


def scenario_a_thing_that_has_started_says_so():
    """The pair photographed off the wall — "NEXT UP" beside "53 min ago" —
    for a ballet class already in its last ten minutes. Either half alone is
    fine; together they argue with the clock two feet above them."""
    got = _run()
    if got is None:
        return
    hero = got['hero']
    check(hero['title'] == 'Pre Jazz/Ballet',
          f"the hero drew something else: {hero}")
    check(hero['label'] == 'Happening now',
          f"a thing that has started is not next up, got {hero['label']!r}")
    check('ago' not in hero['pill'],
          f"the pill still counts up from a start that has passed: {hero['pill']!r}")
    check(hero['pill'].startswith('ends in'),
          f"what is left of it is the useful number, got {hero['pill']!r}")


def scenario_the_drives_page_still_draws_its_own_timeline():
    """The renderer moved OUT of dashboard.html. The page still owns the state
    it fills and the handlers the chips carry, and it is not read-only — its
    chips must still be draggable, or the extraction quietly turned the Drives
    page into a poster."""
    got = _run_dashboard()
    if got is None:
        return
    check(got['hasRenderer'] == 'function',
          "the page lost the renderer it used to define")
    check(not got['errors'], f"the page threw while drawing: {got['errors']}")
    check(got['blocks'] == 2, f"two drives, {got['blocks']} drawn")
    check(got['draggable'] == 2,
          f"the page's chips must stay draggable ({got['draggable']} are) — "
          "read-only is the BOARD's option, not the renderer's new default")
    check('Dribble and Swish' in got['text'] and 'Sam' in got['text'],
          f"the page drew something else: {got['text'][:200]}")


def scenario_the_map_tile_is_only_a_map():
    """It listed everybody underneath for one version. The family's note was
    one line: it should just be the map."""
    got = _run()
    if got is None:
        return
    check(got['map']['mounted'], "the map has nowhere to mount")
    check(got['map']['listRows'] == 0,
          f"the map tile is listing people again ({got['map']['listRows']} chips)")


def scenario_a_multi_day_driving_tile_draws_a_timeline_per_day():
    """The correction. Multi-day was never a missing capability of the
    timeline: `renderSchedule` seeds its day map from
    currentStartDate..currentEndDate and loops `sortedDates.forEach`, drawing
    one COMPLETE timeline section per day — which is how the Schedule page
    shows a week in kiosk mode. The board tile was narrowing it away by passing
    `dateFilter`, and the first attempt at "multiple days" answered a question
    nobody asked with a flat list instead.

    So this asserts the thing itself, in a real DOM. Asserting the payload
    alone would have passed for the broken version too.

    THE EMPTY DAY IS SKIPPED, and that is the Schedule page's rule rather than
    a gap here: in read-only mode a driver column with no real events is
    hidden, and a date left with no columns is not drawn at all. The fixture
    covers three days and has drives on two of them, so two sections is the
    right answer — and it is right because the tile shares that renderer
    instead of reimplementing it, which is the whole reason the tile calls
    `renderSchedule` in the first place.
    """
    got = _run()
    if got is None:
        return
    titles = got['timeline']['dayTitles']
    check(len(titles) == 2,
          f"a 3-day driving tile with drives on two of them drew "
          f"{len(titles)} day sections: {titles}")
    check(len(set(titles)) == 2,
          f"the sections are not two different days: {titles}")
    check('Orthodontist' in got['timeline']['text'],
          "the drive two days out was not drawn, so the range reached the "
          "container but not the events")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    try:
        for fn in SCENARIOS:
            fn()
            print(f"  ok  {fn.__name__}")
        print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} board-render scenarios passed")
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
