"""'Get the dishwasher fixed': one tool opens the thread and the mission and
holds the thread as focus. Spec 2026-10-10 browse missions §4."""
import time

from harness import check  # noqa: F401
from services import storage, threads, missions, triage, situations, agent_tools_v2 as tools, agent_router

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child'}


def _reset():
    for t in (storage.threads_table, storage.missions_table, storage.mission_steps_table, storage.members_table,
              storage.app_state_table, storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7}
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def scenario_opens_thread_and_mission_and_focus():
    _reset()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    check(res['status'] == 'success' and res['thread_id'] and res['mission_id'], f"opened: {res}")
    t = storage.get_thread(res['thread_id'])
    check(t['title'] == 'get the dishwasher fixed' and t['owner_member_id'] == 'mom' and t['goal'] == 'get the dishwasher fixed', f"the thread: {t}")
    m = storage.get_mission(res['mission_id'])
    check(m['origin_kind'] == 'thread' and m['origin_ref'] == res['thread_id'] and m['created_by'] == 'mom' and m['status'] == 'running', f"the mission: {m}")
    f = triage.get_focus('voice:1')
    check(f and f['kind'] == 'thread' and f['id'] == res['thread_id'], "the thread is the focus")
    check(res['message'].startswith('On it.'), f"the reply: {res['message']}")
    res = tools.start_mission_for('fix the fence', title='Back fence', acting_member=MOM, focus_key='voice:1')
    check(storage.get_thread(res['thread_id'])['title'] == 'Back fence', "a given title is used")


def scenario_a_running_mission_is_not_duplicated():
    _reset()
    first = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    again = tools.start_mission_for('get the dishwasher fixed please', acting_member=MOM, focus_key='voice:2')
    check(again['status'] == 'success' and again.get('mission_id') == first['mission_id'] and 'already' in again['message'].lower(), f"named, not duplicated: {again}")
    check(len(storage.get_missions()) == 1 and len(storage.get_threads()) == 1, "one of each")
    check(triage.get_focus('voice:2')['id'] == first['thread_id'], "the second conversation's focus is the same thread")


def scenario_gates():
    _reset()
    check(tools.start_mission_for('x', acting_member=KID)['status'] == 'error', "a child is refused")
    check(tools.start_mission_for('x', acting_member=None)['status'] == 'error', "no actor is refused")
    storage.get_settings = lambda: {'missions_enabled': False, 'thread_stall_days': 7}
    res = tools.start_mission_for('x', acting_member=MOM)
    check(res['status'] == 'error' and 'off' in res['message'].lower() and not storage.get_threads(), "missions off: no thread opened either")


