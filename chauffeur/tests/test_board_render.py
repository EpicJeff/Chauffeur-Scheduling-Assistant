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
# Relative to the machine's real clock, because the panel re-checks the hero
# against the browser's own time between polls — a fixture pinned to a wall
# time would test nothing after midnight.
_NOW = _D.datetime.now()
UNDERWAY_START = (_NOW - _D.timedelta(minutes=53)).isoformat()
UNDERWAY_END = (_NOW + _D.timedelta(minutes=7)).isoformat()


def _board():
    at = lambda h, m=0: f"{TODAY}T{h:02d}:{m:02d}:00"
    return {
        'now': at(15, 20), 'date_label': 'Saturday, August 8', 'weather': None,
        'temp_now': 71, 'condition': 'sunny', 'condition_emoji': '☀️',
        'background': None, 'statuses': [], 'widgets': ['drives', 'calendar', 'map'],
        'row_height': 240, 'columns': 12,
        'spans': {'calendar': {'cols': 12}, 'drives': {'cols': 6, 'rows': 2}},
        # A hero that is ON: it started before `now` and has not ended. This is
        # the state photographed off the wall as "NEXT UP · 53 min ago".
        'hero': {'remaining': 1, 'later': [], 'all_done': False, 'kids': [],
                 'next': {'id': 'e1', 'kind': 'event', 'title': 'Pre Jazz/Ballet',
                          'location': 'Starpath Dance Academy', 'at': '1:00 PM',
                          'start': UNDERWAY_START, 'end': UNDERWAY_END,
                          'driver': 'Vovo', 'color': '#8b5cf6', 'driver_id': 'drv2',
                          'done': False, 'live': False, 'underway': True,
                          'over': False, 'minutes_until': -53, 'minutes_left': 7}},
        'tiles': [
            {'key': 'drives', 'icon': '🚗', 'label': 'The rest of the day', 'data': {
                'count': 2, 'next_event_id': 'e1',
                'schedule': {
                    'date': TODAY,
                    'events': [
                        {'id': 'e1', 'title': 'Dribble and Swish', 'start': at(16),
                         'end': at(17, 30), 'location': 'Academy'},
                        {'id': 'e2', 'title': 'Pickup', 'start': at(17, 45),
                         'end': at(18, 15), 'location': 'Academy'},
                    ],
                    'assignments': {'e1': 'drv1', 'e2': 'drv2'},
                    'ghost_assignments': {}, 'ghost_drivers': [], 'car_assignments': {},
                    'unassigned': [], 'no_location': [], 'overridden_events': [],
                    'lateness_warnings': [], 'scheduled_errands': [],
                    'route_edges': {}, 'initial_edges': {}, 'final_edges': {},
                    'driver_events': {}, 'calendar_metadata': {}, 'home_location': '',
                    'drivers': [{'id': 'drv1', 'name': 'Sam', 'color_code': '#ef4444'},
                                {'id': 'drv2', 'name': 'Vovo', 'color_code': '#8b5cf6'}],
                    'cars': [], 'completed_drives': [], 'in_progress_drives': [],
                }}},
            {'key': 'calendar', 'icon': '📅', 'label': "What's coming", 'data': {
                'total': 1,
                'days': [
                    {'date': TODAY, 'dom': 8, 'day': 'Today', 'today': True,
                     'more': 0, 'earlier': 0, 'events': [
                         {'title': 'Dentist', 'at': '9:00 AM', 'end_at': '10:00 AM',
                          'all_day': False, 'start': at(9), 'driver': None,
                          'needs_driver': False, 'color': '#64748b',
                          'kind': 'event', 'past': True},
                         {'title': 'Dribble and Swish', 'at': '4:00 PM',
                          'end_at': '5:30 PM', 'all_day': False, 'start': at(16),
                          'driver': 'Sam', 'needs_driver': False,
                          'color': '#ef4444', 'kind': 'event', 'past': False}]},
                    {'date': TOMORROW, 'dom': 9, 'day': 'Tomorrow', 'today': False,
                     'more': 0, 'earlier': 0, 'events': []},
                ]}},
            {'key': 'map', 'icon': '🗺️', 'label': 'Where everyone is', 'data': {
                'mapped': 1,
                'people': [{'member_id': 'm1', 'name': 'Sam', 'color_code': '#ef4444',
                            'avatar': None, 'image': None, 'state': 'not_home',
                            'latitude': 41.5, 'longitude': -81.6, 'is_car': False,
                            'driving': {'leg_title': 'Practice'}}]}},
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
  const tl = doc.getElementById('board-timeline');
  const ag = doc.querySelector('.agenda-cards');
  console.log(JSON.stringify({
    errors: errors,
    tiles: [...doc.querySelectorAll('#tile-grid > a')]
      .map(a => (a.querySelector('.panel-label') || {}).textContent),
    timeline: {
      mounted: !!tl,
      blocks: tl ? tl.querySelectorAll('[id^="event-"]').length : 0,
      draggable: tl ? tl.querySelectorAll('[draggable="true"]').length : 0,
      text: tl ? tl.textContent.replace(/\s+/g, ' ').trim() : ''
    },
    agenda: {
      cards: ag ? [...ag.children].filter(c => c.tagName !== 'TEMPLATE').length : 0,
      style: ag ? ag.getAttribute('style') : '',
      text: ag ? ag.textContent.replace(/\s+/g, ' ').trim() : '',
      // Which rows are greyed, by the title they carry.
      dimmed: ag ? [...ag.querySelectorAll('.opacity-45')]
        .map(e => e.textContent.replace(/\s+/g, ' ').trim()) : []
    },
    hero: {
      label: (doc.querySelector('.panel-card .panel-label') || {}).textContent,
      pill: (() => {
        const l = doc.querySelector('.panel-card .panel-label');
        return l && l.nextElementSibling ? l.nextElementSibling.textContent.trim() : '';
      })(),
      title: (doc.querySelector('.panel-card .text-2xl') || {}).textContent
    },
    map: { mounted: !!doc.getElementById('board-map'),
           listRows: doc.querySelectorAll('.panel-chip').length }
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
  .tiles.find(t => t.key === 'drives').data.schedule;

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

    proc = subprocess.run([node, probe, page, _board_json()], capture_output=True, text=True,
                          cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the board threw while drawing:\n{proc.stderr[:2000]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def scenario_the_board_draws_without_throwing():
    got = _run()
    if got is None:
        return
    check(not got['errors'],
          f"something threw while the board drew itself: {got['errors']}")
    check(got['tiles'] == ['The rest of the day', "What's coming", 'Where everyone is'],
          f"the tiles that came back: {got['tiles']}")


def scenario_the_drives_tile_draws_the_real_timeline():
    """The whole point of the shared renderer. If this passes with zero blocks,
    the tile is a heading over an empty card — which is precisely how the first
    version shipped, and it looks identical to a quiet day."""
    got = _run()
    if got is None:
        return
    tl = got['timeline']
    check(tl['mounted'], "the timeline has nowhere to mount")
    check(tl['blocks'] == 2,
          f"two drives were sent and {tl['blocks']} were drawn — an empty tile "
          "reads exactly like a quiet evening")
    for want in ('Dribble and Swish', 'Sam', 'Vovo', '4:00 PM'):
        check(want in tl['text'],
              f"the timeline drew without {want!r}: {tl['text'][:200]}")
    check(tl['draggable'] == 0,
          "the board's chips are draggable — a wall panel must not reassign a "
          "drive by being leaned against")


def scenario_a_day_card_is_three_columns_wide_on_the_real_page():
    """The fix for "the agenda squishes each day down very narrow". The tile is
    the full twelve columns in this fixture, so four quarter-width day cards go
    across it."""
    got = _run()
    if got is None:
        return
    ag = got['agenda']
    check(ag['cards'] == 2, f"both day cards drew, got {ag['cards']}")
    check('--a-lg:4' in (ag['style'] or ''),
          f"a full-width tile fits four day cards; got {ag['style']!r}")
    check('Nothing scheduled' in ag['text'],
          "a quiet day has to say so — a card that renders empty is the reason "
          "the agenda is day cards rather than a list")
    # Today's finished events stay, greyed. Dropping them made a busy morning
    # invisible: two things left at four in the afternoon read as a quiet day
    # rather than as a day nearly done.
    check('Dentist' in ag['text'],
          f"this morning's appointment vanished off the card: {ag['text'][:160]}")
    check(len(ag['dimmed']) == 1 and 'Dentist' in ag['dimmed'][0],
          f"exactly the past events are greyed, got {ag['dimmed']}")


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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    try:
        for fn in SCENARIOS:
            fn()
            print(f"  ok  {fn.__name__}")
        print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} board-render scenarios passed")
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
