"""Argyle from anywhere, in the served PWA (slice 2, Task 3).

The orb's tap opens a Siri-style overlay OVER the current screen (never
through setView, so a pushed screen and the scroll survive); hold talks
through ChauffeurPhoneVoice in host mode; text goes through the Argyle DM's
own POST api/channels/{id}/messages and the reply is drawn when the thread
learns of it (the SSE channel event -> PwaArgyle.onStream -> one messages
read), with the reply's card drawn by renderCard so its buttons are the
thread's buttons. Dismiss by Escape, backdrop, hardware Back, swipe down.
The Ask Argyle popup, its FAB and its More entry are gone.
Hold-to-talk review fixes: a bare click (screen-reader activation) opens type
mode; talk mode shows the wave only once the voice turn says 'listening'
(never for 'starting'); a backdrop click right after opening is ignored.

Written before the overlay exists (Task 4 makes it green), so its first
failure is the missing `#pwa-argyle-overlay`.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_argyle_live.py
Optional PWA_REVIEW_OUTPUT writes the screenshots; PWA_REVIEW_PROFILE runs one.
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
DATA = tempfile.mkdtemp(prefix='chauffeur_argyle_overlay_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
TS = int(NOW.timestamp())
PROFILES = [('parent', 'parent', 'd1'), ('helper_granted', 'helper', 'd3')]
SENT = 'Can Grandma take Kate Thursday?'
REPLY = 'Grandma Ruth is free Thursday at 5:10.'
# services/asks.py _card(): the shape renderAskCard (app.html ~5705) reads —
# ask_id, what, state, outcome, actions[{label, style, ask_id, act}].
ASK_CARD = {'kind': 'ask', 'ask_id': 'a1', 'what': 'Ask Grandma Ruth to take Kate Thursday at 5:10?',
            'state': 'open', 'outcome': None,
            'actions': [{'label': 'Yes', 'style': 'primary', 'ask_id': 'a1', 'act': 'yes'},
                        {'label': 'No', 'style': 'default', 'ask_id': 'a1', 'act': 'no'}]}
ORB_BACK = ("document.getElementById('tab-argyle').checkVisibility("
            "{visibilityProperty: true, opacityProperty: true})")


def seed():
    for key, role, driver in PROFILES:
        member = {'id': key, 'name': 'Alex Morgan', 'role': role,
                  'driver_id': driver, 'color_code': '#287a72'}
        if key == 'helper_granted':
            # A helper whose household let them talk to Argyle
            # (services/scope.py: the 'helper' preset has chat.agent none;
            # _table_value applies scope.overrides[facet]).
            member['scope'] = {'preset': 'helper', 'overrides': {'chat.agent': 'all'}}
        storage.add_member(member)
        if driver:
            storage.add_driver({'id': driver, 'name': 'Alex Morgan',
                                'home_location': 'Home', 'color_code': '#287a72'})


# --- fixtures ---------------------------------------------------------------

def schedule_for(driver):
    """The adult-shell schedule (test_pwa_adult_shell_live.py run())."""
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


def install_mocks(page, key, driver):
    """Every read the shell and the overlay make, per profile. Returns the
    recorded calls and the mutable Argyle thread the test flips."""
    calls = {'dm': [], 'messages_post': [], 'messages_get': [], 'asks': [], 'voice': [],
             'thread': []}
    schedule = schedule_for(driver)
    page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
    page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/messages/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))
    page.route('**/api/members/*/day?*', lambda r: r.fulfill(json={
        'member_id': key, 'name': 'Alex Morgan', 'date': DAY, 'rides': [], 'due_soon': [],
        'still_open': [], 'status_days': [], 'launch': None}))

    def routine_day(route):
        date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
        route.fulfill(json={'date': date, 'items': [], 'streak': {}})
    page.route('**/api/routines/day?*', routine_day)
    page.route('**/api/requests?*', lambda r: r.fulfill(json={'waiting_on_me': [], 'mine': []}))
    chores = [dict(id='dishwasher', title='Unload the dishwasher', description='Kitchen', points=10,
                   state='claimed', claimed_by=key, claimed_by_name='Alex'),
              dict(id='plants', title='Water the plants', points=5, state='open', eligible_member_ids=[])]
    page.route('**/api/chores', lambda r: r.fulfill(json=chores))
    page.route('**/api/points', lambda r: r.fulfill(json=[]))
    page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
    page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))
    page.route('**/api/proposals?*', lambda r: r.fulfill(json=[]))
    page.route('**/api/situations?*', lambda r: r.fulfill(json={'situations': []}))
    page.route('**/api/weather/now*', lambda r: r.fulfill(
        status=200, content_type='application/json', body='null'))
    # The drives view preloads the program's lesson (buildPracticeParts); the brief does not. Mock it so a
    # helper landing on drives never hits the real server for a fixture program.
    page.route('**/api/programs/*/lesson*', lambda r: r.fulfill(json={}))
    page.route('**/api/programs', lambda r: r.fulfill(json={'programs': [dict(
        id='practice', member_id=key, title='Strength training', state='active', progress={}, emissions={})]}))
    page.route('**/api/practice-windows?*', lambda r: r.fulfill(json={'windows': [dict(
        program_id='practice', member_id=key, date=DAY, time_start='21:00', time_end='21:30',
        title='Strength training', session_label='Push and core', steps=[])]}))
    page.route('**/api/channels?*', lambda r: r.fulfill(json=[
        {'id': 'family', 'kind': 'family', 'title': 'Family', 'member_ids': [key],
         'last_message': {'sender_member_id': key, 'body': 'See you at the front doors.', 'ts': TS}},
        {'id': 'school', 'kind': 'group', 'title': 'School pickup', 'member_ids': [key]}]))

    # PwaArgyle.ensureChannel and pwaOpenArgyle (static/pwa_shell.js) POST
    # {member_id, other_member_id: 'argyle'}; openChannel / renderThread read
    # id, kind, member_ids. The granted helper models the server's refusal.
    def open_dm(route):
        if route.request.method != 'POST':
            return route.continue_()
        calls['dm'].append(route.request.post_data_json or {})
        if key == 'helper_granted':
            return route.fulfill(status=403, json={'detail': 'Requires chat.agent'})
        route.fulfill(json={'id': 'dm_argyle', 'kind': 'dm', 'member_ids': [key, 'argyle']})
    page.route('**/api/channels/dm', open_dm)

    # GET: the overlay's pull (?limit=20) and refreshThread (?limit=100, app.html
    # ~4923); both read a list of {id, sender_member_id, body, ts, card?}.
    # POST: the overlay's send, body {sender_member_id, body}; it keeps the
    # returned id as the message the reply must come after.
    def messages(route):
        req = route.request
        if req.method == 'POST':
            body = req.post_data_json or {}
            calls['messages_post'].append(body)
            return route.fulfill(json={'id': 'm3', 'sender_member_id': key,
                                       'body': body.get('body', ''), 'ts': TS})
        calls['messages_get'].append(req.url)
        route.fulfill(json=list(calls['thread']))
    page.route('**/api/channels/dm_argyle/messages*', messages)
    # markRead (app.html ~6471) after refreshThread draws a non-empty thread.
    page.route('**/api/channels/dm_argyle/read*', lambda r: r.fulfill(json={'ok': True}))

    # answerAsk (app.html ~5908): POST {answer, member_id}; reads detail/message.
    def answer(route):
        calls['asks'].append({'url': route.request.url, 'body': route.request.post_data_json or {}})
        route.fulfill(json={'ok': True})
    page.route('**/api/asks/*/answer', answer)

    # app_voice.js json('start') / cancelServer: the spy below stands in for
    # the capture, but a real start or stop must still land on a route.
    def voice_start(route):
        calls['voice'].append(route.request.post_data_json or {})
        route.fulfill(json={'request_id': 'r1', 'channel': {'id': 'dm_argyle', 'kind': 'dm',
                                                            'member_ids': [key, 'argyle']}})
    page.route('**/api/app-voice/start', voice_start)
    page.route('**/api/app-voice/*/cancel', lambda r: r.fulfill(json={'status': 'stopped'}))
    return calls


def reply_thread(key):
    return [{'id': 'm3', 'sender_member_id': key, 'body': SENT, 'ts': TS},
            {'id': 'm4', 'sender_member_id': 'argyle', 'body': REPLY, 'ts': TS + 4, 'card': ASK_CARD}]


# --- helpers ----------------------------------------------------------------

BRIEF_READY = """() => {
    const c = document.getElementById('myday-content');
    return !!c && !!c.querySelector('.pwa-brief-greet') && !!c.querySelector('.pwa-brief-day')
        && !c.innerText.includes('Loading your day');
}"""


def norm(text):
    return ' '.join((text or '').split())


def settle(page, condition, timeout=4000):
    """Let an async step land; the assertion that follows says what was wrong."""
    try:
        page.wait_for_function('() => ' + condition, timeout=timeout)
    except Exception:
        pass


def shot(output, name, page):
    if output:
        page.wait_for_timeout(300)
        Path(output, name).write_bytes(page.screenshot())


def wait_until(page, predicate, timeout_ms=3000):
    """Route handlers run while Playwright pumps events: poll a Python-side
    record with short page waits."""
    for _ in range(max(1, timeout_ms // 50)):
        if predicate():
            return True
        page.wait_for_timeout(50)
    return predicate()


def overlay(page):
    return page.locator('#pwa-argyle-overlay')


def assert_open(page, what='the orb tap'):
    try:
        overlay(page).wait_for(state='visible', timeout=4000)
    except Exception:
        pass
    assert overlay(page).count() == 1 and overlay(page).is_visible(), \
        '#pwa-argyle-overlay missing or hidden after %s' % what
    assert page.evaluate("document.documentElement.dataset.pwaArgyle") == '1'


def assert_closed(page, how):
    try:
        overlay(page).wait_for(state='hidden', timeout=3000)
    except Exception:
        pass
    assert not overlay(page).is_visible(), 'the overlay stayed open after ' + how
    assert page.evaluate("PwaArgyle.isOpen()") is False, how
    assert page.evaluate("document.documentElement.hasAttribute('data-pwa-argyle')") is False, how
    settle(page, ORB_BACK, 2000)
    assert page.evaluate(ORB_BACK), 'the orb did not come back after ' + how


def orb_hidden(page):
    settle(page, "document.getElementById('tab-argyle').classList.contains('argyle-orb-hidden')", 2000)
    assert page.locator('#tab-argyle').evaluate("e => e.classList.contains('argyle-orb-hidden')"), \
        'the orb shows through the overlay'


def open_by_tap(page):
    page.locator('#tab-argyle').click()
    assert_open(page)


def input_focused(page):
    settle(page, "!!document.activeElement && document.activeElement.matches('.pwa-argyle-input')", 3000)
    assert page.evaluate("!!document.activeElement && document.activeElement.matches('.pwa-argyle-input')"), \
        page.evaluate("document.activeElement && document.activeElement.outerHTML.slice(0, 120)")


def status_text(page):
    return norm(page.locator('#pwa-argyle-overlay .pwa-argyle-status').inner_text())


def boot(served, page, key, role, driver):
    failed_assets = []
    page.on('requestfailed', lambda request: failed_assets.append(
        (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
    page.on('response', lambda response: failed_assets.append(
        (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
        and response.status >= 400 else None)
    # Every 4xx/5xx with its URL, so an unmocked route names itself in the
    # failure instead of hiding behind Chromium's "Failed to load resource".
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
              'chauffeur_member_token_for': key, 'chauffeur_view': 'myday',
              'chauffeur_theme': 'light'}
    if driver:
        values['chauffeur_driver_id'] = driver
    page.add_init_script('Object.entries(' + json.dumps(values) +
                         ').forEach(([k,v])=>localStorage.setItem(k,v));')
    calls = install_mocks(page, key, driver)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    page.wait_for_timeout(500)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function('membersData.length > 0')
    page.wait_for_timeout(300)
    assert page.evaluate('selectedMemberId') == key
    assert page.evaluate('currentMemberRole()') == role
    if role == 'parent':
        try:
            page.wait_for_function(BRIEF_READY, timeout=8000)
        except Exception:
            pass
        assert page.locator('#myday-content .pwa-brief-greet').count() == 1, 'My Day did not draw the brief'
    return calls, failed_assets


BAD_RESPONSES = []


def page_errors(served, key):
    errors = list(served.errors())
    if errors:
        errors = errors + [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key and st != 403]
    if key == 'helper_granted':
        # The modelled refusal: Chromium logs the 403 of POST api/channels/dm.
        errors = [e for e in errors if 'status of 403' not in e]
    return errors


# --- scenarios --------------------------------------------------------------

def tap_opens_over_the_screen(page, key, calls, output):
    """A tap opens the overlay over whatever is on the glass: the pushed
    screen stays pushed, the view and its scroll stay put."""
    if page.locator('#myday-content .pwa-brief-day.is-collapsed').count():
        page.locator('#myday-content .pwa-brief-expand').click()
    before = page.evaluate("""() => { const c = document.getElementById('myday-container');
        c.scrollTop = 300; return c.scrollTop; }""")
    assert before > 0, 'My Day is too short to scroll; the scroll check would prove nothing'
    page.evaluate("PwaNav.push({ id: 'probe', title: 'Probe screen', render(body) { body.textContent = 'probe body'; } })")
    assert page.evaluate('PwaNav.depth()') == 1
    page.locator('#tab-argyle').click()
    assert_open(page)
    assert page.evaluate('PwaNav.depth()') == 1, 'the overlay went through PwaNav'
    assert page.locator('#pwa-stack .pwa-screen h1').inner_text() == 'Probe screen'
    assert page.evaluate('currentView') == 'myday', page.evaluate('currentView')
    assert page.evaluate("document.getElementById('myday-container').scrollTop") == before
    assert page.evaluate('history.state && history.state.pwaOverlay') == 'argyle', page.evaluate('history.state')
    orb_hidden(page)
    input_focused(page)
    assert page.locator('#pwa-argyle-overlay .pwa-argyle-input').get_attribute('placeholder') == 'Or type…'
    hint = norm(page.locator('#pwa-argyle-overlay .pwa-argyle-hint').inner_text())
    assert hint.startswith('Swipe down to dismiss') and 'full conversation in Messages' in hint, hint
    assert page.locator('#pwa-argyle-overlay .pwa-argyle-reply').is_visible() is False
    assert wait_until(page, lambda: calls['dm']), 'the overlay never ensured the Argyle DM'
    assert calls['dm'][-1] == {'member_id': key, 'other_member_id': 'argyle'}, calls['dm']
    shot(output, 'argyle-overlay-type.png', page)


def type_and_reply(page, key, calls, output):
    """Text rides the thread's own POST; the reply lands on the stream event
    as one read; its ask card is the thread's card with the thread's buttons."""
    if not page.evaluate('PwaArgyle.isOpen()'):
        open_by_tap(page)
    page.locator('#pwa-argyle-overlay .pwa-argyle-input').fill(SENT)
    page.locator('#pwa-argyle-overlay .pwa-argyle-send').click()
    assert wait_until(page, lambda: calls['messages_post']), 'send never POSTed to the Argyle DM'
    sent = calls['messages_post'][-1]
    assert sent.get('sender_member_id') == key and sent.get('body') == SENT, sent
    you = page.locator('#pwa-argyle-overlay .pwa-argyle-you')
    settle(page, "document.querySelector('#pwa-argyle-overlay .pwa-argyle-you').innerText.includes(%s)" % json.dumps(SENT))
    assert SENT in you.inner_text(), you.inner_text()
    settle(page, "document.querySelector('#pwa-argyle-overlay .pwa-argyle-status').innerText.includes('Thinking')")
    assert 'Thinking' in status_text(page), status_text(page)
    assert not page.locator('#pwa-argyle-overlay .pwa-argyle-reply').is_visible(), 'a reply showed before Argyle answered'
    # The reply arrives the way the thread learns of it.
    calls['thread'][:] = reply_thread(key)
    gets = len(calls['messages_get'])
    page.evaluate("PwaArgyle.onStream('dm_argyle')")
    assert wait_until(page, lambda: len(calls['messages_get']) > gets), 'onStream did not read the thread'
    body = page.locator('#pwa-argyle-overlay .pwa-argyle-reply-body')
    settle(page, "document.querySelector('#pwa-argyle-overlay .pwa-argyle-reply-body').innerText.includes(%s)" % json.dumps(REPLY))
    assert page.locator('#pwa-argyle-overlay .pwa-argyle-reply').is_visible(), 'the reply bubble is hidden'
    assert REPLY in body.inner_text(), body.inner_text()
    card = page.locator('#pwa-argyle-overlay .pwa-argyle-reply-card')
    assert ASK_CARD['what'] in norm(card.inner_text()), card.inner_text()
    buttons = card.locator('button')
    assert buttons.count() == 2, buttons.all_inner_texts()
    assert [norm(t) for t in buttons.all_inner_texts()] == ['Yes', 'No'], buttons.all_inner_texts()
    assert 'Thinking' not in status_text(page), status_text(page)
    shot(output, 'argyle-overlay-reply.png', page)
    # A second stream event for the same reply must not redraw it (the
    # card's node survives; a redraw would throw away a half-tapped card).
    page.evaluate("document.querySelector('#pwa-argyle-overlay .pwa-argyle-reply-card button').__probe = 1")
    gets = len(calls['messages_get'])
    page.evaluate("PwaArgyle.onStream('dm_argyle')")
    wait_until(page, lambda: len(calls['messages_get']) > gets, 1000)
    page.wait_for_timeout(200)
    assert page.evaluate("document.querySelector('#pwa-argyle-overlay .pwa-argyle-reply-card button').__probe === 1"), \
        'a second stream event redrew the same reply'
    card.get_by_role('button', name='Yes', exact=True).click()
    assert wait_until(page, lambda: calls['asks']), 'the card button did not answer the ask'
    assert calls['asks'][-1]['url'].endswith('/api/asks/a1/answer'), calls['asks']
    assert calls['asks'][-1]['body'] == {'answer': 'yes', 'member_id': key}, calls['asks']
    assert 'Thinking' not in status_text(page), status_text(page)
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape after a reply')


def dismissals(page):
    """Escape, the backdrop, hardware Back and a downward swipe all close it;
    Back closes only the overlay, never the pushed screen beneath."""
    open_by_tap(page)
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape')
    assert page.evaluate('PwaNav.depth()') == 1

    open_by_tap(page)
    # A person's backdrop tap comes well after the opening tap; one inside the
    # ghost-click window is ignored on purpose (ghost_click_right_after_open_is_ignored).
    page.wait_for_timeout(500)
    page.locator('#pwa-argyle-overlay .pwa-argyle-dim').click(position={'x': 195, 'y': 120})
    assert_closed(page, 'a backdrop tap')
    assert page.evaluate('PwaNav.depth()') == 1

    open_by_tap(page)
    page.go_back()
    assert_closed(page, 'hardware Back')
    assert page.evaluate('PwaNav.depth()') == 1, 'Back took the pushed screen with the overlay'
    assert page.locator('#pwa-stack').is_visible(), 'the pushed screen did not survive Back'
    assert page.locator('#pwa-stack .pwa-screen h1').inner_text() == 'Probe screen'

    open_by_tap(page)
    ask = page.locator('#pwa-argyle-overlay .pwa-argyle-ask')
    ask.dispatch_event('touchstart', {'touches': [{'identifier': 0, 'clientX': 200, 'clientY': 500}]})
    ask.dispatch_event('touchend', {'touches': [],
                                    'changedTouches': [{'identifier': 0, 'clientX': 200, 'clientY': 580}]})
    assert_closed(page, 'a swipe down')
    assert page.evaluate('PwaNav.depth()') == 1
    page.evaluate('PwaNav.clear()')
    page.wait_for_function('PwaNav.depth() === 0')
    settle(page, "document.getElementById('pwa-stack').hidden")
    assert not page.locator('#pwa-stack').is_visible()


def closed_overlay_ignores_events(page, key, calls):
    """A stream event for the Argyle DM while the overlay is closed reads
    nothing, and reopening shows nothing stale."""
    assert page.evaluate('PwaArgyle.isOpen()') is False
    calls['thread'][:] = reply_thread(key) + [
        {'id': 'm5', 'sender_member_id': key, 'body': 'And Friday?', 'ts': TS + 60},
        {'id': 'm6', 'sender_member_id': 'argyle', 'body': 'Friday is open too.', 'ts': TS + 64}]
    gets = len(calls['messages_get'])
    page.evaluate("PwaArgyle.onStream('dm_argyle')")
    page.wait_for_timeout(400)
    assert len(calls['messages_get']) == gets, calls['messages_get'][gets:]
    open_by_tap(page)
    page.wait_for_timeout(300)
    assert not page.locator('#pwa-argyle-overlay .pwa-argyle-reply').is_visible(), 'a stale reply came back'
    assert norm(page.locator('#pwa-argyle-overlay .pwa-argyle-you').inner_text()) == '', 'your old words came back'
    assert 'Thinking' not in status_text(page), status_text(page)
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape on the reopened overlay')


def to_messages(page, key, calls):
    """The hint's "full conversation in Messages" is the Argyle thread."""
    view = page.evaluate('currentView')
    open_by_tap(page)
    posts = len(calls['dm'])
    page.locator('#pwa-argyle-overlay .pwa-argyle-to-messages').click()
    page.wait_for_function("activeChannelId === 'dm_argyle'")
    assert threads_argyle(page)
    assert len(calls['dm']) >= posts
    assert_closed_only(page)
    # Slice 4: the Argyle thread is a screen pushed over the Messages list
    # (it adopts #thread-view); Back returns to the list.
    settle(page, "PwaNav.depth() === 1 && !!document.querySelector('#pwa-stack .pwa-screen h1')")
    assert page.evaluate('PwaNav.depth()') == 1, 'the Argyle thread is not a pushed screen'
    assert norm(page.locator('#pwa-stack .pwa-screen h1').last.inner_text()) == 'Argyle'
    assert page.evaluate("!!document.getElementById('thread-view').closest('#pwa-stack')"), \
        '#thread-view was not adopted into the pushed screen'
    assert page.evaluate('currentView') == 'messages', page.evaluate('currentView')
    try: page.locator('#tab-argyle').wait_for(state='hidden', timeout=2000)
    except Exception: pass
    assert not page.locator('#tab-argyle').is_visible(), 'the orb covers the composer'
    page.locator('#pwa-stack .pwa-screen .pwa-back').last.click()
    page.wait_for_function('PwaNav.depth() === 0')
    assert page.evaluate('currentView') == 'messages', page.evaluate('currentView')
    assert page.locator('#channel-list').is_visible(), 'Back did not return to the Messages list'
    assert not page.locator('#thread-view').is_visible(), 'the thread stayed up after Back'
    assert page.evaluate('activeChannelId') is None, page.evaluate('activeChannelId')
    page.wait_for_function(ORB_BACK)
    page.evaluate('v => setView(v)', view)
    page.wait_for_function('v => currentView === v', arg=view)


