"""Family vitals — the pulse the Mind reads.

Everything else in this app measures LEVELS: this event is unassigned, that
list has nine items. A level is a fact. A vital sign is a level measured
against *this family's own baseline*, where the meaning lives in the
derivative — which is why "Ellie has six activities" is a fact and "Ellie's
load has run 40% over her own baseline for eleven days" is a finding.

Seven signs, all computed from data the app already keeps:

- load            per person: driving, plus doing (tasks, findings) and
                  carrying (each open thread, every day it stays open)
- margin          household: free waking minutes left after commitments
- follow_through  household: routine checks and tasks landed vs let go
- rest            household: first commitment of the day, empty evenings
- friction        household: rides that reached their day uncovered, cancels,
                  and the scrambles tallied live in `day_counters`
- together        household: meals eaten together, moments caught, kids who
                  rode somewhere with a parent
- progress        per person: program sessions actually logged that day —
                  the one sign that can measure a family WINNING rather than
                  surviving what it was handed

A day's measures ride along inside the existing `daily_stats` row (written
nightly by family_digest.record_daily_stats), so the pulse costs one extra
computation on a job that already runs and never a table of its own.

Nothing here compares one family to another, and nothing compares one PERSON
to another — every reading is against that same subject's own past. The
comparison the pulse must never make is the one that turns instrumentation
into a scoreboard.
"""
import datetime
import logging
import statistics

from services import storage

logger = logging.getLogger(__name__)

WINDOW_DAYS = 56        # ~8 weeks: long enough to hold a season's shape
CURRENT_DAYS = 7        # the near window that counts as "now"
MIN_HISTORY_DAYS = 21   # below this, report levels and refuse a delta
WAKING_START = 7        # the day a family is actually awake for
WAKING_END = 22
EVENING_FROM = 17       # an "evening" commitment starts at or after this
TASK_MINUTES = 15       # a finished household task, as minutes of doing
FINDING_MINUTES = 5     # noticing and resolving something is load too
THREAD_MINUTES = 10     # per open thread per day: holding a loop costs
                        # attention every day it stays open, the invisible
                        # mental load the pulse was missing

HOUSEHOLD_SIGNS = ('margin', 'follow_through', 'rest', 'friction', 'together')

# Every kind of scramble, tallied live by storage.bump_day_counter as it
# happens (the nightly row is written once, so a during-the-day count needs
# its own rail). See _FRICTION_KEYS for what folds into the sign.
FRICTION_COUNTERS = ('arrival_nudge', 'late_override', 'coverage_ask')
_FRICTION_KEYS = ('unassigned', 'canceled') + FRICTION_COUNTERS

# Which direction is bad news, so the Mind can be told plainly.
_WORSE_WHEN = {'margin': 'down', 'follow_through': 'down',
               'friction': 'up', 'load': 'up', 'rest': 'down',
               'together': 'down', 'progress': 'down'}

# Signs that must never be phrased as a run of days. `progress` counts a
# person's own practice sessions, and a consecutive-days count over that is a
# streak by any other name.
_NO_RUN = {'progress'}


def _day_str(d):
    return d.isoformat() if hasattr(d, 'isoformat') else str(d)[:10]


def _parse(ts):
    """A cached-schedule timestamp, or None. Naive — everything in the cache
    is local time and comparing across a DST edge is not worth a tz stack."""
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------- one day

