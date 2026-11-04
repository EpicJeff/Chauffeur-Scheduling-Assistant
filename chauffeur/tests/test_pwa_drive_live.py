"""The drive as a pushed screen, in two moments, in the served PWA (slice 6, Task 2).

For an adult, openActionSheet(...) pushes PwaNav.push({id: 'drive'}) and
ADOPTS #action-sheet-content into `#pwa-stack .pwa-screen[data-screen="drive"]`
(every id and handler kept). Before: the leave-at card (#drive-leave-card,
.pwa-drive-time huge), the stops (.pwa-drive-stops), "Everybody in?" and
"Packed?" chips, Start drive, Ask someone to cover (#btn-drive-cover), the
retro-split options, Mark as completed. On the road: the arrival card
(#drive-arrival-card), Google / Apple / Waze, "Tell <audience>" lines, Send my
ETA, Arrived (#btn-arrived, the one green). Packing joins My Day's pile, the
passenger's ride hero carries the ride row's own buttons, and the adult header
shrinks to the date line (#pwa-header-date), the bell and the avatar. Kids keep
the bottom sheet and their header.

Written before the views exist (Tasks 3-4 make it green), so its first failure
is the parent's hero Start drive NOT landing on a pushed drive screen
(`before_moment`).

Every read the drive makes is mocked with page.route (members, drivers,
passengers and auth are seeded and served for real); every write goes through
a recorder and its path and body are asserted. GET /api/drive_sheet/{leg}
answers the shape of services/drive_sheet.py sheet(), and the mocks are
stateful: Start puts the leg in `in_progress_drives`, the roll call and the
packing claim ride back in the next sheet / schedule read, Arrived (resolved)
or "I've arrived" completes it. The words on the cards are checked against
pwaDriveView(driveSheetData, ctx) evaluated IN THE PAGE (ctx built from
routeContext and the drive row's dataset) and against literal values the
fixture must produce. Geolocation is granted at a fixed position; the no-fix
path is covered once. The maps hand-off is captured by intercepting the
synthetic anchor click (openMaps).

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_drive_live.py
PWA_REVIEW_PROFILE=<key> runs one profile; PWA_REVIEW_SCENARIO=<name>[,<name>]
runs only those scenarios; PWA_KEEP_GOING=1 reports every failing scenario
instead of stopping at the first. PWA_REVIEW_OUTPUT=1 writes the screenshots to
tests/probe_shots/pwa_slice6 (gitignored); any other value is the directory.
"""
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
DATA = tempfile.mkdtemp(prefix='chauffeur_drive_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
NOW_ROAD = NOW.replace(hour=15, minute=42)      # two minutes after the solver's departure
NOW_RIDE = NOW.replace(hour=17, minute=35)      # the parent's ride (Book club 17:30) is underway
DAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + timedelta(days=1)).strftime('%Y-%m-%d')
LONG_DATE = NOW.strftime('%A, %B ') + str(NOW.day)                              # "Wednesday, November 4"
LONG_TOMORROW = (NOW + timedelta(days=1)).strftime('%A, %B ') + str((NOW + timedelta(days=1)).day)
FIX = {'latitude': 40.7128, 'longitude': -74.006, 'accuracy': 12}

# (key, role, driver). `parent` drives soccer at 15:40 with Maya; `helper` is
# an outside driver with their own drive (swim, 16:05); `keeping` is the
# keeping-up adult (no driving facet) who rides to the dentist; `navigator` is
# Sam, a kid on the navigator stage with a ride.
PROFILES = [('parent', 'parent', 'd1'), ('helper', 'helper', 'd3'), ('keeping', 'adult', None),
            ('navigator', 'child', None)]
MEMBERS = [
    {'id': 'parent', 'name': 'Alex Morgan', 'role': 'parent', 'driver_id': 'd1', 'passenger_id': 'p_alex',
     'color_code': '#2f6fde'},
    {'id': 'robin', 'name': 'Robin Lee', 'role': 'adult', 'driver_id': 'd2', 'color_code': '#c2410c'},
    {'id': 'helper', 'name': 'Pat Rivera', 'role': 'helper', 'driver_id': 'd3', 'color_code': '#0f766e'},
    {'id': 'keeping', 'name': 'Casey Morgan', 'role': 'adult', 'color_code': '#6b7280',
     'scope': {'preset': 'keeping_up'}},
    {'id': 'maya', 'name': 'Maya', 'role': 'child', 'stage_override': 'navigator', 'passenger_id': 'p_maya',
     'color_code': '#e07a5f'},
    {'id': 'navigator', 'name': 'Sam', 'role': 'child', 'stage_override': 'navigator', 'passenger_id': 'p_sam',
     'color_code': '#7c3aed'},
]
DRIVERS = [{'id': 'd1', 'name': 'Alex Morgan', 'home_location': 'Home', 'color_code': '#2f6fde'},
           {'id': 'd2', 'name': 'Robin Lee', 'home_location': 'Home', 'color_code': '#c2410c'},
           {'id': 'd3', 'name': 'Pat Rivera', 'home_location': 'Home', 'color_code': '#0f766e'}]
PASSENGERS = [{'id': 'p_alex', 'name': 'Alex', 'calendar_ids': ['cal_alex']},
              {'id': 'p_maya', 'name': 'Maya', 'calendar_ids': ['cal_maya']},
              {'id': 'p_sam', 'name': 'Sam', 'calendar_ids': ['cal_sam']}]
CALENDARS = {'cal_alex': {'backgroundColor': '#2f6fde', 'summary': 'Alex'},
             'cal_maya': {'backgroundColor': '#e07a5f', 'summary': 'Maya'},
             'cal_sam': {'backgroundColor': '#7c3aed', 'summary': 'Sam'}}

SOCCER = 'Soccer practice'
SWIM = 'Swim lessons'
LEG = 'init_soccer'                    # the parent's drive: Home -> Riverside fields, 15:40, 18 min
LEG_TITLE = 'Drive to Riverside fields'
HELPER_LEG = 'init_swim'               # the helper's drive: Home -> Aquatic center, 16:05, 20 min
PREP = ['soccer bag', 'water']
CATALOG = ["I'm outside", 'About 5 minutes', 'Come on out', 'On my way']   # services/drive_sheet.py MESSAGES
DRIVE = '#pwa-stack .pwa-screen[data-screen="drive"]'
ARRIVED_GREEN = 'rgb(31, 122, 92)'     # #1f7a5c
BAD_RESPONSES = []
SHOTS = None


def seed():
    for member in MEMBERS:
        storage.add_member(dict(member))
    # Members first: add_passenger runs ensure_members, which mints a member
    # for any passenger nobody links.
    for driver in DRIVERS:
        storage.add_driver(dict(driver))
    for passenger in PASSENGERS:
        storage.add_passenger(dict(passenger))


# --- fixtures ----------------------------------------------------------------

def at(date, hm):
    return f'{date}T{hm}:00'


def ts(date, hm):
    return datetime.strptime(at(date, hm), '%Y-%m-%dT%H:%M:%S').timestamp()


def arrive_by(hm, label):
    """services/arrive_by.py derive()'s shape."""
    return {'arrive_at': at(DAY, hm), 'arrive_label': label, 'lead_mins': 2, 'source': 'rule',
            'reason': 'warm-up', 'label': f'Arrive {label} · warm-up', 'short_label': f'Arrive {label}'}


# Per leg: what GET /api/drive_sheet/{leg} answers (services/drive_sheet.py
# sheet()). The car's range is a float on purpose: the real car levels are.
SHEETS = {
    LEG: {'event_id': 'soccer', 'label': 'Riverside fields', 'address': 'Field 2, 100 River Road',
          'arrive_by': arrive_by('15:58', '3:58 PM'), 'eta': ('15:58', '3:58 pm'),
          'passengers': [('maya', 'Maya', True)], 'prep': PREP, 'audience': ['Lorena'], 'waiting': True,
          'car': {'id': 'highlander', 'name': 'Highlander', 'icon': '🚙', 'image': None, 'range': 210.4,
                  'warn': None}},
    HELPER_LEG: {'event_id': 'swim', 'label': 'Aquatic center', 'address': 'Lane 4, 20 Pool Street',
                 'arrive_by': arrive_by('16:25', '4:25 PM'), 'eta': ('16:25', '4:25 pm'),
                 'passengers': [('maya', 'Maya', True)], 'prep': [], 'audience': ['Alex Morgan'], 'waiting': False,
                 'car': None},
}