def scenario_declared_dispatched_terminal():
    decl = {t['name'] for t in tools.get_available_tools()}
    # Front door slice 1: start_mission_for left the chat declaration (start_project is the one door) but stays in the registry for plans.
    check('start_mission_for' not in decl and 'start_mission_for' in tools.TOOL_HANDLERS and 'start_mission_for' in tools.TOOL_SCHEMAS, "registry only")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"start_project"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal")
    _reset()
    # Production voice supplies source + a server-verified VoiceContext. A
    # voice: focus key alone is an identity-free admin call (spec 4.4/4.5).
    from services import voice_identity as identity
    import uuid
    storage.add_member({'id': 'alex', 'name': 'Alex', 'role': 'adult'})
    settings = {**storage.get_settings(), 'service_token': 'followup-b-service'}
    storage.get_settings = lambda: settings
    identity.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': 'kitchen', 'enabled': True}])
    storage.set_member_pin('alex', '1234')

    def context():
        return identity.context({'ha_instance_id': 'ha', 'satellite_id': 'kitchen',
                                 'observed_at': time.time(), 'request_id': uuid.uuid4().hex}, True)

    identity.intercept("It's Alex", context())
    identity.intercept('My PIN is 1234', context())
    ctx = context()
    check((ctx.verified_member() or {}).get('id') == 'alex', 'real PIN-verified adult speaker')
    from services import projects
    private = projects.create({'title': 'SECRET repair plan', 'goal': 'get the dishwasher fixed',
                               'owner_member_id': 'alex', 'audience': 'private'},
                              storage.get_member('alex'))['project']
    private_thread = threads.create('SECRET repair correspondence', owner_member_id='alex',
                                    created_by='alex', project_id=private['id'])
    storage.update_thread(private_thread, {'voice_shared': True})
    triage.set_focus('voice:9', 'thread', private_thread, 'SECRET repair correspondence')
    orig = agent_router.call_gemma_with_fallback
    n = {'i': 0}

    def fake(prompt, tools_, system):
        check('SECRET repair' not in prompt + system, 'verified voice still reads as HOUSE (spec 4.5)')
        n['i'] += 1
        return {'tool_calls': [{'name': 'start_project', 'arguments': {'goal': 'get the dishwasher fixed',
                'subject_kind': 'thread', 'subject_id': private_thread}}], 'message': ''} if n['i'] == 1 else {'tool_calls': [], 'message': ''}
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request('get the dishwasher fixed', source='voice',
                                                 voice_context=ctx, focus_key='voice:9')
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(res['message'].startswith('Started a project'), f"verified voice opens a project: {res}")
    project = storage.get_project(triage.get_focus('voice:9')['id'])
    check(project['owner_member_id'] == 'alex' and project['audience'] == 'household',
          f"the project belongs to the verified speaker: {project}")
    mission = storage.get_missions()[0]
    check(mission['created_by'] == 'alex', 'planning runs for the verified speaker')
    check(missions.subject_of(mission)[:2] == ('project', project['id']),
          'the verified speaker cannot bind their private thread into room planning')
    check('SECRET repair' not in res['message'], 'no private words are read aloud')


def scenario_identity_free_non_voice_starts_household_project():
    _reset()
    from unittest.mock import patch
    reply = {'tool_calls': [{'name': 'start_project', 'arguments': {'goal': 'repair the garage'}}], 'message': ''}
    with patch.object(agent_router, 'call_gemma_with_fallback', return_value=reply):
        res = agent_router.process_agent_request('repair the garage', focus_key='voice:legacy')
    check(res['message'].startswith('Started a project'), f"identity-free start remains available: {res}")
    project = storage.get_project(triage.get_focus('voice:legacy')['id'])
    check(project['owner_member_id'] == situations.parent_of_record()['id']
          and project['audience'] == 'household', 'Follow-up B: parent owns the household project')
    check(any(m['project_id'] == project['id'] for m in storage.get_missions()),
          'identity-free call creates planning inside the household project')


SENT = []


def _dm_capture():
    SENT.clear()
    missions._post = lambda dm, argyle, body, card=None: SENT.append(body) or {'id': 'm'}


def scenario_ask_user_dms_the_question():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Send me a photo of the label inside the door.'}
    missions.step(storage.get_mission(res['mission_id']))
    check(SENT and 'photo of the label' in SENT[-1] and 'thread card' in SENT[-1].lower(), f"the question reaches the person with the way to answer: {SENT}")


def scenario_finish_lands_on_the_thread_with_a_prefilled_next_step():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {}, 'result_json': {'outcome': 'done', 'text': 'x', 'turns': 3}})
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Bodewell can come Tue Oct 20 8-noon; trip charge $114.95.',
                                         'next_action': 'Book Tue Oct 20, 8-noon ($114.95 trip charge)', 'next_action_at': '2026-10-17'}
    missions.step(storage.get_mission(mid))
    t = storage.get_thread(tid)
    last = [h for h in t['history'] if h['kind'] == 'mission'][-1]
    check('$114.95' in last['text'] and last['next_action'].startswith('Book Tue') and last['mission_id'] == mid, f"the note: {last}")
    check(t['next_action'].startswith('Book Tue') and t['next_action_at'] == '2026-10-17', f"the thread's next step is set: {t['next_action']}")
    check(SENT and '$114.95' in SENT[-1] and 'Nothing is booked' in SENT[-1] and 'Book Tue' in SENT[-1], f"the DM: {SENT[-1]}")
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['id'] == 'advance:mission' and s['next_step']['label'].startswith('Book Tue')
          and s['next_step']['payload']['next_action'].startswith('Book Tue'), f"the card leads with the pre-filled step: {s['next_step']}")
    check(triage.tier(s) == 1, "a finished mission's thread ranks tier 1")


