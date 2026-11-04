"""Projects & programs have one door (slice 6, Task 5; the user's ruling 2026-11-04).

Projects & programs live in Household for everyone who has a Household tab;
More shows Projects and My programs only to people without one. Library stays
on More. A sprout keeps its own spot (#pwa-sprout-projects, My things). A
helper still has no Projects anywhere. Nothing anyone reaches today becomes
unreachable.

Written before the change (Codex implements it), so its first failures are
`adult_one_door` (More still lists Projects and My programs for a parent) and
`kid_house_projects` (the kid's House tab has no Projects section).

Members and projects are seeded and served for real (api/members,
api/projects and api/projects/<id>, so the projects page and a deep link to a
project draw from the server's own rows); every other read the views make is
mocked with page.route, the way tests/test_pwa_household_live.py does it, and
every 4xx is named with its URL when a scenario fails.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_projects_one_door_live.py
ONE_DOOR_SCENARIO=<name> runs one scenario. PWA_REVIEW_OUTPUT=1 writes the
screenshots to tests/probe_shots/pwa_slice6 (gitignored); any other value is
taken as the output directory.
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
sys.path.insert(0, str(ROOT / 'chauffeur' / 'tests'))
DATA = tempfile.mkdtemp(prefix='chauffeur_one_door_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app  # noqa: E402
from services import storage, ha_api  # noqa: E402

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + timedelta(days=1)).strftime('%Y-%m-%d')

# key: (role, driver, name, extra member fields)
PEOPLE = {
    'parent': ('parent', 'd1', 'Alex Morgan', {}),
    'adult': ('adult', 'd2', 'Robin Lee', {}),
    # services/scope.py _table_value applies scope.overrides[facet]: the
    # chores door closes and a shared list reopens the tab (the lists half).
    'lists_only': ('adult', 'd6', 'Jo Ellis',
                   {'scope': {'preset': 'household_adult', 'overrides': {'chores.board': 'none'}}}),
    'helper': ('helper', 'd3', 'Nana Bea', {}),
    'navigator': ('child', None, 'Sam', {'stage_override': 'navigator'}),
    'explorer': ('child', None, 'Ana', {'stage_override': 'explorer'}),
    'sprout': ('child', None, 'Theo', {'stage_override': 'sprout'}),
}
# Each person's own project (served for real) and own program (mocked).
OWN_PROJECT = {'navigator': ('prj-bike', 'Learn to ride a bike'), 'explorer': ('prj-swim', 'Learn to swim'),
               'sprout': ('prj-potty', 'Use the big-kid potty')}
HOUSE_PROJECT = ('prj-deck', 'Rebuild the deck')
PROGRAMS = [dict(id='practice', member_id='adult', member_name='Robin Lee', title='Strength training',
                 state='active', progress={}, emissions={}),
            dict(id='piano', member_id='navigator', member_name='Sam', title='Piano practice',
                 state='active', progress={}, emissions={}),
            dict(id='swim-drills', member_id='explorer', member_name='Ana', title='Swim drills',
                 state='active', progress={}, emissions={}),
            dict(id='garden', member_id='sprout', member_name='Theo', title='Garden helper',
                 state='active', progress={}, emissions={})]
KID_PROGRAM = {'navigator': 'Piano practice', 'explorer': 'Swim drills'}

BAD_RESPONSES = []
SHOTS = None


def seed():
    for key, (role, driver, name, extra) in PEOPLE.items():
        storage.add_member(dict({'id': key, 'name': name, 'role': role, 'driver_id': driver,
                                 'color_code': '#287a72'}, **extra))
        if driver:
            storage.add_driver({'id': driver, 'name': name, 'home_location': 'Home', 'color_code': '#287a72'})
    pid, title = HOUSE_PROJECT
    storage.add_project({'id': pid, 'title': title, 'goal': 'a safe deck', 'done_when': 'we eat on it',
                         'owner_member_id': 'parent', 'created_by': 'parent', 'audience': 'household',
                         'pieces': [], 'steps': []})
    for kid, (pid, title) in OWN_PROJECT.items():
        storage.add_project({'id': pid, 'title': title, 'goal': 'grow', 'done_when': 'done',
                             'owner_member_id': kid, 'created_by': 'parent', 'audience': 'parents',
                             'pieces': [], 'steps': []})
    storage.set_app_state('projects_adopted_rev', 1)   # no startup migration may re-wrap the fixture


# --- the mocked reads ----------------------------------------------------------

def install_mocks(page, key, driver):
    """Every read the shell, My Day, Household / House and More make, except
    api/members and api/projects*, which the server answers for real."""
    household = key in ('parent', 'adult')
    schedule = {'events': [], 'assignments': {}, 'home_location': 'Home', 'calendar_metadata': {},
                'initial_edges': {}, 'route_edges': {}, 'final_edges': {}}
    page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
    page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))

    def member_day(route):
        date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
        route.fulfill(json={'member_id': key, 'name': PEOPLE[key][2], 'date': date, 'rides': [],
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
    chores = [dict(id='plants', title='Water the plants', points=5, state='open', eligible_member_ids=[])] \
        if key != 'helper' else []
    page.route('**/api/chores', lambda r: r.fulfill(json=chores))
    page.route('**/api/points', lambda r: r.fulfill(json=[{'member_id': key, 'name': PEOPLE[key][2], 'balance': 20}]
                                                    if key != 'helper' else []))
    page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
    page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))
    page.route(re.compile(r'.*/api/household-tasks(\?[^/]*)?$'), lambda r: r.fulfill(json=[]))
    groceries = {'id': 'groceries', 'name': 'Groceries', 'is_default': True, 'audience': 'household',
                 'shared_with': [], 'open_count': 1, 'checked_count': 0}
    lists = [groceries] if (household or key in ('lists_only', 'navigator', 'explorer', 'sprout')) else []
    page.route(re.compile(r'.*/api/shopping/lists(\?.*)?$'), lambda r: r.fulfill(json=lists))
    item = {'id': 'g1', 'list_id': 'groceries', 'name': 'Milk', 'qty': None, 'note': None, 'added_by': 'parent',
            'added_via': 'manual', 'is_checked': False, 'image_id': None, 'claims': [], 'buy_on': None,
            'deadline': None}
    page.route(re.compile(r'.*/api/shopping/items(\?.*)?$'),
               lambda r: r.fulfill(json=[item] if lists else []))
    page.route(re.compile(r'.*/api/shopping/runs(\?.*)?$'), lambda r: r.fulfill(json={
        'shop_date': TOMORROW, 'groups': [], 'runs': {'guess': TOMORROW, 'scheduled': None, 'next': TOMORROW},
        'late': [], 'top_up': False, 'counts': {}}))
    page.route('**/api/projects/elsewhere*', lambda r: r.fulfill(json={'situations': []}))

    # fetchMyPrograms: a grown-up asks unfiltered, anyone else ?member_id=<self>.
    def programs_list(route):
        if route.request.method != 'GET':
            return route.continue_()
        member = parse_qs(urlparse(route.request.url).query).get('member_id', [None])[0]
        rows = [] if key == 'helper' else [p for p in PROGRAMS if not member or p['member_id'] == member]
        route.fulfill(json={'programs': rows})
    page.route(re.compile(r'.*/api/programs(\?.*)?$'), programs_list)
    page.route('**/api/practice-windows*', lambda r: r.fulfill(json={'windows': []}))
    page.route('**/api/situations?*', lambda r: r.fulfill(json={'situations': []}))


# --- page helpers --------------------------------------------------------------

def norm(text):
    return ' '.join((text or '').split())


def shot(page, name):
    if SHOTS:
        page.wait_for_timeout(300)
        Path(SHOTS, name).write_bytes(page.screenshot())


def settle(page, condition, timeout=8000):
    """Give an async render the chance to land; the assertion after it says
    what was wrong if it never did."""
    try:
        page.wait_for_function('() => ' + condition, timeout=timeout)
    except Exception:
        pass


def wait_app(page):
    page.wait_for_function("""() => !!document.querySelector('#screen-schedule:not(.hidden)')
        || !!document.getElementById('pin-modal-skip')?.checkVisibility()""", timeout=20000)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function("typeof membersData !== 'undefined' && membersData.length > 0")


def boot(served, page, key):
    role, driver = PEOPLE[key][0], PEOPLE[key][1]
    failed_assets = []
    page.on('requestfailed', lambda request: failed_assets.append(
        (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
    page.on('response', lambda response: failed_assets.append(
        (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
        and response.status >= 400 else None)
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
    values = {'chauffeur_member_id': key, 'chauffeur_member_token': token, 'chauffeur_member_token_for': key,
              'chauffeur_view': 'myday', 'chauffeur_theme': 'light'}
    if driver:
        values['chauffeur_driver_id'] = driver
    page.add_init_script("if (!sessionStorage.getItem('chf_test_seeded')) { Object.entries(" + json.dumps(values)
                         + ").forEach(([k, v]) => localStorage.setItem(k, v)); sessionStorage.setItem('chf_test_seeded', '1'); }")
    install_mocks(page, key, driver)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    wait_app(page)
    assert page.evaluate('selectedMemberId') == key, page.evaluate('selectedMemberId')
    assert page.evaluate('currentMemberRole()') == role, page.evaluate('currentMemberRole()')
    if role == 'child':
        settle(page, f"pwaChildStage() === '{key}'")
        assert page.evaluate('pwaChildStage()') == key, page.evaluate('pwaChildStage()')
    return failed_assets


def no_errors(served, page, key, failed_assets):
    errors = list(served.errors())
    bad = [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key]
    assert not errors and not failed_assets, (key, errors, bad, failed_assets)


FEATURE_IDS = "() => pwaFeatures().map(f => f.id)"
LISTED = "() => [...document.querySelectorAll('#pwa-feature-list [data-feature]')].map(b => b.dataset.feature)"


def open_more(page):
    page.locator('#tab-more').click()
    page.wait_for_function("currentView === 'more'")
    page.wait_for_selector('#pwa-feature-list > button')
    return page.evaluate(FEATURE_IDS), page.evaluate(LISTED)


def more_has(page, key, present=(), absent=()):
    ids, listed = open_more(page)
    for fid in present:
        assert fid in ids, (key, f'pwaFeatures() lacks {fid!r}', ids)
        assert fid in listed, (key, f'#pwa-feature-list lacks [data-feature="{fid}"]', listed)
        assert page.locator(f'#pwa-feature-list [data-feature="{fid}"]').is_visible(), (key, fid, 'row not visible')
    for fid in absent:
        assert fid not in ids, (key, f'More still offers {fid!r} (pwaFeatures)', ids)
        assert fid not in listed, (key, f'#pwa-feature-list still draws [data-feature="{fid}"]', listed)
    return ids


def visible_cards(page, scope):
    return page.evaluate("""(scope) => [...document.querySelectorAll(scope + ' [data-project-card]')]
        .filter(e => e.checkVisibility()).map(e => e.innerText.replace(/\\s+/g, ' ').trim())""", scope)


def watch_opens(page):
    page.evaluate("""() => { window._projOpens = 0; window._projectOpens = 0;
        window.addEventListener('chf-projects-open', () => window._projOpens++);
        window.addEventListener('chf-project-open', () => window._projectOpens++); }""")


# --- scenarios -----------------------------------------------------------------

def adult_one_door(served):
    """Parent and household adult: More has Library but no Projects and no My
    programs; Household's Projects & programs card is the door to both."""
    for key in ('parent', 'adult'):
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            failed = boot(served, page, key)
            more_has(page, key, present=('library',), absent=('projects', 'programs'))
            # The directory reads the Household's own answer (pwa_household.js).
            assert page.evaluate("typeof pwaHouseHasProjects === 'function' && pwaHouseHasProjects() === true"), \
                (key, 'pwaHouseHasProjects() is not true for a household adult')
            page.locator('#tab-chores').click()
            page.wait_for_function("currentView === 'chores'")
            card = page.locator('#house-cards .pwa-house-card[data-card="projects"]')
            card.wait_for(state='visible', timeout=10000)
            card.click()
            page.wait_for_function("PwaNav.depth() === 1 && !!document.querySelector('#pwa-stack .pwa-screen h1')")
            h1 = norm(page.locator('#pwa-stack .pwa-screen h1').last.text_content())
            assert h1 == 'Projects & programs', (key, h1)
            screen = page.locator('#pwa-stack .pwa-screen').last
            assert screen.locator('#projects-container').count() == 1, (key, '#projects-container was not adopted')
            settle(page, "[...document.querySelectorAll('#pwa-stack .pwa-screen [data-project-card]')]"
                         ".some(e => e.checkVisibility())", timeout=10000)
            cards = visible_cards(page, '#pwa-stack .pwa-screen #projects-container')
            assert any(HOUSE_PROJECT[1] in c for c in cards), (key, 'the household project card is missing', cards)
            # My programs left More: the same screen's Programs segment carries them.
            screen.locator('.pwa-seg .pwa-seg-item[data-segment="programs"]').click()
            settle(page, "document.querySelector('#pwa-stack .pwa-screen').innerText.includes('Strength training')")
            assert 'Strength training' in norm(screen.inner_text()), (key, 'no program under Programs')
            no_errors(served, page, key, failed)
            print('  ok  adult_one_door', key, flush=True)