class Mocks:
    """One profile's server, as page.route answers it. Stateful on purpose:
    the drive's writes come back in the next read. `reset()` per scenario."""

    def __init__(self, key, driver):
        self.key = key
        self.driver = driver
        self.calls = []
        self.schedule_gets = 0
        self.sheet_gets = []
        self.reset()

    def reset(self):
        self.in_progress = set()
        self.completed = set()
        self.roll = {}
        self.prep_confirmed = set()
        self.arrival = {'arrived': True, 'title': 'Riverside fields'}
        self.calls.clear()
        self.sheet_gets.clear()

    # --- reads ---
    def schedule(self):
        """GET /api/schedule: the solver blob with legs stamped as
        services/leave_by.py stamp() writes them, plus prep_by_event /
        prep_confirmed and the drive state lists (main.py ~22650)."""
        events = [
            {'id': 'soccer', 'title': SOCCER, 'start': at(DAY, '16:00'), 'end': at(DAY, '17:00'),
             'location': 'Riverside fields', 'calendar_ids': ['cal_maya'], 'event_type': 'activity',
             'arrive_by': arrive_by('15:58', '3:58 PM')},
            {'id': 'swim', 'title': SWIM, 'start': at(DAY, '16:30'), 'end': at(DAY, '17:30'),
             'location': 'Aquatic center', 'calendar_ids': ['cal_maya'], 'event_type': 'activity'},
        ]
        return {
            'events': events,
            'assignments': {'soccer': 'd1', 'swim': 'd3'},
            'home_location': 'Home', 'leave_margin_mins': 5,
            'initial_edges': {
                'd1': {'soccer': {'travel_mins': 18, 'buffer_before_mins': 0,
                                  'legs': [{'depart': at(DAY, '15:40'), 'mins': 18, 'from': 'home', 'to': 'event'}]}},
                'd3': {'swim': {'travel_mins': 20, 'buffer_before_mins': 0,
                                'legs': [{'depart': at(DAY, '16:05'), 'mins': 20, 'from': 'home', 'to': 'event'}]}}},
            'route_edges': {}, 'final_edges': {},
            'prep_by_event': {'soccer': list(PREP)},
            'prep_confirmed': sorted(self.prep_confirmed),
            'in_progress_drives': sorted(self.in_progress),
            'completed_drives': sorted(self.completed),
            'calendar_metadata': CALENDARS,
            'passengers': PASSENGERS,
            'drivers': DRIVERS,
        }

    def sheet(self, leg):
        spec = SHEETS.get(leg)
        if spec is None:
            ev = re.sub(r'_\d+$', '', re.sub(r'^(init_|route_|final_)', '', leg))
            spec = {'event_id': ev, 'label': 'Your stop', 'address': None, 'arrive_by': None, 'eta': None,
                    'passengers': [], 'prep': [], 'audience': [], 'waiting': False, 'car': None}
        live = leg in self.in_progress
        eta_ts = ts(DAY, spec['eta'][0]) if live and spec['eta'] else None
        return {
            'leg_id': leg, 'event_id': spec['event_id'],
            'status': 'completed' if leg in self.completed else 'in_progress' if live else 'pending',
            'destination': {'label': spec['label'], 'address': spec['address']},
            'eta_ts': eta_ts, 'eta_label': spec['eta'][1] if eta_ts else None,
            'toward_waiting': spec['waiting'],
            'arrive_by': spec['arrive_by'], 'depart_after': None,
            'driver_name': 'Alex Morgan' if self.key == 'parent' else 'Pat Rivera',
            'passengers': [{'member_id': mid, 'name': name, 'is_child': child, 'aboard': self.roll.get(mid)}
                           for mid, name, child in spec['passengers']],
            'prep': {'items': list(spec['prep']), 'confirmed': spec['event_id'] in self.prep_confirmed},
            'car': spec['car'],
            'next_drive': None, 'day_done': True,
            'messages': [{'key': k, 'icon': i, 'label': l} for k, i, l, waiting_only in (
                ('outside', '🚗', "I'm outside", True), ('five_min', '⏱️', 'About 5 minutes', True),
                ('come_out', '👋', 'Come on out', True), ('on_my_way', '🛣️', 'On my way', False))
                if spec['waiting'] or not waiting_only],
            'audience': list(spec['audience']),
        }

    def member_day(self, route):
        """GET /api/members/{id}/day (main.py _ride shapes, as
        renderMyDayCard reads them)."""
        date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
        out = {'member_id': self.key, 'name': self.key, 'date': date, 'rides': [], 'due_soon': [],
               'still_open': [], 'status_days': [], 'launch': None}
        ride = lambda **kw: dict({'assist': None, 'event_type': 'standard', 'span_start': None, 'span_end': None,
                                  'car': None, 'status': None, 'prep': [], 'arrive_by': None, 'depart_after': None,
                                  'optional': False, 'optional_decision': None, 'legs': []}, **kw)
        if date == DAY and self.key == 'parent':
            # Robin (an adult, d2) drives the parent to book club at 17:30.
            out['rides'] = [ride(id='book_club', title='Book club', start=at(DAY, '17:30'), end=at(DAY, '18:15'),
                                 location='Town library',
                                 driver={'member_id': 'robin', 'id': 'd2', 'name': 'Robin', 'color_code': '#c2410c',
                                         'role': 'adult'},
                                 car={'id': 'highlander', 'name': 'Highlander', 'icon': '🚙'})]
        if date == DAY and self.key == 'keeping':
            # Alex drives Casey to the dentist; underway at 15:12.
            out['rides'] = [ride(id='dentist', title='Dentist', start=at(DAY, '15:00'), end=at(DAY, '15:45'),
                                 location='Smile Dental, 5 Oak Avenue',
                                 driver={'member_id': 'parent', 'id': 'd1', 'name': 'Alex', 'color_code': '#2f6fde',
                                         'role': 'parent'})]
        route.fulfill(json=out)

    # --- the recorder ---
    def record(self, route):
        req = route.request
        try:
            body = req.post_data_json
        except Exception:
            body = req.post_data
        self.calls.append({'method': req.method, 'path': urlparse(req.url).path, 'body': body})
        return self.calls[-1]

    def posts_to(self, path_re):
        return [c for c in self.calls if c['method'] == 'POST' and re.search(path_re, c['path'])]

    def last_post(self, path_re):
        hits = self.posts_to(path_re)
        assert hits, ('no POST matched', path_re, [(c['method'], c['path']) for c in self.calls])
        return hits[-1]

    # --- writes ---
    def drive_status(self, route):
        if route.request.method != 'POST':
            return route.continue_()
        body = self.record(route)['body'] or {}
        leg, status = body.get('leg_id'), body.get('status')
        if status == 'in_progress':
            self.in_progress.add(leg)
        elif status == 'completed':
            self.completed.add(leg)
            self.in_progress.discard(leg)
        route.fulfill(json={'status': 'ok'})

    def roll_call(self, route):
        body = self.record(route)['body'] or {}
        self.roll[body.get('member_id')] = body.get('aboard')
        route.fulfill(json={'status': 'ok', 'roll_call': dict(self.roll)})

    def prep_status(self, route):
        body = self.record(route)['body'] or {}
        if body.get('confirmed'):
            self.prep_confirmed.add(body.get('event_id'))
        else:
            self.prep_confirmed.discard(body.get('event_id'))
        route.fulfill(json={'status': 'ok'})

    def message(self, route):
        body = self.record(route)['body'] or {}
        label = next((l for k, l in zip(('outside', 'five_min', 'come_out', 'on_my_way'), CATALOG)
                      if k == body.get('key')), 'On my way')
        route.fulfill(json={'status': 'ok', 'body': f'Alex says: {label}', 'sent_to': ['Lorena']})

    def send_eta(self, route):
        self.record(route)
        route.fulfill(json={'status': 'ok', 'eta_ts': ts(DAY, '15:57'), 'eta_label': '3:57 pm'})

    def share_eta(self, route):
        self.record(route)
        route.fulfill(json={'status': 'ok', 'eta_ts': ts(DAY, '15:58')})

    def arrival_check(self, route):
        body = self.record(route)['body'] or {}
        answer = dict(self.arrival)
        if answer.get('arrived') is True:
            self.completed.add(body.get('leg_id'))
            self.in_progress.discard(body.get('leg_id'))
        route.fulfill(json=answer)

    def ping(self, route):
        self.record(route)
        route.fulfill(json={'status': 'ok', 'completed': False})

    def attendance(self, route):
        self.record(route)
        route.fulfill(json={'status': 'ok'})

    def telemetry(self, route):
        if route.request.method == 'GET':
            return route.fulfill(json=[])     # the bell's list (fetchNotifications)
        self.record(route)
        route.fulfill(json={'status': 'ok'})

    def open_dm(self, route):
        if route.request.method != 'POST':
            return route.continue_()
        body = self.record(route)['body'] or {}
        other = body.get('other_member_id')
        route.fulfill(json={'id': f'dm_{other}', 'kind': 'dm', 'title': other, 'member_ids': [self.key, other]})

    def open_event_thread(self, route):
        body = self.record(route)['body'] or {}
        route.fulfill(json={'id': 'ev_' + str(body.get('event_id')), 'kind': 'event',
                            'title': body.get('title') or 'Event', 'member_ids': [self.key]})

    def install(self, page):
        key = self.key

        def schedule(route):
            self.schedule_gets += 1
            route.fulfill(json=self.schedule())
        page.route('**/api/schedule?*', schedule)

        def sheet(route):
            leg = urlparse(route.request.url).path.rstrip('/').split('/')[-1]
            self.sheet_gets.append(leg)
            route.fulfill(json=self.sheet(leg))
        page.route('**/api/drive_sheet/*', sheet)
        page.route(re.compile(r'.*/api/drive_status(\?.*)?$'), self.drive_status)
        page.route('**/api/drive_status/roll_call', self.roll_call)
        page.route('**/api/drive_status/message', self.message)
        page.route('**/api/drive_status/send_eta', self.send_eta)
        page.route('**/api/drive_status/share_eta', self.share_eta)
        page.route('**/api/drive_status/arrival', self.arrival_check)
        page.route('**/api/drive_status/ping', self.ping)
        page.route('**/api/prep_status', self.prep_status)
        page.route('**/api/events/*/attendance', self.attendance)
        page.route(re.compile(r'.*/api/telemetry(\?.*)?$'), self.telemetry)
        page.route('**/api/channels/dm', self.open_dm)
        page.route('**/api/channels/event', self.open_event_thread)

        page.route('**/api/settings', lambda r: r.fulfill(json={'time_format_24h': False}))
        page.route('**/api/weather/daily*', lambda r: r.fulfill(json=[]))
        page.route('**/api/weather/now*', lambda r: r.fulfill(status=200, content_type='application/json', body='null'))
        page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/messages/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))
        page.route('**/api/members/*/day?*', self.member_day)

        def routine_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'date': date, 'items': [], 'streak': {}})
        page.route('**/api/routines/day?*', routine_day)
        page.route('**/api/requests?*', lambda r: r.fulfill(json={'waiting_on_me': [], 'mine': []}))
        page.route('**/api/proposals?*', lambda r: r.fulfill(json=[]))
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
        page.route('**/api/situations?*', lambda r: r.fulfill(json={'situations': []}))
        page.route('**/api/channels?*', lambda r: r.fulfill(json=[
            {'id': 'family', 'kind': 'family', 'title': 'Family', 'member_ids': [], 'last_message': None,
             'unread': 0}]))
        page.route('**/api/channels/*/messages*', lambda r: r.fulfill(json=[]))
        page.route('**/api/presence/moments*', lambda r: r.fulfill(json=[]))


# --- page helpers ------------------------------------------------------------

# openMaps (app.html ~8714) clicks a synthetic <a>; a real click would leave
# the app for google.com / maps:// / waze://. Capture the href instead.
NAV_CAPTURE = """(() => {
    window.__navClicks = [];
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
        const href = String(this.href || '');
        if (/^(maps:|waze:|https:\\/\\/www\\.google\\.com\\/maps)/.test(href)) { window.__navClicks.push(href); return; }
        return click.call(this);
    };
})();"""

NO_FIX = """() => {
    window.__geoSaved = window.__geoSaved || Geolocation.prototype.getCurrentPosition;
    Geolocation.prototype.getCurrentPosition = function (ok, err) {
        setTimeout(() => err && err({code: 1, message: 'User denied Geolocation'}), 0);
    };
}"""

WITH_FIX = """() => { if (window.__geoSaved) Geolocation.prototype.getCurrentPosition = window.__geoSaved; }"""

# pwaDriveView over what the screen was opened with: routeContext and the
# drive row's dataset (read the way pwaRowsFromDom reads it).
DRIVE_ORACLE = """() => {
    if (typeof pwaDriveView !== 'function') return {missing: true};
    if (typeof routeContext === 'undefined' || !routeContext) return {noContext: true};
    const legId = routeContext.legId || '';
    const row = legId ? (pwaRowsFromDom(document).find(r => r.kind === 'drive' && r.legId === legId) || null) : null;
    const view = pwaDriveView(driveSheetData, {row, origin: routeContext.origin, destination: routeContext.destination,
        legTitle: routeContext.legTitle, now: new Date(), use24h: !!use24h});
    return {view, row};
}"""

