"""Tests for @argyle in the family chat (Layer 1): the Argyle system member,
and identity/role scoping when a family-chat message is routed to the agent as
the sending member.

The message-endpoint glue (mention detection + posting) lives in main.py and is
thin; the security-critical piece is that process_agent_request(acting_member=...)
resolves the speaker's identity and gates the admin scheduling tools by role.
That is what these scenarios lock down.

Run from chauffeur/:  python tests/test_argyle_chat.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, agent_tools_v2, storage


def _seed_members():
    storage.members_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent", "is_child": False})
    storage.add_member({"id": "kid", "name": "Jack", "role": "child", "is_child": True})


def _capture_tools(acting_member, tool_call=None):
    """Run one router turn as acting_member, capturing the tools offered and the
    system prompt. Returns (captured, result)."""
    captured, state = {}, {"n": 0}

    def fake(prompt, tools, system_prompt):
        captured["tools"] = [t["name"] for t in tools]
        captured["system"] = system_prompt
        state["n"] += 1
        if state["n"] == 1 and tool_call is not None:
            return {"message": "ok", "tool_calls": [tool_call]}
        return {"message": "done", "tool_calls": []}

    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request("who is driving me?", source="family",
                                                 acting_member=acting_member)
    finally:
        agent_router.call_gemma_with_fallback = orig
    return captured, res


def scenario_argyle_member_singleton():
    _seed_members()
    a1 = storage.ensure_argyle_member()
    a2 = storage.ensure_argyle_member()
    check(a1["id"] == a2["id"] == storage.ARGYLE_MEMBER_ID, "Argyle is a stable singleton")
    check(a1.get("system") is True and a1.get("role") == "assistant", "Argyle is a system assistant member")
    check("Argyle" not in agent_tools_v2._member_names(),
          f"Argyle is excluded from the agent's family roster, got {agent_tools_v2._member_names()}")


def scenario_parent_gets_identity_and_admin_tools():
    _seed_members()
    parent = storage.get_member("mom")
    captured, _ = _capture_tools(parent)
    check("Mom" in captured["system"] and "Resolve 'me'" in captured["system"],
          "parent's identity is injected so 'me' resolves without asking")
    check("add_routing_rule" in captured["tools"] and "run_solver" in captured["tools"],
          f"parent @argyle is offered the admin scheduling tools, got sample {captured['tools'][:6]}")


def scenario_child_denied_admin_tools():
    _seed_members()
    kid = storage.get_member("kid")
    captured, _ = _capture_tools(kid)
    check("Jack" in captured["system"], "child's identity is injected")
    check("NOT a parent/admin" in captured["system"], "child prompt states the admin restriction")
    check("add_routing_rule" not in captured["tools"] and "run_solver" not in captured["tools"],
          f"child @argyle is NOT offered admin scheduling tools, got {captured['tools']}")
    # ...but still keeps the everyday family-hub tools
    check("list_chores" in captured["tools"] and "send_family_message" in captured["tools"],
          "child keeps the everyday family-hub tools")


def scenario_role_gated_dispatch():
    _seed_members()
    call = {"name": "add_routing_rule",
            "arguments": {"constraint_type": "unavailable", "driver_id": "dad"}}

    storage.rules_table.truncate()
    before = len(storage.get_all_rules())
    _capture_tools(storage.get_member("kid"), tool_call=call)
    check(len(storage.get_all_rules()) == before,
          "a child @argyle cannot execute an admin scheduling tool even if the model emits it")

    _, res = _capture_tools(storage.get_member("mom"), tool_call=call)
    check(len(storage.get_all_rules()) == before + 1,
          f"a parent @argyle can, and the rule persists, got {storage.get_all_rules()}")
    check(res.get("schedule_dirty") is True, "the parent's schedule change flags a re-solve")


SCENARIOS = [
    scenario_argyle_member_singleton,
    scenario_parent_gets_identity_and_admin_tools,
    scenario_child_denied_admin_tools,
    scenario_role_gated_dispatch,
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
