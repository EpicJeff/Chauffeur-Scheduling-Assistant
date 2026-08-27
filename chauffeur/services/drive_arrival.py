"""Arrival detection: a started drive leg completes itself when the driver
gets there.

The failure this closes, photographed off the wall at 4:07: Jeff tapped
Start Drive at 2:35, arrived, and nobody ever tapped complete — the stale
in_progress leg then lied to every surface that read it. The board now
refuses to let that flag extend an event's life (v2.142.2), but the flag
itself stayed wrong. The family's own observation: their locations are
already tracked, so the app KNOWS when the driver reached the destination —
completing the leg is a fact it can record itself.

Deliberately narrow:
  - Only legs somebody explicitly STARTED (in_progress). Arrival never
    starts or guesses at legs on its own; it only closes the loop a human
    opened. Untracked households simply keep the manual button.
  - Cached geocodes only. This runs every 30s in the push loop; a paid
    geocode lookup from a polling loop is a bill, and the solver has already
    geocoded any address it routed to.
  - A position has to be FRESH and PRECISE enough to prove arrival. A phone
    that last reported an hour ago, or a 2 km cell fix, proves nothing, and
    a false complete is worse than a stale flag — it un-tracks a drive that
    is genuinely happening.
"""
import datetime
import math
import re
from typing import List, Optional

from services import storage

# A generous parking lot. GPS accuracy widens the acceptance up to its own
# value, but past MAX_ACCURACY_M the fix is too vague to prove anything.
ARRIVE_RADIUS_M = 175
MAX_ACCURACY_M = 300
STALE_FIX_SECS = 15 * 60

# The TAP check is more generous than the passive sweep above: the driver
# has explicitly said "I think I'm done" and a school car park is a long way
# from the pin, so 300 m accepts the row where people actually stop. The
# passive sweep keeps its tighter radius — it acts with nobody watching.
TAP_RADIUS_M = 300
# The check-in push waits this long past the ETA (an estimate deserves
# slack), and gives up entirely after the expiry — a push about a drive
# from hours ago is noise, and next-open reconciliation owns that case.
NUDGE_GRACE_SECS = 3 * 60
NUDGE_EXPIRE_SECS = 3 * 3600


def _leg_event_id(leg_id: str) -> str:
    s = re.sub(r'^(init_|route_|final_)', '', str(leg_id))
    return re.sub(r'_[123]$', '', s)


def leg_is_toward_waiting(leg_id) -> bool:
    """Does this leg drive TOWARD somebody waiting, or does it CARRY them?

    'Dad is on the way!' is information exactly when a passenger is somewhere
    waiting for the car — and noise when they are sitting in it, which is what
    a plain home->event leg means in this model (the pickup-waypoint machinery
    exists precisely for the passenger who starts somewhere else). Legs that
    drive toward the waiting:

      * `init_*_1` — the drive TO a pickup waypoint (`_2` is them aboard,
        onward to the event);
      * any leg whose event is a `_pickup` slice — driving to collect them.

    Unknowable legs (None, or a route-leg id this cannot parse) count as
    carrying: a wrong silence costs one push, a wrong push teaches the family
    that the push means nothing.

    Lives here rather than in main because the drive sheet asks the same
    question to decide whether 'I'm outside' is a thing worth offering.
    """
    if not leg_id:
        return False
    s = str(leg_id)
    if re.match(r'^init_.*_1$', s):
        return True
    return _leg_event_id(s).endswith('_pickup')


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _dest_address(leg_id: str, events: dict) -> Optional[str]:
    """Where this leg is DRIVING TO. final_* legs come home; everything else
    heads for the event (split dropoff/pickup variants fall back to their
    base event when the variant id is not in the cache)."""
    if str(leg_id).startswith('final_'):
        from services import maps
        return maps.get_home_location()
    ev_id = _leg_event_id(leg_id)
    ev = events.get(ev_id) or events.get(re.sub(r'_(dropoff|pickup)$', '', ev_id))
    return (ev or {}).get('location') or None


