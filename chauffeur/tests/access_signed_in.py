"""HTTP and function probes for access rule section 4.1.

Expected permissions come from the spec table, never the implementation's gate.
External effects (mail, research, browser, calendar) are stubbed after authorization.
Every write starts with a fresh household.
"""
import datetime
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import access_fixture
from test_access_core import TABLE, COLS, KIND, ACT, MISSION_KEEPER_VERBS, load
from services import storage, projects, situations, programs, planned
import main

F, K = 'full', 'keeper'
PROGRAM_VERBS = ('approve', 'session', 'milestone', 'finish', 'reshape', 'pause',
                 'resume', 'drop', 'edit', 'unit')


def request(fx, col, method, path, **kwargs):
    headers = {}
    if col != 'house':
        member = fx.viewers[col]
        if member.get('status') == 'disabled':
            return None
        headers['X-Member-Token'] = storage.create_member_token(member['id'])
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app).request(method, path, headers=headers, **kwargs)


def result(r, words=False):
    if r is None or r.status_code in (401, 404):
        return None
    if r.status_code == 403:
        return 'FORBIDDEN-NOT-404'
    if not 200 <= r.status_code < 300:
        return f'HTTP {r.status_code}: {r.text[:140]}'
    return r.text if words else F


def observed(text, fx, rkey):
    if fx.secret(rkey) in str(text):
        return F
    return K if has_title(text, fx, rkey) else None


def has_title(text, fx, rkey):
    return bool(re.search(re.escape(fx.title(rkey)) + r'(?!\w)', str(text)))


def base(rkey, col):
    return dict(zip(COLS, TABLE[rkey]))[col]


def act_expected(rkey, col, verb):
    value = ACT[rkey][col]
    kind = KIND[rkey]
    if kind == 'mission' and base(rkey, col) == K and verb not in MISSION_KEEPER_VERBS:
        return None
    # Existing role gates remain in addition to record_actable.
    if col in ('kid', 'hal') and value:
        if kind == 'thread' and verb != 'photo':
            return 'FORBIDDEN-NOT-404'
        if kind == 'program' and verb == 'approve':
            return 'FORBIDDEN-NOT-404'
    return value


def project_visible(fx, rkey, col):
    # Fixture audiences, independent of production projects.can_see.
    if col == 'pat':
        return False
    if col == 'house':
        # Household projects, plus the wrapper of a HOUSE-visible thread (§2).
        return rkey in ('R5t', 'R5p', 'R12', 'R13')
    if rkey in ('R1', 'R2', 'R3', 'R7'):
        return col == 'mom'
    if rkey in ('R4', 'R11'):
        return col in ('mom', 'dad') or (rkey == 'R11' and col == 'kid')
    if rkey in ('R6', 'R8'):
        return base(rkey, col) is not None and col in ('mom', 'dad', 'kid')
    return True


def verb_for(rid):
    method, path = rid[1:]
    if path.endswith('/plan/answers'):
        return 'answer'
    if '/proposals/' in path or '/action-proposals/' in path:
        return 'approve'
    if path == '/api/asks':
        return 'ask'
    if path.endswith('/act'):
        return 'ack'
    return 'delete' if method == 'DELETE' else 'edit' if method == 'PATCH' else path.rsplit('/', 1)[-1]


