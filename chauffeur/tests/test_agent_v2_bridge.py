"""Tests for the admin toolset and the one tool registry
(services/agent_tools_v2.py + services/agent_router.py).

The router natively covers messaging, chores, trips and driver overrides;
the scheduling-core (routing/priority rules, solver), errands, memory, places
and deep trip-planning tools reach the model through ADMIN_TOOLS, whose
schemas and handlers live in the registry at the bottom of agent_tools_v2
(moved there from the retired services/agent_tools.py on 2026-10-09) --
admin context only, never for PWA drivers.

Run from chauffeur/:  python tests/test_agent_v2_bridge.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, agent_tools_v2, storage

# Every name the retired v1 registry held on the day it was folded into
# agent_tools_v2. The registry may grow; it may never lose one of these.
V1_NAMES = frozenset((
    'add_dishes', 'add_errand', 'add_errand_rule', 'add_kid_task',
    'add_meal_ingredients_to_list', 'add_meal_to_repertoire', 'add_occasion', 'add_occasion_guests',
    'add_override', 'add_priority_rule', 'add_routing_rule', 'add_shopping_items',
    'add_trip_accommodation', 'add_trip_flight', 'add_trip_poi', 'adjust_points',
    'approve_week_dinners', 'award_pet_xp', 'cancel_event', 'challenge_pet_battle',
    'change_tonights_plate', 'check_off_shopping_item', 'claim_chore', 'clear_dish_prep',
    'clear_leftovers', 'complete_kid_task', 'contribute_to_family_goal', 'create_thread',
    'decide_optional_event', 'delete_errand', 'delete_errand_rule', 'delete_override',
    'delete_priority_rule', 'delete_routing_rule', 'delete_trip_flight', 'dismiss_insight',
    'edit_trip_accommodation', 'edit_trip_flight', 'edit_trip_poi', 'generate_trip_flights',
    'generate_trip_plan', 'get_current_state', 'get_drive_digest', 'get_eating_plan',
    'get_errands', 'get_family_goals', 'get_family_messages', 'get_household_status',
    'get_kid_tasks', 'get_meal_rules', 'get_occasion', 'get_occasion_gaps',
    'get_occasion_insights', 'get_pet_status', 'get_point_balances', 'get_prep_ahead',
    'get_routine_status', 'get_run_sheet', 'get_shopping_list_items', 'get_shopping_trip',
    'get_tonights_plate', 'get_week_dinners', 'group_events_ride_together', 'launch_mission',
    'list_chores', 'list_insights', 'list_open_findings', 'list_programs',
    'manage_car', 'mark_leftovers', 'mark_meal_served', 'negotiate_day',
    'pair_dishes', 'plan_specific_dinner', 'post_weekly_digest', 'refine_meal_dish',
    'remove_shopping_item_by_name', 'reopen_chore', 'restore_event', 'run_solver',
    'schedule_shopping_trip', 'search_places', 'send_direct_message', 'send_family_message',
    'set_dish_categories', 'set_dish_prep', 'set_dish_scope', 'set_event_optional',
    'set_hosting', 'set_household_status', 'set_meal_rule', 'set_occasion_attendance',
    'source_for_occasion', 'start_drive', 'suggest_dinner', 'suggest_gift_ideas',
    'ungroup_event', 'unlock_dinner', 'unpair_dishes', 'update_drive_status',
    'update_errand', 'update_memory',
))


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


def scenario_registry_keeps_every_v1_name():
    """Nothing was lost in the move: every v1 tool still has a schema and a
    handler under the same name, and the two tables agree with each other."""
    missing = sorted(V1_NAMES - set(agent_tools_v2.TOOL_HANDLERS))
    check(not missing, f"every v1 handler survives, missing {missing}")
    missing = sorted(V1_NAMES - set(agent_tools_v2.TOOL_SCHEMAS))
    check(not missing, f"every v1 schema survives, missing {missing}")
    check(set(agent_tools_v2.TOOL_HANDLERS) == set(agent_tools_v2.TOOL_SCHEMAS),
          "schemas and handlers name the same tools")
    check(not hasattr(__import__('services.llm', fromlist=['x']), 'agentic_chat_loop'),
          "the orphaned agentic_chat_loop is gone")


def scenario_bridge_schemas_and_handlers():
    """Every bridged name resolves to a real schema AND a real v1 handler, the
    schedule-mutating subset is a subset of the bridge, and no bridged name
    collides with a native v2 tool (which would double-offer it to the model)."""
    bridged = agent_tools_v2.get_admin_tools()
    names = [t["name"] for t in bridged]
    check(len(names) == len(agent_tools_v2.ADMIN_TOOLS),
          f"all bridge tools resolved a schema, got {len(names)}")
    check(all(t["parameters"].get("type") for t in bridged),
          "every bridged schema carries a parameters.type")
    handlers = set(agent_tools_v2.TOOL_HANDLERS)
    missing = [n for n in agent_tools_v2.ADMIN_TOOLS if n not in handlers]
    check(not missing, f"every bridged tool has a v1 handler, missing {missing}")
    check(agent_tools_v2.SCHEDULE_MUTATING_ADMIN_TOOLS <= set(agent_tools_v2.ADMIN_TOOLS),
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
    scenario_registry_keeps_every_v1_name,
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
