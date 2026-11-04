"""Household, cards then focus, in the served PWA (slice 3, Task 4).

The adult Household tab is five cards ranked by what needs you most (Chores,
Rewards, Tasks, Lists, Projects & programs); a tap pushes a full screen through
PwaNav that ADOPTS today's builders' nodes (renderChores' #chores-content,
renderHouseLists' #house-lists, the Alpine #projects-container) and shows one
segment of them at a time. Threads leave Household for Plan's Family pane and
My Day's pile; the household to-do list reaches the phone.

Written before the view exists (Task 5 makes it green), so its first failure
is the missing `.pwa-house-card` on the parent's Household tab.

Every read the view makes is mocked with page.route (members and auth are
seeded and served for real); every write goes through a recorder and the
scenario asserts its path and body. The card order is checked twice: against
pwaHouseholdCards() evaluated IN THE PAGE over the payloads the mocks served,
and against the order those payloads must produce.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_household_live.py
PWA_REVIEW_PROFILE=<key> runs one profile. PWA_REVIEW_OUTPUT=1 writes the
screenshots to tests/probe_shots/pwa_slice3 (gitignored); any other value is
taken as the output directory.
"""
import atexit
import copy
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
DATA = tempfile.mkdtemp(prefix='chauffeur_household_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + timedelta(days=1)).strftime('%Y-%m-%d')
TWO_DAYS_AGO = (NOW - timedelta(days=2)).strftime('%Y-%m-%d')
IN_THREE = (NOW + timedelta(days=3)).strftime('%Y-%m-%d')
IN_FIVE = (NOW + timedelta(days=5)).strftime('%Y-%m-%d')

PROFILES = [('parent', 'parent', 'd1'), ('adult', 'adult', 'd2'), ('keeping', 'parent', None),
            ('lists_only', 'adult', 'd6'), ('granted', 'adult', None), ('helper', 'helper', 'd3')]
NAMES = {'parent': 'Alex Morgan', 'adult': 'Robin Lee', 'keeping': 'Casey Morgan',
         'lists_only': 'Jo Ellis', 'granted': 'June Ellis', 'helper': 'Nana Bea'}
THREAD = {}
SCREEN_TITLES = {'chores': 'Chores', 'rewards': 'Rewards', 'tasks': 'Tasks', 'lists': 'Lists',
                 'projects': 'Projects'}
ALL_CARDS = {'chores', 'rewards', 'tasks', 'lists', 'projects'}
BAD_RESPONSES = []
SHOTS = None


def seed():
    for key, role, driver in PROFILES:
        member = {'id': key, 'name': NAMES[key], 'role': role, 'driver_id': driver,
                  'color_code': '#287a72'}
        if key == 'keeping':
            member['scope'] = {'preset': 'keeping_up'}
        if key == 'lists_only':
            # services/scope.py _table_value applies scope.overrides[facet]:
            # the chores door closes, a shared list reopens the tab (lists half).
            member['scope'] = {'preset': 'household_adult', 'overrides': {'chores.board': 'none'}}
        if key == 'granted':
            # lists.shopping is an INSTANCE facet: `none` means no household lists,
            # but GET /api/shopping/lists still returns the ones shared with her
            # (main.py list_shopping_lists). The page must never gate that read
            # on the facet, or the grandmother's grocery list vanishes.
            member['scope'] = {'preset': 'household_adult',
                               'overrides': {'chores.board': 'none', 'lists.shopping': 'none'}}
        storage.add_member(member)
        if driver:
            storage.add_driver({'id': driver, 'name': NAMES[key], 'home_location': 'Home',
                                'color_code': '#287a72'})
    # A real thread, so the situation card the mock serves has the server's
    # own shape (services/situations.view) and its detail routes answer.
    from services import threads
    THREAD['id'] = threads.create('Deck permit', owner_member_id='parent',
                                  next_action='Call the county', created_by='parent')


def thread_situation():
    """GET /api/situations?kinds=thread row for the parent's thread, in group
    `now` (needs you), built by the server's own view()."""
    base = {'kind': 'thread', 'id': THREAD['id'], 'title': 'Deck permit', 'subject': None,
            'state': 'open', 'since': NOW.timestamp(), 'people': [], 'due': None,
            'status_note': 'Call the county', 'note_source': 'fallback', 'note_ts': None,
            'next_step': None, 'options': [], 'asks': [], 'needs_attention': True, 'group': 'now',
            'owner_member_id': None, 'sensitivity': None, 'severity': None, 'confidence': None, 'rev': 0}
    try:
        from services import situations as _sit
        real = _sit.view('thread', THREAD['id'], storage.get_member('parent')) or {}
        json.dumps(real)
    except Exception:
        real = {}
    out = dict(base, **real)
    out.update(group='now', needs_attention=True)
    return out


# --- fixtures ----------------------------------------------------------------

def schedule_for(driver):
    event = {'id': 'soccer', 'title': 'Soccer practice', 'start': DAY + 'T16:00:00',
             'end': DAY + 'T17:00:00', 'location': 'Riverside fields', 'calendar_ids': [],
             'event_type': 'activity'}
    later = dict(event, id='piano', title='Piano lesson', start=DAY + 'T17:30:00',
                 end=DAY + 'T18:00:00', location='Music studio')
    return {'events': [event, later], 'assignments': {'soccer': driver, 'piano': driver},
            'home_location': 'Home', 'calendar_metadata': {},
            'initial_edges': {driver: {'soccer': {'travel_mins': 20, 'buffer_before_mins': 5}}} if driver else {},
            'route_edges': {}, 'final_edges': {}}


def household_task(tid, title, due):
    """A GET /api/household-tasks row as main.py list_household_tasks shapes it."""
    return {'id': tid, 'title': title, 'notes': '', 'due_date': due, 'assigned_to': None,
            'created_by': 'parent', 'status': 'open', 'completed_at': None, 'completed_by': None,
            'recurrence': None, 'created_at': NOW.timestamp() - 86400 * 7,
            'past_due': bool(due and due < DAY), 'due_today': bool(due and due == DAY),
            'assigned_to_name': None, 'assigned_to_assist': False}


def shopping_item(iid, name, list_id, checked=False):
    return {'id': iid, 'list_id': list_id, 'name': name, 'qty': None, 'note': None,
            'added_by': 'parent', 'added_via': 'manual', 'is_checked': checked, 'image_id': None,
            'claims': [], 'buy_on': None, 'deadline': None}


GROCERY_NAMES = ['Milk', 'Eggs', 'Bread', 'Apples', 'Bananas', 'Rice', 'Pasta', 'Chicken thighs',
                 'Spinach', 'Yogurt', 'Cheddar', 'Coffee']
COSTCO_NAMES = ['Paper towels', 'Olive oil', 'Dish soap', 'Frozen berries']


class Mocks:
    """One profile's server, as page.route answers it. State is mutable so a
    write changes what the next read returns; `calls` records every write."""

    def __init__(self, key, driver):
        self.key = key
        self.driver = driver
        self.calls = []
        household = key in ('parent', 'adult', 'keeping')
        first = NAMES[key].split()[0]
        # The adult-shell chores: one claimed by the viewer, one done waiting
        # on a parent's verify, one open to anybody.
        self.chores = [dict(id='dishwasher', title='Unload the dishwasher', description='Kitchen', points=10,
                            state='claimed', claimed_by=key, claimed_by_name=first),
                       dict(id='recycling', title='Take out recycling', points=15, state='done',
                            claimed_by='navigator', claimed_by_name='Sam'),
                       dict(id='plants', title='Water the plants', points=5, state='open',
                            eligible_member_ids=[])] if household else []
        self.balances = [{'member_id': 'navigator', 'name': 'Sam', 'balance': 120, 'color_code': '#e07a5f'},
                         {'member_id': 'kate', 'name': 'Kate', 'balance': 45, 'color_code': '#3d85c6'}] if household else []
        # One plain reward and one family goal 180 of 300 pledged (60%).
        self.rewards = [{'id': 'movie', 'title': 'Movie night', 'cost': 50, 'pooled': False},
                        {'id': 'zoo', 'title': 'Zoo trip', 'description': '', 'cost': 300, 'pooled': True,
                         'pool': {'cost': 300, 'pledged': 180, 'remaining': 120, 'funded': False, 'min_share': 0,
                                  'contributions': [{'member_id': 'navigator', 'member_name': 'Sam',
                                                     'amount': 180, 'color_code': '#e07a5f'}]}}] if household else []
        self.redemptions = [{'id': 'red1', 'reward_id': 'movie', 'reward_title': 'Movie night',
                             'member_id': 'navigator', 'member_name': 'Sam', 'cost': 50,
                             'state': 'pending'}] if household else []
        # Served later-first on purpose: the builder sorts overdue to the top.
        self.tasks = [household_task('ht-filter', 'Change the furnace filter', IN_THREE),
                      household_task('ht-reg', 'Renew car registration', TWO_DAYS_AGO)] \
            if key in ('parent', 'adult', 'lists_only') else []
        groceries = {'id': 'groceries', 'name': 'Groceries', 'is_default': True, 'audience': 'household', 'shared_with': []}
        costco = {'id': 'costco', 'name': 'Costco', 'is_default': False, 'audience': 'household', 'shared_with': []}
        self.list_meta = {'parent': [groceries, costco], 'adult': [groceries, costco],
                          'lists_only': [groceries], 'granted': [groceries]}.get(key, [])
        self.items = {'groceries': [shopping_item(f'g{i}', n, 'groceries') for i, n in enumerate(GROCERY_NAMES)]
                      + [shopping_item('g-done-1', 'Butter', 'groceries', True),
                         shopping_item('g-done-2', 'Oranges', 'groceries', True)],
                      'costco': [shopping_item(f'c{i}', n, 'costco') for i, n in enumerate(COSTCO_NAMES)]}
        self.projects = [{'id': 'prj-deck', 'title': 'Rebuild the deck', 'goal': 'a safe deck', 'done_when': 'we eat on it',
                          'owner_member_id': 'parent', 'created_by': 'parent', 'audience': 'household', 'shared_with': [],
                          'state': 'active', 'lane': 'needs_you', 'card_next': 'Pick a contractor',
                          'steps_done': 1, 'steps_total': 3, 'pieces': [], 'steps': [], 'has_program': False,
                          'needs_plan': False},
                         {'id': 'prj-garden', 'title': 'Spring garden', 'goal': 'vegetables', 'done_when': 'first harvest',
                          'owner_member_id': 'adult', 'created_by': 'adult', 'audience': 'household', 'shared_with': [],
                          'state': 'paused', 'lane': 'paused', 'card_next': '', 'steps_done': 0, 'steps_total': 0,
                          'pieces': [], 'steps': [], 'has_program': False, 'needs_plan': False}] if key != 'helper' else []
        self.programs = [dict(id='practice', member_id='adult', member_name=NAMES['adult'], title='Strength training',
                              state='active', progress={}, emissions={})] if key != 'helper' else []
        self.windows = [dict(program_id='practice', member_id='adult', member_name=NAMES['adult'], date=TOMORROW,
                             time_start='16:30', time_end='17:00', title='Strength training',
                             session_label='Push and core', steps=['Warm up', 'Push-ups'], logged=False)] \
            if key != 'helper' else []
        self.thread = thread_situation() if key == 'parent' else None

    # --- derived reads ---
    def open_tasks(self):
        return [copy.deepcopy(t) for t in self.tasks if t['status'] == 'open']

    def lists(self):
        out = []
        for meta in self.list_meta:
            items = self.items.get(meta['id'], [])
            open_count = sum(1 for i in items if not i['is_checked'])
            out.append(dict(meta, open_count=open_count, checked_count=len(items) - open_count))
        return out

    def runs(self):
        """GET /api/shopping/runs as services/shopping.item_runs shapes it; the
        shop day is TOMORROW. pwaHouseholdCards reads `.runs.next`."""
        open_items = [i for i in self.items['groceries'] if not i['is_checked']]
        return {'shop_date': TOMORROW,
                'groups': [{'key': 'next', 'date': TOMORROW, 'items': open_items, 'label': "Tomorrow's shop"}],
                'runs': {'guess': TOMORROW, 'scheduled': None, 'next': TOMORROW},
                'late': [], 'top_up': False, 'counts': {'next': len(open_items)}}

    def running_programs(self):
        return [p for p in self.programs if p['state'] in ('active', 'paused')]

    def oracle_inputs(self):
        return {'chores': self.chores, 'balances': self.balances, 'rewards': self.rewards,
                'redemptions': self.redemptions, 'tasks': self.open_tasks(), 'lists': self.lists(),
                'runs': self.runs()['runs'], 'projects': self.projects, 'programs': self.running_programs(),
                'windows': self.windows, 'today': DAY}

    # --- the recorder ---
    def record(self, route):
        req = route.request
        try:
            body = req.post_data_json
        except Exception:
            body = req.post_data
        self.calls.append({'method': req.method, 'path': urlparse(req.url).path, 'body': body})
        return self.calls[-1]

    def last_call(self, method, path_pattern):
        hits = [c for c in self.calls if c['method'] == method and re.search(path_pattern, c['path'])]
        assert hits, (method, path_pattern, self.calls)
        return hits[-1]

    # --- handlers ---
    def chore_action(self, route):
        if route.request.method != 'POST':
            return route.continue_()
        call = self.record(route)
        cid, verb = call['path'].rstrip('/').split('/')[-2:]
        for c in self.chores:
            if c['id'] == cid:
                if verb == 'verify':
                    c['state'] = 'verified'
                elif verb == 'done':
                    c['state'] = 'done'
                elif verb == 'claim':
                    c.update(state='claimed', claimed_by=self.key, claimed_by_name=NAMES[self.key].split()[0])
        route.fulfill(json={})

    def decide(self, route):
        if route.request.method != 'POST':
            return route.continue_()
        call = self.record(route)
        rid = call['path'].rstrip('/').split('/')[-2]
        self.redemptions[:] = [r for r in self.redemptions if r['id'] != rid]
        route.fulfill(json={'status': 'success'})

    def household_tasks(self, route):
        req = route.request
        if req.method == 'POST':
            call = self.record(route)
            body = call['body'] if isinstance(call['body'], dict) else {}
            row = household_task('ht-new', body.get('title') or '', body.get('due_date') or None)
            row['assigned_to'] = body.get('assigned_to') or None
            self.tasks.append(row)
            return route.fulfill(json={'status': 'success', 'id': 'ht-new'})
        if req.method != 'GET':
            return route.continue_()
        route.fulfill(json=self.open_tasks())

    def complete_task(self, route):
        if route.request.method != 'POST':
            return route.continue_()
        call = self.record(route)
        tid = call['path'].rstrip('/').split('/')[-2]
        for t in self.tasks:
            if t['id'] == tid:
                t['status'] = 'done'
        route.fulfill(json={'status': 'success'})

    def shopping_lists(self, route):
        if route.request.method != 'GET':
            return route.continue_()
        route.fulfill(json=self.lists())

    def shopping_items(self, route):
        req = route.request
        if req.method == 'POST':
            call = self.record(route)
            body = call['body'] if isinstance(call['body'], dict) else {}
            lid = body.get('list_id') or 'groceries'
            item = shopping_item('new-' + str(len(self.calls)), body.get('name') or '', lid)
            self.items.setdefault(lid, []).append(item)
            return route.fulfill(json=item)
        if req.method != 'GET':
            return route.continue_()
        lid = parse_qs(urlparse(req.url).query).get('list_id', ['groceries'])[0]
        route.fulfill(json=copy.deepcopy(self.items.get(lid, [])))

    def shopping_item(self, route):
        if route.request.method != 'PATCH':
            return route.continue_()
        call = self.record(route)
        iid = call['path'].rstrip('/').split('/')[-1]
        body = call['body'] if isinstance(call['body'], dict) else {}
        for items in self.items.values():
            for i in items:
                if i['id'] == iid and 'is_checked' in body:
                    i['is_checked'] = bool(body['is_checked'])
        route.fulfill(json={'status': 'success'})

    def programs_list(self, route):
        if route.request.method != 'GET':
            return route.continue_()
        member = parse_qs(urlparse(route.request.url).query).get('member_id', [None])[0]
        rows = [p for p in self.programs if not member or p['member_id'] == member]
        route.fulfill(json={'programs': rows})

    def projects_list(self, route):
        if route.request.method != 'GET':
            return route.continue_()
        route.fulfill(json={'projects': self.projects})

    def situations(self, route):
        q = parse_qs(urlparse(route.request.url).query)
        kinds = (q.get('kinds', [''])[0] or '').split(',')
        owner = q.get('owner', [None])[0]
        out = []
        if self.thread and 'thread' in kinds and owner in (None, '', 'parent'):
            out.append(self.thread)
        route.fulfill(json={'situations': out})

    def thread_note(self, route):
        if route.request.method != 'POST':
            return route.continue_()
        self.record(route)
        route.fulfill(json={'status': 'success'})

    def install(self, page):
        key = self.key
        schedule = schedule_for(self.driver)
        page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
        page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))

        def member_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'member_id': key, 'name': NAMES[key], 'date': date, 'rides': [],
                                'due_soon': [], 'still_open': [], 'status_days': [], 'launch': None})
        page.route('**/api/members/*/day?*', member_day)

        def routine_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'date': date, 'items': [], 'streak': {}})
        page.route('**/api/routines/day?*', routine_day)
        page.route('**/api/requests?*', lambda r: r.fulfill(json={'waiting_on_me': [], 'mine': []}))
        page.route('**/api/proposals?*', lambda r: r.fulfill(json=[]))
        page.route('**/api/weather/now*', lambda r: r.fulfill(status=200, content_type='application/json', body='null'))
        page.route('**/api/channels?*', lambda r: r.fulfill(json=[]))
        page.route('**/api/commitments?*', lambda r: r.fulfill(json=[]))
        # Chores, points, rewards (fetchChores, app.html ~6771).
        page.route('**/api/chores', lambda r: r.fulfill(json=self.chores))
        page.route('**/api/chores/*/*', self.chore_action)
        page.route('**/api/points', lambda r: r.fulfill(json=self.balances))
        page.route('**/api/rewards', lambda r: r.fulfill(json=self.rewards))
        page.route('**/api/redemptions?*', lambda r: r.fulfill(json=self.redemptions))
        page.route('**/api/redemptions/*/decide', self.decide)
        # Household tasks (main.py ~7404): list + add on one URL, complete.
        page.route(re.compile(r'.*/api/household-tasks(\?[^/]*)?$'), self.household_tasks)
        page.route(re.compile(r'.*/api/household-tasks/[^/?]+/complete$'), self.complete_task)
        # Lists (fetchHouseLists ~6830) and the shop run.
        page.route(re.compile(r'.*/api/shopping/lists(\?.*)?$'), self.shopping_lists)
        page.route(re.compile(r'.*/api/shopping/items(\?.*)?$'), self.shopping_items)
        page.route(re.compile(r'.*/api/shopping/items/[^/?]+$'), self.shopping_item)
        page.route(re.compile(r'.*/api/shopping/runs(\?.*)?$'), lambda r: r.fulfill(json=self.runs()))
        # Projects (the Alpine page: api/projects + api/members (real) + elsewhere).
        page.route(re.compile(r'.*/api/projects(\?.*)?$'), self.projects_list)
        page.route('**/api/projects/elsewhere*', lambda r: r.fulfill(json={'situations': []}))
        # Programs and their windows (fetchMyPrograms ~1377, upcomingWindows ~2013).
        page.route(re.compile(r'.*/api/programs(\?.*)?$'), self.programs_list)
        page.route('**/api/practice-windows*', lambda r: r.fulfill(json={'windows': self.windows}))
        # Situations: findings/insights (fetchMind) empty; the parent's thread
        # (fetchHouseThreads, kinds=thread&owner=) in group `now`.
        page.route('**/api/situations?*', self.situations)
        page.route('**/api/threads/*/note', self.thread_note)


