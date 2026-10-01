"""Opening an inbox event on the Schedule page must not throw.

An event nobody has configured yet lands in the "needs setup" inbox, and
clicking it opens the event modal straight into edit mode
(`switchToEditMode`). That builder ticked each driver's chip from
`currentData.driver_events[d.id]` -- but `driver_events` belongs to the
`schedule.driver_calendars` facet, and `scope.redact_schedule_blob` REMOVES
the key (never empties it) for any viewer who does not reach that facet. So
for such a viewer the click died on

    Cannot read properties of undefined (reading '<driver id>')

and the modal never opened. A missing key reads as "not yours to know"; the
builder has to read it that way too.

A browser, because the break only exists at runtime: the inbox card's inline
onclick, the modal builder and the payload all have to meet.

Run from chauffeur/:  python tests/test_triage_edit_live.py
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()
HOME = '1 Home St'


def _open_inbox_event(drop_driver_events):
    from live_app import live_app
    from services import calendar as cal_svc
    from models.schemas import Event
    import main

    start = datetime.datetime.combine(TODAY, datetime.time(23, 0))
    proto = dict(id='gev1', title='Brand new thing', start=start,
                 end=start + datetime.timedelta(minutes=30),
                 location='2 Corner Rd', description='',
                 calendar_ids=['cal_lily'], source_event_ids=['gev1'])
    real_fetch = cal_svc.fetch_upcoming_events

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
        storage.add_driver({'id': 'vovo', 'name': 'Vovo', 'color_code': '#4ade80',
                            'group': 'primary', 'priority_index': 1,
                            'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'p1', 'name': 'Lily',
                               'calendar_ids': ['cal_lily'], 'hashtags': []})
        # No event_config for gev1: that is what puts it in the inbox.
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**proto)]
        main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(),
                                    force_refresh=True)

    errors = []
    try:
        served = live_app(seed)
        if served is None:
            return None
        try:
            with served.browser() as page:
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.set_viewport_size({'width': 1320, 'height': 950})
                page.goto(served.url('dashboard_v2'), wait_until='networkidle')
                page.wait_for_selector('#inbox-list #event-gev1', timeout=15000)
                if drop_driver_events:
                    # Exactly what redact_schedule_blob serves a viewer who
                    # does not reach schedule.driver_calendars.
                    page.evaluate('() => { delete currentData.driver_events; }')
                # A DOM click: the sign-in overlay covers the page for an
                # unclaimed test household, and the inline onclick is the
                # thing under test.
                page.evaluate('() => document.querySelector("#inbox-list #event-gev1").click()')
                page.wait_for_timeout(500)
                state = page.evaluate(
                    '() => ({'
                    ' open: !document.getElementById("event-modal").classList.contains("hidden"),'
                    ' editing: !document.getElementById("modal-edit-mode").classList.contains("hidden"),'
                    ' chips: [...document.querySelectorAll(".drv-checkbox")].map(c => c.value)'
                    '})')
        finally:
            served.stop()
    finally:
        cal_svc.fetch_upcoming_events = real_fetch
    return state, errors


def scenario_inbox_event_opens_when_driver_calendars_are_redacted():
    got = _open_inbox_event(drop_driver_events=True)
    if got is None:
        return
    state, errors = got
    check(not errors, "clicking the inbox event threw: %s" % errors)
    check(state['open'] and state['editing'],
          "the triage modal did not open in edit mode: %r" % state)
    check(state['chips'] == ['vovo'],
          "the driver chips were not drawn: %r" % state['chips'])


def scenario_inbox_event_opens_for_a_full_viewer():
    got = _open_inbox_event(drop_driver_events=False)
    if got is None:
        return
    state, errors = got
    check(not errors, "clicking the inbox event threw: %s" % errors)
    check(state['open'] and state['editing'],
          "the triage modal did not open in edit mode: %r" % state)


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d triage-edit scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
