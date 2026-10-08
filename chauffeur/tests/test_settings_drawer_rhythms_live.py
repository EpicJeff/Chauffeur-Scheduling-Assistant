"""The Chores drawer, actually clicked (settings-drawer arc, task 7).

Pet XP, the reward store and status tiers are the Chores drawer: a gear,
three chips, a save that reports, a rewards-off line that opens it.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_rhythms_live.py
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
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'kid', 'name': 'Kit', 'role': 'child', 'color_code': '#22c55e'})
    storage.patch_settings({'rewards_enabled': True})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            C = '[data-settings-for~="chores"]'
            page.goto(served.url('chores'), wait_until='networkidle')
            check(not page.locator('#petxp').is_visible(), 'pet XP still sits in the work flow')
            _shot(page, 'chores-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(C + '[data-open]')
            check(page.locator(C + ' [data-settings-chip]').count() == 3, 'Chores drawer has no three chips')
            _shot(page, 'chores-open-desktop')
            before = storage.get_settings()
            page.uncheck(C + ' input[x-model="features.rewards_enabled"]')
            page.wait_for_selector(C + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'rewards_enabled'}, 'the rewards switch changed more')
            page.click(C + ' [aria-label="Close settings"]')
            page.wait_for_selector('[data-settings-off]', state='visible')
            page.click('[data-settings-off] button')
            page.wait_for_selector(C + '[data-open]')
            page.wait_for_timeout(400)
            top = page.evaluate("() => document.getElementById('rewards').getBoundingClientRect().top")
            check(0 <= top < 260, f'Turn on did not land on #rewards: {top}')
            page.check(C + ' input[x-model="features.rewards_enabled"]')
            page.click(C + ' [aria-label="Close settings"]')
            page.goto(served.url('chores?kiosk=true'), wait_until='domcontentloaded')
            check(page.query_selector('[data-settings-for]') is None, 'the chores kiosk drew a drawer')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('chores'), wait_until='networkidle')
            _shot(page, 'chores-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(C + '[data-open]')
            _shot(page, 'chores-open-phone')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_rhythms_live OK')


if __name__ == '__main__':
    main()
