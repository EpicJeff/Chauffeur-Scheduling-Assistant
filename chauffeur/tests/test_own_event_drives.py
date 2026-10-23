"""A driver's own appointments get a drive, a departure and a push.

User report (2026-10-23): "In the PWA we don't calculate driving legs for
their own events and we do not include drives to those in the Next
Departure card. I have a haircut today and would get no reminder of when it
was time to leave for that."

What was true: an event off a driver's own calendar is classified
`is_driver_only` in the refresh and never joins the solver's event list. It
reaches `driver_events` (so the solver treats it as a wall: no kid ride
overlapping it) but `compute_route_edges` is handed only the solved
passenger events plus errands and drops any attendance id it cannot find,
so the haircut has no initial, route or final edge. No edge means no "Drive
to" row on the Drives list, nothing for the Next departure to promote, no
Time to Leave push, nothing on the runway lanes or the drive sheet. Every
surface reads the same edges, so every surface was blind to it.

Pinned here by RUNNING the refresh over one household:

  * a timed, located event on a driver's own calendar gets an initial edge
    and a final edge for that driver, chains with their kid run, and the
    push builder fires a Time to Leave for it;
  * it is never a ride: not assigned, not unassigned, not in the inbox;
  * the solver still treats it as a wall (an overlapping kid ride stays
    unassigned, exactly as before);
  * no location, or a location that is the house itself, draws no drive;
  * an all-day own event stays out of `driver_events` (locked: a
    midnight-to-midnight span would ban the driver from every drive);
  * a calendar-only adult (no driver record) gets no edge: nobody drives
    them and they drive nobody;
  * slice 2: when the solver weighs a ride against the driver's own event
    the drive it measures has the kid in it (home after the ride, fetched
    before it), so a near miss is refused and the diagnostics name the
    own event, and a gap with room for the detour keeps the ride.

Run from chauffeur/:  python tests/test_own_event_drives.py
"""
import datetime
import os

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


def _ev(eid, cal, start, mins, location, title=None, all_day=False):
    return dict(id=eid, title=title or eid, start=start,
                end=start + datetime.timedelta(minutes=mins), location=location,
                description='', calendar_ids=[cal], source_event_ids=[eid],
                all_day=all_day)


def _household():
    for t in ('drivers_table', 'passengers_table', 'members_table',
              'daily_schedules_table', 'custom_schedules_table',
              'settings_table', 'event_configs_table', 'rules_table',
              'overrides_table', 'cache_table', 'inbox_table'):
        tbl = getattr(storage, t, None)
        if tbl is not None:
            tbl.truncate()
    # Suggested outside routes off: a ride nobody in the house can make
    # stays unassigned, so the diagnostics say why instead of a ghost
    # driver quietly covering it.
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
    # A calendar-only adult: seen on the family calendar, never driven,
    # never driving.
    storage.add_member({'id': 'm_gran', 'name': 'Gran', 'role': 'adult',
                        'calendar_ids': ['cal_gran']})
    storage.event_configs_table.insert({'google_id': 'gev1',
                                        'passenger_ids': ['p1']})
    storage.event_configs_table.insert({'google_id': 'match',
                                        'passenger_ids': ['p1']})


def _solve(protos):
    import main
    from services import calendar as cal_svc
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher

    _household()
    real_fetch = cal_svc.fetch_upcoming_events
    real_raw = matcher._raw_get_travel_time_minutes
    real_maps = maps.get_travel_time_minutes
    # The harness mocks storage.get_settings to a bare calendar list; the
    # refresh reads suggested_routes_enabled from that dict, so hand it the
    # row the table holds.
    real_settings = storage.get_settings
    try:
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**p) for p in protos]
        storage.get_settings = lambda: dict(storage.settings_table.all()[0])
        matcher._raw_get_travel_time_minutes = _ten_minutes_apart
        maps.get_travel_time_minutes = _ten_minutes_apart
        res = main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(),
                                          force_refresh=True)
    finally:
        cal_svc.fetch_upcoming_events = real_fetch
        matcher._raw_get_travel_time_minutes = real_raw
        maps.get_travel_time_minutes = real_maps
        storage.get_settings = real_settings
    check(not res.get('error'), "the day did not solve: %s" % res.get('error'))
    return res


