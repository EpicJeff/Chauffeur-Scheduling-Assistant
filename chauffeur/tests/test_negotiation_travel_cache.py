"""Proves the negotiator's travel lookups cannot buy anything.

`harness.py` replaces `maps.get_travel_time_minutes` with an offline mock the
moment it is imported, and every OTHER test in this suite -- including this
task's own `test_negotiation_cost.py` -- runs entirely behind that mock. The
mock has no idea `travel_cache_only()` exists; it would pass any assertion
made about the guard without the guard doing a single thing. So this file
captures the REAL function before harness gets a chance to replace it, and
replays harness's own setup (temp data dir, sys.path) by hand first -- in
that order, on purpose -- so importing `services.maps` early never resolves
to the real data/ directory.
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault("CHAUFFEUR_DATA_DIR",
                      tempfile.mkdtemp(prefix="chauffeur_travelcache_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import maps as _pristine_maps  # noqa: E402  before harness patches it
_REAL_GET_TRAVEL_TIME_MINUTES = _pristine_maps.get_travel_time_minutes

from harness import check  # noqa: E402
from models.schemas import Driver, Event  # noqa: E402
from services import maps, negotiation, solve_pack, storage  # noqa: E402
from solver import matcher  # noqa: E402

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


def scenario_cache_only_blocks_a_live_fetch():
    """Against the REAL `get_travel_time_minutes` (not the offline mock):
    a cache miss normally primes the cache -- that IS the live fetch. Under
    `travel_cache_only()` the same miss must raise instead, and must never
    reach `prime_matrix_cache` at all."""
    calls = []
    real_prime, real_geocode = maps.prime_matrix_cache, maps.geocode_address
    real_cached = storage.get_cached_travel_time
    maps.prime_matrix_cache = lambda *a, **kw: calls.append((a, kw))
    maps.geocode_address = lambda addr: None  # no network for the distance floor either
    storage.get_cached_travel_time = lambda *a, **kw: None  # always a miss
    try:
        # Outside the guard: a miss is the ordinary "go buy it" path.
        _REAL_GET_TRAVEL_TIME_MINUTES('Alpha', 'Beta')
        check(len(calls) == 1,
              f"a plain cache miss must still prime the cache: {calls}")

        # Inside the guard: the identical miss is refused, not fetched.
        calls.clear()
        raised = False
        try:
            with maps.travel_cache_only():
                _REAL_GET_TRAVEL_TIME_MINUTES('Alpha', 'Beta')
        except maps.UncachedTravelPair:
            raised = True
        check(raised, "an uncached pair under travel_cache_only() must raise")
        check(len(calls) == 0,
              f"travel_cache_only() must never reach prime_matrix_cache: {calls}")
    finally:
        maps.prime_matrix_cache, maps.geocode_address = real_prime, real_geocode
        storage.get_cached_travel_time = real_cached


def scenario_search_runs_its_replays_cache_only():
    """`negotiation.search` must itself enter `travel_cache_only()` around its
    replays -- proven by making matcher's travel function raise ONLY while the
    guard reports itself active, and checking that search() absorbs the raise
    as an ordinary candidate failure (drops it, keeps going) rather than a
    crash, and that the guard never leaks past search() into the rest of the
    process."""
    pack = _pack([_event('seed', MONDAY), _event('other', MONDAY, 'Dentist')],
                 [Driver(id='d1', name='Jeff', home_location='Home',
                         color_code='#4f46e5')])

    seen_active = []

    def fake_travel(origin, dest, departure_time=None, return_traffic=False):
        active = maps.travel_cache_only_active()
        seen_active.append(active)
        if active:
            raise maps.UncachedTravelPair(f"{origin} -> {dest}")
        return (10, 0) if return_traffic else 10

    real_raw = matcher._raw_get_travel_time_minutes
    matcher._raw_get_travel_time_minutes = fake_travel
    try:
        deals = negotiation.search(pack, 'seed', budget=4)
    finally:
        matcher._raw_get_travel_time_minutes = real_raw

    check(deals == [],
          f"every replay needed an uncached pair, so nothing should survive: {deals}")
    check(any(seen_active),
          "search() must run its own replays under travel_cache_only()")
    check(not maps.travel_cache_only_active(),
          "the guard must not leak past search()'s replays")


if __name__ == '__main__':
    scenario_cache_only_blocks_a_live_fetch()
    scenario_search_runs_its_replays_cache_only()
    print("test_negotiation_travel_cache OK")
