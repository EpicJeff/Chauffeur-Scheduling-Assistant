"""Intake approve-as-configure: the card is the WHOLE editor.

The old flow was approve → open Google Calendar to fix the location or set
recurrence → open the schedule → find the event in the inbox → configure who
rides. Approval now carries all of it:

  1. **Edited location, description and recurrence land on the Google event**
     — location resolved to a routable address, the source attribution line
     kept under any edited description, RRULE matching DTSTART's value type.
  2. **Attendees picked on the card become the Chauffeur event config**,
     keyed by the new google id (a recurring series' instances find it via
     their recurring_event_id fallback) — so the event never lands in the
     schedule inbox as "Needs Setup".
  3. **No attendees -> no config.** The inbox stays the honest state for a
     ride nobody has claimed; approval must not silently vouch for it.

Run from chauffeur/:  python tests/test_intake_approval.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()


def _reset():
    with storage.db_lock:
        storage.event_proposals_table.truncate()
        storage.event_configs_table.truncate()


def _proposal(**over):
    base = {'title': "Volleyball practice", 'kind': 'event',
            'start': f"{TODAY.isoformat()}T17:00:00",
            'end': f"{TODAY.isoformat()}T18:30:00", 'all_day': False,
            'location': 'apex gym', 'notes': 'extracted note',
            'source_from': 'coach@club.org', 'source_subject': 'Fall schedule'}
    base.update(over)
    return storage.add_proposal(base)


def _reset_tasks():
    with storage.db_lock:
        storage.household_tasks_table.truncate()


def scenario_the_card_is_the_whole_editor():
    import main
    _reset()
    pid = _proposal()
    inserted = {}

    def fake_insert(calendar_id, body):
        inserted['calendar_id'] = calendar_id
        inserted['body'] = body
        return 'gid123'

    with mock.patch('services.calendar.insert_event', side_effect=fake_insert), \
         mock.patch('services.calendar.get_calendar_timezone', return_value='America/New_York'), \
         mock.patch('services.maps.resolve_routable_location',
                    side_effect=lambda x: f"{x} (routable)"):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', location='Apex Volleyball Club',
            description='Bring knee pads', recurrence='weekly',
            recurrence_until='2026-12-15',
            passenger_ids=['p1'], driver_ids=['d1']), mock.MagicMock())

    body = inserted['body']
    check(res['status'] == 'approved' and res['event_id'] == 'gid123', f"got {res}")
    check(body['location'] == 'Apex Volleyball Club (routable)',
          f"the EDITED location wins over the extraction, routable: {body.get('location')}")
    check(body['description'].startswith('Bring knee pads')
          and 'From family email: coach@club.org' in body['description'],
          f"edited description leads, attribution survives: {body['description']!r}")
    check(body['recurrence'] == ['RRULE:FREQ=WEEKLY;UNTIL=20261215T235959Z'],
          f"weekly with an end, UTC form for a timed event: {body.get('recurrence')}")

    conf = storage.get_event_config('gid123')
    check(conf and conf['passenger_ids'] == ['p1'] and conf['driver_ids'] == ['d1'],
          f"attendees became the event config, keyed by the new google id: {conf}")
    check(storage.get_proposal(pid)['status'] == 'approved', "proposal resolved")
    check('🚗' in res.get('message', '') and '🔁' in res.get('message', ''),
          f"the message says both halves happened: {res.get('message')!r}")


def scenario_recurrence_matches_dtstarts_value_type():
    """RFC5545: UNTIL must be a DATE for all-day events, UTC date-time for
    timed ones — and an unknown cadence is a 400, not a silent drop."""
    import main
    from fastapi import HTTPException
    _reset()

    pid = _proposal(all_day=True, start=TODAY.isoformat(), end=TODAY.isoformat())
    inserted = {}
    with mock.patch('services.calendar.insert_event',
                    side_effect=lambda c, b: inserted.update(body=b) or 'gid_ad'), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', recurrence='biweekly',
            recurrence_until='2026-12-15'), mock.MagicMock())
    check(inserted['body']['recurrence'] == ['RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20261215'],
          f"all-day: INTERVAL=2 and a DATE-form UNTIL: {inserted['body'].get('recurrence')}")

    pid2 = _proposal()
    inserted2 = {}
    with mock.patch('services.calendar.insert_event',
                    side_effect=lambda c, b: inserted2.update(body=b) or 'gid_open'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        main.approve_proposal(pid2, main.ProposalApprove(
            calendar_id='cal1', recurrence='monthly'), mock.MagicMock())
    check(inserted2['body']['recurrence'] == ['RRULE:FREQ=MONTHLY'],
          f"no end date -> an open rule: {inserted2['body'].get('recurrence')}")

    pid3 = _proposal()
    try:
        with mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
             mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
            main.approve_proposal(pid3, main.ProposalApprove(
                calendar_id='cal1', recurrence='fortnightly'), mock.MagicMock())
        check(False, "an unknown cadence must 400")
    except HTTPException as e:
        check(e.status_code == 400, f"unknown recurrence refused: {e.detail}")
    check(storage.get_proposal(pid3)['status'] == 'proposed',
          "and the proposal is untouched — nothing was inserted")


def scenario_no_attendees_means_no_config():
    """Approval without a who-rides pick must NOT vouch for the event: the
    schedule inbox stays the honest state for a ride nobody has claimed."""
    import main
    _reset()
    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_bare'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        res = main.approve_proposal(pid, main.ProposalApprove(calendar_id='cal1'),
                                    mock.MagicMock())
    check(res['status'] == 'approved', f"got {res}")
    check(storage.get_event_config('gid_bare') is None,
          "no attendees picked -> no event config written")
    with storage.db_lock:
        check(len(storage.event_configs_table.all()) == 0, "nothing else either")


def scenario_untouched_cards_round_trip_the_extraction():
    """Omitted fields keep the proposal's own values — the fast path (pick a
    calendar, tap Approve) must behave exactly as it always has."""
    import main
    _reset()
    pid = _proposal()
    inserted = {}
    with mock.patch('services.calendar.insert_event',
                    side_effect=lambda c, b: inserted.update(body=b) or 'gid_plain'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location',
                    side_effect=lambda x: f"{x} (routable)"):
        main.approve_proposal(pid, main.ProposalApprove(calendar_id='cal1'),
                              mock.MagicMock())
    body = inserted['body']
    check(body['location'] == 'apex gym (routable)',
          f"the extracted location still resolves and rides along: {body.get('location')}")
    check(body['description'].startswith('extracted note'),
          f"the extracted notes still lead the description: {body['description']!r}")
    check('recurrence' not in body, "no recurrence unless asked for")


def scenario_the_household_list_is_a_reachable_target():
    """The `household_task` branch shipped with load arc A2 and no dropdown
    ever offered it, so a household to-do's only plausible target was
    somebody's calendar — where it became an invisible all-day event."""
    import main
    _reset()
    with storage.db_lock:
        storage.household_tasks_table.truncate()
    pid = _proposal(kind='task', title='📌 Send $12 for picture day',
                    all_day=True, start=TODAY.isoformat(), end=TODAY.isoformat(),
                    location=None)
    res = main.approve_proposal(pid, main.ProposalApprove(calendar_id='household_task'),
                                mock.MagicMock())
    check(res['status'] == 'approved' and 'household list' in res['message'],
          f"the target resolves to a real HouseholdTask: {res}")
    rows = storage.get_household_tasks()
    check(len(rows) == 1 and rows[0]['due_date'] == TODAY.isoformat(),
          f"with its due date intact: {rows}")

    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    for name in ('intake.html', 'app.html'):
        src = open(os.path.join(tpl, name), encoding='utf-8').read()
        check("'household_task'" in src and 'Household list' in src,
              f"{name} offers the household list as a target by hand")


