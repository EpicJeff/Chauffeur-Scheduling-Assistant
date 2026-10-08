"""The same departure on every surface, in a real browser.

User report (2026-09-29): "The times should be the same across every surface.
If there's a 5 minute buffer being added, it should be coming from a single
unified setting that can be adjusted by the user."

A real solve (calendar and travel stubbed) gives one driver a morning drive
from home and a layover at home before a noon drive. Pinned:
  * the PWA's Drives list, the Schedule page and the wall's run list all say
    7:40 and 11:40 (15-minute drives, the default 5-minute leave margin);
  * setting the margin to 12 on the Schedule page moves every one of them to
    7:33 and 11:33 — one setting, every surface.

Run from chauffeur/:  python tests/test_leave_times_live.py
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


def _travel(o, d, departure_time=None, return_traffic=False):
    same = not o or not d or o.lower() == d.lower()
    mins = 0 if same else 15
    return (mins, 0) if return_traffic else mins


def _has(texts, hhmm):
    h, m = hhmm.split(':')
    return any((f'{int(h)}:{m}' in t) or (f'{h}:{m}' in t) for t in texts)


def scenario_one_margin_every_surface():
    from live_app import live_app
    from services import calendar as cal_svc
    from services import home_board
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher
    import main

    at = lambda h, m=0: _dt.datetime.combine(TODAY, _dt.time(h, m))
    school = dict(id='a', title='School', start=at(8), end=at(9),
                  location='2 School Rd', description='',
                  calendar_ids=['cal_lily'], source_event_ids=['a'])
    swim = dict(id='b', title='Swim', start=at(12), end=at(13),
                location='3 Pool Rd', description='',
                calendar_ids=['cal_lily'], source_event_ids=['b'])

    real = (cal_svc.fetch_upcoming_events, matcher._raw_get_travel_time_minutes,
            maps.get_travel_time_minutes, storage.get_settings)
    # The harness stubs settings to a constant; this test is ABOUT a saved
    # setting reaching every surface, so it reads the real table.
    storage.get_settings = lambda: (dict(storage.settings_table.all()[0])
                                    if storage.settings_table.all() else {})

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
        storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#4ade80',
                            'group': 'primary', 'priority_index': 1,
                            'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'p1', 'name': 'Lily',
                               'calendar_ids': ['cal_lily'], 'hashtags': []})
        storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent',
                            'driver_id': 'd1'})
        storage.add_member({'id': 'ml', 'name': 'Lily', 'role': 'child',
                            'passenger_id': 'p1'})
        for g in ('a', 'b'):
            storage.event_configs_table.insert({'google_id': g,
                                                'passenger_ids': ['p1']})
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**school), Event(**swim)]
        matcher._raw_get_travel_time_minutes = _travel
        maps.get_travel_time_minutes = _travel
        main.refresh_schedule_logic(force_refresh=True)

    def wall_labels(page):
        # The wall's own builder (home_board.todays_runs -> leave_by), run
        # over the schedule the live server serves.
        blob = page.evaluate("async () => (await fetch('api/schedule')).json()")
        runs = home_board.todays_runs(sched=blob, now=at(0, 1))
        return [r.get('leave_label') for r in runs if r.get('leave_label')]

    def surfaces(page, served):
        page.goto(served.url('app'))
        page.evaluate("localStorage.setItem('chauffeur_member_id', 'mj');"
                      "localStorage.setItem('chauffeur_driver_id', 'd1');"
                      "localStorage.setItem('chauffeur_view', 'drives')")
        page.goto(served.url('app'))
        page.wait_for_timeout(1500)
        skip = page.get_by_text('Skip', exact=True)
        if skip.count() and skip.first.is_visible():
            skip.first.click()
            page.wait_for_timeout(300)
        page.evaluate("setView('drives')")
        page.wait_for_function(
            "(document.getElementById('days-container') || {}).textContent"
            " && document.getElementById('days-container').textContent.includes('Swim')",
            timeout=20000)
        page.wait_for_timeout(500)
        drives = page.evaluate(
            "() => { const t = new Date().toLocaleDateString('en-CA');"
            " const p = document.getElementById('pane-' + currentDates.indexOf(t));"
            " return p ? [p.textContent.replace(/\s+/g, ' ')] : []; }")
        page.goto(served.url('dashboard_v2'), wait_until='networkidle')
        page.wait_for_timeout(3000)
        sched = page.evaluate(
            '() => [...document.querySelectorAll("span")]'
            '.filter(s => /LEAVE AT/i.test(s.textContent || ""))'
            '.map(s => (s.textContent || "").trim())')
        return drives, sched

    try:
        # The seed runs a real solve; under a parallel sweep that is slow.
        served = live_app(seed, boot_timeout=180.0)
        if served is None:
            return
        try:
            handle = served.browser()
            with handle as page:
                page.set_viewport_size({'width': 1320, 'height': 950})
                drives, sched = surfaces(page, served)
                for hhmm in ('7:40', '11:40'):
                    check(_has(drives, hhmm), f'Drives list shows {hhmm}: {drives}')
                    check(_has(sched, hhmm), f'Schedule page shows {hhmm}: {sched}')
                wall = wall_labels(page)
                check(wall[:2] == ['7:40 AM', '11:40 AM'],
                      f'the wall says the same two departures: {wall}')
                shots = os.environ.get('LEAVE_SHOTS')
                if shots:
                    page.screenshot(path=os.path.join(shots, 'schedule-margin-5.png'))

                # One setting, on the Schedule page, moves every surface.
                # (the admin gate overlays a signed-out page: open the drawer the way the gear does)
                page.evaluate("() => window.chfOpenSettings('drives')")
                page.wait_for_selector('[data-settings-for~="drives"][data-open]')
                page.wait_for_selector('#leave-margin-mins', state='visible')
                check(page.input_value('#leave-margin-mins') == '5',
                      'the Schedule page shows the current margin')
                page.fill('#leave-margin-mins', '12')
                page.dispatch_event('#leave-margin-mins', 'change')
                page.wait_for_timeout(1500)
                check(storage.settings_table.all()[0].get('leave_margin_mins') == 12,
                      'the margin saved')
                main.refresh_schedule_logic(force_refresh=True)
                drives, sched = surfaces(page, served)
                for hhmm in ('7:33', '11:33'):
                    check(_has(drives, hhmm), f'Drives list moved to {hhmm}: {drives}')
                    check(_has(sched, hhmm), f'Schedule page moved to {hhmm}: {sched}')
                wall = wall_labels(page)
                check(wall[:2] == ['7:33 AM', '11:33 AM'],
                      f'the wall moved with it: {wall}')
                if shots:
                    page.screenshot(path=os.path.join(shots, 'schedule-margin-12.png'))
        finally:
            served.stop()
        # Navigating between pages cuts their live streams; a reset from
        # that is the test leaving, not the page failing.
        errors = [e for e in handle.errors if 'ERR_CONNECTION_RESET' not in e]
        check(not errors, 'the pages threw: %r' % errors[:3])
    finally:
        (cal_svc.fetch_upcoming_events, matcher._raw_get_travel_time_minutes,
         maps.get_travel_time_minutes, storage.get_settings) = real


if __name__ == '__main__':
    scenario_one_margin_every_surface()
    print('test_leave_times_live OK')
