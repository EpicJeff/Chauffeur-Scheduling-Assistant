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
    storage.threads_table.truncate()
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


def scenario_a_revert_survives_the_settings_read_failing():
    """The revert's own setup is inside the danger zone too. `_revert_attempt`
    has to read settings to know which calendar the failed attempt's event is
    on -- and when that read raised, it took the whole revert with it: no
    thread deleted, no commitment deleted, and, worst of all, no handback, so
    the program sat in `approving` where nothing can move it. This is the
    shape of every round of this bug: one more statement inside the danger
    zone and outside the guard. Now every step is individually skippable and
    the handback is structural, so a dead settings table costs one orphaned
    calendar event and nothing else."""
    _reset()
    pid = _mk(what='Buy a metronome and a capo before phase 2')
    _with_target_date(pid)
    from services import calendar as _cal
    real_create, real_remove = _cal.create_event, _cal.remove_event
    removed_events = []
    _cal.create_event = lambda *a, **kw: 'fake-event-2'
    _cal.remove_event = lambda cal_id, eid: removed_events.append(eid) or True

    real_update = storage.update_program
    real_settings = storage.get_settings
    down = []

    def flaky_update(program_id, data):
        if data.get('state') == 'active':
            # The database goes away at exactly the moment the revert starts.
            down.append(1)
            raise RuntimeError('db went away')
        return real_update(program_id, data)

    def dead_settings():
        if down:
            raise RuntimeError('settings table unreachable')
        return real_settings()

    storage.update_program = flaky_update
    storage.get_settings = dead_settings
    try:
        res = programs.approve(pid, 'mom')
        row = storage.get_program(pid)
        check(res['status'] == 'error',
              f"approve() returns an error rather than letting the revert's "
              f"own failure escape, got {res}")
        check(row['state'] == 'proposed',
              f"the handback happened anyway, got {row['state']}")
        check(row['emissions'] == {'commitment_ids': [], 'thread_ids': [], 'event_ids': []},
              f"cleared off the row, got {row['emissions']}")
        check(not storage.get_protected_commitments(member_id='lily'),
              "the steps AFTER the one that failed still ran -- no orphan window")
        check(not storage.get_threads(owner='lily'),
              "and the kit thread went too")
        check(removed_events == [],
              f"honest about what the failure cost: the calendar event could "
              f"not be cleaned up, because we never learned which calendar it "
              f"was on, so it is orphaned, got {removed_events}")
    finally:
        storage.update_program = real_update
        storage.get_settings = real_settings

    try:
        retry = programs.approve(pid, 'mom')
        check(retry['status'] == 'success', f"a plain retry must work, got {retry}")
        check(storage.get_program(pid)['state'] == 'active', "and it really goes through")
    finally:
        _cal.create_event = real_create
        _cal.remove_event = real_remove


def scenario_a_failing_cleanup_delete_does_not_take_the_revert_down():
    """One cleanup step failing must cost exactly one orphaned row, not the
    handback. Two commitments land, the third write fails, and then the
    revert's FIRST delete refuses as well -- the rest of the cleanup still
    runs and the program still gets back to `proposed`. Asserted honestly:
    the row whose delete failed really is left behind. That is the trade this
    shape makes on purpose -- an orphan is a thing somebody can see in their
    commitments list and remove, a program stuck in `approving` is not."""
    _reset()
    pid = _mk()
    real_add = storage.add_protected_commitment
    real_delete = storage.delete_protected_commitment
    calls, refused = [], []

    def flaky_add(data):
        calls.append(data)
        if len(calls) == 3:
            raise RuntimeError('disk full')
        return real_add(data)

    def stubborn_delete(cid):
        if not refused:
            refused.append(cid)
            raise RuntimeError('row is locked')
        return real_delete(cid)

    storage.add_protected_commitment = flaky_add
    storage.delete_protected_commitment = stubborn_delete
    try:
        res = programs.approve(pid, 'mom')
    finally:
        storage.add_protected_commitment = real_add
        storage.delete_protected_commitment = real_delete
    check(len(calls) == 3, f"the scenario must fail on the third write, got {len(calls)}")
    check(refused, "and the revert's first delete must really have refused")
    check(res['status'] == 'error', f"it reports the failure, got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'proposed',
          f"a failed cleanup step is not allowed to strand the program, "
          f"got {row['state']}")
    left = storage.get_protected_commitments(member_id='lily')
    check(len(left) == 1 and left[0]['id'] == refused[0],
          f"exactly the one row whose delete refused is orphaned -- the other "
          f"one was still cleaned up, got {left}")

    real_delete(left[0]['id'])
    retry = programs.approve(pid, 'mom')
    check(retry['status'] == 'success', f"a plain retry must work, got {retry}")
    check(storage.get_program(pid)['state'] == 'active', "and it really goes through")


