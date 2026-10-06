"""The Schedule page's Inbox dialog, driven in a real browser.

An event nobody has configured yet lands in the inbox. The inbox used to be
a strip of cards above the timeline whose click opened the event modal
straight into edit mode; it is now a dialog behind the control bar's Inbox
button: the waiting events on the left, the selected one's setup on the
right (the same form the event modal draws), staged until Save.

Kept from the first version of this file: the setup form ticks each driver's
chip from `driver_events[d.id]` — but `driver_events` belongs to the
`schedule.driver_calendars` facet, and `scope.redact_schedule_blob` REMOVES
the key (never empties it) for a viewer who does not reach that facet. So for
such a viewer the form died on

    Cannot read properties of undefined (reading '<driver id>')

and never drew. A missing key reads as "not yours to know"; the builder has
to read it that way too.

A browser, because the breaks only exist at runtime: the button, the fetch,
the shared form builder and the staged drafts all have to meet.

Run from chauffeur/:  python tests/test_triage_edit_live.py
"""
import datetime
import os

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage

NOW = datetime.datetime.now()
HOME = '1 Home St'
SHOT_DIR = os.environ.get('CHAUFFEUR_SHOT_DIR')


def _first_start():
    # Late enough to still be ahead of us whenever the suite runs.
    if NOW.hour < 22:
        return datetime.datetime.combine(NOW.date(), datetime.time(23, 0))
    return datetime.datetime.combine(NOW.date() + datetime.timedelta(days=1), datetime.time(17, 0))


def _serve(drive):
    """Seed two waiting events (the second two days out, beyond the day the
    page opens on), serve the page, open the Inbox and hand the page to
    `drive`."""
    from live_app import live_app
    from services import calendar as cal_svc
    from models.schemas import Event
    import main

    first = _first_start()
    later = datetime.datetime.combine(first.date() + datetime.timedelta(days=2), datetime.time(16, 0))
    protos = [
        dict(id='gev1', title='Brand new thing', start=first,
             end=first + datetime.timedelta(minutes=30), location='2 Corner Rd',
             description='', calendar_ids=['cal_lily'], source_event_ids=['cal_lily::gev1']),
        dict(id='gev2', title='Robotics club', start=later,
             end=later + datetime.timedelta(minutes=90), location='3 Lab Way',
             description='', calendar_ids=['cal_lily'], source_event_ids=['cal_lily::gev2']),
    ]
    real_fetch = cal_svc.fetch_upcoming_events
    real_update = cal_svc.update_event_details

    def seed():
        for t in ('drivers_table', 'passengers_table', 'members_table',
                  'daily_schedules_table', 'custom_schedules_table',
                  'settings_table', 'event_configs_table', 'rules_table',
                  'overrides_table'):
            tbl = getattr(storage, t, None)
            if tbl is not None:
                tbl.truncate()
        storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                       'days_to_build': 4, 'home_location': HOME})
        storage.add_driver({'id': 'vovo', 'name': 'Vovo', 'color_code': '#4ade80',
                            'group': 'primary', 'priority_index': 1,
                            'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'p1', 'name': 'Lily',
                               'calendar_ids': ['cal_lily'], 'hashtags': []})
        # No event_config for either: that is what puts them in the inbox.
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**p) for p in protos]
        cal_svc.update_event_details = lambda *a, **k: None
        # The full-horizon build — the one the Inbox reads.
        main.refresh_schedule_logic(None, None, force_refresh=True)

    try:
        served = live_app(seed)
        if served is None:
            return None
        try:
            with served.browser() as page:
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.set_viewport_size({'width': 1320, 'height': 950})
                page.goto(served.url('dashboard_v2'), wait_until='networkidle')
                return drive(page, errors)
        finally:
            served.stop()
    finally:
        cal_svc.fetch_upcoming_events = real_fetch
        cal_svc.update_event_details = real_update


def _open_inbox(page, drop_driver_events=False):
    page.wait_for_function(
        '() => document.getElementById("inbox-count").textContent === "2"', timeout=15000)
    if drop_driver_events:
        # Exactly what redact_schedule_blob serves a viewer who does not
        # reach schedule.driver_calendars.
        page.evaluate('''() => {
            const orig = window.fetchTriage;
            window.fetchTriage = async () => { const d = await orig(); delete d.driver_events; return d; };
        }''')
    # DOM clicks: the sign-in overlay covers the page for an unclaimed test
    # household, and the handlers are the thing under test.
    page.evaluate('() => document.getElementById("inbox-btn").click()')
    page.wait_for_selector('#triage-form #triage-drivers-container .drv-checkbox', state='attached',
                           timeout=15000)


