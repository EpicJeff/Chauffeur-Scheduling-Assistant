"""Tests for the agent trip-accommodation tools (multi-leg trip support).

Proves the flow the user expects: telling the agent "4 days in Paris, then 3
days in wine country, then 2 days at the coast, then a final night in Paris"
can be expressed through add/edit_trip_accommodation with 1-indexed trip
nights, and the resulting stays drive the scheduler's per-day home bases.

Run from chauffeur/:  python tests/test_agent_trip_tools.py
"""
import datetime
import os
import sys
import tempfile
import zoneinfo

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_agenttools_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import agent_tools, storage, trip_planner  # noqa: E402

# offline: no place enrichment lookups
trip_planner.enrich_poi_data = lambda name, location, trip_location: {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


MOCK_START = datetime.datetime(2030, 1, 1, 9, 0, tzinfo=datetime.timezone.utc)
TRIP_NIGHTS = 10


def mk_draft(event_id):
    storage.set_trip_metadata(event_id, {
        "event_id": event_id,
        "is_draft": True,
        "title": "France Loop",
        "location": "France",
        "draft_duration_nights": TRIP_NIGHTS,
        "mock_start_date": MOCK_START.timestamp(),
        "mock_end_date": (MOCK_START + datetime.timedelta(days=TRIP_NIGHTS)).timestamp(),
        "pois": [],
        "accommodations": [],
    })


def add(event_id, name, **kw):
    res = agent_tools.handle_add_trip_accommodation(
        dict(event_id=event_id, name=name, location=name, **kw))
    check(res["status"] == "success", f"add failed: {res}")
    return res


def get_accs(event_id):
    return storage.get_trip_metadata(event_id)["accommodations"]


def scenario_multi_leg_by_trip_nights():
    """The Paris -> wine country -> coast -> Paris trip, by night ordinals."""
    mk_draft("draft_trip_legs")
    add("draft_trip_legs", "Paris Hotel", check_in_night=1, nights=4)
    add("draft_trip_legs", "Wine Chateau", check_in_night=5, nights=3)
    add("draft_trip_legs", "Coast Inn", check_in_night=8, nights=2)
    add("draft_trip_legs", "Paris Finale", check_in_night=10, nights=1)

    accs = get_accs("draft_trip_legs")
    stays = {a["name"]: (a["check_in_date"], a["check_out_date"]) for a in accs}
    check(stays["Paris Hotel"] == ("2030-01-01", "2030-01-05"), f"leg 1 dates: {stays}")
    check(stays["Wine Chateau"] == ("2030-01-05", "2030-01-08"), f"leg 2 dates: {stays}")
    check(stays["Coast Inn"] == ("2030-01-08", "2030-01-10"), f"leg 3 dates: {stays}")
    check(stays["Paris Finale"] == ("2030-01-10", "2030-01-11"), f"leg 4 dates: {stays}")

    # end-to-end: the scheduler's day grid must use each leg as that day's home base
    from models.schemas import TripMetadata
    from services.trip_scheduler import _build_day_grid
    trip = TripMetadata(**storage.get_trip_metadata("draft_trip_legs"))
    days = _build_day_grid(trip, MOCK_START, MOCK_START + datetime.timedelta(days=TRIP_NIGHTS),
                           zoneinfo.ZoneInfo("UTC"))
    base_by_date = {d.date.isoformat(): (d.accommodation.name if d.accommodation else None)
                    for d in days}
    for date, want in [("2030-01-01", "Paris Hotel"), ("2030-01-04", "Paris Hotel"),
                       ("2030-01-05", "Wine Chateau"), ("2030-01-07", "Wine Chateau"),
                       ("2030-01-08", "Coast Inn"), ("2030-01-09", "Coast Inn"),
                       ("2030-01-10", "Paris Finale")]:
        check(base_by_date.get(date) == want,
              f"{date} should be based at {want}, got {base_by_date.get(date)}")


def scenario_default_full_span():
    mk_draft("draft_trip_default")
    add("draft_trip_default", "Only Hotel")
    a = get_accs("draft_trip_default")[0]
    check(a["check_in_date"] == "2030-01-01" and a["check_out_date"] == "2030-01-11",
          f"no dates given -> full trip span, got {a['check_in_date']} -> {a['check_out_date']}")


def scenario_explicit_dates_win():
    mk_draft("draft_trip_explicit")
    add("draft_trip_explicit", "Datesetter",
        check_in_date="2030-01-03", check_out_date="2030-01-06", check_in_night=9, nights=1)
    a = get_accs("draft_trip_explicit")[0]
    check((a["check_in_date"], a["check_out_date"]) == ("2030-01-03", "2030-01-06"),
          "explicit dates beat ordinals")


def scenario_ordinal_clamped_to_trip_end():
    mk_draft("draft_trip_clamp")
    add("draft_trip_clamp", "Overrun", check_in_night=9, nights=10)
    a = get_accs("draft_trip_clamp")[0]
    check((a["check_in_date"], a["check_out_date"]) == ("2030-01-09", "2030-01-11"),
          f"overrunning stay clamps to trip end, got {a['check_in_date']} -> {a['check_out_date']}")


def scenario_edit_accommodation():
    mk_draft("draft_trip_edit")
    add("draft_trip_edit", "Paris Hotel")   # full span by default

    # re-date by night ordinals, matched by (partial) name, then add the next leg
    res = agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_edit", "name": "paris", "check_in_night": 1, "nights": 4})
    check(res["status"] == "success", f"edit failed: {res}")
    add("draft_trip_edit", "Wine Chateau", check_in_night=5, nights=6)
    stays = {a["name"]: (a["check_in_date"], a["check_out_date"]) for a in get_accs("draft_trip_edit")}
    check(stays["Paris Hotel"] == ("2030-01-01", "2030-01-05"), f"edited leg 1: {stays}")
    check(stays["Wine Chateau"] == ("2030-01-05", "2030-01-11"), f"edited leg 2: {stays}")

    # nights-only edit keeps the current check-in as baseline
    agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_edit", "name": "Wine Chateau", "nights": 3})
    a = {x["name"]: x for x in get_accs("draft_trip_edit")}["Wine Chateau"]
    check((a["check_in_date"], a["check_out_date"]) == ("2030-01-05", "2030-01-08"),
          f"nights-only edit shortens from existing check-in, got {a['check_in_date']} -> {a['check_out_date']}")

    # rename + notes; miss and ambiguity errors
    agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_edit", "name": "Paris Hotel", "new_name": "Le Meurice", "notes": "splurge"})
    names = [a["name"] for a in get_accs("draft_trip_edit")]
    check("Le Meurice" in names, "rename applied")
    res = agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_edit", "name": "Nonexistent Place"})
    check(res["status"] == "error", "missing accommodation -> error")
    add("draft_trip_edit", "Twin A", check_in_night=8, nights=1)
    add("draft_trip_edit", "Twin B", check_in_night=9, nights=2)
    res = agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_edit", "name": "Twin", "nights": 1})
    check(res["status"] == "error" and "Multiple" in res["message"], "ambiguous name -> error")


def scenario_overlapping_add_rejected():
    """Adding a stay that overlaps an existing one is rejected with agent-facing
    guidance in trip nights (never mock dates) — overlaps poison the scheduler's
    day->home-base map."""
    mk_draft("draft_trip_overlap")
    add("draft_trip_overlap", "Paris Hotel", check_in_night=1, nights=4)
    res = agent_tools.handle_add_trip_accommodation(dict(
        event_id="draft_trip_overlap", name="Rival Hotel", location="Rival Hotel",
        check_in_night=3, nights=3))
    check(res["status"] == "error", f"overlapping add must be rejected: {res}")
    check("nights" in res["message"] and "2030" not in res["message"],
          f"guidance speaks in trip nights, not mock dates: {res['message']}")
    check(len(get_accs("draft_trip_overlap")) == 1, "rejected stay must not be persisted")

    # zero-night stay rejected too
    res = agent_tools.handle_add_trip_accommodation(dict(
        event_id="draft_trip_overlap", name="Blip Inn", location="Blip Inn",
        check_in_date="2030-01-06", check_out_date="2030-01-06"))
    check(res["status"] == "error", f"zero-night add must be rejected: {res}")


def scenario_edit_clips_neighbors():
    """Re-dating a stay clips neighboring stays to make room (rejecting would
    deadlock two full-span stays), but never silently swallows one whole."""
    mk_draft("draft_trip_clip")
    add("draft_trip_clip", "Paris Hotel", check_in_night=1, nights=4)     # nights 1-4
    add("draft_trip_clip", "Wine Chateau", check_in_night=5, nights=6)    # nights 5-10
    res = agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_clip", "name": "Wine Chateau", "check_in_night": 4, "nights": 7})
    check(res["status"] == "success", f"edit failed: {res}")
    stays = {a["name"]: (a["check_in_date"], a["check_out_date"]) for a in get_accs("draft_trip_clip")}
    check(stays["Wine Chateau"] == ("2030-01-04", "2030-01-11"), f"edited stay applied: {stays}")
    check(stays["Paris Hotel"] == ("2030-01-01", "2030-01-04"),
          f"neighbor clipped to make room: {stays}")
    check("Adjusted neighboring stays" in res["message"], "clip reported to the agent")

    # an edit that would fully cover another stay is rejected, not silently applied
    res = agent_tools.handle_edit_trip_accommodation(
        {"event_id": "draft_trip_clip", "name": "Wine Chateau", "check_in_night": 1, "nights": 10})
    check(res["status"] == "error" and "fully cover" in res["message"],
          f"swallowing edit must be rejected: {res}")
    stays = {a["name"]: (a["check_in_date"], a["check_out_date"]) for a in get_accs("draft_trip_clip")}
    check(stays["Wine Chateau"] == ("2030-01-04", "2030-01-11"), "rejected edit changed nothing")


def scenario_poi_gate_demotes_and_keeps_anchors():
    """The agent POI path runs through the same ingest gate as plan generation:
    a 60-min 'anchor' is demoted (with a note back to the agent); real multi-day
    anchors are stored as ONE POI with days_claimed."""
    mk_draft("draft_trip_poigate")
    res = agent_tools.handle_add_trip_poi(dict(
        event_id="draft_trip_poigate", name="Quick Museum", location="Quick Museum",
        duration_mins=60, is_background=True))
    check(res["status"] == "success", f"add failed: {res}")
    check("regular POI" in res["message"], f"demotion reported to the agent: {res['message']}")
    res = agent_tools.handle_add_trip_poi(dict(
        event_id="draft_trip_poigate", name="Magic Kingdom", location="Magic Kingdom",
        duration_mins=600, is_background=True, days_claimed=3))
    check(res["status"] == "success", f"add failed: {res}")
    pois = {p["name"]: p for p in storage.get_trip_metadata("draft_trip_poigate")["pois"]}
    check(not pois["Quick Museum"]["is_background"], "60-min 'anchor' stored as regular POI")
    check(pois["Magic Kingdom"]["is_background"] and pois["Magic Kingdom"]["days_claimed"] == 3,
          "multi-day anchor stored as one POI with days_claimed")
    check(len(pois) == 2, "no occurrence-clones for anchors")


def scenario_poi_coord_veto_via_agent():
    """The agent's approx coordinates veto a geocode in the wrong city, exactly
    like plan generation."""
    mk_draft("draft_trip_coords")
    rich = lambda name, location, trip_location: {
        "location": "Rue de Bourgogne, Paris", "mapbox_id": "mb1", "lat": 48.85, "lng": 2.35,
        "wikidata_id": "Q1", "opening_hours": "9-18", "website": "w", "phone_number": "p",
        "cuisine": None, "internet_access": None, "image_url": "i", "link": "l"}
    prev = trip_planner.enrich_poi_data
    trip_planner.enrich_poi_data = rich
    try:
        res = agent_tools.handle_add_trip_poi(dict(
            event_id="draft_trip_coords", name="Beaune Wine Cave", location="Beaune",
            duration_mins=90, approx_lat=47.02, approx_lng=4.84))
        check(res["status"] == "success", f"add failed: {res}")
    finally:
        trip_planner.enrich_poi_data = prev
    poi = storage.get_trip_metadata("draft_trip_coords")["pois"][0]
    check(abs(poi["lat"] - 47.02) < 0.01, f"agent approx coords veto the bad geocode: {poi['lat']}")
    check(poi.get("opening_hours") is None and poi.get("mapbox_id") is None,
          "wrong place's identity fields dropped")


def scenario_flight_add_by_trip_days():
    """Flights via trip-day ordinals on a draft: an overnight outbound departing
    the day BEFORE the trip (day 0), landing day 1; return departs the last day.
    Agent-facing messages must speak in trip days, never mock dates."""
    mk_draft("draft_trip_flights")
    res = agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flights", origin="JFK", destination="CDG",
        airline="Delta", flight_number="DL123",
        departure_day=0, departure_time="18:00", arrival_day=1, arrival_time="08:30"))
    check(res["status"] == "success", f"add outbound failed: {res}")
    check("2029" not in res["message"] and "2030" not in res["message"],
          f"draft flight message must not leak mock dates: {res['message']}")
    res = agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flights", origin="CDG", destination="JFK",
        airline="Delta", flight_number="DL124", departure_day=11, departure_time="16:00"))
    check(res["status"] == "success", f"add return failed: {res}")

    flights = {f["flight_number"]: f for f in storage.get_trip_metadata("draft_trip_flights")["flights"]}
    check(flights["DL123"]["departure_time"] == "2029-12-31T18:00:00",
          f"day 0 = day before mock start: {flights['DL123']['departure_time']}")
    check(flights["DL123"]["arrival_time"] == "2030-01-01T08:30:00",
          f"day 1 arrival: {flights['DL123']['arrival_time']}")
    check(flights["DL124"]["departure_time"] == "2030-01-11T16:00:00",
          f"day 11 return: {flights['DL124']['departure_time']}")
    check(flights["DL123"]["is_live_price"] is False, "agent-added flight is not a live price")

    # the stored dicts must round-trip through the pydantic model
    from models.schemas import TripMetadata
    TripMetadata(**storage.get_trip_metadata("draft_trip_flights"))