def scenario_finish_without_next_action():
    _reset(); _dm_capture()
    res = tools.start_mission_for('fix the fence', acting_member=MOM)
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Two quotes found; both need a site visit.'}
    missions.step(storage.get_mission(res['mission_id']))
    t = storage.get_thread(res['thread_id'])
    check([h for h in t['history'] if h['kind'] == 'mission'] and t['next_action'] == "Read Argyle's summary", f"a default next step: {t['next_action']}")
    check(SENT and 'Two quotes' in SENT[-1] and 'Nothing is booked' not in SENT[-1], "no browse touched a site: no booking line")


def scenario_finish_on_a_closed_thread():
    _reset(); _dm_capture()
    res = tools.start_mission_for('fix the fence', acting_member=MOM)
    threads.close(res['thread_id'], 'done', who='mom')
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Done anyway.', 'next_action': 'Call them'}
    missions.step(storage.get_mission(res['mission_id']))
    t = storage.get_thread(res['thread_id'])
    check(t['state'] == 'done' and [h for h in t['history'] if h['kind'] == 'mission'] and t.get('next_action') != 'Call them', "the note lands; the closed thread is not reopened or advanced")
    check(SENT and 'closed' in SENT[-1].lower(), f"the DM says the thread was closed: {SENT[-1]}")