# --- page helpers ------------------------------------------------------------

def norm(text):
    return ' '.join((text or '').split())


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
        Path(SHOTS, name).write_bytes(page.screenshot())


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


def need_kinds(page):
    return page.evaluate("(window.pwaNeedCards || []).map(c => c.kind)")


DOM_CARDS = "() => [...document.querySelectorAll('#house-cards .pwa-house-card')].map(b => b.dataset.card)"

# pwaHouseholdCards / pwaHouseholdLead (static/pwa_household.js) over the
# payloads the mocks served, with the page's own role, scope map, lists-only
# flag and roster.
ORACLE = """(m) => {
    const role = currentMemberRole();
    const facet = f => (typeof scopeOf === 'function' ? scopeOf(f) : 'all');
    // The next window is the first UPCOMING one (not logged, not before today),
    // handed over as the raw api/practice-windows row {date, time_start}.
    const windows = (m.windows || []).filter(w => !w.logged && w.date >= m.today)
        .sort((a, b) => (a.date + a.time_start).localeCompare(b.date + b.time_start));
    // Pooled rewards are the goals: {id, title, pct (whole percent), funded}.
    const pools = (m.rewards || []).filter(r => r.pool).map(r => ({id: r.id, title: r.title,
        pct: Math.round(100 * ((r.pool.pledged || 0) / (r.pool.cost || r.cost || 1))), funded: !!r.pool.funded}));
    const cards = pwaHouseholdCards({
        role, canReview: role === 'parent',
        listsOnly: typeof houseRevealListsOnly !== 'undefined' && !!houseRevealListsOnly,
        facets: {chores: facet('chores.board'), rewards: facet('rewards'), tasks: facet('lists.household_tasks'),
                 lists: facet('lists.shopping'), projects: 'all'},
        meId: selectedMemberId,
        chores: m.chores, balances: m.balances, rewards: pools, redemptions: m.redemptions,
        householdTasks: m.tasks, lists: m.lists, runs: m.runs, projects: m.projects, programs: m.programs,
        nextWindowFor: id => windows.find(w => w.program_id === id) || null,
        members: membersData, today: m.today});
    return {ids: cards.map(c => c.id), titles: cards.map(c => c.title), lead: pwaHouseholdLead(cards),
            cards: cards.map(c => ({id: c.id, title: c.title, line: c.line, progress: c.progress,
                                    faces: c.faces || [], hot: (c.pills || []).filter(p => p.tone === 'hot').map(p => p.text)})),
            leadOf: Object.fromEntries(cards.map(c => [c.id, pwaHouseholdLead([c])]))};
}"""

