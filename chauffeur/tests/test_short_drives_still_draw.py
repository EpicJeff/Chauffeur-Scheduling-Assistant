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


def scenario_the_between_events_edges_keep_the_solvers_figure():
    """Deliberate asymmetry, pinned so nobody "fixes" it later: the middle
    edges feed late_mins, wait_mins and the layover arithmetic, and those have
    to match what the solver believed. Only the two display-only legs changed.
    """
    import inspect
    import solver.matcher as matcher
    src = inspect.getsource(matcher.compute_route_edges)
    initial_and_final, between = src.split('for i in range(len(date_evs) - 1):', 1)
    check('get_travel_time_minutes(' not in initial_and_final,
          "an initial/final leg is back on the collapsed travel time")
    check('travel_for_display(' not in between,
          "a between-events edge took the uncollapsed time, which moves "
          "late_mins and the layover away from what the solver planned")


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
