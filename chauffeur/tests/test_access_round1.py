"""Task 3 review regressions: HTTP handlers and real services, only model I/O mocked."""
import base64
import traceback
from unittest.mock import patch

from harness import check
import access_fixture
from access_signed_in import request
from services import storage, model_pools


def scenario_edit_cannot_move_pieces():
    fx = access_fixture.build()
    tid = fx.ids['R1']
    home = storage.get_thread(tid)['project_id']
    for col in ('aunt', 'mom'):
        for target in (None, fx.projects['household']['id']):
            r = request(fx, col, 'PATCH', f'/api/threads/{tid}',
                        json={'project_id': target, 'counterparty_name': 'Office'})
            check(r.status_code == 200, r.text)
            check(storage.get_thread(tid)['project_id'] == home, 'thread PATCH changed project_id')
            check(storage.get_thread(tid)['counterparty_name'] == 'Office', 'ordinary edit lost')
            check(request(fx, 'dad', 'GET', f'/api/situations/thread/{tid}').status_code == 404,
                  'Dad can read R1 after PATCH')
    pid, mid = fx.ids['R3'], fx.ids['R2']
    storage.update_program(pid, {'state': 'proposed'})
    for target in (None, fx.projects['household']['id']):
        r = request(fx, 'mom', 'POST', f'/api/programs/{pid}/edit', json={'project_id': target})
        check(r.status_code == 200 and r.json()['status'] == 'success', r.text)
        check(storage.get_program(pid)['project_id'] == home, 'program edit moved its home')
        r = request(fx, 'mom', 'POST', f'/api/missions/{mid}/answer',
                    json={'text': 'Continue', 'project_id': target})
        check(r.status_code == 200 and r.json()['status'] == 'success', r.text)
        check(storage.get_mission(mid)['project_id'] == home, 'mission answer moved its home')
        check(request(fx, 'dad', 'GET', f'/api/missions/{mid}').status_code == 404,
              'Dad can read R2 after answer')


def scenario_draft_uses_viewer_projection():
    fx = access_fixture.build()
    tid = fx.ids['R1']
    history_secret = fx.secret('R1') + '-HISTORY'
    storage.append_thread_history(tid, {'kind': 'mission', 'text': history_secret})
    storage.append_thread_history(tid, {'kind': 'note', 'text': 'Keeper correspondence'})
    history = storage.get_thread(tid)['history']
    for path, body in ((f'/api/threads/{tid}/draft', {'intent': 'Please follow up'}),
                       (f'/api/situations/thread/{tid}/act', {'verb': 'draft', 'option_id': 'draft',
                                                            'payload': {'text': 'Please follow up'}})):
        storage.update_thread(tid, {'history': history})
        for col in ('aunt', 'mom'):
            with patch.object(model_pools, 'call_pool_json', return_value={
                    'subject': 'Follow up', 'body': 'Please reply'}) as model:
                r = request(fx, col, 'POST', path, json=body)
            check(r.status_code == 200 and r.json()['status'] == 'ok', r.text)
            check(model.call_count == 1, 'draft must execute its model path')
            prompt = model.call_args.args[3]
            check('Keeper correspondence' in prompt and 'Please follow up' in prompt, 'allowed draft context lost')
            check(('Next action on file: ' + fx.secret('R1') in prompt) == (col == 'mom'),
                  f'{col}: next_action leaked or lost: {prompt}')
            check((history_secret in prompt) == (col == 'mom'), f'{col}: mission history leaked or lost: {prompt}')
    check(any(h['kind'] == 'drafted' for h in storage.get_thread(tid)['history']), 'draft was not persisted')


def scenario_photo_only_answers_actable_missions():
    fx = access_fixture.build()
    tid = fx.ids['R1']
    hidden = fx.ids['R9a']
    keeper = fx.ids['R2']
    for mid in (hidden, keeper):
        storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid, 'status': 'waiting_user'})
    before = {mid: storage.get_mission_steps(mid) for mid in (hidden, keeper)}
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
    for col in ('aunt', 'mom'):
        with patch.object(model_pools, 'credentials', return_value=('test', 'test-key')), \
             patch.object(model_pools, 'call_pool_json', return_value={'text': 'Serial 12345'}) as model:
            r = request(fx, col, 'POST', f'/api/threads/{tid}/photo',
                        files={'file': ('test.png', png, 'image/png')})
        check(r.status_code == 200 and r.json()['read'], r.text)
        check(model.call_count == 1, 'photo did not run vision read')
        entry = r.json()['entry']
        check(storage.media_file_path(entry['media_id']), 'photo not saved')
        check(any(h.get('media_id') == entry['media_id'] for h in storage.get_thread(tid)['history']),
              'photo upload must remain available')
        for mid in (hidden, keeper):
            steps = storage.get_mission_steps(mid)
            if col == 'aunt':
                check(storage.get_mission(mid)['status'] == 'waiting_user' and steps == before[mid],
                      'Aunt photo answered a hidden or keeper-only mission')
            else:
                check(storage.get_mission(mid)['status'] == 'running', 'Mom photo did not resume mission')
                check(any(s.get('name') == 'user_answer' and 'Serial 12345' in str(s) for s in steps),
                      'Mom photo answer missing')


def scenario_keeper_asks_are_redacted():
    fx = access_fixture.build()
    for kind, key in (('mission', 'R2'), ('thread', 'R1')):
        sid, secret = fx.ids[key], fx.secret(key)
        with patch.object(model_pools, 'call_pool_json', return_value={'subject': secret, 'body': secret}):
            r = request(fx, 'mom', 'POST', '/api/asks', json={
                'kind': kind, 'id': sid, 'to': {'name': 'Office'}, 'what': secret, 'channel': 'email'})
        check(r.status_code == 200 and r.json()['status'] == 'success', r.text)
        ask = r.json()['ask']
        check(secret in ask['what'] and secret in ask['draft_body'], 'ask fixture lacks secret')
        storage.update_ask(ask['id'], {'reply_text': secret + '-REPLY'})
        for path in ('/api/situations', f'/api/situations/{kind}/{sid}'):
            aunt = request(fx, 'aunt', 'GET', path)
            mom = request(fx, 'mom', 'GET', path)
            check(aunt.status_code == mom.status_code == 200, path)
            check(ask['id'] in aunt.text, 'keeper lost ask metadata')
            check(secret not in aunt.text, f'keeper ask secret leaked through {path}')
            check(secret in mom.text and secret + '-REPLY' in mom.text, 'full viewer lost ask text')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failures = 0
    for scenario in SCENARIOS:
        try:
            scenario()
            print('PASS', scenario.__name__, flush=True)
        except Exception:
            failures += 1
            print('FAIL', scenario.__name__, flush=True)
            traceback.print_exc()
    raise SystemExit(bool(failures))
