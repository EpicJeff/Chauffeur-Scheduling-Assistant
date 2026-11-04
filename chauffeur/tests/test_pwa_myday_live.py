"""My Day, the warm brief, in the served PWA for every adult (slice 1, Task 6).

One My Day for the parent who drives, the adult who drives, and the
keeping-up adult who does not: the date line and its pencil, the greeting and
the weather, Argyle's sentence built from the rows on the page, the hero for
the next thing of any kind, the Needs-you pile, and the day collapsed behind
a fade. Written before the brief exists (Task 7 makes it green), so its first
failure is the missing `.pwa-brief-greet`.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_myday_live.py
Optional PWA_REVIEW_OUTPUT writes the screenshots; PWA_REVIEW_PROFILE runs one.
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
DATA = tempfile.mkdtemp(prefix='chauffeur_myday_brief_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + timedelta(days=1)).strftime('%Y-%m-%d')
IN_FIVE = (NOW + timedelta(days=5)).strftime('%Y-%m-%d')
PROFILES = [('parent', 'parent', 'd1'), ('adult', 'adult', 'd2'), ('keeping', 'parent', None)]
DAY_OPEN_KEY = 'chauffeur_myday_day_open'


def seed():
    for key, role, driver in PROFILES:
        member = {'id': key, 'name': 'Alex Morgan', 'role': role,
                  'driver_id': driver, 'color_code': '#287a72'}
        if key == 'keeping':
            member['scope'] = {'preset': 'keeping_up'}
        storage.add_member(member)
        if driver:
            storage.add_driver({'id': driver, 'name': 'Alex Morgan',
                                'home_location': 'Home', 'color_code': '#287a72'})


# --- fixtures, one set per profile ------------------------------------------

def schedule_for(driver):
    """The adult-shell schedule: a past morning appointment, soccer with a
    stamped approach (travel 20 + buffer 5), piano after it."""
    event = {'id': 'soccer', 'title': 'Soccer practice',
             'start': DAY + 'T16:00:00', 'end': DAY + 'T17:00:00',
             'location': 'Riverside fields', 'calendar_ids': [], 'event_type': 'activity'}
    past = dict(event, id='morning', title='Morning appointment', start=DAY + 'T09:00:00',
                end=DAY + 'T10:00:00', location='Medical center, Main Street')
    later = dict(event, id='piano', title='Piano lesson', start=DAY + 'T17:30:00',
                 end=DAY + 'T18:00:00', location='Music studio')
    return {'events': [past, event, later],
            'assignments': {'soccer': driver, 'morning': driver, 'piano': driver},
            'home_location': 'Home', 'calendar_metadata': {},
            'initial_edges': {driver: {'soccer': {'travel_mins': 20, 'buffer_before_mins': 5}}} if driver else {},
            'route_edges': {}, 'final_edges': {}}


def day_payload(key, date):
    """GET /api/members/{id}/day. Shapes are main.py's (_ride 14065-14102,
    the due_soon row 14194-14199, status_protocols.active_statuses) as
    renderMyDayCard (app.html:3342), renderDueSoonRow (:1295) and
    renderStatusBanner (:3234) read them."""
    payload = {'member_id': key, 'name': 'Alex Morgan', 'date': date,
               'rides': [], 'due_soon': [], 'still_open': [], 'status_days': [], 'launch': None}
    if date != DAY:
        return payload
    if key == 'parent':
        # A ride: somebody else (the adult, d2) drives the parent at 17:30.
        payload['rides'] = [{
            'assist': None, 'id': 'book_club', 'title': 'Book club', 'event_type': 'standard',
            'start': DAY + 'T17:30:00', 'end': DAY + 'T18:15:00',
            'span_start': None, 'span_end': None, 'location': 'Town library',
            'driver': None, 'car': None, 'status': None, 'prep': [],
            'arrive_by': None, 'depart_after': None, 'optional': False, 'optional_decision': None,
            'legs': [{'type': 'dropoff', 'start': DAY + 'T17:30:00',
                      'driver': {'member_id': 'adult', 'id': 'd2', 'name': 'Robin',
                                 'color_code': '#5b6cff', 'role': 'adult'},
                      'car': {'id': 'highlander', 'name': 'Highlander', 'icon': '🚙'},
                      'status': None}]}]
        payload['due_soon'] = [{'id': 'essay', 'title': 'History essay', 'kind': 'homework',
                                'emoji': '📚', 'due_date': TOMORROW, 'overdue': False,
                                'label': 'Tomorrow'}]
    if key == 'keeping':
        payload['status_days'] = [{
            'id': 'sick_today', 'date': DAY, 'end_date': DAY, 'day_pos': 1, 'day_count': 1,
            'is_home_day': False, 'within_span': True, 'protocol_id': 'sick', 'name': 'Sick day',
            'emoji': '🤒', 'need': '', 'need_label': '', 'member_name': 'Jamie',
            'kid_message': 'Rest up today.', 'adult_message': 'Jamie is home sick today.',
            'beat_kid_message': '', 'beat_adult_message': '', 'beat_affected_message': '',
            'set_by_name': 'Alex', 'source': 'manual'}]
    return payload


def install_mocks(page, key, driver):
    """Every read the brief makes, per profile. Returns the recorded POSTs."""
    posts = {'routine': [], 'task': []}
    schedule = schedule_for(driver)
    page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
    page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))

    def member_day(route):
        date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
        route.fulfill(json=day_payload(key, date))
    page.route('**/api/members/*/day?*', member_day)

    # renderRoutineSection (app.html:1262) reads id, title, checked,
    # time_of_day and kidGlyph(item) (emoji).
    def routine_day(route):
        date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
        items = [{'id': 'walk', 'title': 'Evening walk', 'time_of_day': '20:00',
                  'checked': False, 'emoji': '🚶'}] if date == DAY else []
        route.fulfill(json={'date': date, 'items': items, 'streak': {}})
    page.route('**/api/routines/day?*', routine_day)

    # renderRequests (app.html:3154) prints r.from and r.body; Task 4's card
    # reads from_name. Both are given.
    waiting = [{'id': 'rq1', 'from': 'Jamie', 'from_name': 'Jamie', 'from_member': 'navigator',
                'to': 'Alex', 'body': 'Can you get me at 3 instead of 4?',
                'created_at': NOW.replace(hour=14).isoformat()}] if key == 'parent' else []
    page.route('**/api/requests?*', lambda r: r.fulfill(json={'waiting_on_me': waiting, 'mine': []}))

    chores = [dict(id='dishwasher', title='Unload the dishwasher', description='Kitchen', points=10,
                   state='claimed', claimed_by=key, claimed_by_name='Alex'),
              dict(id='recycling', title='Take out recycling', points=15, state='done',
                   claimed_by='navigator', claimed_by_name='Sam'),
              dict(id='plants', title='Water the plants', points=5, state='open', eligible_member_ids=[])]
    page.route('**/api/chores', lambda r: r.fulfill(json=chores))
    page.route('**/api/points', lambda r: r.fulfill(json=[]))
    page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
    page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))

    # fetchProposals (app.html:3774) wants a list; renderProposals (:3901)
    # and initProposalEditFields read id, title, start, end, all_day,
    # location, notes; Task 4 reads source_from and status.
    proposals = [{'id': 'prop1', 'title': 'Science fair', 'start': IN_FIVE + 'T18:00:00',
                  'end': IN_FIVE + 'T20:00:00', 'all_day': False, 'location': 'School gym',
                  'notes': '', 'source_from': 'school@example.org', 'status': 'proposed',
                  'calendar_id': None, 'supplies': []}] if key == 'parent' else []
    page.route('**/api/proposals?*', lambda r: r.fulfill(json=proposals))
    # fetchMind (app.html:3705) reads data.situations.
    page.route('**/api/situations?*', lambda r: r.fulfill(json={'situations': []}))

    weather = ({'temp_now': 71, 'condition': 'partlycloudy', 'emoji': '⛅', 'line': 'clearing by 5'}
               if key == 'parent' else None)
    page.route('**/api/weather/now*', lambda r: r.fulfill(
        status=200, content_type='application/json', body=json.dumps(weather)))

    page.route('**/api/programs', lambda r: r.fulfill(json={'programs': [dict(
        id='practice', member_id=key, title='Strength training', state='active', progress={}, emissions={})]}))
    page.route('**/api/practice-windows?*', lambda r: r.fulfill(json={'windows': [dict(
        program_id='practice', member_id=key, date=DAY, time_start='21:00', time_end='21:30',
        title='Strength training', session_label='Push and core', steps=[])]}))
    page.route('**/api/channels?*', lambda r: r.fulfill(json=[]))

    def record(kind):
        def handler(route):
            if route.request.method != 'POST':
                return route.continue_()
            posts[kind].append({'url': route.request.url, 'body': route.request.post_data_json or {}})
            route.fulfill(json={'ok': True})
        return handler
    page.route('**/api/routines/*/check', record('routine'))
    page.route('**/api/kid-tasks/*/complete', record('task'))
    return posts


# --- helpers ----------------------------------------------------------------

BRIEF_READY = """() => {
    const c = document.getElementById('myday-content');
    return !!c && !!c.querySelector('.pwa-brief-greet') && !!c.querySelector('.pwa-brief-day')
        && !c.innerText.includes('Loading your day');
}"""

# The row the hero must be: the earliest upcoming row Your day drew, ties by
# kind in pwaNextThing's order (Task 2).
NEXT_ROW = """() => {
    const order = ['drive', 'ride', 'event', 'session', 'routine', 'task'];
    const rows = [...document.querySelectorAll('.pwa-brief-day [data-kind][data-state="upcoming"]')];
    rows.sort((a, b) => (new Date(a.dataset.start) - new Date(b.dataset.start))
        || (order.indexOf(a.dataset.kind) - order.indexOf(b.dataset.kind)));
    const r = rows[0];
    if (!r) return null;
    return {kind: r.dataset.kind, label: r.dataset.timeLabel || null, start: r.dataset.start,
            title: r.dataset.title, clock: r.dataset.start ? formatTime(r.dataset.start) : ''};
}"""

PICKED = """() => {
    const next = pwaNextThing(pwaRowsFromDom(document.querySelector('.pwa-brief-day')), new Date());
    return next ? {kind: next.kind, title: next.title} : null;
}"""


def norm(text):
    return ' '.join((text or '').split())


def wait_brief(page, timeout=8000):
    try:
        page.wait_for_function(BRIEF_READY, timeout=timeout)
    except Exception:
        pass
    assert page.locator('#myday-content .pwa-brief-greet').count() == 1, \
        '.pwa-brief-greet missing: My Day did not render the brief'
    assert page.locator('#myday-content .pwa-brief-day').count() == 1, \
        '.pwa-brief-day missing: the brief has no Your day section'
    assert 'Loading your day' not in page.locator('#myday-content').inner_text(), \
        'the brief is still loading'


def settle(page, condition, timeout=6000):
    """Give an async re-render the chance to land; the assertion that follows
    says what was wrong if it never did."""
    try:
        page.wait_for_function('() => ' + condition, timeout=timeout)
    except Exception:
        pass


def rerender(page, before=''):
    page.evaluate("async () => { %s; buildTimeline(); await pwaRenderBrief(); }" % (before or 'void 0'))
    wait_brief(page)


def need_kinds(page):
    return page.evaluate("(window.pwaNeedCards || []).map(c => c.kind)")


def open_sheet(page):
    # _pwaModal (app.html ~3548) builds a `.pwa-sheet-overlay.pwa-prompt-overlay`;
    # the static sheets (#pin-modal, #new-chat-modal, ...) share the first class
    # and sit hidden in the DOM, so the prompt class is the one to wait on.
    page.wait_for_selector('.pwa-prompt-overlay', state='visible')
    return page.locator('.pwa-prompt-overlay').last


def close_sheet(page):
    """The sheet's own close control must work: a sheet that cannot be
    dismissed is a trap, not a hand path."""
    page.locator('.pwa-prompt-overlay').last.locator('.pwa-sheet-close').click()
    page.wait_for_function("document.querySelectorAll('.pwa-prompt-overlay').length === 0")


def day_collapsed(page):
    return page.locator('#myday-content .pwa-brief-day.is-collapsed').count() == 1


def no_overflow(page):
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), \
        page.evaluate('[document.documentElement.scrollWidth, innerWidth]')
    assert page.locator('#myday-content').evaluate('e => e.scrollWidth <= e.clientWidth')


def shot(output, name, page):
    if output:
        page.wait_for_timeout(300)
        Path(output, name).write_bytes(page.screenshot())


# --- scenarios --------------------------------------------------------------

def tabs_and_landing(page, key):
    """Every adult has My Day, labelled so, and no separate drives tab; an
    adult who left the app on the old drives view still lands on My Day."""
    assert page.locator('#tab-myday').is_visible(), key
    assert norm(page.locator('#tab-myday > span').inner_text()) == 'My Day', key
    assert not page.locator('#tab-drives').is_visible(), key
    assert page.evaluate('currentView') == 'myday', (key, page.evaluate('currentView'))


def greeting_and_weather(page, key):
    greet = norm(page.locator('.pwa-brief-greet').inner_text())
    assert greet.startswith('Good afternoon'), greet
    assert greet.endswith('Alex'), greet
    assert page.locator('.pwa-brief-date').count() == 1
    weather = page.locator('.pwa-brief-weather')
    if key == 'parent':
        assert weather.count() == 1, 'the weather slot is missing'
        assert '71°' in weather.inner_text(), weather.inner_text()
    else:
        assert weather.count() == 0, 'a null weather read must omit the slot'


def sentence_from_facts(page, key):
    sentence = norm(page.locator('.pwa-brief-sentence').inner_text())
    assert sentence, 'the sentence is empty'
    parts = [p for p in re.split(r'(?<=[.!?])\s+', sentence) if p]
    assert len(parts) <= 2, sentence
    if key != 'parent':
        return
    want = page.evaluate("pwaBriefSentence(pwaBriefFacts({rows: pwaRowsFromDom(document.querySelector('.pwa-brief-day')), role: 'parent', isDriver: true, needs: window.pwaNeedCards || []}))")
    assert sentence == norm(want), (sentence, want)
    assert 'drive' in sentence.lower(), sentence


def hero_is_the_next_row(page, key):
    hero = page.locator('#myday-content .pwa-hero')
    if key == 'keeping':
        # No drive hero for a member who does not drive.
        if hero.count():
            assert 'next departure' not in hero.locator('.pwa-hero-kicker').inner_text().lower()
            assert hero.get_by_role('button', name='Start drive').count() == 0
            # Ruling (slice 1 fix round, item 19): the keeping-up hero is the
            # next thing that happens to THEM — a ride, a session, a routine
            # step or a task — never the family's event from Plan's branch.
            row = page.evaluate(NEXT_ROW.replace("['drive', 'ride', 'event', 'session', 'routine', 'task']",
                                                 "['ride', 'session', 'routine', 'task']")
                                .replace("[data-kind][data-state=\"upcoming\"]",
                                         "[data-kind][data-state=\"upcoming\"]:is([data-kind=ride],[data-kind=session],[data-kind=routine],[data-kind=task])"))
            assert row and row['kind'] in ('ride', 'session', 'routine', 'task'), row
            big = norm(hero.locator('h2').inner_text())
            assert big.upper() == norm(row['clock']).upper(), (big, row)
        return
    assert hero.count() == 1, 'the driver has no hero'
    row = page.evaluate(NEXT_ROW)
    assert row, 'Your day drew no upcoming row'
    big = norm(hero.locator('h2').inner_text())
    if row['kind'] == 'drive':
        assert big == norm(row['label']), (big, row)
    else:
        assert big.upper() == norm(row['clock']).upper(), (big, row)
    if key != 'parent':
        return
    assert row['kind'] == 'drive', row
    hero.locator('.pwa-btn-primary').click()
    page.wait_for_selector('#action-sheet', state='visible')
    page.evaluate('closeActionSheet()')
    page.wait_for_selector('#action-sheet', state='hidden')
    hero.locator('.pwa-btn-secondary').click()
    page.wait_for_selector('#event-modal', state='visible')
    page.evaluate('closeEventModal()')
    page.wait_for_selector('#event-modal', state='hidden')


def needs_you_pile(page, key):
    content = page.locator('#myday-content')
    cards = content.locator('.pwa-need')
    kinds = need_kinds(page)
    if key == 'adult':
        assert cards.count() == 0, kinds
        assert 'Needs you' not in content.inner_text(), 'an empty pile still drew its heading'
        return
    if key == 'keeping':
        assert 'status' in kinds, kinds
        assert cards.count() == len(kinds), (cards.count(), kinds)
        cards.nth(kinds.index('status')).click()
        sheet = open_sheet(page)
        assert sheet.locator('[onclick*="armClearStatus"], [onclick*="toggleStatusSetRow"]').count() > 0, \
            'the status sheet has neither the chooser nor the clear control'
        close_sheet(page)
        return
    # parent: request, review, task, proposal. Deadlines first (the task due
    # tomorrow, then the proposal five days out), then rank (request 2,
    # review 3).
    assert cards.count() == 4, (cards.count(), kinds)
    assert sorted(kinds) == ['proposal', 'request', 'review', 'task'], kinds
    assert kinds == ['task', 'proposal', 'request', 'review'], kinds
    assert 'History essay' in cards.first.inner_text(), cards.first.inner_text()
    heading = content.locator('h3', has_text='Needs you')
    assert heading.count() == 1 and '4' in heading.inner_text(), heading.all_inner_texts()
    cards.nth(kinds.index('review')).click()
    page.wait_for_function("""() => { const c = document.getElementById('chores-container');
        return c.dataset.section === 'reviews' && getComputedStyle(c).display !== 'none'; }""")
    assert page.evaluate('currentView') == 'chores'
    # Slice 3: the review card's route is pwaOpenNeed -> pwaOpenHouseScreen('chores', 'check'):
    # the Household Chores screen, pushed, at its "To check" segment.
    settle(page, "PwaNav.depth() === 1 && !!document.querySelector('#pwa-stack .pwa-screen h1')")
    assert page.evaluate('PwaNav.depth()') == 1, page.evaluate('PwaNav.depth()')
    assert norm(page.locator('#pwa-stack .pwa-screen h1').last.inner_text()) == 'Chores'
    segment = page.evaluate("""() => { const s = [...document.querySelectorAll('#pwa-stack .pwa-screen')].pop();
        const e = s.matches('[data-house-segment]') ? s : s.querySelector('[data-house-segment]');
        return e ? e.dataset.houseSegment : null; }""")
    assert segment == 'check', segment
    assert page.locator('#pwa-stack .pwa-screen').last.get_by_role('button', name='✓ Verify').is_visible()
    page.locator('#tab-myday').click()
    wait_brief(page)
    kinds = need_kinds(page)
    content.locator('.pwa-need').nth(kinds.index('request')).click()
    sheet = open_sheet(page)
    assert sheet.get_by_role('button', name='Yes', exact=True).is_visible(), sheet.inner_text()
    close_sheet(page)


def your_day_collapsed_then_open(page, output):
    page.evaluate("localStorage.removeItem('%s')" % DAY_OPEN_KEY)
    rerender(page)
    assert day_collapsed(page), 'Your day is open by default'
    expand = page.locator('#myday-content .pwa-brief-expand')
    assert norm(expand.inner_text()).startswith('Show the whole day'), expand.inner_text()
    kinds = set(page.evaluate("[...document.querySelectorAll('.pwa-brief-day [data-kind]')].map(e => e.dataset.kind)"))
    # One data assembly: the driver's legs and events, the ride someone else
    # drives, the session, the routine and the due-soon task, in one list.
    assert {'drive', 'event', 'ride', 'session', 'routine', 'task'} <= kinds, kinds
    expand.click()
    assert not day_collapsed(page)
    assert norm(expand.inner_text()).startswith('Show less'), expand.inner_text()
    assert page.evaluate("localStorage.getItem('%s')" % DAY_OPEN_KEY) == '1'
    rerender(page)
    assert not day_collapsed(page), 'the open day did not survive a re-render'
    shot(output, 'myday-parent-expanded.png', page)
    # Fold it again so the next day proves it opens "regardless".
    page.locator('#myday-content .pwa-brief-expand').click()
    assert day_collapsed(page)
    assert page.evaluate("localStorage.getItem('%s')" % DAY_OPEN_KEY) == '0'
    assert page.locator('#day-nav').is_visible(), 'My Day lost its day arrows'
    page.locator('#btn-next-day').click()
    page.wait_for_function('mydayOffset === 1')
    settle(page, "!document.querySelector('#myday-content .pwa-brief-day.is-collapsed') && !document.querySelector('#myday-content .pwa-hero')")
    wait_brief(page)
    assert not day_collapsed(page), 'a day other than today must open expanded'
    assert page.locator('#myday-content .pwa-hero').count() == 0, 'tomorrow has a hero'
    page.locator('#btn-prev-day').click()
    page.wait_for_function('mydayOffset === 0')
    settle(page, "!!document.querySelector('#myday-content .pwa-hero')")
    wait_brief(page)
    assert day_collapsed(page), 'today forgot the folded state'
    assert page.locator('#myday-content .pwa-hero').count() == 1, 'today lost its hero'


def pencil_rule(page, output):
    pencil = page.locator('#myday-content .pwa-brief-pencil')
    assert pencil.count() == 1, 'the parent has options but no pencil'
    pencil.click()
    sheet = open_sheet(page)
    text = sheet.inner_text()
    assert 'Family status' in text and 'Ask for something' in text, text
    shot(output, 'myday-parent-pencil.png', page)
    close_sheet(page)
    page.evaluate("localStorage.setItem('%s','0')" % DAY_OPEN_KEY)
    rerender(page)
    assert day_collapsed(page)
    page.evaluate("localStorage.setItem('%s','1')" % DAY_OPEN_KEY)
    rerender(page)
    assert not day_collapsed(page), 'show-the-whole-day did not open the day'


def nothing_removed(page, posts, key):
    """Every tap the old My Day and the drives timeline had still works on
    the rows the brief adopted."""
    if day_collapsed(page):
        page.locator('#myday-content .pwa-brief-expand').click()
    day = page.locator('#myday-content .pwa-brief-day')
    day.locator('.pwa-leg-row[data-state="upcoming"] .pwa-row-main').first.click()
    page.wait_for_selector('#action-sheet', state='visible')
    page.evaluate('closeActionSheet()')
    page.wait_for_selector('#action-sheet', state='hidden')
    ride = day.locator('[data-kind="ride"]')
    assert ride.count() == 1, 'the ride is not on Your day'
    assert ride.get_by_role('button', name='Message').count() >= 1, ride.inner_text()
    # The due-soon check first: completeKidTask strikes the row in place,
    # while toggleRoutine re-renders the day afterwards.
    task_box = day.locator('[data-kind="task"] input[type="checkbox"], input[type="checkbox"][data-kind="task"]').first
    with page.expect_request(lambda r: r.method == 'POST' and '/api/kid-tasks/' in r.url and r.url.endswith('/complete')):
        task_box.click()
    assert posts['task'] and '/api/kid-tasks/essay/complete' in posts['task'][-1]['url'], posts
    assert posts['task'][-1]['body'].get('done') is True, posts
    routine_box = day.locator('[data-kind="routine"] input[type="checkbox"], input[type="checkbox"][data-kind="routine"]').first
    with page.expect_request(lambda r: r.method == 'POST' and '/api/routines/' in r.url and r.url.endswith('/check')):
        routine_box.click()
    assert posts['routine'] and '/api/routines/walk/check' in posts['routine'][-1]['url'], posts
    assert posts['routine'][-1]['body'].get('member_id') == key, posts
    page.wait_for_timeout(300)
    wait_brief(page)


def widths_and_dark(page, key, output):
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        page.wait_for_timeout(150)
        no_overflow(page)
        if width == 360 and key == 'parent':
            shot(output, 'myday-parent-360.png', page)
    page.set_viewport_size({'width': 390, 'height': 844})
    if key == 'parent':
        page.evaluate("applyTheme('dark')")
        shot(output, 'myday-parent-dark.png', page)
        no_overflow(page)
        page.evaluate("applyTheme('light')")
    # The page runs under prefers-reduced-motion: nothing in the brief moves.
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    running = page.evaluate("""() => document.getElementById('myday-content')
        .getAnimations({subtree: true}).filter(a => a.playState === 'running').length""")
    assert running == 0, running


def evening_has_no_hero(page, key):
    """Every drive has passed. No drive hero may remain; whatever the hero
    shows is exactly pwaNextThing's pick over Your day, and the sentence never
    states a count of nothing."""
    page.clock.set_fixed_time(NOW.replace(hour=18, minute=30))
    page.evaluate('buildTimeline(); pwaRenderBrief()')
    wait_brief(page)
    hero = page.locator('#myday-content .pwa-hero')
    assert hero.get_by_role('button', name='Start drive').count() == 0, 'a passed drive is still the hero'
    picked = page.evaluate(PICKED)
    if picked is None:
        assert hero.count() == 0, 'nothing is next but a hero is drawn'
    else:
        assert picked['kind'] != 'drive', picked
        assert hero.count() == 1, picked
        kicker = hero.locator('.pwa-hero-kicker').inner_text().lower()
        assert 'departure' not in kicker and 'current drive' not in kicker, kicker
    sentence = norm(page.locator('.pwa-brief-sentence').inner_text())
    assert not re.search(r'(^|\D)0(\D|$)', sentence), sentence


# --- the run ----------------------------------------------------------------

def run():
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
        Path(output).mkdir(parents=True, exist_ok=True)
    try:
        for key, role, driver in PROFILES:
            if os.environ.get('PWA_REVIEW_PROFILE') and key != os.environ['PWA_REVIEW_PROFILE']:
                continue
            with served.browser(reduced_motion='reduce', has_touch=True) as page:
                failed_assets = []
                page.on('requestfailed', lambda request: failed_assets.append(
                    (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
                page.on('response', lambda response: failed_assets.append(
                    (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
                    and response.status >= 400 else None)
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
                          'chauffeur_member_token_for': key,
                          'chauffeur_view': 'drives' if key == 'adult' else 'myday',
                          'chauffeur_theme': 'light'}
                if driver:
                    values['chauffeur_driver_id'] = driver
                page.add_init_script('Object.entries(' + json.dumps(values) +
                                     ').forEach(([k,v])=>localStorage.setItem(k,v));')
                posts = install_mocks(page, key, driver)
                page.goto(served.url('app'), wait_until='domcontentloaded')
                page.wait_for_timeout(500)
                if page.locator('#pin-modal-skip').is_visible():
                    page.locator('#pin-modal-skip').click()
                page.wait_for_selector('#screen-schedule:not(.hidden)')
                page.wait_for_function('membersData.length > 0')
                assert page.evaluate('selectedMemberId') == key
                assert page.evaluate('currentMemberRole()') == role
                wait_brief(page)

                tabs_and_landing(page, key)
                greeting_and_weather(page, key)
                shot(output, f'myday-{key}-light.png', page)
                sentence_from_facts(page, key)
                hero_is_the_next_row(page, key)
                needs_you_pile(page, key)
                if key == 'parent':
                    your_day_collapsed_then_open(page, output)
                    pencil_rule(page, output)
                    nothing_removed(page, posts, key)
                widths_and_dark(page, key, output)
                evening_has_no_hero(page, key)
                assert not served.errors() and not failed_assets, (key, served.errors(), failed_assets)
                print('ok', key, flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    run()
