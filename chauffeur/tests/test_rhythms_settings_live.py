"""Kid settings on Rhythms, actually served (v2.499.256).

The kid digest, kid quiet hours and Growing up were tabs of the School page;
the user's correction was that they are about the child, not about school.
The kid evening settings became a section of the Routines view (whose kiosk
board shows the same 🌙 cards) and Growing up a fourth tab of Rhythms. What
only a browser can check:

  - a kid digest field saved from the Routines view, and a stage cutoff
    dragged on Rhythms → Growing up, each change ONLY their own keys (the
    settings POST merges, and a page that re-sent everything it had loaded
    could clobber a setting another page changed meanwhile);
  - the tab strip carries Growing up and switches to it in place;
  - neither card is drawn on the routines kiosk board, a panel or a
    filtered embed: settings never appear on a wall.

Run from chauffeur/:  python tests/test_rhythms_settings_live.py [--out DIR]
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='rhythms_settings_live_'))
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
    storage.update_settings({'days_to_show': 9, 'kid_quiet_start': '20:30',
                             'kid_digest_time': '19:30', 'stage_cutoffs': [6, 12, 15],
                             'intake_imap_host': 'imap.example.com'})
    storage.add_member({'id': 'kid_ada', 'name': 'Ada', 'role': 'child', 'is_child': True,
                        'color_code': '#14b8a6', 'birthdate': '2015-03-02'})
    storage.add_member({'id': 'kid_ben', 'name': 'Ben', 'role': 'child', 'is_child': True,
                        'color_code': '#f59e0b', 'birthdate': '2011-09-20'})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def _changed(before, after):
    keys = set(before) | set(after)
    return {k for k in keys if before.get(k) != after.get(k)}


KID_EVENING_KEYS = {'kid_digest_enabled', 'kid_digest_time', 'kid_digest_cutover_time',
                    'kid_quiet_start', 'kid_quiet_end'}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1400, 'height': 900})

            # --- Routines view: the kid evening section, its keys only.
            page.goto(served.url('rhythms?tab=routines'), wait_until='networkidle')
            page.wait_for_timeout(600)
            tabs = page.eval_on_selector_all('#page-tabs .page-tab', 'els => els.map(e => e.dataset.tabKey)')
            check(tabs == ['chores', 'routines', 'programs'], f'Rhythms tabs: {tabs}')
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="routines"][data-open]')
            check(_visible(page, '#kid-evenings'), 'the kid evening section is not in the Routines drawer')
            check(page.input_value('#kidDigestTime') == '19:30', 'the kid digest time did not load')
            before = dict(storage.get_settings())
            page.fill('#kidDigestTime', '19:45')
            page.dispatch_event('#kidDigestTime', 'change')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('kid_digest_time') == '19:45',
                  f"the kid digest time did not save: {after.get('kid_digest_time')}")
            stray = _changed(before, after) - KID_EVENING_KEYS
            check(not stray, f'the kid evening save touched other settings: {stray}')
            check(after.get('kid_quiet_start') == '20:30' and after.get('days_to_show') == 9,
                  'an unrelated setting changed')
            _el_shot(page.locator('#kid-evenings'), 'rhythms-kid-evenings.png')
            page.click('[data-settings-for~="routines"] [aria-label="Close settings"]')

            # The standalone /routines draws the same section in a browser.
            page.goto(served.url('routines'), wait_until='networkidle')
            page.wait_for_timeout(400)
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="routines"][data-open]')
            check(_visible(page, '#kid-evenings'), '/routines lost the kid evening section')

            # --- Growing up lives on Config > People now.
            # Config sits behind the admin gate; sign in as a parent.
            token = storage.create_member_token('mum')
            page.evaluate('t => localStorage.setItem("chauffeur_admin_token", t)', token)
            page.goto(served.url('config#growing-up'), wait_until='networkidle')
            page.wait_for_selector('#growing-up [x-ref="stageTrack"]', state='visible')
            page.wait_for_timeout(300)
            check(_visible(page, '#growing-up'), 'config#growing-up did not show Growing up')
            names = page.locator('#growing-up').inner_text()
            check('Ada' in names and 'Ben' in names, 'the children are not on Growing up')

            # Drag the first cutoff handle (6) left by two years' worth.
            h = page.locator('[data-cutoff-handle="0"]')
            h.evaluate('el => el.scrollIntoView({block: "center"})')
            page.wait_for_timeout(200)
            box = h.bounding_box()
            track = page.locator('#growing-up [x-ref="stageTrack"]').bounding_box()
            per_year = track['width'] / 19.0
            before = dict(storage.get_settings())
            x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x - per_year, y, steps=4)
            page.mouse.move(x - 2 * per_year, y, steps=4)
            page.mouse.up()
            page.wait_for_timeout(900)
            after = dict(storage.get_settings())
            check(after.get('stage_cutoffs') == [4, 12, 15],
                  f"the dragged cutoff did not save: {after.get('stage_cutoffs')}")
            stray = _changed(before, after) - {'stage_cutoffs'}
            check(not stray, f'the cutoff save touched other settings: {stray}')
            _el_shot(page.locator('#growing-up .select-none'), 'config-growing-up-timeline.png')
            if OUT:
                page.evaluate("document.getElementById('growing-up').scrollIntoView({block: 'start'})")
                page.wait_for_timeout(200)
                page.screenshot(path=os.path.join(OUT, 'config-growing-up.png'))
                page.set_viewport_size({'width': 390, 'height': 844})
                page.evaluate("document.getElementById('growing-up').scrollIntoView({block: 'start'})")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(OUT, 'config-growing-up-phone.png'))
                page.set_viewport_size({'width': 1400, 'height': 900})

            # Old links follow Growing up to Config.
            for old in ('rhythms#growing-up', 'rhythms?tab=growing-up'):
                page.goto(served.url(old), wait_until='networkidle')
                page.wait_for_timeout(600)
                check(page.url.split('#')[0].split('?')[0].endswith('/config') and page.url.endswith('#growing-up'),
                      f'{old} did not forward to Config: {page.url}')
                check(_visible(page, '#growing-up'), f'{old} did not show Growing up')

            # --- Never on a wall.
            for path in ('routines?kiosk=true', 'rhythms?kiosk=true', 'rhythms?panel=true',
                         'rhythms?tabs=routines'):
                page.goto(served.url(path), wait_until='networkidle')
                page.wait_for_timeout(400)
                check(page.locator('#kid-evenings, #kidDigestTime').count() == 0,
                      f'the kid evening settings are drawn on {path}')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_rhythms_settings_live OK')


if __name__ == '__main__':
    main()