def expected(rid, fx, rkey, col, value):
    if rid not in IDS:
        return value
    path = rid[-1]
    if rid[0] == 'route' and rid[1] == 'POST' and path in ('/api/threads', '/api/programs'):
        if col == 'pat':
            return None
        if path == '/api/threads' and col in ('kid', 'hal'):
            return 'FORBIDDEN-NOT-404'
        return F if project_visible(fx, rkey, col) and col in ('mom', 'dad', 'aunt') else 'FORBIDDEN-NOT-404'
    if rid[0] == 'reader':
        if path.endswith('queue_row'):
            return act_expected(rkey, col, 'run_stage')
        if path.endswith('_rows_of'):
            return F if value else None
        if path.endswith('elsewhere'):
            return K if rkey == 'R2' and col == 'aunt' else None
        if path.endswith(('view', 'piece_cards')):
            return K if value and project_visible(fx, rkey, col) else None
        return value
    if rid[1] not in ('GET',) and path != '/api/programs/lessons/sweep':
        if path == '/api/action-proposals/{proposal_id}/act' and KIND[rkey] == 'program':
            return act_expected(rkey, col, 'session')
        if KIND[rkey] == 'thread' and path in ('/api/asks/{ask_id}/sent', '/api/asks/{ask_id}/answer'):
            return F if value else None  # fixture asker may report/mark their own ask
        return act_expected(rkey, col, verb_for(rid))
    if path == '/api/projects/elsewhere':
        return K if rkey == 'R2' and col == 'aunt' else None
    if path == '/api/projects/for/{kind}/{record_id}':
        return F if value else None
    if path in ('/api/projects', '/api/projects/{project_id}', '/api/projects/{project_id}/pieces'):
        return K if value and project_visible(fx, rkey, col) else None
    if path == '/api/subjects/search':
        return K if value else None
    if path == '/api/subjects/{kind}/{sid}/situations':
        return K if value and col in ('mom', 'dad', 'aunt') else None
    if path.endswith('/shots/{name}'):
        return F if value == F else None
    if path.endswith('/channels'):
        return ('FORBIDDEN-NOT-404' if col == 'kid' else F) if value else None
    if path == '/api/action-proposals':
        return F if value == F else None  # a keeper never reads proposal words
    if path == '/api/programs/lessons/sweep' and col in ('kid', 'hal'):
        return 'FORBIDDEN-NOT-404'
    return value


# Explicit ids: adding a reader must fail the register coverage check until probed.
IDS = {
    ('route', 'GET', '/api/threads'),
    ('route', 'POST', '/api/threads'),
    ('route', 'GET', '/api/threads/{thread_id}/missions'),
    ('route', 'PATCH', '/api/threads/{thread_id}'),
    ('route', 'POST', '/api/threads/{thread_id}/note'),
    ('route', 'POST', '/api/threads/{thread_id}/advance'),
    ('route', 'DELETE', '/api/threads/{thread_id}'),
    ('route', 'POST', '/api/threads/{thread_id}/close'),
    ('route', 'POST', '/api/threads/{thread_id}/draft'),
    ('route', 'POST', '/api/threads/{thread_id}/photo'),
    ('route', 'POST', '/api/threads/{thread_id}/send'),
    ('route', 'POST', '/api/threads/{thread_id}/research'),
    ('route', 'GET', '/api/missions/admin'),
    ('route', 'GET', '/api/missions/{mission_id}'),
    ('route', 'POST', '/api/missions/launch'),
    ('route', 'POST', '/api/missions/{mission_id}/proposals/{proposal_id}/act'),
    ('route', 'GET', '/api/missions/{mission_id}/shots/{name}'),
    ('route', 'POST', '/api/missions/{mission_id}/release'),
    ('route', 'POST', '/api/missions/{mission_id}/submit'),
    ('route', 'POST', '/api/missions/{mission_id}/verify'),
    ('route', 'POST', '/api/missions/{mission_id}/plan/answers'),
    ('route', 'POST', '/api/missions/{mission_id}/answer'),
    ('route', 'DELETE', '/api/missions/{mission_id}'),
    ('route', 'POST', '/api/missions/{mission_id}/drop'),
    ('route', 'POST', '/api/missions/{mission_id}/ack'),
    ('route', 'GET', '/api/programs'),
    ('route', 'POST', '/api/programs'),
    ('route-prefix', 'POST', '/api/programs/{program_id}/'),
    ('route', 'GET', '/api/programs/{program_id}/lesson'),
    ('route', 'PUT', '/api/programs/{program_id}/lesson'),
    ('route', 'DELETE', '/api/programs/{program_id}/lesson'),
    ('route', 'POST', '/api/programs/lessons/sweep'),
    ('route', 'GET', '/api/programs/{program_id}/footprint'),
    ('route', 'GET', '/api/situations'),
    ('route', 'GET', '/api/situations/{kind}/{sid}'),
    ('route', 'GET', '/api/subjects/{kind}/{sid}/situations'),
    ('route', 'POST', '/api/situations/{kind}/{sid}/act'),
    ('route', 'POST', '/api/asks'),
    ('route', 'POST', '/api/asks/{ask_id}/answer'),
    ('route', 'GET', '/api/projects'),
    ('route', 'GET', '/api/projects/elsewhere'),
    ('route', 'GET', '/api/projects/for/{kind}/{record_id}'),
    ('route', 'GET', '/api/projects/{project_id}/pieces'),
    ('route', 'GET', '/api/projects/{project_id}'),
    ('route', 'POST', '/api/projects/{project_id}/pieces'),
    ('route', 'POST', '/api/projects/{project_id}/pieces/remove'),
    ('route', 'GET', '/api/subjects/search'),
    ('route', 'GET', '/api/subjects/{kind}/{sid}/projects'),
    ('route', 'GET', '/api/action-proposals'),
    ('route', 'POST', '/api/action-proposals/{proposal_id}/act'),
    ('reader', 'services.planned.queue_row'),
    ('reader', 'services.programs.due_asks_for'),
    ('reader', 'services.projects.elsewhere'),
    ('reader', 'services.projects.piece_cards'),
    ('reader', 'services.projects.view'),
    ('reader', 'services.situations._rows_of'),
    ('route', 'GET', '/api/asks/channels'),
    ('route', 'GET', '/api/asks/{ask_id}/channels'),
    ('route', 'POST', '/api/asks/{ask_id}/sent'),
    ('route', 'POST', '/api/asks/{ask_id}/withdraw'),
}


