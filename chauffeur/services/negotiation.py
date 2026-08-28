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

from services import coverage_options, maps, solve_pack, storage

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
        # `kind` and the id it carries come straight from `driver_options`,
        # not from parsing its `reason` prose -- that string is free to be
        # re-worded on its own schedule, and a lever that only worked as long
        # as nobody touched a sentence would be an outage waiting to happen.
        kind = b.get('kind')
        if kind == 'driving':
            # Somebody else takes the drive that is holding this driver.
            held = events.get(str(b.get('event_id') or ''))
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
        elif kind == 'protected':
            # A protected window. The most expensive thing here, on purpose.
            if not member.get('id'):
                # No member linked to this driver means nobody to ask -- and
                # `get_protected_commitments(member_id=None)` reads that as
                # "no filter" and hands back every family member's protected
                # time, which is not this driver's to give up.
                continue
            for pc in storage.get_protected_commitments(member_id=member['id']):
                if str(pc.get('id')) != str(b.get('commitment_id') or ''):
                    continue
                if str(pc.get('id')) not in (pack.get('protected_rule_index') or {}):
                    continue
                out.append({
                    'mutations': [{'lever': 'lift_protected',
                                   'commitment_id': str(pc.get('id'))}],
                    'give_up': GIVE_UP['lift_protected'],
                    'parts': [{'member_id': member['id'], 'lever': 'lift_protected',
                               'payload': {'commitment_id': str(pc.get('id')),
                                           'title': pc.get('title') or 'your time'},
                               'ask_text': (f"Could you give up "
                                            f"{pc.get('title') or 'your time'} just this "
                                            f"once? Nothing else covers "
                                            f"{seed.get('title') or 'the drive'}.")}]})
        # Anything else is a shape `driver_options` should never produce --
        # skip it rather than guess at what it meant.

    out.sort(key=lambda c: (len({p['member_id'] for p in c['parts']}),
                            c['give_up']))

    # A part whose member_id is '' is a candidate addressed to nobody --
    # `_owner_of` falls back through the parents and, with none on record,
    # returns ''. An ask with no addressee is not an ask, so it never reaches
    # the queue: better a shorter list than a deal the app cannot deliver.
    return [c for c in out if all(p.get('member_id') for p in c['parts'])]


# ── The search: solve the queue, keep what actually works ───────────────────

# How many re-solves a question is allowed. The sweep runs unattended and must
# never be the reason a schedule refresh feels slow; the on-demand path has a
# person waiting on purpose and can afford to go further down the same queue.
SWEEP_BUDGET = 8
DEEP_BUDGET = 40

# How far back fairness looks. Long enough that "you did it last time" is
# still true, short enough that a month-old favour stops counting.
FAIRNESS_DAYS = 14

# The objective is in the millions (a base assignment reward of 1,000,000 and
# an attendance term of 50,000,000), and it is identical across candidates for
# the same event, so what is left after subtraction is routing and priority
# degradation. Scaled down and capped hard: it breaks ties, it never decides.
DELTA_SCALE = 1000.0
DELTA_CAP = 4.0


def part_key(part: dict) -> str:
    payload = part.get('payload') or {}
    subject = (payload.get('event_id') or payload.get('commitment_id') or '')
    return f"{part.get('member_id')}:{part.get('lever')}:{subject}"


def _fairness(member_id: str) -> int:
    """How many times this person has been asked to give something up lately.

    Counted from recorded deals, so it is a real count. Nothing here is
    estimated — a made-up fairness number would be worse than none.
    """
    since = datetime.datetime.now().timestamp() - FAIRNESS_DAYS * 86400
    n = 0
    for d in storage.get_deals(since_ts=since):
        for p in d.get('parts') or []:
            if str(p.get('member_id')) == str(member_id):
                n += 1
    return n


def _score(candidate: dict, objective_delta: float):
    """The one place people/fairness/delta/total get computed. `_rank` and
    `_cost` both call this rather than each doing their own arithmetic --
    two implementations of the same decision is how a sort order and the
    numbers shown for it quietly drift apart."""
    people = sorted({p['member_id'] for p in candidate['parts']})
    fairness = sum(_fairness(m) for m in people)
    delta = min(max(objective_delta, 0.0) / DELTA_SCALE, DELTA_CAP)
    total = candidate['give_up'] + delta + fairness
    return len(people), fairness, delta, total


def _rank(candidate: dict, objective_delta: float):
    """The sort key. People disturbed comes first and is not tradeable."""
    people_n, _fairness_n, _delta, total = _score(candidate, objective_delta)
    return (people_n, total)


