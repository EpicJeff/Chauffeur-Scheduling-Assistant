"""Plan, the family's week one day at a time, in the served PWA (slice 5, Task 3).

The adult Plan tab (currentView 'family') becomes: a 34px "Plan" title with a
"Today" reset when another day is selected; Argyle's one-line lead for the
day; people as filter chips (Everyone first); a week strip of seven days
(letter, date, weather glyph, event count, a Proposed dot); then the selected
day as an hour timeline: an all-day band, a coloured block per timed row in
its row's colour (overlaps side by side in lanes), the now line, and the
solver's stamped legs as thin leave strips. Intake and the Needs-you lane sit
above the timeline. A block's tap runs its row's own handler. The rows stay
the truth: the Family branch still builds them, hidden in `.pwa-plan-rows`.

Written before the view exists (Task 4 makes it green), so its first failure
is the missing `#plan-head` on the parent's Plan tab.

Every read the view makes is mocked with page.route (members, drivers,
passengers and auth are seeded and served for real). The timeline is checked
against pwaPlanGeometry / pwaLeaveStrips / pwaPlanLead / pwaPeopleChips /
pwaPlanFilter / pwaWeekStrip evaluated IN THE PAGE over the rows the pane
holds (their datasets read the way pwaRowsFromDom reads them, plus
data-color / data-cal / data-drivers), and against the literal values the
fixture must produce.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_plan_live.py
PWA_REVIEW_PROFILE=<key> runs one profile. PWA_REVIEW_OUTPUT=1 writes the
screenshots to tests/probe_shots/pwa_slice5 (gitignored); any other value is
taken as the output directory.
"""
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
DATA = tempfile.mkdtemp(prefix='chauffeur_plan_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + timedelta(days=1)).strftime('%Y-%m-%d')

# (key, role, driver). `keeping` is the keeping-up adult (calendar facts, no
# driving facet); `navigator` is Sam, a kid on the navigator stage.
PROFILES = [('parent', 'parent', 'd1'), ('adult', 'adult', 'd2'), ('keeping', 'adult', None),
            ('navigator', 'child', None)]
# Seed order is roster order (GET /api/members returns insertion order).
MEMBERS = [
    {'id': 'parent', 'name': 'Alex Morgan', 'role': 'parent', 'driver_id': 'd1', 'passenger_id': 'p_alex',
     'color_code': '#2f6fde'},
    {'id': 'adult', 'name': 'Robin Lee', 'role': 'adult', 'driver_id': 'd2', 'color_code': '#c2410c'},
    {'id': 'keeping', 'name': 'Casey Morgan', 'role': 'adult', 'color_code': '#6b7280',
     'scope': {'preset': 'keeping_up'}},
    {'id': 'maya', 'name': 'Maya', 'role': 'child', 'stage_override': 'navigator', 'passenger_id': 'p_maya',
     'color_code': '#e07a5f'},
    {'id': 'navigator', 'name': 'Sam', 'role': 'child', 'stage_override': 'navigator', 'passenger_id': 'p_sam',
     'color_code': '#7c3aed'},
]
DRIVERS = [{'id': 'd1', 'name': 'Alex Morgan', 'home_location': 'Home', 'color_code': '#2f6fde'},
           {'id': 'd2', 'name': 'Robin Lee', 'home_location': 'Home', 'color_code': '#c2410c'}]
PASSENGERS = [{'id': 'p_alex', 'name': 'Alex', 'calendar_ids': ['cal_alex']},
              {'id': 'p_maya', 'name': 'Maya', 'calendar_ids': ['cal_maya']},
              {'id': 'p_sam', 'name': 'Sam', 'calendar_ids': ['cal_sam']}]
CALENDARS = {'cal_alex': {'backgroundColor': '#2f6fde', 'summary': 'Alex'},
             'cal_maya': {'backgroundColor': '#e07a5f', 'summary': 'Maya'},
             'cal_sam': {'backgroundColor': '#7c3aed', 'summary': 'Sam'},
             'cal_family': {'backgroundColor': '#0f9d58', 'summary': 'Family'}}

ONE_ON_ONE = '1:1 with Jordan'
SOCCER = 'Soccer practice'
PIANO = 'Piano lesson'
DINNER = 'Family dinner'
TRIP = 'Grandma visiting'
PRACTICE = 'Strength training'
SWIM = 'Swim lessons'
LIBRARY = 'Library club'
# The colour each block must wear: the row's data-color (renderFamilyCard's
# rule: the first calendar's backgroundColor; practice teal #14B8A6).
BLOCK_COLORS = {ONE_ON_ONE: '#2f6fde', SOCCER: '#e07a5f', PIANO: '#7c3aed', DINNER: '#0f9d58',
                PRACTICE: '#14B8A6', SWIM: '#e07a5f', LIBRARY: '#7c3aed'}
TODAY_TIMED = {ONE_ON_ONE, PRACTICE, SOCCER, PIANO, DINNER}
CHIPS = ['Everyone', 'Alex', 'Robin', 'Casey', 'Maya', 'Sam']
# The weather glyph per day offset from today (GET /api/weather/daily rows).
WEATHER_EMOJI = ['☀️', '⛅', '🌧️', '☀️', '⛅', '🌤️', '☀️']
FINDING_LINE = 'Soccer may run into piano pickup'
PROPOSAL_TITLE = 'Science fair'
BAD_RESPONSES = []
SHOTS = None
STATE = {}


def seed():
    for member in MEMBERS:
        storage.add_member(dict(member))
    # Members first: add_passenger runs ensure_members, which mints a member
    # for any passenger nobody links.
    for driver in DRIVERS:
        storage.add_driver(dict(driver))
    for passenger in PASSENGERS:
        storage.add_passenger(dict(passenger))
    STATE['finding'] = storage.add_finding({
        'identity': 'overlap:soccer', 'kind': 'overlap', 'severity': 'heads_up', 'line': FINDING_LINE,
        'subject_type': 'event', 'subject_id': 'soccer', 'due_at': NOW.replace(hour=16).timestamp(),
        'state': 'open', 'fingerprint': 'soccer|overlap'})


def finding_situation():
    """GET /api/situations?kinds=finding,insight row in group `now`, built by
    the server's own view() over the seeded finding."""
    fid = STATE.get('finding') or 'finding-1'
    base = {'kind': 'finding', 'id': fid, 'title': FINDING_LINE, 'subject': None, 'state': 'open',
            'since': NOW.timestamp(), 'people': [], 'due': NOW.replace(hour=16).timestamp(),
            'status_note': '', 'note_source': 'fallback', 'note_ts': None, 'next_step': None, 'options': [],
            'asks': [], 'needs_attention': True, 'group': 'now', 'owner_member_id': None, 'sensitivity': None,
            'severity': 'heads_up', 'confidence': None, 'rev': 0}
    try:
        from services import situations as _sit
        real = _sit.view('finding', fid, storage.get_member('parent')) or {}
        json.dumps(real)
    except Exception:
        real = {}
    out = dict(base, **real)
    out.update(group='now', needs_attention=True)
    return out


# --- fixtures ----------------------------------------------------------------

def at(date, hm):
    return f'{date}T{hm}:00'


def schedule():
    """GET /api/schedule. Shapes are the solver blob's: events (buildFamilyCards
    reads id/title/start/end/location/calendar_ids/event_type/all_day/practice),
    assignments, the three edge maps with `legs` stamped as services/leave_by.py
    stamp() writes them ({depart (ISO, naive local), mins, from, to}; legAt in
    app.html reads legs[i].depart), calendar_metadata, passengers, drivers."""
    events = [
        {'id': 'one_on_one', 'title': ONE_ON_ONE, 'start': at(DAY, '09:00'), 'end': at(DAY, '10:00'),
         'location': 'Office, 5th floor', 'calendar_ids': ['cal_alex'], 'event_type': 'standard'},
        {'id': 'trip_grandma', 'title': TRIP, 'start': at(DAY, '00:00'), 'end': at(TOMORROW, '00:00'),
         'all_day': True, 'location': 'Lake cabin', 'calendar_ids': [], 'event_type': 'background_trip',
         'trip_attendees': []},
        {'id': 'practice_strength', 'title': PRACTICE, 'start': at(DAY, '15:00'), 'end': at(DAY, '15:30'),
         'event_type': 'practice', 'calendar_ids': [],
         'practice': {'program_id': 'strength', 'member_id': 'adult', 'member_name': 'Robin', 'title': PRACTICE,
                      'session_label': 'Push and core', 'date': DAY, 'time_start': '15:00', 'time_end': '15:30',
                      'steps': ['Warm up', 'Push-ups'], 'logged': False}},
        {'id': 'soccer', 'title': SOCCER, 'start': at(DAY, '16:00'), 'end': at(DAY, '17:00'),
         'location': 'Riverside fields', 'calendar_ids': ['cal_maya'], 'event_type': 'activity'},
        {'id': 'piano', 'title': PIANO, 'start': at(DAY, '16:30'), 'end': at(DAY, '17:15'),
         'location': 'Music studio', 'calendar_ids': ['cal_sam'], 'event_type': 'activity'},
        {'id': 'dinner', 'title': DINNER, 'start': at(DAY, '18:30'), 'end': at(DAY, '19:10'),
         'location': 'Home', 'calendar_ids': ['cal_family'], 'event_type': 'standard'},
        {'id': 'swim', 'title': SWIM, 'start': at(TOMORROW, '10:00'), 'end': at(TOMORROW, '11:00'),
         'location': 'Aquatic center', 'calendar_ids': ['cal_maya'], 'event_type': 'activity'},
        {'id': 'library', 'title': LIBRARY, 'start': at(TOMORROW, '14:00'), 'end': at(TOMORROW, '15:00'),
         'location': 'Main library', 'calendar_ids': ['cal_sam'], 'event_type': 'activity'},
    ]
    return {
        'events': events,
        'assignments': {'soccer': 'd1', 'piano': 'd2', 'swim': 'd1', 'library': 'd1'},
        'home_location': 'Home', 'leave_margin_mins': 5,
        'initial_edges': {
            'd1': {'soccer': {'travel_mins': 18, 'buffer_before_mins': 0,
                              'legs': [{'depart': at(DAY, '15:40'), 'mins': 18, 'from': 'home', 'to': 'event'}]}},
            'd2': {'piano': {'travel_mins': 18, 'buffer_before_mins': 0,
                             'legs': [{'depart': at(DAY, '16:05'), 'mins': 18, 'from': 'home', 'to': 'event'}]}}},
        # Tomorrow's one drive is a route edge (keyed by the event driven FROM,
        # with to_event): a leg on another date the today strips must ignore.
        'route_edges': {
            'd1': {'swim': {'to_event': 'library', 'travel_mins': 15,
                            'legs': [{'depart': at(TOMORROW, '13:40'), 'mins': 15, 'from': 'event', 'to': 'event'}]}}},
        'final_edges': {},
        'calendar_metadata': CALENDARS,
        'passengers': PASSENGERS,
        'drivers': DRIVERS,
    }


def weather_rows(start, days):
    out = []
    first = datetime.strptime(DAY, '%Y-%m-%d')
    try:
        begin = datetime.strptime(start, '%Y-%m-%d') if start else first
    except ValueError:
        begin = first
    for i in range(days):
        d = begin + timedelta(days=i)
        offset = (d - first).days
        if 0 <= offset < len(WEATHER_EMOJI):
            out.append({'date': d.strftime('%Y-%m-%d'), 'emoji': WEATHER_EMOJI[offset], 'condition': 'sunny',
                        'high': 68 + offset, 'low': 51, 'precip': 10})
    return out


def channels(key):
    """GET /api/channels (main.py list_channels): the family hub with today's
    14:40 message as its preview."""
    last = {'id': 'f1', 'channel_id': 'family', 'sender_member_id': 'adult' if key != 'adult' else 'parent',
            'body': 'Running ten minutes late', 'ts': int(NOW.replace(hour=14, minute=40).timestamp()),
            'reactions': {}}
    return [{'id': 'family', 'kind': 'family', 'title': 'Family', 'member_ids': [], 'last_message': last,
             'unread': 0}]


class Mocks:
    """One profile's server, as page.route answers it. Mutable on purpose:
    clock_24h flips `use24h` and reloads."""

    def __init__(self, key, driver):
        self.key = key
        self.driver = driver
        self.use24h = False
        # The adult runs with no forecast (no HA): the strip draws no glyphs.
        self.weather = key != 'adult'
        self.weather_calls = []
        self.proposals = [{'id': 'prop1', 'title': PROPOSAL_TITLE, 'start': at(TOMORROW, '18:00'),
                           'end': at(TOMORROW, '20:00'), 'all_day': False, 'location': 'School gym', 'notes': '',
                           'source_from': 'school@example.org', 'status': 'proposed', 'calendar_id': None,
                           'supplies': []}] if key == 'parent' else []
        self.finding = finding_situation() if key == 'parent' else None

    def proposal_dates(self):
        return sorted({p['start'][:10] for p in self.proposals})

    def weather_daily(self, route):
        q = parse_qs(urlparse(route.request.url).query)
        self.weather_calls.append(route.request.url)
        if not self.weather:
            return route.fulfill(json=[])
        days = int(q.get('days', ['7'])[0] or 7)
        route.fulfill(json=weather_rows(q.get('start', [None])[0], days))

    def situations(self, route):
        q = parse_qs(urlparse(route.request.url).query)
        kinds = (q.get('kinds', [''])[0] or '').split(',')
        out = [self.finding] if self.finding and 'finding' in kinds else []
        route.fulfill(json={'situations': out})

    def install(self, page):
        key = self.key
        sched = schedule()
        page.route('**/api/schedule?*', lambda r: r.fulfill(json=sched))
        page.route('**/api/settings', lambda r: r.fulfill(json={'time_format_24h': self.use24h}))
        page.route('**/api/weather/daily*', self.weather_daily)
        page.route('**/api/weather/now*', lambda r: r.fulfill(status=200, content_type='application/json', body='null'))
        page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/messages/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))

        def member_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'member_id': key, 'name': key, 'date': date, 'rides': [], 'due_soon': [],
                                'still_open': [], 'status_days': [], 'launch': None})
        page.route('**/api/members/*/day?*', member_day)

        def routine_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'date': date, 'items': [], 'streak': {}})
        page.route('**/api/routines/day?*', routine_day)
        page.route('**/api/requests?*', lambda r: r.fulfill(json={'waiting_on_me': [], 'mine': []}))
        page.route('**/api/proposals?*', lambda r: r.fulfill(json=self.proposals))
        page.route('**/api/commitments?*', lambda r: r.fulfill(json=[]))
        page.route('**/api/chores', lambda r: r.fulfill(json=[]))
        page.route('**/api/points', lambda r: r.fulfill(json=[]))
        page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
        page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/household-tasks(\?[^/]*)?$'), lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/shopping/lists(\?.*)?$'), lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/shopping/items(\?.*)?$'), lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/shopping/runs(\?.*)?$'), lambda r: r.fulfill(json={
            'shop_date': None, 'groups': [], 'runs': {'guess': None, 'scheduled': None, 'next': None},
            'late': [], 'top_up': False, 'counts': {}}))
        page.route(re.compile(r'.*/api/projects(\?.*)?$'), lambda r: r.fulfill(json={'projects': []}))
        page.route('**/api/projects/elsewhere*', lambda r: r.fulfill(json={'situations': []}))
        page.route(re.compile(r'.*/api/programs(\?.*)?$'), lambda r: r.fulfill(json={'programs': []}))
        page.route('**/api/practice-windows*', lambda r: r.fulfill(json={'windows': []}))
        # Findings/insights (fetchMind, kinds=finding,insight): one finding in
        # `now` for the parent; threads (fetchHouseThreads, kinds=thread) none.
        page.route('**/api/situations?*', self.situations)
        page.route('**/api/channels?*', lambda r: r.fulfill(json=channels(key)))
        page.route('**/api/channels/*/messages*', lambda r: r.fulfill(json=[]))
        page.route('**/api/presence/moments*', lambda r: r.fulfill(json=[]))


