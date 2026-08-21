"""A drive round the corner is still a drive.

`matcher.get_travel_time_minutes` rounds anything under three minutes down to
zero so the CP-SAT model does not fuss over a hop the length of a driveway.
That collapse leaked into `compute_route_edges`, where zero already meant
something else entirely -- SAME PLACE -- and every consumer reads it that way:

  * the Drives timeline draws an initial/final leg only when `travel_mins > 0`
  * `leave_by.travel_into` returns None at zero, so the be-ready-at times, the
    wall board's leave-by and the "Time to Leave!" push all go quiet

So a school two minutes from the house produced an event on the sheet with no
drive to it, no drive home, no leave-by and no push -- and nothing anywhere
said why. The between-events edges keep the collapsed figure on purpose:
theirs feeds lateness, waits and the layover arithmetic, which have to agree
with what the solver believed when it placed the day.

Run from chauffeur/:  python tests/test_short_drives_still_draw.py
"""
import datetime
import os
import re

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()
HOME = '1 Home St'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _two_minutes_away(origin, destination, departure_time=None, return_traffic=False):
    """Every real pair is a two-minute drive -- under the collapse line, and
    unmistakably a drive somebody makes."""
    same = not origin or not destination or origin.lower() == destination.lower()
    mins = 0 if same else 2
    return (mins, 0) if return_traffic else mins


def _solve(location):
    import main
    from services import calendar as cal_svc
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher

    for t in ('drivers_table', 'passengers_table', 'members_table',
              'daily_schedules_table', 'custom_schedules_table',
              'settings_table', 'event_configs_table', 'rules_table',
              'overrides_table'):
        tbl = getattr(storage, t, None)
        if tbl is not None:
            tbl.truncate()
    storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                   'days_to_build': 1, 'home_location': HOME})
    storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#3b82f6',
                        'group': 'primary', 'priority_index': 1,
                        'calendar_ids': [], 'home_location': HOME})
    storage.add_passenger({'id': 'p1', 'name': 'Lily',
                           'calendar_ids': ['cal_lily'], 'hashtags': []})
    storage.add_member({'id': 'm1', 'name': 'Lily', 'role': 'child',
                        'passenger_id': 'p1'})
    storage.event_configs_table.insert({'google_id': 'gev1',
                                        'passenger_ids': ['p1']})

    start = datetime.datetime.combine(TODAY, datetime.time(16, 0))
    proto = dict(id='gev1', title='Piano lesson', start=start,
                 end=start + datetime.timedelta(minutes=30), location=location,
                 description='', calendar_ids=['cal_lily'],
                 source_event_ids=['gev1'])

    real_fetch = cal_svc.fetch_upcoming_events
    real_raw = matcher._raw_get_travel_time_minutes
    real_maps = maps.get_travel_time_minutes
    try:
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**proto)]
        matcher._raw_get_travel_time_minutes = _two_minutes_away
        maps.get_travel_time_minutes = _two_minutes_away
        res = main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(),
                                          force_refresh=True)
    finally:
        cal_svc.fetch_upcoming_events = real_fetch
        matcher._raw_get_travel_time_minutes = real_raw
        maps.get_travel_time_minutes = real_maps
    check(not res.get('error'), "the day did not solve: %s" % res.get('error'))
    return res


def scenario_a_two_minute_drive_is_drawn():
    """The bug, end to end. Two minutes is under the solver's collapse line
    and is still a car journey a person makes."""
    got = _solve('2 Corner Rd')
    check(got.get('assignments', {}).get('gev1') == 'd1',
          "the event was not assigned at all: %s" % got.get('assignments'))
    to = ((got.get('initial_edges') or {}).get('d1') or {}).get('gev1') or {}
    home = ((got.get('final_edges') or {}).get('d1') or {}).get('gev1') or {}
    check(to.get('travel_mins') == 2,
          "the drive TO a two-minute-away event reads %r, and the timeline "
          "draws nothing at 0" % to.get('travel_mins'))
    check(home.get('travel_mins') == 2,
          "the drive HOME reads %r" % home.get('travel_mins'))