def scenario_flight_bad_times_rejected():
    mk_draft("draft_trip_flightbad")
    res = agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightbad", origin="JFK", destination="CDG",
        departure_day=1, departure_time="18:00", arrival_day=1, arrival_time="08:30"))
    check(res["status"] == "error" and "NEXT day" in res["message"],
          f"arrival before departure must be rejected with overnight guidance: {res}")
    check(not storage.get_trip_metadata("draft_trip_flightbad").get("flights"),
          "rejected flight must not be persisted")
    res = agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightbad", origin="JFK", destination="CDG",
        departure_day=1, departure_time="6pm"))
    check(res["status"] == "error", f"unparseable time must be rejected: {res}")


def scenario_flight_duplicate_rejected():
    mk_draft("draft_trip_flightdup")
    agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightdup", origin="JFK", destination="CDG",
        flight_number="DL123", departure_day=1, departure_time="08:00"))
    res = agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightdup", origin="JFK", destination="CDG",
        flight_number="DL 123", departure_day=1, departure_time="09:00"))
    check(res["status"] == "error" and "already exists" in res["message"],
          f"same flight number + day must be rejected: {res}")
    res = agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightdup", origin="JFK", destination="CDG",
        departure_day=1, departure_time="11:00"))
    check(res["status"] == "error", f"same route + day without number must be rejected: {res}")
    check(len(storage.get_trip_metadata("draft_trip_flightdup")["flights"]) == 1,
          "duplicates must not be persisted")


