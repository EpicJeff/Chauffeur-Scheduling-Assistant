"""One day's solver world, written down so it can be asked a second question.

`matcher.solve_schedule` is a pure function, but its arguments are not: they
are assembled across 1300 lines of `_refresh_schedule_logic_impl` -- calendars
fetched, trips resolved, outside hands removed, protected commitments turned
into `unavailable` rules. Two of those inputs cannot be recovered afterwards:

- `driver_events`, a driver's own calendar, which carries the `+50,000,000`
  attendance term and in practice decides assignments on its own. It is built
  during the calendar fetch and is not in the day cache.
- the rule list, assembled from three sources that no single table holds.

So the refresh writes down what it handed the solver. The negotiator replays
THAT, which is the only way its answers describe the schedule the family
actually has rather than one that resembles it.

Nothing here mutates anything. `apply` returns a new pack; `replay` runs a
solve and returns numbers. Whoever wants to change the world does it somewhere
else, after a person has agreed.
"""
import copy
import datetime

from models.schemas import Car, Driver, Event, ManualOverride, Passenger, PriorityRule, Rule
from solver import matcher

PACK_KEYS = ('date', 'events', 'drivers', 'rules', 'priority_rules', 'overrides',
             'passengers', 'cars', 'driver_events', 'trip_metadata',
             'driver_passenger_map', 'previous_assignments', 'load_balancing',
             'load_balancing_metric', 'protected_rule_index')

# Every replay is one of many in a single question, so it gets a shorter leash
# than the daily solve's five seconds.
DEFAULT_TIME_LIMIT_S = 2.0


def _dump(obj):
    if hasattr(obj, 'model_dump'):
        return obj.model_dump(mode='json')
    if hasattr(obj, 'dict'):
        return obj.dict()
    return obj


def _dump_trip(t):
    """A trip entry is a plain dict, not a model, so `_dump` passes it through
    untouched -- but the pack is JSON, and `start`/`end`/`entities` are the
    two Python types JSON cannot hold: a `datetime` and a `set`. Left alone,
    they reach `json.dump`/`json.dumps` in the storage layer and blow up on
    the first day that has a trip. A copy, not a mutation -- the caller's
    dict is still theirs after this returns."""
    t = dict(t)
    for field in ('start', 'end'):
        val = t.get(field)
        if isinstance(val, datetime.datetime):
            t[field] = val.isoformat()
    if 'entities' in t:
        t['entities'] = list(t['entities'])
    return t


def build(date_str, *, events, drivers, rules, priority_rules, overrides,
          passengers, cars, driver_events, trip_metadata, driver_passenger_map,
          previous_assignments, load_balancing, load_balancing_metric,
          protected_rule_index) -> dict:
    """Everything `solve_schedule` was given, as plain JSON-able data.

    `protected_rule_index` maps a protected commitment's id to its position in
    `rules`. The refresh is the only place that knows which rule came from
    which commitment -- the `Rule` object itself carries no provenance -- and
    without it the lift-a-protected-window lever cannot name what it is
    lifting.
    """
    return {
        'date': date_str,
        'events': [_dump(e) for e in events],
        'drivers': [_dump(d) for d in drivers],
        'rules': [_dump(r) for r in rules],
        'priority_rules': [_dump(p) for p in priority_rules],
        'overrides': [_dump(o) for o in overrides],
        'passengers': [_dump(p) for p in passengers],
        'cars': [_dump(c) for c in cars],
        'driver_events': {str(k): [_dump(e) for e in v]
                          for k, v in (driver_events or {}).items()},
        'trip_metadata': [_dump_trip(t) for t in (trip_metadata or [])],
        'driver_passenger_map': dict(driver_passenger_map or {}),
        'previous_assignments': dict(previous_assignments or {}),
        'load_balancing': bool(load_balancing),
        'load_balancing_metric': load_balancing_metric or 'occupied_time',
        'protected_rule_index': dict(protected_rule_index or {}),
        'written_at': datetime.datetime.now().timestamp(),
    }


def _check(pack: dict):
    missing = [k for k in PACK_KEYS if k not in pack]
    if missing:
        raise ValueError(f"solve pack is missing {', '.join(missing)} — it was "
                         f"written by an older refresh and cannot be replayed")


