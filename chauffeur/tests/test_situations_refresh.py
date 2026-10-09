"""Argyle writes the status note on state change only: coalesced, versioned
by rev, discarded when superseded, capped, never on read, and never able
to put a verb outside the closed set on a card."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, threads

CALLS = []


def _fake_pool(reply):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'prompt': prompt})
        return reply() if callable(reply) else reply
    return f


def _reset():
    CALLS.clear()
    for t in (storage.threads_table, storage.findings_table, storage.mind_insights_table,
              storage.missions_table, storage.mission_steps_table, storage.asks_table,
              storage.members_table, storage.app_state_table):
        t.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k'}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    situations.REFRESH_DELAY_S = 0


def scenario_note_is_written_on_change_not_on_read():
    _reset()
    situations._pool_call = _fake_pool({'status_note': 'Waiting on the county since Monday.',
                                        'options': [{'label': 'Call them Friday', 'verb': 'advance',
                                                     'payload': {'next_action': 'call county',
                                                                 'next_action_at': '2026-10-16'}}]})
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    situations.flush_refreshes()
    n = len(CALLS)
    check(n == 1, f"creating a thread wrote one note, got {n}")
    for _ in range(3):
        situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
        situations.list_situations({'id': 'mom', 'role': 'parent'}, kinds=('thread',))
    check(len(CALLS) == 1, "reads never call the model")
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['status_note'] == 'Waiting on the county since Monday.' and s['note_source'] == 'argyle',
          f"the note is Argyle's: {s['status_note']} / {s['note_source']}")
    check(s['options'][0]['verb'] == 'advance' and s['options'][0]['label'] == 'Call them Friday',
          "Argyle's suggestion leads, typed")
    check(s['options'][0]['id'].startswith('advance:argyle:'), "suggested options get their own ids")


def scenario_one_logical_mutation_one_call():
    _reset()
    situations._pool_call = _fake_pool({'status_note': 'n', 'options': []})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    CALLS.clear()
    # send_drafted appends history AND changes state: one refresh. The mail
    # itself is stubbed; this is about the hook, not SMTP.
    from services import mailer
    orig_send, orig_cfg = mailer.send, mailer.configured
    mailer.send = lambda *a, **k: {'sent': True, 'reason': None}
    mailer.configured = lambda settings: True
    try:
        res = threads.send_drafted(tid, 'subj', 'body', 'a@b.c', who='mom')
    finally:
        mailer.send, mailer.configured = orig_send, orig_cfg
    check(res.get('status') == 'ok', f"the send went through the stub: {res}")
    situations.flush_refreshes()
    check(len(CALLS) == 1, f"a send is one refresh, got {len(CALLS)}")


def scenario_out_of_order_result_is_discarded():
    _reset()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    # A slow call started at rev N; the row moves to N+1 before it returns.
    def slow():
        threads.note(tid, 'something happened', who='mom')   # bumps rev mid-call
        return {'status_note': 'OLD', 'options': []}
    situations._pool_call = _fake_pool(slow)
    res = situations.refresh('thread', tid)
    check(res['status'] == 'superseded', f"a result for an older rev is discarded: {res}")
    row = storage.get_thread(tid)
    check(row.get('status_note') != 'OLD', "the stale note never lands")


def scenario_bad_model_output_falls_back():
    _reset()
    tid = threads.create('T', owner_member_id='mom', next_action='call', created_by='mom')
    situations._pool_call = _fake_pool({'status_note': 'x', 'options': [
        {'label': 'Launch', 'verb': 'launch_rocket', 'payload': {}},
        {'label': 'Drop it', 'verb': 'close', 'payload': {'state': 'dropped'}}]})
    res = situations.refresh('thread', tid)
    check(res['status'] == 'noted', f"a note with one bad option still lands: {res}")
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    verbs = {o['verb'] for o in s['options']}
    check('launch_rocket' not in verbs and set(verbs) <= situations.VERBS, f"bad verb dropped: {verbs}")
    situations._pool_call = _fake_pool('not json at all')
    res = situations.refresh('thread', tid)
    check(res['status'] == 'fallback', f"garbage is a fallback, not an exception: {res}")
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['note_source'] == 'fallback' and 'call' in s['status_note'], "deterministic facts remain")


def scenario_cap_and_no_key():
    _reset()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'situation_cap_notes': 1}
    situations._pool_call = _fake_pool({'status_note': 'n', 'options': []})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    storage.set_app_state(f"situation_calls:{datetime.date.today().isoformat()}", {})
    check(situations.refresh('thread', tid)['status'] == 'noted', "first call allowed")
    check(situations.refresh('thread', tid)['status'] == 'capped', "second is capped")
    check(situations.held_notes_today() == 1, "capped notes are counted")
    storage.get_settings = lambda: {}
    check(situations.refresh('thread', tid)['status'] == 'no_key', "no key, no call")


def scenario_the_note_write_does_not_bump_rev():
    _reset()
    situations._pool_call = _fake_pool({'status_note': 'n', 'options': []})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    situations.flush_refreshes()
    rev = storage.get_thread(tid).get('rev')
    situations.refresh('thread', tid)
    check(storage.get_thread(tid).get('rev') == rev, "writing the note leaves rev alone")
    check(storage.get_thread(tid).get('note_rev') == rev, "the note remembers the rev it describes")


SCENARIOS = [scenario_note_is_written_on_change_not_on_read, scenario_one_logical_mutation_one_call,
             scenario_out_of_order_result_is_discarded, scenario_bad_model_output_falls_back,
             scenario_cap_and_no_key, scenario_the_note_write_does_not_bump_rev]

def scenario_argyle_options_are_for_threads_only():
    _reset()
    storage.set_cached_schedule({'events': [], 'assignments': {}, 'unassigned': []})
    fid = storage.add_finding({'identity': 'x:1', 'kind': 'errand_pastdue', 'severity': 'approve', 'line': 'late',
                               'subject_type': 'errand', 'subject_id': 'e1', 'state': 'open'})
    situations._pool_call = _fake_pool({'status_note': 'Overdue since Monday.',
                                        'options': [{'label': 'Look it up', 'verb': 'research', 'payload': {'text': 'x'}}]})
    res = situations.refresh('finding', fid)
    check(res['status'] == 'noted', f"the note lands: {res}")
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['status_note'] == 'Overdue since Monday.', "the sentence is kept")
    check(not any(o['id'].endswith(':argyle:0') for o in s['options']) and s['next_step']['verb'] != 'research',
          f"a thread verb never becomes a finding's main button: {[o['id'] for o in s['options']]}")


SCENARIOS += [scenario_argyle_options_are_for_threads_only]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
