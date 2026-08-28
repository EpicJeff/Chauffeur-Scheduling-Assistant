"""A day's solver world, stored and replayed.

The whole negotiation arc rests on one property: replaying a pack unmutated
reproduces the assignments that day actually got. If it does not, an input is
missing and every deal built on the pack is fiction.
"""
import datetime
import json

from harness import check
from models.schemas import Driver, Event
from services import solve_pack, storage
from solver import matcher

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice'):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def _driver(did, name):
    return Driver(id=did, name=name, home_location='Home', color_code='#4f46e5')


def _world():
    events = [_event('e1', MONDAY), _event('e2', MONDAY, 'Piano')]
    drivers = [_driver('d1', 'Jeff'), _driver('d2', 'Lorena')]
    return events, drivers


def _pack(events, drivers):
    return solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=[],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={}, trip_metadata=[], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={})


def scenario_replay_reproduces_the_solve():
    events, drivers = _world()
    direct, _, _, _ = matcher.solve_schedule(events, drivers, [])
    out = solve_pack.replay(_pack(events, drivers))
    check(out['assignments'] == direct,
          f"replay matches a direct solve\n  direct={direct}\n  replay={out['assignments']}")
    check(isinstance(out['objective'], float), f"and reports a score, got {out}")


def scenario_roundtrip_through_storage():
    events, drivers = _world()
    pack = _pack(events, drivers)
    storage.save_solve_pack('2026-09-07', pack)
    loaded = storage.get_solve_pack('2026-09-07')
    check(loaded is not None, "the pack comes back")
    out = solve_pack.replay(loaded)
    check(out['assignments'] == solve_pack.replay(pack)['assignments'],
          "and a stored pack replays the same as the one in hand")


def scenario_saving_a_day_twice_keeps_one_row():
    events, drivers = _world()
    storage.save_solve_pack('2026-09-07', _pack(events, drivers))
    storage.save_solve_pack('2026-09-07', _pack(events, drivers))
    with storage.db_lock:
        rows = [dict(r) for r in storage.solve_packs_table.all()]
    check(len([r for r in rows if r['date'] == '2026-09-07']) == 1,
          f"one row per day, got {len(rows)}")


def scenario_a_real_trip_survives_the_json_round_trip():
    # A trip entry is a plain dict (main.py builds it with a raw datetime for
    # start/end and a raw set for entities, never a pydantic model), so it is
    # the one input build() cannot just hand to _dump and trust.
    events, drivers = _world()
    trip = {'id': 'trip1', 'start': MONDAY, 'end': MONDAY + datetime.timedelta(hours=3),
            'title': 'Away Game', 'location': 'Stadium',
            'entities': {'driver_d1', 'passenger_c1'}, 'all_day': False}
    pack = solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=[],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={}, trip_metadata=[trip], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={})

    check(trip['start'] == MONDAY and isinstance(trip['entities'], set),
          "build() must not mutate the caller's trip dict")

    json.dumps(pack)  # raises TypeError on a bare datetime or set

    storage.save_solve_pack('2026-09-07', pack)
    loaded = storage.get_solve_pack('2026-09-07')

    captured = {}
    real_solve = matcher.solve_schedule
    def _spy(*args, **kwargs):
        captured['trip_metadata'] = kwargs.get('trip_metadata')
        return real_solve(*args, **kwargs)
    matcher.solve_schedule = _spy
    try:
        solve_pack.replay(loaded)
    finally:
        matcher.solve_schedule = real_solve

    replayed_trip = captured['trip_metadata'][0]
    check(isinstance(replayed_trip['start'], datetime.datetime),
          f"replay hands the solver a real datetime, got {type(replayed_trip['start'])}")
    check(isinstance(replayed_trip['entities'], set),
          f"and a real set, got {type(replayed_trip['entities'])}")


def scenario_an_incomplete_pack_is_refused():
    broken = dict(_pack(*_world()))
    broken.pop('driver_events')
    try:
        solve_pack.replay(broken)
    except ValueError as e:
        check('driver_events' in str(e), f"it names what is missing, got {e}")
        return
    check(False, "a pack missing an input must refuse to replay, not guess")


if __name__ == '__main__':
    scenario_replay_reproduces_the_solve()
    scenario_roundtrip_through_storage()
    scenario_saving_a_day_twice_keeps_one_row()
    scenario_a_real_trip_survives_the_json_round_trip()
    scenario_an_incomplete_pack_is_refused()
    print("test_solve_pack OK")
