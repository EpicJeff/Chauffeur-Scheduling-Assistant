"""The event editor opens the whole event, never a leg (2026-11-03).

Spec: docs/superpowers/specs/2026-11-03-leg-editor-shows-the-whole-event-design.md.

A split event's drop-off and pick-up cards used to open the editor on the
leg: a zero-length event, and a touched time field wrote that pair to the
calendar. Clicking either card now shows the whole event's span, says which
drive the card is, fills the editor from the whole event, and a save from a
leg never writes times.

Run from chauffeur/:  python tests/test_leg_editor_live.py
"""
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check  # noqa: E402  (isolates CHAUFFEUR_DATA_DIR)
from services import storage  # noqa: E402

TODAY = _dt.date.today()
HOME = '1 Home St'
TOKENS = {}
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'probe_shots')


def _refresh():
    import main
    main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(), force_refresh=True)


def _serve():
    from live_app import live_app
    from services import calendar as cal_svc
    from models.schemas import Event
    import main

    at = lambda h, m=0: _dt.datetime.combine(TODAY, _dt.time(h, m))  # noqa: E731
    evs = [dict(id='gev1', title='Swim meet', start=at(16), end=at(19), location='3 Pool Rd',
                description='', calendar_ids=['cal_lily'], source_event_ids=['gev1'])]

    def seed():
        for t in ('drivers_table', 'passengers_table', 'members_table', 'daily_schedules_table',
                  'custom_schedules_table', 'settings_table', 'event_configs_table', 'rules_table',
                  'overrides_table', 'ride_groups_table', 'cache_table'):
            tbl = getattr(storage, t, None)
            if tbl is not None:
                tbl.truncate()
        storage.settings_table.insert({'calendar_ids': ['cal_house'], 'days_to_build': 1, 'home_location': HOME})
        storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#4ade80', 'group': 'primary',
                            'priority_index': 1, 'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'p1', 'name': 'Lily', 'calendar_ids': ['cal_lily'], 'hashtags': []})
        storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent', 'driver_id': 'd1'})
        TOKENS['parent'] = storage.create_member_token('mj')
        storage.event_configs_table.insert({'google_id': 'gev1', 'passenger_ids': ['p1']})
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**e) for e in evs]
        main.trigger_background_refresh = lambda *a, **k: None
        _refresh()

    return live_app(seed)


def _open(page, served):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(t) => { localStorage.clear();'
                  ' localStorage.setItem("chauffeur_admin_token", t);'
                  ' localStorage.setItem("chauffeur_admin_token_for", "mj"); }', TOKENS['parent'])
    page.goto(served.url('dashboard_v2'), wait_until='networkidle')
    page.wait_for_function('() => typeof currentData !== "undefined" && currentData'
                           ' && document.getElementById("event-gev1_dropoff")'
                           ' && document.getElementById("event-gev1_pickup")', timeout=20000)


def _edit_span(page):
    return page.evaluate('() => [document.getElementById("edit-start").value, document.getElementById("edit-end").value]')


def scenario_the_leg_cards_open_the_whole_event():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_viewport_size({'width': 1280, 'height': 900})
            _open(page, served)
            whole = page.evaluate('() => [currentEventsMap.gev1.start, currentEventsMap.gev1.end]')
            check(whole[0][11:16] == '16:00' and whole[1][11:16] == '19:00', f"the whole event is in the page data: {whole}")

            # The drop-off card: the whole span, and which drive this is.
            page.evaluate('() => openEventModal("gev1_dropoff", "")')
            page.wait_for_selector('#modal-view-mode:not(.hidden)', timeout=5000)
            shown = page.inner_text('#view-time')
            check('4:00' in shown and '7:00' in shown, f"view mode shows the whole span, not a zero-length leg: {shown!r}")
            leg = page.inner_text('#view-leg')
            check('Drop-off drive' in leg, f"the card says which drive it is: {leg!r}")
            os.makedirs(SHOTS, exist_ok=True)
            page.screenshot(path=os.path.join(SHOTS, 'leg_editor_view.png'))

            page.evaluate('() => switchToEditMode()')
            page.wait_for_selector('#modal-edit-mode:not(.hidden)', timeout=5000)
            span = _edit_span(page)
            check(span[0].endswith('T16:00') and span[1].endswith('T19:00'), f"the editor holds the whole span: {span}")
            page.screenshot(path=os.path.join(SHOTS, 'leg_editor_edit.png'))

            # Switch to stay and save: the config write carries the mode and
            # NO calendar write fires.
            page.evaluate('''() => {
                window.__calls = [];
                const real = window.fetch;
                window.fetch = (url, opts) => { window.__calls.push([String(url), (opts || {}).method || 'GET', (opts || {}).body || null]); return real(url, opts); };
            }''')
            page.select_option('#edit-attendance-mode', 'stay')
            page.click('#save-config-btn')
            page.wait_for_function('() => document.getElementById("event-modal").classList.contains("hidden")', timeout=5000)
            page.wait_for_function('() => window.__calls.some(c => c[0].includes("api/events/config/"))', timeout=5000)
            calls = page.evaluate('() => window.__calls')
            config = [c for c in calls if 'api/events/config/gev1' in c[0] and c[1] == 'POST']
            patches = [c for c in calls if c[0].endswith('api/events') and c[1] == 'PATCH']
            check(config and '"driver_attendance_mode":"stay"' in config[0][2], f"the config write carries stay: {calls}")
            check(patches == [], f"a save from a leg never writes times to the calendar: {patches}")
            saved = storage.get_event_config('gev1') or {}
            check(saved.get('driver_attendance_mode') == 'stay', f"stored: {saved}")

            # The pick-up card: the same.
            page.evaluate('() => openEventModal("gev1_pickup", "")')
            page.wait_for_selector('#modal-view-mode:not(.hidden)', timeout=5000)
            shown = page.inner_text('#view-time')
            leg = page.inner_text('#view-leg')
            check('4:00' in shown and '7:00' in shown and 'Pick-up drive' in leg, f"{shown!r} {leg!r}")
            page.evaluate('() => switchToEditMode()')
            page.wait_for_selector('#modal-edit-mode:not(.hidden)', timeout=5000)
            span = _edit_span(page)
            check(span[0].endswith('T16:00') and span[1].endswith('T19:00'), f"{span}")
            page.evaluate('() => closeEventModal()')

            # The whole event has no leg line.
            page.evaluate('() => openEventModal("gev1", "")')
            page.wait_for_selector('#modal-view-mode:not(.hidden)', timeout=5000)
            hidden = page.evaluate('() => document.getElementById("view-leg").classList.contains("hidden")'
                                   ' || !document.getElementById("view-leg").textContent.trim()')
            check(hidden, "a whole event says nothing about legs")
            page.evaluate('() => closeEventModal()')

            # Belt and braces: the payload builder never writes times from a leg.
            details = page.evaluate('''() => {
                const leg = currentEventsMap.gev1_dropoff;
                const v = { scope: 'instance', start: '2030-01-01T09:00', end: '2030-01-01T09:00', location: leg.location,
                            attendance_mode: 'stay', passenger_ids: [], passenger_times: {}, driver_ids: [],
                            assist_contact_id: '', is_optional: false, is_trip: false, trip_id: '' };
                return eventConfigPayload(leg, v, null).details;
            }''')
            check(details is None, f"a leg with moved times still writes no details: {details}")
            check(not errors, f"the page threw: {errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    scenario_the_leg_cards_open_the_whole_event()
    print('  ok  scenario_the_leg_cards_open_the_whole_event')
    print('leg-editor live scenarios passed')