def read_probe(rid, fx, rkey, col):
    if col == 'house':
        return 'skip'  # signed-in door is separately asserted below
    kind, row = load(fx, rkey)
    sid, path = row['id'], rid[-1]
    if path == '/api/threads/{thread_id}/missions':
        if kind != 'mission':
            return 'skip'  # endpoint contains mission words, not the origin's words
        tid = fx.ids['R5t']
        storage.update_mission(sid, {'origin_kind': 'thread', 'origin_ref': tid})
        path = f'/api/threads/{tid}/missions'
    elif path.endswith('/shots/{name}'):
        from services import missions
        target = Path(missions.browse_dir(sid)) / 'probe.png'
        target.write_bytes(b'probe image')
        path = f'/api/missions/{sid}/shots/probe.png'
    elif path == '/api/subjects/{kind}/{sid}/situations':
        # A fixture subject already shared with everyone; do not erase the row's
        # original subject: R6/R7/R8/R10/R11/R12 test their actual binding.
        if row.get('subject_kind'):
            path = f"/api/subjects/{row['subject_kind']}/{row['subject_id']}/situations"
        else:
            storage.update_thread(sid, {'subject_kind': 'member', 'subject_id': 'mom'}) if kind == 'thread' else storage.update_mission(sid, {'subject_kind': 'member', 'subject_id': 'mom'})
            path = '/api/subjects/member/mom/situations'
    elif path == '/api/subjects/search':
        path += '?q=' + fx.title(rkey)
    elif path == '/api/asks/channels':
        # A recipient lookup has no record input or piece output.
        r = request(fx, col, 'GET', path + '?member_id=mom')
        if col != 'pat':
            assert r.status_code in (200, 403), r.text
            assert fx.secret(rkey) not in r.text and fx.title(rkey) not in r.text
        return 'skip'
    elif path == '/api/asks/{ask_id}/channels':
        aid = storage.add_ask({'situation_kind': kind, 'situation_id': sid, 'to_name': 'Mom',
                               'asked_by': 'mom', 'what': fx.secret(rkey), 'channel': 'text'})
        path = f'/api/asks/{aid}/channels'
    elif path == '/api/programs/{program_id}/lesson':
        storage.upsert_program_lesson(sid, {'phase_name': '', 'unit_n': 0, 'session_label': ''},
                                      {'scenes': [{'say': fx.secret(rkey)}]})
    elif path == '/api/action-proposals':
        storage.add_action_proposal({'action_type': 'skip_occurrence', 'summary': fx.secret(rkey),
                                     'status': 'proposed', 'origin_kind': 'mission', 'origin_id': sid})
    path = path.replace('{kind}', kind).replace('{sid}', sid).replace('{record_id}', sid).replace('{mission_id}', sid).replace('{program_id}', sid).replace('{project_id}', row['project_id'])
    with ExitStack() as stack:
        if path.endswith('/footprint'):
            stack.enter_context(patch.object(programs, 'footprint', side_effect=lambda p: p))
        if path == '/api/programs/lessons/sweep':
            # Real sweep aggregation, one cached window per program, no LLM.
            from services import program_lessons as pl
            stack.enter_context(patch.object(pl, '_windows_to_scan', return_value=[
                (row, {'phase_name': fx.secret(rkey), 'date': '2026-10-16'}, None)]))
            stack.enter_context(patch.object(pl, 'needs_lesson', return_value=False))
        r = request(fx, col, rid[1], path, **({'json': {}} if rid[1] == 'POST' else {}))
    if path.endswith('/channels') or '/shots/' in path:
        return result(r)
    if rid[-1] == '/api/projects/for/{kind}/{record_id}':
        v = result(r)
        return F if v == F and r.json().get('record_visible') else None if v == F else v
    text = result(r, True)
    if text == 'FORBIDDEN-NOT-404' and rid[-1] in ('/api/missions/admin', '/api/subjects/{kind}/{sid}/situations', '/api/action-proposals'):
        return None  # collection role gate, not disclosure of a named record
    if rid[-1] in ('/api/projects', '/api/projects/{project_id}', '/api/projects/{project_id}/pieces', '/api/subjects/{kind}/{sid}/situations'):
        if base(rkey, col) == K:
            assert fx.secret(rkey) not in str(text), 'keeper words leaked in project/backlink'
        return K if has_title(text, fx, rkey) else None
    if text == 'FORBIDDEN-NOT-404' or (text and text.startswith('HTTP ')):
        return text
    return observed(text, fx, rkey)