TOKEN_PROBE = """(token) => { const p = document.createElement('div'); p.style.color = 'var(' + token + ')';
    document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; }"""

# Every visible button in the drive screen whose background is a saturated
# green (g well above r and above b): Arrived must be the only one.
GREEN_BUTTONS = """(sel) => [...document.querySelectorAll(sel + ' button')].filter(b => b.checkVisibility())
    .filter(b => { const m = getComputedStyle(b).backgroundColor.match(/[\\d.]+/g); if (!m) return false;
        const [r, g, bl, a] = m.map(Number); return (a === undefined || a > 0.5) && g > r + 30 && g > bl + 10; })
    .map(b => b.id || b.textContent.trim())"""

TOPMOST = """(sel) => { const el = document.querySelector(sel); if (!el || !el.checkVisibility()) return false;
    const r = el.getBoundingClientRect(); const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!hit && (el.contains(hit) || hit.contains(el)); }"""


def norm(text):
    return ' '.join((text or '').split())


def settle(page, condition, timeout=6000, arg=None):
    """Give an async step the chance to land; the assertion that follows says
    what was wrong if it never did."""
    try:
        if arg is None:
            # An expression or a { block } becomes the body of an arrow; a
            # condition already written as an arrow is used as it is.
            arrow = re.match(r'\s*(\([^)]*\)|[A-Za-z_]\w*)\s*=>', condition)
            page.wait_for_function(condition if arrow else '() => ' + condition, timeout=timeout)
        else:
            page.wait_for_function(condition, arg=arg, timeout=timeout)
    except Exception:
        pass


def shot(page, name):
    if SHOTS:
        page.mouse.move(0, 0)
        Path(SHOTS, name).write_bytes(page.screenshot())


def no_overflow(page, where=''):
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), \
        (where, page.evaluate('[document.documentElement.scrollWidth, innerWidth]'))


def posting(page, path_re, method='POST'):
    """Wait for the mocked answer, so the recorder already holds the call."""
    return page.expect_response(lambda r: r.request.method == method and bool(re.search(path_re, urlparse(r.url).path)),
                                timeout=10000)


def visible(page, sel):
    return page.locator(sel).first.is_visible()


def text(page, sel):
    return norm(page.locator(sel).first.text_content())


def box(page, sel):
    b = page.locator(sel).first.bounding_box()
    assert b, (sel, 'has no box')
    return b


def depth(page):
    return page.evaluate('window.PwaNav ? PwaNav.depth() : null')


BRIEF_READY = """() => {
    const c = document.getElementById('myday-content');
    return !!c && !!c.querySelector('.pwa-brief-greet') && !!c.querySelector('.pwa-brief-day')
        && !c.innerText.includes('Loading your day');
}"""


def wait_brief(page):
    settle(page, BRIEF_READY[6:], timeout=10000)
    assert page.locator('#myday-content .pwa-brief-greet').count() == 1, 'My Day did not draw the brief'


def rerender_brief(page):
    page.evaluate('async () => { buildTimeline(); await pwaRenderBrief(); }')
    wait_brief(page)


def hero_buttons(page):
    return [norm(t) for t in page.locator('#myday-content .pwa-hero :is(.pwa-btn-primary, .pwa-btn-secondary)')
            .all_text_contents()]


def wait_drive(page, leg=None, where=''):
    """The drive is the pushed screen: one PwaNav entry whose body holds the
    adopted #action-sheet-content; the bottom-sheet overlay stays hidden."""
    cond = ("(leg) => !!window.PwaNav && PwaNav.depth() === 1 && !!document.querySelector('%s #action-sheet-content')"
            " && (!leg || (typeof driveSheetData !== 'undefined' && !!driveSheetData && driveSheetData.leg_id === leg))"
            % DRIVE)
    settle(page, cond, timeout=8000, arg=leg or '')
    state = page.evaluate("""(sel) => ({depth: window.PwaNav ? PwaNav.depth() : null,
        screens: [...document.querySelectorAll('#pwa-stack .pwa-screen')].map(s => s.dataset.screen),
        adopted: !!document.querySelector(sel + ' #action-sheet-content'),
        overlay: !!document.getElementById('action-sheet')?.checkVisibility(),
        leg: typeof driveSheetData !== 'undefined' && driveSheetData ? driveSheetData.leg_id : null})""", DRIVE)
    assert state['depth'] == 1 and state['screens'] == ['drive'] and state['adopted'], \
        (where, 'the drive did not open as the pushed screen #pwa-stack .pwa-screen[data-screen="drive"] '
                'adopting #action-sheet-content', state)
    assert not state['overlay'], (where, 'the bottom-sheet overlay #action-sheet showed for an adult', state)
    if leg:
        assert state['leg'] == leg, (where, 'driveSheetData is not the opened leg', state)
    return page.locator(DRIVE)


def wait_closed(page, where=''):
    settle(page, """!!window.PwaNav && PwaNav.depth() === 0 && !document.querySelector('%s')
        && document.getElementById('action-sheet-content').parentElement === document.getElementById('action-sheet')
        && routeContext === null && driveSheetData === null""" % DRIVE, timeout=10000)
    state = page.evaluate("""() => ({depth: PwaNav.depth(), screens: document.querySelectorAll('#pwa-stack .pwa-screen').length,
        home: document.getElementById('action-sheet-content').parentElement.id,
        overlay: !!document.getElementById('action-sheet').checkVisibility(),
        route: routeContext, sheet: driveSheetData === null ? null : 'set',
        resume: localStorage.getItem('chauffeur_drive_resume'), timer: driveLiveTimer === null ? null : 'running'})""")
    assert state['depth'] == 0 and state['screens'] == 0, (where, 'the drive screen did not pop', state)
    assert state['home'] == 'action-sheet', (where, '#action-sheet-content was not put back into #action-sheet', state)
    assert not state['overlay'], (where, '#action-sheet showed on close', state)
    assert state['route'] is None and state['sheet'] is None, (where, 'routeContext / driveSheetData survived', state)
    assert state['resume'] is None, (where, 'the resume key survived the close', state)
    assert state['timer'] is None, (where, 'the live lane kept running after the close', state)


def open_from_hero(page, leg=LEG, where='hero'):
    hero = page.locator('#myday-content .pwa-hero .pwa-btn-primary')
    settle(page, "!!document.querySelector('#myday-content .pwa-hero .pwa-btn-primary')", timeout=8000)
    assert hero.count() == 1, (where, 'no hero primary button')
    assert norm(hero.text_content()).lower() == 'start drive', (where, hero.text_content())
    hero.click()
    return wait_drive(page, leg, where)


def wait_before(page, where=''):
    settle(page, """{ const t = document.querySelector('%s #drive-leave-card .pwa-drive-time');
        return !!t && t.textContent.trim() !== '' && !!document.querySelector('%s .pwa-drive-stops')
            && document.querySelector('%s .pwa-drive-stops').textContent.trim() !== ''; }""" % (DRIVE, DRIVE, DRIVE),
           timeout=8000)
    assert page.locator(f'{DRIVE} #sheet-state-1 #drive-leave-card').count() == 1, \
        (where, '#drive-leave-card is not in #sheet-state-1 of the drive screen')
    assert visible(page, f'{DRIVE} #drive-leave-card'), (where, '#drive-leave-card is not visible')
    assert visible(page, f'{DRIVE} #drive-leave-card .pwa-drive-time'), (where, 'no .pwa-drive-time')
    assert page.locator(f'{DRIVE} #sheet-state-1 .pwa-drive-stops').count() == 1, \
        (where, '.pwa-drive-stops is not in #sheet-state-1')


def wait_road(page, where=''):
    settle(page, """{ const s1 = document.getElementById('sheet-state-1'), s2 = document.getElementById('sheet-state-2');
        const card = document.querySelector('%s #drive-arrival-card');
        return !!s2 && s2.checkVisibility() && !s1.checkVisibility() && !!card && card.textContent.trim() !== ''; }"""
           % DRIVE, timeout=8000)
    assert visible(page, f'{DRIVE} #sheet-state-2'), (where, 'the on-road block #sheet-state-2 is not showing')
    assert not visible(page, f'{DRIVE} #sheet-state-1'), (where, 'the before block still shows on the road')
    assert page.locator(f'{DRIVE} #sheet-state-2 #drive-arrival-card').count() == 1, \
        (where, '#drive-arrival-card is not in #sheet-state-2')
    assert visible(page, f'{DRIVE} #drive-arrival-card'), (where, '#drive-arrival-card is not visible')


def oracle(page, where=''):
    out = page.evaluate(DRIVE_ORACLE)
    assert not out.get('missing'), (where, 'pwaDriveView is not loaded (static/pwa_drive.js, Task 1)')
    assert not out.get('noContext'), (where, 'routeContext is null while the drive screen is up')
    return out['view'], out['row']


def tap_start(page, mocks, with_fix=True):
    before = len(mocks.posts_to(r'/api/drive_status$'))
    with posting(page, r'/api/drive_status$'):
        page.locator(f'{DRIVE} #btn-start-drive').click()
    starts = mocks.posts_to(r'/api/drive_status$')
    assert len(starts) == before + 1, starts
    body = starts[-1]['body']
    if with_fix:
        assert body == {'leg_id': LEG if mocks.key == 'parent' else HELPER_LEG, 'status': 'in_progress',
                        'lat': FIX['latitude'], 'lng': FIX['longitude'], 'accuracy': FIX['accuracy']}, body
    else:
        assert body == {'leg_id': LEG, 'status': 'in_progress'}, ('the no-fix Start must post without coords', body)
    wait_road(page, 'after Start')
    assert depth(page) == 1, ('Start pushed or popped a screen', depth(page))


def ys(page, sels):
    return [box(page, s)['y'] for s in sels]


def assert_order(page, sels, where):
    tops = ys(page, sels)
    assert tops == sorted(tops) and len(set(tops)) == len(tops), (where, 'out of order', list(zip(sels, tops)))


# --- scenarios ---------------------------------------------------------------

