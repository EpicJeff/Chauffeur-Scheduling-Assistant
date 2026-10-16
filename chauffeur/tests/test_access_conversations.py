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
        check(anon['surface'] == {'kind': 'panel', 'owner': 'anon-panel'}, 'member-only panel fallback')
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
const document = {getElementById:id=>id==='chat-messages'?box:id==='chat-input'?input:{},
 addEventListener(){}, createElement(){return {remove(){}}}};
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
 await loadChatHistory();
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
const window = {chfBase:'/', chfAuthUrl:u=>u+'&member_token=member-credential'};
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
    r = subprocess.run(['node', '-e', js], text=True, capture_output=True)
    check(r.returncode == 0, f'panel widget runtime: {r.stdout}\n{r.stderr}')


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