# --- page helpers ------------------------------------------------------------

def norm(text):
    return ' '.join((text or '').split())


def squash(text):
    return ''.join((text or '').split())


def rgb(hex_color):
    h = hex_color.lstrip('#')
    return 'rgb(%d, %d, %d)' % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def settle(page, condition, timeout=6000, arg=None):
    """Give an async re-render the chance to land; the assertion that follows
    says what was wrong if it never did."""
    try:
        if arg is None:
            page.wait_for_function('() => ' + condition, timeout=timeout)
        else:
            page.wait_for_function(condition, arg=arg, timeout=timeout)
    except Exception:
        pass


def shot(page, name):
    if SHOTS:
        page.mouse.move(0, 0)
        Path(SHOTS, name).write_bytes(page.screenshot())


def no_overflow(page):
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), \
        page.evaluate('[document.documentElement.scrollWidth, innerWidth]')


BRIEF_READY = """() => {
    const c = document.getElementById('myday-content');
    return !!c && !!c.querySelector('.pwa-brief-greet') && !!c.querySelector('.pwa-brief-day')
        && !c.innerText.includes('Loading your day');
}"""


def wait_brief(page):
    try:
        page.wait_for_function(BRIEF_READY, timeout=8000)
    except Exception:
        pass
    assert page.locator('#myday-content .pwa-brief-greet').count() == 1, 'My Day did not draw the brief'