def threads_argyle(page):
    return page.evaluate("!!threadChannel && (threadChannel.member_ids || []).includes('argyle')")


def assert_closed_only(page):
    try:
        overlay(page).wait_for(state='hidden', timeout=3000)
    except Exception:
        pass
    assert not overlay(page).is_visible(), 'the overlay stayed over the Argyle thread'
    assert page.evaluate('PwaArgyle.isOpen()') is False


SPY = """() => {
    window.__argyleStarts = [];
    window.__argyleDone = 0;
    const v = window.ChauffeurPhoneVoice;
    v.start = function (opts) {
        window.__argyleStarts.push(opts || {});
        if (opts && opts.host && typeof opts.host.status === 'function')
            opts.host.status('Listening — press Done to send', 'listening');
        return Promise.resolve();
    };
    v.done = function () { window.__argyleDone += 1; return Promise.resolve(); };
}"""

POINTER = {'pointerId': 1, 'pointerType': 'touch', 'isPrimary': True}


def hold_talks(page, output):
    """Hold the orb past 350 ms: the overlay opens in talk mode and starts ONE
    host-mode voice turn on the Argyle DM. A quick tap types, never talks."""
    page.evaluate(SPY)
    page.mouse.move(5, 5)
    orb = page.locator('#tab-argyle')
    orb.dispatch_event('pointerdown', POINTER)
    page.wait_for_timeout(450)
    orb.dispatch_event('pointerup', POINTER)
    assert_open(page, 'a 450 ms hold')
    settle(page, 'window.__argyleStarts.length > 0', 3000)
    starts = page.evaluate('window.__argyleStarts.length')
    assert starts == 1, 'hold started %d voice turns' % starts
    assert page.evaluate("!!window.__argyleStarts[0].host"), 'the voice turn ran without the overlay as its host'
    assert page.evaluate("window.__argyleStarts[0].host.channelId()") == 'dm_argyle'
    assert overlay(page).count() == 1, 'the hold opened a second overlay'
    wave = page.locator('#pwa-argyle-overlay .pwa-argyle-wave')
    settle(page, "!!document.querySelector('#pwa-argyle-overlay .pwa-argyle-wave') && document.querySelector('#pwa-argyle-overlay .pwa-argyle-wave').checkVisibility()")
    assert wave.is_visible(), 'talk mode shows no wave'
    assert page.locator('#pwa-argyle-overlay .pwa-argyle-wave i').count() == 6
    assert 'Listening' in status_text(page), status_text(page)
    # No reduced motion in this context: the wave moves while listening.
    assert page.locator('#pwa-argyle-overlay .pwa-argyle-wave i').first.evaluate(
        'e => getComputedStyle(e).animationName') != 'none'
    orb_hidden(page)
    shot(output, 'argyle-overlay-talk.png', page)
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape in talk mode')

    orb.dispatch_event('pointerdown', POINTER)
    page.wait_for_timeout(80)
    orb.dispatch_event('pointerup', POINTER)
    assert_open(page, 'a quick tap')
    page.wait_for_timeout(400)
    assert page.evaluate('window.__argyleStarts.length') == 1, 'a quick tap started a voice turn'
    input_focused(page)
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape after a quick tap')


