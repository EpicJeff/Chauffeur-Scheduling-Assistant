"""Drive setup, now the Drives drawer on /dashboard_v2 (settings-drawer arc).

It began as the Drive setup page (v2.499.253), a tab of the Schedule group; the
settings-drawer arc folded it into the Drives drawer behind the gear, with the
leave margin beside it, and /drive_setup forwards. Same ids, same assertions.


Everything that decides how drives get assigned lived on Config: the Rules &
Priorities tab, the solver switches and horizons, routing and traffic policy
and the parents' tomorrow digest. It moved to /drive_setup, a tab of the
Schedule group. What only a browser can check:

  - the drawer opens from the gear, holds six stacked sections with six jump
    chips, and the old addresses (`drive_setup#traffic`) land on their anchor;
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

DRAWER = '[data-settings-for~="drives"]'
OUT = (sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv
       else os.environ.get('CHF_SHOTS'))


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
            seen = []
            page.on('request', lambda r: seen.append(r.url))
            page.goto(served.url('dashboard_v2'), wait_until='networkidle')
            page.wait_for_timeout(1200)
            check(not [u for u in seen if '/api/cars' in u or '/api/commitments' in u or '/api/assist' in u],
                  f'Drives loaded the drawer before it opened: {[u for u in seen if "/api/" in u]}')
            check(len([u for u in seen if '/api/schedule' in u]) <= 2, 'a second schedule fetch before the gear: ' + str([u for u in seen if '/api/schedule' in u]))

            # It is the Drives page's drawer; the Schedule strip lost its Drive setup tab.
            check(_visible(page, '#page-tabs'), 'Drives has no Schedule tab strip')
            tabs = page.eval_on_selector_all('#page-tabs .page-tab', 'els => els.map(e => e.dataset.tabKey)')
            check(tabs == ['drives', 'calendar', 'moments', 'occasions'], f'tabs: {tabs}')
            check(not _visible(page, DRAWER), 'the Drives drawer starts open')
            _shot(page, 'drive-setup-closed.png')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            page.wait_for_timeout(900)
            page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data^=driveSetup]')).cars !== undefined")
            check(any('/api/cars' in u for u in seen), 'opening the drawer did not load the cars')
            check(page.locator(DRAWER + ' [data-settings-chip]').count() == 6,
                  'the Drives drawer does not carry six jump chips')
            for sec in ('leave-margin', 'rules', 'cars', 'protected-time', 'outside-hands', 'solver'):
                check(page.locator(DRAWER + ' #' + sec).count() == 1, f'#{sec} is not in the Drives drawer once')
            _shot(page, 'drive-setup-top.png')

            # Sections are stacked, so all of them are showing; the rule already written is listed.
            check(_visible(page, '#rules') and _visible(page, '#solver'),
                  'the sections are not stacked')
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
            page.locator('#solver').scroll_into_view_if_needed()
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
            page.locator('#cars').scroll_into_view_if_needed()
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
            page.locator('#protected-time').scroll_into_view_if_needed()
            check(_visible(page, '#protected-time'), 'Protected time is not showing')
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
            page.locator('#outside-hands').scroll_into_view_if_needed()
            oh = page.locator('#outside-hands')
            check(_visible(page, '#outside-hands'), 'Outside hands is not showing')
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

            # Old addresses still land, hash and all.
            for old, anchor in (('drive_setup', None), ('drive_setup#traffic', 'traffic'),
                                ('drive_setup#priority-rules', 'priority-rules'), ('drive_setup#car-alerts', 'car-alerts'),
                                ('config#outside-hands', 'outside-hands')):
                page.goto(served.url(old), wait_until='networkidle')
                page.wait_for_selector(DRAWER + '[data-open]')
                page.wait_for_timeout(1800)
                check('dashboard_v2' in page.url, f'{old} did not forward to Drives: {page.url}')
                check('settings=open' not in page.url, f'{old} left settings=open in the address: {page.url}')
                if anchor:
                    top, bar = page.evaluate(
                        "(a) => [document.getElementById(a).getBoundingClientRect().top,"
                        " document.querySelector('[data-settings-for~=\"drives\"] .sticky').getBoundingClientRect().bottom]", anchor)
                    check(bar - 1 <= top < 300, f'{old} did not land on #{anchor} below the header: {top} vs {bar}')
                if anchor == 'priority-rules':
                    check(_visible(page, '#priority-rules'), 'the Priority sub-tab did not open by link')
                if anchor == 'car-alerts':
                    _shot(page, 'drive-setup-car-alerts.png')
                page.click(DRAWER + ' [aria-label="Close settings"]')
            page.goto(served.url('dashboard_v2#cars?from=house'), wait_until='networkidle')
            page.wait_for_selector(DRAWER + '[data-open]')
            page.wait_for_timeout(1500)
            top = page.evaluate("() => document.getElementById('cars').getBoundingClientRect().top")
            check(0 <= top < 300, f'dashboard_v2#cars?from=house did not open at Cars: {top}')
            page.click(DRAWER + ' [aria-label="Close settings"]')
            # A wall view loads none of the drawer's weight.
            page.goto(served.url('dashboard_v2?kiosk=true'), wait_until='domcontentloaded')
            check(page.locator('script[src*="mapbox-gl"]').count() == 0, 'a kiosk view loads Mapbox GL')
            # Leave margin moved out of the toolbar and into the drawer.
            page.goto(served.url('dashboard_v2'), wait_until='networkidle')
            check(not _visible(page, '#header-buttons #leave-margin-mins'), 'leave margin still sits in the toolbar')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            page.wait_for_timeout(600)
            box = page.evaluate("() => { const r = document.querySelector('[data-settings-for~=\"drives\"]').getBoundingClientRect(); return [r.width, innerWidth]; }")
            check(box[0] == box[1], f'the Drives drawer is trapped by an ancestor: {box}')
            check(_visible(page, '#leave-margin') and _visible(page, '#leave-margin-mins'),
                  'the leave margin is not in the drawer')
            before = dict(storage.get_settings())
            page.fill('#leave-margin-mins', '12')
            page.dispatch_event('#leave-margin-mins', 'change')
            page.wait_for_selector(DRAWER + ' [data-settings-status]:has-text("Saved")')
            after = dict(storage.get_settings())
            check(after.get('leave_margin_mins') == 12, 'the leave margin did not save')
            check(_changed(before, after) == {'leave_margin_mins'}, 'the leave margin save touched other settings')
            page.click(DRAWER + ' [aria-label="Close settings"]')

            # Phone: the sheet is a bottom sheet and nothing scrolls sideways.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('drive_setup#car-alerts'), wait_until='networkidle')
            page.wait_for_selector(DRAWER + '[data-open]')
            page.wait_for_timeout(1500)
            check(page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"),
                  'the phone page scrolls sideways')
            _shot(page, 'drive-setup-phone.png')
            page.click(DRAWER + ' [aria-label="Close settings"]')
            page.set_viewport_size({'width': 1400, 'height': 900})

            # A save fired before the lazy settings load lands must not post
            # the in-memory defaults over the stored values.
            posts = []
            page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and r.url.endswith('/api/settings') else None)

            def slow_settings(route):
                if route.request.method == 'GET':
                    resp = route.fetch()
                    page.wait_for_timeout(1500)
                    route.fulfill(response=resp)
                else:
                    route.continue_()
            page.route('**/api/settings', slow_settings)
            page.goto(served.url('dashboard_v2'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            refused = page.evaluate("() => Alpine.$data(document.querySelector('[x-data^=driveSetup]')).saveHorizons()")
            check(refused is False and not posts, f'a save before the settings loaded went out: {refused} {posts}')
            check('Still loading' in page.locator(DRAWER + ' [data-settings-status]').inner_text(),
                  'the early save did not say it was still loading')
            page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data^=driveSetup]')).settingsLoaded === true")
            page.unroute('**/api/settings')

            # The errand rules live in the Errands drawer, opened by the gear;
            # Drive setup's Rules section points there.
            page.goto(served.url('dashboard_v2'), wait_until='networkidle')
            check(page.locator('#rules a[data-errand-rules-link][href$="errands?settings=open"]').count() == 1,
                  'Drive setup does not point at the errand rules')
            page.goto(served.url('errands'), wait_until='networkidle')
            tabs = page.eval_on_selector_all('#page-tabs .page-tab', 'els => els.map(e => e.dataset.tabKey)')
            check(tabs == ['errands', 'tasks'], f'errands tabs: {tabs}')
            ED = '[data-settings-for~="errands"]'
            page.click('#page-settings-gear')
            page.wait_for_selector(ED + '[data-open]')
            page.wait_for_selector('#errand-rules [x-model="newErrandRule.title"]', state='visible')
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

            # Config no longer carries the controls, nor a pointer where each
            # block used to be (v2.499.261).
            page.goto(served.url('config'), wait_until='domcontentloaded')
            check(page.locator('a[href*="drive_setup"]:not(nav a)').count() == 0,
                  'Config still carries a pointer to Drive setup')
            check(page.locator('text=Create Errand Rule').count() == 0, 'Config still carries errand rules')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_drive_setup_live OK')


if __name__ == '__main__':
    main()
