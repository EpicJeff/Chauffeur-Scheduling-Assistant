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


def _revert_attempt(program_id: str, emissions: dict) -> None:
    """Undo what THIS attempt stamped, because a claim that is not going to
    finish must not leave reserved time nothing owns behind it.

    Deletes the commitment rows and the kit thread the attempt already
    created, and a calendar event too in the one case there can be one: the
    state flip is now inside the same bracket as everything else, so a
    failure on that very last write can be reached with a real event id
    already sitting in `emissions['event_ids']` (the calendar branch runs
    right before it). Hands the claim back to `proposed` BEFORE clearing the
    row's `emissions` field -- if that last, purely cosmetic write also
    fails, the program is still retryable rather than the revert itself
    stranding it. A revert that can strand is worse than no revert.
    """
    if emissions.get('event_ids'):
        from services import calendar as _cal
        settings = storage.get_settings() or {}
        cal_id = (settings.get('calendar_ids') or ['primary'])[0]
        for eid in emissions['event_ids']:
            try:
                _cal.remove_event(cal_id, eid)
            except Exception as e:
                print(f"[programs] could not clean up calendar event {eid}: {e}")
    for tid in emissions.get('thread_ids') or []:
        try:
            storage.delete_thread(tid)
        except Exception as e:
            print(f"[programs] could not clean up thread {tid}: {e}")
    for cid in emissions.get('commitment_ids') or []:
        try:
            storage.delete_protected_commitment(cid)
        except Exception as e:
            print(f"[programs] could not clean up commitment {cid}: {e}")
    storage.claim_program(program_id, 'approving', 'proposed')
    storage.update_program(program_id, {
        'emissions': {'commitment_ids': [], 'thread_ids': [], 'event_ids': []}})


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
        # not stranded. The success path below is never reached when this
        # branch runs, so it cannot revert itself.
        _revert_attempt(program_id, emissions)
        return {'status': 'error', 'message': str(e)}

    return {'status': 'success', 'schedule_dirty': True,
            'message': f"{row.get('title')} is on. "
                       f"{len(emissions['commitment_ids'])} practice window(s) claimed."}