CARDS_SETTLED = """(m) => { try {
    const o = (%s)(m);
    const dom = [...document.querySelectorAll('#house-cards .pwa-house-card')].map(b => b.dataset.card);
    if (!dom.length || JSON.stringify(o.ids) !== JSON.stringify(dom)) return false;
    return o.cards.every(c => JSON.stringify([...document.querySelectorAll(
        `#house-cards .pwa-house-card[data-card="${c.id}"] .pwa-house-pills .pwa-pill.hot`)]
        .map(p => p.textContent.replace(/\\s+/g, ' ').trim())) === JSON.stringify(c.hot));
} catch (e) { return false; } }""" % ORACLE


def oracle(page, mocks):
    return page.evaluate(ORACLE, mocks.oracle_inputs())


def wait_cards(page, mocks, timeout=8000):
    settle(page, CARDS_SETTLED, timeout=timeout, arg=mocks.oracle_inputs())


def card(page, cid):
    return page.locator(f'#house-cards .pwa-house-card[data-card="{cid}"]')


def hot_pills(page, cid):
    return [norm(t) for t in card(page, cid).locator('.pwa-house-pills .pwa-pill.hot').all_text_contents()]


def open_household(page, mocks):
    """Tap the Household tab; the cards must draw (the first failure before
    Task 5: there are no cards)."""
    page.locator('#tab-chores').click()
    page.wait_for_function("currentView === 'chores'")
    settle(page, "document.querySelectorAll('#house-cards .pwa-house-card').length > 0", timeout=8000)
    assert page.locator('#house-cards .pwa-house-card').count() > 0, \
        '.pwa-house-card missing: the Household tab drew no cards in #house-cards'
    wait_cards(page, mocks)


