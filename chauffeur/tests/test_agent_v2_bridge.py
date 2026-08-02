"""Tests for the v1->v2 tool bridge (services/agent_tools_v2.py +
services/agent_router.py).

The v2 chat/voice pipeline (agent_router + agent_tools_v2) natively covers
messaging, chores, trips and driver overrides, but the scheduling-core
(routing/priority rules, solver), errands, memory, places and deep
trip-planning tools live only in the v1 handler table. The bridge surfaces
those v1 schemas to the v2 model and delegates execution to the tested v1
handlers -- admin context only, never for PWA drivers.

Run from chauffeur/:  python tests/test_agent_v2_bridge.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, agent_tools, agent_tools_v2, storage


def _seed_driver(d_id="mom"):
    storage.drivers_table.truncate()
    storage.add_driver({"id": d_id, "name": d_id.capitalize(), "color_code": "#fff"})


def _fake_gemma_once(tool_call, captured=None):
    """Returns `tool_call` on the first router round, then an empty round so the
    loop concludes. Optionally records the tool names offered to the model."""
    state = {"n": 0}

    def fake(prompt, tools, system_prompt):
        if captured is not None:
            captured["tools"] = [t["name"] for t in tools]
            captured["system"] = system_prompt
        state["n"] += 1
        if state["n"] == 1 and tool_call is not None:
            return {"message": "ok", "tool_calls": [tool_call]}
        return {"message": "done", "tool_calls": []}

    return fake


def scenario_bridge_schemas_and_handlers():
    """Every bridged name resolves to a real schema AND a real v1 handler, the
    schedule-mutating subset is a subset of the bridge, and no bridged name
    collides with a native v2 tool (which would double-offer it to the model)."""
    bridged = agent_tools_v2.get_bridged_v1_tools()
    names = [t["name"] for t in bridged]
    check(len(names) == len(agent_tools_v2.BRIDGED_V1_TOOLS),
          f"all bridge tools resolved a schema, got {len(names)}")
    check(all(t["parameters"].get("type") for t in bridged),
          "every bridged schema carries a parameters.type")
    handlers = set(agent_tools.TOOL_HANDLERS)
    missing = [n for n in agent_tools_v2.BRIDGED_V1_TOOLS if n not in handlers]
    check(not missing, f"every bridged tool has a v1 handler, missing {missing}")
    check(agent_tools_v2.SCHEDULE_MUTATING_V1_TOOLS <= set(agent_tools_v2.BRIDGED_V1_TOOLS),
          "schedule-mutating set is a subset of the bridge list")
    native = {t["name"] for t in agent_tools_v2.get_available_tools()}
    check(not (native & set(names)), f"no native/bridged name collision, got {native & set(names)}")


def scenario_bridge_admin_exposes_driver_hides():
    """Admin/family-hub chat is offered the bridge tools; PWA driver chat is not
    -- a driver on the go must never reconfigure global scheduling."""
    _seed_driver("mom")
    captured = {}
    orig = agent_router.call_gemma_with_fallback

    agent_router.call_gemma_with_fallback = _fake_gemma_once(None, captured)
    try:
        agent_router.process_agent_request("hello", source="admin")
    finally:
        agent_router.call_gemma_with_fallback = orig
    check("add_routing_rule" in captured["tools"] and "add_errand" in captured["tools"],
          f"admin chat is offered the bridge tools, got {captured['tools']}")

    agent_router.call_gemma_with_fallback = _fake_gemma_once(None, captured)
    try:
        agent_router.process_agent_request("what's my day?", source="pwa", driver_id="mom")
    finally:
        agent_router.call_gemma_with_fallback = orig
    check("add_routing_rule" not in captured["tools"] and "run_solver" not in captured["tools"],
          f"PWA driver chat has no bridge tools, got {captured['tools']}")


def scenario_bridge_admin_dispatch_delegates():
    """An admin bridged tool call routes to the v1 handler (a rule is stored) and
    flags schedule_dirty so the client re-solves."""
    storage.rules_table.truncate()
    before = len(storage.get_all_rules())
    call = {"name": "add_routing_rule",
            "arguments": {"constraint_type": "unavailable", "driver_id": "dad"}}
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = _fake_gemma_once(call)
    try:
        res = agent_router.process_agent_request("dad can't drive", source="admin")
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(len(storage.get_all_rules()) == before + 1,
          f"routing rule persisted through the v2 bridge, got {storage.get_all_rules()}")
    check(res.get("schedule_dirty") is True,
          f"schedule-mutating bridge tool flags schedule_dirty, got {res}")


def scenario_bridge_driver_dispatch_blocked():
    """Even if the model hallucinates a bridged tool name in PWA driver mode, the
    `not driver` dispatch guard refuses to execute it -- no rule is written."""
    _seed_driver("mom")
    storage.rules_table.truncate()
    before = len(storage.get_all_rules())
    call = {"name": "add_routing_rule",
            "arguments": {"constraint_type": "unavailable", "driver_id": "dad"}}
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = _fake_gemma_once(call)
    try:
        agent_router.process_agent_request("block scheduling", source="pwa", driver_id="mom")
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(len(storage.get_all_rules()) == before,
          f"driver-mode bridge dispatch is blocked, rules changed to {storage.get_all_rules()}")


SCENARIOS = [
    scenario_bridge_schemas_and_handlers,
    scenario_bridge_admin_exposes_driver_hides,
    scenario_bridge_admin_dispatch_delegates,
    scenario_bridge_driver_dispatch_blocked,
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
