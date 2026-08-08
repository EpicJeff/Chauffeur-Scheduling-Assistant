"""Status Protocols (Presence & Status arc P1, docs/presence_status_design.md).

A StatusProtocol is a family day-type ("Chemo Day", "Night Shift", "Trip
Day") authored once in the family's own words; a StatusDay is one dated
instance of it. This module owns the semantics: resolving which statuses are
active on a date, and delivering the "never leave a kid guessing" beats —
the announcement when a day is set, the correction when plans change, the
digest heads-up line, and the dismissal-refresh line.

Rules of calm (design principles — argue before violating):
- The family's words are delivered VERBATIM; nothing here composes kid copy
  beyond neutral connective phrases.
- Kid sends respect kid quiet hours and SKIP rather than defer (the digest
  and My Day restate — stale reassurance is worse than none).
- A cleared/changed day is announced too: "never guessing" runs both
  directions, silence after a promise is its own kind of guessing.
- Statuses are date-bound; nothing in this module ever carries a status
  forward past its date.
"""
import datetime

from services import storage

NEEDS = {
    # slug -> (label shown on surfaces, short household meaning)
    'cover':      ('Cover for them', 'out of the rotation today'),
    'help':       ('Bring in help', 'the other parent is caregiving'),
    'clear_deck': ('Clear the deck', 'family time — keep the evening free'),
    'give_space': ('Give space', 'home but resting — keep it low-key'),
}


# How far a beat may reach beyond its instance's own dates. Bounds the
# storage query, not the family's intent — recovery arcs fit well inside it.
MAX_BEAT_REACH_DAYS = 45


def _matched_beats(proto: dict, day: dict, date_str: str):
    """Beats on this protocol that resolve to date_str for this instance
    (anchor start/end + offset_days)."""
    out = []
    try:
        d0 = datetime.date.fromisoformat(day.get('date'))
        d1 = datetime.date.fromisoformat(day.get('end_date') or day.get('date'))
        dq = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return out
    for b in (proto.get('beats') or []):
        anchor = d1 if b.get('anchor') == 'end' else d0
        try:
            if anchor + datetime.timedelta(days=int(b.get('offset_days') or 0)) == dq:
                out.append(b)
        except (ValueError, TypeError):
            continue
    return out


def active_statuses(date_str: str):
    """Resolved active statuses for a date: each instance whose span covers
    the date — OR whose beat timeline reaches it (a chemo recovery beat on
    day+2 makes that date a status day even though the calendar event was
    one day). Spans carry day-position awareness (day_pos/day_count/
    is_home_day); matched beats carry the family's per-day words and can
    override the need FOR THAT DAY. Returns [] on a normal day."""
    protocols = {p['id']: p for p in storage.get_all_status_protocols()}
    members = {m['id']: m for m in storage.get_all_members()}
    try:
        dq = datetime.date.fromisoformat(date_str)
        q_start = (dq - datetime.timedelta(days=MAX_BEAT_REACH_DAYS)).isoformat()
        q_end = (dq + datetime.timedelta(days=MAX_BEAT_REACH_DAYS)).isoformat()
    except (ValueError, TypeError):
        q_start = q_end = date_str
    out = []
    for day in storage.get_status_days(start=q_start, end=q_end):
        proto = protocols.get(day.get('protocol_id'))
        if not proto or not proto.get('enabled', True):
            continue
        span_end = day.get('end_date') or day.get('date')
        within_span = day.get('date') <= date_str <= span_end
        beats = _matched_beats(proto, day, date_str)
        if not within_span and not beats:
            continue
        affected = members.get(proto.get('member_id')) or {}
        setter = members.get(day.get('set_by')) or {}
        # Effective need FOR THIS DATE: a beat's override wins; otherwise the
        # protocol default applies only inside the span (a message-only beat
        # on day+3 never silently extends a driver ban).
        beat_need = next((b.get('need') for b in beats if b.get('need')), None)
        need = beat_need or ((proto.get('need') or 'give_space') if within_span else None)
        try:
            d0 = datetime.date.fromisoformat(day.get('date'))
            d1 = datetime.date.fromisoformat(span_end)
            day_count = max(1, (d1 - d0).days + 1)
            day_pos = (dq - d0).days + 1
        except (ValueError, TypeError):
            day_count, day_pos = 1, 1

        def _msgs(*audiences):
            return "\n".join(b.get('message') for b in beats
                             if b.get('message') and b.get('audience', 'kids') in audiences)
        out.append({
            'id': day['id'],
            'date': day.get('date'),
            'end_date': span_end,
            'day_pos': day_pos,
            'day_count': day_count,
            'is_home_day': day_count > 1 and date_str == span_end,
            'within_span': within_span,
            'protocol_id': proto['id'],
            'name': proto.get('name'),
            'emoji': proto.get('emoji') or '💙',
            'need': need or '',
            'need_label': NEEDS.get(need, ('', ''))[0] if need else '',
            'kid_message': proto.get('kid_message') or '',
            'adult_message': proto.get('adult_message') or '',
            'beat_kid_message': _msgs('kids', 'everyone'),
            'beat_adult_message': _msgs('adults', 'everyone'),
            'beat_affected_message': _msgs('affected', 'everyone'),
            'call_time': proto.get('call_time'),
            'note': day.get('note') or '',
            'member_id': proto.get('member_id'),
            'member_name': affected.get('name'),
            'set_by': day.get('set_by'),
            'set_by_name': setter.get('name'),
            'set_at': day.get('set_at'),
            'source': day.get('source') or 'manual',
            'source_detail': day.get('source_detail'),
        })
    return out