def assert_cards_view(page, mocks, profile):
    """The Household cards view, whole: title, lead, one button per card in
    pwaHouseholdCards' order, the builders' nodes parked out of sight."""
    assert page.evaluate('PwaNav.depth()') == 0, page.evaluate('PwaNav.depth()')
    assert page.locator('#pwa-stack .pwa-screen').count() == 0, 'a pushed screen is still in #pwa-stack'
    assert page.locator('#chores-container').get_attribute('data-house') == 'cards', \
        page.locator('#chores-container').get_attribute('data-house')
    assert norm(page.locator('#house-cards h1.pwa-house-title').text_content()) == 'Household'
    want = oracle(page, mocks)
    dom = page.evaluate(DOM_CARDS)
    assert dom == want['ids'], (profile, 'card order differs from pwaHouseholdCards', dom, want['ids'])
    for c in want['cards']:
        el = card(page, c['id'])
        assert el.count() == 1, (c['id'], el.count())
        assert el.evaluate('e => e.tagName') == 'BUTTON', c['id']
        t1 = norm(el.locator('.pwa-house-t1').text_content())
        assert t1.startswith(c['title']), (c['id'], t1, c['title'])
        t2 = norm(el.locator('.pwa-house-t2').text_content())
        assert t2 == norm(c['line']), (c['id'], t2, c['line'])
        assert hot_pills(page, c['id']) == c['hot'], (c['id'], hot_pills(page, c['id']), c['hot'])
        assert el.locator('.pwa-house-icon').count() == 1, c['id']
        assert el.locator('.pwa-house-faces > *').count() == len(c['faces']), (c['id'], c['faces'])
        assert el.locator('.pwa-house-bar > i').count() == (1 if isinstance(c['progress'], (int, float)) else 0), \
            (c['id'], c['progress'])
    lead = norm(page.locator('#house-cards .pwa-house-lead').text_content())
    assert lead == norm(want['lead']), (lead, want['lead'])
    # The section tabs are gone for adults; the adopted nodes wait out of sight.
    assert page.locator('#chores-container .pwa-section-tabs:visible').count() == 0, 'the old section tabs still draw'
    assert not page.locator('#chores-content').is_visible(), '#chores-content shows on the cards view'
    assert not page.locator('#house-lists').is_visible(), '#house-lists shows on the cards view'
    assert page.locator('#house-threads').count() <= 1, 'two #house-threads in the page'
    assert page.locator('#chores-container #house-threads:visible').count() == 0, 'threads still draw in Household'
    return want


VISIBLE_BUTTONS = """() => { const s = [...document.querySelectorAll('#pwa-stack .pwa-screen')].pop();
    return s ? [...s.querySelectorAll('button')].filter(b => b.checkVisibility())
        .map(b => b.textContent.replace(/\\s+/g, ' ').trim()) : []; }"""

