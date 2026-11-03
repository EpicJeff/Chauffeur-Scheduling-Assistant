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
    for e in events:
        rows = by_date.get(occurrence_date(e), [])
        stamp = {}
        for leg in ('',) + LEGS:
            r = _row_for(e, leg, rows)
            if r:
                stamp[leg] = r['group_id']
        e.ride_groups = stamp
        whole_row = _row_for(e, '', rows)
        e.ride_group_mode = 'one' if whole_row and whole_row.get('mode') == 'one' else None


def group_id_of(ev):
    """The ride group this solver event (a whole event or one leg) is in."""
    return (_get(ev, 'ride_groups') or {}).get(leg_of(_get(ev, 'id')))


def group_mode_of(ev) -> str:
    return 'one' if _get(ev, 'ride_group_mode') == 'one' else 'ride'


def _same_place(events) -> bool:
    places = {' '.join(str(_get(e, 'location') or '').casefold().split()) for e in events}
    return len(places) == 1 and '' not in places


def _known_members(events, rows):
    """Include existing partners still present in the cached occurrence day."""
    members = list(events)
    cached = (storage.get_cached_schedule() or {}).get('events', [])
    whole = [ev for ev in members + cached if not leg_of(_get(ev, 'id'))]
    for row in rows:
        partner = next((ev for ev in whole if occurrence_date(ev) == row['date']
                        and row['google_id'] in _ids(ev)), None)
        if partner is not None and partner not in members:
            members.append(partner)
    return members


def merge_as_one(events, attendance_overrides) -> dict:
    """Plan the attendance split once for each whole-event block on a day."""
    buckets = {}
    for e in events:
        if e.event_type == 'background_trip' or leg_of(e.id) or group_mode_of(e) != 'one':
            continue
        gid = group_id_of(e)
        if gid:
            buckets.setdefault((gid, occurrence_date(e)), []).append(e)
    plan = {'legs': {}, 'skip': set()}
    for members in buckets.values():
        if len(members) < 2 or not _same_place(members):
            continue
        if any((attendance_overrides.get(str(e.id)) or {}).get('action') == 'stay'
               for e in members):
            continue
        members = sorted(members, key=lambda e: e.start)
        first = members[0]
        last = max(members, key=lambda e: e.end)
        title = ' + '.join(dict.fromkeys(e.title for e in members))
        unions = {key: list(dict.fromkeys(value for e in members
                                        for value in (getattr(e, key, None) or [])))
                  for key in ('calendar_ids', 'original_calendar_ids', 'source_event_ids')}
        legs = []
        for kind, prefix, at in (('dropoff', 'Dropoff', first.start),
                                 ('pickup', 'Pickup', last.end)):
            leg = first.model_copy() if hasattr(first, 'model_copy') else first.copy()
            leg.id = f'{first.id}_{kind}'
            leg.event_type = kind
            leg.title = f'{prefix}: {title}'
            leg.start = leg.end = at
            leg.original_start = first.start
            leg.original_end = last.end
            leg.original_event_id = first.id
            leg.needs_triage = False
            for key, values in unions.items():
                setattr(leg, key, list(values))
            legs.append(leg)
        plan['legs'][first.id] = legs
        plan['skip'].update(e.id for e in members)
    return plan


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


def group(items, mode=None) -> str:
    """Put these occurrences in one ride group. `items` is a list of
    (cached event dict, requested event id) -- the requested id carries the
    leg. The LAST item is the drop target: its existing group is kept, and
    any other group a member was already in is merged into it, so dropping
    onto a grouped event joins that group and there is no limit on size.
    Mode one promotes legs to their parents and needs one nonempty place.
    An omitted mode keeps the target group's mode; a new group rides together.
    Raises ValueError when the occurrences are not on one day."""
    if len(items) < 2:
        raise ValueError("Pick at least two events to group.")
    if mode not in (None, 'ride', 'one'):
        raise ValueError("Ride group mode must be ride or one.")
    dates = {occurrence_date(ev) for ev, _ in items}
    if len(dates) != 1 or '' in dates:
        raise ValueError("Only events on the same day can ride together.")
    date = dates.pop()
    rows = storage.get_ride_group_rows(date)
    existing = []
    for ev, req_id in items:
        r = _row_for(ev, leg_of(req_id), rows)
        whole_row = _row_for(ev, '', rows)
        if whole_row and (mode == 'one' or whole_row.get('mode') == 'one'):
            r = whole_row
        if r and r['group_id'] not in existing:
            existing.append(r['group_id'])
    target_row = _row_for(items[-1][0], leg_of(items[-1][1]), rows)
    whole_row = _row_for(items[-1][0], '', rows)
    if whole_row and (mode == 'one' or whole_row.get('mode') == 'one'):
        target_row = whole_row
    target = (target_row['group_id'] if target_row
              else existing[0] if existing else uuid.uuid4().hex)
    target_rows = [r for r in rows if r['group_id'] == target]
    mode = mode or (target_rows[0].get('mode') if target_rows else None) or 'ride'
    if mode == 'one':
        # Existing partners come along when groups join. Check those still in
        # the cached day too; drift after a write is checked again by the plan.
        members = _known_members([ev for ev, _ in items],
                                 [r for r in rows if r['group_id'] in existing])
        if not _same_place(members):
            raise ValueError("One drop-off and pick-up needs every event at the same place.")
    stored_mode = 'one' if mode == 'one' else None
    for r in rows:
        if r['group_id'] in existing:
            old_leg = r.get('leg') or ''
            if mode == 'one' and old_leg:
                storage.remove_ride_group_row(r['google_id'], date, old_leg)
            storage.set_ride_group_row(r['google_id'], date,
                                       '' if mode == 'one' else old_leg, target, stored_mode)
    for ev, req_id in items:
        storage.set_ride_group_row(_ids(ev)[0], date,
                                   '' if mode == 'one' else leg_of(req_id), target, stored_mode)
    return target


