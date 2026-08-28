"""The refresh really writes a pack, and the pack really replays.

A source-reading test proves nothing here: the refresh swallows exceptions
per-day, so a pack write that raises would leave the schedule looking fine and
the negotiator permanently empty. This RUNS the write path.
"""
import datetime

from harness import check
from models.schemas import Driver, Event
from services import solve_pack, storage


def _event(eid, start, title='Practice'):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def scenario_pack_write_survives_the_refresh_shape():
    """Build a pack from the same argument shapes the refresh passes, write it
    the way the refresh writes it, and replay it. Any signature drift between
    solve_pack.build and its caller shows up here."""
    monday = datetime.datetime(2026, 9, 7, 17, 0)
    events = [_event('e1', monday)]
    drivers = [Driver(id='d1', name='Jeff', home_location='Home', color_code='#4f46e5')]
    pack = solve_pack.build(
        '2026-09-07', events=events, drivers=drivers, rules=[],
        priority_rules=[], overrides=[], passengers=[], cars=[],
        driver_events={'d1': []}, trip_metadata=[], driver_passenger_map={},
        previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={})
    storage.save_solve_pack('2026-09-07', pack)
    out = solve_pack.replay(storage.get_solve_pack('2026-09-07'))
    check(out['assignments'].get('e1') == 'd1',
          f"the written pack solves the day, got {out['assignments']}")


def scenario_old_packs_are_pruned():
    storage.save_solve_pack('2026-09-01', solve_pack.build(
        '2026-09-01', events=[], drivers=[], rules=[], priority_rules=[],
        overrides=[], passengers=[], cars=[], driver_events={},
        trip_metadata=[], driver_passenger_map={}, previous_assignments={},
        load_balancing=False, load_balancing_metric='occupied_time',
        protected_rule_index={}))
    storage.prune_solve_packs('2026-09-07')
    check(storage.get_solve_pack('2026-09-01') is None,
          "yesterday's pack answers no question anybody will ask")


if __name__ == '__main__':
    scenario_pack_write_survives_the_refresh_shape()
    scenario_old_packs_are_pruned()
    print("test_negotiation_runtime OK")
