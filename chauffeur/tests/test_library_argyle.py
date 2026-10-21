"""Task 4: child choices, library audience, and the removed creation door."""
import traceback
import copy
import threading
from unittest.mock import patch

from harness import check
from test_library_flows import (_fresh, _library, _project, _http, _runs, _library_rows,
                                _row, _stage, _choice, _interviewed, _mission, _plan, _step,
                                _staged, _waiting_checks, STAGES, ROWS, MOM)
from services import storage, planned, situations, missions, programs, library, agent_tools_v2 as tools, chat_actions


def child_stage(match=True):
    _fresh()
    lid = _library() if match else None
    project = _project('kid', audience='parents')
    mid = _interviewed(mid=_mission(created_by='kid', project_id=project['id']), template=None)
    planned.answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = storage.get_mission(mid)['plan']['rev']
    check(situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve',
                         actor=dict(MOM))['status'] == 'success', 'parent approves the stage plan')
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': ROWS})
    _step(mid)
    snap = _stage(mid)['snapshot']
    check(planned.run_stage(mid, 's1', snap, dict(MOM))['status'] == 'success', 'stage ran')
    return mid, lid


def answer_as(mid, member, opt):
    return _http(member, 'POST', f'/api/situations/mission/{mid}/act', json={
        'verb': opt['verb'], 'option_id': opt['id'], 'payload': opt['payload']})


def scenario_child_can_use_but_cannot_publish():
    mid, lid = child_stage()
    opts = _choice(mid)
    wrong = answer_as(mid, 'aunt', opts['use'])
    check(wrong.status_code == 404 and not _runs(), 'an excluded adult cannot answer')
    response = answer_as(mid, 'kid', opts['use'])
    check(response.status_code == 200 and len(_runs()) == 1 and _runs()[0]['library_id'] == lid,
          f'a child can use the match: {response.status_code} {response.text}')
    check(_row(mid, 'r2')['state'] == 'done', 'original parent approval carries the remaining work')
    answer_as(mid, 'kid', opts['use'])
    check(len(_runs()) == 1, 'child repeated Use is idempotent')
    mid, _ = child_stage()
    with patch('services.programs_curate.curate', side_effect=AssertionError('no child research')):
        response = answer_as(mid, 'kid', _choice(mid)['make_new'])
    check(response.status_code == 403 and response.json()['detail'] == library.EDIT_REFUSAL,
          f'child Make new is refused without consuming the choice: {response.text}')
    _waiting_checks(mid)
    check(not _runs() and len(_library_rows()) == 1 and _row(mid, 'r2')['state'] == 'proposed', 'no half state')
    check(answer_as(mid, 'mom', _choice(mid)['use']).status_code == 200 and len(_runs()) == 1,
          'a parent can still choose after the child refusal')
    mid, _ = child_stage(match=False)
    check(_row(mid, 'r1')['state'] == 'failed' and _row(mid, 'r1')['result']['message'] == library.EDIT_REFUSAL
          and not _runs() and not _library_rows(), 'child no-match fails without publication')


def scenario_child_gets_the_same_hand_card():
    mid, _ = child_stage()
    # Exercise real notice rendering rather than the contract fixture's post stub.
    from test_library_flows import REAL_POST
    with patch.object(missions, '_post', REAL_POST):
        missions._dm_person(storage.get_mission(mid), _row(mid, 'r1')['result']['message'])
    dm = storage.get_or_create_dm(storage.ensure_argyle_member()['id'], 'kid')
    cards = [m.get('card') for m in storage.get_channel_messages(dm['id'])]
    check(any(c and c.get('ask') == 'program_choice' and len(c['options']) == 3 for c in cards),
          'child receives the three-button hand card')


def scenario_library_list_only_names_visible_runners():
    _fresh()
    lid = _library()
    project = _project('kid', audience='private')
    storage.update_project(project['id'], {'shared_with': ['kid', 'mom']})
    run = programs.create_row({'library_id': lid, 'member_id': 'kid', 'created_by': 'mom'}, project_id=project['id'])
    check(run, 'run created')
    seen = tools.list_programs(acting_member=storage.get_member('mom'))['message']
    hidden = tools.list_programs(acting_member=storage.get_member('aunt'))['message']
    check('Learn piano' in seen and 'Kate' in seen, 'seeing viewer names the runner')
    check('Learn piano' in hidden and 'Kate' not in hidden and '1 more' in hidden,
          f'excluded viewer gets public curriculum and only a count: {hidden}')


