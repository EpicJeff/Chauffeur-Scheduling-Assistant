"""An OUTING: one trip out of the house — leaving home, however many stops,
back home.

The app has legs and it has events. It had no word for the thing that spans
them, which is exactly the unit that decides what has to be in the car: a
driver took a passenger to one event, drove straight on to a second, and
arrived without the second event's gear.

The knowledge was already here. `solver/matcher.py` chains each driver's day
and, for every gap, works out whether there is room to detour home — a gap over
45 minutes or a wait over 15, needing a 20-minute layover to be worth taking.
When there is room it hangs a `home_waypoint` on the route edge. When there is
not, it simply omits one. **The absence is the answer**, and this module is the
first thing to read it as a statement rather than as routing arithmetic.

Pure computation over the schedule cache: no storage of its own, nothing
written, safe to call on every poll.

Vocabulary: `run` already means a scheduled ride (`home_board.todays_runs`) and
`runway` already means a child's morning (`services/runway.py`). Neither is
this. An outing is an outing.
"""
import datetime
from typing import List, Optional

from services import storage


def _parse(raw) -> Optional[datetime.datetime]:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(str(raw).replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _as_date(raw) -> Optional[datetime.date]:
    if isinstance(raw, datetime.date) and not isinstance(raw, datetime.datetime):
        return raw
    if isinstance(raw, datetime.datetime):
        return raw.date()
    dt = _parse(raw)
    return dt.date() if dt else None


def outings_for(target_date=None, sched: dict = None,
                now: datetime.datetime = None) -> List[dict]:
    """Every trip out of the house on one day, one entry per driver per trip.

    Sorted by departure, which is the order a household acts in — the same
    rule `todays_runs` states for the wall.
    """
    now = now or datetime.datetime.now()
    target = _as_date(target_date) or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    route_edges = sched.get('route_edges') or {}

    # A driver's events for the day, in time order. Ghost drivers are the
    # solver's "nobody real can do this" placeholder and are not people.
    by_driver = {}
    for ev_id, d_id in (sched.get('assignments') or {}).items():
        if not d_id or str(d_id).startswith('ghost_'):
            continue
        ev = events.get(ev_id)
        start = _parse((ev or {}).get('start'))
        if not ev or not start or start.date() != target:
            continue
        by_driver.setdefault(str(d_id), []).append((start, ev_id, ev))

    out = []
    for d_id, rows in by_driver.items():
        rows.sort(key=lambda r: (r[0], str(r[1])))
        edges = route_edges.get(d_id) or {}
        chain = []
        for i, (start, ev_id, ev) in enumerate(rows):
            chain.append((start, ev_id, ev))
            # Does the driver pass through home before the next one? The
            # solver says so by hanging a home_waypoint on the edge leaving
            # THIS event; an edge with none means they carried straight on.
            last = i == len(rows) - 1
            went_home = bool((edges.get(ev_id) or {}).get('home_waypoint'))
            if last or went_home:
                out.append(_outing(d_id, chain))
                chain = []
    out.sort(key=lambda o: (o['start'], o['key']))
    return out


def _outing(d_id: str, chain: list) -> dict:
    ends = [_parse(ev.get('end')) or start for start, _eid, ev in chain]
    return {
        'key': f"{d_id}:{chain[0][1]}",
        'driver_id': d_id,
        'event_ids': [eid for _s, eid, _e in chain],
        'start': chain[0][0].isoformat(),
        'end': max(ends).isoformat(),
    }
