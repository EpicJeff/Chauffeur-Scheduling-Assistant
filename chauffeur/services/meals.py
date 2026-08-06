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
from typing import Optional

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
        # ALL-DAY PRESENCE IS NOT PHYSICAL OCCUPATION — the same rule the
        # passenger double-booking pass already follows. An all-day event
        # ("Spirit Week") or a background trip starts at midnight and runs 24h,
        # so treating it as a commitment swallowed the entire day and reported
        # everyone as having no gap to eat. A background trip means the person
        # is AWAY, which is handled by `away_on_trip` dropping them from the
        # household plan — not by pretending they are busy every minute.
        if ev.get('all_day') or ev.get('event_type') == 'background_trip':
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


def away_on_trip(member_id: str, date_str: str, sched: dict) -> bool:
    """Is this member away on a background trip covering this day?

    Someone on a trip is not eating at this house, so they belong OUT of the
    household plan entirely — not given a wide-open at-home evening (they are
    not here) and not reported as having no gap (they are not trapped, they
    are in another city). Chauffeur does not plan trip meals.
    """
    from services import presence
    for ev in sched.get('events', []) or []:
        if ev.get('event_type') != 'background_trip':
            continue
        start, end = _parse_iso(ev.get('start')), _parse_iso(ev.get('end'))
        if not start or not end:
            continue
        try:
            day = datetime.date.fromisoformat(date_str)
        except ValueError:
            return False
        # end is exclusive for all-day spans; a same-day trip still counts.
        if not (start.date() <= day <= end.date()):
            continue
        if any(m['id'] == member_id
               for m in presence.members_at_event(ev, str(ev.get('id', '')), sched)):
            return True
    return False


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

    people, no_slot, away = [], [], []
    for m in storage.get_all_members():
        if m.get('system'):
            continue
        # Away on a trip: not eating at this house tonight. Recorded rather
        # than silently dropped — a plan that quietly omits people is the kind
        # of invisible behaviour that reads as a bug.
        if away_on_trip(m['id'], date_str, sched):
            away.append({'member_id': m['id'], 'name': m.get('name')})
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
        'away': away,
        'nobody_can_eat': bool(people) and not sitting_rows,
        'car_dining': dining_setting('car', settings),
        'venue_dining': dining_setting('venue', settings),
    }


# --- M3: matching the repertoire against the day -----------------------------
# The repertoire stores FIT, not method, which is what makes this a filter
# rather than a planning exercise: "3 of yours fit tonight" is a query over
# what M2 already computed.

# What a meal REQUIRES of the place it is eaten.
_PORTABILITY_RANK = {'none': 0, 'handheld': 1, 'utensils_ok': 2}
# What the family is WILLING to do there (the settings).
_LEVEL_RANK = {'none': 0, 'snack': 1, 'handheld': 2, 'full': 3}


def meal_fits_slot(meal: dict, slot: dict) -> tuple:
    """(fits, reason). Reason explains a NO — the editor and the agent both
    say why rather than silently hiding a meal."""
    modality = slot.get('modality')
    port = str(meal.get('portability') or 'none').lower()
    if modality in ('in_car', 'at_venue'):
        if port == 'none':
            return False, "doesn't travel"
        level = str(slot.get('dining_level') or 'full').lower()
        # utensils_ok food needs a family willing to eat a full meal there;
        # handheld food only needs handheld tolerance.
        need = 'full' if port == 'utensils_ok' else 'handheld'
        if _LEVEL_RANK.get(level, 3) < _LEVEL_RANK[need]:
            return False, f"needs {need} eating {'in the car' if modality == 'in_car' else 'out'}"
    return True, ""


def meal_fits_window(meal: dict, cook_window_mins: int, split: bool) -> tuple:
    """Time fit. `prep_ahead_mins` can land in any earlier gap, but with only
    one window known we require the hands-on total to fit inside it.
    `unattended_mins` deliberately does NOT count against the window — that is
    the whole point of the roast."""
    if str(meal.get('source') or 'prep') == 'ordered':
        return True, ""      # nothing to cook; lead time is handled separately
    hands_on = int(meal.get('prep_ahead_mins') or 0) + int(meal.get('finish_mins') or 0)
    if hands_on > max(cook_window_mins, 0):
        return False, f"needs {hands_on} min hands-on, there's {cook_window_mins}"
    if split and not meal.get('holds_well'):
        return False, "doesn't hold for a split dinner"
    return True, ""


def _eater_diet(plan: dict) -> tuple:
    """(hard_avoid, soft_dislike) tag sets across everyone eating this meal."""
    avoid, dislike = set(), set()
    members = {m['id']: m for m in storage.get_all_members()}
    for p in plan.get('people') or []:
        m = members.get(p['member_id']) or {}
        avoid |= {str(t).strip().lower() for t in (m.get('dietary_avoid') or []) if str(t).strip()}
        dislike |= {str(t).strip().lower() for t in (m.get('dietary_dislike') or []) if str(t).strip()}
    return avoid, dislike


# --- M4: a meal is a composition of dishes ----------------------------------
# The DISH is the unit of work. A plate's timing is the aggregate of the
# dishes actually chosen for it, which is both more accurate than one set of
# numbers per plate and what makes per-dish leftovers exact.

