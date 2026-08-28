"""The hand path. Every capability the agent has, a person has by tap."""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


def _denied(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _reset():
    storage.programs_table.truncate()
    storage.members_table.truncate()
    storage.protected_commitments_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})


def scenario_the_endpoints_exist():
    import main
    paths = {r.path for r in main.app.routes}
    for p in ('/programs', '/api/programs', '/api/programs/{program_id}/approve',
              '/api/programs/{program_id}/session',
              '/api/programs/{program_id}/milestone',
              '/api/programs/{program_id}/pause',
              '/api/programs/{program_id}/drop'):
        check(p in paths, f"{p} must be reachable by hand")


def scenario_a_body_aim_is_refused_at_the_door():
    _reset()
    import main
    res = main.create_program(body={'member_id': 'kid',
                                    'title': 'lose 15 pounds'}, request=None)
    check(res.get('status') == 'error', f"got {res}")
    check(res.get('alternatives'), "and the behaviour version is offered")
    check(storage.get_programs(include_finished=True) == [],
          "and nothing was created to accept later")


def scenario_a_child_cannot_approve():
    _reset()
    import main
    check(_denied(main.approve_program, 'nope',
                  body={'member_id': 'kid'}, request=None) == 403,
          "approving claims the family's week — that is grown-up work")


def scenario_logging_a_session_is_reachable():
    """A child logs a session on their OWN program -- ownership, not role,
    is what should let this through."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'active'})
    res = main.log_program_session(pid, body={'minutes': 25,
                                              'member_id': 'kid'}, request=None)
    check(res.get('status') == 'success', f"got {res}")
    check(len(storage.get_program(pid)['sessions']) == 1, "and it counted")


# --- Ownership, not role (task 5 review fix) --------------------------------
# The first cut of these endpoints checked nothing but "is this a signed-in
# member" on session/milestone/pause/resume/drop, which let a child drop a
# PARENT's approved program from the shipped page. The rule now: free rein on
# YOUR OWN program; somebody else's needs a parent/adult, the same stand-in
# `approve` already used.

def scenario_a_child_cannot_drop_a_parents_program():
    _reset()
    import main
    pid = storage.add_program({'member_id': 'mom', 'title': "Learn Spanish",
                               'state': 'active'})
    cid = storage.add_protected_commitment({
        'id': 'commit_mom_1', 'member_id': 'mom', 'title': 'Learn Spanish',
        'days_of_week': [1], 'time_start': '19:00', 'time_end': '19:30',
        'active': True})
    storage.update_program(pid, {'emissions': {'commitment_ids': [cid],
                                               'thread_ids': [], 'event_ids': []}})
    check(_denied(main.drop_program, pid, body={'member_id': 'kid'}, request=None) == 403,
          "a child dropping a PARENT's program must be refused")
    check(storage.get_program(pid)['state'] == 'active',
          "mom's program is untouched by the refused attempt")
    check(len(storage.get_protected_commitments(member_id='mom')) == 1,
          "mom's claimed practice time survives the refused attempt")


def scenario_a_child_cannot_mark_a_siblings_milestone():
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    pid = storage.add_program({'member_id': 'sib', 'title': 'Reading ladder',
                               'state': 'active',
                               'phases': [{'name': 'Level 1', 'weeks': 2, 'what': '',
                                          'milestone': 'Finish 5 books',
                                          'milestone_hit_at': None}]})
    check(_denied(main.hit_program_milestone, pid,
                  body={'member_id': 'kid', 'phase_name': 'Level 1'}, request=None) == 403,
          "a child marking a SIBLING's milestone must be refused")
    check(storage.get_program(pid)['phases'][0]['milestone_hit_at'] is None,
          "the sibling's milestone is untouched")


def scenario_a_parent_acts_on_a_childs_program():
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'active'})
    res = main.pause_program(pid, body={'member_id': 'mom'}, request=None)
    check(res.get('status') == 'success', f"a parent pausing a child's program: got {res}")
    check(storage.get_program(pid)['state'] == 'paused', "mom's pause took effect")


def scenario_the_control_center_surface_acts_via_parent_of_record():
    """No member claimed at all -- the control-center reading. `_mind_actor`
    resolves to None there and `_approver_of_record` stands in the
    household's parent of record, exactly as `approve` already relies on."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'active'})
    res = main.pause_program(pid, body={}, request=None)
    check(res.get('status') == 'success',
          f"the control-center surface should stand in as the parent of record: {res}")
    check(storage.get_program(pid)['state'] == 'paused',
          "the stand-in's pause took effect")


def scenario_a_child_proposes_for_themselves():
    _reset()
    import main
    from services import programs_curate as _cur
    real_curate = _cur.curate
    _cur.curate = lambda *a, **kw: {
        'phases': [], 'source': {'plan_name': '', 'url': '', 'why_this_one': '',
                                 'facts': [], 'runners_up': [], 'hand_written': True}}
    try:
        res = main.create_program(body={'member_id': 'kid', 'for_member_id': 'kid',
                                        'title': 'Learn guitar'}, request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    check(storage.get_program(res['id'])['member_id'] == 'kid',
          "the program belongs to the child who proposed it, for themselves")


def scenario_a_child_cannot_propose_for_somebody_else():
    _reset()
    import main
    check(_denied(main.create_program, body={'member_id': 'kid', 'for_member_id': 'mom',
                                             'title': 'Learn guitar'}, request=None) == 403,
          "a child proposing in somebody ELSE's name needs a parent/adult")
    check(storage.get_programs(include_finished=True) == [],
          "and nothing was created")


if __name__ == '__main__':
    scenario_the_endpoints_exist()
    scenario_a_body_aim_is_refused_at_the_door()
    scenario_a_child_cannot_approve()
    scenario_logging_a_session_is_reachable()
    scenario_a_child_cannot_drop_a_parents_program()
    scenario_a_child_cannot_mark_a_siblings_milestone()
    scenario_a_parent_acts_on_a_childs_program()
    scenario_the_control_center_surface_acts_via_parent_of_record()
    scenario_a_child_proposes_for_themselves()
    scenario_a_child_cannot_propose_for_somebody_else()
    print("test_programs_endpoints OK")