def click_only_activation_opens_type_mode(page):
    """A screen reader activates the orb with a bare click (VoiceOver and
    TalkBack send no pointerdown/pointerup pair): that click opens the
    overlay in type mode, never a voice turn."""
    assert page.evaluate('PwaArgyle.isOpen()') is False
    starts = page.evaluate('(window.__argyleStarts || []).length')
    page.locator('#tab-argyle').evaluate('e => e.click()')
    assert_open(page, 'a click with no pointer pair (screen-reader activation)')
    input_focused(page)
    assert not page.locator('#pwa-argyle-overlay .pwa-argyle-wave').is_visible(), \
        'a click-only activation opened talk mode'
    page.wait_for_timeout(300)
    assert page.evaluate('(window.__argyleStarts || []).length') == starts, 'a click-only activation started a voice turn'
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape after a click-only activation')


# The phone's mic takes a moment: the voice turn says 'starting' at once and
# 'listening' only when the recorder runs (static/app_voice.js; pinned in
# tests/test_app_voice_host.py listening_only_once_recording). The early
# release rule (done() before listening ends the turn) lives in app_voice
# (early_release_cancels_the_turn); here the spy only counts done().
SPY_STAGED = """() => {
    window.__argyleStarts = [];
    window.__argyleDone = 0;
    const v = window.ChauffeurPhoneVoice;
    v.start = function (opts) {
        window.__argyleStarts.push(opts || {});
        const host = opts && opts.host;
        if (host && typeof host.status === 'function') {
            host.status('Starting microphone…', 'starting');
            // The REAL thread labels (static/app_voice.js); the overlay draws its own words.
            setTimeout(() => host.status('Listening — press Done when you finish.', 'listening'), 300);
        }
        return Promise.resolve();
    };
    v.done = function () { window.__argyleDone += 1; return Promise.resolve(); };
}"""