def write_probe(rid, fx, rkey, col, forced_verb=None):
    if col == 'house':
        return 'skip'
    fx = access_fixture.build()
    kind, row = load(fx, rkey)
    sid, path, method = row['id'], rid[-1], rid[1]
    verb = forced_verb or verb_for(rid)
    if rid[0] == 'route-prefix':
        errors = []
        for action in PROGRAM_VERBS:
            got = write_probe(('route', 'POST', '/api/programs/{program_id}/' + action), fx, rkey, col)
            want = act_expected(rkey, col, action)
            if got != want:
                errors.append(f'{action}: want {want} got {got}')
        return '; '.join(errors) if errors else act_expected(rkey, col, verb)
    if path == '/api/missions/launch' and kind != 'thread':
        return 'skip'
    if path.endswith('/photo') and kind != 'thread':
        return 'skip'
    body = {'member_id': col, 'text': 'A note', 'next_action': 'Next', 'question': 'Research this',
            'subject': 'Subject', 'body': 'Message', 'to': 'someone@example.test',
            'decision': 'decline', 'outcome': 'unsure', 'answer': 'yes', 'minutes': 5,
            'phase_name': 'phase', 'unit_n': 1, 'scenes': [{'type': 'say', 'text': 'Hello'}]}
    if path in ('/api/threads', '/api/programs'):
        body.update(title='Learn piano', project_id=row['project_id'], owner_member_id=col)
    if path == '/api/missions/launch':
        body.update(origin_kind='thread', origin_ref=sid, goal='Help with this')
        verb = 'mission'
    if path == '/api/asks':
        body.update(kind=kind, id=sid, to={'name': 'Someone'}, what='Please help', channel='text')
    if '/api/asks/{ask_id}' in path:
        aid = storage.add_ask({'situation_kind': kind, 'situation_id': sid, 'to_name': 'Someone',
                               'asked_by': col, 'what': 'Please help', 'channel': 'text'})
        path = path.replace('{ask_id}', aid)
    if '/proposals/' in path or '/action-proposals/' in path:
        prop = {'action_type': 'log_program_session' if kind == 'program' else 'skip_occurrence',
                'payload': {'program_id': sid} if kind == 'program' else {}, 'summary': 'Do this', 'status': 'proposed'}
        if kind == 'mission':
            prop.update(origin_kind='mission', origin_id=sid)
        pid = storage.add_action_proposal(prop)
        path = path.replace('{proposal_id}', pid)
        body['act'] = 'approve'
    if '/situations/' in path:
        body.update(verb='answer' if kind == 'mission' else 'close',
                    option_id='answer:steer' if kind == 'mission' else 'close:done', payload={'text': 'Please continue'})
        if kind == 'mission':
            storage.update_mission(sid, {'status': 'running'})
    path = path.replace('{kind}', kind).replace('{sid}', sid).replace('{thread_id}', sid).replace('{mission_id}', sid).replace('{program_id}', sid)
    with ExitStack() as stack:
        # Downstream work is outside this route-gate matrix. None of these mocks
        # replace the access check, request identity, or existing role check.
        from services import threads, missions, asks, chat_actions
        stack.enter_context(patch.object(main, 'trigger_background_refresh'))
        stack.enter_context(patch('services.programs_curate.curate', return_value={'phases': [], 'source': {'origin': 'none'}}))
        for obj, name, ret in [(threads, 'draft_message', {'status': 'ok'}),
                               (threads, 'send_drafted', {'status': 'ok'}),
                               (threads, 'research', {'status': 'ok'}),
                               (threads, 'add_photo', {'status': 'ok'}),
                               (missions, 'release', {'status': 'success'}),
                               (missions, 'submit', {'status': 'success'}),
                               (missions, 'verify', {'status': 'success'}),
                               (missions, 'launch', {'status': 'launched'}),
                               (planned, 'answer_plan', {'status': 'success'}),
                               (chat_actions, '_skip_occurrence', {'status': 'success'}),
                               (asks, 'draft', {'subject': '', 'body': '', 'source': 'template'})]:
            stack.enter_context(patch.object(obj, name, return_value=ret))
        for name in ('approve', 'log_session', 'mark_milestone', 'finish', 'reshape', 'pause', 'resume'):
            stack.enter_context(patch.object(programs, name, return_value={'status': 'success'}))
        if kind == 'program' and verb == 'edit':
            storage.update_program(sid, {'state': 'proposed'})
        if kind == 'program' and verb == 'unit':
            storage.update_program(sid, {'phases': [{'name': 'phase', 'units': [{'n': 1, 'title': 'One'}, {'n': 2, 'title': 'Two'}]}]})
            body['direction'] = 'next'
        if path.endswith('/photo'):
            r = request(fx, col, method, path, files={'file': ('test.png', b'png', 'image/png')})
        else:
            r = request(fx, col, method, path, json=body)
    outcome = result(r)
    if outcome == F and r.json().get('status') in ('error', 'refused', 'not_found'):
        return f'ACTION-NOT-ACCEPTED: {r.text[:160]}'
    return outcome