def _fresh_position(pos: dict, now_ts: float) -> Optional[tuple]:
    """(lat, lon, accuracy_m) when the fix is recent and precise enough to
    prove arrival; None otherwise."""
    if not pos:
        return None
    lat, lon = pos.get('latitude'), pos.get('longitude')
    if lat is None or lon is None:
        return None
    acc = pos.get('gps_accuracy')
    try:
        acc = float(acc) if acc is not None else 0.0
    except (TypeError, ValueError):
        acc = 0.0
    if acc > MAX_ACCURACY_M:
        return None
    lu = pos.get('last_updated')
    if lu:
        try:
            ts = datetime.datetime.fromisoformat(str(lu).replace('Z', '+00:00')).timestamp()
            if now_ts - ts > STALE_FIX_SECS:
                return None
        except (TypeError, ValueError):
            pass  # unparseable timestamp: trust the state over dropping it
    return (float(lat), float(lon), acc)


def _driver_position(driver_id: str, ev_id: str, sched: dict,
                     member_by_driver: dict, now_ts: float) -> Optional[tuple]:
    """The drive sheet's own fix first — it comes from the phone that is
    driving this leg right now, and it is the only source a household with no
    Home Assistant companion app has at all. Then the HA person entity (it is
    in their pocket at the destination), then the assigned car's tracker (it
    is at least in the parking lot). Every source goes through the same
    freshness and precision gate, so a stale app fix loses to a live HA one."""
    m = member_by_driver.get(driver_id)
    if m:
        app_pos = storage.get_member_position(m.get('id')) or {}
        if app_pos.get('ts'):
            pos = _fresh_position({
                'latitude': app_pos.get('latitude'),
                'longitude': app_pos.get('longitude'),
                'gps_accuracy': app_pos.get('gps_accuracy'),
                'last_updated': datetime.datetime.fromtimestamp(
                    float(app_pos['ts']), datetime.timezone.utc).isoformat(),
            }, now_ts)
            if pos:
                return pos
    if m and m.get('ha_person_entity'):
        from services import ha_api
        s = ha_api.get_state(m['ha_person_entity'])
        if s:
            attrs = s.get('attributes') or {}
            pos = _fresh_position({
                'latitude': attrs.get('latitude'),
                'longitude': attrs.get('longitude'),
                'gps_accuracy': attrs.get('gps_accuracy'),
                'last_updated': s.get('last_updated'),
            }, now_ts)
            if pos:
                return pos
    car_id = (sched.get('car_assignments') or {}).get(ev_id)
    if car_id:
        from services import cars as cars_svc
        car = next((c for c in storage.get_all_cars()
                    if str(c.get('id')) == str(car_id)), None)
        if car and car.get('ha_device_tracker'):
            return _fresh_position(cars_svc.car_location(car) or {}, now_ts)
    return None


def _dest_geocode(leg_id: str, events: dict):
    """(address, geocode_row) for a leg's destination, or (address, None)
    when the pin is unusable — same precision rules as the passive sweep:
    a city-precision pin is kilometres wide and proves nothing."""
    dest = _dest_address(leg_id, events)
    if not dest:
        return None, None
    g = storage.get_cached_geocode(dest)
    if not g or g.get('precision') in ('failed', 'city'):
        return dest, None
    return dest, g


def eta_for_start(leg_id: str, now_ts: float,
                  lat=None, lng=None, accuracy=None) -> Optional[float]:
    """Absolute ETA (epoch seconds) computed the moment a drive starts.

    The schedule's own edge minutes are the default — the solver already
    priced this exact drive and they cost nothing to reuse. A fresh client
    fix upgrades that to a routed time from where the driver actually is,
    which matters when they start the drive from the store rather than the
    driveway. One Directions call at most, on an explicit human action —
    never from a loop."""
    sched = storage.get_cached_schedule() or {}
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    ev_id = _leg_event_id(leg_id)
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    d_id = assignments.get(ev_id)

    mins = None
    if lat is not None and lng is not None \
            and (accuracy is None or float(accuracy) <= MAX_ACCURACY_M):
        dest, g = _dest_geocode(leg_id, events)
        if g:
            from services import maps
            # Coordinates rounded to ~10 m so a driver two feet from their
            # last fix reuses the cached route instead of minting a new row.
            route = maps.get_route_geometry(
                'driver-position', dest,
                origin_lat=round(float(lat), 4), origin_lng=round(float(lng), 4),
                dest_lat=float(g['lat']), dest_lng=float(g['lon']))
            if route and route.get('duration_mins'):
                mins = float(route['duration_mins'])

    if mins is None:
        if str(leg_id).startswith('final_'):
            edge = ((sched.get('final_edges') or {}).get(d_id) or {}).get(ev_id) or {}
            try:
                mins = float(edge.get('travel_mins') or 0) or None
            except (TypeError, ValueError):
                mins = None
        elif d_id:
            from services import leave_by
            lead = leave_by.travel_into(sched, d_id, ev_id)
            mins = float(lead['travel_mins']) if lead else None

    return (now_ts + mins * 60) if mins else None


