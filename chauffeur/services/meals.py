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
from services import kitchen

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

# --- M5: plates are COMPOSED from typed dishes ------------------------------
# A family does not eat 15-20 unrelated meals; they eat combinations of maybe
# 25 dishes. Storing the combinations was both lossy (the number of sides
# froze at whatever was typed) and misleading (one "meal" standing in for a
# dozen dinners). So the repertoire is DISHES, and a plate is a rule:
# a `meal` dish on its own, or an entree plus N sides — with a dessert if the
# family keeps them. Propose, then let it be edited: that is the same
# propose→approve grammar the intake queue and the car stops already use, and
# it is what keeps this from being a nightly assembly chore.

SIDE_TYPES = ('vegetable', 'starch', 'salad', 'other')
DISH_TYPES = ('meal', 'entree', 'side', 'dessert')


def household_headcount(settings: dict = None) -> int:
    """How many people the cooking is for, by default.

    There was no answer to this at all before v2.109. `serving_for` was None
    unless somebody typed a number on a specific night for hosting, and
    `kitchen.scale_factor` returns 1.0 for a falsy headcount — so every dish
    was quietly made at whatever its `serves` said and nothing was ever scaled
    or forecast. Occasions counted every non-helper member; meals counted
    nobody.

    A configured number wins, because a household is not the same as a list of
    profiles: people live elsewhere, a teenager eats at work, a helper is on
    the driving roster and never at the table. Falling back to the roster is
    better than falling back to nothing, but it is a guess and the setting is
    how the family stops us guessing.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    try:
        n = int(settings.get('household_headcount') or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return n
    roster = [m for m in storage.get_all_members()
              if not m.get('system') and m.get('role') != 'helper']
    return max(1, len(roster))


def eaters_on(date_str: str, settings: dict = None, sched: dict = None) -> int:
    """Tonight's headcount: the household default, less anyone away.

    A per-night override (set for hosting) always wins — it is the family
    stating a fact about that night, not a default to be adjusted.
    """
    saved = storage.get_plate(date_str) or {}
    if saved.get('serving_for'):
        return int(saved['serving_for'])
    base = household_headcount(settings)
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    away = 0
    for m in storage.get_all_members():
        if m.get('system') or m.get('role') == 'helper':
            continue
        if away_on_trip(m['id'], date_str, sched):
            away += 1
    return max(1, base - away)


def leftover_nights(dish: dict, headcount: int) -> int:
    """How many EXTRA nights this dish makes, beyond the one it is cooked for.

    FLOOR, never ceiling: a night only counts when there is enough left to feed
    EVERYONE again. Nine people eating a dish that serves six means making
    double and having three portions spare, and three portions is not dinner —
    proposing it again on the strength of that would mean cooking more of it,
    leaving a little spare again, forever. That forever-cycle is the reason
    this is not "is there anything left".

    Equivalent to the long way round — make whole batches, subtract what was
    eaten, and see how many further full sittings remain:

        floor((ceil(head / serves) * serves - head) / head)

    ...which reduces to the expression below in every case (tested exhaustively
    in `scenario_a_little_bit_left_over_is_not_another_night`).

    `serves` is a SCALING input and nothing else. It says how much to make and
    therefore what is left over; it must never make a dish more or less likely
    to be proposed in its own right.
    """
    try:
        serves = int(dish.get('serves') or 0)
    except (TypeError, ValueError):
        serves = 0
    if serves <= 0 or headcount <= 0:
        return 0
    return max(0, serves // headcount - 1)


def plate_shape() -> list:
    """What a plate is, in the family's own words — the categories and the
    range of each. Replaced `plate_settings`, which returned a side COUNT and a
    dessert flag and could not express "1 protein, 2-3 vegetables, 1-2
    starches" at all."""
    return storage.get_dish_categories()


def _dish_ok(dish: dict, avoid: set, binding_slot: dict, leftover_ids: set,
             open_tags: set = None) -> bool:
    """Hard filters only. An already-made dish skips the portability check —
    it exists, and it is going in a container either way.

    The same bypass governs `scope` (occasions arc O0), and it is the trap
    worth naming: turkey is `scope: occasion`, and the days right after
    Thanksgiving are PRECISELY when it must land on an ordinary plate. Filter
    it naively here and the dish is blocked from the days it exists to cover.
    **Scope gates proposal, never presence** — which is also why hand-picking
    (the plate picker, `set_plate_lock`) never comes through this function.

    `open_tags` is what an occasion's window opens up (O1): the turkey becomes
    ELIGIBLE across Thanksgiving week, which is emphatically not the same as
    proposing turkey for four days running. A dish still has to win on rank
    against everything else, and the family still chooses the night.
    """
    tags = {str(t).strip().lower() for t in (dish.get('tags') or [])}
    if tags & avoid:
        return False
    if dish['id'] not in leftover_ids and str(
            dish.get('scope') or 'everyday') == 'occasion':
        if not (open_tags and (tags & open_tags)):
            return False
    if binding_slot and dish['id'] not in leftover_ids:
        ok, _ = meal_fits_slot(dish, binding_slot)
        if not ok:
            return False
    return True


def _as_of_ts(date_str: str) -> float:
    """The instant a plate should be ranked FROM — midnight of its own date.

    Recency used to be measured from wall-clock now regardless of which day
    was being composed, which is precisely why planning ahead was impossible:
    Monday through Thursday all scored against identical values and proposed
    much the same dinner four nights running.
    """
    try:
        d = datetime.date.fromisoformat(str(date_str))
    except (TypeError, ValueError):
        return _now_ts()
    return datetime.datetime.combine(d, datetime.time(0, 0)).timestamp()


def add_meal_rule(name: str, kind: str = 'frequency_cap', **kw) -> dict:
    """Create a rule. Returns it plus the dishes it currently matches, because
    a rule that matches nothing is the failure mode here — "meat" is not a
    field, and a tag the family never used silently governs nobody."""
    from models.schemas import MealRule
    kind = kind if kind in ('frequency_cap', 'batch_cycle', 'repeat_spacing') else 'frequency_cap'
    rule = MealRule(name=(name or '').strip() or kind.replace('_', ' '),
                    kind=kind,
                    dish_ids=[str(x) for x in (kw.get('dish_ids') or [])],
                    tags=[str(t).strip().lower() for t in (kw.get('tags') or []) if str(t).strip()],
                    types=[str(t) for t in (kw.get('types') or [])],
                    side_types=[str(t) for t in (kw.get('side_types') or [])],
                    sources=[str(t) for t in (kw.get('sources') or [])],
                    exclude_dish_ids=[str(x) for x in (kw.get('exclude_dish_ids') or [])],
                    max_servings=max(1, int(kw.get('max_servings') or 1)),
                    window_days=max(1, int(kw.get('window_days') or 7)),
                    dwell_days=max(1, int(kw.get('dwell_days') or 3))).model_dump()
    storage.save_meal_rule(rule)
    _cats = _category_names_by_id()
    matched = [d for d in storage.get_dishes() if rule_matches(rule, d, _cats)]
    return {'status': 'success', 'rule': rule,
            'matches': [d.get('short_name') or d['name'] for d in matched],
            'match_count': len(matched)}


def edit_meal_rule(rule_id: str, patch: dict) -> dict:
    """Change a rule in place.

    Normalised exactly as `add_meal_rule` does — lowercased tags, floors on the
    numbers — because a rule edited into a different shape than one created is
    the sort of divergence that shows up months later as "it works if I delete
    it and add it again". Only keys actually supplied are touched, so the panel
    can send one field or all of them.
    """
    rule = storage.get_meal_rule(rule_id)
    if not rule:
        return {'status': 'error', 'message': 'No such rule.'}
    clean = {}
    if patch.get('name') is not None:
        clean['name'] = str(patch['name']).strip() or rule.get('name') or 'rule'
    if patch.get('kind') is not None and patch['kind'] in ('frequency_cap', 'batch_cycle', 'repeat_spacing'):
        clean['kind'] = patch['kind']
    if patch.get('is_enabled') is not None:
        clean['is_enabled'] = bool(patch['is_enabled'])
    if patch.get('tags') is not None:
        clean['tags'] = [str(t).strip().lower() for t in patch['tags'] if str(t).strip()]
    for key in ('dish_ids', 'types', 'side_types', 'sources', 'exclude_dish_ids'):
        if patch.get(key) is not None:
            clean[key] = [str(x) for x in patch[key]]
    if patch.get('max_servings') is not None:
        clean['max_servings'] = max(1, int(patch['max_servings']))
    if patch.get('window_days') is not None:
        clean['window_days'] = max(1, int(patch['window_days']))
    if patch.get('dwell_days') is not None:
        clean['dwell_days'] = max(1, int(patch['dwell_days']))
    if clean:
        storage.update_meal_rule(rule_id, clean)
    out = storage.get_meal_rule(rule_id)
    _cats = _category_names_by_id()
    matched = [d for d in storage.get_dishes() if rule_matches(out, d, _cats)]
    return {'status': 'success', 'rule': out,
            'matches': [d.get('short_name') or d['name'] for d in matched],
            'match_count': len(matched)}


def describe_meal_rule(rule: dict) -> str:
    """Plain words, so a family can audit what they told it."""
    what = []
    if rule.get('tags'):
        what.append('/'.join(rule['tags']))
    if rule.get('sources'):
        what.append('takeout' if 'ordered' in rule['sources']
                    else '/'.join(rule['sources']))
    if rule.get('types'):
        # `meal` is schema vocabulary; the family says "whole meals".
        what.append('/'.join('whole meals' if t == 'meal' else t
                             for t in rule['types']))
    if rule.get('dish_ids'):
        names = [(storage.get_dish(i) or {}).get('short_name')
                 or (storage.get_dish(i) or {}).get('name')
                 for i in rule['dish_ids']]
        what.append(', '.join(n for n in names if n))
    subject = ' '.join(what) or 'nothing yet'
    if rule.get('kind') == 'batch_cycle':
        return (f"{subject}: one at a time, about {rule.get('dwell_days', 3)} "
                f"days each, then the next")
    if rule.get('kind') == 'repeat_spacing':
        w = rule.get('window_days', 21)
        span = 'a week' if w == 7 else (f"{w // 7} weeks" if w % 7 == 0 else f"{w} days")
        return f"{subject}: no repeats — once served, not again for {span}"
    n, w = rule.get('max_servings', 1), rule.get('window_days', 7)
    every = 'a week' if w == 7 else ('a day' if w == 1 else f"{w} days")
    return f"{subject}: at most {n} in {every}"


def _category_names_by_id() -> dict:
    """Lowercased current name per DishCategory id, for tag-word matching."""
    return {c['id']: str(c.get('name') or '').strip().lower()
            for c in storage.get_dish_categories()}


def rule_matches(rule: dict, dish: dict, cat_names: dict = None) -> bool:
    """Selector clauses are ANDed; empty clauses are ignored.

    So `sources=['ordered']` alone means all takeout, while `tags=['beef']`
    with `types=['entree']` means beef mains only. Explicit `dish_ids` is the
    escape hatch for anything the tags do not capture cleanly — which is most
    households, since "meat" is not a field.

    A rule's tag words match the dish's free-form tags AND the names of the
    categories it belongs to — the family's own categories (M5) ARE their
    vocabulary, so "protein" in a rule must catch everything IN the protein
    category, not only dishes someone also happened to type a 'protein' tag
    onto. Matched by CURRENT name at eval time: renaming a category renames
    what the rule word means, and a rule orphaned by a rename shows amber
    ("matches nothing") in the panel rather than silently governing nobody.
    Callers looping many dishes pass `cat_names` (from
    `_category_names_by_id`) so the table is read once, not per dish.
    """
    # Exclusions win over every other clause, including an explicit dish list —
    # "not this one" is never something the family meant only conditionally.
    if dish.get('id') in (rule.get('exclude_dish_ids') or []):
        return False
    if rule.get('dish_ids') and dish.get('id') not in rule['dish_ids']:
        return False
    if rule.get('tags'):
        have = {str(t).strip().lower() for t in (dish.get('tags') or [])}
        if cat_names is None:
            cat_names = _category_names_by_id()
        have |= {cat_names[c] for c in (dish.get('category_ids') or [])
                 if c in cat_names}
        if not (have & {str(t).strip().lower() for t in rule['tags']}):
            return False
    if rule.get('types') and (dish.get('type') or '') not in rule['types']:
        return False
    if rule.get('side_types') and (dish.get('side_type') or '') not in rule['side_types']:
        return False
    if rule.get('sources') and str(dish.get('source') or 'prep') not in rule['sources']:
        return False
    # A rule with no clauses at all matches nothing, rather than everything —
    # an empty selector is a half-written rule, not a household-wide ban.
    return any(rule.get(k) for k in
               ('dish_ids', 'tags', 'types', 'side_types', 'sources'))