def lists_only_keeps_more(served):
    """A lists-only adult has no Household door to Projects: More keeps
    Projects (it opens the projects page) and My programs."""
    key = 'lists_only'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        # The tab comes back asynchronously, from the lists the server returned.
        page.wait_for_function("document.getElementById('tab-chores').style.display !== 'none'"
                               " && houseRevealListsOnly === true", timeout=10000)
        page.locator('#tab-chores').click()
        page.wait_for_function("currentView === 'chores'")
        page.wait_for_selector('#house-cards .pwa-house-card[data-card="lists"]', timeout=10000)
        assert page.locator('#house-cards .pwa-house-card[data-card="projects"]').count() == 0, \
            'a lists-only adult has a Projects & programs card'
        more_has(page, key, present=('projects', 'programs', 'library'))
        page.locator('#pwa-feature-list [data-feature="projects"]').click()
        page.wait_for_function("currentView === 'projects'")
        settle(page, "[...document.querySelectorAll('#projects-container [data-project-card]')].some(e => e.checkVisibility())",
               timeout=10000)
        cards = visible_cards(page, '#projects-container')
        assert any(HOUSE_PROJECT[1] in c for c in cards), ('the projects page drew no card', cards)
        assert page.locator('#tab-more').get_attribute('aria-current') == 'page', 'More is not lit on Projects'
        open_more(page)
        page.locator('#pwa-feature-list [data-feature="programs"]').click()
        page.wait_for_function("currentView !== 'more'")
        view = page.evaluate('currentView')
        assert view in ('myday', 'drives'), ('My programs went somewhere new for a lists-only adult', view)
        no_errors(served, page, key, failed)
        print('  ok  lists_only_keeps_more', flush=True)


