"""Proactive parent watchers: deterministic scans that surface stuck state.

Everything downstream of the dashboards assumes someone LOOKS — unassigned
events sit silently in triage, done chores wait for a verify tap, intake
proposals age out of relevance. These watchers close that gap: a periodic
sweep collects findings and DMs each parent ONE consolidated Argyle heads-up
(the DM rails give push + HA notify fan-out for free).

Anti-nag guarantees (the design constraint, not an afterthought):
- Every finding notifies exactly ONCE — keyed markers persist in app_state
  (`watcher_notified`), pruned after NOTIFIED_RETENTION_DAYS.
- One consolidated DM per parent per sweep, never per-finding pushes.
- Quiet hours (21:00-08:00): findings simply wait for the morning sweep.
- Stale-state nudges fire only after a grace period; the instant lifecycle
  notifications (chore done, redemption requested) already covered "new" —
  the watcher is the safety net for the ones that got missed.
- Zero LLM requests, except the WEEKLY prep-kit idea check (background tier;
  skipped silently when no key / no events / the pool errors).
"""
import datetime
import time

from services import storage

WATCH_WINDOW_DAYS = 3          # unassigned-event lookahead
STALE_PROPOSAL_DAYS = 3        # intake proposals pending this long
UNCLAIMED_TASK_LEAD_DAYS = 2   # a dated household task with nobody's name on it
STALE_VERIFY_HOURS = 48        # done chores awaiting parent verification
STALE_REDEMPTION_HOURS = 48    # reward requests awaiting a decision
UNCLAIMED_CHORE_DAYS = 7       # open chores nobody has claimed
PREP_SUGGEST_INTERVAL_DAYS = 7
NOTIFIED_RETENTION_DAYS = 45
QUIET_END_HOUR = 8             # no DMs before 08:00
QUIET_START_HOUR = 21          # ... or after 21:00


def _fmt_when(dt: datetime.datetime) -> str:
    return dt.strftime('%a %m/%d %I:%M %p').replace(' 0', ' ').lstrip('0')