def function_probe(rid, fx, rkey, col):
    kind, row = load(fx, rkey)
    viewer, name = fx.viewers[col], rid[1].rsplit('.', 1)[-1]
    if name == 'queue_row':
        if kind != 'mission':
            return 'skip'
        storage.update_mission(row['id'], {'plan': {'state': 'running', 'stages': [
            {'id': 'w', 'kind': 'work', 'state': 'running', 'title': 'Work', 'rows': []}]}})
        res = planned.queue_row(row['id'], {'tool': 'create_list', 'args': {'name': 'List'}, 'summary': 'List'}, viewer=viewer)
        return F if res.get('status') == 'success' else None
    if name == 'due_asks_for':
        if kind != 'program':
            return 'skip'
        now = datetime.datetime(2026, 10, 16, 12)
        pc = storage.add_protected_commitment({'id': 'probe-' + row['id'], 'member_id': 'kid', 'days_of_week': [3],
                                              'time_start': '17:00', 'time_end': '17:20'})
        row['emissions'] = {'commitment_ids': [pc]}
        with patch('services.family_digest.in_member_quiet_hours', return_value=False):
            return observed(programs.due_asks_for(row, now=now, viewer=viewer), fx, rkey)
    if name == '_rows_of':
        if kind == 'program':
            return 'skip'
        return F if (kind, row['id']) in situations._rows_of(kind, True, viewer=viewer) else None
    if name == 'elsewhere':
        if kind != 'mission':
            return 'skip'
        out = projects.elsewhere(viewer)
    else:
        project = storage.get_project(row['project_id'])
        out = getattr(projects, name)(project, viewer)
        if base(rkey, col) == K:
            assert fx.secret(rkey) not in str(out), 'keeper words leaked'
        return K if has_title(out, fx, rkey) else None
    return observed(out, fx, rkey)


