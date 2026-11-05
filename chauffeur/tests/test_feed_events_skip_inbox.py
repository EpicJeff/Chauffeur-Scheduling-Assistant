"""Feed events skip the inbox; Ignore means shown, never driven.

User (2026-11-05): "A large majority of the events on our calendars are
events that come from connected ICS calendars ... every event on an ICS
calendar has to be triaged. I don't think those ICS events should even go
through the inbox. The act of adding the ICS calendar is me as an admin
saying 'add all of these events to the schedule'." And: "anything that goes
through intake should not need triaging." And, on what a feed switched off
means: "the same as setting 'Ignore event' on every event in the feed",
where Ignore means "shown in the calendar but never driven".

What was true:
  * the ICS sync writes every occurrence into Google as its own event, so no
    two share a series and every one landed in the inbox; an event in the
    inbox is skipped by the solve, so a game nobody triaged had no driver;
  * the sync tags each copy with extendedProperties.private.ics_feed_id but
    the calendar fetch never read it;
  * Ignore dropped the event before the UI list was built, so an ignored
    event vanished from every screen, not just the driving schedule, and
    nothing listed it to undo;
  * an intake card approved with nobody picked wrote no setup, so the event
    went to the inbox.

Pinned by RUNNING the fetch and the refresh:
  * the fetch carries ics_feed_id onto the Event, also through a merge with
    a manual copy of the same event;
  * a feed in the driving schedule (the default, and every feed saved before
    the switch existed): its events never need triage and are driven with
    the defaults (the rider is the calendar's owner);
  * a feed switched off: every event is ignored unless its own setup says
    is_ignored False, which drives it; a per-event Ignore on a feed that is
    on still ignores that one event;
  * an ignored event stays in the schedule's events with `ignored` True and
    never reaches the solve, the inbox, driver_events or the household
    briefing's open list;
  * an event tagged with a feed that no longer exists, and a plain event
    with no setup, still go to the inbox;
  * the feed API stores the switch on create, lists it (true when absent),
    and a change through PUT re-solves;
  * an intake card approved with nobody picked still saves a setup, so the
    event is driven by its calendar and never reaches the inbox.

Run from chauffeur/:  python tests/test_feed_events_skip_inbox.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR, mocks maps)

from services import storage

TODAY = datetime.date.today()
HOME = '1 Home St'


def _ten_minutes_apart(origin, destination, departure_time=None, return_traffic=False):
    same = not origin or not destination or origin.lower() == destination.lower()
    mins = 0 if same else 10
    return (mins, 0) if return_traffic else mins


def _at(h, m=0):
    return datetime.datetime.combine(TODAY, datetime.time(h, m))


def _ev(eid, cal, start, mins, location, title=None, feed=None):
    p = dict(id=eid, title=title or eid, start=start,
             end=start + datetime.timedelta(minutes=mins), location=location,
             description='', calendar_ids=[cal], source_event_ids=[eid])
    if feed:
        p['ics_feed_id'] = feed
    return p


def _household():
    for t in ('drivers_table', 'passengers_table', 'members_table',
              'daily_schedules_table', 'custom_schedules_table',
              'settings_table', 'event_configs_table', 'rules_table',
              'overrides_table', 'cache_table', 'inbox_table',
              'ics_feeds_table', 'event_proposals_table'):
        tbl = getattr(storage, t, None)
        if tbl is not None:
            tbl.truncate()
    storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                   'days_to_build': 1, 'home_location': HOME,
                                   'suggested_routes_enabled': False})
    storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#3b82f6',
                        'group': 'primary', 'priority_index': 1,
                        'calendar_ids': ['cal_jeff'], 'home_location': HOME})
    storage.add_passenger({'id': 'p1', 'name': 'Lily',
                           'calendar_ids': ['cal_lily'], 'hashtags': []})
    storage.add_member({'id': 'm_jeff', 'name': 'Jeff', 'role': 'parent',
                        'driver_id': 'd1', 'can_drive': True,
                        'calendar_ids': ['cal_jeff']})
    storage.add_member({'id': 'm1', 'name': 'Lily', 'role': 'child',
                        'passenger_id': 'p1', 'calendar_ids': ['cal_lily']})
    # A feed saved before the switch existed: no key at all. It is on.
    storage.add_ics_feed({'id': 'feed_legacy', 'url': 'webcal://a.example/x.ics',
                          'name': 'Lions', 'calendar_id': 'cal_lily',
                          'target_kind': 'calendar', 'teams': []})
    storage.add_ics_feed({'id': 'feed_on', 'url': 'webcal://b.example/y.ics',
                          'name': 'Surge', 'calendar_id': 'cal_lily',
                          'target_kind': 'calendar', 'teams': [],
                          'in_driving_schedule': True})
    storage.add_ics_feed({'id': 'feed_off', 'url': 'webcal://c.example/z.ics',
                          'name': 'Rec centre', 'calendar_id': 'cal_lily',
                          'target_kind': 'calendar', 'teams': [],
                          'in_driving_schedule': False})


def _solve(protos, setup=None, whole=False):
    import main
    from services import calendar as cal_svc
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher

    _household()
    if setup:
        setup()
    real_fetch = cal_svc.fetch_upcoming_events
    real_raw = matcher._raw_get_travel_time_minutes
    real_maps = maps.get_travel_time_minutes
    real_settings = storage.get_settings
    try:
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**p) for p in protos]
        storage.get_settings = lambda: dict(storage.settings_table.all()[0])
        matcher._raw_get_travel_time_minutes = _ten_minutes_apart
        maps.get_travel_time_minutes = _ten_minutes_apart
        # whole=True is the default build (no date range): the only one that
        # writes the global cache every reader (briefing, watchers) uses.
        if whole:
            res = main.refresh_schedule_logic(None, None, force_refresh=True)
        else:
            res = main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(),
                                              force_refresh=True)
    finally:
        cal_svc.fetch_upcoming_events = real_fetch
        matcher._raw_get_travel_time_minutes = real_raw
        maps.get_travel_time_minutes = real_maps
        storage.get_settings = real_settings
    check(not res.get('error'), "the day did not solve: %s" % res.get('error'))
    return res


def _event(res, eid):
    for e in res.get('events') or []:
        if e.get('id') == eid:
            return e
    return None


def _ours(ids, eid):
    return [k for k in ids if k == eid or str(k).startswith(eid + '_')]


def _driven_by(res, eid):
    a = res.get('assignments') or {}
    return {a[k] for k in _ours(a, eid)}


def _needs_triage(res, eid):
    return any(e.get('needs_triage') for e in res.get('events') or []
               if e.get('id') == eid or str(e.get('id')).startswith(eid + '_'))


def _check_ignored(res, eid, why):
    ev = _event(res, eid)
    check(ev is not None,
          "%s: the event is gone from the schedule's events, so the calendar "
          "cannot draw it (Ignore must mean shown, never driven)" % why)
    check(ev.get('ignored') is True, "%s: the event is not marked ignored: %r"
          % (why, {k: ev.get(k) for k in ('id', 'ignored', 'needs_triage')}))
    check(not _needs_triage(res, eid), "%s: the event went to the inbox" % why)
    check(not _ours(res.get('assignments') or {}, eid),
          "%s: the event was driven: %s" % (why, res.get('assignments')))
    check(not _ours(res.get('ghost_assignments') or {}, eid),
          "%s: the event got a ghost driver" % why)
    check(not _ours(res.get('unassigned') or [], eid),
          "%s: the event counts as an uncovered ride: %s" % (why, res.get('unassigned')))
    for d_id, ids in (res.get('driver_events') or {}).items():
        check(not _ours(ids, eid), "%s: the event reached %s's driver_events" % (why, d_id))


GAME = lambda feed, eid='game1': _ev(eid, 'cal_lily', _at(16), 60, '9 Field Rd',
                                     title='Vs Storm (Surge)', feed=feed)


def scenario_the_event_model_carries_the_feed():
    from models.schemas import Event
    ev = Event(**GAME('feed_on'))
    check(getattr(ev, 'ics_feed_id', None) == 'feed_on',
          "Event has no ics_feed_id field: the feed tag is dropped on the way in")
    check(getattr(Event(**GAME(None)), 'ignored', None) is False,
          "Event has no `ignored` field defaulting to False")


def scenario_the_fetch_reads_the_feed_tag():
    """The sync writes extendedProperties.private.ics_feed_id on every copy;
    the fetch must carry it, including when a manual copy of the same event
    on another calendar merges with the feed copy."""
    from services import calendar as cal_svc
    start = _at(16).astimezone().isoformat()
    end = _at(17).astimezone().isoformat()

    def item(gid, feed=None):
        it = {'id': gid, 'summary': 'Vs Storm (Surge)', 'location': '9 Field Rd',
              'start': {'dateTime': start}, 'end': {'dateTime': end}}
        if feed:
            it['extendedProperties'] = {'private': {'ics_feed_id': feed,
                                                    'ics_key': 'uid-1'}}
        return it

    pages = {'cal_lily': [item('gfeed', 'feed_on')],
             'cal_jeff': [item('gmanual')],
             'cal_solo': [{'id': 'gsolo', 'summary': 'Dentist', 'location': '3 Tooth Way',
                           'start': {'dateTime': _at(9).astimezone().isoformat()},
                           'end': {'dateTime': _at(10).astimezone().isoformat()}}]}
    real = cal_svc._fetch_single_calendar
    try:
        cal_svc._fetch_single_calendar = lambda cal_id, tmin, tmax: (cal_id, pages[cal_id])
        evs = cal_svc.fetch_upcoming_events(['cal_jeff', 'cal_lily', 'cal_solo'],
                                            start_date_str=TODAY.isoformat(),
                                            end_date_str=TODAY.isoformat())
    finally:
        cal_svc._fetch_single_calendar = real
    by_title = {e.title: e for e in evs}
    game = by_title.get('Vs Storm (Surge)')
    check(game is not None and sorted(game.calendar_ids) == ['cal_jeff', 'cal_lily'],
          "the two copies did not merge: %r" % [(e.title, e.calendar_ids) for e in evs])
    check(getattr(game, 'ics_feed_id', None) == 'feed_on',
          "the merged event lost the feed tag: %r" % getattr(game, 'ics_feed_id', None))
    check(getattr(by_title['Dentist'], 'ics_feed_id', 'missing') is None,
          "an event with no tag must carry ics_feed_id None")


def scenario_a_feed_in_the_schedule_skips_the_inbox():
    for feed in ('feed_on', 'feed_legacy'):
        res = _solve([GAME(feed)])
        check(not _needs_triage(res, 'game1'),
              "%s: a feed event with no setup went to the inbox" % feed)
        check(_driven_by(res, 'game1') == {'d1'},
              "%s: the feed event was not driven with the defaults (Lily's "
              "calendar, Jeff drives): %s" % (feed, res.get('assignments')))
        check(not (_event(res, 'game1') or {}).get('ignored'),
              "%s: a feed in the schedule marked its event ignored" % feed)


def scenario_a_feed_switched_off_is_ignored():
    _check_ignored(_solve([GAME('feed_off')]), 'game1', 'feed off')


def scenario_one_event_of_a_switched_off_feed_can_be_driven():
    def undo():
        storage.event_configs_table.insert({'google_id': 'game1', 'is_ignored': False})
    res = _solve([GAME('feed_off')], setup=undo)
    check(not (_event(res, 'game1') or {}).get('ignored'),
          "the event's own is_ignored False did not win over the feed")
    check(not _needs_triage(res, 'game1'), "the undone event went to the inbox")
    check(_driven_by(res, 'game1') == {'d1'},
          "the undone event was not driven: %s" % res.get('assignments'))


def scenario_one_event_of_a_feed_in_the_schedule_can_be_ignored():
    def ignore():
        storage.event_configs_table.insert({'google_id': 'game1', 'is_ignored': True})
    _check_ignored(_solve([GAME('feed_on')], setup=ignore), 'game1',
                   'per-event Ignore on a feed that is on')


def scenario_ignore_means_shown_never_driven():
    """The Ignore fix on its own: a plain Google event, and a series."""
    piano = _ev('piano', 'cal_lily', _at(15), 30, '4 Key St', title='Piano')
    swim = dict(_ev('swim_20261105', 'cal_lily', _at(18), 45, '7 Pool Ln', title='Swim'),
                recurring_event_id='swimseries')

    def ignore():
        storage.event_configs_table.insert({'google_id': 'piano', 'is_ignored': True})
        storage.event_configs_table.insert({'google_id': 'swimseries', 'is_ignored': True})
    res = _solve([piano, swim], setup=ignore)
    _check_ignored(res, 'piano', 'ignored one-off')
    _check_ignored(res, 'swim_20261105', 'ignored series')


def scenario_the_briefing_never_calls_an_ignored_event_open():
    from services import access, family_digest

    def ignore():
        storage.event_configs_table.insert({'google_id': 'piano', 'is_ignored': True})
    _solve([_ev('piano', 'cal_lily', _at(15), 30, '4 Key St', title='Piano')], setup=ignore,
           whole=True)
    cached = access.cached_schedule() or {}
    check(any(e.get('id') == 'piano' for e in cached.get('events') or []),
          "precondition: the cached schedule does not hold the ignored event")
    brief = family_digest.build_household_briefing(target_date=TODAY)
    lines = ' | '.join(str(x) for x in brief.get('lines') or [])
    check('Piano' not in lines,
          "the household briefing lists an ignored event as an opening: %s" % lines)


def scenario_unknown_feeds_and_plain_events_still_go_to_the_inbox():
    gone = GAME('feed_deleted', eid='game_gone')
    plain = _ev('plain', 'cal_lily', _at(11), 60, '2 Hall Rd', title='Birthday party')
    res = _solve([gone, plain])
    check(_needs_triage(res, 'game_gone'),
          "an event from a feed that no longer exists skipped the inbox")
    check(_needs_triage(res, 'plain'),
          "a plain event with no setup skipped the inbox (unchanged behaviour)")


def scenario_the_feed_api_stores_lists_and_resolves_on_change():
    import main
    from services import ics_sync
    _household()
    real = ics_sync.fetch_and_parse
    try:
        ics_sync.fetch_and_parse = lambda url: {'name': 'Rec', 'items': {}}
        try:
            req = main.IcsFeedCreate(url='webcal://d.example/r.ics', calendar_id='cal_lily',
                                     in_driving_schedule=False)
        except Exception as e:
            raise AssertionError("IcsFeedCreate refuses in_driving_schedule: %s" % e)
        made = main.create_ics_feed(req, mock.MagicMock())
    finally:
        ics_sync.fetch_and_parse = real
    stored = storage.get_ics_feed(made['id'])
    check(stored.get('in_driving_schedule') is False,
          "the switch did not ride the create: %r" % stored.get('in_driving_schedule'))

    listed = {f['id']: f for f in main.list_ics_feeds()}
    check(listed['feed_legacy'].get('in_driving_schedule') is True,
          "a feed saved before the switch must list as in the schedule")
    check(listed[made['id']].get('in_driving_schedule') is False,
          "the listing lost the switch")

    bt = mock.MagicMock()
    main.update_ics_feed('feed_on', main.IcsFeedUpdate(in_driving_schedule=False), bt)
    check(storage.get_ics_feed('feed_on').get('in_driving_schedule') is False,
          "PUT did not store the switch")
    tasks = [c.args[0] for c in bt.add_task.call_args_list if c.args]
    check(main.trigger_background_refresh in tasks,
          "flipping the switch did not re-solve: %r" % tasks)

    bt2 = mock.MagicMock()
    main.update_ics_feed('feed_on', main.IcsFeedUpdate(name='Surge U10'), bt2)
    tasks2 = [c.args[0] for c in bt2.add_task.call_args_list if c.args]
    check(main.trigger_background_refresh not in tasks2,
          "a rename re-solved the schedule for nothing")


def scenario_an_approved_intake_card_never_needs_triage():
    """Approved with nobody picked: a setup is still saved, so the event is
    driven by the calendar it was added to and never reaches the inbox."""
    import main

    def approve():
        pid = storage.add_proposal({
            'title': 'Volleyball practice', 'kind': 'event',
            'start': _at(17).isoformat(), 'end': _at(18, 30).isoformat(),
            'all_day': False, 'location': '5 Gym Ave', 'notes': '',
            'source_from': 'coach@club.org', 'source_subject': 'Fall schedule'})
        with mock.patch('services.calendar.insert_event', return_value='gintake'), \
             mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
             mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
            main.approve_proposal(pid, main.ProposalApprove(calendar_id='cal_lily'),
                                  mock.MagicMock())
        check(storage.get_event_config('gintake') is not None,
              "approval with nobody picked saved no setup")
    res = _solve([_ev('gintake', 'cal_lily', _at(17), 90, '5 Gym Ave',
                      title='Volleyball practice')], setup=approve)
    check(not _needs_triage(res, 'gintake'), "the approved intake event went to the inbox")
    check(_driven_by(res, 'gintake') == {'d1'},
          "the approved intake event was not driven by its calendar: %s"
          % res.get('assignments'))


if __name__ == '__main__':
    scenarios = [v for k, v in globals().items() if k.startswith('scenario_')]
    failed = 0
    for fn in scenarios:
        try:
            fn()
            print('PASS', fn.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', fn.__name__, '-', e)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print('ERROR', fn.__name__, '-', e)
    print('%d/%d passed' % (len(scenarios) - failed, len(scenarios)))
    raise SystemExit(1 if failed else 0)