def _days_ago(ts: float, now_ts: float) -> int:
    return max(1, int((now_ts - ts) // 86400))


def _unassigned_findings(now: datetime.datetime):
    """Events in the next WATCH_WINDOW_DAYS the solver left unassigned."""
    cache = storage.get_cached_schedule() or {}
    events = {str(e.get('id')): e for e in cache.get('events', [])}
    # Outside hands (load arc A1). A ride a carpool parent is making was never
    # ours to cover, and "🚨 No driver yet" for it is the standing false alarm
    # this feature exists to retire. Read from the cache rather than storage so
    # the sweep sees exactly what the last solve saw.
    covered = set((cache.get('assist_assignments') or {}).keys())
    horizon = now + datetime.timedelta(days=WATCH_WINDOW_DAYS)
    out = []
    for ev_id in cache.get('unassigned', []) or []:
        ev = events.get(str(ev_id))
        if not ev or ev.get('trip_suppressed') or ev.get('event_type') == 'errand':
            continue
        if str(ev_id) in covered:
            continue
        try:
            start = datetime.datetime.fromisoformat(ev['start']).replace(tzinfo=None)
        except Exception:
            continue
        if not (now <= start <= horizon):
            continue
        key = f"unassigned:{ev_id}:{start.date().isoformat()}"
        out.append((key, f"🚨 No driver yet: {ev.get('title') or 'Event'} — {_fmt_when(start)}"))
    return out


def _stale_proposal_findings(now_ts: float):
    out = []
    for p in storage.get_proposals(status='proposed'):
        created = p.get('created_at') or 0
        if now_ts - created < STALE_PROPOSAL_DAYS * 86400:
            continue
        n = _days_ago(created, now_ts)
        out.append((f"proposal:{p.get('id')}",
                    f"📥 Intake proposal waiting {n} days: {p.get('title') or 'Untitled'}"))
    return out


def _chore_findings(now_ts: float):
    out = []
    unclaimed = []
    for c in storage.get_all_chores():
        state = c.get('state')
        if state == 'done' and c.get('done_at') \
                and now_ts - c['done_at'] >= STALE_VERIFY_HOURS * 3600:
            out.append((f"chore_verify:{c.get('id')}:{int(c['done_at'])}",
                        f"✅ '{c.get('title')}' has waited {_days_ago(c['done_at'], now_ts)}"
                        f" day(s) for your OK"))
        elif state == 'open' and c.get('created_at') \
                and now_ts - c['created_at'] >= UNCLAIMED_CHORE_DAYS * 86400:
            unclaimed.append((f"chore_unclaimed:{c.get('id')}", c.get('title') or 'Chore'))
    return out, unclaimed


def _redemption_findings(now_ts: float):
    members = {m['id']: m for m in storage.get_all_members()}
    out = []
    for r in storage.get_redemptions(state='pending'):
        requested = r.get('requested_at') or 0
        if now_ts - requested < STALE_REDEMPTION_HOURS * 3600:
            continue
        who = (members.get(r.get('member_id')) or {}).get('name') or 'Someone'
        out.append((f"redemption:{r.get('id')}",
                    f"🎁 {who} asked for '{r.get('reward_title')}'"
                    f" {_days_ago(requested, now_ts)} day(s) ago"))
    return out


def _errand_findings():
    out = []
    for e in storage.get_all_errands():
        if e.get('is_completed') or e.get('status') != 'past_due':
            continue
        out.append((f"errand_pastdue:{e.get('id')}",
                    f"🛒 Past-due errand: {e.get('title')} — complete it or it stays parked"))
    return out


def _prep_kit_findings(now_ts: float):
    """WEEKLY: one background-tier LLM pass proposing prep kits for recurring
    events that have none. Any problem (no key, no events, pool error) skips
    silently — this is a bonus, never a blocker. Suggested names are
    fingerprinted so the same idea is never re-announced."""
    last = storage.get_app_state('prep_suggest_last_run') or 0
    if now_ts - float(last) < PREP_SUGGEST_INTERVAL_DAYS * 86400:
        return []
    storage.set_app_state('prep_suggest_last_run', now_ts)
    try:
        from services import prep_kits
        cache = storage.get_cached_schedule() or {}
        titles = {e.get('title') for e in cache.get('events', [])
                  if e.get('title') and e.get('event_type') != 'errand'
                  and not e.get('trip_suppressed')}
        if not titles:
            return []
        kits = prep_kits.suggest_kits(sorted(titles), tier='background')
    except Exception as e:
        print(f"[watchers] prep-kit suggest skipped: {e}")
        return []
    seen = set(storage.get_app_state('prep_suggest_seen') or [])
    fresh = [k.get('name') for k in kits
             if k.get('name') and k['name'].lower() not in seen]
    if not fresh:
        return []
    storage.set_app_state('prep_suggest_seen',
                          sorted(seen | {n.lower() for n in fresh}))
    names = ', '.join(fresh[:4])
    return [(f"prep_suggest:{int(now_ts)}",
             f"🎒 Prep-kit idea{'s' if len(fresh) != 1 else ''}: {names} — "
             f"tap ✨ Suggest on the Routines page to review & save")]


def _occasion_findings(now: datetime.datetime):
    """ANTICIPATION, which is the half of the mental load a page cannot carry.

    A surface you have to remember to open is one you do not open, so the gap
    report has to come to the parent — but only once it can say something
    useful, and only about the things that are actually running out of room.
    Two guards keep this from becoming noise: nothing fires outside a lead
    window, and a settled decision (`dismissed`) never resurfaces.
    """
    from services import occasions as _occ
    today = now.date()
    out = []
    for o in storage.get_occasions():
        try:
            anchor = datetime.date.fromisoformat(o['anchor_date'])
        except (TypeError, ValueError, KeyError):
            continue
        away = (anchor - today).days
        # Three weeks is where anticipation is still useful and not yet nagging.
        if away < 0 or away > 21:
            continue
        rep = _occ.gap_report(o['id'])
        urgent = [g for g in rep.get('gaps') or [] if g['slack_days'] <= 3]
        if not urgent:
            continue
        # The dedup key carries the DAY, so one nudge a day at most while the
        # gap stands, rather than one forever or one per sweep.
        key = f"occasion_gap:{o['id']}:{today.isoformat()}"
        names = ', '.join(g['label'] for g in urgent[:3])
        more = f" (+{len(urgent) - 3} more)" if len(urgent) > 3 else ""
        when = "today" if away == 0 else f"in {away} day{'s' if away != 1 else ''}"
        out.append((key, f"🎉 {o['title']} is {when} — still to sort: {names}{more}"))
    return out


def collect_findings(now: datetime.datetime = None):
    """All watcher findings as (dedup_key, line) pairs — unfiltered."""
    now = now or datetime.datetime.now()
    now_ts = now.timestamp()
    findings = []
    findings += _unassigned_findings(now)
    findings += _stale_proposal_findings(now_ts)
    chore, unclaimed = _chore_findings(now_ts)
    findings += chore
    findings += _redemption_findings(now_ts)
    findings += _errand_findings()
    findings += _occasion_findings(now)
    findings += _household_task_findings(now)
    findings += _stage_findings(now)
    findings += _care_gap_findings(now)
    return findings, unclaimed


CARE_GAP_HORIZON_DAYS = 21     # closures are known weeks ahead; PTO needs lead time


def _care_gap_findings(now: datetime.datetime):
    """Days school does not run full, said WEEKS ahead (load arc A5).

    The app knew school was closed and knew both parents' calendars, and
    never computed the intersection — the highest-drama moment in a
    two-income household. The 3-day unassigned window is far too late here:
    taking a day off needs lead time, so this one looks 21 days out.

    Framed as a DECISION with named options, not an alarm. Aftercare
    softens a half day (that is what it is for) and is said so; a closure
    closes aftercare with the school, so nothing softens it.
    """
    try:
        from services import school
        kids = [m for m in storage.get_all_members() if m.get('role') == 'child']
        if not kids:
            return []
        out = []
        for gap in school.care_gap_days(CARE_GAP_HORIZON_DAYS):
            d = datetime.date.fromisoformat(gap['date'])
            when = f"{gap['weekday']} {d.strftime('%b %d').replace(' 0', ' ')}"
            if gap['kind'] == 'half':
                covered = [k for k in kids
                           if d.weekday() in (k.get('aftercare_days') or [])
                           and k.get('aftercare_until')]
                if len(covered) == len(kids):
                    continue        # aftercare has the afternoon: not a gap
                names = [k.get('name') for k in kids if k not in covered]
                line = (f"🏫 {when} is a half day — early release, and "
                        f"{', '.join(names)} need{'s' if len(names) == 1 else ''} "
                        f"the afternoon covered. A parent, a grandparent, a "
                        f"carpool family, or an aftercare day all work.")
            elif gap['kind'] == 'delayed':
                line = (f"🏫 {when} is a late start — someone has the morning "
                        f"until school opens.")
            else:
                line = (f"🏫 {when} — no school. Someone has the day: a parent "
                        f"takes it off, a grandparent, a carpool family, or a "
                        f"camp day.")
            out.append((f"caregap:{gap['date']}:{gap['kind']}", line))
        return out
    except Exception as e:
        print(f"[watchers] care-gap findings failed: {e}")
        return []


def _stage_findings(now: datetime.datetime):
    """A child whose age has moved past their stage (load arc A4). One line to
    the parents, because growing up is GRANTED — announced and confirmed —
    never a config value that silently changes one morning. The dedup key is
    (child, stage), so it says so once per transition, not once per sweep."""
    try:
        from services import stages
        out = []
        for p in stages.pending_promotions(now.date()):
            out.append((f"stage:{p['member_id']}:{p['to']}",
                        f"🌱 {p['name']} is {p['age']} now — ready to be a "
                        f"{p['to'].capitalize()}. Confirm it in Config → People."))
        return out
    except Exception as e:
        print(f"[watchers] stage findings failed: {e}")
        return []


def _household_task_findings(now: datetime.datetime):
    """Household work with a deadline and no destination (load arc A2).

    Two findings, and the second is the point of the whole object: a task
    that is DUE SOON AND STILL BELONGS TO NOBODY. "The household owes this"
    is a real state, and the moment it stops being fine is when the date
    arrives with nobody's name on it.
    """
    import datetime as _dt
    today = now.date()
    out = []
    for t in storage.get_household_tasks():
        due = t.get('due_date')
        if not due:
            continue          # an undated task is never late; it is just work
        try:
            due_d = _dt.date.fromisoformat(due)
        except ValueError:
            continue
        title = t.get('title') or 'Something'
        if due_d < today:
            days = (today - due_d).days
            out.append((f"task_overdue:{t['id']}:{due}",
                        f"📋 Past due: {title} — was due "
                        f"{'yesterday' if days == 1 else f'{days} days ago'}"))
        elif not t.get('assigned_to') and (due_d - today).days <= UNCLAIMED_TASK_LEAD_DAYS:
            when = 'today' if due_d == today else (
                'tomorrow' if (due_d - today).days == 1 else due_d.strftime('%a'))
            out.append((f"task_unclaimed:{t['id']}:{due}",
                        f"📋 Nobody has {title} — due {when}"))
    return out


def run_watchers(now: datetime.datetime = None) -> int:
    """One sweep: collect, drop already-notified findings, DM each parent one
    consolidated heads-up. Returns the number of fresh findings sent (0 = no
    post). Quiet hours return without consuming anything — findings wait."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('proactive_watchers_enabled', True):
        return 0
    if not (QUIET_END_HOUR <= now.hour < QUIET_START_HOUR):
        return 0

    now_ts = now.timestamp()
    notified = dict(storage.get_app_state('watcher_notified') or {})
    # prune old markers so the dict never grows without bound
    cutoff = now_ts - NOTIFIED_RETENTION_DAYS * 86400
    notified = {k: ts for k, ts in notified.items() if ts >= cutoff}

    findings, unclaimed = collect_findings(now)
    findings += _prep_kit_findings(now_ts)

    fresh = [(k, line) for k, line in findings if k not in notified]
    fresh_unclaimed = [(k, title) for k, title in unclaimed if k not in notified]
    if fresh_unclaimed:
        titles = [t for _, t in fresh_unclaimed]
        line = f"🧹 Unclaimed for a week: {', '.join(titles[:3])}"
        if len(titles) > 3:
            line += f" (+{len(titles) - 3} more)"
        line += " — lower the points, split it up, or retire it?"
        fresh.append(('__unclaimed_batch__', line))

    real_keys = [k for k, _ in fresh if k != '__unclaimed_batch__'] \
        + [k for k, _ in fresh_unclaimed]
    if not fresh:
        storage.set_app_state('watcher_notified', notified)
        return 0

    parents = [m for m in storage.get_all_members()
               if m.get('role') == 'parent' and not m.get('system')]
    if not parents:
        return 0

    lines = [line for _, line in fresh]
    body = "👋 Heads-up — needs a look:\n" + "\n".join(f"• {l}" for l in lines)
    body += "\n\nAsk me for options, or handle it on the dashboard."

    from services.agent_tools_v2 import _post_chat_message
    argyle = storage.ensure_argyle_member()
    sent = False
    for parent in parents:
        try:
            dm = storage.get_or_create_dm(argyle['id'], parent['id'])
            _post_chat_message(dm, argyle, body)
            sent = True
        except Exception as e:
            print(f"[watchers] DM to {parent.get('name')} failed: {e}")

    if sent:
        for k in real_keys:
            notified[k] = now_ts
        storage.set_app_state('watcher_notified', notified)
        print(f"[watchers] sent {len(fresh)} finding(s) to {len(parents)} parent(s)")
        return len(fresh)
    return 0