def tap_check(leg_id: str, lat=None, lng=None, accuracy=None,
              now_ts: float = None) -> dict:
    """The driver tapped the arrival push (or the app asked on their
    behalf). Three honest answers:

      {'arrived': True}   — fix is at the destination; the leg completes.
      {'arrived': False, 'eta_ts', 'eta_mins'}  — verifiably NOT there; a
          fresh ETA is computed and PARKED on the row (pending_eta_ts).
          Sharing it with the family is the driver's separate, deliberate
          act — the app never narrates somebody's lateness uninvited.
      {'arrived': None}   — no usable fix or no usable pin; the caller
          falls back to asking the human, which is where this started.

    The already-completed case reports success, not error: the passive
    sweep may have beaten the tap by a poll cycle, and telling the driver
    'unknown leg' for a drive that finished correctly reads as breakage."""
    now_ts = now_ts if now_ts is not None else datetime.datetime.now().timestamp()
    row = storage.get_drive_status(leg_id) or {}
    sched = storage.get_cached_schedule() or {}
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    ev_id = _leg_event_id(leg_id)
    ev = events.get(ev_id) or events.get(re.sub(r'_(dropoff|pickup)$', '', ev_id)) or {}
    title = ev.get('title') or ('home' if str(leg_id).startswith('final_') else 'your stop')

    if row.get('status') == 'completed':
        return {'arrived': True, 'already': True, 'title': title}

    fix_ok = (lat is not None and lng is not None
              and (accuracy is None or float(accuracy) <= MAX_ACCURACY_M))
    dest, g = _dest_geocode(leg_id, events)
    if not fix_ok or not g:
        return {'arrived': None, 'title': title}

    dist = _haversine_m(float(lat), float(lng), float(g['lat']), float(g['lon']))
    if dist <= max(TAP_RADIUS_M, float(accuracy or 0)):
        storage.mark_drive_status(leg_id, 'completed', arrived_ts=now_ts)
        return {'arrived': True, 'title': title, 'distance_m': round(dist)}

    eta_ts = eta_for_start(leg_id, now_ts, lat=lat, lng=lng, accuracy=accuracy)
    if eta_ts is None:
        # Not there, but no route either (no key, quota, uncached pin):
        # estimate from straight-line distance at town speeds rather than
        # answering nothing — the label says "about" for a reason.
        eta_ts = now_ts + max(2.0, (dist / 1000.0) / 0.6) * 60
    storage.mark_drive_status(leg_id, 'in_progress', pending_eta_ts=eta_ts)
    return {'arrived': False, 'title': title, 'eta_ts': eta_ts,
            'eta_mins': max(1, round((eta_ts - now_ts) / 60)),
            'distance_m': round(dist)}


