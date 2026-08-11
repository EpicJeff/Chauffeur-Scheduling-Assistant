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
