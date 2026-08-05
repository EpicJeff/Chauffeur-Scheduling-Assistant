"""Presence (Presence & Status arc, Slice 4 — docs/presence_status_design.md).

Whoever IS at the activity posts a photo moment into the event's Discuss chat;
it reaches everyone the schedule kept away. Three jobs live here:

1. The capture prompt — the feature itself. Chauffeur knows the game is live
   NOW, so shortly after start it taps the present adult(s): "You're at the
   game — send the family a moment?" The push deeplinks into the event thread
   with the camera affordance armed. A group chat never asks; this does.
2. Present / kept-away resolution from the solved schedule — the assigned
   driver plus every passenger-bound member is "at" the event; the kept-away
   adults are the differentiated-push audience. Access stays family-wide
   (the event channel is already household-minus-helpers); only the PUSH is
   routed. Kids never get moment pings — moments ride their existing surfaces.
3. The kiosk hearth feed — recent moments for the home/distant kiosk to light
   up with, unbidden.

Never nag: one prompt per event per day, only within the opening minutes,
only when someone is actually kept away.
"""
import datetime
import time

from services import storage, family_digest

# Prompt fires when now is within [start, start + PROMPT_WINDOW_MINS] — i.e.
# during the OPENING minutes, not after them (with the 2-min sweep cadence a
# prompt typically lands 0-2 min after start).
PROMPT_WINDOW_MINS = 20
# Skip blips — a 15-minute drop-off isn't a moment-worthy activity.
MIN_EVENT_MINS = 30
_MARKER = 'presence_prompt_sent'
_TOY_MARKER = 'presence_thinking_of_you_sent'

# --- Prompt-worthiness (family feedback 2026-08-04): a blind nudge on every
# 30-minute event would ask for a moment at a doctor's appointment. Three
# gates, checked in order:
#   1) PRIVATE_KEYWORDS hard-block — medical/solemn events never prompt.
#   2) Status suppression — an event matching a StatusProtocol keyword, or
#      one where the affected member of an active status is present, never
#      gets the outward "send a moment" ask (the INVERSION handles those
#      days: run_thinking_of_you_prompts sends love TOWARD the affected).
#   3) MOMENT_KEYWORDS allowlist — games/performances/celebrations prompt;
#      everything else stays organic (the thread still accepts moments,
#      Chauffeur just doesn't ask).
PRIVATE_KEYWORDS = [
    'appointment', 'appt', 'doctor', 'dr.', 'dentist', 'orthodont', 'therapy',
    'therapist', 'clinic', 'hospital', 'checkup', 'check-up', 'check up',
    'physical', 'surgery', 'infusion', 'treatment', 'counsel', 'funeral',
    'memorial', 'visitation', 'urgent care',
]
MOMENT_KEYWORDS = [
    # event shapes
    'game', 'match', 'meet', 'tournament', 'tourney', 'scrimmage', 'race',
    'recital', 'concert', 'performance', 'showcase', 'musical', 'ceremony',
    'graduation', 'party', 'birthday', 'celebration', 'competition',
    'invitational', 'championship', 'finals', 'playoff', 'field day',
    'talent show', 'science fair', 'spelling bee',
    # common kid activities that read as moment-worthy on their own
    'soccer', 'volleyball', 'basketball', 'baseball', 'softball', 'football',
    'hockey', 'lacrosse', 'tennis', 'swim', 'dive', 'gymnastics', 'dance',
    'cheer', 'track', 'cross country', 'wrestling', 'karate', 'taekwondo',
    'martial arts', 'golf', 'skate', 'ski', 'archery', 'bowling', 'crew',
    'rowing', 'rugby', 'theater', 'theatre', 'choir', 'band', 'orchestra',
]


def _event_text(ev) -> str:
    return f"{ev.get('title') or ''} {ev.get('description') or ''}".lower()


def prompt_worthiness(ev, present_ids, date_str):
    """'blocked' | 'status' | 'moment' | 'quiet'. Only 'moment' events get the
    outward capture prompt; 'status' days are handled by the inversion."""
    text = _event_text(ev)
    if any(k in text for k in PRIVATE_KEYWORDS):
        return 'blocked'
    try:
        from services import status_protocols
        for p in storage.get_all_status_protocols():
            if not p.get('enabled', True):
                continue
            if any((k or '').strip().lower() in text
                   for k in (p.get('keywords') or []) if (k or '').strip()):
                return 'status'
        for st in status_protocols.active_statuses(date_str):
            if st.get('member_id') and st['member_id'] in present_ids:
                return 'status'
    except Exception:
        pass  # status layer unavailable -> fall through to the allowlist
    if any(k in text for k in MOMENT_KEYWORDS):
        return 'moment'
    return 'quiet'


