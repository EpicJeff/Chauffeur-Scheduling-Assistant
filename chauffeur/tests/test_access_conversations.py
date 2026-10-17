"""Spec 4.2 / user ruling: admin, PWA and panel conversations are owned.

Run from chauffeur/: python tests/test_access_conversations.py
"""
import asyncio
import subprocess
import traceback
from pathlib import Path
from unittest.mock import patch

from harness import check
import access_fixture
from fastapi.testclient import TestClient
from starlette.requests import Request
from services import storage, access, agent_router, llm
import main

ROOT = Path(__file__).resolve().parents[1]


def fresh():
    fx = access_fixture.build()
    storage.clear_chat_history()
    main.CHAT_EVENTS.clear()
    return fx


def enforced():
    return patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True,
                                                            'service_local_grace': False})


def headers(mid):
    return {'X-Member-Token': storage.create_member_token(mid)}


def conversation(c, h, surface='admin'):
    r = c.get('/api/chat/conversation?surface=' + surface, headers=h)
    check(r.status_code == 200, f'choose {surface}: {r.status_code} {r.text}')
    return r.json()['conversation']


def scenario_members_own_separate_admin_and_pwa_conversations():
    fresh()
    with enforced():
        c = TestClient(main.app)
        mom, dad = headers('mom'), headers('dad')
        ids = set()
        for surface in ('admin', 'pwa'):
            conv = conversation(c, mom, surface)
            ids.add(conv['id'])
            check(conv['surface'] == {'kind': surface, 'owner': 'mom'}, 'member surface owner')
            check(conversation(c, mom, surface)['id'] == conv['id'], 'one live conversation')
            storage.add_message_to_conversation(conv['id'], {'role': 'assistant', 'content': 'private words'})
            own_history = c.get('/api/chat/history?conversation_id=' + conv['id'], headers=mom)
            check(own_history.status_code == 200 and 'private words' in own_history.text, 'owner can read history')
            check(conv['id'] in {x['id'] for x in c.get('/api/chat/conversations', headers=mom).json()['conversations']}, 'owner can list')
            for method, path in [('GET', '/api/chat/history?conversation_id='),
                                 ('DELETE', '/api/chat/history?conversation_id='),
                                 ('DELETE', '/api/chat/conversations/')]:
                r = c.request(method, path + conv['id'], headers=dad)
                check(r.status_code == 404, f'other person {method}: {r.status_code}')
            r = c.post('/api/chat', headers=dad, json={'message': 'hi', 'conversation_id': conv['id']})
            check(r.status_code == 404, 'other person cannot prompt with owned history')
            check(conv['id'] not in {x['id'] for x in c.get('/api/chat/conversations', headers=dad).json()['conversations']}, 'other parent cannot list')
        check(len(ids) == 2, 'PWA and admin stay separate')
        for surface in ('admin', 'pwa', 'panel'):
            check(c.get('/api/chat/conversation?surface=' + surface).status_code == 401, 'no identity refuses')