def scenario_thread_card_carries_its_missions_question():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Which Friday works?'}
    missions.step(storage.get_mission(mid))
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['verb'] == 'answer' and s['next_step']['id'] == f'answer:mission:{mid}' and 'Which Friday' in s['next_step']['label'], f"the thread leads with the mission's question: {s['next_step']}")
    check(triage.tier(s) == 0, "a thread waiting on the person's answer is tier 0")
    out = tools.act_on_situation(verb='answer', text='the 17th', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', f"'tell the mission' through the thread focus: {out}")
    last = storage.get_mission_steps(mid)[-1]
    check(last['name'] == 'user_answer' and last['result_json']['text'] == 'the 17th', "the answer is on the transcript")


def scenario_thread_card_carries_its_missions_release():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7, 'contact_first_name': 'Jeff'}
    missions._browse_async = False
    missions._browse = lambda **kw: {'outcome': 'needs_release', 'text': 'wants first_name', 'learned': {}, 'stopped_at': 'https://bodewell.com/f',
                                     'wanted_fields': ['first_name'], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    s = situations.view('thread', tid, MOM)
    ask_id = [st for st in storage.get_mission_steps(mid) if st['kind'] == 'ask'][-1]['id']
    ids = [o['id'] for o in s['options'] if o['verb'] == 'release']
    check(ids == [f'release:mission:{mid}:{ask_id}:approve', f'release:mission:{mid}:{ask_id}:decline', f'release:mission:{mid}:{ask_id}:stop'], f"the thread carries the release: {ids}")
    seq = [{'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': 'u', 'wanted_fields': [], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}]
    missions._browse = lambda **kw: seq.pop(0)
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:{ask_id}:approve', actor=MOM)
    check(out['status'] == 'success' and storage.get_mission(mid)['status'] == 'running' and storage.get_mission(mid)['releases'], f"approve through the thread card: {out}")


def scenario_answer_when_not_waiting_is_a_steer():
    """2026-10-14: a mission that is running can be told something ('use the
    manufacturer instead'); through the thread focus it lands as a user_steer
    note the planner reads next step, and the mission keeps running (it used
    to be refused as 'not on the table'; see tests/test_mission_steer.py)."""
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    out = tools.act_on_situation(verb='answer', text='use the official manufacturer service', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'success', f"a running mission takes a steer: {out}")
    steps = storage.get_mission_steps(res['mission_id'])
    check([s for s in steps if s['name'] == 'user_steer'] and not [s for s in steps if s['name'] == 'user_answer'], "a steer, not an answer")
    check(storage.get_mission(res['mission_id'])['status'] == 'running', "still running")


def scenario_e2e_get_the_dishwasher_fixed():
    """Spec acceptance 1, with every outside call faked."""
    _reset(); _dm_capture()
    from services import mail_search
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k', 'thread_stall_days': 7,
                                    'ingest_email_host': 'h', 'ingest_email_user': 'u', 'ingest_email_password': 'p',
                                    'contact_first_name': 'Jeff', 'contact_last_name': 'Wilson', 'contact_email': 'ffejnosliw@gmail.com',
                                    'contact_phone': '919-327-7497', 'contact_street': '1 Chestnut Walk', 'contact_city': 'Cary', 'contact_state': 'NC', 'contact_zip': '27519',
                                    'missions_captcha_attempts': True}
    mail_search.search = lambda q, since_days=365, limit=5, settings=None: {'status': 'success', 'hits': [{'uid': 1, 'from': 'orders@cafeappliances.com', 'date': '2021-03-14', 'subject': 'Your Cafe order', 'snippet': 'Model CDT805P2N3S1'}]}
    threads._pool_call = lambda tier, key, system, prompt, **kw: {'text': 'Serial LS758759B'}
    missions._browse_async = False
    reports = [
        {'outcome': 'needs_release', 'text': 'the form wants contact details', 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
         'wanted_fields': ['first_name', 'last_name', 'email', 'phone', 'street', 'city', 'state', 'zip'], 'turns': 9, 'tokens_in': 80000, 'tokens_out': 2000, 'seconds': 90, 'screenshots': [], 'filled': {}},
        {'outcome': 'captcha_failed', 'text': '3 attempts at the human-verification check failed', 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
         'wanted_fields': [], 'turns': 6, 'tokens_in': 50000, 'tokens_out': 1000, 'seconds': 60, 'screenshots': [], 'filled': {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'}},
    ]
    missions._browse = lambda **kw: reports.pop(0)
    plan = [
        {'action': 'tool', 'tool': 'search_mail', 'args': {'query': 'cafe dishwasher'}},
        {'action': 'ask_user', 'question': 'Send me a photo of the label inside the door.'},
        {'action': 'browse', 'goal': 'find appointment windows and the trip charge for a dishwasher repair', 'site': 'bodewell.com'},
        {'action': 'finish', 'summary': 'Bodewell can come Tue Oct 20, 8-noon; trip charge $114.95, parts and labor extra.',
         'next_action': 'Book Tue Oct 20, 8-noon ($114.95 trip charge)', 'next_action_at': '2026-10-17'},
    ]
    missions._llm = lambda m, s, u, st: plan.pop(0)
    # 1. voice opens it
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    # 2. the mail is found, the photo asked for
    missions.step(storage.get_mission(mid))
    steps = storage.get_mission_steps(mid)
    check(any(st['kind'] == 'tool' and st['name'] == 'search_mail' and 'CDT805P2N3S1' in str(st['result_json']) for st in steps), f"the mail was searched: {steps}")
    missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'waiting_user' and 'photo' in SENT[-1].lower(), "asks for the photo")
    PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8ff1f0003030200f0b3c2d10000000049454e44ae426082')
    threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(storage.get_mission(mid)['status'] == 'running', "the photo answers it")
    # 3. the browse stops for the release; the parent approves from the thread
    missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'waiting_user' and 'bodewell.com' in SENT[-1] and 'Jeff' in SENT[-1], "the release card")
    ask_id = [st for st in storage.get_mission_steps(mid) if st['kind'] == 'ask'][-1]['id']
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:{ask_id}:approve', actor=MOM)
    check(out['status'] == 'success', f"approved: {out}")
    # 4. the resumed browse fails the CAPTCHA -> hand-off
    m = storage.get_mission(mid)
    check(m['status'] == 'waiting_user' and 'bodewell.com' in SENT[-1] and 'first_name=Jeff' in SENT[-1] and 'tell me what you found' in SENT[-1].lower(), f"the hand-off: {SENT[-1]}")
    # 5. the person answers in words; the mission finishes
    out = tools.act_on_situation(verb='answer', text='Tue 20th 8-noon, $114.95 trip charge', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'success', f"answered: {out}")
    missions.step(storage.get_mission(mid))
    m = storage.get_mission(mid)
    t = storage.get_thread(tid)
    check(m['status'] == 'done' and t['next_action'].startswith('Book Tue') and '$114.95' in SENT[-1] and 'Nothing is booked' in SENT[-1], f"finished: {m['status']} / {t['next_action']} / {SENT[-1]}")
    check(not storage.get_action_proposals(), "nothing proposed, nothing booked")


