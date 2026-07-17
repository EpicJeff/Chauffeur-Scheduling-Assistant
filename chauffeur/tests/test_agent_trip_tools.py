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


def scenario_tool_registered():
    check("edit_trip_accommodation" in agent_tools.TOOL_SCHEMAS, "schema registered")
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
