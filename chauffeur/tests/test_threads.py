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


if __name__ == '__main__':
    scenario_overdue_next_action_stalls()
    scenario_silence_stalls_even_with_no_date()
    scenario_a_note_resets_the_quiet_clock()
    scenario_closed_threads_never_stall()
    scenario_open_by_owner_counts_the_carrying()
    scenario_a_stalled_thread_becomes_a_finding()
    print("test_threads OK")