def _chip_label(dish: dict, pool: list) -> str:
    """What the chip should SAY.

    `short_name` is the family's generic word ("potatoes") and is right for a
    slot with one option — but with three potato varieties in the pool every
    chip read "potatoes" and you could not tell which was selected. So when
    there are options, show what DISTINGUISHES this one: the words in its name
    that its siblings do not share ("roasted red potatoes" among red/russet/
    yellow -> "red potatoes"). Falls back to the full name when the names have
    nothing in common, and to short_name when there is nothing to distinguish.
    """
    name = (dish.get('name') or '').strip()
    short = (dish.get('short_name') or '').strip()
    if len(pool) < 2:
        return short or name
    shared = None
    for other in pool:
        if other.get('id') == dish.get('id'):
            continue
        words = {w for w in (other.get('name') or '').lower().split() if w}
        shared = words if shared is None else (shared & words)
    shared = shared or set()
    # Drop the words every sibling shares, EXCEPT the family's own noun — "red"
    # alone is not a dish, "red potatoes" is. Walking the name in order keeps
    # the words in the order a person would say them; re-appending the noun
    # produced things like "grilled thighs chicken".
    protect = {w for w in short.lower().split() if w}
    kept = [w for w in name.split()
            if w.lower() not in shared or w.lower() in protect]
    return ' '.join(kept) if kept else (name or short)


def slot_key(slot: dict, idx: int = 0) -> str:
    """Stable identity for a slot. Falls back to position for rows written
    before slots had ids — NEVER to the label, which repeats ("veggies x 2")
    and caused two slots to share one choice."""
    return str(slot.get('id') or f"slot{idx}")


def choose_dishes(meal: dict, prefer: dict = None, leftovers: list = None) -> list:
    """One dish per slot — the plate as it would actually be made today.

    Choice order: an explicit preference, then anything already made (a
    leftover in the pool is the obvious pick), then least-recently-served so
    the pools rotate on their own.

    Two slots drawing on the SAME pool ("veggies x 2") must not land on the
    same dish, so anything a sibling slot already took is skipped — that is
    what makes it two vegetables rather than the same one twice.
    """
    prefer = prefer or {}
    done = set()
    for l in leftovers or []:
        done.update(l.get('dish_ids') or [])

    chosen, taken = [], set()
    slots = meal.get('slots') or []
    # Explicit picks are honoured first so a later slot's auto-choice cannot
    # steal a dish the family deliberately selected for an earlier one.
    order = sorted(range(len(slots)),
                   key=lambda i: 0 if prefer.get(slot_key(slots[i], i)) else 1)
    picks = {}
    for i in order:
        slot = slots[i]
        pool = storage.get_dishes_by_ids(slot.get('dish_ids') or [])
        if not pool:
            continue
        key = slot_key(slot, i)
        free = [d for d in pool if d['id'] not in taken] or pool
        pick = next((d for d in pool if d['id'] == prefer.get(key)), None)
        if pick is None:
            pick = next((d for d in free if d['id'] in done), None)
        if pick is None:
            pick = min(free, key=lambda d: d.get('last_served_at') or 0)
        taken.add(pick['id'])
        picks[i] = {**pick, '_slot': key, '_label': slot.get('label'),
                    '_optional': bool(slot.get('optional')), '_pool': len(pool),
                    '_chip': _chip_label(pick, pool)}
    for i in range(len(slots)):
        if i in picks:
            chosen.append(picks[i])
    return chosen


def compose(meal: dict, dishes: list, leftovers: list = None) -> dict:
    """Roll a set of dishes up into the timing shape the fit filter reads.

    Hands-on time SUMS (one cook, one pair of hands) while unattended time
    takes the MAX (the oven runs while the rice sits). Portability and
    holds_well take the weakest link — a plate travels only as well as its
    worst dish. Anything already made contributes nothing at all, which is
    the exactness M3's proportional guess could not reach.
    """
    done = set()
    for l in leftovers or []:
        done.update(l.get('dish_ids') or [])

    prep = finish = 0
    unattended = 0
    holds, port_rank = True, 9
    ahead = 'none'
    ahead_rank = {'none': 0, 'thaw': 1, 'marinate': 2, 'slow_cooker': 3}
    for d in dishes:
        if d['id'] in done:
            continue                      # already made: costs nothing
        prep += int(d.get('prep_ahead_mins') or 0)
        finish += int(d.get('finish_mins') or 0)
        unattended = max(unattended, int(d.get('unattended_mins') or 0))
        holds = holds and bool(d.get('holds_well'))
        port_rank = min(port_rank, _PORTABILITY_RANK.get(
            str(d.get('portability') or 'none').lower(), 0))
        if ahead_rank.get(d.get('needs_ahead') or 'none', 0) > ahead_rank.get(ahead, 0):
            ahead = d.get('needs_ahead') or 'none'

    port = 'none'
    for k, v in _PORTABILITY_RANK.items():
        if v == (port_rank if port_rank < 9 else 0):
            port = k
    return {
        **meal,
        'prep_ahead_mins': prep, 'finish_mins': finish,
        'unattended_mins': unattended, 'needs_ahead': ahead,
        'holds_well': holds if dishes else bool(meal.get('holds_well')),
        'portability': port if dishes else str(meal.get('portability') or 'none'),
        'dishes': dishes,
        'leftover_dish_ids': sorted(done & {d['id'] for d in dishes}),
    }


_CHOICES_KEY = 'meal_slot_choices'


