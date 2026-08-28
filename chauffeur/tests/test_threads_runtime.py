"""The runtime seam for threads: entry points swallow exceptions, so a
feature can be green on unit tests and still broken in the wire. This test
does not call the collector and check its return value — it runs the actual
`watchers.run_watchers` sweep, the actual `services/findings.py` reconciler,
and the actual `vitals.measure_day`, and checks what landed in storage.

One scenario: a thread goes overdue, the real sweep turns that into a
`thread_stall` finding sitting in the findings table (not just something
`collect_findings` returned), the thread moves again, the real sweep closes
that finding through `reconcile` because it looked and the trouble was gone,
and `vitals.measure_day` counted the open thread as load the whole time it
was open and stops the moment it closes.

Run from chauffeur/:  python tests/test_threads_runtime.py
"""
import datetime
from unittest import mock

from harness import check
from services import storage, threads, vitals, watchers

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _day(off):
    return (datetime.date.today() + datetime.timedelta(days=off)).isoformat()


def _reset():
    for t in (storage.threads_table, storage.findings_table,
              storage.members_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.app_state_table,
              storage.agent_action_proposals_table):
        t.truncate()
    storage.get_settings = lambda: {}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})


def _sweep(now=NOON):
    """The real `run_watchers`. Only the LLM prep-kit check and the literal
    chat-send are stubbed (same seam `test_watchers.py` stubs) — collection,
    the signal-policy filtering, and `findings.reconcile` all run for real,
    including the DM branch (parent lookup, Argyle's DM channel, the
    consolidated post) since this thread's stall is old enough to qualify."""
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None: {}):
        return watchers.run_watchers(now=now)


def scenario_a_stall_becomes_and_unbecomes_a_real_finding():
    _reset()
    thread_id = threads.create(
        'Pest control', owner_member_id='mom', goal='Get the ants sorted',
        next_action='Call them back', next_action_at=_day(-10))

    # The load is counted per open thread per owner, stalled or not, from
    # the moment it opens.
    measured = vitals.measure_day(_day(0), sched={'events': []})
    check(measured['load'].get('mom') == vitals.THREAD_MINUTES,
          f"an open thread costs load, got {measured['load']}")

    sent = _sweep()
    check(sent >= 1, f"the stall is old enough to page a parent, got {sent}")

    identity = f'thread_stall:{thread_id}'
    finding = storage.get_finding_by_identity(identity)
    check(finding is not None,
          "the stall reached the findings table through the real sweep, "
          "not just the collector's return value")
    check(finding['state'] == 'open', f"got {finding}")
    check(finding['kind'] == 'thread_stall', f"got {finding}")
    check('Pest control' in finding['line'] and 'Call them back' in finding['line'],
          f"the watcher-signal policy (a next action, never a bare nag) "
          f"still holds through the real sweep, got {finding['line']!r}")

    # The thread moves again — no longer stalled.
    threads.advance(thread_id, 'Call them back', _day(2))
    check(threads.is_stalled(storage.get_thread(thread_id)) is None,
          "a future action is no longer a stall")

    _sweep(now=NOON + datetime.timedelta(minutes=1))

    finding = storage.get_finding_by_identity(identity)
    check(finding['state'] == 'done' and finding['resolved_by'] == 'auto',
          f"the real reconcile closed it because this sweep looked for "
          f"thread_stall and did not find it, got {finding}")

    # The thread is still OPEN (advanced, not closed) — it still costs load.
    measured = vitals.measure_day(_day(0), sched={'events': []})
    check(measured['load'].get('mom') == vitals.THREAD_MINUTES,
          f"an unstalled thread is still an open loop, still load, "
          f"got {measured['load']}")

    threads.close(thread_id)
    measured = vitals.measure_day(_day(0), sched={'events': []})
    check(measured['load'].get('mom', 0) == 0,
          f"a closed thread stops costing load, got {measured['load']}")


if __name__ == '__main__':
    scenario_a_stall_becomes_and_unbecomes_a_real_finding()
    print("test_threads_runtime OK")
