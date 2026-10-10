"""A vendor's reply on a thread is read once, recorded on the ask ledger,
never applied. Spec: docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §2."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, threads, asks, mailer

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
CALLS = []


def _reset():
    CALLS.clear()
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.app_state_table, storage.threads_table, storage.missions_table, storage.mission_steps_table,
              storage.assist_contacts_table, storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True


def _thread(title='Pest control', email='ops@pestco.example'):
    return threads.create(title, owner_member_id='mom', counterparty_name='Pest Co',
                          counterparty_email=email, created_by='mom')


def scenario_send_records_a_sent_ask_with_no_unlocks():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'Can you come Friday?', 'Hi, could you come Friday morning?',
                               'ops@pestco.example', who='mom', intent='come Friday morning')
    check(res['status'] == 'ok' and res.get('ask_id'), f"sent: {res}")
    a = storage.get_ask(res['ask_id'])
    check(a['situation_kind'] == 'thread' and a['situation_id'] == tid, "the ask belongs to the thread")
    check(a['state'] == 'sent' and a['sent_via'] == 'household' and a['channel'] == 'email', f"sent at once, by the household address: {a}")
    check(a['what'] == 'come Friday morning' and a['to_name'] == 'Pest Co' and a['unlocks'] is None, f"the commitment is the intent, unbound: {a}")
    check(a['draft_subject'] == 'Can you come Friday?' and a['asked_by'] == 'mom', "what went out is on the row")
    res2 = threads.send_drafted(tid, 'Following up', 'Any news?', 'ops@pestco.example', who='mom')
    a2 = storage.get_ask(res2['ask_id'])
    check(a2['what'] == 'Following up', "with no intent the subject is the commitment")
    s = situations.view('thread', tid, MOM)
    check(len(s['asks']) == 2 and all(x['state'] == 'sent' for x in s['asks']), "the card's ledger shows both, waiting")


def scenario_send_without_a_member_is_asked_by_the_parent_of_record():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who=None)
    check(storage.get_ask(res['ask_id'])['asked_by'] == 'mom', "an admin-surface send is the parent of record's ask")


SCENARIOS = [scenario_send_records_a_sent_ask_with_no_unlocks, scenario_send_without_a_member_is_asked_by_the_parent_of_record]

from services import replies  # noqa: E402


def _fake_pool(reply):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'prompt': prompt, 'kw': kw})
        return reply() if callable(reply) else reply
    return f


def _reply(tid, text='Friday at 9 works for us.', mid='<m1@pestco>'):
    return threads.match_inbound('ops@pestco.example', 'Re: Can you come Friday?', text, message_id=mid)


def scenario_a_matched_reply_is_read_once_and_stored_on_the_entry():
    _reset()
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
    tid = _thread()
    threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
    rev0 = storage.get_thread(tid)['rev']
    matched = _reply(tid)
    check(matched == tid, "the reply lands on the thread")
    replies.read(tid, '<m1@pestco>')
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'interactive' and CALLS[0]['kw'].get('timeout_s') == 20, f"one Lite call: {CALLS}")
    check('come Friday morning' in CALLS[0]['prompt'] and 'Pest control' in CALLS[0]['prompt'], "the prompt carries the ask and the title")
    h = storage.get_thread(tid)['history'][-1]
    check(h['kind'] == 'received' and h.get('message_id') == '<m1@pestco>', f"the entry knows its mail: {h}")
    check(h.get('reading', {}).get('answer') == 'yes' and h['reading']['summary'] == 'Friday 9am works'
          and h['reading']['source'] == 'argyle', f"the reading is on the entry: {h}")
    check(storage.get_thread(tid)['rev'] > rev0, "a reading moves the rev so the note refreshes")
    replies.read(tid, '<m1@pestco>')
    check(len(CALLS) == 1, "read once, never again")
    check(_reply(tid) == tid and len([x for x in storage.get_thread(tid)['history'] if x['kind'] == 'received']) == 1,
          "a rescan of the same mail appends nothing")


def scenario_no_key_cap_or_failure_leaves_no_reading():
    _reset()
    tid = _thread()
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    storage.get_settings = lambda: {'thread_stall_days': 7}            # no key
    replies._pool_call = _fake_pool({'answer': 'info', 'summary': 'x'})
    _reply(tid, mid='<a>')
    check(replies.read(tid, '<a>') is None and not CALLS, "no key: no call, no reading")
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'reply_cap_reads': 1}
    _reply(tid, mid='<b>')
    check(replies.read(tid, '<b>') is not None and len(CALLS) == 1, "under the cap: read")
    _reply(tid, mid='<c>')
    check(replies.read(tid, '<c>') is None and len(CALLS) == 1, "over the cap: no call")
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    def boom(*a, **k):
        raise RuntimeError('timeout')
    replies._pool_call = boom
    _reply(tid, mid='<d>')
    check(replies.read(tid, '<d>') is None, "a failure is no reading, not a crash")
    replies._pool_call = _fake_pool({'answer': 'maybe-ish', 'summary': 'x'})
    _reply(tid, mid='<e>')
    r = replies.read(tid, '<e>')
    check(r and r['answer'] == 'unclear', f"an answer outside the five words is unclear: {r}")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<d>'][0]
    check('reading' not in h, "the failed one carries no reading")


def scenario_the_module_never_applies_and_never_reads_dms():
    src = open('services/replies.py', encoding='utf-8').read()
    for banned in ('apply(', 'get_channel_messages', 'get_gift', 'gifts_table'):
        check(banned not in src, f"replies.py never names {banned}")


SCENARIOS += [scenario_a_matched_reply_is_read_once_and_stored_on_the_entry, scenario_no_key_cap_or_failure_leaves_no_reading,
              scenario_the_module_never_applies_and_never_reads_dms]


def scenario_reading_yes_records_manual_never_applies():
    _reset()
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
    tid = _thread()
    res = threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
    _reply(tid)
    replies.read(tid, '<m1@pestco>')
    a = storage.get_ask(res['ask_id'])
    check(a['state'] == 'yes' and a['outcome'] == 'manual' and a['answered_by'] == 'argyle', f"recorded, apply by hand: {a}")
    check(a['read_from'] == '<m1@pestco>' and a['read_summary'] == 'Friday 9am works', "the reading is on the ask")
    check(a['applied_at'] is None, "nothing applied")


def scenario_reading_no_question_info_unclear():
    _reset()
    tid = _thread()
    for i, (answer, expect_state) in enumerate([('no', 'no'), ('question', 'sent'), ('info', 'sent'), ('unclear', 'sent')]):
        res = threads.send_drafted(tid, f'S{i}', 'B', 'ops@pestco.example', who='mom')
        replies._pool_call = _fake_pool({'answer': answer, 'summary': f'{answer} summary'})
        _reply(tid, mid=f'<r{i}>')
        replies.read(tid, f'<r{i}>')
        a = storage.get_ask(res['ask_id'])
        check(a['state'] == expect_state, f"{answer}: the ask is {a['state']}, expected {expect_state}")
        h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == f'<r{i}>'][0]
        check(h['reading']['answer'] == answer, "the reading is on the history whatever the answer")


def scenario_reading_with_no_live_ask_lands_on_history_only():
    _reset()
    tid = _thread()
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'sure'})
    _reply(tid, mid='<x>')
    r = replies.read(tid, '<x>')
    check(r and r['answer'] == 'yes' and not storage.get_asks(situation_kind='thread', situation_id=tid), "no ask to answer; the reading is kept")


def scenario_reading_never_overwrites_a_human_answer():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    asks.answer(res['ask_id'], 'no', MOM, reported=True)
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'sure'})
    _reply(tid, mid='<y>')
    replies.read(tid, '<y>')
    a = storage.get_ask(res['ask_id'])
    check(a['state'] == 'no' and a['answered_by'] == 'mom', f"the owner's no stands: {a}")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<y>'][0]
    check(h['reading']['answer'] == 'yes', "the reading still lands on the history")


def scenario_unread_reverts_a_reading_and_refuses_a_tap():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday works'})
    _reply(tid, mid='<z>')
    replies.read(tid, '<z>')
    out = asks.unread(res['ask_id'], MOM)
    a = storage.get_ask(res['ask_id'])
    check(out['status'] == 'success' and a['state'] == 'sent' and a['answered_by'] is None and a['outcome'] is None
          and a['read_from'] is None, f"back to waiting: {a}")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<z>'][0]
    check(h['reading']['disputed'] is True and h['reading']['answer'] == 'yes', "the reading is kept, disputed")
    asks.answer(res['ask_id'], 'yes', MOM, reported=True)
    out = asks.unread(res['ask_id'], MOM)
    check(out['status'] == 'refused' and 'Mom' in out['message'], f"a human answer is not undone this way: {out}")
    check(asks.unread(res['ask_id'], {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a child cannot")


SCENARIOS += [scenario_reading_yes_records_manual_never_applies, scenario_reading_no_question_info_unclear,
              scenario_reading_with_no_live_ask_lands_on_history_only, scenario_reading_never_overwrites_a_human_answer,
              scenario_unread_reverts_a_reading_and_refuses_a_tap]

SENT = []


def _capture_post():
    def p(dm, argyle, body, card=None):
        SENT.append({'dm': dm, 'body': body})
        return {'id': f'm{len(SENT)}'}
    replies._post = p


def scenario_one_dm_to_the_owner_inside_the_window():
    _reset()
    SENT.clear(); _capture_post()
    # replies._now is the module's one clock; pin it inside the window.
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
        tid = _thread()
        threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
        _reply(tid)
        replies.read(tid, '<m1@pestco>')
        check(len(SENT) == 1, f"exactly one DM went: {SENT}")
        body = SENT[0]['body']
        check("Pest Co replied on 'Pest control'" in body and 'Friday 9am works' in body and '→' in body, f"the line: {body}")
        # storage.get_or_create_dm keys the channel by the sorted member pair.
        check('mom' in (SENT[0]['dm'].get('dm_key') or ''), f"to the owner: {SENT[0]['dm']}")
        h = storage.get_thread(tid)['history'][-1]
        check(not h.get('dm_pending'), "nothing pending")
    finally:
        replies._now = datetime.datetime.now


def scenario_dm_outside_quiet_hours_is_deferred_once():
    _reset()
    SENT.clear(); _capture_post()
    replies._pool_call = _fake_pool({'answer': 'no', 'summary': 'cannot do Friday'})
    tid = _thread()
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<late>')
    late = datetime.datetime.now().replace(hour=23, minute=0)
    # The real flow stores the reading on the entry before notifying; the
    # flush reads it back from there.
    reading = {'answer': 'no', 'summary': 'cannot do Friday', 'ts': time.time(), 'source': 'argyle'}
    storage.update_thread_history_entry(tid, {'message_id': '<late>'}, {'reading': reading})
    thread = storage.get_thread(tid)
    entry = [x for x in thread['history'] if x.get('message_id') == '<late>'][0]
    replies._notify(thread, entry, reading, now=late)
    check(not SENT, "nothing posted at 23:00")
    h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<late>'][0]
    check(h.get('dm_pending') is True, "marked pending")
    morning = datetime.datetime.now().replace(hour=9, minute=0)
    n = replies.flush_pending_dms(now=morning)
    check(n == 1 and len(SENT) == 1 and 'cannot do Friday' in SENT[0]['body'], f"posted once by the morning sweep: {SENT}")
    check(replies.flush_pending_dms(now=morning) == 0 and len(SENT) == 1, "a second sweep posts nothing")
    # A pending DM on a thread that closes overnight is never sent.
    _reply(tid, mid='<late2>')
    thread = storage.get_thread(tid)
    entry = [x for x in thread['history'] if x.get('message_id') == '<late2>'][0]
    replies._notify(thread, entry, None, now=late)
    threads.close(tid, 'done', who='mom')
    check(replies.flush_pending_dms(now=morning) == 0 and len(SENT) == 1, "nothing for a closed thread")


def scenario_no_reading_still_tells_the_owner_to_read_it():
    _reset()
    SENT.clear(); _capture_post()
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        storage.get_settings = lambda: {'thread_stall_days': 7}      # no key: no reading
        tid = _thread()
        threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
        _reply(tid, mid='<nk>', text='We can do Friday at 9.\nThanks')
        replies.read(tid, '<nk>')
        check(len(SENT) == 1 and 'read it' in SENT[0]['body'], f"'a reply came in — read it': {SENT}")
    finally:
        replies._now = datetime.datetime.now


def scenario_sweep_flushes_pending_dms_inside_the_window():
    src = open('services/watchers.py', encoding='utf-8').read()
    body = src.split('def run_watchers(')[1]
    before_toggle = body.split("proactive_watchers_enabled")[0]
    check('flush_pending_dms' in before_toggle,
          "run_watchers flushes pending reply DMs before the heads-up toggle (the flush keeps to the window itself)")


SCENARIOS += [scenario_one_dm_to_the_owner_inside_the_window, scenario_dm_outside_quiet_hours_is_deferred_once,
              scenario_no_reading_still_tells_the_owner_to_read_it, scenario_sweep_flushes_pending_dms_inside_the_window]


def _next(tid):
    return situations.view('thread', tid, MOM)['next_step']


def scenario_next_step_follows_the_reading():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
    _reply(tid, mid='<1>'); replies.read(tid, '<1>')
    n = _next(tid)
    check(n['verb'] == 'advance' and n['id'] == 'advance:confirm' and n['label'] == 'Confirm with Pest Co: Friday 9am works'
          and n['payload'].get('next_action') == 'Confirm with Pest Co: Friday 9am works', f"yes → confirm: {n}")
    opts = situations.view('thread', tid, MOM)['options']
    un = [o for o in opts if o['verb'] == 'unread']
    check(len(un) == 1 and un[0]['id'] == f"unread:{res['ask_id']}" and un[0]['label'] == 'Argyle got it wrong', f"the revert is on the card: {opts}")
    out = situations.act('thread', tid, 'unread', option_id=un[0]['id'], actor=MOM)
    check(out['status'] == 'success' and storage.get_ask(res['ask_id'])['state'] == 'sent', f"unread through act: {out}")
    n = _next(tid)
    check(n['id'] == 'advance:read' and n['label'].startswith('Read their reply'), f"after unread: read it yourself: {n}")
    check(not [o for o in situations.view('thread', tid, MOM)['options'] if o['verb'] == 'unread'], "nothing left to revert")
    replies._pool_call = _fake_pool({'answer': 'question', 'summary': 'which Friday?'})
    threads.send_drafted(tid, 'S2', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<2>'); replies.read(tid, '<2>')
    n = _next(tid)
    check(n['verb'] == 'draft' and n['id'] == 'draft:reply' and n['label'] == 'Reply: which Friday?'
          and n['payload'].get('text') == 'which Friday?', f"question → reply: {n}")
    replies._pool_call = _fake_pool({'answer': 'no', 'summary': 'cannot do Friday'})
    threads.send_drafted(tid, 'S3', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<3>'); replies.read(tid, '<3>')
    n = _next(tid)
    check(n['id'] not in ('advance:confirm', 'draft:reply', 'advance:read'), f"no → the ordinary options: {n}")
    storage.get_settings = lambda: {'thread_stall_days': 7}
    threads.send_drafted(tid, 'S4', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<4>', text='We can do Friday at 9.\nThanks, Pest Co')
    replies.read(tid, '<4>')
    n = _next(tid)
    check(n['id'] == 'advance:read' and n['label'] == 'Read their reply: We can do Friday at 9.', f"no reading → the first line: {n}")
    threads.note(tid, 'called them', who='mom')
    n = _next(tid)
    check(n['id'] != 'advance:read', f"once the person acts the ordinary options return: {n}")


SCENARIOS += [scenario_next_step_follows_the_reading]


def scenario_e2e_thread_mail_reply_reading_and_revert():
    """Spec acceptance 3."""
    _reset()
    SENT.clear(); _capture_post()
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        notes = []
        situations._pool_call = lambda tier, key, system, prompt, **kw: (notes.append(prompt) or {'status_note': 'They can do Friday.', 'options': []})
        tid = _thread()
        res = threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
        check(storage.get_ask(res['ask_id'])['state'] == 'sent', "sent")
        replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'Friday 9am works'})
        _reply(tid); replies.read(tid, '<m1@pestco>')
        situations.flush_refreshes()
        a = storage.get_ask(res['ask_id'])
        check(a['state'] == 'yes' and a['outcome'] == 'manual', "yes, manual")
        check(_next(tid)['label'] == 'Confirm with Pest Co: Friday 9am works', "next step")
        check(len(SENT) == 1 and 'Confirm with Pest Co' in SENT[0]['body'], f"one DM naming the next step: {SENT}")
        check(storage.get_thread(tid).get('status_note') == 'They can do Friday.', "the note refreshed")
        un = [o for o in situations.view('thread', tid, MOM)['options'] if o['verb'] == 'unread'][0]
        situations.act('thread', tid, 'unread', option_id=un['id'], actor=MOM)
        check(storage.get_ask(res['ask_id'])['state'] == 'sent' and _next(tid)['id'] == 'advance:read', "reverted")
        h = [x for x in storage.get_thread(tid)['history'] if x.get('message_id') == '<m1@pestco>'][0]
        check(h['reading']['disputed'] is True, "the reading is kept as disputed")
    finally:
        replies._now = datetime.datetime.now


def scenario_e2e_capped_reply_is_filed_unread_and_not_read_twice():
    """Spec acceptance 4."""
    _reset()
    SENT.clear(); _capture_post()
    replies._now = lambda: datetime.datetime.now().replace(hour=12, minute=0)
    try:
        storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'reply_cap_reads': 0}
        replies._pool_call = _fake_pool({'answer': 'yes', 'summary': 'x'})
        tid = _thread()
        res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
        from services import email_ingest
        msg = {'from': 'ops@pestco.example', 'subject': 'Re: S', 'text': 'Friday at 9 works.\nThanks', 'message_id': '<cap>'}
        email_ingest._match_thread(msg)
        check(not CALLS, "capped: no call")
        check(storage.get_ask(res['ask_id'])['state'] == 'sent', "the ask waits")
        check(_next(tid)['label'] == 'Read their reply: Friday at 9 works.', f"first line: {_next(tid)}")
        check(len(SENT) == 1 and 'read it' in SENT[0]['body'], "the DM says a reply came in")
        email_ingest._match_thread(msg)
        check(not CALLS and len(SENT) == 1 and len([h for h in storage.get_thread(tid)['history'] if h['kind'] == 'received']) == 1,
              "the next poll does not read or file it again")
    finally:
        replies._now = datetime.datetime.now


SCENARIOS += [scenario_e2e_thread_mail_reply_reading_and_revert, scenario_e2e_capped_reply_is_filed_unread_and_not_read_twice]


# --- the deferred minors, fixed ------------------------------------------------

def scenario_deferred_dm_flushes_even_with_heads_ups_off():
    _reset()
    SENT.clear(); _capture_post()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'proactive_watchers_enabled': False}
    tid = _thread()
    threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='mom')
    _reply(tid, mid='<night>')
    thread = storage.get_thread(tid)
    entry = [x for x in thread['history'] if x.get('message_id') == '<night>'][0]
    replies._notify(thread, entry, None, now=datetime.datetime.now().replace(hour=23, minute=0))
    check(not SENT, "deferred at night")
    from services import watchers
    watchers.run_watchers(datetime.datetime.now().replace(hour=9, minute=0))
    check(len(SENT) == 1, f"the morning sweep posts it although heads-ups are off: {SENT}")


def scenario_reading_counts_against_the_ingest_daily_limit():
    _reset()
    from services import email_ingest
    replies._pool_call = _fake_pool({'answer': 'info', 'summary': 'x'})
    tid = _thread()
    _reply(tid, mid='<w>')
    replies.read(tid, '<w>')
    check(CALLS and CALLS[0]['kw'].get('workflow') == email_ingest.WORKFLOW,
          f"the reading is an intake request and counts as one: {CALLS and CALLS[0]['kw']}")


def scenario_dm_does_not_repeat_the_summary():
    _reset()
    tid = _thread()
    thread = storage.get_thread(tid)
    entry = {'kind': 'received', 'text': 'Received from ops@pestco.example: Re\n\nQuote is $500', 'message_id': '<i>'}
    reading = {'answer': 'info', 'summary': 'Quote is $500', 'ts': time.time(), 'source': 'argyle'}
    line = replies.dm_line(thread, entry, reading, 'Read their reply: Quote is $500')
    check(line.count('Quote is $500') == 1 and 'Read their reply' in line, f"said once: {line}")
    line = replies.dm_line(thread, entry, {'answer': 'yes', 'summary': 'Friday 9am works', 'ts': 0, 'source': 'argyle'},
                           'Confirm with Pest Co: Friday 9am works')
    check(line.count('Friday 9am works') == 1, f"said once for a yes too: {line}")


def scenario_record_sent_never_trusts_a_non_member_as_the_asker():
    _reset()
    tid = _thread()
    res = threads.send_drafted(tid, 'S', 'B', 'ops@pestco.example', who='argyle')
    check(storage.get_ask(res['ask_id'])['asked_by'] == 'mom', "a sender that is not a member becomes the parent of record")


def scenario_the_call_counter_holds_the_lock():
    src = open('services/situations.py', encoding='utf-8').read()
    body = src.split('def _bump_call(')[1].split('\ndef ')[0]
    check('with storage.db_lock' in body, "the per-day call counter is a locked read-modify-write")


SCENARIOS += [scenario_deferred_dm_flushes_even_with_heads_ups_off, scenario_reading_counts_against_the_ingest_daily_limit,
              scenario_dm_does_not_repeat_the_summary, scenario_record_sent_never_trusts_a_non_member_as_the_asker,
              scenario_the_call_counter_holds_the_lock]

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
