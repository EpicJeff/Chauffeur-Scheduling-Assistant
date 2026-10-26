"""The team picker on a feed subscription, actually served (v2.499.692).

What only a browser can check: pasting a league feed and tapping Subscribe
reads the feed first and, when it names more than one team, stops to ask
which; the chosen teams ride the create; an existing feed shows its teams
and the Teams button edits them through the PUT.

The feed and Google Calendar are stubbed in-process (uvicorn runs on a
thread), so no network and nothing touches data/.

Run from chauffeur/:  python tests/test_ics_team_filter_live.py [--out DIR]
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='ics_teams_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app

from services import ics_sync, storage
from test_ics_team_filter import FEED_TITLES, PURPLE, SURGE, WOMBATS, FakeGcal, build_ics

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'kid_ada', 'name': 'Ada', 'role': 'child', 'is_child': True,
                        'color_code': '#14b8a6', 'calendar_ids': ['ada@cal']})
    ics_sync.fetch_ics = lambda url: build_ics(FEED_TITLES)
    ics_sync.gcal = FakeGcal()


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1400, 'height': 1000})
            # Signed in as a parent before the first load (the admin gate), so
            # no request on the way in is refused and logged as a page error.
            token = storage.create_member_token('mum')
            page.add_init_script(f'localStorage.setItem("chauffeur_admin_token", {token!r})')
            page.goto(served.url('config'), wait_until='networkidle')
            page.wait_for_timeout(600)
            page.get_by_role('button', name='People').first.click()
            page.wait_for_timeout(300)
            # People are listed in seed order (Mum, then Ada): the second
            # Identity button is Ada's. Mum has no calendar, so her editor
            # would show no feed form at all.
            page.locator('button:has-text("Identity")').nth(1).click()
            page.wait_for_timeout(400)

            # Every person's editor is in the DOM; only the open one is visible.
            url_box = page.get_by_placeholder('https://... .ics or webcal://...').locator('visible=true')
            check(url_box.count() == 1, 'the feed form is not on the person editor')
            url_box.fill('webcal://league.example/team.ics')
            page.locator('button:visible', has_text='Subscribe').first.click()
            page.wait_for_timeout(900)
            boxes = page.locator('input[type="checkbox"][value]:visible')
            labels = sorted(boxes.evaluate_all('els => els.map(e => e.value)'))
            check(labels == sorted([PURPLE, SURGE, WOMBATS]),
                  f'the form did not stop to ask which teams: {labels}')
            check(not storage.get_ics_feeds(), 'the feed was subscribed before the teams were picked')
            if OUT:
                os.makedirs(OUT, exist_ok=True)
                picker = page.locator('div:visible', has_text='Keep events for these, then tap Subscribe').last
                page.evaluate('el => el.scrollIntoView({block: "center"})', picker.element_handle())
                page.wait_for_timeout(200)
                picker.locator('xpath=..').screenshot(path=os.path.join(OUT, 'feed-team-picker.png'))

            page.locator(f'input[type="checkbox"][value="{SURGE}"]:visible').check()
            page.locator(f'input[type="checkbox"][value="{WOMBATS}"]:visible').check()
            page.locator('button:visible', has_text='Subscribe').first.click()
            page.wait_for_timeout(1500)
            feeds = storage.get_ics_feeds()
            check(len(feeds) == 1 and feeds[0].get('teams') == [SURGE, WOMBATS],
                  f'the chosen teams did not ride the create: {feeds}')
            check(feeds[0].get('calendar_id') == 'ada@cal', feeds)
            titles = sorted(b['summary'] for b in ics_sync.gcal.events.values())
            check(titles == sorted(['Practice (Surge (G10w))', 'Vs  Storm (G10w) (Surge (G10w))',
                                    'Practice (Wombats (CO6w))', 'League picture day']),
                  f'the first sync created the wrong rows: {titles}')

            # The "Subscribed" alert sits over the page until it is closed.
            page.evaluate('closeGlobalAlert()')
            page.wait_for_timeout(500)
            # The row says its teams; Teams edits them.
            check(page.locator('p:visible', has_text=f'Only: {SURGE}, {WOMBATS}').count() == 1,
                  'the feed row does not say which teams it keeps')
            page.locator('button:visible', has_text='Teams').filter(has_text='Teams').first.click()
            page.wait_for_timeout(900)
            page.locator(f'input[type="checkbox"][value="{WOMBATS}"]:visible').last.uncheck()
            page.locator('button:visible', has_text='Save teams').click()
            page.wait_for_timeout(1500)
            page.evaluate('closeGlobalAlert()')
            feeds = storage.get_ics_feeds()
            check(feeds[0].get('teams') == [SURGE], f'the edit did not save: {feeds[0].get("teams")}')
            titles = sorted(b['summary'] for b in ics_sync.gcal.events.values())
            check('Practice (Wombats (CO6w))' not in titles,
                  f'narrowing the teams did not take the Wombats row off the calendar: {titles}')
            if OUT:
                page.locator('div:visible', has_text='Subscribed ICS Feeds').last                     .screenshot(path=os.path.join(OUT, 'feed-teams-saved.png'))
            check(not handle.errors, f'page errors: {handle.errors}')
        print('ok  the team picker subscribes, shows and edits the teams in a browser')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
