"""What approving a program does to the week.

One approval covers the whole footprint, shown before the tap -- a drip of
approvals is the named killer of assistants. And it applies the way negotiation
proved: pre-flight everything, local writes before the one external write, stamp
each emission as it lands.
"""
from harness import check
from services import programs, storage


def _reset():
    storage.programs_table.truncate()
    storage.protected_commitments_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})


def _mk(what='Three chords'):
    return storage.add_program({
        'member_id': 'lily', 'title': 'Play campfire songs by summer',
        'shape': {'sessions_per_week': 3, 'minutes': 25,
                  'preferred_days': [1, 3, 5]},
        'phases': [{'name': 'Phase 1', 'weeks': 4, 'what': what,
                    'milestone': 'G to C', 'milestone_hit_at': None}]})


def scenario_slots_match_the_shape():
    _reset()
    slots = programs.propose_slots('lily', {'sessions_per_week': 3,
                                            'minutes': 25,
                                            'preferred_days': [1, 3, 5]})
    check(len(slots) == 3, f"one slot per session a week, got {slots}")
    check({s['day'] for s in slots} == {1, 3, 5},
          f"on the days they asked for, got {slots}")
    for s in slots:
        check(s['time_start'] < s['time_end'], f"a real window, got {s}")


def scenario_the_footprint_is_visible_before_the_tap():
    _reset()
    fp = programs.footprint(storage.get_program(_mk()))
    check(len(fp['slots']) == 3, f"it says what time it claims, got {fp}")
    check('thread' in fp and 'event' in fp,
          "and what else it would create, so nothing is a surprise")


def scenario_approval_claims_the_time():
    _reset()
    pid = _mk()
    res = programs.approve(pid, 'mom')
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'active', f"the program is live, got {row['state']}")
    check(row['approved_by'] == 'mom', "and records who approved it")
    ids = row['emissions']['commitment_ids']
    check(len(ids) == 3, f"three practice slots were really created, got {ids}")
    for cid in ids:
        rows = [c for c in storage.get_protected_commitments() if c['id'] == cid]
        check(rows and rows[0]['member_id'] == 'lily',
              f"and belong to whose program it is, got {rows}")


def _with_target_date(pid):
    storage.update_program(pid, {'baseline': {'start_date': None,
                                              'target_date': '2026-06-14',
                                              'target_event_id': None,
                                              'rebaselined_at': None,
                                              'rebaselines': 0}})


def scenario_a_pre_insert_failure_says_what_already_happened():
    """One way create_event can fail this module: OUR code raises before
    ever reaching Google (a bad date string, e.g.) -- the try/except exists
    for exactly this. The calendar is the one write that reaches another
    system, so it goes last, and when it refuses the program must not imply
    nothing happened -- but the practice time it claimed on the way there
    is also not real anymore, so the revert has to clean that up rather
    than leave it as an orphan reservation nothing owns."""
    _reset()
    pid = _mk()
    _with_target_date(pid)
    from services import calendar as _cal
    real = _cal.create_event
    _cal.create_event = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError('calendar said no'))
    try:
        res = programs.approve(pid, 'mom')
        row = storage.get_program(pid)
        check(res['status'] == 'error', f"it reports the failure, got {res}")
        check(row['state'] == 'proposed',
              f"reverted, not stranded and not silently active, got {row['state']}")
        msg = (res.get('message') or '').lower()
        check('nothing was kept' in msg or 'unclaimed' in msg,
              f"the message has to describe what is NOW true -- the revert "
              f"already undid it, got {res}")
        check('is claimed' not in msg,
              f"must not claim something the revert already undid, got {res}")
        check(not row['emissions']['commitment_ids'],
              f"the revert cleaned up what it claimed, got {row['emissions']}")
        check(not storage.get_protected_commitments(member_id='lily'),
              "and left no orphan reservation behind either")
    finally:
        _cal.create_event = real


