"""Stall detection is the whole value: the eleven days nobody was watching."""
import datetime
import time
from harness import check
from services import storage, threads


def _day(off):
    return (datetime.date.today() + datetime.timedelta(days=off)).isoformat()


def _reset():
    storage.threads_table.truncate()
    storage.get_settings = lambda: {}


def scenario_overdue_next_action_stalls():
    _reset()
    t = threads.create('Pest control', owner_member_id='m1',
                       next_action='Call them back', next_action_at=_day(-1))
    check(threads.is_stalled(storage.get_thread(t)) == 'overdue',
          "yesterday's next action is a stall")
    threads.advance(t, 'Call them back', _day(2))
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "a future action is not")


def scenario_silence_stalls_even_with_no_date():
    _reset()
    t = threads.create('Gutters', owner_member_id='m1')
    row = storage.get_thread(t)
    check(threads.is_stalled(row) is None, "a fresh thread is not stalled")
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    check(threads.is_stalled(storage.get_thread(t)) == 'quiet',
          "nine days with nothing happening is")


def scenario_a_note_resets_the_quiet_clock():
    _reset()
    t = threads.create('Gutters', owner_member_id='m1')
    storage.update_thread(t, {'created_at': time.time() - 9 * 86400})
    threads.note(t, 'left a voicemail', who='m1')
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "movement is movement, even when nothing was achieved")


def scenario_closed_threads_never_stall():
    _reset()
    t = threads.create('Old thing', owner_member_id='m1',
                       next_action='x', next_action_at=_day(-30))
    threads.close(t)
    check(threads.is_stalled(storage.get_thread(t)) is None,
          "a finished thread is not a problem")
    check(threads.stalled() == [], "and does not appear in the sweep")


def scenario_open_by_owner_counts_the_carrying():
    _reset()
    threads.create('A', owner_member_id='m1')
    threads.create('B', owner_member_id='m1')
    threads.create('C', owner_member_id='m2')
    d = threads.open_by_owner()
    check(d == {'m1': 2, 'm2': 1}, f"who is holding what, got {d}")


def scenario_a_stalled_thread_becomes_a_finding():
    _reset()
    from services import watchers
    t = threads.create('Pest control', owner_member_id='m1',
                       next_action='Call them back', next_action_at=_day(-3))
    found = [f for f in watchers.collect_findings()[0] if f.kind == 'thread_stall']
    check(len(found) == 1, f"the stall is a finding, got {found}")
    f = found[0]
    check('Pest control' in f.line and 'Call them back' in f.line,
          f"and it arrives with what to do next, got {f.line!r}")
    check(f.subject_id == t and f.subject_type == 'thread', f"got {f}")
    check('thread_stall' in watchers.SCANNED_KINDS,
          "registered, or reconcile will never close it")


def scenario_drafting_never_sends():
    _reset()
    sent = []
    from services import mailer as _m
    orig = _m.send
    threads._pool_call = lambda *a, **k: {'subject': 'Following up',
                                          'body': 'Hi — checking in.'}
    try:
        _m.send = lambda *a, **k: sent.append(a) or {'sent': True}
        t = threads.create('Pool', owner_member_id='m1',
                           counterparty_email='pool@example.com')
        d = threads.draft_message(t)
        check(d['status'] == 'ok' and d['subject'] == 'Following up', f"got {d}")
        check(not sent, "DRAFTING MUST NEVER SEND")
        check(not any(h.get('kind') == 'sent'
                      for h in storage.get_thread(t)['history']),
              "and must not claim it did")
    finally:
        _m.send = orig


def scenario_sending_records_what_went_out():
    _reset()
    from services import mailer as _m
    orig_send, orig_conf = _m.send, _m.configured
    try:
        _m.configured = lambda *a, **k: True
        _m.send = lambda to, subject, body, settings=None: {'sent': True}
        t = threads.create('Pool', owner_member_id='m1',
                           counterparty_email='pool@example.com')
        res = threads.send_drafted(t, 'Hi', 'Body text', 'pool@example.com', 'm1')
        check(res['status'] == 'ok', f"got {res}")
        h = storage.get_thread(t)['history'][-1]
        check(h['kind'] == 'sent' and 'Body text' in h['text'],
              f"the thread remembers what was actually said, got {h}")
        check(storage.get_thread(t)['state'] == 'waiting',
              "and that the ball is now with them")
    finally:
        _m.send, _m.configured = orig_send, orig_conf


def scenario_send_without_smtp_is_an_honest_refusal():
    _reset()
    from services import mailer as _m
    orig = _m.configured
    try:
        _m.configured = lambda *a, **k: False
        t = threads.create('Pool', owner_member_id='m1')
        res = threads.send_drafted(t, 'Hi', 'B', 'a@b.example', 'm1')
        check(res['status'] == 'not_configured', f"got {res}")
    finally:
        _m.configured = orig


if __name__ == '__main__':
    scenario_overdue_next_action_stalls()
    scenario_silence_stalls_even_with_no_date()
    scenario_a_note_resets_the_quiet_clock()
    scenario_closed_threads_never_stall()
    scenario_open_by_owner_counts_the_carrying()
    scenario_a_stalled_thread_becomes_a_finding()
    scenario_drafting_never_sends()
    scenario_sending_records_what_went_out()
    scenario_send_without_smtp_is_an_honest_refusal()
    print("test_threads OK")
