"""Programs — an ambition with a plan attached, and the week it needs.

Taking work off the plate is the smaller idea. This is the bigger one: a goal
fails not because nobody has forty minutes but because nobody knows what would
go IN the forty minutes. So a program carries the path as well as the time.

This module owns the object's life — create, approve, pause, resume, drop, log
a session, mark a milestone, read progress. It knows nothing about how a plan
is found (services/programs_curate.py) and nothing about HTTP.

Everything here is written so that the only numbers it can produce go UP. There
is no function that returns a streak, a miss count, or a comparison between two
people, because there is no field to build one from.
"""
import datetime
import time
import uuid

from services import storage

# The states a program can be in. `paused` is a peer of `active`, not a flavour
# of failure: if the only way out of a program is to fail it, people fail it.
LIVE_STATES = ('proposed', 'active', 'paused')


def progress(program: dict) -> dict:
    """What this program has done. Every number is monotonic.

    Deliberately NOT returned: a total to divide `milestones_hit` by. A count
    next to a total is a completion percentage away, and a completion
    percentage is one of the six banned things — so the total stays out of
    this dict even though `len(phases)` is trivial to compute, and `phase`
    (the milestone ahead) is what a caller actually needs to show.
    """
    sessions = program.get('sessions') or []
    phases = program.get('phases') or []
    hit = [p for p in phases if p.get('milestone_hit_at')]
    current = next((p for p in phases if not p.get('milestone_hit_at')), None)
    return {'sessions': len(sessions),
            'minutes': sum(int(s.get('minutes') or 0) for s in sessions),
            'milestones_hit': len(hit),
            'phase': current}


def sessions_between(program: dict, start: datetime.date,
                     end: datetime.date) -> list:
    """The log entries inside a date window, for the derived read in
    services/watchers.py. Reading, never writing."""
    out = []
    for s in program.get('sessions') or []:
        try:
            d = datetime.datetime.fromtimestamp(float(s['ts'])).date()
        except (KeyError, TypeError, ValueError):
            continue
        if start <= d <= end:
            out.append(s)
    return out


def log_session(program_id: str, minutes: int = None, source: str = 'added',
                note: str = '') -> dict:
    """Record that it happened. `asked` came from the question after a slot;
    `added` is a person saying so themselves — practising on the bus is still
    practising."""
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') not in ('active', 'paused'):
        return {'status': 'error',
                'message': f"That program is {row.get('state')}."}
    mins = int(minutes if minutes is not None
               else (row.get('shape') or {}).get('minutes') or 0)
    storage.append_program_session(program_id, {
        'minutes': mins, 'source': source, 'note': (note or '').strip()})
    p = progress(storage.get_program(program_id))
    return {'status': 'success', 'sessions': p['sessions'],
            'message': f"{p['sessions']} sessions so far."}


def mark_milestone(program_id: str, phase_name: str) -> dict:
    """A person marks it, because 'switch G to C without looking' is a
    judgement no app can make. Only ever sets a date — there is no counterpart
    that marks one missed."""
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    phases, found = [], False
    for ph in row.get('phases') or []:
        if not found and ph.get('name') == phase_name and not ph.get('milestone_hit_at'):
            ph = {**ph, 'milestone_hit_at': time.time()}
            found = True
        phases.append(ph)
    if not found:
        return {'status': 'error', 'message': "I can't find that milestone."}
    storage.update_program(program_id, {'phases': phases})
    return {'status': 'success',
            'message': f"🎉 {row.get('title')}: {phase_name} done."}


def pause(program_id: str) -> dict:
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') in ('done', 'dropped'):
        return {'status': 'error',
                'message': f"That program is {row.get('state')} — there's nothing to pause."}
    storage.update_program(program_id, {'state': 'paused',
                                        'paused_at': time.time()})
    return {'status': 'success', 'message': 'Paused. Nothing counts against it.'}


def resume(program_id: str) -> dict:
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') != 'paused':
        return {'status': 'error',
                'message': f"That program is {row.get('state')}, not paused."}
    storage.update_program(program_id, {'state': 'active', 'paused_at': None})
    return {'status': 'success', 'message': 'Back on.'}


# --- The footprint: what a program does to the week ------------------------
# A program is a generator. It emits reserved practice time, a thread for the
# kit, and a real dated event to aim at -- and the parent sees all of it on one
# screen before one tap, because approvals arriving as a drip is the failure
# mode that kills assistants.