# The rows a pane holds, read the way pwaRowsFromDom reads them plus the
# three datasets Plan adds, then the pure functions over them. `chip` is a
# chip NAME ('Maya'); the filter is applied only for a person's chip.
PLAN_ORACLE = """(arg) => {
    const pane = document.getElementById('pane-' + arg.index);
    const host = pane && pane.querySelector('#pane-events .pwa-plan-rows');
    if (!host) return null;
    const ids = s => String(s || '').split(',').map(x => x.trim()).filter(Boolean);
    const els = [...host.querySelectorAll('[data-kind]')].filter(e => PWA_DAY_KIND_ORDER.includes(e.dataset.kind));
    const rows = pwaRowsFromDom(host).map((r, i) => Object.assign(r, {color: els[i].dataset.color || '',
        cal: ids(els[i].dataset.cal), drivers: ids(els[i].dataset.drivers)}));
    const date = currentDates[arg.index];
    const now = new Date();
    const clock = {use24h: !!use24h};
    const chips = pwaPeopleChips(membersData, scheduleData);
    const chip = arg.chip ? chips.find(c => c.name === arg.chip) : null;
    const shown = chip && chip.id !== 'everyone' ? pwaPlanFilter(rows, chip, chips) : rows;
    const strips = pwaLeaveStrips(scheduleData, date, Object.assign({drivers: scheduleData.drivers || driversData,
        passengers: scheduleData.passengers || [], events: scheduleData.events || [],
        keepingUp: isKeepingUpAdult()}, clock));
    // Strips share the blocks' lane sweep (v2.499.756), so the geometry takes them.
    const geo = pwaPlanGeometry(shown, Object.assign({date, now, hourPx: 66, strips}, clock));
    const mins = v => { const d = new Date(v); return d.getHours() * 60 + d.getMinutes(); };
    const first = geo.hours.length ? geo.hours[0].h : 0;
    return {
        date, chips: chips.map(c => c.name), rowTitles: rows.map(r => r.title),
        hours: geo.hours.map(h => ({h: h.h, label: h.label})),
        blocks: geo.blocks.map(b => ({title: b.row.title, top: b.top, height: b.height, lane: b.lane,
                                      lanes: b.lanes, color: b.color || b.row.color, dim: !!b.dim})),
        allDay: geo.allDay.map(r => r.title),
        now: geo.now ? geo.now.top : null,
        strips: (geo.strips || []).map(s => ({label: s.label, color: s.color, driverId: s.driverId,
                                  top: s.top, height: s.height, lane: s.lane, lanes: s.lanes})),
        lead: pwaPlanLead(rows, strips, date, now),
    };
}"""

# What the pane's timeline actually draws, measured from the first hour row
# (the range start): blocks, leave strips and the now line by their boxes.
PLAN_DOM = """(index) => {
    const pane = document.getElementById('pane-' + index);
    const tl = pane && pane.querySelector('#pane-events .pwa-tl');
    if (!tl) return null;
    const n = s => (s || '').replace(/\\s+/g, ' ').trim();
    const hrs = [...tl.querySelectorAll('.pwa-hr[data-h]')];
    const origin = hrs.length ? hrs[0].getBoundingClientRect() : tl.getBoundingClientRect();
    const box = e => { const r = e.getBoundingClientRect();
        return {top: r.top - origin.top, height: r.height, left: r.left - origin.left, width: r.width}; };
    const label = hr => { const c = hr.cloneNode(true);
        c.querySelectorAll('.pwa-ev, .pwa-leave, .pwa-now').forEach(e => e.remove()); return n(c.textContent); };
    const now = tl.querySelector('.pwa-now');
    return {
        track: {width: origin.width},
        hours: hrs.map(hr => ({h: Number(hr.dataset.h), label: label(hr), height: hr.getBoundingClientRect().height})),
        blocks: [...tl.querySelectorAll('.pwa-ev')].filter(e => e.checkVisibility()).map(e => Object.assign(box(e), {
            aria: e.getAttribute('aria-label') || '', text: n(e.textContent), bg: getComputedStyle(e).backgroundColor,
            dim: e.classList.contains('dim')})),
        leave: [...tl.querySelectorAll('.pwa-leave')].filter(e => e.checkVisibility()).map(e => Object.assign(box(e),
            {text: n(e.textContent)})),
        now: now ? Object.assign(box(now), {text: n(now.textContent)}) : null,
        band: [...pane.querySelectorAll('#pane-events .pwa-plan-allday .pwa-band-item')].filter(e => e.checkVisibility())
            .map(e => ({text: n(e.textContent), tag: e.tagName})),
    };
}"""

# Does this element (or anything inside it) wear the colour? The hex in its
# markup (an inline style or a custom property) or the colour in a computed
# paint property.
WEARS = """([el, hex]) => {
    if (!el) return false;
    if (el.outerHTML.toLowerCase().includes(hex.toLowerCase())) return true;
    const probe = document.createElement('i'); probe.style.color = hex; document.body.append(probe);
    const want = getComputedStyle(probe).color; probe.remove();
    return [el, ...el.querySelectorAll('*')].some(e => { const cs = getComputedStyle(e);
        return ['backgroundColor', 'borderLeftColor', 'borderTopColor', 'color', 'boxShadow', 'backgroundImage',
                'outlineColor'].some(p => String(cs[p] || '').includes(want)); });
}"""

LEAVE_WEARS = """([index, label, hex]) => {
    const squash = s => (s || '').replace(/\\s+/g, '');
    const el = [...document.querySelectorAll('#pane-' + index + ' #pane-events .pwa-tl .pwa-leave')]
        .find(e => squash(e.textContent) === squash(label));
    return (%s)([el, hex]);
}""" % WEARS

CHIP_WEARS = """([name, hex]) => {
    const el = [...document.querySelectorAll('#plan-head .pwa-people .pwa-pp')]
        .find(e => e.textContent.replace(/\\s+/g, ' ').trim() === name);
    return (%s)([el, hex]);
}""" % WEARS