def _fmt_hhmm(hhmm: str):
    try:
        h, m = [int(x) for x in str(hhmm).split(':')[:2]]
        return datetime.time(h, m).strftime('%I:%M %p').lstrip('0')
    except (ValueError, TypeError):
        return str(hhmm)


def kid_lines(date_str: str):
    """The kid-facing digest/push lines for a date, family's words first.
    A protocol with no kid_message still yields its label — the kid must
    never see LESS than the adults planned around. An authored BEAT for the
    date always wins (the family wrote words for exactly this day of the
    timeline); otherwise spans speak by position (mirroring the kid
    digest's trip-line convention): day 1 is the family's full message,
    middle days count ("day 2 of 4"), the last day is the excited home
    beat."""
    lines = []
    for s in active_statuses(date_str):
        who = s['member_name'] or s['name']
        if s['beat_kid_message']:
            for part in s['beat_kid_message'].split("\n"):
                lines.append(f"{s['emoji']} {part}")
        elif not s['within_span']:
            pass  # adult/affected-only beat day: nothing for the kids
        elif s['is_home_day']:
            lines.append(f"🏠 {who} — home day! 🎉")
            continue
        elif s['day_count'] > 1 and s['day_pos'] > 1:
            lines.append(f"{s['emoji']} {s['name']} — day {s['day_pos']} of {s['day_count']}")
        else:
            body = s['kid_message'] or f"It's a {s['name']} day."
            line = f"{s['emoji']} {body}"
            if s['note']:
                line += f" ({s['note']})"
            lines.append(line)
        # Soft nightly call window on away nights (never the home day —
        # they're walking in the door). "Around", by design: a slid or
        # missed call is "catch you tomorrow", not a broken chain.
        if s['within_span'] and s['day_count'] > 1 and s['call_time'] \
                and s['day_pos'] < s['day_count']:
            lines.append(f"📞 Around {_fmt_hhmm(s['call_time'])} — call with {who}")
    return lines


def _when_phrase(date_str: str, now: datetime.datetime = None):
    now = now or datetime.datetime.now()
    try:
        d = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return date_str
    if d == now.date():
        return 'today'
    if d == now.date() + datetime.timedelta(days=1):
        return 'tomorrow'
    return f"{d.strftime('%A, %b')} {d.day}"  # %-d/%#d are platform-split


def _post_dm(member_id: str, body: str):
    from services.agent_tools_v2 import _post_chat_message
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], member_id)
    _post_chat_message(dm, argyle, body)


def _kids():
    return [m for m in storage.get_all_members()
            if m.get('role') == 'child' and not m.get('system')]


