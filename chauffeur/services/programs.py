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

from services import storage

# The states a program can be in. `paused` is a peer of `active`, not a flavour
# of failure: if the only way out of a program is to fail it, people fail it.
LIVE_STATES = ('proposed', 'active', 'paused')


def progress(program: dict) -> dict:
    """What this program has done. Every number is monotonic."""
    sessions = program.get('sessions') or []
    phases = program.get('phases') or []
    hit = [p for p in phases if p.get('milestone_hit_at')]
    current = next((p for p in phases if not p.get('milestone_hit_at')), None)
    return {'sessions': len(sessions),
            'minutes': sum(int(s.get('minutes') or 0) for s in sessions),
            'milestones_hit': len(hit),
            'milestones_total': len(phases),
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
        if ph.get('name') == phase_name and not ph.get('milestone_hit_at'):
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
    storage.update_program(program_id, {'state': 'paused',
                                        'paused_at': time.time()})
    return {'status': 'success', 'message': 'Paused. Nothing counts against it.'}


def resume(program_id: str) -> dict:
    row = storage.get_program(program_id)
    if not row:
        return {'status': 'error', 'message': 'That program is no longer here.'}
    storage.update_program(program_id, {'state': 'active', 'paused_at': None})
    return {'status': 'success', 'message': 'Back on.'}
