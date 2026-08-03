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

    # Intake accountability (phase-2 (d), folded into the weekly digest
    # instead of a new push channel — the watchers already nudge stale
    # pending items; this is the week's summary of what intake did).
    all_props = storage.get_proposals()
    new_props = [p for p in all_props if (p.get('created_at') or 0) >= start_ts]
    pending = [p for p in all_props if p.get('status') == 'proposed']
    if new_props or pending:
        lines = []
        if new_props:
            approved = sum(1 for p in new_props if p.get('status') == 'approved')
            ignored = sum(1 for p in new_props if p.get('status') == 'ignored')
            lines.append(f"• {len(new_props)} new proposal{'s' if len(new_props) != 1 else ''}"
                         f" — {approved} approved, {ignored} ignored")
        if pending:
            lines.append(f"• {len(pending)} still waiting for a decision")
        sections.append(("📬 Intake", lines))

    if not sections:
        return None
    period = (f"{start_date.strftime('%b')} {start_date.day} – "
              f"{end_date.strftime('%b')} {end_date.day}")
    blocks = [f"{header}\n" + "\n".join(lines) for header, lines in sections]
    return f"📊 Family Week in Review ({period})\n\n" + "\n\n".join(blocks)


_WEATHER_EMOJI = {
    'sunny': '☀️', 'clear-night': '🌙', 'partlycloudy': '⛅', 'cloudy': '☁️',
    'rainy': '🌧️', 'pouring': '🌧️', 'lightning': '⛈️', 'lightning-rainy': '⛈️',
    'snowy': '❄️', 'snowy-rainy': '🌨️', 'hail': '🌨️', 'fog': '🌫️',
    'windy': '💨', 'windy-variant': '💨', 'exceptional': '⚠️',
}


def in_kid_quiet_hours(now: datetime.datetime, settings: dict) -> bool:
    """True when kid-facing sends must stay silent. The window (defaults
    20:30–07:00, wraps midnight; Settings kid_quiet_start/kid_quiet_end)
    gates the K1 evening digest and every future kid push (K2+). Equal
    start/end = window disabled."""
    def _mins(val, dflt):
        try:
            h, m = [int(x) for x in str(val or dflt).split(':')[:2]]
        except Exception:
            h, m = [int(x) for x in dflt.split(':')]
        return h * 60 + m
    start = _mins(settings.get('kid_quiet_start'), '20:30')
    end = _mins(settings.get('kid_quiet_end'), '07:00')
    cur = now.hour * 60 + now.minute
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def day_label(target: datetime.date) -> str:
    """'Today' / 'Tomorrow' / 'Fri 08/07' — shared by digest titles and the
    get_drive_digest tool's headers."""
    today = datetime.date.today()
    if target == today:
        return "Today"
    if target == today + datetime.timedelta(days=1):
        return "Tomorrow"
    return target.strftime('%a %m/%d')


def weather_line(target: datetime.date):
    """One-line forecast for the digest ("🌧️ 78°/61° · rain 60%"), or None.
    Works for any date inside the daily forecast window. Uses the configured
    weather_entity (auto-detect when unset); any HA problem just drops the
    line — weather never blocks a digest."""
    try:
        from services import ha_api
        settings = storage.get_settings() or {}
        forecast = ha_api.get_weather_forecast(settings.get('weather_entity') or None)
        for f in forecast:
            if str(f.get('datetime') or '')[:10] != target.isoformat():
                continue
            cond = str(f.get('condition') or '')
            parts = []
            hi, lo = f.get('temperature'), f.get('templow')
            if hi is not None:
                parts.append(f"{round(hi)}°" + (f"/{round(lo)}°" if lo is not None else ""))
            precip = f.get('precipitation_probability')
            if precip:
                parts.append(f"rain {round(precip)}%")
            if not parts and not cond:
                return None
            line = f"{_WEATHER_EMOJI.get(cond, '🌤️')} " + (" · ".join(parts) or cond)
            # ≥50% rain: say the actionable thing, not just the number
            if (precip or 0) >= 50:
                line += " — pack rain gear ☔"
            return line
    except Exception as we:
        print(f"Digest weather error: {we}")
    return None


def build_drive_digests(target_date: datetime.date = None) -> dict:
    """Per-driver drive-digest content for one day from the combined schedule
    cache (assigned events + scheduled errands, prep-kit items appended,
    sorted by time, capped at 6 lines). Defaults to TOMORROW (the evening DM's
    day). Returns {'date', 'label', 'weather', 'drivers': {driver_id:
    {'title', 'lines', 'count'}}}. ONE implementation shared by the evening
    push-loop delivery (main._send_tomorrow_digests) and the read-only
    get_drive_digest agent tool — the builder never delivers."""
    from services import prep_kits
    tomorrow = target_date or (datetime.date.today() + datetime.timedelta(days=1))
    cache = storage.get_cached_schedule() or {}
    events = {e.get("id"): e for e in cache.get("events", [])}
    kits = storage.get_prep_kits()
    pax = prep_kits.passenger_objs()

    per_driver = {}
    for ev_id, d_id in (cache.get("assignments") or {}).items():
        if not d_id or str(d_id).startswith("ghost_"):
            continue
        ev = events.get(ev_id)
        if not ev:
            continue
        try:
            start = datetime.datetime.fromisoformat(ev["start"])
        except Exception:
            continue
        if start.date() != tomorrow:
            continue
        title = ev.get("title") or "Event"
        prep = prep_kits.items_for_event(ev, kits, pax)
        if prep:
            title += f" (bring: {', '.join(prep[:4])})"
        per_driver.setdefault(d_id, []).append((start, title))

    for er in cache.get("scheduled_errands", []):
        d_id = (er.get("driver") or {}).get("id")
        if not d_id:
            continue
        try:
            start = datetime.datetime.fromisoformat(er["start_time"])
        except Exception:
            continue
        if start.date() != tomorrow:
            continue
        per_driver.setdefault(d_id, []).append((start, f"Errand: {er.get('title') or 'Errand'}"))

    label = day_label(tomorrow)
    drivers = {}
    for d_id, items in per_driver.items():
        items.sort(key=lambda x: x[0])
        lines = [f"{start.strftime('%I:%M %p').lstrip('0')} - {title}"
                 for start, title in items[:6]]
        if len(items) > 6:
            lines.append(f"...and {len(items) - 6} more")
        n = len(items)
        drivers[d_id] = {"title": f"{label}: {n} drive{'s' if n != 1 else ''}",
                         "lines": lines, "count": n}
    return {"date": tomorrow.isoformat(), "label": label,
            "weather": weather_line(tomorrow),
            "drivers": drivers}


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
