"""Argyle can find a plan and count a session. It cannot claim the week."""
from harness import check
from services import agent_tools, agent_tools_v2


def scenario_reads_are_in_both_stacks():
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('list_programs' in names, "the Gemma stack can list programs")
    check('list_programs' in agent_tools.TOOL_SCHEMAS, "and so can the v1 loop")


def scenario_approving_is_never_a_chat_tool():
    """The footprint claims time in the family's week. That stays a deliberate
    tap on a screen showing what it will do."""
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('approve_program' not in names, "approval is not a chat tool")
    check('approve_program' not in agent_tools.TOOL_SCHEMAS, "in either stack")


def scenario_writes_refuse_an_unresolved_caller():
    res = agent_tools_v2.propose_program('learn guitar', acting_member=None)
    check(res.get('status') == 'error',
          f"an anonymous wall panel may not start a program, got {res}")


def scenario_a_body_aim_is_refused_in_chat_too():
    res = agent_tools_v2.propose_program(
        'lose 15 pounds', acting_member={'id': 'p1', 'role': 'parent'})
    check(res.get('status') == 'error', f"got {res}")
    check('weight' in (res.get('message') or '').lower()
          or 'behaviour' in (res.get('message') or '').lower()
          or 'behavior' in (res.get('message') or '').lower(),
          f"and says what it will do instead, got {res}")


if __name__ == '__main__':
    scenario_reads_are_in_both_stacks()
    scenario_approving_is_never_a_chat_tool()
    scenario_writes_refuse_an_unresolved_caller()
    scenario_a_body_aim_is_refused_in_chat_too()
    print("test_programs_agent_tools OK")
