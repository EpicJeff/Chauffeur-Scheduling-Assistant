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
    storage.update_project(home, {'audience': 'private', 'shared_with': ['aunt', 'mom']})
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
    check(not {'owner_member_id', 'audience', 'shared_with'} & plan['approval']['reshape'].keys(),
          f"the reshape intent carries content only: {plan['approval']}")
    # An old persisted reshape may still contain planner-selected people.
    plan['approval']['reshape'].update(owner_member_id='dad', audience='household', shared_with=[])
    storage.update_mission(mid, {'plan': plan})
    check(storage.get_project(home).get('wrapped_from') and storage.get_project(home)['audience'] == 'private',
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


def scenario_plan_approval_cannot_change_wrapper_people_even_for_a_parent():
    from services import projects
    for proposed_owner, listed in (('aunt', ('mom', 'dad', 'aunt', 'kid')), ('mom', ('mom', 'dad', 'aunt'))):
        _fresh()
        mid = missions.launch('plan a family gathering', created_by='mom')['mission_id']
        pid = _wrapper_of_mission(mid)
        storage.update_project(pid, {'audience': 'private', 'shared_with': ['mom', 'dad', 'aunt', 'kid']})
        proposal = _plan_project(listed=listed)
        proposal['owner'] = proposed_owner
        mission = _drive_to_proposal(mid, proposal)
        before = storage.get_project(pid)
        check(projects.can_act(before, dict(AUNT)) and not projects.can_edit_audience(before, dict(AUNT)),
              'Aunt is listed and can act, but cannot change the audience')
        rev = mission['plan']['rev']
        check(projects.can_edit_audience(before, dict(DAD)), 'Dad is a parent who sees the before-row')
        for actor in (AUNT, DAD):
            # Each actor approves the same pending plan against the same wrapper.
            storage.update_project(pid, before)
            storage.update_mission(mid, mission)
            res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve',
                                 payload={}, actor=dict(actor))
            check(res['status'] == 'success', f'{actor["id"]} may approve content: {res}')
            after = storage.get_project(pid)
            check(all(after[k] == before[k] for k in ('owner_member_id', 'audience', 'shared_with'))
                  and not after.get('wrapped_from'), f'approval preserves the wrapper people exactly: {after}')


def scenario_kates_surprise_wrapper_stays_hidden_from_dad_on_approval_and_replay():
    from unittest.mock import patch
    from services import planned, projects
    for interrupted in (False, True):
        _fresh()
        mid = missions.launch('plan Dad surprise', created_by='mom')['mission_id']
        pid = _wrapper_of_mission(mid)
        storage.update_project(pid, {'owner_member_id': 'kid', 'audience': 'private',
                                     'shared_with': ['kid', 'mom']})
        proposal = _plan_project()
        proposal.update(owner='kid', audience='private')
        proposal.pop('shared_with')  # The planner never picks people.
        mission = _drive_to_proposal(mid, proposal)
        preview = mission['plan']['project']
        check(preview['owner'] == 'kid' and preview['shared_with'] == ['kid', 'mom']
              and preview['audience_label'] == projects.audience_label(storage.get_project(pid)),
              f'preview names the preserved audience: {preview}')
        if interrupted:
            with patch.object(planned, '_complete_approval', side_effect=RuntimeError('lost write')):
                try:
                    planned.approve_plan(mid, mission['plan']['rev'], dict(MOM))
                except RuntimeError:
                    pass
            check(storage.get_mission(mid)['plan']['state'] == 'approving', 'a real interrupted claim')
            planned.reconcile()
        else:
            res = planned.approve_plan(mid, mission['plan']['rev'], dict(MOM))
            check(res['status'] == 'success', f'Mom approves Kate plan: {res}')
        for replay in (False, True):
            if replay:
                planned.reconcile()
            project = storage.get_project(pid)
            check(project['owner_member_id'] == 'kid' and project['audience'] == 'private'
                  and project['shared_with'] == ['kid', 'mom'], f'people preserved exactly: {project}')
            check(project['steps'] and not projects.view(project, dict(DAD))
                  and projects.view(project, dict(MOM))['steps'],
                  f'Dad sees neither project nor steps after approval/replay ({interrupted=}, {replay=})')
            check(access.record_view('mission', storage.get_mission(mid), dict(DAD)) is None,
                  'Dad cannot read the reshaped mission either')


