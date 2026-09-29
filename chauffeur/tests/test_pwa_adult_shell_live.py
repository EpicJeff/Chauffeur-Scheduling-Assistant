"""Adult navigation and drive summary in the served PWA, with isolated fixtures.

Run: venv/Scripts/python.exe -X utf8 chauffeur/tests/test_pwa_adult_shell_live.py
Optional PWA_REVIEW_OUTPUT writes screenshots without touching audit originals.
"""
import atexit
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
DATA = tempfile.mkdtemp(prefix='chauffeur_adult_shell_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

DAY = datetime.now().strftime('%Y-%m-%d')
PROFILES = [('parent', 'parent', 'd1'), ('adult', 'adult', 'd2'),
            ('keeping', 'parent', None), ('helper', 'helper', 'd3'),
            ('guest', 'guest', None)] + [(stage, 'child', None) for stage in
            ('sprout', 'explorer', 'navigator', 'copilot')]


def seed():
    for key, role, driver in PROFILES:
        member = {'id': key, 'name': 'Alex Morgan' if role != 'child' else 'Jamie',
                  'role': role, 'driver_id': driver, 'color_code': '#287a72'}
        if role == 'child':
            member['stage_override'] = key
        if key == 'keeping':
            member['scope'] = {'preset': 'keeping_up'}
        storage.add_member(member)
        if driver:
            storage.add_driver({'id': driver, 'name': 'Alex Morgan', 'home_location': 'Home', 'color_code': '#287a72'})


def check_route_departure(page, schedule, driver, output=None):
    """The event modal and hero must identify the SAME rider and stop.

    Use the real drive-sheet endpoint, not a mocked sheet response. The
    earlier appointment's route ID survives a home layover before practice.
    """
    for pid, name in [('lorena', 'Lorena'), ('james', 'James')]:
        storage.add_passenger({'id': pid, 'name': name,
                               'calendar_ids': ['cal_' + pid]})
    schedule['events'][0]['calendar_ids'] = ['cal_lorena']
    schedule['events'][1]['calendar_ids'] = ['cal_james']
    schedule['calendar_metadata'] = {'cal_lorena': {'summary': 'Lorena'},
                                     'cal_james': {'summary': 'James'}}
    schedule['initial_edges'] = {}
    schedule['route_edges'] = {driver: {'morning': {
        'to_event': 'soccer', 'travel_mins': 35,
        'home_waypoint': {'driver_home_location': 'Home', 'to_home_mins': 15,
                          'from_home_mins': 20, 'layover_mins': 315}}}}
    storage.set_cached_schedule(schedule)
    page.clock.set_fixed_time(datetime.now().replace(hour=12, minute=0, second=0))
    page.evaluate('''s => {
        document.documentElement.style.fontSize = '';
        scheduleData = s; setView('drives'); buildTimeline();
    }''', schedule)
    page.locator('.pwa-event-row .pwa-row-main').filter(has_text='Soccer practice').click()
    assert page.locator('#em-passengers').inner_text() == 'James'
    assert page.locator('#em-map-btn').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(34, 98, 76)'
    page.wait_for_function("getComputedStyle(document.getElementById('event-modal')).opacity === '1'")
    page.wait_for_timeout(350)
    if output: Path(output, 'adult-event-sheet-light.png').write_bytes(page.screenshot())
    page.evaluate('closeEventModal()')
    page.wait_for_selector('#event-modal', state='hidden')
    page.locator('.pwa-next button').click()
    page.wait_for_function("driveSheetData?.leg_id === 'route_morning_2'")
    assert page.locator('#drive-dest').inner_text() == 'Riverside fields'
    assert page.evaluate('driveSheetData.passengers.map(p=>p.name)') == ['James']
    assert page.evaluate('routeContext.eventId') == 'soccer'
    assert page.evaluate('routeContext.destination') == 'Riverside fields'
    assert page.evaluate('driveSheetData.next_drive.title') == 'Piano lesson'
    assert page.locator('#sheet-title').inner_text() == 'Your drive'
    assert page.locator('#btn-start-drive').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(34, 98, 76)'
    assert page.locator('#btn-mark-completed').evaluate('(e)=>getComputedStyle(e).boxShadow') == 'none'
    page.locator('#drive-roll-chips button').click()
    page.wait_for_function("driveSheetData.passengers[0].aboard === true")
    assert page.locator('#drive-roll-chips button').get_attribute('data-aboard') == 'yes'
    if output: Path(output, 'adult-drive-sheet-light.png').write_bytes(page.screenshot())
    page.evaluate("applyTheme('dark')")
    page.wait_for_function("getComputedStyle(document.getElementById('btn-start-drive')).backgroundColor === 'rgb(174, 216, 189)'")
    if output: Path(output, 'adult-drive-sheet-dark.png').write_bytes(page.screenshot())
    page.evaluate("applyTheme('light')")
    for width in (360, 768):
        page.set_viewport_size({'width': width, 'height': 844})
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert page.locator('#action-sheet-content').evaluate('(e)=>e.scrollWidth <= e.clientWidth')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='Close drive details', exact=True).click()
    page.wait_for_selector('#action-sheet', state='hidden')
    page.evaluate("window.sheetAnswer = 'pending'; void promptConfirm('Approve task?', 'Sam finished taking out recycling.', 'Approve', 'Not yet').then(v=>window.sheetAnswer=v)")
    if output: Path(output, 'adult-confirm-sheet-light.png').write_bytes(page.screenshot())
    page.locator('.pwa-prompt-overlay [data-yes]').click()
    page.wait_for_function('window.sheetAnswer === true')
    page.evaluate("void promptInput('Send a request', 'What would help?', {okText:'Send request'}).then(v=>window.sheetAnswer=v)")
    page.locator('.pwa-prompt-overlay textarea').fill('Please cover the school pickup.')
    page.locator('.pwa-prompt-overlay [data-yes]').click()
    page.wait_for_function("window.sheetAnswer === 'Please cover the school pickup.'")
    page.evaluate("void promptChoice('Who is doing it?', 'Choose a family member.', [{label:'James',value:'james'}]).then(v=>window.sheetAnswer=v)")
    page.locator('.pwa-prompt-overlay [data-pick]').click()
    page.wait_for_function("window.sheetAnswer === 'james'")
    page.evaluate("void promptConfirm('Keep this change?', '').then(v=>window.sheetAnswer=v)")
    page.get_by_role('button', name='Close dialog', exact=True).click()
    page.wait_for_function('window.sheetAnswer === false')