def _adults(exclude_ids=()):
    return [m for m in storage.get_all_members()
            if m.get('role') in ('parent', 'adult') and not m.get('system')
            and m.get('id') not in exclude_ids]


def announce_set(day_id: str, now: datetime.datetime = None):
    """The set-beat. Kids get the family's words as an Argyle DM (chat
    fan-out delivers push + HA lanes for free) — but only for today/tomorrow
    and outside kid quiet hours; further-out days wait for the D-1 evening
    digest (announcing Thursday's chemo day on Monday just moves the dread
    up). Adults ALWAYS hear about it (they plan around it), whoever set it
    excepted — you don't need a push about your own tap."""
    from services import family_digest
    now = now or datetime.datetime.now()
    statuses = [s for s in active_statuses_by_day_id(day_id)]
    if not statuses:
        return
    s = statuses[0]
    when = _when_phrase(s['date'], now)
    is_span = (s.get('end_date') or s['date']) != s['date']
    end_when = _when_phrase(s.get('end_date') or s['date'], now)
    if is_span:
        when = f"{when} through {end_when}"

    horizon = (now.date() + datetime.timedelta(days=1)).isoformat()
    kids_ok = s['date'] <= horizon and \
        not family_digest.in_kid_quiet_hours(now, storage.get_settings() or {})
    if kids_ok:
        body = s['kid_message'] or f"It's a {s['name']} day {when}."
        line = f"{s['emoji']} Heads up for {when}: {body}"
        if is_span:
            # The whole span up front — "never guessing" includes when it ends.
            line += f"\n🏠 Home {end_when}."
            if s.get('call_time'):
                line += f"\n📞 Call window most nights around {_fmt_hhmm(s['call_time'])}."
        if s['note']:
            line += f"\n{s['note']}"
        for kid in _kids():
            try:
                _post_dm(kid['id'], line)
            except Exception as e:
                print(f"Status kid DM failed for {kid.get('name')}: {e}")

    setter = s.get('set_by')
    for adult in _adults(exclude_ids={setter} if setter else ()):
        parts = [f"{s['emoji']} {s['name']} — {when}"]
        if s['adult_message']:
            parts.append(s['adult_message'])
        need = NEEDS.get(s['need'])
        if need:
            parts.append(f"Need: {need[0].lower()} ({need[1]}).")
        if is_span and s.get('call_time'):
            parts.append(f"📞 Nightly call window around {_fmt_hhmm(s['call_time'])}.")
        if s['note']:
            parts.append(s['note'])
        if s.get('source') == 'calendar':
            parts.append(f"📅 Set from the calendar: {s.get('source_detail') or 'a matching event'}."
                         f" Clear it from My Day if that's wrong — I won't re-set it.")
        elif s['set_by_name']:
            parts.append(f"Set by {s['set_by_name']}.")
        try:
            _post_dm(adult['id'], "\n".join(parts))
        except Exception as e:
            print(f"Status adult DM failed for {adult.get('name')}: {e}")


def announce_cleared(day_row: dict, now: datetime.datetime = None):
    """The correction-beat: a cleared today/tomorrow day is said out loud —
    a kid braced for a hard day deserves the relief as much as the warning.
    Neutral factual copy only (the family authored the day's meaning, not
    its cancellation). Quiet hours still skip kid sends; adults always."""
    from services import family_digest
    now = now or datetime.datetime.now()
    proto = storage.get_status_protocol(day_row.get('protocol_id')) or {}
    name = proto.get('name') or 'status'
    emoji = proto.get('emoji') or '💙'
    when = _when_phrase(day_row.get('date', ''), now)
    span_end = day_row.get('end_date') or day_row.get('date', '')
    if span_end != day_row.get('date', ''):
        when = f"{when} through {_when_phrase(span_end, now)}"

    horizon = (now.date() + datetime.timedelta(days=1)).isoformat()
    # Kid-relevant when the span touches today/tomorrow (an ongoing trip
    # cleared mid-span is exactly the "home early!" moment).
    if day_row.get('date', '') <= horizon and span_end >= now.date().isoformat():
        if not family_digest.in_kid_quiet_hours(now, storage.get_settings() or {}):
            line = f"{emoji} Change of plans — {when} isn't a {name} day after all."
            for kid in _kids():
                try:
                    _post_dm(kid['id'], line)
                except Exception as e:
                    print(f"Status clear kid DM failed for {kid.get('name')}: {e}")
    for adult in _adults():
        try:
            _post_dm(adult['id'], f"{emoji} {name} on {when} was cleared.")
        except Exception as e:
            print(f"Status clear adult DM failed for {adult.get('name')}: {e}")