def scenario_panel_reads_as_house_and_keeps_its_device():
    fresh()
    device = {'X-Device-Token': storage.enrol_device_token('panel-kitchen', 'Kitchen')}
    other = {'X-Device-Token': storage.enrol_device_token('panel-office', 'Office')}
    seen = []
    def fake(message, **kw):
        seen.append(kw)
        return {'message': 'ok'}
    with enforced(), patch.object(agent_router, 'process_agent_request', side_effect=fake), patch.object(llm, 'auto_name_conversation'):
        c = TestClient(main.app)
        conv = conversation(c, device, 'panel')
        check(conv['surface'] == {'kind': 'panel', 'owner': 'panel-kitchen'}, 'device owns panel')
        mom = headers('mom')
        for h in (device, {**device, **mom}):
            chosen = c.get('/api/chat/conversation?surface=panel&panel=true', headers=h).json()['conversation']
            check(chosen['id'] == conv['id'], 'member on enrolled panel keeps device conversation')
            r = c.post('/api/chat?surface=panel', headers=h, json={'message': 'hi', 'conversation_id': conv['id']})
            check(r.status_code == 200 and r.json().get('reply') == 'ok', f'panel chat runs: {r.text}')
            check(seen[-1]['acting_member'] == access.HOUSE, 'panel Argyle reads as HOUSE')
            check(seen[-1]['focus_key'] == 'conv:' + conv['id'], 'surface focus key')
        for h in (other, headers('aunt')):
            check(c.get('/api/chat/history?conversation_id=' + conv['id'], headers=h).status_code == 404, 'unrelated caller cannot read panel')
            check(conv['id'] not in {x['id'] for x in c.get('/api/chat/conversations', headers=h).json()['conversations']}, 'unrelated caller cannot list panel')
        check(c.get('/api/chat/history?conversation_id=' + conv['id'], headers=mom).status_code == 200, 'parent can read panel')
        check(c.get('/api/chat/conversation?surface=admin', headers=device).status_code == 401, 'device cannot open admin')
        check(c.get('/api/chat/conversation?surface=pwa', headers=device).status_code == 401, 'device cannot open PWA')
        anon = c.get('/api/chat/conversation?panel=true', headers=mom).json()['conversation']
        check(anon['surface'] == {'kind': 'panel', 'owner': 'anon-panel:mom'}, 'member-only panel fallback is per person')
        kate = headers('kid')
        kate_panel = c.get('/api/chat/conversation?panel=true', headers=kate).json()['conversation']
        check(kate_panel['surface']['owner'] == 'anon-panel:kid' and kate_panel['id'] != anon['id'], 'Kate has a separate panel')
        storage.add_message_to_conversation(anon['id'], {'role': 'assistant', 'content': 'Mom tablet words'})
        check(c.get('/api/chat/history?panel=true&conversation_id=' + anon['id'], headers=kate).status_code == 404,
              'Kate cannot read Mom tablet history')
        check(c.post('/api/chat?panel=true', headers=kate, json={'message': 'hi', 'conversation_id': anon['id']}).status_code == 404,
              'Kate cannot post into Mom tablet conversation')
        c.post('/api/chat?panel=true', headers=mom, json={'message': 'hi', 'conversation_id': anon['id']})
        check(seen[-1]['acting_member'] == access.HOUSE, 'member-only panel reads HOUSE')
        r = c.post('/api/chat?surface=admin', headers=mom,
                   json={'message': 'hi', 'conversation_id': anon['id'], 'context': {'search': '?panel=true'}})
        check(r.status_code == 200 and seen[-1]['acting_member'] == access.HOUSE,
              'panel page context cannot be promoted to a private admin surface')
        chosen = c.get('/api/chat/conversation?surface=panel&device_token=' + device['X-Device-Token'], headers=mom).json()['conversation']
        check(chosen['id'] == conv['id'], 'member session plus explicit panel credential keeps device owner')


def scenario_legacy_and_satellite_history_are_parents_only():
    fresh()
    for cid, extra in [('old-general', {'type': 'general'}), ('voice-old', {'type': 'voice'}),
                       ('satellite-new', {'type': 'voice', 'surface': {'kind': 'satellite', 'owner': 'kitchen'}})]:
        storage.create_conversation({'id': cid, 'messages': [{'role': 'assistant', 'content': 'old words'}], 'updated_at': 9e9, **extra})
    with enforced(), patch.object(agent_router, 'process_agent_request') as router:
        c = TestClient(main.app)
        for mid in ('mom', 'dad', 'aunt', 'kid', 'hal', 'sib'):
            h = headers(mid)
            listing = c.get('/api/chat/conversations', headers=h)
            if mid == 'hal':
                check(listing.status_code == 403, 'helper chat facet remains refused')
                continue
            listed = {x['id'] for x in listing.json()['conversations']}
            for cid in ('old-general', 'voice-old', 'satellite-new'):
                parent = mid in ('mom', 'dad')
                check((cid in listed) == parent, 'history listing agrees with parent rule')
                check(c.get('/api/chat/history?conversation_id=' + cid, headers=h).status_code == (200 if parent else 404), 'history authorization')
                r = c.post('/api/chat', headers=h, json={'message': 'hi', 'conversation_id': cid})
                check(r.status_code == (409 if parent else 404), f'never answer into history: {r.status_code}')
                if parent:
                    check(r.json()['detail'] == 'That conversation is history; start a new one', 'history refusal wording')
                    for method, path in [('DELETE', '/api/chat/history?conversation_id='), ('DELETE', '/api/chat/conversations/')]:
                        check(c.request(method, path + cid, headers=h).status_code == 404, 'parents cannot erase read-only history')
                    check(storage.get_conversation(cid)['messages'], 'read-only history preserved')
        router.assert_not_called()


