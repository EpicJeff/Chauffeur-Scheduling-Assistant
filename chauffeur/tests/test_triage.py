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