def _base_event_id(ev_id: str) -> str:
    s = str(ev_id)
    for suffix in ('_dropoff', '_pickup'):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    return s.split('_slice_')[0]


def _parse_iso(val):
    try:
        dt = datetime.datetime.fromisoformat(str(val))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def members_at_event(ev, ev_id, sched=None):
    """Members the schedule places AT this event: the assigned driver plus
    every passenger-bound member (any role — the same four-way binding My Day
    uses, so adults with passenger profiles count as present too)."""
    sched = sched or storage.get_cached_schedule() or {}
    matched_rules = sched.get('matched_rules', {}) or {}
    passengers = {p.get('id'): p for p in storage.get_all_passengers()}
    assignments = dict(sched.get('assignments', {}) or {})
    assignments.update(sched.get('ghost_assignments', {}) or {})

    present, seen = [], set()
    # Driver: check the base event and both split legs.
    base = _base_event_id(ev_id)
    for eid in (str(ev_id), base, f"{base}_dropoff", f"{base}_pickup"):
        d_id = assignments.get(eid)
        if d_id and not str(d_id).startswith('ghost_'):
            m = storage.get_member_by_driver_id(d_id)
            if m and not m.get('system') and m['id'] not in seen:
                seen.add(m['id'])
                present.append(m)
    # Passengers (kids AND adults with a passenger profile).
    for m in storage.get_all_members():
        if m.get('system') or not m.get('passenger_id') or m['id'] in seen:
            continue
        p = passengers.get(m['passenger_id']) or {}
        p_cals = set(p.get('calendar_ids') or [])
        p_tags = {t.lower() for t in (p.get('hashtags') or [])}
        if family_digest._kid_event_match(ev, str(ev_id), m['passenger_id'],
                                          p_cals, p_tags, matched_rules):
            seen.add(m['id'])
            present.append(m)
    return present


def moment_push_audience(channel, sched=None):
    """Kept-away ADULTS for a moment posted into an event channel: household
    minus helpers, minus kids (their surfaces carry moments — no new pings),
    minus everyone the schedule proves was at the event. Falls back to all
    non-helper adults when the event isn't in the cache (old thread)."""
    sched = sched or storage.get_cached_schedule() or {}
    ev_id = str(channel.get('event_id') or '')
    ev = next((e for e in sched.get('events', [])
               if _base_event_id(e.get('id')) == _base_event_id(ev_id)), None)
    present_ids = {m['id'] for m in members_at_event(ev, ev_id, sched)} if ev else set()
    return [m for m in storage.get_all_members()
            if m.get('role') in ('parent', 'adult') and not m.get('system')
            and m['id'] not in present_ids]


def run_capture_prompts(send, now=None):
    """Sweep today's live events and prompt the present adult(s) to share a
    moment. `send(member, title, body, path)` is injected (cars.run_sweep
    convention). Returns the base event ids prompted."""
    now = now or datetime.datetime.now()
    sched = storage.get_cached_schedule() or {}
    events = sched.get('events', []) or []
    today = now.date().isoformat()

    sent = dict(storage.get_app_state(_MARKER) or {})
    cutoff = (now - datetime.timedelta(days=2)).timestamp()
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    prompted = []

    for ev in events:
        ev_id = str(ev.get('id') or '')
        # Base events only — split legs and trip slices ride with their base.
        if ev_id != _base_event_id(ev_id):
            continue
        if ev.get('event_type') in ('errand', 'background_trip') or ev.get('trip_suppressed'):
            continue
        start = _parse_iso(ev.get('start'))
        end = _parse_iso(ev.get('end'))
        if not start or not end or start.date().isoformat() != today:
            continue
        if (end - start).total_seconds() < MIN_EVENT_MINS * 60:
            continue
        if not (start <= now <= start + datetime.timedelta(minutes=PROMPT_WINDOW_MINS)):
            continue
        key = f"{ev_id}:{today}"
        if key in sent:
            continue

        present = members_at_event(ev, ev_id, sched)
        present_adults = [m for m in present if m.get('role') in ('parent', 'adult')]
        if not present_adults:
            continue
        present_ids = {m['id'] for m in present}
        if prompt_worthiness(ev, present_ids, today) != 'moment':
            continue  # not moment-worthy (or a status/private event): no ask
        kept_away = [m for m in storage.get_all_members()
                     if m.get('role') in ('parent', 'adult') and not m.get('system')
                     and m['id'] not in present_ids]
        if not kept_away:
            continue  # everyone's there — no audience, no ask

        # Marker FIRST (house convention): a half-failing send must not
        # re-prompt every sweep.
        sent[key] = now.timestamp()
        storage.set_app_state(_MARKER, sent)

        title = (ev.get('title') or 'the activity').strip()
        channel = storage.get_or_create_event_channel(
            ev_id, title=title, event_end=str(ev.get('end') or '') or None)
        away_names = ', '.join(m.get('name', '?') for m in kept_away[:3])
        for m in present_adults:
            send(m, f"📸 You're at {title}",
                 f"Send the family a moment — {away_names} couldn't be there.",
                 f"/app?open_channel={channel['id']}&compose=moment")
        prompted.append(ev_id)

    if prompted:
        storage.set_app_state(_MARKER, sent)
    return prompted


