"""The Morning & Bedtime Runway (arc R2) — an ambient lens over routines.

Parents act as vocal alarm clocks — "put your shoes on" ten times every
morning. The runway replaces the repetition with a PULL: a progress vehicle
on the wall that fills as the flagged routine items (and their steps) tick
off, paced against a real deadline.

The anchors, from the family's own data (decided 2026-08-21):

  * **Bedtime**: the flagged items' own `time_of_day` — the family already
    keeps a timed Bedtime item. Last flagged time = runway end.
  * **Morning**: item times are the spine, which is what makes NO-SCHOOL
    mornings work — up, dressed, breakfast all carry times regardless of
    destination. When the solver has a real departure for this kid (a drive's
    leave-at, a covered ride's be-ready-at), it TIGHTENS the end:
    min(last item time, be-ready). A school day compresses automatically;
    Saturday runs on item times alone.

Rules this module holds to:

  * **A lens, never a writer.** It reads routines_for_day and the cached
    schedule; ticks happen through the same check endpoints as always; XP
    and streaks are untouched; the rocket mints nothing.
  * **"Behind" is honest**: a flagged, TIMED item unticked past its time
    plus grace — never raw idle-time guessing (a four-year-old mid-shoe is
    not tapping a wall). This flag is R3's cue trigger; here it only tints.
  * No flagged items — no runway. Blank means blank.
"""
import datetime
from typing import Optional

from services import storage

GRACE_MINS = 10          # a timed item is "behind" this long after its time
WINDOW_LEAD_MINS = 45    # the runway takes over the lane this long before
                         # its first timed item
WINDOW_TAIL_MINS = 90    # and lets go this long after its end


def _hhmm_to_dt(date_str: str, hhmm: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(f"{date_str}T{hhmm}:00")
    except (TypeError, ValueError):
        return None


def _member_be_ready(member: dict, date_str: str) -> Optional[datetime.datetime]:
    """The kid's real departure anchor for the morning: the earliest
    leave-at (a drive of ours) or be-ready-at (a covered ride) among today's
    events this member is on. Cache-only reads throughout — a wall panel
    polls this. None when the schedule makes no claim, which is most
    Saturdays, and exactly when item times should carry the runway alone."""
    from services import scope, leave_by
    sched = storage.get_cached_schedule() or {}
    members = storage.get_all_members()
    passengers = {p.get('id'): p for p in storage.get_all_passengers()}
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    assist = sched.get('assist_assignments') or {}
    rules = sched.get('matched_rules') or {}
    best = None
    for ev in sched.get('events') or []:
        start_str = str(ev.get('start') or '')
        if start_str[:10] != date_str or ev.get('canceled'):
            continue
        try:
            start = datetime.datetime.fromisoformat(start_str)
            if start.tzinfo is not None:
                start = start.replace(tzinfo=None)
        except ValueError:
            continue
        ev_id = str(ev.get('id') or '')
        subjects = scope.calendar_event_subjects(ev, members, passengers,
                                                 matched_rules=rules)
        if member.get('id') not in subjects:
            continue
        anchor = None
        d_id = assignments.get(ev_id)
        if d_id:
            run = leave_by.for_run(sched, d_id, ev_id, start,
                                   from_home_only=True)
            if run:
                anchor = datetime.datetime.fromisoformat(run['leave_at'])
        elif ev_id in assist:
            ready = leave_by.ready_for_covered(ev, start)
            if ready:
                anchor = datetime.datetime.fromisoformat(ready['ready_at'])
        if anchor and (best is None or anchor < best):
            best = anchor
    return best


def _units(item: dict) -> int:
    """Steps subdivide the fill: five backpack ticks advance the rocket five
    notches. A stepless item is one notch."""
    return len(item.get('steps') or []) or 1


def _units_done(item: dict) -> int:
    if item.get('checked'):
        return _units(item)
    if item.get('steps'):
        return len(item.get('steps_checked') or [])
    return 0


def runways_for(member_id: str, date_str: str,
                now: datetime.datetime = None) -> dict:
    """{'morning': {...}, 'bedtime': {...}} — only kinds with flagged items
    scheduled on this date appear. Each: units done/total, the ordered
    flagged items' ids, next_up, end label, window_active, behind."""
    now = now or datetime.datetime.now()
    member = storage.get_member(member_id) or {}
    items = storage.routines_for_day(member_id, date_str)
    out = {}
    for kind in ('morning', 'bedtime'):
        flagged = [r for r in items if r.get('runway') == kind]
        if not flagged:
            continue
        flagged.sort(key=lambda r: (r.get('time_of_day') is None,
                                    r.get('time_of_day') or '',
                                    r.get('title') or ''))
        total = sum(_units(r) for r in flagged)
        done = sum(_units_done(r) for r in flagged)
        timed = [r for r in flagged if r.get('time_of_day')]
        end_dt = _hhmm_to_dt(date_str, timed[-1]['time_of_day']) if timed else None
        tightened_by = None
        if kind == 'morning':
            br = _member_be_ready(member, date_str)
            if br and (end_dt is None or br < end_dt):
                end_dt, tightened_by = br, 'schedule'
        start_dt = _hhmm_to_dt(date_str, timed[0]['time_of_day']) if timed else None
        complete = done >= total
        next_up = next((r for r in flagged if not r.get('checked')), None)
        # Behind: a timed, unticked item past its own time + grace — and only
        # on the live day. Calm by design; R3's single cue reads this flag.
        behind = False
        if not complete and date_str == now.date().isoformat():
            for r in timed:
                if r.get('checked'):
                    continue
                t = _hhmm_to_dt(date_str, r['time_of_day'])
                if t and now > t + datetime.timedelta(minutes=GRACE_MINS):
                    behind = True
                    break
        window_active = False
        if date_str == now.date().isoformat() and start_dt:
            opens = start_dt - datetime.timedelta(minutes=WINDOW_LEAD_MINS)
            closes = (end_dt or start_dt) + datetime.timedelta(minutes=WINDOW_TAIL_MINS)
            window_active = opens <= now <= closes and not complete
        from services import leave_by
        out[kind] = {
            'kind': kind,
            'item_ids': [r['id'] for r in flagged],
            'units_total': total, 'units_done': done,
            'complete': complete,
            'next_up': ({'id': next_up['id'], 'title': next_up.get('title'),
                         'emoji': next_up.get('emoji'),
                         'image_id': next_up.get('image_id'),
                         'time_of_day': next_up.get('time_of_day')}
                        if next_up else None),
            'end_at': end_dt.isoformat() if end_dt else None,
            'end_label': leave_by.clock(end_dt) if end_dt else None,
            'tightened_by': tightened_by,
            'window_active': window_active,
            'behind': behind,
        }
    return out
