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
               now: datetime.datetime = None,
               items_by_key: dict = None) -> dict:
    """Every block of one day, time-ordered, plus the all-day banner.

    `items_by_key` maps a block key to how many things it needs packed. It is
    how the caller (the endpoint, which owns kits and claims) tells this
    module which blocks deserve a prep block — this module never touches kits
    or claims itself. Passing `None` means "work it out from the kits", which
    is what a caller without the counts already to hand gets.
    """
    now = now or datetime.datetime.now()
    target = outings._as_date(target_date) or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    day = _raw_blocks(target, sched, now)
    day['blocks'].extend(_prep_blocks(target, sched, now, items_by_key))
    day['blocks'].sort(key=lambda b: (b['start'], b['key']))
    return day


def _raw_blocks(target, sched: dict, now: datetime.datetime) -> dict:
    """One day's happenings, before prep is placed among them."""
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    assist = sched.get('assist_assignments') or {}
    contacts = {str(c.get('id')): c
                for c in (sched.get('assist_contacts')
                          or _assist_contacts_fallback())}

    cal_meta = sched.get('calendar_metadata') or {}
    members = sched.get('members') or _members_fallback()

    blocks = []
    all_day = []
    outing_rows = outings.outings_for(target, sched, now)
    inside_an_outing = {eid for o in outing_rows for eid in o['event_ids']}
    for o in outing_rows:
        lines = [_line(events.get(e), members, cal_meta) for e in o['event_ids']]
        blocks.append({'kind': 'outing', **o, 'events': lines,
                       'passengers': _union_people(lines)})

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
            'color': _event_color(ev, cal_meta),
            'passengers': _passengers_for(ev, members, cal_meta),
        })

    blocks.sort(key=lambda b: (b['start'], b['key']))
    all_day.sort()
    return {'blocks': blocks, 'all_day': all_day}


# ── Prep is work, and work has a place in the day ────────────────────────
#
# F1 drew a trip's items on the trip, so the list for a 4:00 PM departure
# appeared at 4:00 PM — a report, not help. A prep block is NOT an
# appointment: no duration, no owner, never seen by the solver. It is a
# POSITION in the list, at the start of the last part of the day that ends
# before the outing leaves:
#
#   leaves before 12:00  ->  the PREVIOUS day's evening (17:00)
#   leaves 12:00-17:00   ->  that day's morning        (00:00)
#   leaves after 17:00   ->  that day's afternoon      (12:00)
#
# This is the rule the packing design already wrote for a child's own day
# ("the last bucket before its outing leaves, and never after it"), which the
# family tile never inherited. Derived on read, like everything else here.

_MORNING_ENDS = 12
_AFTERNOON_ENDS = 17


def _prep_window(depart: datetime.datetime):
    """Where the prep sits, and when that window shuts.

    The window's END is what decides whether prep is late — being at 6am
    inside a morning window is not "passed", it is early, which is the whole
    point of putting the work there.
    """
    day = depart.date()
    if depart.hour < _MORNING_ENDS:
        anchor = datetime.datetime.combine(
            day - datetime.timedelta(days=1),
            datetime.time(_AFTERNOON_ENDS, 0))
        return anchor, depart          # the whole evening and night to do it
    if depart.hour < _AFTERNOON_ENDS:
        return (datetime.datetime.combine(day, datetime.time(0, 0)),
                datetime.datetime.combine(day, datetime.time(_MORNING_ENDS, 0)))
    return (datetime.datetime.combine(day, datetime.time(_MORNING_ENDS, 0)),
            datetime.datetime.combine(day, datetime.time(_AFTERNOON_ENDS, 0)))


def _prep_blocks(target, sched: dict, now: datetime.datetime,
                 items_by_key: dict = None) -> List[dict]:
    """The prep blocks that belong to `target` — at most one per part of the
    day, each holding a tile per event.

    F3 drew one block per outing, and a Friday evening carrying four
    Saturday-morning trips became four blocks stacked at one anchor, sorted
    (because they shared a timestamp) by their internal keys — alphabetical
    by event id, which to a household is no order at all. One block per
    bucket, tiles inside it ordered by the departure they serve.

    A morning outing's prep belongs to the evening BEFORE it, so this looks at
    tomorrow's happenings as well as today's — and a tile whose window has
    already gone moves into the block for the part of the day we are in now,
    because a list you can act on beats a list that is filed correctly and
    invisible.
    """
    buckets = {}
    for offset in (0, 1):
        day = target + datetime.timedelta(days=offset)
        for b in _raw_blocks(day, sched, now)['blocks']:
            if b.get('canceled') or b['kind'] == 'prep':
                continue
            if not _has_items(b, sched, items_by_key):
                continue
            depart = outings._parse(b.get('start'))
            if not depart:
                continue
            anchor, window_ends = _prep_window(depart)
            caught_up = window_ends < now < depart
            if caught_up:
                anchor = _bucket_anchor(now)   # it joins the block for NOW
            if anchor.date() != target:
                continue
            name = _bucket_name(anchor)
            slot = buckets.setdefault(name, {
                'kind': 'prep',
                'key': f"prep:{target.isoformat()}:{name}",
                'bucket': name,
                'start': anchor.isoformat(),
                'end': anchor.isoformat(),
                'tiles': [],
            })
            if caught_up:
                # A block holding work that is already late sits at the FRONT
                # of what is left, not back at the start of a bucket most of
                # which has gone. A list you can act on beats a list that is
                # filed correctly and invisible.
                slot['start'] = max(slot['start'], now.isoformat())
                slot['end'] = slot['start']
            for ev in _tile_events(b):
                slot['tiles'].append({
                    'key': f"{slot['key']}:{ev['id']}",
                    'for_key': b['key'],
                    'event_id': ev['id'],
                    'title': ev.get('title') or 'Event',
                    'start': ev.get('start') or b.get('start'),
                    'depart': b.get('start'),
                    'passengers': ev.get('passengers') or b.get('passengers') or [],
                })

    out = []
    for slot in buckets.values():
        # The order the day will actually happen in — the whole point.
        slot['tiles'].sort(key=lambda t: (str(t.get('depart') or ''),
                                          str(t.get('start') or ''),
                                          t['title'].lower()))
        out.append(slot)
    return out