def scenario_create_clear_and_prompt_history_are_scoped():
    fresh()
    seen = []
    def fake(message, **kw):
        seen.append(kw)
        return {'message': 'ok'}
    with enforced(), patch.object(agent_router, 'process_agent_request', side_effect=fake), patch.object(llm, 'auto_name_conversation'):
        c = TestClient(main.app)
        mom, dad = headers('mom'), headers('dad')
        own, other = conversation(c, mom), conversation(c, dad)
        pwa = conversation(c, mom, 'pwa')
        for conv in (own, other, pwa):
            storage.add_message_to_conversation(conv['id'], {'role': 'assistant', 'content': conv['id']})
        created = c.post('/api/chat/conversations?surface=pwa', headers=mom, json={'type': 'general', 'title': 'test'}).json()['conversation']
        check(created['id'] == pwa['id'] and created['surface']['kind'] == 'pwa', 'create cannot mint unowned conversation')
        r = c.post('/api/chat?surface=pwa', headers=mom, json={'message': 'hi', 'conversation_id': pwa['id']})
        check(r.json().get('reply') == 'ok', f'PWA prompt: {r.text}')
        check(seen[-1]['acting_member']['id'] == 'mom', 'PWA actor')
        check(seen[-1]['history'] == [{'role': 'assistant', 'content': pwa['id']}], 'only own previous history injected')
        check(c.post('/api/chat?surface=panel', headers=mom, json={'message': 'hi', 'conversation_id': own['id']}).status_code == 404, 'cannot inject private history into panel')
        check(c.post('/api/chat', headers=mom, json={'message': 'hi', 'conversation_id': 'invented'}).status_code == 404, 'unknown ID refused')
        check(c.post('/api/chat', headers=mom, json={'message': 'hi'}).json().get('reply') == 'ok', 'omitted ID uses own surface')
        c.delete('/api/chat/history', headers=mom)
        check(storage.get_conversation(own['id'])['messages'] == [], 'clear own current surface')
        check(storage.get_conversation(other['id'])['messages'], 'clear preserves other person')
        check(storage.get_conversation(pwa['id'])['messages'], 'clear preserves other surface')
        r = c.delete('/api/chat/history?conversation_id=' + pwa['id'], headers=mom)
        check(r.status_code == 200 and not storage.get_conversation(pwa['id'])['messages'], 'explicit clear uses owner gate')
        r = c.delete('/api/chat/conversations/' + pwa['id'], headers=mom)
        check(r.status_code == 200 and storage.get_conversation(pwa['id']) is None, 'owner can delete conversation')
        check(storage.get_conversation(other['id'])['messages'], 'delete preserves other person')


def stream_chunk(h, cid):
    """Run the real SSE generator; inject events on its first await, then close."""
    async def run():
        req = Request({'type': 'http', 'headers': [(k.lower().encode(), v.encode()) for k, v in h.items()],
                       'query_string': ('conversation_id=' + cid).encode()})
        response = await main.stream_agent_chat(request=req, conversation_id=cid)
        async def tick(*args):
            main.CHAT_EVENTS.extend([{'reply': 'untagged secret'},
                                     {'conversation_id': 'someone-else', 'reply': 'other secret'},
                                     {'conversation_id': cid, 'reply': 'own words'}])
        try:
            with patch.object(main.asyncio, 'sleep', side_effect=tick):
                return await anext(response.body_iterator)
        finally:
            await response.body_iterator.aclose()
    return asyncio.run(run())


def scenario_stream_has_the_same_surface_owner_as_chat():
    fresh()
    with enforced():
        c = TestClient(main.app)
        mom, dad = headers('mom'), headers('dad')
        conv = conversation(c, mom)
        for h, cid in [(dad, conv['id']), (mom, 'missing')]:
            r = c.get('/api/v2/chat/stream?conversation_id=' + cid, headers=h)
            check(r.status_code == 404, 'stream refuses unowned or missing conversation')
        chunk = stream_chunk(mom, conv['id'])
        check('own words' in chunk and 'secret' not in chunk, f'stream filters global events: {chunk}')
        check(c.get('/api/v2/chat/stream?surface=panel&conversation_id=' + conv['id'], headers=mom).status_code == 404, 'private stream cannot enter panel')