def kid_house_projects(served):
    """Navigator and explorer: the House tab's Projects section adopts the
    projects page with the kid's own programs under it; More has neither;
    another section or another view sends #projects-container home; a deep
    link to a project lands on the section."""
    for key in ('navigator', 'explorer'):
        pid, title = OWN_PROJECT[key]
        program = KID_PROGRAM[key]
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            failed = boot(served, page, key)
            page.evaluate("() => { const n = document.getElementById('projects-container');"
                          " window._projHome = n.parentElement; window._projNext = n.nextElementSibling; }")
            home = "(() => { const n = document.getElementById('projects-container');" \
                   " return n.parentElement === window._projHome && n.nextElementSibling === window._projNext" \
                   " && !n.closest('#chores-container') && !n.checkVisibility(); })()"
            watch_opens(page)
            page.locator('#tab-chores').click()
            page.wait_for_function("currentView === 'chores'")
            page.wait_for_selector('#chores-container .child-section-tabs', timeout=10000)
            labels = [norm(t) for t in page.locator('#chores-container .child-section-tabs button').all_text_contents()]
            assert 'Projects' in labels, (key, 'the House tab has no Projects section', labels)
            tabs = page.locator('#chores-container .child-section-tabs')
            tabs.get_by_role('button', name='Projects', exact=True).click()
            settle(page, "document.getElementById('chores-container').dataset.childSection === 'projects'")
            assert page.locator('#chores-container').get_attribute('data-child-section') == 'projects', \
                (key, page.locator('#chores-container').get_attribute('data-child-section'))
            assert tabs.get_by_role('button', name='Projects', exact=True).get_attribute('aria-pressed') == 'true'
            assert page.locator('#chores-container #projects-container').count() == 1, \
                (key, '#projects-container was not adopted into the House view')
            settle(page, "[...document.querySelectorAll('#chores-container [data-project-card]')].some(e => e.checkVisibility())",
                   timeout=10000)
            cards = visible_cards(page, '#chores-container #projects-container')
            assert any(title in c for c in cards), (key, f'the kid\'s own project {title!r} is missing', cards)
            assert page.evaluate('window._projOpens') >= 1, (key, 'chf-projects-open was never dispatched')
            # The kid's own programs under it (renderProgramsSection, as My Day's).
            settle(page, f"document.getElementById('chores-container').innerText.includes({json.dumps(program)})")
            text = norm(page.locator('#chores-container').inner_text())
            assert program in text, (key, f'the kid\'s program {program!r} is not in the Projects section', text[:400])
            # Scoped to the House: My Day draws the same program earlier in the DOM (hidden).
            assert page.locator('#chores-container').get_by_text(program, exact=True).first.is_visible(), (key, program, 'not visible')
            if key == 'navigator':
                shot(page, 'kid-house-projects.png')
            else:
                shot(page, 'kid-house-projects-explorer.png')
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), (key, 'overflow')
            # Another section sends the node home.
            tabs.get_by_role('button', name='Tasks', exact=True).click()
            settle(page, "document.getElementById('chores-container').dataset.childSection === 'tasks'")
            assert page.locator('#chores-container').get_attribute('data-child-section') == 'tasks'
            settle(page, home)
            assert page.evaluate(home), (key, '#projects-container did not go home after another section')
            # So does another view.
            tabs.get_by_role('button', name='Projects', exact=True).click()
            page.wait_for_selector('#chores-container #projects-container', state='attached', timeout=10000)
            page.locator('#tab-myday').click()
            page.wait_for_function("currentView === 'myday'")
            settle(page, home)
            assert page.evaluate(home), (key, '#projects-container did not go home after leaving the House tab')
            # More offers neither; Library stays.
            more_has(page, key, present=('library',), absent=('projects', 'programs'))
            # A deep link to the kid's project lands on the House Projects section.
            page.evaluate(f"() => window.phoneOpenRecord('project', {json.dumps(pid)})")
            page.wait_for_function("currentView === 'chores'", timeout=10000)
            settle(page, "document.getElementById('chores-container').dataset.childSection === 'projects'"
                         " && !!document.querySelector('#chores-container [data-project-detail]')?.checkVisibility()",
                   timeout=10000)
            assert page.locator('#chores-container').get_attribute('data-child-section') == 'projects', \
                (key, 'phoneOpenRecord did not land on the Projects section',
                 page.locator('#chores-container').get_attribute('data-child-section'))
            detail = page.locator('#chores-container [data-project-detail]')
            assert detail.count() >= 1 and detail.first.is_visible(), (key, 'the project did not open in the section')
            assert title in norm(detail.first.inner_text()), (key, norm(detail.first.inner_text())[:200])
            assert page.evaluate('window._projectOpens') >= 1, (key, 'chf-project-open was never dispatched')
            # chfPwaOpenProjects for this kid opens the same section.
            page.locator('#tab-myday').click()
            page.wait_for_function("currentView === 'myday'")
            answer = page.evaluate('() => window.chfPwaOpenProjects()')
            assert answer is True, (key, 'chfPwaOpenProjects answered', answer)
            page.wait_for_function("currentView === 'chores'", timeout=10000)
            settle(page, "document.getElementById('chores-container').dataset.childSection === 'projects'")
            assert page.locator('#chores-container').get_attribute('data-child-section') == 'projects'
            assert page.locator('#chores-container #projects-container').count() == 1
            no_errors(served, page, key, failed)
            print('  ok  kid_house_projects', key, flush=True)


