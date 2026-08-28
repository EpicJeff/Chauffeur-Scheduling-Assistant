"""Negotiation — the smallest change that makes a day work, and who must agree.

The app has always been asked one question: *who drives?* When the answer is
nobody, `services/coverage_options.py` softens it with a ladder, but every rung
still hands the problem back to a parent.

This module asks the second question. The constraints are already in the model,
so a candidate is nothing more than the same day with one thing changed --
re-solved, and kept only if it actually works. What makes it a *negotiation*
rather than an optimisation is that every change costs a named person
something, and that person is asked.

Four levers, all occurrence-scoped, because a lever that reaches other days
would invalidate the single-day validation below:

    shift_event     move an event by a quarter or half hour
    lift_protected  give up ONE occurrence of a standing commitment
    swap_drive      take on a drive that was not yours
    skip_optional   do not go, this once

The prices in `GIVE_UP` are the design, not tuning. Lifting a protected window
is the most expensive thing the negotiator can ask for, because protected time
is the one place an adult's time is FOR something rather than an obstacle.
"""
import datetime

from services import coverage_options, solve_pack, storage

# Either side of the seed. A change further away than this is not plausibly
# about the seed, and proposing it reads as the app rummaging.
WINDOW_MINS = 90

# Ordered cheapest-first: a quarter hour is a smaller thing to ask than half.
SHIFT_STEPS = (-15, 15, -30, 30)

GIVE_UP = {'shift_15': 1, 'shift_30': 2, 'skip_optional': 2,
           'swap_drive': 3, 'lift_protected': 5}


