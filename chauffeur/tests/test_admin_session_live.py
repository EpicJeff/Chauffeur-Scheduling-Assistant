"""The admin pages keep their own session, apart from the PWA's.

User report (2026-10-02): "Failed to force swap" on every drag on the
Schedule page, after testing the PWA in the same browser signed in as a
child. localStorage is per origin, and the admin gate kept its session in the
PWA's own `chauffeur_member_token`. So signing the PWA in as a child turned
the admin page into the child's view: /api/schedule came back redacted for a
child (no `unassigned`, no `driver_events`), the swap's redraw threw on the
missing key, and the catch around it said the save had failed when it had
not. Signing in on the admin page wrote the PWA's identity the other way.

Pinned, in a real browser against the served app:
  * a child signed in to the PWA does not change what the admin page sees;
  * an admin page signed in as a parent leaves the PWA's keys alone;
  * a parent's PWA session from before the split carries over (nobody is
    signed out by the upgrade), and a child's does not;
  * signing in on the admin page writes only the admin keys;
  * a swap whose redraw meets a redacted schedule is saved and says nothing.

Run from chauffeur/:  python tests/test_admin_session_live.py
"""
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check
from services import storage

TODAY = _dt.date.today()
HOME = '1 Home St'
TOKENS = {}
PASSWORD = 'correct horse battery'


def _travel(o, d, departure_time=None, return_traffic=False):
    same = not o or not d or o.lower() == d.lower()
    mins = 0 if same else 15
    return (mins, 0) if return_traffic else mins


def _serve():
    from live_app import live_app
    from services import calendar as cal_svc
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher
    import main

    at = lambda h: _dt.datetime.combine(TODAY, _dt.time(h, 0))
    evs = [dict(id=g, title=t, start=at(h), end=at(h + 1), location=loc,
                description='', calendar_ids=['cal_lily'], source_event_ids=[g])
           for g, t, h, loc in (('a', 'School', 8, '2 School Rd'),
                                ('b', 'Swim', 12, '3 Pool Rd'))]

    def seed():
        for t in ('drivers_table', 'passengers_table', 'members_table',
                  'daily_schedules_table', 'custom_schedules_table',
                  'settings_table', 'event_configs_table', 'rules_table',
                  'overrides_table'):
            tbl = getattr(storage, t, None)
            if tbl is not None:
                tbl.truncate()
        storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                       'days_to_build': 1, 'home_location': HOME})
        for i, (did, name) in enumerate((('d1', 'Jeff'), ('d2', 'Vovo'))):
            storage.add_driver({'id': did, 'name': name, 'color_code': '#4ade80',
                                'group': 'primary', 'priority_index': i + 1,
                                'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'p1', 'name': 'Lily',
                               'calendar_ids': ['cal_lily'], 'hashtags': []})
        storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent',
                            'driver_id': 'd1', 'email': 'jeff@example.com'})
        storage.add_member({'id': 'ml', 'name': 'Lily', 'role': 'child',
                            'passenger_id': 'p1'})
        storage.set_member_password('mj', PASSWORD)
        TOKENS['parent'] = storage.create_member_token('mj')
        TOKENS['child'] = storage.create_member_token('ml')
        for g in ('a', 'b'):
            storage.event_configs_table.insert({'google_id': g,
                                                'passenger_ids': ['p1']})
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**e) for e in evs]
        matcher._raw_get_travel_time_minutes = _travel
        maps.get_travel_time_minutes = _travel
        main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(),
                                    force_refresh=True)

    return live_app(seed)


def _open(page, served, store):
    """Land on the origin, set localStorage exactly as `store` says, then load
    the Schedule page."""
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear();'
                  ' for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  store)
    page.goto(served.url('dashboard_v2'), wait_until='networkidle')
    page.wait_for_function('() => typeof currentData !== "undefined" && currentData',
                           timeout=20000)


def _state(page):
    return page.evaluate('''() => ({
        keys: Object.keys(currentData),
        gate: Alpine.$data(document.querySelector('[x-data="adminGate()"]')).state,
        ls: Object.fromEntries(['chauffeur_member_token', 'chauffeur_member_token_for',
                                'chauffeur_member_id', 'chauffeur_admin_token',
                                'chauffeur_admin_token_for']
                               .map(k => [k, localStorage.getItem(k)])),
    })''')