def _state(page):
    return page.evaluate('''() => ({
        open: !document.getElementById("triage-modal").classList.contains("hidden"),
        rows: [...document.querySelectorAll("#triage-list [id^=triage-row-]")].map(r => r.id),
        chips: [...document.querySelectorAll("#triage-form .drv-checkbox")].map(c => c.value),
        checked: [...document.querySelectorAll("#triage-form .drv-checkbox:checked")].map(c => c.value),
        save: document.getElementById("triage-save-btn").textContent.trim(),
        saveDisabled: document.getElementById("triage-save-btn").disabled,
        edited: [...document.querySelectorAll("#triage-list [id^=triage-row-]")]
            .filter(r => r.textContent.includes("Edited")).map(r => r.id),
    })''')


def _tick_vovo(page):
    page.evaluate('''() => {
        const cb = document.querySelector('#triage-form .drv-checkbox[value="vovo"]');
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event("change", { bubbles: true }));
    }''')


def _select(page, eid):
    page.evaluate(f'() => document.getElementById("triage-row-{eid}").click()')
    page.wait_for_function(
        f'() => document.getElementById("triage-row-{eid}").classList.contains("ring-2")'
        ' && document.querySelector("#triage-form .drv-checkbox")', timeout=10000)
    page.wait_for_timeout(300)


def scenario_inbox_opens_when_driver_calendars_are_redacted():
    def drive(page, errors):
        _open_inbox(page, drop_driver_events=True)
        return _state(page), errors
    got = _serve(drive)
    if got is None:
        return
    state, errors = got
    check(not errors, "opening the inbox threw: %s" % errors)
    check(state['open'] and state['chips'] == ['vovo'],
          "the driver chips were not drawn: %r" % state)


def scenario_inbox_lists_every_waiting_event_not_just_the_loaded_day():
    def drive(page, errors):
        _open_inbox(page)
        return _state(page), errors
    got = _serve(drive)
    if got is None:
        return
    state, errors = got
    check(not errors, "opening the inbox threw: %s" % errors)
    check(state['rows'] == ['triage-row-gev1', 'triage-row-gev2'],
          "both waiting events are listed, in time order: %r" % state['rows'])
    check(state['saveDisabled'] and state['save'] == 'Save',
          "nothing to save before anything changed: %r" % state)


def scenario_answers_are_staged_until_save_then_saved_together():
    posts = []

    def drive(page, errors):
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and '/api/events/config' in r.url else None)
        _open_inbox(page)
        _tick_vovo(page)
        after_tick = _state(page)
        _select(page, 'gev2')
        _select(page, 'gev1')
        returned = _state(page)
        before_save = list(posts)
        if SHOT_DIR:
            page.screenshot(path=os.path.join(SHOT_DIR, 'triage_inbox.png'))
        page.evaluate('() => document.getElementById("triage-save-btn").click()')
        page.wait_for_function(
            '() => document.getElementById("triage-modal").classList.contains("hidden")', timeout=15000)
        return after_tick, returned, before_save, list(posts), errors
    got = _serve(drive)
    if got is None:
        return
    after_tick, returned, before_save, all_posts, errors = got
    check(not errors, "the inbox threw: %s" % errors)
    check(after_tick['edited'] == ['triage-row-gev1'] and after_tick['save'] == 'Save 1 change',
          "a change marks its row and arms Save: %r" % after_tick)
    check(returned['checked'] == ['vovo'],
          "coming back to an event shows what was staged for it: %r" % returned)
    check(before_save == [], "nothing was saved before Save: %r" % before_save)
    check(len(all_posts) == 1 and all_posts[0].endswith('/api/events/config/batch'),
          "Save is one batch request: %r" % all_posts)
    cfg = storage.get_event_config('gev1') or {}
    check(cfg.get('driver_ids') == ['vovo'], "the staged driver was saved: %r" % cfg)
    check(storage.get_event_config('gev2') is None,
          "an event only looked at is not saved: %r" % storage.get_event_config('gev2'))