def scenario_the_house_itself_still_draws_no_drive():
    """The other meaning of zero has to survive: an event AT the house is not
    a drive, and inventing a pill for it would be the opposite bug."""
    got = _solve(HOME)
    to = ((got.get('initial_edges') or {}).get('d1') or {}).get('gev1') or {}
    home = ((got.get('final_edges') or {}).get('d1') or {}).get('gev1') or {}
    check(to.get('travel_mins') == 0 and home.get('travel_mins') == 0,
          "an event at the driver's own address grew a drive: %r / %r"
          % (to.get('travel_mins'), home.get('travel_mins')))


def scenario_leave_by_wakes_up_for_a_short_drive():
    """`travel_into` returns None at zero, which is what took the be-ready-at
    times and the "Time to Leave!" push offline for close-by events."""
    from services import leave_by
    got = _solve('2 Corner Rd')
    lead = leave_by.travel_into(got, 'd1', 'gev1')
    check(lead and lead.get('travel_mins') == 2,
          "leave-by still knows nothing about a two-minute drive: %r" % lead)
    at_home = leave_by.travel_into(_solve(HOME), 'd1', 'gev1')
    check(at_home is None,
          "an event at the house grew a leave-by time: %r" % at_home)


def scenario_every_leg_in_the_picture_is_honest():
    """No exceptions, and the first cut of this fix made one. It spared the
    between-events edges on the theory that late_mins, wait_mins and the
    layover arithmetic had to match what the solver believed -- but nothing in
    that function feeds back into scheduling; both numbers are read by the
    timeline templates and nowhere else. The household reported the leg the
    theory left behind within the hour: a drive home from an event round the
    corner, drawn as "0M -> home for 15M"."""
    import inspect
    import solver.matcher as matcher
    src = inspect.getsource(matcher.compute_route_edges)
    check('get_travel_time_minutes(' not in src,
          "a leg on the sheet is back on the solver's collapsed travel time")


def scenario_the_layover_home_leg_is_honest_too():
    """The exact shape from the report: an event two minutes from the house,
    a long gap, then somewhere further away. The driver goes home in between,
    and BOTH halves of that trip are drives."""
    import solver.matcher as matcher
    from models.schemas import Event, Driver

    def travel(origin, dest, departure_time=None, return_traffic=False):
        if not origin or not dest or origin.lower() == dest.lower():
            return (0, 0) if return_traffic else 0
        mins = 2 if HOME in (origin, dest) and 'Corner' in (origin + dest) else 10
        return (mins, 0) if return_traffic else mins

    real = matcher._raw_get_travel_time_minutes
    try:
        matcher._raw_get_travel_time_minutes = travel
        base = datetime.datetime.combine(TODAY, datetime.time(10, 30))
        near = Event(id='a', title='Meet the teacher', start=base,
                     end=base + datetime.timedelta(minutes=30),
                     location='2 Corner Rd', calendar_ids=['cal_lily'],
                     source_event_ids=['a'])
        far = Event(id='b', title='Meet the Teacher (6th Grade)',
                    start=base + datetime.timedelta(hours=1),
                    end=base + datetime.timedelta(hours=2, minutes=30),
                    location='9 Far School Rd', calendar_ids=['cal_lily'],
                    source_event_ids=['b'])
        d = Driver(id='d1', name='Jeff', color_code='#3b82f6',
                   home_location=HOME)
        edges, initial, _final = matcher.compute_route_edges(
            {'a': 'd1', 'b': 'd1'}, [near, far], [d], home_location=HOME)
    finally:
        matcher._raw_get_travel_time_minutes = real

    check((initial.get('d1') or {}).get('a', {}).get('travel_mins') == 2,
          "no drive to the first event of the day")
    wp = ((edges.get('d1') or {}).get('a') or {}).get('home_waypoint') or {}
    check(wp, "the layover home trip vanished: %r" % edges.get('d1'))
    check(wp.get('to_home_mins') == 2,
          "the drive home from the near event still reads %r"
          % wp.get('to_home_mins'))
    check(wp.get('from_home_mins') == 10,
          "the drive out to the far event reads %r" % wp.get('from_home_mins'))


def scenario_the_timeline_still_gates_on_a_real_drive():
    """The `> 0` gate stays: it is what keeps an at-home event from sprouting
    a pill. This pins the gate, so the fix is understood to be the NUMBER
    reaching it honestly rather than the gate going away."""
    app = open(os.path.join(ROOT, 'templates', 'app.html'), encoding='utf-8').read()
    check(len(re.findall(r'travel_mins > 0', app)) >= 2,
          "the timeline no longer distinguishes a drive from no drive")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d short-drive scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
