"""The trip itinerary is scheduled on the server, by one path (planned
missions spec §3 row Trips, Codex H3).

`auto_schedule_trip_itinerary` only returns a `ui_action` for the trip page's
JavaScript and schedules nothing, so a mission could "schedule" a trip and
leave every POI unplaced. The CP-SAT bulk path inside
`main.schedule_pois_bulk_api` moves into `services/trip_schedule.py` so the
endpoint and a registry tool share it; it stays the only writer of itinerary
state (locked: trip scheduling ownership).

Pinned here (Task 3):
  * `trip_schedule.iter_bulk(event_id, poi_ids)` yields the scheduler's per-POI
    results and persists them (the endpoint's streaming body is this);
  * `trip_schedule.run_bulk(event_id, poi_ids=None)` consumes it and returns
    {'scheduled': [poi_id], 'unplaced': [{'poi_id', 'reason'}]}; None means
    every unscheduled POI; the windows are stored;
  * a POI that cannot fit is reported, not dropped;
  * the endpoint's stream and `run_bulk` store the same itinerary;
  * the registry write `schedule_trip_itinerary(trip_id)` runs it with no
    trip-page JavaScript and says how many it placed.

Run from chauffeur/:  python tests/test_trip_schedule.py
"""
import asyncio
import datetime
import json

from harness import check, mk_trip, mk_poi, mk_acc, MONDAY  # noqa: F401
from services import storage

PARK = (28.4177, -81.5812)


def _trip(extra_pois=()):
    storage.trip_metadata_table.truncate()
    hotel = mk_acc('Pop Century', *PARK, MONDAY, MONDAY + datetime.timedelta(days=3))
    trip = mk_trip(days=3, accommodations=[hotel], location='Orlando')
    trip.pois = [mk_poi('Magic Kingdom', *PARK, category='sightseeing', duration_mins=240),
                 mk_poi("Chef Mickey's", *PARK, category='food', duration_mins=60),
                 *extra_pois]
    meta = trip.model_dump()
    storage.set_trip_metadata(trip.event_id, meta)
    return trip


def _stored(event_id):
    return {p['id']: p for p in (storage.get_trip_metadata(event_id) or {}).get('pois') or []}


def scenario_run_bulk_schedules_and_stores_every_unscheduled_poi():
    from services import trip_schedule
    trip = _trip()
    out = trip_schedule.run_bulk(trip.event_id)
    ids = {p.id for p in trip.pois}
    check(set(out.get('scheduled') or []) == ids and out.get('unplaced') == [], f"both placed: {out}")
    stored = _stored(trip.event_id)
    for pid in ids:
        p = stored[pid]
        check(p.get('is_scheduled') and p.get('scheduled_start') and p.get('scheduled_end'), f"a stored window for {p.get('name')}: {p}")


def scenario_a_poi_that_cannot_fit_is_reported():
    from services import trip_schedule
    huge = mk_poi('Every ride twice', *PARK, category='sightseeing', duration_mins=60 * 24 * 10)
    trip = _trip([huge])
    out = trip_schedule.run_bulk(trip.event_id)
    unplaced = {u['poi_id']: u for u in out.get('unplaced') or []}
    check(huge.id in unplaced and unplaced[huge.id].get('reason'), f"reported with a reason: {out}")
    check(not _stored(trip.event_id)[huge.id].get('is_scheduled'), "and left unscheduled")


def scenario_the_endpoint_streams_the_same_path():
    import main
    from services import trip_schedule
    trip = _trip()
    ids = [p.id for p in trip.pois]
    resp = main.schedule_pois_bulk_api(trip.event_id, {'poi_ids': ids})

    async def _drain(it):
        return [chunk async for chunk in it]
    body = ''.join(c if isinstance(c, str) else c.decode() for c in asyncio.run(_drain(resp.body_iterator)))
    rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    # The stream also carries the scheduler's own summary row; the contract keeps it.
    poi_rows = [r for r in rows if r.get('poi_id')]
    check(len(poi_rows) == 2 and all(r.get('success') for r in poi_rows), f"the stream reports both stops: {rows}")
    via_endpoint = {pid: (p.get('scheduled_start'), p.get('scheduled_end')) for pid, p in _stored(trip.event_id).items()}
    trip2 = _trip()
    for a, b in zip(trip2.pois, trip.pois):
        a.id = b.id
    storage.set_trip_metadata(trip.event_id, {**trip2.model_dump(), 'event_id': trip.event_id})
    trip_schedule.run_bulk(trip.event_id, ids)
    via_tool = {pid: (p.get('scheduled_start'), p.get('scheduled_end')) for pid, p in _stored(trip.event_id).items()}
    check(via_endpoint == via_tool, f"one path, one result:\n{via_endpoint}\n{via_tool}")


def scenario_the_registry_tool_schedules_without_the_page():
    from services import agent_tools_v2 as tools
    trip = _trip()
    check('schedule_trip_itinerary' in tools.TOOL_HANDLERS, "a registry write")
    out = tools.execute_tool('schedule_trip_itinerary', {'trip_id': trip.event_id}, actor={'id': 'mom', 'role': 'parent'})
    check(out.get('status') == 'success' and '2' in (out.get('message') or '') and not out.get('ui_action'),
          f"placed on the server and says how many: {out}")
    check(all(p.get('is_scheduled') for p in _stored(trip.event_id).values()), "stored")
    missing = tools.execute_tool('schedule_trip_itinerary', {'trip_id': 'nope'}, actor={'id': 'mom', 'role': 'parent'})
    check(missing.get('status') == 'error', f"no such trip: {missing}")


SCENARIOS = [
    scenario_run_bulk_schedules_and_stores_every_unscheduled_poi,
    scenario_a_poi_that_cannot_fit_is_reported,
    scenario_the_endpoint_streams_the_same_path,
    scenario_the_registry_tool_schedules_without_the_page,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