CHIPS_DOM = """() => [...document.querySelectorAll('#plan-head .pwa-people .pwa-pp')].map(e => ({
    text: e.textContent.replace(/\\s+/g, ' ').trim(), on: e.classList.contains('on'),
    pressed: e.getAttribute('aria-pressed'), tag: e.tagName}))"""

WEEK_DOM = """() => [...document.querySelectorAll('#plan-head .pwa-week .pwa-week-day')].map(e => {
    const n = s => (s || '').replace(/\\s+/g, ' ').trim();
    const c = e.cloneNode(true); c.querySelectorAll('b, .w, .cnt, .proposed').forEach(x => x.remove());
    const b = e.querySelector('b'), w = e.querySelector('.w'), cnt = e.querySelector('.cnt');
    return {tag: e.tagName, letter: n(c.textContent), day: n(b && b.textContent), w: n(w && w.textContent),
            cnt: cnt ? n(cnt.textContent) : null, proposed: !!e.querySelector('.proposed'),
            pressed: e.getAttribute('aria-pressed'),
            bBg: b ? getComputedStyle(b).backgroundColor : null, bColor: b ? getComputedStyle(b).color : null};
})"""

WEEK_ORACLE = """(m) => pwaWeekStrip(currentDates, {counts: m.counts, weather: m.weather,
    proposalDates: new Set(m.proposed), today: todayStr(), selected: currentDates[activeDateIndex]})
    .map(d => ({letter: d.letter, day: String(d.day), emoji: d.emoji || '', count: d.count || 0,
                proposed: !!d.proposed, selected: !!d.selected}))"""

# Per pane, the rows the count and the lead count: timed, any kind but drive.
TIMED_COUNTS = """() => currentDates.map((d, i) => { const host = document.querySelector('#pane-' + i + ' #pane-events .pwa-plan-rows');
    return host ? pwaRowsFromDom(host).filter(r => !r.allDay && r.kind !== 'drive').length : 0; })"""

TOKEN_PROBE = """(token) => { const p = document.createElement('div'); p.style.background = 'var(' + token + ')';
    p.style.color = 'var(' + token + ')';
    document.getElementById('plan-head').append(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; }"""


def today_index(page):
    return page.evaluate("currentDates.indexOf(todayStr())")


def open_plan(page):
    """Tap Plan; the Family branch must have built today's rows, and the head
    must exist (the first failure before Task 4: there is no #plan-head)."""
    if page.evaluate('currentView') != 'family':
        page.locator('#tab-family').click()
    page.wait_for_function("currentView === 'family'")
    idx = today_index(page)
    assert idx >= 0, page.evaluate('currentDates')
    page.wait_for_function("(i) => !!document.querySelector('#pane-' + i + ' #pane-events [data-kind]')",
                           arg=idx, timeout=10000)
    settle(page, "!!document.querySelector('#plan-head .pwa-plan-title')", timeout=8000)
    assert page.locator('#plan-head').count() == 1, \
        '#plan-head missing: the adult Plan tab drew no head (title, lead, chips, week strip) above #day-nav'
    assert page.locator('#plan-head .pwa-plan-title').count() == 1, '#plan-head has no .pwa-plan-title'
    settle(page, "(i) => !!document.querySelector('#pane-' + i + ' #pane-events .pwa-tl .pwa-ev')", arg=idx,
           timeout=8000)
    return idx


def oracle(page, index, chip=None):
    want = page.evaluate(PLAN_ORACLE, {'index': index, 'chip': chip})
    assert want is not None, f'#pane-{index} #pane-events has no .pwa-plan-rows (the row list must stay in the pane)'
    return want


def plan_dom(page, index):
    dom = page.evaluate(PLAN_DOM, index)
    assert dom is not None, f'#pane-{index} #pane-events has no .pwa-tl timeline'
    return dom


def block_for(dom, title):
    hits = [b for b in dom['blocks'] if b['aria'].startswith(title)]
    assert len(hits) == 1, (title, [b['aria'] for b in dom['blocks']])
    return hits[0]


def assert_timeline(page, index, chip=None, where=''):
    """The pane's timeline, whole, against pwaPlanGeometry over its own rows."""
    want = oracle(page, index, chip)
    settle(page, "(m) => { const d = (%s)(m.index); return !!d && d.blocks.length === m.n; }" % PLAN_DOM,
           arg={'index': index, 'n': len(want['blocks'])})
    dom = plan_dom(page, index)
    assert [h['h'] for h in dom['hours']] == [h['h'] for h in want['hours']], \
        (where, [h['h'] for h in dom['hours']], [h['h'] for h in want['hours']])
    assert [h['label'] for h in dom['hours']] == [norm(h['label']) for h in want['hours']], \
        (where, [h['label'] for h in dom['hours']], want['hours'])
    for h in dom['hours']:
        assert abs(h['height'] - 66) <= 0.5, (where, 'a .pwa-hr is not 66px tall', h)
    titles = sorted(b['aria'] for b in dom['blocks'])
    assert len(dom['blocks']) == len(want['blocks']), (where, titles, [w['title'] for w in want['blocks']])
    track = dom['track']['width']
    for w in want['blocks']:
        b = block_for(dom, w['title'])
        assert w['title'] in b['text'], (where, w['title'], b['text'])
        assert abs(b['top'] - w['top']) <= 1.5, (where, w['title'], 'top', b['top'], w['top'])
        assert abs(b['height'] - w['height']) <= 1.5, (where, w['title'], 'height', b['height'], w['height'])
        lane = track / w['lanes']
        assert abs(b['left'] - w['lane'] * lane) <= 10, (where, w['title'], 'left', b['left'], w['lane'], w['lanes'])
        assert abs(b['width'] - lane) <= 10, (where, w['title'], 'width', b['width'], lane)
        assert b['dim'] == w['dim'], (where, w['title'], 'dim', b['dim'], w['dim'])
        if not w['dim']:
            assert b['bg'] == rgb(w['color']), (where, w['title'], b['bg'], w['color'])
    band = [x['text'] for x in dom['band']]
    assert len(band) == len(want['allDay']), (where, band, want['allDay'])
    for title in want['allDay']:
        assert any(title in t for t in band), (where, title, band)
    return want, dom


def assert_leave(page, index, want, dom, where=''):
    assert len(dom['leave']) == len(want['strips']), (where, [l['text'] for l in dom['leave']], want['strips'])
    for s in want['strips']:
        hits = [l for l in dom['leave'] if squash(l['text']) == squash(s['label'])]
        assert len(hits) == 1, (where, s['label'], [l['text'] for l in dom['leave']])
        strip = hits[0]
        assert abs(strip['top'] - s['top']) <= 1.5, (where, s['label'], 'top', strip['top'], s['top'])
        assert abs(strip['height'] - 22) <= 1, (where, s['label'], 'height', strip['height'])
        assert page.evaluate(LEAVE_WEARS, [index, s['label'], s['color']]), \
            (where, s['label'], 'the strip does not wear its driver colour', s['color'])


def head_lead(page):
    return norm(page.locator('#plan-head .pwa-plan-lead').text_content())


def wait_lead(page, index):
    settle(page, """(i) => { const e = document.querySelector('#plan-head .pwa-plan-lead'); if (!e) return false;
        const o = (%s)({index: i}); return !!o && e.textContent.replace(/\\s+/g, ' ').trim() === o.lead.replace(/\\s+/g, ' ').trim(); }"""
           % PLAN_ORACLE, arg=index)


def pressed_days(page):
    return [d['pressed'] for d in page.evaluate(WEEK_DOM)]


def expect_pressed(page, index):
    settle(page, "(i) => [...document.querySelectorAll('#plan-head .pwa-week .pwa-week-day')]"
                 ".map(e => e.getAttribute('aria-pressed')).indexOf('true') === i", arg=index)
    pressed = pressed_days(page)
    assert pressed == ['true' if i == index else 'false' for i in range(len(pressed))], (index, pressed)


