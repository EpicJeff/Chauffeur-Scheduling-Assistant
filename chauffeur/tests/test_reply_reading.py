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
