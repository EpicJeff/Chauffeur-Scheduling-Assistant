"""An outing: one trip out of the house, leaving home to coming back.

The app had legs and it had events and no word for the thing that spans them —
which is the unit that decides what has to be in the car. A driver took a
passenger to one event, went straight on to a second, and arrived without the
second event's gear; the solver already knew they were not stopping home, and
nothing ever said so.

The solver encodes that knowledge as an ABSENCE: a route edge carries a
`home_waypoint` when there was room to detour home, and simply omits it when
there was not. So an outing is a driver's chained events for a date, cut
wherever a home waypoint appears.

Run from chauffeur/:  python tests/test_outings.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_outings_'))

import datetime  # noqa: E402

from services import outings  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DAY = '2026-09-08'


def _ev(eid, hh, mm=0, dur=60, title=None):
    start = datetime.datetime(2026, 9, 8, hh, mm)
    return {'id': eid, 'title': title or eid,
            'start': start.isoformat(),
            'end': (start + datetime.timedelta(minutes=dur)).isoformat()}


def _sched(events, assignments, route_edges=None):
    return {'events': events, 'assignments': assignments,
            'route_edges': route_edges or {}, 'initial_edges': {}, 'final_edges': {}}


def scenario_two_events_with_no_way_home_are_one_outing():
    """The incident, in fixture form. Soccer at 16:00, band at 17:30, and no
    room to get home in between — so it is one trip, and one packing job."""
    sched = _sched([_ev('soccer', 16), _ev('band', 17, 30)],
                   {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20}}})
    got = outings.outings_for(DAY, sched)
    check(len(got) == 1, f"two events with no way home are one outing, got {len(got)}")
    check(got[0]['event_ids'] == ['soccer', 'band'],
          f"the outing does not hold both events in order: {got[0]}")


def scenario_a_home_layover_ends_the_outing():
    """The same two events with room to go home in between are two trips —
    and two packing jobs, because making a family carry the whole day's gear
    on every trip is its own kind of wrong."""
    sched = _sched([_ev('soccer', 9), _ev('band', 17, 30)],
                   {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20,
                                      'home_waypoint': {'layover_mins': 240}}}})
    got = outings.outings_for(DAY, sched)
    check([o['event_ids'] for o in got] == [['soccer'], ['band']],
          f"a home layover did not split the day: {[o['event_ids'] for o in got]}")


def scenario_each_driver_gets_their_own_outings():
    """Two cars out at once is two outings — and at four activities a day it
    is most days. Whose car a bag belongs in is the whole question."""
    sched = _sched([_ev('soccer', 16), _ev('swim', 16, 15)],
                   {'soccer': 'd1', 'swim': 'd2'})
    got = outings.outings_for(DAY, sched)
    check(sorted(o['driver_id'] for o in got) == ['d1', 'd2'],
          f"two drivers did not produce two outings: {got}")


def scenario_outings_are_sorted_by_departure():
    got = outings.outings_for(DAY, _sched(
        [_ev('late', 18), _ev('early', 8)],
        {'late': 'd1', 'early': 'd2'}))
    check([o['event_ids'][0] for o in got] == ['early', 'late'],
          f"outings are not in departure order: {got}")


def scenario_a_day_with_nothing_has_no_outings():
    """Rule 1: nothing to say, nothing drawn."""
    check(outings.outings_for(DAY, _sched([], {})) == [], "an empty day invented an outing")


def scenario_a_ghost_driver_is_not_an_outing():
    """`ghost_` is the solver's placeholder for nobody real. Naming one on the
    wall would be inventing a person."""
    got = outings.outings_for(DAY, _sched([_ev('soccer', 16)], {'soccer': 'ghost_1'}))
    check(got == [], f"a ghost assignment became an outing: {got}")


def scenario_another_day_is_not_this_day():
    sched = _sched([_ev('soccer', 16)], {'soccer': 'd1'})
    check(outings.outings_for('2026-09-09', sched) == [],
          "an outing leaked across days")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} outing scenarios passed")
