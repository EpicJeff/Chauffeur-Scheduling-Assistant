"""With enforcement ON, every admin page must be able to act as the signed-in
parent, and ask for a sign-in when it cannot.

User report (2026-10-09), the day after flipping Config → People →
Enforcement: "forever not a parent in the admin side, and no way to sign in
that I can see" — and "neither config nor schedule ask for sign in."

Three causes, each pinned here against the served app in a real browser:
  * a browser that was ever paired as a trusted DEVICE sent X-Device-Token on
    every admin fetch, and `identify` prefers a device over a member, so a
    valid parent session was read as furniture (403, member or parent);
  * the admin gate said "a stale token is caught by the first 403" and never
    did anything on one, so a dead session left the page refused with no
    overlay;
  * only /schedule and /config carried the gate at all; /work and the other
    admin pages had no session and no sign-in.

Run from chauffeur/:  python tests/test_admin_gate_everywhere_live.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage


# Not harness.check: importing harness replaces storage.get_settings with a
# fixed dict, and this test needs the real settings row (the flip lives there).
def check(cond, msg):
    if not cond:
        raise AssertionError(msg)

TOKENS = {}
PASSWORD = 'correct horse battery'
DEVICE_TOKEN = 'paired-browser-token'


def _serve():
    from live_app import live_app

    def seed():
        storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent', 'email': 'jeff@example.com'})
        storage.set_member_password('mj', PASSWORD)
        TOKENS['parent'] = storage.create_member_token('mj')
        storage.trusted_devices_table.insert({'device_id': 'laptop', 'device_token': DEVICE_TOKEN,
                                              'label': 'Laptop', 'kind': 'personal'})
        storage.add_mission({'goal': 'Find a plumber', 'status': 'running', 'created_by': 'mj',
                             'tier': 'flash', 'origin_kind': 'manual', 'step_count': 0})

    served = live_app(seed)
    if served is not None:
        # The flip, as the household did it (Decision 9 holds: the one member
        # has a password). Written AFTER the server is up: the harness's own
        # start-up rewrites settings, so a value seeded before it is lost.
        storage.update_settings({'auth_enforce': True, 'missions_enabled': True})
        check(storage.get_settings().get('auth_enforce') is True, "enforcement is on for the test")
    return served


def _land(page, served, store):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear();'
                  ' for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }', store)


def _gate_state(page):
    return page.evaluate('''() => { const el = document.querySelector('[x-data="adminGate()"]');
        return el ? Alpine.$data(el).state : null; }''')


def scenario_a_paired_browser_still_acts_as_the_signed_in_parent():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            _land(page, served, {'chauffeur_admin_token': TOKENS['parent'], 'chauffeur_admin_token_for': 'mj',
                                 'chauffeur_device_token': DEVICE_TOKEN, 'chauffeur_device_id': 'laptop'})
            page.goto(served.url('work?tab=missions'), wait_until='load')
            page.wait_for_timeout(1500)
            got = page.evaluate('''async () => {
                const r = await fetch('api/missions/admin');
                return { status: r.status, refusal: r.headers.get('X-Auth-Refusal') || '' };
            }''')
            check(got['status'] == 200, f"a paired browser with a parent session is the parent, got {got}")
            check(_gate_state(page) == 'in', f"the gate is in: {_gate_state(page)!r}")
            check(page.locator('#missions .situation-card').count() >= 1, "the missions lane drew as the parent")
    finally:
        served.stop()


def scenario_b_a_dead_session_asks_again():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            _land(page, served, {'chauffeur_admin_token': 'stale-token', 'chauffeur_admin_token_for': 'mj'})
            # A page whose reads need a PERSON (the schedule reads pass on local
            # ground as the service tier; the missions admin view does not).
            page.goto(served.url('work?tab=missions'), wait_until='load')
            page.wait_for_function('''() => { const el = document.querySelector('[x-data="adminGate()"]');
                return el && Alpine.$data(el).state === 'sign-in'; }''', timeout=15000)
            check(page.locator('form input[type=email]').is_visible(), "the sign-in overlay is up")
            page.fill('form input[type=email]', 'jeff@example.com')
            page.fill('form input[type=password]', PASSWORD)
            with page.expect_navigation():
                page.click('form button[type=submit]')
            page.wait_for_selector('#missions .situation-card', timeout=20000)
            check(page.evaluate("() => localStorage.getItem('chauffeur_admin_token')") != 'stale-token',
                  "signing in replaced the dead token")
    finally:
        served.stop()


def scenario_c_every_admin_page_carries_the_gate_and_panels_do_not():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            _land(page, served, {})
            for path in ('work?tab=threads', 'errands', 'rhythms'):
                page.goto(served.url(path), wait_until='load')
                page.wait_for_function('''() => { const el = document.querySelector('[x-data="adminGate()"]');
                    return el && Alpine.$data(el).state === 'sign-in'; }''', timeout=15000)
                check(page.locator('form input[type=email]').is_visible(), f"/{path} asks who you are")
            # Signing in on one admin page signs in every admin page (one origin, one session).
            page.fill('form input[type=email]', 'jeff@example.com')
            page.fill('form input[type=password]', PASSWORD)
            with page.expect_navigation():
                page.click('form button[type=submit]')
            page.goto(served.url('work?tab=missions'), wait_until='load')
            page.wait_for_selector('#missions .situation-card', timeout=15000)
            check(_gate_state(page) == 'in', "the Work page is in after signing in elsewhere")
            # A wall panel is a place, not a person: no gate, no overlay.
            _land(page, served, {'chauffeur_device_token': DEVICE_TOKEN, 'chauffeur_device_id': 'laptop'})
            page.goto(served.url('home?panel=true'), wait_until='load')
            page.wait_for_timeout(1000)
            check(_gate_state(page) is None, "a panel page carries no admin gate")
            page.goto(served.url('trip?kiosk=true'), wait_until='load')
            check(_gate_state(page) is None, "a kiosk page carries no admin gate")
    finally:
        served.stop()


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d admin-gate scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
