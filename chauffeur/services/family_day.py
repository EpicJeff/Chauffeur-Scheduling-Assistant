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
    # The agenda this card replaced flagged an unsolved ride — red "Needs
    # driver", or amber "Conflict" when every driver is hard-blocked and
    # assigning one is not the fix. The card lost that in the swap, and an
    # unhandled ride drawn in its calendar's own colour reads as handled.
    # Same resolution the calendar's agenda does client-side:
    # `true_unassigned` (the combined endpoints publish it as `unassigned`
    # too), conflict when the event's diagnostics exist and none is a mere
    # 'optimization' reason.
    unassigned = set(sched.get('true_unassigned')
                     or sched.get('unassigned') or [])
    diagnostics = sched.get('diagnostics') or {}

    cal_meta = sched.get('calendar_metadata') or {}
    members = sched.get('members') or _members_fallback()
    # WHO RIDES an event is not only a question of whose calendar it is on.
    # A routing rule binds passengers to events their own calendar never owns
    # (a family calendar's "Practice" that two children attend), and
    # `sched['matched_rules']` is where the solver records which rules matched
    # which event -- the same resolution the calendar's own details dialog and
    # the member-day endpoint use (`main.py:9637-9644`). Resolving by calendar
    # alone is why every tile and every dialog said "No passengers".
    matched = sched.get('matched_rules') or {}

    blocks = []
    all_day = []
    outing_rows = outings.outings_for(target, sched, now)
    inside_an_outing = {eid for o in outing_rows for eid in o['event_ids']}
    for o in outing_rows:
        lines = [_line(events.get(e), members, cal_meta, matched.get(e))
                 for e in o['event_ids']]
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
        # Covered beats unassigned (a ride somebody outside has is handled,
        # whatever the solve said before they took it), and a canceled event
        # needs nobody.
        needs_driver = (not cov and not ev.get('canceled')
                        and ev_id in unassigned)
        conflict = False
        conflict_reason = None
        if needs_driver:
            reasons = [r for r in (diagnostics.get(ev_id) or {}).values() if r]
            conflict = bool(reasons) and all(
                r.get('type') != 'optimization' for r in reasons)
            # When every driver is blocked for the SAME reason — a passenger
            # double-booked at another activity blocks everybody identically
            # — that reason IS the conflict, and "every driver is blocked"
            # is the mechanism, not the explanation. Only a single distinct
            # text is safe to promote; mixed reasons keep the generic line.
            if conflict:
                texts = {r.get('text') for r in reasons if r.get('text')}
                if len(texts) == 1:
                    conflict_reason = texts.pop()
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
            'needs_driver': needs_driver,
            'conflict': conflict,
            'conflict_reason': conflict_reason,
            'color': _event_color(ev, cal_meta),
            'passengers': _passengers_for(ev, members, cal_meta, matched.get(ev_id)),
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
            elif anchor.date() < target == now.date() and now < window_ends:
                # Past midnight before a morning trip: the evening anchor is
                # on a day already behind the one being drawn, but the window
                # is still open — the work joins the part of the day we are
                # in now, same reasoning as caught_up.
                anchor = _bucket_anchor(now)
            if anchor.date() != target:
                continue
            name = _bucket_name(anchor)
            slot = buckets.setdefault(name, {
                'kind': 'prep',
                'key': f"prep:{target.isoformat()}:{name}",
                'bucket': name,
                'start': anchor.isoformat(),
                'end': anchor.isoformat(),
                # When the LAST tile's window shuts — the block's lifetime,
                # as opposed to start/end, which are its POSITION in the
                # day. day_in_focus reads this: packing for tomorrow is
                # still ahead of the household all evening, and treating
                # the 17:00 anchor as the end flipped the day at 17:01 and
                # hid the block during the exact hours it exists for.
                'window_ends': window_ends.isoformat(),
                'tiles': [],
            })
            slot['window_ends'] = max(slot['window_ends'],
                                      window_ends.isoformat())
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

    # The evening block is tomorrow's work, so it belongs at the END of the
    # day rather than wherever 17:00 happens to fall — a 17:00 anchor put it
    # ahead of a 5:15 practice, which reads as "pack before you leave" when
    # the truth is "pack when you get back".
    evening = buckets.get('evening')
    if evening:
        ends = [b.get('end') or b.get('start')
                for b in _raw_blocks(target, sched, now)['blocks']
                if not b.get('canceled')]
        latest = max(ends) if ends else None
        if latest and latest > evening['start']:
            evening['start'] = latest
            evening['end'] = latest

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


def pack_window_opens(start_iso: str) -> Optional[str]:
    """When the outing's own part of the day begins — the moment the card
    starts wearing its own "N to pack" pill. Before that the prep block alone
    talks about packing: prep anchors to the window before departure and the
    list sorts by time, so pill and prep count sat one row apart saying the
    same thing all day."""
    d = outings._parse(start_iso)
    return _bucket_anchor(d).isoformat() if d else None