def run_thinking_of_you_prompts(send, now=None):
    """The INVERSION (family feedback 2026-08-04): on a status day the arrow
    flips — the schedule knows Mom is at chemo, so instead of an outward
    "send a moment" ask, the FAMILY gets prompted to send love TOWARD her:
    "Mom — Chemo Day today. Send a little something to let them know you're
    thinking of them", deeplinked into each member's own DM with the affected
    member (private, personal, no new container). cover/help days only —
    give_space means the family said space, and clear_deck isn't absence.
    Once per (instance, date, member); kids gated by quiet hours (skip to a
    later sweep the same day, never lost); after 9am so it lands in the day,
    not at dawn. `send(member, title, body, path)` injected as usual."""
    from services import status_protocols, family_digest
    now = now or datetime.datetime.now()
    if now.hour < 9:
        return []
    today = now.date().isoformat()
    kid_quiet = family_digest.in_kid_quiet_hours(now, storage.get_settings() or {})

    sent = dict(storage.get_app_state(_TOY_MARKER) or {})
    cutoff = (now - datetime.timedelta(days=2)).timestamp()
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    delivered = []

    for st in status_protocols.active_statuses(today):
        if st.get('need') not in ('cover', 'help'):
            continue
        affected = storage.get_member(st.get('member_id') or '')
        if not affected or affected.get('role') == 'helper':
            continue
        label = f"{st.get('emoji') or '💙'} {st.get('name') or 'a hard day'}"
        for m in storage.get_all_members():
            if m['id'] == affected['id'] or m.get('system') \
                    or m.get('role') == 'helper':
                continue
            if m.get('role') == 'child' and kid_quiet:
                continue  # skip this sweep; a later one today still delivers
            key = f"{st['id']}:{today}:{m['id']}"
            if key in sent:
                continue
            sent[key] = now.timestamp()
            dm = storage.get_or_create_dm(m['id'], affected['id'])
            send(m, f"{label} — {affected.get('name', '?')} today",
                 f"Send a little something to let them know you're thinking "
                 f"of them 💙",
                 f"/app?open_channel={dm['id']}&compose=moment")
            delivered.append(key)

    if delivered:
        storage.set_app_state(_TOY_MARKER, sent)
    return delivered


def poster_url_for(att) -> str:
    """Thumbnail URL for a clip: the ffmpeg-extracted {stem}.jpg beside it
    (generated on demand if missing). Derived rather than stored, so clips
    that predate posters get one too. '' for photos — they are their own
    thumbnail."""
    if (att or {}).get('kind') != 'video':
        return ''
    url = str((att or {}).get('url') or '')
    if not url.startswith('/api/media/'):
        return ''
    stem = url.rsplit('/', 1)[-1].split('.')[0]
    # Only advertise a poster we can actually deliver (it exists, or ffmpeg is
    # installed to make it). Without this a box with no ffmpeg serves 404s and
    # every clip tile renders empty — worse than the black box we replaced.
    if not stem or not storage.poster_available(stem):
        return ''
    return f'/api/media/{stem}.jpg'


