"""The errand habits card, actually clicked (2026-11-02).

Spec: docs/superpowers/specs/2026-11-02-errand-habits-design.md §5. A parent
opens the Errands drawer at the card, sees one card per driver, adds Jeff's
hours and picks a day: the whole card goes to the server and the summary line
under the card says it back. Screenshot to probe_shots/errand_habits_drawer.png.
Skips without playwright, like every live test.

Run from chauffeur/:  python tests/test_errand_habits_live.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check  # noqa: E402  (isolates CHAUFFEUR_DATA_DIR)
from live_app import live_app  # noqa: E402
from services import storage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, 'probe_shots')
DRAWER = '[data-settings-for~="errands"]'
TOKENS = {}


def seed():
    for t in ('drivers_table', 'members_table', 'settings_table'):
        getattr(storage, t).truncate()
    storage.settings_table.insert({'calendar_ids': [], 'days_to_build': 1, 'home_location': '1 Home St',
                                   'errand_dedicated_trip_mins': 25})
    storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#4ade80', 'group': 'primary', 'priority_index': 1,
                        'calendar_ids': [], 'home_location': '1 Home St'})
    storage.add_driver({'id': 'd2', 'name': 'Lorena', 'color_code': '#60a5fa', 'group': 'primary', 'priority_index': 2,
                        'calendar_ids': [], 'home_location': '1 Home St'})
    storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent', 'driver_id': 'd1', 'email': 'jeff@example.com'})
    storage.set_member_password('mj', 'pw-for-the-test')
    TOKENS['parent'] = storage.create_member_token('mj')
    storage.set_errand_habits('d2', {'separate_trip_mins': 40, 'together_kinds': ['groceries', 'pharmacy']})


def scenario_live():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 1000})
            page.goto(served.url('api/account/setup'))
            page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                          {'chauffeur_admin_token': TOKENS['parent'], 'chauffeur_admin_token_for': 'mj'})
            page.goto(served.url('errands?tab=errands#errand-habits'), wait_until='domcontentloaded')
            page.wait_for_selector(DRAWER + '[data-open]')
            page.wait_for_selector('#errand-habits fieldset')
            names = page.eval_on_selector_all('#errand-habits fieldset h3', 'els => els.map(e => e.textContent)')
            check(names == ['Jeff', 'Lorena'], f"one card per active driver, in name order: {names}")
            lines = page.eval_on_selector_all('#errand-habits fieldset > p:last-child', 'els => els.map(e => e.textContent)')
            check(lines[0] == 'No errand habits set' and 'groceries and pharmacy runs each in one outing' in lines[1], f"{lines}")
            top = page.evaluate("() => document.getElementById('errand-habits').getBoundingClientRect().top")
            check(0 <= top < 400, f"the deep link lands on the card: {top}")
            os.makedirs(SHOTS, exist_ok=True)
            page.screenshot(path=os.path.join(SHOTS, 'errand_habits_drawer.png'))
            jeff = page.locator('#errand-habits fieldset').first
            jeff.get_by_role('button', name='Add hours').click()
            check(storage.get_driver_errand_habits('d1')['hours'] == [], "a row with no day is a draft, nothing saved yet")
            with page.expect_request(lambda r: r.url.endswith('/api/errands/habits/d1') and r.method == 'PUT'):
                jeff.get_by_role('button', name='Mon', exact=True).click()
            page.wait_for_function("() => document.querySelector('#errand-habits fieldset > p:last-child').textContent.includes('runs errands')")
            saved = storage.get_driver_errand_habits('d1')
            check(saved['hours'] == [{'days': [0], 'start': '13:00', 'end': '15:00'}] and saved['hours_strict'] is True,
                  f"the whole card reached the server: {saved}")
            line = jeff.locator('> p:last-child').text_content()
            check(line == 'Jeff runs errands 13:00-15:00 on Mondays (strict)', f"the summary says it back: {line}")
            check(page.locator(DRAWER + ' [data-settings-status]').text_content().strip().startswith('Saved'),
                  "the drawer's status says Saved")
            page.screenshot(path=os.path.join(SHOTS, 'errand_habits_drawer_saved.png'))
        errs = [e for e in handle.errors if 'favicon' not in str(e)]
        check(not errs, f"no page errors: {errs}")
    finally:
        served.stop()


if __name__ == '__main__':
    scenario_live()
    print('  ok  scenario_live')
    print('errand-habits live scenarios passed')