def _edge(res, kind, ev_id, driver='d1'):
    return ((res.get(kind) or {}).get(driver) or {}).get(ev_id) or {}


def _pushes(res, protos):
    import main
    from models.schemas import Event
    events = {p['id']: Event(**p) for p in protos}
    # Midnight: every departure of the day is still ahead.
    now_ts = _at(0, 1).timestamp()
    return main._departure_notifications(res, events, {'home_location': HOME},
                                         now_ts, set())


PIANO = _ev('gev1', 'cal_lily', _at(16), 30, '9 Studio Ln', title='Piano lesson')
HAIRCUT = _ev('haircut', 'cal_jeff', _at(13), 45, '5 Salon Ave', title='Haircut')


def scenario_the_haircut_gets_a_drive_and_a_push():
    """The report, end to end: Jeff's own 1pm haircut is a drive Jeff makes."""
    res = _solve([PIANO, HAIRCUT])
    check('haircut' in (res.get('driver_events') or {}).get('d1', []),
          "the haircut left Jeff's own events: %s" % res.get('driver_events'))
    check('haircut' in {e.get('id') for e in res.get('events') or []},
          "the haircut is not in the day the UI draws")
    to = _edge(res, 'initial_edges', 'haircut')
    check(to.get('travel_mins') == 10,
          "the drive TO the haircut reads %r; the Drives list draws nothing, "
          "the Next departure has nothing to promote" % to.get('travel_mins'))
    pushes = {p['notif_id']: p for p in _pushes(res, [PIANO, HAIRCUT])}
    check('init_haircut' in pushes,
          "no Time to Leave push for the haircut: %s" % sorted(pushes))
    leave = datetime.datetime.fromtimestamp(pushes['init_haircut']['trigger_timestamp'])
    check(leave < _at(13) and leave >= _at(12, 30),
          "the push fires at %s for a 1pm start ten minutes away" % leave)
    check(pushes['init_haircut'].get('driver_id') == 'd1', "the push is Jeff's")


def scenario_it_is_never_a_ride():
    res = _solve([PIANO, HAIRCUT])
    check('haircut' not in (res.get('assignments') or {}),
          "the haircut became an assignment: %s" % res.get('assignments'))
    check('haircut' not in (res.get('ghost_assignments') or {}),
          "the haircut became a ghost assignment")
    check('haircut' not in (res.get('unassigned') or []),
          "the haircut counts as an uncovered ride: %s" % res.get('unassigned'))
    check(not any(e.get('needs_triage') for e in res.get('events') or []
                  if e.get('id') == 'haircut'),
          "the haircut went to the inbox")
    check(res.get('assignments', {}).get('gev1') == 'd1',
          "the kid run was not assigned to Jeff: %s" % res.get('assignments'))


def scenario_it_chains_with_the_kid_run():
    """One day, one driver: haircut 1pm, Lily's piano 4pm. The route edge
    from the haircut carries on to piano (home in between, hours apart) and
    the drive home is from piano, not from the salon."""
    res = _solve([PIANO, HAIRCUT])
    hop = _edge(res, 'route_edges', 'haircut')
    check(hop.get('to_event') == 'gev1',
          "no route edge from the haircut on to piano: %s" % hop)
    check(hop.get('home_waypoint'),
          "two hours apart and ten minutes from home: the chain goes home "
          "in between: %s" % hop)
    check(_edge(res, 'final_edges', 'gev1').get('travel_mins') == 10,
          "the drive home is from piano")
    check(not _edge(res, 'final_edges', 'haircut'),
          "a drive home from the salon was minted on top of the chain")
    check(not _edge(res, 'initial_edges', 'gev1'),
          "piano grew a second from-home departure on top of the chain")