def get_choices(date_str: str, meal_id: str = None) -> dict:
    """Which option the family picked per slot, for one day. Kept in app_state
    rather than its own table because it is a same-day preference, not a
    record worth keeping — and it is pruned on every write."""
    all_ch = storage.get_app_state(_CHOICES_KEY) or {}
    day = all_ch.get(date_str) or {}
    return (day.get(meal_id) or {}) if meal_id else day


def set_choices(date_str: str, meal_id: str, mapping: dict):
    """Pin several slots at once.

    Swapping one chip PINS the whole plate, because the other slots' automatic
    picks avoid whatever is already taken — so without pinning, moving one
    vegetable would shuffle the other one under the family's hand. Once you
    touch a plate, it holds still.
    """
    all_ch = storage.get_app_state(_CHOICES_KEY) or {}
    # Yesterday's pick is not today's dinner.
    all_ch = {d: v for d, v in all_ch.items() if d >= date_str}
    slot_map = all_ch.setdefault(date_str, {}).setdefault(meal_id, {})
    slot_map.update({k: v for k, v in (mapping or {}).items() if k and v})
    storage.set_app_state(_CHOICES_KEY, all_ch)


def set_choice(date_str: str, meal_id: str, slot: str, dish_id: str):
    set_choices(date_str, meal_id, {slot: dish_id})


def next_in_pool(meal: dict, slot_id: str, after_dish_id: str,
                 exclude: set = None) -> Optional[str]:
    """The next option in THIS slot's pool, wrapping — what a tap on the chip
    should land on.

    Matched by slot id, not label: two "vegetable" slots have their own pools
    and their own cycles. Dishes a sibling slot is currently showing are
    skipped, so cycling one veg never lands on the other one.
    """
    exclude = set(exclude or ())
    for idx, slot in enumerate(meal.get('slots') or []):
        if slot_key(slot, idx) != str(slot_id):
            continue
        ids = list(slot.get('dish_ids') or [])
        if len(ids) < 2:
            return None
        try:
            start = ids.index(after_dish_id)
        except ValueError:
            start = -1
        for step in range(1, len(ids) + 1):
            cand = ids[(start + step) % len(ids)]
            if cand != after_dish_id and cand not in exclude:
                return cand
        return None
    return None


def ensure_slot_ids(meal: dict) -> dict:
    """Backfill ids onto slots written before slots had them, and persist.

    Without this, meals already in the family's repertoire keep colliding on
    their labels — the very rows most likely to hit the bug are the ones that
    predate the fix.
    """
    slots = meal.get('slots') or []
    if not slots or all(s.get('id') for s in slots):
        return meal
    import uuid as _uuid
    patched = [{**s, 'id': s.get('id') or _uuid.uuid4().hex} for s in slots]
    storage.update_meal(meal['id'], {'slots': patched})
    return {**meal, 'slots': patched}


def compose_meal(meal: dict, prefer: dict = None, leftovers: list = None) -> dict:
    """`choose_dishes` + `compose`. Legacy meals with no slots pass through on
    their own stored numbers, so nothing breaks mid-migration."""
    if not (meal.get('slots') or []):
        return {**meal, 'dishes': []}
    meal = ensure_slot_ids(meal)
    dishes = choose_dishes(meal, prefer, leftovers)
    return compose(meal, dishes, leftovers)


def leftover_for(meal: dict, leftovers: list) -> Optional[dict]:
    """The leftover record covering this meal, if any."""
    for l in leftovers or []:
        if l.get('meal_id') and l['meal_id'] == meal.get('id'):
            return l
    return None


def apply_leftovers(meal: dict, leftover: dict) -> dict:
    """A copy of `meal` with the work already done taken out.

    Whole-meal leftovers are exact: the only cost left is reheating, and
    nothing is bought. A PARTIAL leftover ("the rice is already made") cannot
    be exact — the schema deliberately has no per-component times, and adding
    them would be recipe-box drift — so the remaining hands-on is scaled by
    the share of components still to make and flagged as an estimate. The
    point is not an exact number; it is that the app stops holding time for
    work nobody is going to do.
    """
    if not leftover:
        return meal
    out = dict(meal)
    reheat = max(0, int(leftover.get('reheat_mins') or 0))
    parts = [str(p).strip().lower() for p in (leftover.get('parts') or []) if str(p).strip()]
    out['leftover'] = True
    out['leftover_parts'] = parts

    if not parts:                       # the whole thing is already made
        out['prep_ahead_mins'] = 0
        out['finish_mins'] = reheat
        out['unattended_mins'] = 0
        out['needs_ahead'] = 'none'
        out['leftover_exact'] = True
        return out

    ings = meal.get('ingredients') or []
    total = len(ings) or 1
    covered = sum(1 for i in ings
                  if (i.get('name') or '').strip().lower() in parts)
    remaining = max(0.0, (total - covered) / total)
    out['prep_ahead_mins'] = int(round((meal.get('prep_ahead_mins') or 0) * remaining))
    out['finish_mins'] = int(round((meal.get('finish_mins') or 0) * remaining)) + reheat
    out['leftover_exact'] = False
    if covered:
        # Nothing left to thaw if the thing needing the head start is made.
        out['needs_ahead'] = 'none' if remaining == 0 else meal.get('needs_ahead')
    return out


