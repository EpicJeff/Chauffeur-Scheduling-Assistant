"""What the negotiator is allowed to propose, and what it never proposes."""
import datetime

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice', mins=60, optional=False, source=None):
    # `source_event_ids` entries are 'calendar_id::google_event_id' for
    # everything services/calendar.py fetches, and that composite is the only
    # thing a shift can be written to -- so the fixtures carry the real shape.
    # `source=[]` builds the other real case: an event the app made up, which
    # no calendar will accept a patch for.
    ev = Event(id=eid, title=title, start=start,
               end=start + datetime.timedelta(minutes=mins),
               location='Field', calendar_ids=['c1'],
               source_event_ids=[f'cal1::{eid}'] if source is None else source)
    if optional:
        ev.app_config = {'is_optional': True}
    return ev


def _pack(events, drivers, rules=None, protected_index=None):
    return solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=rules or [],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={}, trip_metadata=[], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time',
        protected_rule_index=protected_index or {})


def _seed_parent():
    """A resolvable owner for every part below. Deliberately not called by
    `scenario_no_resolvable_owner_yields_no_ask`, which runs first for exactly
    that reason -- once a parent exists in this process's shared DB it stays
    there for every scenario that runs after it."""
    storage.add_member({'id': 'parent1', 'name': 'Jeff', 'role': 'parent'})


