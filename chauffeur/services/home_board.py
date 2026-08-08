"""What the wall panel shows when nobody has asked it for anything.

Every other Chauffeur surface answers a question you arrived with: which
chores are unclaimed, what are we eating, where is everyone. A panel screwed
to the kitchen wall is looked at by somebody walking past with their hands
full, who asked nothing. So the board is built around one claim — **the hero
says the next thing that is actually about to happen**, and the tiles below it
are glances, not pages.

Three rules the tiles follow, because a wall display fails differently from a
web page:

1. **Hide what is not SET UP; never hide what is merely quiet.**

   The first version of this rule was "a tile with nothing to say renders
   nothing", and it was wrong in practice — the panel kept dropping to four
   tiles and the family could not tell whether the map was empty or broken.
   The mistake was conflating two different silences. A household that has
   never made a shopping list wants no Lists tile; a household with a list
   that happens to be empty tonight wants to SEE that it is empty. Same for
   the map (where everyone is has no empty day), the calendar, and chores and
   routines once any are configured.

   So a builder returns `None` only when the feature is unconfigured, and
   otherwise returns a payload — possibly `{'empty': "…"}`, which renders as
   an honest sentence. The original instinct still holds where it belongs: a
   grid of boxes explaining that they are empty is the characteristic failure
   of every wall dashboard, and `{'empty': …}` is a real answer rather than a
   placeholder. What it is NOT is a reason to make a configured feature vanish.
2. **One request, one cache.** The tiles are assembled server-side and served
   as ONE payload, so a six-tile board costs one HTTP request per tick instead
   of six. `TTL_SECONDS` then protects the DB and Home Assistant when a second
   panel (or an HA dashboard card) polls on its own offset.
3. **Nothing here computes, proposes, or writes.** The meals tile reads the
   PINNED plate and shows nothing when none is pinned — it deliberately does
   not call `get_or_compose_plate`, which would compose a proposal (and
   persist one) every 60 seconds forever. A display that changes what it is
   displaying is not a display.
"""

import datetime
import re
import time
from typing import Callable, List, Optional

from services import storage

# The catalog. `label` is what the setup UI calls the tile; `blurb` is the
# sentence explaining what it is FOR, which is the thing a person picking six
# of nine tiles actually needs.
WIDGETS = [
    {'key': 'drives', 'icon': '🚗', 'label': 'The rest of the day',
     'blurb': "Every drive still ahead today, and who has it."},
    {'key': 'kids', 'icon': '🎒', 'label': 'Each kid',
     'blurb': "The same calm look at the day each child gets in their digest."},
    {'key': 'meals', 'icon': '🍽️', 'label': "Tonight's plate",
     'blurb': "What is planned to eat, once a plate is pinned for the day."},
    {'key': 'shopping', 'icon': '🛒', 'label': 'Lists',
     'blurb': "How much is open on each shopping list."},
    {'key': 'chores', 'icon': '⭐', 'label': 'Chore points',
     'blurb': "The points leaderboard, exactly as the chores kiosk shows it."},
    {'key': 'routines', 'icon': '🔁', 'label': 'Streaks',
     'blurb': "Who has kept their routine going, and for how long."},
    {'key': 'occasions', 'icon': '🎁', 'label': 'Coming up',
     'blurb': "The next occasion and how many days are left to get ready."},
    {'key': 'weather', 'icon': '🌤️', 'label': 'The week',
     'blurb': "A forecast chip per day. Needs a Home Assistant weather entity."},
    {'key': 'moments', 'icon': '📸', 'label': 'Latest moments',
     'blurb': "Recent photos from the family's events."},
    {'key': 'calendar', 'icon': '📅', 'label': "What's coming",
     'blurb': "The next few days on the family calendar, drives or not."},
    {'key': 'errands', 'icon': '📋', 'label': 'Errands waiting',
     'blurb': "What still needs doing, past-due first."},
    {'key': 'trips', 'icon': '🧭', 'label': 'Next trip',
     'blurb': "The next trip and how long until it starts."},
    {'key': 'map', 'icon': '🗺️', 'label': 'Where everyone is',
     'blurb': "Who is home, out, or driving. Needs Home Assistant."},
    {'key': 'intake', 'icon': '📬', 'label': 'Waiting to approve',
     'blurb': "How many intake proposals need a parent. A COUNT only — the "
              "mail itself stays off shared screens."},
]
WIDGET_KEYS = [w['key'] for w in WIDGETS]

# Everything the household has actually set up, in a sensible reading order.
# The earlier six-tile default was chosen when any quiet tile vanished, which
# made "show them all" look like a wall of empty boxes; under rule 1 the board
# prunes itself to what this family uses, so the honest default is everything.
# `intake` is the one exclusion — it is an admin surface and stays opt-in.
DEFAULT_WIDGETS = ['drives', 'calendar', 'kids', 'meals', 'map', 'chores',
                   'routines', 'shopping', 'errands', 'occasions', 'trips',
                   'weather', 'moments']