def meals_that_fit(plan: dict, limit: int = 5) -> dict:
    """Repertoire entries that actually work for this plan, ranked.

    Hard filters: the household's tightest slot (a meal everyone can eat has
    to survive the car if someone is in the car), the cook window, and
    allergies. Soft signals only reorder: recency (rotation), dislikes,
    effort. Returns {'fits': [...], 'blocked': [...]} — blocked entries carry
    their reason so nothing vanishes without explanation.
    """
    repertoire = storage.get_meals()
    leftovers = storage.get_leftovers(plan.get('date'))
    # "We just have leftovers tonight" with no repertoire entry attached is a
    # complete answer on its own — it needs no meal and beats everything else.
    loose = [l for l in leftovers if not l.get('meal_id')]
    if not repertoire and not loose:
        return {'fits': [], 'blocked': [], 'empty': True}

    avoid, dislike = _eater_diet(plan)
    window = int(plan.get('cook_window_mins') or 0)
    split = bool(plan.get('split'))
    # The binding slot is the most restrictive one anyone actually has.
    slots = [p['first'] for p in (plan.get('people') or []) if p.get('first')]
    slots.sort(key=lambda s: _PORTABILITY_RANK.get('none') if s['modality'] == 'at_home' else 1,
               reverse=True)
    binding = next((s for s in slots if s['modality'] in ('in_car', 'at_venue')),
                   slots[0] if slots else None)

    fits, blocked = [], []
    for l in loose:
        # Ranked above everything by construction: there is nothing to make.
        fits.append({'id': f"leftover:{l['id']}", 'name': l.get('label') or 'Leftovers',
                     'prep_ahead_mins': 0, 'finish_mins': int(l.get('reheat_mins') or 0),
                     'unattended_mins': 0, 'needs_ahead': 'none', 'holds_well': True,
                     'portability': 'utensils_ok', 'source': 'prep', 'effort': 'easy',
                     'ingredients': [], 'tags': [], 'leftover': True,
                     'leftover_exact': True, 'score': 99.0})

    for meal in repertoire:
        tags = {str(t).strip().lower() for t in (meal.get('tags') or [])}
        if tags & avoid:
            blocked.append({**meal, 'why': "someone eating can't have it"})
            continue
        # Leftovers are applied BEFORE the window check — the whole point is
        # that the app stops holding time for work already done.
        if meal.get('slots'):
            # M4: composition already excludes already-made dishes, exactly.
            meal = compose_meal(meal,
                                prefer=get_choices(plan.get('date') or _today_iso(),
                                                   meal.get('id')),
                                leftovers=leftovers)
            if meal.get('leftover_dish_ids'):
                meal['leftover'] = True
                meal['leftover_exact'] = True
        else:
            lo = leftover_for(meal, leftovers)
            meal = apply_leftovers(meal, lo) if lo else meal
        if binding:
            ok, why = meal_fits_slot(meal, binding)
            if not ok:
                blocked.append({**meal, 'why': why})
                continue
        ok, why = meal_fits_window(meal, window, split)
        if not ok:
            blocked.append({**meal, 'why': why})
            continue
        score = 3.0 if meal.get('leftover') else 0.0
        score -= 2.0 if tags & dislike else 0.0            # soft: demote, never remove
        score -= {'easy': 0.0, 'normal': 0.5, 'project': 2.0}.get(
            str(meal.get('effort') or 'normal'), 0.5)
        last = meal.get('last_served_at') or 0
        score += min((_now_ts() - last) / 86400.0, 21) / 21.0   # rotation, capped at 3 weeks
        if meal.get('needs_ahead') not in (None, '', 'none'):
            score -= 0.75          # possible but it wanted a morning decision
        fits.append({**meal, 'score': round(score, 3)})

    fits.sort(key=lambda m: -m['score'])
    return {'fits': fits[:limit], 'blocked': blocked, 'empty': False}


def _now_ts() -> float:
    import time as _t
    return _t.time()


def _today_iso() -> str:
    return datetime.date.today().isoformat()


# --- population: the human supplies the NAME, the model supplies the rest ----
# This is where the phase dies if it dies. Nobody fills in fifteen meals on a
# form with twelve fields, and a repertoire that never reaches critical mass
# has nothing to filter. Entry cost must be one sentence.

