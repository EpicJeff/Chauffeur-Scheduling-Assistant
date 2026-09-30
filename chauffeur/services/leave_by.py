"""When you actually have to leave.

The one number a family standing in the kitchen wants, and the app has always
had it — the solver computes the travel into every drive it assigns, and the
kid digest has printed "🚀 Leave by 8:47 AM with Vovo" since arc K5. It lived
inside `main.member_day`, so the wall panel's hero could not reach it and was
left saying "in 2 hr 26 min" about a start time nobody sets an alarm for.

**This module is the only place a departure is worked out.** Every surface
that states one — the Drives list, the desktop Schedule, the Time-to-leave
pushes, every hero, the drive sheet, the kid's leave-by — reads it from here:
Python callers through `legs()` / `for_run()`, the pages through the `legs`
that `stamp()` puts on every edge the schedule API serves. There used to be
four copies of this arithmetic (app.html, schedule_timeline.html, the push
builder in main.py, and here), each with its own idea of the rule, and the
family could see them disagree (2026-09-29): "The times should be the same
across every surface."

The rule, for every leg a driver drives:

- **Leaving HOME** (the day's first drive, or back out after a layover at
  home): as late as still gets there — start − the drive − the event's own
  arrive-early buffer − the household's leave margin (`leave_margin_mins`,
  one setting, default 5, adjustable on the Schedule page). After a layover it
  is never earlier than getting home.
- **Leaving an EVENT**: when it ends (plus its after-buffer). Nobody leaves a
  game early to shave a wait off the next drop-off.
- **The next leg of the same trip** (after a pickup, after dropping someone):
  straight on, when the previous leg arrives.

And **no travel time means no leave time**. A guessed departure is worse than
none: it is the kind of number a household plans around once, gets burned by,
and then stops trusting the whole board over.

A route edge is not always one drive. When the gap allows, the solver sends the
driver HOME in between (`home_waypoint`), and it can route through a passenger
pickup (`pickup_waypoint`); either way the edge's `travel_mins` is the SUM of
every leg. Reading that sum as one drive into the event is what once put a
leave time and a drive length on the hero that the Drives list contradicted.
`legs()` is the decomposition, and everything reads it.

`from_home_only=True` keeps departures from somewhere else out — the kid digest
wants "leave by" in the kitchen sense only, because a child reading "leave by
4:20" is being told when to put their shoes on. A layover at home counts:
that departure IS from home.
"""

import datetime
from typing import List, Optional

DEFAULT_MARGIN_MINS = 5


def margin_mins(settings: dict = None) -> int:
    """The household's leave margin: minutes added before every departure
    from home, on every surface. One setting (`leave_margin_mins`)."""
    if settings is None:
        try:
            from services import storage
            settings = storage.get_settings() or {}
        except Exception:
            # The solver reads this too; a settings read that fails must not
            # take a solve down with it.
            settings = {}
    raw = settings.get('leave_margin_mins')
    try:
        v = int(raw if raw is not None else DEFAULT_MARGIN_MINS)
    except (TypeError, ValueError):
        v = DEFAULT_MARGIN_MINS
    return max(0, min(60, v))


