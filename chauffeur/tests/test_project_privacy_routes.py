"""Round-two visibility: exercise authenticated doors, not source text."""
import datetime
import json
import sys
from contextlib import ExitStack
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_project_privacy_gaps import (project, thread, program, mission, _fresh as _base_fresh,
                                      storage, subjects, missions, tools, main, MOM, DAD, AUNT)
from harness import check


def _fresh():
    _base_fresh()
    storage.programs_table.truncate()
    storage.protected_commitments_table.truncate()


def scenario_routes():
    _fresh()
    tokens = {who: {'X-Member-Token': storage.create_member_token(who)} for who in ('mom', 'dad', 'aunt')}
    errors = []
    cases = [('thread', method, suffix, body) for method, suffix, body in [
        ('patch', '', {'title': 'Changed'}), ('post', '/note', {'text': 'note'}),
        ('post', '/advance', {'next_action': 'Call'}), ('delete', '', {}),
        ('post', '/close', {}), ('post', '/draft', {}), ('post', '/photo', {}),
        ('post', '/send', {'subject': 'hi', 'body': 'hello', 'to': 'vendor@example.com'}),
        ('post', '/research', {'question': 'What next?'})]]
    cases += [('mission', method, suffix, body) for method, suffix, body in [
        ('get', '', {}), ('post', '/answer', {'text': 'yes'}), ('post', '/release', {'decision': 'stop'}),
        ('post', '/submit', {'decision': 'stop'}), ('post', '/verify', {'outcome': 'failed'}),
        ('delete', '', {}), ('post', '/drop', {}), ('post', '/ack', {})]]
    cases += [('program', 'post', '/approve', {})]
    from services import threads
    with ExitStack() as stack:
        stack.enter_context(patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}))
        for name in ('draft_message', 'research', 'send_drafted', 'add_photo'):
            stack.enter_context(patch.object(threads, name, return_value={'status': 'ok'}))
        for name in ('release', 'submit', 'verify'):
            stack.enter_context(patch.object(missions, name, return_value={'status': 'success'}))
        stack.enter_context(patch('services.programs.approve', return_value={'status': 'success'}))
        client = TestClient(main.app)
        for kind, method, suffix, body in cases:
            p = project()
            rid = {'thread': thread, 'mission': mission, 'program': program}[kind]('Secret record', p)
            kw = {'headers': tokens['dad']}
            if suffix == '/photo':
                kw['files'] = {'file': ('photo.png', b'fake image', 'image/png')}
            elif method not in ('get', 'delete'):
                kw['json'] = body
            response = client.request(method.upper(), f'/api/{kind}s/{rid}{suffix}', **kw)
            if response.status_code not in (403, 404):
                errors.append(f'{method} {kind}{suffix}: {response.status_code} {response.text[:100]}')
        # Every listed mutation also reaches its domain service for the
        # project owner, a different record keeper, and each household adult.
        for audience, owner, who in [('private', 'mom', 'mom'), ('private', 'aunt', 'aunt'),
                                      ('household', 'mom', 'mom'), ('household', 'mom', 'dad'),
                                      ('household', 'mom', 'aunt')]:
            for kind, method, suffix, body in cases:
                rid = {'thread': thread, 'mission': mission, 'program': program}[kind]('Allowed record', project(audience))
                if owner == 'aunt':
                    getattr(storage, 'update_' + kind)(rid, {
                        {'thread': 'owner_member_id', 'mission': 'created_by', 'program': 'member_id'}[kind]: owner})
                kw = {'headers': tokens[who]}
                if suffix == '/photo':
                    kw['files'] = {'file': ('photo.png', b'fake image', 'image/png')}
                elif method not in ('get', 'delete'):
                    kw['json'] = body
                response = client.request(method.upper(), f'/api/{kind}s/{rid}{suffix}', **kw)
                if response.status_code != 200:
                    errors.append(f'allowed {who}/{audience} {kind}{suffix}: {response.status_code} {response.text[:100]}')
        tid = thread('Secret origin', project())
        response = client.post('/api/missions/launch', headers=tokens['dad'],
                               json={'goal': 'Call', 'origin_kind': 'thread', 'origin_ref': tid})
        if response.status_code not in (403, 404):
            errors.append(f'launch origin: {response.status_code}')
        response = client.post('/api/asks', headers=tokens['dad'], json={
            'kind': 'thread', 'id': tid, 'option_id': 'ask:any', 'what': 'Call'})
        if response.status_code not in (403, 404):
            errors.append(f'ask option: {response.status_code}')
        for audience, owner, actor in [('private', 'mom', 'mom'), ('private', 'aunt', 'aunt'),
                                        ('household', 'mom', 'dad')]:
            tid = thread('Reachable', project(audience), owner)
            response = client.post(f'/api/threads/{tid}/note', headers=tokens[actor], json={'text': 'My note'})
            if response.status_code != 200:
                errors.append(f'{audience}/{owner}/{actor}: {response.text}')
        pid = program('Child keeper', project(), 'kid')
        response = client.post(f'/api/programs/{pid}/session', headers=tokens['dad'], json={'minutes': 12})
        if response.status_code != 200:
            errors.append(f'child keeper parent: {response.text}')
    check(not errors, '\n'.join(errors))


