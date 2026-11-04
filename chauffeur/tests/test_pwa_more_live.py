"""More and its destinations in the new look (slice 7 of the reimagined PWA).

For an adult, More is a list: a 34 px "More" title, a borderless search field
whose label is visually hidden, rows with a 44 px icon tile, a 16 px title, one
secondary line in the muted ink (wrapping, never ellipsized) and a chevron, no
cards and no separators. Profile's sheet takes the same rows. The destinations
More opens (Projects, Library, School, Family map, Music, the critter) take the
vocabulary through the shared adult CSS keyed on `data-pwa-skin`: the wash
shows through, cards are the translucent 22 px card with no border, Music's
now-playing is the one raised card, the dark primary is the ink, and every
visible line of text measures 4.5:1 or better against what it is drawn on
(tests/pwa_vocab_checks.py), light and dark, 360 and 390 wide. Kids and the
other hosts of the same components are untouched.

Written before the change (Codex implements Tasks 2-4), so its first failure
is `more_rows` (the title still reads "More from Chauffeur").

Members, projects, the library, school tasks and critters are seeded and
served for real; every other read the views make is mocked with page.route,
the way tests/test_projects_one_door_live.py does it, and every 4xx is named
with its URL when a scenario fails.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_more_live.py
MORE_SCENARIO=<name> runs one scenario. PWA_REVIEW_OUTPUT=1 writes the
screenshots to tests/probe_shots/pwa_slice7 (gitignored); any other value is
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
DATA = tempfile.mkdtemp(prefix='chauffeur_more_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app  # noqa: E402
from services import storage, ha_api  # noqa: E402
from pwa_projects_door import open_projects  # noqa: E402
from pwa_vocab_checks import assert_skin, check_skin, token_is  # noqa: E402

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + timedelta(days=1)).strftime('%Y-%m-%d')

# key: (role, driver, name, extra member fields)
PEOPLE = {
    'parent': ('parent', 'd1', 'Alex Morgan', {}),
    'lists_only': ('adult', 'd6', 'Jo Ellis',
                   {'scope': {'preset': 'household_adult', 'overrides': {'chores.board': 'none'}}}),
    'navigator': ('child', None, 'Sam', {'stage_override': 'navigator', 'is_child': True}),
    'sprout': ('child', None, 'Theo', {'stage_override': 'sprout', 'is_child': True}),
}
HOUSE_PROJECT = ('prj-deck', 'Rebuild the deck')
LIBRARY = {'id': 'lib-piano', 'title': 'Learn piano', 'created_by': 'parent', 'archived': False,
           'made_for': {'age_band': 'explorer', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'complete beginner'},
           'source': {'origin': 'generated', 'reason': 'test'},
           'phases': [{'id': 'ph-found', 'name': 'Foundations', 'weeks': 2, 'steps': [], 'milestone': 'Plays a C scale'}],
           'lessons': [{'id': 'ls-scales', 'phase_id': 'ph-found', 'title': 'Scales', 'sessions': 1,
                        'steps': ['C major, slowly'], 'variants': []}]}
SCHOOL_TASKS = [('Cell Lab Report', 1, 'homework'), ('Chapter 4 Quiz', 2, 'test'), ('Essay draft', 3, 'homework')]
PLAYER = {'entity_id': 'media_player.kitchen', 'name': 'Kitchen', 'state': 'playing',
          'media_title': 'Here Comes the Sun', 'media_artist': 'The Beatles', 'volume_level': 0.4}
LOCATIONS = [
    {'member_id': 'parent', 'name': 'Alex Morgan', 'state': 'home', 'latitude': 40.0, 'longitude': -83.0,
     'color_code': '#287a72'},
    # No coordinates: tracked by zone only, so it draws as a chip over the map.
    {'member_id': 'navigator', 'name': 'Sam', 'state': 'School', 'color_code': '#7a2850'},
]
DESTINATIONS = ('projects', 'library', 'music', 'map', 'school', 'critter')

BAD_RESPONSES = []
SHOTS = None


def seed():
    from models.schemas import KidTask
    for key, (role, driver, name, extra) in PEOPLE.items():
        storage.add_member(dict({'id': key, 'name': name, 'role': role, 'driver_id': driver,
                                 'color_code': '#287a72'}, **extra))
        if driver:
            storage.add_driver({'id': driver, 'name': name, 'home_location': 'Home', 'color_code': '#287a72'})
    pid, title = HOUSE_PROJECT
    storage.add_project({'id': pid, 'title': title, 'goal': 'a safe deck', 'done_when': 'we eat on it',
                         'owner_member_id': 'parent', 'created_by': 'parent', 'audience': 'household',
                         'pieces': [], 'steps': []})
    storage.set_app_state('projects_adopted_rev', 1)
    storage.add_library_program(json.loads(json.dumps(LIBRARY)))
    sci = storage.ensure_school_class('navigator', 'course_88', 'Biology')
    for task, days, kind in SCHOOL_TASKS:
        due = (NOW + timedelta(days=days)).strftime('%Y-%m-%d')
        storage.add_kid_task(KidTask(member_id='navigator', source='ics', title=task, due_date=due, kind=kind,
                                     course_key='course_88', course_label=sci['label']).model_dump())


# --- the mocked reads ----------------------------------------------------------

def install_mocks(page, key):
    """Every read the shell, My Day, Household, Music and the map make, except
    members, projects, library, kid tasks and pets, which the server answers."""
    schedule = {'events': [], 'assignments': {}, 'home_location': 'Home', 'calendar_metadata': {},
                'initial_edges': {}, 'route_edges': {}, 'final_edges': {}}
    page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
    page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))

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
    page.route('**/api/chores', lambda r: r.fulfill(json=[dict(id='plants', title='Water the plants', points=5,
                                                               state='open', eligible_member_ids=[])]))
    page.route('**/api/points', lambda r: r.fulfill(json=[{'member_id': key, 'name': PEOPLE[key][2], 'balance': 20}]))
    page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
    page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))
    page.route(re.compile(r'.*/api/household-tasks(\?[^/]*)?$'), lambda r: r.fulfill(json=[]))
    groceries = {'id': 'groceries', 'name': 'Groceries', 'is_default': True, 'audience': 'household',
                 'shared_with': [], 'open_count': 1, 'checked_count': 0}
    page.route(re.compile(r'.*/api/shopping/lists(\?.*)?$'), lambda r: r.fulfill(json=[groceries]))
    item = {'id': 'g1', 'list_id': 'groceries', 'name': 'Milk', 'qty': None, 'note': None, 'added_by': 'parent',
            'added_via': 'manual', 'is_checked': False, 'image_id': None, 'claims': [], 'buy_on': None,
            'deadline': None}
    page.route(re.compile(r'.*/api/shopping/items(\?.*)?$'), lambda r: r.fulfill(json=[item]))
    page.route(re.compile(r'.*/api/shopping/runs(\?.*)?$'), lambda r: r.fulfill(json={
        'shop_date': TOMORROW, 'groups': [], 'runs': {'guess': TOMORROW, 'scheduled': None, 'next': TOMORROW},
        'late': [], 'top_up': False, 'counts': {}}))
    page.route('**/api/projects/elsewhere*', lambda r: r.fulfill(json={'situations': []}))

    def programs_list(route):
        if route.request.method != 'GET':
            return route.continue_()
        route.fulfill(json={'programs': []})
    page.route(re.compile(r'.*/api/programs(\?.*)?$'), programs_list)
    page.route('**/api/practice-windows*', lambda r: r.fulfill(json={'windows': []}))
    page.route('**/api/situations?*', lambda r: r.fulfill(json={'situations': []}))
    # Music (static/music_logic.js) and the map (family_map_core.html).
    page.route(re.compile(r'.*/api/ha/media_players(\?.*)?$'), lambda r: r.fulfill(json=[PLAYER]))
    page.route('**/api/music/my?*', lambda r: r.fulfill(json={'favorites': [], 'recent': []}))
    page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))
    page.route('**/api/music/now?*', lambda r: r.fulfill(status=200, content_type='application/json', body='null'))
    page.route('**/api/music/shelves*', lambda r: r.fulfill(json={'available': False, 'recently_played': [],
                                                                  'recommendations': []}))
    page.route('**/api/music/queue?*', lambda r: r.fulfill(json={'items': []}))
    page.route('**/api/music/playlists/editable*', lambda r: r.fulfill(json=[]))
    page.route('**/api/family/locations*', lambda r: r.fulfill(json=LOCATIONS))


# --- page helpers --------------------------------------------------------------

def norm(text):
    return ' '.join((text or '').split())


def shot(page, name):
    if SHOTS:
        page.wait_for_timeout(300)
        Path(SHOTS, name).write_bytes(page.screenshot())


def settle(page, condition, timeout=8000):
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


def boot(served, page, key, theme='light', width=390):
    role, driver = PEOPLE[key][0], PEOPLE[key][1]
    failed_assets = []
    page.on('requestfailed', lambda request: failed_assets.append(
        (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
    page.on('response', lambda response: failed_assets.append(
        (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
        and response.status >= 400 else None)
    page.on('response', lambda response: BAD_RESPONSES.append(
        (key, response.status, response.url.split('?')[0])) if response.status >= 400 else None)
    page.set_viewport_size({'width': width, 'height': 844})
    page.clock.set_fixed_time(NOW)

    def static_asset(route):
        if route.request.resource_type in ('script', 'stylesheet'):
            route.fulfill(response=route.fetch(max_retries=2))
        else:
            route.continue_()
    page.route('**/static/**', static_asset)
    token = storage.create_member_token(key)
    values = {'chauffeur_member_id': key, 'chauffeur_member_token': token, 'chauffeur_member_token_for': key,
              'chauffeur_view': 'myday', 'chauffeur_theme': theme}
    if driver:
        values['chauffeur_driver_id'] = driver
    page.add_init_script("if (!sessionStorage.getItem('chf_test_seeded')) { Object.entries(" + json.dumps(values)
                         + ").forEach(([k, v]) => localStorage.setItem(k, v)); sessionStorage.setItem('chf_test_seeded', '1'); }")
    install_mocks(page, key)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    wait_app(page)
    assert page.evaluate('selectedMemberId') == key, page.evaluate('selectedMemberId')
    assert page.evaluate('currentMemberRole()') == role, page.evaluate('currentMemberRole()')
    if role == 'child':
        settle(page, f"pwaChildStage() === '{key}'")
    return failed_assets


def no_errors(served, page, key, failed_assets):
    errors = list(served.errors())
    bad = [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key]
    assert not errors and not failed_assets and not bad, (key, errors, bad, failed_assets)


def open_more(page):
    page.locator('#tab-more').click()
    page.wait_for_function("currentView === 'more'")
    page.wait_for_selector('#pwa-feature-list > button')


def row(page, feature):
    return page.locator(f'#pwa-feature-list [data-feature="{feature}"]')


GUIDE = '[x-data="petGuidePanel()"]'


def close_guide(page):
    """The critter guide opens by itself the first time someone with no
    critter reaches the editor (pet_guide.html maybeOpenPetGuide); close it."""
    settle(page, f"!!document.querySelector('{GUIDE}')?.checkVisibility()", timeout=2000)
    if page.locator(GUIDE).is_visible():
        page.locator(GUIDE).get_by_role('button', name='Got it!').click()
        page.wait_for_selector(GUIDE, state='hidden', timeout=5000)


def visit(page, name):
    """Open one destination from More (or Projects through its door); returns
    the host selector the vocabulary is measured on, and the kwargs for
    check_skin."""
    if name == 'projects':
        door = open_projects(page)
        if door == 'household':
            settle(page, "[...document.querySelectorAll('#pwa-stack [data-project-card]')].some(e => e.checkVisibility())",
                   timeout=10000)
            return '#pwa-stack .pwa-screen #projects-container', {'cards': '[data-project-card]'}
        return '#projects-container', {'title': '#projects-container .panel-page-title', 'cards': '[data-project-card]'}
    open_more(page)
    if name == 'library':
        row(page, 'library').click()
        page.wait_for_function("currentView === 'library'")
        page.wait_for_selector('#library-container [data-library-card]', state='visible', timeout=10000)
        return '#library-container', {'title': '#library-container .panel-page-title', 'cards': '[data-library-card]'}
    if name == 'music':
        row(page, 'music').click()
        page.wait_for_function("currentView === 'music'")
        page.wait_for_selector('#mw-nowplaying', state='visible', timeout=10000)
        return '#music-container', {'title': '#pwa-page-heading h2', 'raised': '#mw-nowplaying'}
    if name == 'map':
        row(page, 'map').click()
        page.wait_for_function("currentView === 'map'")
        page.wait_for_selector('#family-map-chips > *', state='visible', timeout=10000)
        return '#map-container', {}
    if name == 'school':
        row(page, 'school').click()
        if PEOPLE[page.evaluate('selectedMemberId')][0] != 'child':
            choice = page.locator('.pwa-prompt-overlay').get_by_role('button', name='Sam', exact=True)
            choice.wait_for(state='visible', timeout=5000)
            choice.click()
        page.wait_for_selector('#pwa-school-overlay [onclick^="openKidTaskDetail"]', state='visible', timeout=10000)
        return '#pwa-school-overlay .pwa-sheet', {}
    if name == 'critter':
        row(page, 'critter').click()
        page.wait_for_selector('#pet-editor-panel', state='visible', timeout=10000)
        settle(page, "!!document.querySelector('#pet-editor-panel .pet-preview svg')", timeout=10000)
        close_guide(page)
        return '#pet-editor-panel', {}
    raise ValueError(name)


def leave(page, name):
    """Close what visit() opened so the next visit starts from the tab bar."""
    if name == 'school':
        page.evaluate('pwaSchoolClose()')
    elif name == 'critter':
        page.evaluate("Alpine.$data(document.getElementById('pet-editor-panel')).close()")
        page.wait_for_selector('#pet-editor-panel', state='hidden', timeout=5000)
    elif name == 'projects' and page.evaluate('!!window.PwaNav && PwaNav.depth() > 0'):
        page.evaluate('PwaNav.clear()')
        page.wait_for_function('PwaNav.depth() === 0')


# --- scenarios -----------------------------------------------------------------

def checker_catches_a_grey(served):
    """The checker reports a faint line, so a green run means something."""
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        open_more(page)
        page.evaluate("""() => { const p = document.createElement('p'); p.id = 'vocab-probe';
            p.style.color = '#d4d3dc'; p.textContent = 'Faint words';
            document.getElementById('pwa-more-container').append(p); }""")
        report = check_skin(page, '#pwa-more-container')
        assert any(f['text'] == 'Faint words' for f in report['failures']), ('the checker missed a faint line', report)
        page.evaluate("document.getElementById('vocab-probe').remove()")
        # A Tailwind grey on a translucent card inside a skinned host, with
        # the adult map off: the composite path must report it too.
        page.evaluate("""() => { document.documentElement.dataset.audience = 'child';
            const host = document.createElement('div'); host.id = 'vocab-host'; host.setAttribute('data-pwa-skin', '');
            host.innerHTML = '<div style="background: var(--pwa-card); padding: 12px"><p class="text-gray-600">Grey on a card</p></div>';
            document.getElementById('pwa-more-container').append(host); }""")
        report = check_skin(page, '#vocab-host')
        page.evaluate("() => { document.getElementById('vocab-host').remove(); document.documentElement.dataset.audience = 'adult'; }")
        assert any(f['text'] == 'Grey on a card' for f in report['failures']), ('the composite path missed a grey', report)
        no_errors(served, page, key, failed)
        print('  ok  checker_catches_a_grey', flush=True)


ROW_PROBLEMS = r"""() => {
    const probe = document.createElement('span'); document.body.append(probe);
    const resolve = v => { probe.style.color = ''; probe.style.color = v; return getComputedStyle(probe).color; };
    const muted = resolve(getComputedStyle(document.documentElement).getPropertyValue('--pwa-msg-muted').trim());
    const problems = [];
    const rows = [...document.querySelectorAll('#pwa-feature-list .pwa-feature')].filter(e => e.checkVisibility());
    if (!rows.length) problems.push('no rows');
    for (const r of rows) {
        const id = r.dataset.feature, cs = getComputedStyle(r), box = r.getBoundingClientRect();
        const borders = ['Top', 'Right', 'Bottom', 'Left'].map(s => parseFloat(cs['border' + s + 'Width']));
        if (borders.some(w => w > 0)) problems.push(`${id}: border ${borders.join('/')}`);
        if (!/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor)) problems.push(`${id}: background ${cs.backgroundColor}`);
        if (box.height < 56) problems.push(`${id}: height ${box.height}`);
        const icon = r.querySelector('.pwa-feature-icon');
        const ib = icon && icon.getBoundingClientRect();
        if (!icon || Math.round(ib.width) !== 44 || Math.round(ib.height) !== 44) problems.push(`${id}: icon ${ib && ib.width}x${ib && ib.height}`);
        else if (parseFloat(getComputedStyle(icon).borderTopLeftRadius) < 12) problems.push(`${id}: icon radius`);
        const title = r.querySelector('div > span'), small = r.querySelector('small');
        if (!title || getComputedStyle(title).fontSize !== '16px' || getComputedStyle(title).fontWeight !== '600')
            problems.push(`${id}: title ${title && getComputedStyle(title).fontSize}/${title && getComputedStyle(title).fontWeight}`);
        if (!small || getComputedStyle(small).fontSize !== '14px') problems.push(`${id}: description size`);
        else if (getComputedStyle(small).color !== muted) problems.push(`${id}: description ${getComputedStyle(small).color} (want ${muted})`);
        else if (getComputedStyle(small).textOverflow === 'ellipsis' || small.scrollWidth > small.clientWidth + 1)
            problems.push(`${id}: description clipped`);
        const chevron = r.querySelector('.pwa-feature-chevron');
        if (!chevron || !chevron.checkVisibility()) problems.push(`${id}: no chevron`);
        else if (box.right - chevron.getBoundingClientRect().right > 24) problems.push(`${id}: chevron not at the right edge`);
        if (r.nextElementSibling && Math.round(r.nextElementSibling.getBoundingClientRect().top - box.bottom) < 0)
            problems.push(`${id}: rows overlap`);
    }
    probe.remove();
    return problems;
}"""


def more_rows(served):
    """The list, measured; the search; every row still runs its destination."""
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        open_more(page)
        title = page.locator('#pwa-more-title')
        assert norm(title.text_content()) == 'More', ('the title', norm(title.text_content()))
        assert_skin(page, '#pwa-more-container', 'more', title='#pwa-more-title')
        lead = token_is(page, '#pwa-more-container > .pwa-muted', 'color', '--pwa-msg-muted')
        assert lead is True, lead
        search = page.get_by_role('searchbox', name='Search features')
        assert search.is_visible(), 'the search field lost its accessible name'
        assert search.evaluate("e => ['Top','Right','Bottom','Left'].every(s => parseFloat(getComputedStyle(e)['border'+s+'Width']) === 0)"), \
            'the search field has a border'
        label = page.evaluate("""() => { const l = document.querySelector('label[for="pwa-feature-search"]');
            const r = l.getBoundingClientRect(); return {w: r.width, h: r.height}; }""")
        assert label['w'] <= 1 and label['h'] <= 1, ('the label is still drawn', label)
        problems = page.evaluate(ROW_PROBLEMS)
        assert not problems, problems
        listed = page.evaluate("[...document.querySelectorAll('#pwa-feature-list [data-feature]')].map(b => b.dataset.feature)")
        for fid in ('library', 'map', 'music', 'school', 'critter', 'profile'):
            assert fid in listed, (fid, 'missing from More', listed)
        shot(page, 'more-light.png')
        # 360: the longest description wraps rather than clipping.
        page.set_viewport_size({'width': 360, 'height': 780})
        page.wait_for_timeout(100)
        problems = page.evaluate(ROW_PROBLEMS)
        assert not problems, ('360', problems)
        lines = row(page, 'school').locator('small').evaluate(
            "e => Math.round(e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight))")
        assert lines >= 2, ('the School description did not wrap at 360', lines)
        shot(page, 'more-360.png')
        page.set_viewport_size({'width': 390, 'height': 844})
        # Search: filter, the no-match line in the muted ink, clear.
        search.fill('map')
        assert page.evaluate("[...document.querySelectorAll('#pwa-feature-list [data-feature]')].map(b => b.dataset.feature)") == ['map']
        search.fill('no-match-xyz')
        assert page.locator('#pwa-search-empty').is_visible()
        empty = token_is(page, '#pwa-search-empty', 'color', '--pwa-msg-muted')
        assert empty is True, empty
        search.fill('')
        # Every row still runs.
        for name in ('map', 'music', 'library'):
            open_more(page)
            row(page, name).click()
            page.wait_for_function(f"currentView === '{name}'")
            assert page.locator('#tab-more').get_attribute('aria-current') == 'page', (name, 'More is not lit')
        for name in ('school', 'critter'):
            visit(page, name)
            leave(page, name)
        open_more(page)
        row(page, 'profile').click()
        page.wait_for_selector('#pwa-profile', state='visible')
        page.keyboard.press('Escape')
        no_errors(served, page, key, failed)
        print('  ok  more_rows', flush=True)


def profile_sheet(served):
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        page.locator('#pwa-identity').click()
        page.wait_for_selector('#pwa-profile', state='visible')
        bg = token_is(page, '#pwa-profile', 'backgroundColor', '--pwa-card-raised')
        assert bg is True, bg
        shape = page.locator('#pwa-profile').evaluate("""e => { const cs = getComputedStyle(e);
            return {r: cs.borderTopLeftRadius, b: ['Top','Right','Bottom','Left'].map(s => parseFloat(cs['border'+s+'Width']))}; }""")
        assert shape['r'] == '22px' and not any(shape['b']), shape
        rows = page.locator('#pwa-profile .pwa-feature').evaluate_all(
            "rs => rs.filter(r => r.checkVisibility()).map(r => parseFloat(getComputedStyle(r).borderBottomWidth))")
        assert rows and not any(rows), ('Profile rows keep their separators', rows)
        assert_skin(page, '#pwa-profile', 'profile')
        chevrons = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#pwa-profile .pwa-feature[data-feature]')]
            .filter(r => r.checkVisibility()).map(r => [r.dataset.feature, !!r.querySelector('.pwa-feature-chevron')?.checkVisibility()]))""")
        for fid in ('avatar', 'critter', 'voice'):
            if fid in chevrons:
                assert chevrons[fid], (fid, 'a row that opens something lost its chevron', chevrons)
        for fid in ('theme', 'refresh', 'push', 'voice-delete', 'switch'):
            if fid in chevrons:
                assert not chevrons[fid], (fid, 'an in-place action shows a chevron', chevrons)
        shot(page, 'profile-light.png')
        page.locator('#pwa-profile [data-feature="theme"]').click()
        assert page.locator('#pwa-profile').is_visible(), 'Appearance closed Profile'
        page.keyboard.press('Escape')
        # The voice-setup dialog's actions share the .pwa-feature class: they
        # stay buttons (border and fill), not borderless rows.
        page.evaluate("document.getElementById('pwa-voice-setup').showModal()")
        start = page.locator('#pwa-voice-setup-start').evaluate("""e => { const cs = getComputedStyle(e);
            return {b: parseFloat(cs.borderTopWidth), bg: cs.backgroundColor, h: e.getBoundingClientRect().height}; }""")
        assert start['b'] >= 1 and start['bg'] not in ('rgba(0, 0, 0, 0)', 'transparent') and start['h'] < 56,             ('the voice-setup Start button lost its button look', start)
        page.evaluate("document.getElementById('pwa-voice-setup').close()")
        no_errors(served, page, key, failed)
        print('  ok  profile_sheet', flush=True)


