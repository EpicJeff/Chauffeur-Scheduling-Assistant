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


def active_statuses(date_str: str):
    """Resolved active statuses for a date: each dated instance joined to its
    (enabled) protocol plus display fields. Returns [] on a normal day."""
    protocols = {p['id']: p for p in storage.get_all_status_protocols()}
    members = {m['id']: m for m in storage.get_all_members()}
    out = []
    for day in storage.get_status_days(start=date_str, end=date_str):
        proto = protocols.get(day.get('protocol_id'))
        if not proto or not proto.get('enabled', True):
            continue
        affected = members.get(proto.get('member_id')) or {}
        setter = members.get(day.get('set_by')) or {}
        need = proto.get('need') or 'give_space'
        out.append({
            'id': day['id'],
            'date': day.get('date'),
            'protocol_id': proto['id'],
            'name': proto.get('name'),
            'emoji': proto.get('emoji') or '💙',
            'need': need,
            'need_label': NEEDS.get(need, NEEDS['give_space'])[0],
            'kid_message': proto.get('kid_message') or '',
            'adult_message': proto.get('adult_message') or '',
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


def kid_lines(date_str: str):
    """The kid-facing digest/push lines for a date, family's words first.
    A protocol with no kid_message still yields its label — the kid must
    never see LESS than the adults planned around."""
    lines = []
    for s in active_statuses(date_str):
        body = s['kid_message'] or f"It's a {s['name']} day."
        line = f"{s['emoji']} {body}"
        if s['note']:
            line += f" ({s['note']})"
        lines.append(line)
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

    horizon = (now.date() + datetime.timedelta(days=1)).isoformat()
    kids_ok = s['date'] <= horizon and \
        not family_digest.in_kid_quiet_hours(now, storage.get_settings() or {})
    if kids_ok:
        body = s['kid_message'] or f"It's a {s['name']} day {when}."
        line = f"{s['emoji']} Heads up for {when}: {body}"
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

    horizon = (now.date() + datetime.timedelta(days=1)).isoformat()
    if day_row.get('date', '') <= horizon and day_row.get('date', '') >= now.date().isoformat():
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
    created = []
    for ev in (storage.get_cached_schedule() or {}).get('events', []):
        if ev.get('event_type') == 'errand':
            continue
        try:
            ev_date = datetime.date.fromisoformat(str(ev.get('start', ''))[:10])
        except (ValueError, TypeError):
            continue
        if not (today <= ev_date <= horizon):
            continue
        text = f"{ev.get('title') or ''} {ev.get('description') or ''}".lower()
        for proto in protocols:
            if not any((kw or '').lower() in text
                       for kw in proto['keywords'] if (kw or '').strip()):
                continue
            key = (ev_date.isoformat(), proto['id'])
            if key in existing or storage.status_auto_dismissed(*key):
                continue
            existing.add(key)
            day_id = storage.add_status_day({
                'date': ev_date.isoformat(), 'protocol_id': proto['id'],
                'note': '', 'set_by': None,
                'source': 'calendar', 'source_detail': ev.get('title') or ''})
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
    out = []
    protocols = {p['id']: p for p in storage.get_all_status_protocols()}
    members = {m['id']: m for m in storage.get_all_members()}
    for day in storage.get_status_days(start=start, end=end):
        proto = protocols.get(day.get('protocol_id'))
        if not proto or not proto.get('enabled', True):
            continue
        if (proto.get('need') or 'give_space') not in ('cover', 'help'):
            continue
        member = members.get(proto.get('member_id')) or {}
        if not member.get('driver_id'):
            continue  # not a driver — nothing to take out of the rotation
        out.append({'date': day.get('date'),
                    'driver_id': member['driver_id'],
                    'label': f"{proto.get('name')} — {member.get('name')}"})
    return out
