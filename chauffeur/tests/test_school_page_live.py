"""The School page, actually served (v2.499.250).

School setup lived in three places — Config's General tab (the school
calendar, the kid digest), each child's member card (hours, bus, feeds) and
People → Growing up. It moved to /school, one tab per concern. What only a
browser can check:

  - the page draws, its tab strip switches the four blocks, and a deep link
    to an anchor in a closed tab (the settings index's `school#evenings`)
    opens that tab;
  - a change on a tab saves ONLY that tab's keys: the settings POST merges,
    and a page that sent everything it had loaded could still clobber a
    setting another page changed meanwhile.

Run from chauffeur/:  python tests/test_school_page_live.py [--out DIR]
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='school_page_live_'))
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


def _shot(page, name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        page.screenshot(path=os.path.join(OUT, name), full_page=True)


def _el_shot(locator, name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        locator.screenshot(path=os.path.join(OUT, name))


def seed():
    storage.update_settings({'days_to_show': 9, 'kid_quiet_start': '20:30',
                             'school_closed_keywords': 'no school, holiday',
                             'intake_imap_host': 'imap.example.com'})
    storage.add_member({'id': 'kid_ada', 'name': 'Ada', 'role': 'child', 'is_child': True,
                        'color_code': '#14b8a6', 'birthdate': '2015-03-02',
                        'school_hours_start': '08:00', 'school_hours_end': '15:00',
                        'quiet_start': '21:00', 'notify_lanes': 'urgent'})
    storage.ensure_school_class('kid_ada', 'SCI.7.2', 'SCI.7.2')
    # A school feed is a URL the server reads; served in-process, the read is
    # stubbed so the add path runs without the network.
    from services import ics_sync
    ics_sync.fetch_and_parse = lambda url: {'name': 'Ada Canvas', 'items': {'a': {}, 'b': {}}}
    ics_sync.sync_feed = lambda feed: {}
    storage.add_member({'id': 'kid_ben', 'name': 'Ben', 'role': 'child', 'is_child': True,
                        'color_code': '#f59e0b', 'birthdate': '2011-09-20'})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def _changed(before, after):
    keys = set(before) | set(after)
    return {k for k in keys if before.get(k) != after.get(k)}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser()
        with handle as page:
            page.set_viewport_size({'width': 1400, 'height': 900})
            page.goto(served.url('school'), wait_until='networkidle')
            page.wait_for_timeout(600)

            check(_visible(page, '#page-tabs'), 'the School page has no tab strip')
            tabs = page.eval_on_selector_all('#page-tabs .page-tab', 'els => els.map(e => e.dataset.tabKey)')
            check(tabs == ['children', 'calendar', 'evenings', 'growing'], f'tabs: {tabs}')
            check(_visible(page, '[data-page-tab="children"]'), 'Children is not the default view')
            check(not _visible(page, '[data-page-tab="calendar"]'), 'Calendar shows beside Children')
            # Children: one card per child, saving only the school fields.
            ada = page.locator('[data-child="kid_ada"]')
            check(ada.count() == 1 and page.locator('[data-child="kid_ben"]').count() == 1,
                  'each child does not get a card')
            check(ada.locator('[data-field="school_hours_end"]').input_value() == '15:00',
                  "Ada's school hours did not load")
            before = dict(storage.get_member('kid_ada'))
            ada.locator('[data-field="school_hours_end"]').fill('15:20')
            ada.locator('[data-field="bus_am_stop_time"]').fill('07:12')
            ada.locator('[data-field="school_end_push"]').uncheck()
            ada.locator('[data-save-child]').click()
            page.wait_for_timeout(800)
            after = dict(storage.get_member('kid_ada'))
            check(after.get('school_hours_end') == '15:20', f"hours not saved: {after.get('school_hours_end')}")
            check(after.get('bus_am_stop_time') == '07:12', f"bus stop not saved: {after.get('bus_am_stop_time')}")
            check(after.get('school_end_push') is False, 'the dismissal push switch did not save')
            for k in ('name', 'color_code', 'quiet_start', 'notify_lanes', 'birthdate', 'role'):
                check(after.get(k) == before.get(k), f'the School save changed {k}')

            # Diagnose bus against a child with no bus: readable sentences.
            ben = page.locator('[data-child="kid_ben"]')
            ben.locator('[data-diagnose]').click()
            page.wait_for_timeout(800)
            diag = ben.locator('[data-diagnosis]').inner_text()
            check('No AM stop time' in diag and 'not on the map' in diag,
                  f'the bus diagnosis did not read as text: {diag!r}')
            _el_shot(ben, 'school-child-ben-diagnosis.png')

            # A school task feed: added from the card, listed under the child.
            ada.locator('[data-feed-url]').fill('https://canvas.example.edu/feeds/calendars/user_abc.ics')
            ada.locator('[data-add-feed]').click()
            page.wait_for_timeout(1000)
            feeds = [f for f in storage.get_ics_feeds() if f.get('member_id') == 'kid_ada']
            check(len(feeds) == 1 and feeds[0].get('target_kind') == 'tasks',
                  f'the task feed was not added for Ada: {feeds}')
            alert = page.locator('#cc-alert-message').inner_text()
            check('Ada Canvas' in alert, f'the subscribe confirmation did not say what it found: {alert!r}')
            page.evaluate('closeGlobalAlert()')
            check(ada.locator('[data-feed]').count() == 1, 'the new feed is not listed on the card')

            # Classes: rename through the class API.
            ada.locator('[data-class-name]').fill('Science')
            ada.locator('[data-class-name]').dispatch_event('change')
            page.wait_for_timeout(800)
            cls = storage.get_school_classes('kid_ada')
            check(cls and cls[0].get('name') == 'Science', f'the class rename did not save: {cls}')
            _el_shot(ada, 'school-child-ada.png')
            _shot(page, 'school-children.png')

            # Evenings: one field changes, and nothing else does.
            page.click('#page-tabs [data-tab-key="evenings"]')
            page.wait_for_timeout(200)
            check(_visible(page, '#evenings'), 'clicking Evenings did not show it')
            before = dict(storage.get_settings())
            page.fill('#kidQuietStart', '21:15')
            page.dispatch_event('#kidQuietStart', 'change')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('kid_quiet_start') == '21:15', f"quiet start not saved: {after.get('kid_quiet_start')}")
            stray = _changed(before, after) - {'kid_quiet_start', 'kid_digest_enabled', 'kid_digest_time',
                                                'kid_digest_cutover_time', 'kid_quiet_end'}
            check(not stray, f'the Evenings save touched other settings: {stray}')
            check(after.get('days_to_show') == 9 and after.get('intake_imap_host') == 'imap.example.com',
                  'an unrelated setting changed')
            _shot(page, 'school-evenings.png')

            # Calendar: a new vocabulary word saves, again alone.
            page.click('#page-tabs [data-tab-key="calendar"]')
            page.wait_for_timeout(200)
            check(_visible(page, '#calendar'), 'clicking Calendar did not show it')
            shown = page.input_value('#kw-schoolHalfDayKeywords')
            check('early release' in shown, f'the half-day words do not show the defaults: {shown!r}')
            before = dict(storage.get_settings())
            page.fill('#kw-schoolHalfDayKeywords', 'early release, medio dia')
            page.dispatch_event('#kw-schoolHalfDayKeywords', 'change')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('school_half_day_keywords') == 'early release, medio dia',
                  f"half-day words not saved: {after.get('school_half_day_keywords')!r}")
            stray = {k for k in _changed(before, after) if not k.startswith('school_')}
            check(not stray, f'the Calendar save touched non-school settings: {stray}')
            check(after.get('school_closed_keywords') == 'no school, holiday',
                  'the closure words were rewritten by an unrelated edit')
            _shot(page, 'school-calendar.png')

            # A deep link to an anchor in a closed tab opens that tab.
            page.goto(served.url('school#growing-up'), wait_until='networkidle')
            page.wait_for_timeout(600)
            check(_visible(page, '#growing-up'), 'school#growing-up did not open Growing up')
            check(not _visible(page, '#children'), 'Children still shows on the Growing up link')
            names = page.locator('#growing-up').inner_text()
            check('Ada' in names and 'Ben' in names, 'the children are not on Growing up')
            _shot(page, 'school-growing.png')

            # Config keeps a pointer where each block used to be.
            page.goto(served.url('config'), wait_until='domcontentloaded')
            # (Config rewrites its own links to absolute paths.)
            check(page.locator('main a[href$="/school"], a[href$="/school"]:not(nav a)').count() >= 1,
                  'Config has no pointer to School')
            check(page.locator('a[href$="school?tab=growing"]').count() >= 1,
                  'Config has no pointer to Growing up')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_school_page_live OK')


if __name__ == '__main__':
    main()