DEFAULT_SLOT_START = '19:00'


def _fmt_hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def propose_slots(member_id: str, shape: dict, now=None) -> list:
    """Practice windows, proposed from the week's existing shape.

    No CP-SAT run: proposing a practice time is not a solve. This reads what is
    already committed and picks windows that do not sit on top of it, and the
    person can move them on the approval screen anyway.
    """
    per_week = max(1, int((shape or {}).get('sessions_per_week') or 3))
    minutes = max(5, int((shape or {}).get('minutes') or 25))
    days = list((shape or {}).get('preferred_days') or [])
    while len(days) < per_week:
        for candidate in (1, 3, 5, 0, 2, 4, 6):
            if candidate not in days:
                days.append(candidate)
                break
    days = sorted(days[:per_week])

    taken = {}
    for pc in storage.get_protected_commitments(member_id=member_id):
        for d in (pc.get('days_of_week') or []):
            taken.setdefault(d, []).append(pc.get('time_start'))

    default_hour, default_minute = (int(x) for x in DEFAULT_SLOT_START.split(':'))
    out = []
    for d in days:
        hour, minute = default_hour, default_minute
        while _fmt_hhmm(hour, minute) in (taken.get(d) or []) and hour < 21:
            hour += 1
        end_total = hour * 60 + minute + minutes
        out.append({'day': d, 'time_start': _fmt_hhmm(hour, minute),
                    'time_end': _fmt_hhmm(end_total // 60, end_total % 60)})
    return out


def footprint(program: dict) -> dict:
    """Everything approval would create, for the screen that asks."""
    shape = program.get('shape') or {}
    baseline = program.get('baseline') or {}
    kit = _kit_line(program)
    target_date = baseline.get('target_date')
    return {
        'slots': propose_slots(program.get('member_id'), shape),
        'thread': kit,
        'event': ({'title': program.get('title'), 'date': target_date}
                  if target_date and not baseline.get('target_event_id')
                  else None),
    }


def _kit_line(program: dict) -> str:
    """What the plan says to get, if it says anything. Never invented -- an
    empty kit is better than a shopping list nobody's plan asked for."""
    for ph in program.get('phases') or []:
        what = (ph.get('what') or '').lower()
        for word in ('buy', 'you will need', 'equipment', 'gear'):
            if word in what:
                return f"{program.get('title')}: what to get"
    return ''


def _quietly(what: str, fn, *args, **kwargs):
    """Run one step of a revert and refuse to let it out of this function.

    Every step of undoing a half-finished approval goes through here, and that
    is what makes the revert total rather than merely careful. Returns None
    when the step raised, which is how a caller tells "it failed" apart from
    "it ran and said no".
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"[programs] revert could not {what}: {e}")
        return None


def _cleanup_calendar_id() -> str:
    """Which calendar a reverted attempt's event would be sitting on.

    Reading settings is not a write, but it is still a trip to the database
    and can still fail, so it lives behind `_quietly` with everything else the
    revert does. It is a lookup, not a safe operation.
    """
    settings = storage.get_settings() or {}
    return (settings.get('calendar_ids') or ['primary'])[0]


def _remove_calendar_event(cal_id: str, event_id: str) -> bool:
    """Delete one event the failed attempt created. The import is in here so
    that even a failure to import the calendar module is just another skipped
    cleanup step rather than the thing that kills the revert."""
    from services import calendar as _cal
    return _cal.remove_event(cal_id, event_id)


def _revert_attempt(program_id: str, emissions: dict) -> None:
    """Undo what THIS attempt stamped, and hand the claim back no matter what.

    Two jobs, and the second one outranks the first. The first: a claim that
    is not going to finish must not leave reserved time nothing owns behind
    it, so the commitment rows, the kit thread, and -- in the one case there
    can be one -- the calendar event all go. The second: THIS FUNCTION CANNOT
    FAIL. Every step runs through `_quietly`, and the handback to `proposed`
    sits in a `finally`, so no step here, and nothing anybody adds here later,
    can take the recovery down with it.

    That ranking is deliberate, because the two failure modes are not equally
    bad and must not be traded the wrong way round. A cleanup step that gives
    up leaves one orphaned row -- a practice window in somebody's commitments
    list that they can see and delete. A revert that raises leaves the program
    in `approving`, and nothing anywhere transitions a program out of
    `approving`: `approve()`'s own gate demands `proposed`, so the ambition is
    stuck there with no button in the app that fixes it. A recovery path that
    can itself fail is a recovery path that strands people. So the handback is
    structural and the cleanup is best-effort, never the other way around.

    (An event id can only be in `emissions` when the calendar branch succeeded
    and the state flip immediately after it failed -- the calendar write is the
    last thing before that flip.)
    """
    emissions = emissions if isinstance(emissions, dict) else {}
    try:
        if emissions.get('event_ids'):
            cal_id = _quietly('read the calendar settings', _cleanup_calendar_id)
            for eid in emissions.get('event_ids') or []:
                if cal_id and eid:
                    _quietly(f"remove calendar event {eid}",
                             _remove_calendar_event, cal_id, eid)
        for tid in emissions.get('thread_ids') or []:
            _quietly(f"delete thread {tid}", storage.delete_thread, tid)
        for cid in emissions.get('commitment_ids') or []:
            _quietly(f"delete commitment {cid}",
                     storage.delete_protected_commitment, cid)
    except Exception as e:
        # Unreachable while every call above is wrapped -- which is the point:
        # this is here so a future edit that forgets the wrapper degrades to a
        # skipped cleanup instead of quietly restoring the stranding bug.
        print(f"[programs] revert cleanup gave up early: {e}")
    finally:
        # The handback is the whole reason this function exists, so it runs
        # whatever happened above.
        handed_back = _quietly('hand the claim back to proposed',
                               storage.claim_program, program_id,
                               'approving', 'proposed')
        if handed_back is None:
            # It RAISED -- the compare-and-set never happened at all. (A plain
            # False is different: that means somebody else already moved this
            # row, and overwriting their state would be worse than leaving
            # it.) Write the state back the plain way instead: a second,
            # independent path to the only outcome that actually matters.
            _quietly('force the state back to proposed', storage.update_program,
                     program_id, {'state': 'proposed'})
        # Last and least: clearing the row's emissions is cosmetic, because the
        # next attempt starts from a fresh empty triple regardless and never
        # reads this. It goes after the handback so that its failing costs a
        # stale dict, not a stranded program.
        _quietly('clear the emissions off the row', storage.update_program,
                 program_id, {'emissions': {'commitment_ids': [],
                                            'thread_ids': [], 'event_ids': []}})


def approve(program_id: str, approver_id: str = None, slots: list = None) -> dict:
    """Claim the week. One act, everything the footprint showed.

    Applies the way negotiation proved: pre-flight everything first, local
    writes before the single external one, and stamp each emission as it lands
    so a failure can say how far it got instead of implying nothing happened.
    """
    from services import calendar as _cal
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') != 'proposed':
        return {'status': 'error',
                'message': f"That program is already {row.get('state')}."}
    member = storage.get_member(row.get('member_id'))
    if not member:
        return {'status': 'error',
                'message': "I can't tell whose program this is."}

    use = slots or propose_slots(row.get('member_id'), row.get('shape') or {})
    if not use:
        return {'status': 'error', 'message': 'There is no time to claim.'}

    # CLAIM before touching anything. A double-tap or two open tabs can both
    # pass the state check above in the same instant (FastAPI runs sync
    # handlers in a threadpool) -- whoever flips proposed -> approving owns
    # the apply; the other is told it is already claimed and does nothing.
    if not storage.claim_program(program_id, 'proposed', 'approving'):
        current = storage.get_program(program_id) or {}
        return {'status': 'error',
                'message': f"That program is already {current.get('state')}."}

    emissions = {'commitment_ids': [], 'thread_ids': [], 'event_ids': []}

    # Everything from here to the final flip is bracketed. The claim above
    # moved the point of no return earlier than a plain `state='proposed'`
    # row, and nothing else transitions a program OUT of `approving` -- so
    # any exception in here, not just the calendar's, has to be caught and
    # reverted, or the program is stuck un-retryable forever.
    try:
        # Local writes first: cheap, ours, and undoable by a person who can
        # see them. One commitment per slot, not merged by window -- three
        # practice sessions a week are three claimed windows, each one
        # individually visible and individually undoable in the commitments
        # list.
        for s in use:
            # add_protected_commitment writes the dict as given -- it does
            # not go through the pydantic model the way the HTTP route does
            # -- so the id has to be minted here, not left for storage to
            # invent one.
            cid = storage.add_protected_commitment({
                'id': uuid.uuid4().hex,
                'member_id': row['member_id'], 'title': row.get('title') or 'Practice',
                'days_of_week': [s['day']], 'time_start': s['time_start'],
                'time_end': s['time_end'], 'active': True})
            emissions['commitment_ids'].append(cid)
            storage.update_program(program_id, {'emissions': emissions})

        kit = _kit_line(row)
        if kit:
            tid = storage.add_thread({'title': kit, 'kind': 'project',
                                      'owner_member_id': row['member_id'],
                                      'goal': 'Have what the next phase needs',
                                      'created_by': approver_id})
            emissions['thread_ids'].append(tid)
            storage.update_program(program_id, {'emissions': emissions})

        # The one write that reaches another system goes last.
        baseline = dict(row.get('baseline') or {})
        if baseline.get('target_date') and not baseline.get('target_event_id'):
            try:
                settings = storage.get_settings() or {}
                cal_id = (settings.get('calendar_ids') or ['primary'])[0]
                # calendar.create_event sends {'dateTime': start} with no
                # timeZone attached, and Google rejects a naive dateTime
                # outright ("Missing time zone definition") -- the same trap
                # chat_actions._create_event documents and normalizes at the
                # caller. Stamp the server's local offset on here rather
                # than teaching create_event a new parameter for one caller.
                naive_start = datetime.datetime.fromisoformat(
                    f"{baseline['target_date']}T09:00:00")
                start_iso = naive_start.astimezone().isoformat()
                end_iso = (naive_start + datetime.timedelta(hours=1)).astimezone().isoformat()
                ev_id = _cal.create_event(cal_id, row.get('title') or 'Program',
                                          start_iso, end_iso)
                # create_event catches every Google API exception itself and
                # returns None on a real rejection (bad calendar id, quota,
                # transient failure) rather than raising -- the try/except
                # above only ever catches OUR pre-insert failures (a bad
                # date string). A falsy id IS the production failure signal,
                # same convention as chat_actions._create_event's
                # `if not gid`, and it must never be recorded as though it
                # were a real event id.
                if not ev_id:
                    raise RuntimeError("the calendar didn't create the event")
                emissions['event_ids'].append(ev_id)
                baseline['target_event_id'] = ev_id
            except Exception as e:
                # _revert_attempt undoes EVERYTHING this attempt stamped, the
                # commitments included -- so by the time whoever called
                # approve() reads this message, the practice time is not
                # claimed anymore. Say that, not the opposite.
                raise RuntimeError(
                    "The calendar refused the target date, so nothing was "
                    f"kept -- {row.get('title') or 'this program'} is back "
                    f"to unclaimed and can be approved again once that's "
                    f"sorted out: {e}") from e

        # The state flip has to be inside this same bracket: it is a write
        # like any other (update_program's own key screen can raise), and
        # anything after the claim that isn't guarded reintroduces the exact
        # stranding bug this bracket exists to close.
        baseline['start_date'] = baseline.get('start_date') or \
            datetime.date.today().isoformat()
        storage.update_program(program_id, {
            'state': 'active', 'approved_by': approver_id,
            'emissions': emissions, 'baseline': baseline})
    except Exception as e:
        # Whatever failed -- a local write, the kit thread, the calendar
        # branch re-raising its own message above, or the state flip itself
        # -- this attempt did not finish, so nothing it stamped gets to
        # stay: delete what was created, clear it off the row, and hand the
        # claim back so the program is exactly where `approve()` found it,
        # not stranded. `_revert_attempt` cannot raise, by construction, so
        # this handler always gets to return an error rather than letting an
        # exception out of a function that has already taken a claim. The
        # success path below is never reached when this branch runs, so it
        # cannot revert itself.
        _revert_attempt(program_id, emissions)
        return {'status': 'error', 'message': str(e)}

    return {'status': 'success', 'schedule_dirty': True,
            'message': f"{row.get('title')} is on. "
                       f"{len(emissions['commitment_ids'])} practice window(s) claimed."}


# --- Living with a program -------------------------------------------------

REBASELINE_WINDOW_DAYS = 21     # how far back "is this working?" looks
REBASELINE_COOLDOWN_DAYS = 14   # so it cannot chatter
ASK_GRACE_HOURS = 2             # after the slot ends, before asking


def weekday_shortfall(program: dict, now=None) -> dict:
    """Which weekday keeps getting eaten — computed, never stored.

    To say 'Wednesdays keep getting eaten' you have to know Wednesdays were
    missed, and the schema deliberately has nowhere to record a miss. So the
    miss is derived here, used to write one sentence, and thrown away. The wins
    are durable; the shortfall is a momentary calculation, which is why nothing
    any surface reads can ever render a person as behind.
    """
    now = now or datetime.datetime.now()
    shape = program.get('shape') or {}
    days = list(shape.get('preferred_days') or [])
    if not days:
        return None
    start = (program.get('baseline') or {}).get('start_date')
    try:
        began = datetime.date.fromisoformat(start) if start else None
    except (TypeError, ValueError):
        began = None
    window_start = max(began or now.date(),
                       now.date() - datetime.timedelta(days=REBASELINE_WINDOW_DAYS))
    weeks = max(1, (now.date() - window_start).days // 7)
    done = {}
    for s in sessions_between(program, window_start, now.date()):
        try:
            wd = datetime.datetime.fromtimestamp(float(s['ts'])).weekday()
        except (KeyError, TypeError, ValueError):
            continue
        done[wd] = done.get(wd, 0) + 1
    worst, gap = None, 0
    for d in days:
        missing = weeks - done.get(d, 0)
        if missing > gap:
            worst, gap = d, missing
    if worst is None or gap < 2:
        return None
    return {'weekday': worst, 'expected': weeks, 'done': done.get(worst, 0)}


def _compress_phases(phases: list, target_date: str, now) -> tuple:
    """Shrink the remaining phases so the plan still lands on a fixed date,
    rather than moving the date — the counterpart to stretching an undated
    target.

    A phase whose milestone is already hit is done: it consumed its time
    already and is never touched. Everything still ahead compresses toward
    the date, floored at one week each, because a phase with zero weeks in
    it is not a phase, it is a phase that got deleted while pretending not
    to be. If even the floor does not fit before the date, this refuses to
    fake it — the phases come back exactly as they were, and the second
    return value says plainly that it does not fit, so the caller can say so
    too rather than claim room that was never made.
    """
    try:
        target = datetime.date.fromisoformat(target_date)
    except (TypeError, ValueError):
        return phases, None
    weeks_available = max(0, (target - now.date()).days // 7)
    remaining_idx = [i for i, p in enumerate(phases) if not p.get('milestone_hit_at')]
    if not remaining_idx:
        return phases, True          # nothing left to compress -- it fits by default
    if len(remaining_idx) > weeks_available:
        return phases, False         # not even one week each fits -- admit it
    current = [max(1, int(p.get('weeks') or 1)) for p in
               (phases[i] for i in remaining_idx)]
    if sum(current) <= weeks_available:
        return phases, True          # already fits -- nothing needs shrinking
    scale = weeks_available / sum(current)
    new_weeks = [max(1, int(w * scale)) for w in current]
    # Floor-and-scale can still overshoot by a week or two of rounding; trim
    # the largest phase down (never below one week) until it truly fits.
    while sum(new_weeks) > weeks_available:
        idx = max(range(len(new_weeks)), key=lambda i: new_weeks[i])
        if new_weeks[idx] <= 1:
            break
        new_weeks[idx] -= 1
    out = [dict(p) for p in phases]
    for i, nw in zip(remaining_idx, new_weeks):
        out[i]['weeks'] = nw
    return out, sum(new_weeks) <= weeks_available


def maybe_rebaseline(program: dict, now=None) -> dict:
    """Stretch the timeline when life delivered fewer sessions than the plan
    assumed. A plan that can only be fallen behind is a plan designed to be
    abandoned — so the plan bends, and says so.

    What it never moves is a date the world fixed. A June campfire is not the
    app's to reschedule; the phases compress instead — and when they cannot
    compress far enough to still fit, `fits` comes back False so the caller
    can say the plan is tight rather than pretend room was made where none
    was.
    """
    now = now or datetime.datetime.now()
    if program.get('state') != 'active':
        return None
    baseline = dict(program.get('baseline') or {})
    last = baseline.get('rebaselined_at')
    if last and (now.timestamp() - float(last)) < REBASELINE_COOLDOWN_DAYS * 86400:
        return None
    short = weekday_shortfall(program, now)
    if not short:
        return None
    baseline['rebaselines'] = int(baseline.get('rebaselines') or 0) + 1
    baseline['rebaselined_at'] = now.timestamp()

    original_phases = program.get('phases') or []
    phases = original_phases
    fits = None
    date_moved = False
    update = {'baseline': baseline}
    if baseline.get('target_date') and baseline.get('target_event_id'):
        # A real event pins the date -- the phases give way instead of it.
        phases, fits = _compress_phases(original_phases, baseline['target_date'], now)
        update['phases'] = phases
    elif baseline.get('target_date'):
        # No event pins this one down: an undated target is the app's to move.
        try:
            target = datetime.date.fromisoformat(baseline['target_date'])
            baseline['target_date'] = (target + datetime.timedelta(days=14)).isoformat()
            date_moved = True
        except (TypeError, ValueError):
            pass
    storage.update_program(program['id'], update)
    # `fits` alone isn't enough to word the finding honestly: a program that
    # already had slack before the date needs `fits=True` without ever
    # claiming credit for a squeeze that never happened. `date_moved` closes
    # the same gap on the other branch -- malformed baseline data (an event id
    # with no date, or a date string that won't parse) must not read as "I
    # gave the plan more room" when nothing was ever touched.
    return {'weekday': short['weekday'], 'baseline': baseline, 'phases': phases,
            'fits': fits, 'phases_changed': phases != original_phases,
            'date_moved': date_moved}


def orphaned_emissions(program: dict) -> list:
    """Emission ids the program believes in that are no longer there.

    Someone deleted a practice window by hand. The program stops believing the
    time is reserved and says so once — it never silently re-creates it,
    because an app that puts back what you deleted is an app you stop trusting.
    """
    ids = list((program.get('emissions') or {}).get('commitment_ids') or [])
    if not ids:
        return []
    live = {c['id'] for c in storage.get_protected_commitments()}
    return [cid for cid in ids if cid not in live]


def forget_emissions(program_id: str, gone: list) -> None:
    row = storage.get_program(program_id)
    if not row:
        return
    em = dict(row.get('emissions') or {})
    em['commitment_ids'] = [c for c in (em.get('commitment_ids') or [])
                            if c not in set(gone)]
    storage.update_program(program_id, {'emissions': em})


def due_session_asks(now=None) -> list:
    """Slots that have passed and have not been asked about.

    One question per slot, ever. Silence counts nothing — the number only means
    sessions a person said they did. Quiet hours are honoured, so a 9pm slot
    asks in the morning rather than at 9:25pm.

    Each program's check is wrapped on its own, the same way the drift and
    rebaseline checks in watchers.py guard themselves per program below --
    one member's malformed record (a bad quiet-hours string, a corrupt
    commitment) must cost only that program's ask, not silence every family
    member's practice check for the whole sweep.
    """
    from services import family_digest
    now = now or datetime.datetime.now()
    out = []
    for row in storage.get_programs(state='active'):
        try:
            member = storage.get_member(row.get('member_id'))
            if not member or family_digest.in_member_quiet_hours(member, now):
                continue
            cids = set((row.get('emissions') or {}).get('commitment_ids') or [])
            for pc in storage.get_protected_commitments(member_id=row['member_id']):
                if pc.get('id') not in cids:
                    continue
                for d in (pc.get('days_of_week') or []):
                    slot_date = _last_occurrence(d, now)
                    if slot_date is None:
                        continue
                    ended = _slot_end(slot_date, pc.get('time_end') or '19:25')
                    if (now - ended).total_seconds() < ASK_GRACE_HOURS * 3600:
                        continue
                    if _already_logged(row, slot_date):
                        continue
                    out.append({'program': row, 'slot_date': slot_date.isoformat(),
                                'body': f"{row.get('title')} on "
                                        f"{slot_date.strftime('%A')} — did it happen?"})
        except Exception as e:
            print(f"[programs] session ask check failed for {row.get('id')}: {e}")
    return out


def _last_occurrence(weekday: int, now):
    delta = (now.weekday() - weekday) % 7
    d = now.date() - datetime.timedelta(days=delta)
    return d if d <= now.date() else None


def _slot_end(day, hhmm: str):
    try:
        h, m = [int(x) for x in str(hhmm).split(':')[:2]]
    except (ValueError, TypeError):
        h, m = 19, 25
    return datetime.datetime(day.year, day.month, day.day, h, m)


def _already_logged(program: dict, day) -> bool:
    return bool(sessions_between(program, day, day))
