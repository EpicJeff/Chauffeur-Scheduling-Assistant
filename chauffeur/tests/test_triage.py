"""Sub-project 3: one rank across the four kinds, one spoken sentence, focus
held per conversation, voice as the parent of record. Spec:
docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §1."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, triage, threads

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.threads_table, storage.missions_table,
              storage.mission_steps_table, storage.assist_contacts_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.conversations_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _finding(line, severity, due_in_hours, fid):
    due = (NOON + datetime.timedelta(hours=due_in_hours))
    return storage.add_finding({'identity': f'unassigned:{fid}', 'kind': 'unassigned', 'severity': severity,
                                'line': line, 'subject_type': 'event', 'subject_id': fid,
                                'due_at': due.timestamp(), 'state': 'open'})


def scenario_rank_tiers_across_four_kinds():
    _reset()
    _finding('No driver: soccer today', 'decide', 6, 'ev-soon')          # tier 0: due within 24h
    _finding('No driver: recital next week', 'decide', 24 * 6, 'ev-late')  # tier 1
    _finding('Approve the swap', 'approve', 24 * 2, 'ev-appr')             # tier 2
    _finding('FYI: bus late', 'fyi', 24 * 2, 'ev-fyi')                     # tier 4
    storage.add_mind_insight({'slug': 'i', 'line': 'Thursday is tight', 'category': 'c', 'approach': 'ask Sarah',
                              'identity': 'c:1', 'confidence': 0.8})      # tier 3
    overdue = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                             next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')  # tier 0
    quiet = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    storage.update_thread(quiet, {'created_at': time.time() - 9 * 86400})                                              # tier 1 (quiet)
    mid = storage.add_mission({'goal': 'Find a sitter', 'status': 'waiting_user', 'created_by': 'mom'})                # tier 0
    rows = situations.list_situations(MOM)
    ranked = triage.triage_rank(rows)
    titles = [s['title'] for s in ranked]
    tiers = [triage.tier(s) for s in ranked]
    check(tiers == sorted(tiers), f"tiers are non-decreasing: {list(zip(titles, tiers))}")
    check(set(titles[:3]) == {'No driver: soccer today', 'Pest control', 'Find a sitter'},
          f"tier 0 is the due-today ride, the overdue thread and the waiting mission: {titles[:3]}")
    check(titles.index('No driver: recital next week') < titles.index('Approve the swap') < titles.index('Thursday is tight')
          < titles.index('FYI: bus late'), f"decide, then approve, then insight, then fyi: {titles}")
    check(titles.index('Gutters') < titles.index('Approve the swap'), "a quiet thread outranks an approve finding")


def scenario_spoken_sentence_per_kind():
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    fid = _finding('No driver yet: Soccer Thu 4:00', 'decide', 30, 'ev1')
    s = situations.view('finding', fid, MOM)
    line = triage.spoken(s)
    check(line.startswith('No driver yet: Soccer Thu 4:00.') and 'Next: ' in line, f"title then next step: {line}")
    storage.update_finding(fid, {'status_note': 'Mike was asked and said no.', 'note_source': 'argyle',
                                 'note_rev': storage.get_finding(fid).get('rev') or 0})
    s = situations.view('finding', fid, MOM)
    check('Mike was asked and said no.' in triage.spoken(s), "Argyle's note is spoken when it is hers")
    storage.update_finding(fid, {'note_source': 'fallback'})
    s = situations.view('finding', fid, MOM)
    check('Mike was asked' not in triage.spoken(s), "a fallback note is never spoken as hers")
    from services import asks
    asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate Thursday', 'text', 'mom', draft_mode='template')
    s = situations.view('finding', fid, MOM)
    check('asked Sarah by text' in triage.spoken(s) and 'not sent yet' in triage.spoken(s), f"the ask clause: {triage.spoken(s)}")
    tid = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    s = situations.view('thread', tid, MOM)
    check(triage.spoken(s).startswith('Pest control.'), f"a thread speaks its title: {triage.spoken(s)}")
    check(triage.spoken(s).endswith('.'), "a sentence ends with a full stop")


def scenario_spoken_list_never_holds_a_sensitive_insight():
    _reset()
    storage.add_mind_insight({'slug': 'n', 'line': 'normal', 'category': 'c', 'approach': 'x', 'identity': 'c:1'})
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'sensitivity': 'sensitive'})
    plain = [s['title'] for s in situations.list_situations(MOM)]
    check('SECRET' in plain, "a parent's ordinary list holds the sensitive row")
    spoken = [s['title'] for s in situations.list_situations(MOM, spoken=True)]
    check('SECRET' not in spoken and 'normal' in spoken, f"a spoken list never does: {spoken}")


SCENARIOS = [scenario_rank_tiers_across_four_kinds, scenario_spoken_sentence_per_kind,
             scenario_spoken_list_never_holds_a_sensitive_insight]


def scenario_focus_set_read_and_cursor():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    b = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    storage.update_thread(b, {'created_at': time.time() - 9 * 86400})
    check(triage.get_focus('conv:1') is None, "no focus to begin with")
    first = triage.next_for(MOM, 'conv:1')
    check(first and first['id'] == a, f"the overdue thread comes first: {first and first['title']}")
    f = triage.get_focus('conv:1')
    check(f and f['kind'] == 'thread' and f['id'] == a and f['cursor'] == 0, f"focus is the first one: {f}")
    second = triage.next_for(MOM, 'conv:1', skip_current=True)
    check(second and second['id'] == b, f"'next' moves down the list: {second and second['title']}")
    check(triage.get_focus('conv:1')['cursor'] == 1, "the cursor advanced")
    third = triage.next_for(MOM, 'conv:1', skip_current=True)
    check(third is None and triage.get_focus('conv:1') is None, "the end of the list clears the focus")
    check(triage.get_focus('conv:other') is None, "another conversation has its own focus")


def scenario_focus_on_a_closed_situation_is_dropped():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    triage.next_for(MOM, 'conv:1')
    threads.close(a, 'done', who='mom')
    check(triage.get_focus('conv:1') is None, "a focus whose situation closed is gone")
    fid = _finding('No driver: soccer', 'decide', 6, 'ev1')
    triage.set_focus('conv:2', 'finding', fid, 'No driver: soccer')
    storage.update_finding(fid, {'snoozed_until': time.time() + 7 * 86400})
    check(triage.get_focus('conv:2') is None, "a snoozed focus is gone too")


def scenario_focus_entries_are_pruned_after_a_day():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    triage.set_focus('conv:old', 'thread', a, 'Pest control')
    m = dict(storage.get_app_state(triage.FOCUS_KEY) or {})
    m['conv:old']['set_at'] = time.time() - 2 * 86400
    storage.set_app_state(triage.FOCUS_KEY, m)
    triage.set_focus('conv:new', 'thread', a, 'Pest control')
    m = storage.get_app_state(triage.FOCUS_KEY) or {}
    check('conv:old' not in m and 'conv:new' in m, f"a day-old focus is pruned on the next write: {list(m)}")
    check(triage.get_focus(None) is None, "no key, no focus")
    triage.set_focus(None, 'thread', a, 'Pest control')
    check(None not in (storage.get_app_state(triage.FOCUS_KEY) or {}), "nothing is written under no key")


SCENARIOS += [scenario_focus_set_read_and_cursor, scenario_focus_on_a_closed_situation_is_dropped,
              scenario_focus_entries_are_pruned_after_a_day]

from services import agent_tools_v2 as tools  # noqa: E402


def scenario_next_situation_speaks_one_and_sets_focus():
    _reset()
    a = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    res = tools.next_situation(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res['message'].startswith('Pest control.') and 'Next: ' in res['message'],
          f"one sentence: {res}")
    check(triage.get_focus('conv:1')['id'] == a, "focus is set")
    res = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and 'Nothing else' in res['message'], f"the end of the list says so: {res}")
    storage.threads_table.truncate()
    res = tools.next_situation(acting_member=MOM, focus_key='conv:9')
    check(res['message'] == 'Nothing needs anyone right now.', f"empty: {res}")


def scenario_ref_less_tools_use_the_focus():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    storage.update_thread(tid, {'created_at': time.time() - 9 * 86400})
    res = tools.explain_situation(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'error' and 'what needs your attention' in res['message'], f"no focus: the way out: {res}")
    tools.next_situation(acting_member=MOM, focus_key='conv:1')
    res = tools.explain_situation(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res['situation']['id'] == tid, f"ref-less explain is the focus: {res}")
    res = tools.act_on_situation(verb='advance', text='email the inspector', next_action_at='2026-10-20',
                                 acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and storage.get_thread(tid)['next_action'] == 'email the inspector', f"ref-less act: {res}")
    res = tools.start_ask(to_name='the inspector', what='come Friday', channel='email', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res['ask_id'], f"ref-less ask: {res}")
    res = tools.mark_ask_sent(acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and storage.get_ask(res['ask']['id'])['state'] == 'sent', f"ref-less sent: {res}")
    res = tools.answer_ask(answer='yes', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and res.get('outcome') == 'manual', f"ref-less yes: {res}")
    other = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    tools.explain_situation('Gutters', acting_member=MOM, focus_key='conv:1')
    check(triage.get_focus('conv:1')['id'] == other, "naming a situation makes it the focus")


def scenario_ref_less_answer_with_two_live_asks_refuses():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', created_by='mom')
    triage.set_focus('conv:1', 'thread', tid, 'Deck permit')
    tools.start_ask(to_name='Sarah', what='come Friday', channel='text', acting_member=MOM, focus_key='conv:1')
    tools.start_ask(to_name='Mike', what='come Friday', channel='email', acting_member=MOM, focus_key='conv:1')
    res = tools.answer_ask(answer='yes', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'error' and 'Sarah' in res['message'] and 'Mike' in res['message'], f"two live asks: which? {res}")
    check(all(a['state'] == 'drafted' for a in storage.get_asks(situation_kind='thread', situation_id=tid)), "nothing answered")
    res = tools.answer_ask(answer='yes', acting_member=MOM, focus_key='conv:none')
    check(res['status'] == 'error', "no focus, no ask: refused plainly")


def scenario_next_situation_is_declared_and_terminal():
    decl = {t['name']: t for t in tools.get_available_tools()}
    check('next_situation' in decl, "declared to the model")
    check('next_situation' in tools.TOOL_HANDLERS and 'next_situation' in tools.TOOL_SCHEMAS, "in the registry")
    from services import agent_router
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"next_situation"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal: no concluding round")
    check('next_situation' in agent_router.PROPOSE_ONLY_READS and 'list_situations' in agent_router.PROPOSE_ONLY_READS,
          "a read on the propose-only rail")
    verb_enum = decl['act_on_situation']['parameters']['properties']['verb']['enum']
    check('unread' not in verb_enum or 'unread' in situations.VERBS, "the enum never names a verb the server lacks")


SCENARIOS += [scenario_next_situation_speaks_one_and_sets_focus, scenario_ref_less_tools_use_the_focus,
              scenario_ref_less_answer_with_two_live_asks_refuses, scenario_next_situation_is_declared_and_terminal]

from services import agent_router  # noqa: E402


def _fake_gemma(tool_call, captured=None):
    state = {'n': 0}

    def fake(prompt, tools, system_prompt):
        if captured is not None:
            captured['tools'] = [t['name'] for t in tools]
            captured['system'] = system_prompt
        state['n'] += 1
        if state['n'] == 1 and tool_call:
            return {'tool_calls': [tool_call], 'message': ''}
        # An EMPTY concluding message: the router keeps the tool's own
        # message as the reply, which is what these scenarios assert on.
        return {'tool_calls': [], 'message': ''}
    return fake


def _with_gemma(fake, fn):
    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake
    try:
        return fn()
    finally:
        agent_router.call_gemma_with_fallback = orig


def scenario_voice_acts_as_the_parent_of_record():
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    fid = _finding('No driver yet: Soccer', 'decide', 30, 'ev1')
    start = NOON + datetime.timedelta(hours=30)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    call = {'name': 'next_situation', 'arguments': {}}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('what needs my attention', focus_key='voice:1'))
    check(res['message'].startswith('No driver yet: Soccer.'), f"voice hears the ride with no identity: {res}")
    call = {'name': 'start_ask', 'arguments': {'to_name': 'Sarah', 'what': 'drive Kate Thursday', 'channel': 'text'}}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('text Sarah and ask her', focus_key='voice:1'))
    asks = storage.get_asks(situation_kind='finding', situation_id=fid)
    check(len(asks) == 1 and asks[0]['asked_by'] == 'mom', f"the ask is the parent of record's: {asks}")
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('text Sarah', focus_key='voice:1', propose_only=True))
    check(len(storage.get_asks(situation_kind='finding', situation_id=fid)) == 1, "propose-only never reaches start_ask")
    kid = {'id': 'kid', 'name': 'Kate', 'role': 'child'}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('text Sarah', source='family',
                                                                                     acting_member=kid, focus_key='channel:9'))
    check(len(storage.get_asks(situation_kind='finding', situation_id=fid)) == 1 and 'parent or adult' in res['message'],
          f"a child via @argyle is refused as today: {res}")


def scenario_voice_never_hears_a_sensitive_insight():
    _reset()
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'sensitivity': 'sensitive'})
    for name in ('next_situation', 'list_situations'):
        res = _with_gemma(_fake_gemma({'name': name, 'arguments': {}}),
                          lambda: agent_router.process_agent_request('what needs me', focus_key='voice:1'))
        check('SECRET' not in res['message'], f"{name} on voice never speaks a sensitive insight: {res}")
    res = _with_gemma(_fake_gemma({'name': 'list_situations', 'arguments': {}}),
                      lambda: agent_router.process_agent_request('what needs me', source='family', acting_member=MOM))
    check('SECRET' in res['message'], "a parent on her own phone still sees it in the list")


def scenario_focus_line_present_exactly_when_live():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    cap = {}
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', focus_key='conv:1'))
    check('FOCUS:' not in cap['system'], "no focus, no line")
    triage.set_focus('conv:1', 'thread', tid, 'Deck permit')
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', focus_key='conv:1'))
    check('FOCUS: thread "Deck permit"' in cap['system'] and 'Handle it' in cap['system'], f"the line: {cap['system'][-400:]}")
    threads.close(tid, 'done', who='mom')
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', focus_key='conv:1'))
    check('FOCUS:' not in cap['system'], "a settled focus is not injected")


def scenario_voice_without_a_conversation_has_no_focus():
    _reset()
    threads.create('Deck permit', owner_member_id='mom', next_action='call',
                   next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    res = _with_gemma(_fake_gemma({'name': 'next_situation', 'arguments': {}}),
                      lambda: agent_router.process_agent_request('what needs my attention'))
    check(res['message'].startswith('Deck permit.') and "Say 'Deck permit'" in res['message'], f"ends with the title: {res}")
    check(not storage.get_app_state(triage.FOCUS_KEY), "nothing written with no key")


SCENARIOS += [scenario_voice_acts_as_the_parent_of_record, scenario_voice_never_hears_a_sensitive_insight,
              scenario_focus_line_present_exactly_when_live, scenario_voice_without_a_conversation_has_no_focus]


def scenario_e2e_voice_ask_round_trip():
    """Spec acceptance 1: voice, no identity: triage → text Sarah → sent it →
    she said yes → applied once → the finding retires by absence."""
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'No driver yet: Soccer', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    turn = lambda call, text: _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request(text, focus_key='voice:7'))
    res = turn({'name': 'next_situation', 'arguments': {}}, 'what needs my attention')
    check(res['message'].startswith('No driver yet: Soccer.'), f"turn 1: {res}")
    res = turn({'name': 'start_ask', 'arguments': {'to_name': 'Sarah', 'what': '', 'channel': 'text'}}, 'text Sarah and ask her')
    a = storage.get_asks(situation_kind='finding', situation_id=fid)[0]
    check(a['state'] == 'drafted' and a['asked_by'] == 'mom' and (a['unlocks'] or {}).get('action_type') == 'assist_assignment', f"turn 2: {a}")
    res = turn({'name': 'mark_ask_sent', 'arguments': {}}, 'sent it')
    check(storage.get_ask(a['id'])['state'] == 'sent', f"turn 3: {res}")
    res = turn({'name': 'answer_ask', 'arguments': {'answer': 'yes'}}, 'she said yes')
    a = storage.get_ask(a['id'])
    check(a['state'] == 'yes' and a['outcome'] == 'applied', f"turn 4: {a}")
    res = turn({'name': 'answer_ask', 'arguments': {'answer': 'yes'}}, 'she said yes')
    check(storage.get_ask(a['id'])['outcome'] == 'applied' and res['status'] != 'error', "a duplicate yes is a no-op")
    check(storage.get_ask(a['id'])['applied_at'] is not None, "applied once, stamped once")
    from services import findings as _f
    _f.reconcile([], {'unassigned'}, time.time())
    check(storage.get_finding(fid)['state'] != 'open', "absence on the next sweep retires the finding")
    check(triage.get_focus('voice:7') is None, "and the focus is gone with it")


def scenario_e2e_next_walks_the_list_without_repeating_a_closed_row():
    """Spec acceptance 2."""
    _reset()
    a = threads.create('A overdue', owner_member_id='mom', next_action='x',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    b = threads.create('B quiet', owner_member_id='mom', created_by='mom')
    storage.update_thread(b, {'created_at': time.time() - 9 * 86400})
    c = threads.create('C quiet too', owner_member_id='mom', created_by='mom')
    storage.update_thread(c, {'created_at': time.time() - 10 * 86400})
    first = tools.next_situation(acting_member=MOM, focus_key='conv:3')['situation']['id']
    check(first == a, "tier 0 first")
    threads.close(b, 'done', who='mom')
    second = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:3')['situation']['id']
    check(second == c, f"B closed between turns is skipped: got {second}")
    res = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:3')
    check(res['situation'] is None, "then the list ends")


SCENARIOS += [scenario_e2e_voice_ask_round_trip, scenario_e2e_next_walks_the_list_without_repeating_a_closed_row]


# --- final review fixes ------------------------------------------------------

def scenario_a_pwa_turn_with_no_person_never_becomes_the_parent():
    """A PWA always carries a person; one that cannot name its member gets no
    substitution, so a passenger child's chat cannot act as the parent."""
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', created_by='mom')
    triage.set_focus('conv:p', 'thread', tid, 'Deck permit')
    call = {'name': 'act_on_situation', 'arguments': {'verb': 'own'}}
    res = _with_gemma(_fake_gemma(call), lambda: agent_router.process_agent_request('handle it', source='pwa', focus_key='conv:p'))
    check(storage.get_thread(tid).get(situations.OWNER) is None and 'parent or adult' in res['message'],
          f"a PWA with no member is refused, not substituted: {res}")
    src = open('main.py', encoding='utf-8').read()
    block = src.split('def handle_chat(')[1].split('\ndef ')[0]
    check('acting_member=' in block and '_acting_id(request' in block,
          "handle_chat resolves the signed-in member and hands it to the router")