def scenario_a_revert_survives_the_handback_itself_failing():
    """The last thing that can strand a program: the handback write itself
    raising. `claim_program` is the only door out of `approving`, so if that
    call is the thing that breaks, the compare-and-set never happened -- and
    a plain `update_program` is a second, independent path to the one outcome
    that matters. (Only when it RAISED: a False is claim_program working and
    saying somebody else already moved the row, which must not be
    overwritten.)"""
    _reset()
    pid = _mk()
    real_add = storage.add_protected_commitment
    real_claim = storage.claim_program
    calls, handbacks = [], []

    def flaky_add(data):
        calls.append(data)
        if len(calls) == 2:
            raise RuntimeError('disk full')
        return real_add(data)

    def flaky_claim(program_id, expected, new):
        if new == 'proposed':
            handbacks.append(1)
            raise RuntimeError('compare-and-set is down')
        return real_claim(program_id, expected, new)

    storage.add_protected_commitment = flaky_add
    storage.claim_program = flaky_claim
    try:
        res = programs.approve(pid, 'mom')
    finally:
        storage.add_protected_commitment = real_add
        storage.claim_program = real_claim
    check(handbacks, "the handback must really have been attempted and raised")
    check(res['status'] == 'error',
          f"approve() still returns rather than raising out of its own "
          f"recovery, got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'proposed',
          f"the fallback write got it back to retryable anyway, got {row['state']}")
    check(not storage.get_protected_commitments(member_id='lily'),
          "and the cleanup before it still ran")

    retry = programs.approve(pid, 'mom')
    check(retry['status'] == 'success', f"a plain retry must work, got {retry}")
    check(storage.get_program(pid)['state'] == 'active', "and it really goes through")


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


def scenario_an_impossible_shape_cannot_hang_or_write_a_bad_window():
    """Two failures with one cause: a shape nobody bounded.

    `propose_slots` padded `days` out to `sessions_per_week` and appended
    nothing once all seven weekdays were in it, so anything above seven never
    terminated -- and `/programs` calls the footprint endpoint for EVERY
    proposed program, so one such row pinned a threadpool worker at 100% CPU
    on every page load, forever. Six hundred minutes produced `time_end` of
    '29:00', which becomes a solver `Rule` inside the single try/except that
    wraps every protected commitment: one malformed row silently disabled
    protected time for the whole household.

    This scenario RUNS the call rather than reading it: a hang shows up as a
    test that never returns, which is the only honest way to check.
    """
    _reset()
    slots = programs.propose_slots('lily', {'sessions_per_week': 8,
                                            'minutes': 600,
                                            'preferred_days': []})
    check(1 <= len(slots) <= 7,
          f"a week has seven days and no more, got {len(slots)}")
    for s in slots:
        hh, mm = [int(x) for x in s['time_end'].split(':')]
        check(0 <= hh <= 23 and 0 <= mm <= 59,
              f"a window has to end inside the day it started in, got {s}")
        check(s['time_start'] < s['time_end'], f"a real window, got {s}")


def scenario_the_shape_is_clamped_at_every_door():
    """The bound lives in services/programs.py, not only in `max="7"` on a
    number input -- the endpoint and the chat tool both take a raw integer,
    and a model asked for "twice a day" says 14."""
    out = programs.clamp_shape({'sessions_per_week': 14, 'minutes': 600,
                                'preferred_days': [1, 9, 'x', 1]})
    check(out['sessions_per_week'] == 7, f"got {out}")
    check(out['minutes'] == programs.MAX_MINUTES, f"got {out}")
    check(out['preferred_days'] == [1], f"junk days are dropped, got {out}")
    # -1, not 0: a falsy value means "not said" and takes the default, the
    # same `or 3` reading every caller of this shape has always had.
    low = programs.clamp_shape({'sessions_per_week': -1, 'minutes': 1})
    check(low['sessions_per_week'] == 1 and low['minutes'] == programs.MIN_MINUTES,
          f"and the floor holds too, got {low}")


