"""The day's eating plan (meals & provisioning arc M2).

Eating is PER-PERSON and ALL-DAY, not a household cook window at 6pm: meals
get prepped in pieces across the day and eaten in the car between activities.
The everyone-is-home-at-dinner case is the degenerate one.

This is squarely solver ground — eating competes for the same two resources
the solver already allocates, gaps in the day and seats in cars — so this
module DERIVES, read-only, from the cached schedule and never writes any
schedule state (design principle 8).

Two facts do most of the work:

1. **A passenger can eat during a leg; the driver cannot.** The manifest gives
   this away for free, and it is the structural reason the driving parent is
   the one who does not eat: their slots are only the gaps BETWEEN legs, while
   everyone they are driving has the whole ride.
2. **What counts as edible where is family policy, not physics.** This family
   eats full meals with utensils in the car; others will not eat in the car at
   all. Hence `car_dining` / `venue_dining` settings with a permissive default
   — a wrong permission is a visible suggestion someone corrects in seconds, a
   wrong restriction hides slots invisibly (design principle 5).

Slots are emitted as SPANS, never timestamps: "between drop-off and about
5:30" is honest, "eats at 5:10" claims precision the schedule does not have.

See docs/meal_design.md §M2.
"""
import datetime

from services import storage

# Daily-life meal windows. Deliberately module constants for v1 — see the
# open question in docs/meal_design.md about whether a family needs to move
# them. (trip_scheduler has its own MEAL_ANCHOR for trips; these are separate
# because a vacation dinner at 8:30pm is not a Tuesday.)
MEAL_WINDOWS = {
    'breakfast': (datetime.time(6, 0), datetime.time(9, 30)),
    'lunch': (datetime.time(11, 0), datetime.time(14, 0)),
    'dinner': (datetime.time(16, 30), datetime.time(20, 30)),
}

# Below this a "slot" is not a meal, it is a scramble.
MIN_SLOT_MINS = 10

# How much longer than the drive itself a gap can run and still be genuinely
# "in the car" (parking, loading, the walk out). Beyond this the gap is time
# spent somewhere, not time spent driving.
IN_CAR_SLACK_MINS = 25

# Slack required on top of the round trip before we believe someone went home
# between two commitments. Being wrong here means telling a family to pack
# food they could have cooked, so it is deliberately conservative.
HOME_DETOUR_MINS = 30

# Nobody starts dinner at 6am. The cook window is measured from at most this
# far before food is needed, so a free afternoon reports "plenty of time"
# rather than a meaningless eleven hours.
PREP_HORIZON_MINS = 180

# At or above this the window is not the story — the split or the packing is.
COMFORTABLE_COOK_MINS = 90

# Dining permissiveness, ordered. A meal needs the modality's level to be at
# least as permissive as what the meal requires (M3 supplies `portability`).
DINING_LEVELS = ('none', 'snack', 'handheld', 'full')

_COOKING_ROLES = ('parent', 'adult')


def dining_setting(kind: str, settings: dict = None) -> str:
    """`car_dining` / `venue_dining`. Default 'full' — permissive, so a family
    that DOES eat in the car is never silently denied slots it wanted."""
    settings = settings if settings is not None else (storage.get_settings() or {})
    val = str(settings.get(f'{kind}_dining') or '').strip().lower()
    return val if val in DINING_LEVELS else 'full'


def _parse_iso(val):
    try:
        dt = datetime.datetime.fromisoformat(str(val))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def _norm_loc(loc) -> str:
    return (str(loc or '')).strip().lower()


def _is_home(loc, home) -> bool:
    n = _norm_loc(loc)
    return bool(n) and bool(home) and n == _norm_loc(home)


def _base_event_id(ev_id: str) -> str:
    s = str(ev_id)
    for suffix in ('_dropoff', '_pickup'):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    return s.split('_slice_')[0]


