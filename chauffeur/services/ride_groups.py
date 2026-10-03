"""Ride groups -- these occurrences ride together.

Two kids, two events at the same place, a little apart. On paper one driver
can't cover both: there is no time to drive home between them for the second
kid. In life both kids get in the car at the start and one parent does it.
A ride group says exactly that, for exactly these occurrences:

  - one driver for every event in the group (the solver never splits it),
  - never a driver conflict between members,
  - routed as one trip: no drive home in between, no separate pickup.

It is deliberately NOT a rule. A `group` rule matches by keyword/passenger
and reaches every future occurrence; a ride group is a hand decision about
one day, made on the Schedule page by dropping one event onto another (or
from the diagnostics' "Ride together" suggestion).

Rows live in their own table (storage.ride_groups), never the event config,
for the reason optional decisions do: an instance config replaces the series
config wholesale, so a programmatic write there would lose passengers and
attendance settings. Keyed (instance google id, occurrence date, leg) -- the
leg because a split event's dropoff and pickup are separate drives that group
independently. A member whose event moves to another day, is canceled, or
disappears simply stops matching; nothing breaks.
"""
import datetime
import re
import uuid

from services import storage
from services.optional_events import candidate_google_ids

# Kept a month so a past day redrawn on the Schedule page still shows how it
# was driven; the rows are a few bytes each.
KEEP_DAYS = 30

LEGS = ('dropoff', 'pickup')


def leg_of(event_id) -> str:
    s = str(event_id or '')
    for leg in LEGS:
        if s.endswith('_' + leg):
            return leg
    return ''


def _get(ev, key, default=None):
    if isinstance(ev, dict):
        return ev.get(key, default)
    return getattr(ev, key, default)


def occurrence_date(ev) -> str:
    """The date the occurrence is keyed by. A pickup leg starts at its
    parent's END, so a leg reads the parent's own start."""
    src = _get(ev, 'original_start') if leg_of(_get(ev, 'id')) else None
    return str(src or _get(ev, 'start') or '')[:10]


def _ids(ev) -> list:
    """candidate_google_ids, read off the WHOLE event: a leg's own id carries
    a _dropoff/_pickup suffix the stamped parent never had."""
    if isinstance(ev, dict) and leg_of(ev.get('id')):
        ev = dict(ev, id=re.sub(r'_(dropoff|pickup)$', '', str(ev['id'])))
    return candidate_google_ids(ev)


def _row_for(ev, leg, rows):
    ids = _ids(ev)
    for gid in ids:
        for r in rows:
            if r.get('google_id') == gid and (r.get('leg') or '') == leg:
                return r
    return None


def stamp_ride_groups(events) -> None:
    """Refresh-pipeline pass, before unrolling and the attendance split so
    every copy carries the stamp. Prunes rows past KEEP_DAYS."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    storage.prune_ride_groups(cutoff)
    by_date = {}
    for r in storage.get_ride_group_rows():
        by_date.setdefault(r.get('date'), []).append(r)
    if not by_date:
        return
    for e in events:
        rows = by_date.get(occurrence_date(e))
        if not rows:
            continue
        stamp = {}
        for leg in ('',) + LEGS:
            r = _row_for(e, leg, rows)
            if r:
                stamp[leg] = r['group_id']
        if stamp:
            e.ride_groups = stamp


def group_id_of(ev):
    """The ride group this solver event (a whole event or one leg) is in."""
    return (_get(ev, 'ride_groups') or {}).get(leg_of(_get(ev, 'id')))


def pairs(events) -> set:
    """Ordered (id, id) pairs for every two events sharing a ride group on
    the same day -- the shape matcher.get_grouped_event_pairs returns."""
    members = {}
    for e in events:
        gid = group_id_of(e)
        if gid:
            members.setdefault((gid, e.start.date()), []).append(e.id)
    out = set()
    for ids in members.values():
        for a in ids:
            for b in ids:
                if a != b:
                    out.add((a, b))
    return out


def same_group(e1, e2) -> bool:
    g = group_id_of(e1)
    return bool(g) and g == group_id_of(e2)


def group(items) -> str:
    """Put these occurrences in one ride group. `items` is a list of
    (cached event dict, requested event id) -- the requested id carries the
    leg. The LAST item is the drop target: its existing group is kept, and
    any other group a member was already in is merged into it, so dropping
    onto a grouped event joins that group and there is no limit on size.
    Raises ValueError when the occurrences are not on one day."""
    if len(items) < 2:
        raise ValueError("Pick at least two events to group.")
    dates = {occurrence_date(ev) for ev, _ in items}
    if len(dates) != 1 or '' in dates:
        raise ValueError("Only events on the same day can ride together.")
    date = dates.pop()
    rows = storage.get_ride_group_rows(date)
    existing = []
    for ev, req_id in items:
        r = _row_for(ev, leg_of(req_id), rows)
        if r and r['group_id'] not in existing:
            existing.append(r['group_id'])
    target_row = _row_for(items[-1][0], leg_of(items[-1][1]), rows)
    target = (target_row['group_id'] if target_row
              else existing[0] if existing else uuid.uuid4().hex)
    for r in rows:
        if r['group_id'] in existing and r['group_id'] != target:
            storage.set_ride_group_row(r['google_id'], date, r.get('leg') or '', target)
    for ev, req_id in items:
        storage.set_ride_group_row(_ids(ev)[0], date,
                                   leg_of(req_id), target)
    return target


def ungroup(ev, req_id) -> bool:
    """Take one occurrence out of its group. A group left with one member
    is dissolved -- a group of one says nothing."""
    date = occurrence_date(ev)
    leg = leg_of(req_id)
    rows = storage.get_ride_group_rows(date)
    r = _row_for(ev, leg, rows)
    if not r:
        return False
    storage.remove_ride_group_row(r['google_id'], date, r.get('leg') or '')
    rest = [x for x in rows if x['group_id'] == r['group_id'] and x is not r
            and not (x['google_id'] == r['google_id'] and (x.get('leg') or '') == (r.get('leg') or ''))]
    if len(rest) == 1:
        storage.remove_ride_group_row(rest[0]['google_id'], date, rest[0].get('leg') or '')
    return True
