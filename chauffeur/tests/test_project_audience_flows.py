"""Project audiences driven through the real entry points (spec sections 2, 3 and 6): a subject
bound by any production writer narrows the record's wrapper, and a plan's explicit list survives
proposal, preview, approval, the wrapper reshape and an interrupted approval replayed by reconcile.

Nothing here calls project_audience.narrow_on_bind: the tests fail if a writer forgets to.

Binding entry points exercised (Task 3 must call narrow_on_bind after each of these writes):
  thread    agent_tools_v2.start_mission_for        (agent_tools_v2.py, `storage.update_thread` after _threads.create)
  thread    missions._apply_planner_action 'subject' on a thread-origin mission   (missions.py:1570)
  mission   missions._apply_planner_action 'subject' on a manual mission          (missions.py:1574)
  mission   missions.launch(subject=...)            (missions.py:1770; the wrapper is made after, so it is born right)
  mission/thread  planned._bind_created via planned.run_stage creating an occasion  (planned.py:1003)
  thread/mission  subjects.retarget via situations.act(verb='subject')              (subjects.py:358)
  program   NO WRITER: nothing in services/ or main.py sets subject_* on a program row.

Run from chauffeur/:  python tests/test_project_audience_flows.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, access
from services import agent_tools_v2 as tools
from test_planned_missions import _fresh as _fresh_planned, _staged
from test_mission_subject import _plan, _mission, _step
from test_projects import _p
from test_subjects import MOM, DAD, AUNT, KID


def _fresh():
    _fresh_planned()
    storage.projects_table.truncate()
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})


def _seen(pid, members=(MOM, DAD, AUNT, KID)):
    row = storage.get_project(pid)
    return {m['id'] for m in members if _p().can_see(row, dict(m))}


def _wrapper_of_thread(tid):
    return storage.get_thread(tid)['project_id']


def _wrapper_of_mission(mid):
    return storage.get_mission(mid)['project_id']


def _only_mom(pid, how):
    row = storage.get_project(pid)
    check(_seen(pid) == {'mom'}, f"{how}: the wrapper narrowed to the people who may read the record: {_seen(pid)} {row}")
    check(not access.project_visible(row, access.HOUSE), f"{how}: and the house no longer reads it")
    check(row.get('wrapped_from'), f"{how}: provenance is kept")


def scenario_start_mission_for_narrows_the_new_threads_wrapper():
    _fresh()
    res = tools.start_mission_for('plan the surprise party', acting_member=dict(MOM), focus_key='conv:1',
                                  subject_kind='occasion', subject_id='occ-dad')
    check(res['status'] == 'success', f"started: {res}")
    t = storage.get_thread(res['thread_id'])
    check(t['subject_kind'] == 'occasion', f"the thread is bound: {t}")
    _only_mom(t['project_id'], 'start_mission_for')


def scenario_planner_subject_action_narrows_a_thread_missions_wrapper():
    _fresh()
    from services import threads
    tid = threads.create(title='Surprise', owner_member_id='mom', created_by='mom')
    pid = _wrapper_of_thread(tid)
    check(_seen(pid) == {'mom', 'dad', 'aunt', 'kid'} and storage.get_project(pid)['audience'] == 'household', "the fixture: an open thread's household wrapper")
    mid = _mission(created_by='mom', origin=tid)
    _plan({'action': 'subject', 'kind': 'occasion', 'id': 'occ-dad'})
    _step(mid)
    check(storage.get_thread(tid)['subject_id'] == 'occ-dad', "the planner bound the thread")
    _only_mom(pid, 'planner subject on a thread mission')


def scenario_planner_subject_action_narrows_a_manual_missions_wrapper():
    _fresh()
    mid = missions.launch('plan the surprise party', created_by='mom')['mission_id']
    pid = _wrapper_of_mission(mid)
    check(_seen(pid) == {'mom', 'dad', 'aunt', 'kid'}, "the fixture: a manual mission's wrapper is open")
    _plan({'action': 'subject', 'kind': 'occasion', 'id': 'occ-dad'})
    missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['subject_id'] == 'occ-dad', "the planner bound the mission")
    _only_mom(pid, 'planner subject on a manual mission')


def scenario_launch_with_a_subject_is_born_narrow():
    _fresh()
    mid = missions.launch('plan the surprise party', created_by='mom', subject=('occasion', 'occ-dad'))['mission_id']
    _only_mom(_wrapper_of_mission(mid), 'launch with a subject')


def scenario_a_created_party_binds_and_narrows_the_missions_wrapper():
    _fresh()
    mid, st = _staged()
    from services import projects
    projects.adopt('mission', mid, dict(MOM))
    pid = _wrapper_of_mission(mid)
    check(storage.get_project(pid)['audience'] == 'household' and 'dad' in _seen(pid), "the fixture: an open wrapper")
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"ran: {res}")
    check(missions.subject_of(storage.get_mission(mid))[0] == 'occasion', "the created party became the subject")
    row = storage.get_project(pid)
    check(_seen(pid) == {'mom', 'dad'}, f"the parents-only party it created narrowed the wrapper to the parents: {_seen(pid)} {row}")
    check(not access.project_visible(row, access.HOUSE), "and the house no longer reads it")


def scenario_a_created_party_on_a_thread_origin_mission_narrows_the_threads_wrapper():
    """planned._bind_created has two branches (planned.py:999): the mission's own subject, and, for a
    mission that came from a thread, the THREAD's. This is the second, driven through run_stage."""
    _fresh()
    from services import threads, planned
    from test_planned_missions import _interviewed, _plan_of, ROWS, STAGES
    tid = threads.create(title='Birthday errands', owner_member_id='mom', created_by='mom')
    pid = _wrapper_of_thread(tid)
    check(storage.get_project(pid)['audience'] == 'household' and 'dad' in _seen(pid) and 'aunt' in _seen(pid),
          "the fixture: the thread's open household wrapper")
    mid = _mission(created_by='mom', origin=tid)
    _interviewed(mid, template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = _plan_of(mid)['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"approved: {res}")
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': ROWS})
    _step(mid)
    st = _plan_of(mid)['stages'][0]
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"ran: {res}")
    thread = storage.get_thread(tid)
    check(thread['subject_kind'] == 'occasion' and not storage.get_mission(mid).get('subject_kind'),
          f"the created party became the THREAD's subject, not the mission's: {thread.get('subject_kind')}")
    check(_seen(pid) == {'mom', 'dad'} and not access.project_visible(storage.get_project(pid), access.HOUSE),
          f"so the thread's wrapper narrowed to the parents (the party is parents-only): {_seen(pid)} {storage.get_project(pid)}")


def scenario_a_person_retargeting_narrows_and_unlinking_never_widens():
    _fresh()
    from services import threads
    tid = threads.create(title='Surprise', owner_member_id='mom', created_by='mom')
    pid = _wrapper_of_thread(tid)
    res = situations.act('thread', tid, 'subject', option_id='subject', payload={'kind': 'occasion', 'id': 'occ-dad'}, actor=dict(MOM))
    check(res['status'] == 'success', f"retargeted: {res}")
    _only_mom(pid, 'a person linking a thread')
    narrowed = storage.get_project(pid)
    res = situations.act('thread', tid, 'subject', option_id='subject', payload={'clear': True}, actor=dict(MOM))
    check(res['status'] == 'success' and not storage.get_thread(tid).get('subject_kind'), f"unlinked: {res}")
    again = storage.get_project(pid)
    check(again['audience'] == narrowed['audience'] and again['shared_with'] == narrowed['shared_with'] and _seen(pid) == {'mom'},
          f"unlinking never widens the project: {again}")
    mid = missions.launch('another plan', created_by='mom')['mission_id']
    mpid = _wrapper_of_mission(mid)
    res = situations.act('mission', mid, 'subject', option_id='subject', payload={'kind': 'occasion', 'id': 'occ-dad'}, actor=dict(MOM))
    check(res['status'] == 'success', f"retargeted: {res}")
    _only_mom(mpid, 'a person linking a mission')


def scenario_programs_have_no_subject_writer():
    """Recorded so Task 3 does not look for one: nothing sets subject_* on a program."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    hits = []
    for path in [root / 'main.py'] + sorted((root / 'services').glob('*.py')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        for m in re.finditer(r"update_program\([^)]*subject_(?:kind|id|history)", text):
            hits.append(f'{path.name}: {m.group(0)[:80]}')
    check(not hits, f"a program subject writer exists now; add its narrow_on_bind call and a test: {hits}")


# --- plans carry the list ---------------------------------------------------------

STAGES = [{'id': 's1', 'kind': 'work', 'title': 'Find a cake bakery', 'why': 'nearby', 'goal': 'two bakeries', 'step_budget': 2, 'makes': ['bakeries']}]
STEPS = [{'id': 'p1', 'title': 'Order the cake', 'owner': 'mom'}]


def _plan_project(audience='private', listed=('aunt',)):
    return {'title': 'Surprise party', 'goal': 'A party Dad does not know about', 'done_when': 'He walks in',
            'owner': 'mom', 'audience': audience, 'shared_with': list(listed)}


def _drive_to_proposal(mid, project):
    _plan({'action': 'interview', 'questions': [{'key': 'who', 'ask': 'Who is coming?', 'kind': 'text'}]})
    missions.step(storage.get_mission(mid))
    from services import planned
    planned.answer_plan(mid, {'who': 'family'}, dict(MOM))
    _plan({'action': 'plan', 'project': project, 'steps': STEPS, 'stages': STAGES})
    missions.step(storage.get_mission(mid))
    return storage.get_mission(mid)


def _check_preview(mid, listed, how):
    mission = storage.get_mission(mid)
    proposed = mission['plan']['project']
    check(proposed['audience'] == 'private' and set(proposed['shared_with']) == set(listed),
          f"{how}: the proposal keeps the list, owner added: {proposed}")
    card = missions.ask_card(mission)
    check(card and card['ask'] == 'plan' and 'project' not in card and 'Surprise party' not in str(card),
          f"{how}: the chat card is drawn for the house-class reader, so a private proposal's words stay out of it: {card}")
    check(access.record_view('mission', mission, dict(DAD)) is None and access.record_view('mission', mission, dict(KID)) is None,
          f"{how}: Dad and the child do not read a mission about a project they are not on")
    check(access.record_view('mission', mission, dict(AUNT)) == 'full' and access.record_view('mission', mission, dict(MOM)) == 'full',
          f"{how}: the people on the list do")


def scenario_a_plans_list_survives_preview_approval_reshape_and_a_lost_claim():
    _fresh()
    from services import planned
    mid = missions.launch('plan the surprise party', created_by='mom')['mission_id']
    home = _wrapper_of_mission(mid)
    mission = _drive_to_proposal(mid, _plan_project())
    check(mission['plan']['state'] == 'proposed', f"proposed: {mission['plan'].get('state')}")
    _check_preview(mid, {'aunt', 'mom'}, 'wrapper plan')
    rev = mission['plan']['rev']

    def lost(*args, **kwargs):
        raise RuntimeError('the process died before the write landed')
    real = planned._complete_approval
    planned._complete_approval = lost
    try:
        try:
            planned.approve_plan(mid, rev, dict(MOM))
        except RuntimeError:
            pass
    finally:
        planned._complete_approval = real
    plan = storage.get_mission(mid)['plan']
    check(plan['state'] == 'approving', f"the claim is persisted: {plan['state']}")
    check(set(plan['approval']['reshape']['shared_with']) == {'aunt', 'mom'} and plan['approval']['reshape']['audience'] == 'private',
          f"and its intent carries the list: {plan['approval']}")
    check(storage.get_project(home).get('wrapped_from') and storage.get_project(home)['audience'] == 'household',
          "nothing landed on the wrapper yet")
    for round_ in (1, 2):
        planned.reconcile()
        project = storage.get_project(home)
        check(project['audience'] == 'private' and set(project['shared_with']) == {'aunt', 'mom'} and not project.get('wrapped_from'),
              f"reconcile {round_}: the wrapper became the plan's project with its list: {project}")
        check(_seen(home) == {'mom', 'aunt'}, f"reconcile {round_}: Dad and the child are out: {_seen(home)}")
    check(len(storage.get_projects()) == 1, "never a second project")


def scenario_a_plans_list_survives_into_a_new_project():
    _fresh()
    mid = _mission(created_by='mom')
    _drive_to_proposal(mid, _plan_project(listed=('aunt', 'kid')))
    _check_preview(mid, {'aunt', 'kid', 'mom'}, 'new-project plan')
    rev = storage.get_mission(mid)['plan']['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"approved: {res}")
    made = [p for p in storage.get_projects() if p.get('origin_mission_id') == mid]
    check(len(made) == 1, f"one project came of it: {[p['title'] for p in storage.get_projects()]}")
    project = made[0]
    check(project['audience'] == 'private' and set(project['shared_with']) == {'aunt', 'kid', 'mom'}, f"with the list: {project}")
    check(_seen(project['id']) == {'mom', 'aunt', 'kid'}, f"Dad is out: {_seen(project['id'])}")


if __name__ == '__main__':
    import sys
    import traceback
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            try:
                fn()
                print('PASS', name)
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    sys.exit(1 if failed else 0)
