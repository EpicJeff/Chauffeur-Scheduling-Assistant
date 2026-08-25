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


def _kit(kid, name, items, passengers=None, per_person=True):
    return {'id': kid, 'name': name, 'items': items, 'enabled': True,
            'passenger_ids': passengers or [], 'per_person': per_person,
            'keywords': [name.split()[0].lower()]}


class _Pax:
    def __init__(self, pid, name, cal_ids=None):
        self.id, self.name = pid, name
        self.calendar_ids = cal_ids or []


def scenario_two_children_at_one_event_need_two_of_everything():
    """The silent failure this exists to stop: prep items are deduped
    case-insensitively today, so two kids at one practice get ONE water bottle
    ticked and one child goes thirsty."""
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie', 'sam']
    sched = _sched([ev], {'soccer': 'd1'})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k1', 'Soccer bag', ['Water bottle', 'Cleats'],
                                         passengers=['ellie', 'sam'])],
                              passengers=[_Pax('ellie', 'Ellie'), _Pax('sam', 'Sam')])
    check(len(got) == 1, f"one kit should produce one group: {got}")
    check([i['needed'] for i in got[0]['items']] == [2, 2],
          f"two children need two of each item: {got[0]['items']}")


def scenario_one_child_at_two_events_still_needs_one_bottle():
    """The kid carries it all afternoon. Needed is DISTINCT PEOPLE across the
    outing, never the sum of the events."""
    a, b = _ev('soccer', 16, title='Soccer practice'), _ev('band', 17, 30, title='Soccer social')
    a['calendar_ids'] = b['calendar_ids'] = ['ellie']
    sched = _sched([a, b], {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 15}}})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k1', 'Soccer bag', ['Water bottle'],
                                         passengers=['ellie'])],
                              passengers=[_Pax('ellie', 'Ellie')])
    check([i['needed'] for i in got[0]['items']] == [1],
          f"one child on two events still needs one bottle: {got}")


def scenario_a_group_kit_is_one_however_many_are_going():
    """The team snack, the folding chair, the cash for the fundraiser. A
    counter that is wrong about these teaches the household to ignore counters."""
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie', 'sam']
    sched = _sched([ev], {'soccer': 'd1'})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k2', 'Soccer snack', ['Orange slices'],
                                         passengers=['ellie', 'sam'], per_person=False)],
                              passengers=[_Pax('ellie', 'Ellie'), _Pax('sam', 'Sam')])
    check([i['needed'] for i in got[0]['items']] == [1],
          f"a group item is one however many are going: {got}")


def scenario_a_kit_naming_nobody_needs_one():
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie']
    sched = _sched([ev], {'soccer': 'd1'})
    out = outings.outings_for(DAY, sched)[0]
    got = outings.packing_for(out, sched,
                              kits=[_kit('k3', 'Soccer bag', ['Ball'])],
                              passengers=[_Pax('ellie', 'Ellie')])
    check([i['needed'] for i in got[0]['items']] == [1],
          f"an unfiltered kit needs one: {got}")


def scenario_the_last_outings_end_includes_the_drive_home():
    """Fix round finding #3: the spec says the turn-over point is the last
    outing's end — the drive home — not the last event's end. `final_edges`
    already carries the solver's own `travel_mins` for that leg (the driver's
    trip home after the day's last event); nothing consumed it before this."""
    sched = _sched([_ev('soccer', 16, dur=60)], {'soccer': 'd1'})
    sched['final_edges'] = {'d1': {'soccer': {'from_event': 'soccer', 'travel_mins': 25}}}
    got = outings.outings_for(DAY, sched)
    check(len(got) == 1, f"expected one outing: {got}")
    event_end = datetime.datetime(2026, 9, 8, 17, 0)
    want_end = (event_end + datetime.timedelta(minutes=25)).isoformat()
    check(got[0]['end'] == want_end,
          f"the outing's end should include the drive home: {got[0]['end']} != {want_end}")


def scenario_a_mid_day_home_layover_keeps_its_own_end():
    """Only the LAST outing of a driver's day gets the drive-home add-on. A
    mid-day outing cut at a home_waypoint already ends when the layover
    starts at home — the spec does not touch that end at all, even when a
    final edge exists for the day's actual last outing."""
    sched = _sched([_ev('soccer', 9), _ev('band', 17, 30)],
                   {'soccer': 'd1', 'band': 'd1'},
                   {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20,
                                      'home_waypoint': {'layover_mins': 240}}}})
    sched['final_edges'] = {'d1': {'band': {'from_event': 'band', 'travel_mins': 15}}}
    got = outings.outings_for(DAY, sched)
    soccer_outing = next(o for o in got if o['event_ids'] == ['soccer'])
    band_outing = next(o for o in got if o['event_ids'] == ['band'])
    soccer_end = datetime.datetime(2026, 9, 8, 10, 0).isoformat()
    check(soccer_outing['end'] == soccer_end,
          f"a mid-day outing's end should not move: {soccer_outing['end']} != {soccer_end}")
    band_end = (datetime.datetime(2026, 9, 8, 18, 30)
               + datetime.timedelta(minutes=15)).isoformat()
    check(band_outing['end'] == band_end,
          f"the day's actual last outing should include the drive home: "
          f"{band_outing['end']} != {band_end}")


def scenario_missing_final_edges_leaves_ends_unchanged():
    """No final edge for this driver — the common case today — must draw
    exactly what it always has: the last event's own end."""
    sched = _sched([_ev('soccer', 16, dur=60)], {'soccer': 'd1'})
    got = outings.outings_for(DAY, sched)
    want_end = datetime.datetime(2026, 9, 8, 17, 0).isoformat()
    check(got[0]['end'] == want_end,
          f"an outing with no final edge should keep the event's own end: "
          f"{got[0]['end']} != {want_end}")


def scenario_a_malformed_final_edge_leaves_the_end_unchanged():
    """A `travel_mins` that is not a number is a malformed edge, not a
    reason to guess — the end must stay exactly what it was."""
    sched = _sched([_ev('soccer', 16, dur=60)], {'soccer': 'd1'})
    sched['final_edges'] = {'d1': {'soccer': {'from_event': 'soccer', 'travel_mins': 'lots'}}}
    got = outings.outings_for(DAY, sched)
    want_end = datetime.datetime(2026, 9, 8, 17, 0).isoformat()
    check(got[0]['end'] == want_end,
          f"a malformed final edge should not move the end: {got[0]['end']} != {want_end}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} outing scenarios passed")