def _dt(raw):
    try:
        return datetime.datetime.fromisoformat(str(raw)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _fmt(t):
    return t.strftime('%I:%M').lstrip('0') if t else ''


def series_key(ev: dict) -> str:
    """What makes this the same recurring thing across weeks. A refusal is
    remembered against the SERIES: 'the lesson cannot move' is a fact about the
    lesson, not about one Tuesday."""
    return str(ev.get('recurring_event_id') or ev.get('original_event_id')
               or ev.get('id'))


def _members_by_driver():
    return {str(m['driver_id']): m for m in storage.get_all_members()
            if m.get('driver_id')}


def _owner_of(ev: dict, pack: dict) -> str:
    """Whose event is this? The passenger's member if we can tell, else the
    parents — an event with no owner still costs somebody something, and an
    ask with no addressee is not an ask."""
    cals = set(ev.get('calendar_ids') or [])
    for p in pack.get('passengers') or []:
        if cals.intersection(set(p.get('calendar_ids') or [])):
            for m in storage.get_all_members():
                if str(m.get('passenger_id') or '') == str(p.get('id')):
                    return m['id']
    parents = [m for m in storage.get_all_members()
               if m.get('role') == 'parent' and not m.get('system')]
    return parents[0]['id'] if parents else ''


def _in_window(ev: dict, seed_start, seed_end) -> bool:
    start, end = _dt(ev.get('start')), _dt(ev.get('end'))
    if not start:
        return False
    end = end or start
    lo = seed_start - datetime.timedelta(minutes=WINDOW_MINS)
    hi = seed_end + datetime.timedelta(minutes=WINDOW_MINS)
    return start < hi and end > lo


def candidates(pack: dict, seed_event_id: str) -> list:
    """Every change worth trying for this seed, cheapest first.

    Ordering happens HERE, before anything is solved, because the budget is a
    cutoff on this list: the sweep's few solves must be spent on the most
    promising deals, not on a random sample of them.
    """
    events = {str(e.get('id')): e for e in pack.get('events') or []}
    seed = events.get(str(seed_event_id))
    if not seed:
        return []
    seed_start = _dt(seed.get('start'))
    if not seed_start:
        return []
    seed_end = _dt(seed.get('end')) or seed_start + datetime.timedelta(hours=1)

    refused = {r['series_key'] for r in storage.get_shift_refusals()}
    out = []

    # --- shift a neighbour, or the seed itself -----------------------------
    for ev in [seed] + [e for e in events.values()
                        if str(e.get('id')) != str(seed_event_id)]:
        if not _in_window(ev, seed_start, seed_end):
            continue
        if series_key(ev) in refused:
            continue
        owner = _owner_of(ev, pack)
        start = _dt(ev.get('start'))
        for delta in SHIFT_STEPS:
            cost = GIVE_UP['shift_15' if abs(delta) == 15 else 'shift_30']
            when = start + datetime.timedelta(minutes=delta)
            direction = 'later' if delta > 0 else 'earlier'
            out.append({
                'mutations': [{'lever': 'shift_event',
                               'event_id': str(ev.get('id')),
                               'delta_mins': delta}],
                'give_up': cost,
                'parts': [{'member_id': owner, 'lever': 'shift_event',
                           'payload': {'event_id': str(ev.get('id')),
                                       'series_key': series_key(ev),
                                       'title': ev.get('title') or 'that',
                                       'delta_mins': delta},
                           'ask_text': (f"Could {ev.get('title') or 'that'} move "
                                        f"{abs(delta)} minutes {direction}, to "
                                        f"{_fmt(when)}? It would cover "
                                        f"{seed.get('title') or 'the other drive'}.")}]})

    # --- skip something the family already called optional ------------------
    for ev in events.values():
        if str(ev.get('id')) == str(seed_event_id):
            continue
        if not (ev.get('app_config') or {}).get('is_optional'):
            continue
        if not _in_window(ev, seed_start, seed_end):
            continue
        owner = _owner_of(ev, pack)
        out.append({
            'mutations': [{'lever': 'skip_optional',
                           'event_id': str(ev.get('id'))}],
            'give_up': GIVE_UP['skip_optional'],
            'parts': [{'member_id': owner, 'lever': 'skip_optional',
                       'payload': {'event_id': str(ev.get('id')),
                                   'title': ev.get('title') or 'that'},
                       'ask_text': (f"Skip {ev.get('title') or 'that'} this once? "
                                    f"It would cover "
                                    f"{seed.get('title') or 'the other drive'}.")}]})

    # --- the reasons the ladder already found: swaps and protected windows --
    cache = {'events': list(events.values()),
             'assignments': dict(pack.get('previous_assignments') or {})}
    try:
        _free, blocked = coverage_options.driver_options(seed, cache)
    except Exception as e:
        print(f"[negotiation] driver options failed: {e}")
        blocked = []
    by_driver = _members_by_driver()
    for b in blocked:
        member = by_driver.get(str(b['id'])) or {}
        reason = b.get('reason') or ''
        if reason.startswith('driving '):
            # Somebody else takes the drive that is holding this driver.
            held = next((e for e in events.values()
                         if (e.get('title') or '') == reason[len('driving '):]), None)
            if not held:
                continue
            for d in pack.get('drivers') or []:
                if str(d.get('id')) == str(b['id']):
                    continue
                taker = by_driver.get(str(d.get('id'))) or {}
                if not taker or taker.get('status') in ('disabled', 'archived'):
                    continue
                out.append({
                    'mutations': [{'lever': 'swap_drive',
                                   'event_id': str(held.get('id')),
                                   'driver_id': str(d.get('id'))}],
                    'give_up': GIVE_UP['swap_drive'],
                    'parts': [{'member_id': taker['id'], 'lever': 'swap_drive',
                               'payload': {'event_id': str(held.get('id')),
                                           'driver_id': str(d.get('id')),
                                           'title': held.get('title') or 'that drive'},
                               'ask_text': (f"Could you take "
                                            f"{held.get('title') or 'that drive'}? "
                                            f"It frees {b.get('name')} for "
                                            f"{seed.get('title') or 'the other one'}.")}]})
            continue
        # A protected window. The most expensive thing here, on purpose.
        for pc in storage.get_protected_commitments(member_id=member.get('id')):
            if str(pc.get('id')) not in (pack.get('protected_rule_index') or {}):
                continue
            out.append({
                'mutations': [{'lever': 'lift_protected',
                               'commitment_id': str(pc.get('id'))}],
                'give_up': GIVE_UP['lift_protected'],
                'parts': [{'member_id': member.get('id'), 'lever': 'lift_protected',
                           'payload': {'commitment_id': str(pc.get('id')),
                                       'title': pc.get('title') or 'your time'},
                           'ask_text': (f"Could you give up "
                                        f"{pc.get('title') or 'your time'} just this "
                                        f"once? Nothing else covers "
                                        f"{seed.get('title') or 'the drive'}.")}]})

    out.sort(key=lambda c: (len({p['member_id'] for p in c['parts']}),
                            c['give_up']))

    # A part whose member_id is '' is a candidate addressed to nobody --
    # `_owner_of` falls back through the parents and, with none on record,
    # returns ''. An ask with no addressee is not an ask, so it never reaches
    # the queue: better a shorter list than a deal the app cannot deliver.
    return [c for c in out if all(p.get('member_id') for p in c['parts'])]