SEGMENTS = """() => { const s = [...document.querySelectorAll('#pwa-stack .pwa-screen')].pop();
    return s ? [...s.querySelectorAll('.pwa-seg .pwa-seg-item')].map(b => ({
        text: b.textContent.replace(/\\s+/g, ' ').trim(), pressed: b.getAttribute('aria-pressed')})) : []; }"""

SEGMENT = """() => { const s = [...document.querySelectorAll('#pwa-stack .pwa-screen')].pop();
    if (!s) return null;
    const e = s.matches('[data-house-segment]') ? s : s.querySelector('[data-house-segment]');
    return e ? e.dataset.houseSegment : null; }"""

GROUPS_HIDDEN = """(attr) => { const s = [...document.querySelectorAll('#pwa-stack .pwa-screen')].pop();
    return !!s && [...s.querySelectorAll('[' + attr + ']')].every(e => !e.checkVisibility()); }"""


def top_screen(page):
    return page.locator('#pwa-stack .pwa-screen').last


def screen_text(page):
    return norm(top_screen(page).inner_text())


def section(page):
    return page.locator('#chores-container').get_attribute('data-section')


def expect_screen(page, title, mocks=None, card_id=None):
    settle(page, "PwaNav.depth() === 1 && !!document.querySelector('#pwa-stack .pwa-screen h1')")
    assert page.evaluate('PwaNav.depth()') == 1, ('no pushed screen for', title)
    h1 = norm(page.locator('#pwa-stack .pwa-screen h1').last.text_content())
    assert h1 == title, (h1, title)
    back = norm(page.locator('#pwa-stack .pwa-screen .pwa-back').last.text_content())
    assert back == '‹ Household', back
    assert page.evaluate('currentView') == 'chores', page.evaluate('currentView')
    if mocks is not None and card_id:
        # Every screen's lead is pwaHouseholdLead([thatCard]).
        want = oracle(page, mocks)['leadOf'].get(card_id)
        lead = top_screen(page).locator('.pwa-house-lead')
        assert lead.count() == 1, ('the screen has no .pwa-house-lead', title)
        assert norm(lead.text_content()) == norm(want), (norm(lead.text_content()), want)


def open_card(page, mocks, cid):
    card(page, cid).click()
    expect_screen(page, SCREEN_TITLES[cid], mocks, cid)


def go_back(page, mocks):
    page.locator('#pwa-stack .pwa-screen .pwa-back').last.click()
    page.wait_for_function('PwaNav.depth() === 0')
    wait_cards(page, mocks)


def pick_segment(page, label, value):
    top_screen(page).locator('.pwa-seg .pwa-seg-item').filter(has_text=label).first.click()
    settle(page, "(%s)() === '%s'" % (SEGMENT, value))
    assert page.evaluate(SEGMENT) == value, (label, page.evaluate(SEGMENT))
    pressed = [s['text'] for s in page.evaluate(SEGMENTS) if s['pressed'] == 'true']
    assert len(pressed) == 1 and pressed[0].startswith(label), (label, page.evaluate(SEGMENTS))


def visible_buttons(page):
    return page.evaluate(VISIBLE_BUTTONS)


def no_overflow(page):
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), \
        page.evaluate('[document.documentElement.scrollWidth, innerWidth]')


def answer_task_prompts(page):
    """The add flow asks the due date (promptInput) and who (promptChoice,
    household adults + Anyone); answer each sheet once, in whatever order."""
    for _ in range(2):
        page.wait_for_selector('.pwa-prompt-overlay', state='visible')
        overlay = page.locator('.pwa-prompt-overlay').last
        handle = overlay.element_handle()
        if overlay.locator('[data-field]').count():
            overlay.locator('[data-field]').fill(IN_FIVE)
            overlay.locator('[data-yes]').click()
        else:
            overlay.locator('[data-pick]').filter(has_text='Anyone').first.click()
        handle.wait_for_element_state('hidden')


def task_check_button(page, title):
    row = top_screen(page).locator(
        f'xpath=.//*[contains(normalize-space(.), "{title}")][.//button[starts-with(normalize-space(.), "✓")]]').last
    return row.locator('xpath=.//button[starts-with(normalize-space(.), "✓")]').first


# --- scenarios ----------------------------------------------------------------

def cards_in_need_order(page, mocks, profile):
    open_household(page, mocks)
    want = assert_cards_view(page, mocks, profile)
    ids = want['ids']
    if profile == 'parent':
        assert set(ids) == ALL_CARDS, ids
        pos = {c: i for i, c in enumerate(ids)}
        # From the payloads: chores 3*1 done + 1 open = 4; tasks 3*1 past due
        # + this week >= 4; rewards 3*1 pending = 3; projects 3*1 needs_you = 3;
        # lists 2 (shop day tomorrow).
        assert pos['chores'] < pos['rewards'] and pos['chores'] < pos['projects'], ids
        assert pos['tasks'] < pos['rewards'] and pos['tasks'] < pos['projects'], ids
        assert ids[-1] == 'lists', ids
        assert hot_pills(page, 'chores') == ['1 to check'], hot_pills(page, 'chores')
        assert hot_pills(page, 'rewards') == ['1 request'], hot_pills(page, 'rewards')
        assert hot_pills(page, 'tasks') == ['1 overdue'], hot_pills(page, 'tasks')
        assert hot_pills(page, 'lists') == ['Shop day tomorrow'], hot_pills(page, 'lists')
        assert card(page, 'projects').locator('.pwa-house-faces > *').count() == 2, 'projects card: two faces'
        # Tomorrow's 16:30 practice window is the soonest session: a hot pill
        # from the raw api/practice-windows row, never dropped for its shape.
        tomorrow_wd = (NOW + timedelta(days=1)).strftime('%A')
        assert hot_pills(page, 'projects') == ['Strength training · %s 4:30' % tomorrow_wd], hot_pills(page, 'projects')
        lead = norm(page.locator('#house-cards .pwa-house-lead').text_content())
        assert lead == 'Two things want your yes. Shop day is tomorrow.', lead
        badge = page.locator('#tab-chores-badge')
        assert badge.is_visible() and norm(badge.text_content()) == '2', norm(badge.text_content())
        shot(page, 'household-cards-light.png')
    elif profile == 'adult':
        assert set(ids) == ALL_CARDS, ids
        assert ids[0] == 'tasks', ids
        assert not any('to check' in p for p in hot_pills(page, 'chores')), hot_pills(page, 'chores')
        assert 'Shop day tomorrow' in hot_pills(page, 'lists'), hot_pills(page, 'lists')
        # A non-parent's rewards card shows the top goal with its bar (60%).
        assert card(page, 'rewards').locator('.pwa-house-bar > i').count() == 1, 'the goal bar is missing'
    elif profile == 'keeping':
        # keeping_up: lists.shopping none, household_tasks none.
        assert set(ids) == {'chores', 'rewards', 'projects'}, ids
        assert ids[0] == 'chores', ids
    elif profile == 'lists_only':
        assert ids == ['lists'], ids
    for c in ids:
        box = card(page, c).bounding_box()
        assert box and box['height'] >= 44, (c, box)


