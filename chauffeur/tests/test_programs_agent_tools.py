"""Argyle can find a plan and count a session. It cannot claim the week."""
from harness import check
from program_fixture import add_run
import datetime
import json
from unittest.mock import patch
from services import agent_tools_v2, storage


def scenario_reads_are_in_both_stacks():
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('list_programs' in names, "the Gemma stack can list programs")
    check('list_programs' in agent_tools_v2.TOOL_SCHEMAS, "and so can the v1 loop")


def scenario_approving_is_never_a_chat_tool():
    """The footprint claims time in the family's week. That stays a deliberate
    tap on a screen showing what it will do."""
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('approve_program' not in names, "approval is not a chat tool")
    check('approve_program' not in agent_tools_v2.TOOL_SCHEMAS, "in either stack")


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
    storage.library_programs_table.truncate()
    # Access spec §2: a keeper must name an active stored member. These
    # fixtures used to contain program member ids without any member rows.
    for mid in ('kid-a', 'kid-b'):
        if not storage.get_member(mid):
            storage.add_member({'id': mid, 'name': mid, 'role': 'child'})
    if not storage.get_member('mom'):
        storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})


def scenario_a_childs_not_found_hint_never_names_a_sibling():
    """A mistyped title used to build its failure message from EVERY
    household program, not just the ones this caller may see -- so a kid's
    typo read a sibling's program title back to them. `_match_program` now
    scopes before it matches, the same partition `list_programs` already
    uses, so the not-found hint can carry only what this caller could see
    on a successful lookup too."""
    _reset_programs()
    add_run({'member_id': 'kid-a', 'title': 'Guitar practice'})
    add_run({'member_id': 'kid-b', 'title': 'Soccer skills'})
    res = agent_tools_v2.program_progress(
        'Xylophone', acting_member={'id': 'kid-a', 'role': 'child'})
    check(res.get('status') == 'error', f"got {res}")
    msg = res.get('message') or ''
    check('Soccer skills' not in msg,
          f"a sibling's program must never leak through the hint, got {msg!r}")
    check('Guitar practice' in msg,
          f"the caller's own program is still a fair hint, got {msg!r}")


def scenario_a_parents_not_found_hint_still_sees_the_household():
    """A parent/adult keeps the household hint through the conversation gate,
    just as in `list_programs`."""
    _reset_programs()
    add_run({'member_id': 'kid-a', 'title': 'Guitar practice'})
    add_run({'member_id': 'kid-b', 'title': 'Soccer skills'})
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
    # Front door slice 1: propose_program is a registry tool (plans propose programs); chat starts a project.
    props = agent_tools_v2.TOOL_SCHEMAS['propose_program']['properties']
    check('starting_point' in props, f"the tool takes it, got {sorted(props)}")
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


def scenario_a_proposal_curates_only_a_public_profile_and_keeps_its_private_start():
    from services import programs_curate
    _reset_programs()
    actor = storage.get_member('mom')
    secret = 'PRIVATE-START: already plays open chords but is shy about singing'
    calls = []

    def echo_input(title, shape, **kwargs):
        calls.append((title, shape, kwargs))
        return {'phases': [{'name': 'Start', 'weeks': 2, 'steps': [repr((shape, kwargs))]}],
                'source': {'origin': 'generated', 'reason': repr((shape, kwargs))}}

    for birthdate, expected_band in ((f'{datetime.date.today().year - 9}-03-01', 'explorer'), (None, 'any')):
        storage.update_member('kid-a', {'birthdate': birthdate, 'stage_override': 'copilot'})
        with patch.object(programs_curate, 'curate', side_effect=echo_input):
            result = agent_tools_v2.propose_program('Learn guitar', for_member_name='kid-a', minutes=20,
                sessions_per_week=2, starting_point=secret, acting_member=actor)
        check(result.get('status') == 'success', f'the parent can propose for a child: {result}')
        run = storage.get_program(result['id'])
        curriculum = storage.get_library_program(run['library_id'])
        expected = {'age_band': expected_band, 'minutes': 20, 'sessions_per_week': 2, 'assumes': ''}
        check(curriculum['made_for'] == expected, f'public profile from birthdate, not pinned stage: {curriculum}')
        check(calls[-1][1] == expected and not calls[-1][2], f'no member or private starting point reaches curation: {calls[-1]}')
        check(secret not in json.dumps(curriculum) and secret not in json.dumps(storage.get_library_programs()),
              'no private starting point can be echoed into public curriculum or source')
        check(run['starting_point'] == secret and run['member_id'] == 'kid-a' and curriculum['created_by'] == 'mom',
              'the private starting point stays on the correct run; its adult made the library row')


def scenario_a_childs_argyle_proposal_is_refused_before_publication():
    from services import programs_curate
    _reset_programs()
    before = storage.get_library_programs()
    runs_before = storage.get_programs(include_finished=True)
    with patch.object(programs_curate, 'curate', side_effect=AssertionError('a child cannot publish curriculum')) as curate:
        result = agent_tools_v2.propose_program('Learn guitar', starting_point='already plays open chords',
                                               acting_member=storage.get_member('kid-a'))
    check(result == {'status': 'error', 'message': 'Only a signed-in parent or adult can start a program.'},
          f'the existing child refusal is returned cleanly: {result}')
    check(not curate.called and storage.get_library_programs() == before
          and storage.get_programs(include_finished=True) == runs_before,
          'the refused proposal spends no research and creates no half state')


if __name__ == '__main__':
    scenario_reads_are_in_both_stacks()
    scenario_approving_is_never_a_chat_tool()
    scenario_writes_refuse_an_unresolved_caller()
    scenario_a_body_aim_is_refused_in_chat_too()
    scenario_a_childs_not_found_hint_never_names_a_sibling()
    scenario_a_parents_not_found_hint_still_sees_the_household()
    scenario_the_chat_tool_can_be_told_where_somebody_is_starting()
    scenario_a_body_target_in_the_starting_point_is_refused_in_chat_too()
    scenario_a_proposal_curates_only_a_public_profile_and_keeps_its_private_start()
    scenario_a_childs_argyle_proposal_is_refused_before_publication()
    print("test_programs_agent_tools OK")