def open_sheet(page):
    page.wait_for_selector('.pwa-prompt-overlay', state='visible')
    return page.locator('.pwa-prompt-overlay').last


def close_sheet(page):
    page.locator('.pwa-prompt-overlay').last.locator('[data-close]').click()
    page.wait_for_function("document.querySelectorAll('.pwa-prompt-overlay').length === 0")


# --- scenarios ----------------------------------------------------------------

def plan_head(page, mocks):
    idx = open_plan(page)
    head = page.locator('#plan-head')
    assert page.evaluate("""() => { const h = document.getElementById('plan-head'), n = document.getElementById('day-nav');
        return !!h && !!n && !!(h.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING)
            && !!h.closest('#screen-schedule'); }"""), '#plan-head must sit in #screen-schedule before #day-nav'
    title = head.locator('.pwa-plan-title')
    assert title.evaluate('e => e.tagName') == 'H1', title.evaluate('e => e.tagName')
    assert norm(title.text_content()) == 'Plan', norm(title.text_content())
    assert head.locator('.pwa-plan-today').count() == 0, 'Today shows while today is selected'
    assert title.evaluate('e => getComputedStyle(e).fontSize') == '34px'
    assert title.evaluate('e => getComputedStyle(e).fontWeight') == '700'
    # The lead: Argyle's one line for the selected day, from the pane's rows.
    wait_lead(page, idx)
    want = oracle(page, idx)
    assert head.locator('.pwa-plan-lead').count() == 1, '.pwa-plan-lead missing'
    assert head_lead(page) == norm(want['lead']), (head_lead(page), want['lead'])
    if mocks.key == 'parent':
        # test_pwa_plan.py's ruling: sessions count as events, so the practice
        # window makes five (1:1, practice, soccer, piano, dinner).
        assert head_lead(page) == 'Today is two drives and five events.', head_lead(page)
    # People chips: Everyone first, then the household's first names.
    chips = page.evaluate(CHIPS_DOM)
    assert [c['text'] for c in chips] == want['chips'], ([c['text'] for c in chips], want['chips'])
    assert [c['text'] for c in chips] == CHIPS, [c['text'] for c in chips]
    assert all(c['tag'] == 'BUTTON' for c in chips), chips
    assert chips[0]['on'] and chips[0]['pressed'] == 'true', chips[0]
    assert all(not c['on'] and c['pressed'] == 'false' for c in chips[1:]), chips
    for member in MEMBERS:
        name = member['name'].split()[0]
        assert page.evaluate(CHIP_WEARS, [name, member['color_code']]), (name, 'chip has no colour dot', member['color_code'])
    # The week strip: seven days from the pane dates, today selected.
    if mocks.weather:
        settle(page, "[...document.querySelectorAll('#plan-head .pwa-week .pwa-week-day .w')].filter(e => e.textContent.trim()).length === 7",
               timeout=8000)
    if mocks.proposals:
        settle(page, "!!document.querySelector('#plan-head .pwa-week .pwa-week-day .proposed')", timeout=8000)
    week = page.evaluate(WEEK_DOM)
    dates = page.evaluate('currentDates')
    assert len(week) == 7 and len(dates) == 7, (len(week), dates)
    assert all(d['tag'] == 'BUTTON' for d in week), week
    for i, d in enumerate(week):
        day = datetime.strptime(dates[i], '%Y-%m-%d')
        assert d['letter'] == day.strftime('%a')[0], (i, d['letter'])
        assert d['day'] == str(day.day), (i, d['day'])
    assert [d['pressed'] for d in week] == ['true'] + ['false'] * 6, [d['pressed'] for d in week]
    accent = page.evaluate(TOKEN_PROBE, '--pwa-accent')
    assert week[0]['bBg'] == accent, ('the selected day is not filled with the accent', week[0]['bBg'], accent)
    assert week[0]['bColor'] == 'rgb(255, 255, 255)', week[0]['bColor']
    # The count is the lead's event count for that day: timed rows of any kind
    # but drive in the pane's .pwa-plan-rows (the all-day trip never counts).
    counts = {DAY: 5, TOMORROW: 2}
    assert [d['cnt'] or None for d in week] == ['5', '2'] + [None] * 5, [d['cnt'] for d in week]
    assert page.evaluate(TIMED_COUNTS) == [5, 2, 0, 0, 0, 0, 0], page.evaluate(TIMED_COUNTS)
    if mocks.weather:
        assert [d['w'] for d in week] == WEATHER_EMOJI, [d['w'] for d in week]
    else:
        assert all(not d['w'] for d in week), [d['w'] for d in week]
    assert [d['proposed'] for d in week] == ([False, True] + [False] * 5 if mocks.proposals else [False] * 7), \
        [d['proposed'] for d in week]
    words = page.evaluate(WEEK_ORACLE, {'counts': counts, 'proposed': mocks.proposal_dates(),
                                        'weather': weather_rows(dates[0], 7) if mocks.weather else []})
    for i, (d, w) in enumerate(zip(week, words)):
        assert d['letter'] == w['letter'] and d['day'] == w['day'], (i, d, w)
        assert d['w'] == w['emoji'], (i, d['w'], w['emoji'])
        assert (d['cnt'] or '') == (str(w['count']) if w['count'] else ''), (i, d['cnt'], w['count'])
        assert d['proposed'] == w['proposed'] and (d['pressed'] == 'true') == w['selected'], (i, d, w)
    # The old heading and date strip give way to the head.
    assert not page.locator('#pwa-page-heading').is_visible(), '#pwa-page-heading still shows on Plan'
    assert not page.locator('#pwa-date-strip').is_visible(), '#pwa-date-strip still shows on Plan'
    shot(page, 'plan-light.png')


