"""Tests for the PWA driver chat tools (services/agent_tools_v2.py).

get_my_route / start_route / complete_route act on the logged-in driver's
assigned events from the combined schedule cache, mirroring what the PWA's
Start Drive and Mark Completed buttons write (drive_status + telemetry).

Run from chauffeur/:  python tests/test_agent_driver_tools.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services.agent_tools_v2 import complete_route, get_my_route, start_route


def seed(events_by_driver):
    """Reset drivers + combined schedule cache. events_by_driver: {driver_id: [(title, hour)]}"""
    storage.drivers_table.truncate()
    storage.drive_status_table.truncate()
    storage.clear_telemetry_events()
    events, assignments = [], {}
    today = datetime.date.today()
    for d_id, evs in events_by_driver.items():
        # add_driver truncates the schedule cache, so seed drivers first
        storage.add_driver({"id": d_id, "name": d_id.capitalize(), "color_code": "#fff"})
        for i, (title, hour) in enumerate(evs):
            ev_id = f"{d_id}_ev{i}"
            start = datetime.datetime.combine(today, datetime.time(hour, 0))
            events.append({"id": ev_id, "title": title, "location": f"{title} Field",
                           "start": start.isoformat(), "end": (start + datetime.timedelta(hours=1)).isoformat()})
            assignments[ev_id] = d_id
    storage.set_cached_schedule({"events": events, "assignments": assignments, "ghost_assignments": {}})


def scenario_get_my_route_filters_by_driver():
    seed({"mom": [("Soccer Practice", 9), ("Piano Lesson", 14)], "dad": [("Karate", 10)]})
    res = get_my_route("mom")
    check(res["status"] == "success" and len(res["events"]) == 2,
          f"mom sees exactly her two drives, got {res}")
    titles = [e["title"] for e in res["events"]]
    check(titles == ["Soccer Practice", "Piano Lesson"], f"sorted by start time, got {titles}")
    check(all(e["drive_status"] == "pending" for e in res["events"]), "fresh drives are pending")

    res_dad = get_my_route("dad")
    check(len(res_dad["events"]) == 1 and res_dad["events"][0]["title"] == "Karate",
          f"dad sees only his drive, got {res_dad}")


def scenario_start_route_marks_in_progress():
    seed({"mom": [("Soccer Practice", 9)]})
    res = start_route("mom", "soccer")
    check(res["status"] == "success" and res["event_id"] == "mom_ev0",
          f"fuzzy 'soccer' resolves mom's drive, got {res}")
    in_prog = storage.get_in_progress_drives()
    check("route_mom_ev0_1" in in_prog and "init_mom_ev0" in in_prog,
          f"leg-id family marked in progress, got {in_prog}")
    check(get_my_route("mom")["events"][0]["drive_status"] == "driving now",
          "status reads back as driving now")


def scenario_complete_route_telemetry_and_legs():
    seed({"mom": [("Soccer Practice", 9)]})
    res = complete_route("mom", "soccer practice", action="dropped off")
    check(res["status"] == "success", f"complete succeeds, got {res}")
    tel = storage.get_telemetry_events()
    check(len(tel) == 1 and tel[0]["action"] == "dropped off" and tel[0]["driver_id"] == "mom"
          and tel[0]["event_id"] == "mom_ev0", f"telemetry recorded, got {tel}")
    check("route_mom_ev0_2" in storage.get_completed_drives(), "legs marked completed")
    check(get_my_route("mom")["events"][0]["drive_status"] == "completed",
          "status reads back as completed")

    # bogus action falls back to 'completed' instead of failing mid-drive
    res2 = complete_route("mom", "soccer", action="finished up")
    check("completed" in res2["message"], f"unknown action falls back to completed, got {res2}")


def scenario_no_match_errors():
    seed({"mom": [("Soccer Practice", 9)]})
    res = start_route("dad", "soccer")
    check(res["status"] == "error" and "no assigned drives" in res["message"],
          f"driver with no drives gets a clear error, got {res}")
    res2 = complete_route("mom", "zzz quantum banquet")
    check(res2["status"] == "error" or res2.get("event_id") == "mom_ev0",
          f"nonsense name errors or falls back to only event, got {res2}")


def scenario_router_injects_driver_context():
    # No LLM call: stub the Gemma caller and verify the driver prompt + tools wiring.
    seed({"mom": [("Soccer Practice", 9)]})
    from services import agent_router
    captured = {}

    def fake_gemma(prompt, tools, system_prompt):
        captured["system"] = system_prompt
        captured["tools"] = [t["name"] for t in tools]
        return {"message": "ok", "tool_calls": []}

    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake_gemma
    try:
        agent_router.process_agent_request("what's my day?", source="pwa", driver_id="mom")
    finally:
        agent_router.call_gemma_with_fallback = orig

    check("DRIVER MODE" in captured["system"] and "Mom" in captured["system"],
          "driver prompt names the driver")
    check("Soccer Practice" in captured["system"], "today's drives injected into prompt")
    check({"get_my_route", "start_route", "complete_route"} <= set(captured["tools"]),
          f"driver tools exposed, got {captured['tools']}")

    # admin chat must NOT get driver tools
    agent_router.call_gemma_with_fallback = fake_gemma
    try:
        agent_router.process_agent_request("hello", source="admin")
    finally:
        agent_router.call_gemma_with_fallback = orig
    check("start_route" not in captured["tools"], "admin chat has no driver tools")


def scenario_misheard_names_still_find_the_person():
    """Speech-to-text has never met this family. It renders Celma as "Selma"
    and Vovo as "Volvo", and the old matcher was substring-only — "selma" is
    not inside "celma", so a voice command simply failed. Both tiers of the fix
    are guarded here: the sound-folding that catches a swapped letter, and the
    scored tier that catches a whole inserted one."""
    from services.agent_tools_v2 import _match_person

    roster = [{"name": n} for n in
              ("Celma", "Vovo", "Jeff", "Grandpa", "Grandma", "Lily")]

    for heard, expected in (("Selma", "Celma"), ("Volvo", "Vovo"),
                            ("Lilly", "Lily"), ("Celma", "Celma")):
        got, _ = _match_person(heard, roster)
        check(got and got["name"] == expected,
              f"{heard!r} should resolve to {expected}, got {got}")

    # The pair that must NOT be guessed at. They are 0.857 similar, so a bare
    # threshold hands over the wrong grandparent; only the margin check saves it.
    for exact in ("Grandpa", "Grandma"):
        got, _ = _match_person(exact, roster)
        check(got and got["name"] == exact, f"{exact} resolves to itself, got {got}")
    got, known = _match_person("granma or granpa", roster)
    check(got is None and "Grandpa" in known and "Grandma" in known,
          f"an ambiguous grandparent is refused and the roster named, got {got}")

    # A miss reports who DOES exist — without that the model just retries the
    # same misheard name.
    got, known = _match_person("Beyonce", roster)
    check(got is None and set(known) == {p["name"] for p in roster},
          f"unknown name lists the roster, got {known}")


def scenario_router_injects_the_family_roster():
    """The real fix for a misheard name is upstream of any matcher: give the
    model the list of people who exist and it corrects the name itself, for
    every tool that takes one. The prompt carried no roster at all."""
    seed({"mom": [("Soccer Practice", 9)]})
    storage.add_driver({"id": "celma", "name": "Celma", "color_code": "#fff"})
    from services import agent_router
    captured = {}

    def fake_gemma(prompt, tools, system_prompt):
        captured["system"] = system_prompt
        return {"message": "ok", "tool_calls": []}

    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake_gemma
    try:
        agent_router.process_agent_request("have Selma drive tonight", source="admin")
    finally:
        agent_router.call_gemma_with_fallback = orig

    check("Celma" in captured["system"],
          "the roster names every driver so the model can correct a mishearing")
    check("speech-to-text" in captured["system"].lower(),
          "and says WHY an unfamiliar name is probably one of them misheard")


SCENARIOS = [
    scenario_get_my_route_filters_by_driver,
    scenario_start_route_marks_in_progress,
    scenario_complete_route_telemetry_and_legs,
    scenario_no_match_errors,
    scenario_router_injects_driver_context,
    scenario_misheard_names_still_find_the_person,
    scenario_router_injects_the_family_roster,
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
