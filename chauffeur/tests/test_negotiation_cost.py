"""What survives, and which survivor wins."""
import datetime
import time

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage
from solver import matcher

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


def scenario_budget_caps_failed_replays_too():
    """A queue that fails often must not be able to walk itself unbounded.
    The first replay (the baseline, on the untouched pack) is allowed to
    succeed; every candidate replay after it raises. If the budget only
    counted successes, `spent` would never move and every candidate in the
    queue would get tried regardless of `budget`.

    Needs a resolvable owner -- `_seed_parent`'s reasoning in
    `test_negotiation_levers.py` applies here too: with no parent on record
    `_owner_of` returns '' for every part and `candidates()` filters the whole
    queue down to nothing, which would make this test pass whether or not the
    budget fix works. A real queue (16 shift candidates for this pack) is
    what makes "the budget still caps it" a claim worth checking.
    """
    storage.add_member({'id': 'parent1', 'name': 'Jeff', 'role': 'parent'})
    pack = _pack([_event('seed', MONDAY),
                  _event('n1', MONDAY + datetime.timedelta(minutes=20)),
                  _event('n2', MONDAY + datetime.timedelta(minutes=40)),
                  _event('n3', MONDAY + datetime.timedelta(minutes=60))],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])
    calls = []
    real = solve_pack.replay

    def flaky(p, **kw):
        calls.append(1)
        if len(calls) == 1:
            return real(p, **kw)  # the baseline replay
        raise RuntimeError('boom')  # every candidate replay fails

    solve_pack.replay = flaky
    try:
        deals = negotiation.search(pack, 'seed', budget=3)
    finally:
        solve_pack.replay = real
    check(deals == [], f"every candidate failed, so nothing should survive: {deals}")
    check(len(calls) <= 4,  # 1 baseline + budget(3) candidate attempts
          f"failed attempts must still count against the budget: {len(calls)}")


def scenario_a_same_count_conflict_trade_is_rejected():
    """A candidate that trades one person's conflict for another's must be
    rejected even though the total conflict count never changes -- exactly
    what a count comparison cannot see and a key comparison can.

    `solve_pack.replay` currently calls `compute_conflicts` with an empty
    ghost-assignment map (`solve_pack.py:178`), so a real pack replayed through
    `search()` can never produce a non-empty `conflicts` dict -- there is no
    pack this scenario could build that would exercise the trade end-to-end
    through `search()` itself. So this drives `matcher.compute_conflicts`
    directly, the same function `solve_pack.replay` calls, to get a REAL
    conflicts dict shaped exactly like the one `search()` would receive if
    that wiring gap were closed, and checks `negotiation._newly_conflicted` --
    the function `search()` actually calls -- against it.
    """
    def _ev(eid, start, mins=60):
        return Event(id=eid, title=eid, start=start,
                     end=start + datetime.timedelta(minutes=mins),
                     location='Field', calendar_ids=['c1'], source_event_ids=[eid])

    # Baseline: e1 collides with ghost g1; e2 and ghost g2 do not.
    base_events = [_ev('e1', MONDAY), _ev('e2', MONDAY + datetime.timedelta(hours=2)),
                   _ev('g1', MONDAY + datetime.timedelta(minutes=30)),
                   _ev('g2', MONDAY + datetime.timedelta(hours=4))]
    base_conflicts = matcher.compute_conflicts(
        {'e1': 'd1', 'e2': 'd1'}, {'g1': 'd2', 'g2': 'd2'}, base_events)
    check('e1' in base_conflicts and 'e2' not in base_conflicts,
          f"the baseline must have exactly the collision set up here: {dict(base_conflicts)}")

    # Traded: g1 moves clear of e1 (fixed), but g2 moves onto e2 (broken) --
    # same total conflict count, a DIFFERENT person now double-booked.
    traded_events = [_ev('e1', MONDAY), _ev('e2', MONDAY + datetime.timedelta(hours=2)),
                     _ev('g1', MONDAY + datetime.timedelta(hours=3)),
                     _ev('g2', MONDAY + datetime.timedelta(hours=2, minutes=15))]
    traded_conflicts = matcher.compute_conflicts(
        {'e1': 'd1', 'e2': 'd1'}, {'g1': 'd2', 'g2': 'd2'}, traded_events)
    check('e2' in traded_conflicts and 'e1' not in traded_conflicts,
          f"the trade must swap WHICH event collides: {dict(traded_conflicts)}")
    check(len(traded_conflicts) == len(base_conflicts) == 1,
          "the trade must be a same-count swap, or this test proves nothing")

    check(negotiation._newly_conflicted(base_conflicts, traded_conflicts),
          "a same-count conflict TRADE must still be rejected")
    check(not negotiation._newly_conflicted(base_conflicts, dict(base_conflicts)),
          "an unchanged conflict set must not disqualify a candidate")

    # A same-event conflict getting worse (one collision becomes two) -- the
    # per-key list length carries this, wherever the data actually exists.
    worse = {**base_conflicts,
             'e1': base_conflicts['e1'] + [{'event_id': 'g3', 'title': 'g3'}]}
    check(negotiation._newly_conflicted(base_conflicts, worse),
          "an existing conflict growing worse on the same event must be caught")


if __name__ == '__main__':
    scenario_a_candidate_that_breaks_the_day_is_rejected()
    scenario_one_person_beats_two()
    scenario_a_shift_beats_a_protected_lift()
    scenario_fairness_counts_recent_asks()
    scenario_budget_caps_the_solves()
    scenario_budget_caps_failed_replays_too()
    scenario_a_same_count_conflict_trade_is_rejected()
    print("test_negotiation_cost OK")
