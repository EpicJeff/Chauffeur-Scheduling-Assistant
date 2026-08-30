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
              '/api/programs/{program_id}/unit',
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
              '/api/programs/{program_id}/edit',
              '/api/programs/celebrations'):
        check(p in paths, f"{p} must be reachable by hand")


def _stub_curate(phases, source=None):
    from services import programs_curate as _cur
    src = source or {'plan_name': 'Found Plan', 'url': 'https://x.example/',
                     'why_this_one': 'it fits', 'facts': [], 'runners_up': [],
                     'origin': 'cited', 'reason': '', 'hand_written': False}
    _cur.curate = lambda *a, **kw: {'phases': list(phases), 'source': src}
    return _cur


def scenario_a_proposal_can_be_re_shaped_without_spending_research():
    """Changing how many evenings a week are realistic re-paces the phases
    already found. It reads nothing: the material did not change, only how
    much of it fits in a week -- and a research run is a real, capped cost."""
    _reset()
    import main
    from services import programs_curate as _cur
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 3, 'minutes': 25, 'preferred_days': []},
        'phases': [{'name': 'Grade 1', 'weeks': 4, 'what': 'Open chords',
                    'milestone': 'G-C-D', 'milestone_hit_at': None}]})
    called = []
    real_curate = _cur.curate
    _cur.curate = lambda *a, **kw: called.append(1) or {'phases': [],
                                                        'source': {}}
    try:
        res = main.edit_program(pid, body={'member_id': 'mom',
                                            'sessions_per_week': 2},
                                 request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    check(called == [], "a shape edit must not spend a research run")
    row = storage.get_program(pid)
    check(row['shape']['sessions_per_week'] == 2, f"the shape moved: {row['shape']}")
    check(row['phases'][0]['weeks'] == _cur.phase_weeks(2),
          f"and the phases were re-paced by the same arithmetic, got "
          f"{row['phases']}")
    check(row['phases'][0]['name'] == 'Grade 1',
          "the material itself is untouched")


def scenario_changing_the_aim_looks_for_a_new_plan():
    _reset()
    import main
    from services import programs_curate as _cur
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 3, 'minutes': 25, 'preferred_days': []},
        'phases': [{'name': 'Old', 'weeks': 4, 'what': 'old material',
                    'milestone': '', 'milestone_hit_at': None}]})
    real_curate = _cur.curate
    _stub_curate([{'name': 'New', 'weeks': 4, 'what': 'new material',
                   'milestone': '', 'milestone_hit_at': None}])
    try:
        res = main.edit_program(pid, body={'member_id': 'mom',
                                            'title': 'Learn the ukulele'},
                                 request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['title'] == 'Learn the ukulele', f"the aim moved: {row['title']}")
    check(row['phases'][0]['name'] == 'New',
          f"a plan found for the OLD aim must not survive it, got {row['phases']}")


def scenario_looking_again_re_runs_research_on_the_same_aim():
    """The hand path out of the 'none' tier: research was off, capped or down
    when this was proposed, and nothing on the card could ever try again."""
    _reset()
    import main
    from services import programs_curate as _cur
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 3, 'minutes': 25, 'preferred_days': []},
        'phases': [], 'source': {'origin': 'none', 'reason': 'capped',
                                 'hand_written': True}})
    real_curate = _cur.curate
    _stub_curate([{'name': 'Grade 1', 'weeks': 4, 'what': 'Open chords',
                   'milestone': 'G-C-D', 'milestone_hit_at': None}])
    try:
        res = main.edit_program(pid, body={'member_id': 'mom',
                                            'recurate': True}, request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['phases'], f"the second look replaced the empty plan, got {row}")
    check(row['source']['origin'] == 'cited', f"and its tier moved, got {row['source']}")


def scenario_looking_again_never_costs_the_plan_already_found():
    """Research can be down, capped or simply unlucky. Overwriting a cited
    plan with an empty one would make Look again a button that can only
    lose."""
    _reset()
    import main
    from services import programs_curate as _cur
    had = [{'name': 'Grade 1', 'weeks': 4, 'what': 'Open chords',
            'milestone': 'G-C-D', 'milestone_hit_at': None}]
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'phases': list(had),
        'source': {'plan_name': 'Justin Guitar', 'url': 'https://jg.example/',
                   'origin': 'cited', 'reason': '', 'hand_written': False}})
    real_curate = _cur.curate
    _cur.curate = lambda *a, **kw: {
        'phases': [], 'source': {'origin': 'none', 'reason': 'capped',
                                 'hand_written': True}}
    try:
        res = main.edit_program(pid, body={'member_id': 'mom',
                                            'recurate': True}, request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['phases'] == had, f"the plan they had must stand, got {row['phases']}")
    check(row['source']['plan_name'] == 'Justin Guitar',
          f"and so must where it came from, got {row['source']}")
    check('stands' in res.get('message', ''),
          f"and the message says nothing new was found, got {res.get('message')!r}")