def scenario_readers_and_channels():
    _fresh()
    from services import agent_router, house_programs, study, mind
    from test_subject_hardening import _router_capture
    for audience in ('household', 'private', 'parents'):
        p = project(audience)
        thread(audience + ' tiler', p)
        program(audience + ' piano', p)
    errors = []
    for name, args in [('list_threads', {}), ('list_programs', {}),
                       ('program_progress', {'program_title': 'household piano'})]:
        result = tools.execute_tool(name, args, actor={'id': None, 'role': 'adult'})
        if 'household' not in json.dumps(result) or 'private piano' in json.dumps(result):
            errors.append(f'id-less {name}: {result}')
    group = storage.get_or_create_group(['mom', 'dad', 'kid'], 'Family')
    for name, args in [('list_programs', {}), ('program_progress', {'program_title': 'household piano'})]:
        seen, undo = _router_capture([{'message': '', 'tool_calls': [{'name': name, 'arguments': args}]},
                                      {'message': 'done', 'tool_calls': []}])
        try:
            agent_router.process_agent_request('list programs', source='family', acting_member=dict(MOM),
                                               focus_key='channel:' + group['id'])
        finally:
            undo()
        if 'household piano' not in json.dumps(seen[1:]) or 'private piano' in json.dumps(seen[1:]):
            errors.append(f'channel {name}: {seen[1:]}')
    for name, value in [('objects', house_programs.objects()), ('mind', mind.snapshot(datetime.datetime.now())),
                        ('study', study.state(None))]:
        text = json.dumps(value)
        if 'private tiler' in text or 'private piano' in text or 'parents piano' in text:
            errors.append(name + ' leaked')
    check(not errors, '\n'.join(errors))
    check(missions._match_thread('private tiler', dict(DAD)) is None, 'mission title lookup leaked')


