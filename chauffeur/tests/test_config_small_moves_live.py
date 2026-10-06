"""The small moves off Config, actually served (v2.499.257).

Four things left Config for the surface they belong to:

  - trip hashtags → the Trips page (#trip-hashtags);
  - proactive heads-ups → Work → Mind (#heads-ups);
  - Status Days (the day types and the days set with them) → the Calendar
    page (#status-days);
  - the house facade editor → Config's Boards tab, renamed Boards & House,
    with config#home still landing on it.

What only a browser can check: each save sends ONLY its own key (the
settings POST merges), the Status Days editor does its whole job from the
Calendar page (add, edit, set a day, clear it, delete), none of it is drawn
on a kiosk, a panel or a filtered embed, and Config points at every new home.

Run from chauffeur/:  python tests/test_config_small_moves_live.py [--out DIR]
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='config_small_moves_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app

from services import storage

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _visible(page, sel):
    return page.evaluate(
        "(s) => { const el = document.querySelector(s);"
        " return !!el && getComputedStyle(el).display !== 'none'; }", sel)


def _el_shot(locator, name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        locator.screenshot(path=os.path.join(OUT, name))


def seed():
    storage.update_settings({'days_to_show': 9, 'trip_hashtags': ['#trip'],
                             'proactive_watchers_enabled': True,
                             'intake_imap_host': 'imap.example.com'})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'kid_ada', 'name': 'Ada', 'role': 'child', 'is_child': True,
                        'color_code': '#14b8a6'})


def _changed(before, after):
    keys = set(before) | set(after)
    return {k for k in keys if before.get(k) != after.get(k)}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1400, 'height': 900})

            # --- Trips: add a hashtag; only trip_hashtags changes.
            page.goto(served.url('trips#trip-hashtags'), wait_until='networkidle')
            page.wait_for_timeout(500)
            check(_visible(page, '#trip-hashtags'), 'the Trips page has no trip hashtags section')
            check(page.locator('#trip-hashtags [data-trip-hashtag]').count() == 1, 'the saved hashtag did not load')
            before = dict(storage.get_settings())
            page.fill('#newTripHashtagInput', 'Holiday')
            page.click('#trip-hashtags [data-add-trip-hashtag]')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('trip_hashtags') == ['#trip', '#holiday'],
                  f"the hashtag did not save: {after.get('trip_hashtags')}")
            check(_changed(before, after) == {'trip_hashtags'},
                  f'the hashtag save touched other settings: {_changed(before, after)}')
            _el_shot(page.locator('#trip-hashtags'), 'trips-hashtags.png')

            # --- Work → Mind: the heads-up switch; only its key changes.
            page.goto(served.url('work?tab=mind#heads-ups'), wait_until='networkidle')
            page.wait_for_timeout(500)
            check(_visible(page, '#heads-ups'), 'Work → Mind has no heads-ups switch')
            check(page.is_checked('#proactiveWatchersEnabled'), 'the heads-up switch did not load as on')
            before = dict(storage.get_settings())
            page.uncheck('#proactiveWatchersEnabled')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('proactive_watchers_enabled') is False, 'the heads-up switch did not save')
            check(_changed(before, after) == {'proactive_watchers_enabled'},
                  f'the heads-up save touched other settings: {_changed(before, after)}')
            if OUT:
                page.evaluate("document.getElementById('heads-ups').scrollIntoView({block: 'center'})")
                page.wait_for_timeout(200)
                page.screenshot(path=os.path.join(OUT, 'mind-heads-ups.png'))

            # --- Calendar: Status Days, the whole hand path.
            page.goto(served.url('calendar'), wait_until='networkidle')
            page.wait_for_timeout(600)
            check(page.locator('[data-status-days-link]').count() == 1, 'the Calendar header has no Status days link')
            sd = page.locator('#status-days')
            sd.scroll_into_view_if_needed()
            check(sd.is_visible(), 'the Calendar page has no Status days section')
            # Add a day type.
            sd.locator('[data-status-add]').click()
            sd.locator('[data-status-name]').fill('Chemo Day')
            sd.locator('[data-status-kid]').fill("Mom's resting today. Grandma's picking you up.")
            sd.locator('select[x-model="newStatusProtocol.member_id"]').select_option('mum')
            sd.locator('[data-status-submit]').click()
            page.wait_for_timeout(800)
            protos = storage.get_all_status_protocols()
            check(len(protos) == 1 and protos[0]['name'] == 'Chemo Day' and protos[0].get('member_id') == 'mum',
                  f'the day type was not created: {protos}')
            check(sd.locator('[data-status-row]').count() == 1, 'the new day type is not listed')
            # Edit it.
            sd.locator('[data-status-edit]').click()
            check(sd.locator('[data-status-name]').input_value() == 'Chemo Day', 'Edit did not load the day type')
            sd.locator('[data-status-name]').fill('Treatment Day')
            sd.locator('[data-status-submit]').click()
            page.wait_for_timeout(800)
            protos = storage.get_all_status_protocols()
            check(len(protos) == 1 and protos[0]['name'] == 'Treatment Day',
                  f'the edit did not save: {protos}')
            # Set a day with it, then clear it.
            tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
            sd.locator('input[x-model="newStatusDay.date"]').fill(tomorrow)
            sd.locator('select[x-model="newStatusDay.protocol_id"]').select_option(protos[0]['id'])
            sd.locator('[data-status-set]').click()
            page.wait_for_timeout(1000)
            days = storage.get_status_days()
            check(len(days) == 1 and days[0]['date'] == tomorrow, f'the status day was not set: {days}')
            check(tomorrow in sd.inner_text(), 'the set day is not listed under Upcoming')
            _el_shot(sd, 'calendar-status-days.png')
            sd.locator('[data-status-clear]').click()
            page.locator('#cc-confirm-execute-btn').click()
            page.wait_for_timeout(800)
            check(not storage.get_status_days(), 'clearing the day did not remove it')
            # Delete the day type.
            sd.locator('[data-status-delete]').click()
            page.locator('#cc-confirm-execute-btn').click()
            page.wait_for_timeout(800)
            check(not storage.get_all_status_protocols(), 'deleting the day type did not remove it')

            # --- Config: Boards & House, config#home, and the pointers.
            # Signed in as a parent (the admin gate), as the house editor
            # test does, so the screenshot shows the page and not the gate.
            token = storage.create_member_token('mum')
            page.evaluate('t => localStorage.setItem("chauffeur_admin_token", t)', token)
            page.goto(served.url('config#home'), wait_until='networkidle')
            page.wait_for_timeout(800)
            check(_visible(page, '#home'), 'config#home did not open the house editor')
            check(_visible(page, '#boards'), 'the house editor is not on the Boards & House tab')
            check(page.get_by_role('button', name='Boards & House').count() == 1, 'the tab is not called Boards & House')
            if OUT:
                page.screenshot(path=os.path.join(OUT, 'config-boards-house.png'))
            page.goto(served.url('config'), wait_until='networkidle')
            page.wait_for_timeout(400)
            check(page.locator('a[href$="trips#trip-hashtags"]').count() >= 1, 'Config has no pointer to trip hashtags')
            check(page.locator('a[href$="work?tab=mind#heads-ups"]').count() >= 1, 'Config has no pointer to heads-ups')
            check(page.locator('a[href$="calendar#status-days"]').count() >= 1, 'Config has no pointer to Status Days')
            check(page.locator('#trip-hashtags, #proactiveWatchersEnabled, [data-status-add]').count() == 0,
                  'Config still draws a moved control')

            # --- Never on a wall.
            for path, sel in (('trips?kiosk=true', '#trip-hashtags'),
                              ('trips?tabs=trips', '#trip-hashtags'),
                              ('calendar?kiosk=true', '#status-days, [data-status-days-link]'),
                              ('calendar?tabs=calendar', '#status-days, [data-status-days-link]'),
                              ('work?panel=true', '#heads-ups, #proactiveWatchersEnabled'),
                              ('mind?kiosk=true', '#heads-ups, #proactiveWatchersEnabled')):
                page.goto(served.url(path), wait_until='domcontentloaded')
                page.wait_for_timeout(300)
                check(page.locator(sel).count() == 0, f'a moved setting is drawn on {path}')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_config_small_moves_live OK')


if __name__ == '__main__':
    main()