def pack_status_for(key: str, event_ids, sched: dict,
                    target: datetime.date) -> Optional[dict]:
    """One block's needed/packed, resolved the way /api/packing/day resolves
    it — same outing key, same item keys, claims read off the day the outing
    is on — so the hero and the card cannot disagree about the same bags.
    None when there is nothing to pack (or resolution fails): a surface
    should say nothing rather than "0 of 0"."""
    try:
        from services import prep_kits as _prep
        groups = outings.packing_for({'event_ids': list(event_ids)}, sched,
                                     storage.get_prep_kits(), _prep.passenger_objs())
        claims = {}
        for row in storage.get_packing_claims(target.isoformat()):
            k = (row.get('outing_key'), row.get('item_key'))
            claims[k] = claims.get(k, 0) + 1
        needed = packed = 0
        for g in groups:
            for item in g.get('items') or []:
                n = item.get('needed') or 0
                needed += n
                packed += min(n, claims.get((key, item.get('key')), 0))
        if not needed:
            return None
        return {'needed': needed, 'packed': packed}
    except Exception:
        return None


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
        # A prep block's `end` is its POSITION (the bucket anchor); its
        # `window_ends` is its lifetime. Tonight's packing for tomorrow
        # morning is ahead of the household until the trip leaves, and
        # reading the anchor here flipped the day at 17:01 and hid it.
        end = outings._parse(b.get('window_ends') or b.get('end'))
        if end and end > now:
            return today
    return today + datetime.timedelta(days=1)


def _line(ev, members: list = None, cal_meta: dict = None,
          rules: list = None) -> dict:
    """The compact inner line an outing container shows: title, time, and the
    people it is for — driver and car live on the container, because those are
    facts about the trip rather than about the event."""
    ev = ev or {}
    return {'id': ev.get('id'), 'title': ev.get('title') or 'Event',
            'start': ev.get('start'),
            'color': _event_color(ev, cal_meta or {}),
            'passengers': _passengers_for(ev, members or [], cal_meta or {}, rules)}


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


def _passengers_for(ev: dict, members: list, cal_meta: dict,
                    rules: list = None) -> List[dict]:
    """The people an event is for — nobody invented.

    Two ways somebody is on an event, and the app has always needed both:

    * **Their calendar owns it.** The event names their member id or one of
      their calendar ids — the rule the kit resolver uses
      (`outings._people_on`).
    * **A rule binds them to it.** A routing rule matched the event and names
      them, which is how a family calendar's "Practice" carries two children
      who have no calendar of their own. `sched['matched_rules']` is the
      solver's record of which rules matched what, and it is the same source
      the calendar's details dialog and the member-day endpoint read.

    Resolving by calendar alone found nobody on this household's real data,
    and every tile and dialog said "No passengers" while the kits underneath
    them were matching those same people perfectly well.

    Either way, the id being compared is a PASSENGER id: rules name
    passengers, and the solver rewrites a matched event's `calendar_ids`
    into resolved passenger ids. A real member record keeps that id in
    `passenger_id`, one field over from its own `id` — so both fields have
    to be tried, or a household whose member ids differ from their passenger
    ids (every real one) finds nobody.
    """
    cal_ids = {str(c) for c in ((ev or {}).get('calendar_ids') or [])}
    named = set()
    for r in rules or []:
        for pid in ((r.get('passenger_ids') if isinstance(r, dict) else None) or []):
            named.add(str(pid))
    if not cal_ids and not named:
        return []
    out = []
    for m in members or []:
        mid = str(m.get('id') or '')
        pax_id = str(m.get('passenger_id') or '')
        my_ids = {i for i in (mid, pax_id) if i}
        m_cals = {str(c) for c in (m.get('calendar_ids') or [])}
        on_calendar = bool(my_ids & cal_ids) or bool(m_cals & cal_ids)
        by_rule = bool(my_ids & named)
        if not on_calendar and not by_rule:
            continue
        color = None
        for cid in m_cals:
            meta = cal_meta.get(cid) or {}
            if meta.get('backgroundColor'):
                color = meta['backgroundColor']
                break
        if not color:
            meta = cal_meta.get(mid) or {}
            color = meta.get('backgroundColor')
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
    """Everybody an event could name, with a colour each.

    PASSENGERS first, because that is the app's own notion of who rides:
    prep kits resolve their people through `passenger_objs()`, and a tile
    that resolved people any other way named nobody at all on a household
    whose riders are passenger records rather than members. Members are
    merged in behind them so a member-only person is still found, and so a
    passenger who is also a member inherits that member's chosen colour.
    """
    out, seen = [], set()
    members = []
    try:
        members = storage.get_all_members()
    except Exception:
        members = []
    color_by_name = {}
    for m in members:
        name = str(m.get('name') or '').lower()
        if name and m.get('color_code'):
            color_by_name[name] = m['color_code']
    try:
        for p in storage.get_all_passengers():
            pid = str(p.get('id') or '')
            if not pid or pid in seen:
                continue
            seen.add(pid)
            out.append({'id': pid, 'name': p.get('name') or 'Somebody',
                        'calendar_ids': p.get('calendar_ids') or [],
                        'color_code': (p.get('color_code')
                                       or color_by_name.get(str(p.get('name') or '').lower()))})
    except Exception:
        pass
    for m in members:
        mid = str(m.get('id') or '')
        # A member whose passenger is already on the list IS that passenger —
        # two entries would draw the same person twice now that
        # `_passengers_for` matches through `passenger_id` as well.
        if str(m.get('passenger_id') or '') in seen:
            continue
        if mid and mid not in seen:
            seen.add(mid)
            out.append(m)
    return out


def _assist_contacts_fallback() -> list:
    try:
        return storage.get_assist_contacts(include_inactive=True)
    except Exception:
        return []