def _i(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _td(mins) -> datetime.timedelta:
    return datetime.timedelta(minutes=mins)


def _leg(depart, mins, frm, to):
    return {'depart': depart, 'mins': int(mins), 'from': frm, 'to': to}


def initial_legs(edge: dict, start: datetime.datetime, margin: int) -> List[dict]:
    """The day's first drive, from home. Through a passenger pickup when the
    edge says so (two legs, straight on); otherwise one."""
    if not edge or not start:
        return []
    bb = _i(edge.get('buffer_before_mins'))
    wp = edge.get('pickup_waypoint') or None
    if wp:
        a, b = _i(wp.get('from_driver_home_mins')), _i(wp.get('from_global_home_mins'))
        if a > 0 and b > 0:
            out = start - _td(a + b + bb + margin)
            return [_leg(out, a, 'home', 'pickup'),
                    _leg(out + _td(a), b, 'pickup', 'event')]
    t = _i(edge.get('travel_mins'))
    if t <= 0:
        return []
    return [_leg(start - _td(t + bb + margin), t, 'home', 'event')]


def route_legs(edge: dict, prev_end: datetime.datetime,
               start: datetime.datetime, margin: int) -> List[dict]:
    """From one event to the next, exactly the legs the Drives list draws:
    [to home, (home to pickup,) to the event] after a layover; [to pickup,
    to the event] through a pickup; one leg otherwise."""
    if not edge or not prev_end or not start:
        return []
    free = prev_end + _td(_i(edge.get('buffer_after_mins')))
    bb = _i(edge.get('buffer_before_mins'))
    home = edge.get('home_waypoint') or None
    pick = edge.get('pickup_waypoint') or None
    if home:
        to_home, from_home = _i(home.get('to_home_mins')), _i(home.get('from_home_mins'))
        fp = _i(pick.get('from_pickup_mins')) if pick else 0
        approach = from_home + fp
        home_by = free + _td(to_home)
        out = max(home_by, start - _td(approach + bb + margin))
        legs = [_leg(free, to_home, 'event', 'home')]
        if pick and from_home > 0:
            legs += [_leg(out, from_home, 'home', 'pickup'),
                     _leg(out + _td(from_home), fp, 'pickup', 'event')]
        else:
            legs.append(_leg(out, approach, 'home', 'event'))
        return legs
    if pick:
        tp, fp = _i(pick.get('to_pickup_mins')), _i(pick.get('from_pickup_mins'))
        return [_leg(free, tp, 'event', 'pickup'),
                _leg(free + _td(tp), fp, 'pickup', 'event')]
    t = _i(edge.get('travel_mins'))
    return [_leg(free, t, 'event', 'event')] if t > 0 else []


def final_legs(edge: dict, end: datetime.datetime) -> List[dict]:
    """After the day's last event: home, through a drop-off when there is one."""
    if not edge or not end:
        return []
    free = end + _td(_i(edge.get('buffer_after_mins')))
    wp = edge.get('dropoff_waypoint') or None
    if wp:
        a, b = _i(wp.get('to_global_home_mins')), _i(wp.get('to_driver_home_mins'))
        return [_leg(free, a, 'event', 'dropoff'),
                _leg(free + _td(a), b, 'dropoff', 'home')]
    t = _i(edge.get('travel_mins'))
    return [_leg(free, t, 'event', 'home')] if t > 0 else []


def _parse(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return _naive(value)
    try:
        return _naive(datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')))
    except ValueError:
        return None


def _naive(dt):
    # Wall-clock local, offset stripped rather than converted — the repo-wide
    # convention for event stamps.
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo else dt


def _event_index(sched: dict) -> dict:
    return {str(e.get('id')): e for e in (sched.get('events') or [])}


def _event(events: dict, ev_id) -> dict:
    return events.get(str(ev_id)) or events.get(_base_id(str(ev_id))) or {}


def stamp(sched: dict, margin: int = None) -> dict:
    """Put `legs` (ISO departures + minutes) on every initial, route and final
    edge of a schedule blob, in place, so the pages draw the departures this
    module decided instead of re-deriving them. Called on every schedule the
    API serves."""
    if not sched:
        return sched
    margin = margin_mins() if margin is None else margin
    events = _event_index(sched)
    sched['leave_margin_mins'] = margin

    def out(legs):
        return [dict(l, depart=l['depart'].isoformat()) for l in legs]

    for d_id, by_ev in (sched.get('initial_edges') or {}).items():
        for ev_id, edge in (by_ev or {}).items():
            if isinstance(edge, dict):
                edge['legs'] = out(initial_legs(
                    edge, _parse(_event(events, ev_id).get('start')), margin))
    for d_id, by_ev in (sched.get('route_edges') or {}).items():
        for ev_id, edge in (by_ev or {}).items():
            if isinstance(edge, dict):
                edge['legs'] = out(route_legs(
                    edge, _parse(_event(events, ev_id).get('end')),
                    _parse(_event(events, edge.get('to_event')).get('start')), margin))
    for d_id, by_ev in (sched.get('final_edges') or {}).items():
        for ev_id, edge in (by_ev or {}).items():
            if isinstance(edge, dict):
                edge['legs'] = out(final_legs(
                    edge, _parse(_event(events, ev_id).get('end'))))
    return sched


def travel_into(sched: dict, driver_id: str, event_id: str,
                from_home_only: bool = False, start: datetime.datetime = None,
                margin: int = None) -> Optional[dict]:
    """The departure toward `event_id`: `{'travel_mins', 'from_home',
    'depart'?, ...}`, or None when the schedule does not know.

    The departure is the one you set out on from somewhere you were resting
    — home, or the previous event — and the drive is every leg from there to
    the event. Initial edges are keyed by the event being driven to; route
    edges by the event being driven FROM, found here by their `to_event`.
    `depart` is present whenever the event's start is known (passed, or read
    from the schedule)."""
    if not driver_id or not event_id or str(driver_id).startswith('ghost_'):
        return None
    margin = margin_mins() if margin is None else margin
    events = _event_index(sched)
    start = _naive(start) or _parse(_event(events, event_id).get('start'))

    def lead_from(legs, from_home, **extra):
        legs = [l for l in legs]
        if not legs:
            return None
        mins = sum(l['mins'] for l in legs)
        if mins <= 0:
            return None
        lead = {'travel_mins': mins, 'from_home': from_home,
                'margin_mins': margin if from_home else 0, **extra}
        lead['depart'] = legs[0]['depart']
        return lead

    initial = ((sched.get('initial_edges') or {}).get(driver_id) or {})
    # `{id}_dropoff` is the split-leg key the ride cards use; member_day has
    # always looked under both.
    for key in (event_id, f"{event_id}_dropoff"):
        edge = initial.get(key)
        if edge and _i(edge.get('travel_mins')) > 0:
            bb = _i(edge.get('buffer_before_mins'))
            if not start:
                return {'travel_mins': _i(edge.get('travel_mins')),
                        'buffer_mins': bb, 'from_home': True,
                        'margin_mins': margin}
            return lead_from(initial_legs(edge, start, margin), True,
                             buffer_mins=bb,
                             home_location=edge.get('driver_home_location'),
                             via_pickup=bool(edge.get('pickup_waypoint')))

    for from_id, edge in ((sched.get('route_edges') or {}).get(driver_id) or {}).items():
        if not edge or edge.get('to_event') not in (event_id, f"{event_id}_dropoff"):
            continue
        home_wp = edge.get('home_waypoint') or None
        if from_home_only and not home_wp:
            continue
        prev_end = _parse(_event(events, from_id).get('end'))
        bb = _i(edge.get('buffer_before_mins'))
        # Where the driver sets out FROM — the day-of traffic overlay needs
        # a route, and a route edge's origin is the event it leaves.
        extra = {'from_event': from_id, 'buffer_mins': bb,
                 'via_pickup': bool(edge.get('pickup_waypoint'))}
        if not prev_end or not start:
            mins = _i(edge.get('travel_mins'))
            return ({'travel_mins': mins, 'from_home': False, 'margin_mins': 0,
                     **extra} if mins > 0 else None)
        legs = route_legs(edge, prev_end, start, margin)
        if home_wp:
            # The drive home is its own leg; the departure that matters is
            # back out from home, never earlier than getting there.
            return lead_from(legs[1:], True,
                             earliest=legs[0]['depart'] + _td(legs[0]['mins']),
                             home_location=home_wp.get('driver_home_location'),
                             **extra)
        return lead_from(legs, False, **extra)
    return None


def leave_at(start: datetime.datetime, lead: dict) -> Optional[datetime.datetime]:
    """The departure itself. `lead` is what `travel_into` returned."""
    if not start or not lead:
        return None
    if lead.get('depart'):
        return lead['depart']
    return _naive(start) - _td(lead['travel_mins'] + lead.get('buffer_mins', 0)
                               + lead.get('margin_mins', 0))


def clock(dt: datetime.datetime) -> str:
    """4:20 PM. Built with %I and stripped rather than %-I, which is glibc-only
    and raises on Windows, where this is developed."""
    return dt.strftime('%I:%M %p').lstrip('0')


def clock_label(ts: float) -> str:
    """An epoch stamp as the household's own clock reads it — '3:58 pm', or
    '15:58' with the 24-hour setting on. `clock()` above says a datetime the
    same way but always in 12-hour; this is the one that rides inside push
    bodies and the drive sheet, where the setting has to be honoured."""
    from services import storage
    dt = datetime.datetime.fromtimestamp(float(ts))
    if (storage.get_settings() or {}).get('time_format_24h'):
        return dt.strftime('%H:%M')
    return dt.strftime('%I:%M %p').lstrip('0').lower()


def for_run(sched: dict, driver_id: str, event_id: str,
            start: datetime.datetime, from_home_only: bool = False,
            live: bool = False, now: datetime.datetime = None) -> Optional[dict]:
    """Everything a surface needs to say it: `leave_at`, `leave_label`,
    `travel_mins`, `from_home`. None when the schedule cannot support the
    claim.

    `live=True` overlays TODAY's traffic (the day-of cache the sweep in
    services/maps maintains: a predictive morning pass, refined an hour
    before departure) and adds `traffic_delay_mins` when it moved anything.
    Surfaces that state a departure someone will act on today opt in; the
    solver and anything describing another day must not — which the overlay
    also enforces itself, so a tomorrow-digest caller passing live=True gets
    static numbers, not today's rush hour."""
    # Event stamps are wall-clock local that MAY carry an offset (Google
    # calendar ISO strings do). Strip rather than convert — the repo-wide
    # convention (main, watchers, digest all read them this way) — or the
    # overlay's naive `now` comparison raises and takes My Day down with it.
    if start is not None and start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if now is not None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    lead = travel_into(sched, driver_id, event_id, from_home_only, start=start)
    when = leave_at(start, lead) if lead else None
    if not when:
        return None
    out = {'leave_at': when.isoformat(), 'leave_label': clock(when),
           'travel_mins': lead['travel_mins'], 'from_home': lead['from_home']}
    if live:
        out.update(_day_of_overlay(sched, driver_id, event_id, start, lead,
                                   now) or {})
    return out


DEFAULT_READY_BUFFER_MINS = 10


def ready_for_covered(event: dict, start: datetime.datetime,
                      buffer_mins: int = None, live: bool = False,
                      now: datetime.datetime = None) -> Optional[dict]:
    """**Be ready at** — the covered-event twin of `for_run`.

    An outside hand drives it, so there is no departure of ours to state. But
    the pickup still happens at OUR door, and the drive from here to there is
    the same road whoever is at the wheel: `start − travel − buffer` is when a
    child needs shoes on and a bag by the door. The buffer is not a driver's
    scheduling slack (there is no driver of ours) — it is the minutes between
    being ready and the car actually arriving, so nobody is met at the kerb
    still looking for a shin pad.

    The honesty rule from `for_run` carries over verbatim: **no travel time,
    no claim**. And the read is CACHE-ONLY (`get_cached_travel_time`, the
    day-of row) — this runs inside a board builder a wall panel polls every
    sixty seconds, and that must never become an API call. The solve primes
    covered events' locations for exactly this reason.
    """
    from services import storage
    if not event or not start:
        return None
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    if now is not None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    dest = (event.get('location') or '').strip()
    if not dest:
        return None
    settings = storage.get_settings() or {}
    origin = (settings.get('home_location') or '').strip()
    if not origin:
        return None
    if buffer_mins is None:
        try:
            buffer_mins = int(settings.get('assist_ready_buffer_mins')
                              if settings.get('assist_ready_buffer_mins') is not None
                              else DEFAULT_READY_BUFFER_MINS)
        except (TypeError, ValueError):
            buffer_mins = DEFAULT_READY_BUFFER_MINS
    buffer_mins = max(0, min(120, buffer_mins))
    # ignore_age: these are free-flow durations between fixed addresses and
    # never go stale — the same reasoning the solve primes with.
    mins = storage.get_cached_travel_time(origin, dest, ignore_age=True)
    if mins is None or mins == storage.UNROUTABLE or mins <= 0:
        return None
    delay = None
    if live and now is not None and start.date() == now.date() and now < start:
        # Today's traffic, cache-read, EARLIER-only — identical to the rule
        # `_day_of_overlay` applies to a departure of our own.
        from services import maps
        row = maps.get_day_of_traffic(origin, dest)
        if row and row.get('duration_mins', 0) > mins:
            delay = row['duration_mins'] - mins
            mins = row['duration_mins']
    when = start - datetime.timedelta(minutes=mins + buffer_mins)
    out = {'ready_at': when.isoformat(), 'ready_label': clock(when),
           'travel_mins': mins, 'ready_buffer_mins': buffer_mins}
    if delay:
        out['traffic_delay_mins'] = delay
    return out


def _base_id(event_id: str) -> str:
    return event_id[:-8] if str(event_id).endswith('_dropoff') else str(event_id)


def _day_of_overlay(sched: dict, driver_id: str, event_id: str,
                    start: datetime.datetime, lead: dict,
                    now: datetime.datetime = None) -> Optional[dict]:
    """Today's traffic, laid over the solver's static minutes.

    Cache-read only — the maps sweep buys the numbers (twice per leg per
    day); a wall panel polling every 60 seconds must never turn into API
    calls. EARLIER only: the static matrix is essentially free-flow, so a
    slower day-of reading advances the departure, and a faster one is never
    allowed to delay a plan somebody may already be moving on.
    """
    from services import storage
    now = now or datetime.datetime.now()
    if start.date() != now.date() or now >= start:
        # The overlay is about TODAY: tomorrow's digest reading today's rush
        # hour would be confidently wrong in the other direction.
        return None
    if lead.get('via_pickup'):
        # The drive goes through a pickup; a direct origin -> destination
        # reading is a different road and would price the wrong thing.
        return None
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    dest = (events.get(_base_id(event_id)) or {}).get('location')
    if lead.get('from_home'):
        drv = next((d for d in storage.get_all_drivers()
                    if str(d.get('id')) == str(driver_id)), None)
        origin = (lead.get('home_location') or '').strip() \
            or ((drv or {}).get('home_location') or '').strip() \
            or (storage.get_settings() or {}).get('home_location')
    else:
        origin = (events.get(_base_id(lead.get('from_event') or '')) or {}).get('location')
    if not origin or not dest:
        return None
    # The keyed reader: the same house is spelled differently by the solver's
    # edges and the settings record, so the cache is coordinate-keyed and
    # maps owns the translation.
    from services import maps
    row = maps.get_day_of_traffic(origin, dest)
    if not row or row['duration_mins'] <= lead['travel_mins']:
        return None
    mins = row['duration_mins']
    delay = mins - lead['travel_mins']
    if lead.get('depart') and not lead.get('from_home'):
        # Straight on from the previous event: nobody can leave before it
        # ends, so traffic lengthens the drive and leaves the departure be.
        return {'travel_mins': mins, 'traffic_delay_mins': delay}
    when = leave_at(start, lead) - datetime.timedelta(minutes=delay)
    if lead.get('earliest') and when < lead['earliest']:
        when = lead['earliest']
    return {'leave_at': when.isoformat(), 'leave_label': clock(when),
            'travel_mins': mins,
            'traffic_delay_mins': delay}