def scenario_misfiled_todos_are_found_from_the_ledger_not_the_calendar():
    """Exact, not guessed: the other three approval branches write
    created_task_id/created_errand_id, so a task-kind proposal carrying
    created_event_id means precisely 'a to-do that became a calendar event'."""
    import main
    _reset()
    with storage.db_lock:
        storage.household_tasks_table.truncate()

    bad = storage.add_proposal({'title': '📌 Permission slip due', 'kind': 'task',
                                'status': 'approved', 'start': TODAY.isoformat(),
                                'end': TODAY.isoformat(), 'all_day': True,
                                'notes': 'signed copy to homeroom',
                                'calendar_id': 'cal1', 'created_event_id': 'gid_bad'})
    # Three things that must NOT be collected:
    storage.add_proposal({'title': 'Volleyball', 'kind': 'event', 'status': 'approved',
                          'start': TODAY.isoformat(), 'calendar_id': 'cal1',
                          'created_event_id': 'gid_event'})       # a real event
    storage.add_proposal({'title': '📌 Buy poster board', 'kind': 'task',
                          'status': 'approved', 'start': TODAY.isoformat(),
                          'calendar_id': 'errand', 'created_errand_id': 'e1'})  # errand
    storage.add_proposal({'title': '📌 Waiting', 'kind': 'task', 'status': 'proposed',
                          'start': TODAY.isoformat()})                          # unapproved

    rows = main.list_misfiled_proposals()
    check(len(rows) == 1 and rows[0]['id'] == bad,
          f"only the to-do that landed on a calendar is collected: {rows}")
    check(rows[0]['title'] == 'Permission slip due',
          f"and the 📌 is a proposal convention, not part of the job: {rows[0]['title']!r}")

    removed = {}
    with mock.patch('services.calendar.remove_event',
                    side_effect=lambda c, e: removed.update(cal=c, ev=e) or True):
        res = main.refile_proposal(bad, mock.MagicMock())
    check(res['status'] == 'refiled', f"got {res}")
    check(removed == {'cal': 'cal1', 'ev': 'gid_bad'},
          f"the stray calendar event is taken back off: {removed}")
    tasks = storage.get_household_tasks()
    check(len(tasks) == 1 and tasks[0]['title'] == 'Permission slip due'
          and tasks[0]['due_date'] == TODAY.isoformat()
          and tasks[0]['notes'] == 'signed copy to homeroom',
          f"the household task carries title, due date and notes: {tasks}")
    check(not main.list_misfiled_proposals(),
          "and the item leaves the rescue list — the ledger now says household_task")

    from fastapi import HTTPException
    try:
        main.refile_proposal(bad, mock.MagicMock())
        check(False, "refiling twice must refuse")
    except HTTPException as e:
        check(e.status_code == 400, f"a second refile is refused: {e.detail}")
    check(len(storage.get_household_tasks()) == 1, "so no duplicate task is created")