def projects_both_doors(served):
    """Household's pushed screen (parent) and More (lists-only adult) skin the
    same; the pushed screen's own h1 replaces the component's title."""
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        host, kw = visit(page, 'projects')
        assert host.startswith('#pwa-stack'), host
        assert_skin(page, host, 'projects (household)', **kw)
        assert not page.locator('#pwa-stack #projects-container .panel-page-title').is_visible()
        assert page.locator('#pwa-stack .pwa-screen h1').last.is_visible()
        shot(page, 'projects-light.png')
        # A project opens inside the same skin.
        page.locator('#pwa-stack [data-project-card]').first.click()
        page.wait_for_selector('#pwa-stack [data-project-detail]', state='visible', timeout=10000)
        assert_skin(page, host, 'project detail')
        no_errors(served, page, key, failed)
    key = 'lists_only'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        page.wait_for_function("document.getElementById('tab-chores').style.display !== 'none'"
                               " && houseRevealListsOnly === true", timeout=10000)
        host, kw = visit(page, 'projects')
        assert host == '#projects-container', host
        settle(page, "[...document.querySelectorAll('#projects-container [data-project-card]')].some(e => e.checkVisibility())",
               timeout=10000)
        assert_skin(page, host, 'projects (more)', **kw)
        shot(page, 'projects-more-light.png')
        no_errors(served, page, key, failed)
    print('  ok  projects_both_doors', flush=True)