def scenario_surface_storage_is_atomic_and_expires():
    fresh()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(lambda _: storage.get_surface_conversation('pwa', 'mom')['id'], range(12)))
    check(len(set(ids)) == 1, 'concurrent first use creates one conversation')
    storage.update_conversation(ids[0], {'updated_at': 1})
    check(storage.get_surface_conversation('pwa', 'mom')['id'] != ids[0], 'expired surface recreated')


def scenario_only_the_panel_owner_can_clear_or_delete():
    fresh()
    device = {'X-Device-Token': storage.enrol_device_token('kitchen', 'Kitchen')}
    with enforced():
        c = TestClient(main.app)
        for owner, surface in ((device, 'panel'), (headers('mom'), 'panel')):
            conv = conversation(c, owner, surface)
            storage.add_message_to_conversation(conv['id'], {'role': 'assistant', 'content': 'keep this'})
            for parent in (headers('dad'), headers('mom') if owner == device else headers('dad')):
                check(c.get('/api/chat/history?conversation_id=' + conv['id'], headers=parent).status_code == 200, 'parent may read panel')
                for path in ('/api/chat/history?conversation_id=', '/api/chat/conversations/'):
                    check(c.delete(path + conv['id'], headers=parent).status_code == 404, 'read permission grants no erase permission')
                check(storage.get_conversation(conv['id'])['messages'], 'parent read preserves panel messages')
            check(c.delete('/api/chat/history?conversation_id=' + conv['id'], headers=owner).status_code == 200, 'owner clears panel')
            check(not storage.get_conversation(conv['id'])['messages'], 'owner clear ran')
            check(c.delete('/api/chat/conversations/' + conv['id'], headers=owner).status_code == 200, 'owner deletes panel')
            check(storage.get_conversation(conv['id']) is None, 'owner delete ran')


def scenario_panel_refuses_person_only_adult_tools_and_person_prompt():
    from services import agent_tools_v2 as tools, negotiation, trips, occasions, mail_search
    from access_channels import capture_router
    fresh()
    cases = [('ask_deal', {'event_title': 'Soccer'}, 'grown-up'),
             ('add_trip_accommodation', {'trip_id': 't1', 'name': 'Hotel'}, 'parent or adult'),
             ('create_trip', {'title': 'Vacation'}, 'parent or adult'),
             ('answer_occasion_question', {'occasion_id': 'o1', 'key': 'theme', 'value': 'party'}, 'parent or adult'),
             ('launch_mission', {'goal': 'Find available lessons'}, 'parent or adult'),
             ('search_mail', {'query': 'appointment'}, 'signed-in parent or adult'),
             ('read_mail', {'uid': 1}, 'signed-in parent or adult')]
    for actor in (access.HOUSE, access.HOUSE_PARENT, {'id': 'mom', 'role': 'parent', 'house': True}):
        with patch.object(negotiation, 'start_asks') as send, patch.object(trips, 'create_draft') as create, \
             patch.object(occasions, 'answer') as answer, patch.object(tools, 'handle_launch_mission') as launch, \
             patch.object(mail_search, 'search', return_value={'status': 'success', 'hits': []}) as search, \
             patch.object(mail_search, 'read', return_value={
                 'status': 'success', 'subject': 'Private mail', 'from': 'sender',
                 'date': '2026-10-16', 'text': 'Private body'}) as read:
            for name, args, refusal in cases:
                prompt, out = capture_router(actor, 'conv:panel', [{'name': name, 'arguments': args}])
                check(refusal in str([prompt, out]), f'{name} refuses household actor: {out}')
                check('You are speaking with' not in prompt and 'Resolve \'me\'' not in prompt, 'HOUSE prompt has no person line')
            send.assert_not_called()
            create.assert_not_called()
            answer.assert_not_called()
            launch.assert_not_called()
            search.assert_not_called()
            read.assert_not_called()
        check(not agent_router._is_admin_member(actor), 'house actor cannot pass adult scheduling bridge gate')
        before = storage.get_all_rules()
        capture_router(actor, 'conv:panel', [{'name': 'add_routing_rule', 'arguments': {
            'constraint_type': 'unavailable', 'driver_id': 'dad'}}])
        check(storage.get_all_rules() == before, 'real router refuses HOUSE scheduling bridge write')
    for actor in (storage.get_member('mom'), storage.get_member('aunt')):
        check(agent_router._is_admin_member(actor), 'real adult retains scheduling bridge access')