_META_SYSTEM = (
    "You turn a family's own description of a meal they make into scheduling "
    "metadata. The description may be a bare name ('tacos') or a full plate "
    "written out however they say it ('chicken, rice, beans (black, red, or "
    "pinto), veggies (carrots, green beans, broccoli), salad'). Reply with "
    "STRICT JSON only, no prose, no code fences. You are NOT writing a recipe "
    "— never return steps or instructions.\n\n"
    "Schema: {\"name\": str, \"prep_ahead_mins\": int, \"finish_mins\": int, "
    "\"unattended_mins\": int, \"needs_ahead\": \"none|thaw|marinate|slow_cooker\", "
    "\"holds_well\": bool, \"portability\": \"none|handheld|utensils_ok\", "
    "\"source\": \"prep|ordered|hybrid\", \"effort\": \"easy|normal|project\", "
    "\"serves\": int, \"tags\": [str], "
    "\"ingredients\": [{\"name\": str, \"kind\": \"staple|fresh\", "
    "\"options\": [str], \"role\": str|null, \"optional\": bool}]}\n\n"
    "Definitions that matter:\n"
    "- name: a SHORT label the family would actually say out loud — 2-4 words, "
    "e.g. 'Chicken plate', 'Tacos', 'Pizza night'. NEVER echo back the whole "
    "description. If they listed a plate's parts, name the plate after its "
    "protein or its character, and put the parts in `ingredients`.\n"
    "- prep_ahead_mins: hands-on work that can be done EARLIER in the day and "
    "set aside (chopping, browning, cooking rice).\n"
    "- finish_mins: hands-on work that must happen close to eating.\n"
    "- unattended_mins: oven/slow-cooker time needing nobody at the stove. A "
    "roast is a small finish time and a large unattended time.\n"
    "- holds_well: survives sitting 60-90 minutes and reheating.\n"
    "- portability: can it be eaten away from a table? 'utensils_ok' means it "
    "travels in a container and is eaten with a fork; 'handheld' needs no "
    "utensils; 'none' does not travel.\n"
    "- source: 'ordered' for takeout/delivery a family buys, 'hybrid' when "
    "part is bought and part is made, else 'prep'.\n"
    "- ingredients: what a shopper would write. kind='staple' for things "
    "essentially always in a kitchen (salt, oil, common spices, rice, pasta, "
    "flour); kind='fresh' for anything bought for this dish. Do NOT include "
    "quantities.\n"
    "- options: use this when the line is a CATEGORY the family fills with "
    "any one of several things. A plate meal like 'chicken, rice, beans, "
    "veggies, salad' is ONE meal whose parts substitute: emit "
    "{\"name\": \"beans\", \"options\": [\"black\", \"red\", \"pinto\"]} and "
    "{\"name\": \"vegetable\", \"options\": [\"carrots\", \"green beans\", "
    "\"broccoli\"]}. Separate lines mean AND (rice AND salad); options inside "
    "one line mean OR (rice OR potatoes). Leave options empty for a fixed "
    "ingredient like 'ground beef'. NEVER split one substitutable category "
    "into several lines — a shopper buys one bean, not three.\n"
    "- role: a short label for a plate component ('protein', 'starch', "
    "'vegetable', 'side'), or null for an ordinary ingredient.\n"
    "- optional: true for a part the family would happily skip (a salad "
    "alongside a full plate), false otherwise.\n"
    "- tags: short lowercase descriptors useful for dietary filtering and "
    "variety, e.g. ['chicken','mexican','gluten'].\n\n"
    "Be realistic about a home kitchen on a weeknight. If the name is too "
    "vague to judge, return conservative middle values rather than refusing."
)


