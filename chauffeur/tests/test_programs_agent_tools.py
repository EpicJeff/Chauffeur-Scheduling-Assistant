"""Argyle can find a plan and count a session. It cannot claim the week."""
from harness import check
from services import agent_tools, agent_tools_v2, storage


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


def _reset_programs():
    storage.programs_table.truncate()


def scenario_a_childs_not_found_hint_never_names_a_sibling():
    """A mistyped title used to build its failure message from EVERY
    household program, not just the ones this caller may see -- so a kid's
    typo read a sibling's program title back to them. `_match_program` now
    scopes before it matches, the same partition `list_programs` already
    uses, so the not-found hint can carry only what this caller could see
    on a successful lookup too."""
    _reset_programs()
    storage.add_program({'member_id': 'kid-a', 'title': 'Guitar practice'})
    storage.add_program({'member_id': 'kid-b', 'title': 'Soccer skills'})
    res = agent_tools_v2.program_progress(
        'Xylophone', acting_member={'id': 'kid-a', 'role': 'child'})
    check(res.get('status') == 'error', f"got {res}")
    msg = res.get('message') or ''
    check('Soccer skills' not in msg,
          f"a sibling's program must never leak through the hint, got {msg!r}")
    check('Guitar practice' in msg,
          f"the caller's own program is still a fair hint, got {msg!r}")


def scenario_a_parents_not_found_hint_still_sees_the_household():
    """A parent/adult keeps the full household hint -- the scope
    `_program_scope_id` gives a parent is `None` (everyone), same as
    `list_programs`."""
    _reset_programs()
    storage.add_program({'member_id': 'kid-a', 'title': 'Guitar practice'})
    storage.add_program({'member_id': 'kid-b', 'title': 'Soccer skills'})
    res = agent_tools_v2.program_progress(
        'Xylophone', acting_member={'id': 'mom', 'role': 'parent'})
    check(res.get('status') == 'error', f"got {res}")
    msg = res.get('message') or ''
    check('Guitar practice' in msg and 'Soccer skills' in msg,
          f"a parent still sees the whole household's titles, got {msg!r}")


def scenario_the_chat_tool_can_be_told_where_somebody_is_starting():
    """Every capability the hand path has, the agent has -- and the router
    has to forward it, or the schema advertises a field that goes nowhere."""
    import inspect
    from services import agent_router
    tool = next(t for t in agent_tools_v2.get_available_tools()
                if t['name'] == 'propose_program')
    check('starting_point' in tool['parameters']['properties'],
          f"the tool takes it, got {sorted(tool['parameters']['properties'])}")
    check('starting_point' in
          inspect.signature(agent_tools_v2.propose_program).parameters,
          "and the function behind it does too")
    src = inspect.getsource(agent_router.run_agent_turn) \
        if hasattr(agent_router, 'run_agent_turn') \
        else inspect.getsource(agent_router)
    check('starting_point=args.get("starting_point")' in src,
          "and the router passes it through rather than dropping it")


def scenario_a_body_target_in_the_starting_point_is_refused_in_chat_too():
    """Same screen, same sentence, wherever the second free field is typed."""
    _reset_programs()
    res = agent_tools_v2.propose_program(
        'learn to cook', starting_point='I want to be at my goal weight',
        acting_member={'id': 'p1', 'name': 'Mom', 'role': 'parent'})
    check(res.get('status') == 'error', f"got {res}")
    check(res.get('alternatives'), f"and offers the behaviour version, got {res}")
    check(storage.get_programs(include_finished=True) == [],
          "and nothing was created to approve later")


if __name__ == '__main__':
    scenario_reads_are_in_both_stacks()
    scenario_approving_is_never_a_chat_tool()
    scenario_writes_refuse_an_unresolved_caller()
    scenario_a_body_aim_is_refused_in_chat_too()
    scenario_a_childs_not_found_hint_never_names_a_sibling()
    scenario_a_parents_not_found_hint_still_sees_the_household()
    scenario_the_chat_tool_can_be_told_where_somebody_is_starting()
    scenario_a_body_target_in_the_starting_point_is_refused_in_chat_too()
    print("test_programs_agent_tools OK")