def extra_contracts():
    """Rows without piece kinds, exact missing responses, and non-HTTP callers."""
    from harness import check
    from services import asks, chat_actions
    fx = access_fixture.build()
    # Signed-in routes reject HOUSE before their handlers; internal fallback is HOUSE.
    check(main._piece_viewer(None) == {'id': None, 'role': 'adult', 'house': True}, 'no parent stand-in')
    r = request(fx, 'house', 'GET', '/api/threads')
    check(r.status_code in (401, 403), f'identity-free signed-in request: {r.status_code}')
    for kind, key, path in [('thread', 'R1', '/api/situations/thread/{}'),
                           ('mission', 'R2', '/api/missions/{}'),
                           ('program', 'R3', '/api/programs/{}/footprint')]:
        col = 'aunt' if kind == 'program' else 'dad'
        hidden = request(fx, col, 'GET', path.format(fx.ids[key]))
        missing = request(fx, col, 'GET', path.format('missing'))
        check(hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json(),
              f'{kind}: hidden must equal missing')
    project = fx.projects['household']['id']
    for method, suffix, body in [('POST', '/pieces', {'kind': 'thread', 'id': fx.ids['R1']}),
                                 ('POST', '/pieces/remove', {'kind': 'thread', 'id': fx.ids['R5t']})]:
        r = request(fx, 'dad', method, f'/api/projects/{project}{suffix}', json=body)
        check(r.status_code == (400 if suffix == '/pieces' else 200), r.text)
    r = request(fx, 'mom', 'GET', '/api/subjects/thread/' + fx.ids['R1'] + '/projects')
    check(r.status_code == 200 and fx.projects['mom_private']['id'] in r.text, r.text)
    for col, accepted in [('mom', True), ('dad', False)]:
        res = asks.create('thread', fx.ids['R1'], {'name': 'Someone'}, 'Help', 'text', col, draft_mode='template')
        check((res.get('status') == 'success') == accepted, f'asks.create {col}: {res}')
    storage.update_mission(fx.ids['R2'], {'status': 'running'})
    for col, status in [('aunt', 200), ('dad', 404)]:
        r = request(fx, col, 'POST', f"/api/missions/{fx.ids['R2']}/answer", json={'text': 'Try another approach'})
        check(r.status_code == status, f'keeper steering {col}: {r.status_code} {r.text}')
    for action, function in [('log_program_session', 'log_session'), ('reshape_program', 'reshape')]:
        for col, accepted in [('dad', True), ('aunt', False), ('kid', True)]:
            pid = storage.add_action_proposal({'action_type': action, 'payload': {'program_id': fx.ids['R3']},
                                               'summary': 'Practice', 'status': 'proposed', 'requires_admin': False})
            with patch.object(programs, function, return_value={'status': 'success'}) as effect:
                res = chat_actions.act_on_proposal(pid, 'approve', fx.viewers[col])
                check((res.get('status') == 'success') == accepted and effect.called == accepted,
                      f'proposal {action} {col}: {res}')
    # A visible thread must not forward a different, hidden mission's question.
    storage.update_mission(fx.ids['R2'], {'origin_kind': 'thread', 'origin_ref': fx.ids['R5t'], 'status': 'waiting_user'})
    r = request(fx, 'dad', 'GET', f"/api/situations/thread/{fx.ids['R5t']}")
    check(r.status_code == 200 and fx.secret('R2') not in r.text, f'hidden forwarded question: {r.text}')
    from services import program_lessons as pl
    windows = [(storage.get_program(fx.ids[key]), {'phase_name': fx.secret(key), 'date': '2026-10-16'}, None)
               for key in ('R3', 'R5p')]
    storage.set_app_state('program_lessons_swept', 'before')
    with patch.object(pl, '_windows_to_scan', return_value=windows), patch.object(pl, 'needs_lesson', return_value=False):
        r = request(fx, 'aunt', 'POST', '/api/programs/lessons/sweep', json={})
    check(r.status_code == 200 and r.json()['skipped'] == 1 and len(r.json()['slots']) == 1
          and fx.secret('R3') not in r.text and fx.secret('R5p') in r.text, 'scoped sweep words and counts')
    check(storage.get_app_state('program_lessons_swept') == 'before', 'scoped sweep does not claim the household pass')


def register(probe):
    for rid in IDS:
        if rid[0] == 'reader':
            fn = function_probe
        elif rid[1] == 'GET' or rid[-1] == '/api/programs/lessons/sweep':
            fn = read_probe
        else:
            fn = write_probe
        def run(fx, rkey, col, rid=rid, fn=fn):
            # Isolate setup changes and cached identity tokens between cells.
            if col == 'house' and rid[0] != 'reader':
                return 'skip'
            return fn(rid, fx if fn == write_probe else access_fixture.build(), rkey, col)
        probe(rid)(run)