def library(served):
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        host, kw = visit(page, 'library')
        assert_skin(page, host, 'library', **kw)
        coloured = page.evaluate("""() => [...document.querySelectorAll('#library-container :is(.bg-teal-700, .bg-blue-600, .bg-emerald-600)')]
            .filter(e => e.tagName === 'BUTTON' && e.checkVisibility()).map(e => e.id || e.textContent.trim().slice(0, 30))""")
        for i, label in enumerate(coloured):
            ink = page.evaluate("""([i]) => { const b = [...document.querySelectorAll('#library-container :is(.bg-teal-700, .bg-blue-600, .bg-emerald-600)')]
                .filter(e => e.tagName === 'BUTTON' && e.checkVisibility())[i]; b.id = b.id || 'vocab-btn-' + i; return b.id; }""", [i])
            verdict = token_is(page, '#' + ink, 'backgroundColor', '--pwa-ink')
            assert verdict is True, (label, verdict)
        # Error and warning lines keep their colour (a cue, not decoration).
        page.evaluate("""() => { const p = document.createElement('div'); p.id = 'vocab-cues';
            p.innerHTML = '<p id="vocab-err" class="text-xs text-red-400">Could not save the lesson.</p>'
                + '<p id="vocab-warn" class="text-xs text-amber-300">Pick the day it is due.</p>';
            document.querySelector('#library-container [data-library-page]').prepend(p); }""")
        cues = page.evaluate("""() => ['vocab-err', 'vocab-warn'].map(id => getComputedStyle(document.getElementById(id)).color.match(/[\\d.]+/g).map(Number))""")
        err, warn = cues
        assert err[0] > err[1] + 40 and err[0] > err[2] + 40, ('an error line lost its red', err)
        assert warn[0] > warn[2] + 40 and warn[1] > warn[2] + 20, ('a warning line lost its amber', warn)
        assert_skin(page, '#vocab-cues', 'error and warning lines')
        page.evaluate("document.getElementById('vocab-cues').remove()")
        # Destructive verbs keep their red (a cue, not decoration).
        red = page.evaluate("""() => { const d = [...document.querySelectorAll('#library-container [data-library-card] button')]
            .find(b => b.textContent.trim() === 'Delete' && b.checkVisibility());
            if (!d) return null; const c = getComputedStyle(d).color.match(/[\\d.]+/g).map(Number); return c; }""")
        assert red and red[0] > red[1] + 40 and red[0] > red[2] + 40, ('Delete lost its red', red)
        shot(page, 'library-light.png')
        # A program opens in place, in the same skin, and Back returns.
        page.locator('#library-container [data-library-open]').first.click()
        page.wait_for_selector('#library-container [data-library-card]', state='hidden', timeout=10000)
        assert_skin(page, host, 'library program')
        page.evaluate("Alpine.$data(document.querySelector('#library-container [data-library-page]')).back()")
        page.wait_for_selector('#library-container [data-library-card]', state='visible', timeout=10000)
        no_errors(served, page, key, failed)
        print('  ok  library', flush=True)