def rewards_screen(page, mocks):
    # The review card's route: Chores at To check never shows a redemption.
    page.evaluate("pwaOpenHouseScreen('chores', 'check')")
    expect_screen(page, 'Chores', mocks, 'chores')
    assert page.evaluate(SEGMENT) == 'check', page.evaluate(SEGMENT)
    assert section(page) == 'reviews', section(page)
    btns = visible_buttons(page)
    assert '✓ Verify' in btns and '✓ Grant' not in btns, btns
    assert page.evaluate(GROUPS_HIDDEN, 'data-reward-group'), 'reward groups show on the Chores screen'
    go_back(page, mocks)

    open_card(page, mocks, 'rewards')
    screen = top_screen(page)
    assert screen.locator('.pwa-seg').count() == 0, 'Rewards has no segments'
    assert section(page) == 'rewards', section(page)
    balances = screen.locator('[data-reward-group="balances"]')
    goals = screen.locator('[data-reward-group="goals"]')
    redemptions = screen.locator('[data-reward-group="redemptions"]')
    for name, group in (('balances', balances), ('goals', goals), ('redemptions', redemptions)):
        assert group.count() >= 1 and group.first.is_visible(), f'[data-reward-group="{name}"] is not shown'
    assert 'Sam: 120' in norm(balances.first.text_content()), norm(balances.first.text_content())
    assert 'Zoo trip' in norm(goals.first.text_content()), norm(goals.first.text_content())
    assert goals.first.locator('[style*="width:60%"]').count() >= 1, 'the family goal bar is not at 60%'
    red = norm(redemptions.first.text_content())
    assert 'Movie night' in red and 'Sam' in red and '50 pts' in red, red
    btns = visible_buttons(page)
    assert '✓ Grant' in btns, btns
    assert not {'✓ Verify', 'Claim', 'Mark done'} & set(btns), btns
    assert page.evaluate(GROUPS_HIDDEN, 'data-chore-group'), 'chore groups show on the Rewards screen'
    with page.expect_response(lambda r: r.request.method == 'POST' and '/api/redemptions/red1/decide' in r.url):
        screen.get_by_role('button', name='✓ Grant').first.click()
    call = mocks.last_call('POST', r'/api/redemptions/red1/decide$')
    assert call['body'].get('approve') is True, call
    settle(page, "!document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Movie night')")
    assert 'Movie night' not in screen_text(page), 'the granted redemption is still listed'
    go_back(page, mocks)
    assert hot_pills(page, 'rewards') == [], hot_pills(page, 'rewards')


def chores_screen_segments(page, mocks, profile):
    open_card(page, mocks, 'chores')
    h1 = page.locator('#pwa-stack .pwa-screen h1').last
    assert h1.evaluate('e => e === document.activeElement'), 'focus did not move to the screen title'
    assert h1.get_attribute('tabindex') == '-1', h1.get_attribute('tabindex')
    covered = page.evaluate("""() => { const c = document.getElementById('pwa-covered');
        return c && {inert: c.inert, hidden: c.getAttribute('aria-hidden'),
            chores: c.contains(document.getElementById('chores-container')),
            bar: c.contains(document.getElementById('pwa-tab-bar')),
            stack: c.contains(document.getElementById('pwa-stack'))}; }""")
    assert covered == {'inert': True, 'hidden': 'true', 'chores': True, 'bar': False, 'stack': False}, covered
    segs = page.evaluate(SEGMENTS)
    labels = [s['text'] for s in segs]
    if profile != 'parent':
        assert labels == ['Mine', 'Open'], labels
    else:
        assert labels == ['Mine', 'Open', 'To check · 1'], labels
    # The member has claimed work, so Mine leads.
    assert page.evaluate(SEGMENT) == 'mine', page.evaluate(SEGMENT)
    assert [s['pressed'] for s in segs][0] == 'true', segs
    assert section(page) == 'tasks', section(page)
    btns = visible_buttons(page)
    assert 'Mark done' in btns and '✓ Verify' not in btns, btns
    assert page.evaluate(GROUPS_HIDDEN, 'data-reward-group'), 'reward groups show on the Chores screen'
    pick_segment(page, 'Open', 'open')
    assert section(page) == 'tasks', section(page)
    btns = visible_buttons(page)
    assert 'Claim' in btns and '✓ Verify' not in btns, btns
    if profile != 'parent':
        go_back(page, mocks)
        return
    pick_segment(page, 'To check', 'check')
    assert section(page) == 'reviews', section(page)
    btns = visible_buttons(page)
    assert '✓ Verify' in btns and 'Claim' not in btns, btns
    shot(page, 'household-chores-check.png')
    with page.expect_response(lambda r: r.request.method == 'POST' and '/api/chores/recycling/verify' in r.url):
        top_screen(page).get_by_role('button', name='✓ Verify').first.click()
    mocks.last_call('POST', r'/api/chores/recycling/verify$')
    settle(page, "!(%s)().some(s => s.text.includes('· 1'))" % SEGMENTS)
    labels = [s['text'] for s in page.evaluate(SEGMENTS)]
    assert not any('· 1' in t for t in labels), labels
    assert '✓ Verify' not in visible_buttons(page), visible_buttons(page)
    go_back(page, mocks)
    covered = page.evaluate("""() => { const c = document.getElementById('pwa-covered');
        return {inert: c.inert, hidden: c.hasAttribute('aria-hidden')}; }""")
    assert covered == {'inert': False, 'hidden': False}, covered
    settle(page, "!document.querySelector('#house-cards .pwa-house-card[data-card=\"chores\"] .pwa-pill.hot')")
    assert hot_pills(page, 'chores') == [], hot_pills(page, 'chores')
    settle(page, "getComputedStyle(document.getElementById('tab-chores-badge')).display === 'none'")
    assert not page.locator('#tab-chores-badge').is_visible(), 'the Household badge still shows'