def before_moment(page, mocks):
    """Parent: the hero's Start drive opens the pushed screen in the before
    moment, every control of the old sheet's state 1 on it, in the order the
    design gives."""
    screen = open_from_hero(page, LEG, 'before_moment')
    back = norm(screen.locator('.pwa-back').text_content())
    assert back == '‹ My Day', back
    assert norm(screen.locator('h1').first.text_content()) == LEG_TITLE, screen.locator('h1').first.text_content()
    wait_before(page, 'before_moment')
    # The sheet's own head is replaced by the back button and the h1.
    for sel in ('#sheet-title', '#sheet-subtitle', '.pwa-drive-handle', '.pwa-sheet-head'):
        assert not visible(page, f'{DRIVE} {sel}'), (sel, 'the sheet head still shows inside the stack')
    # The brief's address and car lines live on the cards now (the nodes stay).
    for sel in ('#drive-dest', '#drive-car'):
        assert not visible(page, f'{DRIVE} {sel}'), (sel, 'shows beside the leave card')
    assert 'Field 2, 100 River Road' in text(page, '#drive-dest'), text(page, '#drive-dest')
    assert screen.get_by_role('button', name='Cancel', exact=True).filter(visible=True).count() == 0, \
        'a Cancel button shows inside the stack (Back replaces it)'
    assert text(page, '#sheet-title') == 'Your drive', text(page, '#sheet-title')

    view, row = oracle(page, 'before_moment')
    assert row and row['legId'] == LEG, row
    # The leave-at card: the solver's departure huge, the sub line under it.
    time_el = screen.locator('#drive-leave-card .pwa-drive-time')
    assert norm(time_el.text_content()) == '3:40' == view['leave']['time'], (time_el.text_content(), view['leave'])
    size = time_el.evaluate('e => [getComputedStyle(e).fontSize, getComputedStyle(e).fontWeight]')
    assert size == ['56px', '700'], size
    card = text(page, f'{DRIVE} #drive-leave-card')
    assert 'leave at' in card.lower(), card
    assert norm(view['leave']['sub']) in card, (view['leave']['sub'], card)
    for want in ('18 min drive', 'arrive 3:58', 'Highlander', '210 mi range'):
        assert want in card, (want, card)
    # The stops as a line: where you start, who and what; the destination.
    stops = text(page, f'{DRIVE} .pwa-drive-stops')
    assert len(view['stops']) == 2, view['stops']
    at_ = 0
    for stop in view['stops']:
        for part in (stop['place'], stop['sub']):
            i = stops.find(norm(part), at_)
            assert i >= 0, ('stop words missing or out of order', part, stops)
            at_ = i
    for want in ('Home', 'Pick up Maya', 'soccer bag, water', 'Riverside fields', 'Arrive by 3:58', 'Field 2'):
        assert want in stops, (want, stops)
    assert stops.index('Home') < stops.index('Riverside fields'), stops

    # "Everybody in?": three states, each one a POST; never a gate.
    assert visible(page, f'{DRIVE} #drive-roll'), '#drive-roll is not on the screen'
    assert 'everybody in?' in text(page, f'{DRIVE} #drive-roll').lower()
    chip = screen.locator('#drive-roll-chips button')
    assert chip.count() == 1 and 'Maya' in norm(chip.text_content()), chip.all_text_contents()
    stops_before = page.locator(f'{DRIVE} .pwa-drive-stops').evaluate('e => e.innerHTML')
    for want, state in ((True, 'yes'), (False, 'no'), (None, 'unknown'), (True, 'yes')):
        with posting(page, r'/api/drive_status/roll_call$'):
            screen.locator('#drive-roll-chips button').click()
        assert mocks.last_post(r'/roll_call$')['body'] == {'leg_id': LEG, 'member_id': 'maya', 'aboard': want}, \
            mocks.last_post(r'/roll_call$')
        settle(page, "(s) => document.querySelector('#drive-roll-chips button')?.dataset.aboard === s", arg=state)
        assert screen.locator('#drive-roll-chips button').get_attribute('data-aboard') == state, state
    # Maya aboard: the first stop reads done (its dot fills).
    settle(page, "(h) => document.querySelector('%s .pwa-drive-stops').innerHTML !== h" % DRIVE, arg=stops_before)
    view, _ = oracle(page, 'aboard')
    assert view['stops'][0]['done'] is True, view['stops']
    assert page.locator(f'{DRIVE} .pwa-drive-stops').evaluate('e => e.innerHTML') != stops_before, \
        'the first stop did not change once Maya was aboard'

    # "Packed?": the last tick is the household's confirmation.
    assert visible(page, f'{DRIVE} #drive-prep') and 'packed?' in text(page, f'{DRIVE} #drive-prep').lower()
    items = screen.locator('#drive-prep-items button')
    assert [norm(t) for t in items.all_text_contents()] == PREP, items.all_text_contents()
    posts = len(mocks.posts_to(r'/api/prep_status$'))
    items.nth(0).click()
    settle(page, "document.querySelectorAll('#drive-prep-items button')[0]?.getAttribute('aria-pressed') === 'true'")
    assert len(mocks.posts_to(r'/api/prep_status$')) == posts, 'the first tick posted a confirmation'
    with posting(page, r'/api/prep_status$'):
        screen.locator('#drive-prep-items button').nth(1).click()
    assert mocks.last_post(r'/api/prep_status$')['body'] == {'event_id': 'soccer', 'confirmed': True,
                                                             'member_id': 'parent'}, mocks.last_post(r'/prep_status$')

    # Start drive: primary, full width, 56px.
    start = screen.locator('#btn-start-drive')
    assert start.is_visible() and norm(start.text_content()).lower() == 'start drive', start.text_content()
    assert screen.locator('#sheet-state-1 #btn-start-drive').count() == 1
    sb, s1 = box(page, f'{DRIVE} #btn-start-drive'), box(page, f'{DRIVE} #sheet-state-1')
    assert abs(sb['width'] - s1['width']) <= 2, ('Start is not full width', sb, s1)
    assert sb['height'] >= 55, ('Start is not 56px tall', sb)
    # Ask someone to cover: the drive row's own secondary (the event dialog).
    cover = screen.locator('#btn-drive-cover')
    assert cover.count() == 1 and cover.is_visible(), '#btn-drive-cover is missing'
    assert norm(cover.text_content()) == 'Ask someone to cover', cover.text_content()
    assert screen.locator('#sheet-state-1 #btn-drive-cover').count() == 1
    # The retro-split options and Mark as completed stay, below.
    split = f'{DRIVE} #sheet-state-1 .btn-not-staying'
    assert visible(page, split), 'Not Staying — Schedule Pick-up is gone from the before moment'
    assert not visible(page, f'{DRIVE} #sheet-state-1 .btn-staying-after-all')
    assert visible(page, f'{DRIVE} #btn-mark-completed'), 'Mark as Completed is gone'
    assert visible(page, f'{DRIVE} #drive-next') and 'Last drive of the day' in text(page, f'{DRIVE} #drive-next')
    assert_order(page, [f'{DRIVE} #drive-leave-card', f'{DRIVE} .pwa-drive-stops', f'{DRIVE} #drive-roll',
                        f'{DRIVE} #drive-prep', f'{DRIVE} #btn-start-drive', f'{DRIVE} #btn-drive-cover', split,
                        f'{DRIVE} #btn-mark-completed', f'{DRIVE} #drive-next'], 'before')
    assert not visible(page, f'{DRIVE} #drive-live'), 'the live banner shows before Start'
    assert not visible(page, f'{DRIVE} #sheet-state-2'), 'the on-road block shows before Start'
    no_overflow(page, 'before')
    shot(page, 'drive-before.png')

    cover.click()
    settle(page, "!!document.getElementById('event-modal')?.checkVisibility()")
    assert visible(page, '#event-modal'), 'Ask someone to cover did not open the event dialog'
    assert SOCCER in text(page, '#em-title'), text(page, '#em-title')
    assert page.evaluate("!document.getElementById('event-modal').closest('[inert]')"), \
        'the event dialog sits inside an inert root'
    # The dialog slides up (translate-y-full -> 0); hit-test once it is in view.
    settle(page, "{ const r = document.getElementById('em-title').getBoundingClientRect(); "
                 "return r.top >= 0 && r.bottom <= innerHeight; }")
    assert page.evaluate(TOPMOST, '#em-title'), 'the event dialog is under the drive screen'
    page.evaluate('closeEventModal()')
    page.wait_for_selector('#event-modal', state='hidden')
    assert depth(page) == 1, 'closing the event dialog closed the drive'

    # Back closes it the way the x did.
    screen.locator('.pwa-back').click()
    wait_closed(page, 'back from before')
    assert page.evaluate('currentView') == 'myday'

    # Not staying: POST /api/events/soccer/attendance {action: split}, then closed.
    open_from_hero(page, LEG, 'not staying')
    wait_before(page, 'not staying')
    with posting(page, r'/api/events/[^/]+/attendance$'):
        page.locator(f'{DRIVE} #sheet-state-1 .btn-not-staying').click()
    call = mocks.last_post(r'/attendance$')
    assert call['path'].endswith('/api/events/soccer/attendance') and call['body'] == {'action': 'split'}, call
    wait_closed(page, 'after not staying')

    # Mark as completed: telemetry + drive_status completed, then closed.
    open_from_hero(page, LEG, 'mark completed')
    wait_before(page, 'mark completed')
    with posting(page, r'/api/drive_status$'):
        page.locator(f'{DRIVE} #btn-mark-completed').click()
    assert mocks.last_post(r'/api/telemetry$')['body'] == {'driver_id': 'd1', 'event_id': 'soccer', 'action': 'completed',
                                                           'details': LEG_TITLE, 'leg_id': LEG}, mocks.last_post(r'/telemetry$')
    assert mocks.last_post(r'/api/drive_status$')['body'] == {'leg_id': LEG, 'status': 'completed'}
    wait_closed(page, 'after mark completed')