WAVE_SHOWN = ("!!document.querySelector('#pwa-argyle-overlay .pwa-argyle-wave') && "
              "document.querySelector('#pwa-argyle-overlay .pwa-argyle-wave').checkVisibility()")


def talk_mode_waits_for_the_microphone(page):
    """Talk mode shows the wave only once the voice turn says 'listening';
    while the mic starts the overlay says so and shows no wave."""
    assert page.evaluate('PwaArgyle.isOpen()') is False
    page.evaluate(SPY_STAGED)
    page.mouse.move(5, 5)
    orb = page.locator('#tab-argyle')
    orb.dispatch_event('pointerdown', POINTER)
    page.wait_for_timeout(450)
    orb.dispatch_event('pointerup', POINTER)
    assert_open(page, 'a 450 ms hold')
    settle(page, 'window.__argyleStarts.length > 0', 1000)
    assert page.evaluate('window.__argyleStarts.length') == 1, page.evaluate('window.__argyleStarts.length')
    wave = page.locator('#pwa-argyle-overlay .pwa-argyle-wave')
    # Inside the spy's 300 ms: the voice turn has said only 'starting'.
    assert not wave.is_visible(), "the wave shows while the microphone is still starting ('starting' drawn as listening)"
    assert 'Starting' in status_text(page), status_text(page)
    assert status_text(page) == 'Starting microphone…', status_text(page)
    page.wait_for_timeout(400)
    settle(page, WAVE_SHOWN, 2000)
    assert wave.is_visible(), "the wave never showed once the turn said 'listening'"
    assert 'Listening' in status_text(page), status_text(page)
    assert status_text(page) == 'Listening…', \
        "the overlay drew the thread's label, not its own word 'Listening…': %r" % status_text(page)
    assert page.evaluate('window.__argyleDone') == 1, \
        'the release at pointerup called done() %d times' % page.evaluate('window.__argyleDone')
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape after a staged talk start')