def scenario_binding_narrows_when_only_the_house_reader_is_lost():
    from services import threads
    _fresh()
    tid = threads.create(title='Family surprise', owner_member_id='kid', created_by='kid')
    pid = _wrapper_of_thread(tid)
    before = _seen(pid)
    check(before == {'mom', 'dad', 'aunt', 'kid'}
          and access.project_visible(storage.get_project(pid), access.HOUSE), 'starts open to all humans and house')
    storage.save_occasion({'id': 'all-humans', 'title': 'Family surprise', 'audience': 'shared',
                           'shared_with': ['aunt', 'kid']})
    res = situations.act('thread', tid, 'subject', option_id='subject',
                         payload={'kind': 'occasion', 'id': 'all-humans'}, actor=dict(MOM))
    check(res['status'] == 'success', f'bound through the real subject writer: {res}')
    check(_seen(pid) == before and not access.project_visible(storage.get_project(pid), access.HOUSE),
          'same human viewers, but losing HOUSE still narrows the wrapper')


def scenario_plan_preview_renders_the_named_audience_in_the_shared_builder():
    import json
    from pathlib import Path
    import subprocess
    _fresh()
    mid = missions.launch('plan Dad surprise', created_by='mom')['mission_id']
    storage.update_project(_wrapper_of_mission(mid), {'owner_member_id': 'kid', 'audience': 'private',
                                                      'shared_with': ['kid', 'mom']})
    mission = _drive_to_proposal(mid, {'title': 'Surprise', 'goal': 'Party', 'done_when': 'Ready',
                                     'owner': 'kid', 'audience': 'private'})
    script = """const fs = require('fs'); global.window = {};
eval(fs.readFileSync('static/situations.js', 'utf8'));
console.log(window.Situations.planStepperHtml(JSON.parse(fs.readFileSync(0, 'utf8'))));"""
    result = subprocess.run(['node', '-e', script], input=json.dumps(mission['plan']),
                            capture_output=True, text=True, encoding='utf-8',
                            cwd=Path(__file__).resolve().parents[1], timeout=30)
    check(result.returncode == 0, f'the real JS builder runs: {result.stderr}')
    label = mission['plan']['project']['audience_label']
    check(label in result.stdout and 'private' not in result.stdout,
          f'the preview uses the named audience, not its raw enum: {result.stdout}')


def scenario_child_manual_mission_fallback_uses_the_default_private_list():
    _fresh()
    mid = missions.launch('plan the birthday', created_by='kid', subject=('occasion', 'o1'))['mission_id']
    project = storage.get_project(_wrapper_of_mission(mid))
    check(project['owner_member_id'] == 'kid' and project['audience'] == 'private',
          f'the child keeps the fallback wrapper: {project}')
    check(set(project['shared_with']) == {'kid', 'mom', 'dad'}
          and _seen(project['id']) == {'kid', 'mom', 'dad'},
          f'no explicit list was supplied, so both active parents join the child: {project}')
    check(all(access.record_view('mission', storage.get_mission(mid), dict(m)) == access.FULL
              for m in (MOM, DAD)), 'the parents can actually read the child-created mission')