def _tile_events(b: dict) -> List[dict]:
    """One tile per EVENT: you work one event's list at a time, even when one
    trip covers two."""
    if b['kind'] == 'outing':
        return [dict(e) for e in (b.get('events') or [])]
    return [{'id': b.get('event_id'), 'title': b.get('title'),
             'start': b.get('start'), 'passengers': b.get('passengers') or []}]


def _bucket_name(anchor: datetime.datetime) -> str:
    if anchor.hour < _MORNING_ENDS:
        return 'morning'
    if anchor.hour < _AFTERNOON_ENDS:
        return 'afternoon'
    return 'evening'


def _bucket_anchor(when: datetime.datetime) -> datetime.datetime:
    """The start of the part of the day `when` falls in — a caught-up tile
    joins the block for now, it does not invent an anchor of its own."""
    day = when.date()
    if when.hour < _MORNING_ENDS:
        return datetime.datetime.combine(day, datetime.time(0, 0))
    if when.hour < _AFTERNOON_ENDS:
        return datetime.datetime.combine(day, datetime.time(_MORNING_ENDS, 0))
    return datetime.datetime.combine(day, datetime.time(_AFTERNOON_ENDS, 0))


def _has_items(b: dict, sched: dict, items_by_key: dict = None) -> bool:
    if items_by_key is not None:
        return bool(items_by_key.get(b['key']))
    try:
        groups = outings.packing_for(
            {'event_ids': (b['event_ids'] if b['kind'] == 'outing'
                           else [b['event_id']])}, sched)
        return any(g.get('items') for g in groups)
    except Exception:
        return False


def _block_title(b: dict) -> str:
    if b['kind'] == 'outing':
        return ' + '.join(e.get('title') or 'Event' for e in b.get('events') or [])
    return b.get('title') or 'Event'


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


def _line(ev, members: list = None, cal_meta: dict = None) -> dict:
    """The compact inner line an outing container shows: title, time, and the
    people it is for — driver and car live on the container, because those are
    facts about the trip rather than about the event."""
    ev = ev or {}
    return {'id': ev.get('id'), 'title': ev.get('title') or 'Event',
            'start': ev.get('start'),
            'color': _event_color(ev, cal_meta or {}),
            'passengers': _passengers_for(ev, members or [], cal_meta or {})}


# ── Whose event is this? ─────────────────────────────────────────────────
#
# Everywhere else in this app an event's colour is the colour of the calendar
# it lives on (`family_calendar.html:1468-1470`), and in this household a
# calendar belongs to a person. The Family Day card once overrode that with
# the driver's colour and the family could not read it. So: passenger colour
# belongs to the event, driver colour to the trip.
#
# `calendar_metadata` on the schedule cache already has each member's chosen
# identity colour overlaid onto their calendar ids (`main.py:16097`), so the
# colour here is the same one every other surface draws.

def _event_color(ev: dict, cal_meta: dict) -> Optional[str]:
    for cid in (ev or {}).get('calendar_ids') or []:
        meta = cal_meta.get(str(cid)) or {}
        if meta.get('backgroundColor'):
            return meta['backgroundColor']
    return None


def _passengers_for(ev: dict, members: list, cal_meta: dict) -> List[dict]:
    """The people an event is for — nobody invented.

    Matching mirrors the rule the kit resolver already uses
    (`outings._people_on`): a member is on an event when the event names their
    member id or any of their calendar ids.
    """
    cal_ids = {str(c) for c in ((ev or {}).get('calendar_ids') or [])}
    if not cal_ids:
        return []
    out = []
    for m in members or []:
        mid = str(m.get('id') or '')
        m_cals = {str(c) for c in (m.get('calendar_ids') or [])}
        if mid not in cal_ids and not (m_cals & cal_ids):
            continue
        color = None
        for cid in m_cals:
            meta = cal_meta.get(cid) or {}
            if meta.get('backgroundColor'):
                color = meta['backgroundColor']
                break
        out.append({'id': mid, 'name': m.get('name') or 'Somebody',
                    'color': color or m.get('color_code') or None})
    out.sort(key=lambda p: p['name'].lower())
    return out


def _union_people(lines: list) -> List[dict]:
    """An outing is for everyone its events are for, each named once."""
    seen, out = set(), []
    for line in lines or []:
        for p in line.get('passengers') or []:
            if p['id'] in seen:
                continue
            seen.add(p['id'])
            out.append(p)
    out.sort(key=lambda p: p['name'].lower())
    return out


def _members_fallback() -> list:
    try:
        return storage.get_all_members()
    except Exception:
        return []


def _assist_contacts_fallback() -> list:
    try:
        return storage.get_assist_contacts(include_inactive=True)
    except Exception:
        return []
