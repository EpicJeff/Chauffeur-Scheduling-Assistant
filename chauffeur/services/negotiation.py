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

GIVE_UP = {'shift_15': 1, 'shift_30': 2, 'skip_optional': 2,
           'swap_drive': 3, 'lift_protected': 5}


def _dt(raw):
    try:
        return datetime.datetime.fromisoformat(str(raw)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _aware_dt(raw):
    """The same parse as `_dt`, but keeping whatever offset was written down.

    `_dt` strips tzinfo, which is right for the relative arithmetic candidate
    generation does and wrong for anything that has to survive as an ABSOLUTE
    time -- the target a person actually agreed to, and the comparison that
    proves the event is still where the ask said it was.
    """
    try:
        return datetime.datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None


def _same_moment(a, b) -> bool:
    """Is this the same start time, written two ways?

    A pack event and a cached event are two dumps of the same record and
    normally carry byte-identical strings, but a naive/aware mismatch would
    make a plain `==` say 'moved' about an event that never moved. Compare
    instants when both sides know their offset, wall times when they do not.
    """
    da, db = _aware_dt(a), _aware_dt(b)
    if da is None or db is None:
        return str(a) == str(b)
    if (da.tzinfo is None) != (db.tzinfo is None):
        return da.replace(tzinfo=None) == db.replace(tzinfo=None)
    return da == db


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


def candidates(pack: dict, seed_event_id: str, assignments: dict = None) -> list:
    """Every change worth trying for this seed, cheapest first.

    Ordering happens HERE, before anything is solved, because the budget is a
    cutoff on this list: the sweep's few solves must be spent on the most
    promising deals, not on a random sample of them.

    `assignments` is THIS day's result -- who the solver actually put on what
    -- and `search()` passes the baseline replay's own map. It is not
    optional in spirit: `previous_assignments` is the stickiness INPUT (the
    last refresh's map plus this run's earlier days), so on a first refresh,
    after a cache clear, or for a newly added event it is empty or stale and
    the `swap_drive` lever finds nobody to free. Falling back to it here is a
    last resort for a caller with nothing better, not the intended path.
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
    # The smaller step is a setting (default 15); the larger step is always
    # double it, so a family that wants coarser moves gets both from one dial.
    shift_mins = int(storage.get_settings().get('negotiation_shift_mins', 15) or 15)
    shift_steps = (-shift_mins, shift_mins, -shift_mins * 2, shift_mins * 2)
    out = []

    # --- shift a neighbour, or the seed itself -----------------------------
    for ev in [seed] + [e for e in events.values()
                        if str(e.get('id')) != str(seed_event_id)]:
        if not _in_window(ev, seed_start, seed_end):
            continue
        if series_key(ev) in refused:
            continue
        # An event this app cannot write to cannot be moved, however well the
        # re-solve goes. Discovering that only in `_check_part` -- AFTER every
        # person in the deal has agreed -- spends a family's goodwill on a
        # change that was never possible, so the queue never carries one.
        cal_id, google_id = _calendar_address(ev)
        raw_start, raw_end = _aware_dt(ev.get('start')), _aware_dt(ev.get('end'))
        if not cal_id or not google_id or not raw_start or not raw_end:
            continue
        owner = _owner_of(ev, pack)
        start = _dt(ev.get('start'))
        for delta in shift_steps:
            cost = GIVE_UP['shift_15' if abs(delta) == shift_mins else 'shift_30']
            when = start + datetime.timedelta(minutes=delta)
            direction = 'later' if delta > 0 else 'earlier'
            step = datetime.timedelta(minutes=delta)
            out.append({
                'mutations': [{'lever': 'shift_event',
                               'event_id': str(ev.get('id')),
                               'delta_mins': delta}],
                'give_up': cost,
                # The ask quotes an ABSOLUTE time ("to 5:15"), so that is what
                # gets written down and later applied. `delta_mins` alone is a
                # promise about a starting point that may not still be there:
                # if the event moves between the ask and the last yes, adding
                # the delta again lands somewhere nobody agreed to. `from_start`
                # is the starting point the ask assumed, and `_check_part`
                # refuses the whole deal if the event has left it.
                'parts': [{'member_id': owner, 'lever': 'shift_event',
                           'payload': {'event_id': str(ev.get('id')),
                                       'series_key': series_key(ev),
                                       'title': ev.get('title') or 'that',
                                       'delta_mins': delta,
                                       'from_start': raw_start.isoformat(),
                                       'target_start': (raw_start + step).isoformat(),
                                       'target_end': (raw_end + step).isoformat()},
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
    # THIS day's assignments, not the stickiness input. `driver_options` reads
    # this map to say who is busy and on what, and the whole `swap_drive`
    # lever hangs off that answer -- handed `previous_assignments` it reasons
    # about a day that is one refresh old, or (first refresh, cleared cache,
    # new event) about no day at all.
    cache = {'events': list(events.values()),
             'assignments': dict(assignments if assignments is not None
                                 else (pack.get('previous_assignments') or {}))}
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


def fairness_counts() -> dict:
    """Everybody's recent give-ups, from ONE pass over the deals table.

    `storage.get_deals` deserialises the whole table, and scoring asks about
    fairness twice per surviving candidate, once per person -- a hundred-odd
    whole-table scans for one tap if each question is answered on its own. One
    scan, one dict, handed down through `search()`.
    """
    since = datetime.datetime.now().timestamp() - FAIRNESS_DAYS * 86400
    counts = {}
    for d in storage.get_deals(since_ts=since):
        for p in d.get('parts') or []:
            mid = str(p.get('member_id'))
            counts[mid] = counts.get(mid, 0) + 1
    return counts


def _fairness(member_id: str, counts: dict = None) -> int:
    """How many times this person has been asked to give something up lately.

    Counted from recorded deals, so it is a real count. Nothing here is
    estimated — a made-up fairness number would be worse than none.
    """
    if counts is None:
        counts = fairness_counts()
    return counts.get(str(member_id), 0)


def _score(candidate: dict, objective_delta: float, counts: dict = None):
    """The one place people/fairness/delta/total get computed. `_rank` and
    `_cost` both call this rather than each doing their own arithmetic --
    two implementations of the same decision is how a sort order and the
    numbers shown for it quietly drift apart."""
    if counts is None:
        counts = fairness_counts()
    people = sorted({p['member_id'] for p in candidate['parts']})
    fairness = sum(_fairness(m, counts) for m in people)
    delta = min(max(objective_delta, 0.0) / DELTA_SCALE, DELTA_CAP)
    total = candidate['give_up'] + delta + fairness
    return len(people), fairness, delta, total


def _rank(candidate: dict, objective_delta: float, counts: dict = None):
    """The sort key. People disturbed comes first and is not tradeable."""
    people_n, _fairness_n, _delta, total = _score(candidate, objective_delta, counts)
    return (people_n, total)


def _cost(candidate: dict, objective_delta: float, counts: dict = None) -> dict:
    people_n, fairness, delta, total = _score(candidate, objective_delta, counts)
    return {'people': people_n, 'give_up': candidate['give_up'],
            'delta': round(delta, 3), 'fairness': fairness,
            'total': round(total, 3)}


def _line(candidate: dict, seed_title: str, when: str) -> str:
    asks = '; '.join(p['ask_text'] for p in candidate['parts'])
    return f"🤝 {seed_title} ({when}) works if — {asks}"


def search(pack: dict, seed_event_id: str, budget: int = SWEEP_BUDGET,
           exclude: set = None) -> list:
    """Solve down the candidate queue and return what actually worked.

    A candidate survives only if the seed ends up covered AND nothing else on
    the day was broken to do it. Validation is this one day, which is sound
    only because every lever is occurrence-scoped: none of them reaches another
    day's pack. If a series-level lever is ever added, this must widen with it.

    "Nothing else was broken" means, precisely, that no event which solved in
    the baseline goes unassigned in the replay. There is deliberately no
    separate conflict check: CP-SAT will not double-book a real driver, so the
    only way a mutation can break a solve is by leaving an event uncovered --
    which is exactly what this compares. (An earlier draft carried a conflict
    comparison as well. `matcher.compute_conflicts` pairs assignments against
    GHOST routes, and replaying ghost routes for every candidate would roughly
    double the cost of this hot path to re-check something the unassigned
    comparison already catches, so it was dropped rather than wired up.)

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

    # Per-replay time limit -- a search runs many of these for one question,
    # so it gets a shorter leash than the daily solve (solve_pack's own
    # default). Configurable because a bigger day may need more of it.
    time_limit_s = float(storage.get_settings().get(
        'negotiation_solve_seconds', solve_pack.DEFAULT_TIME_LIMIT_S)
        or solve_pack.DEFAULT_TIME_LIMIT_S)

    try:
        with maps.travel_cache_only():
            base = solve_pack.replay(pack, time_limit_s=time_limit_s)
    except ValueError as e:
        print(f"[negotiation] no usable pack for {pack.get('date')}: {e}")
        return []
    except maps.UncachedTravelPair as e:
        print(f"[negotiation] baseline needs a travel pair the cache does "
              f"not have ({e}) -- refusing to buy it")
        return []
    # A baseline that did not actually solve answers a different question, and
    # `solve_schedule` reports a timeout by calling EVERY event unassigned.
    # Taken at face value that makes `baseline_broken` the whole day, after
    # which `broken - baseline_broken` is empty for every candidate and the
    # "nothing new breaks" check silently waves everything through -- on a big
    # day, which is exactly the day negotiation exists for. Same principle as
    # the drifted-pack refusal above: an answer to a different question is
    # worse than no answer.
    if base['status'] not in ('OPTIMAL', 'FEASIBLE'):
        print(f"[negotiation] baseline replay for {pack.get('date')} came back "
              f"{base['status']} -- refusing to validate candidates against it")
        return []
    baseline_broken = set(base['unassigned'])
    baseline_objective = base['objective']
    counts = fairness_counts()

    scored = []
    spent = 0
    for cand in candidates(pack, seed_event_id, assignments=base['assignments']):
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
                result = solve_pack.replay(solve_pack.apply(pack, cand['mutations']),
                                           time_limit_s=time_limit_s)
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
        delta = baseline_objective - result['objective']
        scored.append((_rank(cand, delta, counts),
                       {'mutations': cand['mutations'], 'parts': cand['parts'],
                        'cost': _cost(cand, delta, counts),
                        'line': _line(cand, seed_title, when)}))
    scored.sort(key=lambda pair: pair[0])
    return [entry for _, entry in scored]


# --- The day's rules, with any lift for THAT date already taken out --------
# `main.py`'s per-day loop needs this every refresh; pulled out as a pure
# function (rules + index + today's exceptions in, filtered pair out) so the
# index math -- the exact thing that makes the pack's rules and its
# rule-index agree with each other -- is provable without going through
# `_refresh_schedule_logic_impl`.

def day_rules_for(date_str: str, rules: list, protected_rule_index: dict):
    """This date's rule list and rule-index, with every commitment lifted for
    THIS date dropped. The standing rule stays in `rules` for every other day
    -- only the copy handed to this date's solve (and this date's pack) is
    missing it.
    """
    lifted = {str(x['commitment_id'])
              for x in storage.get_protected_exceptions()
              if str(x.get('date')) == date_str}
    if not lifted:
        return list(rules), dict(protected_rule_index)
    drop = {protected_rule_index[c] for c in lifted if c in protected_rule_index}
    day_rules = [r for i, r in enumerate(rules) if i not in drop]
    # Every surviving commitment's index shifts down by however many DROPPED
    # rules sat before it -- walked in `rules` order (dict insertion order,
    # since each commitment's index was assigned by `len(rules)` at the point
    # it was appended, so earlier commitments were inserted first).
    day_protected_index = {}
    offset = 0
    for cid, idx in protected_rule_index.items():
        if cid in lifted:
            offset += 1
            continue
        day_protected_index[cid] = idx - offset
    return day_rules, day_protected_index


# --- The deal, and the way people agree to it ----------------------------
# Every part is agreed to by the person it costs. A schedule that works because
# somebody was volunteered is not a schedule that works, so a partly agreed
# deal changes nothing at all — not the calendar, not the overrides, nothing.


# How long a refused part keeps excluding itself, and how long a "nothing
# works" answer stays believed. Both are memory about one occurrence, and the
# occurrence itself is days away at most.
MEMORY_DAYS = 14

# Where the "I already looked and there was nothing" memo lives. Keyed by seed
# AND by the pack's identity, so the answer is only reused while the world it
# was computed from is still the world.
_NO_DEAL_KEY = 'negotiation_no_deal'


def _refused_part_keys(seed_event_id: str) -> set:
    """Everything a person has already said no to for this seed.

    Rule 5 of the design: one decline kills the deal and the RUNNER-UP is
    offered — the next candidate down the queue that does not contain the
    refused part. The runner-up arrives on the next `propose()`, so the
    refusal has to be carried across it. Without this, three of the four
    levers (only `shift_event` writes a series refusal) would re-propose the
    identical deal on the next sweep and re-ask the person who just declined.
    """
    since = datetime.datetime.now().timestamp() - MEMORY_DAYS * 86400
    out = set()
    for d in storage.get_deals(seed_event_id=seed_event_id, since_ts=since):
        if d.get('state') in ('dead', 'expired'):
            out.update(str(k) for k in (d.get('refused_parts') or []))
    return out


def _no_deal_memo() -> dict:
    memo = storage.get_app_state(_NO_DEAL_KEY) or {}
    return memo if isinstance(memo, dict) else {}


def _remember_no_deal(seed_event_id: str, pack: dict):
    """A hopeless seed is remembered against the pack that made it hopeless.

    The sweep runs every half hour for the whole 14-day watch window, and a
    genuinely broken day is the COMMON case for an uncovered event — so
    without this, one such event costs a baseline plus up to eight replays,
    forty-eight times a day, forever, always reaching the same answer. The
    memo clears itself the moment the refresh writes a new pack, because
    that is the only thing that can change the answer.
    """
    now = datetime.datetime.now().timestamp()
    memo = {k: v for k, v in _no_deal_memo().items()
            if isinstance(v, dict) and (v.get('at') or 0) > now - MEMORY_DAYS * 86400}
    memo[str(seed_event_id)] = {'pack': pack.get('written_at'), 'at': now}
    storage.set_app_state(_NO_DEAL_KEY, memo)


def _already_hopeless(seed_event_id: str, pack: dict) -> bool:
    entry = _no_deal_memo().get(str(seed_event_id))
    return bool(entry and entry.get('pack') == pack.get('written_at'))


def propose(date_str: str, seed_event_id: str,
            budget: int = SWEEP_BUDGET) -> dict:
    """The best deal for this seed, stored as a draft. Nobody is asked yet.

    An open deal for the same seed is REUSED rather than re-solved: the sweep
    runs constantly, and re-searching a seed the family is already looking at
    would burn the budget re-deciding a question that is already on their
    screen. A `dead` or `expired` deal is NOT reused — the whole point of one
    is that this seed needs looking at again — but what it was refused for is
    carried forward as an exclusion.
    """
    for existing in storage.get_deals(seed_event_id=seed_event_id):
        if existing.get('state') in ('draft', 'asking'):
            return existing
    pack = storage.get_solve_pack(date_str)
    if not pack:
        return None
    if _already_hopeless(seed_event_id, pack):
        return None
    found = search(pack, seed_event_id, budget=budget,
                   exclude=_refused_part_keys(seed_event_id))
    if not found:
        _remember_no_deal(seed_event_id, pack)
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


# A calendar write is the one part-application step that reaches another
# system and can fail for reasons nothing here can predict in advance. Every
# other lever only ever touches this app's own storage, so it is cheap,
# local, and about as close to certain-to-succeed as a write gets. Applying
# those first and the calendar write last means a real failure leaves at
# most local state -- state a person can see in the app and undo by hand --
# rather than a half-moved calendar sitting behind a deal that failed before
# it got there.
_EXTERNAL_LEVERS = {'shift_event'}


def _close_open_requests(deal: dict, status: str) -> int:
    """A deal that is over takes its unanswered asks with it.

    Nothing can come of answering half of a dead deal, and an ask that
    outlives its reason is exactly the thing `services/requests.py` exists to
    prevent — so the siblings are closed here rather than left to grind
    through their own 20h TTL and then DM two people about a deal that ended
    yesterday.
    """
    n = 0
    for p in deal.get('parts') or []:
        rid = p.get('request_id')
        if not rid:
            continue
        req = storage.get_request(rid)
        if not req or req.get('status') != 'open':
            continue
        storage.update_request(rid, {'status': status})
        n += 1
    return n


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

    # CLAIM the deal before touching anything. Two people can answer the last
    # two parts in the same second (FastAPI runs sync handlers in a
    # threadpool), and everything between "all parts accepted" and
    # `state='applied'` — a Google Calendar round trip included — is a window
    # both of them could walk through, applying the deal twice: an event
    # shifted 15 minutes twice is an event 30 minutes from where anybody
    # agreed. Whoever flips `asking` → `applying` owns the apply; the other is
    # told it is already going through and does nothing.
    if not storage.claim_deal(deal['id'], 'asking', 'applying'):
        return {'status': 'success', 'applied': False,
                'message': "Got it — that was the last one; it's going through now."}

    parts = deal.get('parts') or []

    # Pre-flight EVERY part before applying ANY of them. Most of the ways a
    # part can fail -- the event got cancelled since the deal was proposed,
    # a commitment was deleted, a driver no longer exists -- are visible
    # without touching anything, and catching them here means the deal that
    # cannot fully go through applies nothing at all, exactly like a decline
    # would have.
    for p in parts:
        reason = _check_part(p)
        if reason:
            storage.update_deal(deal['id'], {
                'state': 'dead',
                'dead_reason': f"couldn't apply the {p.get('lever')} part: {reason}"})
            return {'status': 'error',
                    'message': f"Everyone agreed, but {reason} — nothing was changed."}

    # Local levers first, the calendar write last (see _EXTERNAL_LEVERS).
    ordered = sorted(parts, key=lambda p: p.get('lever') in _EXTERNAL_LEVERS)
    done = []
    for p in ordered:
        try:
            _apply_part(p, deal)
        except Exception as e:
            print(f"[negotiation] applying {p.get('lever')} failed: {e}")
            # The record has to say exactly how far this got: a part already
            # marked applied here really did happen and was not rolled back
            # -- there is no undo for a calendar write already sent -- so the
            # deal's own data has to be the thing that lets a person work out
            # what to fix by hand.
            already = ', '.join(done)
            storage.update_deal(deal['id'], {
                'state': 'dead',
                'dead_reason': (f"{already + ' already went through; then ' if already else ''}"
                                f"the {p.get('lever')} part failed: {e}")})
            message = ("Everyone agreed, and part of it already happened, "
                       "but I couldn't finish — worth a look."
                       if done else
                       "Everyone agreed, but I couldn't make the change — "
                       "worth a look.")
            return {'status': 'error', 'message': message}
        storage.update_deal_part(p['id'], {'applied': True})
        done.append(p.get('lever'))

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
    # What was refused rides on the deal, so the NEXT search for this seed can
    # skip it and offer the runner-up instead of re-asking the person who just
    # said no. A shift also teaches the series-level flag above, but the other
    # three levers have nowhere else to record a no.
    refused = list(deal.get('refused_parts') or [])
    if part:
        key = part_key(part)
        if key not in refused:
            refused.append(key)
    storage.update_deal(deal['id'], {
        'state': 'dead', 'refused_parts': refused,
        'dead_reason': (reason or '').strip() or 'somebody could not'})
    _close_open_requests(storage.get_deal(deal['id']) or deal, 'cancelled')
    return {'status': 'success', 'message': "That's fine — I'll look again."}


def kill(deal_id: str, member_id: str = None, reason: str = '') -> dict:
    deal = storage.get_deal(deal_id)
    if not deal:
        return {'status': 'error', 'message': 'That deal is no longer here.'}
    storage.update_deal(deal_id, {'state': 'dead',
                                  'dead_reason': (reason or '').strip() or 'dropped'})
    _close_open_requests(deal, 'cancelled')
    return {'status': 'success', 'message': 'Dropped it.'}


def expire_part(part_id: str) -> dict:
    """Nobody answered in time, so the deal is over.

    `services/requests.py` expires an unanswered ask after its TTL and tells
    both parties — but the deal itself heard nothing, so before this existed a
    deal sat in `asking` forever: `propose()` kept handing that stranded deal
    back instead of searching, `watchers._deal_line` kept printing "N of M
    said yes, waiting on the rest" with nothing to tap, and the coverage
    ladder — somebody is free / an outside hand covered this / here is why
    nobody can — never came back for that event. An expired deal is a dead
    deal in every way that matters; the separate state is only so a person
    reading the record can tell "nobody answered" from "somebody said no".
    """
    deal = storage.get_deal_by_part(part_id)
    if not deal:
        return {'status': 'error', 'message': 'That ask is no longer here.'}
    if deal.get('state') not in ('draft', 'asking'):
        return {'status': 'success', 'message': f"Already {deal.get('state')}."}
    storage.update_deal(deal['id'], {
        'state': 'expired',
        'dead_reason': 'nobody answered in time'})
    _close_open_requests(storage.get_deal(deal['id']) or deal, 'expired')
    return {'status': 'success', 'deal_id': deal['id'],
            'message': 'That deal ran out of time.'}


def _cached_event(event_id) -> dict:
    sched = storage.get_cached_schedule() or {}
    return next((e for e in (sched.get('events') or [])
                 if str(e.get('id')) == str(event_id)), None)


def _calendar_address(ev: dict):
    """(calendar_id, bare google event id) this event actually writes to, or
    (None, None) if it isn't addressable.

    `source_event_ids` entries are "calendar_id::google_event_id"
    (services/calendar.py's fetch groups every event this way), not a bare
    Google id -- patch_event needs the id AFTER the '::', or the write 404s
    against a calendar that has no event by that composite name. Both halves
    come from the SAME string so they can never point at mismatched
    calendars, unlike zipping calendar_ids[0] against source_event_ids[0]
    from two separately-ordered lists.
    """
    raw_src = (ev.get('source_event_ids') or [ev.get('id')])[0]
    parts = str(raw_src).split('::', 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None, None


def _shift_body(ev: dict, payload: dict, tz: str = None):
    """The patch body that moves this event where the ask said, or None if
    either endpoint can't be read.

    The times come from the payload when the payload has them: the ask quoted
    an absolute clock time ("could Piano move to 5:15?") and that is what the
    person agreed to. Re-deriving it by adding `delta_mins` to whatever the
    event's start happens to be at apply time would honour the arithmetic and
    break the promise. `delta_mins` remains the fallback for deals written
    before the target was recorded.

    BOTH endpoints are required, not just whichever parses: a body with only
    `start` would move the start of a real calendar event and silently
    garble its duration, which is worse than refusing the write outright.

    `_dt` (this module's own helper, used by candidates()/search()) strips
    tzinfo -- fine for the relative-time arithmetic those do, but a naive
    dateTime sent to Google is REJECTED outright ("Missing time zone
    definition"). This keeps the real offset, and stamps the calendar's own
    IANA zone too (chat_actions._create_event does the same) so the event
    isn't left pinned to a fixed GMT offset in the edit UI.
    """
    payload = payload or {}
    delta = datetime.timedelta(minutes=int(payload.get('delta_mins') or 0))
    body = {}
    for field in ('start', 'end'):
        target = _aware_dt(payload.get(f'target_{field}'))
        if target is None:
            raw = _aware_dt(ev.get(field))
            if raw is None:
                return None
            target = raw + delta
        # An event whose own endpoints cannot be read has nothing to patch
        # against, target or no target.
        if _aware_dt(ev.get(field)) is None:
            return None
        entry = {'dateTime': target.isoformat()}
        if tz:
            entry['timeZone'] = tz
        body[field] = entry
    return body


def _check_part(part: dict) -> str:
    """Would this part's side effect actually be possible right now, without
    changing anything? '' when yes, else a reason a person would recognise.

    Called on EVERY part before ANY of them apply (see accept_part): the
    time between a deal being proposed and its last yes is real time, and an
    event can be cancelled, a commitment deleted, or a driver removed in
    between. Catching that here is what keeps a deal that cannot fully go
    through from applying part of itself anyway.
    """
    lever, payload = part.get('lever'), part.get('payload') or {}
    if lever == 'shift_event':
        ev = _cached_event(payload.get('event_id'))
        if not ev:
            return 'that event is no longer in the schedule'
        cal_id, google_id = _calendar_address(ev)
        if not cal_id or not google_id:
            return 'that event has no calendar to write to'
        if _shift_body(ev, payload) is None:
            return "that event's time could not be read"
        # The ask named a time ("to 5:15") computed from where the event was
        # when it was asked. If it has moved since, that sentence is no longer
        # true about anything and the agreement was to a different change --
        # so the deal dies rather than writing a time nobody said yes to.
        if payload.get('from_start') and not _same_moment(ev.get('start'),
                                                          payload['from_start']):
            return 'that event has already moved since everyone was asked'
    elif lever == 'lift_protected':
        cid = str(payload.get('commitment_id') or '')
        if not any(str(pc.get('id')) == cid
                   for pc in storage.get_protected_commitments()):
            return 'that commitment is no longer here'
    elif lever == 'swap_drive':
        drv = str(payload.get('driver_id') or '')
        if not any(str(m.get('driver_id')) == drv
                   for m in storage.get_all_members()):
            return 'that driver is no longer set up to drive'
    elif lever == 'skip_optional':
        if not _cached_event(payload.get('event_id')):
            return 'that event is no longer in the schedule'
    else:
        return f"'{lever}' isn't a lever this app knows"
    return ''


def _apply_part(part: dict, deal: dict):
    """Make the change this part promised. Called only after every part in
    the deal has passed `_check_part`."""
    from services import calendar as _cal, optional_events as _opt
    lever, payload = part.get('lever'), part.get('payload') or {}
    if lever == 'shift_event':
        ev = _cached_event(payload.get('event_id'))
        if not ev:
            raise ValueError('that event is no longer in the schedule')
        cal_id, google_id = _calendar_address(ev)
        if not cal_id or not google_id:
            raise ValueError('that event has no calendar to write to')
        tz = _cal.get_calendar_timezone(cal_id)
        body = _shift_body(ev, payload, tz)
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
        ev = _cached_event(payload.get('event_id'))
        if not ev:
            raise ValueError('that event is no longer in the schedule')
        _opt.record_decision(ev, 'skip', decided_by=part.get('member_id'))
    else:
        raise ValueError(f"unknown lever '{lever}'")