def scenario_voice_fragment_never_names_a_sensitive_insight():
    _reset()
    storage.add_mind_insight({'slug': 's', 'line': 'Kate seems anxious about school', 'category': 'c', 'approach': 'x',
                              'identity': 'c:2', 'sensitivity': 'sensitive'})
    threads.create('School supplies order', owner_member_id='mom', created_by='mom')
    res = _with_gemma(_fake_gemma({'name': 'explain_situation', 'arguments': {'ref': 'school'}}),
                      lambda: agent_router.process_agent_request('tell me about the school one', focus_key='voice:1'))
    check('anxious' not in res['message'] and 'School supplies' in res['message'], f"the ambiguity list is spoken-safe: {res}")
    res = _with_gemma(_fake_gemma({'name': 'explain_situation', 'arguments': {'ref': 'anxious'}}),
                      lambda: agent_router.process_agent_request('the anxious one', focus_key='voice:1'))
    check('Kate seems' not in res['message'] and 'Nothing open matches' in res['message'],
          f"a unique fragment on a sensitive row is not named aloud (only the person's own word echoes): {res}")
    f = triage.get_focus('voice:1')
    check(not f or f['kind'] != 'insight', f"the sensitive row never becomes the room's focus: {f}")
    iid = storage.get_mind_insight_by_slug('s')['id']
    res = _with_gemma(_fake_gemma({'name': 'explain_situation', 'arguments': {'ref': iid}}),
                      lambda: agent_router.process_agent_request('that one', focus_key='voice:1'))
    check('anxious' not in res['message'], f"an id hit is refused aloud too: {res}")
    res = tools.explain_situation('anxious', acting_member=MOM, focus_key='conv:phone')
    check(res['status'] == 'success', "a parent on her own phone still may")