def active_statuses_by_day_id(day_id: str):
    day = storage.get_status_day(day_id)
    if not day:
        return []
    return [s for s in active_statuses(day['date']) if s['id'] == day_id]


# --- P2: the calendar knows -------------------------------------------------

def auto_set_from_calendar(now: datetime.datetime = None, horizon_days: int = 7):
    """Keyword sweep over the cached schedule window: a calendar event whose
    title/description contains a protocol's trigger words auto-sets that
    status day — the set-burden lands on NOBODY, which is the whole point
    (the affected parent is least able to remember a tap on their worst day).
    Safety comes from the beat design, not from asking permission first: the
    family authored the keywords deliberately, adults are told immediately
    (with the matched event named and how to undo), and kids only ever hear
    about today/tomorrow — so a day set in advance has a built-in adult
    review window before any kid does. A cleared calendar-set day leaves a
    tombstone and is never re-set. Returns the day ids it created."""
    now = now or datetime.datetime.now()
    today = now.date()
    horizon = today + datetime.timedelta(days=horizon_days)
    protocols = [p for p in storage.get_all_status_protocols()
                 if p.get('enabled', True) and p.get('keywords')]
    if not protocols:
        return []
    existing = {(d.get('date'), d.get('protocol_id'))
                for d in storage.get_status_days(start=today.isoformat(),
                                                 end=horizon.isoformat())}

    # Collapse cached slices back to their real event (background trips are
    # cached one slice per day — a 5-day trip must become ONE 5-day span,
    # never five one-day instances), then span the event's own dates.
    spans = {}  # base id -> {'title','text','start','end'}
    for ev in (storage.get_cached_schedule() or {}).get('events', []):
        if ev.get('event_type') == 'errand':
            continue
        base = str(ev.get('id', '')).split('_slice_')[0]
        try:
            # The slice's own span when it has one. Collapsing slices back into
            # a span can only recover the part of the trip inside the solve
            # window — the days before it opened were never sliced — so a camp
            # already under way read as starting the day the window did, and
            # the protocol days were set against the wrong dates.
            s_dt = datetime.datetime.fromisoformat(
                str(ev.get('span_start') or ev['start'])).replace(tzinfo=None)
            e_dt = datetime.datetime.fromisoformat(
                str(ev.get('span_end') or ev['end'])).replace(tzinfo=None)
        except (ValueError, TypeError, KeyError):
            continue
        # exclusive-midnight ends (all-day convention) belong to the prior day
        e_date = e_dt.date()
        if e_date > s_dt.date() and e_dt.time() == datetime.time(0, 0):
            e_date -= datetime.timedelta(days=1)
        entry = spans.setdefault(base, {
            'title': ev.get('title') or '',
            'text': f"{ev.get('title') or ''} {ev.get('description') or ''}".lower(),
            'start': s_dt.date(), 'end': e_date})
        entry['start'] = min(entry['start'], s_dt.date())
        entry['end'] = max(entry['end'], e_date)

    created = []
    for span in spans.values():
        if span['end'] < today or span['start'] > horizon:
            continue
        for proto in protocols:
            if not any((kw or '').lower() in span['text']
                       for kw in proto['keywords'] if (kw or '').strip()):
                continue
            key = (span['start'].isoformat(), proto['id'])
            if key in existing or storage.status_auto_dismissed(*key):
                continue
            existing.add(key)
            day_id = storage.add_status_day({
                'date': span['start'].isoformat(), 'protocol_id': proto['id'],
                'end_date': span['end'].isoformat() if span['end'] > span['start'] else None,
                'note': '', 'set_by': None,
                'source': 'calendar', 'source_detail': span['title']})
            created.append(day_id)
            try:
                announce_set(day_id, now=now)
            except Exception as e:
                print(f"Status auto-set announce failed: {e}")
    return created