def scenario_a_rejected_write_returns_none_not_an_exception():
    """The REAL production shape: calendar.create_event catches every Google
    API exception itself (services/calendar.py) and returns None on a bad
    calendar id, a quota error, or a transient failure -- it does not raise.
    A stub that raises instead doesn't exercise this at all, so this one
    keeps the actual contract: a falsy return is the failure signal, and
    approve() must catch it rather than recording None as an event id and
    reporting success with a target date that silently does not exist."""
    _reset()
    pid = _mk()
    _with_target_date(pid)
    from services import calendar as _cal
    real = _cal.create_event
    _cal.create_event = lambda *a, **kw: None
    try:
        res = programs.approve(pid, 'mom')
        row = storage.get_program(pid)
        check(res['status'] == 'error',
              f"a None from the calendar must not read as success, got {res}")
        check(row['state'] == 'proposed',
              f"reverted, not stranded and not silently active, got {row['state']}")
        check(None not in row['emissions']['event_ids'],
              f"a null id must never be recorded as a real one, got {row['emissions']}")
        msg = (res.get('message') or '').lower()
        check('nothing was kept' in msg or 'unclaimed' in msg,
              f"the message has to describe what is NOW true -- the revert "
              f"already undid it, got {res}")
        check('is claimed' not in msg,
              f"must not claim something the revert already undid, got {res}")
        check(not row['emissions']['commitment_ids'],
              f"the revert cleaned up what it claimed, got {row['emissions']}")
        check(not storage.get_protected_commitments(member_id='lily'),
              "and left no orphan reservation behind either")
    finally:
        _cal.create_event = real


def scenario_a_local_write_failure_reverts_and_cleans_up():
    """Before the claim, an exception mid-approval just left the row at
    `proposed` for free. After the claim, nothing but the calendar branch
    reverted -- so a raise from add_protected_commitment or add_thread
    propagated straight out of approve() and stranded the program in
    `approving` forever, un-retryable, with whatever it had already created
    left behind as an orphan. This proves the whole post-claim body is now
    bracketed: the SECOND commitment fails, after the first one really was
    written, and both the row and the already-written first commitment get
    cleaned up -- then a plain retry, once the fault is gone, succeeds."""
    _reset()
    pid = _mk()
    real_add = storage.add_protected_commitment
    calls = []

    def flaky(data):
        calls.append(data)
        if len(calls) == 2:
            raise RuntimeError('disk full')
        return real_add(data)

    storage.add_protected_commitment = flaky
    try:
        res = programs.approve(pid, 'mom')
    finally:
        storage.add_protected_commitment = real_add
    check(len(calls) == 2, f"the scenario must fail on the second write, got {len(calls)}")
    check(res['status'] == 'error', f"it reports the failure, got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'proposed',
          f"not stranded in approving, not silently active, got {row['state']}")
    check(row['emissions'] == {'commitment_ids': [], 'thread_ids': [], 'event_ids': []},
          f"cleared off the row, got {row['emissions']}")
    check(not storage.get_protected_commitments(member_id='lily'),
          "the first write that DID succeed before the second failed is not an orphan")

    retry = programs.approve(pid, 'mom')
    check(retry['status'] == 'success', f"a plain retry must work, got {retry}")
    check(storage.get_program(pid)['state'] == 'active', "and it really goes through")