def scenario_wall_feed_and_state():
    _fresh()
    from services import programs, house_programs
    pid = program('Secret piano', project())
    day = datetime.date.today()
    cid = storage.add_protected_commitment({'id': 'privacy-slot', 'member_id': 'mom', 'title': 'Secret piano',
        'active': True, 'days_of_week': [day.weekday()], 'time_start': '19:00', 'time_end': '19:30'})
    storage.update_program(pid, {'emissions': {'commitment_ids': [cid]},
        'phases': [{'name': 'Secret phase', 'steps': ['Secret exercise'], 'weeks': 3, 'milestone': 'Secret milestone'}]})
    storage.upsert_program_lesson(pid, {'phase_name': '', 'unit_n': 0, 'session_label': ''},
                                  {'scenes': [{'type': 'say', 'text': 'Secret lesson'}]})
    thread('Secret thread', project())
    headers = {who: {'X-Member-Token': storage.create_member_token(who)} for who in ('mom', 'dad')}
    headers['wall'] = {'X-Device-Token': storage.enrol_device_token('privacy-wall', 'Privacy test wall')}
    errors = []
    events = [e.model_dump(mode='json') for e in main._practice_events(day.isoformat(), day.isoformat())]
    if not events or events[0]['title'] != 'Busy' or 'Secret' in json.dumps(events):
        errors.append(f'shared feed: {events}')
    restored = main._project_hold_titles({'events': events}, dict(MOM))
    if 'Secret piano' not in json.dumps(restored) or 'Secret' in json.dumps(events):
        errors.append('Mom restoration/cache mutation')
    storage.set_cached_schedule({'events': events, 'assignments': {}, 'unassigned': [], 'drivers': []})
    if house_programs.session(pid) is not None or 'Secret' in json.dumps(programs.celebrations()):
        errors.append('house session/celebrations')
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        client = TestClient(main.app)
        for who in ('mom', 'dad', 'wall'):
            response = client.get('/api/practice-windows', headers=headers[who])
            if response.status_code != 200 or ('Secret piano' in response.text) != (who == 'mom'):
                errors.append(f'practice {who}: {response.text}')
            with patch.object(main, 'trigger_background_refresh'):
                response = client.get('/api/schedule', headers=headers[who])
            if response.status_code != 200 or ('Secret piano' in response.text) != (who == 'mom'):
                errors.append(f'schedule {who}: {response.status_code} {response.text[:200]}')
        check('Secret' not in json.dumps(storage.get_cached_schedule()), 'authenticated schedule polluted shared cache')
        result = tools.execute_tool('get_calendar_events', {}, actor=dict(MOM))
        check('Secret' not in json.dumps(result), 'calendar tool received private practice words')
        for path in [f'/api/programs/{pid}/lesson-scenes', f'/api/house/programs/{pid}/session',
                     '/api/programs/celebrations', '/api/study/state']:
            response = client.get(path, headers=headers['dad'])
            if response.status_code not in (200, 404) or 'Secret' in response.text:
                errors.append(f'{path}: {response.status_code} {response.text[:150]}')
            if path != '/api/study/state':
                wall = client.get(path, headers=headers['wall'])
                if wall.status_code not in (200, 404) or 'Secret' in wall.text:
                    errors.append(f'wall {path}: {wall.status_code} {wall.text[:150]}')
        response = client.post(f'/api/programs/{pid}/lesson-help', headers=headers['dad'], json={'question': 'Help'})
        if response.status_code not in (403, 404):
            errors.append(f'lesson help: {response.status_code}')
        for path in [f'/api/programs/{pid}/lesson-scenes', f'/api/house/programs/{pid}/session']:
            response = client.get(path, headers=headers['mom'])
            if response.status_code != 200 or 'Secret' not in response.text:
                errors.append(f'Mom {path}: {response.text}')
        with patch('services.model_pools.call_pool_json', return_value={'answer': 'Play it slowly.'}):
            response = client.post(f'/api/programs/{pid}/lesson-help', headers=headers['mom'], json={})
            if response.status_code != 200 or not response.json().get('answer'):
                errors.append(f'Mom lesson help: {response.text}')
    check(not errors, '\n'.join(errors))


def scenario_idless_http():
    _fresh()
    for audience in ('private', 'parents', 'household'):
        p = project(audience)
        thread(audience + ' record', p)
        mission(audience + ' record', p)
        program(audience + ' record', p)
    token = {'X-Member-Token': storage.create_member_token('mom'),
             'X-Ingress-Path': '/api/hassio_ingress/test', 'X-Hass-Is-Admin': 'true'}
    # Auth remains enforced. Simulate the legacy trusted admin's unresolved
    # application actor after the HTTP tier has authenticated the request.
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}), \
         patch.object(main, '_acting_id', return_value=None):
        client = TestClient(main.app)
        for path in ('/api/threads', '/api/missions/admin', '/api/programs', '/api/study/state'):
            response = client.get(path, headers=token)
            check(response.status_code == 200, f'{path}: {response.text}')
            check('household record' in response.text and 'private record' not in response.text
                  and 'parents record' not in response.text, f'{path} audience: {response.text[:200]}')


