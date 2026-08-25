"""The day as BLOCKS — the one spine the wall's Family Day card draws.

The event block is the atom. The outing (services/outings.py) is a container
over driven events; at-home and covered events are bare blocks from the same
feed the calendar card reads (`sched['events']` carries everything — driven,
undriven, canceled-and-stamped, skip-decided — see main.py's solve cache
assembly). All-day events become a banner: they have no time to anchor a
block to, and they must never reach the solver.

Pure computation over the schedule cache: nothing stored, nothing written,
safe on every poll. The solver sees nothing new through this module.
"""
import datetime
from typing import List, Optional

from services import outings, storage


def blocks_for(target_date=None, sched: dict = None,
               now: datetime.datetime = None) -> dict:
    """Every block of one day, time-ordered, plus the all-day banner."""
    now = now or datetime.datetime.now()
    target = outings._as_date(target_date) or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    assist = sched.get('assist_assignments') or {}
    contacts = {str(c.get('id')): c
                for c in (sched.get('assist_contacts')
                          or _assist_contacts_fallback())}

    blocks = []
    all_day = []
    outing_rows = outings.outings_for(target, sched, now)
    inside_an_outing = {eid for o in outing_rows for eid in o['event_ids']}
    for o in outing_rows:
        blocks.append({'kind': 'outing', **o,
                       'events': [_line(events.get(e)) for e in o['event_ids']]})

    for ev_id, ev in events.items():
        start = outings._parse((ev or {}).get('start'))
        if not ev or not start or start.date() != target:
            continue
        if ev.get('all_day'):
            all_day.append(ev.get('title') or 'All day')
            continue
        if ev.get('event_type') == 'background_trip':
            continue
        if ev_id in inside_an_outing:
            continue
        if ev.get('optional_decision') == 'skip':
            # The family decided not to go; drawing it anyway nags a decision
            # already made (the optional-events arc's own no-daily-ping rule).
            continue
        cov = assist.get(ev_id)
        c = contacts.get(str(cov)) or {}
        end = outings._parse(ev.get('end')) or start
        blocks.append({
            'kind': 'event',
            'key': f"home:{ev_id}",
            'event_id': ev_id,
            'title': ev.get('title') or 'Event',
            'start': start.isoformat(),
            'end': end.isoformat(),
            'canceled': bool(ev.get('canceled')),
            'covered_by': ((c.get('relation_label') or c.get('name')
                            or 'Outside help') if cov else None),
        })

    blocks.sort(key=lambda b: (b['start'], b['key']))
    all_day.sort()
    return {'blocks': blocks, 'all_day': all_day}


def day_in_focus(now: datetime.datetime = None, sched: dict = None) -> datetime.date:
    """The day the household is actually thinking about.

    Today while any block is still ahead; tomorrow once the last one is done.
    This is the packing arc's day-follows-the-day rule with wider input: a day
    ending with an at-home party must not flip to tomorrow mid-party. Canceled
    blocks never hold the day — a thing that is not happening cannot be ahead.
    """
    now = now or datetime.datetime.now()
    today = now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    for b in blocks_for(today, sched, now)['blocks']:
        if b.get('canceled'):
            continue
        end = outings._parse(b.get('end'))
        if end and end > now:
            return today
    return today + datetime.timedelta(days=1)


def _line(ev) -> dict:
    """The compact inner line an outing container shows: title and time only —
    driver and car live on the container."""
    ev = ev or {}
    return {'id': ev.get('id'), 'title': ev.get('title') or 'Event',
            'start': ev.get('start')}


def _assist_contacts_fallback() -> list:
    try:
        return storage.get_assist_contacts(include_inactive=True)
    except Exception:
        return []