def music(served):
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        host, kw = visit(page, 'music')
        assert norm(page.locator('#pwa-page-heading h2').text_content()) == 'Music'
        assert_skin(page, host, 'music', **kw)
        widget = page.locator('#music-widget').evaluate("""e => { const cs = getComputedStyle(e);
            return {bg: cs.backgroundColor, b: ['Top','Right','Bottom','Left'].map(s => parseFloat(cs['border'+s+'Width']))}; }""")
        assert widget['bg'] in ('rgba(0, 0, 0, 0)', 'transparent') and not any(widget['b']), \
            ('the widget is still one big card', widget)
        play = token_is(page, '#mw-playpause', 'backgroundColor', '--pwa-ink')
        assert play is True, play
        round_ = page.locator('#mw-playpause').evaluate(
            "e => parseFloat(getComputedStyle(e).borderTopLeftRadius) >= e.getBoundingClientRect().height / 2 - 1")
        assert round_, 'the play button is no longer round'
        # A selected filter chip still reads as selected (music_widget.html _MW_CHIP_ON / _OFF).
        page.evaluate("""() => { const chip = 'shrink-0 px-2.5 py-1 rounded-full text-xs font-bold border';
            const host = document.getElementById('mw-search-filters'); host.style.display = 'flex';
            host.innerHTML = `<button id="vocab-chip-on" class="${chip} bg-blue-600 border-blue-500 text-white">Tracks</button>`
                + `<button id="vocab-chip-off" class="${chip} bg-gray-800 border-gray-700 text-gray-300">Albums</button>`; }""")
        on = token_is(page, '#vocab-chip-on', 'backgroundColor', '--pwa-ink')
        assert on is True, ('a selected music chip does not read as selected', on)
        assert token_is(page, '#vocab-chip-off', 'backgroundColor', '--pwa-ink') is not True, 'an unselected chip reads as selected'
        assert_skin(page, '#mw-search-filters', 'music chips')
        page.evaluate("() => { const h = document.getElementById('mw-search-filters'); h.innerHTML = ''; h.style.display = 'none'; }")
        assert page.locator('#mw-search').evaluate(
            "e => ['Top','Right','Bottom','Left'].every(s => parseFloat(getComputedStyle(e)['border'+s+'Width']) === 0)"), \
            'the music search has a border'
        dividers = page.evaluate("""() => [...document.querySelectorAll('#music-container :is(#mw-results, #mw-fav-tracks, #mw-queue) > *')]
            .filter(e => e.checkVisibility()).map(e => parseFloat(getComputedStyle(e).borderTopWidth)).filter(w => w > 0)""")
        assert not dividers, ('hairlines between music rows', dividers)
        shot(page, 'music-light.png')
        no_errors(served, page, key, failed)
        print('  ok  music', flush=True)