def tasks_screen(page, mocks):
    before = norm(card(page, 'tasks').locator('.pwa-house-t2').text_content())
    open_card(page, mocks, 'tasks')
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Change the furnace filter')")
    text = screen_text(page)
    assert 'Renew car registration' in text and 'Change the furnace filter' in text, text
    assert text.index('Renew car registration') < text.index('Change the furnace filter'), 'overdue is not first'
    assert 'overdue' in text.lower(), text
    assert 'anyone' in text.lower(), 'an unassigned task does not say anyone'
    assert top_screen(page).locator('#household-task-add').count() == 1, '#household-task-add missing'
    with page.expect_response(lambda r: r.request.method == 'POST' and '/api/household-tasks/ht-filter/complete' in r.url):
        task_check_button(page, 'Change the furnace filter').click()
    mocks.last_call('POST', r'/api/household-tasks/ht-filter/complete$')
    settle(page, "!document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Change the furnace filter')")
    assert 'Change the furnace filter' not in screen_text(page), 'the completed task is still listed'
    go_back(page, mocks)
    after = norm(card(page, 'tasks').locator('.pwa-house-t2').text_content())
    assert after != before, ('the tasks card line did not change', before)

    open_card(page, mocks, 'tasks')
    top_screen(page).locator('#household-task-add').fill('Book the chimney sweep')
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and urlparse(r.url).path.endswith('/api/household-tasks')):
        top_screen(page).get_by_role('button', name='Add', exact=True).click()
        answer_task_prompts(page)
    call = mocks.last_call('POST', r'/api/household-tasks$')
    body = call['body'] or {}
    assert body.get('title') == 'Book the chimney sweep', body
    assert body.get('due_date') == IN_FIVE, body
    assert not body.get('assigned_to'), body
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Book the chimney sweep')")
    assert 'Book the chimney sweep' in screen_text(page), 'the added task did not appear'
    shot(page, 'household-tasks.png')
    go_back(page, mocks)


def lists_screen(page, mocks, profile):
    open_card(page, mocks, 'lists')
    assert section(page) == 'lists', section(page)
    lists = top_screen(page).locator('#house-lists')
    assert lists.count() == 1 and lists.is_visible(), '#house-lists was not adopted into the screen'
    settle(page, "!!document.querySelector('#pwa-stack .pwa-screen #house-lists input[type=checkbox]')")
    btns = visible_buttons(page)
    if profile == 'parent':
        assert any(b.startswith('Groceries') for b in btns) and any(b.startswith('Costco') for b in btns), btns
        assert '2 in the cart' in screen_text(page), screen_text(page)
    with page.expect_response(lambda r: r.request.method == 'PATCH' and '/api/shopping/items/g0' in r.url):
        lists.locator('input[type=checkbox]').first.click()
    call = mocks.last_call('PATCH', r'/api/shopping/items/g0$')
    assert call['body'].get('is_checked') is True, call
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('3 in the cart')")
    assert '3 in the cart' in screen_text(page), screen_text(page)
    if profile != 'parent':
        go_back(page, mocks)
        return
    lists.locator('#house-add-input').fill('Oat milk')
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and urlparse(r.url).path.endswith('/api/shopping/items')):
        lists.locator('form button[type=submit]').click()
    call = mocks.last_call('POST', r'/api/shopping/items$')
    assert call['body'].get('name') == 'Oat milk' and call['body'].get('list_id') == 'groceries', call
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Oat milk')")
    assert 'Oat milk' in screen_text(page), 'the added item did not appear'
    shot(page, 'household-lists.png')
    top_screen(page).get_by_role('button').filter(has_text='Costco').first.click()
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Paper towels')")
    assert 'Paper towels' in screen_text(page), 'the Costco chip did not switch lists'
    top_screen(page).get_by_role('button').filter(has_text='Groceries').first.click()
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Oat milk')")
    go_back(page, mocks)
    assert not page.locator('#house-lists').is_visible(), '#house-lists did not go back out of sight'


def projects_screen(page, mocks):
    open_card(page, mocks, 'projects')
    # The user's ruling 2026-11-04 (slice 7): Projects, one list. A program
    # lives in its project (its piece sheet carries Coming up); no Programs tab.
    segs = page.evaluate(SEGMENTS)
    assert segs == [], ('the Projects screen still has segments', segs)
    screen = top_screen(page)
    assert screen.locator('[data-house-programs]').count() == 0, 'a Programs list is still drawn'
    assert screen.locator('#projects-container').count() == 1, '#projects-container was not adopted'
    settle(page, "[...document.querySelectorAll('#pwa-stack .pwa-screen [data-project-card]')].filter(e => e.checkVisibility()).length === 2", timeout=8000)
    cards = screen.locator('#projects-container [data-project-card]')
    assert cards.count() == 2 and cards.first.is_visible(), cards.count()
    titles = norm(screen.locator('#projects-container').inner_text())
    assert 'Rebuild the deck' in titles and 'Spring garden' in titles, titles
    shot(page, 'household-projects.png')
    assert 'Strength training' not in screen_text(page), 'a program is listed outside its project'
    go_back(page, mocks)
    assert page.locator('#pwa-stack #projects-container').count() == 0, '#projects-container stayed in the stack'


def wait_app(page):
    page.wait_for_function("""() => !!document.querySelector('#screen-schedule:not(.hidden)')
        || !!document.getElementById('pin-modal-skip')?.checkVisibility()""", timeout=20000)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function("typeof membersData !== 'undefined' && membersData.length > 0")


def back_and_reload(page, mocks):
    open_card(page, mocks, 'chores')
    page.reload(wait_until='domcontentloaded')
    wait_app(page)
    settle(page, "currentView === 'chores' && document.querySelectorAll('#house-cards .pwa-house-card').length > 0", timeout=8000)
    assert page.evaluate('currentView') == 'chores', page.evaluate('currentView')
    wait_cards(page, mocks)
    assert page.evaluate('PwaNav.depth()') == 0
    assert page.locator('#pwa-stack .pwa-screen').count() == 0, 'a reload restored a screen'
    assert page.evaluate('history.state && history.state.pwaDepth') == 0, page.evaluate('history.state')
    assert_cards_view(page, mocks, 'parent')
    page.go_back(wait_until='domcontentloaded')
    wait_app(page)
    settle(page, "currentView === 'chores' && document.querySelectorAll('#house-cards .pwa-house-card').length > 0", timeout=8000)
    wait_cards(page, mocks)
    assert page.evaluate('PwaNav.depth()') == 0
    assert page.locator('#pwa-stack .pwa-screen').count() == 0, 'Back after a reload drew a screen'
    assert_cards_view(page, mocks, 'parent')


def threads_live_on_plan(page, mocks):
    page.locator('#tab-family').click()
    page.wait_for_function("currentView === 'family'")
    settle(page, "!!document.querySelector('#house-threads .situation-card')?.checkVisibility()", timeout=10000)
    threads = page.locator('#house-threads')
    assert threads.count() == 1, threads.count()
    assert threads.is_visible(), '#house-threads is not on Plan'
    assert page.evaluate("!document.getElementById('house-threads').closest('#chores-container')"), \
        '#house-threads is still hosted in Household'
    assert 'Deck permit' in norm(threads.locator('.sit-title').first.text_content())
    note = threads.locator('form input[id^="house-thread-note-"]')
    assert note.count() == 1, 'the note form is missing from the thread card'
    note.fill('Called the county, permit is in review')
    with page.expect_response(lambda r: r.request.method == 'POST' and f"/api/threads/{THREAD['id']}/note" in r.url):
        threads.get_by_role('button', name='Add note').first.click()
    call = mocks.last_call('POST', r'/api/threads/[^/]+/note$')
    assert call['body'].get('text') == 'Called the county, permit is in review', call
    # My Day's pile carries the thread that needs you; it opens Plan at the lane.
    page.locator('#tab-myday').click()
    wait_brief(page)
    settle(page, "(window.pwaNeedCards || []).some(c => c.kind === 'thread')")
    kinds = need_kinds(page)
    assert 'thread' in kinds, kinds
    page.locator('#myday-content .pwa-need').nth(kinds.index('thread')).click()
    page.wait_for_function("currentView === 'family'")
    settle(page, """(() => { const e = document.getElementById('house-threads'); if (!e || !e.checkVisibility()) return false;
        const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; })()""")
    box = page.evaluate("(() => { const r = document.getElementById('house-threads').getBoundingClientRect(); return [r.top, r.bottom, innerHeight]; })()")
    assert box[0] < box[2] and box[1] > 0, ('Plan did not open at the lane', box)


