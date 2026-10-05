"""Email intake under a provider pause: never drop mail, and recover what
was dropped before.

Load-bearing properties: a paused/busy model stops the run and leaves the
email (and the rest of the batch) in line — the cursor moves one handled
message at a time; a permanent extraction error and an unreadable email are
passed over so they cannot block the inbox; a rescan queue re-reads mail
since a date and skips what already went through (by Message-ID, the log, or
an existing proposal); the missed summary counts logged extraction failures.

Run from chauffeur/:  python tests/test_email_backlog.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, email_ingest

SETTINGS = {'ingest_email_user': 'u@x.org', 'ingest_email_password': 'pw'}
CURSOR = 'ingest_last_uid::u@x.org'
QUEUE = 'ingest_rescan::u@x.org'


def _reset(cursor=10):
    import main  # noqa: F401
    for t in (storage.ingest_log_table, storage.ingest_seen_table, storage.app_state_table,
              storage.members_table):
        t.truncate()
    storage.get_proposals = lambda *a, **k: []
    storage.add_proposal = lambda p: None
    storage.get_settings = lambda: dict(SETTINGS)
    storage.set_app_state(CURSOR, cursor)


def _msg(uid, subject, rescan=False):
    return {'uid': uid, 'from': 'school@x.org', 'subject': subject,
            'text': 'Picture day Friday', 'message_id': f'<m{uid}@x>', 'rescan': rescan}


def _run(messages, extract):
    with mock.patch.object(email_ingest, 'fetch_new_messages', return_value=(messages, None)), \
         mock.patch.object(email_ingest, 'extract_items', side_effect=extract), \
         mock.patch.object(email_ingest, '_match_thread') as threads:
        return email_ingest.run_ingest(), threads


def scenario_a_pause_keeps_mail_in_line():
    _reset()
    calls = []

    def extract(subject, *a, **k):
        calls.append(subject)
        if subject == 'two':
            raise email_ingest.ExtractionDeferred('AI requests paused after provider failure')
        return []
    summary, threads = _run([_msg(11, 'one'), _msg(12, 'two'), _msg(13, 'three')], extract)
    check(calls == ['one', 'two'], f"the run stops at the pause, three is not attempted: {calls}")
    check(summary.get('deferred') and summary['checked'] == 1, f"summary says so: {summary}")
    check(storage.get_app_state(CURSOR) == 11, "the cursor is at the last HANDLED email, not past the batch")
    check(storage.ingest_seen('<m11@x>') and not storage.ingest_seen('<m12@x>'), "only handled mail is marked seen")
    check(threads.call_count == 1, "the paused email was not thread-matched (it will be on retry)")
    log = storage.get_ingest_log()
    check(any(r['outcome'].startswith('waiting: AI busy') for r in log)
          and not any('two' == r.get('subject') for r in log),
          f"one 'waiting' row, no per-email error for the paused one: {[r['outcome'] for r in log]}")
    # Next poll, model back: two and three go through.
    summary, _ = _run([_msg(12, 'two'), _msg(13, 'three')], lambda *a, **k: [])
    check(storage.get_app_state(CURSOR) == 13 and summary['checked'] == 2, "the retry finishes the batch")


def scenario_permanent_errors_do_not_block():
    _reset()

    def extract(subject, *a, **k):
        if subject == 'bad':
            raise RuntimeError('model returned nonsense')
        return []
    unreadable = {'uid': 11, 'unreadable': 'fetch NO', 'rescan': False}
    _run([unreadable, _msg(12, 'bad'), _msg(13, 'fine')], extract)
    check(storage.get_app_state(CURSOR) == 13, "unreadable and permanently failing mail is passed over")
    outcomes = [r['outcome'] for r in storage.get_ingest_log()]
    check(any(o.startswith('error: unreadable email') for o in outcomes)
          and any(o.startswith('error: extraction failed') for o in outcomes),
          f"both are logged: {outcomes}")


def scenario_deferral_detection():
    _reset()
    with mock.patch('services.model_pools.call_pool_json',
                    return_value={'error': 'AI requests paused after provider failure',
                                  'deferred': True, 'retry_at': 1}):
        storage.get_settings = lambda: {'llm_gemini_api_key': 'k'}
        try:
            email_ingest.extract_items('s', 'f', 'b', [])
            check(False, "a deferred answer must raise ExtractionDeferred")
        except email_ingest.ExtractionDeferred:
            check(True, "")
    with mock.patch('services.model_pools.call_pool_json',
                    return_value={'error': 'gemma timed out', 'transient': True}):
        try:
            email_ingest.extract_items('s', 'f', 'b', [])
            check(False, "a transient failure must raise ExtractionDeferred")
        except email_ingest.ExtractionDeferred:
            check(True, "")
    with mock.patch('services.model_pools.call_pool_json',
                    return_value={'error': 'bad request', 'transient': False}):
        try:
            email_ingest.extract_items('s', 'f', 'b', [])
            check(False, "a permanent failure must raise")
        except email_ingest.ExtractionDeferred:
            check(False, "a permanent failure is not a deferral")
        except RuntimeError:
            check(True, "")


def scenario_rescan_skips_what_went_through():
    _reset()
    storage.set_app_state(QUEUE, [3, 4, 5, 6])
    storage.mark_ingest_seen('<m3@x>')                                 # handled after the fix
    storage.add_ingest_log({'from': 'school@x.org', 'subject': 'four', 'outcome': 'no actionable items'})
    storage.get_proposals = lambda *a, **k: [{'source_from': 'school@x.org', 'source_subject': 'five'}]
    storage.add_ingest_log({'from': 'school@x.org', 'subject': 'six',
                            'outcome': 'error: extraction failed (AI requests paused after provider failure)'})
    seen = []
    summary, _ = _run([_msg(3, 'three', True), _msg(4, 'four', True), _msg(5, 'five', True),
                       _msg(6, 'six', True)], lambda subject, *a, **k: seen.append(subject) or [])
    check(seen == ['six'], f"only the email that failed before is read again: {seen}")
    check(summary.get('already') == 3, f"three skipped as already handled: {summary}")
    check(storage.get_app_state(QUEUE) == [], "the queue empties as it goes")
    check(storage.get_app_state(CURSOR) == 10, "a rescan never moves the new-mail cursor")


def scenario_missed_summary_and_queue():
    _reset()
    import main
    storage.add_ingest_log({'from': 'a', 'subject': 'x', 'outcome': 'error: extraction failed (paused)', 'ts': 1000})
    storage.add_ingest_log({'from': 'b', 'subject': 'y', 'outcome': 'error: extraction failed (paused)', 'ts': 2000})
    storage.add_ingest_log({'from': 'c', 'subject': 'z', 'outcome': 'proposed 1 item', 'ts': 3000})
    m = main.ingest_missed()
    check(m['failed'] == 2 and m['since_ts'] == 1000 and m['pending'] == 0, f"missed summary: {m}")

    class FakeIMAP:
        def __init__(self, host): pass
        def login(self, u, p): pass
        def select(self, *a, **k): return 'OK', [b'1']
        def uid(self, cmd, *args):
            check(args[1:] == ('SINCE', '01-Oct-2026'), f"IMAP date format: {args}")
            return 'OK', [b'21 22 23']
        def logout(self): pass
    storage.set_app_state(QUEUE, [22, 40])
    with mock.patch.object(email_ingest.imaplib, 'IMAP4_SSL', FakeIMAP):
        res = main.ingest_rescan(main.IngestRescanRequest(since='2026-10-01'))
    check(res['queued'] == 3 and res['pending'] == 4, f"queued, merged with what was pending: {res}")
    check(storage.get_app_state(QUEUE) == [21, 22, 23, 40], "queue is sorted and de-duplicated")
    from fastapi import HTTPException
    try:
        main.ingest_rescan(main.IngestRescanRequest(since='last week'))
        check(False, "a bad date must 400")
    except HTTPException as e:
        check(e.status_code == 400, "bad date refused")


SCENARIOS = [
    scenario_a_pause_keeps_mail_in_line,
    scenario_permanent_errors_do_not_block,
    scenario_deferral_detection,
    scenario_rescan_skips_what_went_through,
    scenario_missed_summary_and_queue,
]

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
    raise SystemExit(1 if failed else 0)