def scenario_house_insight_dispatch_never_uses_a_parent_role():
    from access_channels import capture_router
    fresh()
    sid = storage.add_mind_insight({'slug': 'private', 'line': 'SENSITIVE parent words',
                                   'category': 'c', 'sensitivity': 'sensitive', 'identity': 'c:private'})
    for actor in (access.HOUSE, access.HOUSE_PARENT, {'role': 'parent'}):
        prompt, out = capture_router(actor, 'conv:panel', [{'name': 'list_insights', 'arguments': {}}])
        check('SENSITIVE parent words' not in str([prompt, out]), 'identity-free role cannot read private insights')
        before = storage.get_mind_insight(sid)
        prompt, out = capture_router(actor, 'conv:panel', [{'name': 'dismiss_insight', 'arguments': {'insight_id': sid}}])
        check(storage.get_mind_insight(sid) == before, 'identity-free role cannot dismiss insights')


def scenario_panel_mission_keeps_member_subject_but_cannot_see_contacts():
    from services import subjects, missions
    from access_channels import capture_router
    fresh()
    storage.add_member({'id': 'emma', 'name': 'Emma', 'role': 'child'})
    for viewer in (access.HOUSE, access.HOUSE_PARENT):
        check(subjects.visible('member', storage.get_member('emma'), viewer), 'house can see member subject')
        check(not subjects.visible('contact', {'id': 'contact', 'name': 'Grandma'}, viewer), 'contacts still require a person')
        # Run router -> tool -> persisted thread; only the asynchronous mission launch is stubbed.
        with patch.object(missions, 'launch', return_value={'status': 'launched', 'mission_id': 'new'}):
            prompt, out = capture_router(viewer, 'conv:panel', [{'name': 'start_mission_for', 'arguments': {
                'goal': 'Find piano lessons for Emma', 'subject_kind': 'member', 'subject_id': 'emma'}}])
        rows = [t for t in storage.get_threads() if t.get('subject_kind') == 'member' and t.get('subject_id') == 'emma']
        check(rows, f'panel for Emma keeps its member subject: {out}')


def scenario_clients_request_server_owned_conversations():
    src = (ROOT / 'templates/components/control_center.html').read_text(encoding='utf-8')
    check('chauffeurActiveConvId' not in src, 'widget has no invented localStorage id')
    check('api/chat/conversation?surface=' in src, 'widget asks server')
    src = (ROOT / 'templates/app.html').read_text(encoding='utf-8')
    # Execute the actual popup script with DOM/network stubs, including identity loss.
    script = src[src.index("        const chatMessages = document.getElementById('chat-messages');"):src.rindex('</script>')]
    js = """
const assert = require('assert');
let selectedMemberId = 'mom', token = 'mom-token', selectedDriverId = 'driver';
let calls = [], messages = [];
const box = {innerHTML:'', scrollHeight:0, scrollTop:0, appendChild(){}};
const input = {value:'hello', style:{}, focus(){}};
const events = {};
const popup = {classList:{hidden:true, toggle(k){if(k==='hidden')this.hidden=!this.hidden;}, contains(){return this.hidden;}}};
const document = {getElementById:id=>id==='chat-messages'?box:id==='chat-input'?input:id==='kiosk-chat-popup'?popup:{},
 addEventListener(k,fn){events[k]=fn;}, createElement(){return {remove(){}}}};
const window = {location:{pathname:'/app', search:''}};
function memberToken(){return token;}
function showGlobalAlert(s){messages.push(s);}
async function fetch(url, opts){calls.push([url,opts]); return {ok:true,json:async()=>
 url.includes('conversation?')?{conversation:{id:'owned-'+selectedMemberId,surface:{kind:'pwa',owner:selectedMemberId},messages:[]}}:
 url.includes('history?')?{history:[]}:{reply:'ok'}};}
function fetchSchedule(){}
""" + script + """
appendMessage = (role,text)=>messages.push(text);
(async()=>{
 if(events.DOMContentLoaded) await events.DOMContentLoaded();
 assert.equal(calls.length,0,'closed popup does not create a row on page load');
 toggleKioskChat();
 await new Promise(resolve=>setImmediate(resolve));
 assert(calls.some(x=>x[0].includes('api/chat/conversation?surface=pwa')));
 assert(!calls.some(x=>x[0].endsWith('api/chat/conversations')));
 await submitChat({preventDefault(){}});
 let sent = calls.find(x=>x[1]?.method==='POST');
 assert.equal(JSON.parse(sent[1].body).conversation_id,'owned-mom');
 selectedMemberId='dad'; token='dad-token'; input.value='hello';
 await loadChatHistory(); await submitChat({preventDefault(){}});
 sent = calls.filter(x=>x[1]?.method==='POST').at(-1);
 assert.equal(JSON.parse(sent[1].body).conversation_id,'owned-dad');
 selectedMemberId=null; token=''; calls=[]; input.value='hello';
 await loadChatHistory(); await submitChat({preventDefault(){}});
 assert.equal(activeConversationId,null); assert.equal(calls.length,0);
 assert(messages.some(x=>x.includes('Sign in on your personal device')));
 selectedMemberId='mom'; token='mom-token'; calls=[]; popup.classList.hidden=true;
 await resetPwaChat();
 assert.equal(activeConversationId,null); assert.equal(calls.length,0,'closed identity reset stays lazy');
 input.value='first send'; await submitChat({preventDefault(){}});
 assert(calls.some(x=>x[0].includes('conversation?surface=pwa')),'first send resolves its conversation');
 selectedMemberId='dad'; token='dad-token'; calls=[]; popup.classList.hidden=false;
 await resetPwaChat();
 assert.equal(activeConversationId,'owned-dad','open popup follows changed identity');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    r = subprocess.run(['node', '-e', js], text=True, capture_output=True)
    check(r.returncode == 0, f'popup runtime: {r.stdout}\n{r.stderr}')


def scenario_widget_preserves_enrolled_panel_with_member_session():
    src = (ROOT / 'templates/components/control_center.html').read_text(encoding='utf-8')
    setup = src[src.index('    let activeConversationId = null;'):src.index('    if (chatInput) {', src.index('    let activeConversationId = null;'))]
    stream = src[src.index('    async function initChatStream() {'):src.index('    // Start listening', src.index('    async function initChatStream() {'))]
    js = """