def run():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    # This test serves the real UI/routes against fictional data. Background
    # schedule, email and push pollers are outside the test and can block
    # startup on network I/O before uvicorn starts accepting requests.
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
                errors = []
                failed_scripts = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('requestfailed', lambda request: failed_scripts.append(
                    (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
                page.on('response', lambda response: failed_scripts.append(
                    (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
                    and response.status >= 400 else None)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.clock.set_fixed_time(datetime.now().replace(hour=12, minute=0, second=0))
                # Windows loopback occasionally resets a static-script socket
                # (ERR_CONNECTION_RESET). Retry transport only; serve the real
                # response and still fail on HTTP errors or JS exceptions.
                def static_asset(route):
                    if route.request.resource_type in ('script', 'stylesheet'):
                        route.fulfill(response=route.fetch(max_retries=2))
                    else:
                        route.continue_()
                page.route('**/static/**', static_asset)
                token = storage.create_member_token(key)
                values = {'chauffeur_member_id': key, 'chauffeur_member_token': token,
                          'chauffeur_member_token_for': key, 'chauffeur_view': 'drives',
                          'chauffeur_theme': 'light'}
                if driver:
                    values['chauffeur_driver_id'] = driver
                page.add_init_script('Object.entries(' + json.dumps(values) +
                                     ').forEach(([k,v])=>localStorage.setItem(k,v));')
                event = {'id': 'soccer', 'title': 'Soccer practice',
                         'start': DAY + 'T16:00:00', 'end': DAY + 'T17:00:00',
                         'location': 'Riverside fields', 'calendar_ids': [], 'event_type': 'activity'}
                past = dict(event, id='morning', title='Morning appointment', start=DAY+'T09:00:00', end=DAY+'T10:00:00', location='Medical center, Main Street')
                later = dict(event, id='piano', title='Piano lesson', start=DAY+'T17:30:00', end=DAY+'T18:00:00', location='Music studio')
                schedule = {'events': [past, event, later], 'assignments': {'soccer': driver, 'morning': driver, 'piano': driver},
                            'home_location': 'Home', 'calendar_metadata': {},
                            'initial_edges': {driver: {'soccer': {'travel_mins': 20, 'buffer_before_mins': 5}}} if driver else {},
                            'route_edges': {}, 'final_edges': {}}
                page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
                page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
                page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
                page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))
                page.route('**/api/members/*/day?*', lambda r: r.fulfill(json={'rides': [], 'due_soon': [], 'status_days': []}))
                page.route('**/api/routines/day?*', lambda r: r.fulfill(json={'items': [], 'streak': {}}))
                chores = [dict(id='dishwasher', title='Unload the dishwasher', description='Kitchen', points=10, state='claimed', claimed_by=key, claimed_by_name='Alex'),
                          dict(id='recycling', title='Take out recycling', points=15, state='done', claimed_by='navigator', claimed_by_name='Sam'),
                          dict(id='plants', title='Water the plants', points=5, state='open', eligible_member_ids=[])]
                page.route('**/api/chores', lambda r: r.fulfill(json=chores))
                page.route('**/api/points', lambda r: r.fulfill(json=[]))
                page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
                page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))
                page.route('**/api/channels?*', lambda r: r.fulfill(json=[{'id':'family','kind':'family','title':'Family','member_ids':[key], 'last_message':{'sender_member_id':key,'body':'See you at the front doors.','ts':int(datetime.now().timestamp())}}, {'id':'school','kind':'group','title':'School pickup','member_ids':[key]}]))
                page.route('**/api/programs', lambda r: r.fulfill(json={'programs':[dict(id='practice', member_id=key, title='Strength training', state='active', progress={}, emissions={})]}))
                page.route('**/api/practice-windows?*', lambda r: r.fulfill(json={'windows':[dict(program_id='practice', member_id=key, date=DAY, time_start='21:00', time_end='21:30', title='Strength training', session_label='Push and core', steps=[])]}))
                page.goto(served.url('app'), wait_until='domcontentloaded')
                page.wait_for_timeout(500)
                if page.locator('#pin-modal-skip').is_visible():
                    page.locator('#pin-modal-skip').click()
                page.wait_for_selector('#screen-schedule:not(.hidden)')
                page.wait_for_function('membersData.length > 0')
                page.wait_for_timeout(500)
                assert page.evaluate('selectedMemberId') == key
                assert page.evaluate('currentMemberRole()') == role
                tabs = page.locator('#pwa-tab-bar > button:visible').all_text_contents()
                tabs = [' '.join(t.split()) for t in tabs]
                overflow = page.evaluate('''()=>({width:document.documentElement.scrollWidth,
                    viewport:innerWidth, elements:[...document.querySelectorAll('body *')]
                    .filter(e=>e.checkVisibility()&&e.getBoundingClientRect().right>innerWidth+1)
                    .slice(0,8).map(e=>({tag:e.tagName,id:e.id,cls:e.className}))})''')
                assert overflow['width'] <= overflow['viewport'], (key, overflow, errors)
                if role == 'child':
                    assert not page.locator('#tab-more').is_visible(), tabs
                    assert page.locator('#tab-map').is_visible(), tabs
                    assert page.locator('#tab-myday').inner_text() == 'My Day'
                    assert page.locator('#btn-pet').is_visible()
                    page.evaluate("setView('more')")
                    assert page.evaluate('currentView') != 'more'
                    page.evaluate("void promptConfirm('Keep your plan?', 'Your schedule stays the same.').then(()=>{})")
                    assert page.locator('.pwa-prompt-overlay .pwa-sheet-head').is_hidden()
                    # The existing app utility uses 20px child corners.
                    assert page.locator('.pwa-prompt-overlay > div').evaluate('(e)=>getComputedStyle(e).borderTopLeftRadius') == '20px'
                    page.locator('.pwa-prompt-overlay [data-no]').click()
                else:
                    assert page.locator('#tab-more').is_visible(), tabs
                    assert not page.locator('#tab-map').is_visible()
                    assert not page.locator('#kiosk-chat-fab').is_visible()
                    assert page.locator('header').bounding_box()['height'] <= 72
                    if key == 'parent':
                        assert len(tabs) == 5, tabs
                        page.wait_for_selector('.pwa-next')
                        original = page.locator('.pwa-leg-row[data-next="upcoming"]').first
                        time_label = original.get_attribute('data-time-label')
                        assert page.locator('.pwa-next h2').inner_text() == time_label
                        page.locator('.pwa-next button').click()
                        assert page.locator('#action-sheet').is_visible()
                        page.evaluate('closeActionSheet()')
                        page.wait_for_selector('#action-sheet', state='hidden')
                        assert page.locator('#pwa-page-heading h2').inner_text() == 'Your afternoon'
                        assert page.locator('#day-nav').is_hidden()
                        assert page.locator('.pwa-event-row').first.evaluate('(e)=>getComputedStyle(e).opacity') == '1'
                        assert page.locator('.pwa-event-row').first.evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgba(0, 0, 0, 0)'
                        if output:
                            Path(output, 'adult-today-light.png').write_bytes(page.screenshot())
                        page.locator('.pwa-attention').click()
                        page.locator('#pwa-attention-dialog [data-feature="household"]').click()
                        assert page.locator('#chores-container').get_attribute('data-section') == 'reviews'
                        assert page.get_by_role('button', name='\u2713 Verify').is_visible()
                        page.get_by_role('button', name='Tasks', exact=True).click()
                        assert page.get_by_role('button', name='Mark done').is_visible()
                        assert not page.get_by_role('button', name='\u2713 Verify').is_visible()
                        if output: Path(output, 'adult-household-light.png').write_bytes(page.screenshot())
                        page.locator('#tab-family').click()
                        page.wait_for_selector('#pane-events .pwa-agenda-row')
                        assert page.locator('#pwa-page-heading h2').inner_text() == 'Family plan'
                        if output: Path(output, 'adult-plan-light.png').write_bytes(page.screenshot())
                        page.locator('#pwa-date-strip button').nth(1).click()
                        assert page.evaluate('activeDateIndex') == 1
                        page.locator('#pwa-date-strip button').first.click()
                        page.locator('#tab-messages').click()
                        page.get_by_role('searchbox', name='Find a conversation').fill('School')
                        assert page.locator('#channel-list > button:visible').count() == 1
                        page.get_by_role('searchbox', name='Find a conversation').fill('')
                        page.get_by_role('searchbox', name='Find a conversation').blur()
                        if output: Path(output, 'adult-messages-light.png').write_bytes(page.screenshot())
                        page.locator('#tab-drives').click()
                        page.evaluate("scheduleData.completed_drives=['init_soccer']; buildTimeline()")
                        assert page.locator('.pwa-next').count() == 0
                        page.evaluate("scheduleData.completed_drives=[]; scheduleData.in_progress_drives=['init_soccer']; buildTimeline()")
                        assert page.locator('.pwa-next > p').inner_text() == 'CURRENT DRIVE'
                        page.evaluate("scheduleData.in_progress_drives=[]; buildTimeline()")
                        # Real program disclosures retain their existing handler.
                        program = page.locator('[data-myday-program="practice"]').first
                        page.wait_for_selector('[data-myday-program="practice"]')
                        program.locator('[data-myday-toggle]').click()
                        assert program.locator('[data-myday-body]').is_visible()
                        program.locator('[data-myday-toggle]').click()
                        page.evaluate('document.getElementById(`pane-${activeDateIndex}`).scrollTop=0')
                    page.get_by_role('button', name='Search features', exact=True).click()
                    search = page.get_by_role('searchbox', name='Search features')
                    assert search.evaluate('(e)=>e === document.activeElement')
                    search.fill('music')
                    assert page.locator('#pwa-feature-list [data-feature="music"]').count() == (0 if role in ('helper', 'guest') else 1)
                    search.fill('no-match-xyz')
                    assert page.locator('#pwa-search-empty').is_visible()
                    search.fill('')
                    if key in ('parent', 'adult'):
                        page.locator('[data-feature="map"]').click()
                        assert page.locator('#tab-more').get_attribute('aria-current') == 'page'
                        page.locator('#tab-more').click()
                    else:
                        assert page.locator('[data-feature="map"]').count() == 0
                    if output and key == 'parent':
                        Path(output, 'adult-more-light.png').write_bytes(page.screenshot())
                    page.locator('#pwa-identity').click()
                    assert page.locator('#pwa-profile').is_visible()
                    page.locator('#pwa-profile [data-feature="theme"]').click()
                    assert page.evaluate('themePref()') == 'dark'
                    page.keyboard.press('Escape')
                    assert not page.locator('#pwa-profile').is_visible()
                    assert page.locator('#pwa-identity').evaluate('(e)=>e === document.activeElement')
                    if key == 'parent':
                        page.locator('#tab-drives').click()
                        if output:
                            page.wait_for_function("document.getElementById('global-alert').classList.contains('opacity-0')")
                            page.wait_for_timeout(350)
                            Path(output, 'adult-today-dark.png').write_bytes(page.screenshot())
                        # Match the user's reported case: all drives have passed,
                        # with a later program still ahead. Past text stays legible.
                        page.clock.set_fixed_time(datetime.now().replace(hour=18, minute=0, second=0))
                        page.evaluate("applyTheme('light'); buildTimeline()")
                        assert page.locator('.pwa-next').count() == 0
                        assert page.locator('.pwa-leg-row[data-next="past"]').first.evaluate('(e)=>getComputedStyle(e).opacity') == '1'
                        if output: Path(output, 'adult-driver-past-light.png').write_bytes(page.screenshot())
                        # Follow the review summary to the original verify action.
                        def verify(route):
                            assert route.request.method == 'POST'
                            assert route.request.headers.get('x-member-token')
                            chores[1]['state'] = 'verified'
                            route.fulfill(json={})
                        page.route('**/api/chores/recycling/verify', verify)
                        page.locator('.pwa-attention').click()
                        page.locator('#pwa-attention-dialog [data-feature="household"]').click()
                        page.get_by_role('button', name='\u2713 Verify').click()
                        page.wait_for_function('houseChoresAttention() === 0')
                        page.locator('#tab-drives').click()
                        assert page.locator('.pwa-attention').count() == 0
                        page.get_by_role('button', name='Choose schedule day').click()
                        assert page.locator('#day-nav').is_visible()
                        page.locator('#pwa-date-strip button').nth(1).click()
                        assert page.evaluate('activeDateIndex') == 1
                        page.locator('#pwa-date-strip button').first.click()
                        page.get_by_role('button', name='Choose schedule day').click()
                        for width in (360, 768):
                            page.set_viewport_size({'width': width, 'height': 844})
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.set_viewport_size({'width': 390, 'height': 844})
                        page.evaluate("document.documentElement.style.fontSize='200%'")
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        check_route_departure(page, schedule, driver, output)
                        check_other_adult_sheets(page, output)
                assert not errors and not failed_scripts, (key, errors, failed_scripts)
                print('ok', key, tabs, flush=True)
    finally:
        served.stop()


def check_other_adult_sheets(page, output=None):
    for theme in ('light', 'dark'):
        page.evaluate('t=>applyTheme(t)', theme)
        for name, selector, opening, closing in (
            ('notifications', '#notif-modal-content', 'toggleNotifications()', 'toggleNotifications()'),
            ('profile', '#pwa-profile', 'pwaOpenProfile()', "document.getElementById('pwa-profile').close()"),
            ('new-chat', '#new-chat-modal > div', 'openNewChat()', 'closeNewChat()'),
        ):
            page.evaluate(opening)
            page.wait_for_timeout(350)
            panel = page.locator(selector)
            assert panel.is_visible(), name
            assert panel.evaluate('(e)=>e.scrollWidth<=e.clientWidth'), name
            if name == 'notifications':
                assert panel.bounding_box()['height'] < 400  # empty sheet fits its content
            if name == 'profile':
                assert panel.locator('.pwa-feature small').first.evaluate('(e)=>getComputedStyle(e).fontWeight') == '400'
            if name == 'new-chat':
                assert page.locator('#new-chat-start').is_disabled()
                page.locator('#new-chat-suggestions > button').first.click()
                assert page.locator('#new-chat-start').is_enabled()
                assert page.locator('#new-chat-pills button').get_attribute('aria-label').startswith('Remove ')
            small = panel.locator('button:visible').evaluate_all('(els)=>els.filter(e=>e.getBoundingClientRect().height<43).map(e=>e.textContent)')
            assert not small, (name, small)
            if output:
                page.mouse.move(0, 0)
                page.wait_for_function("document.getElementById('global-alert').classList.contains('opacity-0')")
                page.wait_for_timeout(350)
                Path(output, f'adult-{name}-sheet-{theme}.png').write_bytes(page.screenshot())
            if name == 'new-chat':
                page.locator('#new-chat-pills button').click()
                assert page.locator('#new-chat-start').is_disabled()
            page.evaluate(closing)
            page.wait_for_timeout(350)


if __name__ == '__main__':
    run()