def _cost(candidate: dict, objective_delta: float) -> dict:
    people_n, fairness, delta, total = _score(candidate, objective_delta)
    return {'people': people_n, 'give_up': candidate['give_up'],
            'delta': round(delta, 3), 'fairness': fairness,
            'total': round(total, 3)}


def _line(candidate: dict, seed_title: str, when: str) -> str:
    asks = '; '.join(p['ask_text'] for p in candidate['parts'])
    return f"🤝 {seed_title} ({when}) works if — {asks}"


def _newly_conflicted(base_conflicts: dict, result_conflicts: dict) -> bool:
    """True if the replay broke something the baseline didn't already carry.

    Keyed by event id, not counted: a same-count TRADE -- event A's conflict
    resolves while a previously-clean event B, on somebody else, becomes newly
    conflicted -- has to disqualify the candidate even though the totals never
    move. `len(a) > len(b)` cannot see that; comparing which keys are present
    can. Each value is a list of the OTHER events colliding with that key, so
    where the data is there, a same-event conflict growing (two collisions
    becoming three) also disqualifies -- not just a new key appearing.

    NOTE: as of this writing `solve_pack.replay` calls `compute_conflicts`
    with an empty ghost-assignment map (`solve_pack.py:178`), so both sides of
    this comparison are always `{}` and this function currently never returns
    True. That is a real gap in the wiring, not this function's -- see
    `search()`'s docstring and the task report for why it is out of this
    module's scope to fix here.
    """
    for event_id, hits in (result_conflicts or {}).items():
        base_hits = (base_conflicts or {}).get(event_id)
        if base_hits is None or len(hits) > len(base_hits):
            return True
    return False


def search(pack: dict, seed_event_id: str, budget: int = SWEEP_BUDGET,
           exclude: set = None) -> list:
    """Solve down the candidate queue and return what actually worked.

    A candidate survives only if the seed ends up covered AND nothing else on
    the day was broken to do it. Validation is this one day, which is sound
    only because every lever is occurrence-scoped: none of them reaches another
    day's pack. If a series-level lever is ever added, this must widen with it.

    Every replay here runs inside `maps.travel_cache_only()`: none of the four
    levers can introduce a location the day's own solve did not already need,
    so a genuine miss means the original fetch failed or the cache emptied --
    and re-solving the same day dozens of times unattended is exactly the
    shape of the incident that guard exists to prevent. See its docstring.

    `budget` caps replay ATTEMPTS, not successes -- a candidate whose replay
    raises (an uncached travel pair, a solver timeout, anything) still spent
    one of the sweep's re-solves, and a queue that fails often must not be
    able to walk itself unbounded just because nothing it tried came back.
    """
    exclude = set(exclude or ())
    events = {str(e.get('id')): e for e in pack.get('events') or []}
    seed = events.get(str(seed_event_id))
    if not seed:
        return []
    seed_start = _dt(seed.get('start'))
    when = seed_start.strftime('%a %I:%M %p').replace(' 0', ' ') if seed_start else ''
    seed_title = seed.get('title') or 'That drive'

    try:
        with maps.travel_cache_only():
            base = solve_pack.replay(pack)
    except ValueError as e:
        print(f"[negotiation] no usable pack for {pack.get('date')}: {e}")
        return []
    except maps.UncachedTravelPair as e:
        print(f"[negotiation] baseline needs a travel pair the cache does "
              f"not have ({e}) -- refusing to buy it")
        return []
    baseline_broken = set(base['unassigned'])
    baseline_objective = base['objective']

    scored = []
    spent = 0
    for cand in candidates(pack, seed_event_id):
        if spent >= budget:
            break
        if any(part_key(p) in exclude for p in cand['parts']):
            continue
        # Counted here, before the solve, not after a successful return: the
        # budget is a ceiling on how many times this search is allowed to ask
        # the solver a question, and a replay that raises still asked it.
        spent += 1
        try:
            with maps.travel_cache_only():
                result = solve_pack.replay(solve_pack.apply(pack, cand['mutations']))
        except Exception as e:
            # Includes `maps.UncachedTravelPair` -- a candidate this replay
            # would have needed to buy a travel pair for is dropped exactly
            # like any other candidate that fails to solve, not special-cased.
            print(f"[negotiation] candidate failed: {e}")
            continue
        broken = set(result['unassigned'])
        if str(seed_event_id) in broken:
            continue
        # Nothing new may break. Something already broken that STAYS broken is
        # not this candidate's fault and does not disqualify it.
        if broken - baseline_broken:
            continue
        if _newly_conflicted(base.get('conflicts'), result.get('conflicts')):
            continue
        delta = baseline_objective - result['objective']
        scored.append((_rank(cand, delta),
                       {'mutations': cand['mutations'], 'parts': cand['parts'],
                        'cost': _cost(cand, delta),
                        'line': _line(cand, seed_title, when)}))
    scored.sort(key=lambda pair: pair[0])
    return [entry for _, entry in scored]