GHOST_TAP = """async () => {
    const orb = document.getElementById('tab-argyle');
    const o = {pointerId: 1, pointerType: 'touch', isPrimary: true, bubbles: true, cancelable: true};
    orb.dispatchEvent(new PointerEvent('pointerdown', o));
    await new Promise(r => setTimeout(r, 80));
    orb.dispatchEvent(new PointerEvent('pointerup', o));
    const t0 = performance.now();
    const openedByTap = PwaArgyle.isOpen();
    await new Promise(r => setTimeout(r, 40));
    const dim = document.querySelector('#pwa-argyle-overlay .pwa-argyle-dim');
    const ghostAfterMs = performance.now() - t0;
    if (dim) dim.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    return {openedByTap, ghostAfterMs, openAfterGhost: PwaArgyle.isOpen()};
}"""


def ghost_click_right_after_open_is_ignored(page):
    """The click a phone synthesises from the opening tap can land on the
    backdrop the tap just raised; a backdrop click that soon after opening is
    ignored, and a real backdrop tap later still closes."""
    assert page.evaluate('PwaArgyle.isOpen()') is False
    r = page.evaluate(GHOST_TAP)
    assert r['openedByTap'], 'the tap did not open the overlay: %r' % r
    assert r['ghostAfterMs'] < 100, 'the ghost click came too late to prove anything: %r' % r
    assert r['openAfterGhost'], 'a backdrop click %d ms after opening closed the overlay' % r['ghostAfterMs']
    assert overlay(page).is_visible(), 'the overlay hid after the ghost click'
    page.wait_for_timeout(500)
    page.locator('#pwa-argyle-overlay .pwa-argyle-dim').click(position={'x': 195, 'y': 120})
    assert_closed(page, 'a backdrop tap 500 ms after opening')


