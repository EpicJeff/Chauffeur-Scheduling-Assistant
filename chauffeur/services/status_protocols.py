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
        if s['set_by_name']:
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