def scenario_a_family_can_choose_their_own_practice_windows():
    """`propose_slots` has always said in its own docstring that "the person
    can move them on the approval screen anyway". Until this landed the screen
    offered no such thing: preferred DAYS was as close as a family could get
    to naming a time, and the hour came from a module constant."""
    _reset()
    import main
    from services import programs as _prog
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 3, 'minutes': 30, 'preferred_days': []}})
    res = main.edit_program(pid, body={
        'member_id': 'mom',
        'slots': [{'day': 2, 'time_start': '07:15'},
                  {'day': 5, 'time_start': '16:00'}]}, request=None)
    check(res.get('status') == 'success', f"got {res}")
    row = storage.get_program(pid)
    check([s['time_start'] for s in row['shape']['slots']] == ['07:15', '16:00'],
          f"the chosen times are what is stored, got {row['shape']['slots']}")
    check(row['shape']['slots'][0]['time_end'] == '07:45',
          f"the end is computed from minutes, never accepted, got "
          f"{row['shape']['slots'][0]}")
    check(row['shape']['sessions_per_week'] == 2,
          f"two windows IS twice a week -- the two must never disagree, got "
          f"{row['shape']}")
    proposed = _prog.propose_slots('kid', row['shape'])
    check([s['day'] for s in proposed] == [2, 5],
          f"and proposing yields to the choice rather than second-guessing "
          f"it, got {proposed}")
    fp = main.program_footprint(pid, request=None)
    check([s['time_start'] for s in fp['slots']] == ['07:15', '16:00'],
          f"the approval screen shows what will really be claimed, got {fp}")


def scenario_handing_the_choice_back_resumes_proposing():
    _reset()
    import main
    from services import programs as _prog
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 2, 'minutes': 25, 'preferred_days': [1],
                  'slots': [{'day': 6, 'time_start': '08:00',
                             'time_end': '08:25'}]}})
    res = main.edit_program(pid, body={'member_id': 'mom', 'slots': []},
                            request=None)
    check(res.get('status') == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['shape']['slots'] == [],
          f"an explicit empty list is an instruction, not a no-op, got {row['shape']}")
    check([s['day'] for s in _prog.propose_slots('kid', row['shape'])],
          "and the app proposes again from the preferred days")


def scenario_an_edit_of_the_minutes_keeps_the_chosen_windows():
    """Building the shape from three named fields quietly dropped the fourth,
    so changing how long a session runs threw away every time somebody had
    picked by hand."""
    _reset()
    import main
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 1, 'minutes': 25, 'preferred_days': [],
                  'slots': [{'day': 3, 'time_start': '17:30',
                             'time_end': '17:55'}]}})
    main.edit_program(pid, body={'member_id': 'mom', 'minutes': 60},
                      request=None)
    row = storage.get_program(pid)
    check(len(row['shape']['slots']) == 1,
          f"the chosen window survives an unrelated edit, got {row['shape']}")
    check(row['shape']['slots'][0]['time_end'] == '18:30',
          f"and its end follows the new length, got {row['shape']['slots'][0]}")


def scenario_a_slot_list_from_a_request_cannot_reach_the_solver_unchecked():
    """The hole picking your own times would have opened. `approve()` took
    `slots` from the request body and handed them straight to
    `_emit_commitments`, which writes `time_end` into a `ProtectedCommitment`
    and from there into a solver `Rule` -- and every commitment is converted
    inside ONE try/except, so a single '29:00' silently disables protected
    time for the whole household."""
    _reset()
    import main
    from services import programs as _prog
    pid = storage.add_program({
        'member_id': 'mom', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 1, 'minutes': 25, 'preferred_days': []}})
    res = _prog.approve(pid, approver_id='mom', slots=[
        {'day': 2, 'time_start': '19:00', 'time_end': '29:00'},
        {'day': 99, 'time_start': '19:00'},
        {'day': 4, 'time_start': 'whenever'},
    ])
    check(res.get('status') == 'success', f"got {res}")
    windows = [(c['days_of_week'], c['time_start'], c['time_end'])
               for c in storage.get_protected_commitments(member_id='mom')]
    check(len(windows) == 1, f"only the real window survives, got {windows}")
    check(windows[0][2] == '19:25',
          f"and its end is the app's arithmetic, not the caller's claim, got "
          f"{windows[0]}")