def suggest_meal_metadata(description: str) -> dict:
    """One LLM call on the INTERACTIVE tier (someone is waiting) turning the
    family's own words into a full entry — including a SHORT display name, so
    they can type a whole plate out the way they say it instead of having to
    pre-digest it into a title. Returns {} on any failure: the caller falls
    back to a plain entry, because failing to save a meal someone just named
    is worse than saving a rough one."""
    from services import model_pools
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key or not (description or '').strip():
        return {}
    try:
        res = model_pools.call_pool_json(
            'interactive', api_key, _META_SYSTEM,
            f"The family describes one of their meals as: {description.strip()}",
            temperature=0.2, timeout_s=45,
            settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            return {}
    except Exception as e:
        print(f"[meals] metadata suggestion failed for {description!r}: {e}")
        return {}

    def _int(key, lo=0, hi=600):
        try:
            return max(lo, min(hi, int(res.get(key) or 0)))
        except (TypeError, ValueError):
            return 0

    def _choice(key, allowed, default):
        v = str(res.get(key) or '').strip().lower()
        return v if v in allowed else default

    ings = []
    seen = set()
    for i in (res.get('ingredients') or [])[:30]:
        if not isinstance(i, dict):
            continue
        nm = str(i.get('name') or '').strip()[:60]
        if not nm or nm.lower() in seen:
            continue
        seen.add(nm.lower())
        opts, opt_seen = [], set()
        for o in (i.get('options') or [])[:12]:
            ov = str(o).strip()[:40]
            if ov and ov.lower() not in opt_seen:
                opt_seen.add(ov.lower())
                opts.append(ov)
        role = str(i.get('role') or '').strip()[:24] or None
        ings.append({'name': nm,
                     'kind': 'staple' if str(i.get('kind') or '').lower() == 'staple'
                             else 'fresh',
                     'options': opts,
                     'role': role,
                     'optional': bool(i.get('optional'))})
    out = {
        'prep_ahead_mins': _int('prep_ahead_mins'),
        'finish_mins': _int('finish_mins'),
        'unattended_mins': _int('unattended_mins'),
        'needs_ahead': _choice('needs_ahead',
                               ('none', 'thaw', 'marinate', 'slow_cooker'), 'none'),
        'holds_well': bool(res.get('holds_well')),
        'portability': _choice('portability',
                               ('none', 'handheld', 'utensils_ok'), 'none'),
        'source': _choice('source', ('prep', 'ordered', 'hybrid'), 'prep'),
        'effort': _choice('effort', ('easy', 'normal', 'project'), 'normal'),
        'serves': _int('serves', 1, 20) or 4,
        'tags': [str(t).strip().lower()[:24] for t in (res.get('tags') or [])[:8]
                 if str(t).strip()],
        'ingredients': ings,
    }
    # A short name only counts if it is actually shorter than what they typed —
    # a model that echoes the description back has not helped.
    short = str(res.get('name') or '').strip()[:60]
    if short and len(short) < len(description.strip()):
        out['name'] = short
    return out


_DISH_SYSTEM = (
    "You break a family's description of a meal into DISHES. Reply with "
    "STRICT JSON only, no prose, no code fences. You are NOT writing recipes "
    "— never return steps, instructions or quantities.\n\n"
    "Schema: {\"name\": str, \"slots\": [{\"label\": str, \"optional\": bool, "
    "\"dishes\": [{\"name\": str, \"short_name\": str, \"role\": str, "
    "\"prep_ahead_mins\": int, \"finish_mins\": int, \"unattended_mins\": int, "
    "\"needs_ahead\": \"none|thaw|marinate|slow_cooker\", \"holds_well\": bool, "
    "\"portability\": \"none|handheld|utensils_ok\", "
    "\"source\": \"prep|ordered\", \"tags\": [str], "
    "\"ingredients\": [{\"name\": str, \"kind\": \"staple|fresh\"}], "
    "\"needs_detail\": bool, \"detail_question\": str|null}]}]}\n\n"
    "How to split:\n"
    "- name: a SHORT label for the whole meal, 2-4 words ('Chicken plate'). "
    "Never echo the description back.\n"
    "- Each part of the plate is a SLOT. A part with alternatives becomes ONE "
    "slot holding one dish PER ALTERNATIVE: 'beans (black, red, or pinto)' is "
    "a slot labelled 'beans' with THREE dishes — black beans, red beans, "
    "pinto beans. A fixed part is a slot with a single dish.\n"
    "- optional: true for a part the family would happily skip (a side salad).\n\n"
    "Each DISH is a unit of cooking work, timed on its own:\n"
    "- prep_ahead_mins is work that can be done earlier and set aside; "
    "finish_mins must happen near eating; unattended_mins is oven or "
    "slow-cooker time needing nobody at the stove. Rice is a little prep and "
    "a lot of unattended; a salad is all finish.\n"
    "- name is SPECIFIC enough to time and shop for ('roasted russet "
    "potatoes'), short_name is what the family says ('potatoes').\n"
    "- ingredients: kind='staple' for things a kitchen always has (salt, oil, "
    "common spices, rice, pasta, flour), 'fresh' for what must be bought. No "
    "quantities.\n"
    "- needs_detail: TRUE only when the family was too vague to time or shop "
    "accurately — bare 'potatoes' says neither which kind nor how cooked, and "
    "roasted vs mashed are different jobs. GUESS a sensible common version "
    "anyway and put it in `name`; never refuse and never leave it blank. Set "
    "detail_question to the single short question that would resolve it "
    "('Which potatoes, and roasted or mashed?').\n"
    "  FALSE whenever they already told you. 'roasted potatoes (red, russet, "
    "yellow)' gives BOTH the method and the varieties — that is three fully "
    "specified dishes, not a question. Never ask about something stated in "
    "the description, and be consistent: options in one slot are variants of "
    "the same thing, so either all of them need detail or none do.\n"
    "- Be realistic about a weeknight home kitchen."
)


def _clean_dish(raw: dict) -> Optional[dict]:
    from models.schemas import Dish
    if not isinstance(raw, dict):
        return None
    name = str(raw.get('name') or '').strip()[:70]
    if not name:
        return None

    def _int(key, hi=600):
        try:
            return max(0, min(hi, int(raw.get(key) or 0)))
        except (TypeError, ValueError):
            return 0

    def _choice(key, allowed, default):
        v = str(raw.get(key) or '').strip().lower()
        return v if v in allowed else default

    ings, seen = [], set()
    for i in (raw.get('ingredients') or [])[:15]:
        if not isinstance(i, dict):
            continue
        nm = str(i.get('name') or '').strip()[:60]
        if not nm or nm.lower() in seen:
            continue
        seen.add(nm.lower())
        ings.append({'name': nm,
                     'kind': 'staple' if str(i.get('kind') or '').lower() == 'staple'
                             else 'fresh'})
    return Dish(
        name=name,
        short_name=str(raw.get('short_name') or '').strip()[:40] or None,
        role=str(raw.get('role') or '').strip()[:24] or None,
        prep_ahead_mins=_int('prep_ahead_mins'), finish_mins=_int('finish_mins'),
        unattended_mins=_int('unattended_mins'),
        needs_ahead=_choice('needs_ahead',
                            ('none', 'thaw', 'marinate', 'slow_cooker'), 'none'),
        holds_well=bool(raw.get('holds_well')),
        portability=_choice('portability', ('none', 'handheld', 'utensils_ok'), 'none'),
        source=_choice('source', ('prep', 'ordered'), 'prep'),
        ingredients=ings,
        tags=[str(t).strip().lower()[:24] for t in (raw.get('tags') or [])[:6]
              if str(t).strip()],
        needs_detail=bool(raw.get('needs_detail')),
        detail_question=str(raw.get('detail_question') or '').strip()[:120] or None,
    ).model_dump()


def split_into_dishes(description: str) -> dict:
    """One interactive-tier call turning the family's words into a meal name
    plus slots of dishes. Returns {} on failure so the caller can still save
    something."""
    from services import model_pools
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key or not (description or '').strip():
        return {}
    try:
        res = model_pools.call_pool_json(
            'interactive', api_key, _DISH_SYSTEM,
            f"The family describes one of their meals as: {description.strip()}",
            temperature=0.2, timeout_s=45, settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            return {}
    except Exception as e:
        print(f"[meals] dish split failed for {description!r}: {e}")
        return {}

    slots = []
    for raw_slot in (res.get('slots') or [])[:10]:
        if not isinstance(raw_slot, dict):
            continue
        dishes = [d for d in (_clean_dish(x) for x in (raw_slot.get('dishes') or [])[:8])
                  if d]
        if not dishes:
            continue
        # Options in one slot are variants of the same thing, so they are
        # either all specific enough or none of them are. The model flags them
        # inconsistently — "roasted potatoes (red, russet, yellow)" came back
        # with two clean dishes and one asking which type and how cooked — and
        # a lone question mark on one of three identical-looking chips is just
        # noise. If any sibling is clean, they all are.
        if len(dishes) > 1 and any(not d.get('needs_detail') for d in dishes):
            for d in dishes:
                d['needs_detail'] = False
                d['detail_question'] = None
        slots.append({'label': str(raw_slot.get('label') or '').strip()[:40] or None,
                      'optional': bool(raw_slot.get('optional')),
                      'dishes': dishes})
    if not slots:
        return {}
    name = str(res.get('name') or '').strip()[:60]
    return {'name': name if name and len(name) < len(description.strip()) else '',
            'slots': slots}


def create_meal_from_dishes(description: str) -> dict:
    """The M4 entry path: type a plate however you say it, get one meal whose
    parts are real dishes — and reuse the dishes already defined, so the rice
    in a second meal is the same rice."""
    from models.schemas import Meal
    raw = (description or '').strip()
    split = split_into_dishes(raw)
    if not split:
        return create_meal(raw)          # extraction unavailable — M3 fallback

    slots = []
    for s in split['slots']:
        ids = []
        for d in s['dishes']:
            existing = storage.find_dish_by_name(d['name'])
            if existing:
                ids.append(existing['id'])
                continue
            storage.add_dish(d)
            ids.append(d['id'])
        slots.append({'label': s['label'], 'dish_ids': ids,
                      'optional': s['optional']})

    name = split['name'] or raw[:60]
    meal = Meal(name=name, slots=slots,
                description=raw if name != raw else None).model_dump()
    storage.add_meal(meal)
    return meal


def create_meal(description: str, enrich: bool = True) -> dict:
    """Add a repertoire entry from the family's own words.

    `description` may be a bare name ("tacos") or a whole plate written out
    the way they say it ("chicken, rice, beans (black, red, or pinto),
    veggies (…), salad"). The model derives a short display name and the
    components; without enrichment the raw text becomes the name, truncated,
    and can be renamed in the editor.
    """
    from models.schemas import Meal
    raw = (description or '').strip()
    data = {'name': raw[:60]}
    if enrich:
        data.update(suggest_meal_metadata(raw))
    if data['name'] != raw:
        data['description'] = raw
    meal = Meal(**data).model_dump()
    storage.add_meal(meal)
    return meal


def _category_already_open(list_id: str, name: str, options: list) -> bool:
    """Is this (possibly substitutable) ingredient line already covered by
    something open on the list?

    Checks the category itself, each bare option, and each option combined
    with the category in both orders — 'black' + 'beans' is how the family
    wrote it, but the list will say 'black beans'.
    """
    if storage.find_open_shopping_item(list_id, name):
        return True
    for o in options or []:
        for candidate in (o, f"{o} {name}", f"{name} {o}"):
            if storage.find_open_shopping_item(list_id, candidate):
                return True
    return False


def refine_dish(dish_id: str, description: str) -> Optional[dict]:
    """Re-derive a vague dish from a more specific answer ("russet, roasted").

    This is what makes the guess safe: the model never blocks entry, and the
    family sharpens it when they feel like it — which fixes the timing AND
    the shopping line in one move.
    """
    dish = storage.get_dish(dish_id)
    if not dish:
        return None
    fresh = split_into_dishes(description) or {}
    picked = None
    for s in fresh.get('slots') or []:
        for d in s.get('dishes') or []:
            picked = d
            break
        if picked:
            break
    if not picked:
        # No model: at least record what they said and stop asking.
        storage.update_dish(dish_id, {'name': (description or dish['name']).strip()[:70],
                                      'needs_detail': False, 'detail_question': None})
        return storage.get_dish(dish_id)
    patch = {k: v for k, v in picked.items()
             if k not in ('id', 'doc_id', 'created_at', 'last_served_at', 'is_active')}
    patch['needs_detail'] = False
    patch['detail_question'] = None
    patch['short_name'] = dish.get('short_name') or patch.get('short_name')
    storage.update_dish(dish_id, patch)
    return storage.get_dish(dish_id)


def dishes_to_shopping(dishes: list, list_id: str = None, added_by: str = None,
                       skip_dish_ids: list = None) -> dict:
    """Shop for the dishes actually chosen — one plate's worth, not every
    alternative in every pool. Already-made dishes buy nothing."""
    from models.schemas import ShoppingItem
    skip = set(skip_dish_ids or [])
    lst_id = list_id or storage.ensure_default_shopping_list()['id']
    added, skipped = [], []
    for d in dishes:
        if d.get('id') in skip:
            skipped.append(d.get('short_name') or d.get('name'))
            continue
        if str(d.get('source') or 'prep') == 'ordered':
            skipped.append(d.get('name'))
            continue
        for ing in d.get('ingredients') or []:
            name = (ing.get('name') or '').strip()
            if not name:
                continue
            if (ing.get('kind') or 'fresh') == 'staple':
                skipped.append(name)
                continue
            if storage.find_open_shopping_item(lst_id, name):
                skipped.append(name)
                continue
            storage.add_shopping_item(ShoppingItem(
                list_id=lst_id, name=name, added_via='meal',
                source_meal_id=d.get('id'), added_by=added_by).model_dump())
            added.append(name)
    return {'added': added, 'skipped': skipped, 'list_id': lst_id}


def ingredients_to_shopping(meal: dict, list_id: str = None,
                            added_by: str = None) -> dict:
    """Drain a meal's FRESH ingredients onto the shopping list.

    Staples never go — that is the whole point of classifying them, and it is
    how this recovers most of inventory's value while tracking item CLASS
    rather than item STATE. An `ordered` meal contributes nothing at all; a
    hybrid contributes only its prepped part.
    """
    from models.schemas import ShoppingItem
    # M4: a composed meal shops from the dishes actually chosen.
    if meal.get('slots'):
        today = _today_iso()
        leftovers = storage.get_leftovers(today)
        composed = compose_meal(meal, prefer=get_choices(today, meal.get('id')),
                                leftovers=leftovers)
        return dishes_to_shopping(composed.get('dishes') or [], list_id, added_by,
                                  skip_dish_ids=composed.get('leftover_dish_ids'))
    if str(meal.get('source') or 'prep') == 'ordered':
        return {'added': [], 'skipped': [], 'reason': 'ordered — nothing to buy'}
    # Already-made food is not shopping. A whole-meal leftover buys nothing;
    # a partial one skips just the parts that are done.
    if meal.get('leftover') and not (meal.get('leftover_parts') or []):
        return {'added': [], 'skipped': [], 'reason': 'leftovers — nothing to buy'}
    done_parts = {str(p).strip().lower() for p in (meal.get('leftover_parts') or [])}
    lst_id = list_id or storage.ensure_default_shopping_list()['id']
    added, skipped = [], []
    for ing in meal.get('ingredients') or []:
        name = (ing.get('name') or '').strip()
        if not name:
            continue
        if name.lower() in done_parts:
            skipped.append(name)
            continue
        if (ing.get('kind') or 'fresh') == 'staple':
            skipped.append(name)
            continue
        opts = [str(o).strip() for o in (ing.get('options') or []) if str(o).strip()]
        # A substitutable line is satisfied by ANY of its options, so an open
        # "black beans" means the family does not also need a "beans" line.
        # Options are usually QUALIFIERS ('black') that only name a real
        # product once combined with the category ('beans'), so match the
        # combined forms too — matching the bare option alone misses every
        # realistic case.
        if _category_already_open(lst_id, name, opts):
            skipped.append(name)
            continue
        note = None
        if opts:
            note = (", ".join(opts[:-1]) + f", or {opts[-1]}") if len(opts) > 1 \
                else opts[0]
        if ing.get('optional'):
            note = (note + " · optional") if note else "optional"
        storage.add_shopping_item(ShoppingItem(
            list_id=lst_id, name=name, note=note, added_via='meal',
            source_meal_id=meal.get('id'), added_by=added_by).model_dump())
        added.append(name)
    return {'added': added, 'skipped': skipped, 'list_id': lst_id}


def morning_prep_note(date_str: str = None) -> Optional[str]:
    """The K5-launch-line touchpoint: if tonight is tight and the repertoire's
    best fit wanted a head start, say so THIS MORNING while it is still
    actionable. Returns None when there is nothing worth saying."""
    import datetime as _dt
    date_str = date_str or _dt.date.today().isoformat()
    plan = eating_plan(date_str, 'dinner')
    if not plan.get('people') or plan.get('nobody_can_eat'):
        return None
    res = meals_that_fit(plan, limit=3)
    for meal in res.get('fits') or []:
        need = meal.get('needs_ahead')
        if need in (None, '', 'none'):
            continue
        verb = {'thaw': 'get out to thaw', 'marinate': 'get marinating',
                'slow_cooker': 'get in the slow cooker'}.get(need, 'start')
        window = plan.get('cook_window_mins') or 0
        tight = f" Tonight's window is about {window} min." if window and window < 60 else ""
        return f"🍽️ If it's {meal['name']} tonight, {verb} now.{tight}"
    return None


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

    # Leftovers answer the cook question outright, so a tight window is no
    # longer pressure — reporting it anyway would be manufacturing stress
    # about work nobody is doing.
    leftovers = storage.get_leftovers(plan.get('date'))
    whole_night = [l for l in leftovers if not (l.get('parts') or [])]
    if whole_night:
        what = next((l.get('label') for l in whole_night if l.get('label')), None)
        lines.append(f"🍲 Leftovers tonight{f' — {what}' if what else ''}. "
                     "Nothing to make.")

    window = plan.get('cook_window_mins') or 0
    who = plan.get('cook_window_who')
    if whole_night:
        pass                       # already answered — do not add cook pressure
    elif not window:
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
    # Only worth saying when the evening was already worth talking about; on
    # its own, "someone is away" is not news the family needs told back.
    if lines and plan.get('away'):
        names = ", ".join(a['name'] for a in plan['away'])
        lines.append(f"✈️ {names} away — not counted in.")
    return lines