def scenario_title_only_creation_is_refused():
    _fresh()
    try:
        programs.create_row({'title': 'Do not publish', 'member_id': 'kid', 'created_by': 'mom'})
    except ValueError as exc:
        check('library' in str(exc), 'explicit refusal')
    else:
        check(False, 'title-only compatibility door must be closed')
    check(not _runs() and not _library_rows(), 'no implicit publication')


def scenario_make_new_rolls_back_publication_with_the_run():
    _fresh()
    _library()
    mid, project = _staged()
    opt = _choice(mid)['make_new']
    before = storage.get_project(project['id'])
    real = programs.create_row

    def crash(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError('crash after the new library and run were inserted')

    with patch.object(programs, 'create_row', side_effect=crash):
        response = _http('mom', 'POST', f'/api/situations/mission/{mid}/act', raise_errors=False, json={
            'verb': opt['verb'], 'option_id': opt['id'], 'payload': opt['payload']})
    check(response.status_code == 500 and len(_library_rows()) == 1, 'new public curriculum rolls back')
    _waiting_checks(mid)
    check(storage.get_project(project['id']) == before, 'adoption rolls back too')
    check(answer_as(mid, 'mom', opt).status_code == 200 and len(_runs()) == 1 and len(_library_rows()) == 2,
          'retry creates one new curriculum and one run')


def scenario_restart_between_the_waiting_row_and_its_card():
    _fresh()
    _library()
    mid, _ = _staged()
    choice_id = _row(mid, 'r1')['result']['choice_id']
    # A crash after storing the waiting row but before publishing its ask.
    storage.mission_steps_table.remove((storage.Query().mission_id == mid) &
                                      (storage.Query().name == 'program_choice'))
    storage.update_mission(mid, {'status': 'running'})
    with patch.object(tools, 'propose_program', side_effect=AssertionError('never rerun a waiting row')):
        planned.reconcile()
    _waiting_checks(mid, choice_id)
    check(_choice(mid)['use']['payload']['choice_id'] == choice_id, 'reconstructed from the persisted row')


def scenario_a_reference_waits_without_an_explicit_needs_list():
    import test_library_flows as flows
    _fresh()
    _library()
    rows = copy.deepcopy(ROWS)
    rows[1]['needs'] = []
    rows[1]['args']['goal'] = {'$ref': 'r1', 'kind': 'program'}
    with patch.object(flows, 'ROWS', rows):
        mid, _ = _staged()
    _waiting_checks(mid)
    response = answer_as(mid, 'mom', _choice(mid)['use'])
    check(response.status_code == 200 and _row(mid, 'r2')['state'] == 'done', 'referencing row resumes')
    thread_id = _row(mid, 'r2')['result']['created'][0]['id']
    check(storage.get_thread(thread_id)['goal'] == _runs()[0]['id'], 'reference resolves to the bound run')


def scenario_standalone_proposal_keeps_a_durable_choice():
    from test_library_flows import REAL_POST
    _fresh()
    lid = _library()
    project = _project('mom', audience='private')
    mid = _mission(project_id=project['id'])
    _plan({'action': 'propose', 'tool': 'propose_program', 'summary': 'Piano for Kate', 'args': ROWS[0]['args']})
    _step(mid)
    prop = next(p for p in storage.agent_action_proposals_table.all() if p.get('origin_id') == mid)
    check(not prop.get('stage_id') and prop['status'] == 'proposed', 'ordinary mission posted a standalone proposal')
    with patch.object(missions, '_post', REAL_POST):
        response = _http('mom', 'POST', f"/api/action-proposals/{prop['id']}/act", json={'act': 'approve', 'member_id': 'mom'})
    check(response.status_code == 200 and not _runs(), f'approval waits: {response.text}')
    check(storage.get_action_proposal(prop['id'])['status'] in ('proposed', 'waiting_choice'), 'proposal is still open')
    opts = _choice(mid)
    dm = storage.get_or_create_dm(storage.ensure_argyle_member()['id'], 'mom')
    check(any((m.get('card') or {}).get('ask') == 'program_choice'
              for m in storage.get_channel_messages(dm['id'])), 'the real notice path stored a choice card')
    response = answer_as(mid, 'mom', opts['use'])
    check(response.status_code == 200, f'Use on the standalone choice: {response.text}')
    runs = _runs()
    check(len(runs) == 1 and runs[0]['library_id'] == lid and runs[0]['project_id'] == project['id'], 'one run in its mission project')
    bound = storage.get_action_proposal(prop['id'])
    check(bound['status'] == 'approved' and bound['result']['run_id'] == runs[0]['id'], 'proposal binds the run durably')
    answer_as(mid, 'mom', opts['use'])
    check(len(_runs()) == 1, 'repeated standalone answer creates nothing')


def scenario_choice_continuation_recovers_after_commit():
    for recovery in ('reconcile', 'prepare_next'):
        _fresh()
        _library()
        mid, _ = _staged()
        opt = _choice(mid)['use']
        with patch.object(planned, 'run_stage', side_effect=RuntimeError('power loss before continuation')):
            response = _http('mom', 'POST', f'/api/situations/mission/{mid}/act', raise_errors=False,
                             json={'verb': opt['verb'], 'option_id': opt['id'], 'payload': opt['payload']})
        check(response.status_code == 500 and len(_runs()) == 1 and _row(mid, 'r1')['state'] == 'done', 'answer committed before crash')
        getattr(planned, recovery)(*(() if recovery == 'reconcile' else (mid,)))
        card = missions.ask_card(storage.get_mission(mid))
        check(card and card['ask'] == 'stage' and any(o['verb'] == 'run_stage' for o in card['options']),
              f'{recovery} restores a stage approval: {card}')
        opt = next(o for o in card['options'] if o['payload'].get('decision') == 'approve')
        with patch.object(tools, 'propose_program', side_effect=AssertionError('answered row must not rerun')):
            check(answer_as(mid, 'mom', opt).status_code == 200, 'resume untouched rows')
        check(_row(mid, 'r2')['state'] == 'done' and len(_runs()) == 1, 'continuation runs once')


def scenario_recovery_itself_cannot_lose_the_continuation():
    _fresh()
    _library()
    mid, _ = _staged()
    opt = _choice(mid)['use']
    with patch.object(planned, 'run_stage', side_effect=RuntimeError('power loss')):
        _http('mom', 'POST', f'/api/situations/mission/{mid}/act', raise_errors=False,
              json={'verb': opt['verb'], 'option_id': opt['id'], 'payload': opt['payload']})
    with patch.object(planned, '_ask', side_effect=RuntimeError('power loss while restoring the ask')):
        try:
            planned.reconcile()
        except RuntimeError:
            pass
    check(_stage(mid).get('continue_after_choice') and len(_runs()) == 1, 'failed recovery retains its durable marker')
    planned.reconcile()
    card = missions.ask_card(storage.get_mission(mid))
    check(card and card['ask'] == 'stage', 'a later recovery still offers continuation')


def scenario_standalone_choice_restores_an_existing_question():
    _fresh()
    _library()
    project = _project('mom', audience='private')
    mid = _mission(project_id=project['id'])
    question = 'Which books should I look for?'
    _plan({'action': 'propose', 'tool': 'propose_program', 'summary': 'Piano for Kate', 'args': ROWS[0]['args']},
          {'action': 'ask_user', 'question': question})
    _step(mid)
    _step(mid)
    prop = next(p for p in storage.agent_action_proposals_table.all() if p.get('origin_id') == mid)
    response = _http('mom', 'POST', f"/api/action-proposals/{prop['id']}/act", json={'act': 'approve', 'member_id': 'mom'})
    check(response.status_code == 200, 'standalone approval while the mission waits')
    check(answer_as(mid, 'mom', _choice(mid)['use']).status_code == 200, 'answered the program choice')
    card = missions.ask_card(storage.get_mission(mid))
    check(card and card['question'] == question, 'the earlier mission question is actionable again')


def scenario_a_refused_continuation_offers_a_fresh_stage():
    for refusal in ({'status': 'refused', 'message': 'Approver no longer allowed'},
                    {'status': 'success', 'moved': True, 'message': 'The subject moved; look again.'}):
        _fresh()
        _library()
        mid, _ = _staged()
        with patch.object(planned, 'run_stage', return_value=refusal):
            check(answer_as(mid, 'mom', _choice(mid)['use']).status_code == 200, 'run choice succeeds')
        card = missions.ask_card(storage.get_mission(mid))
        check(card and card['ask'] == 'stage' and len(_runs()) == 1, 'refusal/move leaves a fresh actionable stage ask')


def scenario_uncertain_sibling_is_checked_after_the_choice():
    import test_library_flows as flows
    _fresh()
    _library()
    rows = copy.deepcopy(ROWS)
    rows.append({'id': 'r3', 'tool': 'create_thread', 'needs': ['r2'], 'summary': 'Needs the uncertain row',
                 'args': {'title': 'Later', 'kind': 'project'}})
    with patch.object(flows, 'ROWS', rows):
        mid, _ = _staged()
    mission = storage.get_mission(mid)
    stage = mission['plan']['stages'][0]
    stage['state'] = 'running'
    stage['rows'][1]['state'] = 'running'
    storage.update_action_proposal(stage['rows'][1]['proposal_id'], {'status': 'executing'})
    storage.update_mission(mid, {'plan': mission['plan']})
    planned.reconcile()
    check(_row(mid, 'r2')['state'] == 'uncertain', 'lost sibling is uncertain')
    check(answer_as(mid, 'mom', _choice(mid)['use']).status_code == 200, 'choice succeeds')
    card = missions.ask_card(storage.get_mission(mid))
    check(_stage(mid)['state'] == 'uncertain' and card and card['ask'] == 'stage_check', 'person must check the lost write')
    check(_row(mid, 'r3')['state'] == 'proposed' and _row(mid, 'r2')['state'] == 'uncertain', 'dependent stays untouched until the check')
    check(card['question'] == 'Please check what happened before carrying on.', 'normal uncertainty warning')


def scenario_failed_choices_stay_open():
    _fresh()
    lid = _library()
    mid, _ = _staged()
    before = copy.deepcopy(_row(mid, 'r1'))
    storage.delete_library_program(lid)
    response = answer_as(mid, 'mom', _choice(mid)['use'])
    check(response.status_code == 400 and 'Make new' in response.text and 'Not now' in response.text, 'vanished match offers alternatives')
    check(_row(mid, 'r1') == before and _row(mid, 'r2')['state'] == 'proposed', 'vanished match does not consume the choice')
    with patch.object(library, 'prepare', return_value={'status': 'error', 'message': 'Research unavailable'}):
        response = answer_as(mid, 'mom', _choice(mid)['make_new'])
    check(response.status_code == 400 and 'Research unavailable' in response.text and _row(mid, 'r1') == before,
          'curation error leaves the original choice intact')
    with patch.object(library, 'prepare', side_effect=RuntimeError('Research disconnected')):
        response = answer_as(mid, 'mom', _choice(mid)['make_new'])
    check(response.status_code == 400 and 'Research disconnected' in response.text and _row(mid, 'r1') == before,
          'curation exception is reported without consuming the choice')
    check(answer_as(mid, 'mom', _choice(mid)['make_new']).status_code == 200 and len(_runs()) == 1, 'Make new still works after failures')


def scenario_stop_and_delete_leave_no_waiting_choices():
    from test_library_flows import REAL_POST
    from services import deletion
    for action in ('stop', 'delete'):
        _fresh()
        _library()
        with patch.object(missions, '_post', REAL_POST):
            mid, _ = _staged()
        opt = _choice(mid)['use']
        proposal_id = _row(mid, 'r1')['proposal_id']
        if action == 'stop':
            check(planned.stop_plan(mid, dict(MOM))['status'] == 'success', 'stopped')
        else:
            preview = deletion.preview('mission', mid, dict(MOM))
            check(deletion.start('mission', mid, dict(MOM), preview['token'])['status'] == 'ok', 'deletion admitted')
        check(_stage(mid)['state'] != 'waiting_choice' and _row(mid, 'r1')['state'] != 'waiting_choice', 'no waiting stage/row remains')
        check(storage.get_action_proposal(proposal_id)['status'] == 'dismissed', 'waiting proposal dismissed')
        copies = [m['card'] for m in storage.chat_messages_table.all() if (m.get('card') or {}).get('mission_id') == mid
                  and (m.get('card') or {}).get('ask') == 'program_choice']
        check(copies and all(c['state'] == 'answered' and not c['options'] for c in copies), 'every stored choice card is settled')
        check(answer_as(mid, 'mom', opt).status_code != 200 and not _runs(), 'stale choice cannot create a run')
        if action == 'delete':
            for _ in range(5):
                deletion.maintain()
            check(storage.get_mission(mid) is None and storage.get_action_proposal(proposal_id) is None, 'cleanup removes mission and proposal')


def scenario_deleting_a_stage_run_does_not_mute_the_next_ask():
    from test_library_flows import REAL_POST
    from services import access, deletion
    _fresh()
    mid, _ = _staged()
    run = _runs()[0]
    check(_stage(mid)['state'] == 'done' and any(
        ref.get('kind') == 'program' and ref.get('id') == run['id']
        for ref in (_row(mid, 'r1').get('result') or {}).get('created') or []),
        'the completed stage records its created run')
    preview = deletion.preview('program', run['id'], dict(MOM))
    check(deletion.start('program', run['id'], dict(MOM), preview['token'])['status'] == 'ok', 'run deletion admitted')
    check(access.gone('program', storage.get_program(run['id']))
          and not access.gone('mission', storage.get_mission(mid)), 'the run is gone but its mission survives')
    question = 'Which music book should we look at next?'
    _plan({'action': 'ask_user', 'question': question})
    with patch.object(missions, '_post', REAL_POST):
        _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_user', 'the mission waits for its next answer')
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')
    delivered = [m for m in storage.chat_messages_table.all()
                 if m.get('channel_id') == dm['id'] and question in (m.get('body') or '')]
    check(len(delivered) == 1 and storage.message_visible(delivered[0]), 'the next ask reaches Mom in her Argyle DM')
    check(delivered[0]['card']['question'] == question
          and {'kind': 'program', 'id': run['id']} not in delivered[0].get('refs', []),
          'the actionable ask carries no ref to the deleted work')


def scenario_run_row_persists_only_the_choice_contract():
    _fresh()
    result = {'status': 'success', 'message': 'Done', 'created': [], 'choice_id': 'c', 'options': ['use'],
              'choice': {'title': 'Public'}, 'run_id': 'r', 'notice': 'A notice', 'debug': {'private': 'must not persist'}}
    made = chat_actions.create_action_proposal('create_thread', 'Test', {}, extra_allowed=missions.proposable_tools())
    with patch.object(chat_actions, '_execute', return_value=result):
        out = chat_actions.run_row(made['proposal_id'], dict(MOM), None)
    expected = {k: v for k, v in result.items() if k != 'debug'}
    check(out == expected and storage.get_action_proposal(made['proposal_id'])['result'] == expected,
          'only status/message/created and the five choice fields are persisted')


def scenario_standalone_approval_racing_taps_do_not_reopen_the_claim():
    _fresh()
    project = _project('mom', audience='private')
    mid = _mission(project_id=project['id'])
    made = chat_actions.create_action_proposal('propose_program', 'Piano for Kate', ROWS[0]['args'],
        created_by_member_id='mom', extra_allowed=missions.proposable_tools(),
        extra={'origin_kind': 'mission', 'origin_id': mid})
    pid = made['proposal_id']
    stale_ready, executing, release = threading.Event(), threading.Event(), threading.Event()
    results, errors, calls = {}, [], []
    real_run_row, real_execute = chat_actions.run_row, chat_actions._execute

    def delayed_claim(*args, **kwargs):
        if threading.current_thread().name == 'approval-b':
            # B has already read `proposed` in act_on_proposal. Let A claim it.
            stale_ready.set()
            check(executing.wait(10), 'A reached the real executor')
        return real_run_row(*args, **kwargs)

    def held_executor(*args, **kwargs):
        calls.append(threading.current_thread().name)
        if threading.current_thread().name == 'approval-a':
            executing.set()
            check(release.wait(15), 'A is released after B and C')
        return real_execute(*args, **kwargs)

    def tap(label):
        try:
            results[label] = chat_actions.act_on_proposal(pid, 'approve', storage.get_member('mom'))
        except BaseException as exc:
            errors.append(exc)

    a = threading.Thread(target=tap, args=('a',), name='approval-a', daemon=True)
    b = threading.Thread(target=tap, args=('b',), name='approval-b', daemon=True)
    with patch.object(chat_actions, 'run_row', side_effect=delayed_claim), \
            patch.object(chat_actions, '_execute', side_effect=held_executor):
        try:
            b.start()
            check(stale_ready.wait(10), 'B holds a stale proposed read')
            a.start()
            b.join(10)
            check(not b.is_alive(), 'B returns while A remains in the executor')
            after_b = storage.get_action_proposal(pid)['status']
            tap('c')
            after_c = storage.get_action_proposal(pid)['status']
        finally:
            release.set()
            if a.ident is not None:
                a.join(15)
            b.join(15)
    check(not errors and not a.is_alive() and not b.is_alive(), f'all approvals finished: {errors}')
    check(results['b']['status'] == 'error' and results['c']['status'] == 'error'
          and after_b == after_c == 'executing', f'B/C cannot reopen A: {after_b}, {after_c}, {results}')
    check(results['a']['status'] == 'success' and calls == ['approval-a'], 'only A executes the tool')
    check(len(_library_rows()) == len(_runs()) == 1, 'one library program and one run')
    check(storage.get_action_proposal(pid)['status'] == 'approved'
          and not [r for r in storage.get_mission(mid).get('program_choices') or [] if r['state'] == 'waiting_choice']
          and not missions.ask_card(storage.get_mission(mid)), 'no open choice beside the existing run')


def scenario_an_executed_standalone_failure_can_still_retry():
    _fresh()
    mid = _mission(project_id=_project('mom', audience='private')['id'])
    made = chat_actions.create_action_proposal('propose_program', 'Piano for Kate', ROWS[0]['args'],
        created_by_member_id='mom', extra_allowed=missions.proposable_tools(),
        extra={'origin_kind': 'mission', 'origin_id': mid})
    with patch.object(chat_actions, '_execute', return_value={'status': 'error', 'message': 'Research unavailable'}):
        failed = chat_actions.act_on_proposal(made['proposal_id'], 'approve', storage.get_member('mom'))
    check(failed['status'] == 'error' and storage.get_action_proposal(made['proposal_id'])['status'] == 'proposed',
          'a call that actually executed and failed remains retryable')
    retried = chat_actions.act_on_proposal(made['proposal_id'], 'approve', storage.get_member('mom'))
    check(retried['status'] == 'success' and len(_library_rows()) == len(_runs()) == 1, 'one successful retry')


def scenario_cancellation_preserves_an_earlier_use_outcome():
    import test_library_flows as flows
    from test_library_flows import REAL_POST
    from services import deletion
    for action in ('stop', 'delete'):
        _fresh()
        _library()
        rows = [copy.deepcopy(ROWS[0]), {**copy.deepcopy(ROWS[0]), 'id': 'r2'}]
        with patch.object(flows, 'ROWS', rows), patch.object(missions, '_post', REAL_POST):
            mid, _ = _staged()
            check(answer_as(mid, 'mom', _choice(mid)['use']).status_code == 200, 'first choice answered Use')
        check(_row(mid, 'r2')['state'] == 'waiting_choice', 'second choice is still open')
        before = {m['id']: copy.deepcopy(m['card']) for m in storage.chat_messages_table.all()
                  if (m.get('card') or {}).get('mission_id') == mid
                  and (m.get('card') or {}).get('ask') == 'program_choice'}
        used = {key: card for key, card in before.items() if card.get('outcome') == 'Use'}
        pending = [key for key, card in before.items() if card.get('state') == 'open']
        check(used and pending, 'stored answered and open copies coexist')
        if action == 'stop':
            check(planned.stop_plan(mid, dict(MOM))['status'] == 'success', 'stopped')
        else:
            preview = deletion.preview('mission', mid, dict(MOM))
            check(deletion.start('mission', mid, dict(MOM), preview['token'])['status'] == 'ok', 'deletion admitted')
        check(all(storage.get_chat_message(key)['card'] == card for key, card in used.items()),
              f'{action} preserves the previous Use card exactly')
        check(all(storage.get_chat_message(key)['card'].get('outcome') == 'Stopped' for key in pending),
              f'{action} settles the choice that was still waiting')


def scenario_reconcile_does_not_interrupt_a_live_choice_continuation():
    from test_library_flows import POSTS
    _fresh()
    _library()
    mid, _ = _staged()
    continue_real = planned._continue_program_choice
    observed = []

    def reconcile_in_the_gap(mission_id, stage_id):
        check(_row(mid, 'r1')['state'] == 'done' and _stage(mid).get('continue_after_choice'), 'answer has committed')
        before = len(POSTS)
        planned.reconcile()
        observed.extend(p for p in POSTS[before:] if (p.get('card') or {}).get('ask') == 'stage')
        return continue_real(mission_id, stage_id)

    with patch.object(planned, '_continue_program_choice', side_effect=reconcile_in_the_gap):
        check(answer_as(mid, 'mom', _choice(mid)['use']).status_code == 200, 'choice and continuation succeed')
    check(not observed and _row(mid, 'r2')['state'] == 'done', 'no stray stage DM during a live continuation')
    check((mid, 's1') not in planned._active_stages, 'live continuation releases its claim')


# --- Task 7: the brief through the waiting choice, and the DM course card -------------------

BRIEF = {'notes': 'songs over drills', 'based_on': 'Piano Adventures'}


def _brief_rows():
    rows = copy.deepcopy(ROWS)
    rows[0]['args'].update(BRIEF)
    return rows


def scenario_make_new_curates_from_the_brief():
    import json
    import test_library_flows as flows
    from test_library_flows import SECRET, CURATED
    from services import programs_curate
    _fresh()
    _library()
    project = _project('mom', audience='private')
    res = tools.propose_program('Learn piano', for_member_name='Kate', brief=dict(BRIEF),
                                acting_member=dict(MOM), project_id=project['id'])
    check(res['status'] == 'waiting_choice' and res['choice'].get('brief', {}).get('based_on') == 'Piano Adventures'
          and res['choice']['brief'].get('notes') == 'songs over drills', f'the brief rides on the choice: {res}')
    refused = tools.propose_program('Learn piano', for_member_name='Kate', brief={'notes': 'lose 10 kg by June'},
                                    acting_member=dict(MOM), project_id=project['id'])
    check(refused['status'] == 'error' and not _runs(), f'a body target in the brief is refused before any choice: {refused}')
    with patch.object(flows, 'ROWS', _brief_rows()):
        mid, _ = _staged()
    stored = _row(mid, 'r1')['result']['choice']
    check(stored.get('brief', {}).get('based_on') == 'Piano Adventures', f'the planner row persists the brief: {stored}')
    calls = []

    def curate(*a, **k):
        calls.append((a, k))
        return json.loads(json.dumps(CURATED))
    with patch.object(programs_curate, 'curate', curate):
        response = answer_as(mid, 'mom', _choice(mid)['make_new'])
    check(response.status_code == 200 and len(_runs()) == 1, f'Make new made one run: {response.text}')
    check(len(calls) == 1 and (calls[0][1].get('brief') or {}).get('based_on') == 'Piano Adventures'
          and (calls[0][1].get('brief') or {}).get('notes') == 'songs over drills',
          f'Make new curates from the brief, not the title alone: {calls}')
    check(SECRET not in repr(calls), 'the private starting point never reaches the curator')


def _course_cards(member_id='mom'):
    dm = storage.get_or_create_dm(storage.ensure_argyle_member()['id'], member_id)
    return [m for m in storage.get_channel_messages(dm['id']) if (m.get('card') or {}).get('kind') == 'program_course']


def scenario_dm_course_card_binds_the_run():
    from test_library_flows import REAL_POST
    _fresh()
    lid = _library()
    with patch.object(missions, '_post', REAL_POST):
        mid, project = _staged()
        check(not _course_cards(), 'no course card before the choice is answered')
        opts = _choice(mid)
        response = answer_as(mid, 'mom', opts['use'])
        check(response.status_code == 200, f'Use: {response.text}')
        answer_as(mid, 'mom', opts['use'])
    runs = _runs()
    cards = _course_cards()
    check(len(runs) == 1 and len(cards) == 1, f'one run and one course card, even after a repeated answer: {runs} {cards}')
    message, card = cards[0], cards[0]['card']
    refs = [{k: r.get(k) for k in ('kind', 'id')} for r in message.get('refs') or []]
    check({'kind': 'library', 'id': lid} in refs and {'kind': 'program', 'id': runs[0]['id']} in refs,
          f'the card refers to the library row and the run: {refs}')
    check(card['setup'] == {'run_id': runs[0]['id'], 'project_id': project['id']} and card['library_id'] == lid
          and card['for_name'] == 'Kate', f"Set it up binds the run Use made, never a new one: {card}")
    check(card['title'] == 'Learn piano' and card['phases'] == [{'name': 'Foundations', 'lessons': 2}]
          and card['source_line'] == library.source_line(storage.get_library_program(lid)),
          f'title, source line and phases with lesson counts: {card}')
    check(storage.message_visible(message), 'the card passes the delivery re-check')
    _fresh()
    with patch.object(missions, '_post', REAL_POST):
        mid, project = _staged()
    runs = _runs()
    cards = _course_cards()
    check(len(runs) == 1 and len(cards) == 1 and cards[0]['card']['setup']['run_id'] == runs[0]['id']
          and cards[0]['card']['library_id'] == runs[0]['library_id'],
          f'a no-match curation posts the card for the run it made: {cards}')


COURSE = {'kind': 'program_course', 'library_id': 'lib<1>', 'run_id': 'run1', 'project_id': 'proj1',
          'for_member_id': 'kid', 'for_name': 'Kate', 'title': 'Learn <piano>', 'source_line': 'Based on Faber · cited',
          'phases': [{'name': 'Foundations', 'lessons': 2}, {'name': 'Songs', 'lessons': 1}],
          'setup': {'run_id': 'run1', 'project_id': 'proj1'}}

COURSE_HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const [,, chunkPath, sitPath, cardPath] = process.argv;
const dom = new JSDOM('<!doctype html><body></body>');
global.window = dom.window; global.document = dom.window.document;
var selectedMemberId = 'mom';
function myRole() { return 'parent'; }
function mfEscape(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
eval(fs.readFileSync(chunkPath, 'utf8'));
eval(fs.readFileSync(sitPath, 'utf8'));
const card = JSON.parse(fs.readFileSync(cardPath, 'utf8'));
const calls = [];
window.chfLibrary = { open: (id, o) => calls.push(o ? ['open', id, o] : ['preview', id]) };
window.chfProgramSetup = { open: o => calls.push(['setup', o]) };
window.fetch = () => { calls.push(['fetch']); return Promise.reject(new Error('no fetch')); };
const html = renderCard(card);
document.body.innerHTML = html;
document.querySelector('[data-course-preview]').click();
document.querySelector('[data-course-setup]').click();
document.querySelector('[data-course-steer]').click();
const mine = renderCard({...card, for_member_id: 'mom', for_name: 'Mom'});
console.log(JSON.stringify({html, mine, calls}));
"""


def scenario_course_card_renders_and_its_buttons_open():
    import json
    import os
    import shutil
    import subprocess
    import tempfile
    node = shutil.which('node')
    scratch = tempfile.mkdtemp(prefix='chauffeur_course_card_')
    if not node or subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, cwd=scratch).returncode != 0:
        print('  skip  node/jsdom not available')
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, 'templates', 'app.html'), encoding='utf-8').read()
    start = src.index('function renderCard(card)')
    files = {'chunk.js': src[start:src.index('async function answerAsk(', start)], 'harness.js': COURSE_HARNESS,
             'card.json': json.dumps(COURSE)}
    for name, text in files.items():
        with open(os.path.join(scratch, name), 'w', encoding='utf-8') as f:
            f.write(text)
    proc = subprocess.run([node, os.path.join(scratch, 'harness.js'), os.path.join(scratch, 'chunk.js'),
                           os.path.join(root, 'static', 'situations.js'), os.path.join(scratch, 'card.json')],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=scratch, timeout=120)
    check(proc.returncode == 0, f'render threw:\n{proc.stderr[-1500:]}')
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    html = out['html']
    check('Learn &lt;piano&gt;' in html and '<piano>' not in html, f'the title is escaped: {html}')
    check('Based on Faber · cited' in html and 'Foundations' in html and '2 lessons' in html and '1 lesson' in html,
          f'source line and phases with lesson counts: {html}')
    check('Preview' in html and 'Set it up for Kate' in html and '>Steer<' in html, f'the three buttons: {html}')
    check(out['calls'] == [['preview', 'lib<1>'], ['setup', {'runId': 'run1', 'projectId': 'proj1'}],
                           ['open', 'lib<1>', {'steer': True}]],
          f'Preview opens the library program; Set it up opens the sheet on the run, nothing posted; '
          f'Steer opens the course page with its Steer box: {out["calls"]}')
    check('Set it up for Mom' not in out['mine'] and 'Set it up' in out['mine'], f'your own program: Set it up: {out["mine"]}')


if __name__ == '__main__':
    cases = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
    failures = 0
    for case in cases:
        try:
            case()
            print('PASS', case.__name__)
        except Exception:
            failures += 1
            print('FAIL', case.__name__)
            traceback.print_exc()
    print(f'{len(cases) - failures}/{len(cases)} scenarios passed')
    raise SystemExit(bool(failures))
