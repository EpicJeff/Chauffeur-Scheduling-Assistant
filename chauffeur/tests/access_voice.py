"""Task 7: shared-speaker probes through dispatch, router and the real HA route."""
import json
import time
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from harness import check
import access_fixture
from test_access_core import TABLE, COLS, load
from services import access, access_readers, agent_router, app_voice, missions, storage
from services import voice_identity as identity, voice_tools, voice_approval as approval

PRIVATE = "That one's private — open it on your phone."


def context():
    return identity.VoiceContext('', '', uuid.uuid4().hex, 'room')


def dispatch(fx, rkey, col):
    with patch.object(identity.VoiceContext, 'verified_member', return_value=fx.viewers[col]):
        return voice_tools.dispatch('find_in_chauffeur', {'query': fx.title(rkey)}, context())


def router(fx, rkey, col, http=False):
    captured = []
    replies = [{'message': '', 'tool_calls': [{'name': 'find_in_chauffeur', 'arguments': {'query': fx.title(rkey)}}]},
               {'message': 'ok', 'tool_calls': []}]
    def model(prompt, tools, system_prompt):
        captured.append((prompt or '') + '\n' + (system_prompt or ''))
        return replies.pop(0)
    ctx = context()
    results = []
    real_dispatch = voice_tools.dispatch
    def dispatch_result(*args, **kwargs):
        result = real_dispatch(*args, **kwargs)
        results.append(result)
        return result
    with patch.object(identity.VoiceContext, 'verified_member', return_value=fx.viewers[col]), \
            patch.object(agent_router, 'call_gemma_with_fallback', side_effect=model), \
            patch.object(voice_tools, 'dispatch', side_effect=dispatch_result):
        if http:
            import main
            from services import voice_fingerprint, voice_setup
            with patch.object(identity, 'context', return_value=ctx), \
                    patch.object(voice_fingerprint, 'consume', return_value=None), \
                    patch.object(voice_fingerprint, 'apply', return_value=ctx), \
                    patch.object(voice_setup, 'intercept', return_value=None):
                response = TestClient(main.app).post('/api/v2/converse', json={'text': 'What is next?'})
                check(response.status_code == 200, response.text)
        else:
            agent_router.process_agent_request('What is next?', source='voice', voice_context=ctx)
    check(len(captured) == 2, f'voice must reach the real router tool loop: {len(captured)}')
    check(results, 'real voice dispatch executed')
    return json.dumps(results)


def register(probe):
    for rid, cls, kinds, _ in access_readers.READERS:
        if cls != '4.5-voice':
            continue
        name = rid[-1].rsplit('.', 1)[-1]
        def run(fx, rkey, col, name=name):
            fx = access_fixture.build()
            storage.update_thread(fx.ids['R13'], {'title': 'Unrelated wrapper'})
            for thread in storage.get_threads():
                storage.update_thread(thread['id'], {'voice_shared': True})
            if name in ('prepare', 'valid', 'intercept'):
                if rkey in ('R1', 'R2') and col == 'mom':
                    approval_contract(name, origin=rkey == 'R1')
                return 'skip'
            if name == 'tool_result':
                turn = app_voice.Turn('turn', fx.viewers[col], '', {})
                turn.tools = ['find_in_chauffeur']
                turn.speech_safe = False  # before_tool's existing conservative policy
                turn.tool_result(dispatch(fx, rkey, col))
                check(not turn.audible({'status': 'success'}), 'phone voice finder stays text-only')
                return 'skip'
            out = (router(fx, rkey, col, http=True) if name in ('/api/v2/converse', 'perform')
                   else dispatch(fx, rkey, col))
            text = out if isinstance(out, str) else json.dumps(out)
            allowed = TABLE[rkey][COLS.index('house')] is not None
            seen = fx.title(rkey) in text or fx.secret(rkey) in text
            check(seen == allowed, f'voice {name} {rkey} {col}: allowed={allowed}: {text[:1800]}')
            return 'skip'
        probe(rid)(run)


def verified(fx):
    settings = {**storage.get_settings(), 'service_token': 'service', 'missions_submit_enabled': True}
    storage.get_settings = lambda: settings
    identity.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'kitchen', 'enabled': True}],
                       approvals_enabled=True)
    storage.set_member_pin('mom', '1234')
    def ctx():
        return identity.context({'ha_instance_id': 'ha', 'satellite_id': 'kitchen',
                                 'observed_at': time.time(), 'request_id': uuid.uuid4().hex}, True)
    identity.intercept("It's Mom", ctx())
    identity.intercept('My PIN is 1234', ctx())
    check(ctx().verified_member(), 'real verified voice session')
    return ctx