def measure_day(date_str: str, sched: dict = None) -> dict:
    """The day's raw vital measures. Merged into that day's daily_stats row
    by record_daily_stats — this function never writes."""
    from services import cancellations as _canc
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = sched.get('events') or []
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})

    committed = 0
    first_hour = None
    evening = False
    unassigned = 0
    canceled = 0
    driving = {}
    kid_rides = 0
    kid_pax = {p for m in storage.get_all_members()
               if m.get('role') == 'child' and m.get('passenger_id')
               for p in [m['passenger_id']]}

    for e in events:
        start = _parse(e.get('start'))
        if not start or start.date().isoformat() != date_str:
            continue
        if _canc.is_canceled_title(e.get('title')):
            canceled += 1
            continue
        end = _parse(e.get('end')) or start
        mins = max(0, int((end - start).total_seconds() // 60))
        committed += mins
        if first_hour is None or start.hour < first_hour:
            first_hour = start.hour
        if start.hour >= EVENING_FROM:
            evening = True
        d_id = assignments.get(e.get('id'))
        if not d_id:
            unassigned += 1
        elif not str(d_id).startswith('ghost_'):
            driving[str(d_id)] = driving.get(str(d_id), 0) + mins
            # A kid in the car with a parent driving is time together, not
            # just logistics — the family eats in that car, and it is where
            # most of the talking happens.
            drv = storage.get_member_by_driver_id(str(d_id))
            if (drv or {}).get('role') in ('parent', 'adult') \
                    and kid_pax.intersection(e.get('attendees') or []):
                kid_rides += 1

    # Driving minutes belong to the MEMBER, not the driver record.
    load = {}
    for d_id, mins in driving.items():
        m = storage.get_member_by_driver_id(d_id)
        key = (m or {}).get('id') or d_id
        load[key] = load.get(key, 0) + mins

    day0 = datetime.datetime.fromisoformat(f'{date_str}T00:00:00').timestamp()
    day1 = day0 + 86400

    done = missed = 0
    for t in storage.get_household_tasks(include_done=True) or []:
        ts = t.get('completed_at')
        if t.get('status') == 'done' and ts and day0 <= float(ts) < day1:
            done += 1
            who = t.get('completed_by')
            if who:
                load[who] = load.get(who, 0) + TASK_MINUTES
        elif t.get('status') != 'done' and str(t.get('due_date') or '')[:10] == date_str:
            missed += 1

    try:
        with storage.db_lock:
            checks = [dict(r) for r in storage.routine_checks_table.all()]
        done += sum(1 for r in checks if str(r.get('day') or '')[:10] == date_str)
    except Exception as e:
        logger.warning(f"[vitals] routine checks unreadable: {e}")

    for f in storage.get_findings(state='resolved') or []:
        ts = f.get('resolved_at')
        who = f.get('resolved_by')
        if who and ts and day0 <= float(ts) < day1:
            load[who] = load.get(who, 0) + FINDING_MINUTES

    # Threads only when the measured day IS today: open_by_owner() is a
    # snapshot of what's open right now, and folding it into a PAST day —
    # backfill() calls this for up to WINDOW_DAYS of history — would invent
    # thread load for days when those threads did not exist, poisoning the
    # very baseline the backfill is meant to establish. Same reason the
    # backfill already pops follow_through, and the same today-only guard
    # _together applies to moments. The nightly caller
    # (family_digest.record_daily_stats) measures today, so the real row
    # always carries the real count.
    if date_str == datetime.date.today().isoformat():
        try:
            from services import threads as _threads
            thread_counts = _threads.open_by_owner()
            for member_id, count in thread_counts.items():
                load[member_id] = load.get(member_id, 0) + (count * THREAD_MINUTES)
        except Exception as e:
            logger.warning(f"[vitals] open threads unreadable for {date_str}: {e}")

    friction = {'unassigned': unassigned, 'canceled': canceled}
    try:
        counters = storage.get_day_counters(date_str) or {}
        for k in FRICTION_COUNTERS:
            friction[k] = int(counters.get(k) or 0)
        # The tallies have been folded into the day's row; anything older than
        # the window they feed is dead weight.
        cutoff = (datetime.date.fromisoformat(date_str)
                  - datetime.timedelta(days=WINDOW_DAYS + 7)).isoformat()
        storage.prune_day_counters(cutoff)
    except Exception as e:
        logger.warning(f"[vitals] day counters unreadable for {date_str}: {e}")

    # Programs: sessions actually done today, per person. The one sign that can
    # measure a family WINNING rather than surviving -- and the reason it is
    # safe to have at all is that it is Mind-input only and read against the
    # family's own baseline, never rendered as a gauge or a target. A session
    # carries its own timestamp, so this answers for date_str itself (a real
    # date filter on sessions_between) rather than for today, which is what
    # makes it safe to call from the historical backfill below.
    progress = {}
    try:
        from services import programs as _prog
        day = datetime.date.fromisoformat(date_str)
        for row in storage.get_programs(include_finished=True):
            n = len(_prog.sessions_between(row, day, day))
            if n:
                mid = row.get('member_id')
                progress[mid] = progress.get(mid, 0) + n
    except Exception as e:
        logger.warning(f"[vitals] programs unreadable for {date_str}: {e}")

    waking = (WAKING_END - WAKING_START) * 60
    return {
        'load': load,
        'margin_mins': max(0, waking - committed),
        'follow_through': {'done': done, 'missed': missed},
        'rest': {'first_hour': first_hour if first_hour is not None else WAKING_START,
                 'empty_evening': not evening},
        'friction': friction,
        'together': _together(date_str, sched, kid_rides),
        'progress': progress,
    }


def _together(date_str, sched, parent_rides):
    """Occasions of connection, in one unit: a meal eaten together, a moment
    captured, a kid who rode somewhere with a parent. Car meals are counted
    apart rather than subtracted — the family eats in the car on purpose, and
    a dinner in a minivan between two practices is still dinner together."""
    meals_together = car_meals = 0
    try:
        from services import meals as _meals
        plan = _meals.eating_plan(date_str, 'dinner', sched=sched) or {}
        for s in (plan.get('sittings') or []):
            if s.get('where_kind') == 'in_car':
                car_meals += 1
            elif len(s.get('member_ids') or []) >= 2:
                meals_together += 1
    except Exception as e:
        logger.warning(f"[vitals] eating plan unreadable for {date_str}: {e}")

    moments = 0
    try:
        from services import presence as _presence
        day0 = datetime.datetime.fromisoformat(f'{date_str}T00:00:00').timestamp()
        since = _presence.count_moments_since(day0)
        # count_moments_since is open-ended; only today's number is exact, so
        # older days keep whatever the nightly pass recorded at the time.
        moments = int(since or 0) if date_str == datetime.date.today().isoformat() else 0
    except Exception as e:
        logger.warning(f"[vitals] moments unreadable for {date_str}: {e}")

    return {'meals_together': meals_together, 'car_meals': car_meals,
            'moments': moments, 'parent_rides': parent_rides}


# ------------------------------------------------------------ the reading

def _series(rows, pick):
    """(date, value) for every day that has one, oldest first."""
    out = []
    for r in sorted(rows, key=lambda r: r.get('date') or ''):
        v = (r.get('vitals') or {})
        if not v:
            continue
        try:
            val = pick(v)
        except (TypeError, KeyError, ValueError):
            continue
        if val is not None:
            out.append((r['date'], float(val)))
    return out


def _reading(name, series, label=None):
    """Current mean vs baseline median, with how long it has been off."""
    if not series:
        return None
    vals = [v for _, v in series]
    current = round(statistics.fmean(vals[-CURRENT_DAYS:]), 1)
    out = {'name': name, 'label': label or name, 'current': current,
           'baseline': None, 'delta_pct': None, 'direction': None,
           'run_days': 0, 'worse': False}
    if len(series) < MIN_HISTORY_DAYS:
        return out
    base_vals = vals[:-CURRENT_DAYS] or vals
    baseline = statistics.median(base_vals)
    out['baseline'] = round(baseline, 1)
    if baseline:
        out['delta_pct'] = int(round((current - baseline) / abs(baseline) * 100))
    elif current:
        out['delta_pct'] = 100
    else:
        out['delta_pct'] = 0
    if out['delta_pct'] > 0:
        out['direction'] = 'up'
    elif out['delta_pct'] < 0:
        out['direction'] = 'down'

    # The run: consecutive most-recent days on the same side of baseline.
    # NOT for `progress`. A run of consecutive days on a person's practice
    # count IS a streak -- "6 days running" about a child's guitar is exactly
    # the shame machine the programs arc promises exists nowhere, and it slid
    # past the banned-key screen because it lives in `daily_stats`, outside
    # the program row. Suppressed here rather than in `_phrase` so there is no
    # number for any future surface to find and render.
    if out['direction'] and name not in _NO_RUN:
        want_high = out['direction'] == 'up'
        run = 0
        for _, v in reversed(series):
            if (v > baseline) if want_high else (v < baseline):
                run += 1
            else:
                break
        out['run_days'] = run
    out['worse'] = out['direction'] is not None and \
        out['direction'] == _WORSE_WHEN.get(name)
    return out


def read(now: datetime.datetime = None, days: int = WINDOW_DAYS) -> dict:
    """Every vital, current against this family's own baseline."""
    now = now or datetime.datetime.now()
    wanted = [(now.date() - datetime.timedelta(days=i)).isoformat()
              for i in range(days)]
    rows = [r for r in (storage.get_daily_stats(wanted) or []) if r.get('vitals')]
    n = len(rows)
    res = {'ready': n >= MIN_HISTORY_DAYS, 'days': n,
           'household': [], 'people': [], 'streaks': {}}
    if not n:
        return res

    picks = [
        ('margin', 'margin', lambda v: v.get('margin_mins')),
        ('follow_through', 'follow-through',
         lambda v: (lambda d, m: (d / (d + m) * 100) if (d + m) else None)(
             (v.get('follow_through') or {}).get('done', 0),
             (v.get('follow_through') or {}).get('missed', 0))),
        ('rest', 'rest', lambda v: 1 if (v.get('rest') or {}).get('empty_evening') else 0),
        ('friction', 'friction',
         lambda v: sum(int((v.get('friction') or {}).get(k) or 0)
                       for k in _FRICTION_KEYS)),
        ('together', 'togetherness',
         lambda v: (lambda t: (t.get('meals_together', 0) + t.get('moments', 0)
                               + t.get('parent_rides', 0)) if t else None)(
             v.get('together'))),
    ]
    for name, label, pick in picks:
        r = _reading(name, _series(rows, pick), label)
        if r:
            res['household'].append(r)

    who = set()
    for r in rows:
        who.update((r.get('vitals') or {}).get('load') or {})
    for member_id in sorted(who):
        series = _series(rows, lambda v, k=member_id: (v.get('load') or {}).get(k, 0))
        r = _reading('load', series, 'load')
        if not r:
            continue
        m = storage.get_member(member_id)
        r['member_id'] = member_id
        r['label'] = (m or {}).get('name') or member_id
        res['people'].append(r)

    who_p = set()
    for r in rows:
        who_p.update((r.get('vitals') or {}).get('progress') or {})
    for member_id in sorted(who_p):
        series = _series(rows, lambda v, k=member_id: (v.get('progress') or {}).get(k, 0))
        r = _reading('progress', series, 'progress')
        if not r:
            continue
        m = storage.get_member(member_id)
        r['member_id'] = member_id
        # Both readings ride res['people'] and `_phrase` prints only the
        # label, so a bare name here produced two indistinguishable bullets in
        # the Mind's snapshot -- one meaning Lily's LOAD fell (good) and one
        # meaning her PRACTICE did (not). The sign has to say which it is.
        r['label'] = f"{(m or {}).get('name') or member_id} — practice"
        res['people'].append(r)

    # Days since the last evening with nothing in it.
    since = 0
    for r in sorted(rows, key=lambda r: r.get('date') or '', reverse=True):
        if ((r.get('vitals') or {}).get('rest') or {}).get('empty_evening'):
            break
        since += 1
    res['streaks']['days_since_empty_evening'] = since
    return res


# ------------------------------------------------------- what the Mind sees

def _phrase(r):
    if r['delta_pct'] is None:
        return None
    if abs(r['delta_pct']) < 10:
        return None                      # noise, not a trend
    word = 'up' if r['direction'] == 'up' else 'down'
    run = f", {r['run_days']} days running" if r['run_days'] >= 3 else ''
    return f"{r['label']} {word} {abs(r['delta_pct'])}%{run}"


def snapshot_section(now: datetime.datetime = None) -> str:
    """The text block the Mind's snapshot carries. Empty when there is
    nothing honest to say — a pulse with no history is not a pulse."""
    res = read(now)
    if not res['days']:
        return ''
    lines = []
    if not res['ready']:
        lines.append(f"(only {res['days']} days of history — levels only, "
                     f"no trends yet)")
        for r in res['household']:
            lines.append(f"- {r['label']}: {r['current']}")
        return '\n'.join(lines)

    for r in res['household'] + res['people']:
        p = _phrase(r)
        if p:
            lines.append(f"- {p}" + ("  ← worth attention" if r['worse'] else ''))
    since = res['streaks'].get('days_since_empty_evening', 0)
    if since >= 10:
        lines.append(f"- {since} days since an evening with nothing in it")
    if not lines:
        lines.append("- everything sits within this family's normal range")
    return '\n'.join(lines)


# ------------------------------------------------------------- backfilling

def backfill(days: int = WINDOW_DAYS, now: datetime.datetime = None) -> dict:
    """Rebuild past vitals from real calendar history, so the pulse has a
    baseline on day one instead of in two months. Schedule-derived signs only
    — behaviour (tasks, routines, findings) genuinely wasn't recorded then and
    inventing it would poison the baseline it is meant to establish."""
    from services import calendar as _cal
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    cal_ids = settings.get('calendar_ids') or []
    if not cal_ids:
        return {'status': 'no_calendars'}
    start = (now.date() - datetime.timedelta(days=days)).isoformat()
    end = (now.date() - datetime.timedelta(days=1)).isoformat()
    try:
        events = _cal.fetch_upcoming_events(cal_ids, start_date_str=start,
                                            end_date_str=end) or []
    except Exception as e:
        logger.warning(f"[vitals] backfill fetch failed: {e}")
        return {'status': 'error', 'message': str(e)}

    raw = []
    for e in events:
        d = e.model_dump() if hasattr(e, 'model_dump') else dict(e)
        raw.append({'id': d.get('id'), 'title': d.get('title'),
                    'start': d.get('start'), 'end': d.get('end')})
    sched = {'events': raw, 'assignments': {}, 'ghost_assignments': {}}

    filled = 0
    for i in range(1, days + 1):
        date_str = (now.date() - datetime.timedelta(days=i)).isoformat()
        existing = storage.get_daily_stats([date_str])
        if existing and (existing[0].get('vitals') or {}).get('backfilled') is not True \
                and existing[0].get('vitals'):
            continue                      # a real recorded day always wins
        v = measure_day(date_str, sched=sched)
        # Behaviour was never recorded for these days; leave it absent rather
        # than reporting a family that did nothing.
        v.pop('follow_through', None)
        v['backfilled'] = True
        row = dict(existing[0]) if existing else {'date': date_str, 'drivers': {}, 'kids': {}}
        row['vitals'] = v
        storage.upsert_daily_stats(date_str, row)
        filled += 1
    return {'status': 'ok', 'days': filled, 'events': len(raw)}
