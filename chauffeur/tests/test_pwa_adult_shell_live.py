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


def run():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    if served is None:
        return
    output = os.environ.get('PWA_REVIEW_OUTPUT')
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
    try:
        for key, role, driver in PROFILES:
            with served.browser(reduced_motion='reduce', has_touch=True) as page:
                errors = []
                failed_scripts = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('requestfailed', lambda request: failed_scripts.append(
                    (request.url, request.failure)) if request.resource_type == 'script' else None)
                page.on('response', lambda response: failed_scripts.append(
                    (response.url, response.status)) if response.request.resource_type == 'script'
                    and response.status >= 400 else None)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.clock.set_fixed_time(datetime.now().replace(hour=12, minute=0, second=0))
                # Windows loopback occasionally resets a static-script socket
                # (ERR_CONNECTION_RESET). Retry transport only; serve the real
                # response and still fail on HTTP errors or JS exceptions.
                def static_asset(route):
                    if route.request.resource_type == 'script':
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
                schedule = {'events': [event], 'assignments': {'soccer': driver},
                            'home_location': 'Home', 'calendar_metadata': {},
                            'initial_edges': {driver: {'soccer': {'travel_mins': 20, 'buffer_before_mins': 5}}} if driver else {},
                            'route_edges': {}, 'final_edges': {}}
                page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
                page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
                page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
                page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))
                page.route('**/api/members/*/day?*', lambda r: r.fulfill(json={'rides': [], 'due_soon': [], 'status_days': []}))
                page.route('**/api/routines/day?*', lambda r: r.fulfill(json={'items': [], 'streak': {}}))
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
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), key
                if role == 'child':
                    assert not page.locator('#tab-more').is_visible(), tabs
                    assert page.locator('#tab-map').is_visible(), tabs
                    assert page.locator('#tab-myday').inner_text() == 'My Day'
                    assert page.locator('#btn-pet').is_visible()
                    page.evaluate("setView('more')")
                    assert page.evaluate('currentView') != 'more'
                else:
                    assert page.locator('#tab-more').is_visible(), tabs
                    assert not page.locator('#tab-map').is_visible()
                    assert not page.locator('#kiosk-chat-fab').is_visible()
                    assert page.locator('header').bounding_box()['height'] <= 72
                    if key == 'parent':
                        assert len(tabs) == 5, tabs
                        page.wait_for_selector('.pwa-next')
                        original = page.locator('.pwa-leg-row[data-next="upcoming"]').first
                        time_label = original.locator(':scope > div:nth-child(2) > div').first.text_content()
                        assert page.locator('.pwa-next h2').inner_text() == time_label
                        page.locator('.pwa-next button').click()
                        assert page.locator('#action-sheet').is_visible()
                        page.evaluate('closeActionSheet()')
                        if output:
                            Path(output, 'adult-today-light.png').write_bytes(page.screenshot())
                        page.evaluate("scheduleData.completed_drives=['init_soccer']; buildTimeline()")
                        assert page.locator('.pwa-next').count() == 0
                        page.evaluate("scheduleData.completed_drives=[]; scheduleData.in_progress_drives=['init_soccer']; buildTimeline()")
                        assert page.locator('.pwa-next > p').inner_text() == 'CURRENT DRIVE'
                        page.evaluate("scheduleData.in_progress_drives=[]; buildTimeline()")
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
                        for width in (360, 768):
                            page.set_viewport_size({'width': width, 'height': 844})
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.set_viewport_size({'width': 390, 'height': 844})
                        page.evaluate("document.documentElement.style.fontSize='200%'")
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                assert not errors and not failed_scripts, (key, errors, failed_scripts)
                print('ok', key, tabs, flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    run()