def on_the_road(page, mocks):
    """Parent: Start (with a fix) turns the same screen to the on-road moment:
    the arrival card, maps three across, Tell Lorena, Send my ETA, the green
    Arrived, the live banner."""
    screen = open_from_hero(page, LEG, 'on_the_road')
    wait_before(page, 'on_the_road')
    with posting(page, r'/api/drive_status/roll_call$'):
        screen.locator('#drive-roll-chips button').click()
    page.clock.set_fixed_time(NOW_ROAD)
    sheets = len(mocks.sheet_gets)
    with posting(page, r'/api/drive_status/ping$'):
        tap_start(page, mocks, with_fix=True)
    assert mocks.last_post(r'/api/drive_status/ping$')['body'] == {
        'leg_id': LEG, 'member_id': 'parent', 'lat': FIX['latitude'], 'lng': FIX['longitude'],
        'accuracy': FIX['accuracy']}, mocks.last_post(r'/ping$')
    settle(page, "(n) => typeof driveSheetData !== 'undefined' && !!driveSheetData && driveSheetData.status === 'in_progress'",
           arg=sheets)
    assert len(mocks.sheet_gets) > sheets, 'the sheet was not re-read after Start'
    settle(page, "document.querySelector('%s #drive-arrival-card')?.textContent.includes('aboard')" % DRIVE)
    view, _ = oracle(page, 'on_the_road')
    arrival = text(page, f'{DRIVE} #drive-arrival-card')
    assert 'on the way' in arrival.lower(), arrival
    for part in (view['arrival']['place'], view['arrival']['eta'], view['arrival']['sub']):
        assert norm(part) and norm(part) in arrival, (part, view['arrival'], arrival)
    for want in ('Riverside fields', '3:58', '16 min', 'Maya aboard'):
        assert want in arrival, (want, arrival)
    assert not visible(page, f'{DRIVE} #drive-eta'), '#drive-eta shows beside the arrival card'
    big = page.locator(f'{DRIVE} #drive-arrival-card').evaluate("""c => Math.max(...[...c.querySelectorAll('*')]
        .filter(e => e.textContent.includes('3:58') && e.children.length === 0)
        .map(e => parseFloat(getComputedStyle(e).fontSize)))""")
    assert big >= 32, ('the ETA is not big', big)
    # Google / Apple / Waze: one row, three tiles.
    tiles = screen.locator('#sheet-state-2 button[onclick^="openMaps"]')
    assert tiles.count() == 3, tiles.count()
    boxes = [tiles.nth(i).bounding_box() for i in range(3)]
    assert all(b and abs(b['y'] - boxes[0]['y']) <= 2 for b in boxes), ('the maps are not three across', boxes)
    assert all(b['height'] >= 63 for b in boxes), ('the map tiles are not 64px', boxes)
    assert [norm(t) for t in tiles.all_text_contents()] == ['Google', 'Apple', 'Waze'], tiles.all_text_contents()
    # Tell Lorena, with the catalog's lines.
    assert visible(page, f'{DRIVE} #drive-messages') and 'Tell Lorena' in text(page, f'{DRIVE} #drive-messages')
    lines = [norm(t) for t in screen.locator('#drive-message-buttons button').all_text_contents()]
    assert len(lines) == len(CATALOG) and all(want in got for want, got in zip(CATALOG, lines)), lines
    b0, b1 = (screen.locator('#drive-message-buttons button').nth(i).bounding_box() for i in (0, 1))
    assert abs(b0['y'] - b1['y']) <= 2, ('the Tell lines are not two across', b0, b1)
    with posting(page, r'/api/drive_status/message$'):
        screen.locator('#drive-message-buttons button', has_text='On my way').click()
    assert mocks.last_post(r'/message$')['body'] == {'leg_id': LEG, 'key': 'on_my_way', 'member_id': 'parent'}, \
        mocks.last_post(r'/message$')
    with posting(page, r'/api/drive_status/send_eta$'):
        screen.locator('#btn-send-eta').click()
    assert mocks.last_post(r'/send_eta$')['body'] == {'leg_id': LEG, 'status': 'in_progress', 'lat': FIX['latitude'],
                                                      'lng': FIX['longitude'], 'accuracy': FIX['accuracy']}
    settle(page, "driveSheetData && driveSheetData.eta_label === '3:57 pm'")
    # Arrived: green #1f7a5c, 56px, the only green; the live banner below.
    arrived = screen.locator('#btn-arrived')
    assert arrived.is_visible() and 'Arrived' in norm(arrived.text_content())
    assert arrived.evaluate('e => getComputedStyle(e).backgroundColor') == ARRIVED_GREEN, \
        arrived.evaluate('e => getComputedStyle(e).backgroundColor')
    assert box(page, f'{DRIVE} #btn-arrived')['height'] >= 55
    assert page.evaluate(GREEN_BUTTONS, DRIVE) == ['btn-arrived'], page.evaluate(GREEN_BUTTONS, DRIVE)
    assert visible(page, f'{DRIVE} #drive-live') and 'Sharing where you are' in text(page, f'{DRIVE} #drive-live')
    assert visible(page, f'{DRIVE} #sheet-state-2 .btn-not-staying'), 'the retro-split left the on-road moment'
    assert_order(page, [f'{DRIVE} #drive-arrival-card', f'{DRIVE} #sheet-state-2 button[onclick^="openMaps"]',
                        f'{DRIVE} #drive-messages', f'{DRIVE} #btn-arrived', f'{DRIVE} #sheet-state-2 .btn-not-staying'],
                 'on the road')
    assert box(page, f'{DRIVE} #drive-live')['y'] > box(page, f'{DRIVE} #btn-arrived')['y']
    assert box(page, f'{DRIVE} #drive-next')['y'] > box(page, f'{DRIVE} #btn-arrived')['y']
    assert not visible(page, f'{DRIVE} #btn-drive-cover'), 'Ask someone to cover shows on the road'
    # Nothing the old sheet offered on the road is lost: the roll call and the
    # packing claims stay editable after Start (inventory §5: "Also editable on
    # road", "Retained on road"), below Send my ETA and above Arrived.
    assert visible(page, f'{DRIVE} #drive-roll-chips button'), 'Everybody in? left the on-road moment'
    assert visible(page, f'{DRIVE} #drive-prep-items button'), 'Packed? left the on-road moment'
    with posting(page, r'/api/drive_status/roll_call$'):
        screen.locator('#drive-roll-chips button').first.click()
    # The arrival card names the arrive-by (the old brief's line).
    assert 'Arrive by 3:58' in text(page, f'{DRIVE} #drive-arrival-card'), text(page, f'{DRIVE} #drive-arrival-card')
    no_overflow(page, 'road')
    shot(page, 'drive-road.png')
    # The maps hand-off (openMaps): the href is captured, never followed.
    screen.locator('#sheet-state-2 button[onclick^="openMaps"]', has_text='Google').click()
    settle(page, '(window.__navClicks || []).length > 0')
    nav = page.evaluate('window.__navClicks')
    assert nav and nav[-1].startswith('https://www.google.com/maps/dir/?api=1&destination=Riverside%20fields'), nav


def arrived_resolved(page, mocks):
    """No fix at Start (the POST carries no coords); Arrived answered
    arrived:true pops the screen and refetches the schedule."""
    page.evaluate(NO_FIX)
    open_from_hero(page, LEG, 'arrived_resolved')
    wait_before(page, 'arrived_resolved')
    tap_start(page, mocks, with_fix=False)
    assert not mocks.posts_to(r'/ping$'), ('a ping went out without a fix', mocks.posts_to(r'/ping$'))
    page.evaluate(WITH_FIX)
    mocks.arrival = {'arrived': True, 'title': 'Riverside fields'}
    gets = mocks.schedule_gets
    with posting(page, r'/api/drive_status/arrival$'):
        page.locator(f'{DRIVE} #btn-arrived').click()
    assert mocks.last_post(r'/arrival$')['body'] == {'leg_id': LEG, 'status': 'in_progress', 'lat': FIX['latitude'],
                                                     'lng': FIX['longitude'], 'accuracy': FIX['accuracy']}
    wait_closed(page, 'arrived resolved')
    # handleArrivalCheck refetches; the mock now lists the leg as completed.
    settle(page, "(scheduleData.completed_drives || []).includes('%s')" % LEG, timeout=8000)
    assert mocks.schedule_gets > gets, ('the schedule was not refetched after Arrived', mocks.schedule_gets, gets)
    assert page.evaluate("(scheduleData.completed_drives || []).includes('%s')" % LEG)
    assert page.locator('.pwa-prompt-overlay').count() == 0, 'a resolved arrival still asked the human'


def arrived_unresolved(page, mocks):
    """arrived:false with eta_mins: the choice sits ABOVE the screen; "Still
    driving" keeps it on the road; "I've arrived" completes it and pops."""
    open_from_hero(page, LEG, 'arrived_unresolved')
    wait_before(page, 'arrived_unresolved')
    tap_start(page, mocks)
    mocks.arrival = {'arrived': False, 'title': 'Riverside fields', 'eta_ts': ts(DAY, '15:58'), 'eta_mins': 6,
                     'distance_m': 3200}
    with posting(page, r'/api/drive_status/arrival$'):
        page.locator(f'{DRIVE} #btn-arrived').click()
    page.wait_for_selector('.pwa-prompt-overlay [data-pick]', state='visible')
    picks = [norm(t) for t in page.locator('.pwa-prompt-overlay').last.locator('[data-pick]').all_text_contents()]
    assert len(picks) == 3 and "I've arrived — check it off" in picks[0] and 'about 6 min away' in picks[1] \
        and 'Still driving' in picks[2], picks
    assert page.evaluate(TOPMOST, '.pwa-prompt-overlay [data-pick]'), 'the arrival choice is under the drive screen'
    page.locator('.pwa-prompt-overlay').last.locator('[data-pick]', has_text='Still driving').click()
    page.wait_for_function("document.querySelectorAll('.pwa-prompt-overlay').length === 0")
    wait_drive(page, LEG, 'still driving')
    wait_road(page, 'still driving')
    settle(page, "!document.getElementById('btn-arrived').disabled")
    assert not page.locator('#btn-arrived').is_disabled()
    with posting(page, r'/api/drive_status/arrival$'):
        page.locator(f'{DRIVE} #btn-arrived').click()
    page.wait_for_selector('.pwa-prompt-overlay [data-pick]', state='visible')
    with posting(page, r'/api/drive_status$'):
        page.locator('.pwa-prompt-overlay').last.locator('[data-pick]', has_text="I've arrived").click()
    assert mocks.last_post(r'/api/drive_status$')['body'] == {'leg_id': LEG, 'status': 'completed'}
    wait_closed(page, "I've arrived")


def resume_after_reload(page, mocks):
    """Start, reload mid-drive: the resume reopens the screen on the road with
    the live lane; hardware Back closes it and forgets the resume."""
    open_from_hero(page, LEG, 'resume')
    wait_before(page, 'resume')
    tap_start(page, mocks)
    saved = json.loads(page.evaluate("localStorage.getItem('chauffeur_drive_resume')") or 'null')
    assert saved and saved.get('legId') == LEG, saved
    pings = len(mocks.posts_to(r'/ping$'))
    with posting(page, r'/api/drive_status/ping$'):
        page.reload(wait_until='domcontentloaded')
    wait_app(page)
    wait_drive(page, LEG, 'resumed')
    wait_road(page, 'resumed')
    assert len(mocks.posts_to(r'/ping$')) > pings
    assert visible(page, f'{DRIVE} #drive-live'), 'the live banner is not back after the resume'
    assert page.evaluate('driveLiveTimer !== null'), 'the live lane did not restart'
    assert norm(page.locator(f'{DRIVE} .pwa-back').text_content()) == '‹ My Day'
    page.go_back()
    wait_closed(page, 'hardware Back')
    assert page.evaluate('currentView') == 'myday'