def _driver_member_ids(sched: dict) -> dict:
    """event_id -> the MEMBER id driving it (not the driver-profile id)."""
    assignments = dict(sched.get('assignments', {}) or {})
    assignments.update(sched.get('ghost_assignments', {}) or {})
    out = {}
    for ev_id, d_id in assignments.items():
        if not d_id or str(d_id).startswith('ghost_'):
            continue
        m = storage.get_member_by_driver_id(d_id)
        if m and not m.get('system'):
            out[str(ev_id)] = m['id']
    return out


def member_commitments(member_id: str, date_str: str, sched: dict,
                       drivers_by_event: dict = None) -> list:
    """Everywhere the schedule puts this member on this day, time-ordered.

    Each entry: {start, end, location, title, is_driving}. Split legs collapse
    into their parent event so a drop-off/pickup pair reads as one block of
    'that kid is at practice' rather than two.
    """
    from services import presence
    drivers_by_event = drivers_by_event if drivers_by_event is not None \
        else _driver_member_ids(sched)

    blocks = {}
    for ev in sched.get('events', []) or []:
        if not str(ev.get('start', '')).startswith(date_str):
            continue
        if ev.get('trip_suppressed'):
            continue
        ev_id = str(ev.get('id', ''))
        present = presence.members_at_event(ev, ev_id, sched)
        if not any(m['id'] == member_id for m in present):
            continue
        start, end = _parse_iso(ev.get('start')), _parse_iso(ev.get('end'))
        if not start or not end or end <= start:
            continue
        base = _base_event_id(ev_id)
        driving = drivers_by_event.get(ev_id) == member_id
        prev = blocks.get(base)
        if prev:
            prev['start'] = min(prev['start'], start)
            prev['end'] = max(prev['end'], end)
            prev['is_driving'] = prev['is_driving'] or driving
        else:
            blocks[base] = {'start': start, 'end': end,
                            'location': ev.get('location') or '',
                            'title': ev.get('title') or '',
                            'is_driving': driving}
    out = sorted(blocks.values(), key=lambda b: b['start'])
    return out


def _travel_mins(a, b) -> int:
    if not a or not b or _norm_loc(a) == _norm_loc(b):
        return 0
    try:
        from services import maps
        return int(maps.get_travel_time_minutes(a, b) or 0)
    except Exception:
        return 0


def _meal_intersections(start: datetime.datetime, end: datetime.datetime):
    """Every meal window this span can serve, CLIPPED to that window.

    One span can serve several meals — a wide-open evening is a dinner slot
    bounded by the dinner window, not a fifteen-hour blob — so this yields one
    (meal, start, end) per window rather than picking the first match.
    """
    out = []
    for meal, (w_start, w_end) in MEAL_WINDOWS.items():
        ws = datetime.datetime.combine(start.date(), w_start)
        we = datetime.datetime.combine(start.date(), w_end)
        lo, hi = max(start, ws), min(end, we)
        if (hi - lo).total_seconds() / 60.0 >= MIN_SLOT_MINS:
            out.append((meal, lo, hi))
    return out