def popup_is_gone(page):
    assert page.locator('#kiosk-chat-popup').count() == 0, '#kiosk-chat-popup is still in the page'
    assert page.locator('#kiosk-chat-fab').count() == 0, '#kiosk-chat-fab is still in the page'
    assert page.evaluate("typeof toggleKioskChat") == 'undefined'
    view = page.evaluate('currentView')
    page.evaluate("setView('more')")
    page.wait_for_selector('#pwa-more-container [data-feature]')
    assert page.locator('[data-feature="assistant"]').count() == 0, 'Ask Argyle is still in More'
    page.evaluate('v => setView(v)', view)
    page.wait_for_function('v => currentView === v', arg=view)


def glow_and_dark(page, output):
    """In the normal context the glow breathes; dark keeps the overlay."""
    open_by_tap(page)
    glow = page.locator('#pwa-argyle-overlay .pwa-argyle-glow')
    assert glow.count() == 1
    assert glow.evaluate("e => getComputedStyle(e).pointerEvents") == 'none', 'the glow eats taps'
    assert glow.evaluate("e => getComputedStyle(e).animationName") != 'none', 'the glow does not move'
    page.evaluate("applyTheme('dark')")
    assert overlay(page).is_visible()
    shot(output, 'argyle-overlay-dark.png', page)
    page.evaluate("applyTheme('light')")
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape in dark')