def unavailable_driver_dates(start: str, end: str):
    """P2 solver feed: (date, driver_id, label) for every status day in
    [start, end] whose protocol needs the affected member OUT of the driving
    rotation — 'cover' (they're resting/at treatment) and 'help' (they're
    being cared for). clear_deck/give_space days don't touch driving.
    main.refresh_schedule_logic turns these into synthetic one-day
    'unavailable' Rules, so the solver machinery needs nothing new."""
    members = {m['id']: m for m in storage.get_all_members()}
    out = []
    try:
        d = datetime.date.fromisoformat(start)
        end_d = datetime.date.fromisoformat(end)
    except (ValueError, TypeError):
        return out
    # Per-date, because beats make the need a function of the DAY: protocol
    # default 'cover' can relax to 'give_space' on day 2 (driving is fine
    # again), and a cover beat on day+1 extends the ban past a one-day
    # event. Emitted per (driver, date); contiguous runs are fine as
    # individual one-day rules.
    while d <= end_d:
        seen_drivers = set()
        for s in active_statuses(d.isoformat()):
            if s['need'] not in ('cover', 'help'):
                continue
            member = members.get(s.get('member_id')) or {}
            drv = member.get('driver_id')
            if not drv or drv in seen_drivers:
                continue  # not a driver — nothing to take out of the rotation
            seen_drivers.add(drv)
            out.append({'date': d.isoformat(), 'end_date': d.isoformat(),
                        'driver_id': drv,
                        'label': f"{s['name']} — {member.get('name')}"})
        d += datetime.timedelta(days=1)
    return out


def send_beat_dms(now: datetime.datetime = None):
    """Deliver today's adult/affected-audience beats as Argyle DMs, once per
    (instance, beat, date). Kids-audience beats need NO push machinery —
    they ride the existing surfaces (last night's digest previewed them,
    My Day shows them, the dismissal push restates them); DMing them too
    would be the N-pings failure. 'adults' excludes the affected member
    (day+1 care logistics are for the co-parent); 'affected' is the member
    themselves; 'everyone' reaches both (kids still via surfaces)."""
    now = now or datetime.datetime.now()
    today = now.date().isoformat()
    marks = dict(storage.get_app_state('status_beat_dms') or {})
    cutoff = now.timestamp() - 60 * 86400
    marks = {k: v for k, v in marks.items() if v >= cutoff}
    members = {m['id']: m for m in storage.get_all_members()}
    protocols = {p['id']: p for p in storage.get_all_status_protocols()}
    sent = []
    for s in active_statuses(today):
        proto = protocols.get(s['protocol_id']) or {}
        day_row = storage.get_status_day(s['id']) or {}
        for idx, b in enumerate(_matched_beats(proto, day_row, today)):
            audience = b.get('audience', 'kids')
            if audience == 'kids' or not (b.get('message') or '').strip():
                continue
            key = f"{s['id']}:{idx}:{today}"
            if key in marks:
                continue
            marks[key] = now.timestamp()
            body = f"{s['emoji']} {s['name']}: {b['message']}"
            targets = []
            if audience in ('adults', 'everyone'):
                targets += _adults(exclude_ids={s['member_id']} if s['member_id'] else ())
            if audience in ('affected', 'everyone') and s['member_id']:
                affected = members.get(s['member_id'])
                if affected:
                    targets.append(affected)
            for t in targets:
                try:
                    _post_dm(t['id'], body)
                except Exception as e:
                    print(f"Status beat DM failed for {t.get('name')}: {e}")
            sent.append(key)
    storage.set_app_state('status_beat_dms', marks)
    return sent