def opens_from_every_door(page, mocks):
    """My Day's row, the hero, Plan's timeline block (via the event dialog's
    map button: the map-only on-road screen, no leg operations) — the same
    screen, with the right Back."""
    day = page.locator('#myday-content .pwa-brief-day')
    if page.locator('#myday-content .pwa-brief-day.is-collapsed').count():
        page.locator('#myday-content .pwa-brief-expand').click()
    day.locator(f'.pwa-leg-row[data-leg-id="{LEG}"] .pwa-row-main').first.click()
    screen = wait_drive(page, LEG, 'My Day row')
    assert norm(screen.locator('.pwa-back').text_content()) == '‹ My Day'
    wait_before(page, 'My Day row')
    # Re-opening the same leg is a no-op; another open re-uses the screen.
    page.evaluate("new Function(document.querySelector('.pwa-leg-row[data-leg-id=\"%s\"]').dataset.primary)()" % LEG)
    wait_drive(page, LEG, 'same leg again')
    page.evaluate("openActionSheet('', 'Aquatic center', 'Map to Event')")
    settle(page, "document.querySelector('%s h1')?.textContent.trim() === 'Map to Event'" % DRIVE)
    wait_drive(page, None, 'another open')
    assert norm(page.locator(f'{DRIVE} h1').first.text_content()) == 'Map to Event'
    page.evaluate('closeActionSheet()')
    wait_closed(page, 'closeActionSheet()')

    open_from_hero(page, LEG, 'hero door')
    page.locator(f'{DRIVE} .pwa-back').click()
    wait_closed(page, 'hero door')

    page.locator('#tab-family').click()
    page.wait_for_function("currentView === 'family'")
    block = page.locator('#pane-events .pwa-tl .pwa-ev[aria-label^="%s"]' % SOCCER).first
    block.wait_for(state='visible', timeout=10000)
    block.click()
    page.wait_for_selector('#event-modal', state='visible')
    page.locator('#em-map-btn').click()
    screen = wait_drive(page, None, 'Plan block -> map')
    assert norm(screen.locator('.pwa-back').text_content()) == '‹ Plan', screen.locator('.pwa-back').text_content()
    assert norm(screen.locator('h1').first.text_content()) == 'Map to Event'
    assert page.evaluate('routeContext.legId') is None
    settle(page, "document.querySelector('%s #drive-arrival-card')?.textContent.includes('Riverside fields')" % DRIVE)
    wait_road(page, 'map only')
    view, _ = oracle(page, 'map only')
    assert view['leave'] is None and view['arrival']['place'] == 'Riverside fields', view
    for sel in ('#btn-start-drive', '#btn-arrived', '#btn-send-eta', '#btn-mark-completed', '#btn-drive-cover',
                '#drive-roll', '#drive-prep'):
        assert not visible(page, f'{DRIVE} {sel}'), (sel, 'a leg operation shows on a map-only drive')
    assert page.locator(f'{DRIVE} #sheet-state-2 button[onclick^="openMaps"]').filter(visible=True).count() == 3
    screen.locator('.pwa-back').click()
    wait_closed(page, 'back to Plan')
    assert page.evaluate('currentView') == 'family'
    assert visible(page, '#plan-head'), 'Back did not return to Plan'


def helper_drive(page, mocks):
    """Helper: their own drive opens the screen with Start and Arrived; the
    retro-split options show exactly as today's retroSplitState() decides
    (removing them for a helper would take away something a person can do)."""
    # The helper lands on the drives timeline; the next drive is promoted into
    # the .pwa-next card ("View drive" clicks the row's own handler).
    row = page.locator(f'.pwa-leg-row[data-leg-id="{HELPER_LEG}"] .pwa-row-main').first
    door = row if row.is_visible() else page.locator('.pwa-next button', has_text='View drive').first
    door.click()
    screen = wait_drive(page, HELPER_LEG, 'helper')
    assert norm(screen.locator('.pwa-back').text_content()).startswith('‹ ')
    wait_before(page, 'helper')
    assert norm(screen.locator('#drive-leave-card .pwa-drive-time').text_content()) == '4:05'
    assert visible(page, f'{DRIVE} #btn-start-drive')
    def split_matches(where):
        state = page.evaluate("() => typeof retroSplitState === 'function' ? retroSplitState() : null")
        want = {'.btn-not-staying': state == 'can_split', '.btn-staying-after-all': state == 'can_stay'}
        for sel, shown in want.items():
            got = screen.locator(sel).filter(visible=True).count() > 0
            assert got == shown, (sel, where, 'the retro-split differs from retroSplitState()', state)
    split_matches('before')
    tap_start(page, mocks)
    assert visible(page, f'{DRIVE} #btn-arrived')
    split_matches('on the road')
    screen.locator('.pwa-back').click()
    wait_closed(page, 'helper back')


def keeping_never_drives(page, mocks):
    """The keeping-up adult has no drive rows, no Start drive, no packing."""
    assert page.locator('#myday-content [data-kind="drive"]').count() == 0, 'a keeping-up adult got a drive row'
    assert page.locator('#myday-content .pwa-hero').get_by_role('button', name='Start drive').count() == 0
    kinds = page.evaluate('(window.pwaNeedCards || []).map(c => c.kind)')
    assert 'packing' not in kinds, kinds
    assert depth(page) == 0


def packing_on_my_day(page, mocks):
    """Parent: unconfirmed prep is a Needs-you card; it opens the drive; once
    both items are ticked and Back is tapped, the card is gone."""
    settle(page, "(window.pwaNeedCards || []).some(c => c.kind === 'packing')", timeout=8000)
    cards = page.evaluate('(window.pwaNeedCards || []).map(c => ({kind: c.kind, title: c.title, why: c.why, icon: c.icon}))')
    packing = [c for c in cards if c['kind'] == 'packing']
    assert len(packing) == 1, cards
    assert packing[0]['title'] == 'Pack for Soccer practice' and packing[0]['why'] == 'soccer bag, water · leave 3:40', \
        packing[0]
    assert packing[0]['icon'] == '🎒', packing[0]
    card = page.locator('#myday-content .pwa-need', has_text='Pack for Soccer practice')
    assert card.count() == 1, page.locator('#myday-content .pwa-need').all_text_contents()
    assert 'soccer bag, water · leave 3:40' in norm(card.text_content()), card.text_content()
    card.click()
    screen = wait_drive(page, LEG, 'packing card')
    wait_before(page, 'packing card')
    screen.locator('#drive-prep-items button').nth(0).click()
    with posting(page, r'/api/prep_status$'):
        screen.locator('#drive-prep-items button').nth(1).click()
    assert mocks.last_post(r'/prep_status$')['body'] == {'event_id': 'soccer', 'confirmed': True, 'member_id': 'parent'}
    screen.locator('.pwa-back').click()
    wait_closed(page, 'packing back')
    settle(page, """!(window.pwaNeedCards || []).some(c => c.kind === 'packing')
        && ![...document.querySelectorAll('#myday-content .pwa-need')].some(e => e.textContent.includes('Pack for'))""",
           timeout=8000)
    assert 'packing' not in page.evaluate('(window.pwaNeedCards || []).map(c => c.kind)'), 'the packed card stayed'
    assert page.locator('#myday-content .pwa-need', has_text='Pack for').count() == 0


def ride_row_labels(page):
    return page.evaluate("""() => { const row = document.querySelector('#myday-content .pwa-brief-day [data-kind="ride"]');
        if (!row) return null;
        return [...row.querySelectorAll('button')].map(b => b.textContent.replace(/\\s+/g, ' ').trim())
            .filter(t => /^(Where\\?|Message|(📷 )?Add a moment)$/.test(t)).map(t => t.replace(/^📷 /, '')); }""")


def ride_hero_buttons(page, mocks):
    """The passenger's ride hero carries the ride row's own buttons."""
    if mocks.key == 'parent':
        page.clock.set_fixed_time(NOW_RIDE)
        rerender_brief(page)
    settle(page, "!!document.querySelector('#myday-content .pwa-hero')", timeout=8000)
    picked = page.evaluate("""() => { const n = pwaNextThing(pwaRowsFromDom(document.querySelector('.pwa-brief-day')), new Date());
        return n ? n.kind : null; }""")
    assert picked == 'ride', ('the hero is not the ride', picked)
    row = ride_row_labels(page)
    hero = [t.replace('📷 ', '') for t in hero_buttons(page)]
    if mocks.key == 'parent':
        assert row == ['Where?', 'Message', 'Add a moment'], row
    else:
        assert row and 'Message' in row and 'Add a moment' in row, row
    assert hero == row, ('the ride hero does not carry the row buttons', hero, row)
    assert norm(page.locator('#myday-content .pwa-hero .pwa-btn-primary').text_content()).replace('📷 ', '') == row[0]
    if mocks.key == 'parent':
        with posting(page, r'/api/channels/dm$'):
            page.locator('#myday-content .pwa-hero :is(.pwa-btn-primary, .pwa-btn-secondary)', has_text='Message').click()
        assert mocks.last_post(r'/channels/dm$')['body'] == {'member_id': 'parent', 'other_member_id': 'robin'}
    else:
        with posting(page, r'/api/channels/event$'):
            page.locator('#myday-content .pwa-hero :is(.pwa-btn-primary, .pwa-btn-secondary)', has_text='Add a moment').click()
        body = mocks.last_post(r'/channels/event$')['body']
        assert body.get('event_id') == 'dentist' and body.get('title') == 'Dentist', body
    page.wait_for_function("currentView === 'messages'")


def header_shrinks(page, mocks):
    """Adult header: the date line left; the bell and the avatar right; search,
    sync, theme, switch, push and the critter gone from it (Profile and More
    keep them)."""
    head = 'body > header'
    date = page.locator(f'{head} #pwa-header-date')
    assert date.count() == 1 and date.is_visible(), '#pwa-header-date is not in the header'
    assert norm(date.text_content()) == LONG_DATE, (date.text_content(), LONG_DATE)
    for sel in ('#btn-notif', '#pwa-identity'):
        assert visible(page, f'{head} {sel}'), (sel, 'is not in the header')
    d, bell, me = box(page, f'{head} #pwa-header-date'), box(page, f'{head} #btn-notif'), box(page, f'{head} #pwa-identity')
    assert d['x'] < bell['x'] < me['x'], ('date left, bell then avatar right', d, bell, me)
    assert me['x'] + me['width'] > page.evaluate('innerWidth') - 40, ('the avatar is not top-right', me)
    for sel in ('[aria-label="Search features"]', '#btn-sync', '#btn-theme', '#btn-switch-driver', '#btn-push',
                '#btn-pet', '#driver-name'):
        assert not visible(page, f'{head} {sel}'), (sel, 'still shows in the adult header')
    assert box(page, head)['height'] <= 72, box(page, head)
    # The date line follows the selected day.
    page.locator('#btn-next-day').click()
    page.wait_for_function('mydayOffset === 1')
    settle(page, "(t) => document.getElementById('pwa-header-date').textContent.trim() === t", arg=LONG_TOMORROW)
    assert norm(date.text_content()) == LONG_TOMORROW, date.text_content()
    page.locator('#btn-prev-day').click()
    page.wait_for_function('mydayOffset === 0')
    settle(page, "(t) => document.getElementById('pwa-header-date').textContent.trim() === t", arg=LONG_DATE)
    # Profile keeps every door the header gave up, and carries the name.
    page.locator(f'{head} #pwa-identity').click()
    page.wait_for_selector('#pwa-profile', state='visible')
    assert 'Alex Morgan' in text(page, '#pwa-profile'), text(page, '#pwa-profile')
    features = page.evaluate("[...document.querySelectorAll('#pwa-profile [data-feature]')].map(b => b.dataset.feature)")
    for want in ('refresh', 'theme', 'switch'):
        assert want in features, (want, features)
    if page.evaluate("typeof openPetEditor === 'function'"):
        assert 'critter' in features, features
    push_shown = page.evaluate("!document.getElementById('btn-push').classList.contains('hidden')")
    assert ('push' in features) == push_shown, (features, push_shown)
    gets = mocks.schedule_gets
    with page.expect_response(lambda r: '/api/schedule' in r.url, timeout=10000):
        page.locator('#pwa-profile [data-feature="refresh"]').click()
    assert mocks.schedule_gets > gets
    page.keyboard.press('Escape')
    page.evaluate("document.getElementById('pwa-profile').open && document.getElementById('pwa-profile').close()")
    page.evaluate("document.getElementById('btn-push').classList.remove('hidden')")
    page.locator(f'{head} #pwa-identity').click()
    page.wait_for_selector('#pwa-profile', state='visible')
    assert page.locator('#pwa-profile [data-feature="push"]').count() == 1, 'Profile lost Enable notifications'
    page.evaluate("document.getElementById('pwa-profile').close(); document.getElementById('btn-push').classList.add('hidden')")
    # The bell still opens the notifications list.
    page.locator(f'{head} #btn-notif').click()
    page.wait_for_selector('#notif-modal', state='visible')
    page.evaluate('toggleNotifications()')
    page.wait_for_selector('#notif-modal', state='hidden')
    # Search reaches More's field.
    page.locator('#tab-more').click()
    page.wait_for_function("currentView === 'more'")
    assert visible(page, '#pwa-feature-search'), "More's search field is gone"