def scenario_the_wall_still_stands():
    """An own event overlapping a kid ride still blocks the driver, exactly
    as before: the haircut is a drive Jeff makes AND a place Jeff is."""
    clash = _ev('haircut', 'cal_jeff', _at(16), 45, '5 Salon Ave', title='Haircut')
    res = _solve([PIANO, clash])
    check(res.get('assignments', {}).get('gev1') != 'd1',
          "Jeff was assigned a ride during his own haircut: %s"
          % res.get('assignments'))
    check(_edge(res, 'initial_edges', 'haircut').get('travel_mins') == 10,
          "the haircut lost its drive because a ride clashed with it")


def scenario_no_location_means_no_drive():
    call = _ev('call', 'cal_jeff', _at(13), 30, '', title='Team call')
    res = _solve([PIANO, call])
    check('call' in (res.get('driver_events') or {}).get('d1', []),
          "a located-nowhere own event left Jeff's busy list")
    check(not _edge(res, 'initial_edges', 'call')
          and not _edge(res, 'final_edges', 'call'),
          "a drive was minted to an event with no location: %s / %s"
          % (_edge(res, 'initial_edges', 'call'), _edge(res, 'final_edges', 'call')))


def scenario_the_house_itself_draws_no_drive():
    nap = _ev('nap', 'cal_jeff', _at(13), 30, HOME, title='Nap')
    res = _solve([PIANO, nap])
    to = _edge(res, 'initial_edges', 'nap')
    home = _edge(res, 'final_edges', 'nap')
    check((to.get('travel_mins') or 0) == 0 and (home.get('travel_mins') or 0) == 0,
          "an own event at the house grew a drive: %r / %r"
          % (to.get('travel_mins'), home.get('travel_mins')))


def scenario_an_all_day_own_event_stays_out():
    """Locked since v2.170.0: an all-day span must never reach
    driver_events, or its owner is banned from every drive that day."""
    bday = _ev('bday', 'cal_jeff', _at(0), 24 * 60, '5 Salon Ave',
               title='Birthday', all_day=True)
    res = _solve([PIANO, bday])
    check('bday' not in (res.get('driver_events') or {}).get('d1', []),
          "an all-day event reached driver_events")
    check(not _edge(res, 'initial_edges', 'bday'),
          "an all-day event grew a drive")
    check(res.get('assignments', {}).get('gev1') == 'd1',
          "the all-day event walled Jeff off the kid run")


def scenario_a_calendar_only_adult_gets_no_drive():
    """Gran has a calendar and no driver record. Her lunch shows on the
    family calendar; nobody drives her and she drives nobody."""
    lunch = _ev('lunch', 'cal_gran', _at(12), 60, '7 Cafe St', title='Lunch')
    res = _solve([PIANO, lunch])
    for d_id, ids in (res.get('driver_events') or {}).items():
        check('lunch' not in ids, "Gran's lunch landed in %s's own events" % d_id)
    for kind in ('initial_edges', 'route_edges', 'final_edges'):
        for d_id, edges in (res.get(kind) or {}).items():
            check('lunch' not in edges and not any(
                e.get('to_event') == 'lunch' for e in edges.values()),
                "a drive was minted for Gran's lunch in %s/%s" % (kind, d_id))
    check('lunch' in {e.get('id') for e in res.get('events') or []},
          "Gran's lunch vanished from the family day")


def _reason(res, ev_id, driver='d1'):
    return ((res.get('diagnostics') or {}).get(ev_id) or {}).get(driver) or {}