def scenario_the_calendar_shows_what_the_solver_cannot_drive_to():
    """A no-school day, a birthday, 'Dad in Chicago' — all-day events were
    dropped at fetch and so appeared on NO Chauffeur screen, which made the
    calendar a view of the driving schedule instead of the family's life.

    They must reach the UI payload and stop there: a midnight-to-midnight
    span overlaps every drive that day, and matcher 3c bans a driver from any
    event truly overlapping one of their personal events."""
    import inspect
    import main

    class _Ev:
        def __init__(self, all_day=False, event_type='standard'):
            self.all_day, self.event_type = all_day, event_type

    check(main.is_display_only_event(_Ev(all_day=True)),
          "an all-day event is display-only")
    check(not main.is_display_only_event(_Ev(all_day=False)),
          "a timed event is the solver's business as always")
    check(not main.is_display_only_event(_Ev(all_day=True, event_type='background_trip')),
          "an all-day TRIP is scheduling information — the one exception")

    src = inspect.getsource(main._refresh_schedule_logic_impl)
    head, rest = src.split('all_fetched_events.append(e)', 1)
    check('continue' not in head.split('for e in raw_events:', 1)[1],
          "nothing is dropped for being all-day at fetch time any more")
    before, after = rest.split('all_events_for_ui[e.id] = e', 1)
    check('is_display_only_event' in after.split('# 2. Check Passengers')[0],
          "the guard sits AFTER the UI payload — the family sees the event")
    guard = after.split('is_display_only_event')[0]
    for downstream in ('needs_triage', 'driver_events_map', 'events.append(e)'):
        check(downstream not in guard,
              f"...and BEFORE {downstream}, so the solver never sees it")


def scenario_the_hand_path_carries_it_all():
    """BOTH approval surfaces — /intake and the PWA Family tab — carry the
    whole editor, and both location fields search real places through the
    same Mapbox /api/places pair the errands page uses."""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    intake = open(os.path.join(tpl, 'intake.html'), encoding='utf-8').read()
    for needle, what in (("p._location", "location edit"),
                         ("p._description", "description edit"),
                         ("p._recurrence", "recurrence picker"),
                         ("Who's going?", "attendee chips"),
                         ("onTargetChange", "picking a kid's calendar pre-checks that kid"),
                         ("api/places/autocomplete", "Mapbox place search"),
                         ("api/places/retrieve", "canonical name+address retrieve")):
        check(needle in intake, f"the intake card carries the {what}")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    for needle, what in (("proposalIsCalTarget", "target-aware editor"),
                         ('data-role="f-loc"', "location edit"),
                         ('data-role="f-desc"', "description edit"),
                         ('data-role="f-rec"', "recurrence picker"),
                         ("data-pax-id", "attendee chips"),
                         ("prefillProposalPax", "picking a kid's calendar pre-checks that kid"),
                         ("api/places/autocomplete", "Mapbox place search"),
                         ("api/places/retrieve", "canonical name+address retrieve")):
        check(needle in app, f"the PWA approval card carries the {what}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} intake-approval scenarios passed")
