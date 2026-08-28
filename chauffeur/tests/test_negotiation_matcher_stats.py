"""solve_schedule reports what it did, and can be given less time."""
import datetime

from harness import check
from models.schemas import Driver, Event
from solver import matcher

MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _event(eid, start, title='Practice'):
    return Event(id=eid, title=title, start=start,
                 end=start + datetime.timedelta(hours=1),
                 location='Field', calendar_ids=['c1'], source_event_ids=[eid])


def _driver(did, name):
    return Driver(id=did, name=name, home_location='Home', color_code='#4f46e5')


def scenario_stats_are_reported():
    events = [_event('e1', MONDAY)]
    drivers = [_driver('d1', 'Jeff')]
    stats = {}
    assignments, unassigned, _, _ = matcher.solve_schedule(
        events, drivers, [], stats=stats)
    check(assignments.get('e1') == 'd1', f"the one driver takes it, got {assignments}")
    check(stats.get('status') in ('OPTIMAL', 'FEASIBLE'),
          f"the status comes back, got {stats}")
    check(isinstance(stats.get('objective'), float),
          f"and so does the objective, got {stats}")


def scenario_time_limit_is_honoured():
    events = [_event('e1', MONDAY)]
    drivers = [_driver('d1', 'Jeff')]
    stats = {}
    matcher.solve_schedule(events, drivers, [], time_limit_s=0.5, stats=stats)
    check(stats.get('wall_time') is not None, f"wall time is reported, got {stats}")
    check(stats['wall_time'] < 5.0, f"and the short cap was used, got {stats}")


def scenario_stats_is_optional():
    # The existing caller passes neither parameter and must be unaffected.
    events = [_event('e1', MONDAY)]
    out = matcher.solve_schedule(events, [_driver('d1', 'Jeff')], [])
    check(len(out) == 4, f"still a four-tuple, got {len(out)}")


if __name__ == '__main__':
    scenario_stats_are_reported()
    scenario_time_limit_is_honoured()
    scenario_stats_is_optional()
    print("test_negotiation_matcher_stats OK")