def map_view(served):
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        host, kw = visit(page, 'map')
        box = page.evaluate("""() => { const m = document.getElementById('family-map'), c = document.getElementById('map-container');
            const a = m.getBoundingClientRect(), b = c.getBoundingClientRect(), cs = getComputedStyle(m);
            return {w: a.width, cw: b.width, left: a.left - b.left, h: a.height, r: cs.borderTopLeftRadius,
                    filter: cs.filter, opacity: cs.opacity}; }""")
        assert abs(box['w'] - box['cw']) <= 1 and abs(box['left']) <= 1, ('the map is no longer full-bleed', box)
        assert box['h'] >= 300 and box['r'] == '0px' and box['filter'] == 'none' and box['opacity'] == '1', box
        chips = page.locator('#family-map-chips').evaluate("""e => { const cs = getComputedStyle(e);
            return {bg: cs.backgroundColor, b: parseFloat(cs.borderBottomWidth)}; }""")
        assert chips['bg'] in ('rgba(0, 0, 0, 0)', 'transparent') and chips['b'] == 0, ('the chip band', chips)
        pills = page.evaluate("""() => [...document.querySelectorAll('#family-map-chips > *')].map(e => {
            const cs = getComputedStyle(e), r = e.getBoundingClientRect();
            return {pill: parseFloat(cs.borderTopLeftRadius) >= r.height / 2 - 1,
                    b: ['Top','Right','Bottom','Left'].map(s => parseFloat(cs['border'+s+'Width'])).some(w => w > 0)}; })""")
        assert pills and all(p['pill'] and not p['b'] for p in pills), ('chips', pills)
        page.evaluate("document.querySelector('#family-map-chips > *').id = 'vocab-chip'")
        chip = token_is(page, '#vocab-chip', 'backgroundColor', '--pwa-card-raised')
        assert chip is True, chip
        assert_skin(page, host, 'map')
        shot(page, 'map-light.png')
        no_errors(served, page, key, failed)
        print('  ok  map_view', flush=True)


