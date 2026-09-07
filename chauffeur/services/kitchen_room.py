"""The Kitchen ROOM — the family's ambient room on the wall.

Named kitchen_room, not kitchen: services/kitchen.py is the meals arc's
cook-time model (kitchen.totals) and was here first.

Spec: docs/superpowers/specs/2026-09-06-kitchen-design.md. The Study's
family-side twin: seven zones, one number each, from one endpoint. Laws:
attention-only furniture; quiet room = success; the room NEVER writes (this
module is reads only, pinned by test); family-safe by construction — no
threads/missions/mind/watchers/occasions imports, nothing sensitive in the
JSON, because the youngest eye in the house is the audience.

Every section is built inside try/except falling to a _CALM form: a broken
source makes a calm zone, never a broken room.
"""
import datetime
import logging
import time

from services import storage

logger = logging.getLogger(__name__)

MOMENT_CAPTIONS = 3
BOARD_TOP = 6
CALENDAR_NEXT = 3


def _calm(**extra):
    return {'calm': True, **extra}


def _fridge(since_ts: float) -> dict:
    n = storage.count_event_moments_since(since_ts)
    if not n:
        return _calm(new_moments=0, latest=[])
    latest = []
    for m in storage.get_recent_event_moments(since_ts, limit=MOMENT_CAPTIONS):
        who = ''
        try:
            member = storage.get_member(m.get('sender_member_id'))
            who = (member or {}).get('name') or ''
        except Exception:
            pass
        latest.append({'caption': (m.get('body') or m.get('event_title') or 'a moment'),
                       'who': who})
    return {'calm': False, 'new_moments': int(n), 'latest': latest}


def _counter() -> dict:
    from services import meals
    day = datetime.date.today().isoformat()
    plan = meals.eating_plan(day, 'dinner')
    plate = meals.showing_plate(day, plan)
    dishes = plate.get('dishes') or []
    if not dishes:
        return _calm(count=0, dishes=[], hands_mins=0)
    names = [d.get('short_name') or d.get('name') or 'a dish' for d in dishes]
    hands = 0
    try:
        totals = meals.plate_totals(dishes, day)
        hands = int(totals.get('prep_ahead_mins') or 0) + int(totals.get('finish_mins') or 0)
    except Exception:
        pass
    return {'calm': False, 'count': len(names), 'dishes': names,
            'hands_mins': hands}


def _board() -> dict:
    items = storage.get_shopping_items(include_checked=False)
    if not items:
        return _calm(items=0, top=[])
    return {'calm': False, 'items': len(items),
            'top': [(i.get('name') or i.get('title') or 'something')
                    for i in items[:BOARD_TOP]]}


def _flat(dt: datetime.datetime) -> datetime.datetime:
    """Cache events mix aware and naive stamps depending on which calendar
    they came from; comparing those raises (home_board._local_naive learned
    this first). Flattened to local wall time once, here."""
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone().replace(tzinfo=None)
        except Exception:
            dt = dt.replace(tzinfo=None)
    return dt


def _today_events(now: datetime.datetime):
    """Today's still-to-come events from the schedule CACHE — the
    calendar-shows-everything feed, never recomputed here (trip ownership
    and driver_events rules live upstream). The try covers the COMPARISON
    too: one malformed or mixed-tz event drops itself, never the day."""
    cache = storage.get_cached_schedule() or {}
    out = []
    for ev in cache.get('events', []):
        try:
            start = _flat(datetime.datetime.fromisoformat(ev.get('start')))
            if start.date() != now.date() or start < now:
                continue
            out.append((start, ev))
        except Exception:
            continue
    out.sort(key=lambda p: p[0])
    return out, (cache.get('assignments') or {})


def _door(now: datetime.datetime) -> dict:
    upcoming, assignments = _today_events(now)
    driven = [(s, e) for s, e in upcoming if assignments.get(e.get('id'))]
    nxt = driven[0] if driven else (upcoming[0] if upcoming else None)
    if not nxt:
        return _calm(mins=None, label='')
    start, ev = nxt
    label = f"{start.strftime('%H:%M')} — {ev.get('title') or 'Event'}"
    ab = (ev.get('arrive_by') or {}).get('label')
    if ab:
        label += f" [{ab}]"
    return {'calm': False, 'mins': max(0, int((start - now).total_seconds() // 60)),
            'label': label}


def _calendar(now: datetime.datetime) -> dict:
    upcoming, _ = _today_events(now)
    if not upcoming:
        return _calm(today=0, next=None)
    return {'calm': False, 'today': len(upcoming),
            'next': [f"{s.strftime('%H:%M')} {e.get('title') or 'Event'}"
                     for s, e in upcoming[:CALENDAR_NEXT]]}


def _radio() -> dict:
    from services import ma_api
    if not ma_api.available():
        return _calm(playing=False, track='')
    players = ma_api.command('players/all') or []
    if isinstance(players, dict):
        players = players.get('players') or players.get('items') or []
    for p in players:
        state = (p.get('state') or p.get('playback_state') or '').lower()
        if state == 'playing':
            cur = p.get('current_media') or p.get('current_item') or {}
            track = cur.get('title') or cur.get('name') or ''
            artist = cur.get('artist') or ''
            return {'calm': False, 'playing': True,
                    'track': (f"{track} — {artist}" if artist else track)}
    return _calm(playing=False, track='')


def _pet() -> dict:
    # get_pets, never the raw table: level is DERIVED from the owner's
    # lifetime xp (a stored 'level' is a lie), and retired pets are filtered.
    rows = storage.get_pets()
    if not rows:
        return _calm(count=0, pets=[])
    return {'calm': False, 'count': len(rows),
            'pets': [{'name': r.get('name') or 'Pet',
                      'level': int(r.get('level') or 1)} for r in rows[:4]]}


def state(since_ts: float = 0, now: datetime.datetime = None) -> dict:
    """The room's one feed. `since_ts` is the panel's own last-visit epoch
    (localStorage on the panel, study idiom) — it shapes only the fridge's
    catch-up count."""
    now = now or datetime.datetime.now()
    out = {'status': 'ok', 'ts': time.time()}
    sections = (('fridge', lambda: _fridge(float(since_ts or 0))),
                ('counter', _counter),
                ('board', _board),
                ('door', lambda: _door(now)),
                ('calendar', lambda: _calendar(now)),
                ('radio', _radio),
                ('pet', _pet))
    for name, build in sections:
        try:
            out[name] = build()
        except Exception as e:
            logger.debug(f"[kitchen] {name} fell to calm: {e}")
            out[name] = _calm()
    return out