# --- The deal, and the way people agree to it ----------------------------
# Every part is agreed to by the person it costs. A schedule that works because
# somebody was volunteered is not a schedule that works, so a partly agreed
# deal changes nothing at all — not the calendar, not the overrides, nothing.


def propose(date_str: str, seed_event_id: str,
            budget: int = SWEEP_BUDGET) -> dict:
    """The best deal for this seed, stored as a draft. Nobody is asked yet.

    An open deal for the same seed is REUSED rather than re-solved: the sweep
    runs constantly, and re-searching a seed the family is already looking at
    would burn the budget re-deciding a question that is already on their
    screen.
    """
    for existing in storage.get_deals(seed_event_id=seed_event_id):
        if existing.get('state') in ('draft', 'asking'):
            return existing
    pack = storage.get_solve_pack(date_str)
    if not pack:
        return None
    found = search(pack, seed_event_id, budget=budget)
    if not found:
        return None
    best = found[0]
    events = {str(e.get('id')): e for e in pack.get('events') or []}
    seed = events.get(str(seed_event_id)) or {}
    parts = []
    for i, p in enumerate(best['parts']):
        parts.append({**p, 'id': f"{seed_event_id}-{i}-{int(datetime.datetime.now().timestamp())}",
                      'state': 'open', 'request_id': None})
    deal_id = storage.add_deal({
        'date': date_str, 'seed_event_id': str(seed_event_id),
        'seed_title': seed.get('title') or '', 'line': best['line'],
        'parts': parts, 'cost': best['cost'], 'mutations': best['mutations'],
        'state': 'draft'})
    return storage.get_deal(deal_id)


def start_asks(deal_id: str, actor_member_id: str = None) -> dict:
    """Send the asks. A person does this — never the sweep, never the model."""
    from services import requests as _req
    deal = storage.get_deal(deal_id)
    if not deal:
        return {'status': 'error', 'message': 'That deal is no longer here.'}
    if deal.get('state') != 'draft':
        return {'status': 'error',
                'message': f"That one is already {deal.get('state')}."}
    parts = []
    for p in deal.get('parts') or []:
        req = _req.create(from_member_id=actor_member_id or '',
                          body=p['ask_text'], kind='deal_part',
                          to_member_id=p['member_id'], subject_ref=p['id'],
                          subject_label=deal.get('seed_title') or 'the schedule')
        parts.append({**p, 'request_id': (req or {}).get('id')})
    storage.update_deal(deal_id, {'parts': parts, 'state': 'asking'})
    who = len({p['member_id'] for p in parts})
    return {'status': 'success', 'deal_id': deal_id,
            'message': f"Asked {who} {'person' if who == 1 else 'people'} — "
                       f"nothing changes until everyone says yes."}


def accept_part(part_id: str, member_id: str = None) -> dict:
    deal = storage.get_deal_by_part(part_id)
    if not deal:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if deal.get('state') != 'asking':
        return {'status': 'error',
                'message': f"That deal is {deal.get('state')} — nothing to agree to."}
    storage.update_deal_part(part_id, {'state': 'accepted'})
    deal = storage.get_deal(deal['id'])
    if any(p.get('state') != 'accepted' for p in deal.get('parts') or []):
        waiting = [p['member_id'] for p in deal['parts']
                   if p.get('state') != 'accepted']
        return {'status': 'success', 'applied': False,
                'message': f"Got it — still waiting on {len(waiting)}."}
    for p in deal['parts']:
        try:
            _apply_part(p, deal)
        except Exception as e:
            print(f"[negotiation] applying {p.get('lever')} failed: {e}")
            storage.update_deal(deal['id'], {
                'state': 'dead',
                'dead_reason': f"couldn't apply the {p.get('lever')} part: {e}"})
            return {'status': 'error',
                    'message': "Everyone agreed, but I couldn't make the "
                               "change — worth a look."}
    storage.update_deal(deal['id'], {
        'state': 'applied',
        'applied_at': datetime.datetime.now().timestamp()})
    return {'status': 'success', 'applied': True, 'schedule_dirty': True,
            'message': f"✓ {deal.get('seed_title') or 'That day'} is covered."}


