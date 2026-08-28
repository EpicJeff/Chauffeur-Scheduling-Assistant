"""What the negotiator is allowed to propose, and what it never proposes."""
import datetime

from harness import check
from models.schemas import Driver, Event
from services import negotiation, solve_pack, storage

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice', mins=60, optional=False):
    ev = Event(id=eid, title=title, start=start,
               end=start + datetime.timedelta(minutes=mins),
               location='Field', calendar_ids=['c1'], source_event_ids=[eid])
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


if __name__ == '__main__':
    scenario_no_resolvable_owner_yields_no_ask()
    _seed_parent()
    scenario_shift_candidates_stay_in_the_window()
    scenario_a_skip_only_targets_an_optional()
    scenario_cheap_candidates_come_first()
    scenario_a_refused_shift_is_never_proposed_again()
    scenario_every_part_names_a_person()
    print("test_negotiation_levers OK")