def scenario_flight_edit_and_delete():
    mk_draft("draft_trip_flightedit")
    agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightedit", origin="JFK", destination="CDG",
        airline="Delta", flight_number="DL123", departure_day=1, departure_time="08:00",
        estimated_price_usd=900.0))
    # time-only edit keeps the existing date; price edit clears any live-price flag
    meta = storage.get_trip_metadata("draft_trip_flightedit")
    meta["flights"][0]["is_live_price"] = True
    storage.set_trip_metadata("draft_trip_flightedit", meta)
    res = agent_tools.handle_edit_trip_flight(dict(
        event_id="draft_trip_flightedit", origin="JFK", destination="CDG",
        departure_time="10:15", estimated_price_usd=850.0))
    check(res["status"] == "success", f"edit failed: {res}")
    f = storage.get_trip_metadata("draft_trip_flightedit")["flights"][0]
    check(f["departure_time"] == "2030-01-01T10:15:00",
          f"time-only edit keeps the existing date: {f['departure_time']}")
    check(f["is_live_price"] is False, "hand-edited price is an estimate again")
    check(f["estimated_price_usd"] == 850.0, "price applied")

    # ambiguity is an error, never a guess
    agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightedit", origin="JFK", destination="CDG",
        flight_number="DL999", departure_day=3, departure_time="08:00"))
    res = agent_tools.handle_edit_trip_flight(dict(
        event_id="draft_trip_flightedit", origin="JFK", destination="CDG", airline="United"))
    check(res["status"] == "error" and "Multiple" in res["message"],
          f"ambiguous route match -> error: {res}")

    res = agent_tools.handle_delete_trip_flight(dict(
        event_id="draft_trip_flightedit", flight_number="DL999"))
    check(res["status"] == "success", f"delete failed: {res}")
    check(len(storage.get_trip_metadata("draft_trip_flightedit")["flights"]) == 1,
          "deleted flight removed, the other kept")