def scenario_next_after_closing_the_focus_continues_from_the_cursor():
    _reset()
    a = threads.create('A overdue', owner_member_id='mom', next_action='x',
                       next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')
    b = threads.create('B quiet', owner_member_id='mom', created_by='mom')
    storage.update_thread(b, {'created_at': time.time() - 9 * 86400})
    c = threads.create('C quiet too', owner_member_id='mom', created_by='mom')
    storage.update_thread(c, {'created_at': time.time() - 10 * 86400})
    check(tools.next_situation(acting_member=MOM, focus_key='conv:4')['situation']['id'] == a, "A first")
    check(tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:4')['situation']['id'] == b, "then B")
    threads.close(b, 'done', who='mom')
    nxt = tools.next_situation(skip_current=True, acting_member=MOM, focus_key='conv:4')['situation']
    check(nxt and nxt['id'] == c, f"B handled, 'next' continues to C, never back to A: {nxt and nxt['title']}")


def scenario_handle_it_accepts_the_reading_built_step():
    _reset()
    from services import replies, mailer
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True
    replies._post = lambda *a, **k: {'id': 'x'}
    tid = threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co',
                         counterparty_email='ops@pestco.example', created_by='mom')
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    threads.match_inbound('ops@pestco.example', 'Re: S', 'Friday at 9 works.', message_id='<m1>')
    storage.update_thread_history_entry(tid, {'message_id': '<m1>'},
                                        {'reading': {'answer': 'yes', 'summary': 'Friday 9am works', 'ts': time.time(), 'source': 'argyle'}})
    triage.set_focus('conv:h', 'thread', tid, 'Pest control')
    res = tools.act_on_situation(verb='advance', acting_member=MOM, focus_key='conv:h')
    check(res['status'] == 'success' and storage.get_thread(tid)['next_action'] == 'Confirm with Pest Co: Friday 9am works',
          f"'handle it' with no text takes the pre-filled step: {res} / {storage.get_thread(tid)['next_action']}")
    # A second thread whose newest entry is a question: the reply lead is a draft.
    tid2 = threads.create('Gutters', owner_member_id='mom', counterparty_name='Gutter Co',
                          counterparty_email='ops@gutter.example', created_by='mom')
    threads.send_drafted(tid2, 'S', 'B', 'ops@gutter.example', who='mom')
    threads.match_inbound('ops@gutter.example', 'Re: S', 'Which Friday did you mean?', message_id='<g1>')
    storage.update_thread_history_entry(tid2, {'message_id': '<g1>'},
                                        {'reading': {'answer': 'question', 'summary': 'which Friday?', 'ts': time.time(), 'source': 'argyle'}})
    triage.set_focus('conv:h', 'thread', tid2, 'Gutters')
    threads._pool_call = lambda tier, key, system, prompt, **kw: {'subject': 'Re', 'body': 'BODY ' + prompt}
    res = tools.act_on_situation(verb='draft', acting_member=MOM, focus_key='conv:h')
    check(res.get('status') == 'ok' and 'which Friday?' in res.get('body', ''), f"the reply draft carries the summary as intent: {res}")


def scenario_spoken_clause_names_a_reading_as_argyles():
    _reset()
    from services import mailer, asks
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True
    tid = threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co',
                         counterparty_email='ops@pestco.example', created_by='mom')
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    asks.record_reading(res['ask_id'], 'yes', '<m1>', summary='Friday works')
    line = triage.spoken(situations.view('thread', tid, MOM))
    check('Argyle read their reply as yes' in line and 'said yes' not in line, f"a reading is never spoken as a tap: {line}")