def apply(pack: dict, mutations: list) -> dict:
    """A copy of the pack with the mutations applied. The original is untouched.

    Mutations are the negotiation levers, each occurrence-scoped:
        {'lever': 'shift_event',    'event_id': str, 'delta_mins': int}
        {'lever': 'lift_protected', 'commitment_id': str}
        {'lever': 'swap_drive',     'event_id': str, 'driver_id': str}
        {'lever': 'skip_optional',  'event_id': str}
    """
    out = copy.deepcopy(pack)
    for m in mutations or []:
        lever = m.get('lever')
        if lever == 'shift_event':
            delta = datetime.timedelta(minutes=int(m['delta_mins']))
            for e in out['events']:
                if str(e.get('id')) != str(m['event_id']):
                    continue
                for field in ('start', 'end'):
                    raw = e.get(field)
                    if raw:
                        e[field] = (datetime.datetime.fromisoformat(str(raw))
                                    + delta).isoformat()
        elif lever == 'lift_protected':
            idx = out['protected_rule_index'].get(str(m['commitment_id']))
            if idx is None or idx >= len(out['rules']):
                raise ValueError(f"no protected rule for commitment {m['commitment_id']}")
            out['rules'] = [r for i, r in enumerate(out['rules']) if i != idx]
            # Every later index shifts by one; keep the map honest so a second
            # lift in the same candidate does not remove the wrong rule.
            out['protected_rule_index'] = {
                k: (v - 1 if v > idx else v)
                for k, v in out['protected_rule_index'].items()
                if v != idx}
        elif lever == 'swap_drive':
            out['overrides'].append({'event_id': str(m['event_id']),
                                     'driver_id': str(m['driver_id']),
                                     'created_at': out['written_at'],
                                     'source': 'negotiation'})
        elif lever == 'skip_optional':
            out['events'] = [e for e in out['events']
                             if str(e.get('id')) != str(m['event_id'])]
        else:
            raise ValueError(f"unknown lever '{lever}'")
    return out


def replay(pack: dict, time_limit_s: float = DEFAULT_TIME_LIMIT_S) -> dict:
    """Solve this pack. Returns what happened; changes nothing."""
    _check(pack)
    events = [Event(**e) for e in pack['events']]
    drivers = [Driver(**d) for d in pack['drivers']]
    driver_events = {k: [Event(**e) for e in v]
                     for k, v in pack['driver_events'].items()}
    trips = []
    for t in pack['trip_metadata']:
        t = dict(t)
        for field in ('start', 'end'):
            if isinstance(t.get(field), str):
                t[field] = datetime.datetime.fromisoformat(t[field])
        t['entities'] = set(t.get('entities') or [])
        trips.append(t)
    stats = {}
    assignments, unassigned, lateness, cars_out = matcher.solve_schedule(
        events, drivers,
        [Rule(**r) for r in pack['rules']],
        [PriorityRule(**p) for p in pack['priority_rules']],
        overrides=[ManualOverride(**o) for o in pack['overrides']],
        previous_assignments=dict(pack['previous_assignments']),
        driver_events=driver_events,
        passengers=[Passenger(**p) for p in pack['passengers']],
        trip_metadata=trips,
        load_balancing=pack['load_balancing'],
        load_balancing_metric=pack['load_balancing_metric'],
        cars=[Car(**c) for c in pack['cars']],
        driver_passenger_map=dict(pack['driver_passenger_map']),
        time_limit_s=time_limit_s, stats=stats)
    # No `conflicts` and no `true_unassigned` here, deliberately. Both would
    # be lies of a different kind: `compute_conflicts` pairs assignments
    # against GHOST routes, which a replay does not solve, so it could only
    # ever return `{}` -- a documented no-op in the negotiator's hot path. And
    # `true_unassigned` means something specific everywhere else in this app
    # (`unassigned` MINUS what a ghost route covers, main.py's refresh), so
    # publishing a copy of `unassigned` under that name would put two meanings
    # on one key. A caller that wants either must solve ghost routes itself.
    return {'assignments': assignments, 'unassigned': list(unassigned),
            'lateness_warnings': lateness, 'car_assignments': cars_out,
            'objective': float(stats.get('objective') or 0.0),
            'status': stats.get('status') or 'UNKNOWN'}