def school(served):
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        host, kw = visit(page, 'school')
        assert page.locator(host).get_attribute('data-pwa-skin') is not None, 'the adult School sheet is not marked'
        bg = token_is(page, host, 'backgroundColor', '--pwa-card-raised')
        assert bg is True, bg
        assert_skin(page, host, 'school')
        rows = page.evaluate("""() => [...document.querySelectorAll('#pwa-school-overlay [onclick^="openKidTaskDetail"]')]
            .map(b => parseFloat(getComputedStyle(b.parentElement).borderTopRightRadius))""")
        assert rows and all(r >= 12 for r in rows), ('school rows', rows)
        shot(page, 'school-light.png')
        # A task's detail opens above the sheet in slice 0's sheet skin and closes back to it.
        page.locator('#pwa-school-overlay [onclick^="openKidTaskDetail"]').first.click()
        detail = page.locator('.pwa-prompt-overlay .pwa-sheet').last
        detail.wait_for(state='visible', timeout=5000)
        on_top = detail.evaluate("e => { const r = e.getBoundingClientRect(); return e.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); }")
        assert on_top, 'the task detail is not above the School sheet'
        assert detail.get_attribute('data-pwa-skin') is None
        page.locator('.pwa-prompt-overlay [data-pwa-dismiss]').last.click()
        detail.wait_for(state='detached', timeout=5000)
        assert page.locator(host).is_visible(), 'closing the detail closed School'
        no_errors(served, page, key, failed)
        print('  ok  school', flush=True)


