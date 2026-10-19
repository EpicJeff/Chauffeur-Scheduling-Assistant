"""Task 4: child choices, library audience, and the removed creation door."""
import traceback
import copy
from unittest.mock import patch

from harness import check
from test_library_flows import (_fresh, _library, _project, _http, _runs, _library_rows,
                                _row, _stage, _choice, _interviewed, _mission, _plan, _step,
                                _staged, _waiting_checks, STAGES, ROWS, MOM)
from services import storage, planned, situations, missions, programs, library, agent_tools_v2 as tools


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
    check(response.status_code == 200 and _row(mid, 'r1')['state'] == 'failed'
          and _row(mid, 'r1')['result']['message'] == library.EDIT_REFUSAL,
          f'child Make new fails cleanly: {response.text}')
    check(not _runs() and len(_library_rows()) == 1 and _row(mid, 'r2')['state'] == 'skipped', 'no half state')
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