def sprout_unchanged(served):
    """A sprout's projects stay in More's own slot; its House has no Projects
    section; More offers no Projects row and no Library, as today."""
    key = 'sprout'
    pid, title = OWN_PROJECT[key]
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        ids = more_has(page, key, absent=('projects', 'library'))
        assert 'programs' in ids, ('a sprout lost My programs (it has no Projects section)', ids)
        settle(page, "[...document.querySelectorAll('#pwa-sprout-projects [data-project-card]')].some(e => e.checkVisibility())",
               timeout=10000)
        cards = visible_cards(page, '#pwa-sprout-projects')
        assert any(title in c for c in cards), ('the sprout\'s project is not in My things', cards)
        page.evaluate("setView('chores')")
        page.wait_for_function("currentView === 'chores'")
        page.wait_for_selector('#chores-container .child-section-tabs', timeout=10000)
        labels = [norm(t) for t in page.locator('#chores-container .child-section-tabs button').all_text_contents()]
        assert 'Projects' not in labels, ('a sprout\'s House grew a Projects section', labels)
        assert page.locator('#chores-container #projects-container').count() == 0
        page.evaluate(f"() => window.phoneOpenRecord('project', {json.dumps(pid)})")
        page.wait_for_selector('#pwa-sprout-projects [data-project-detail]', state='visible', timeout=10000)
        assert page.evaluate('currentView') == 'more', page.evaluate('currentView')
        no_errors(served, page, key, failed)
        print('  ok  sprout_unchanged', flush=True)