def scenario_narrowing_errors_preserve_subject_writer_bookkeeping():
    from unittest.mock import patch
    from services import threads, planned, project_audience

    def must_raise(action):
        with patch.object(project_audience, 'narrow_on_bind', side_effect=RuntimeError('narrowing failed')) as narrow:
            try:
                action()
            except RuntimeError as exc:
                check(str(exc) == 'narrowing failed' and narrow.call_count == 1,
                      'the narrowing error propagates to the caller')
            else:
                check(False, 'narrowing errors must not be swallowed')

    for target_kind in ('thread', 'mission'):
        _fresh()
        tid = threads.create(title='Party errands', owner_member_id='mom', created_by='mom')
        mid = _mission(origin=tid if target_kind == 'thread' else None)
        sid = tid if target_kind == 'thread' else mid
        proposal_id = storage.add_action_proposal({'tool': 'add_occasion', 'payload': {}, 'status': 'proposed'})
        storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_occasion',
                                       'result_json': {'proposal_id': proposal_id}})
        before_rev = (situations.load(target_kind, sid) or {}).get('rev') or 0
        refreshed = []
        with patch.object(situations, 'request_refresh', side_effect=lambda *args: refreshed.append(args)):
            must_raise(lambda: situations.act(target_kind, sid, 'subject', option_id='subject',
                       payload={'kind': 'occasion', 'id': 'occ-dad'}, actor=dict(MOM)))
        check(any(s['name'] == 'subject_changed' for s in storage.get_mission_steps(mid)),
              f'{target_kind} retarget records the subject-change note before narrowing')
        check(storage.get_action_proposal(proposal_id)['status'] == 'dismissed',
              f'{target_kind} retarget invalidates the stale proposal before narrowing')
        check(situations.load(target_kind, sid)['rev'] > before_rev and refreshed == [(target_kind, sid)],
              f'{target_kind} retarget bumps and refreshes the situation before narrowing')

    for thread_origin in (False, True):
        _fresh()
        from test_planned_missions import _approved
        mid = _approved(stages=STAGES)
        if thread_origin:
            tid = threads.create(title='Party errands', owner_member_id='mom', created_by='mom')
            storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
        planned.prepare_next(mid)
        check(planned.running_work(storage.get_mission(mid)),
              'the fixture has running work to pause when its subject changes')
        _plan({'action': 'subject', 'kind': 'occasion', 'id': 'occ-dad'})
        must_raise(lambda: _step(mid))
        check(any(s['name'] == 'subject' for s in storage.get_mission_steps(mid)),
              f'planner subject ({thread_origin=}) records its note before narrowing')
        check(not planned.running_work(storage.get_mission(mid))
              and storage.get_mission(mid)['status'] == 'waiting_user',
              f'planner subject ({thread_origin=}) pauses bound work before narrowing')

    for thread_origin in (False, True):
        _fresh()
        mid, stage = _staged()
        if thread_origin:
            tid = threads.create(title='Party errands', owner_member_id='mom', created_by='mom')
            storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
        must_raise(lambda: planned.run_stage(mid, stage['id'], stage['snapshot'], dict(MOM)))
        current = storage.get_mission(mid)
        saved_stage = current['plan']['stages'][0]
        check(saved_stage['state'] == 'done' and all(r['state'] == 'done' for r in saved_stage['rows']),
              f'created subject ({thread_origin=}) finishes the rows and stage before narrowing')
        check(current['status'] == 'running' and (mid, stage['id']) not in planned._active_stages,
              f'created subject ({thread_origin=}) completes mission bookkeeping and releases the claim')