def scenario_cached_argyle_note_never_hides_the_missions_ask():
    """Review C1: in production the thread carries Argyle's cached next steps
    (note_rev == rev); the mission's ask must still lead, and the ask must
    bump the thread so its note is re-asked for."""
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    before = storage.get_thread(tid)
    storage.update_thread(tid, {'note_rev': before.get('rev') or 0, 'note_source': 'argyle', 'status_note': 'Waiting on the repair shop.',
                                'next_steps': [{'id': 'advance:argyle:0', 'label': 'Call Bodewell', 'verb': 'advance', 'payload': {'next_action': 'Call Bodewell'}}]})
    missions._llm = lambda m, s, u, st: {'action': 'ask_user', 'question': 'Which Friday works?'}
    missions.step(storage.get_mission(mid))
    after = storage.get_thread(tid)
    check((after.get('rev') or 0) > (before.get('rev') or 0), "the ask moved the thread (its note is re-asked for)")
    # Even with a note that still matches, the ask leads.
    storage.update_thread(tid, {'note_rev': after.get('rev') or 0})
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['id'] == f'answer:mission:{mid}' and 'Which Friday' in s['next_step']['label'], f"the question leads over the cached suggestion: {s['next_step']}")
    check(triage.tier(s) == 0, f"tier 0, not the cached note's rank: {triage.tier(s)}")
    check(s['next_step']['payload'].get('ask') == 'question', "the option says what kind of ask it is (the card shows a question to a child, never a hand-off's filled values)")


def scenario_thread_missions_endpoint_is_parent_only():
    """Review C2: a child who owns the thread may see the thread, never the
    mission's transcript (mail results, released values)."""
    _reset(); _dm_capture()
    import main
    tid = threads.create("Kate's science fair", owner_member_id='kid', created_by='mom')
    mid = storage.add_mission({'goal': 'supplies', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'q', 'site': 's', 'fields': ['phone'], 'values': {'phone': '919-327-7497'}}})
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    client = TestClient(main.app)
    tokens = {member: {'X-Member-Token': storage.create_member_token(member)} for member in ('kid', 'mom')}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        # Both a parent's mission and the child's own mission stay WRITE_ROLES
        # reading. Exercise middleware and real token resolution, not a resolver stub.
        for creator in ('mom', 'kid'):
            storage.update_mission(mid, {'created_by': creator})
            response = client.get(f'/api/threads/{tid}/missions', headers=tokens['kid'])
            check(response.status_code == 403 and response.json() == {'detail': 'Not yours to see'},
                  f"the owner child is refused the transcript: {response.status_code} {response.text}")
            detail = client.get(f'/api/missions/{mid}', headers=tokens['kid'])
            check(detail.status_code == 404 and '919-327-7497' not in detail.text,
                  f"a child creator cannot read a mission by id: {detail.status_code} {detail.text}")
            response = client.get(f'/api/threads/{tid}/missions', headers=tokens['mom'])
            check(response.status_code == 200, f"a parent reads it: {response.text}")
            out = response.json()
            check(out['missions'] and out['missions'][0]['steps'], "a parent reads the transcript")
            check('919-327-7497' in response.text, 'parent positive control includes the released value')