def scenario_focus_line_never_shows_a_title_the_speaker_cannot_see():
    _reset()
    fid = _finding('No driver: soccer', 'decide', 6, 'ev1')
    triage.set_focus('channel:fam', 'finding', fid, 'No driver: soccer')
    cap = {}
    kid = {'id': 'kid', 'name': 'Kate', 'role': 'child'}
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', source='family', acting_member=kid, focus_key='channel:fam'))
    check('FOCUS:' not in cap['system'], "a child in the family channel is not told a parent's focus")
    _with_gemma(_fake_gemma(None, cap), lambda: agent_router.process_agent_request('hi', source='family', acting_member=MOM, focus_key='channel:fam'))
    check('FOCUS:' in cap['system'], "the parent still is")


def scenario_a_reply_waiting_on_the_person_ranks_right_after_due_today():
    """Somebody wrote back and is waiting on us: that belongs near the top,
    not under the insights. Any reading but 'no' (and an unread reply) puts
    the thread in tier 1; the person acting on it returns it to its place."""
    _reset()
    from services import mailer
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True
    _finding('No driver: soccer today', 'decide', 6, 'ev-soon')               # tier 0
    storage.add_mind_insight({'slug': 'i', 'line': 'Thursday is tight', 'category': 'c', 'approach': 'ask Sarah',
                              'identity': 'c:1', 'confidence': 0.8})         # tier 3
    tid = threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co',
                         counterparty_email='ops@pestco.example', created_by='mom')
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    threads.match_inbound('ops@pestco.example', 'Re: S', 'Which Friday did you mean?', message_id='<q>')
    s = situations.view('thread', tid, MOM)
    check(triage.tier(s) == 1, f"an unread reply is tier 1: {triage.tier(s)} / {s['next_step']}")
    storage.update_thread_history_entry(tid, {'message_id': '<q>'},
                                        {'reading': {'answer': 'question', 'summary': 'which Friday?', 'ts': time.time(), 'source': 'argyle'}})
    s = situations.view('thread', tid, MOM)
    check(triage.tier(s) == 1, "a question is tier 1")
    titles = [x['title'] for x in triage.triage_rank(situations.list_situations(MOM))]
    check(titles.index('No driver: soccer today') < titles.index('Pest control') < titles.index('Thursday is tight'),
          f"after today's ride, before the insights: {titles}")
    storage.update_thread_history_entry(tid, {'message_id': '<q>'},
                                        {'reading': {'answer': 'yes', 'summary': 'Friday works', 'ts': time.time(), 'source': 'argyle'}})
    check(triage.tier(situations.view('thread', tid, MOM)) == 1, "a yes to confirm is tier 1")
    storage.update_thread_history_entry(tid, {'message_id': '<q>'},
                                        {'reading': {'answer': 'no', 'summary': 'cannot', 'ts': time.time(), 'source': 'argyle'}})
    check(triage.tier(situations.view('thread', tid, MOM)) == 4, "a no leaves the ordinary options and the ordinary rank")
    storage.update_thread_history_entry(tid, {'message_id': '<q>'},
                                        {'reading': {'answer': 'question', 'summary': 'which Friday?', 'ts': time.time(), 'source': 'argyle'}})
    threads.note(tid, 'called them back', who='mom')
    check(triage.tier(situations.view('thread', tid, MOM)) == 4, "once the person acts the thread sinks back")


SCENARIOS += [scenario_a_reply_waiting_on_the_person_ranks_right_after_due_today]

SCENARIOS += [scenario_a_pwa_turn_with_no_person_never_becomes_the_parent, scenario_voice_fragment_never_names_a_sensitive_insight,
              scenario_next_after_closing_the_focus_continues_from_the_cursor, scenario_handle_it_accepts_the_reading_built_step,
              scenario_spoken_clause_names_a_reading_as_argyles, scenario_focus_line_never_shows_a_title_the_speaker_cannot_see]

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