def scenario_later_stage_rows_use_the_already_narrowed_project():
    from unittest.mock import patch
    from services import planned, projects
    from test_planned_missions import ROWS

    for thread_origin in (False, True):
        _fresh()
        rows = [ROWS[0], {'id': 'r2', 'tool': 'create_thread', 'args': {'title': 'Party arrangements'},
                         'summary': 'Discuss the party', 'needs': ['r1']}]
        mid, stage = _staged(rows=rows)
        if thread_origin:
            from services import threads
            tid = threads.create(title='Party errands', owner_member_id='mom', created_by='mom')
            storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
        projects.adopt('mission', mid, dict(MOM))
        pid = _wrapper_of_mission(mid)
        check(storage.get_project(pid)['audience'] == 'household', 'the wrapper starts household')
        create = tools.TOOL_HANDLERS['create_thread']
        created = []

        def create_after_binding(args, actor=None):
            check(storage.get_project(pid)['audience'] == 'parents',
                  'the first row narrows the project before the later row executes')
            result = create(args, actor=actor)
            thread = storage.get_thread(result['id'])
            created.append(thread)
            check(thread['project_id'] == pid
                  and storage.get_project(thread['project_id'])['audience'] == 'parents',
                  'the later thread is created inside the already-narrowed home')
            return result

        with patch.dict(tools.TOOL_HANDLERS, {'create_thread': create_after_binding}):
            result = planned.run_stage(mid, stage['id'], stage['snapshot'], dict(MOM))
        check(result['status'] == 'success' and len(created) == 1,
              f'the stage really creates its later thread: {result}')


def scenario_a_narrowing_error_does_not_mask_a_stage_error():
    from unittest.mock import patch
    from services import planned, projects, project_audience

    _fresh()
    mid, stage = _staged()
    stage_error = ValueError('stage bookkeeping failed')
    with patch.object(project_audience, 'narrow_on_bind', side_effect=RuntimeError('narrowing failed')), \
         patch.object(projects, 'on_stage_done', side_effect=stage_error):
        try:
            planned.run_stage(mid, stage['id'], stage['snapshot'], dict(MOM))
        except Exception as exc:
            check(exc is stage_error, f'the original stage error is preserved: {exc!r}')
        else:
            check(False, 'the stage error must propagate')
    check((mid, stage['id']) not in planned._active_stages, 'the stage claim is still released')


def scenario_household_replies_with_no_visible_recipient_age_out():
    import datetime
    from unittest.mock import patch
    from services import threads, replies, watchers

    _fresh()
    tid = threads.create(title='Old replies', owner_member_id='mom', created_by='mom')
    check(storage.get_project(_wrapper_of_thread(tid))['audience'] == 'household', 'a household home')
    now = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    old_ts = (now - datetime.timedelta(days=watchers.NOTIFIED_RETENTION_DAYS + 1)).timestamp()
    for message_id, ts in [('old', old_ts), ('recent', now.timestamp())]:
        storage.append_thread_history(tid, {'kind': 'received', 'message_id': message_id,
                                           'text': 'Reply', 'ts': ts, 'dm_pending': True})
    with patch.object(access, 'record_view', return_value=None), patch.object(replies, '_post') as post:
        check(replies.flush_pending_dms(now) == 0 and not post.called, 'hidden recipients get no reply')
    history = {h['message_id']: h for h in storage.get_thread(tid)['history'] if h.get('message_id')}
    check(not history['old']['dm_pending'] and history['recent']['dm_pending']
          and history['old']['ts'] == old_ts, 'recipientless household replies age out on their original timestamp')


def scenario_private_recipients_include_the_project_owner_and_filter_them():
    from services import projects, threads

    for audience in ('parents', 'shared', 'private'):
        _fresh()
        project = projects.create({'title': 'Aunt coordinates', 'owner_member_id': 'aunt',
                                   'audience': audience, 'shared_with': ['mom']}, dict(AUNT))['project']
        tid = threads.create(title='Arrangements', owner_member_id='mom', created_by='mom', project_id=project['id'])
        # The owner is a project viewer independently of the stored list.
        if audience == 'private':
            storage.update_project(project['id'], {'shared_with': ['mom']})
        check('aunt' in access.private_recipients('thread', storage.get_thread(tid)),
              f'{audience}: the non-parent project owner receives the record signal')
        storage.update_thread(tid, {'subject_kind': 'occasion', 'subject_id': 'occ-dad', 'subject_rev': 1})
        check('aunt' not in access.private_recipients('thread', storage.get_thread(tid)),
              f'{audience}: project ownership does not bypass the record projection')


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