def run_nudges(now_ts: float, notify) -> List[str]:
    """The check-in push: an in-progress leg past its ETA asks its DRIVER
    'arrived?' — once. Tapping opens the app, which answers with a location
    fix instead of a question (tap_check above). Drivers the passive sweep
    can see (HA-tracked) rarely get this far: their legs complete
    themselves. This is the lane for everybody else's phone.

    `notify` is main's _notify_member_lanes, passed in so this module stays
    importable without the app. Returns the nudged leg ids (for tests)."""
    rows = [r for r in storage.get_drive_status_rows('in_progress')
            if r.get('eta_ts') and not r.get('arrival_nudged_ts')]
    if not rows:
        return []
    sched = storage.get_cached_schedule() or {}
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    # include_archived: the leg is only nudged if its driver resolves here, so a
    # driver archived mid-week would have their in-flight drives skipped outright.
    member_by_driver = {m.get('driver_id'): m for m in storage.get_all_members(include_archived=True)
                        if m.get('driver_id')}
    nudged = []
    for row in rows:
        try:
            eta = float(row['eta_ts'])
            if now_ts < eta + NUDGE_GRACE_SECS:
                continue
            leg_id = row['leg_id']
            if now_ts > eta + NUDGE_EXPIRE_SECS:
                # Too old to ask about; burn the marker silently so a
                # restarted loop does not push about yesterday's drive.
                storage.mark_drive_status(leg_id, 'in_progress',
                                          arrival_nudged_ts=now_ts)
                continue
            ev_id = _leg_event_id(leg_id)
            d_id = assignments.get(ev_id)
            member = member_by_driver.get(d_id)
            if not member or str(d_id).startswith('ghost_'):
                continue
            ev = events.get(ev_id) or {}
            where = ('home' if str(leg_id).startswith('final_')
                     else (ev.get('title') or 'your stop'))
            storage.mark_drive_status(leg_id, 'in_progress',
                                      arrival_nudged_ts=now_ts)
            notify(member, f"Arrived at {where}?",
                   "Tap to check the drive off — or send the family a new time.",
                   f"/app?arrival={leg_id}")
            nudged.append(leg_id)
            # A drive nobody closed on time is friction (services/vitals.py).
            # Counting must never break the notifying.
            try:
                storage.bump_day_counter(
                    datetime.datetime.fromtimestamp(now_ts).date().isoformat(),
                    'arrival_nudge')
            except Exception:
                pass
        except Exception as e:
            print(f"drive_arrival nudge: {row.get('leg_id')}: {e}")
    return nudged


def check_leg_at(leg_id: str, lat, lng, accuracy=None,
                 now_ts: float = None) -> Optional[dict]:
    """Complete ONE started leg if this fix proves the driver is there.

    The passive sweep's rules exactly — the tighter radius, the cached
    street-level pin, a started leg only — because this runs unattended from
    a position ping rather than from somebody's tap. No routing call, no
    parked ETA, no question: it either closes the leg or says nothing.
    """
    now_ts = now_ts if now_ts is not None else datetime.datetime.now().timestamp()
    if lat is None or lng is None:
        return None
    try:
        acc = float(accuracy) if accuracy is not None else 0.0
    except (TypeError, ValueError):
        acc = 0.0
    if acc > MAX_ACCURACY_M:
        return None
    row = storage.get_drive_status(leg_id) or {}
    if row.get('status') != 'in_progress':
        return None
    sched = storage.get_cached_schedule() or {}
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    dest, g = _dest_geocode(leg_id, events)
    if not g:
        return None
    dist = _haversine_m(float(lat), float(lng), float(g['lat']), float(g['lon']))
    if dist > max(ARRIVE_RADIUS_M, acc):
        return None
    storage.mark_drive_status(leg_id, 'completed', arrived_ts=now_ts)
    return {'leg_id': leg_id, 'dest': dest, 'distance_m': round(dist)}


def check_arrivals(now_ts: float = None) -> List[dict]:
    """Complete every in_progress leg whose driver is verifiably AT the
    leg's destination. Returns what was completed (for the caller's log).
    Cheap when idle: one storage read and out."""
    legs = storage.get_in_progress_drives()
    if not legs:
        return []
    now_ts = now_ts if now_ts is not None else datetime.datetime.now().timestamp()
    sched = storage.get_cached_schedule() or {}
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    member_by_driver = {m.get('driver_id'): m for m in storage.get_all_members(include_archived=True)
                        if m.get('driver_id')}
    completed = []
    for leg in legs:
        try:
            dest = _dest_address(leg, events)
            if not dest:
                continue
            g = storage.get_cached_geocode(dest)
            if not g or g.get('precision') == 'failed':
                continue
            # City-precision pins are kilometres wide; "arrived in Cary"
            # proves nothing about a music shop.
            if g.get('precision') == 'city':
                continue
            ev_id = _leg_event_id(leg)
            pos = _driver_position(assignments.get(ev_id), ev_id, sched,
                                   member_by_driver, now_ts)
            if not pos:
                continue
            lat, lon, acc = pos
            dist = _haversine_m(lat, lon, float(g['lat']), float(g['lon']))
            if dist <= max(ARRIVE_RADIUS_M, acc):
                storage.mark_drive_status(leg, 'completed')
                completed.append({'leg_id': leg, 'dest': dest,
                                  'distance_m': round(dist)})
        except Exception as e:
            # One bad leg must not stop the sweep; the loop retries in 30s.
            print(f"drive_arrival: {leg}: {e}")
    return completed
