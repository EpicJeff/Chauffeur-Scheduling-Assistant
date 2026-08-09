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


def _leg_event_id(leg_id: str) -> str:
    s = re.sub(r'^(init_|route_|final_)', '', str(leg_id))
    return re.sub(r'_[123]$', '', s)


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
    """The driver's phone first (it is in their pocket at the destination),
    the assigned car's tracker second (it is at least in the parking lot)."""
    m = member_by_driver.get(driver_id)
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
    member_by_driver = {m.get('driver_id'): m for m in storage.get_all_members()
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