def scenario_generate_flights_tool():
    """A bare 'add flights' goes through generate_trip_flights: generated flights
    are persisted, re-suggestions of existing routes are dropped, and the agent
    message speaks in trip days (never mock dates)."""
    from models.schemas import TripFlight
    mk_draft("draft_trip_flightgen")
    agent_tools.handle_add_trip_flight(dict(
        event_id="draft_trip_flightgen", origin="JFK", destination="CDG",
        departure_day=0, departure_time="18:00"))

    prev = trip_planner.generate_trip_flights
    trip_planner.generate_trip_flights = lambda trip, prompt: (None, [
        TripFlight(airline="Delta", origin="JFK", destination="CDG",
                   departure_time="2029-12-31T19:00:00"),   # same route+day as existing: dropped
        TripFlight(airline="Delta", origin="CDG", destination="JFK",
                   departure_time="2030-01-11T11:00:00"),
    ])
    try:
        res = agent_tools.handle_generate_trip_flights(dict(event_id="draft_trip_flightgen"))
    finally:
        trip_planner.generate_trip_flights = prev
    check(res["status"] == "success", f"generate failed: {res}")
    check("2029" not in res["message"] and "2030" not in res["message"],
          f"draft message must not leak mock dates: {res['message']}")
    flights = storage.get_trip_metadata("draft_trip_flightgen")["flights"]
    check(len(flights) == 2, f"1 existing + 1 new (dupe route dropped), got {len(flights)}")
    check(any(f["origin"] == "CDG" for f in flights), "the return flight was added")