def timeline_blocks(page, mocks):
    idx = open_plan(page)
    events = page.locator(f'#pane-{idx} #pane-events')
    assert events.locator('.pwa-plan-allday').count() == 1, '.pwa-plan-allday missing'
    want, dom = assert_timeline(page, idx, where='today')
    # The fixture's own numbers: 8 AM to 8 PM, five blocks, the trip banded.
    labels = [h['label'] for h in dom['hours']]
    assert labels[0] == '8 AM' and labels[-1] == '8 PM', labels
    assert {w['title'] for w in want['blocks']} == TODAY_TIMED, [w['title'] for w in want['blocks']]
    assert want['allDay'] == [TRIP], want['allDay']
    for w in want['blocks']:
        assert w['color'].lower() == BLOCK_COLORS[w['title']].lower(), (w['title'], w['color'])
    by = {w['title']: w for w in want['blocks']}
    assert by[SOCCER]['lanes'] == 2 and by[PIANO]['lanes'] == 2, (by[SOCCER], by[PIANO])
    assert by[SOCCER]['lane'] != by[PIANO]['lane'], (by[SOCCER], by[PIANO])
    soccer, piano = block_for(dom, SOCCER), block_for(dom, PIANO)
    left, right = sorted([soccer, piano], key=lambda b: b['left'])
    assert left['left'] + left['width'] <= right['left'] + 1, ('soccer and piano overlap', soccer, piano)
    assert '4:00' in soccer['aria'], soccer['aria']
    # Past at 15:12: the morning 1:1 is dimmed, never dropped.
    assert block_for(dom, ONE_ON_ONE)['dim'] and by[ONE_ON_ONE]['dim'], block_for(dom, ONE_ON_ONE)
    for title in TODAY_TIMED - {ONE_ON_ONE}:
        assert not block_for(dom, title)['dim'], (title, 'dimmed but not past')
    # The now line, at the 3 PM hour.
    assert dom['now'] is not None, '.pwa-now missing on today'
    assert want['now'] is not None and abs(dom['now']['top'] - want['now']) <= 3, (dom['now'], want['now'])
    hour = {h['h']: i for i, h in enumerate(dom['hours'])}
    assert 15 in hour and hour[15] * 66 <= dom['now']['top'] < (hour[15] + 1) * 66, (dom['now'], dom['hours'])
    assert '3:12' in dom['now']['text'], dom['now']['text']
    # The row list stays in the pane, hidden: the dataset contract and every
    # handler live there.
    rows = events.locator('.pwa-plan-rows')
    assert rows.count() == 1 and rows.get_attribute('hidden') is not None, 'the row list is not hidden in .pwa-plan-rows[hidden]'
    assert events.locator('.pwa-plan-rows[hidden] .pwa-agenda-row').count() >= 6, \
        events.locator('.pwa-plan-rows[hidden] .pwa-agenda-row').count()
    assert not rows.is_visible()
    soccer_row = events.locator('.pwa-plan-rows [data-kind="event"][data-title="%s"]' % SOCCER)
    assert soccer_row.count() == 1, 'the soccer row is missing from .pwa-plan-rows'
    assert soccer_row.get_attribute('data-color').lower() == '#e07a5f', soccer_row.get_attribute('data-color')
    assert soccer_row.get_attribute('data-cal') == 'cal_maya', soccer_row.get_attribute('data-cal')
    assert soccer_row.get_attribute('data-drivers') == 'd1', soccer_row.get_attribute('data-drivers')
    assert 'Alex Morgan' in soccer_row.text_content(), 'the driver row lost its driver chip'
    # Leave strips: the solver's stamped legs, the driver's colour.
    assert_leave(page, idx, want, dom, 'today')
    # A leave strip never covers a block: Robin leaves at 4:05 while soccer
    # (4:00-5:00) is on, so the strip takes a lane beside the blocks it
    # overlaps in time instead of drawing over the soccer title.
    hits = page.evaluate("""(i) => {
        const pane = document.getElementById('pane-' + i);
        const r = el => el.getBoundingClientRect();
        const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
        const out = [];
        pane.querySelectorAll('.pwa-leave').forEach(s => pane.querySelectorAll('.pwa-ev').forEach(b => {
            if (hit(r(s), r(b))) out.push([s.textContent.trim(), b.textContent.trim()]); }));
        return out; }""", idx)
    assert hits == [], ('a leave strip draws over a block', hits)
    labels = [squash(s['label']) for s in want['strips']]
    assert any(squash('Leave 3:40 · Alex drives Maya') in l for l in labels), want['strips']
    assert any(squash('Leave 4:05 · Robin drives Sam') in l for l in labels), want['strips']
    colors = sorted(s['color'].lower() for s in want['strips'])
    assert colors == ['#2f6fde', '#c2410c'], colors
    # Taps run each row's own handler.
    tl = events.locator('.pwa-tl')
    tl.locator(f'.pwa-ev[aria-label^="{SOCCER}"]').click()
    page.wait_for_selector('#event-modal', state='visible')
    assert norm(page.locator('#em-title').text_content()) == SOCCER, page.locator('#em-title').text_content()
    page.evaluate('closeEventModal()')
    page.wait_for_selector('#event-modal', state='hidden')
    practice = tl.locator(f'.pwa-ev[aria-label^="{PRACTICE}"]')
    pbox = practice.bounding_box()
    practice.click(position={'x': pbox['width'] / 2, 'y': max(4, pbox['height'] - 6)})
    sheet = open_sheet(page)
    text = norm(sheet.inner_text())
    assert PRACTICE in text and 'Push and core' in text, text
    close_sheet(page)
    events.locator('.pwa-plan-allday .pwa-band-item').filter(has_text=TRIP).first.click()
    sheet = open_sheet(page)
    text = norm(sheet.inner_text())
    assert 'trip' in text.lower() and TRIP in text, text  # the trip sheet labels it 'TRIP'
    close_sheet(page)


def people_filter(page, mocks):
    idx = open_plan(page)
    lead = head_lead(page)
    full = oracle(page, idx)
    chip = page.locator('#plan-head .pwa-people .pwa-pp').filter(has_text='Maya').first
    chip.click()
    settle(page, """() => { const c = [...document.querySelectorAll('#plan-head .pwa-people .pwa-pp')]
        .find(e => e.textContent.trim() === 'Maya'); return !!c && c.getAttribute('aria-pressed') === 'true'; }""")
    chips = {c['text']: c for c in page.evaluate(CHIPS_DOM)}
    assert chips['Maya']['on'] and chips['Maya']['pressed'] == 'true', chips['Maya']
    assert not chips['Everyone']['on'] and chips['Everyone']['pressed'] == 'false', chips['Everyone']
    want, dom = assert_timeline(page, idx, chip='Maya', where='chip Maya')
    shown = {w['title'] for w in want['blocks']}
    # Maya's soccer stays; the practice window has no calendar and no driver,
    # and the Family calendar's dinner is claimed by no chip -- both are
    # unresolved, so never hidden; Sam's piano and Alex's 1:1 go.
    assert shown == {SOCCER, PRACTICE, DINNER}, shown
    for title in (PIANO, ONE_ON_ONE):
        assert not any(b['aria'].startswith(title) for b in dom['blocks']), (title, [b['aria'] for b in dom['blocks']])
    assert any(TRIP in x['text'] for x in dom['band']), dom['band']
    assert head_lead(page) == lead, ('the lead follows the filter; it must count everyone', head_lead(page), lead)
    page.locator('#plan-head .pwa-people .pwa-pp').filter(has_text='Everyone').first.click()
    settle(page, """() => { const c = document.querySelector('#plan-head .pwa-people .pwa-pp');
        return !!c && c.getAttribute('aria-pressed') === 'true'; }""")
    want, dom = assert_timeline(page, idx, where='chip Everyone')
    assert len(dom['blocks']) == len(full['blocks']), (len(dom['blocks']), len(full['blocks']))
    chips = page.evaluate(CHIPS_DOM)
    assert chips[0]['on'] and all(not c['on'] for c in chips[1:]), chips


def swipe_next(page):
    """Page to the next day the way a swipe does: a touch on the strip, then
    the strip scrolls one pane. Headless Chromium does not drive a
    scroll-snap container from a CDP synthesized touch gesture (measured
    2026-11-04: neither the gesture nor a wheel reached the next pane, with
    no element cancelling touch), so the scroll is applied directly; what
    the app owns -- the onscroll handler mapping scrollLeft to the active
    day, the head and the strip following it -- is what this exercises.
    The native swipe itself is a device check."""
    page.evaluate("""() => {
        const c = document.getElementById('days-container');
        c.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
        c.scrollTo({left: (activeDateIndex + 1) * c.clientWidth, behavior: 'instant'});
        c.dispatchEvent(new Event('scroll'));
    }""")


