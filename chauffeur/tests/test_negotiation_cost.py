"""What survives, and which survivor wins."""
import datetime
import time

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice', mins=60):
    # 'calendar_id::google_event_id' is the shape services/calendar.py's fetch
    # produces, and `candidates()` will not offer a shift for anything it
    # cannot address -- a bare id here would empty the queue and make every
    # scenario below pass without testing anything.
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(minutes=mins),
                 location='Field', calendar_ids=['c1'],
                 source_event_ids=[f'cal1::{eid}'])


def _seed_parent():
    """A resolvable owner, so `candidates()` actually returns a queue.

    `_owner_of` falls through to the household's parents, and with none on
    record every part is addressed to '' and filtered out — leaving
    `candidates()` empty and any scenario that says "nothing survived" or
    "the budget capped it" true for the wrong reason. This has to run BEFORE
    the first scenario, not partway down the file.
    """
    storage.add_member({'id': 'cost_parent', 'name': 'Jeff', 'role': 'parent'})


def _pack(events, drivers, **kw):
    base = dict(rules=[], priority_rules=[], overrides=[], passengers=[],
                cars=[], driver_events={}, trip_metadata=[],
                driver_passenger_map={}, previous_assignments={},
                load_balancing=False, load_balancing_metric='occupied_time',
                protected_rule_index={})
    base.update(kw)
    return solve_pack.build('2026-09-07', events=events, drivers=drivers, **base)


def scenario_a_candidate_that_breaks_the_day_is_rejected():
    """The arc's central hard-filter claim: a change that covers the seed by
    breaking something else is not a deal.

    Two events five minutes apart at two different places (the harness charges
    ten minutes between any two) and one driver: he can have one of them, never
    both. Every shift the queue offers is therefore a real question — does this
    move cover the seed without dropping the Dentist? — and the filter has to
    answer it, not be handed an empty queue.
    """
    other = _event('other', MONDAY + datetime.timedelta(minutes=5), 'Dentist')
    other.location = 'Clinic'
    pack = _pack([_event('seed', MONDAY), other],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])
    queue = negotiation.candidates(pack, 'seed')
    check(len(queue) >= 4,
          f"the filter must have real candidates to reject, got {len(queue)}")
    base = solve_pack.replay(pack)
    check('seed' in base['unassigned'] or 'other' in base['unassigned'],
          f"one of the two really has to go uncovered, got {base['unassigned']}")
    deals = negotiation.search(pack, 'seed', budget=8)
    for d in deals:
        check(d['cost']['people'] >= 1, f"a deal costs somebody something: {d}")
    # Whatever survives must leave 'other' covered too.
    for d in deals:
        out = solve_pack.replay(solve_pack.apply(pack, d['mutations']))
        check('other' not in out['unassigned'],
              f"fixing the seed by dropping another event is not a deal: {d}")


def scenario_a_timed_out_baseline_answers_nothing():
    """A baseline that did not solve makes the whole 'nothing new breaks'
    check vacuous: `matcher.solve_schedule` reports a timeout by calling EVERY
    event unassigned, so `baseline_broken` becomes the whole day and
    `broken - baseline_broken` is empty for every candidate that comes back at
    all. On a big day — the day negotiation exists for — that would wave
    everything through with no validation behind it."""
    pack = _pack([_event('seed', MONDAY),
                  _event('n1', MONDAY + datetime.timedelta(minutes=20))],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])
    real = solve_pack.replay
    calls = []

    def timed_out(p, **kw):
        calls.append(1)
        out = real(p, **kw)
        if len(calls) == 1:                     # only the baseline
            out = {**out, 'status': 'UNKNOWN',
                   'unassigned': [str(e['id']) for e in p['events']]}
        return out

    solve_pack.replay = timed_out
    try:
        deals = negotiation.search(pack, 'seed', budget=8)
    finally:
        solve_pack.replay = real
    check(deals == [],
          f"a search must refuse to validate against a baseline that did not "
          f"solve, got {deals}")
    check(len(calls) == 1,
          f"and must not spend the budget replaying candidates it cannot "
          f"judge, got {len(calls)} replays")


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
    """The budget is a ceiling on how many times one question may ask the
    solver. It only means anything against a queue longer than the budget --
    with no parent on record `candidates()` returns nothing and this passes
    on an empty list, which is why `_seed_parent()` runs first."""
    pack = _pack([_event('seed', MONDAY),
                  _event('n1', MONDAY + datetime.timedelta(minutes=20)),
                  _event('n2', MONDAY + datetime.timedelta(minutes=40)),
                  _event('n3', MONDAY + datetime.timedelta(minutes=60))],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])
    check(len(negotiation.candidates(pack, 'seed')) > 3,
          "the queue must be longer than the budget, or this proves nothing")
    seen = []
    real = solve_pack.replay
    solve_pack.replay = lambda p, **kw: (seen.append(1), real(p, **kw))[1]
    try:
        negotiation.search(pack, 'seed', budget=3)
    finally:
        solve_pack.replay = real
    check(len(seen) <= 4,  # 1 baseline + budget(3) candidate attempts
          f"the budget is a ceiling, not a suggestion: {len(seen)}")


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


if __name__ == '__main__':
    _seed_parent()
    scenario_a_candidate_that_breaks_the_day_is_rejected()
    scenario_a_timed_out_baseline_answers_nothing()
    scenario_one_person_beats_two()
    scenario_a_shift_beats_a_protected_lift()
    scenario_fairness_counts_recent_asks()
    scenario_budget_caps_the_solves()
    scenario_budget_caps_failed_replays_too()
    print("test_negotiation_cost OK")