def scenario_a_final_flip_failure_reverts_and_cleans_up():
    """The narrowest window of all: local writes, the kit thread, and even
    the calendar all finish -- and then the very LAST write, the state flip
    itself, is what raises. Before this round's fix the bracket stopped one
    statement short of that write, which reintroduced exactly the stranding
    bug this whole round exists to close.

    Also the one case `_revert_attempt` can ever be asked to clean up a real
    calendar event: the calendar branch is the last thing before the flip,
    so a flip failure is the only way a real event id reaches the revert
    path. And the phase text here mentions gear on purpose, so a kit thread
    gets created too -- proving the thread-deletion branch actually runs
    rather than just trusting it by reading the code."""
    _reset()
    pid = _mk(what='Buy a metronome and a capo before phase 2')
    _with_target_date(pid)
    from services import calendar as _cal
    real_create, real_remove = _cal.create_event, _cal.remove_event
    removed_events = []
    _cal.create_event = lambda *a, **kw: 'fake-event-1'
    _cal.remove_event = lambda cal_id, eid: removed_events.append(eid) or True

    real_update = storage.update_program

    def flaky_update(program_id, data):
        if data.get('state') == 'active':
            raise RuntimeError('db went away')
        return real_update(program_id, data)

    real_delete_thread = storage.delete_thread
    deleted_threads = []

    def tracked_delete_thread(tid):
        deleted_threads.append(tid)
        return real_delete_thread(tid)

    storage.update_program = flaky_update
    storage.delete_thread = tracked_delete_thread
    try:
        res = programs.approve(pid, 'mom')
        row = storage.get_program(pid)
        check(res['status'] == 'error', f"it reports the failure, got {res}")
        check(row['state'] == 'proposed',
              f"not stranded in approving, not silently active, got {row['state']}")
        check(row['emissions'] == {'commitment_ids': [], 'thread_ids': [], 'event_ids': []},
              f"cleared off the row, got {row['emissions']}")
        check(not storage.get_protected_commitments(member_id='lily'),
              "no orphan commitment left from the attempt that didn't finish")
        check(deleted_threads,
              "the kit thread this attempt created gets cleaned up too, "
              "not just assumed to")
        check(not storage.get_threads(owner='lily'),
              "and it is really gone, not just attempted")
        check(removed_events == ['fake-event-1'],
              f"the calendar event this attempt created also gets cleaned "
              f"up -- the only write here that reaches another system, and "
              f"the one thing a plain delete can't undo if left alone, "
              f"got {removed_events}")
    finally:
        storage.update_program = real_update
        storage.delete_thread = real_delete_thread

    # The retry still needs the calendar stubbed -- baseline.target_date is
    # unchanged (that write never landed), so the calendar branch fires
    # again.
    try:
        retry = programs.approve(pid, 'mom')
        check(retry['status'] == 'success', f"a plain retry must work, got {retry}")
        check(storage.get_program(pid)['state'] == 'active', "and it really goes through")
    finally:
        _cal.create_event = real_create
        _cal.remove_event = real_remove


def scenario_approving_twice_does_not_claim_twice():
    _reset()
    pid = _mk()
    programs.approve(pid, 'mom')
    before = len(storage.get_program(pid)['emissions']['commitment_ids'])
    res = programs.approve(pid, 'mom')
    after = len(storage.get_program(pid)['emissions']['commitment_ids'])
    check(res['status'] == 'error', f"a second approval is refused, got {res}")
    check(before == after, "and claims no more of the week")


def scenario_two_taps_claim_the_week_once():
    """The two-taps-in-the-same-second case the serial test above can't
    reach: both callers can pass `state != 'proposed'` before either has
    written anything (FastAPI runs sync handlers in a threadpool). Simulated
    deterministically -- the second call is let in at exactly the instant the
    first has already passed every read-only check and is about to claim, via
    a stub on `storage.claim_program` that re-enters `approve()` once before
    doing the real compare-and-set. Without it, both would claim the week."""
    _reset()
    pid = _mk()
    real_claim = storage.claim_program
    reentered = []

    def claim_once(program_id, expected, new):
        if not reentered:
            reentered.append(1)
            programs.approve(program_id, 'dad')
        return real_claim(program_id, expected, new)

    storage.claim_program = claim_once
    try:
        res = programs.approve(pid, 'mom')
    finally:
        storage.claim_program = real_claim
    check(reentered, "the scenario must actually have re-entered, or it proves nothing")
    row = storage.get_program(pid)
    check(row['state'] == 'active', f"one of them won, got {row['state']}")
    check(row['approved_by'] == 'dad',
          f"the one that actually claimed it first, got {row['approved_by']}")
    ids = row['emissions']['commitment_ids']
    check(len(ids) == 3, f"claimed exactly once, not twice, got {ids}")
    check(res['status'] == 'error',
          f"the outer call lost the race and must say so, got {res}")


if __name__ == '__main__':
    scenario_slots_match_the_shape()
    scenario_the_footprint_is_visible_before_the_tap()
    scenario_approval_claims_the_time()
    scenario_a_pre_insert_failure_says_what_already_happened()
    scenario_a_rejected_write_returns_none_not_an_exception()
    scenario_a_local_write_failure_reverts_and_cleans_up()
    scenario_a_final_flip_failure_reverts_and_cleans_up()
    scenario_approving_twice_does_not_claim_twice()
    scenario_two_taps_claim_the_week_once()
    print("test_programs_footprint OK")