def _served_days(dish_ids: set, as_of: float, window_days: int,
                 served: dict, all_dishes: list) -> int:
    """How many days inside the window already carry one of these dishes.

    Counts the forward-simulation overlay exactly (M6 records every day the
    horizon has composed so far), plus at most ONE historical serving from
    `last_served_at`. That last part is a real limit and worth naming: the
    dish row remembers only its most recent serving, so a cap of "twice a
    week" cannot see a third helping from last Tuesday. For "once a week" —
    which is what families actually say, and both cases here — it is exact.
    """
    lo = as_of - window_days * 86400.0
    days = set()
    for did in dish_ids:
        ts = served.get(did)
        if ts and lo <= ts < as_of:
            days.add(int(ts // 86400))
    if not days:
        for d in all_dishes:
            if d.get('id') in dish_ids:
                ts = d.get('last_served_at') or 0
                if lo <= ts < as_of:
                    days.add(int(ts // 86400))
                    break
    return len(days)


def _leftover_coverage(as_of: float, served: dict, headcount: int,
                       runs: dict = None) -> dict:
    """dish id -> how strongly tonight is already covered by what was made.

    A dish that serves eight in a house of four covers ONE more night, so it
    earns the bonus on the night after it was cooked and nothing after that.
    The bonus decays with the nights already eaten so that a very big pot
    tapers off rather than owning the week, and it stays well below the +50 an
    explicit `batch_cycle` rule carries: the family saying "one pot of beans at
    a time" must outrank us inferring the same thing from a number.
    """
    if headcount <= 0:
        return {}
    out = {}
    for d in storage.get_dishes():
        last = max((served or {}).get(d['id'], 0) or 0,
                   d.get('last_served_at') or 0)
        if not last or last >= as_of:
            continue
        extra = leftover_nights(d, headcount)
        if not extra:
            continue
        nights = int((as_of - last) // 86400) or 1
        # The pot EMPTIES. Measuring only "when did we last eat it" made the
        # gap permanently one day, so a big batch was covered forever and took
        # every night of the week — the same mistake `batch_cycle` was written
        # to fix, which is why it counts servings rather than elapsed days.
        # `runs` is how many nights of this horizon have already eaten from it.
        eaten = (runs or {}).get(d['id'], 0)
        if nights <= extra and eaten <= extra:
            out[d['id']] = 20.0 / nights
    return out


def rule_context(as_of: float, served: dict, settings: dict = None,
                 runs: dict = None, planned: dict = None) -> dict:
    """Everything the rules decide ONCE per composed day.

    Batch cycles in particular must be resolved per day rather than per
    candidate: the question "which pot is open" has one answer, and asking it
    per dish would let two members of the same group both look eligible.

    `planned` is {dish_id -> stamps of PINNED nights across the horizon} from
    compose_week. A pinned night is a decision the family already made, and it
    binds in BOTH directions: with brisket locked for Tuesday, Monday proposing
    brisket makes the locked night the repeat — and the composer walks the days
    in order, so without this the earlier day literally cannot know. The
    `served` overlay only ever carries the days already walked past.
    """
    rules = storage.get_meal_rules()
    if not rules:
        return {'blocked': set(), 'forced': set(), 'rules': []}
    # Occasion dishes are invisible to ordinary rule ACCOUNTING, not merely
    # given rules of their own (occasions arc O0). Otherwise the Thanksgiving
    # turkey — which carries a `meat` tag like any other — burns the week's
    # "meat about once a week" cap and the family gets a baffling vegetarian
    # weekend, and a batch_cycle advances on a day that had no beans in it.
    # Excluding them from the member set does both directions at once: serving
    # one never counts, and being one never blocks.
    all_dishes = [d for d in storage.get_dishes()
                  if str(d.get('scope') or 'everyday') != 'occasion']
    blocked, forced = set(), set()
    cat_names = _category_names_by_id()

    for rule in rules:
        members = [d for d in all_dishes if rule_matches(rule, d, cat_names)]
        if not members:
            continue
        ids = {d['id'] for d in members}

        if rule.get('kind') == 'frequency_cap':
            window = max(1, int(rule.get('window_days') or 7))
            used = _served_days(ids, as_of, window, served, all_dishes)
            # Pinned nights AHEAD of this one spend the budget too. Counted as
            # distinct days, strictly inside the forward window — a night
            # exactly window_days out starts a fresh budget. (Two sparse
            # servings straddling tonight can over-count by sharing no single
            # window; that errs toward variety, which is what the cap is for.)
            used += len({int(s // 86400) for did in ids
                         for s in (planned or {}).get(did, ())
                         if 0 < s - as_of < window * 86400.0})
            if used >= max(1, int(rule.get('max_servings') or 1)):
                blocked |= ids

        elif rule.get('kind') == 'repeat_spacing':
            # Per-MEMBER cooldown, where frequency_cap spends a budget on the
            # SET: Tuesday's pizza is off the table for `window_days`, and
            # every other match is untouched. One rule covers a whole
            # category — the alternative was one frequency_cap per dish, and
            # every new takeout dish silently escaping until somebody
            # remembered to write its rule. `served` carries the days this
            # horizon has already composed, so a repeat is blocked inside the
            # plan being built, not just against history.
            window = max(1, int(rule.get('window_days') or 21)) * 86400.0
            for d in members:
                last = max(served.get(d['id'], 0), d.get('last_served_at') or 0)
                if last and (as_of - last) < window:
                    blocked.add(d['id'])
                # The cooldown radiates from a pinned night both ways — see
                # `planned` in the docstring. `s != as_of` spares the pinned
                # day itself; its own dishes are returned as-is, never
                # re-proposed against the rules.
                elif any(s != as_of and abs(s - as_of) < window
                         for s in (planned or {}).get(d['id'], ())):
                    blocked.add(d['id'])

        elif rule.get('kind') == 'batch_cycle':
            dwell = max(1, int(rule.get('dwell_days') or 3))

            def last_of(d):
                return max(served.get(d['id'], 0), d.get('last_served_at') or 0)

            recent = max(members, key=last_of)
            when = last_of(recent)
            # HOW LONG the pot has been open, not how long since it was last
            # eaten. Measuring the gap keeps a batch alive forever: it is eaten
            # every day, so "time since last served" is permanently one day and
            # the window slides indefinitely. A 14-day plan sat on black beans
            # for all 14 days before this was counted properly.
            run = int((runs or {}).get(recent['id'], 0))
            # A skipped night (takeout, someone else cooking) does not end a
            # batch — the pot is still in the fridge.
            still_open = bool(when) and (as_of - when) <= (dwell + 1) * 86400.0
            if still_open and run < dwell:
                blocked |= (ids - {recent['id']})
                forced.add(recent['id'])
            else:
                others = [d for d in members if d['id'] != recent['id']] or members
                nxt = min(others, key=last_of)
                blocked |= (ids - {nxt['id']})
                forced.add(nxt['id'])
                if runs is not None and runs.get(nxt['id']):
                    runs[nxt['id']] = 0      # a fresh pot starts a fresh count

    return {'blocked': blocked, 'forced': forced, 'rules': rules}


def _rules_ok(dish: dict, ctx: dict) -> bool:
    return dish.get('id') not in (ctx or {}).get('blocked', ())


def _pairing_ok(dish: dict, chosen: list) -> bool:
    """`only_with` is the reverse of `always_with`: this dish is never proposed
    on its own merits, only alongside a partner it names. A sauce that belongs
    to exactly one entree should not turn up next to salmon."""
    partners = dish.get('only_with') or []
    if not partners:
        return True
    have = {d['id'] for d in chosen}
    return any(p in have for p in partners)


def _rank(dish: dict, leftover_ids: set, affinity: set, dislike: set,
          as_of: float = None, served: dict = None, covered: dict = None) -> float:
    score = 0.0
    if dish['id'] in leftover_ids:
        score += 100.0                        # already made — obviously tonight
    tags = {str(t).strip().lower() for t in (dish.get('tags') or [])}
    if tags & dislike:
        score -= 2.0
    if affinity and (tags & affinity):
        score += 1.5                          # soft coherence, not a rule
    score -= {'easy': 0.0, 'normal': 0.3, 'project': 1.5}.get(
        str(dish.get('effort') or 'normal'), 0.3)
    last = dish.get('last_served_at') or 0
    # `served` carries the days ALREADY composed in this horizon. Without it a
    # week of plates is just the same ranking run seven times; with it, taking
    # a dish on Monday pushes it down the order for Tuesday exactly as really
    # serving it would.
    if served:
        last = max(last, served.get(dish['id'], 0))
    ref = as_of if as_of is not None else _now_ts()
    score += min(max(ref - last, 0.0) / 86400.0, 21) / 21.0
    # A pot big enough for a second night SHOULD come back tomorrow: that is
    # eating what was made, not repeating themselves, and it is exactly what a
    # family does without being asked. Deliberately smaller than an explicit
    # batch_cycle (+50) — the family stating "one pot of beans at a time" still
    # outranks us inferring it from a number — and it decays with the nights
    # already eaten so a huge pot does not colonise the week.
    if covered:
        score += covered.get(dish['id'], 0.0)
    return score


def compose_plate(date_str: str, plan: dict = None, settings: dict = None,
                  served: dict = None, runs: dict = None,
                  rejected: list = None, planned: dict = None) -> list:
    """Propose one day's dishes. Nothing is stored — this is the suggestion.

    Coherence is handled with a SOFT tag affinity to the entree rather than a
    modelled "goes with" relation: getting salmon and tortillas occasionally
    is a much smaller cost than making the family maintain a compatibility
    matrix, and swapping a chip is one tap.

    `served` is the forward-simulation overlay from compose_week: {dish_id ->
    when an earlier day in this horizon took it}. Absent, this behaves exactly
    as it always did for a single day.

    `rejected` is what this night has already been offered and turned down
    (Repropose), OLDEST FIRST. It is a heavy rank penalty rather than a filter,
    and it is ordered rather than a set, which is what makes a small repertoire
    rotate instead of dead-ending: a never-refused dish wins outright, and once
    everything has been refused the one turned down longest ago comes back
    first. A filter would either empty the night or need an exhaustion reset
    that cannot see which pool actually ran out.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    plan = plan or eating_plan(date_str, 'dinner')
    headcount = eaters_on(date_str, settings)
    avoid, dislike = _eater_diet(plan)
    leftovers = storage.get_leftovers(date_str)
    leftover_ids = set()
    for l in leftovers:
        leftover_ids.update(l.get('dish_ids') or [])
    as_of = _as_of_ts(date_str)
    # How this household eats, resolved once for the day (M11).
    ctx = rule_context(as_of, served or {}, settings, runs or {}, planned)
    # What an occasion's window opens up (O1) — eligibility, not selection.
    from services import occasions as _occ
    open_tags = _occ.dish_tags_for(date_str)
    # A guest's allergy binds exactly like a family member's, or the guest
    # list is decorative.
    g_avoid, g_dislike = _occ.diet_on(date_str)
    avoid = avoid | g_avoid
    dislike = dislike | g_dislike

    # Big enough to dominate every term in _rank (which tops out around 100 for
    # an already-made dish): "not this one" is the family speaking, not another
    # heuristic to be outweighed.
    refused_at = {d: i for i, d in enumerate(rejected or ())}

    def refusal(dish):
        i = refused_at.get(dish['id'])
        return 0.0 if i is None else -1000.0 * (i + 1)

    slots = [p['first'] for p in (plan.get('people') or []) if p.get('first')]
    binding = next((s for s in slots if s['modality'] in ('in_car', 'at_venue')), None)

    def pick(pool, affinity=frozenset(), exclude=()):
        # `chosen` is empty when the entree is picked, so an entree declaring
        # only_with can never lead a plate — which is right: a dish that only
        # exists alongside something else is not the something else.
        cands = [d for d in pool
                 if d['id'] not in exclude
                 and _dish_ok(d, avoid, binding, leftover_ids, open_tags)
                 and _pairing_ok(d, chosen)
                 and _rules_ok(d, ctx)]
        if not cands:
            return None
        return max(cands, key=lambda d: refusal(d)
                   + _rank(d, leftover_ids, affinity, dislike, as_of, served, covered))

    # Which dishes tonight is already covered by, because the pot was big
    # enough. Computed once per day, like the rule context, since the answer is
    # a property of the night rather than of each candidate.
    covered = _leftover_coverage(as_of, served, headcount, runs)

    chosen = []
    cats = storage.get_dish_categories()

    def pool_for(cid):
        return [d for d in storage.get_dishes()
                if (d.get('type') or 'dish') != 'meal'
                and cid in (d.get('category_ids') or [])]

    # A `meal` dish is the whole plate. It competes on rank against the LEAD
    # block — the first category the family said a plate must have, which is
    # the protein in every household that has told us about one. That keeps
    # one-pot meals in rotation without letting them take every night.
    lead = next((c for c in cats if int(c.get('min_per_plate') or 0) > 0), None)
    best_meal = pick(storage.get_dishes_by_type('meal'))
    best_lead = pick(pool_for(lead['id'])) if lead else None
    # Strictly greater, not >=: on a tie the composed path wins. Everything
    # ties while nothing has been served yet, and a >= here let one-dish meals
    # take every plate on a fresh repertoire.
    use_meal = best_meal and (
        not best_lead
        or _rank(best_meal, leftover_ids, frozenset(), dislike, as_of, served, covered)
        > _rank(best_lead, leftover_ids, frozenset(), dislike, as_of, served, covered))

    def attach(seed, acc):
        """Pull in whatever this dish ALWAYS brings.

        Hard filters still win: a pairing is the family saying "these go
        together", not a licence to put an allergen on the plate. Cycles are
        guarded because brisket->beans and beans->brisket is a thing a family
        can easily say.
        """
        queue, seen = [seed], {seed['id']}
        while queue:
            cur = queue.pop(0)
            for did in (cur.get('always_with') or []):
                if did in seen or any(d['id'] == did for d in acc):
                    continue
                seen.add(did)
                mate = storage.get_dish(did)
                if not mate or not mate.get('is_active', True):
                    continue
                if not _dish_ok(mate, avoid, binding, leftover_ids, open_tags):
                    continue          # allergy/portability still governs
                if not _rules_ok(mate, ctx):
                    continue          # nor does a pairing bust a frequency cap
                acc.append(mate)
                queue.append(mate)
        return acc

    # dish id -> the ONE category slot it is filling tonight.
    assigned = {}

    def fill_categories(blocks, affinity=frozenset()):
        """Fill each block to its minimum, in the family's own order.

        A dish fills AT MOST ONE slot per plate — it is in `chosen` after the
        first, so a dish tagged protein AND starch answers whichever slot is
        still open tonight without ever counting twice. That one rule is what
        keeps multi-category dishes from making the family do arithmetic.

        Order matters and is the family's: with protein first, beans answer the
        protein slot and rice takes the starch. Within a block, a dish that
        belongs to FEWER categories wins ties, which keeps the versatile ones
        available for the slots still to be filled.
        """
        def claim_existing():
            """Assign whatever is already on the plate — the lead dish, a
            pairing, a leftover — to ONE block each.

            Counting a dish against every category it lists was the bug this
            replaces: black beans (protein AND starch) filled the protein slot
            and silently satisfied the starch block too, so rice never arrived.
            Assignment walks the family's order and takes the first block with
            room, which is also why they put protein first.
            """
            for d in chosen:
                if d['id'] in assigned:
                    continue
                for b in blocks:
                    bid = b['id']
                    if bid not in (d.get('category_ids') or []):
                        continue
                    cap = max(0, int(b.get('max_per_plate') or 0))
                    if len([1 for v in assigned.values() if v == bid]) < cap:
                        assigned[d['id']] = bid
                        break

        for block in blocks:
            cid = block['id']
            lo = max(0, int(block.get('min_per_plate') or 0))
            hi = max(lo, int(block.get('max_per_plate') or 0))
            claim_existing()
            # Whatever arrived already counts against the ONE block it was
            # assigned to. A plate wanting two starches that turns up with
            # beans and fries is FULL; a plate that got beans as its protein
            # still wants a starch.
            have = len([1 for v in assigned.values() if v == cid])
            for _ in range(max(0, min(lo, hi) - have)):
                taken_ids = {d['id'] for d in chosen}
                cands = [d for d in pool_for(cid)
                         if d['id'] not in taken_ids
                         and _dish_ok(d, avoid, binding, leftover_ids, open_tags)
                         and _pairing_ok(d, chosen)
                         and _rules_ok(d, ctx)]
                if not cands:
                    break                 # minimums bend; the plate says so
                got = max(cands, key=lambda d: (
                    refusal(d)
                    + _rank(d, leftover_ids, affinity, dislike, as_of, served, covered)
                    # Specialists first, so the dish that can only be a
                    # vegetable is not spent on the starch slot.
                    + (1.0 if len(d.get('category_ids') or []) <= 1 else 0.0)
                    # The open pot outranks variety: a batch cycle is the family
                    # saying they WILL be eating this for a few days.
                    + (50.0 if d['id'] in ctx.get('forced', ()) else 0.0)))
                chosen.append(got)
                assigned[got['id']] = cid     # this is the slot it just filled
                attach(got, chosen)

    if use_meal:
        chosen.append(best_meal)
        attach(best_meal, chosen)
        # A whole meal satisfies the composition. Only the blocks that opted in
        # still apply — spaghetti night still ends with something sweet, and
        # the family says which block that is rather than the code assuming
        # "dessert" is a word they use.
        fill_categories([c for c in cats if c.get('with_complete_meal')],
                        affinity={str(t).strip().lower()
                                  for t in (best_meal.get('tags') or [])})
    else:
        if best_lead:
            chosen.append(best_lead)
            attach(best_lead, chosen)
        affinity = {str(t).strip().lower()
                    for t in ((best_lead or {}).get('tags') or [])}
        fill_categories(cats, affinity)
    return chosen


def get_or_compose_plate(date_str: str, plan: dict = None,
                         settings: dict = None) -> dict:
    """Tonight's plate: what the family edited, or a fresh proposal.

    An edited plate is never re-proposed under them — the same hold-still rule
    that swapping a chip already followed.
    """
    saved = storage.get_plate(date_str)
    if saved and saved.get('edited'):
        dishes = storage.get_dishes_by_ids([i['dish_id'] for i in saved.get('items') or []])
        by_id = {d['id']: d for d in dishes}
        items = [by_id[i['dish_id']] for i in (saved.get('items') or [])
                 if i['dish_id'] in by_id]
        return {'date': date_str, 'dishes': items, 'edited': True}
    return {'date': date_str,
            'dishes': compose_plate(date_str, plan, settings), 'edited': False}


def showing_plate(date_str: str, plan: dict = None,
                  settings: dict = None) -> dict:
    """get_or_compose_plate, but answering with the dinner the family is
    LOOKING at.

    Every surface that says "here is this night's dinner" — the Tonight card,
    the voice answer, the prep nudges, the + List buy — must give the same
    answer as the week strip, because to the family they are one question.
    get_or_compose_plate composes the date in isolation, which ignores both
    the span threading and the night's Repropose refusals; that is how the
    Tonight card kept proposing a dinner the family had just refused, directly
    above a strip row that had moved on.
    """
    saved = storage.get_plate(date_str)
    if saved and saved.get('edited'):
        return get_or_compose_plate(date_str, plan, settings)
    return {'date': date_str, 'edited': False,
            'dishes': dishes_showing_on(date_str, plan, settings)}


def dishes_showing_on(date_str: str, plan: dict = None,
                      settings: dict = None) -> list:
    """What this night is SHOWING — not what it would get if it were the only
    night in the world.

    `compose_plate` ranks one date in isolation. `compose_week` composes the
    span IN ORDER, threading what each earlier night took, and that threading
    is the whole reason a week is not the same top-ranked entree seven times.
    So the two disagree for every night except the first, and anything that
    FREEZES a night — locking it, pinning it, adding or dropping a chip — has
    to freeze the answer the family is looking at.

    Without this, locking Thursday wrote Thursday's dishes as if the week
    started there, which is the plate the FIRST night of the strip was already
    showing: click the padlock and the dinner changed to one further up the
    page. It was not a display bug. `set_plate_lock` persists what it locks, so
    the wrong dinner was genuinely stored, which is why the night then offered
    a Reset.

    A date outside both spans (a birthday three weeks out, reached through
    "plan a specific night") has no week context to be read in, and the
    standalone composition is exactly what that picker showed. That is the one
    case where isolation is the right answer.
    """
    saved = storage.get_plate(date_str)
    if saved and saved.get('edited'):
        return get_or_compose_plate(date_str, plan, settings)['dishes']
    win = plan_window(settings)
    for span in win.get('spans') or []:
        if not span.get('days'):
            continue
        dates = week_dates(span['start'], span['days'])
        if date_str in dates:
            # The WHOLE span, not the prefix up to this date. Composing only
            # the first N days used to give the same answer — the walk was
            # forward-only — but pinned nights now bind in both directions
            # (v2.160.0), so a prefix cannot see a lock that sits LATER in
            # the week. Caught on video: with brisket locked for Tuesday,
            # Monday's strip row correctly showed chicken — and dropping one
            # chip from it pinned brisket, because the prefix compose behind
            # this function was blind to the lock and "froze" a dinner the
            # family had never been shown.
            week = compose_week(span['start'], span['days'], settings)
            idx = dates.index(date_str)
            return week[idx]['dishes'] if idx < len(week) else []
    return get_or_compose_plate(date_str, plan, settings)['dishes']


def _persist_plate(date_str: str, dishes: list, reconcile: bool = True) -> dict:
    from models.schemas import Plate, PlateItem
    # Prune relative to TODAY, never to the plate being written. Pruning by the
    # saved date was harmless while only tonight existed; with a week of plans
    # in the table, pinning Thursday would have deleted Monday through
    # Wednesday on the way past.
    storage.prune_plates(_history_cutoff())
    # Carry the lock and its note forward. This rebuilds the record from
    # scratch, so without this an ordinary edit — or the week approval, which
    # re-persists every night — would silently unlock Mom's birthday and drop
    # the reason it was locked.
    prior = storage.get_plate(date_str) or {}
    rec = Plate(date=date_str, edited=True,
                locked=bool(prior.get('locked')),
                note=prior.get('note'),
                rejected=list(prior.get('rejected') or []),
                # Hosting survives an edit for exactly the reason the lock does:
                # swapping a side on the night twelve people are coming must not
                # quietly reset it to a family of four.
                serving_for=prior.get('serving_for'),
                cooks=prior.get('cooks'),
                items=[PlateItem(dish_id=d['id']) for d in dishes]).model_dump()
    storage.save_plate(rec)
    # Every change of mind about a night runs through here, so this is the one
    # place the list has to be told. A dish dropped from a plate whose
    # ingredients were already bought leaves them stranded otherwise — the
    # family's own complaint, and the reason claims exist at all.
    #
    # `reconcile=False` is for the callers that write SEVERAL nights as one
    # act. Moving a dinner from Thursday to Friday is two writes, and between
    # them the dish is planned nowhere — reconciling in that gap took the
    # ingredients off the list for a dinner the family had merely dragged. A
    # batch writes every night first and reconciles once at the end.
    if reconcile:
        reconcile_claims()
    return rec


def set_plate_lock(date_str: str, locked: bool = True, note: str = None,
                   dish_ids: list = None) -> dict:
    """Spoken for: "steak on Monday, it's Mom's birthday".

    Locking pins whatever is on the plate, so it can be used either after
    choosing the dishes or on its own to hold a night that is already right.
    An empty locked plate is a legitimate state — it is how "someone is
    bringing us dinner" is said.
    """
    from models.schemas import Plate, PlateItem
    if dish_ids is None:
        # What the night is SHOWING. Composing it standalone here is what made
        # the padlock change the dinner — see dishes_showing_on.
        cur = dishes_showing_on(date_str)
    else:
        by_id = {d['id']: d for d in storage.get_dishes_by_ids(dish_ids)}
        cur = [by_id[i] for i in dish_ids if i in by_id]
    prior = storage.get_plate(date_str) or {}
    storage.prune_plates(_history_cutoff())
    rec = Plate(date=date_str, edited=True, locked=bool(locked),
                note=(note if note is not None else prior.get('note')) or None,
                rejected=list(prior.get('rejected') or []),
                serving_for=prior.get('serving_for'), cooks=prior.get('cooks'),
                items=[PlateItem(dish_id=d['id']) for d in cur]).model_dump()
    storage.save_plate(rec)
    return {'status': 'success', 'date': date_str, 'locked': bool(locked),
            'note': rec['note'], 'dishes': cur}


def set_plate_hosting(date_str: str, serving_for: int = None,
                      cooks: int = None) -> dict:
    """"We're having twelve people on Saturday, and two of us are cooking."

    Deliberately does NOT set `edited`. Saying how many are coming is a fact
    about the evening, not a decision about what to eat — pinning the night on
    the strength of it would freeze whatever happened to be proposed at the
    moment somebody answered the door question, which is the opposite of
    helpful three weeks out.

    Passing 0 or a blank clears the value back to an ordinary night.
    """
    from models.schemas import Plate, PlateItem
    prior = storage.get_plate(date_str) or {}
    storage.prune_plates(_history_cutoff())

    def _n(given, existing):
        if given is None:
            return existing
        try:
            v = int(given)
        except (TypeError, ValueError):
            return existing
        return v if v > 0 else None

    rec = Plate(date=date_str,
                edited=bool(prior.get('edited')),
                locked=bool(prior.get('locked')),
                note=prior.get('note'),
                rejected=list(prior.get('rejected') or []),
                serving_for=_n(serving_for, prior.get('serving_for')),
                cooks=_n(cooks, prior.get('cooks')),
                items=[PlateItem(**i) for i in (prior.get('items') or [])]
                ).model_dump()
    storage.save_plate(rec)
    dishes = get_or_compose_plate(date_str)['dishes']
    totals = plate_totals(dishes, date_str, plate=rec)
    return {'status': 'success', 'date': date_str,
            'serving_for': rec['serving_for'], 'cooks': rec['cooks'],
            'hands_on_mins': totals.get('prep_ahead_mins', 0) + totals.get('finish_mins', 0),
            'unattended_mins': totals.get('unattended_mins'),
            'oven_conflicts': totals.get('oven_conflicts')}


def plate_run_sheet(date_str: str = None, serve_at: str = None,
                    settings: dict = None) -> dict:
    """Clock times for a night's cooking, working back from when people eat.

    The serve time is the household's own dinner sitting when one can be
    derived from the solved day — the whole reason this app can do a run sheet
    at all is that it already knows when this family gets to sit down. Falls
    back to the start of the dinner window, never to a guess.
    """
    day = date_str or _today_iso()
    settings = settings if settings is not None else (storage.get_settings() or {})
    saved = storage.get_plate(day) or {}
    dishes = get_or_compose_plate(day)['dishes']
    if not serve_at:
        plan = eating_plan(day, 'dinner', settings=settings)
        # The EARLIEST sitting, not the latest: on a split evening the food has
        # to be ready when the first person eats, and cooking to the last one
        # is how the kids in the car get nothing.
        firsts = sorted(p['first']['start'] for p in (plan.get('people') or [])
                        if p.get('first') and p['first'].get('start'))
        serve_at = (firsts[0][11:16] if firsts
                    else MEAL_WINDOWS['dinner'][0].strftime('%H:%M'))
    sheet = kitchen.run_sheet(dishes, serve_at, settings,
                              saved.get('cooks'), saved.get('serving_for'))
    sheet['date'] = day
    sheet['dish_count'] = len(dishes)
    return sheet


def grocery_settings(settings: dict = None) -> tuple:
    """The shop day and how early to ask. An UNSET shop day is derived from the
    family's actual free time rather than guessed — the first cut hardcoded
    Saturday, which is exactly the day a family with weekend activities has
    least room for a 90-minute trip."""
    settings = settings if settings is not None else (storage.get_settings() or {})
    raw = settings.get('grocery_weekday')
    if raw is None or raw == '':
        gw = suggest_grocery_weekday(settings).get('weekday')
        gw = 5 if gw is None else gw     # nothing to judge from yet
    else:
        try:
            gw = max(0, min(6, int(raw)))
        except (TypeError, ValueError):
            gw = 5
    try:
        lead = max(0, min(6, int(settings.get('grocery_plan_lead_days', 2))))
    except (TypeError, ValueError):
        lead = 2
    return gw, lead


SHOP_TRIP_MINS = 90          # a real grocery run, not a dash for milk


def grocery_day_candidates(settings: dict = None, today: datetime.date = None,
                           weeks: int = 3, need_mins: int = None) -> list:
    """Which weekday actually has room for a shopping trip, from the schedule.

    Ranked by the WORST occurrence in the horizon, not the average: a standing
    shop day has to work most weeks, and a weekday that is wide open twice and
    impossible once is worse than one that is merely adequate every time.

    Uses `member_spans` — the same free-time primitive the cook window is built
    from — restricted to at_home spans, because a gap spent parked at a game is
    not a gap you can buy groceries in.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    need = need_mins or SHOP_TRIP_MINS
    today = today or datetime.date.today()
    sched = storage.get_cached_schedule() or {}
    adults = [m for m in storage.get_all_members()
              if m.get('role') in ('parent', 'adult') and not m.get('system')]
    if not adults or not sched:
        return []
    drivers_by_event = _driver_member_ids(sched)

    by_weekday = {}
    for i in range(weeks * 7):
        day = today + datetime.timedelta(days=i)
        best, who = 0, None
        for m in adults:
            for s in member_spans(m, day.isoformat(), sched, settings, drivers_by_event):
                if s['modality'] != 'at_home':
                    continue
                mins = int((s['end'] - s['start']).total_seconds() / 60.0)
                if mins > best:
                    best, who = mins, m.get('name')
        by_weekday.setdefault(day.weekday(), []).append({'date': day.isoformat(),
                                                         'free_mins': best, 'who': who})
    out = []
    for wd, occs in by_weekday.items():
        mins = [o['free_mins'] for o in occs]
        out.append({
            'weekday': wd,
            'weekday_name': ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                             'Friday', 'Saturday', 'Sunday'][wd],
            'worst_mins': min(mins),
            'best_mins': max(mins),
            'typical_mins': sorted(mins)[len(mins) // 2],
            'fits': min(mins) >= need,
            'who': next((o['who'] for o in occs if o['free_mins'] == max(mins)), None),
            'occurrences': occs,
        })
    out.sort(key=lambda c: (-c['worst_mins'], -c['typical_mins'], c['weekday']))
    return out


def suggest_grocery_weekday(settings: dict = None, today: datetime.date = None) -> dict:
    """The recommended shop day plus WHY, so the choice is arguable.

    Cached for a day: this walks every adult's spans over three weeks and is
    called from plan_window, which runs on every week read and every sweep.
    """
    key = 'grocery_day_suggestion'
    today = today or datetime.date.today()
    cached = storage.get_app_state(key) or {}
    if cached.get('computed_on') == today.isoformat():
        return cached
    cands = grocery_day_candidates(settings, today)
    if not cands:
        res = {'computed_on': today.isoformat(), 'weekday': None,
               'reason': 'no schedule to judge from yet', 'candidates': []}
    else:
        top = cands[0]
        worst_h = round(top['worst_mins'] / 60.0, 1)
        res = {'computed_on': today.isoformat(), 'weekday': top['weekday'],
               'weekday_name': top['weekday_name'],
               'worst_mins': top['worst_mins'], 'fits': top['fits'],
               'reason': (f"{top['weekday_name']}s have at least {worst_h}h free "
                          f"every week in the next three"
                          if top['fits'] else
                          f"nothing clears {SHOP_TRIP_MINS} min every week — "
                          f"{top['weekday_name']}s come closest at {worst_h}h"),
               'candidates': [{k: v for k, v in c.items() if k != 'occurrences'}
                              for c in cands]}
    storage.set_app_state(key, res)
    return res


def next_grocery_date(today: datetime.date = None, weekday: int = 5) -> datetime.date:
    today = today or datetime.date.today()
    return today + datetime.timedelta(days=(weekday - today.weekday()) % 7)


def shop_date(settings: dict = None, today: datetime.date = None,
              list_id: str = None) -> tuple:
    """The next shopping trip, and where that answer came from.

    Three sources, best first:
      `scheduled` — the solver actually placed the bound errand this week. This
        is a decision made against the real week, with drives and detour
        accounted for, and it beats any weekday rule.
      `errand`    — a trip exists but has not been placed yet; use its allowed
        weekday if it names one.
      `weekday`   — no trip exists. Fall back to the configured or derived day.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    today = today or datetime.date.today()
    gw, _ = grocery_settings(settings)
    try:
        from services import shopping as _shop
        lid = list_id or (storage.ensure_default_shopping_list() or {}).get('id')
        nxt = _shop.next_scheduled_shop(lid)
    except Exception:
        nxt = None
    if nxt and nxt.get('scheduled'):
        when = datetime.date.fromisoformat(nxt['date'])
        if when >= today:
            return when, 'scheduled', nxt
    if nxt and nxt.get('errand'):
        days = nxt['errand'].get('valid_days_of_week') or []
        if days:
            return next_grocery_date(today, int(days[0])), 'errand', nxt
    return next_grocery_date(today, gw), 'weekday', nxt


def grocery_cadence(settings: dict = None) -> int:
    """How many nights one shop has to cover. Seven for most families, which is
    why it was hardcoded — but a household that shops every ten days had three
    nights a cycle that nothing ever bought for, and the number changes nothing
    about how any of this works."""
    settings = settings if settings is not None else (storage.get_settings() or {})
    try:
        return max(1, min(21, int(settings.get('grocery_cadence_days', 7))))
    except (TypeError, ValueError):
        return 7


def plan_window(settings: dict = None, today: datetime.date = None) -> dict:
    """The two spans a family is holding at once, and which one is being bought.

    This used to be one span with a mode: inside the lead window you saw the
    coming shop's week, outside it you saw the dwindling tail of the span
    already bought for. Two things were wrong with that, and both were reported
    from the kitchen. The plan for the NEXT shop only existed for the two days
    before the trip, so an idea that landed on a Monday ("lasagna next week")
    had nowhere to go and the list could not accumulate against the next run
    the way a real list does. And in planning mode the window STARTED on the
    shop date, so the last nights before the trip belonged to neither span and
    vanished off the page entirely.

    So: both, always. `current` is what the last shop bought for, running out
    at the trip. `next` is what the coming trip has to buy for. The current
    span is settled rather than frozen — a meeting lands, tonight's dinner gets
    punted, everything shifts, and a night that slides across the boundary
    arrives already paid for. That resolves itself in the claims (see
    `reconcile_claims`) instead of needing a rule.

    `start`/`days`/`mode` are kept pointing at the span being BOUGHT FOR, which
    is what every existing caller meant by them.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    _, lead = grocery_settings(settings)
    cadence = grocery_cadence(settings)
    today = today or datetime.date.today()
    nxt, source, detail = shop_date(settings, today)
    until = (nxt - today).days
    base = {'grocery_date': nxt.isoformat(), 'days_until_shop': until,
            'shop_source': source, 'cadence_days': cadence,
            'shop_time_label': (detail or {}).get('time_label') if source == 'scheduled' else None,
            'has_errand': bool((detail or {}).get('errand'))}
    # The run after the coming one — what a night beyond the next span is
    # bought on, and the horizon past which nothing is proposed at all.
    after = (nxt + datetime.timedelta(days=cadence)).isoformat()
    spans = [
        # `days: until` and not until+1: the shop day itself opens the next
        # span. A trip in the morning feeds that night.
        {'key': 'current', 'start': today.isoformat(), 'days': max(0, until),
         'label': 'Already bought for', 'buy_on': None, 'settled': True},
        {'key': 'next', 'start': nxt.isoformat(), 'days': cadence,
         'label': 'Shopping for', 'buy_on': nxt.isoformat(), 'settled': False},
    ]
    return {**base, 'spans': spans, 'next_shop_after': after,
            'start': nxt.isoformat(), 'days': cadence,
            'mode': 'planning' if until <= lead else 'current'}


def buy_on_for(date_str: str, settings: dict = None,
               today: datetime.date = None) -> str:
    """Which shop run has to buy for a given night.

    The run BEFORE the night, not the next one on the calendar — that is what
    "buying for a span" means. A night that falls before the next run is a
    TOP-UP: the plan changed after the shopping was done, and whatever it needs
    has to come from the next time somebody is in a store rather than from
    Saturday. That is the one case where an item is not for the standing run,
    and it is exactly the case that must not drag the rest of the list along
    with it to the corner shop.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    today = today or datetime.date.today()
    nxt, _, _ = shop_date(settings, today)
    cadence = grocery_cadence(settings)
    try:
        night = datetime.date.fromisoformat(str(date_str))
    except (TypeError, ValueError):
        return nxt.isoformat()
    if night < nxt:
        return today.isoformat()
    return (nxt + datetime.timedelta(
        days=((night - nxt).days // cadence) * cadence)).isoformat()


def week_dates(start_date: str = None, days: int = 7) -> list:
    try:
        start = datetime.date.fromisoformat(str(start_date)) if start_date \
            else datetime.date.today()
    except (TypeError, ValueError):
        start = datetime.date.today()
    days = max(1, min(21, int(days or 7)))
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(days)]


def compose_week(start_date: str = None, days: int = 7,
                 settings: dict = None) -> list:
    """The days ahead, composed in order so each one knows what the ones
    before it took.

    Deciding dinner and buying for it is the load — and neither is possible on
    the day. The horizon is the whole point; a week of independently-ranked
    plates would just be the same top-ranked entree seven times.

    A day the family has touched is PINNED and returned as-is (the hold-still
    rule that swapping a chip already followed). An untouched day stays fluid
    and recomposes as the schedule moves under it, which is a feature: Thursday
    turning into a 20-minute night should change what Thursday proposes.
    Pinned days still feed the rotation, or the plan would repeat around them.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    sched = storage.get_cached_schedule() or {}   # read once, not once per day
    # `runs` counts how many days a batch has been open, which is what a
    # batch_cycle needs; `served` only ever holds the most recent stamp.
    served, runs, out = {}, {}, []
    dates = week_dates(start_date, days)
    plates = {ds: storage.get_plate(ds) for ds in dates}
    # Every pinned night in the span, gathered BEFORE the walk. The walk goes
    # in order, so an overlay fed day-by-day can never tell Monday what the
    # family locked in for Tuesday — and a no-repeats rule that only looks
    # backward proposes the very dish a locked night makes a repeat of.
    planned = {}
    for ds, saved in plates.items():
        if saved and saved.get('edited'):
            for it in saved.get('items') or []:
                if it.get('dish_id'):
                    planned.setdefault(it['dish_id'], set()).add(_as_of_ts(ds))
    for date_str in dates:
        plan = eating_plan(date_str, 'dinner', sched=sched, settings=settings)
        saved = plates[date_str]
        pinned = bool(saved and saved.get('edited'))
        locked = bool(saved and saved.get('locked'))
        note = (saved or {}).get('note')
        if pinned:
            by_id = {d['id']: d for d in storage.get_dishes_by_ids(
                [i['dish_id'] for i in saved.get('items') or []])}
            dishes = [by_id[i['dish_id']] for i in (saved.get('items') or [])
                      if i['dish_id'] in by_id]
        else:
            dishes = compose_plate(date_str, plan, settings, served=served,
                                   runs=runs,
                                   rejected=(saved or {}).get('rejected'),
                                   planned=planned)
        stamp = _as_of_ts(date_str)
        # Deliberately NOT zeroed on a night the dish is skipped: one takeout
        # evening does not empty the pot, and zeroing there stretched a 3-day
        # batch across 5 calendar days. `still_open` ends an abandoned batch.
        for d in dishes:
            served[d['id']] = stamp
            runs[d['id']] = runs.get(d['id'], 0) + 1
        totals = plate_totals(dishes, date_str, settings, plate=saved or {})
        out.append({
            'date': date_str,
            'weekday': datetime.date.fromisoformat(date_str).strftime('%a'),
            'dishes': with_chip_labels(dishes),
            'pinned': pinned, 'locked': locked, 'note': note,
            'cook_window_mins': plan.get('cook_window_mins'),
            'cook_window_who': plan.get('cook_window_who'),
            # A cook window of 0 is ambiguous on its own: it is what an
            # unsolved day reports AND what a genuinely impossible evening
            # reports. This says whether anyone who COULD cook was even
            # considered, so the board can tell "we don't know" from "there is
            # no time" — the second being a first-class M2 finding.
            'has_cook': any(p.get('role') in _COOKING_ROLES
                            for p in (plan.get('people') or [])),
            'no_slot': [p.get('name') for p in (plan.get('no_slot') or [])],
            'away': [p.get('name') for p in (plan.get('away') or [])],
            'prep_ahead_mins': totals.get('prep_ahead_mins'),
            'finish_mins': totals.get('finish_mins'),
            'unattended_mins': totals.get('unattended_mins'),
            'oven_conflicts': totals.get('oven_conflicts'),
            'serving_for': totals.get('serving_for'),
            'cooks': totals.get('cooks'),
            'leftover_dish_ids': totals.get('leftover_dish_ids'),
        })
    return out


def repropose_week(start_date: str = None, days: int = 7) -> list:
    """"Not this — show me something else." The whole span, minus locked nights.

    The button existed before this and did nothing, which took some working
    out. It reset every PINNED night and reloaded — but the composer is
    deterministic, so an untouched night recomposes to exactly what was already
    on it, and an untouched night is the normal case. Pressing Repropose on a
    week nobody had edited was guaranteed to return the same week. It only ever
    worked as an undo for edits.

    What makes it move is remembering the refusal: every dish currently on an
    unlocked night is written to that night's `rejected` list, so the next
    composition steps past it. Rejection rather than randomness, because these
    nights recompose on every page load — a random composer would deal the
    family a different week every fifteen minutes.

    Locked nights are untouched, including their rejections: a locked night is
    not being proposed at all, so there is nothing to refuse.
    """
    week = compose_week(start_date, days)
    storage.prune_plates(_history_cutoff())
    for day in week:
        if not day.get('locked'):
            _refuse(day['date'], [d['id'] for d in day['dishes']])
    # "Not this" is a change of mind about the whole span, so anything bought
    # for a night that has just been refused comes back off — unless it is
    # already in the cart, which reconcile leaves alone.
    reconcile_claims()
    return compose_week(start_date, days)


def served_history(days: int = 21, before: str = None) -> list:
    """The nights already eaten, newest first.

    Plates ARE the record — there is no second table, because a second source
    of truth for "what was on Tuesday" is how the two disagree. A night appears
    here once it has been pinned, which the week approval does for every night
    it covers, so the ordinary flow fills this in on its own. A night nobody
    ever touched or approved leaves no trace, and that is honest: the app does
    not know what was actually eaten, only what was agreed.
    """
    end = before or _today_iso()
    start = (datetime.date.fromisoformat(end)
             - datetime.timedelta(days=max(1, days))).isoformat()
    out = []
    for p in storage.get_plates_between(start, end):
        if (p.get('date') or '') >= end:
            continue                      # today is not yet history
        ids = [i['dish_id'] for i in (p.get('items') or [])]
        if not ids:
            continue                      # a refusal record, not a dinner
        by_id = {d['id']: d for d in storage.get_dishes_by_ids(ids)}
        dishes = [by_id[i] for i in ids if i in by_id]
        if not dishes:
            continue
        out.append({
            'date': p['date'],
            'weekday': datetime.date.fromisoformat(p['date']).strftime('%a'),
            'dishes': [{'id': d['id'], 'name': d['name'],
                        'short_name': d.get('short_name'),
                        'image_url': d.get('image_url')} for d in dishes],
            'headline': (dishes[0].get('short_name') or dishes[0]['name']),
            'note': p.get('note'),
        })
    out.reverse()
    return out


def arrange_week(days: list) -> dict:
    """Write a whole arrangement of nights at once.

    One primitive under two gestures, because they are the same operation: a
    drag that swaps Tuesday and Thursday, and "we have this again tomorrow,
    push the rest back", both end as "these dates now hold these dishes".
    Doing it in one write also means the week never renders a half-applied
    order.

    A LOCKED night is refused rather than silently skipped: it is somebody's
    birthday dinner, and a reorder that quietly moved it — or quietly didn't —
    is worse than being told. Past dates are refused for the same reason; the
    record of what was eaten is not editable by a drag.
    """
    today = _today_iso()
    written, refused = [], []
    for day in days or []:
        date_str = (day or {}).get('date')
        if not date_str:
            continue
        if date_str < today:
            refused.append({'date': date_str, 'reason': 'past'})
            continue
        prior = storage.get_plate(date_str) or {}
        if prior.get('locked'):
            refused.append({'date': date_str, 'reason': 'locked'})
            continue
        ids = [i for i in (day.get('dish_ids') or []) if i]
        dishes = storage.get_dishes_by_ids(ids)
        by_id = {d['id']: d for d in dishes}
        # One act, several nights — see _persist_plate. Reconciling between the
        # night a dinner left and the night it arrived on unbought it.
        _persist_plate(date_str, [by_id[i] for i in ids if i in by_id],
                       reconcile=False)
        written.append(date_str)
    if written:
        reconcile_claims()
    return {'status': 'success', 'written': written, 'refused': refused}


def _refuse(date_str: str, dish_ids: list) -> dict:
    """Record a night's refusals, dropping any edit that was on it.

    A bulk repropose is entitled to sweep an edit away (that is the whole
    `edited` vs `locked` distinction), so this deliberately writes
    `edited=False` and no items — the night goes back to being fluid.

    A dish refused AGAIN moves to the back of the queue rather than staying
    where it was, which is what keeps the rotation turning: the order is
    oldest-refusal-first, and compose_plate brings those back first.
    """
    from models.schemas import Plate
    prior = storage.get_plate(date_str) or {}
    if prior.get('locked'):
        return prior
    fresh = [i for i in dish_ids or []]
    keep = [i for i in (prior.get('rejected') or []) if i not in fresh] + fresh
    if not keep:
        storage.delete_plate(date_str)
        return {}
    rec = Plate(date=date_str, edited=False, locked=False,
                note=prior.get('note'), rejected=keep, items=[]).model_dump()
    storage.save_plate(rec)
    return rec


def approve_week(start_date: str = None, days: int = 7, list_id: str = None,
                 added_by: str = None) -> dict:
    """"How does this look?" — yes. Pin every day and buy for all of them.

    This is the whole point of the arc: the family's planning session collapses
    into one approval, and the list for the shop is a consequence rather than a
    second chore. Pinning is not decoration — once the ingredients are bought,
    a day that quietly recomposed itself would have spent their money on a
    dinner they are no longer having.
    """
    week = compose_week(start_date, days)
    lst_id = list_id or storage.ensure_default_shopping_list()['id']
    added, skipped, pinned = [], [], []
    # Pin the WHOLE span before buying a thing. Persisting and provisioning day
    # by day meant each night's write reconciled the list against a plan that
    # was still half-written — Thursday's chicken looked unwanted while
    # Thursday was still two iterations away from being pinned.
    for day in week:
        _persist_plate(day['date'], day['dishes'], reconcile=False)
        pinned.append(day['date'])
    reconcile_claims()
    for day in week:
        res = dishes_to_shopping(day['dishes'], lst_id, added_by=added_by,
                                 skip_dish_ids=day.get('leftover_dish_ids'),
                                 date_str=day['date'],
                                 buy_on=buy_on_for(day['date']))
        added.extend(res['added'])
        # The day rides along on every skip: "already on the list" is the
        # normal case across a week (chicken on Monday and Thursday buys once)
        # and it is only legible if you can see which day it came from.
        # dishes_to_shopping already grouped WITHIN the day; flatten back to
        # one record per (ingredient, dish, night) so the cross-day pass can
        # regroup them into a single line naming every night.
        for sk in res['skipped']:
            for d in sk['dishes'] or [{'id': None, 'name': None}]:
                skipped.append({'name': sk['name'], 'reason': sk['reason'],
                                'dish': d['name'], 'dish_id': d['id'],
                                'date': day['date'], 'weekday': day['weekday']})
    skipped = consolidate_skips(skipped)
    return {'added': added, 'skipped': skipped, 'skipped_names': [x['name'] for x in skipped],
            'list_id': lst_id, 'pinned_dates': pinned, 'day_count': len(week),
            'dish_count': sum(len(d['dishes']) for d in week)}


def _week_proposal_body(week: list, win: dict) -> str:
    """What Argyle actually says. The nights ARE the message — a card saying
    "a meal plan is ready" would just be a second trip to go and look at it."""
    shop = datetime.date.fromisoformat(win['grocery_date']).strftime('%A')
    when = {0: 'today', 1: 'tomorrow'}.get(win['days_until_shop'],
                                           f"in {win['days_until_shop']} days")
    lines = [f"🗓️ Shopping {shop} ({when}) — here's what I have for the {len(week)} nights it covers:"]
    for day in week:
        names = [d.get('short_name') or d['name'] for d in day['dishes']]
        lines.append(f"  {day['weekday']}: " + (", ".join(names) if names else "—"))
    lines.append("Approve and I'll put the whole week on the list, or change any "
                 "night on the Meals page first.")
    return "\n".join(lines)


def propose_week_plan(now: datetime.datetime = None, deliver=None) -> dict:
    """Bring the week to the family a couple of days before the shop.

    This is the arc's reason to exist: the planning session becomes one "how
    does this look?". Fires ONCE per shopping cycle, keyed on the grocery date,
    with the marker set before delivery (the push-loop convention). Returns
    {status, ...} describing what happened, for logs and tests.
    """
    settings = storage.get_settings() or {}
    if not settings.get('meal_week_enabled', True):
        return {'status': 'disabled'}
    now = now or datetime.datetime.now()
    win = plan_window(settings, now.date())
    if win['mode'] != 'planning':
        return {'status': 'not_yet', 'days_until_shop': win['days_until_shop']}

    marker = f"week_plan:{win['grocery_date']}"
    seen = dict(storage.get_app_state('week_plan_proposed') or {})
    if marker in seen:
        return {'status': 'already_proposed', 'marker': marker}

    week = compose_week(win['start'], win['days'], settings)
    if not any(d['dishes'] for d in week):
        # Nothing to propose from. Silence is right — a card saying "I have no
        # dinners for you" is not a plan, and the repertoire prompt already
        # lives on the page.
        return {'status': 'empty_repertoire'}

    # Marker FIRST: a half-failing delivery must not re-propose every sweep.
    cutoff = (now.date() - datetime.timedelta(days=60)).isoformat()
    seen = {k: v for k, v in seen.items() if str(v) >= cutoff}
    seen[marker] = now.date().isoformat()
    storage.set_app_state('week_plan_proposed', seen)

    summary = (f"{len(week)} nights of dinners for the "
               f"{datetime.date.fromisoformat(win['grocery_date']).strftime('%A')} shop")
    payload = {'start': win['start'], 'days': win['days'],
               'grocery_date': win['grocery_date']}
    body = _week_proposal_body(week, win)
    (deliver or _deliver_week_proposal)(summary, payload, body)
    return {'status': 'proposed', 'marker': marker, 'days': len(week),
            'dish_count': sum(len(d['dishes']) for d in week)}


def _deliver_week_proposal(summary: str, payload: dict, body: str):
    """Same delivery as the car-stop card: family channel (parents approve
    there, chat fan-out pushes phones) plus the dashboard approvals banner."""
    from services import chat_actions
    res = chat_actions.create_action_proposal('approve_week_plan', summary, payload)
    if res.get('status') != 'success':
        return None
    pid = res['proposal_id']
    try:
        fam = storage.get_family_channel()
        if fam:
            storage.update_action_proposal(pid, {'channel_id': fam['id']})
            argyle = storage.ensure_argyle_member()
            from services.agent_tools_v2 import _post_chat_message
            _post_chat_message(fam, argyle, body, card=res['card'])
    except Exception as ex:
        print(f"week plan proposal delivery failed: {ex}")
    return pid


def pin_plate(date_str: str, dishes: list = None) -> dict:
    """Freeze a day exactly as proposed. Shopping for a day pins it: once the
    ingredients are bought, a plan that quietly recomposed itself would have
    spent the family's money on a dinner they are no longer having."""
    if dishes is None:
        # The night as SHOWN, not as composed in isolation — pinning has the
        # same failure mode locking had. See dishes_showing_on.
        dishes = dishes_showing_on(date_str)
    _persist_plate(date_str, dishes)
    return {'date': date_str, 'dishes': dishes, 'pinned': True}


def add_to_plate(date_str: str, dish_id: str, plan: dict = None) -> dict:
    """Add a dish to tonight — "we've got corn too"."""
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'error': 'no such dish'}
    cur = dishes_showing_on(date_str, plan)
    if any(d['id'] == dish_id for d in cur):
        return {'dishes': cur, 'unchanged': True}
    cur = cur + [dish]
    _persist_plate(date_str, cur)
    return {'dishes': cur}


def remove_from_plate(date_str: str, dish_id: str, plan: dict = None) -> dict:
    """Drop a dish — "no salad tonight".

    Also clears any already-made mark on it. That mark only means something
    while the dish is ON the plate, and leaving it behind meant re-adding the
    dish brought back a struck-through chip nobody asked for.
    """
    # Not the standalone composition: dropping a chip off an unpinned night
    # would otherwise be asked to remove a dish that night was never showing,
    # report "unchanged", and freeze a different dinner on the way past.
    cur = dishes_showing_on(date_str, plan)
    kept = [d for d in cur if d['id'] != dish_id]
    if len(kept) == len(cur):
        return {'dishes': cur, 'unchanged': True}
    unmark_leftover_dish(date_str, dish_id)
    _persist_plate(date_str, kept)
    return {'dishes': kept}


def reset_plate(date_str: str, force: bool = False) -> dict:
    """Back to the proposal — plans change.

    A LOCKED night refuses unless forced: the whole point of locking is that a
    bulk repropose cannot sweep away a birthday dinner set three weeks out. The
    per-day reset passes force, because that one is a deliberate act on that
    specific night.
    """
    saved = storage.get_plate(date_str)
    if saved and saved.get('locked') and not force:
        out = get_or_compose_plate(date_str)
        out['locked'] = True
        out['refused'] = True
        return out
    storage.delete_plate(date_str)
    # Deleting the plate is a dish change like any other: whatever was bought
    # for that night is now unclaimed unless another night wants the same dish.
    reconcile_claims()
    return get_or_compose_plate(date_str)


def dish_is_leftover(date_str: str, dish_id: str) -> bool:
    for l in storage.get_leftovers(date_str):
        if dish_id in (l.get('dish_ids') or []):
            return True
    return False


def unmark_leftover_dish(date_str: str, dish_id: str) -> bool:
    """Take a single dish back off the already-made list.

    A record may cover several dishes ("rice and beans are made"), so this
    strips just this one and deletes the record only when it was a per-dish
    record that has been emptied. Whole-meal leftovers carry no dish_ids and
    are left alone — they are a different statement.
    """
    changed = False
    for l in storage.get_leftovers(date_str):
        ids = list(l.get('dish_ids') or [])
        if dish_id not in ids:
            continue
        ids.remove(dish_id)
        changed = True
        if ids:
            storage.delete_leftover(l['id'])
            storage.add_leftover({**l, 'dish_ids': ids})
        else:
            storage.delete_leftover(l['id'])
    return changed


def toggle_leftover_dish(date_str: str, dish_id: str, label: str = None) -> bool:
    """Returns the NEW state. Marking already-made has to be reversible in
    place — the first cut only ever added, so undoing it meant removing the
    dish from the plate and adding it back."""
    from models.schemas import Leftover
    if dish_is_leftover(date_str, dish_id):
        unmark_leftover_dish(date_str, dish_id)
        return False
    storage.prune_leftovers(date_str)
    dish = storage.get_dish(dish_id) or {}
    storage.add_leftover(Leftover(
        date=date_str, dish_ids=[dish_id],
        label=label or dish.get('name')).model_dump())
    return True


def plate_totals(dishes: list, date_str: str = None, settings: dict = None,
                 cooks: int = None, serving_for: int = None,
                 plate: dict = None) -> dict:
    """The aggregate timing for a plate, same rules as the slot version: the
    dishes are scheduled against the declared kitchen, and the weakest link
    wins on portability.

    Headcount and hands are read off the STORED plate when the caller does not
    override them, so a night marked "twelve people, two of us cooking" keeps
    saying so on every surface that renders it, rather than only on the one
    where it was typed.
    """
    day = date_str or _today_iso()
    leftovers = storage.get_leftovers(day)
    if serving_for is None or cooks is None:
        saved = plate if plate is not None else (storage.get_plate(day) or {})
        serving_for = serving_for if serving_for is not None else saved.get('serving_for')
        cooks = cooks if cooks is not None else saved.get('cooks')
    # No override for the night: cook for the household, less anyone away.
    # Leaving this None meant every dish was made at its own `serves` and the
    # scale factor was permanently 1.0.
    if serving_for is None:
        serving_for = eaters_on(day, settings)
    return compose({'name': 'plate'}, dishes, leftovers, settings, cooks,
                   serving_for)


def slot_detail_is_moot(pool: list) -> bool:
    """Does this slot's own set of options already answer the question?

    Options are variants of one thing, so if any sibling is specific enough
    the whole slot is — "roasted potatoes (red, russet, yellow)" states both
    the method and the varieties. A "?" on one of three otherwise-identical
    chips is model noise, not a question worth asking.
    """
    return len(pool) > 1 and any(not d.get('needs_detail') for d in pool)


def normalize_slot_detail(dish_ids: list) -> int:
    """Clear stale flags across a slot, IN STORAGE. Returns how many changed."""
    pool = storage.get_dishes_by_ids(dish_ids or [])
    if not slot_detail_is_moot(pool):
        return 0
    n = 0
    for d in pool:
        if d.get('needs_detail'):
            storage.update_dish(d['id'], {'needs_detail': False,
                                          'detail_question': None})
            n += 1
    return n


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
        entry = {**pick, '_slot': key, '_label': slot.get('label'),
                 '_optional': bool(slot.get('optional')), '_pool': len(pool),
                 '_chip': _chip_label(pick, pool)}
        # Suppress a stale flag on READ too. Dishes already saved with one
        # would otherwise keep showing "?" until the meal happened to be
        # re-entered, which is not something anyone should have to discover.
        if entry.get('needs_detail') and slot_detail_is_moot(pool):
            entry['needs_detail'] = False
            entry['detail_question'] = None
        picks[i] = entry
    for i in range(len(slots)):
        if i in picks:
            chosen.append(picks[i])
    return chosen


def compose(meal: dict, dishes: list, leftovers: list = None,
            settings: dict = None, cooks: int = None,
            serving_for: int = None) -> dict:
    """Roll a set of dishes up into the timing shape the fit filter reads.

    The three timing numbers come from `services/kitchen.py`, which schedules
    the dishes against a declared kitchen (ovens and their temperatures,
    burners, hands) rather than the two constants this function used to carry:
    hands-on SUMS because there is one cook, unattended takes the MAX because
    the oven is infinite. **With one cook, one oven and no temperature clash
    those are exactly what kitchen.totals returns** — and where they differ
    (two dishes wanting the oven at different temperatures) the old arithmetic
    was wrong, quietly, in the optimistic direction.

    Portability and holds_well take the weakest link — a plate travels only as
    well as its worst dish. Anything already made contributes nothing at all,
    which is the exactness M3's proportional guess could not reach.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    done = set()
    for l in leftovers or []:
        done.update(l.get('dish_ids') or [])

    holds, port_rank = True, 9
    ahead = 'none'
    ahead_rank = {'none': 0, 'thaw': 1, 'marinate': 2, 'slow_cooker': 3}
    # An already-made dish is not cooked, so it occupies no oven, no burner and
    # nobody's hands — it must leave the kitchen model entirely, not merely
    # contribute zero to a sum.
    to_cook = [d for d in dishes if d['id'] not in done]
    kt = kitchen.totals(to_cook, settings, cooks, serving_for)
    for d in to_cook:
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
        'prep_ahead_mins': kt['prep_ahead_mins'], 'finish_mins': kt['finish_mins'],
        'unattended_mins': kt['unattended_mins'], 'needs_ahead': ahead,
        'serving_for': kt['serving_for'],
        'holds_well': holds if dishes else bool(meal.get('holds_well')),
        'portability': port if dishes else str(meal.get('portability') or 'none'),
        'dishes': dishes,
        'leftover_dish_ids': sorted(done & {d['id'] for d in dishes}),
        # Reported, never merely priced into the number above: "these two want
        # the oven at different temperatures" is the most useful sentence this
        # model can say, and a total that quietly grew says none of it.
        'oven_conflicts': kt['oven_conflicts'],
        'cooks': kt['cooks'],
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


def compose_meal(meal: dict, prefer: dict = None, leftovers: list = None,
                 settings: dict = None, cooks: int = None) -> dict:
    """`choose_dishes` + `compose`. Legacy meals with no slots pass through on
    their own stored numbers, so nothing breaks mid-migration.

    `settings` is threaded rather than re-read because the fit filter calls
    this once per repertoire entry per day — a whole-repertoire fortnight is
    several hundred calls, and the kitchen capacities are the same for all of
    them.
    """
    if not (meal.get('slots') or []):
        return {**meal, 'dishes': []}
    meal = ensure_slot_ids(meal)
    dishes = choose_dishes(meal, prefer, leftovers)
    return compose(meal, dishes, leftovers, settings, cooks)


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


def meals_that_fit(plan: dict, limit: int = 5, settings: dict = None) -> dict:
    """Repertoire entries that actually work for this plan, ranked.

    Hard filters: the household's tightest slot (a meal everyone can eat has
    to survive the car if someone is in the car), the cook window, and
    allergies. Soft signals only reorder: recency (rotation), dislikes,
    effort. Returns {'fits': [...], 'blocked': [...]} — blocked entries carry
    their reason so nothing vanishes without explanation.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
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
                                leftovers=leftovers, settings=settings)
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


def category_prompt_block() -> str:
    """The family's vocabulary, handed to the classifier.

    This is the whole inversion: the model is told THEIR words instead of
    teaching them ours. The old prompt asserted that beans are a starch, which
    meant a household whose protein comes from beans got plates with no protein
    on them and no way to say otherwise.
    """
    cats = storage.get_dish_categories()
    if not cats:
        return ""
    lines = ["\nTHIS FAMILY'S CATEGORIES — use exactly these names:"]
    for c in cats:
        desc = (c.get('description') or '').strip()
        lines.append(f"  - {c['name']}" + (f": {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


def resolve_category_names(names) -> list:
    """Model answers -> the family's category ids. Matching is loose on case
    and whitespace and tolerant of a plural, because the classifier writing
    "vegetable" for a category called "vegetables" is not a disagreement worth
    dropping the answer over. Unknown names are discarded rather than invented:
    a category the family did not create is not one the composer can fill."""
    if not names:
        return []
    cats = storage.get_dish_categories()
    by_key = {}
    for c in cats:
        key = str(c.get('name') or '').strip().lower()
        by_key[key] = c['id']
        by_key[key.rstrip('s')] = c['id']
    out = []
    for n in names[:6]:
        key = str(n or '').strip().lower()
        cid = by_key.get(key) or by_key.get(key.rstrip('s'))
        if cid and cid not in out:
            out.append(cid)
    return out


def _today_iso() -> str:
    return datetime.date.today().isoformat()


# How long a night stays on the record. Plates used to be pruned to TODAY on
# every write, which meant the family's own history was destroyed daily: what
# they ate last night was gone the moment anything touched tonight, and the
# only trace left was one `last_served_at` per dish — a single timestamp that
# cannot answer "what did we have on Tuesday", "what do we cook most", or the
# frequency caps' own documented gap ("a cap of twice a week cannot see a third
# helping from last Tuesday"). A plate row is a date and a handful of dish ids;
# a year of them is nothing, and it is the only copy of this that will ever
# exist. Kept for two years, then pruned.
PLATE_RETENTION_DAYS = 730


def _history_cutoff() -> str:
    return (datetime.date.today()
            - datetime.timedelta(days=PLATE_RETENTION_DAYS)).isoformat()


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


_DISH_SYSTEM_V5 = (
    "You turn a family's description of what they eat into a flat list of "
    "DISHES. Reply with STRICT JSON only, no prose, no code fences. You are "
    "NOT writing recipes — never return steps, instructions or quantities.\n\n"
    "Schema: {\"dishes\": [{\"name\": str, \"short_name\": str, "
    "\"type\": \"meal|dish\", \"categories\": [str], "
    "\"prep_ahead_mins\": int, \"finish_mins\": int, \"unattended_mins\": int, "
    "\"needs_ahead\": \"none|thaw|marinate|slow_cooker\", \"holds_well\": bool, "
    "\"portability\": \"none|handheld|utensils_ok\", "
    "\"source\": \"prep|ordered\", \"tags\": [str], "
    "\"equipment\": \"none|oven|burner\", \"oven_temp_f\": int|null, "
    "\"serves\": int, \"whole_units\": bool, \"scope\": \"everyday|occasion\", "
    "\"ingredients\": [{\"name\": str, \"kind\": \"staple|fresh\"}], "
    "\"needs_detail\": bool, \"detail_question\": str|null}]}\n\n"
    "ONE DISH PER THING THEY WOULD ACTUALLY COOK OR SERVE:\n"
    "- Every alternative is its OWN dish. 'beans (black, red, or pinto)' is "
    "THREE dishes; 'roasted potatoes (red, russet, yellow)' is THREE dishes, "
    "each already specific ('roasted russet potatoes').\n"
    "- IGNORE quantities like 'veggies x 2' — that is how many sides they "
    "want on a plate, not a property of any dish. Just emit the vegetables.\n"
    "- type: 'meal' ONLY when the dish is a whole dinner by itself (tacos, "
    "spaghetti and meatballs, chili) — it satisfies the whole plate and "
    "nothing is served beside it. 'dish' for everything else.\n"
    "- categories: choose from THIS FAMILY'S list, given below, and use "
    "THEIR words, not yours. Give EVERY category a dish can serve as: black "
    "beans may be both the protein and the starch, and picking both is what "
    "lets it answer whichever the plate still needs. A dish fills only ONE "
    "slot per meal, so listing several is never double-counting. Use [] "
    "only when none of their categories fit.\n"
    "- tags: short lowercase words that say what a dish goes WITH as much as "
    "what it is ('mexican', 'chicken', 'asian', 'comfort'). These are used to "
    "keep a proposed plate coherent.\n\n"
    "Each dish is timed on its own: prep_ahead_mins is work that can be done "
    "earlier and set aside, finish_mins must happen near eating, "
    "unattended_mins is oven or slow-cooker time needing nobody at the stove. "
    "Rice is a little prep and a lot of unattended; a salad is all finish.\n"
    "- equipment: what the dish OCCUPIES while it cooks — 'oven' for anything "
    "baked or roasted, 'burner' for a stovetop pot or pan, 'none' for a salad, "
    "a slow cooker, or anything served cold. With 'oven', give oven_temp_f "
    "(two dishes share an oven only at the SAME temperature); null otherwise.\n"
    "- serves: how many people the times and ingredients above assume. Use 4 "
    "unless the description says otherwise.\n"
    "- whole_units: TRUE only for food made in indivisible units - a tray of "
    "lasagna, a casserole, a cake, a sheet pan, a pot pie, a loaf. Feeding more "
    "people means making ANOTHER whole one. FALSE for anything you can simply "
    "make more or less of (rice, carrots, chicken thighs, salad), which is most "
    "food. When in doubt, false.\n"
    "- scope: 'occasion' for food a family eats at holidays and parties rather "
    "than on an ordinary weeknight (turkey, stuffing, cranberry sauce, deviled "
    "eggs, a birthday cake). 'everyday' for everything else, INCLUDING dishes "
    "that show up at both (mashed potatoes, rolls, green beans) — when in "
    "doubt choose 'everyday'.\n"
    "- name is SPECIFIC enough to time and shop for; short_name is what the "
    "family says ('potatoes').\n"
    "- ingredients: kind='staple' for what a kitchen always has (salt, oil, "
    "common spices, rice, pasta, flour), 'fresh' for what must be bought. No "
    "quantities.\n"
    "- needs_detail: TRUE only when they were too vague to time or shop for — "
    "bare 'potatoes' says neither which kind nor how cooked. GUESS a sensible "
    "version anyway and put it in `name`; never refuse. FALSE whenever they "
    "already told you: 'roasted potatoes (red, russet, yellow)' gives both "
    "the method and the varieties, so all three are fully specified.\n"
    "- Be realistic about a weeknight home kitchen."
)

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
        equipment=_choice('equipment', ('none', 'oven', 'burner'), 'none'),
        # Only meaningful on an oven dish, and a model that answers 'burner'
        # while still volunteering a temperature should not leave a phantom
        # sharing key behind.
        oven_temp_f=(_int('oven_temp_f', 600) or None
                     if _choice('equipment', ('none', 'oven', 'burner'), 'none') == 'oven'
                     else None),
        serves=_int('serves', 40) or 4,
        whole_units=bool(raw.get('whole_units')),
        scope=_choice('scope', ('everyday', 'occasion'), 'everyday'),
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


# M4's free-text `role` -> the category NAME a family is most likely to have
# for it. Resolved against their own list at migration time, so a household
# that calls it "carbs" gets carbs and one that deleted "salad" gets nothing
# rather than a category resurrected behind their back.
_ROLE_TO_CATEGORY = {
    'protein': 'protein',
    'main': 'protein',
    'entree': 'protein',
    'starch': 'starches/carbs',
    'carb': 'starches/carbs',
    'vegetable': 'vegetables',
    'veg': 'vegetables',
    'salad': 'salad',
    'dessert': 'something sweet',
    'sweet': 'something sweet',
}


def migrate_slot_meals() -> dict:
    """Bring M4's slot-meals across to M5's typed dishes.

    The dishes already exist and are already right — only their TYPE was
    implicit (in `role`) and their grouping lived on `Meal.slots`. So this
    types them and retires the meal rows; nothing the family entered is lost,
    and their combinations become emergent instead of frozen.
    """
    typed, retired = 0, 0
    for d in storage.get_dishes(include_inactive=True):
        # A whole-meal dish is already right; anything else with a category is
        # already migrated. The old guard tested for `type != 'side'`, which
        # after v2.108 excluded every dish (the default is now 'dish').
        if d.get('type') == 'meal' or d.get('category_ids'):
            continue
        role = str(d.get('role') or '').strip().lower()
        cats = resolve_category_names([_ROLE_TO_CATEGORY.get(role, role)])
        storage.update_dish(d['id'], {'type': 'dish', 'category_ids': cats})
        typed += 1
    for meal in storage.get_meals(include_inactive=True):
        if not (meal.get('slots') or []):
            continue
        storage.update_meal(meal['id'], {'is_active': False})
        retired += 1
    return {'typed': typed, 'retired_meals': retired}


def add_dishes_from_text(description: str) -> dict:
    """M5 entry: type what you eat, get typed DISHES in the repertoire.

    No slots, no option pools, no "x 2" — every alternative is simply its own
    dish, and how many sides go on a plate is a setting rather than something
    baked into a stored combination.
    """
    from services import model_pools
    raw = (description or '').strip()
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key or not raw:
        return {'added': [], 'existing': [], 'error': 'no LLM API key configured'
                if not api_key else 'nothing to add'}
    try:
        res = model_pools.call_pool_json(
            'interactive', api_key, _DISH_SYSTEM_V5 + category_prompt_block(),
            f"The family describes what they eat as: {raw}",
            temperature=0.2, timeout_s=45, settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            raise RuntimeError(res.get('error') if isinstance(res, dict) else 'bad response')
    except Exception as e:
        print(f"[meals] dish extraction failed for {raw!r}: {e}")
        return {'added': [], 'existing': [], 'error': 'could not read that'}

    added, existing = [], []
    for raw_dish in (res.get('dishes') or [])[:30]:
        d = _clean_dish(raw_dish)
        if not d:
            continue
        d['type'] = 'meal' if str(raw_dish.get('type') or '').strip().lower() == 'meal' else 'dish'
        d['category_ids'] = resolve_category_names(raw_dish.get('categories'))
        prior = storage.find_dish_for_reuse(d['name'])
        if prior:
            existing.append(prior)
            continue
        storage.add_dish(d)
        added.append(d)
    return {'added': added, 'existing': existing, 'error': None}


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
            existing = storage.find_dish_for_reuse(d['name'])
            if existing:
                ids.append(existing['id'])
                continue
            storage.add_dish(d)
            ids.append(d['id'])
        # Dishes are REUSED, so a row saved with a stale needs_detail flag
        # comes back flagged however many times the meal is re-entered — the
        # sibling rule has to run over the RESOLVED slot, not just over the
        # freshly extracted dicts.
        normalize_slot_detail(ids)
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


def consolidate_skips(records: list) -> list:
    """One line per ingredient, naming every dish that wanted it.

    Rice used by four dishes produced four identical "assumed on hand" lines,
    which reads as a broken list rather than one judgement about rice. Grouped
    by (ingredient, reason) — the reason must stay in the key, because "staple"
    and "already on the list" are different statements about the same word and
    only the first is something the family can override.
    """
    out, by_key = [], {}
    for r in records:
        key = ((r.get('name') or '').strip().lower(), r.get('reason'))
        entry = by_key.get(key)
        ref = {'id': r.get('dish_id'), 'name': r.get('dish')}
        if r.get('weekday'):
            ref['weekday'] = r['weekday']
            ref['date'] = r.get('date')
        if entry is None:
            entry = {k: v for k, v in r.items() if k not in ('dish', 'dish_id')}
            entry['name'] = r.get('name')
            entry['dishes'] = []
            entry['dish_ids'] = []
            by_key[key] = entry
            out.append(entry)
        if ref['id'] and ref['id'] not in entry['dish_ids']:
            entry['dish_ids'].append(ref['id'])
        # Same dish on two nights is ONE reason to buy it, not two.
        if ref['name'] and not any(d['name'] == ref['name'] and
                                   d.get('weekday') == ref.get('weekday')
                                   for d in entry['dishes']):
            entry['dishes'].append(ref)
    for entry in out:
        labels = []
        for d in entry['dishes']:
            labels.append(f"{d['name']} ({d['weekday']})" if d.get('weekday') else d['name'])
        # `dish` stays a plain string so every existing reader keeps working.
        entry['dish'] = ', '.join(labels)
        entry['dish_id'] = entry['dish_ids'][0] if entry['dish_ids'] else None
        entry['dish_count'] = len(entry['dishes'])
    return out


def claim_shopping_item(item: dict, claim: dict, buy_on: str = None) -> dict:
    """Record one more night's stake in a row that is already on the list.

    `buy_on` moves EARLIER only. Two nights wanting the same chicken are
    bought once, on the run that has to cover the first of them — buying it
    later would be buying it too late, and there is no version of this where
    the second night is the one that decides.
    """
    claims = list(item.get('claims') or [])
    if not claims and item.get('source_meal_id'):
        # A row from before claims existed: promote what it does remember, so
        # it is not mistaken for a row nobody can account for.
        claims.append({'dish_id': item['source_meal_id'], 'date': None,
                       'dish_name': None})
    key = (claim.get('dish_id'), claim.get('date'))
    if key not in {(c.get('dish_id'), c.get('date')) for c in claims}:
        claims.append(claim)
    patch = {'claims': claims}
    have = item.get('buy_on')
    if buy_on and (not have or buy_on < have):
        patch['buy_on'] = buy_on
    storage.update_shopping_item(item['id'], patch)
    return {**item, **patch}


def reconcile_claims(today: datetime.date = None, horizon_days: int = 60) -> dict:
    """Take back off the list what no planned night wants any more.

    The rule, in one sentence: **an ingredient stays while any planned night
    still wants the dish that brought it.** Matching is by DISH rather than by
    (dish, night) on purpose — plans change at the drop of a hat, and what
    actually happens is that a meal gets punted to a different day and
    everything shifts. Matching per-night would strip the noodles off the list
    the moment lasagna moved from Thursday to Friday, which is the one case
    that must cost nothing.

    Three things are never removed, and each is a real household:

    - a row a PERSON put there. Somebody typing "milk" is not a consequence of
      the meal plan and does not evaporate when the meal plan changes, even if
      a dish later claimed the same name.
    - a row already CHECKED OFF. You own it now. This is the mid-week top-up
      case: bought on Wednesday, Thursday's dinner changes, and rewriting the
      list to pretend it was never bought helps nobody.
    - a row nobody can account for — a meal item from before claims existed,
      carrying no claims at all. Unexplained is not the same as unwanted, and
      guessing wrong here throws away somebody's shopping.
    """
    today = today or datetime.date.today()
    end = (today + datetime.timedelta(days=max(1, horizon_days))).isoformat()
    wanted = set()
    for plate in storage.get_plates_between(today.isoformat(), end):
        for it in plate.get('items') or []:
            if it.get('dish_id'):
                wanted.add(it['dish_id'])

    removed, kept = [], []
    for item in storage.get_shopping_items(include_checked=False):
        if str(item.get('added_via')) != 'meal':
            continue                      # a person's own need; not ours to prune
        claims = list(item.get('claims') or [])
        if not claims:
            continue                      # unexplained, therefore untouched
        live = [c for c in claims if c.get('dish_id') in wanted]
        if live:
            if len(live) != len(claims):
                storage.update_shopping_item(item['id'], {'claims': live})
            continue
        storage.delete_shopping_item(item['id'])
        removed.append({'id': item['id'], 'name': item.get('name'),
                        'list_id': item.get('list_id'),
                        'was_for': [c.get('dish_name') for c in claims if c.get('dish_name')]})
    return {'removed': removed, 'removed_names': [r['name'] for r in removed],
            'kept': kept}


def _claim(dish: dict, date_str: str = None) -> dict:
    """One night's stake in a shopping row. The dish NAME rides along so the
    list can say why something stayed ("Thursday still wants it") without a
    second lookup per row on a page that renders forty of them."""
    return {'dish_id': dish.get('id'), 'date': date_str,
            'dish_name': dish.get('short_name') or dish.get('name')}


def dishes_to_shopping(dishes: list, list_id: str = None, added_by: str = None,
                       skip_dish_ids: list = None, date_str: str = None,
                       buy_on: str = None) -> dict:
    """Shop for the dishes actually chosen — one plate's worth, not every
    alternative in every pool. Already-made dishes buy nothing.

    An ingredient already on the list is still not bought twice, but the
    asking dish now leaves a CLAIM on the existing row instead of being waved
    away. That difference is the whole of un-adding: without it the list
    remembers only whoever asked first, and taking Monday's dinner off would
    take Thursday's chicken with it.
    """
    from models.schemas import ShoppingItem
    skip = set(skip_dish_ids or [])
    lst_id = list_id or storage.ensure_default_shopping_list()['id']
    added, skipped = [], []

    def note(name, reason, dish):
        # Skips carry their REASON. Every one of these is a judgement the
        # model made and the family cannot see: whether beans are a pantry
        # staple, whether a dish has any ingredients recorded at all. A silent
        # skip is indistinguishable from a bug — and was reported as one.
        skipped.append({'name': name, 'reason': reason,
                        'dish': dish.get('short_name') or dish.get('name'),
                        'dish_id': dish.get('id')})

    for d in dishes:
        label = d.get('short_name') or d.get('name')
        if d.get('id') in skip:
            note(label, 'already made', d)
            continue
        if str(d.get('source') or 'prep') == 'ordered':
            note(label, 'ordered', d)
            continue
        ings = [i for i in (d.get('ingredients') or [])
                if (i.get('name') or '').strip()]
        if not ings:
            # Nothing recorded for this dish, so nothing can be bought for it.
            # Reported rather than passed over in silence.
            note(label, 'no ingredients recorded', d)
            continue
        for ing in ings:
            name = ing['name'].strip()
            if (ing.get('kind') or 'fresh') == 'staple':
                note(name, 'staple', d)
                continue
            existing = storage.find_open_shopping_item(lst_id, name)
            if existing:
                # Not a second purchase — but it IS a second night depending on
                # this row, and that is the fact removal turns on.
                claim_shopping_item(existing, _claim(d, date_str), buy_on)
                note(name, 'already on the list', d)
                continue
            storage.add_shopping_item(ShoppingItem(
                list_id=lst_id, name=name, added_via='meal',
                source_meal_id=d.get('id'), added_by=added_by,
                claims=[_claim(d, date_str)], buy_on=buy_on).model_dump())
            added.append(name)
    skipped = consolidate_skips(skipped)
    return {'added': added, 'skipped': skipped,
            'skipped_names': [x['name'] for x in skipped],
            'list_id': lst_id}


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
                                  skip_dish_ids=composed.get('leftover_dish_ids'),
                                  date_str=today, buy_on=buy_on_for(today))
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


# --- Dish images (kiosk board, arc K1) --------------------------------------
# Images earn their place for ONE reason: a child who cannot read fluently yet
# can still see what is for dinner. That makes accuracy matter more than
# polish, which is why generated art is not used — an uncanny or wrong-looking
# dish defeats the only case that justified having a picture.

STOCK_QUERY_SUFFIX = "food dish cooked meal"


def dish_image_query(dish: dict) -> str:
    """Bias the search toward a plated, cooked dish. Searching the bare name
    finds raw ingredients and diagrams — a photograph of uncooked chicken
    thighs is worse than no picture for the reader who needs it most."""
    name = (dish.get('name') or dish.get('short_name') or '').strip()
    return f"{name} {STOCK_QUERY_SUFFIX}".strip()


def unsplash_key() -> str:
    """Delegate to the resolver the REST of the app uses.

    This was originally a second implementation reading only
    /data/options.json and an env var — so a key saved through the config UI
    (which lands in settings) was invisible here while the trip backgrounds
    found it perfectly well, and the backfill reported "no key configured" to a
    family who plainly had one. Same class as every other bug in this arc: two
    individually-correct pieces that did not refer to each other.
    """
    from services import maps as _maps
    return (str(_maps.get_map_option('unsplash_api_key', '') or '').strip()
            or None)


def fetch_stock_image(dish: dict) -> str:
    """Unsplash only — deliberately NOT the Wikidata/Wikipedia chain the trip
    backgrounds use, which returns anatomical diagrams for things like
    'chicken thighs'."""
    import urllib.parse
    import requests
    key = unsplash_key()
    if not key:
        return None
    try:
        q = urllib.parse.quote(dish_image_query(dish))
        r = requests.get(
            f"https://api.unsplash.com/search/photos?query={q}"
            "&orientation=landscape&per_page=1&content_filter=high",
            headers={"Authorization": f"Client-ID {key}"}, timeout=6)
        if r.ok:
            hits = (r.json() or {}).get('results') or []
            if hits:
                return hits[0]['urls'].get('small') or hits[0]['urls'].get('regular')
    except Exception as ex:
        print(f"dish image lookup failed: {ex}")
    return None


def set_dish_image(dish_id: str, url: str = None, source: str = 'family') -> dict:
    """A family photo always wins and is never overwritten by a stock one."""
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'status': 'error', 'message': 'No such dish.'}
    storage.update_dish(dish_id, {'image_url': (url or '').strip() or None,
                                  'image_source': source if url else None})
    return {'status': 'success', 'dish': storage.get_dish(dish_id)}


def backfill_dish_images(limit: int = 12, only_missing: bool = True) -> dict:
    """Fill in stock images for dishes that have none.

    Explicit and rate-limited rather than lazy-on-render: a board that stalls
    while it fetches pictures is worse than a board with none, and the
    no-image state is designed to look intentional anyway.
    """
    done, skipped, failed = [], 0, 0
    for d in storage.get_dishes():
        if len(done) >= max(1, limit):
            break
        if only_missing and (d.get('image_url') or '').strip():
            skipped += 1
            continue
        if d.get('image_source') == 'family':
            skipped += 1          # never paint over the family's own photo
            continue
        url = fetch_stock_image(d)
        if not url:
            failed += 1
            continue
        storage.update_dish(d['id'], {'image_url': url, 'image_source': 'stock'})
        done.append(d.get('short_name') or d.get('name'))
    return {'status': 'success', 'filled': done, 'skipped': skipped,
            'failed': failed, 'configured': bool(unsplash_key())}


def household_staples(limit: int = 40) -> list:
    """One-tap things to drop in the cart, ranked by what this household
    ACTUALLY buys.

    Two sources, and the order between them matters. What the family has really
    bought (the check-off tally) outranks what the recipes merely mention,
    because "how many dishes list black pepper" is a fact about the recipes and
    "we buy milk every week" is a fact about the household. Staples still seed
    the grid on a fresh install — otherwise the shortcut is empty exactly when
    the family has no history for it to learn from — but they sink below
    anything with a real purchase behind it as soon as one exists.

    Staples are here at all because they never reach a list on their own (that
    IS the classification), so running out of one had no gesture except the
    "+ List" skip dialog's Add, which permanently reclassifies it as fresh.
    """
    tally = storage.get_purchase_tally()
    rows, labels = {}, {}
    for key, t in tally.items():
        rows[key] = {'buys': int(t.get('count') or 0),
                     'last_at': t.get('last_at') or 0, 'dish_count': 0}
        labels[key] = t.get('label') or key

    for d in storage.get_dishes():
        for ing in (d.get('ingredients') or []):
            if (ing.get('kind') or 'fresh') != 'staple':
                continue
            raw = (ing.get('name') or '').strip()
            if not raw:
                continue
            key = ' '.join(raw.lower().split())
            row = rows.setdefault(key, {'buys': 0, 'last_at': 0, 'dish_count': 0})
            row['dish_count'] += 1
            labels.setdefault(key, raw)

    out = [{'name': labels[k], 'buys': v['buys'], 'dish_count': v['dish_count'],
            'known': v['buys'] > 0} for k, v in rows.items()]
    # Bought-before first (by how often, then how recently), then recipe
    # staples by how many dishes want them.
    out.sort(key=lambda x: (-x['buys'], -rows[' '.join(x['name'].lower().split())]['last_at'],
                            -x['dish_count'], x['name'].lower()))
    return out[:limit]


# --- Prep reminders (arc M8) ------------------------------------------------
# Soaking beans the night before is cognitively separate from cooking dinner:
# it happens on a different DAY, nothing on the plate prompts it, and
# forgetting it silently invalidates tomorrow's plan. The plate could already
# say a dish "needs a thaw head start" — a label with no time attached that
# reminded nobody, which is precisely the useless half.

PREP_GRACE_MINS = 90          # a late nudge still helps; a stale one does not


def set_pairing(dish_id: str, partner_ids: list, mode: str = 'always_with',
                replace: bool = False) -> dict:
    """"Brisket always comes with beans and fries."

    Directed on purpose: this records a fact about BRISKET, and leaves beans
    and fries free to appear beside anything else. The symmetric version — a
    goes-with matrix — is the thing M5 refused to build, because it is O(n^2)
    of upkeep a family will never do.
    """
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'status': 'error', 'message': 'No such dish.'}
    if mode not in ('always_with', 'only_with'):
        return {'status': 'error', 'message': f"Unknown pairing '{mode}'."}
    ids = [p for p in (partner_ids or []) if p and p != dish_id]
    real = [p for p in ids if storage.get_dish(p)]
    cur = [] if replace else list(dish.get(mode) or [])
    for p in real:
        if p not in cur:
            cur.append(p)
    storage.update_dish(dish_id, {mode: cur})
    return {'status': 'success', 'dish': storage.get_dish(dish_id),
            'partners': cur, 'ignored': [p for p in ids if p not in real]}


def clear_pairing(dish_id: str, partner_id: str = None,
                  mode: str = 'always_with') -> dict:
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'status': 'error', 'message': 'No such dish.'}
    cur = list(dish.get(mode) or [])
    keep = [] if not partner_id else [p for p in cur if p != partner_id]
    storage.update_dish(dish_id, {mode: keep})
    return {'status': 'success', 'removed': len(cur) - len(keep),
            'dish': storage.get_dish(dish_id)}


def pairing_view(dish: dict, all_by_id: dict = None) -> dict:
    """Names rather than ids, for anything that has to show this to a human."""
    all_by_id = all_by_id if all_by_id is not None else \
        {d['id']: d for d in storage.get_dishes()}

    def names(ids):
        return [(all_by_id.get(i) or {}).get('short_name')
                or (all_by_id.get(i) or {}).get('name')
                for i in (ids or []) if i in all_by_id]
    return {'always_with': names(dish.get('always_with')),
            'only_with': names(dish.get('only_with'))}


def plate_display_order(dishes: list, cats: list = None) -> list:
    """The plate, in the order "What a plate looks like" lists its blocks.

    Stored plate order is insertion order — a replaced protein re-enters at
    the END — but the family reads a plate the way their own blocks are
    ordered, and every surface that leads with the first dish (the wall
    blocks, the chip rows) inherits whatever order editing left behind.
    A whole meal leads outright; every other dish sorts at its earliest
    matching block; the sort is stable, so uncategorized dishes keep their
    relative order at the back.
    """
    if not dishes:
        return dishes
    cats = cats if cats is not None else storage.get_dish_categories()
    order = {c['id']: i for i, c in enumerate(cats)}
    tail = len(cats)

    def key(d):
        if (d.get('type') or 'dish') == 'meal':
            return -1
        return min((order[c] for c in (d.get('category_ids') or [])
                    if c in order), default=tail)

    return sorted(dishes, key=key)


def with_chip_labels(dishes: list, all_dishes: list = None) -> list:
    """Give each dish a chip label that names the OPTION, not the category.

    M4 established this and built `_chip_label` for it — then M5 retired slots
    and the plate went back to bare `short_name`, so "frozen pizza", "takeout
    pizza" and "homemade pizza" all showed as "pizza" again. Same principle,
    new pool: a dish is disambiguated against every OTHER dish in the
    repertoire sharing its short name, rather than against its slot siblings.

    Also the one place every plate display passes through, so the canonical
    block order is applied here — see plate_display_order.
    """
    if not dishes:
        return dishes
    dishes = plate_display_order(dishes)
    all_dishes = all_dishes if all_dishes is not None else storage.get_dishes()
    by_short = {}
    for d in all_dishes:
        key = (d.get('short_name') or '').strip().lower()
        if key:
            by_short.setdefault(key, []).append(d)
    out = []
    for d in dishes:
        key = (d.get('short_name') or '').strip().lower()
        pool = by_short.get(key) or []
        out.append({**d, 'chip': _chip_label(d, pool) if key
                    else (d.get('name') or '')})
    return out


def dish_prep_steps(dish: dict) -> list:
    return [s for s in (dish.get('prep_steps') or []) if (s.get('action') or '').strip()]


def add_prep_step(dish_id: str, action: str, when: str = 'hours_before',
                  hours: float = 1.0, note: str = None) -> dict:
    """Whether rice gets soaked is a fact about THIS household, not about rice
    — so this is opt-in per dish and never inferred."""
    from models.schemas import PrepStep
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'status': 'error', 'message': 'No such dish.'}
    action = (action or '').strip()
    if not action:
        return {'status': 'error', 'message': 'What should happen ahead of time?'}
    when = when if when in ('night_before', 'hours_before', 'morning_of') else 'hours_before'
    step = PrepStep(action=action, when=when, hours=float(hours or 1),
                    note=(note or '').strip() or None).model_dump()
    steps = [s for s in (dish.get('prep_steps') or [])
             if (s.get('action') or '').strip().lower() != action.lower()]
    steps.append(step)          # same action = editing it, not stacking a second
    storage.update_dish(dish_id, {'prep_steps': steps})
    return {'status': 'success', 'dish': storage.get_dish(dish_id), 'step': step}


def remove_prep_step(dish_id: str, action: str = None, step_id: str = None) -> dict:
    dish = storage.get_dish(dish_id)
    if not dish:
        return {'status': 'error', 'message': 'No such dish.'}
    steps = list(dish.get('prep_steps') or [])
    if not step_id and not (action or '').strip():
        keep = []               # "stop reminding me about the rice" = all of it
    else:
        keep = [s for s in steps
                if not ((step_id and s.get('id') == step_id)
                        or (action and (s.get('action') or '').lower()
                            == action.strip().lower()))]
    storage.update_dish(dish_id, {'prep_steps': keep})
    return {'status': 'success', 'removed': len(steps) - len(keep),
            'dish': storage.get_dish(dish_id)}


def _hhmm(raw, dh, dm):
    try:
        parts = str(raw).split(':')
        return max(0, min(23, int(parts[0]))), max(0, min(59, int(parts[1])))
    except (TypeError, ValueError, IndexError):
        return dh, dm


def _dinner_time(date_str: str, plan: dict = None) -> datetime.datetime:
    """When the food is actually needed — the first sitting, else the dinner
    window's start."""
    plan = plan or eating_plan(date_str, 'dinner')
    rows = plan.get('sittings') or []
    if rows:
        try:
            return _parse_iso(rows[0]['start'])
        except Exception:
            pass
    day = datetime.date.fromisoformat(date_str)
    return datetime.datetime.combine(day, MEAL_WINDOWS['dinner'][0])


def prep_step_due_at(step: dict, date_str: str, settings: dict = None,
                     plan: dict = None) -> datetime.datetime:
    """When to actually say it.

    `night_before` is deliberately NOT dinner-minus-N. Soaking rice for a 6pm
    dinner is something you do at 9pm the evening before; the arithmetic answer
    (6am on the day) is correct and useless. It fires at the household's
    evening prep time on the PREVIOUS day.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    day = datetime.date.fromisoformat(date_str)
    when = step.get('when') or 'hours_before'
    if when == 'night_before':
        hh, mm = _hhmm(settings.get('prep_reminder_time'), 20, 30)
        return datetime.datetime.combine(day - datetime.timedelta(days=1),
                                         datetime.time(hh, mm))
    if when == 'morning_of':
        hh, mm = _hhmm(settings.get('prep_morning_time'), 8, 0)
        return datetime.datetime.combine(day, datetime.time(hh, mm))
    try:
        hours = float(step.get('hours') or 1)
    except (TypeError, ValueError):
        hours = 1.0
    return _dinner_time(date_str, plan) - datetime.timedelta(hours=hours)


def prep_reminders_due(now: datetime.datetime = None, settings: dict = None,
                       horizon_days: int = 2) -> list:
    """Every prep nudge that should have gone out by `now` and has not.

    Looks forward far enough to catch TOMORROW's night-before steps, which is
    the whole point — a sweep that only ever considers today can never tell you
    to soak anything.
    """
    now = now or datetime.datetime.now()
    settings = settings if settings is not None else (storage.get_settings() or {})
    out = []
    for i in range(max(1, horizon_days)):
        date_str = (now.date() + datetime.timedelta(days=i)).isoformat()
        plan = eating_plan(date_str, 'dinner', settings=settings)
        plate = get_or_compose_plate(date_str, plan, settings)
        made = set((plate_totals(plate['dishes'], date_str) or {})
                   .get('leftover_dish_ids') or [])
        for dish in plate['dishes']:
            if dish.get('id') in made:
                continue          # already cooked; nothing to prepare for it
            for step in dish_prep_steps(dish):
                due = prep_step_due_at(step, date_str, settings, plan)
                if due > now:
                    continue
                # Stale nudges are worse than none: "soak the beans" three
                # hours after they needed to be in water is just noise.
                if (now - due).total_seconds() > PREP_GRACE_MINS * 60:
                    continue
                out.append({
                    'key': f"prep:{dish['id']}:{date_str}:{step.get('id') or step['action']}",
                    'date': date_str, 'dish_id': dish['id'],
                    'dish': dish.get('short_name') or dish.get('name'),
                    'action': step['action'], 'when': step.get('when'),
                    'note': step.get('note'), 'due_at': due.isoformat(),
                    'for_label': 'tonight' if i == 0 else
                                 datetime.date.fromisoformat(date_str).strftime('%A'),
                })
    return out


def run_prep_reminders(send, now: datetime.datetime = None) -> list:
    """One sweep. `send(member, title, body)` delivers to one person.

    Markers are set BEFORE sending (the push-loop convention): a half-failing
    send must not re-nudge every thirty seconds.
    """
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('prep_reminders_enabled', True):
        return []
    due = prep_reminders_due(now, settings)
    if not due:
        return []
    sent = dict(storage.get_app_state('prep_reminders_sent') or {})
    cutoff = now.timestamp() - 14 * 86400
    sent = {k: v for k, v in sent.items() if float(v or 0) >= cutoff}

    cooks = [m for m in storage.get_all_members()
             if m.get('role') in _COOKING_ROLES and not m.get('system')]
    fired = []
    for item in due:
        if item['key'] in sent:
            continue
        sent[item['key']] = now.timestamp()
        fired.append(item['key'])
        when_word = 'for tonight' if item['for_label'] == 'tonight' else 'for tomorrow'
        title = f"🍽️ {item['action'].capitalize()} the {item['dish']}"
        body = (f"{item['action'].capitalize()} the {item['dish']} {when_word}"
                + (f" — {item['note']}" if item.get('note') else "") + ".")
        for m in cooks:
            try:
                send(m, title, body)
            except Exception:
                pass
    storage.set_app_state('prep_reminders_sent', sent)
    return fired