# Long enough to collapse several panels onto one build, short enough that
# checking a chore off in the kitchen and glancing at the wall agrees.
TTL_SECONDS = 20
_CACHE = {'key': None, 'at': 0.0, 'data': None}


# --- small shared helpers -------------------------------------------------

def _local_naive(dt: datetime.datetime) -> datetime.datetime:
    """Everything on this board gets compared against `now`, and the schedule
    cache mixes aware and naive stamps depending on which calendar an event
    came from. Comparing those raises, so they are flattened to local wall
    time once, here, rather than defensively at every call site."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _parse(val) -> Optional[datetime.datetime]:
    try:
        return _local_naive(datetime.datetime.fromisoformat(str(val)))
    except (TypeError, ValueError):
        return None


def _leg_event_id(leg_id: str) -> str:
    """init_{ev} / route_{ev}_1..3 / final_{ev} -> {ev}. Mirrors
    main._leg_event_id; duplicated rather than imported because importing main
    from a service is a cycle."""
    s = re.sub(r'^(init_|route_|final_)', '', str(leg_id))
    return re.sub(r'_[123]$', '', s)


def _clock(dt: datetime.datetime) -> str:
    return dt.strftime('%I:%M %p').lstrip('0')


def day_word(d: datetime.date, today: datetime.date) -> str:
    """'Today' / 'Tomorrow' / 'Wed'. Same convention as family_digest's
    day_label, shortened — a tile has room for three letters, not a date."""
    if d == today:
        return 'Today'
    if d == today + datetime.timedelta(days=1):
        return 'Tomorrow'
    return d.strftime('%a')


def _driver_index() -> dict:
    """driver_id -> {name, color, avatar, image}. Built once per board rather
    than looked up per drive: family_digest._driver_name scans every driver on
    every call, which is fine for a digest of six lines and not for a board
    rebuilt on a timer."""
    idx = {}
    for d in storage.get_all_drivers():
        idx[d.get('id')] = {'name': d.get('name') or 'Driver',
                            'color': d.get('color_code') or '#3b82f6',
                            'avatar': None, 'image': None}
    for m in storage.get_all_members():
        d_id = m.get('driver_id')
        if not d_id:
            continue
        idx[d_id] = {'name': m.get('name') or idx.get(d_id, {}).get('name') or 'Driver',
                     'color': m.get('color_code') or '#3b82f6',
                     'avatar': m.get('avatar'), 'image': m.get('image')}
    return idx


def todays_runs(target: datetime.date = None, sched: dict = None,
                now: datetime.datetime = None) -> List[dict]:
    """Every assigned drive and scheduled errand on one day, sorted by time,
    each tagged done / live / **over**.

    `over` is the one that matters, and it is computed HERE rather than by each
    consumer, because the hero and the drives tile both need it and the wall
    must not contradict itself. A drive is behind us if somebody marked it
    complete OR its end time has simply passed — and nobody marks drives
    complete. Reading only the manual flag put "Nothing left to drive today"
    directly above a tile headed "the rest of the day" listing a 5pm drive at
    6:34pm, which is the exact failure this shared builder existed to prevent.
    A drive under way is never over, whatever the clock says.
    """
    now = now or datetime.datetime.now()
    target = target or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    drivers = _driver_index()

    try:
        done_events = {_leg_event_id(l) for l in storage.get_completed_drives()}
        live_events = {_leg_event_id(l) for l in storage.get_in_progress_drives()}
    except Exception:
        done_events, live_events = set(), set()

    runs = []
    for ev_id, d_id in (sched.get('assignments') or {}).items():
        # Ghost drivers are the solver's "nobody real can do this" placeholder;
        # naming one on the wall would be inventing a person.
        if not d_id or str(d_id).startswith('ghost_'):
            continue
        ev = events.get(ev_id)
        start = _parse((ev or {}).get('start'))
        if not ev or not start or start.date() != target:
            continue
        d = drivers.get(d_id) or {'name': 'Driver', 'color': '#3b82f6'}
        end = _parse(ev.get('end')) or start
        live = ev_id in live_events
        done = ev_id in done_events
        runs.append({
            'id': ev_id, 'kind': 'event', 'title': ev.get('title') or 'Event',
            'location': ev.get('location') or None,
            'start': start.isoformat(), 'at': _clock(start),
            'end': end.isoformat(),
            'driver_id': d_id, 'driver': d['name'], 'color': d['color'],
            'avatar': d.get('avatar'), 'image': d.get('image'),
            'done': done, 'live': live,
            'over': bool(not live and (done or end < now)),
        })

    for er in (sched.get('scheduled_errands') or []):
        d_id = (er.get('driver') or {}).get('id')
        start = _parse(er.get('start_time'))
        if not d_id or not start or start.date() != target:
            continue
        d = drivers.get(d_id) or {'name': 'Driver', 'color': '#3b82f6'}
        end = _parse(er.get('end_time')) or start
        runs.append({
            'id': er.get('id') or er.get('title'), 'kind': 'errand',
            'title': er.get('title') or 'Errand',
            'location': er.get('location') or None,
            'start': start.isoformat(), 'at': _clock(start),
            'end': end.isoformat(),
            'driver_id': d_id, 'driver': d['name'], 'color': d['color'],
            'avatar': d.get('avatar'), 'image': d.get('image'),
            'done': False, 'live': False, 'over': bool(end < now),
        })

    runs.sort(key=lambda r: r['start'])
    return runs


# --- the hero -------------------------------------------------------------

def _hero(now: datetime.datetime, runs: List[dict]) -> dict:
    """The one thing that matters right now.

    A wall board that only tiles six lists is a worse phone — the app already
    KNOWS what is next, so the panel should lead with it. `next` is the first
    run not yet done; `minutes_until` is what makes it a countdown rather than
    a timetable, and negative values mean it should already be underway, which
    is exactly when somebody walking past needs to see it.
    """
    upcoming = [r for r in runs if not r['over']]
    live = next((r for r in upcoming if r['live']), None)
    nxt = live or (upcoming[0] if upcoming else None)

    hero = {'next': None, 'remaining': len(upcoming), 'later': [], 'all_done': False,
            'kids': []}
    if nxt:
        start = _parse(nxt['start']) or now
        hero['next'] = {**nxt,
                        'minutes_until': int(round((start - now).total_seconds() / 60))}
        hero['later'] = [r for r in upcoming if r['id'] != nxt['id']][:3]
    elif runs:
        # There WERE drives and they are all behind us. Saying so is a real
        # answer; a blank hero reads as a broken panel.
        hero['all_done'] = True
    return hero


# --- tile builders --------------------------------------------------------
# Each returns the tile's payload, or None when it has nothing to say.

def _tile_drives(now, runs, **_):
    # `over`, not `done` — the heading says "the rest of the day", so a drive
    # whose end time has passed does not belong here whether or not anybody
    # remembered to tap it complete. Reading `done` here while the hero read
    # the clock is what let the wall contradict itself.
    rest = [r for r in runs if not r['over']]
    if not rest:
        if not storage.get_all_drivers():
            return None                      # no drivers: the feature is unused
        return {'empty': "Nothing left to drive today." if runs
                else "No drives on the schedule today."}
    by_driver = {}
    for r in rest:
        by_driver.setdefault(r['driver_id'], {'driver': r['driver'], 'color': r['color'],
                                              'avatar': r.get('avatar'),
                                              'image': r.get('image'), 'runs': []})
        by_driver[r['driver_id']]['runs'].append(
            {'at': r['at'], 'title': r['title'], 'live': r['live']})
    return {'drivers': sorted(by_driver.values(), key=lambda d: -len(d['runs'])),
            'count': len(rest)}


def _tile_kids(now, kid_digest_fn=None, **_):
    """The kid digest, which main.py owns (it is the same builder the evening
    DMs use). Passed in rather than imported, because reaching into main from a
    service is the cycle this module is avoiding."""
    if not kid_digest_fn:
        return None
    try:
        digest = kid_digest_fn() or {}
    except Exception as e:
        print(f"[home_board] kid digests failed: {e}")
        return None
    kids = [k for k in (digest.get('kids') or {}).values() if k.get('lines')]
    if not kids:
        # No children in the household is unconfigured; children with a quiet
        # day is a thing worth saying out loud.
        if not any(m.get('role') == 'child' for m in storage.get_all_members()):
            return None
        return {'empty': "Nothing on for the kids today."}
    return {'label': digest.get('label'), 'kids': kids}


def _tile_meals(now, **_):
    """The PINNED plate only. Composing one here would make the wall panel a
    writer of meal plans, on a timer, forever."""
    try:
        plate = storage.get_plate(now.date().isoformat())
        items = (plate or {}).get('items') or []
        if not items:
            # A household with no dishes has never used meals at all; one with
            # dishes and no plate tonight has simply not decided yet.
            if not storage.get_dishes():
                return None
            return {'empty': "Nothing pinned for tonight yet."}
        dishes = storage.get_dishes_by_ids([i['dish_id'] for i in items])
        by_id = {d['id']: d for d in dishes}
        rows = [{'name': by_id[i['dish_id']].get('short_name')
                         or by_id[i['dish_id']].get('name'),
                 'image': by_id[i['dish_id']].get('image_url')}
                for i in items if i['dish_id'] in by_id]
        return {'dishes': rows, 'edited': bool(plate.get('edited'))} if rows \
            else {'empty': "Nothing pinned for tonight yet."}
    except Exception as e:
        print(f"[home_board] plate failed: {e}")
        return None


def _tile_shopping(now, **_):
    try:
        all_lists = storage.get_shopping_lists()
        if not all_lists:
            return None                       # never made a list: feature unused
        lists = []
        for l in all_lists:
            items = storage.get_shopping_items(l['id'])
            open_items = [i for i in items if not i.get('is_checked')]
            if open_items:
                lists.append({
                    'id': l.get('id'),
                    'name': l.get('name') or 'List',
                    'store': l.get('store'),
                    'open': len(open_items),
                    # The THINGS, not the count. "Groceries — 12" tells you
                    # nothing you can act on walking past; "milk, eggs, bread…"
                    # is the entire reason a list is on the wall.
                    'items': [i.get('name') or '' for i in open_items[:12]],
                })
        if not lists:
            return {'empty': "Nothing on the lists."}
        lists.sort(key=lambda x: -x['open'])
        return {'lists': lists[:3], 'total': sum(l['open'] for l in lists)}
    except Exception as e:
        print(f"[home_board] shopping failed: {e}")
        return None


def _tile_chores(now, **_):
    try:
        from services import status_tiers
        rows = storage.get_all_point_balances() or []
        rows = [r for r in rows if r.get('member_id')]
        if not rows:
            # Configured means the household set up the economy at all —
            # chores, or rewards to spend points on. Zeroes across the board
            # are a real answer ("nobody has earned anything yet"), not a
            # reason for the tile to disappear.
            if not (storage.get_all_chores() or storage.get_rewards()):
                return None
            return {'empty': "No points earned yet."}
        for r in rows:
            try:
                r['status'] = status_tiers.compute_member_status(r['member_id'], 'chore')
            except Exception:
                r['status'] = None
        rows.sort(key=lambda r: -(r.get('balance') or 0))
        return {'balances': rows[:6]}
    except Exception as e:
        print(f"[home_board] chores failed: {e}")
        return None


def _tile_routines(now, **_):
    try:
        member_ids = {r['member_id'] for r in storage.get_routines()}
        if not member_ids:
            return None
        rows = []
        for m in storage.get_all_members():
            if m['id'] not in member_ids:
                continue
            rows.append({'name': m.get('name'), 'color_code': m.get('color_code'),
                         'avatar': m.get('avatar'), 'image': m.get('image'),
                         'streak': storage.compute_streak(m['id'])})
        rows = [r for r in rows if r.get('streak')]
        if not rows:
            return {'empty': "No streaks going yet."}
        rows.sort(key=lambda r: (-(r['streak'].get('current') or 0), r['name'] or ''))
        return {'streaks': rows[:6]}
    except Exception as e:
        print(f"[home_board] routines failed: {e}")
        return None


def _tile_occasions(now, **_):
    try:
        today = now.date()
        rows = []
        for o in storage.get_occasions(include_done=False) or []:
            anchor = o.get('anchor_date') or o.get('window_start')
            try:
                d = datetime.date.fromisoformat(str(anchor)[:10])
            except (TypeError, ValueError):
                continue
            if d < today:
                continue
            rows.append({'title': o.get('title') or 'Occasion', 'date': d.isoformat(),
                         'kind': o.get('kind'), 'days': (d - today).days})
        if not rows:
            # Nothing upcoming, but the household clearly uses occasions if any
            # exist at all (including ones already done).
            if not storage.get_occasions(include_done=True):
                return None
            return {'empty': "Nothing coming up."}
        rows.sort(key=lambda r: r['days'])
        return {'occasions': rows[:3]}
    except Exception as e:
        print(f"[home_board] occasions failed: {e}")
        return None


def _tile_weather(now, **_):
    """Needs Home Assistant. The panel is pitched as standalone, so this tile
    disappearing when HA is absent is the designed behaviour, not a gap."""
    try:
        from services import ha_api
        from services import family_digest
        settings = storage.get_settings() or {}
        forecast = ha_api.get_weather_forecast(settings.get('weather_entity') or None)
        days = []
        for f in (forecast or [])[:5]:
            d = str(f.get('datetime') or '')[:10]
            if not d:
                continue
            try:
                dd = datetime.date.fromisoformat(d)
            except ValueError:
                continue
            hi, lo = f.get('temperature'), f.get('templow')
            days.append({
                'day': 'Today' if dd == now.date() else dd.strftime('%a'),
                'emoji': family_digest._WEATHER_EMOJI.get(str(f.get('condition') or ''), '🌤️'),
                'hi': round(hi) if hi is not None else None,
                'lo': round(lo) if lo is not None else None,
                'rain': round(f.get('precipitation_probability') or 0) or None,
            })
        return {'days': days} if days else None
    except Exception as e:
        print(f"[home_board] weather failed: {e}")
        return None


def _tile_moments(now, **_):
    try:
        from services import presence
        # A generous window rather than 48h: on a wall, last week's photo from
        # the game beats an empty frame, and the hearth overlay is what handles
        # "brand new" anyway.
        rows = presence.recent_moments(hours=24 * 30, limit=6) or []
        rows = [m for m in rows if m.get('media_url') or m.get('poster_url')
                or (m.get('attachment') or {}).get('url')]
        return {'moments': rows} if rows else None
    except Exception as e:
        print(f"[home_board] moments failed: {e}")
        return None


def _tile_calendar(now, **_):
    """What is coming that is not a drive. The drives tile answers "who is
    taking whom"; this answers "what is this family doing", which on most days
    is a different list — a dentist appointment nobody drives to still belongs
    on the wall."""
    try:
        sched = storage.get_cached_schedule() or {}
        horizon = now.date() + datetime.timedelta(days=3)
        rows = []
        for ev in (sched.get('events') or []):
            start = _parse(ev.get('start'))
            if not start or not (now <= start) or start.date() > horizon:
                continue
            rows.append({'day': day_word(start.date(), now.date()),
                         'at': '' if ev.get('all_day') else _clock(start),
                         'title': ev.get('title') or 'Event',
                         'start': start.isoformat()})
        # Never hidden. A family calendar with a quiet stretch is information;
        # a calendar tile that vanishes just looks broken.
        if not rows:
            return {'empty': "Nothing on the calendar for the next few days."}
        rows.sort(key=lambda r: r['start'])
        return {'events': rows[:6]}
    except Exception as e:
        print(f"[home_board] calendar failed: {e}")
        return None


def _tile_errands(now, **_):
    try:
        every = storage.get_all_errands() or []
        if not every:
            return None                       # never made one: feature unused
        rows = []
        for er in every:
            if er.get('is_completed') or er.get('status') == 'completed':
                continue
            rows.append({'title': er.get('title') or 'Errand',
                         'location': er.get('location') or None,
                         'past_due': er.get('status') == 'past_due',
                         'priority': er.get('priority') or 2})
        if not rows:
            return {'empty': "Nothing waiting."}
        # Past-due first, then by priority: a wall panel shows the thing that
        # has already slipped before the thing that has not.
        rows.sort(key=lambda r: (not r['past_due'], r['priority']))
        return {'errands': rows[:5], 'total': len(rows)}
    except Exception as e:
        print(f"[home_board] errands failed: {e}")
        return None


def _trip_rows(now) -> List[dict]:
    """Trips this install can know about WITHOUT calling Google, newest-first.

    Three sources, because no single one is complete:

    1. The `/api/trips` snapshot — the only place a real trip's dates and title
       exist, since both live on its Google calendar event. Written whenever
       somebody loads the trips page.
    2. Draft trips from `trip_metadata`, which carry their own mock dates and
       never touch Google at all.
    3. Spans derived from the cached schedule by grouping scheduled activities
       on `trip_id`. This is the safety net for the case that actually bit: a
       trip whose snapshot is stale or was never taken still shows up, because
       its POIs are sitting in the schedule cache with real dates on them.
    """
    seen, rows = set(), []

    def add(tid, title, start, end, location=None, image=None, draft=False):
        if not start or (tid and tid in seen):
            return
        if tid:
            seen.add(tid)
        end = end or start
        # background_url is not always a URL — older trips stored a search
        # phrase ("disney world") in it, which as an <img src> is a broken
        # image on the kitchen wall.
        img = str(image or '')
        img = img if img.startswith(('http://', 'https://', '/', 'data:')) else None
        rows.append({
            'id': tid, 'title': title or 'Trip', 'location': location or None,
            'image': img, 'draft': bool(draft),
            'start': start.isoformat(), 'end': end.isoformat(),
            # NEGATIVE days would mean "already started", so an in-progress
            # trip reports 0 and says so. The first version filtered anything
            # starting before today, which is precisely how a trip the family
            # was ON showed as "No trips planned".
            'days': max(0, (start - now.date()).days),
            'live': start <= now.date() <= end,
        })

    def as_date(val):
        if val in (None, ''):
            return None
        try:
            return datetime.datetime.fromisoformat(str(val).replace('Z', '+00:00')).date()
        except (TypeError, ValueError):
            pass
        try:
            return datetime.datetime.fromtimestamp(float(val)).date()
        except (TypeError, ValueError, OSError):
            return None

    for t in (storage.get_cached_trips() or {}).get('trips') or []:
        s, e = as_date(t.get('start')), as_date(t.get('end'))
        if s and e and e >= now.date():
            add(t.get('id'), t.get('title'), s, e, t.get('location'),
                t.get('background_url'), t.get('is_draft'))

    for t in storage.get_all_trip_metadata() or []:
        if not t.get('is_draft'):
            continue
        s, e = as_date(t.get('mock_start_date')), as_date(t.get('mock_end_date'))
        if s and (e or s) >= now.date():
            add(t.get('event_id'), t.get('title') or 'Draft trip', s, e,
                t.get('location'), t.get('background_url'), True)

    spans = {}
    for ev in (storage.get_cached_schedule() or {}).get('events') or []:
        tid = ev.get('trip_id')
        s, e = _parse(ev.get('start')), _parse(ev.get('end'))
        if not tid or not s:
            continue
        lo, hi = spans.get(tid, (s, e or s))
        spans[tid] = (min(lo, s), max(hi, e or s))
    for tid, (lo, hi) in spans.items():
        if hi.date() < now.date():
            continue
        meta = storage.get_trip_metadata(tid) or {}
        add(tid, meta.get('title'), lo.date(), hi.date(),
            meta.get('location'), meta.get('background_url'), meta.get('is_draft'))

    rows.sort(key=lambda r: (not r['live'], r['start']))
    return rows


def _tile_trips(now, **_):
    try:
        if not (storage.get_all_trip_metadata() or storage.get_cached_trips()):
            return None                       # no trips ever: feature unused
        rows = _trip_rows(now)
        return {'trips': rows[:4]} if rows else {'empty': "No trips planned."}
    except Exception as e:
        print(f"[home_board] trips failed: {e}")
        return None


def _tile_map(now, runs=None, **_):
    """Who is home, out, or driving right now. Needs Home Assistant for the
    zone; the driving half comes from in-progress legs and works without it,
    which is why a member with no person entity still appears when they are
    behind the wheel."""
    try:
        from services import ha_api
        driving = {r['driver_id']: r['title'] for r in (runs or []) if r.get('live')}
        rows = []
        for m in storage.get_all_members():
            if m.get('role') == 'helper' or m.get('system'):
                continue
            state = None
            ent = m.get('ha_person_entity')
            if ent:
                try:
                    s = ha_api.get_state(ent)
                    state = (s or {}).get('state')
                except Exception:
                    state = None
            leg = driving.get(m.get('driver_id'))
            # Everyone appears, tracked or not. "Where is everyone" has no
            # empty day, and a person silently missing from the list is worse
            # than a person shown as unknown — you cannot tell the difference
            # between "not tracked" and "not home".
            rows.append({'name': m.get('name'), 'color_code': m.get('color_code'),
                         'avatar': m.get('avatar'), 'image': m.get('image'),
                         'state': state or None, 'driving': leg})
        if not rows:
            return None                       # no family members at all
        # Anyone out ranks anyone home: "everybody is home" is the boring case.
        rows.sort(key=lambda r: (not r['driving'], (r['state'] or '') == 'home',
                                 r['name'] or ''))
        return {'people': rows[:6]}
    except Exception as e:
        print(f"[home_board] map failed: {e}")
        return None


def _tile_intake(now, **_):
    """A COUNT and nothing else. Intake is mail approvals and IMAP settings —
    an admin surface the kiosk rule keeps off shared screens — but "three
    things are waiting for a parent" is not confidential, and it is the only
    part of intake anybody needs from across a kitchen. The proposals
    themselves stay on /intake."""
    try:
        # Unconfigured means intake is switched off entirely; switched on with
        # an empty queue is "you are caught up", which is worth saying.
        if not (storage.get_settings() or {}).get('ingest_email_enabled'):
            return None
        # 'proposed' is the waiting-for-a-parent status — NOT 'pending', which
        # matches nothing and would have made this tile permanently silent.
        waiting = storage.get_proposals('proposed') or []
        return {'pending': len(waiting)} if waiting else {'empty': "Nothing waiting."}
    except Exception as e:
        print(f"[home_board] intake failed: {e}")
        return None


_BUILDERS: dict = {
    'drives': _tile_drives, 'kids': _tile_kids, 'meals': _tile_meals,
    'shopping': _tile_shopping, 'chores': _tile_chores, 'routines': _tile_routines,
    'occasions': _tile_occasions, 'weather': _tile_weather, 'moments': _tile_moments,
    'calendar': _tile_calendar, 'errands': _tile_errands, 'trips': _tile_trips,
    'map': _tile_map, 'intake': _tile_intake,
}


# --- assembly -------------------------------------------------------------

def _as_background(raw: Optional[str]) -> Optional[str]:
    """A URL is used as-is; anything else is treated as a search phrase and
    handed to the Unsplash endpoint that already backs trip artwork (which
    redirects, caches for a day, and falls back on its own). So "mountains at
    dusk" is a valid value, which is the point — nobody wants to go and find an
    image URL to hang a picture on their kitchen wall, and a household that has
    to find eleven of them will set none."""
    raw = str(raw or '').strip()
    if not raw:
        return None
    if raw.startswith(('http://', 'https://', '/', 'data:')):
        return raw
    import urllib.parse
    return f"api/unsplash/background?query={urllib.parse.quote(raw)}"


def _background_url(settings: dict) -> Optional[str]:
    return _as_background((settings or {}).get('panel_background'))


def backgrounds(settings: dict = None) -> dict:
    """`{'default': url|None, '<nav slug>': url}` — every page's picture,
    resolved. The whole map travels in the panel profile so a page change does
    not cost a round trip: the panel already has the answer before you tap."""
    settings = settings if settings is not None else (storage.get_settings() or {})
    out = {'default': _background_url(settings)}
    per_page = settings.get('panel_page_backgrounds') or {}
    if isinstance(per_page, dict):
        for slug, raw in per_page.items():
            slug = str(slug).strip().lower()
            url = _as_background(raw)
            if slug in NAV_SLUGS and url:
                out[slug] = url
    return out


def resolve_widgets(requested: Optional[str] = None, settings: dict = None) -> List[str]:
    """URL wins, then the stored panel profile, then the default set.

    The URL has to win because an HA dashboard card is a second panel with
    different needs, and its config channel is its own address. The stored
    profile exists so the display bolted to a wall needs no address at all —
    the case that a URL-only design serves worst.

    An empty result always falls back to the defaults. "Show nothing" is never
    what someone meant by a blank setting, and a blank screen on a wall is
    indistinguishable from a crash.
    """
    known = set(WIDGET_KEYS)

    def clean(seq):
        out = []
        for k in seq or []:
            k = str(k).strip().lower()
            if k in known and k not in out:
                out.append(k)
        return out

    if requested is not None:
        picked = clean(requested.split(','))
        if picked:
            return picked
    picked = clean((settings or {}).get('panel_widgets'))
    return picked or list(DEFAULT_WIDGETS)


# The shelf's vocabulary — the same slugs `?tabs=` already speaks, plus the
# home board itself. Kept here rather than in the template because the panel
# profile endpoint has to validate against it.
NAV_SLUGS = ['home', 'schedule', 'calendar', 'errands', 'shopping', 'occasions',
             'chores', 'routines', 'intake', 'trips', 'map', 'moments']
# Every destination except the admin one. An earlier six-slug default put more
# than half the app out of reach from the panel, which is not a shelf, it is a
# bookmark bar. The shelf measures itself and moves whatever does not fit into
# a "More" flyout, so the number of destinations is no longer a design
# constraint that has to be guessed here. Intake stays off: it is an admin
# surface (mail approvals, IMAP settings) and the kiosk rule has always been to
# keep it off shared screens.
DEFAULT_TABS = ['home', 'schedule', 'calendar', 'chores', 'routines', 'shopping',
                'errands', 'occasions', 'trips', 'map', 'moments']


def resolve_tabs(requested: Optional[str] = None, settings: dict = None) -> List[str]:
    """Same precedence as the tiles: URL, then profile, then defaults.

    `?tabs=none` is passed through untouched — that one means "this is an
    embedded card, give it no chrome at all", and it is the one case where
    showing nothing IS the request.
    """
    if requested is not None and requested.strip().lower() in ('', 'none'):
        return []
    known = set(NAV_SLUGS)

    def clean(seq):
        out = []
        for k in seq or []:
            k = str(k).strip().lower()
            if k in known and k not in out:
                out.append(k)
        return out

    if requested is not None:
        picked = clean(requested.split(','))
        if picked:
            return picked
    picked = clean((settings or {}).get('panel_tabs'))
    return picked or list(DEFAULT_TABS)


def profile(tabs: Optional[str] = None, widgets: Optional[str] = None) -> dict:
    """Everything a panel needs to know about itself, in one call — so a
    display bolted to a wall can be pointed at a bare URL and still come up
    configured. The alternative is a two-hundred-character bookmark that only
    the person who wrote it can maintain."""
    settings = storage.get_settings() or {}
    # storage.get_settings() returns the STORED dict, not a validated Settings,
    # so model defaults never appear in it. Absent has to mean 180 here or
    # every install that predates this arc reads as "idle return disabled" —
    # which is a silently-off feature, not a default. An explicit 0 is a real
    # choice and stays off.
    raw = settings.get('panel_idle_return_seconds')
    try:
        idle = 180 if raw is None else int(raw)
    except (TypeError, ValueError):
        idle = 180
    theme = str(settings.get('panel_theme') or 'dark').lower()
    return {'tabs': resolve_tabs(tabs, settings),
            'widgets': resolve_widgets(widgets, settings),
            'spans': settings.get('panel_tile_spans') or {},
            'row_height': grid_row_height(settings),
            'theme': theme if theme in ('light', 'dark', 'auto') else 'dark',
            'backgrounds': backgrounds(settings),
            'idle_seconds': max(0, idle)}


def build(requested: Optional[str] = None, kid_digest_fn: Callable = None,
          now: datetime.datetime = None) -> dict:
    """The whole board in one payload."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    keys = resolve_widgets(requested, settings)

    cache_key = ','.join(keys)
    if (_CACHE['data'] and _CACHE['key'] == cache_key
            and time.time() - _CACHE['at'] < TTL_SECONDS):
        return _CACHE['data']

    from services import family_digest
    # `now` threaded through, not left to default: the hero, the tiles and the
    # `over` flag must all be reasoning about the same instant.
    runs = todays_runs(now.date(), now=now)

    tiles = []
    for key in keys:
        builder = _BUILDERS.get(key)
        if not builder:
            continue
        try:
            payload = builder(now, runs=runs, kid_digest_fn=kid_digest_fn)
        except Exception as e:
            print(f"[home_board] tile '{key}' failed: {e}")
            payload = None
        if payload:  # rule 1: nothing to say -> no tile, no reserved space
            meta = next(w for w in WIDGETS if w['key'] == key)
            tiles.append({'key': key, 'icon': meta['icon'], 'label': meta['label'],
                          'data': payload})

    # The kids belong in the hero, not in a tile of their own. The hero band is
    # full width and was spending it restating the drives tile; a column per
    # child is the thing a family actually walks up to the panel to read, and
    # "Each Kid" was never a phrase anybody says out loud.
    hero = _hero(now, runs)
    kid_tile = next((t for t in tiles if t['key'] == 'kids'), None)
    if kid_tile:
        hero['kids'] = kid_tile['data'].get('kids') or []
        hero['kids_empty'] = kid_tile['data'].get('empty')
        tiles = [t for t in tiles if t['key'] != 'kids']

    try:
        weather = family_digest.weather_line(now.date())
    except Exception:
        weather = None

    # The temperature RIGHT NOW, not today's high. On these displays the
    # temperature is the second-largest thing on the screen after the clock,
    # and a forecast high shown that big is wrong for most of the day.
    temp_now, condition = None, None
    try:
        from services import ha_api
        ent = (settings.get('weather_entity') or '').strip()
        if not ent:
            ents = ha_api.get_entities('weather') or []
            ent = (ents[0] or {}).get('entity_id') if ents else None
        if ent:
            st = ha_api.get_state(ent) or {}
            attrs = st.get('attributes') or {}
            if attrs.get('temperature') is not None:
                temp_now = round(float(attrs['temperature']))
            condition = st.get('state')
    except Exception as e:
        print(f"[home_board] current temp failed: {e}")

    try:
        from services import status_protocols
        statuses = status_protocols.active_statuses(now.date().isoformat()) or []
    except Exception:
        statuses = []

    data = {
        'now': now.isoformat(),
        # Built by hand rather than with %-d: that directive is glibc-only and
        # raises on Windows, where this is developed.
        'date_label': f"{now.strftime('%A, %B')} {now.day}",
        'weather': weather,
        'temp_now': temp_now,
        'condition': condition,
        'condition_emoji': (family_digest._WEATHER_EMOJI.get(condition or '', '🌤️')
                            if condition else None),
        'background': _background_url(settings),
        'statuses': [{'label': s.get('label') or s.get('name'),
                      'emoji': s.get('emoji'), 'note': s.get('note')}
                     for s in statuses][:2],
        'hero': hero,
        'tiles': tiles,
        'widgets': keys,
        'spans': (settings.get('panel_tile_spans') or {}),
        'row_height': grid_row_height(settings),
    }
    _CACHE.update(key=cache_key, at=time.time(), data=data)
    return data