def critter(served):
    key = 'parent'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        # First visit: the guide opens over the editor; it sits on the wash too.
        open_more(page)
        row(page, 'critter').click()
        page.wait_for_selector(GUIDE, state='visible', timeout=10000)
        guide = page.locator(GUIDE).evaluate("""e => ({img: getComputedStyle(e).backgroundImage,
            marked: e.hasAttribute('data-pwa-skin')})""")
        assert guide['marked'] and 'gradient' in guide['img'], ('the critter guide does not sit on the wash', guide)
        page.locator(GUIDE).get_by_role('button', name='Got it!').evaluate("e => e.id = 'vocab-got-it'")
        got = token_is(page, '#vocab-got-it', 'backgroundColor', '--pwa-ink')
        assert got is True, got
        page.evaluate(f"document.querySelector('{GUIDE}').id = 'vocab-guide'")
        assert_skin(page, '#vocab-guide', 'critter guide')
        shot(page, 'critter-guide-light.png')
        close_guide(page)
        host = '#pet-editor-panel'
        settle(page, "!!document.querySelector('#pet-editor-panel .pet-preview svg')", timeout=10000)
        panel = page.locator(host).evaluate("""e => { const cs = getComputedStyle(e);
            return {img: cs.backgroundImage, marked: e.hasAttribute('data-pwa-skin')}; }""")
        assert panel['marked'] and 'gradient' in panel['img'], ('the critter panel does not sit on the wash', panel)
        art = page.locator('#pet-editor-panel .pet-preview').evaluate("""e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
            return {w: r.width, h: r.height, opacity: cs.opacity, filter: cs.filter}; }""")
        assert art['w'] >= 100 and art['h'] >= 100 and art['opacity'] == '1' and art['filter'] == 'none', art
        save = page.locator('#pet-editor-panel').get_by_role('button', name=re.compile(r'^(Save|Hatch)', re.I)).first
        save.evaluate("e => e.id = e.id || 'vocab-save'")
        ink = token_is(page, '#' + save.evaluate('e => e.id'), 'backgroundColor', '--pwa-ink')
        assert ink is True, ink
        assert_skin(page, host, 'critter')
        tiles = page.evaluate("""() => [...document.querySelectorAll('#pet-editor-panel .pet-parts > button')].filter(b => b.checkVisibility())
            .map(b => parseFloat(getComputedStyle(b).borderTopLeftRadius) < b.getBoundingClientRect().height / 2 - 1)""")
        assert tiles and all(tiles), ('critter part tiles are cropped into circles', tiles)
        shot(page, 'critter-light.png')
        leave(page, 'critter')
        no_errors(served, page, key, failed)
        print('  ok  critter', flush=True)