def scenario_no_resolvable_owner_yields_no_ask():
    """No parent on record and no matching passenger means `_owner_of` falls
    all the way through to '' -- and a candidate addressed to nobody is a
    promise the app cannot keep, so it must never reach the queue at all."""
    pack = _pack([_event('seed', MONDAY),
                  _event('near', MONDAY + datetime.timedelta(minutes=30)),
                  _event('opt', MONDAY + datetime.timedelta(minutes=40),
                         'Extra', optional=True)],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    for c in negotiation.candidates(pack, 'seed'):
        for m in c['mutations']:
            check(m['lever'] not in ('shift_event', 'skip_optional'),
                  f"an ask with no addressee is not an ask, got {c}")


def scenario_shift_candidates_stay_in_the_window():
    near = _event('near', MONDAY + datetime.timedelta(minutes=30), 'Piano')
    far = _event('far', MONDAY + datetime.timedelta(hours=6), 'Book club')
    pack = _pack([_event('seed', MONDAY), near, far],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    shifts = [c for c in negotiation.candidates(pack, 'seed')
              if any(m['lever'] == 'shift_event' for m in c['mutations'])]
    moved = {m['event_id'] for c in shifts for m in c['mutations']}
    check('near' in moved, f"a neighbour in the window is movable, got {moved}")
    check('far' not in moved,
          f"an event six hours away has nothing to do with this, got {moved}")


def scenario_a_skip_only_targets_an_optional():
    optional = _event('opt', MONDAY + datetime.timedelta(minutes=20),
                      'Extra practice', optional=True)
    required = _event('req', MONDAY + datetime.timedelta(minutes=25), 'Dentist')
    pack = _pack([_event('seed', MONDAY), optional, required],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    skipped = {m['event_id'] for c in negotiation.candidates(pack, 'seed')
               for m in c['mutations'] if m['lever'] == 'skip_optional'}
    check(skipped == {'opt'},
          f"only what the family already called optional, got {skipped}")


def scenario_cheap_candidates_come_first():
    pack = _pack([_event('seed', MONDAY),
                  _event('near', MONDAY + datetime.timedelta(minutes=30))],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5'),
                  Driver(id='d2', name='Lorena', home_location='Home', color_code='#4f46e5')])
    give_ups = [c['give_up'] for c in negotiation.candidates(pack, 'seed')]
    check(give_ups == sorted(give_ups),
          f"the queue is ordered before anything is solved, got {give_ups}")


def scenario_a_refused_shift_is_never_proposed_again():
    near = _event('near', MONDAY + datetime.timedelta(minutes=30), 'Piano')
    pack = _pack([_event('seed', MONDAY), near],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    storage.add_shift_refusal('near', 'Piano')
    moved = {m['event_id'] for c in negotiation.candidates(pack, 'seed')
             for m in c['mutations'] if m['lever'] == 'shift_event'}
    check('near' not in moved,
          f"somebody already said that cannot move, got {moved}")


def scenario_every_part_names_a_person():
    pack = _pack([_event('seed', MONDAY),
                  _event('near', MONDAY + datetime.timedelta(minutes=30))],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    found = False
    for c in negotiation.candidates(pack, 'seed'):
        for p in c['parts']:
            found = True
            check(p.get('ask_text'), f"a part with no question is not an ask: {p}")
            check('lever' in p, f"and it knows what it is asking for: {p}")
    check(found, "the pack should have produced at least one candidate to check")


def scenario_a_shift_is_never_proposed_for_an_event_nothing_can_move():
    """An event with no addressable calendar id can never be patched, so a
    shift for it is a promise the app cannot keep. `_check_part` would catch
    it -- but only AFTER everybody in the deal has already agreed, spending a
    family's goodwill on a change that was never possible. It has to be gone
    at generation time."""
    homemade = _event('homemade', MONDAY + datetime.timedelta(minutes=30),
                      'Errand', source=[])
    real = _event('real', MONDAY + datetime.timedelta(minutes=45), 'Piano')
    pack = _pack([_event('seed', MONDAY), homemade, real],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    moved = {m['event_id'] for c in negotiation.candidates(pack, 'seed')
             for m in c['mutations'] if m['lever'] == 'shift_event'}
    check('homemade' not in moved,
          f"nothing can write that event's new time, got {moved}")
    check('real' in moved,
          f"and the one with a real calendar id is still offered, got {moved}")


def scenario_a_shift_carries_the_time_the_ask_quoted():
    """The ask names an absolute clock time, so the part has to carry that
    time -- and the start it was computed from. Re-deriving it from
    `delta_mins` at apply time honours the arithmetic and breaks the promise
    if the event moved in between."""
    # A distinct id: an earlier scenario teaches the app that 'near' cannot
    # move, and this process shares one DB across every scenario in the file.
    near = _event('quoted', MONDAY + datetime.timedelta(minutes=30), 'Piano')
    pack = _pack([_event('seed', MONDAY), near],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    parts = [p for c in negotiation.candidates(pack, 'seed') for p in c['parts']
             if p['lever'] == 'shift_event' and p['payload']['event_id'] == 'quoted'
             and p['payload']['delta_mins'] == 15]
    check(parts, "expected a +15 shift for the neighbour")
    payload = parts[0]['payload']
    check(payload['from_start'] == near.start.isoformat(),
          f"the start the ask assumed is written down, got {payload}")
    check(payload['target_start'] == (near.start + datetime.timedelta(minutes=15)).isoformat(),
          f"and so is the time it quoted, got {payload}")
    check(payload['target_end'] == (near.end + datetime.timedelta(minutes=15)).isoformat(),
          f"both endpoints, or the duration silently changes, got {payload}")


def scenario_swap_drive_names_the_held_event_and_a_real_taker():
    """The swap lever has to find the event actually holding a driver by ID,
    not by matching `driver_options`' prose against a title -- a rewording of
    that sentence must not silently stop this lever from firing.

    The assignment map comes from a REAL replay of this pack, which is what
    `search()` passes in production. Hand-setting `previous_assignments`
    (what this test used to do) built an input the production caller does not
    supply: `previous_assignments` is the stickiness INPUT, so on a first
    refresh or after a cache clear it is empty and this lever produced
    nothing at all while the test went on passing.
    """
    # Three events starting within ten minutes of each other at three
    # different places (the harness charges ten minutes between any two), and
    # two drivers -- so the day genuinely cannot cover all three and the solve
    # itself, not a hand-written map, is what says who is on what.
    held = _event('held', MONDAY, 'Recital')
    seed = _event('seed', MONDAY + datetime.timedelta(minutes=5), 'Soccer')
    seed.location = 'Studio'
    extra = _event('extra', MONDAY + datetime.timedelta(minutes=10), 'Swim')
    extra.location = 'Pool'
    d1 = Driver(id='swap_d1', name='Priya', home_location='Home', color_code='#4f46e5')
    d2 = Driver(id='swap_d2', name='Sam', home_location='Home', color_code='#4f46e5')
    storage.add_driver({'id': 'swap_d1', 'name': 'Priya', 'color_code': '#4f46e5'})
    storage.add_driver({'id': 'swap_d2', 'name': 'Sam', 'color_code': '#4f46e5'})
    pack = _pack([held, seed, extra], [d1, d2])
    base = solve_pack.replay(pack)
    check('seed' in base['unassigned'],
          f"the baseline must really leave the seed uncovered, got {base}")
    check(base['assignments'].get('held'),
          f"and must really have somebody on the Recital, got {base['assignments']}")
    check(not pack['previous_assignments'],
          "with the stickiness input empty, or this proves nothing")
    swaps = [m for c in negotiation.candidates(pack, 'seed',
                                               assignments=base['assignments'])
             for m in c['mutations'] if m['lever'] == 'swap_drive']
    check(swaps, f"expected a swap candidate, got none from {pack['events']}")
    check(all(set(m.keys()) == {'lever', 'event_id', 'driver_id'} for m in swaps),
          f"swap_drive must match solve_pack.apply's contract exactly, got {swaps}")
    holder = base['assignments']['held']
    taker = 'swap_d2' if holder == 'swap_d1' else 'swap_d1'
    check(any(m['event_id'] == 'held' and m['driver_id'] == taker for m in swaps),
          f"the OTHER driver should be offered the Recital by id, got {swaps}")


def scenario_lift_protected_names_a_commitment_in_the_rule_index():
    """The lift-protected lever only fires for a commitment the pack actually
    knows how to remove -- one present in `protected_rule_index` -- and only
    for the member it actually belongs to."""
    seed = _event('seed', MONDAY)
    d1 = Driver(id='prot_d1', name='Alicia', home_location='Home', color_code='#4f46e5')
    storage.add_driver({'id': 'prot_d1', 'name': 'Alicia', 'color_code': '#4f46e5'})
    alicia = next(m for m in storage.get_all_members() if m.get('driver_id') == 'prot_d1')
    commitment_id = storage.add_protected_commitment({
        'id': 'commit1', 'member_id': alicia['id'], 'title': 'Run club',
        'days_of_week': [MONDAY.weekday()], 'time_start': '16:30',
        'time_end': '18:00', 'active': True})
    pack = _pack([seed], [d1], protected_index={commitment_id: 0})
    lifts = [m for c in negotiation.candidates(pack, 'seed')
             for m in c['mutations'] if m['lever'] == 'lift_protected']
    check(lifts, f"expected a lift_protected candidate, got none from {pack['events']}")
    check(all(set(m.keys()) == {'lever', 'commitment_id'} for m in lifts),
          f"lift_protected must match solve_pack.apply's contract exactly, got {lifts}")
    check(any(m['commitment_id'] == commitment_id for m in lifts),
          f"expected Run club's own id, got {lifts}")


def scenario_the_search_hands_candidates_this_days_own_assignments():
    """The production wiring, not a hand-built input: whatever `search()`
    passes as `assignments` must be the baseline replay's own result. Anything
    else and `driver_options` reasons about a different day."""
    pack = _pack([_event('seed', MONDAY),
                  _event('near', MONDAY + datetime.timedelta(minutes=30), 'Piano')],
                 [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')])
    seen = {}
    real = negotiation.candidates

    def spy(p, seed_id, assignments=None):
        seen['assignments'] = assignments
        return real(p, seed_id, assignments=assignments)

    negotiation.candidates = spy
    try:
        negotiation.search(pack, 'seed', budget=1)
    finally:
        negotiation.candidates = real
    expected = solve_pack.replay(pack)['assignments']
    check(seen.get('assignments') == expected,
          f"search must hand over the day's real result, got "
          f"{seen.get('assignments')} vs {expected}")
    check(expected, "and that result must not be empty, or this proves nothing")


if __name__ == '__main__':
    scenario_no_resolvable_owner_yields_no_ask()
    _seed_parent()
    scenario_shift_candidates_stay_in_the_window()
    scenario_a_skip_only_targets_an_optional()
    scenario_cheap_candidates_come_first()
    scenario_a_refused_shift_is_never_proposed_again()
    scenario_every_part_names_a_person()
    scenario_a_shift_is_never_proposed_for_an_event_nothing_can_move()
    scenario_a_shift_carries_the_time_the_ask_quoted()
    scenario_swap_drive_names_the_held_event_and_a_real_taker()
    scenario_lift_protected_names_a_commitment_in_the_rule_index()
    scenario_the_search_hands_candidates_this_days_own_assignments()
    print("test_negotiation_levers OK")
