"""The hand path. Every capability the agent has, a person has by tap."""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


class Req:
    """A minimal stand-in for a real request, carrying only what
    `_acting_id`/`_auth.acting_member` read: a bearer token on the header.
    Same shape as `test_calendar_scope.py`'s own `Req` — a direct-call test
    has no live HTTP layer to mint a real one, and this is the only thing
    that can distinguish "a specific real actor" from `request=None`'s
    trusted-place reading."""
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


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


# --- GET /api/programs is a read, not exempt (task 6/7 review, two rounds).
# Round one only gated the request when a member_id FILTER was present, which
# left a strictly easier hole open: dropping the filter entirely returned
# every member's programs to anybody, token or no token. `_program_list_scope`
# now decides the effective filter on EVERY call, whether or not one was
# asked for: a parent, an adult or the control-center stand-in gets the
# household either way; anyone else is narrowed to their own id even when
# they asked for nothing, and refused outright if they name somebody else.

def scenario_a_child_cannot_list_a_siblings_programs():
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    storage.add_program({'member_id': 'sib', 'title': 'Reading ladder',
                         'state': 'active'})
    kid_token = storage.create_member_token('kid')
    check(_denied(main.list_programs_api, member_id='sib',
                  request=Req(kid_token)) == 403,
          "a child reading a SIBLING's program list must be refused")


def scenario_a_child_can_list_their_own_programs_by_token():
    _reset()
    import main
    storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active'})
    kid_token = storage.create_member_token('kid')
    res = main.list_programs_api(member_id='kid', request=Req(kid_token))
    check([p['title'] for p in res['programs']] == ['Guitar'],
          f"a child reading their OWN list must go through, got {res}")


def scenario_a_parent_can_list_a_childs_programs():
    _reset()
    import main
    storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active'})
    mom_token = storage.create_member_token('mom')
    res = main.list_programs_api(member_id='kid', request=Req(mom_token))
    check([p['title'] for p in res['programs']] == ['Guitar'],
          f"a parent reading a child's list must go through, got {res}")


def scenario_a_child_with_no_filter_gets_only_their_own():
    """Dropping the filter is not a way out -- easier to reach than the
    sibling-by-name hole the first round closed, so it has to close the
    same way: narrowed, not refused, so the PWA's own unfiltered-by-role
    call keeps working with no special case."""
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active'})
    storage.add_program({'member_id': 'sib', 'title': 'Reading ladder',
                         'state': 'active'})
    kid_token = storage.create_member_token('kid')
    res = main.list_programs_api(request=Req(kid_token))
    titles = [p['title'] for p in res['programs']]
    check(titles == ['Guitar'],
          f"a child with no filter must be narrowed to their own, not the "
          f"household, got {titles}")


def scenario_a_parent_with_no_filter_still_gets_the_household():
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active'})
    storage.add_program({'member_id': 'sib', 'title': 'Reading ladder',
                         'state': 'active'})
    mom_token = storage.create_member_token('mom')
    res = main.list_programs_api(request=Req(mom_token))
    titles = sorted(p['title'] for p in res['programs'])
    check(titles == ['Guitar', 'Reading ladder'],
          f"a parent with no filter must still see the household, got {titles}")


def scenario_the_control_center_still_gets_the_household():
    """No token, no claim -- the same trusted-place reading `_mind_actor`
    already grants the writes (and `programs.html`'s own unfiltered fetch
    relies on for the admin page). The child-narrowing above must not have
    turned this into a refusal too."""
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active'})
    storage.add_program({'member_id': 'sib', 'title': 'Reading ladder',
                         'state': 'active'})
    res = main.list_programs_api(request=Req())
    titles = sorted(p['title'] for p in res['programs'])
    check(titles == ['Guitar', 'Reading ladder'],
          f"the control-center reading must still see the household, got {titles}")


class _Bg:
    """Stands in for FastAPI's BackgroundTasks so a direct call can see
    whether the endpoint really asked for a solver refresh."""
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append(fn)


def scenario_the_new_endpoints_exist():
    import main
    paths = {r.path for r in main.app.routes}
    for p in ('/api/programs/{program_id}/finish',
              '/api/programs/{program_id}/reshape',
              '/api/programs/celebrations'):
        check(p in paths, f"{p} must be reachable by hand")


def scenario_a_child_cannot_read_a_siblings_footprint():
    """The one program read with no ownership gate at all: a title, the times
    it would claim, the kit line and the target date, to any signed-in caller
    holding an id."""
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'proposed',
                               'shape': {'sessions_per_week': 2, 'minutes': 25,
                                         'preferred_days': [1, 3]}})
    sib_token = storage.create_member_token('sib')
    check(_denied(main.program_footprint, pid, request=Req(sib_token)) == 403,
          "a sibling learns nothing about it, not even the times it claims")
    kid_token = storage.create_member_token('kid')
    fp = main.program_footprint(pid, request=Req(kid_token))
    check('slots' in fp, f"the owner still sees their own, got {fp}")
    fp = main.program_footprint(pid, request=None)
    check('slots' in fp, f"and the control-center surface does, got {fp}")


def scenario_claiming_and_releasing_time_reaches_the_solver():
    """`programs.approve()` has always returned `schedule_dirty` and every
    endpoint threw it away -- while `create_commitment` force-refreshes on
    exactly this event, because protecting an evening that stays scheduled is
    not protecting it."""
    _reset()
    import main
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 2, 'minutes': 25,
                  'preferred_days': [1, 3]}})
    bg = _Bg()
    res = main.approve_program(pid, background_tasks=bg,
                               body={'member_id': 'mom'}, request=None)
    check(res['status'] == 'success', f"got {res}")
    check(len(bg.tasks) == 1,
          f"approving asks the solver to learn the ban now, got {bg.tasks}")

    bg2 = _Bg()
    res = main.drop_program(pid, background_tasks=bg2,
                            body={'member_id': 'mom'}, request=None)
    check(res['status'] == 'success', f"got {res}")
    check(len(bg2.tasks) == 1,
          f"and dropping asks it to give the evening back, got {bg2.tasks}")
    check(storage.get_program(pid)['emissions']['commitment_ids'] == [],
          "a dropped program stops believing in windows that are really gone")


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
    scenario_a_child_cannot_list_a_siblings_programs()
    scenario_a_child_can_list_their_own_programs_by_token()
    scenario_a_parent_can_list_a_childs_programs()
    scenario_a_child_with_no_filter_gets_only_their_own()
    scenario_a_parent_with_no_filter_still_gets_the_household()
    scenario_the_control_center_still_gets_the_household()
    scenario_the_new_endpoints_exist()
    scenario_a_child_cannot_read_a_siblings_footprint()
    scenario_claiming_and_releasing_time_reaches_the_solver()
    print("test_programs_endpoints OK")