def scenario_mission_readers():
    _fresh()
    from services import threads, agent_router, voice_approval
    from test_mission_subject import _plan
    from test_subject_hardening import _router_capture
    from types import SimpleNamespace
    private = project()
    tid = thread('Secret tiler', private)
    before = len(storage.get_missions())
    denied = tools.execute_tool('launch_mission', {'goal': 'Call tiler', 'thread_title': 'Secret tiler'}, actor=dict(DAD))
    check(denied['status'] in ('error', 'refused') and len(storage.get_missions()) == before, 'registry launch leaked')
    allowed = tools.execute_tool('launch_mission', {'goal': 'Call tiler', 'thread_title': 'Secret tiler'}, actor=dict(MOM))
    check(allowed.get('mission_id') and storage.get_mission(allowed['mission_id'])['origin_ref'] == tid,
          f'owner launch failed: {allowed}')
    group = storage.get_or_create_group(['mom', 'dad'], 'Parents')
    before = len(storage.get_missions())
    seen, undo = _router_capture([{'message': '', 'tool_calls': [{'name': 'launch_mission',
        'arguments': {'goal': 'Call tiler', 'thread_title': 'Secret tiler'}}]}, {'message': 'done', 'tool_calls': []}])
    try:
        agent_router.process_agent_request('handle this', source='family', acting_member=dict(MOM),
                                           focus_key='channel:' + group['id'])
    finally:
        undo()
    check(len(storage.get_missions()) == before and 'No visible thread matched' in json.dumps(seen[1:]),
          'channel launch attached hidden thread')
    # Existing-work dedupe cannot announce a private thread in a group.
    with patch.object(tools, '_intent_words', return_value=['call']):
        result = tools.start_mission_for('Call tiler', acting_member=dict(MOM), focus_key='channel:' + group['id'])
    check(result.get('thread_id') != tid and 'Secret tiler' not in json.dumps(result), 'already-under-way leak')
    mid = mission('Draft something', status='running')
    _plan({'action': 'draft', 'thread_title': 'Secret tiler', 'intent': 'Ask for quote'})
    with patch.object(threads, 'draft_message') as draft:
        missions.step(storage.get_mission(mid))
        check(not draft.called, 'engine drafted from a restricted thread')
    mid = mission('Secret creatorless mission', private)
    storage.update_mission(mid, {'created_by': None})
    sent = []
    with patch.object(missions, '_post', side_effect=lambda channel, *a, **kw: sent.append(channel) or {'id': 'posted'}):
        missions._dm_person(storage.get_mission(mid), 'Secret notification')
    mom_dm = storage.get_or_create_dm(storage.ensure_argyle_member()['id'], 'mom')
    check(sent and all(ch['id'] == mom_dm['id'] for ch in sent), 'creatorless mission DM leaked to Dad')
    ctx = SimpleNamespace(verified_member=lambda: dict(MOM))
    with patch.object(voice_approval, '_enabled', return_value=True), \
         patch.object(missions, '_pending_ask') as ask:
        result = voice_approval.prepare(ctx, mid, 'release')
        check(result['status'] == 'refused' and not ask.called, 'private mission spoken to room')


def scenario_watcher_delivery():
    _fresh()
    from services import watchers, programs
    now = datetime.datetime.now().replace(hour=12)
    expected = []
    for audience in ('private', 'parents'):
        p = project(audience)
        thread(audience + ' secret thread', p)
        mission(audience + ' secret mission', p)
        program(audience + ' secret program', p)
    storage.set_app_state('watcher_notified', {})
    with patch.object(programs, 'orphaned_emissions', return_value=['gone']), \
         patch.object(programs, 'forget_emissions'), \
         patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         patch.object(watchers, 'collect_findings', side_effect=lambda when: (
             watchers._thread_stalls(when) + watchers._mission_states(when) + watchers._program_findings(when), [])), \
         patch.object(tools, '_post_chat_message', side_effect=lambda channel, sender, body, **kw: expected.append((channel, body))):
        findings = watchers._thread_stalls(now) + watchers._mission_states(now) + watchers._program_findings(now)
        check(not findings, 'restricted records became household findings')
        watchers.run_watchers(now)
        before = len(expected)
        check(before > 0, 'restricted owners lost their nudges')
        watchers.run_watchers(now)
        check(len(expected) == before, 'watcher_notified did not dedupe')
    for who in ('mom', 'dad'):
        channel = storage.get_or_create_dm(storage.ensure_argyle_member()['id'], who)
        text = '\n'.join(body for ch, body in expected if ch['id'] == channel['id'])
        for kind in ('thread', 'mission', 'program'):
            check('parents secret ' + kind in text, f'{who} lost parents {kind} nudge')
            check(('private secret ' + kind in text) == (who == 'mom'), f'{who} private {kind} nudge audience')


def scenario_watcher_quiet_rebaseline():
    _fresh()
    from services import watchers, programs
    pid = program('Secret rebaseline', project())
    now = datetime.datetime.now().replace(hour=23)
    bent = {'fits': None, 'date_moved': True, 'baseline': {'rebaselines': 1}}
    with patch.object(programs, 'orphaned_emissions', return_value=[]), \
         patch.object(programs, 'maybe_rebaseline', side_effect=[bent, None, None]), \
         patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         patch.object(watchers, 'collect_findings', side_effect=lambda when: (watchers._program_findings(when), [])), \
         patch.object(tools, '_post_chat_message') as post:
        watchers.run_watchers(now)
        check(not post.called, 'quiet-hour nudge')
        watchers.run_watchers(now + datetime.timedelta(hours=13))
        check(post.call_count == 1 and 'Secret rebaseline' in post.call_args.args[2], 'one-shot rebaseline lost overnight')
        watchers.run_watchers(now + datetime.timedelta(hours=14))
        check(post.call_count == 1, 'rebaseline repeated')


if __name__ == '__main__':
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
    sys.exit(bool(failed))
