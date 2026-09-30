"""A day you page back to stays on screen.

User report (2026-09-30): "I was looking at viewing past days to see old
events and it still doesn't work. ... you can go back and it shows the schedule
for a second and then it clears and says there is nothing."

The Drives / Family back arrow pages a past day in (`fetchMoreDays`), which
merged it into `scheduleData`. But every schedule refetch — the stream's
"update", the wake-up and 5-minute refreshes — REPLACES `scheduleData` with the
rolling from-today window, and paging back to a day the server has to work out
is itself what fires that update. So the day drew, then blanked.

Pinned in a real browser against a real solve (calendar and travel stubbed):
  * Drives and Family, as a parent, with the real taps (the date button, then
    the back arrow): yesterday draws, and after two refetches like the
    stream's it is still drawn and still the day on screen.

Run from chauffeur/:  python tests/test_past_days_stay_live.py
"""
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check
from services import storage

TODAY = _dt.date.today()
YESTERDAY = TODAY - _dt.timedelta(days=1)
HOME = '1 Home St'


def _travel(o, d, departure_time=None, return_traffic=False):
    same = not o or not d or o.lower() == d.lower()
    mins = 0 if same else 15
    return (mins, 0) if return_traffic else mins


def scenario_a_paged_back_day_survives_a_refetch():
    from live_app import live_app
    from services import calendar as cal_svc
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher
    import main

    def ev(i, title, day, h):
        start = _dt.datetime.combine(day, _dt.time(h))
        return Event(id=i, title=title, start=start, end=start + _dt.timedelta(hours=1),
                     location=f'{i} Field Rd', description='',
                     calendar_ids=['cal_lily'], source_event_ids=[i])

    def fetch(ids, days=7, start_date_str=None, end_date_str=None):
        evs = [ev('old', 'Yesterday Soccer', YESTERDAY, 10),
               ev('new', 'Today Piano', TODAY, 16)]
        lo = _dt.date.fromisoformat(start_date_str[:10]) if start_date_str else TODAY
        hi = _dt.date.fromisoformat(end_date_str[:10]) if end_date_str else TODAY + _dt.timedelta(days=days)
        return [e for e in evs if lo <= e.start.date() <= hi]

    real = (cal_svc.fetch_upcoming_events, matcher._raw_get_travel_time_minutes,
            maps.get_travel_time_minutes, storage.get_settings)
    storage.get_settings = lambda: (dict(storage.settings_table.all()[0])
                                    if storage.settings_table.all() else {})

    def seed():
        for t in ('drivers_table', 'passengers_table', 'members_table',
                  'daily_schedules_table', 'custom_schedules_table',
                  'settings_table', 'event_configs_table'):
            getattr(storage, t).truncate()
        storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                       'days_to_build': 2, 'home_location': HOME})
        storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#4ade80',
                            'group': 'primary', 'priority_index': 1,
                            'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'p1', 'name': 'Lily',
                               'calendar_ids': ['cal_lily'], 'hashtags': []})
        storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent',
                            'driver_id': 'd1'})
        storage.add_member({'id': 'ml', 'name': 'Lily', 'role': 'adult',
                            'passenger_id': 'p1'})
        for g in ('old', 'new'):
            storage.event_configs_table.insert({'google_id': g, 'passenger_ids': ['p1']})
        cal_svc.fetch_upcoming_events = fetch
        matcher._raw_get_travel_time_minutes = _travel
        maps.get_travel_time_minutes = _travel
        main.refresh_schedule_logic(force_refresh=True)   # the rolling window only

    def open_as(page, served, name, driver=None, view='drives'):
        page.goto(served.url('app'), wait_until='domcontentloaded', timeout=90000)
        # add_member mints its own ids: find the member by name.
        member = page.evaluate(
            "async (n) => ((await (await fetch('api/members')).json()) || [])"
            ".find(m => m.name === n).id", name)
        page.evaluate("([m, d, v]) => { localStorage.clear(); localStorage.setItem('chauffeur_member_id', m);"
                      " if (d) localStorage.setItem('chauffeur_driver_id', d);"
                      " else localStorage.removeItem('chauffeur_driver_id');"
                      " localStorage.setItem('chauffeur_view', v); }", [member, driver, view])
        page.goto(served.url('app'), wait_until='domcontentloaded', timeout=90000)
        page.wait_for_timeout(1500)
        skip = page.get_by_text('Skip', exact=True)
        if skip.count() and skip.first.is_visible():
            skip.first.click()
            page.wait_for_timeout(300)
        page.evaluate("(v) => setView(v)", view)

    pane_text = ("() => { const y = new Date(); y.setDate(y.getDate() - 1);"
                 " const k = y.toLocaleDateString('en-CA');"
                 " const p = document.getElementById('pane-' + currentDates.indexOf(k));"
                 " return p ? p.textContent : ''; }")
    try:
        served = live_app(seed, boot_timeout=180.0)
        if served is None:
            return
        try:
            handle = served.browser()
            with handle as page:
                page.set_viewport_size({'width': 430, 'height': 900})
                for view in ('drives', 'family'):
                    open_as(page, served, 'Jeff', 'd1', view)
                    page.wait_for_function(
                        "(document.getElementById('days-container') || {}).textContent"
                        " && document.getElementById('days-container').textContent.includes('Today Piano')",
                        timeout=30000)
                    # The real taps: the date button opens the day pager,
                    # then the back arrow.
                    toggle = page.locator('.pwa-date-toggle')
                    if toggle.count() and toggle.first.is_visible():
                        toggle.first.click()
                        page.wait_for_timeout(300)
                    page.click('#btn-prev-day')
                    page.wait_for_function(f"({pane_text})().includes('Yesterday Soccer')",
                                           timeout=60000)
                    # What the stream's "update" does, twice, the second after
                    # the server's own refresh has had time to land.
                    page.evaluate("fetchSchedule(false, true)")
                    page.wait_for_timeout(2500)
                    page.evaluate("fetchSchedule(false, true)")
                    page.wait_for_timeout(2500)
                    txt = page.evaluate(pane_text)
                    check('Yesterday Soccer' in txt,
                          f"{view}: yesterday is still drawn after a refetch: {txt[:300]!r}")
                    check(page.evaluate("activeDateIndex") == page.evaluate(
                        "(() => { const y = new Date(); y.setDate(y.getDate() - 1);"
                        " return currentDates.indexOf(y.toLocaleDateString('en-CA')); })()"),
                          f'{view}: and the view is still on yesterday')
                    shots = os.environ.get('PD_SHOTS')
                    if shots:
                        page.screenshot(path=os.path.join(shots, f'past-{view}.png'))
        finally:
            served.stop()
        errors = [e for e in handle.errors if 'ERR_CONNECTION_RESET' not in e]
        check(not errors, 'the page threw: %r' % errors[:3])
    finally:
        (cal_svc.fetch_upcoming_events, matcher._raw_get_travel_time_minutes,
         maps.get_travel_time_minutes, storage.get_settings) = real


if __name__ == '__main__':
    scenario_a_paged_back_day_survives_a_refetch()
    print('test_past_days_stay_live OK')