def helper_no_projects(served):
    """A helper has no Projects anywhere, as today."""
    key = 'helper'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        assert not page.locator('#tab-chores').is_visible(), 'a helper has a Household tab'
        ids = page.evaluate(FEATURE_IDS)
        assert 'projects' not in ids and 'library' not in ids, ('More offers a helper Projects or Library', ids)
        assert page.evaluate("typeof pwaHouseHasProjects !== 'function' || pwaHouseHasProjects() === false"), \
            'pwaHouseHasProjects() is true for a helper'
        watch_opens(page)
        before = page.evaluate('currentView')
        assert before != 'projects', before
        page.evaluate("() => window.phoneOpenRecord('project', %s)" % json.dumps(HOUSE_PROJECT[0]))
        page.wait_for_function("() => (document.getElementById('global-alert') || {}).textContent?.includes('projects page on a computer')",
                               timeout=5000)
        assert page.evaluate('currentView') == before, ('phoneOpenRecord moved a helper', page.evaluate('currentView'))
        assert page.evaluate('window.chfPwaOpenProjects()') is False
        assert page.evaluate('currentView') == before
        assert page.evaluate('window._projOpens + window._projectOpens') == 0, 'something opened Projects for a helper'
        assert page.locator('#chores-container #projects-container, #pwa-stack #projects-container').count() == 0
        no_errors(served, page, key, failed)
        print('  ok  helper_no_projects', flush=True)


SCENARIOS = [adult_one_door, lists_only_keeps_more, kid_house_projects, sprout_unchanged, helper_no_projects]


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
        return 0
    output = os.environ.get('PWA_REVIEW_OUTPUT')
    if output:
        SHOTS = (Path(__file__).resolve().parent / 'probe_shots' / 'pwa_slice6'
                 if output.lower() in ('1', 'true', 'yes', 'on') else Path(output))
        SHOTS.mkdir(parents=True, exist_ok=True)
    failed = 0
    try:
        for fn in SCENARIOS:
            if os.environ.get('ONE_DOOR_SCENARIO') and fn.__name__ != os.environ['ONE_DOOR_SCENARIO']:
                continue
            try:
                fn(served)
                print(f'PASS {fn.__name__}', flush=True)
            except Exception:
                failed += 1
                print(f'FAIL {fn.__name__}', flush=True)
                traceback.print_exc()
    finally:
        served.stop()
    return failed


if __name__ == '__main__':
    raise SystemExit(1 if run() else 0)
