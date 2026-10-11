"""'Get the dishwasher fixed': one tool opens the thread and the mission and
holds the thread as focus. Spec 2026-10-10 browse missions §4."""
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
    check('start_mission_for' in decl and 'start_mission_for' in tools.TOOL_HANDLERS and 'start_mission_for' in tools.TOOL_SCHEMAS, "registry")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"start_mission_for"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal")
    _reset()
    orig = agent_router.call_gemma_with_fallback
    n = {'i': 0}

    def fake(prompt, tools_, system):
        n['i'] += 1
        return {'tool_calls': [{'name': 'start_mission_for', 'arguments': {'goal': 'get the dishwasher fixed'}}], 'message': ''} if n['i'] == 1 else {'tool_calls': [], 'message': ''}
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request('get the dishwasher fixed', focus_key='voice:9')
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(res['message'].startswith('On it.') and storage.get_missions()[0]['created_by'] == 'mom', f"voice opens it as the parent of record: {res}")


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
    ids = [o['id'] for o in s['options'] if o['verb'] == 'release']
    check(ids == [f'release:mission:{mid}:approve', f'release:mission:{mid}:decline', f'release:mission:{mid}:stop'], f"the thread carries the release: {ids}")
    seq = [{'outcome': 'done', 'text': 'ok', 'learned': {}, 'stopped_at': 'u', 'wanted_fields': [], 'turns': 1, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}]
    missions._browse = lambda **kw: seq.pop(0)
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:approve', actor=MOM)
    check(out['status'] == 'success' and storage.get_mission(mid)['status'] == 'running' and storage.get_mission(mid)['releases'], f"approve through the thread card: {out}")


def scenario_answer_when_not_waiting_is_refused():
    _reset(); _dm_capture()
    res = tools.start_mission_for('get the dishwasher fixed', acting_member=MOM, focus_key='voice:1')
    out = tools.act_on_situation(verb='answer', text='yes', acting_member=MOM, focus_key='voice:1')
    check(out['status'] == 'error' and 'not on the table' in out['message'], f"nothing to answer: {out}")
    check(not [s for s in storage.get_mission_steps(res['mission_id']) if s['name'] == 'user_answer'], "nothing appended")


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
    out = situations.act('thread', tid, 'release', option_id=f'release:mission:{mid}:approve', actor=MOM)
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


SCENARIOS = [scenario_opens_thread_and_mission_and_focus, scenario_a_running_mission_is_not_duplicated, scenario_gates,
             scenario_declared_dispatched_terminal,
             scenario_ask_user_dms_the_question, scenario_finish_lands_on_the_thread_with_a_prefilled_next_step,
             scenario_finish_without_next_action, scenario_finish_on_a_closed_thread,
             scenario_thread_card_carries_its_missions_question, scenario_thread_card_carries_its_missions_release,
             scenario_answer_when_not_waiting_is_refused, scenario_e2e_get_the_dishwasher_fixed]

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