def scenario_pause_gives_the_evenings_back_and_resume_claims_them_again():
    """The spec is explicit -- "Pause removes the reservations... Resuming
    re-creates the emissions" -- and no task carried it: pause flipped a state
    and left the commitments live, so an adult's paused program kept CP-SAT
    out of those evenings indefinitely, and `resume()` re-created nothing
    because nothing had been removed."""
    _reset()
    pid = _mk()
    check(programs.approve(pid, 'mom')['status'] == 'success', 'approved')
    before = [(c['days_of_week'][0], c['time_start'], c['time_end'])
              for c in storage.get_protected_commitments(member_id='lily')]
    check(len(before) == 3, f"three windows are claimed, got {before}")

    res = programs.pause(pid)
    check(res['status'] == 'success' and res.get('schedule_dirty'),
          f"pausing is a schedule change, got {res}")
    check(storage.get_protected_commitments(member_id='lily') == [],
          "a paused program holds no evening")
    check(storage.get_program(pid)['emissions']['commitment_ids'] == [],
          "and stops believing it does")

    res = programs.resume(pid)
    check(res['status'] == 'success' and res.get('schedule_dirty'),
          f"resuming is one too, got {res}")
    after = sorted((c['days_of_week'][0], c['time_start'], c['time_end'])
                   for c in storage.get_protected_commitments(member_id='lily'))
    check(after == sorted(before),
          f"the SAME evenings come back, not re-proposed ones: {before} -> {after}")
    ids = storage.get_program(pid)['emissions']['commitment_ids']
    live = {c['id'] for c in storage.get_protected_commitments()}
    check(len(ids) == 3 and set(ids) <= live,
          f"and the program can find them again, got {ids}")


def scenario_a_reshaped_program_can_be_approved_again_without_a_duplicate_thread():
    """`reshape()` returns a program to `proposed` so `approve()` can rebuild
    the footprint -- which means approve now runs twice on one row. Its kit
    thread and target event are still standing, so a second run must adopt
    them rather than orphan one and open another beside it."""
    _reset()
    pid = _mk(what='buy a capo and a clip tuner')
    check(programs.approve(pid, 'mom')['status'] == 'success', 'approved')
    threads = list(storage.get_program(pid)['emissions']['thread_ids'])
    check(len(threads) == 1, f"one kit thread, got {threads}")

    check(programs.reshape(pid)['status'] == 'success', 're-shaped')
    check(storage.get_program(pid)['state'] == 'proposed',
          "the offer in the drift finding is one the app can really perform")
    check(storage.get_protected_commitments(member_id='lily') == [],
          "and it stops holding time it is no longer sure about")

    check(programs.approve(pid, 'mom')['status'] == 'success', 're-approved')
    row = storage.get_program(pid)
    check(row['emissions']['thread_ids'] == threads,
          f"the same kit thread, never a second one, got {row['emissions']}")
    check(len(row['emissions']['commitment_ids']) == 3,
          f"and the week is claimed again, got {row['emissions']}")


if __name__ == '__main__':
    scenario_slots_match_the_shape()
    scenario_the_footprint_is_visible_before_the_tap()
    scenario_approval_claims_the_time()
    scenario_a_pre_insert_failure_says_what_already_happened()
    scenario_a_rejected_write_returns_none_not_an_exception()
    scenario_a_local_write_failure_reverts_and_cleans_up()
    scenario_a_final_flip_failure_reverts_and_cleans_up()
    scenario_a_revert_survives_the_settings_read_failing()
    scenario_a_failing_cleanup_delete_does_not_take_the_revert_down()
    scenario_a_revert_survives_the_handback_itself_failing()
    scenario_approving_twice_does_not_claim_twice()
    scenario_two_taps_claim_the_week_once()
    scenario_an_impossible_shape_cannot_hang_or_write_a_bad_window()
    scenario_the_shape_is_clamped_at_every_door()
    scenario_pause_gives_the_evenings_back_and_resume_claims_them_again()
    scenario_a_reshaped_program_can_be_approved_again_without_a_duplicate_thread()
    print("test_programs_footprint OK")
