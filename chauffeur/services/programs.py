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
import math
import re
import time
import uuid

from services import storage

# The states a program can be in. `paused` is a peer of `active`, not a flavour
# of failure: if the only way out of a program is to fail it, people fail it.
LIVE_STATES = ('proposed', 'active', 'paused')

# The week has seven days, so seven windows is the most a program can ever
# claim; a session that ran four hours is a day out, not a practice slot.
# These are the OUTER bounds, enforced here rather than only in the number
# input on the page: a chat model asked for "twice a day" will happily say 14,
# and a shape nobody bounded produced two real failures -- a `propose_slots`
# loop that could never fill an eighth day and so never terminated, and a
# `time_end` of '29:00' that a solver `Rule` cannot parse, which took protected
# time down for the WHOLE household because every commitment is converted
# inside one try/except. Both are shape problems, so the shape is where the
# bound belongs.
MAX_SESSIONS_PER_WEEK = 7
MIN_MINUTES = 5
MAX_MINUTES = 240


_HHMM_RE = re.compile(r'^(\d{1,2}):([0-5]\d)$')


def sanitize_slots(slots, minutes: int) -> list:
    """Practice windows a person chose, forced into shapes the solver can eat.

    This is the check that has to exist before anybody is allowed to pick
    their own times, and it did not: `approve()` took a `slots` list from the
    request and handed it STRAIGHT to `_emit_commitments`, which writes
    `time_start`/`time_end` into a `ProtectedCommitment` and from there into a
    solver `Rule`. Every commitment is converted inside ONE try/except, so a
    single '29:00' does not cost one program its window -- it silently
    disables protected time for the whole household. The clamp on
    `sessions_per_week` and `minutes` was written for exactly that failure and
    then the slot list walked around it.

    A window is a DAY and a START. The end is computed from `minutes`, never
    accepted, so the two can never disagree and a window can never be
    stretched by a client that just says so.
    """
    minutes = max(MIN_MINUTES, min(MAX_MINUTES, int(minutes or 25)))
    out, seen = [], set()
    for raw in (slots or []):
        if not isinstance(raw, dict):
            continue
        try:
            day = int(raw.get('day'))
        except (TypeError, ValueError):
            continue
        if not 0 <= day <= 6:
            continue
        m = _HHMM_RE.match(str(raw.get('time_start') or '').strip())
        if not m:
            continue
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23:
            continue
        key = (day, hour, minute)
        if key in seen:
            continue
        seen.add(key)
        end_total = min(hour * 60 + minute + minutes, 23 * 60 + 59)
        out.append({'day': day, 'time_start': _fmt_hhmm(hour, minute),
                    'time_end': _fmt_hhmm(end_total // 60, end_total % 60)})
    out.sort(key=lambda s: (s['day'], s['time_start']))
    return out[:MAX_SESSIONS_PER_WEEK]


def clamp_shape(shape: dict) -> dict:
    """A program's shape, forced inside what a week can actually hold.

    Every door into a program goes through here -- the page, the endpoint, the
    chat tool -- because a bound that lives in only one of them is a bound
    somebody routes around without meaning to.
    """
    shape = dict(shape or {})
    try:
        per_week = int(shape.get('sessions_per_week') or 3)
    except (TypeError, ValueError):
        per_week = 3
    try:
        minutes = int(shape.get('minutes') or 25)
    except (TypeError, ValueError):
        minutes = 25
    shape['sessions_per_week'] = max(1, min(MAX_SESSIONS_PER_WEEK, per_week))
    shape['minutes'] = max(MIN_MINUTES, min(MAX_MINUTES, minutes))
    days = []
    for d in (shape.get('preferred_days') or []):
        try:
            d = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= d <= 6 and d not in days:
            days.append(d)
    shape['preferred_days'] = days
    # Chosen windows, when a person has picked them rather than taking what
    # was proposed. They live on the SHAPE because that is what they are --
    # the same statement as "three evenings a week", said exactly. Which also
    # means the two cannot be allowed to disagree: a week with four chosen
    # windows IS four sessions a week, and pacing is arithmetic over that
    # number, so it follows the list rather than sitting beside it lying.
    shape['slots'] = sanitize_slots(shape.get('slots'), shape['minutes'])
    if shape['slots']:
        shape['sessions_per_week'] = len(shape['slots'])
    return shape


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


def _slot_ts(slot_date) -> float:
    """When a session answered for a named slot actually happened.

    A 9pm slot asks in the morning, so "yes, it happened" is very often tapped
    the day AFTER the evening it is about. Stamping that answer with `now`
    would file Thursday's practice under Friday -- which quietly breaks two
    things at once: `weekday_shortfall` would blame the wrong day, and the
    prompt for Thursday would never clear, because nothing was ever logged on
    Thursday. Midday is used rather than the slot's own end time because this
    layer does not hold the commitment, and any hour inside the day derives
    the same weekday. A date in the future clamps to now: a session cannot
    have happened yet.
    """
    if not slot_date:
        return None
    try:
        d = datetime.date.fromisoformat(str(slot_date))
    except (TypeError, ValueError):
        return None
    stamp = datetime.datetime(d.year, d.month, d.day, 12, 0)
    return min(stamp, datetime.datetime.now()).timestamp()


def log_session(program_id: str, minutes: int = None, source: str = 'added',
                note: str = '', slot_date: str = None) -> dict:
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
    entry = {'minutes': mins, 'source': source, 'note': (note or '').strip()}
    ts = _slot_ts(slot_date)
    if ts:
        entry['ts'] = ts
    storage.append_program_session(program_id, entry)
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
    # The last milestone IS done -- that is the design's own definition, and
    # without this the only exit from a finished plan was a button reading
    # "Dropped. The time is back." Reaching the end of a plan must not be
    # indistinguishable from abandoning it, and a program nobody can finish
    # keeps its practice windows and keeps asking "did it happen?" forever.
    if not any(not ph.get('milestone_hit_at') for ph in phases):
        released = release_commitments(program_id)
        storage.update_program(program_id, {'state': 'done',
                                            'finished_at': time.time()})
        return {'status': 'success', 'schedule_dirty': bool(released),
                'message': f"🎉 {row.get('title')}: {phase_name} done — "
                           f"that's the last one. The whole program is done."}
    return {'status': 'success',
            'message': f"🎉 {row.get('title')}: {phase_name} done."}


def finish(program_id: str) -> dict:
    """A person says it's finished. The other half of `done`: the design says
    done is the last milestone OR a person saying so, and only the first of
    those was ever built.

    Finishing releases the reserved time the same way dropping does, because
    the time really is free either way — what differs is the record, and the
    record is the whole point of having two words for it.
    """
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') in ('done', 'dropped'):
        return {'status': 'error',
                'message': f"That program is already {row.get('state')}."}
    released = release_commitments(program_id)
    storage.update_program(program_id, {'state': 'done',
                                        'finished_at': time.time()})
    return {'status': 'success', 'schedule_dirty': bool(released),
            'message': f"{row.get('title')} is finished. The time is back."}


def release_commitments(program_id: str) -> int:
    """Hand the reserved evenings back and stop believing they are ours.

    Every exit from a live program goes through here -- pause, done, drop,
    re-shape -- because reserved time that outlives the thing that reserved it
    is worse than no reservation at all: CP-SAT keeps refusing to schedule a
    drive in an evening nothing is using, and nobody can see why.
    """
    row = storage.get_program(program_id)
    if not row:
        return 0
    em = dict(row.get('emissions') or {})
    ids = list(em.get('commitment_ids') or [])
    for cid in ids:
        try:
            storage.delete_protected_commitment(cid)
        except Exception as e:
            print(f"[programs] could not remove commitment {cid}: {e}")
    em['commitment_ids'] = []
    storage.update_program(program_id, {'emissions': em})
    return len(ids)


def emitted_slots(program: dict) -> list:
    """The windows this program's own commitments currently occupy.

    Read back off the rows rather than recomputed from `shape`: `propose_slots`
    pads the days out and the parent can edit every one of them on the
    approval screen, and none of that is ever written back into `shape`. So
    the commitment rows are the only honest record of when this actually
    happens -- which matters most on resume, where re-proposing would quietly
    move somebody's practice to a different evening than the one they paused.
    """
    ids = set((program.get('emissions') or {}).get('commitment_ids') or [])
    if not ids:
        return []
    out = []
    for pc in storage.get_protected_commitments(
            member_id=program.get('member_id'), include_inactive=True):
        if pc.get('id') not in ids:
            continue
        for d in (pc.get('days_of_week') or []):
            out.append({'day': d, 'time_start': pc.get('time_start'),
                        'time_end': pc.get('time_end')})
    return sorted(out, key=lambda s: (s['day'], s['time_start'] or ''))


def pause(program_id: str) -> dict:
    """Stop, without failing. Pause REMOVES the reservations — the spec is
    explicit and it is the whole point: a paused program that keeps CP-SAT out
    of three evenings a week is not paused, it is invisible.

    The windows themselves are remembered on the row so that resuming puts
    back exactly what was there rather than proposing somewhere new.
    """
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') != 'active':
        # ONLY active. `resume()` emits real reserved time, so every state
        # this accepts becomes a route into the family's week -- and pausing a
        # `proposed` program and then resuming it claimed practice windows
        # with no parent, no footprint screen, and `approved_by` and
        # `baseline.start_date` never set. Both endpoints let an owner act
        # freely, which is right for a program somebody already approved and
        # exactly wrong as a way in: approving is the one act this arc says is
        # never an ownership matter. Guarded here so the pair can only ever
        # move a program a parent has already approved.
        return {'status': 'error',
                'message': f"That program is {row.get('state')} — only an "
                           f"active program can be paused."}
    slots = emitted_slots(row)
    released = release_commitments(program_id)
    storage.update_program(program_id, {'state': 'paused',
                                        'paused_at': time.time(),
                                        'paused_slots': slots})
    return {'status': 'success', 'schedule_dirty': bool(released),
            'message': 'Paused. Nothing counts against it, and the evenings '
                       'are back until you resume.'}


def _revert_resume(program_id: str, made: list, slots: list,
                   keep: dict) -> None:
    """Undo a half-finished resume and leave the row where a retry works.

    `_emit_commitments` persists each id the moment it lands, which is what
    makes a crash survivable -- but only if somebody undoes the ones that DID
    land. Unbracketed, a storage failure on the second of three slots
    propagated out with the row still `paused`, `paused_slots` still full, and
    one commitment created AND recorded, so the retry emitted all three again
    and double-claimed the first evening. `approve()` has been bracketed for
    exactly this since it was written; the write path extracted out of it has
    to be guarded wherever it is called, not only there.

    Same ranking as `_revert_attempt`: every cleanup step runs through
    `_quietly` and the state write sits in a `finally`, because a recovery
    path that can itself fail is a recovery path that strands people. `paused`
    with the slots remembered and no commitments held is a genuinely
    consistent state -- it is exactly what pause promises -- so a retry starts
    from a clean row rather than from a half-claimed week.
    """
    try:
        for cid in made or []:
            _quietly(f"delete commitment {cid}",
                     storage.delete_protected_commitment, cid)
    finally:
        _quietly('put the program back to paused', storage.update_program,
                 program_id,
                 {'state': 'paused', 'paused_slots': list(slots or []),
                  'emissions': {**(keep if isinstance(keep, dict) else {}),
                                'commitment_ids': []}})


def resume(program_id: str) -> dict:
    """Back on — and the reservations come back with it, through the same
    write path `approve()` uses rather than a second one that could drift
    away from it.

    Only from `paused`, and `paused` is now only reachable from `active`: the
    pair moves a program a parent already approved, and can never be a way of
    claiming time nobody approved at all.
    """
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') != 'paused':
        return {'status': 'error',
                'message': f"That program is {row.get('state')}, not paused."}
    slots = [s for s in (row.get('paused_slots') or []) if s.get('time_start')]
    if not slots:
        # A row paused by the code that shipped BEFORE pause released anything
        # still has its commitments standing and its ids recorded, and
        # remembers no slots. Reading the windows off those live rows resumes
        # it to what it actually had -- proposing fresh ones would place them
        # AROUND the standing windows on purpose (that is what `propose_slots`
        # does with a member's existing commitments) and leave six windows on
        # different evenings.
        slots = emitted_slots(row)
    if not slots:
        # Nothing remembered and nothing standing -- windows deleted by hand
        # while it slept. Propose fresh ones rather than come back with no
        # practice time at all.
        slots = propose_slots(row.get('member_id'), row.get('shape') or {})
    # Whatever is still standing goes before anything new is written, so
    # re-emitting can never double-claim an evening the row already holds.
    release_commitments(program_id)
    row = storage.get_program(program_id) or row
    emissions = dict(row.get('emissions') or {})
    emissions['commitment_ids'] = []
    keep = dict(emissions)
    made = []
    try:
        _emit_commitments(program_id, row, slots, emissions, made)
        storage.update_program(program_id, {'state': 'active',
                                            'paused_at': None,
                                            'paused_slots': [],
                                            'emissions': emissions})
    except Exception as e:
        _revert_resume(program_id, made, slots, keep)
        return {'status': 'error',
                'message': f"Couldn't claim those evenings again, so nothing "
                           f"was kept — {row.get('title') or 'this program'} "
                           f"is still paused and can be resumed again once "
                           f"that's sorted out: {e}"}
    return {'status': 'success', 'schedule_dirty': True,
            'message': f"Back on. {len(slots)} practice window(s) claimed again."}


def reshape(program_id: str) -> dict:
    """Drift's real answer: hand the program back to `proposed` so the
    footprint can be rebuilt and approved again.

    The drift finding asks "want it back, or shall I re-shape the week?" and
    for one release that offer had nothing behind it — no action, no endpoint,
    and `approve()` demands `state == 'proposed'`, so nothing in the app could
    perform the sentence it had just said. An offer the app cannot honour is
    worse than no offer: it teaches people the assistant is decorative.

    This never re-creates the deleted window silently. It puts the program
    back in front of a person with the whole footprint on one screen, which
    is the same gate the time went through the first time.
    """
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    if row.get('state') not in ('active', 'paused'):
        return {'status': 'error',
                'message': f"That program is {row.get('state')} — there's "
                           f"nothing to re-shape."}
    released = release_commitments(program_id)
    storage.update_program(program_id, {'state': 'proposed',
                                        'paused_at': None, 'paused_slots': []})
    return {'status': 'success', 'schedule_dirty': bool(released),
            'message': f"{row.get('title')} is back to a proposal — approve "
                       f"the footprint on the Programs page to claim the "
                       f"week again."}


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
    already committed and picks windows that do not sit on top of it.

    A chosen `shape['slots']` wins outright and is not second-guessed: the
    whole point of picking Tuesday at seven is that the app stops picking. An
    empty list is how a family hands the choice back -- proposing resumes from
    the preferred days, exactly as it did before anybody touched anything.
    """
    shape = clamp_shape(shape)
    if shape.get('slots'):
        return [dict(s) for s in shape['slots']]
    per_week = shape['sessions_per_week']
    minutes = shape['minutes']
    days = list(shape['preferred_days'])
    # Pad out to the number of sessions asked for. The loop stops the moment a
    # pass adds nothing, not only when it is full: with every weekday already
    # taken there is no candidate left, and a `while len(days) < per_week`
    # with no such guard spins forever on any `per_week` above seven. The
    # clamp above makes that unreachable; this break is what makes it
    # unreachable a second, independent way, because the failure mode was a
    # threadpool worker pinned at 100% CPU on every page load, permanently.
    while len(days) < per_week:
        for candidate in (1, 3, 5, 0, 2, 4, 6):
            if candidate not in days:
                days.append(candidate)
                break
        else:
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
        # A window has to end inside the day it started in. `time_end` is
        # written straight into a `ProtectedCommitment` and from there into a
        # solver `Rule`, and every commitment is converted inside ONE
        # try/except -- so a single '29:00' does not cost one program its
        # window, it silently disables protected time for the whole household.
        end_total = min(hour * 60 + minute + minutes, 23 * 60 + 59)
        out.append({'day': d, 'time_start': _fmt_hhmm(hour, minute),
                    'time_end': _fmt_hhmm(end_total // 60, end_total % 60)})
    return out


# --- Where a practice window is actually VISIBLE ---------------------------
# A program claimed the week and then nothing showed it. The window became a
# `ProtectedCommitment`, which the solver honours through `member.driver_id`
# and which no shared surface has ever drawn -- commitments are private by
# design ("somebody's own life is nobody else's business", the erosion finding
# in services/watchers.py). The effect on a family is that an approved program
# is an invisible arrangement one person has to remember, and everybody else
# books over it in good faith because there is nothing there to see.
#
# So programs get their own dated feed, and only programs. A practice window
# is already household knowledge -- the Programs page lists every member's,
# and the wall card names whose milestone is close -- so putting the TIME
# beside the thing everyone can already see discloses nothing new. Commitments
# that did not come from a program stay exactly as private as they were.
#
# These are not calendar events and must never become them: an event needs a
# driver, and a recurring practice event would arrive in the solver as work to
# assign rather than time to protect.

PUSH_STATE_KEY = 'programs_practice_pushed'
PUSH_WINDOW_SECONDS = 15 * 60      # how late a start-of-window push may fire
PUSH_KEEP_DAYS = 3


def practice_windows(start: datetime.date, end: datetime.date,
                     member_id: str = None) -> list:
    """Every practice window between two dates, as dated occurrences.

    One row per day a program's claimed window lands on, carrying what the
    session IS (the current phase and its steps) rather than only when it is
    -- a time with no content is the thing that made this feature invisible
    twice over.
    """
    members = {m['id']: m for m in storage.get_all_members(include_archived=True)}
    live = {c['id']: c for c in storage.get_protected_commitments(member_id=member_id)
            if c.get('active')}
    out = []
    for row in storage.get_programs(member_id=member_id):
        if row.get('state') != 'active':
            # Paused and proposed programs hold no time: pause releases the
            # commitments outright, and a proposal has never claimed any.
            continue
        phase = progress(row).get('phase') or {}
        member = members.get(row.get('member_id')) or {}
        for cid in (row.get('emissions') or {}).get('commitment_ids') or []:
            pc = live.get(cid)
            if not pc:
                continue
            days = set(pc.get('days_of_week') or [])
            day = start
            while day <= end:
                if day.weekday() in days:
                    out.append({
                        'program_id': row['id'],
                        'commitment_id': cid,
                        'member_id': row.get('member_id'),
                        'member_name': member.get('name') or '',
                        'title': row.get('title') or 'Practice',
                        'date': day.isoformat(),
                        'time_start': pc.get('time_start'),
                        'time_end': pc.get('time_end'),
                        'phase_name': phase.get('name') or '',
                        'steps': list(phase.get('steps') or []),
                        'milestone': phase.get('milestone') or '',
                        'logged': _already_logged(row, day),
                    })
                day += datetime.timedelta(days=1)
    out.sort(key=lambda w: (w['date'], w['time_start'] or '', w['title']))
    return out


def due_practice_pushes(now=None) -> list:
    """Windows that have just started and have not been announced yet.

    The "did it happen?" ask has always existed and always arrived AFTERWARDS,
    which is a strange thing to be the only cue: it asks about a session
    nothing ever told anybody to start. This is the other half, and it carries
    the steps, because "practice now" without what to practise is the same
    empty gesture in a different costume.

    Marked in `app_state` rather than in the program row: what got announced
    is app bookkeeping, and a program document is the one place in this app
    that must not accumulate fields about how somebody is doing.
    """
    now = now or datetime.datetime.now()
    today = now.date()
    fired = set(storage.get_app_state(PUSH_STATE_KEY) or [])
    out = []
    for w in practice_windows(today, today):
        if w['logged']:
            continue
        try:
            sh, sm = [int(x) for x in (w['time_start'] or '').split(':')[:2]]
        except (ValueError, TypeError):
            continue
        start_at = datetime.datetime.combine(today, datetime.time(sh, sm))
        late = (now - start_at).total_seconds()
        if not 0 <= late <= PUSH_WINDOW_SECONDS:
            continue
        key = f"{w['program_id']}|{w['date']}|{w['time_start']}"
        if key in fired:
            continue
        out.append({**w, 'push_key': key})
    return out


def mark_practice_pushed(keys) -> None:
    """Remember what was announced, and forget it again within days -- this
    list exists to stop a duplicate push across a restart, not to become a
    record of somebody's practice."""
    keys = [k for k in (keys or []) if k]
    if not keys:
        return
    cutoff = (datetime.date.today()
              - datetime.timedelta(days=PUSH_KEEP_DAYS)).isoformat()
    kept = [k for k in (storage.get_app_state(PUSH_STATE_KEY) or [])
            if isinstance(k, str) and k.split('|')[1:2] and k.split('|')[1] >= cutoff]
    storage.set_app_state(PUSH_STATE_KEY, sorted(set(kept) | set(keys)))


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


def _revert_attempt(program_id: str, emissions: dict,
                    restore: dict = None) -> None:
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
        # Last and least: putting the row's emissions back the way this
        # attempt found them. Usually that is the empty triple; after a
        # re-shape it is the kit thread and target event that were ALREADY
        # standing before this attempt and which it therefore never deleted --
        # writing an empty triple over those would orphan them for good. It
        # goes after the handback so that its failing costs a stale dict, not
        # a stranded program.
        _quietly('put the emissions back the way they were',
                 storage.update_program, program_id,
                 {'emissions': restore if isinstance(restore, dict) else
                  {'commitment_ids': [], 'thread_ids': [], 'event_ids': []}})


def _emit_commitments(program_id: str, row: dict, slots: list,
                      emissions: dict, made: list = None) -> dict:
    """Turn proposed windows into real reserved time, stamping each id as it
    lands.

    One commitment per slot, not merged by window -- three practice sessions a
    week are three claimed windows, each one individually visible and
    individually undoable in the commitments list. The row is updated after
    EVERY insert rather than once at the end, so a crash halfway through
    leaves a program that knows about the rows it really created instead of an
    orphan nobody owns.

    Shared by `approve()` and `resume()` on purpose: resuming re-creates the
    emissions, and a second copy of this loop is a second place for the two to
    drift apart.
    """
    for s in slots:
        # add_protected_commitment writes the dict as given -- it does not go
        # through the pydantic model the way the HTTP route does -- so the id
        # has to be minted here, not left for storage to invent one.
        cid = storage.add_protected_commitment({
            'id': uuid.uuid4().hex,
            'member_id': row['member_id'], 'title': row.get('title') or 'Practice',
            'days_of_week': [s['day']], 'time_start': s['time_start'],
            'time_end': s['time_end'], 'active': True})
        emissions['commitment_ids'].append(cid)
        # `made` is appended to INSIDE the loop, never sliced off afterwards:
        # the whole point of this list is the case where the loop RAISES
        # halfway, and a caller that computes it from the return value learns
        # nothing at all in exactly that case -- leaving the rows this attempt
        # really did write as orphans the revert never sees.
        if made is not None:
            made.append(cid)
        storage.update_program(program_id, {'emissions': emissions})
    return emissions


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

    # Whatever the caller sent goes through the same sanitation the shape
    # does. This is a request body reaching a solver rule; trusting it was a
    # hole that only stayed shut because the one page that posts here happened
    # to echo back what the server had just proposed.
    shape = row.get('shape') or {}
    use = (sanitize_slots(slots, shape.get('minutes') or 25)
           or propose_slots(row.get('member_id'), shape))
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

    # A program can reach `proposed` a SECOND time, through `reshape()` after
    # drift. Its kit thread and its target event are still standing, so the
    # emissions start from what the row already holds rather than an empty
    # triple -- otherwise a re-approval orphans the thread it forgot and opens
    # a duplicate beside it. `made` tracks only what THIS attempt created,
    # because that is the exact set a revert is allowed to delete.
    prior = dict(row.get('emissions') or {})
    emissions = {'commitment_ids': [],
                 'thread_ids': list(prior.get('thread_ids') or []),
                 'event_ids': list(prior.get('event_ids') or [])}
    made = {'commitment_ids': [], 'thread_ids': [], 'event_ids': []}
    restore = {'commitment_ids': [], 'thread_ids': list(emissions['thread_ids']),
               'event_ids': list(emissions['event_ids'])}

    # Everything from here to the final flip is bracketed. The claim above
    # moved the point of no return earlier than a plain `state='proposed'`
    # row, and nothing else transitions a program OUT of `approving` -- so
    # any exception in here, not just the calendar's, has to be caught and
    # reverted, or the program is stuck un-retryable forever.
    try:
        # Local writes first: cheap, ours, and undoable by a person who can
        # see them.
        _emit_commitments(program_id, row, use, emissions,
                          made['commitment_ids'])

        kit = _kit_line(row)
        if kit and not emissions['thread_ids']:
            tid = storage.add_thread({'title': kit, 'kind': 'project',
                                      'owner_member_id': row['member_id'],
                                      'goal': 'Have what the next phase needs',
                                      'created_by': approver_id})
            emissions['thread_ids'].append(tid)
            made['thread_ids'].append(tid)
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
                made['event_ids'].append(ev_id)
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
        _revert_attempt(program_id, made, restore)
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
    window_days = int(storage.get_settings().get(
        'programs_rebaseline_days', REBASELINE_WINDOW_DAYS) or REBASELINE_WINDOW_DAYS)
    window_start = max(began or now.date(),
                       now.date() - datetime.timedelta(days=window_days))
    weeks = max(1, (now.date() - window_start).days // 7)
    done = {}
    for s in sessions_between(program, window_start, now.date()):
        try:
            wd = datetime.datetime.fromtimestamp(float(s['ts'])).weekday()
        except (KeyError, TypeError, ValueError):
            continue
        done[wd] = done.get(wd, 0) + 1
    gaps = {d: weeks - done.get(d, 0) for d in days}
    gap = max(gaps.values()) if gaps else 0
    if gap < 2:
        return None
    # Every preferred day tying is the normal case for a program that has
    # logged nothing at all, and a strict `>` used to hand back whichever one
    # happened to be first in the list -- so a program with Mon/Wed/Fri and an
    # empty log said "Mondays keep getting eaten" about three equally empty
    # days. The whole value of that sentence is naming the RIGHT day, so when
    # nothing distinguishes them it names none of them and says "these days".
    worst_days = sorted(d for d, g in gaps.items() if g == gap)
    worst = worst_days[0] if len(worst_days) == 1 else None
    logged = len(sessions_between(program, window_start, now.date()))
    return {'weekday': worst, 'weekdays': worst_days, 'expected': weeks,
            'done': done.get(worst, 0) if worst is not None else 0,
            'window_weeks': weeks, 'window_sessions': logged,
            'per_week': max(1, int(shape.get('sessions_per_week') or 1))}


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


def _stretch_factor(short: dict) -> float:
    """How much more room the plan needs, from what the window actually
    delivered against what it assumed. Bounded at double: a fortnight where
    almost nothing happened is a reason to give the plan room, not a reason to
    turn a six-week phase into a six-month one."""
    expected = max(1, int(short.get('window_weeks') or 1)) * \
        max(1, int(short.get('per_week') or 1))
    done = max(0, int(short.get('window_sessions') or 0))
    if not done:
        return 2.0
    return max(1.0, min(2.0, expected / done))


def _stretch_phases(phases: list, factor: float) -> list:
    """Give the remaining phases more weeks — the counterpart to
    `_compress_phases`, for the program that has no date to compress toward.

    A phase whose milestone is already hit is done and is never touched. Every
    phase still ahead gains at least one week, so a stretch always really
    stretches: a "the timeline bent" finding that moved nothing is the same
    fake door as an offer with no action behind it.
    """
    out = []
    for p in phases:
        p = dict(p)
        if not p.get('milestone_hit_at'):
            weeks = max(1, int(p.get('weeks') or 1))
            p['weeks'] = max(weeks + 1, int(math.ceil(weeks * factor)))
        out.append(p)
    return out


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
    cooldown_days = int(storage.get_settings().get(
        'programs_rebaseline_cooldown_days', REBASELINE_COOLDOWN_DAYS)
        or REBASELINE_COOLDOWN_DAYS)
    if last and (now.timestamp() - float(last)) < cooldown_days * 86400:
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
    elif not baseline.get('target_event_id'):
        # No target date at all -- which is the DEFAULT, both from the chat
        # tool and from the page unless somebody types one, so this is the
        # common program rather than an edge case.
        #
        # An event id with no date falls through BOTH branches deliberately:
        # that is malformed data (the schema writes the pair together), and
        # the event still pins a real day in the world that this app cannot
        # read. Giving the plan more weeks against a date it cannot see is
        # exactly the lie about fitting the compress path refuses to tell, so
        # nothing moves and the finding says only what is on the table. For one release this branch
        # did not exist: it bumped a counter, burned the fortnight cooldown,
        # and still posted "want to try a different day?" while the timeline
        # it promised to stretch was never touched. Here the phases ARE the
        # timeline, so they are what gives.
        phases = _stretch_phases(original_phases, _stretch_factor(short))
        update['phases'] = phases
    storage.update_program(program['id'], update)
    # `fits` alone isn't enough to word the finding honestly: a program that
    # already had slack before the date needs `fits=True` without ever
    # claiming credit for a squeeze that never happened. `date_moved` closes
    # the same gap on the other branch -- malformed baseline data (an event id
    # with no date, or a date string that won't parse) must not read as "I
    # gave the plan more room" when nothing was ever touched.
    return {'weekday': short['weekday'], 'weekdays': short.get('weekdays') or [],
            'baseline': baseline, 'phases': phases,
            'fits': fits, 'phases_changed': phases != original_phases,
            'date_moved': date_moved,
            'stretched': phases is not original_phases and fits is None
                         and not date_moved}


def orphaned_emissions(program: dict) -> list:
    """Emission ids the program believes in that are no longer there.

    Someone deleted a practice window by hand. The program stops believing the
    time is reserved and says so once — it never silently re-creates it,
    because an app that puts back what you deleted is an app you stop trusting.
    """
    ids = list((program.get('emissions') or {}).get('commitment_ids') or [])
    if not ids:
        return []
    # include_inactive, because DEACTIVATING is not DELETING. The default read
    # hides `active: False` rows, so a window somebody switched off for a
    # fortnight looked exactly like one they had deleted -- the program fired
    # the drift finding and then permanently forgot the id, which meant
    # switching it back on could never re-link it. Only a row that is really
    # gone counts as gone.
    live = {c['id'] for c in storage.get_protected_commitments(include_inactive=True)}
    return [cid for cid in ids if cid not in live]


def forget_emissions(program_id: str, gone: list) -> None:
    row = storage.get_program(program_id)
    if not row:
        return
    em = dict(row.get('emissions') or {})
    em['commitment_ids'] = [c for c in (em.get('commitment_ids') or [])
                            if c not in set(gone)]
    storage.update_program(program_id, {'emissions': em})


def due_asks_for(program: dict, now=None) -> list:
    """Slots of ONE program that have passed and have not been logged.

    One question per slot: silence counts nothing — the number only means
    sessions a person said they did. Quiet hours are honoured, so a 9pm slot
    asks in the morning rather than at 9:25pm, and they are the PROGRAM
    OWNER's quiet hours because this question is only ever put to the person
    whose program it is. It rides their own surface (the PWA card), not a DM
    to their parents: a parent tapping "yes, it happened" about a session
    nobody watched is the one place in this arc where the app could claim more
    than happened, and the design's promise is that it never does.
    """
    from services import family_digest
    now = now or datetime.datetime.now()
    if program.get('state') != 'active':
        return []
    if not storage.get_settings().get('programs_enabled', True):
        return []
    member = storage.get_member(program.get('member_id'))
    if not member or family_digest.in_member_quiet_hours(member, now):
        return []
    grace_hours = float(storage.get_settings().get(
        'programs_ask_grace_hours', ASK_GRACE_HOURS) or ASK_GRACE_HOURS)
    cids = set((program.get('emissions') or {}).get('commitment_ids') or [])
    out = []
    for pc in storage.get_protected_commitments(member_id=program['member_id']):
        if pc.get('id') not in cids:
            continue
        # An evening the family GAVE UP through negotiation's `lift_protected`
        # is not an evening anybody failed to practise on -- it is one they
        # agreed to spend elsewhere. Asking "did it happen?" about it is the
        # app forgetting a deal it brokered itself.
        lifted = {str(r.get('date')) for r in
                  storage.get_protected_exceptions(pc.get('id'))}
        for d in (pc.get('days_of_week') or []):
            slot_date = _last_occurrence(d, now)
            if slot_date is None or slot_date.isoformat() in lifted:
                continue
            ended = _slot_end(slot_date, pc.get('time_end') or '19:25')
            if (now - ended).total_seconds() < grace_hours * 3600:
                continue
            if _already_logged(program, slot_date):
                continue
            out.append({'program': program, 'slot_date': slot_date.isoformat(),
                        'body': f"{program.get('title')} on "
                                f"{slot_date.strftime('%A')} — did it happen?"})
    return sorted(out, key=lambda a: a['slot_date'])


def due_session_asks(now=None) -> list:
    """Every program's pending question, in one pass.

    Each program's check is wrapped on its own, the same way the drift and
    rebaseline checks in watchers.py guard themselves per program --
    one member's malformed record (a bad quiet-hours string, a corrupt
    commitment) must cost only that program's ask, not silence every family
    member's practice check for the whole sweep.
    """
    now = now or datetime.datetime.now()
    out = []
    for row in storage.get_programs(state='active'):
        try:
            out.extend(due_asks_for(row, now))
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


# --- What a hallway is allowed to know --------------------------------------

CELEBRATION_WINDOW_DAYS = 7


def celebrations(now=None) -> dict:
    """The wall's whole view of every program in the house, and nothing else.

    The wall card used to fetch `GET /api/programs` — which could never work
    from a panel (a `?panel=true` board identifies as DEVICE, and both the
    read scope and the admin-surface reading refuse a device outright, so the
    card said "Nothing to celebrate yet." forever), and which should not work
    from a panel even if it did: the full program payload carries an aim in
    somebody's own words, a curated plan, a target date and every session they
    have logged. A wall is read by whoever is in the room.

    So this is a PROJECTION, not a widened read. Three sentences: whose
    milestone is close, what got practised this week, who just reached one.
    Names and titles, never a total to divide, never an ordering — a family is
    not a cohort, and the wall is the surface where treating it like one would
    land hardest.
    """
    now = now or datetime.datetime.now()
    since = now.timestamp() - CELEBRATION_WINDOW_DAYS * 86400
    names = {m['id']: (m.get('name') or '')
             for m in storage.get_all_members(include_archived=True)}
    up_next, practiced, celebrated = None, [], []
    for row in storage.get_programs():
        # Paused is a peer of active, not a flavour of stopped: the wall still
        # gets to celebrate a paused program's last week same as a running one.
        if row.get('state') not in ('active', 'paused'):
            continue
        who = names.get(row.get('member_id')) or 'Somebody'
        phase = progress(row)['phase']
        if phase and phase.get('milestone'):
            try:
                weeks = int(phase.get('weeks'))
            except (TypeError, ValueError):
                weeks = None
            # A phase's own stated length is the only honest signal of "soon"
            # a program carries -- nothing here counts down or divides one
            # number by another.
            if up_next is None or (weeks is not None and
                                   (up_next['weeks'] is None or
                                    weeks < up_next['weeks'])):
                up_next = {'weeks': weeks, 'member_name': who,
                           'milestone': phase.get('milestone') or '',
                           'title': row.get('title') or ''}
        recent = 0
        for s in row.get('sessions') or []:
            try:
                if float(s.get('ts') or 0) >= since:
                    recent += 1
            except (TypeError, ValueError):
                continue
        if recent:
            practiced.append({'key': row['id'], 'member_name': who,
                              'title': row.get('title') or '',
                              'sessions': recent})
        for ph in row.get('phases') or []:
            try:
                hit = float(ph.get('milestone_hit_at') or 0)
            except (TypeError, ValueError):
                continue
            if hit >= since:
                celebrated.append({'key': f"{row['id']}:{ph.get('name')}",
                                   'member_name': who,
                                   'milestone': ph.get('milestone')
                                                or ph.get('name') or ''})
    return {'up_next': up_next, 'practiced': practiced,
            'celebrated': celebrated}