TAB_LABELS = {
    'home': 'Home', 'schedule': 'Drives', 'calendar': 'Calendar',
    'errands': 'Errands', 'shopping': 'Meals', 'occasions': 'Occasions',
    'chores': 'Chores', 'routines': 'Routines', 'intake': 'Intake',
    'trips': 'Trips', 'map': 'Map', 'moments': 'Moments',
}


def grid_row_height(settings: dict = None) -> int:
    """What one row of the board's grid is worth, in pixels.

    A span of 2 used to mean "as tall as whatever two content-sized rows
    happened to be" — a height decided by the other tiles in those rows, not by
    the household — and in the LAST row it did nothing at all, because there
    was no second row there to occupy. With a fixed unit, `rows` is a real
    measurement everywhere on the board.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    try:
        return max(80, min(600, int(settings.get('panel_grid_row_height', 240))))
    except (TypeError, ValueError):
        return 240


def catalog() -> dict:
    """Everything the setup UI needs to offer a choice. Includes the defaults
    so the editor can show what "leave it alone" actually means — a picker
    whose empty state is indistinguishable from a deliberate empty selection
    is how a blank wall panel gets shipped."""
    return {
        'widgets': WIDGETS,
        'widget_defaults': list(DEFAULT_WIDGETS),
        'tabs': [{'slug': s, 'label': TAB_LABELS.get(s, s)} for s in NAV_SLUGS],
        'tab_defaults': list(DEFAULT_TABS),
    }