def scenario_the_kid_run_before_the_haircut_needs_the_drop_home():
    """Slice 2 (user, 2026-10-23: "assuming a kid's activity drive works seems
    bad"). Piano 1:00-1:30 at the studio, haircut 1:45 at the salon, every
    pair ten minutes apart. Salon is ten minutes from the studio and the gap
    is fifteen, so a direct drive fits; the real drive takes Lily home first
    (studio, home, salon: twenty minutes) and does not. The ride must not be
    handed to Jeff on the strength of a drive he cannot make."""
    piano = _ev('gev1', 'cal_lily', _at(13), 30, '9 Studio Ln', title='Piano lesson')
    haircut = _ev('haircut', 'cal_jeff', _at(13, 45), 45, '5 Salon Ave', title='Haircut')
    res = _solve([piano, haircut])
    check(res.get('assignments', {}).get('gev1') != 'd1',
          "Jeff was given a ride he cannot make: %s" % res.get('assignments'))
    why = _reason(res, 'gev1')
    check(why.get('type') == 'personal_conflict' and 'Haircut' in (why.get('text') or ''),
          "the diagnostics do not name the haircut: %s" % why)


def scenario_the_kid_run_after_the_haircut_needs_the_pickup_from_home():
    """Haircut 3:00-3:45, piano 4:00. Fifteen minutes between them; the drive
    is salon, home (fetch Lily), studio: twenty. Not Jeff's to make."""
    haircut = _ev('haircut', 'cal_jeff', _at(15), 45, '5 Salon Ave', title='Haircut')
    res = _solve([PIANO, haircut])
    check(res.get('assignments', {}).get('gev1') != 'd1',
          "Jeff was given a ride he cannot make: %s" % res.get('assignments'))
    why = _reason(res, 'gev1')
    check(why.get('type') == 'personal_conflict' and 'Haircut' in (why.get('text') or ''),
          "the diagnostics do not name the haircut: %s" % why)


def scenario_room_to_fetch_the_kid_keeps_the_ride():
    """Haircut 3:00-3:30, piano 4:00: thirty minutes covers salon, home,
    studio. The ride stays Jeff's and the route edge says the pickup."""
    haircut = _ev('haircut', 'cal_jeff', _at(15), 30, '5 Salon Ave', title='Haircut')
    res = _solve([PIANO, haircut])
    check(res.get('assignments', {}).get('gev1') == 'd1',
          "a ride with room to fetch Lily was dropped: %s / %s"
          % (res.get('assignments'), _reason(res, 'gev1')))
    hop = _edge(res, 'route_edges', 'haircut')
    check(hop.get('to_event') == 'gev1' and hop.get('pickup_waypoint'),
          "the hop from the salon does not go by home for Lily: %s" % hop)


def scenario_room_to_drop_the_kid_keeps_the_ride():
    """Piano 1:00-1:30, haircut 1:50: twenty minutes covers studio, home
    (Lily out), salon. The boundary the detour rule sits on."""
    piano = _ev('gev1', 'cal_lily', _at(13), 30, '9 Studio Ln', title='Piano lesson')
    haircut = _ev('haircut', 'cal_jeff', _at(13, 50), 40, '5 Salon Ave', title='Haircut')
    res = _solve([piano, haircut])
    check(res.get('assignments', {}).get('gev1') == 'd1',
          "a ride with room to take Lily home was dropped: %s / %s"
          % (res.get('assignments'), _reason(res, 'gev1')))


def scenario_the_kid_rides_along_to_the_event_the_driver_attends():
    """Codex review finding: an activity the driver ATTENDS with the kid is
    on the driver's calendar too, so it sits in driver_events beside the
    haircut. Piano 1:00-1:30 at the studio, then Lily's match at 1:45 at
    the field with Jeff watching. Lily goes studio to field in Jeff's car;
    nobody goes home in between. Both rides stay Jeff's."""
    piano = _ev('gev1', 'cal_lily', _at(13), 30, '9 Studio Ln', title='Piano lesson')
    match = _ev('match', 'cal_lily', _at(13, 45), 60, '3 Field Rd', title='Match')
    match['calendar_ids'] = ['cal_lily', 'cal_jeff']
    res = _solve([piano, match])
    check(res.get('assignments', {}).get('gev1') == 'd1'
          and res.get('assignments', {}).get('match') == 'd1',
          "a kid-to-kid hop the driver attends was sent home in between: %s / %s"
          % (res.get('assignments'), _reason(res, 'gev1')))


if __name__ == '__main__':
    scenarios = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]
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