def week_and_arrows(page, mocks):
    idx = open_plan(page)
    days = page.locator('#plan-head .pwa-week .pwa-week-day')
    days.nth(idx + 1).click()
    page.wait_for_function('(i) => activeDateIndex === i', arg=idx + 1)
    expect_pressed(page, idx + 1)
    settle(page, "!!document.querySelector('#plan-head .pwa-plan-today')")
    today = page.locator('#plan-head .pwa-plan-today')
    assert today.count() == 1 and today.is_visible(), 'Today does not show on another day'
    assert norm(today.text_content()) == 'Today', today.text_content()
    assert today.evaluate('e => e.tagName') == 'BUTTON'
    assert norm(page.locator('#plan-head .pwa-plan-title').text_content()) == 'Plan Today', \
        page.locator('#plan-head .pwa-plan-title').text_content()
    want, dom = assert_timeline(page, idx + 1, where='tomorrow')
    assert sorted(w['title'] for w in want['blocks']) == sorted([SWIM, LIBRARY]), want['blocks']
    assert len(dom['blocks']) == 2, dom['blocks']
    assert dom['now'] is None, 'the now line draws on another day'
    assert_leave(page, idx + 1, want, dom, 'tomorrow')
    assert [squash(s['label']) for s in want['strips']] and \
        squash('Leave 1:40 · Alex drives Sam') in squash(want['strips'][0]['label']), want['strips']
    wait_lead(page, idx + 1)
    assert head_lead(page) == norm(want['lead']), (head_lead(page), want['lead'])
    # The arrows still page the days.
    page.locator('#btn-prev-day').click()
    page.wait_for_function('(i) => activeDateIndex === i', arg=idx)
    expect_pressed(page, idx)
    settle(page, "!document.querySelector('#plan-head .pwa-plan-today')")
    assert page.locator('#plan-head .pwa-plan-today').count() == 0, 'Today stays on today'
    # And so does a swipe.
    swipe_next(page)
    page.wait_for_function('(i) => activeDateIndex === i', arg=idx + 1, timeout=8000)
    expect_pressed(page, idx + 1)
    # Today resets.
    settle(page, "!!document.querySelector('#plan-head .pwa-plan-today')")
    page.locator('#plan-head .pwa-plan-today').click()
    page.wait_for_function('(i) => activeDateIndex === i', arg=idx)
    expect_pressed(page, idx)
    settle(page, "!document.querySelector('#plan-head .pwa-plan-today')")
    assert page.locator('#plan-head .pwa-plan-today').count() == 0
    # The day after tomorrow is empty: no blocks, no count.
    week = page.evaluate(WEEK_DOM)
    assert not week[idx + 2]['cnt'], week[idx + 2]
    empty = page.evaluate(PLAN_ORACLE, {'index': idx + 2, 'chip': None})
    assert empty is None or not empty['blocks'], empty


def needs_you_and_intake_above(page, mocks):
    idx = open_plan(page)
    order = """(i) => { const pane = document.getElementById('pane-' + i); const ev = pane && pane.querySelector('#pane-events');
        if (!ev) return null; return ['proposals-container', 'mind-container'].map(id => { const el = pane.querySelector('#' + id);
            return !!el && !!(el.compareDocumentPosition(ev) & Node.DOCUMENT_POSITION_FOLLOWING); }); }"""
    settle(page, "(i) => { const o = (%s)(i); return !!o && o.every(Boolean); }" % order, arg=idx, timeout=8000)
    assert page.evaluate(order, idx) == [True, True], \
        ('intake and Needs you must sit above the timeline', page.evaluate(order, idx))
    settle(page, "(i) => !!document.querySelector('#pane-' + i + ' #mind-container .situation-card')", arg=idx, timeout=8000)
    pane = page.locator(f'#pane-{idx}')
    card = pane.locator('#mind-container .situation-card').first
    assert card.count() == 1 and card.is_visible(), 'the finding card is not drawn in #mind-container'
    assert FINDING_LINE in norm(card.locator('.sit-title').first.text_content()), card.inner_text()
    settle(page, "(i) => (document.querySelector('#pane-' + i + ' #proposals-content') || {}).textContent?.includes('%s')"
           % PROPOSAL_TITLE, arg=idx, timeout=8000)
    intake = pane.locator('#proposals-content')
    assert intake.is_visible() and PROPOSAL_TITLE in intake.inner_text(), 'the proposal row is not on Plan'
    assert intake.get_by_role('button', name='📸 Snap a flyer').is_visible(), 'Snap a flyer is gone'
    assert page.locator('#house-threads').count() == 1, page.locator('#house-threads').count()


def plan_myday_round_trip(page, mocks):
    idx = open_plan(page)
    before = oracle(page, idx)
    page.locator('#tab-myday').click()
    page.wait_for_function("currentView === 'myday'")
    wait_brief(page)
    assert page.locator('#myday-content .pwa-brief-day').count() == 1
    assert page.locator('#myday-content .pwa-hero').count() == 1, 'the brief lost its hero after Plan'
    page.locator('#tab-family').click()
    page.wait_for_function("currentView === 'family'")
    settle(page, "(m) => { const d = (%s)(m.i); return !!d && d.blocks.length === m.n; }" % PLAN_DOM,
           arg={'i': idx, 'n': len(before['blocks'])}, timeout=8000)
    want, dom = assert_timeline(page, idx, where='back from My Day')
    assert len(dom['blocks']) == len(before['blocks']), (len(dom['blocks']), len(before['blocks']))
    assert page.locator('#house-threads').count() == 1, page.locator('#house-threads').count()
    assert page.evaluate("(i) => document.querySelectorAll('#pane-' + i).length", idx) == 1, 'two panes share an id'
    assert page.locator(f'#pane-{idx} #pane-events .pwa-plan-rows[hidden]').count() == 1
    assert page.locator('#myday-content [data-pwa-brief-pane]').count() == 0, 'the brief pane stayed adopted on Plan'
    page.locator('#tab-myday').click()
    wait_brief(page)
    assert page.locator('#myday-content .pwa-hero').count() == 1, 'the brief did not survive the round trip'
    open_plan(page)


def widths_and_dark(page, mocks):
    idx = open_plan(page)
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        page.wait_for_function('(w) => innerWidth === w', arg=width)
        no_overflow(page)
        assert page.locator('#plan-head').evaluate('e => e.scrollWidth <= e.clientWidth'), \
            page.locator('#plan-head').evaluate('e => [e.scrollWidth, e.clientWidth]')
        tl = page.locator(f'#pane-{idx} #pane-events .pwa-tl')
        assert tl.evaluate('e => e.scrollWidth <= e.clientWidth'), tl.evaluate('e => [e.scrollWidth, e.clientWidth]')
        assert_timeline(page, idx, where=f'width {width}')
        if width == 360:
            shot(page, 'plan-360.png')
    title = page.locator('#plan-head .pwa-plan-title')
    assert title.evaluate('e => getComputedStyle(e).fontSize') == '34px'
    light_ink = page.evaluate(TOKEN_PROBE, '--pwa-ink')
    assert title.evaluate('e => getComputedStyle(e).color') == light_ink, (title.evaluate('e => getComputedStyle(e).color'), light_ink)
    page.evaluate("applyTheme('dark')")
    dark_ink = page.evaluate(TOKEN_PROBE, '--pwa-ink')
    assert dark_ink != light_ink, 'the ink token did not change for dark'
    assert title.evaluate('e => getComputedStyle(e).color') == dark_ink, (title.evaluate('e => getComputedStyle(e).color'), dark_ink)
    no_overflow(page)
    shot(page, 'plan-dark.png')
    page.evaluate("applyTheme('light')")
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    running = page.evaluate("""() => document.getElementById('plan-head')
        .getAnimations({subtree: true}).filter(a => a.playState === 'running').length""")
    assert running == 0, running


def clock_24h(page, mocks):
    """time_format_24h on: every hour label, the leave strip, the now line,
    My Day's hero and a Messages time read 15:40, never 3:40 PM."""
    mocks.use24h = True
    page.reload(wait_until='domcontentloaded')
    wait_app(page)
    assert page.evaluate('use24h') is True, 'GET api/settings time_format_24h was not read'
    idx = open_plan(page)
    want, dom = assert_timeline(page, idx, where='24h')
    labels = {h['h']: h['label'] for h in dom['hours']}
    assert labels.get(8) == '08:00' and labels.get(16) == '16:00' and labels.get(20) == '20:00', labels
    assert not any('AM' in l or 'PM' in l for l in labels.values()), labels
    assert_leave(page, idx, want, dom, '24h')
    texts = [l['text'] for l in dom['leave']]
    assert any('Leave 15:40' in t for t in texts) and any('Leave 16:05' in t for t in texts), texts
    assert dom['now'] and '15:12' in dom['now']['text'], dom['now']
    assert '16:00' in block_for(dom, SOCCER)['aria'], block_for(dom, SOCCER)['aria']
    page.locator('#tab-myday').click()
    wait_brief(page)
    settle(page, "!!document.querySelector('#myday-content .pwa-hero h2')")
    hero = norm(page.locator('#myday-content .pwa-hero h2').text_content())
    assert hero == 'Leave at 15:40', hero
    page.locator('#tab-messages').click()
    page.wait_for_function("currentView === 'messages'")
    settle(page, "!!document.querySelector('#channel-list > button.pwa-conv[data-channel=\"family\"] .pwa-conv-time')",
           timeout=8000)
    time_label = norm(page.locator('#channel-list > button.pwa-conv[data-channel="family"] .pwa-conv-time').text_content())
    assert time_label == '14:40', time_label
    mocks.use24h = False