def scenario_launch_refused_opens_no_thread_and_launch_mission_defers():
    """Review I1/I2: a capped or keyless launch opens no orphan thread; the
    older launch_mission tool points a new goal at start_mission_for."""
    _reset(); _dm_capture()
    from datetime import date
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {'launch': 3})
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM)
    check(res['status'] == 'error' and 'cap' in res['message'].lower() and not storage.get_threads(), f"capped: no thread: {res} {storage.get_threads()}")
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    storage.get_settings = lambda: {'missions_enabled': True, 'thread_stall_days': 7}
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM)
    check(res['status'] == 'error' and 'key' in res['message'].lower() and not storage.get_threads(), f"no paid key: no thread: {res}")
    desc = next(t for t in tools.get_available_tools() if t['name'] == 'launch_mission')['description']
    check('start_project' in desc and 'existing thread' in desc.lower(), "launch_mission says when start_project is the one to use")
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7}
    out = tools.launch_mission('get the dishwasher fixed', actor=MOM)
    check(out.get('thread_id') and storage.get_threads() and storage.get_missions()[0]['origin_kind'] == 'thread', f"launch_mission with no thread named opens a thread like start_mission_for: {out}")


def scenario_release_label_carries_the_values_and_a_handoff_names_its_kind():
    """Review I3: the card's Share button shows what leaves the house; the
    hand-off option is marked so the card can draw its link."""
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7, 'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com'}
    missions._browse_async = False
    missions._browse = lambda **kw: {'outcome': 'needs_release', 'text': 'x', 'learned': {}, 'stopped_at': 'https://bodewell.com/f',
                                     'wanted_fields': ['first_name', 'email'], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    for kind, sid in (('mission', mid), ('thread', tid)):
        s = situations.view(kind, sid, MOM)
        check(s['next_step']['verb'] == 'release' and 'Jeff' in s['next_step']['label'] and 'ffejnosliw@gmail.com' in s['next_step']['label'],
              f"the {kind} card's Share shows the exact values: {s['next_step']['label']}")
    missions.release(mid, 'decline', MOM, ask_id=[st for st in storage.get_mission_steps(mid) if st['kind'] == 'ask'][-1]['id'])
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['verb'] == 'answer' and s['next_step']['payload'].get('ask') == 'handoff' and 'https://bodewell.com/f' in s['next_step']['label'],
          f"the hand-off lead is marked and carries its link: {s['next_step']}")


def scenario_a_follow_up_on_the_focus_thread_reuses_it():
    """2026-10-11: after the first mission finished, "get available times and
    pricing for me" opened nothing useful. A new goal said while a thread is
    the focus, with no live mission on it, is a new mission ON THAT THREAD."""
    _reset(); _dm_capture()
    first = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    storage.update_mission(first['mission_id'], {'status': 'done'})
    again = tools.start_mission_for('get available times and pricing for my home', acting_member=MOM, focus_key='voice:1')
    check(again['status'] == 'success' and again['thread_id'] == first['thread_id'] and again['mission_id'] != first['mission_id'],
          f"the focus thread carries the new mission: {again}")
    m = storage.get_mission(again['mission_id'])
    check(m['origin_kind'] == 'thread' and m['origin_ref'] == first['thread_id'] and m['goal'].startswith('get available'), f"on the thread: {m}")
    check(len(storage.get_threads()) == 1, "no second thread")
    # A different conversation with no focus and no matching thread still opens its own.
    other = tools.start_mission_for('clean the gutters', acting_member=MOM, focus_key='voice:2')
    check(other['thread_id'] != first['thread_id'], "an unrelated goal gets its own thread")


def scenario_the_model_is_told_argyle_acts_on_websites():
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('start_project' in src and 'never say' in src.lower() and 'website' in src.lower(),
          "the router's prompt says Argyle browses and fills forms inside projects and never denies it")
    desc = next(t for t in tools.get_available_tools() if t['name'] == 'start_project')['description']
    check('enter' in desc.lower() and 'pricing' in desc.lower(), f"the tool description names the web-form case: {desc}")