def scenario_closing_with_changes_asks_and_discard_saves_nothing():
    def drive(page, errors):
        _open_inbox(page)
        _tick_vovo(page)
        page.evaluate('() => document.getElementById("triage-modal").querySelector("[aria-label=Close]").click()')
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        asked = page.evaluate('() => [...document.querySelectorAll("#cc-choice-options button")].map(b => b.textContent)')
        page.evaluate('''() => [...document.querySelectorAll("#cc-choice-options button")]
            .find(b => b.textContent.startsWith("Discard")).click()''')
        page.wait_for_function(
            '() => document.getElementById("triage-modal").classList.contains("hidden")', timeout=5000)
        return asked, errors
    got = _serve(drive)
    if got is None:
        return
    asked, errors = got
    check(not errors, "the inbox threw: %s" % errors)
    check(asked == ['Save 1 change', 'Discard changes'], "the question offers both: %r" % asked)
    check(storage.get_event_config('gev1') is None, "Discard saved nothing")


def scenario_a_failed_event_keeps_the_dialog_open_on_it():
    def drive(page, errors):
        # The server's own answer when one event's calendar write misses.
        page.route('**/api/events/config/batch', lambda route: route.fulfill(
            status=200, content_type='application/json',
            body='{"results":[{"key":"gev1","ok":false,"error":"The setup saved, but the new time could not be written to Google Calendar. (quota)"},'
                 '{"key":"gev2","ok":true}],"saved":1,"failed":1}'))
        _open_inbox(page)
        _tick_vovo(page)
        _select(page, 'gev2')
        _tick_vovo(page)
        page.evaluate('() => document.getElementById("triage-save-btn").click()')
        page.wait_for_selector('#triage-list :text("Not saved")', timeout=10000)
        page.wait_for_timeout(300)
        st = _state(page)
        st['head'] = page.evaluate('() => document.getElementById("triage-detail-head").textContent')
        st['status'] = page.evaluate('() => document.getElementById("triage-status").textContent')
        return st, errors
    got = _serve(drive)
    if got is None:
        return
    st, errors = got
    check(not errors, "the inbox threw: %s" % errors)
    check(st['open'], "a failure keeps the dialog open")
    check(st['rows'] == ['triage-row-gev1'], "what saved leaves, what failed stays: %r" % st['rows'])
    check('Google Calendar' in st['head'], "the failed event says why: %r" % st['head'])
    check(st['checked'] == ['vovo'], "its staged answers are still there: %r" % st)
    check('could not be saved' in st['status'], "the footer says so: %r" % st['status'])


def scenario_the_event_modal_still_draws_the_shared_form():
    def drive(page, errors):
        page.wait_for_function('() => typeof currentEventsMap !== "undefined" && currentEventsMap["gev1"]', timeout=15000)
        page.evaluate('() => openEventModal("gev1")')
        page.wait_for_selector('#edit-form #edit-drivers-container .drv-checkbox', state='attached', timeout=10000)
        return page.evaluate('''() => {
            const v = eventConfigFormRead("edit");
            const ev = { id: "i1", source_event_ids: ["cal::inst1"], recurring_event_id: "ser1",
                         start: "2026-01-01T10:00:00", end: "2026-01-01T11:00:00" };
            return {
                editing: !document.getElementById("modal-edit-mode").classList.contains("hidden"),
                ids: ["edit-start", "edit-end", "edit-location", "edit-assist-contact", "edit-trip-id"]
                    .filter(id => !document.getElementById(id)),
                untouched: eventConfigPayload(Object.assign({}, currentEventsMap["gev1"]), v, v).details,
                series: eventConfigPayload(ev, Object.assign({}, v, { scope: "series" }), null).google_id,
                instance: eventConfigPayload(ev, Object.assign({}, v, { scope: "instance" }), null).google_id,
            };
        }'''), errors
    got = _serve(drive)
    if got is None:
        return
    st, errors = got
    check(not errors, "the event modal threw: %s" % errors)
    check(st['editing'] and not st['ids'], "edit mode draws the shared form: %r" % st)
    check(st['untouched'] is None,
          "an untouched time never rewrites the Google event: %r" % st['untouched'])
    check(st['series'] == 'ser1' and st['instance'] == 'inst1',
          "the scope row picks the series or the occurrence: %r" % st)


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d inbox scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
