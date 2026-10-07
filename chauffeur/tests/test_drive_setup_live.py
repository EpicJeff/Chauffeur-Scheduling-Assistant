"""The Drive setup page, actually served (v2.499.253).

Everything that decides how drives get assigned lived on Config: the Rules &
Priorities tab, the solver switches and horizons, routing and traffic policy
and the parents' tomorrow digest. It moved to /drive_setup, a tab of the
Schedule group. What only a browser can check:

  - the page draws inside the Schedule tab strip, its section switcher shows
    one section at a time, and a deep link to an anchor in a closed section
    (the settings index's `drive_setup#traffic`) opens that section;
  - a change saves ONLY its own keys: the settings POST merges, and a page
    that sent everything it had loaded could still clobber a setting another
    page changed meanwhile;
  - a routing rule, a car, a protected-time commitment and an outside hand
    can each be added by hand from the page, and an errand rule from the
    Errands page's Rules tab (v2.499.255).

Run from chauffeur/:  python tests/test_drive_setup_live.py [--out DIR]
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='drive_setup_live_'))
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


TOKENS = {}


def seed():
    storage.update_settings({'days_to_show': 9, 'days_to_build': 5,
                             'load_balancing_enabled': False,
                             'routing_avoid_tolls': False,
                             'kid_quiet_start': '20:30',
                             'intake_imap_host': 'imap.example.com'})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent', 'color_code': '#f59e0b'})
    TOKENS['parent'] = storage.create_member_token('mum')
    storage.add_driver({'id': 'mum', 'name': 'Mum', 'color_code': '#6366f1', 'group': 'primary',
                        'priority_index': 1, 'calendar_ids': [], 'hashtags': []})
    storage.add_driver({'id': 'dad', 'name': 'Dad', 'color_code': '#f59e0b', 'group': 'primary',
                        'priority_index': 2, 'calendar_ids': [], 'hashtags': []})
    storage.add_rule({'driver_id': 'dad', 'constraint_type': 'required',
                      'keywords': ['Swim'], 'passenger_ids': [], 'days_of_week': []})
    storage.add_errand_rule({'title': 'Swim run', 'constraint_type': 'driver_assignment',
                             'keywords': ['swim'], 'is_enabled': True})


def _sign_in(page, served):
    """Drive setup carries the admin sign-in gate (as the Drives page does):
    a parent's admin session, the way test_ride_groups_live opens /dashboard_v2."""
    page.goto(served.url('api/account/setup'))
    page.evaluate('(t) => { localStorage.clear();'
                  ' localStorage.setItem("chauffeur_admin_token", t);'
                  ' localStorage.setItem("chauffeur_admin_token_for", "mum"); }',
                  TOKENS['parent'])


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
            _sign_in(page, served)
            page.goto(served.url('drive_setup'), wait_until='networkidle')
            page.wait_for_timeout(600)

            # It is a tab of the Schedule group, and the tab it is on is lit.
            check(_visible(page, '#page-tabs'), 'Drive setup has no Schedule tab strip')
            tabs = page.eval_on_selector_all('#page-tabs .page-tab', 'els => els.map(e => e.dataset.tabKey)')
            check(tabs == ['drives', 'calendar', 'moments', 'occasions', 'setup'], f'tabs: {tabs}')
            lit = page.eval_on_selector_all('#page-tabs .page-tab.bg-blue-600', 'els => els.map(e => e.dataset.tabKey)')
            check(lit == ['setup'], f'the lit tab is {lit}, not Drive setup')

            _shot(page, 'drive-setup-top.png')

            # Rules is the default section; the rule already written is listed.
            check(_visible(page, '#rules') and not _visible(page, '#solver'),
                  'Rules is not the only section showing')
            cards = '#routing-rules [x-data="{ expanded: false }"]'
            check(page.locator(cards).count() == 1 and 'Dad' in page.locator(cards).first.inner_text(),
                  'the existing rule is not listed')

            # A routing rule written by hand.
            form = page.locator('#routing-rule-form')
            form.locator('[x-model="newRule.driver_id"]').select_option('mum')
            form.locator('[x-model="newRuleKeywordInput"]').fill('Piano')
            page.locator('#routing-rules').get_by_role('button', name='Add Rule', exact=True).click()
            page.wait_for_timeout(900)
            rules = page.request.get(served.url('api/rules')).json()
            piano = [r for r in rules if 'Piano' in (r.get('keywords') or [])]
            check(len(piano) == 1 and piano[0]['driver_id'] == 'mum', f'the hand-written rule did not save: {rules}')
            check(page.locator(cards).count() == 2, 'the new rule is not listed')
            _shot(page, 'drive-setup-rules.png')

            # A rule switch saves alone.
            before = dict(storage.get_settings())
            page.locator('#routing-rules input[x-model="enableAiRules"]').uncheck(force=True)
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('enable_ai_rules') is False, 'the AI rules switch did not save')
            stray = _changed(before, after) - {'enable_standard_rules', 'enable_ai_rules',
                                                'enable_standard_priority_rules', 'enable_ai_priority_rules'}
            check(not stray, f'the rule switch touched other settings: {stray}')

            # Priority sub-tab.
            page.get_by_role('button', name='Priority Rules').click()
            page.wait_for_timeout(200)
            check(_visible(page, '#priority-rules') and not _visible(page, '#routing-rules'),
                  'the Priority Rules sub-tab did not switch')

            # Solver & horizons: one change, and nothing else moves.
            page.click('#drive-sections [data-section-tab="solver"]')
            page.wait_for_timeout(200)
            check(_visible(page, '#solver') and not _visible(page, '#rules'), 'clicking Solver did not show it')
            check(page.input_value('#daysToShow') == '9' and page.input_value('#daysToBuild') == '5',
                  'the horizons did not load')
            before = dict(storage.get_settings())
            page.locator('#loadBalancingEnabled').check(force=True)
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('load_balancing_enabled') is True, 'load balancing did not save')
            stray = _changed(before, after) - {'load_balancing_enabled', 'load_balancing_metric',
                                                'suggested_routes_enabled'}
            check(not stray, f'the solver save touched other settings: {stray}')
            check(after.get('days_to_show') == 9 and after.get('intake_imap_host') == 'imap.example.com'
                  and after.get('kid_quiet_start') == '20:30', 'an unrelated setting changed')

            before = dict(storage.get_settings())
            page.fill('#daysToBuild', '10')
            page.dispatch_event('#daysToBuild', 'change')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('days_to_build') == 10, f"days to solve not saved: {after.get('days_to_build')}")
            check(not (_changed(before, after) - {'days_to_show', 'days_to_build'}),
                  f'the horizon save touched other settings: {_changed(before, after)}')

            before = dict(storage.get_settings())
            page.locator('#routingAvoidTolls').check(force=True)
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('routing_avoid_tolls') is True, 'avoid tolls did not save')
            check(not (_changed(before, after) - {'traffic_live_enabled', 'traffic_morning_hour',
                                                  'routing_avoid_tolls'}),
                  f'the traffic save touched other settings: {_changed(before, after)}')

            before = dict(storage.get_settings())
            page.fill('#tomorrowDigestTime', '21:15')
            page.dispatch_event('#tomorrowDigestTime', 'change')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('tomorrow_digest_time') == '21:15', 'the digest time did not save')
            check(not (_changed(before, after) - {'tomorrow_digest_enabled', 'tomorrow_digest_time'}),
                  f'the digest save touched other settings: {_changed(before, after)}')
            _shot(page, 'drive-setup-solver.png')

            # Cars: one added and then edited by hand, through the form.
            page.click('#drive-sections [data-section-tab="cars"]')
            page.wait_for_timeout(200)
            check(_visible(page, '#cars') and not _visible(page, '#solver'), 'clicking Cars did not show it')
            page.locator('#cars').get_by_role('button', name='+ Add a Car').click()
            page.locator('#cars [x-model="newCar.name"]').fill('Minivan')
            page.locator('#cars [x-model\\.number="newCar.seat_capacity"]').fill('6')
            page.locator('#cars').get_by_role('button', name='Mum', exact=True).click()
            page.locator('#cars').get_by_role('button', name='Add Car', exact=True).click()
            page.wait_for_timeout(900)
            cars = page.request.get(served.url('api/cars')).json()
            check(len(cars) == 1 and cars[0]['name'] == 'Minivan' and cars[0]['seat_capacity'] == 6
                  and cars[0]['allowed_driver_ids'] == ['mum'], f'the car did not save: {cars}')
            page.locator('#cars').get_by_role('button', name='Edit', exact=True).click()
            page.locator('#cars [x-model\\.number="newCar.seat_capacity"]').fill('7')
            page.locator('#cars').get_by_role('button', name='Save Car', exact=True).click()
            page.wait_for_timeout(900)
            cars = page.request.get(served.url('api/cars')).json()
            check(len(cars) == 1 and cars[0]['seat_capacity'] == 7, f'the car edit did not save: {cars}')
            check('7 passenger seats' in page.locator('#cars').inner_text(), 'the edited car is not shown')

            # Car alerts send only their own four keys (they used to send all
            # of Config's settings).
            before = dict(storage.get_settings())
            page.locator('#car-alerts [x-model\\.number="carFuelWarnPct"]').fill('15')
            page.locator('#car-alerts [data-save-alerts]').click()
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('car_fuel_warn_pct') == 15, f"fuel warning not saved: {after.get('car_fuel_warn_pct')}")
            check(not (_changed(before, after) - {'car_battery_warn_pct', 'car_fuel_warn_pct',
                                                  'car_auto_errand', 'car_fuel_station'}),
                  f'Save Alerts touched other settings: {_changed(before, after)}')
            _shot(page, 'drive-setup-cars.png')

            # Protected time: a commitment added by hand.
            page.click('#drive-sections [data-section-tab="protected"]')
            page.wait_for_timeout(200)
            check(_visible(page, '#protected-time'), 'clicking Protected time did not show it')
            pt = page.locator('#protected-time')
            pt.locator('[x-model="commitmentForm.title"]').fill('Thursday run')
            pt.locator('[data-commitment-member]').select_option('dad')
            pt.get_by_role('button', name='T', exact=True).nth(1).click()   # Thursday
            pt.locator('[data-protect]').click()
            page.wait_for_timeout(800)
            got = storage.get_protected_commitments()
            check(len(got) == 1 and got[0]['title'] == 'Thursday run' and got[0]['member_id'] == 'dad'
                  and got[0]['days_of_week'] == [3], f'the commitment did not save: {got}')
            check('Thursday run' in pt.inner_text(), 'the commitment is not listed')
            _shot(page, 'drive-setup-protected.png')

            # Outside hands: one added by hand, and the be-ready buffer alone.
            page.click('#drive-sections [data-section-tab="hands"]')
            page.wait_for_timeout(200)
            oh = page.locator('#outside-hands')
            check(_visible(page, '#outside-hands'), 'clicking Outside hands did not show it')
            oh.locator('[x-model="assistForm.name"]').fill('Sarah Whitfield')
            oh.locator('[x-model="assistForm.relation_label"]').fill("Emma's mom")
            oh.get_by_role('button', name='🚗 Driving').click()
            oh.locator('[data-save-hand]').click()
            page.wait_for_timeout(800)
            hands = storage.get_assist_contacts()
            check(len(hands) == 1 and hands[0]['name'] == 'Sarah Whitfield' and 'driving' in hands[0].get('kinds', []),
                  f'the outside hand did not save: {hands}')
            check("Emma's mom" in oh.inner_text(), 'the outside hand is not listed')
            before = dict(storage.get_settings())
            page.fill('#assistReadyBuffer', '15')
            page.dispatch_event('#assistReadyBuffer', 'change')
            page.wait_for_timeout(800)
            after = dict(storage.get_settings())
            check(after.get('assist_ready_buffer_mins') == 15, 'the be-ready buffer did not save')
            check(not (_changed(before, after) - {'assist_ready_buffer_mins'}),
                  f'the buffer save touched other settings: {_changed(before, after)}')
            _shot(page, 'drive-setup-hands.png')

            # A deep link to an anchor in a closed section opens it.
            page.goto(served.url('drive_setup#traffic'), wait_until='networkidle')
            page.wait_for_timeout(600)
            check(_visible(page, '#traffic') and not _visible(page, '#rules'),
                  'drive_setup#traffic did not open Solver & horizons')
            page.goto(served.url('drive_setup#priority-rules'), wait_until='networkidle')
            page.wait_for_timeout(600)
            check(_visible(page, '#priority-rules'), 'drive_setup#priority-rules did not open the Priority sub-tab')

            page.goto(served.url('drive_setup#car-alerts'), wait_until='networkidle')
            page.wait_for_timeout(600)
            check(_visible(page, '#car-alerts') and not _visible(page, '#rules'),
                  'drive_setup#car-alerts did not open Cars')

            # An old link to a moved Config anchor lands on its new home.
            page.goto(served.url('config#outside-hands'), wait_until='networkidle')
            page.wait_for_timeout(800)
            check('/drive_setup' in page.url and _visible(page, '#outside-hands'),
                  f'config#outside-hands did not forward to Drive setup: {page.url}')

            # Errand rules live on the Errands page's Rules tab now; Drive
            # setup's Rules section says so.
            page.goto(served.url('drive_setup'), wait_until='networkidle')
            check(page.locator('#rules a[data-errand-rules-link][href$="errands?tab=rules"]').count() == 1,
                  'Drive setup does not point at the errand rules')
            page.goto(served.url('errands?tab=rules'), wait_until='networkidle')
            page.wait_for_timeout(800)
            tabs = page.eval_on_selector_all('#page-tabs .page-tab', 'els => els.map(e => e.dataset.tabKey)')
            check(tabs == ['errands', 'tasks', 'rules'], f'errands tabs: {tabs}')
            check(_visible(page, '#errand-rules') and not _visible(page, '[data-page-tab="errands"]'),
                  'errands?tab=rules does not show the Rules tab alone')
            er = page.locator('#errand-rules')
            check('Swim run' in er.inner_text(), 'the existing errand rule is not listed')
            er.locator('[x-model="newErrandRule.title"]').fill('Grocery runs')
            er.locator('[x-model="newErrandRuleKeywordInput"]').fill('grocery')
            er.locator('[x-model="newErrandRuleKeywordInput"]').press('Enter')
            er.get_by_role('button', name='Save Rule', exact=True).click()
            page.wait_for_timeout(900)
            rules = page.request.get(served.url('api/errand_rules')).json()
            mine = [r for r in rules if r.get('title') == 'Grocery runs']
            check(len(mine) == 1 and mine[0].get('keywords') == ['grocery'],
                  f'the errand rule did not save: {rules}')
            check('Grocery runs' in er.inner_text(), 'the new errand rule is not listed')
            _shot(page, 'errands-rules.png')
            # The tab strip switches to it in place from the Errands tab too.
            page.goto(served.url('errands'), wait_until='networkidle')
            page.click('#page-tabs [data-tab-key="rules"]')
            page.wait_for_timeout(800)
            check(_visible(page, '#errand-rules') and 'Grocery runs' in page.locator('#errand-rules').inner_text(),
                  'switching to Rules in place did not load the rules')

            # Config no longer carries the controls, nor a pointer where each
            # block used to be (v2.499.261).
            page.goto(served.url('config'), wait_until='domcontentloaded')
            check(page.locator('a[href*="drive_setup#"]:not(nav a)').count() == 0,
                  'Config still carries a pointer to Drive setup')
            check(page.locator('text=Create Errand Rule').count() == 0, 'Config still carries errand rules')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_drive_setup_live OK')


if __name__ == '__main__':
    main()
