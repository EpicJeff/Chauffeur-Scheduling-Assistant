"""Schedule-group settings drawers, actually clicked (settings-drawer arc, task 11).

Calendar: the status day TYPES live in the Calendar drawer; setting and
clearing days and the Upcoming list stay on the page, with an honest empty
state (and a way to add a type) when no types exist. Occasions: the gift lead
time lives in the Occasions drawer.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_schedule_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_schedule_live_'))
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
    storage.add_member({'id': 'kid_ada', 'name': 'Ada', 'role': 'child', 'is_child': True,
                        'color_code': '#14b8a6'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            K = '[data-settings-for~="calendar"]'
            page.goto(served.url('calendar'), wait_until='networkidle')
            check(page.locator('[data-status-days-link]').count() == 0, 'the Status days header link survived')
            page.wait_for_selector('[data-status-types-empty]', state='visible')
            _shot(page, 'calendar-closed-desktop')
            page.click('[data-status-types-empty] button')
            page.wait_for_selector(K + '[data-open]')
            page.click(K + ' [data-status-add]')
            _shot(page, 'calendar-open-desktop')
            page.fill(K + ' [data-status-name]', 'Snow day')
            page.click(K + ' [data-status-submit]')
            page.wait_for_selector(K + ' [data-status-row]:has-text("Snow day")')
            check(not page.locator('#status-days > div:not([data-settings-for]) [data-status-row]').count(),
                  'day types still draw in the work flow')
            page.click(K + ' [aria-label="Close settings"]')
            page.wait_for_selector('#status-days [data-status-set]', state='visible')
            check(not _visible(page, '[data-status-types-empty]'), 'the empty state outlived the type')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('calendar'), wait_until='networkidle')
            page.wait_for_selector('#status-days [data-status-set]', state='visible')
            _shot(page, 'calendar-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(K + '[data-open]')
            _shot(page, 'calendar-open-phone')

            page.set_viewport_size({'width': 1300, 'height': 900})
            O = '[data-settings-for~="occasions"]'
            page.goto(served.url('occasions'), wait_until='networkidle')
            check(not page.locator('#gifts').is_visible(), 'gift lead time still sits in the work flow')
            _shot(page, 'occasions-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(O + '[data-open]')
            before = storage.get_settings()
            page.fill(O + ' input[x-model\\.number="giftLeadDays"]', '5')
            page.dispatch_event(O + ' input[x-model\\.number="giftLeadDays"]', 'change')
            page.wait_for_selector(O + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'gift_lead_days'},
                  'gift lead saved more than itself')
            _shot(page, 'occasions-open-desktop')
            page.click(O + ' [aria-label="Close settings"]')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('occasions'), wait_until='networkidle')
            _shot(page, 'occasions-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(O + '[data-open]')
            _shot(page, 'occasions-open-phone')

            page.set_viewport_size({'width': 1300, 'height': 900})
            E = '[data-settings-for~="errands"]'
            for start in ('errands', 'errands?tab=tasks'):
                page.goto(served.url(start), wait_until='networkidle')
                _shot(page, 'errands-closed-' + start.replace('?tab=', '-'))
                page.click('#page-settings-gear')
                page.wait_for_selector(E + '[data-open]')
                page.wait_for_selector('#errand-rules [x-model="newErrandRule.title"]', state='visible')
                check(_visible(page, '#errand-rules'), f'{start}: the rules are not in the drawer')
                _shot(page, 'errands-open-' + start.replace('?tab=', '-'))
                page.click(E + ' [aria-label="Close settings"]')
            page.goto(served.url('errands?tab=rules'), wait_until='networkidle')
            page.wait_for_selector(E + '[data-open]')
            check('tab=rules' not in page.url, f'the retired tab survived: {page.url}')
            check(page.locator('#page-tabs [data-tab-key="rules"]').count() == 0, 'the Rules tab is still on the bar')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('errands'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(E + '[data-open]')
            page.wait_for_selector('#errand-rules [x-model="newErrandRule.title"]', state='visible')
            _shot(page, 'errands-open-phone')
            check(page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"),
                  'the phone page scrolls sideways')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_schedule_live OK')


if __name__ == '__main__':
    main()
