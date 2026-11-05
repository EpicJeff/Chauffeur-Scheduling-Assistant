"""The feed's driving switch and Undo Ignore, actually served.

What only a browser can check:
  * the Subscribe form carries "Include in the driving schedule", ticked by
    default; unticking it rides the create (through the team picker too);
  * a feed row that is off says so, and its own "In the driving schedule"
    box turns it back on through the PUT;
  * the calendar's event setup reads "Undo Ignore" on an ignored event and
    tapping it saves is_ignored False for that event (no confirm: undoing is
    safe); a driven event still reads "Ignore Event".

The feed and Google Calendar are stubbed in-process (uvicorn runs on a
thread), so no network and nothing touches data/.

Run from chauffeur/:  python tests/test_feed_driving_switch_live.py [--out DIR]
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='feed_switch_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app

from services import ics_sync, storage
from test_ics_team_filter import FEED_TITLES, SURGE, FakeGcal, build_ics

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
OFF_TEXT = 'Calendar only, never driven'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'kid_ada', 'name': 'Ada', 'role': 'child', 'is_child': True,
                        'color_code': '#14b8a6', 'calendar_ids': ['ada@cal']})
    ics_sync.fetch_ics = lambda url: build_ics(FEED_TITLES)
    ics_sync.gcal = FakeGcal()


def _event(eid, title, ignored):
    return {'id': f'ada@cal::{eid}', 'title': title,
            'start': '2026-11-06T16:00:00', 'end': '2026-11-06T17:00:00',
            'location': '9 Field Rd', 'calendar_ids': ['ada@cal'],
            'source_event_ids': [f'ada@cal::{eid}'], 'ignored': ignored,
            'app_config': {'is_ignored': True} if ignored else {}}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1400, 'height': 1000})
            token = storage.create_member_token('mum')
            page.add_init_script(f'localStorage.setItem("chauffeur_admin_token", {token!r})')

            # --- The Subscribe form ------------------------------------
            page.goto(served.url('config'), wait_until='networkidle')
            page.wait_for_timeout(600)
            page.get_by_role('button', name='People').first.click()
            page.wait_for_timeout(300)
            page.locator('button:has-text("Identity")').nth(1).click()
            page.wait_for_timeout(400)

            include = page.get_by_label('Include in the driving schedule', exact=True) \
                .locator('visible=true')
            check(include.count() == 1, 'the Subscribe form has no driving switch')
            check(include.is_checked(), 'the driving switch must start ticked')
            include.uncheck()
            page.get_by_placeholder('https://... .ics or webcal://...').locator('visible=true') \
                .fill('webcal://league.example/team.ics')
            page.locator('button:visible', has_text='Subscribe').first.click()
            page.wait_for_timeout(900)
            # The league feed names several teams: the picker stops the
            # create; the switch must survive it.
            page.locator(f'input[type="checkbox"][value="{SURGE}"]:visible').check()
            page.locator('button:visible', has_text='Subscribe').first.click()
            page.wait_for_timeout(1500)
            feeds = storage.get_ics_feeds()
            check(len(feeds) == 1, f'expected one feed: {feeds}')
            check(feeds[0].get('in_driving_schedule') is False,
                  f'the unticked switch did not ride the create: {feeds[0].get("in_driving_schedule")!r}')
            page.evaluate('closeGlobalAlert()')
            page.wait_for_timeout(500)

            # --- The feed row ------------------------------------------
            check(page.locator('p:visible', has_text=OFF_TEXT).count() == 1,
                  f'a switched-off feed row does not say "{OFF_TEXT}"')
            row_box = page.get_by_label('In the driving schedule', exact=True).locator('visible=true')
            check(row_box.count() == 1, 'the feed row has no driving switch')
            check(not row_box.is_checked(), 'the row switch disagrees with the stored feed')
            if OUT:
                os.makedirs(OUT, exist_ok=True)
                page.locator('div:visible', has_text='Subscribed ICS Feeds').last \
                    .screenshot(path=os.path.join(OUT, 'feed-row-off.png'))
            row_box.check()
            page.wait_for_timeout(1200)
            check(storage.get_ics_feeds()[0].get('in_driving_schedule') is True,
                  'ticking the row switch did not save through the PUT')
            check(page.locator('p:visible', has_text=OFF_TEXT).count() == 0,
                  'the row still says it is never driven after switching on')

            # --- Undo Ignore on the calendar ---------------------------
            page.goto(served.url('calendar'), wait_until='networkidle')
            page.wait_for_timeout(800)
            page.evaluate('''(evs) => {
                window._schedData = Object.assign({}, window._schedData || {},
                    {events: evs, passengers: [], drivers: [], calendar_metadata: {}});
            }''', [_event('gign', 'Rec swim', True), _event('gdrive', 'Vs Storm', False)])

            page.evaluate("openCalConfigModal('ada@cal::gdrive')")
            page.wait_for_timeout(400)
            btn = page.locator('#cal-ignore-btn')
            check(btn.inner_text().strip() == 'Ignore Event',
                  f'a driven event must offer Ignore Event, got {btn.inner_text()!r}')
            page.evaluate('closeCalConfigModal()')

            page.evaluate("openCalConfigModal('ada@cal::gign')")
            page.wait_for_timeout(400)
            check(btn.inner_text().strip() == 'Undo Ignore',
                  f'an ignored event must offer Undo Ignore, got {btn.inner_text()!r}')
            if OUT:
                page.screenshot(path=os.path.join(OUT, 'calendar-undo-ignore.png'))
            btn.click()
            page.wait_for_timeout(1200)
            conf = storage.get_event_config('gign')
            check(conf is not None and conf.get('is_ignored') is False,
                  f'Undo Ignore did not save is_ignored False: {conf}')
            check(not handle.errors, f'page errors: {handle.errors}')
        print('ok  the feed driving switch and Undo Ignore work in a browser')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