const assert = require('assert');
const location = {search:'?panel=true'};
const localStorage = {getItem:k=>k==='chauffeur_device_token'?'panel-credential':null};
let requests=[], streams=[];
const window = {chfBase:'/', chfPersonToken:()=>MEMBER_TOKEN, chfAuthUrl:u=>u+'&member_token=member-credential'};
async function fetch(u){requests.push(u);return {ok:true,json:async()=>({conversation:{id:'owned-panel'}})};}
class EventSource {constructor(u){streams.push(u)}}
""" + setup + stream + """
(async()=>{
 await initChatStream();
 assert.equal(requests.length,1);
 assert(requests[0].includes('surface=panel'));
 assert(requests[0].includes('device_token=panel-credential'));
 assert(streams[0].includes('device_token=panel-credential'));
 assert(streams[0].includes('member_token=member-credential'));
 assert(streams[0].includes('conversation_id=owned-panel'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    for search, member in [('?panel=true', 'member-credential'), ('', '')]:
        runtime = js.replace("search:'?panel=true'", 'search:' + repr(search)).replace('MEMBER_TOKEN', repr(member))
        r = subprocess.run(['node', '-e', runtime], text=True, capture_output=True)
        check(r.returncode == 0, f'panel widget runtime ({search}, member={bool(member)}): {r.stdout}\n{r.stderr}')


def scenario_conversation_probes_run_extra_contracts_once():
    import access_conversations as probes
    from services import access_readers
    from test_access_core import COLS
    registered = {}
    def probe(rid):
        def save(fn):
            registered[rid] = fn
            return fn
        return save
    probes.register(probe)
    fx = fresh()
    with patch.object(probes, 'extra_contracts') as contracts:
        for rid, cls, kinds, _ in access_readers.READERS:
            if cls == '4.2-conversation' and not kinds:
                for col in COLS:
                    registered[rid](fx, 'R1', col)
        check(contracts.call_count == 0, 'per-column probes leave contracts to the matrix once-only hook')
        import test_access_matrix as matrix
        with patch.object(matrix.sys, 'argv', ['test_access_matrix.py', '4.2']):
            matrix.scenario_conversation_contracts()
        contracts.assert_called_once()


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
def extra_contracts():
    for fn in SCENARIOS:
        fn()
        print('PASS', fn.__name__)


if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
