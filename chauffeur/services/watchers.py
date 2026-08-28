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

**The signal policy** (docs/needs_you_design.md, from the family's own report
that most of these messages were not worth reading). A finding may interrupt
somebody only if it passes all three:

    time-critical?   actionable?   does it arrive with a solution?

Anything that fails one is still WATCHED — it becomes a record, it shows up
where somebody has chosen to look — but it does not get to buzz a phone.
Unclaimed chores and a skipped optional activity days out are the two the
family named: neither has a clock, and neither is a decision anybody wants to
be handed. They are marked `dm=False` below rather than deleted, because a
count of them is still worth having.

Findings are `findings.Finding` tuples now, not bare `(key, line)` pairs — the
extra fields carry severity, subject and the proposed action. Indexing still
works, so the collectors read the same as they always did.
"""
import datetime
import time

from services import coverage_options as _coverage, findings as _findings, storage
from services.findings import Finding

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


# How many seeds one sweep may negotiate. The search costs real solver time,
# and a sweep that negotiated every uncovered event on a bad day would spend
# minutes deciding things nobody has read yet. One seed per sweep, most urgent
# first, and an open deal is reused rather than re-searched.
NEGOTIATE_PER_SWEEP = 1


def _deal_line(event_id: str):
    """(line, action) for an open deal on this event, or (None, None).

    Read-only: it reports a deal that already exists. Finding one is
    `_negotiate_seed`'s job, and it happens at most once per sweep.

    Only a LIVE deal speaks. `dead` and `expired` both mean this event is
    uncovered with nothing pending, and both have to fall through to the
    coverage ladder — a settled deal holding the line would leave the event
    showing a status about a negotiation that ended.
    """
    for d in storage.get_deals(seed_event_id=str(event_id)):
        if d.get('state') not in ('draft', 'asking'):
            continue
        if d.get('state') == 'asking':
            waiting = [p for p in d.get('parts') or []
                       if p.get('state') != 'accepted']
            said_yes = len(d.get('parts') or []) - len(waiting)
            return (f"🤝 {d.get('seed_title') or 'That drive'}: "
                    f"{said_yes} of {len(d.get('parts') or [])} said yes, "
                    f"waiting on the rest.", None)
        return (d.get('line'), {'label': 'Ask them', 'action_type': 'ask_deal',
                                'payload': {'deal_id': d['id']}})
    return (None, None)


def _negotiate_seed(event_id: str, date_str: str):
    """Try to find a deal for one uncovered event. Never fatal, never chatty."""
    from services import negotiation
    if not storage.get_settings().get('negotiation_enabled', True):
        return
    try:
        negotiation.propose(date_str, str(event_id),
                            budget=int(storage.get_settings().get(
                                'negotiation_sweep_budget',
                                negotiation.SWEEP_BUDGET)))
    except Exception as e:
        print(f"[watchers] negotiation failed for {event_id}: {e}")


def _unassigned_findings(now: datetime.datetime):
    """Events in the next WATCH_WINDOW_DAYS the solver left unassigned.

    This is the one finding a parent genuinely cannot act on without help, so
    it is the one that carries the ladder: who at home is free, who has covered
    this before, or an honest can't-cover with the reasons named
    (services/coverage_options.py). A siren with no answer attached was the
    complaint that produced all of this.

    Before the ladder, though: is there a deal? Negotiation is checked (and,
    budget allowing, searched) first — the Mind is supposed to arrive with the
    answer, not with the problem. `negotiated` is scoped to this one call, not
    per-event, because it is the sweep's cap: this function runs once per
    sweep, so counting here caps the whole sweep at NEGOTIATE_PER_SWEEP seeds
    no matter how many uncovered events it finds.
    """
    cache = storage.get_cached_schedule() or {}
    events = {str(e.get('id')): e for e in cache.get('events', [])}
    # Outside hands (load arc A1). A ride a carpool parent is making was never
    # ours to cover, and "🚨 No driver yet" for it is the standing false alarm
    # this feature exists to retire. Read from the cache rather than storage so
    # the sweep sees exactly what the last solve saw.
    covered = set((cache.get('assist_assignments') or {}).keys())
    horizon = now + datetime.timedelta(days=WATCH_WINDOW_DAYS)
    out = []
    negotiated = 0
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
        title = ev.get('title') or 'Event'
        # Optional events (event config `is_optional`): dropped-first is the
        # DESIGN, not a coverage hole — one calm line, never the siren. The
        # key differs from the unassigned one so flipping the flag re-says
        # the day in the right voice. An occurrence decided 'attend'
        # deliberately falls through to the siren — somebody promised a kid;
        # 'skip' never gets here (excluded from the solve upstream).
        #
        # It does NOT get to interrupt anybody. The family's verdict: an
        # optional thing that did not fit, days out, is not a decision they
        # want handed to them — the schedule already shows it as skipped, and
        # "she's still going" is a sentence they will say when they mean it.
        if (ev.get('app_config') or {}).get('is_optional') \
                and ev.get('optional_decision') != 'attend':
            out.append(Finding(
                key=f"optional_skip:{ev_id}:{start.date().isoformat()}",
                line=(f"⏭️ {title} ({_fmt_when(start)}) is optional and didn't "
                      f"fit around the other drives — skipped it."),
                kind='optional_skip', severity='fyi', dm=False,
                subject_type='event', subject_id=ev_id,
                due_at=start.timestamp()))
            continue
        key = f"unassigned:{ev_id}:{start.date().isoformat()}"
        # Before the siren: is there a deal? The Mind is supposed to arrive
        # with the answer, not with the problem.
        deal_line, deal_action = _deal_line(ev_id)
        if not deal_line and negotiated < NEGOTIATE_PER_SWEEP:
            negotiated += 1
            _negotiate_seed(ev_id, start.date().isoformat())
            deal_line, deal_action = _deal_line(ev_id)
        if deal_line:
            # A draft deal carries one real tap ('approve' — go work it,
            # matching the coverage ladder's own tiers). An asking deal has
            # already sent its requests; there is nothing left to press until
            # the rest answer, same as the ladder's tier-0 'waiting' rung
            # (coverage_options.py) — 'fyi', no action, so the finding-list
            # grouping downstream (agent_tools_v2.list_open_findings, which
            # reads severity, not action) never labels it a tap that isn't
            # there.
            out.append(Finding(key=key, line=deal_line, kind='unassigned',
                               severity='approve' if deal_action else 'fyi',
                               subject_type='event', subject_id=ev_id,
                               due_at=start.timestamp(), action=deal_action))
            continue
        try:
            rung = _coverage.ladder(ev, cache, now)
        except Exception as e:
            print(f"[watchers] coverage ladder failed for {ev_id}: {e}")
            rung = None
        if not rung:
            out.append(Finding(key=key,
                               line=f"🚨 No driver yet: {title} — {_fmt_when(start)}",
                               kind='unassigned', severity='decide',
                               subject_type='event', subject_id=ev_id,
                               due_at=start.timestamp()))
            continue
        out.append(Finding(
            key=key, line=rung['line'], kind='unassigned',
            severity=rung.get('severity') or 'decide',
            # A rung-0 line ("asked the Muellers, waiting") is a status, not a
            # question: the nudge rail is already carrying that conversation
            # and a second reminder would be the app talking over itself.
            dm=rung.get('tier') != 0,
            subject_type='event', subject_id=ev_id, due_at=start.timestamp(),
            action=(rung.get('actions') or [None])[0]))
    return out


def _stale_proposal_findings(now_ts: float):
    out = []
    for p in storage.get_proposals(status='proposed'):
        created = p.get('created_at') or 0
        if now_ts - created < STALE_PROPOSAL_DAYS * 86400:
            continue
        n = _days_ago(created, now_ts)
        out.append(Finding(key=f"proposal:{p.get('id')}",
                           line=f"📥 Intake proposal waiting {n} days: "
                                f"{p.get('title') or 'Untitled'}",
                           kind='proposal', severity='approve',
                           subject_type='proposal', subject_id=str(p.get('id'))))
    return out


def _chore_findings(now_ts: float):
    """Verify nudges interrupt; unclaimed chores no longer do.

    A chore somebody finished and is waiting to be paid for has a person at the
    end of it — that is time-critical in the way that matters. A chore nobody
    has claimed in a week is a fact about the chore list, and the family was
    explicit that being asked about it weekly was noise.
    """
    out = []
    unclaimed = []
    for c in storage.get_all_chores():
        state = c.get('state')
        if state == 'done' and c.get('done_at') \
                and now_ts - c['done_at'] >= STALE_VERIFY_HOURS * 3600:
            out.append(Finding(
                key=f"chore_verify:{c.get('id')}:{int(c['done_at'])}",
                line=(f"✅ '{c.get('title')}' has waited "
                      f"{_days_ago(c['done_at'], now_ts)} day(s) for your OK"),
                kind='chore_verify', severity='approve',
                subject_type='chore', subject_id=str(c.get('id'))))
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
        out.append(Finding(key=f"redemption:{r.get('id')}",
                           line=(f"🎁 {who} asked for '{r.get('reward_title')}'"
                                 f" {_days_ago(requested, now_ts)} day(s) ago"),
                           kind='redemption', severity='approve',
                           subject_type='redemption', subject_id=str(r.get('id'))))
    return out


def _errand_findings():
    out = []
    for e in storage.get_all_errands():
        if e.get('is_completed') or e.get('status') != 'past_due':
            continue
        out.append(Finding(key=f"errand_pastdue:{e.get('id')}",
                           line=f"🛒 Past-due errand: {e.get('title')} — "
                                f"complete it or it stays parked",
                           kind='errand_pastdue', severity='approve',
                           subject_type='errand', subject_id=str(e.get('id'))))
    return out


def _supply_deadline_findings(now: datetime.datetime):
    """Supply intake §A2: a thing with a deadline the shop run will not meet.

    A surface you have to open is one you do not open, which is why this is a
    watcher and not only a badge on the list. Any failure skips silently —
    the sweep's other findings must not be lost to a shopping problem.
    """
    try:
        from services import shopping as _shop
        rows = _shop.deadline_findings(now.date())
    except Exception as e:
        print(f"[watchers] supply deadline check failed: {e}")
        return []
    return [_as_finding(r, kind='supply_deadline', severity='approve') for r in rows]


def _as_finding(row, kind: str, severity: str = 'fyi', dm: bool = True) -> Finding:
    """Adapt a collector that still speaks in `(key, line)` pairs. Kept so a
    service outside this module never has to import the Finding shape just to
    hand back a sentence."""
    if isinstance(row, Finding):
        return row
    key, line = row[0], row[1]
    return Finding(key=key, line=line, kind=kind, severity=severity, dm=dm,
                   subject_type=kind, subject_id=str(key))


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
    return [Finding(key=f"prep_suggest:{int(now_ts)}",
                    line=(f"🎒 Prep-kit idea{'s' if len(fresh) != 1 else ''}: {names} — "
                          f"tap ✨ Suggest on the Routines page to review & save"),
                    kind='prep_suggest', severity='fyi',
                    subject_type='prep_suggest', subject_id=f"prep_suggest:{int(now_ts)}")]


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
        out.append(Finding(
            key=key,
            line=f"🎉 {o['title']} is {when} — still to sort: {names}{more}",
            kind='occasion_gap', severity='decide',
            subject_type='occasion', subject_id=str(o['id']),
            due_at=datetime.datetime.combine(anchor, datetime.time.max).timestamp()))
    return out


# Every kind this sweep looks for. Reconciliation is scoped to it: a record of
# a kind that was not scanned must never be auto-closed by a sweep that did not
# ask the question (services/findings.py).
SCANNED_KINDS = ('unassigned', 'optional_skip', 'proposal', 'chore_verify',
                 'redemption', 'errand_pastdue', 'supply_deadline',
                 'occasion_gap', 'household_task', 'stage', 'care_gap',
                 'commitment', 'chore_unclaimed', 'thread_stall',
                 'program_session', 'program_rebaseline', 'program_drift')


def _thread_stalls(now: datetime.datetime):
    """A thread (services/threads.py) that stalled — a promise to a vendor or
    a project that stopped moving and nothing else in the app would ever
    notice.

    The signal policy still applies: a quiet thread, or one whose next-action
    date only just passed, is watched but not paged — that's the normal shape
    of a slow-moving thread, not an emergency. It becomes a `decide` DM only
    once the missed promise has sat more than a week, because that is the
    point where "I'll get to it" has stopped being true.

    Every line carries the thread's title AND its next action (never a bare
    "this went quiet") — a thread with no next action set still gets an
    actionable line, because the missing decision IS the next action.
    """
    from services import threads as _threads
    today = now.date()
    out = []
    for t in _threads.stalled(today=today):
        thread_id = t.get('id')
        title = t.get('title') or 'Thread'
        next_action = t.get('next_action') or ''
        what = f"next: {next_action}" if next_action \
            else "no next action set — decide one"
        severity, dm = 'fyi', False
        if t.get('stall_reason') == 'overdue':
            overdue_days = 0
            try:
                due_date = datetime.date.fromisoformat(t.get('next_action_at'))
                overdue_days = (today - due_date).days
            except (TypeError, ValueError):
                pass
            if overdue_days > 7:
                severity, dm = 'decide', True
        out.append(Finding(
            key=f"thread_stall:{thread_id}",
            line=f"🧵 {title} has stalled — {what}",
            kind='thread_stall', severity=severity, dm=dm,
            subject_type='thread', subject_id=str(thread_id)))
    return out


def _program_findings(now: datetime.datetime):
    """A program that needs a word: a session to confirm, a timeline that bent,
    or reserved time that has quietly disappeared.

    Every line here blames the WEEK, never the person — that is the design's
    rule and it is the difference between a finding with a fix attached and a
    reprimand with a number attached.
    """
    from services import programs as _prog
    out = []
    if not storage.get_settings().get('programs_enabled', True):
        return out

    try:
        for due in _prog.due_session_asks(now):
            row = due['program']
            out.append(Finding(
                key=f"program_session:{row['id']}:{due['slot_date']}",
                line=f"🎸 {due['body']}",
                kind='program_session', severity='fyi', dm=True,
                subject_type='program', subject_id=str(row['id']),
                action={'label': 'Yes, it happened',
                        'action_type': 'log_program_session',
                        'payload': {'program_id': row['id']}}))
    except Exception as e:
        print(f"[watchers] program session asks failed: {e}")

    for row in storage.get_programs(state='active'):
        try:
            gone = _prog.orphaned_emissions(row)
            if gone:
                _prog.forget_emissions(row['id'], gone)
                out.append(Finding(
                    key=f"program_drift:{row['id']}",
                    line=(f"📅 {row.get('title')}: that practice time isn't on "
                          f"the calendar any more. Want it back, or shall I "
                          f"re-shape the week?"),
                    kind='program_drift', severity='decide', dm=True,
                    subject_type='program', subject_id=str(row['id'])))
                continue
            bent = _prog.maybe_rebaseline(row, now)
            if bent:
                day = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                       'Saturday', 'Sunday')[bent['weekday']]
                # Four honest endings, not one reused for all of them: an
                # undated target can just move; a dated one that already had
                # slack needs no claim of a squeeze that never happened; a
                # dated one that needed it gets the real compression named;
                # and a dated one too far behind to bend has to say so rather
                # than claim room that was never made.
                if bent['fits'] is False:
                    line = (f"🎸 {row.get('title')}: {day}s keep getting eaten, "
                            f"and the plan is now tight against the date — the "
                            f"phases are as short as they can go. Want to try "
                            f"a different day?")
                elif bent['fits'] is True and bent.get('phases_changed'):
                    line = (f"🎸 {row.get('title')}: {day}s keep getting eaten — "
                            f"I've tightened the phases so it still lands on "
                            f"time. Want to try a different day?")
                elif bent['fits'] is True:
                    line = (f"🎸 {row.get('title')}: {day}s keep getting eaten — "
                            f"want to try a different day? The plan still has "
                            f"room to land on time as it stands.")
                else:
                    line = (f"🎸 {row.get('title')}: {day}s keep getting eaten — "
                            f"want to try a different day? I've given the plan "
                            f"more room either way.")
                out.append(Finding(
                    key=f"program_rebaseline:{row['id']}:{bent['baseline']['rebaselines']}",
                    line=line,
                    kind='program_rebaseline', severity='fyi', dm=True,
                    subject_type='program', subject_id=str(row['id'])))
        except Exception as e:
            print(f"[watchers] program check failed for {row.get('id')}: {e}")
    return out


def collect_findings(now: datetime.datetime = None):
    """All watcher findings as `Finding` tuples — unfiltered, un-deduped."""
    now = now or datetime.datetime.now()
    now_ts = now.timestamp()
    findings = []
    findings += _unassigned_findings(now)
    findings += _stale_proposal_findings(now_ts)
    chore, unclaimed = _chore_findings(now_ts)
    findings += chore
    findings += _redemption_findings(now_ts)
    findings += _errand_findings()
    findings += _supply_deadline_findings(now)
    findings += _occasion_findings(now)
    findings += _household_task_findings(now)
    findings += _stage_findings(now)
    findings += _care_gap_findings(now)
    findings += _commitment_findings(now)
    findings += _thread_stalls(now)
    findings += _program_findings(now)
    return findings, unclaimed


def _commitment_findings(now: datetime.datetime):
    """Protected time, watched (load arc A6).

    Two findings per commitment, both forward-looking:

    **Erosion**: the solver is BANNED from a protected window, so a drive can
    only land there through a manual override — which is exactly the quiet
    way an outlet dies, one reasonable-seeming exception at a time. Say it
    before it costs the evening, name the drive.

    **Coverage**: a commitment marked needs_coverage with open drives in its
    window a few days out — wishing for time does not produce time; covered
    time does.
    """
    try:
        cache = storage.get_cached_schedule() or {}
        events = {str(e.get('id')): e for e in cache.get('events', [])}
        assignments = dict(cache.get('assignments') or {})
        unassigned = set(str(x) for x in cache.get('unassigned') or [])
        covered_out = set((cache.get('assist_assignments') or {}).keys())
        members = {m['id']: m for m in storage.get_all_members()}
        horizon = now + datetime.timedelta(days=4)
        out = []
        for pc in storage.get_protected_commitments():
            member = members.get(pc.get('member_id')) or {}
            drv = member.get('driver_id')
            days = set(pc.get('days_of_week') or [])
            if not days:
                continue
            try:
                sh, sm = [int(x) for x in (pc.get('time_start') or '18:00').split(':')[:2]]
                eh, em = [int(x) for x in (pc.get('time_end') or '20:00').split(':')[:2]]
            except (ValueError, TypeError):
                continue
            for ev_id, ev in events.items():
                try:
                    start = datetime.datetime.fromisoformat(str(ev['start'])).replace(tzinfo=None)
                except (ValueError, TypeError, KeyError):
                    continue
                if not (now <= start <= horizon) or start.weekday() not in days:
                    continue
                w_start = start.replace(hour=sh, minute=sm, second=0)
                w_end = start.replace(hour=eh, minute=em, second=0)
                if not (w_start <= start <= w_end):
                    continue
                day_label = start.strftime('%A')
                # Somebody's own life is nobody else's business: these stay in
                # the DM and are marked so no shared surface can render them.
                if drv and assignments.get(ev_id) == drv:
                    out.append(Finding(
                        key=f"erosion:{pc['id']}:{ev_id}",
                        line=(f"⏳ {day_label}'s {pc.get('title')} is about to be "
                              f"lost to a drive ({ev.get('title') or 'an event'}) — "
                              f"that took an override, so make sure it was worth it."),
                        kind='commitment', severity='fyi',
                        subject_type='commitment', subject_id=f"{pc['id']}:{ev_id}",
                        due_at=start.timestamp()))
                elif pc.get('needs_coverage') and str(ev_id) in unassigned \
                        and str(ev_id) not in covered_out:
                    out.append(Finding(
                        key=f"pc_cover:{pc['id']}:{ev_id}",
                        line=(f"🛡️ {member.get('name')}'s {pc.get('title')} is "
                              f"{day_label} — {ev.get('title') or 'a drive'} in that "
                              f"window still needs a driver."),
                        kind='commitment', severity='decide',
                        subject_type='commitment', subject_id=f"{pc['id']}:{ev_id}",
                        due_at=start.timestamp()))
        return out
    except Exception as e:
        print(f"[watchers] commitment findings failed: {e}")
        return []


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
            # DM-only, forever. A care gap names a specific child and a
            # specific hole in their week; the wall panel is semi-public and
            # this is not wall material (docs/needs_you_design.md §9).
            out.append(Finding(
                key=f"caregap:{gap['date']}:{gap['kind']}", line=line,
                kind='care_gap', severity='decide', subject_type='care_gap',
                subject_id=f"{gap['date']}:{gap['kind']}",
                due_at=datetime.datetime.combine(d, datetime.time.max).timestamp()))
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
            out.append(Finding(
                key=f"stage:{p['member_id']}:{p['to']}",
                line=(f"🌱 {p['name']} is {p['age']} now — ready to be a "
                      f"{p['to'].capitalize()}. Confirm it in Config → People."),
                kind='stage', severity='decide', subject_type='member',
                subject_id=f"{p['member_id']}:{p['to']}"))
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
        due_ts = _dt.datetime.combine(due_d, _dt.time.max).timestamp()
        if due_d < today:
            days = (today - due_d).days
            out.append(Finding(
                key=f"task_overdue:{t['id']}:{due}",
                line=(f"📋 Past due: {title} — was due "
                      f"{'yesterday' if days == 1 else f'{days} days ago'}"),
                kind='household_task', severity='approve',
                subject_type='task', subject_id=f"overdue:{t['id']}"))
        elif not t.get('assigned_to') and (due_d - today).days <= UNCLAIMED_TASK_LEAD_DAYS:
            when = 'today' if due_d == today else (
                'tomorrow' if (due_d - today).days == 1 else due_d.strftime('%a'))
            out.append(Finding(
                key=f"task_unclaimed:{t['id']}:{due}",
                line=f"📋 Nobody has {title} — due {when}",
                kind='household_task', severity='decide',
                subject_type='task', subject_id=f"unclaimed:{t['id']}",
                due_at=due_ts))
    return out


def _unclaimed_batch(unclaimed) -> Finding:
    """The week-old unclaimed chores, as one record nobody is pinged about.

    Kept, because "seven chores have sat there a fortnight" is worth knowing
    when you go looking. Silenced, because being asked about it every week was
    the noise the family actually complained about.
    """
    titles = [t for _, t in unclaimed]
    line = f"🧹 Unclaimed for a week: {', '.join(titles[:3])}"
    if len(titles) > 3:
        line += f" (+{len(titles) - 3} more)"
    line += " — lower the points, split it up, or retire it?"
    return Finding(key='__unclaimed_batch__', line=line, kind='chore_unclaimed',
                   severity='fyi', dm=False, subject_type='chore_batch',
                   subject_id='__unclaimed_batch__')


def run_watchers(now: datetime.datetime = None) -> int:
    """One sweep: collect, reconcile the record table, then DM each parent one
    consolidated heads-up about the findings that earned an interruption.
    Returns the number of fresh findings SENT (0 = no post).

    The two halves are deliberately independent. Records are reconciled on
    every sweep, including inside quiet hours and including for findings that
    may never be DM'd — the app's picture of what is true should not depend on
    whether it was a polite hour to say so.
    """
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('proactive_watchers_enabled', True):
        return 0

    now_ts = now.timestamp()
    findings, unclaimed = collect_findings(now)
    if unclaimed:
        findings.append(_unclaimed_batch(unclaimed))
    findings += _prep_kit_findings(now_ts)

    # Records first, so a finding that resolved itself is closed even on a
    # sweep that posts nothing.
    scanned = set(SCANNED_KINDS)
    if any(f.kind == 'prep_suggest' for f in findings):
        scanned.add('prep_suggest')
    try:
        _findings.reconcile(findings, scanned, now_ts)
    except Exception as e:
        print(f"[watchers] finding reconcile failed: {e}")

    if not (QUIET_END_HOUR <= now.hour < QUIET_START_HOUR):
        return 0

    notified = dict(storage.get_app_state('watcher_notified') or {})
    # prune old markers so the dict never grows without bound
    cutoff = now_ts - NOTIFIED_RETENTION_DAYS * 86400
    notified = {k: ts for k, ts in notified.items() if ts >= cutoff}

    # The signal policy, applied in one line: only findings that carry a
    # solution or a clock get to interrupt a person.
    fresh = [f for f in findings if f.dm and f.key not in notified]
    if not fresh:
        storage.set_app_state('watcher_notified', notified)
        return 0

    parents = [m for m in storage.get_all_members()
               if m.get('role') == 'parent' and not m.get('system')]
    if not parents:
        return 0

    body = "👋 Heads-up — needs a look:\n" + "\n".join(f"• {f.line}" for f in fresh)
    body += "\n\nAsk me for options, or handle it on the dashboard."

    from services.agent_tools_v2 import _post_chat_message
    argyle = storage.ensure_argyle_member()
    sent = False
    for parent in parents:
        try:
            dm = storage.get_or_create_dm(argyle['id'], parent['id'])
            _post_chat_message(dm, argyle, body)
            _post_action_cards(dm, argyle, fresh, parent)
            sent = True
        except Exception as e:
            print(f"[watchers] DM to {parent.get('name')} failed: {e}")

    if sent:
        for f in fresh:
            if f.key != '__unclaimed_batch__':
                notified[f.key] = now_ts
        storage.set_app_state('watcher_notified', notified)
        print(f"[watchers] sent {len(fresh)} finding(s) to {len(parents)} parent(s)")
        return len(fresh)
    return 0


# At most this many approve-cards ride a single sweep. The consolidated DM is
# the contract; cards are the hand path for the findings that have a concrete
# thing to tap, and a sweep that posted nine of them would have broken the one
# guarantee this module has always made.
MAX_ACTION_CARDS = 3


def _post_action_cards(dm, argyle, fresh, parent):
    """One approve card per actionable finding, after the consolidated line.

    This is the hand path: the same proposal machinery the agent uses
    (services/chat_actions.py), so a tap goes through the tested handler and
    the parent/admin gate is enforced at approval rather than here.
    """
    from services import chat_actions
    from services.agent_tools_v2 import _post_chat_message
    posted = 0
    for f in fresh:
        if posted >= MAX_ACTION_CARDS or not f.action:
            continue
        act = f.action
        try:
            res = chat_actions.create_action_proposal(
                act['action_type'], act.get('label') or act['action_type'],
                act.get('payload') or {}, created_by_member_id=argyle.get('id'))
            if res.get('status') != 'success':
                continue
            storage.update_action_proposal(res['proposal_id'], {'channel_id': dm['id']})
            _post_chat_message(dm, argyle, act.get('label') or 'Suggested',
                               card=res.get('card'))
            posted += 1
        except Exception as e:
            print(f"[watchers] action card failed ({act.get('action_type')}): {e}")
