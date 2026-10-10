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
    # 'info' until Task 7 adds asks.record_reading; Task 7 switches this to 'yes'.
    replies._pool_call = _fake_pool({'answer': 'info', 'summary': 'Friday 9am works'})
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
    check(h.get('reading', {}).get('answer') == 'info' and h['reading']['summary'] == 'Friday 9am works'
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