def kid_unchanged(page, mocks):
    """A kid keeps the bottom sheet (no PwaNav entry) and their header."""
    page.wait_for_selector('.child-greeting')
    assert visible(page, '.child-pickup') and 'Alex' in text(page, '.child-pickup'), 'the kid ride card changed'
    assert not visible(page, '#myday-content .pwa-hero'), 'a kid got the adult hero'
    assert visible(page, 'body > header #driver-name'), 'the kid header lost the name'
    assert not visible(page, '#pwa-header-date'), 'the kid header got the adult date line'
    assert not visible(page, 'body > header [aria-label="Search features"]')
    page.evaluate("openActionSheet('Home', 'Riverside fields', 'Drive to Riverside fields', 'practice', 'init_practice')")
    page.wait_for_selector('#action-sheet', state='visible')
    assert text(page, '#sheet-title') == 'Your drive', text(page, '#sheet-title')
    assert depth(page) == 0, 'a kid drive pushed a PwaNav screen'
    assert page.locator(DRIVE).count() == 0
    assert page.evaluate("document.getElementById('action-sheet-content').parentElement.id") == 'action-sheet'
    page.evaluate('closeActionSheet()')
    page.wait_for_selector('#action-sheet', state='hidden')


def widths_and_dark(page, mocks):
    """Both moments at 360 and 390 without overflow, and in dark through the
    tokens."""
    open_from_hero(page, LEG, 'widths')
    wait_before(page, 'widths')
    light_ink = page.evaluate(TOKEN_PROBE, '--pwa-ink')
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        page.wait_for_function('(w) => innerWidth === w', arg=width)
        no_overflow(page, f'before {width}')
        assert page.locator(DRIVE).evaluate('e => e.scrollWidth <= e.clientWidth'), \
            page.locator(DRIVE).evaluate('e => [e.scrollWidth, e.clientWidth]')
        assert page.locator('#action-sheet-content').evaluate('e => e.scrollWidth <= e.clientWidth')
    page.evaluate("applyTheme('dark')")
    dark_ink = page.evaluate(TOKEN_PROBE, '--pwa-ink')
    assert dark_ink != light_ink, 'the ink token did not change for dark'
    time_color = page.locator(f'{DRIVE} .pwa-drive-time').evaluate('e => getComputedStyle(e).color')
    assert time_color == dark_ink, ('the leave time is not drawn in the ink token', time_color, dark_ink)
    card_bg = page.locator(f'{DRIVE} #drive-leave-card').evaluate('e => getComputedStyle(e).backgroundColor')
    assert card_bg not in ('rgb(255, 255, 255)', 'rgba(0, 0, 0, 0)'), ('the leave card stayed white in dark', card_bg)
    no_overflow(page, 'before dark')
    shot(page, 'drive-before-dark.png')
    page.evaluate("applyTheme('light')")
    page.clock.set_fixed_time(NOW_ROAD)
    tap_start(page, mocks)
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        page.wait_for_function('(w) => innerWidth === w', arg=width)
        no_overflow(page, f'road {width}')
        assert page.locator(DRIVE).evaluate('e => e.scrollWidth <= e.clientWidth')
    page.evaluate("applyTheme('dark')")
    no_overflow(page, 'road dark')
    shot(page, 'drive-road-dark.png')
    page.evaluate("applyTheme('light')")
    page.locator(f'{DRIVE} .pwa-back').click()
    wait_closed(page, 'widths back')


# --- the lane's lifecycle ----------------------------------------------------
# The ruling (slice 6 ledger, R34 #10 / R34-r1): a tab switch while a drive is
# IN PROGRESS dismisses the screen but keeps the live lane (the 45 s ping) and
# the resume record; only an explicit close of THAT drive, its completion or
# arrival stops them, and a member switch or a sign-out always does. The clock
# is the page clock: run_for fires the lane's setInterval(DRIVE_PING_MS).

PING_MS = 45000
LANE = """() => ({timer: driveLiveTimer !== null,
    context: driveLiveContext ? {legId: driveLiveContext.legId, memberId: driveLiveContext.memberId} : null,
    resume: JSON.parse(localStorage.getItem('chauffeur_drive_resume') || 'null'),
    member: selectedMemberId, view: currentView, depth: PwaNav.depth()})"""
# One position read and one mocked round trip: a ping the interval fired has
# reached its route (and the recorder) by the time this resolves.
FLUSH = """async () => {
    await new Promise(r => navigator.geolocation.getCurrentPosition(() => r(), () => r(), {timeout: 8000}));
    await fetch(apiBase + 'api/settings');
}"""


def lane(page):
    return page.evaluate(LANE)


def tick(page, mocks, expect_ping, where=''):
    """Advance the page clock past one ping interval; answer the pings it sent."""
    before = len(mocks.posts_to(r'/api/drive_status/ping$'))
    if expect_ping:
        try:
            with posting(page, r'/api/drive_status/ping$'):
                page.clock.run_for(PING_MS + 1000)
        except Exception:
            raise AssertionError((where, 'no ping was POSTed in the 46 s after', lane(page)))
    else:
        page.clock.run_for(PING_MS + 1000)
        page.evaluate(FLUSH)
    return mocks.posts_to(r'/api/drive_status/ping$')[before:]


def start_live(page, mocks, where):
    """Hero -> Start drive with a fix: the lane runs (one ping at once) and the
    resume record holds the leg."""
    open_from_hero(page, LEG, where)
    wait_before(page, where)
    with posting(page, r'/api/drive_status/ping$'):
        tap_start(page, mocks, with_fix=True)
    state = lane(page)
    assert state['timer'] and state['context'] == {'legId': LEG, 'memberId': 'parent'}, (where, state)
    assert state['resume'] and state['resume'].get('legId') == LEG, (where, state)


def lane_kept(page, mocks, where):
    """The background lane is still the original leg's: timer, context, resume,
    and a ping for LEG as the parent within the next interval."""
    state = lane(page)
    assert state['timer'], (where, 'the live lane (driveLiveTimer) was stopped', state)
    assert state['context'] == {'legId': LEG, 'memberId': 'parent'}, (where, 'driveLiveContext changed', state)
    assert state['resume'] and state['resume'].get('legId') == LEG, \
        (where, 'the resume record no longer holds the running leg', state)
    pings = tick(page, mocks, True, where)
    assert pings and all(p['body'] == {'leg_id': LEG, 'member_id': 'parent', 'lat': FIX['latitude'],
                                       'lng': FIX['longitude'], 'accuracy': FIX['accuracy']} for p in pings), \
        (where, pings)
    state = lane(page)
    assert state['resume'] and state['resume'].get('legId') == LEG, (where, 'the resume went after the ping', state)


def lane_stopped(page, mocks, where):
    state = lane(page)
    assert not state['timer'] and state['context'] is None, (where, 'the live lane still runs', state)
    assert state['resume'] is None, (where, 'the resume record survived', state)
    pings = tick(page, mocks, False, where)
    assert not pings, (where, 'a ping went out after the lane stopped', pings)


def open_row(page, leg, where):
    if page.locator('#myday-content .pwa-brief-day.is-collapsed').count():
        page.locator('#myday-content .pwa-brief-expand').click()
    row = page.locator(f'#myday-content .pwa-brief-day .pwa-leg-row[data-leg-id="{leg}"] .pwa-row-main').first
    row.wait_for(state='visible', timeout=10000)
    row.click()
    return wait_drive(page, leg, where)


def to_tab(page, tab, view):
    page.locator(f'#tab-{tab}').click()
    page.wait_for_function('(v) => currentView === v', arg=view)
    settle(page, "PwaNav.depth() === 0 && !document.querySelector('%s')" % DRIVE)
    assert depth(page) == 0 and page.locator(DRIVE).count() == 0, (tab, 'the drive screen stayed up', lane(page))


def sign_in_as_parent(page):
    """Put the parent's sign-in back (a member switch or clearDriver replaced
    it); the next fresh() reload boots as the parent again."""
    page.evaluate("""(v) => Object.entries(v).forEach(([k, val]) => localStorage.setItem(k, val))""",
                  {'chauffeur_member_id': 'parent', 'chauffeur_member_token': storage.create_member_token('parent'),
                   'chauffeur_member_token_for': 'parent', 'chauffeur_driver_id': 'd1'})


def tab_switch_keeps_the_lane(page, mocks):
    """Start, tap Plan: the screen goes, the lane and the resume stay (a ping
    within the next interval). My Day's row reopens it on the road with the
    live banner; the explicit Back stops the lane and forgets the resume."""
    start_live(page, mocks, 'tab switch')
    to_tab(page, 'family', 'family')
    lane_kept(page, mocks, 'after the tab switch to Plan')
    to_tab(page, 'myday', 'myday')
    wait_brief(page)
    lane_kept(page, mocks, 'back on My Day')
    open_row(page, LEG, 'reopened from My Day')
    wait_road(page, 'reopened from My Day')
    settle(page, "!!document.getElementById('drive-live')?.checkVisibility() && driveLiveTimer !== null")
    assert visible(page, f'{DRIVE} #drive-live'), 'the live banner is not on the reopened drive'
    assert lane(page)['timer'], ('the reopened drive has no live lane', lane(page))
    page.locator(f'{DRIVE} .pwa-back').click()
    wait_closed(page, 'explicit close after the reopen')
    lane_stopped(page, mocks, 'after the explicit close')