def scenario_v2_router_flight_tool():
    """The v2 chat router (/api/chat -> agent_router -> agent_tools_v2) shares
    the v1 flight implementation: generate delegates to the generator, add/edit/
    delete hit the validated handlers, and success requests a UI sync."""
    from models.schemas import TripFlight
    from services import agent_tools_v2
    mk_draft("draft_trip_v2flights")

    prev = trip_planner.generate_trip_flights
    trip_planner.generate_trip_flights = lambda trip, prompt: (None, [
        TripFlight(airline="Delta", origin="JFK", destination="CDG",
                   departure_time="2029-12-31T18:00:00"),
    ])
    try:
        res = agent_tools_v2.manage_trip_flights("draft_trip_v2flights", "generate",
                                                 prompt="add flights to my trip")
    finally:
        trip_planner.generate_trip_flights = prev
    check(res["status"] == "success", f"v2 generate failed: {res}")
    check(res.get("ui_action") == "sync", "success triggers a UI data sync")
    check(len(storage.get_trip_metadata("draft_trip_v2flights")["flights"]) == 1,
          "generated flight persisted through the v2 path")

    res = agent_tools_v2.manage_trip_flights("draft_trip_v2flights", "add", flight={
        "origin": "CDG", "destination": "JFK", "departure_day": 11, "departure_time": "16:00"})
    check(res["status"] == "success", f"v2 add failed: {res}")
    res = agent_tools_v2.manage_trip_flights("draft_trip_v2flights", "delete",
                                             flight={"origin": "CDG", "destination": "JFK"})
    check(res["status"] == "success", f"v2 delete failed: {res}")
    check(len(storage.get_trip_metadata("draft_trip_v2flights")["flights"]) == 1,
          "v2 delete removed the flight")
    res = agent_tools_v2.manage_trip_flights("draft_trip_v2flights", "teleport")
    check(res["status"] == "error", "unknown action -> error")


def scenario_tool_registered():
    check("edit_trip_accommodation" in agent_tools.TOOL_SCHEMAS, "schema registered")
    for t in ("generate_trip_flights", "add_trip_flight", "edit_trip_flight", "delete_trip_flight"):
        check(t in agent_tools.TOOL_SCHEMAS, f"{t} schema registered")
        check(t in agent_tools.TOOL_HANDLERS, f"{t} handler registered")
    props = agent_tools.TOOL_SCHEMAS["add_trip_flight"].get("properties", {})
    check("departure_day" in props and "arrival_day" in props,
          "flight add tool exposes trip-day ordinals to the LLM")
    check("edit_trip_accommodation" in agent_tools.TOOL_HANDLERS
          if hasattr(agent_tools, "TOOL_HANDLERS") else True, "handler registered")
    schema = agent_tools.TOOL_SCHEMAS["add_trip_accommodation"]
    props = schema.get("properties", {})
    check("check_in_night" in props and "nights" in props,
          "add tool exposes trip-night ordinals to the LLM")


SCENARIOS = [
    scenario_multi_leg_by_trip_nights,
    scenario_default_full_span,
    scenario_explicit_dates_win,
    scenario_ordinal_clamped_to_trip_end,
    scenario_edit_accommodation,
    scenario_overlapping_add_rejected,
    scenario_edit_clips_neighbors,
    scenario_poi_gate_demotes_and_keeps_anchors,
    scenario_poi_coord_veto_via_agent,
    scenario_flight_add_by_trip_days,
    scenario_flight_bad_times_rejected,
    scenario_flight_duplicate_rejected,
    scenario_flight_edit_and_delete,
    scenario_generate_flights_tool,
    scenario_v2_router_flight_tool,
    scenario_tool_registered,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