def send_coverage_reports(now: datetime.datetime = None, lookahead_days: int = 4):
    """The plan-assist beat (design doc: 'the crown jewel'): when a
    cover/help day or span is coming (or already running), the OTHER adults
    get one Argyle DM showing exactly what the schedule looks like without
    the affected driver — every event in the span with its resolved driver,
    unassigned ones flagged. Not a reminder: the solver already reshuffled
    (status days invalidate the caches); this makes the result — and the
    collisions — visible at the moment load spikes. Once per instance
    (app_state marker set only after a successful build, so an unsolved
    cache retries next sweep instead of going silent)."""
    now = now or datetime.datetime.now()
    today = now.date()
    horizon = (today + datetime.timedelta(days=lookahead_days)).isoformat()
    sched = storage.get_cached_schedule() or {}
    if not sched.get('events') and not sched.get('assignments'):
        return []  # not re-solved yet — retry next sweep
    sent_marks = dict(storage.get_app_state('status_coverage_sent') or {})
    cutoff = now.timestamp() - 60 * 86400
    sent_marks = {k: v for k, v in sent_marks.items() if v >= cutoff}

    protocols = {p['id']: p for p in storage.get_all_status_protocols()}
    members = {m['id']: m for m in storage.get_all_members()}
    assignments = dict(sched.get('assignments', {}))
    assignments.update(sched.get('ghost_assignments', {}))

    sent = []
    for day in storage.get_status_days(start=today.isoformat(), end=horizon):
        if day['id'] in sent_marks:
            continue
        proto = protocols.get(day.get('protocol_id'))
        if not proto or not proto.get('enabled', True):
            continue
        beat_needs = {b.get('need') for b in (proto.get('beats') or []) if b.get('need')}
        if (proto.get('need') or 'give_space') not in ('cover', 'help') \
                and not (beat_needs & {'cover', 'help'}):
            continue
        affected = members.get(proto.get('member_id')) or {}
        span_start = day.get('date')
        span_end = day.get('end_date') or span_start

        lines = []
        for ev in sorted(sched.get('events', []), key=lambda e: str(e.get('start', ''))):
            if ev.get('event_type') in ('errand', 'background_trip') or ev.get('trip_suppressed'):
                continue
            ev_id = str(ev.get('id', ''))
            if ev_id.endswith('_dropoff') or ev_id.endswith('_pickup'):
                continue  # split legs: the parent event line is enough here
            if not (span_start <= str(ev.get('start', ''))[:10] <= span_end):
                continue
            try:
                s_dt = datetime.datetime.fromisoformat(str(ev['start'])).replace(tzinfo=None)
                stamp = f"{s_dt.strftime('%a')} {s_dt.strftime('%I:%M %p').lstrip('0')}"
            except (ValueError, TypeError, KeyError):
                stamp = span_start
            d_id = assignments.get(ev_id)
            drv = None
            if d_id and not str(d_id).startswith('ghost_'):
                drv = next((m for m in members.values()
                            if m.get('driver_id') == d_id), None)
            who = (drv or {}).get('name')
            lines.append(f"• {stamp} — {ev.get('title') or 'Event'} — "
                         + (who if who else "⚠️ needs a driver"))

        when = _when_phrase(span_start, now)
        if span_end != span_start:
            when = f"{when} through {_when_phrase(span_end, now)}"
        header = (f"🧳 Coverage while {affected.get('name') or 'they'}'s out "
                  f"({proto.get('name')}, {when}):")
        if not lines:
            body = header + "\nNothing on the schedule needs covering. 🎉"
        else:
            shown = lines[:14]
            if len(lines) > 14:
                shown.append(f"…and {len(lines) - 14} more on the calendar.")
            body = "\n".join([header] + shown)
        n_open = sum(1 for l in lines if "needs a driver" in l)
        if n_open:
            body += f"\n⚠️ {n_open} still need a driver — tap the dashboard to sort them."

        target_adults = _adults(exclude_ids={proto.get('member_id')}
                                if proto.get('member_id') else ())
        for adult in target_adults:
            try:
                _post_dm(adult['id'], body)
            except Exception as e:
                print(f"Coverage report DM failed for {adult.get('name')}: {e}")
        sent_marks[day['id']] = now.timestamp()
        sent.append(day['id'])
    storage.set_app_state('status_coverage_sent', sent_marks)
    return sent