def scenario_admin_and_pwa_sessions_are_separate():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            pwa_child = {'chauffeur_member_token': TOKENS['child'],
                         'chauffeur_member_token_for': 'ml',
                         'chauffeur_member_id': 'ml'}

            # 1. The report: PWA signed in as the child, admin as the parent.
            _open(page, served, dict(pwa_child,
                                     chauffeur_admin_token=TOKENS['parent'],
                                     chauffeur_admin_token_for='mj'))
            s = _state(page)
            check(s['gate'] == 'in', "the admin page is signed in: %r" % s['gate'])
            check('unassigned' in s['keys'] and 'driver_events' in s['keys'],
                  "the admin page got the child's redacted schedule: %s" % s['keys'])
            check(s['ls']['chauffeur_member_token'] == TOKENS['child']
                  and s['ls']['chauffeur_member_id'] == 'ml',
                  "the admin page changed the PWA's session: %r" % s['ls'])

            # 2. A child's PWA session from before the split is NOT adopted.
            _open(page, served, pwa_child)
            s = _state(page)
            check(s['gate'] == 'sign-in',
                  "a child's PWA token signed the admin page in: %r" % s['gate'])
            check(not s['ls']['chauffeur_admin_token'],
                  "a child's token became the admin session: %r" % s['ls'])
            check('unassigned' in s['keys'],
                  "the child's token still rode the admin page's requests: %s" % s['keys'])

            # 3. Signing in on the admin page writes only the admin keys.
            page.fill('input[type=email]', 'jeff@example.com')
            page.fill('input[type=password]', PASSWORD)
            with page.expect_navigation():   # store() reloads the page
                page.click('form button[type=submit]')
            page.wait_for_function('() => typeof currentData !== "undefined" && currentData'
                                   ' && localStorage.getItem("chauffeur_admin_token")',
                                   timeout=20000)
            s = _state(page)
            check(s['ls']['chauffeur_admin_token_for'] == 'mj', "admin session is Jeff's: %r" % s['ls'])
            check(s['ls']['chauffeur_member_token'] == TOKENS['child']
                  and s['ls']['chauffeur_member_token_for'] == 'ml'
                  and s['ls']['chauffeur_member_id'] == 'ml',
                  "signing in on the admin page re-signed the PWA: %r" % s['ls'])

            # 4. A parent's PWA session from before the split carries over.
            _open(page, served, {'chauffeur_member_token': TOKENS['parent'],
                                 'chauffeur_member_token_for': 'mj',
                                 'chauffeur_member_id': 'mj'})
            s = _state(page)
            check(s['gate'] == 'in', "a parent was signed out by the upgrade: %r" % s['gate'])
            check(s['ls']['chauffeur_admin_token'] == TOKENS['parent'],
                  "the parent's session was not carried over: %r" % s['ls'])
            check(not errors, "the page threw: %s" % errors)
    finally:
        served.stop()


def scenario_swap_on_a_redacted_schedule_is_saved_quietly():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            _open(page, served, {'chauffeur_admin_token': TOKENS['parent'],
                                 'chauffeur_admin_token_for': 'mj'})
            got = page.evaluate('''async () => {
                const alerts = [];
                window.showGlobalAlert = (m) => alerts.push(m);
                // What redact_schedule_blob serves a viewer without
                // schedule.diagnostics / schedule.driver_calendars.
                for (const k of ['diagnostics', 'ai_metadata', 'matched_rules',
                                 'unassigned', 'true_unassigned', 'conflicts',
                                 'lateness_warnings', 'overridden_events',
                                 'no_location', 'solving_dates', 'driver_events'])
                    delete currentData[k];
                const eid = Object.keys(currentData.assignments)[0];
                const to = currentData.assignments[eid] === 'd1' ? 'd2' : 'd1';
                await forceSwap(eid, to);
                const saved = await (await fetch('api/overrides')).json();
                return { alerts, eid, to, saved };
            }''')
    finally:
        served.stop()
    check(got['alerts'] == [],
          "a saved swap still reported a failure: %r" % got['alerts'])
    saved = got['saved'] if isinstance(got['saved'], list) else []
    check(any(o.get('event_id') == got['eid'] and o.get('driver_id') == got['to']
              for o in saved),
          "the swap was not saved: %r" % got['saved'])


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d admin-session scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