def approval_contract(name, origin=False):
    fx = access_fixture.build()
    ctx = verified(fx)
    mid = fx.ids['R2']
    if origin:
        storage.update_mission(mid, {'project_id': fx.projects['household']['id'],
                                    'origin_kind': 'thread', 'origin_ref': fx.ids['R1']})
        storage.update_thread(fx.ids['R1'], {'voice_shared': True})
    def snapshot():
        return storage.get_mission(mid), storage.get_mission_steps(mid), storage.get_thread(fx.ids['R1'])
    def home(project):
        if origin:
            storage.update_thread(fx.ids['R1'], {'project_id': fx.projects[project]['id']})
        else:
            storage.update_mission(mid, {'project_id': fx.projects[project]['id']})
    aid = storage.add_mission_step(mid, {'kind': 'ask', 'name': 'submit', 'result_json': {
        'question': 'Approve?', 'site': 'merchant.test', 'url': 'https://merchant.test/review',
        'button': 'Book', 'state': {'text': 'Tuesday'}, 'facts': {'slot': 'Tuesday'}}})
    before = snapshot()
    if name == 'prepare':
        result = approval.prepare(ctx(), mid, 'submit')
        check(result.get('message') == PRIVATE, f'exact private spoken refusal: {result}')
        # The production HA handler must speak the refusal verbatim, through
        # source='voice', even if the model tries to summarize it afterwards.
        import main
        from services import voice_fingerprint, voice_setup
        fake = {'message': '', 'tool_calls': [{'name': 'prepare_voice_approval',
                'arguments': {'mission_ref': mid, 'kind': 'submit'}}]}
        current = ctx()
        with patch.object(identity, 'context', return_value=current), \
                patch.object(voice_fingerprint, 'consume', return_value=None), \
                patch.object(voice_fingerprint, 'apply', return_value=current), \
                patch.object(voice_setup, 'intercept', return_value=None), \
                patch.object(agent_router, 'call_gemma_with_fallback', return_value=fake) as model:
            response = TestClient(main.app).post('/api/v2/converse', json={'text': 'approve it'})
        check(response.status_code == 200 and
              response.json()['response']['speech']['plain']['speech'] == PRIVATE,
              f'production spoken refusal: {response.text}')
        check(model.call_count == 1, 'private refusal is deterministic, without another model summary')
    else:
        # Prepare while household, then narrow before confirmation/validation.
        home('household')
        result = approval.prepare(ctx(), mid, 'submit')
        check(result['status'] == 'success', f'household readback works: {result}')
        readback = identity._sessions[('ha', 'kitchen')]['readback']
        ask = missions._pending_ask(mid, 'submit')
        proof = approval.ApprovalContext(ctx(), readback['id'], aid, 'submit', readback['digest'], time.time())
        check(approval.valid(proof, ask, fx.viewers['mom']), 'positive control: household approval is valid')
        home('mom_private')
        before = snapshot()
        if name == 'intercept':
            result = approval.intercept('approve booking', ctx())
            check(result.get('message') == PRIVATE, f'privacy change spoken refusal: {result}')
        else:
            ask = missions._pending_ask(mid, 'submit')
            check(not approval.valid(proof, ask, fx.viewers['mom']), 'valid rejects narrowed record')
    check(snapshot() == before, 'private approval leaves mission, origin and ask unchanged')


def extra_contracts():
    for name in ('prepare', 'valid', 'intercept'):
        approval_contract(name)
        approval_contract(name, origin=True)
    # Both restrictions apply, even with a verified parent and a household home.
    fx = access_fixture.build()
    storage.update_thread(fx.ids['R5t'], {'voice_shared': False})
    for out in (dispatch(fx, 'R5t', 'mom'), router(fx, 'R5t', 'mom')):
        check(fx.title('R5t') not in str(out) and fx.secret('R5t') not in str(out), 'HOUSE still requires spoken_safe')
    # Focus ABOUT is gated by HOUSE, not the authenticated voice's private access.
    fx = access_fixture.build()
    from services import triage
    storage.update_thread(fx.ids['R1'], {'subject_kind': 'thread', 'subject_id': fx.ids['R4'], 'voice_shared': True})
    storage.update_thread(fx.ids['R4'], {'voice_shared': True})
    focus = {'kind': 'thread', 'id': fx.ids['R1']}
    captured = []
    def model(prompt, tools, system_prompt):
        captured.append(system_prompt)
        return {'message': 'ok', 'tool_calls': []}
    with patch.object(identity.VoiceContext, 'verified_member', return_value=fx.viewers['mom']), \
            patch.object(triage, 'get_focus', return_value=focus), \
            patch.object(agent_router, 'call_gemma_with_fallback', side_effect=model):
        agent_router.process_agent_request('What about it?', source='voice', voice_context=context(), focus_key='voice:room')
    check(captured and fx.title('R4') not in captured[0] and fx.secret('R4') not in captured[0], 'voice ABOUT uses HOUSE')
    captured.clear()
    storage.update_thread(fx.ids['R5t'], {'subject_kind': 'program', 'subject_id': fx.ids['R5p'], 'voice_shared': True})
    with patch.object(triage, 'get_focus', return_value={'kind': 'thread', 'id': fx.ids['R5t']}), \
            patch.object(agent_router, 'call_gemma_with_fallback', side_effect=model):
        agent_router.process_agent_request('What about it?', source='voice', voice_context=context(), focus_key='voice:room')
    check(captured and fx.title('R5p') in captured[0], 'HOUSE focus keeps household ABOUT context')