def scenario_a_body_aim_is_refused_on_an_edit_too():
    """The screen runs on every door into a title, not just the first one --
    an aim that could not be proposed must not be reachable by renaming."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'proposed'})
    res = main.edit_program(pid, body={'member_id': 'mom',
                                        'title': 'lose 15 pounds'},
                             request=None)
    check(res.get('status') == 'error', f"got {res}")
    check(res.get('alternatives'), "and the behaviour version is offered")
    check(storage.get_program(pid)['title'] == 'Guitar', "and nothing moved")


def scenario_only_a_proposal_is_editable():
    """Once time is claimed, changing the plan under it would move windows
    nobody re-approved. `reshape` is the way back, and it frees the time."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'active'})
    res = main.edit_program(pid, body={'member_id': 'mom', 'minutes': 45},
                             request=None)
    check(res.get('status') == 'error', f"an active program is not editable: {res}")
    check(storage.get_program(pid).get('shape', {}).get('minutes') != 45,
          "and nothing moved")


def scenario_a_child_cannot_edit_a_siblings_proposal():
    _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'proposed'})
    token = storage.create_member_token('sib')
    check(_denied(main.edit_program, pid, body={}, request=Req(token)) == 403,
          "editing somebody else's proposal needs a parent/adult")


def scenario_dismissing_a_proposal_is_reachable_and_honest():
    """A proposal used to have exactly one exit -- approve -- so a typo or a
    bad guess sat on the page forever. Dropping one never had time to give
    back, and saying it did would be a small lie about the one thing this
    page is careful about."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'proposed'})
    res = main.drop_program(pid, background_tasks=None,
                            body={'member_id': 'mom'}, request=None)
    check(res.get('status') == 'success', f"got {res}")
    check('claimed' in res.get('message', ''),
          f"the words must match the facts, got {res.get('message')!r}")
    check(storage.get_program(pid)['state'] == 'dropped',
          "and the proposal is gone from the live list")


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


def scenario_a_starting_point_is_taken_by_hand_and_used():
    """The hand path for the field that stops a plan being written for a
    generic beginner. Typed on the Programs page, stored on the program, and
    handed to curation with the member themselves rather than a first name."""
    _reset()
    import main
    from services import programs_curate as _cur
    seen = {}
    real_curate = _cur.curate
    def fake(title, shape, member_name='', member=None, starting_point=''):
        seen['member'] = member
        seen['starting_point'] = starting_point
        return {'phases': [], 'source': {}}
    _cur.curate = fake
    try:
        res = main.create_program(body={
            'member_id': 'kid', 'title': 'learn guitar',
            'starting_point': 'already plays open chords'}, request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    check(seen.get('starting_point') == 'already plays open chords',
          f"it has to reach curation, got {seen}")
    check((seen.get('member') or {}).get('id') == 'kid',
          f"and so does the person, not only their name, got {seen}")
    row = storage.get_program(res['id'])
    check(row.get('starting_point') == 'already plays open chords',
          f"and it is kept, so looking again can use it, got {row}")


def scenario_a_body_target_in_the_starting_point_is_refused_too():
    """The aim screen guards one box. A body target typed one box lower is
    the same refused thing, and nothing may be created to approve later."""
    _reset()
    import main
    from services import programs_curate as _cur
    called = []
    real_curate = _cur.curate
    _cur.curate = lambda *a, **kw: called.append(1) or {'phases': [],
                                                        'source': {}}
    try:
        res = main.create_program(body={
            'member_id': 'kid', 'title': 'learn to cook',
            'starting_point': 'I weigh 200 lbs and want to be 170'},
            request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'error', f"got {res}")
    check(res.get('alternatives'), "and the behaviour version is offered")
    check(called == [], "and no research run is spent on a refused proposal")
    check(storage.get_programs(include_finished=True) == [],
          "and nothing was created to accept later")


def scenario_editing_the_starting_point_spends_no_research():
    """The material on the page did not change; how it should be organised
    did. Re-reading the web to learn that would charge the family for an
    edit, so it is saved and used the next time somebody looks again -- and
    the answer says so rather than leaving them to wonder."""
    _reset()
    import main
    from services import programs_curate as _cur
    pid = storage.add_program({
        'member_id': 'kid', 'title': 'Guitar', 'state': 'proposed',
        'shape': {'sessions_per_week': 3, 'minutes': 25, 'preferred_days': []},
        'phases': [{'name': 'Grade 1', 'weeks': 4, 'what': 'Open chords',
                    'milestone': 'G-C-D', 'milestone_hit_at': None}]})
    called = []
    real_curate = _cur.curate
    _cur.curate = lambda *a, **kw: called.append(1) or {'phases': [],
                                                        'source': {}}
    try:
        res = main.edit_program(pid, body={
            'member_id': 'mom',
            'starting_point': 'can already read music'}, request=None)
    finally:
        _cur.curate = real_curate
    check(res.get('status') == 'success', f"got {res}")
    check(called == [], "an edit of the starting point reads nothing")
    check('Look again' in (res.get('message') or ''),
          f"and it says how to act on it, got {res.get('message')!r}")
    check(storage.get_program(pid).get('starting_point') ==
          'can already read music', "and it is stored")


def scenario_a_program_says_whether_its_owner_can_reach_it():
    """A three-year-old's program is a real program whose owner will never
    open the app. Every surface that draws "your own" programs leaves that
    plan reachable by nobody, so the list says which programs are like that
    -- from `stages.CAPABILITIES['own_account']`, which a parent can override
    per child, so nothing here guesses at a birthday.
    """
    _reset()
    import datetime
    import main
    from services import stages
    tot = datetime.date.today()
    storage.update_member('kid', {'birthdate':
                                  tot.replace(year=tot.year - 3).isoformat()})
    storage.add_program({'member_id': 'kid', 'title': 'Learn to swim',
                         'state': 'active'})
    storage.add_program({'member_id': 'mom', 'title': 'Guitar',
                         'state': 'active'})
    rows = main.list_programs_api(request=None)['programs']
    by_title = {r['title']: r for r in rows}
    check(by_title['Learn to swim']['owner_self_serves'] is False,
          f"a three-year-old cannot reach their own program, got {by_title}")
    check(by_title['Learn to swim']['member_name'] == 'Lily',
          "and the row names whose it is, so a card can say")
    check(by_title['Guitar']['owner_self_serves'] is True,
          "an adult reaches their own")
    # The stage bundle is a bundle, not a verdict: pinning the capability
    # changes the answer without touching the birthday.
    storage.update_member('kid', {'capability_overrides': {'own_account': True}})
    rows = main.list_programs_api(request=None)['programs']
    again = {r['title']: r for r in rows}['Learn to swim']
    check(again['owner_self_serves'] is True,
          f"a per-child override decides, got {again}")
    check(stages.capabilities(storage.get_member('kid'))['own_account'] is True,
          "and it is the same switch the rest of the app reads")


def scenario_a_parent_can_log_a_small_childs_session():
    """The server has always allowed this -- ownership OR parent/adult. It is
    the only way a session ever gets logged for somebody who cannot tap."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Learn to swim',
                               'state': 'active'})
    res = main.log_program_session(pid, body={'member_id': 'mom',
                                              'source': 'asked'}, request=None)
    check(res.get('status') == 'success', f"a parent may log it, got {res}")
    check(len(storage.get_program(pid)['sessions']) == 1,
          "and it counted once")


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
    scenario_a_proposal_can_be_re_shaped_without_spending_research()
    scenario_changing_the_aim_looks_for_a_new_plan()
    scenario_looking_again_re_runs_research_on_the_same_aim()
    scenario_looking_again_never_costs_the_plan_already_found()
    scenario_a_family_can_choose_their_own_practice_windows()
    scenario_handing_the_choice_back_resumes_proposing()
    scenario_an_edit_of_the_minutes_keeps_the_chosen_windows()
    scenario_a_slot_list_from_a_request_cannot_reach_the_solver_unchecked()
    scenario_a_body_aim_is_refused_on_an_edit_too()
    scenario_only_a_proposal_is_editable()
    scenario_a_child_cannot_edit_a_siblings_proposal()
    scenario_dismissing_a_proposal_is_reachable_and_honest()
    scenario_a_child_cannot_read_a_siblings_footprint()
    scenario_claiming_and_releasing_time_reaches_the_solver()
    scenario_a_starting_point_is_taken_by_hand_and_used()
    scenario_a_body_target_in_the_starting_point_is_refused_too()
    scenario_editing_the_starting_point_spends_no_research()
    scenario_a_program_says_whether_its_owner_can_reach_it()
    scenario_a_parent_can_log_a_small_childs_session()
    print("test_programs_endpoints OK")