def ungroup(ev, req_id) -> bool:
    """Take one occurrence out of its group. A group left with one member
    is dissolved -- a group of one says nothing."""
    date = occurrence_date(ev)
    leg = leg_of(req_id)
    rows = storage.get_ride_group_rows(date)
    r = _row_for(ev, leg, rows)
    whole_row = _row_for(ev, '', rows)
    if whole_row and whole_row.get('mode') == 'one':
        r = whole_row
    if not r:
        return False
    storage.remove_ride_group_row(r['google_id'], date, r.get('leg') or '')
    rest = [x for x in rows if x['group_id'] == r['group_id'] and x is not r
            and not (x['google_id'] == r['google_id'] and (x.get('leg') or '') == (r.get('leg') or ''))]
    if len(rest) == 1:
        storage.remove_ride_group_row(rest[0]['google_id'], date, rest[0].get('leg') or '')
    return True


# --- Agent path (both stacks) ---

def _refused(acting_member) -> dict:
    """Regrouping the family's drives is a parent/adult act, same gate as
    cancellations (and the endpoints' _cancel_actor_refused)."""
    if (acting_member or {}).get('role') in ('child', 'helper', 'guest'):
        return {'status': 'error',
                'message': "Only a parent or adult can group or ungroup "
                           "events -- ask one of them."}
    return None


def _refresh():
    try:
        import main as _m
        _m.trigger_background_refresh()
    except Exception:
        pass


def group_by_titles(event_names, target_date: str = 'today',
                    acting_member: dict = None, mode=None) -> dict:
    """Resolve each name on the date (fuzzy, over the cached schedule) and
    group them to ride together. The LAST name is the one the others join,
    as with a drop."""
    refused = _refused(acting_member)
    if refused:
        return refused
    from services.agent_tools_v2 import _find_event_fuzzy
    if isinstance(event_names, str):
        event_names = re.split(r',|\band\b', event_names)
    names = [str(n).strip() for n in (event_names or []) if str(n or '').strip()]
    if len(names) < 2:
        return {'status': 'error',
                'message': "Name at least two events to ride together."}
    items, seen = [], {}
    for name in names:
        ev, err = _find_event_fuzzy(name, target_date or 'today')
        if err:
            return {'status': 'error', 'message': err}
        if ev['id'] in seen:
            return {'status': 'error',
                    'message': f"'{name}' and '{seen[ev['id']]}' both matched "
                               f"'{ev.get('title')}' -- name them more exactly."}
        seen[ev['id']] = name
        items.append((ev, ev['id']))
    try:
        gid = group(items, mode=mode)
    except ValueError as err:
        return {'status': 'error', 'message': str(err)}
    _refresh()
    titles = [ev.get('title') for ev, _ in items]
    rows = [r for r in storage.get_ride_group_rows() if r['group_id'] == gid]
    if any(r.get('mode') == 'one' for r in rows):
        members = _known_members([ev for ev, _ in items], rows)
        drop = min(str(ev.get('original_start') or ev['start']) for ev in members)[11:16]
        pick = max(str(ev.get('original_end') or ev['end']) for ev in members)[11:16]
        return {'status': 'success',
                'message': f"Grouped {', '.join(titles)} as one event: one drop-off at {drop} "
                           f"and one pick-up at {pick}, for that day only."}
    return {'status': 'success',
            'message': f"Grouped {', '.join(titles[:-1])} with {titles[-1]}: "
                       f"they ride together with one driver, for that day only."}


def ungroup_by_title(event_name: str, target_date: str = 'today',
                     acting_member: dict = None) -> dict:
    refused = _refused(acting_member)
    if refused:
        return refused
    from services.agent_tools_v2 import _find_event_fuzzy
    ev, err = _find_event_fuzzy(event_name or '', target_date or 'today')
    if err:
        return {'status': 'error', 'message': err}
    if not ungroup(ev, ev['id']):
        return {'status': 'success',
                'message': f"'{ev.get('title')}' wasn't riding with anything."}
    _refresh()
    return {'status': 'success',
            'message': f"'{ev.get('title')}' no longer rides with the others; "
                       f"the solver plans it on its own again."}