def scenario_a_release_is_a_tap_never_the_models_word():
    """2026-10-11: with the thread in focus and "enter my information" in the
    person's message, the chat model called act_on_situation(verb='release')
    and the tool picked the highlighted option, Share. The family's details
    left the house on the model's say-so. Through the agent tool the release
    verb is refused; the card's own path (situations.act) still works."""
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7, 'contact_zip': '27523'}
    missions._browse_async = False
    missions._browse = lambda **kw: {'outcome': 'needs_release', 'text': 'wants zip', 'learned': {}, 'stopped_at': 'https://repair.geappliances.com/x',
                                     'wanted_fields': ['zip'], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'repair.geappliances.com'}
    missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'waiting_user', "waiting on the release")
    ask_id = [st for st in storage.get_mission_steps(mid) if st['kind'] == 'ask'][-1]['id']
    for kwargs in ({'verb': 'release'}, {'verb': 'release', 'option_id': f'release:mission:{mid}:{ask_id}:approve'},
                   {'verb': 'release', 'ref': mid, 'kind': 'mission', 'option_id': f'release:{ask_id}:approve'}):
        out = tools.act_on_situation(acting_member=MOM, focus_key='voice:1', **kwargs)
        check(out['status'] == 'error' and 'tap' in out['message'].lower() and 'share' in out['message'].lower(), f"refused with where to tap: {kwargs} -> {out}")
    row = storage.get_mission(mid)
    check(row['status'] == 'waiting_user' and not row.get('releases'), "nothing was shared, the mission still waits")
    # The person's own tap (the card, the transcript, the endpoint) is the only yes.
    seq = [{'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': 'u', 'wanted_fields': [], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}]
    missions._browse = lambda **kw: seq.pop(0)
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:{ask_id}:approve', actor=MOM)
    check(out['status'] == 'success' and storage.get_mission(mid).get('releases'), f"the tap shares: {out}")
    desc = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['description']
    check('release' in desc.lower() and 'tap' in desc.lower(), "the tool's description says a release is a tap")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('tap Share' in src or 'tap share' in src.lower(), "the router's standing rule says a release is the person's tap")


