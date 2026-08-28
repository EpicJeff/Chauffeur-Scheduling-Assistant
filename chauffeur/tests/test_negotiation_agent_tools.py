"""Argyle can look for a deal. Argyle cannot send the asks on its own."""
from harness import check
from services import agent_tools, agent_tools_v2, storage


def scenario_both_stacks_can_look():
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('negotiate_day' in names, f"the Gemma stack has it, got {len(names)} tools")
    check('negotiate_day' in agent_tools.TOOL_SCHEMAS,
          "and so does the v1 loop")


def scenario_only_the_new_stack_can_ask():
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('ask_deal' in names, "asking lives where identity is resolved")
    check('ask_deal' not in agent_tools.TOOL_SCHEMAS,
          "and not in the admin loop, which resolves nobody")


def scenario_asking_refuses_an_unresolved_caller():
    res = agent_tools_v2.ask_deal('Soccer', acting_member=None)
    check(res.get('status') == 'error',
          f"an anonymous wall panel may not fan out asks, got {res}")


def scenario_asking_refuses_a_child():
    res = agent_tools_v2.ask_deal('Soccer',
                                  acting_member={'id': 'k1', 'role': 'child'})
    check(res.get('status') == 'error', f"nor may a kid, got {res}")


def scenario_looking_never_asks():
    """negotiate_day must not create a single request, whatever it finds."""
    before = len(storage.get_requests(status='open'))
    agent_tools_v2.negotiate_day(day='2026-09-07',
                                 acting_member={'id': 'p1', 'role': 'parent'})
    after = len(storage.get_requests(status='open'))
    check(before == after,
          f"searching is free and silent, got {before} -> {after}")


if __name__ == '__main__':
    scenario_both_stacks_can_look()
    scenario_only_the_new_stack_can_ask()
    scenario_asking_refuses_an_unresolved_caller()
    scenario_asking_refuses_a_child()
    scenario_looking_never_asks()
    print("test_negotiation_agent_tools OK")
