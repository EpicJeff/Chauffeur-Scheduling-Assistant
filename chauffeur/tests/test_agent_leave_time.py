"""Argyle answers "what time do I need to leave" with the household's own
departure, read from services/leave_by (the one place a departure is worked
out), never with arithmetic of its own; and it can look a drive up for a
question nobody pre-computed, saying "unknown" instead of passing on a guess.

Background (2026-10-13): a parent asked and got the start time read back plus
"leave in time to get there" — no agent tool read leave_by and no travel-time
primitive existed, so the model had nothing to compose. Codex's adversarial
review of the design added: the PWA's injected drive list must carry the
departure (the model is told that list is authoritative), the satellite only
reaches get_calendar_events, the digest's six-line cap must not hide a drive,
and maps.get_travel_time_minutes silently returns 15 when routing fails, so the
primitive needs a strict lookup with a real "unknown".

Run from chauffeur/:  python tests/test_agent_leave_time.py
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import maps, storage, family_digest, voice_tools
from services import agent_tools_v2 as tools
from services import voice_identity as voice

TODAY = datetime.date.today()


def seed(edges=True, mom_second=False, more=0):
    """Mom drives Soccer at 9:00 from home: 20 min drive, 5 min arrive-early
    buffer, the household's 5 min margin -> leave by 8:30 AM. Dad's Karate at
    10:00 has no travel edge, so no departure may be claimed for it. Piano is
    a ghost suggestion. `mom_second` adds an edge-less 1 PM drive for mom;
    `more` adds that many extra afternoon drives for mom (digest cap tests)."""
    storage.drivers_table.truncate()
    storage.drive_status_table.truncate()
    storage.add_driver({"id": "mom", "name": "Mom", "color_code": "#fff"})
    storage.add_driver({"id": "dad", "name": "Dad", "color_code": "#000"})
    day = TODAY.isoformat()
    events = [
        {"id": "mom_ev0", "title": "Soccer Practice", "location": "Soccer Field",
         "start": f"{day}T09:00:00", "end": f"{day}T10:00:00"},
        {"id": "dad_ev0", "title": "Karate", "location": "Dojo",
         "start": f"{day}T10:00:00", "end": f"{day}T11:00:00"},
        {"id": "open_ev", "title": "Piano", "location": "Studio",
         "start": f"{day}T15:00:00", "end": f"{day}T16:00:00"},
    ]
    assignments = {"mom_ev0": "mom", "dad_ev0": "dad"}
    initial = {"mom_ev0": {"travel_mins": 20, "buffer_before_mins": 5, "driver_home_location": "Home St"}}
    if mom_second:
        events.append({"id": "mom_ev1", "title": "Dentist", "location": "Clinic",
                       "start": f"{day}T13:00:00", "end": f"{day}T14:00:00"})
        assignments["mom_ev1"] = "mom"
    for i in range(more):
        ev_id = f"mom_more{i}"
        events.append({"id": ev_id, "title": f"Errand {i}", "location": f"Shop {i}",
                       "start": f"{day}T{16 + (i % 3)}:{10 * i % 60:02d}:00", "end": f"{day}T{17 + (i % 3)}:00:00"})
        assignments[ev_id] = "mom"
    sched = {"events": events, "assignments": assignments,
             "ghost_assignments": {"open_ev": "ghost_1"}, "scheduled_errands": []}
    if edges:
        sched["initial_edges"] = {"mom": initial}
    storage.set_cached_schedule(sched)


def _ctx():
    return voice.VoiceContext('ha', 'assist_satellite.kitchen', '', '', service_revision=voice._revision(), paired=True)


# --- the schedule tools carry the departure --------------------------------

def scenario_get_my_route_states_the_departure():
    seed()
    ev = tools.get_my_route("mom")["events"][0]
    check(ev.get("leave_label") == "8:30 AM", f"mom's drive says leave by 8:30 AM, got {ev}")
    check(ev.get("leave_at", "").endswith("T08:30:00"), f"leave_at is the ISO departure, got {ev.get('leave_at')}")
    check(ev.get("travel_mins") == 20 and ev.get("from_home") is True, f"travel and origin stamped, got {ev}")
    check(ev["start"].endswith("T09:00:00"), "the start is still when the thing starts")


def scenario_no_travel_means_no_leave_time():
    seed()
    ev = tools.get_my_route("dad")["events"][0]
    check("leave_label" not in ev and "leave_at" not in ev and "travel_mins" not in ev,
          f"no travel edge -> no departure fields at all (a guess is worse than none), got {ev}")
    seed(edges=False)
    ev = tools.get_my_route("mom")["events"][0]
    check("leave_label" not in ev, f"an edge-less schedule claims nothing, got {ev}")


def scenario_get_calendar_events_states_the_departure_for_assigned_events():
    """The satellite and admin/family chat reach only get_calendar_events for
    a schedule read, so this is the path that matters most."""
    seed()
    day = TODAY.isoformat()
    for spoken in (False, True):
        res = tools.get_calendar_events(day, day, spoken=spoken)
        by_id = {e["id"]: e for e in res["events"]}
        check(by_id["mom_ev0"].get("leave_label") == "8:30 AM" and by_id["mom_ev0"].get("assigned_driver") == "Mom",
              f"spoken={spoken}: the calendar read carries the departure, got {by_id['mom_ev0']}")
        check(by_id["mom_ev0"].get("travel_mins") == 20, "travel minutes ride along")
        check("leave_label" not in by_id["dad_ev0"], "no edge, no departure")
        check("leave_label" not in by_id["open_ev"], f"a ghost suggestion never gets a departure, got {by_id['open_ev']}")


def scenario_drive_digest_line_says_leave_by_and_rows_are_uncapped():
    seed(more=7)   # mom: 8 drives; the digest shows six lines and must not hide the rest
    digest = family_digest.build_drive_digests(TODAY)
    mom = digest["drivers"]["mom"]
    soccer = next(l for l in mom["lines"] if "Soccer Practice" in l)
    check(soccer.startswith("9:00 AM - Soccer Practice") and "[leave by 8:30 AM]" in soccer,
          f"the start leads the line and the departure follows, got {soccer}")
    check(any(l.startswith("...and") for l in mom["lines"]), f"the six-line cap still applies to notification lines, got {mom['lines']}")
    rows = mom.get("events") or []
    check(len(rows) == 8 and {"id", "title", "start"} <= set(rows[0]), f"structured rows carry every drive, got {len(rows)}: {rows[:1]}")
    soccer_row = next(r for r in rows if r["id"] == "mom_ev0")
    check(soccer_row.get("leave_label") == "8:30 AM" and soccer_row.get("leave_at", "").endswith("T08:30:00"),
          f"rows carry the departure fields, got {soccer_row}")
    dad = digest["drivers"]["dad"]
    check(not any("leave by" in l for l in dad["lines"]) and "leave_label" not in dad["events"][0],
          f"no edge, no departure anywhere, got {dad}")
    res = tools.get_drive_digest("today", member_name="Mom")
    check("[leave by 8:30 AM]" in res["message"], f"the agent's digest tool says it too, got {res['message']}")
    check(len(res.get("events") or []) == 8 and res["events"][0].get("driver_id") == "mom",
          f"the tool returns every drive as a row with its driver, got {res.get('events')}")
    res_all = tools.get_drive_digest("today")
    check(len(res_all.get("events") or []) == 9, f"the all-drivers read returns every driver's rows, got {len(res_all.get('events') or [])}")


def scenario_another_day_never_asks_for_the_live_overlay():
    seed()
    day = (TODAY + datetime.timedelta(days=1)).isoformat()
    storage.set_cached_schedule({
        "events": [{"id": "mom_ev1", "title": "Swim", "location": "Pool", "start": f"{day}T09:00:00", "end": f"{day}T10:00:00"}],
        "assignments": {"mom_ev1": "mom"}, "ghost_assignments": {}, "scheduled_errands": [],
        "initial_edges": {"mom": {"mom_ev1": {"travel_mins": 20, "buffer_before_mins": 5}}}})
    calls = []
    from services import leave_by
    orig = leave_by.for_run

    def spy(sched, driver_id, event_id, start, **kw):
        calls.append(bool(kw.get("live")))
        return orig(sched, driver_id, event_id, start, **kw)
    leave_by.for_run = spy
    try:
        res = tools.get_my_route("mom", "tomorrow")
        digest = family_digest.build_drive_digests(TODAY + datetime.timedelta(days=1))
    finally:
        leave_by.for_run = orig
    check(res["events"][0].get("leave_label") == "8:30 AM", f"tomorrow's departure is stated (static), got {res}")
    check(digest["drivers"]["mom"]["events"][0].get("leave_label") == "8:30 AM", "the evening digest states it too")
    check(calls and not any(calls), f"another day never asks for the live overlay, got live={calls}")


# --- the router: the driver's prompt and the one rule ------------------------

def _capture(text, **kw):
    from services import agent_router
    captured = {}

    def fake_gemma(prompt, tools_, system_prompt):
        captured["system"] = system_prompt
        captured["tools"] = [t["name"] for t in tools_]
        return {"message": "ok", "tool_calls": []}
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake_gemma
    try:
        agent_router.process_agent_request(text, **kw)
    finally:
        agent_router.call_gemma_with_fallback = orig
    return captured


def scenario_router_prompt_carries_the_departure_and_the_rule():
    seed(mom_second=True)
    captured = _capture("what time do I need to leave?", source="pwa", driver_id="mom")
    system = captured["system"]
    block = system[system.find("YOUR DRIVES TODAY"):][:400]
    check("Soccer Practice" in block and "leave by 8:30 AM" in block, f"YOUR DRIVES TODAY carries the departure, got: {block}")
    check("Dentist" in block and "leave time unknown" in block, f"a drive with no departure says so explicitly, got: {block}")
    check("leave_label" in system and "never work out a departure yourself" in system,
          "the rule is in the prompt: answer with leave_label, never compute one")
    check("drive time is unknown" in system, "the prompt says what to say when no departure is known")
    check("get_travel_time" in captured["tools"], f"the travel primitive is offered, got {captured['tools']}")

    captured = _capture("when should we leave for karate?", source="admin")
    check("never work out a departure yourself" in captured["system"], "the rule holds in admin/family chat too")
    check("get_travel_time" in captured["tools"], "the primitive is offered outside driver chat too")


# --- the travel primitive, for questions nobody pre-computed -------------------

def _no_prime(*a, **kw):
    return None


def scenario_lookup_is_strict():
    """maps.lookup_travel_minutes: a number only when the matrix cache holds
    one; never the 15-minute fallback, never 900 for an unroutable pair."""
    storage.set_cached_travel_time("pool", "grandma's house", 10)
    check(maps.lookup_travel_minutes("Pool", "Grandma's House") == 10, "a cached pair is read, case-insensitively")
    storage.set_cached_travel_time("pool", "nowhere", storage.UNROUTABLE)
    check(maps.lookup_travel_minutes("Pool", "Nowhere") is None, "an unroutable pair is unknown, not 900")
    orig = maps.prime_matrix_cache
    maps.prime_matrix_cache = _no_prime
    try:
        check(maps.lookup_travel_minutes("Pool", "Dojo") is None, "a miss that priming cannot fill is unknown, not 15")
        primed = []
        maps.prime_matrix_cache = lambda locs, **kw: primed.append(locs)
        with maps.travel_cache_only():
            check(maps.lookup_travel_minutes("Pool", "Dojo") is None and not primed,
                  f"cache-only mode never fetches, got primed={primed}")
    finally:
        maps.prime_matrix_cache = orig
    check(maps.lookup_travel_minutes("Pool", "Pool") == 0 and maps.lookup_travel_minutes("", "Pool") is None,
          "same place is zero; a missing end is unknown")


def scenario_get_travel_time_looks_up_a_drive():
    storage.set_cached_travel_time("pool", "grandma's house", 10)
    res = tools.get_travel_time(origin="Pool", destination="Grandma's House")
    check(res["status"] == "success" and res["travel_mins"] == 10, f"the cached drive is reported, got {res}")
    check("10 min" in res["message"] and "Pool" in res["message"] and "Grandma's House" in res["message"],
          f"spoken answer names both ends and the minutes, got {res['message']}")
    check("traffic" in res["message"].lower(), f"the answer says it is a typical drive, not live traffic, got {res['message']}")


def scenario_get_travel_time_defaults_to_home():
    storage.set_cached_travel_time("12 home st", "dojo", 10)
    orig = maps.get_home_location
    maps.get_home_location = lambda: "12 Home St"
    try:
        res = tools.get_travel_time(destination="Dojo")
    finally:
        maps.get_home_location = orig
    check(res["status"] == "success" and res["origin"] == "12 Home St" and "from home" in res["message"].lower(),
          f"no origin means from home, got {res}")
    maps.get_home_location = lambda: None
    try:
        res = tools.get_travel_time(destination="Dojo")
    finally:
        maps.get_home_location = orig
    check(res["status"] == "error" and "home" in res["message"].lower(), f"no home set -> an honest error, got {res}")


def scenario_get_travel_time_is_honest_when_it_cannot_look_up():
    orig = maps.prime_matrix_cache
    maps.prime_matrix_cache = _no_prime
    try:
        res = tools.get_travel_time(origin="Pool", destination="Dojo")
    finally:
        maps.prime_matrix_cache = orig
    check(res["status"] == "error" and "travel_mins" not in res, f"an unavailable lookup carries no number, got {res}")
    check("look" in res["message"].lower() and "Dojo" in res["message"], f"says it could not look that drive up, got {res['message']}")
    res = tools.get_travel_time(origin="Pool", destination="")
    check(res["status"] == "error", f"a missing destination is an error, got {res}")


def scenario_chat_lookups_are_budgeted():
    """A chatty model must not spend the scheduler's Mapbox allowance: at most
    CHAT_LOOKUPS_PER_HOUR live primes an hour from chat; beyond that the
    tool is cache-only (an uncached pair is unknown, a cached one still answers)."""
    tools._chat_lookups.clear()
    primed = []
    orig = maps.prime_matrix_cache
    maps.prime_matrix_cache = lambda locs, **kw: primed.append(locs)
    try:
        for i in range(tools.CHAT_LOOKUPS_PER_HOUR + 5):
            tools.get_travel_time(origin=f"Place {i}", destination="Dojo")
        check(len(primed) == tools.CHAT_LOOKUPS_PER_HOUR, f"live primes stop at the budget, got {len(primed)}")
        storage.set_cached_travel_time("pool", "dojo", 12)
        res = tools.get_travel_time(origin="Pool", destination="Dojo")
        check(res["status"] == "success" and res["travel_mins"] == 12 and len(primed) == tools.CHAT_LOOKUPS_PER_HOUR,
              f"a cached pair still answers over budget without a fetch, got {res}")
    finally:
        maps.prime_matrix_cache = orig
        tools._chat_lookups.clear()


def scenario_get_travel_time_is_registered_everywhere_it_is_needed():
    check("get_travel_time" in tools.TOOL_SCHEMAS and "get_travel_time" in tools.TOOL_HANDLERS, "registered once, in both maps")
    check("get_travel_time" not in tools.SCHEDULE_MUTATING_ADMIN_TOOLS, "a lookup never counts as a schedule mutation")
    schema = tools.TOOL_SCHEMAS["get_travel_time"]
    props = schema.get("properties", {})
    check({"origin", "destination"} <= set(props) and "depart_at" not in props,
          f"schema names origin and destination and promises no departure-time routing, got {list(props)}")
    check("leave_label" in (schema.get("description") or ""), "the description points scheduled drives at leave_label")
    storage.set_cached_travel_time("pool", "dojo", 10)
    out = tools.TOOL_HANDLERS["get_travel_time"]({"destination": "Dojo", "origin": "Pool"})
    check(out.get("travel_mins") == 10, f"the handler dispatches the lookup, got {out}")
    check("get_travel_time" in voice_tools.TOOLS and "get_travel_time" not in voice_tools.MUTATIONS, "the satellite may ask too")
    out = voice_tools.dispatch("get_travel_time", {"origin": "Pool", "destination": "Dojo"}, _ctx())
    check(out.get("travel_mins") == 10, f"the voice rail dispatches it, got {out}")


SCENARIOS = [
    scenario_get_my_route_states_the_departure,
    scenario_no_travel_means_no_leave_time,
    scenario_get_calendar_events_states_the_departure_for_assigned_events,
    scenario_drive_digest_line_says_leave_by_and_rows_are_uncapped,
    scenario_another_day_never_asks_for_the_live_overlay,
    scenario_router_prompt_carries_the_departure_and_the_rule,
    scenario_lookup_is_strict,
    scenario_get_travel_time_looks_up_a_drive,
    scenario_get_travel_time_defaults_to_home,
    scenario_get_travel_time_is_honest_when_it_cannot_look_up,
    scenario_chat_lookups_are_budgeted,
    scenario_get_travel_time_is_registered_everywhere_it_is_needed,
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