def moment_stream_meta(channel, message, sender=None):
    """Small payload rides the message SSE so an OPEN app can pop the moment
    itself — the kiosk hearth experience, for whoever is holding a phone.
    URLs only, never media bytes.

    Deliberately does NOT resolve who was at the event: that needs the cached
    schedule, and this runs on the send request path. The client suppresses
    the sender, which is the exclusion that actually matters; the full
    kept-away routing still governs the PUSH in the background fan-out."""
    att = (message or {}).get('attachment') or {}
    mid = (message or {}).get('id')
    by_message = f"/api/moments/{mid}/media"
    return {'moment': {
        'id': mid,
        'channel_id': (channel or {}).get('id'),
        'kind': att.get('kind') or 'photo',
        'media_url': str(att.get('url') or '') or by_message,
        'poster_url': (poster_url_for(att) or str(att.get('url') or '') or by_message),
        'body': (message or {}).get('body') or '',
        'sender_member_id': (message or {}).get('sender_member_id'),
        'sender_name': (sender or {}).get('name') or '?',
        'event_title': (channel or {}).get('title') or 'A family moment',
    }}


def _moment_row(m, members, event_title=None):
    """One moment shaped for display. `media_url` is the stable by-message
    URL — galleries use it instead of the inline photo data URL so a page of
    thumbnails is a few KB of JSON with lazy-loaded, cacheable images."""
    sender = members.get(m.get('sender_member_id')) or {}
    att = m.get('attachment') or {}
    return {
        'id': m.get('id'),
        'channel_id': m.get('channel_id'),
        'ts': m.get('ts'),
        'body': m.get('body') or '',
        'kind': att.get('kind') or 'photo',
        # Direct media-store URL when there is one (photos and clips both live
        # there now); the by-message URL stays the fallback that decodes
        # legacy inline photos.
        'media_url': str(att.get('url') or '') or f"/api/moments/{m.get('id')}/media",
        # Videos show their poster frame in tiles; photos are their own.
        'poster_url': (poster_url_for(att) or str(att.get('url') or '')
                       or f"/api/moments/{m.get('id')}/media"),
        'attachment': att,
        'reactions': m.get('reactions') or {},
        'event_id': m.get('event_id'),
        'event_title': event_title or m.get('event_title') or 'Family moment',
        'sender_name': sender.get('name') or '?',
        'sender_color': sender.get('color_code') or '#3b82f6',
        'sender_avatar': sender.get('avatar'),
        # Lets a surface decide whether THIS viewer may delete the moment
        # without re-fetching the message (the strip's lightbox opens rows
        # older than the thread's 100-message window).
        'sender_member_id': m.get('sender_member_id'),
    }


def recent_moments(hours: float = 12, limit: int = 12):
    """The kiosk hearth feed: recent moments with sender + event context."""
    since = time.time() - hours * 3600
    members = {m['id']: m for m in storage.get_all_members()}
    return [_moment_row(m, members)
            for m in storage.get_recent_event_moments(since, limit=limit)]


def moment_events(offset: int = 0, limit: int = 24):
    """Gallery top level: one card per EVENT, newest first, PAGED — the whole
    history, so it must never be loaded in one shot."""
    members = {m['id']: m for m in storage.get_all_members()}
    index = storage.get_event_moment_index()
    page = index[offset:offset + limit]
    items = []
    for b in page:
        cover = b.get('cover') or {}
        cover_att = cover.get('attachment') or {}
        names = [(members.get(sid) or {}).get('name') for sid in b.get('sender_ids') or []]
        by_message = f"/api/moments/{cover.get('id')}/media" if cover.get('id') else ''
        items.append({
            'channel_id': b['channel_id'],
            'event_id': b.get('event_id'),
            'event_title': b.get('event_title'),
            'count': b.get('count', 0),
            'latest_ts': b.get('latest_ts'),
            'cover_url': (poster_url_for(cover_att) or str(cover_att.get('url') or '')
                          or by_message),
            # The media itself, for the client's thumbnail-failed fallback.
            'cover_media_url': str(cover_att.get('url') or '') or by_message,
            'cover_kind': cover_att.get('kind') or 'photo',
            'sender_names': sorted(n for n in names if n),
        })
    return {'items': items, 'total': len(index),
            'offset': offset, 'has_more': offset + limit < len(index)}


def event_moments(channel_id: str, offset: int = 0, limit: int = 30):
    """Every moment for ONE event, newest first, paged."""
    members = {m['id']: m for m in storage.get_all_members()}
    channel = storage.get_channel(channel_id) or {}
    title = channel.get('title') or 'Family moment'
    all_moments = storage.get_channel_moments(channel_id)
    page = all_moments[offset:offset + limit]
    return {'items': [_moment_row(m, members, event_title=title) for m in page],
            'total': len(all_moments), 'offset': offset,
            'has_more': offset + limit < len(all_moments),
            'event_title': title, 'channel_id': channel_id}