def household_task_due_today(page, mocks):
    page.locator('#tab-myday').click()
    wait_brief(page)
    settle(page, "(window.pwaNeedCards || []).some(c => c.kind === 'household_task')")
    kinds = need_kinds(page)
    assert 'household_task' in kinds, kinds
    need = page.locator('#myday-content .pwa-need').nth(kinds.index('household_task'))
    assert 'Renew car registration' in norm(need.inner_text()), need.inner_text()
    need.click()
    expect_screen(page, 'Tasks')
    settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Renew car registration')")
    with page.expect_response(lambda r: r.request.method == 'POST' and '/api/household-tasks/ht-reg/complete' in r.url):
        task_check_button(page, 'Renew car registration').click()
    mocks.last_call('POST', r'/api/household-tasks/ht-reg/complete$')
    settle(page, "!document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Renew car registration')")
    page.locator('#tab-myday').click()
    wait_brief(page)
    settle(page, "!(window.pwaNeedCards || []).some(c => c.kind === 'household_task')")
    assert 'household_task' not in need_kinds(page), need_kinds(page)


CARD_BG_PROBE = """() => { const p = document.createElement('div'); p.style.background = 'var(--pwa-card)';
    document.getElementById('house-cards').append(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; }"""


def widths_and_dark(page, mocks):
    page.locator('#tab-chores').click()
    page.wait_for_function("currentView === 'chores'")
    wait_cards(page, mocks)
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        no_overflow(page)
        assert page.locator('#chores-container').evaluate('e => e.scrollWidth <= e.clientWidth')
        if width == 360:
            shot(page, 'household-360.png')
    first = page.locator('#house-cards .pwa-house-card').first
    title = page.locator('#house-cards .pwa-house-title')
    assert title.evaluate('e => getComputedStyle(e).fontSize') == '34px'
    assert title.evaluate('e => getComputedStyle(e).fontWeight') == '700'
    assert first.evaluate('e => getComputedStyle(e).borderTopLeftRadius') == '22px'
    icon = first.locator('.pwa-house-icon').bounding_box()
    assert round(icon['width']) == 44 and round(icon['height']) == 44, icon
    light_bg = page.evaluate(CARD_BG_PROBE)
    assert first.evaluate('e => getComputedStyle(e).backgroundColor') == light_bg, light_bg
    hot = page.locator('#house-cards .pwa-pill.hot').first
    if hot.count():
        assert hot.evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(255, 230, 204)'
    page.evaluate("applyTheme('dark')")
    dark_bg = page.evaluate(CARD_BG_PROBE)
    assert dark_bg != light_bg, 'the card token did not change for dark'
    assert first.evaluate('e => getComputedStyle(e).backgroundColor') == dark_bg, dark_bg
    no_overflow(page)
    shot(page, 'household-cards-dark.png')
    page.evaluate("applyTheme('light')")
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    running = page.evaluate("""() => document.getElementById('house-cards')
        .getAnimations({subtree: true}).filter(a => a.playState === 'running').length""")
    assert running == 0, running


def lists_only_member(page, mocks):
    # The tab comes back asynchronously, from the lists the server returned.
    page.wait_for_function("document.getElementById('tab-chores').style.display !== 'none'", timeout=10000)
    cards_in_need_order(page, mocks, 'lists_only')
    lists_screen(page, mocks, 'lists_only')


def helper_has_no_household(page):
    assert not page.locator('#tab-chores').is_visible(), 'a helper has a Household tab'
    assert page.evaluate("pwaFeatures().some(f => f.id === 'household')") is False, 'More offers Household to a helper'
    assert page.locator('#house-cards .pwa-house-card').count() == 0


# --- the run -----------------------------------------------------------------

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
    # Once per tab: a reload must keep the view the app stored (back_and_reload).
    page.add_init_script("if (!sessionStorage.getItem('chf_test_seeded')) { Object.entries(" + json.dumps(values)
                         + ").forEach(([k, v]) => localStorage.setItem(k, v)); sessionStorage.setItem('chf_test_seeded', '1'); }")
    mocks = Mocks(key, driver)
    mocks.install(page)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    wait_app(page)
    assert page.evaluate('selectedMemberId') == key
    assert page.evaluate('currentMemberRole()') == role
    if key == 'parent':
        wait_brief(page)
    return mocks, failed_assets


def page_errors(served, key):
    errors = list(served.errors())
    if errors:
        errors = errors + [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key]
    return errors


def run():
    global SHOTS
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
        SHOTS = (Path(__file__).resolve().parent / 'probe_shots' / 'pwa_slice3'
                 if output.lower() in ('1', 'true', 'yes', 'on') else Path(output))
        SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        for key, role, driver in PROFILES:
            if os.environ.get('PWA_REVIEW_PROFILE') and key != os.environ['PWA_REVIEW_PROFILE']:
                continue
            with served.browser(reduced_motion='reduce', has_touch=True) as page:
                mocks, failed_assets = boot(served, page, key, role, driver)
                if key == 'parent':
                    cards_in_need_order(page, mocks, key)
                    rewards_screen(page, mocks)
                    chores_screen_segments(page, mocks, key)
                    tasks_screen(page, mocks)
                    lists_screen(page, mocks, key)
                    projects_screen(page, mocks)
                    back_and_reload(page, mocks)
                    threads_live_on_plan(page, mocks)
                    household_task_due_today(page, mocks)
                    widths_and_dark(page, mocks)
                elif key == 'adult':
                    cards_in_need_order(page, mocks, key)
                    chores_screen_segments(page, mocks, key)
                elif key == 'keeping':
                    cards_in_need_order(page, mocks, key)
                elif key in ('lists_only', 'granted'):
                    lists_only_member(page, mocks)
                else:
                    helper_has_no_household(page)
                errors = page_errors(served, key)
                assert not errors and not failed_assets, (key, errors, failed_assets)
                print('ok', key, flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    run()