def contrast(served):
    """Every destination in dark at 390, and light and dark at 360."""
    key = 'parent'
    for theme, width in (('dark', 390), ('light', 360), ('dark', 360)):
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            failed = boot(served, page, key, theme=theme, width=width)
            assert page.evaluate('document.documentElement.dataset.theme') == theme
            open_more(page)
            assert_skin(page, '#pwa-more-container', f'more {theme} {width}', title='#pwa-more-title')
            if width == 390:
                shot(page, f'more-{theme}.png')
            for name in DESTINATIONS:
                page.locator('#tab-myday').click()
                page.wait_for_function("currentView === 'myday'")
                if name == 'critter':
                    # The first-visit guide, measured before visit() closes it.
                    open_more(page)
                    row(page, 'critter').click()
                    page.wait_for_selector(GUIDE, state='visible', timeout=10000)
                    page.evaluate(f"document.querySelector('{GUIDE}').id = 'vocab-guide'")
                    assert_skin(page, '#vocab-guide', f'critter guide {theme} {width}')
                    close_guide(page)
                    leave(page, 'critter')
                    page.locator('#tab-myday').click()
                    page.wait_for_function("currentView === 'myday'")
                host, kw = visit(page, name)
                assert_skin(page, host, f'{name} {theme} {width}', **kw)
                if name == 'school':
                    page.locator('#pwa-school-overlay [onclick="pwaSchoolMode(\'month\')"]').click()
                    page.wait_for_timeout(300)
                    assert_skin(page, host, f'school month {theme} {width}')
                    if width == 390:
                        shot(page, f'school-month-{theme}.png')
                if width == 390:
                    shot(page, f'{name}-{theme}.png')
                leave(page, name)
            no_errors(served, page, key, failed)
    print('  ok  contrast', flush=True)


def other_hosts_untouched(served):
    """The stylesheet reaches only app.html; kids keep their look."""
    templates = ROOT / 'chauffeur' / 'templates'
    linked = [p.name for p in templates.rglob('*.html') if p.name != 'app.html'
              and 'pwa_shell.css' in p.read_text(encoding='utf-8')]
    assert not linked, ('pwa_shell.css is linked outside app.html', linked)
    key = 'navigator'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        host, kw = visit(page, 'school')
        assert page.locator(host).get_attribute('data-pwa-skin') is None, 'a kid School sheet is marked'
        kid_bg = page.locator(host).evaluate("""e => { const p = document.createElement('span'); document.body.append(p);
            p.style.color = 'rgb(' + getComputedStyle(document.documentElement).getPropertyValue('--c-gray-900').trim() + ')';
            const want = getComputedStyle(p).color; p.remove(); return [getComputedStyle(e).backgroundColor, want]; }""")
        assert kid_bg[0] == kid_bg[1], ('the kid School sheet changed', kid_bg)
        page.evaluate('pwaSchoolClose()')
        open_more(page)
        chevrons = page.evaluate("[...document.querySelectorAll('#pwa-feature-list .pwa-feature-chevron')].filter(e => e.checkVisibility()).length")
        assert chevrons == 0, ('a kid More row grew a chevron', chevrons)
        no_errors(served, page, key, failed)
    key = 'sprout'
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        failed = boot(served, page, key)
        open_more(page)
        assert page.locator('#pwa-feature-list').evaluate("e => getComputedStyle(e).display") == 'grid'
        chevrons = page.evaluate("[...document.querySelectorAll('#pwa-feature-list .pwa-feature-chevron')].filter(e => e.checkVisibility()).length")
        assert chevrons == 0, ('a sprout More tile grew a chevron', chevrons)
        no_errors(served, page, key, failed)
    print('  ok  other_hosts_untouched', flush=True)


SCENARIOS = [checker_catches_a_grey, more_rows, profile_sheet, projects_both_doors, library, music, map_view,
             school, critter, contrast, other_hosts_untouched]


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
        SHOTS = (Path(__file__).resolve().parent / 'probe_shots' / 'pwa_slice7'
                 if output.lower() in ('1', 'true', 'yes', 'on') else Path(output))
        SHOTS.mkdir(parents=True, exist_ok=True)
    failed = 0
    try:
        for fn in SCENARIOS:
            if os.environ.get('MORE_SCENARIO') and fn.__name__ != os.environ['MORE_SCENARIO']:
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