def reduced_motion(page):
    open_by_tap(page)
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    glow = page.locator('#pwa-argyle-overlay .pwa-argyle-glow')
    assert glow.evaluate("e => getComputedStyle(e).animationName") == 'none', 'the glow moves under reduced motion'
    page.evaluate("PwaArgyle.setState('listening')")
    bars = page.locator('#pwa-argyle-overlay .pwa-argyle-wave i')
    assert bars.count() == 6
    names = bars.evaluate_all("els => els.map(e => getComputedStyle(e).animationName)")
    assert set(names) == {'none'}, names
    page.evaluate("PwaArgyle.setState('idle')")
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape under reduced motion')


def helper_refusal(page, calls):
    """A helper the household let talk to Argyle sees the orb; the server's
    refusal is said in the overlay, never as a dead input."""
    assert page.evaluate('pwaOrbAllowed()') is True
    assert page.locator('#tab-argyle').is_visible(), 'the granted helper has no orb'
    open_by_tap(page)
    settle(page, "!!document.querySelector('#pwa-argyle-overlay .pwa-argyle-status.is-refused')")
    status = page.locator('#pwa-argyle-overlay .pwa-argyle-status')
    assert 'Requires chat.agent' in status.inner_text(), status.inner_text()
    assert 'is-refused' in (status.get_attribute('class') or ''), status.get_attribute('class')
    assert not page.locator('#pwa-argyle-overlay .pwa-argyle-bar').is_visible(), 'a refused member got an input bar'
    assert calls['dm'] and calls['dm'][-1] == {'member_id': 'helper_granted', 'other_member_id': 'argyle'}, calls['dm']
    assert not calls['messages_post'], calls['messages_post']
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape on a refusal')
    # The hold path: a release after the refusal must not replace the server's
    # words with "Keep holding…" (there is no input bar to type into).
    page.mouse.move(5, 5)
    orb = page.locator('#tab-argyle')
    orb.dispatch_event('pointerdown', POINTER)
    page.wait_for_timeout(450)
    settle(page, "!!document.querySelector('#pwa-argyle-overlay .pwa-argyle-status.is-refused')")
    orb.dispatch_event('pointerup', POINTER)
    page.wait_for_timeout(300)
    status = page.locator('#pwa-argyle-overlay .pwa-argyle-status')
    assert 'Requires chat.agent' in status.inner_text(), ('a release replaced the refusal', status.inner_text())
    assert 'is-refused' in (status.get_attribute('class') or ''), status.get_attribute('class')
    assert not page.locator('#pwa-argyle-overlay .pwa-argyle-bar').is_visible(), 'a refused member got an input bar after a hold'
    page.keyboard.press('Escape')
    assert_closed(page, 'Escape on a refusal after a hold')


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
            with served.browser(reduced_motion='no-preference', has_touch=True) as page:
                calls, failed_assets = boot(served, page, key, role, driver)
                if key == 'parent':
                    tap_opens_over_the_screen(page, key, calls, output)
                    type_and_reply(page, key, calls, output)
                    dismissals(page)
                    closed_overlay_ignores_events(page, key, calls)
                    to_messages(page, key, calls)
                    hold_talks(page, output)
                    click_only_activation_opens_type_mode(page)
                    talk_mode_waits_for_the_microphone(page)
                    ghost_click_right_after_open_is_ignored(page)
                    popup_is_gone(page)
                    glow_and_dark(page, output)
                else:
                    helper_refusal(page, calls)
                errors = page_errors(served, key)
                assert not errors and not failed_assets, (key, errors, failed_assets)
            if key == 'parent':
                with served.browser(reduced_motion='reduce', has_touch=True) as page:
                    calls, failed_assets = boot(served, page, key, role, driver)
                    reduced_motion(page)
                    errors = page_errors(served, key)
                    assert not errors and not failed_assets, (key, 'reduced motion', errors, failed_assets)
            print('ok', key, flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    run()
