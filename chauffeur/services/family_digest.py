"""Weekly family digest: a stats recap Argyle posts into the family channel.

The combined schedule cache is forward-looking (past days roll out of it), so
per-day driving/activity stats are SNAPSHOTTED once each evening into the
`daily_stats` table (`record_daily_stats`, upsert keyed by date) and the
weekly digest sums the last 7 snapshots. Chores, rewards, and routines need no
snapshots — the points ledger, redemptions, and routine checks are already
durable history.

Delivery reuses the family-chat rails: the digest is an ordinary ChatMessage
from the Argyle system member, so SSE + push/HA fan-out come free and the
recap is readable by everyone, forever, in the thread.
"""
import datetime

from services import storage


def _minutes(ev):
    try:
        start = datetime.datetime.fromisoformat(ev['start'])
        end = datetime.datetime.fromisoformat(ev['end'])
        return max(0, min(600, int((end - start).total_seconds() // 60)))
    except Exception:
        return 0


def _kid_event_match(ev, ev_id, p_id, p_cals, p_tags, matched_rules):
    # Same three-way binding My Day uses: passenger calendar ownership,
    # hashtag in the title, or a matched rule naming the passenger.
    if set(ev.get('calendar_ids') or []) & p_cals:
        return True
    title_l = (ev.get('title') or '').lower()
    if any(t in title_l for t in p_tags):
        return True
    parent_id = ev_id
    for suffix in ('_dropoff', '_pickup'):
        if parent_id.endswith(suffix):
            parent_id = parent_id[:-len(suffix)]
    for eid in {ev_id, parent_id, parent_id.split('_unrolled_')[0]}:
        for r in matched_rules.get(eid, []) or []:
            pax = r.get('passenger_ids') if isinstance(r, dict) else None
            if pax and str(p_id) in [str(x) for x in pax]:
                return True
    return False


def record_daily_stats(date_str: str = None) -> dict:
    """Snapshot today's per-driver drives/minutes and per-kid activity counts
    from the combined schedule cache. Upsert — safe to call repeatedly; the
    evening call (after most activities) wins."""
    date_str = date_str or datetime.date.today().isoformat()
    cache = storage.get_cached_schedule() or {}
    events = {str(e.get('id')): e for e in cache.get('events', [])}
    assignments = dict(cache.get('assignments') or {})
    assignments.update(cache.get('ghost_assignments') or {})
    matched_rules = cache.get('matched_rules') or {}

    day_events = {eid: e for eid, e in events.items()
                  if str(e.get('start', '')).startswith(date_str)
                  and e.get('event_type') != 'errand' and not e.get('trip_suppressed')}

    drivers = {}
    for ev_id, d_id in (cache.get('assignments') or {}).items():
        if not d_id or str(d_id).startswith('ghost_'):
            continue
        ev = day_events.get(str(ev_id))
        if not ev:
            continue
        d = drivers.setdefault(str(d_id), {'drives': 0, 'minutes': 0})
        d['drives'] += 1
        d['minutes'] += _minutes(ev)
    for er in cache.get('scheduled_errands', []):
        d_id = (er.get('driver') or {}).get('id')
        if d_id and str(er.get('start_time', '')).startswith(date_str):
            d = drivers.setdefault(str(d_id), {'drives': 0, 'minutes': 0})
            d['drives'] += 1

    kids = {}
    # child members only — the digest's "busy kids" line, not an everyone-audit
    for m in storage.get_all_members():
        p_id = m.get('passenger_id')
        if not p_id or m.get('role') != 'child':
            continue
        p_cals, p_tags = set(), set()
        for p in storage.get_all_passengers():
            if p.get('id') == p_id:
                p_cals = set(p.get('calendar_ids') or [])
                p_tags = {t.lower() for t in (p.get('hashtags') or [])}
                break
        seen_parents = set()
        for ev_id, ev in day_events.items():
            if not _kid_event_match(ev, ev_id, p_id, p_cals, p_tags, matched_rules):
                continue
            parent_id = ev_id
            for suffix in ('_dropoff', '_pickup'):
                if parent_id.endswith(suffix):
                    parent_id = parent_id[:-len(suffix)]
            seen_parents.add(parent_id)   # split legs = one activity
        if seen_parents:
            kids[m['id']] = len(seen_parents)

    row = {'date': date_str, 'drivers': drivers, 'kids': kids}
    storage.upsert_daily_stats(date_str, row)
    return row


def _fmt_minutes(mins: int) -> str:
    h, m = divmod(int(mins), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _driver_name(driver_id: str) -> str:
    m = storage.get_member_by_driver_id(driver_id)
    if m:
        return m.get('name') or driver_id
    for d in storage.get_all_drivers():
        if d.get('id') == driver_id:
            return d.get('name') or driver_id
    return driver_id


def build_weekly_digest(end_date: datetime.date = None, days: int = 7):
    """The recap text for the `days`-day window ending end_date (inclusive),
    or None when there is nothing at all to report."""
    end_date = end_date or datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days - 1)
    start_ts = datetime.datetime.combine(start_date, datetime.time.min).timestamp()
    day_strs = [(start_date + datetime.timedelta(days=i)).isoformat() for i in range(days)]
    members = {m['id']: m for m in storage.get_all_members()}

    def name_of(member_id):
        return (members.get(member_id) or {}).get('name') or member_id

    sections = []   # (header, [bullet lines]) — rendered one bullet per line

    # Driving (from snapshots)
    drivers = {}
    for row in storage.get_daily_stats(day_strs):
        for d_id, d in (row.get('drivers') or {}).items():
            agg = drivers.setdefault(d_id, {'drives': 0, 'minutes': 0})
            agg['drives'] += d.get('drives', 0)
            agg['minutes'] += d.get('minutes', 0)
    if drivers:
        lines = [f"• {_driver_name(d_id)} — {d['drives']} drive{'s' if d['drives'] != 1 else ''}"
                 + (f" · {_fmt_minutes(d['minutes'])}" if d['minutes'] else "")
                 for d_id, d in sorted(drivers.items(), key=lambda kv: -kv[1]['drives'])]
        sections.append(("🚗 Driving", lines))

    # Kid activities (from snapshots)
    kids = {}
    for row in storage.get_daily_stats(day_strs):
        for m_id, n in (row.get('kids') or {}).items():
            kids[m_id] = kids.get(m_id, 0) + n
    if kids:
        lines = [f"• {name_of(m_id)} — {n} activit{'ies' if n != 1 else 'y'}"
                 for m_id, n in sorted(kids.items(), key=lambda kv: -kv[1])]
        sections.append(("🏃 Activities", lines))

    # Chores + points (ledger is durable history — no snapshot needed)
    chore_entries = [e for e in storage.points_ledger_table.all()
                     if e.get('reason') == 'chore' and (e.get('delta') or 0) > 0
                     and (e.get('ts') or 0) >= start_ts]
    if chore_entries:
        per_kid = {}
        for e in chore_entries:
            per_kid[e['member_id']] = per_kid.get(e['member_id'], 0) + e['delta']
        n = len(chore_entries)
        lines = [f"• {name_of(m_id)} — +{pts} pts" for m_id, pts
                 in sorted(per_kid.items(), key=lambda kv: -kv[1])]
        sections.append((f"✅ Chores — {n} verified", lines))

    # Rewards granted this week
    granted = [r for r in storage.get_redemptions()
               if r.get('state') == 'approved' and (r.get('decided_at') or 0) >= start_ts]
    if granted:
        # Pooled grants have no single member — the whole family earned it.
        lines = [f"• {'Family goal' if r.get('pooled') else name_of(r['member_id'])}"
                 f" — {r.get('reward_title')}" for r in granted[:4]]
        if len(granted) > 4:
            lines.append(f"• …and {len(granted) - 4} more")
        sections.append((f"🎁 Rewards — {len(granted)} granted", lines))

    # Routines: days complete this week + current streak
    routine_members = {r['member_id'] for r in storage.get_routines()}
    routine_lines = []
    for m_id in sorted(routine_members, key=name_of):
        scheduled_days = complete_days = 0
        for ds in day_strs:
            items = storage.routines_for_day(m_id, ds)
            if not items:
                continue
            scheduled_days += 1
            if all(i.get('checked') for i in items):
                complete_days += 1
        if not scheduled_days:
            continue
        streak = storage.compute_streak(m_id)
        line = f"• {name_of(m_id)} — {complete_days}/{scheduled_days} days"
        if streak.get('current'):
            line += f" · 🔥 {streak['current']}"
        routine_lines.append(line)
    if routine_lines:
        sections.append(("📋 Routines", routine_lines))

    if not sections:
        return None
    period = (f"{start_date.strftime('%b')} {start_date.day} – "
              f"{end_date.strftime('%b')} {end_date.day}")
    blocks = [f"{header}\n" + "\n".join(lines) for header, lines in sections]
    return f"📊 Family Week in Review ({period})\n\n" + "\n\n".join(blocks)


def post_weekly_digest() -> bool:
    """Snapshot today (so the send-day counts), build, and post as Argyle to
    the family channel. False when there was nothing to report."""
    try:
        record_daily_stats()
    except Exception as e:
        print(f"[family_digest] send-day snapshot failed: {e}")
    text = build_weekly_digest()
    if not text:
        print("[family_digest] nothing to report this week; skipping post")
        return False
    from services.agent_tools_v2 import _post_chat_message
    storage.ensure_family_channel()
    channel = storage.get_family_channel()
    argyle = storage.ensure_argyle_member()
    _post_chat_message(channel, argyle, text)
    print("[family_digest] weekly digest posted to the family channel")
    return True