def scenario_the_dishwasher_is_booked_on_a_tap():
    """Spec 2026-10-11: after the slots are read the browse asks, the parent taps Book it, the attempt lands,
    the resumed browse confirms, the mission finishes Booked; nothing proposed, nothing paid."""
    _reset(); _dm_capture()
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7, 'missions_submit_enabled': True,
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519'}
    missions._browse_async = False
    res = tools.start_mission_for('Get availability and pricing for GE Bodewell service for a 2021 GE Cafe dishwasher and book the earliest slot', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    rec = {'button': 'Book appointment', 'url': 'https://www.bodewell.com/schedule', 'intent': 'book Tue',
           'state': {'fields': {}, 'selected': ['Tue, Oct 20 8AM-12PM'], 'text': 'Trip charge $114.95 Tue, Oct 20 8AM-12PM', 'text_sha': 'c' * 64, 'prices': ['$114.95']},
           'display': 'Trip charge $114.95', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}}
    runs = []

    def fake(**kw):
        runs.append(kw)
        base = {'learned': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}, 'stopped_at': rec['url'], 'wanted_fields': [], 'turns': 9, 'tokens_in': 1, 'tokens_out': 1,
                'seconds': 1, 'screenshots': [], 'filled': {'first_name': 'Jeff'}, 'submit': None, 'attempt': None, 'changed': [], 'attempts_extra': []}
        if kw.get('approved'):
            ok = kw['on_attempt']({'ask_id': kw['approved']['ask_id'], 'button': 'Book appointment', 'url': rec['url'], 'state': rec['state'], 'pressed_at': time.time(), 'outcome': None, 'text': ''})
            assert ok, "the engine must authorize the press"
            return {**base, 'outcome': 'submitted', 'text': 'CONFIRMED: Confirmation number 12345',
                    'attempt': {**kw['approved'], 'pressed_at': time.time(), 'outcome': 'confirmed', 'text': 'Confirmation number 12345'}}
        return {**base, 'outcome': 'needs_submit', 'text': 'Book appointment', 'submit': rec}
    missions._browse = fake
    plan = [{'action': 'browse', 'goal': 'find the slots and the fee, then book the earliest', 'site': 'bodewell.com'},
            {'action': 'finish', 'summary': 'Bodewell comes Tue Oct 20 8-12; trip charge $114.95.', 'next_action': 'Be home Tue Oct 20 8-12', 'next_action_at': '2026-10-20'}]
    missions._llm = lambda m, s, u, st: plan.pop(0)
    row = missions.step(storage.get_mission(mid))
    ask = storage.get_mission_steps(mid)[-1]
    check(row['status'] == 'waiting_user' and ask['name'] == 'submit' and ask['result_json']['question'].startswith('Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95'), f"the ask: {ask['result_json']['question']}")
    check(SENT[-1].endswith("Tap the booking question here, on the Missions page or the thread card to approve it, or I'll finish it myself / Stop there."), f"the DM: {SENT[-1]}")
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['label'].startswith('Book at bodewell.com') and s['next_step']['id'] == f"submit:mission:{mid}:{ask['id']}:approve", f"the thread card leads with the whole question, never a blind Book it: {s['next_step']}")
    res = situations.act('thread', tid, 'submit', option_id=s['next_step']['id'], actor=MOM)
    check(res['status'] == 'success' and len(runs) == 2 and runs[1]['approved']['ask_id'] == ask['id'], f"Book it resumed the browse with the record: {res}")
    atts = missions.attempts_for(mid)
    check(len(atts) == 1 and atts[0]['outcome'] == 'confirmed', f"one attempt, confirmed: {atts}")
    check(storage.get_mission(mid)['status'] == 'running', "the planner runs on")
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'done', f"finished: {row['status']}")
    check('Booked: Tue, Oct 20 8AM-12PM, $114.95, confirmation 12345' in SENT[-1] and 'Nothing is booked' not in SENT[-1], f"the finish says Booked: {SENT[-1]}")
    t = storage.get_thread(tid)
    check(t['next_action_at'] == '2026-10-20' and 'Booked:' in [h for h in t['history'] if h['kind'] == 'mission'][-1]['text'], "the thread's next step is the appointment")
    check(not [st for st in storage.get_mission_steps(mid) if st['kind'] == 'proposal'], "nothing proposed")
    check(all('payment' not in ((st.get('result_json') or {}).get('text') or '') for st in storage.get_mission_steps(mid) if st['kind'] == 'browse'), "nothing paid")


SCENARIOS = [scenario_opens_thread_and_mission_and_focus, scenario_a_running_mission_is_not_duplicated, scenario_gates,
             scenario_declared_dispatched_terminal, scenario_identity_free_non_voice_starts_household_project,
             scenario_ask_user_dms_the_question, scenario_finish_lands_on_the_thread_with_a_prefilled_next_step,
             scenario_finish_without_next_action, scenario_finish_on_a_closed_thread,
             scenario_thread_card_carries_its_missions_question, scenario_thread_card_carries_its_missions_release,
             scenario_answer_when_not_waiting_is_a_steer,
             scenario_cached_argyle_note_never_hides_the_missions_ask, scenario_thread_missions_endpoint_is_parent_only,
             scenario_launch_refused_opens_no_thread_and_launch_mission_defers,
             scenario_release_label_carries_the_values_and_a_handoff_names_its_kind,
             scenario_a_follow_up_on_the_focus_thread_reuses_it, scenario_the_model_is_told_argyle_acts_on_websites,
             scenario_a_release_is_a_tap_never_the_models_word,
             scenario_e2e_get_the_dishwasher_fixed, scenario_the_dishwasher_is_booked_on_a_tap]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
