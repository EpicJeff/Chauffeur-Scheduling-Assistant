"""The settings drawer, actually clicked (settings-drawer arc).

A drawer is a fixed overlay inside a page's Alpine island; whether it covers
the viewport, opens from the gear, saves, reports and closes is only true in
a layout engine. One file for the shell and the slice-1 pilots; later
slices add their own files.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')
DRAWER = '[data-settings-for~="threads"]'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _visible(page, sel):
    return page.evaluate(
        "(s) => { const el = document.querySelector(s);"
        " return !!el && getComputedStyle(el).display !== 'none'; }", sel)


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': 'test-key', 'thread_stall_days': 7})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            check(_visible(page, '#page-settings-gear'), 'Threads shows no gear')
            check(not _visible(page, DRAWER), 'the drawer starts open')
            _shot(page, 'threads-closed-desktop')

            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            box = page.evaluate(
                "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
                " return [r.left, r.top, r.width, r.height, innerWidth, innerHeight]; }", DRAWER)
            check(box[0] == 0 and box[1] == 0 and box[2] == box[4] and box[3] == box[5],
                  f'the drawer does not cover the viewport: {box}')
            _shot(page, 'threads-open-desktop')

            before = storage.get_settings()
            with page.expect_request(lambda r: r.url.endswith('/api/settings') and r.method == 'POST'):
                page.fill('#threadStallDays', '11')
                page.dispatch_event('#threadStallDays', 'change')
            page.wait_for_selector(DRAWER + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'thread_stall_days'},
                  'saving stall days changed other settings')

            page.keyboard.press('Escape')
            page.wait_for_timeout(150)
            check(not _visible(page, DRAWER), 'Escape did not close the drawer')
            page.reload(wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            check(page.input_value('#threadStallDays') == '11', 'the stall days did not stick')

            # A failed save says so, in the header, in the server's words.
            page.route('**/api/settings', lambda route: route.fulfill(
                status=500, content_type='application/json', body='{"detail": "The house said no"}')
                if route.request.method == 'POST' else route.continue_())
            page.fill('#threadStallDays', '12')
            page.dispatch_event('#threadStallDays', 'change')
            page.wait_for_selector(DRAWER + ' [data-settings-status]:has-text("The house said no")')
            page.unroute('**/api/settings')
            page.click(DRAWER + ' [aria-label="Close settings"]')

            # Deep link from another tab: the bar switches, the drawer opens.
            page.goto(served.url('work?tab=mind#threads-settings'), wait_until='networkidle')
            page.wait_for_selector(DRAWER + '[data-open]')
            check(_visible(page, '[data-page-tab="threads"]'), 'the deep link did not switch to Threads')
            check('tab=threads' in page.url, f'the bar forgot the tab: {page.url}')
            page.click(DRAWER + ' [aria-label="Close settings"]')
            check('#' not in page.url, f'closing left the hash: {page.url}')
            page.reload(wait_until='networkidle')
            check(not _visible(page, DRAWER), 'a reload after closing reopened the drawer')

            # Settings pages carry the bar, never a gear.
            for path in ('config', 'settings'):
                page.goto(served.url(path), wait_until='domcontentloaded')
                page.wait_for_timeout(300)
                check(_visible(page, '#page-tabs'), f'/{path} has no page bar')
                check(not _visible(page, '#page-settings-gear'), f'/{path} shows a gear')

            # Phone: the gear stays on screen beside four tabs; the sheet is 88vh.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            gear = page.evaluate("() => document.getElementById('page-settings-gear').getBoundingClientRect().right")
            check(gear <= 390, f'the gear is off screen on a phone: right={gear}')
            _shot(page, 'threads-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            sheet = page.evaluate("(s) => { const r = document.querySelector(s + ' [role=dialog]').getBoundingClientRect(); return [r.top, r.bottom, innerHeight]; }", DRAWER)
            check(abs(sheet[1] - sheet[2]) < 2 and abs((sheet[1] - sheet[0]) - 0.88 * sheet[2]) < 4,
                  f'the phone sheet is not an 88vh bottom sheet: {sheet}')
            _shot(page, 'threads-open-phone')

            # Programs: a deep link from another tab lands on the section.
            page.set_viewport_size({'width': 1300, 'height': 900})
            P = '[data-settings-for~="programs"]'
            page.goto(served.url('rhythms?tab=routines#lessons'), wait_until='networkidle')
            page.wait_for_selector(P + '[data-open]')
            check(_visible(page, '[data-page-tab="programs"]'), 'rhythms#lessons did not open Programs')
            # The sheet is short enough to need no scroll at 900px, so "in view"
            # is the claim (a taller page scrolls it to the top).
            top = page.evaluate("() => { const r = document.getElementById('lessons').getBoundingClientRect(); return r.top >= 60 && r.bottom <= innerHeight ? r.top : -1; }")
            check(top >= 0, f'#lessons is not in view in the drawer: {top}')
            check(page.locator(P + ' [data-settings-chip]').count() == 3, 'Programs has no jump chips')
            _shot(page, 'programs-open-desktop')

            # Escape belongs to a global prompt open above the drawer.
            page.evaluate("() => { window.promptConfirm('Write lessons now?', 'Test'); }")
            page.wait_for_selector('#cc-confirm-modal:not(.hidden)')
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
            check(_visible(page, P), 'Escape on a prompt closed the drawer under it')
            if _visible(page, '#cc-confirm-modal'):
                page.click('#cc-confirm-modal button:has-text("Cancel")')

            # A switch saves, reports, sticks.
            before = storage.get_settings()
            page.click(P + ' input[x-model="s.programs_enabled"]')
            page.wait_for_selector(P + ' [data-settings-status]:has-text("Saved")')
            check('programs_enabled' in _changed(before, storage.get_settings()),
                  'the Programs switch did not save programs_enabled')
            page.click(P + ' [aria-label="Close settings"]')

            # Walls: no bar, no gear, no drawer.
            for q in ('work?kiosk=true', 'work?panel=true', 'work?tabs=threads'):
                page.goto(served.url(q), wait_until='domcontentloaded')
                check(page.query_selector('[data-settings-for]') is None, f'{q} drew a drawer')
                check(page.query_selector('#page-settings-gear') is None, f'{q} drew the gear')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_live OK')


if __name__ == '__main__':
    main()