def decline_part(part_id: str, member_id: str = None, reason: str = '') -> dict:
    """A no ends the deal — blamelessly, and with the reason kept.

    A refused shift also teaches the app something permanent: that series
    cannot move. That is the movable flag, earned rather than declared.
    """
    deal = storage.get_deal_by_part(part_id)
    if not deal:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    part = next((p for p in deal.get('parts') or []
                 if str(p.get('id')) == str(part_id)), None)
    storage.update_deal_part(part_id, {'state': 'declined'})
    if part and part.get('lever') == 'shift_event':
        payload = part.get('payload') or {}
        if payload.get('series_key'):
            storage.add_shift_refusal(payload['series_key'],
                                      payload.get('title') or '',
                                      member_id)
    storage.update_deal(deal['id'], {
        'state': 'dead',
        'dead_reason': (reason or '').strip() or 'somebody could not'})
    return {'status': 'success', 'message': "That's fine — I'll look again."}


def kill(deal_id: str, member_id: str = None, reason: str = '') -> dict:
    deal = storage.get_deal(deal_id)
    if not deal:
        return {'status': 'error', 'message': 'That deal is no longer here.'}
    storage.update_deal(deal_id, {'state': 'dead',
                                  'dead_reason': (reason or '').strip() or 'dropped'})
    return {'status': 'success', 'message': 'Dropped it.'}


def _apply_part(part: dict, deal: dict):
    """Make the change this part promised. Called only when EVERY part is in."""
    from services import calendar as _cal, optional_events as _opt
    lever, payload = part.get('lever'), part.get('payload') or {}
    if lever == 'shift_event':
        sched = storage.get_cached_schedule() or {}
        ev = next((e for e in (sched.get('events') or [])
                   if str(e.get('id')) == str(payload.get('event_id'))), None)
        if not ev:
            raise ValueError('that event is no longer in the schedule')
        delta = datetime.timedelta(minutes=int(payload.get('delta_mins') or 0))
        # `source_event_ids` entries are "calendar_id::google_event_id"
        # (services/calendar.py's fetch groups every event this way), not a
        # bare Google id -- patch_event needs the id AFTER the '::', or the
        # write 404s against a calendar that has no event by that composite
        # name. Both halves come from the SAME string so they can never
        # point at mismatched calendars, unlike zipping calendar_ids[0]
        # against source_event_ids[0] from two separately-ordered lists.
        raw_src = (ev.get('source_event_ids') or [ev.get('id')])[0]
        src_parts = str(raw_src).split('::', 1)
        cal_id, google_id = (src_parts[0], src_parts[1]) if len(src_parts) == 2 else (None, None)
        if not cal_id or not google_id:
            raise ValueError('that event has no calendar to write to')
        # `_dt` (this module's own helper) strips tzinfo -- fine for the
        # relative-time arithmetic candidates() does, but a naive dateTime
        # sent to Google is REJECTED outright ("Missing time zone
        # definition"). Keep the real offset, and stamp the calendar's own
        # IANA zone too (chat_actions._create_event does the same) so the
        # event isn't left pinned to a fixed GMT offset in the edit UI.
        tz = _cal.get_calendar_timezone(cal_id)
        body = {}
        for field in ('start', 'end'):
            try:
                raw = datetime.datetime.fromisoformat(str(ev.get(field)))
            except (ValueError, TypeError):
                raw = None
            if raw:
                entry = {'dateTime': (raw + delta).isoformat()}
                if tz:
                    entry['timeZone'] = tz
                body[field] = entry
        if not body or not _cal.patch_event(cal_id, google_id, body):
            raise ValueError('the calendar refused the new time')
    elif lever == 'lift_protected':
        storage.add_protected_exception(payload.get('commitment_id'),
                                        deal.get('date'))
    elif lever == 'swap_drive':
        storage.add_override({'event_id': str(payload.get('event_id')),
                              'driver_id': str(payload.get('driver_id')),
                              'created_at': datetime.datetime.now().timestamp(),
                              'source': 'negotiation'})
    elif lever == 'skip_optional':
        sched = storage.get_cached_schedule() or {}
        ev = next((e for e in (sched.get('events') or [])
                   if str(e.get('id')) == str(payload.get('event_id'))), None)
        if not ev:
            raise ValueError('that event is no longer in the schedule')
        _opt.record_decision(ev, 'skip', decided_by=part.get('member_id'))
    else:
        raise ValueError(f"unknown lever '{lever}'")