def member_spans(member: dict, date_str: str, sched: dict, settings: dict = None,
                 drivers_by_event: dict = None) -> list:
    """Raw free spans for a member — UNCLIPPED by meal windows.

    Cooking is the reason this is separate from `eating_slots`: prep happens
    *before* people eat (you cook at 4:00 for a 4:30 departure), so clipping
    the cook window to the dinner window would erase exactly the time that
    matters.

    Modality:
      at_home  — before the first commitment / after the last / a gap at home
      in_car   — the gap is barely longer than the drive between two places
      at_venue — parked somewhere that isn't home (bleachers)
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    home = settings.get('home_location') or ''
    car_level = dining_setting('car', settings)
    venue_level = dining_setting('venue', settings)

    try:
        day = datetime.date.fromisoformat(date_str)
    except ValueError:
        return []
    blocks = member_commitments(member['id'], date_str, sched, drivers_by_event)

    day_start = datetime.datetime.combine(day, datetime.time(6, 0))
    day_end = datetime.datetime.combine(day, datetime.time(21, 0))

    spans = []
    if not blocks:
        spans.append({'start': day_start, 'end': day_end, 'modality': 'at_home',
                      'where': 'home', 'after': None, 'before': None,
                      'driving_next': False, 'travel_mins': 0})
    else:
        # before the first commitment
        first = blocks[0]
        if first['start'] > day_start:
            spans.append({'start': day_start, 'end': first['start'],
                          'modality': 'at_home', 'where': 'home',
                          'after': None, 'before': first['title'],
                          'driving_next': first['is_driving'],
                          'travel_mins': _travel_mins(home, first['location'])})
        # gaps between commitments
        for prev, nxt in zip(blocks, blocks[1:]):
            if nxt['start'] <= prev['end']:
                continue
            gap_mins = (nxt['start'] - prev['end']).total_seconds() / 60.0
            moved = _norm_loc(prev['location']) != _norm_loc(nxt['location'])
            leg = _travel_mins(prev['location'], nxt['location'])
            if not moved:
                # Stayed put: home is home, anywhere else is bleachers.
                modality = 'at_home' if _is_home(prev['location'], home) else 'at_venue'
                where = prev['location'] or 'home'
            elif gap_mins <= leg + IN_CAR_SLACK_MINS:
                # The gap is barely more than the drive — they really are in
                # the car. This is the case the family described.
                modality, where = 'in_car', (nxt['location'] or prev['location'] or '')
            elif (_travel_mins(prev['location'], home)
                  + _travel_mins(home, nxt['location'])
                  + HOME_DETOUR_MINS) <= gap_mins:
                # Long enough to have gone home and still made it. Calling
                # this "in the car" would be a lie — and the wrong lie, since
                # it implies packing food that could just be cooked.
                modality, where = 'at_home', 'home'
            else:
                modality = 'at_venue'
                where = nxt['location'] or prev['location'] or ''
            spans.append({'start': prev['end'], 'end': nxt['start'],
                          'modality': modality, 'where': where,
                          'after': prev['title'], 'before': nxt['title'],
                          'driving_next': nxt['is_driving'],
                          'travel_mins': _travel_mins(prev['location'], nxt['location'])})
        # after the last commitment — home, if they end the day going home
        last = blocks[-1]
        if last['end'] < day_end:
            spans.append({'start': last['end'], 'end': day_end,
                          'modality': 'at_home', 'where': 'home',
                          'after': last['title'], 'before': None,
                          'driving_next': False,
                          'travel_mins': _travel_mins(last['location'], home)})

    out = []
    for s in spans:
        s['dining_level'] = {'in_car': car_level,
                             'at_venue': venue_level}.get(s['modality'], 'full')
        # The driver of the next leg spends the tail of the gap driving; a
        # passenger eats straight through it. This is why the driver has no
        # slot — and the travel comes off the END, right before the event.
        s['usable_end'] = s['end']
        if s['driving_next'] and s['travel_mins']:
            s['usable_end'] = s['end'] - datetime.timedelta(minutes=s['travel_mins'])
        s['usable_mins'] = int(max(
            0, (s['usable_end'] - s['start']).total_seconds() / 60.0))
        out.append(s)
    return out


def eating_slots(member: dict, date_str: str, sched: dict, settings: dict = None,
                 drivers_by_event: dict = None) -> list:
    """`member_spans` clipped to the meal windows they can actually serve.

    One span can yield several slots — a wide-open evening is a dinner slot
    bounded by the dinner window, not a fifteen-hour blob.
    """
    slots = []
    for s in member_spans(member, date_str, sched, settings, drivers_by_event):
        if s['dining_level'] == 'none':
            continue          # this family does not eat there
        if s['usable_mins'] < MIN_SLOT_MINS:
            continue
        for meal, lo, hi in _meal_intersections(s['start'], s['usable_end']):
            mins = int((hi - lo).total_seconds() / 60.0)
            slots.append({
                'start': lo.isoformat(),
                'end': hi.isoformat(),
                'mins': mins,
                'modality': s['modality'],
                'dining_level': s['dining_level'],
                'where': s['where'],
                'meal': meal,
                'is_driving': bool(s['driving_next']),
                'label': _span_label(s, mins, lo),
            })
    slots.sort(key=lambda s: s['start'])
    return slots


def _span_label(s, mins, lo=None) -> str:
    """Human phrasing for a span. Deliberately fuzzy about the end time."""
    start = (lo or s['start']).strftime('%I:%M').lstrip('0')
    mins = int(mins)
    if s['after'] and s['before']:
        return f"between {s['after']} and {s['before']} — about {mins} min"
    if s['before']:
        return f"before {s['before']} — about {mins} min"
    if s['after']:
        return f"after {s['after']} — from about {start}"
    return f"from about {start} — about {mins} min"


def eating_plan(date_str: str, meal: str = 'dinner', sched: dict = None,
                settings: dict = None) -> dict:
    """The day's eating plan for one meal window.

    Returns per-member slots plus the household picture: who eats when, how
    many sittings, and the largest at-home window a cooking-capable adult has
    before the first of them.

    `no_slot` is a FIRST-CLASS output, not an absence: "nobody has a feasible
    slot" is the honest trigger for suggesting food on the route, and a
    cooking adult with no window is why dinner did not happen.
    """
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    settings = settings if settings is not None else (storage.get_settings() or {})
    drivers_by_event = _driver_member_ids(sched)

    people, no_slot = [], []
    for m in storage.get_all_members():
        if m.get('system'):
            continue
        slots = [s for s in eating_slots(m, date_str, sched, settings, drivers_by_event)
                 if s['meal'] == meal]
        entry = {'member_id': m['id'], 'name': m.get('name'),
                 'role': m.get('role'), 'slots': slots,
                 'first': slots[0] if slots else None}
        people.append(entry)
        if not slots:
            no_slot.append(entry)

    # Sittings group by PLACE first, then time. Splitting on start time alone
    # is useless here: every slot is clipped to the same meal-window boundary,
    # so a kid eating in the car at 5 and a sibling eating at home at 6:30
    # would look like one sitting. What a family means by "split service" is
    # that people eat in different places — that is the real discriminator.
    groups = {}
    for p in people:
        if not p['first']:
            continue
        f = p['first']
        key = (f['modality'], _norm_loc(f['where']))
        g = groups.setdefault(key, {'modality': f['modality'], 'where': f['where'],
                                    'start': None, 'end': None, 'people': []})
        st, en = _parse_iso(f['start']), _parse_iso(f['end'])
        g['start'] = st if g['start'] is None else min(g['start'], st)
        g['end'] = en if g['end'] is None else max(g['end'], en)
        g['people'].append(p)

    sitting_rows = []
    for g in sorted(groups.values(), key=lambda g: (g['start'], g['modality'])):
        where_txt = {'at_home': 'at home', 'in_car': 'in the car'}.get(
            g['modality'], f"at {g['where']}")
        sitting_rows.append({
            'start': g['start'].isoformat(), 'end': g['end'].isoformat(),
            'label': (f"{g['start'].strftime('%I:%M').lstrip('0')}–"
                      f"{g['end'].strftime('%I:%M').lstrip('0')} {where_txt}"),
            'where_kind': g['modality'], 'where': g['where'],
            'member_ids': [p['member_id'] for p in g['people']],
            'names': [p['name'] for p in g['people']],
        })

    packed = [p for p in people
              if p['first'] and p['first']['modality'] in ('in_car', 'at_venue')]

    # The deadline that actually bites: whoever eats away from home needs
    # their food BEFORE their slot opens. Reported separately from the cook
    # window because they answer different questions ("how long do I have"
    # vs "by when").
    deadline = None
    for p in packed:
        st = _parse_iso(p['first']['start'])
        if st and (deadline is None or st < deadline):
            deadline = st

    # Cook window: the largest AT-HOME span a cooking-capable adult has inside
    # the meal window, trimmed to the packed deadline when there is one.
    # Assumption recorded in the design brief: every adult counts as
    # cooking-capable until the family says otherwise.
    members_by_id = {m['id']: m for m in storage.get_all_members()}
    # Raw spans, NOT meal-clipped: cooking happens before people eat.
    cutoff = deadline or (_parse_iso(sitting_rows[0]['start']) if sitting_rows else None)
    cook_window, cook_who = 0, None
    for p in people:
        if p['role'] not in _COOKING_ROLES:
            continue
        for s in member_spans(members_by_id[p['member_id']], date_str, sched,
                              settings, drivers_by_event):
            if s['modality'] != 'at_home':
                continue
            start, end = s['start'], s['usable_end']
            if cutoff:
                if start >= cutoff:
                    continue      # entirely after people started eating
                end = min(end, cutoff)
                # Measure back from when food is needed, not from dawn.
                start = max(start, end - datetime.timedelta(minutes=PREP_HORIZON_MINS))
            usable = (end - start).total_seconds() / 60.0
            if usable > cook_window:
                cook_window, cook_who = int(usable), p['name']

    return {
        'date': date_str,
        'meal': meal,
        'people': people,
        'sittings': sitting_rows,
        'split': len(sitting_rows) > 1,
        'cook_window_mins': cook_window,
        'cook_window_who': cook_who,
        'packed_deadline': deadline.isoformat() if deadline else None,
        'packed_deadline_label': (deadline.strftime('%I:%M').lstrip('0')
                                  if deadline else None),
        'packed_count': len(packed),
        'packed_member_ids': [p['member_id'] for p in packed],
        'no_slot': [{'member_id': p['member_id'], 'name': p['name']} for p in no_slot],
        'nobody_can_eat': bool(people) and not sitting_rows,
        'car_dining': dining_setting('car', settings),
        'venue_dining': dining_setting('venue', settings),
    }


def plan_summary_lines(plan: dict) -> list:
    """The evening-digest / kiosk phrasing.

    Returns [] on an ordinary day. Silence is a feature (principle 6): a plan
    emitted every single day is a stream of orders, not a reduction in load.
    """
    if not plan or not plan.get('people'):
        return []
    lines = []
    constrained = (plan.get('split') or plan.get('packed_count')
                   or plan.get('nobody_can_eat') or plan.get('no_slot')
                   or (plan.get('cook_window_mins') or 0) < 30)
    if not constrained:
        return []

    if plan.get('nobody_can_eat'):
        lines.append("🍽️ Nobody has a real gap to eat tonight — worth grabbing "
                     "something on the way.")
        return lines

    window = plan.get('cook_window_mins') or 0
    who = plan.get('cook_window_who')
    if not window:
        lines.append("🍽️ No real window at home to cook tonight.")
    elif window < COMFORTABLE_COOK_MINS:
        # Only a tight window is the headline; a comfortable one is not news,
        # and leading with "660 min to cook" is noise, not relief.
        lines.append(f"🍽️ About {window} min at home to cook"
                     + (f" ({who})" if who else "") + ".")

    if plan.get('split'):
        parts = [f"{', '.join(s['names'])} {s['label']}" for s in plan['sittings']]
        lines.append("Split: " + " · ".join(parts))

    if plan.get('packed_count'):
        names = [p['name'] for p in plan['people']
                 if p['member_id'] in plan['packed_member_ids']]
        by = plan.get('packed_deadline_label')
        lines.append(f"🥡 Pack {plan['packed_count']} — " + ", ".join(names) +
                     (f", out the door by {by}." if by else " eat out of the house."))

    for miss in plan.get('no_slot') or []:
        lines.append(f"⏳ {miss['name']} has no gap to eat — worth a look.")
    return lines
