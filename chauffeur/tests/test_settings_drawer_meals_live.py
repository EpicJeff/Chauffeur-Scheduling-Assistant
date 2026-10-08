"""The Meals drawer, actually clicked (settings-drawer arc, task 6).

Meals' How this works block is the Meals drawer: no buttons, a gear, eight
chips, a save that reports, a deep link that opens it at a section.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_meals_live.py
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
    storage.update_settings({'kitchen_ovens': 1})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            D = '[data-settings-for~="meals"]'
            page.goto(served.url('meals'), wait_until='networkidle')
            check(page.locator('button:has-text("How this works")').count() == 0, 'the How this works buttons survived')
            check(_visible(page, '#page-settings-gear'), 'Meals shows no gear')
            _shot(page, 'meals-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(D + '[data-open]')
            check(page.locator(D + ' [data-settings-chip]').count() == 8, 'Meals drawer chips are not the eight sections')
            _shot(page, 'meals-open-desktop')
            before = storage.get_settings()
            ovens = D + ' input[x-model\.number="kitchen.ovens"]'
            page.fill(ovens, '2')
            page.dispatch_event(ovens, 'change')
            page.wait_for_selector(D + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) <= {'kitchen_ovens', 'kitchen_burners', 'kitchen_cooks'},
                  'saving the kitchen changed other settings')
            check(storage.get_settings().get('kitchen_ovens') == 2, 'ovens did not save')
            page.reload(wait_until='networkidle')
            page.goto(served.url('meals#planning'), wait_until='networkidle')
            page.wait_for_selector(D + '[data-open]')
            page.wait_for_timeout(400)
            top = page.evaluate("() => document.getElementById('planning').getBoundingClientRect().top")
            check(0 <= top < 260, f'meals#planning is not in view: {top}')
            page.click(D + ' [aria-label="Close settings"]')

            # Find a setting links straight into a section (page carries ?tab=).
            page.goto(served.url('settings'), wait_until='networkidle')
            hrefs = page.evaluate("() => [...document.querySelectorAll('a')].map(a => a.getAttribute('href'))")
            check(any(h and h.endswith('meals?tab=meals#planning') for h in hrefs),
                  'Find a setting has no meals?tab=meals#planning link')
            page.goto(served.url('meals?tab=meals#planning'), wait_until='networkidle')
            page.wait_for_selector(D + '[data-open]')
            page.wait_for_timeout(400)
            top = page.evaluate("() => document.getElementById('planning').getBoundingClientRect().top")
            check(0 <= top < 260, f'meals?tab=meals#planning is not in view: {top}')
            # The rules loaded because the drawer opened (not "No rules yet").
            check(not _visible(page, D + ' [x-show="!rules.length && !rulesLoaded && !rulesError"]'),
                  'the rules never loaded when the drawer opened from a link')
            page.goto(served.url('meals#how'), wait_until='networkidle')
            page.wait_for_selector(D + '[data-open]')
            page.click(D + ' [aria-label="Close settings"]')

            page.click('#page-tabs [data-tab-key="groceries"]')
            page.wait_for_timeout(200)
            check(not _visible(page, '#page-settings-gear'), 'Groceries shows a gear')
            page.goto(served.url('lists'), wait_until='networkidle')
            check(not _visible(page, '#page-settings-gear'), 'Lists shows a gear')
            page.goto(served.url('meals?kiosk=true'), wait_until='domcontentloaded')
            check(page.query_selector('[data-settings-for]') is None, 'the meals kiosk drew a drawer')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('meals'), wait_until='networkidle')
            _shot(page, 'meals-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(D + '[data-open]')
            _shot(page, 'meals-open-phone')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_meals_live OK')


if __name__ == '__main__':
    main()