def no_weather(page, mocks):
    """GET /api/weather/daily answers [] (no HA): no glyphs, nothing broken."""
    try:
        with page.expect_request(lambda r: '/api/weather/daily' in r.url, timeout=8000):
            page.locator('#tab-family').click()
    except Exception:
        pass   # asked earlier, or never: the assertion below says which
    idx = open_plan(page)
    assert mocks.weather_calls, 'Plan never asked GET api/weather/daily'
    assert '/api/weather/daily' in mocks.weather_calls[-1]
    q = parse_qs(urlparse(mocks.weather_calls[-1]).query)
    assert q.get('days') == ['7'], q
    week = page.evaluate(WEEK_DOM)
    assert len(week) == 7, week
    assert all(not d['w'] for d in week), [d['w'] for d in week]
    assert [d['cnt'] or None for d in week] == ['5', '2'] + [None] * 5, [d['cnt'] for d in week]
    wait_lead(page, idx)
    assert head_lead(page) == norm(oracle(page, idx)['lead']), head_lead(page)
    want, dom = assert_timeline(page, idx, where='adult')
    assert_leave(page, idx, want, dom, 'adult')


def keeping_up_plan(page, mocks):
    idx = open_plan(page)
    want, dom = assert_timeline(page, idx, where='keeping up')
    assert {w['title'] for w in want['blocks']} == TODAY_TIMED, [w['title'] for w in want['blocks']]
    assert any(TRIP in x['text'] for x in dom['band']), dom['band']
    assert want['strips'] == [], want['strips']
    assert page.locator('.pwa-leave').count() == 0, 'a keeping-up adult got leave strips'
    text = page.locator(f'#pane-{idx} #pane-events').text_content()
    assert 'needs driver' not in text.lower(), 'a keeping-up adult reads Needs Driver'
    assert 'conflict' not in text.lower(), 'a keeping-up adult reads Conflict'
    for name in ('Alex Morgan', 'Robin Lee'):
        assert name not in text, (name, 'a driver chip reached a keeping-up adult')
    wait_lead(page, idx)
    assert head_lead(page) == norm(want['lead']), (head_lead(page), want['lead'])
    assert 'drive' not in head_lead(page).lower(), head_lead(page)


def kid_unchanged(page, mocks):
    page.wait_for_selector('.child-greeting')
    assert not page.locator('#tab-family').is_visible(), 'a kid has the adult Plan tab'
    assert not page.locator('#plan-head').is_visible(), '#plan-head shows for a kid'
    page.locator('#tab-kidplan').click()
    page.wait_for_selector('.child-dates')
    assert page.locator('.child-dates button').count() == 14, page.locator('.child-dates button').count()
    assert not page.locator('#plan-head').is_visible(), '#plan-head shows on the kid plan'
    assert page.locator('.pwa-tl').count() == 0, 'a kid got the adult timeline'
    assert page.locator('.pwa-plan-title:visible').count() == 0
    page.locator('#tab-myday').click()
    page.wait_for_function('pwaChildDay.offset === 0 && !pwaChildPlan')


# --- the run -----------------------------------------------------------------

def wait_app(page):
    page.wait_for_function("""() => !!document.querySelector('#screen-schedule:not(.hidden)')
        || !!document.getElementById('pin-modal-skip')?.checkVisibility()""", timeout=20000)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function("typeof membersData !== 'undefined' && membersData.length > 0")


def boot(served, page, key, role, driver):
    failed_assets = []
    page.on('requestfailed', lambda request: failed_assets.append(
        (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
    page.on('response', lambda response: failed_assets.append(
        (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
        and response.status >= 400 else None)
    # Every 4xx/5xx with its URL, so an unmocked route names itself.
    page.on('response', lambda response: BAD_RESPONSES.append(
        (key, response.status, response.url.split('?')[0])) if response.status >= 400 else None)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.clock.set_fixed_time(NOW)

    def static_asset(route):
        if route.request.resource_type in ('script', 'stylesheet'):
            route.fulfill(response=route.fetch(max_retries=2))
        else:
            route.continue_()
    page.route('**/static/**', static_asset)
    token = storage.create_member_token(key)
    values = {'chauffeur_member_id': key, 'chauffeur_member_token': token,
              'chauffeur_member_token_for': key, 'chauffeur_view': 'myday', 'chauffeur_theme': 'light'}
    if driver:
        values['chauffeur_driver_id'] = driver
    # Once per tab: clock_24h's reload must keep the stored sign-in.
    page.add_init_script("if (!sessionStorage.getItem('chf_test_seeded')) { Object.entries(" + json.dumps(values)
                         + ").forEach(([k, v]) => localStorage.setItem(k, v)); sessionStorage.setItem('chf_test_seeded', '1'); }")
    mocks = Mocks(key, driver)
    mocks.install(page)
    if role == 'child':
        # Registered last, so the child's own day and routines win.
        from pwa_child_checks import install_child_data
        install_child_data(page, key, DAY)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    wait_app(page)
    assert page.evaluate('selectedMemberId') == key
    assert page.evaluate('currentMemberRole()') == role
    if role in ('parent', 'adult'):
        wait_brief(page)
    return mocks, failed_assets


def page_errors(served, key):
    errors = list(served.errors())
    if errors:
        errors = errors + [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key]
    return errors


SCENARIOS = {
    'parent': [plan_head, timeline_blocks, people_filter, week_and_arrows, needs_you_and_intake_above,
               plan_myday_round_trip, widths_and_dark, clock_24h],
    'adult': [no_weather],
    'keeping': [keeping_up_plan],
    'navigator': [kid_unchanged],
}


def run():
    global SHOTS
    # Failure lines quote strip labels (🚗); a cp1252 console must not turn a
    # red test into an encoding traceback.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='backslashreplace')
        except Exception:
            pass
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    import main

    @asynccontextmanager
    async def isolated_lifespan(app):
        yield
    main.app.router.lifespan_context = isolated_lifespan
    served = live_app(seed)
    if served is None:
        return
    output = os.environ.get('PWA_REVIEW_OUTPUT')
    if output:
        SHOTS = (Path(__file__).resolve().parent / 'probe_shots' / 'pwa_slice5'
                 if output.lower() in ('1', 'true', 'yes', 'on') else Path(output))
        SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        for key, role, driver in PROFILES:
            if os.environ.get('PWA_REVIEW_PROFILE') and key != os.environ['PWA_REVIEW_PROFILE']:
                continue
            with served.browser(reduced_motion='reduce', has_touch=True) as page:
                mocks, failed_assets = boot(served, page, key, role, driver)
                for scenario in SCENARIOS[key]:
                    try:
                        scenario(page, mocks)
                    except Exception:
                        bad = sorted({f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key})
                        print('FAIL', key, scenario.__name__, '| page errors:', list(served.errors())[:5],
                              '| 4xx/5xx:', bad[:8], flush=True)
                        raise
                    print('  ok', key, scenario.__name__, flush=True)
                errors = page_errors(served, key)
                assert not errors and not failed_assets, (key, errors, failed_assets)
                print('ok', key, flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    run()