def other_drive_or_map_keeps_the_lane(page, mocks):
    """Review I-2: with a drive running in the background, a map-only screen
    (the event dialog's map button) or another leg's drive opened and closed
    must leave the running lane and its resume record alone."""
    start_live(page, mocks, 'map over a running lane')
    to_tab(page, 'family', 'family')
    page.evaluate("openActionSheet('', 'Aquatic center', 'Map to Event')")
    screen = wait_drive(page, None, 'map-only over a running lane')
    assert norm(screen.locator('h1').first.text_content()) == 'Map to Event'
    screen.locator('.pwa-back').click()
    settle(page, "PwaNav.depth() === 0 && !document.querySelector('%s')" % DRIVE)
    assert depth(page) == 0 and page.evaluate('currentView') == 'family', lane(page)
    lane_kept(page, mocks, 'after a map-only screen opened and closed')
    # Another leg (the swim drive the fixture serves a sheet for).
    page.evaluate("openActionSheet('Home', 'Aquatic center', 'Drive to Aquatic center', 'swim', '%s')" % HELPER_LEG)
    screen = wait_drive(page, HELPER_LEG, 'another leg over a running lane')
    screen.locator('.pwa-back').click()
    settle(page, "PwaNav.depth() === 0 && !document.querySelector('%s')" % DRIVE)
    assert depth(page) == 0, lane(page)
    lane_kept(page, mocks, 'after another leg opened and closed')


def switch_and_sign_out_stop_the_lane(page, mocks):
    """A member switch (selectDriver to Robin) and a sign-out (clearDriver)
    each stop the lane and forget the resume; no ping ever carries Robin. Both
    happen with the drive in the BACKGROUND (after a tab switch), so nothing
    but the switch and the sign-out themselves can stop the lane (with the
    screen up, closeActionSheet's restore would stop it on its own)."""
    try:
        start_live(page, mocks, 'member switch')
        to_tab(page, 'family', 'family')
        assert lane(page)['timer'], ('the tab switch stopped the lane', lane(page))
        page.evaluate("localStorage.setItem('chauffeur_pin_offered_robin', '1')")
        pings_before = len(mocks.posts_to(r'/api/drive_status/ping$'))
        page.evaluate("() => { selectDriver('d2'); }")
        page.wait_for_function("selectedMemberId === 'robin'", timeout=10000)
        settle(page, "driveLiveTimer === null && driveLiveContext === null && PwaNav.depth() === 0")
        state = lane(page)
        assert state['member'] == 'robin' and state['depth'] == 0, ('the switch left the drive up', state)
        lane_stopped(page, mocks, 'after the switch to Robin')
        since = mocks.posts_to(r'/api/drive_status/ping$')[pings_before:]
        assert not [p for p in since if (p['body'] or {}).get('member_id') == 'robin'], \
            ('a ping carried the new member for the old leg', since)
        assert not since, ('a ping went out after the member switch', since)

        sign_in_as_parent(page)
        fresh(page, mocks)
        start_live(page, mocks, 'sign out')
        to_tab(page, 'family', 'family')
        assert lane(page)['timer'], ('the tab switch stopped the lane', lane(page))
        pings_before = len(mocks.posts_to(r'/api/drive_status/ping$'))
        page.evaluate('clearDriver()')
        page.wait_for_function('selectedMemberId === null')
        state = lane(page)
        assert state['depth'] == 0, ('the sign-out left the drive up', state)
        lane_stopped(page, mocks, 'after the sign-out')
        assert not mocks.posts_to(r'/api/drive_status/ping$')[pings_before:]
    finally:
        sign_in_as_parent(page)


def argyle_over_drive_close(page, mocks):
    """closeActionSheet() with the Argyle overlay over the drive: the overlay
    and the screen both go, history lands on the root (no pwaOverlay, no
    pwaDepth > 0), and the next push is popped by exactly one Back."""
    open_from_hero(page, LEG, 'argyle over drive')
    wait_before(page, 'argyle over drive')
    assert page.evaluate("typeof window.PwaArgyle?.open === 'function'"), 'PwaArgyle is not loaded'
    page.evaluate("() => { PwaArgyle.open({mode: 'type'}); }")
    page.wait_for_function("PwaArgyle.isOpen() && history.state?.pwaOverlay === 'argyle'")
    assert depth(page) == 1, 'opening Argyle popped the drive'
    page.evaluate('closeActionSheet()')
    settle(page, """!PwaArgyle.isOpen() && PwaNav.depth() === 0
        && !(history.state && (history.state.pwaOverlay || history.state.pwaDepth > 0))""", timeout=8000)
    state = page.evaluate("""() => ({open: PwaArgyle.isOpen(), depth: PwaNav.depth(), history: history.state,
        overlay: document.documentElement.dataset.pwaArgyle === '1'})""")
    assert not state['open'] and not state['overlay'], ('the Argyle overlay stayed open', state)
    assert state['depth'] == 0, ('the drive screen stayed', state)
    hist = state['history'] or {}
    assert not hist.get('pwaOverlay') and not (hist.get('pwaDepth') or 0) > 0, ('history did not land on the root', state)
    wait_closed(page, 'closeActionSheet over Argyle')
    assert page.evaluate('currentView') == 'myday'
    # History is in step: one push, one Back.
    page.evaluate("PwaNav.push({id: 'probe', title: 'Probe', render(body) { body.textContent = 'probe'; }})")
    page.wait_for_function("PwaNav.depth() === 1 && history.state?.pwaDepth === 1", timeout=5000)
    url = page.url
    page.go_back()
    settle(page, "PwaNav.depth() === 0 && !document.querySelector('#pwa-stack .pwa-screen')")
    after = page.evaluate("""() => ({depth: PwaNav.depth(), screens: document.querySelectorAll('#pwa-stack .pwa-screen').length,
        view: currentView, history: history.state, argyle: PwaArgyle.isOpen()})""")
    assert page.url == url, ('Back left the app', page.url, url)
    assert after['depth'] == 0 and after['screens'] == 0 and after['view'] == 'myday' and not after['argyle'], \
        ('one Back did not pop the pushed screen (history desynced)', after)
    hist = after['history'] or {}
    assert not hist.get('pwaOverlay') and not (hist.get('pwaDepth') or 0) > 0, after


# --- the run -----------------------------------------------------------------

def wait_app(page):
    page.wait_for_function("""() => !!document.querySelector('#screen-schedule:not(.hidden)')
        || !!document.getElementById('pin-modal-skip')?.checkVisibility()""", timeout=20000)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function("typeof membersData !== 'undefined' && membersData.length > 0")


def ready(page, mocks):
    wait_app(page)
    if mocks.key in ('parent', 'keeping'):
        wait_brief(page)
    if mocks.key == 'parent':
        settle(page, "!!document.querySelector('#myday-content .pwa-hero .pwa-btn-primary')", timeout=8000)
    if mocks.key == 'helper':
        page.wait_for_selector(f'.pwa-leg-row[data-leg-id="{HELPER_LEG}"]', state='attached', timeout=10000)
    if mocks.key == 'navigator':
        page.wait_for_selector('.child-greeting')


def fresh(page, mocks):
    """Each scenario starts from a reload: no drive open, no resume, today,
    light, the server state reset."""
    mocks.reset()
    page.clock.set_fixed_time(NOW)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.evaluate("""() => { localStorage.removeItem('chauffeur_drive_resume'); localStorage.setItem('chauffeur_view', 'myday');
        localStorage.setItem('chauffeur_theme', 'light'); localStorage.setItem('chauffeur_myday_day_open', '1'); }""")
    page.reload(wait_until='domcontentloaded')
    ready(page, mocks)


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
              'chauffeur_member_token_for': key, 'chauffeur_view': 'myday', 'chauffeur_theme': 'light',
              'chauffeur_myday_day_open': '1'}
    if driver:
        values['chauffeur_driver_id'] = driver
    # Once per tab: the reloads must keep the stored sign-in and the resume.
    page.add_init_script("if (!sessionStorage.getItem('chf_test_seeded')) { Object.entries(" + json.dumps(values)
                         + ").forEach(([k, v]) => localStorage.setItem(k, v)); sessionStorage.setItem('chf_test_seeded', '1'); }")
    page.add_init_script(NAV_CAPTURE)
    mocks = Mocks(key, driver)
    mocks.install(page)
    if role == 'child':
        # Registered last, so the child's own day and routines win.
        from pwa_child_checks import install_child_data
        install_child_data(page, key, DAY)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    ready(page, mocks)
    assert page.evaluate('selectedMemberId') == key
    assert page.evaluate('currentMemberRole()') == role
    return mocks, failed_assets


def page_errors(served, key):
    errors = list(served.errors())
    if errors:
        errors = errors + [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key]
    return errors


SCENARIOS = {
    'parent': [before_moment, on_the_road, arrived_resolved, arrived_unresolved, resume_after_reload,
               opens_from_every_door, packing_on_my_day, ride_hero_buttons, header_shrinks, widths_and_dark,
               tab_switch_keeps_the_lane, other_drive_or_map_keeps_the_lane, switch_and_sign_out_stop_the_lane,
               argyle_over_drive_close],
    'helper': [helper_drive],
    'keeping': [keeping_never_drives, ride_hero_buttons],
    'navigator': [kid_unchanged],
}


def run():
    global SHOTS
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
        SHOTS = (Path(__file__).resolve().parent / 'probe_shots' / 'pwa_slice6'
                 if output.lower() in ('1', 'true', 'yes', 'on') else Path(output))
        SHOTS.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in os.environ.get('PWA_REVIEW_SCENARIO', '').split(',') if s.strip()}
    keep_going = bool(os.environ.get('PWA_KEEP_GOING'))
    failures = []
    try:
        for key, role, driver in PROFILES:
            if os.environ.get('PWA_REVIEW_PROFILE') and key != os.environ['PWA_REVIEW_PROFILE']:
                continue
            scenarios = [s for s in SCENARIOS[key] if not only or s.__name__ in only]
            if not scenarios:
                continue
            with served.browser(reduced_motion='reduce', has_touch=True, geolocation=FIX,
                                permissions=['geolocation']) as page:
                mocks, failed_assets = boot(served, page, key, role, driver)
                for i, scenario in enumerate(scenarios):
                    try:
                        if i:
                            fresh(page, mocks)
                        scenario(page, mocks)
                    except Exception:
                        bad = sorted({f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key})
                        print('FAIL', key, scenario.__name__, '| page errors:', list(served.errors())[:5],
                              '| 4xx/5xx:', bad[:8], flush=True)
                        if not keep_going:
                            raise
                        traceback.print_exc()
                        failures.append((key, scenario.__name__))
                        continue
                    print('  ok', key, scenario.__name__, flush=True)
                errors = page_errors(served, key)
                assert not errors and not failed_assets, (key, errors, failed_assets)
                print('ok', key, flush=True)
    finally:
        served.stop()
    assert not failures, failures


if __name__ == '__main__':
    run()
