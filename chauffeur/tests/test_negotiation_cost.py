"""What survives, and which survivor wins."""
import datetime
import time

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice', mins=60):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(minutes=mins),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def _pack(events, drivers, **kw):
    base = dict(rules=[], priority_rules=[], overrides=[], passengers=[],
                cars=[], driver_events={}, trip_metadata=[],
                driver_passenger_map={}, previous_assignments={},
                load_balancing=False, load_balancing_metric='occupied_time',
                protected_rule_index={})
    base.update(kw)
    return solve_pack.build('2026-09-07', events=events, drivers=drivers, **base)


def scenario_a_candidate_that_breaks_the_day_is_rejected():
    """Two events at the same hour, one driver. Nothing can cover both, so no
    candidate may be reported as a deal."""
    pack = _pack([_event('seed', MONDAY), _event('other', MONDAY, 'Dentist')],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])
    deals = negotiation.search(pack, 'seed', budget=8)
    for d in deals:
        check(d['cost']['people'] >= 1, f"a deal costs somebody something: {d}")
    # Whatever survives must leave 'other' covered too.
    for d in deals:
        out = solve_pack.replay(solve_pack.apply(pack, d['mutations']))
        check('other' not in out['unassigned'],
              f"fixing the seed by dropping another event is not a deal: {d}")


def scenario_one_person_beats_two():
    a = {'mutations': [], 'give_up': 9,
         'parts': [{'member_id': 'm1', 'lever': 'shift_event',
                    'payload': {'event_id': 'x'}, 'ask_text': 'a'}]}
    b = {'mutations': [], 'give_up': 1,
         'parts': [{'member_id': 'm1', 'lever': 'shift_event',
                    'payload': {'event_id': 'x'}, 'ask_text': 'a'},
                   {'member_id': 'm2', 'lever': 'swap_drive',
                    'payload': {'event_id': 'y'}, 'ask_text': 'b'}]}
    ranked = sorted([b, a], key=lambda c: negotiation._rank(c, objective_delta=0.0))
    check(ranked[0] is a,
          "a one-person deal beats a two-person deal even when it costs more")


def scenario_a_shift_beats_a_protected_lift():
    shift = {'mutations': [], 'give_up': negotiation.GIVE_UP['shift_15'],
             'parts': [{'member_id': 'm1', 'lever': 'shift_event',
                        'payload': {'event_id': 'x'}, 'ask_text': 'a'}]}
    lift = {'mutations': [], 'give_up': negotiation.GIVE_UP['lift_protected'],
            'parts': [{'member_id': 'm2', 'lever': 'lift_protected',
                       'payload': {'commitment_id': 'c'}, 'ask_text': 'b'}]}
    ranked = sorted([lift, shift], key=lambda c: negotiation._rank(c, 0.0))
    check(ranked[0] is shift,
          "somebody's own evening is the last thing the negotiator asks for")


def scenario_fairness_counts_recent_asks():
    storage.deals_table.truncate()
    storage.add_deal({'date': '2026-09-06', 'seed_event_id': 'old',
                      'state': 'dead',
                      'parts': [{'id': 'p1', 'member_id': 'm2',
                                 'lever': 'shift_event', 'payload': {},
                                 'ask_text': '', 'state': 'declined'}]})
    check(negotiation._fairness('m2') >= 1,
          "somebody asked recently is asked less readily")
    check(negotiation._fairness('m1') == 0, "and somebody who has not is not")


def scenario_budget_caps_the_solves():
    pack = _pack([_event('seed', MONDAY),
                  _event('n1', MONDAY + datetime.timedelta(minutes=20)),
                  _event('n2', MONDAY + datetime.timedelta(minutes=40)),
                  _event('n3', MONDAY + datetime.timedelta(minutes=60))],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])
    seen = []
    real = solve_pack.replay
    solve_pack.replay = lambda p, **kw: (seen.append(1), real(p, **kw))[1]
    try:
        negotiation.search(pack, 'seed', budget=3)
    finally:
        solve_pack.replay = real
    check(len(seen) <= 3, f"the budget is a ceiling, not a suggestion: {len(seen)}")


if __name__ == '__main__':
    scenario_a_candidate_that_breaks_the_day_is_rejected()
    scenario_one_person_beats_two()
    scenario_a_shift_beats_a_protected_lift()
    scenario_fairness_counts_recent_asks()
    scenario_budget_caps_the_solves()
    print("test_negotiation_cost OK")
