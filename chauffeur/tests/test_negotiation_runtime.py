"""A pack built the way the refresh builds one really replays.

This does NOT run the refresh's own call to `solve_pack.build` -- it calls
`build`/`save_solve_pack`/`replay` directly with hand-authored arguments that
only mirror the call site's keyword names. A mistyped variable at the real
call site would raise, be swallowed by that call's by-design try/except (a
family's schedule must never break because a pack failed to write), and leave
zero packs behind with nothing but a warning in the log -- and this test would
still pass, because it never touches that code path at all.

What this guards instead: `build`'s signature and the prune helper. If a
later change renames or reorders a `build` keyword, or changes what
`prune_solve_packs` expects, it breaks here first -- which is exactly the
kind of drift the refresh's swallowed exception would otherwise hide from
every other test in the suite. The refresh's actual wiring -- that the
keyword names it passes match `build`'s signature, and that every variable
it references is genuinely in scope at the call site -- was verified by hand
against the source (see the task report); confirming it end to end still
means a real refresh on a real device, because that is the only place the
swallowed exception's silence would actually show up.
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
