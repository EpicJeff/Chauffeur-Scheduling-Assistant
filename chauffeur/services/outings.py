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
    final_edges = sched.get('final_edges') or {}

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
        d_final_edges = final_edges.get(d_id) or {}
        chain = []
        for i, (start, ev_id, ev) in enumerate(rows):
            chain.append((start, ev_id, ev))
            # Does the driver pass through home before the next one? The
            # solver says so by hanging a home_waypoint on the edge leaving
            # THIS event; an edge with none means they carried straight on.
            last = i == len(rows) - 1
            went_home = bool((edges.get(ev_id) or {}).get('home_waypoint'))
            if last or went_home:
                # Only the chain that IS the driver's actual last outing of
                # the day gets the drive home added — a mid-day outing cut at
                # a home_waypoint already ends when the layover starts at
                # home, and the spec does not touch that.
                out.append(_outing(d_id, chain, d_final_edges if last else None))
                chain = []
    out.sort(key=lambda o: (o['start'], o['key']))
    return out


def _outing(d_id: str, chain: list, final_edges_for_driver: dict = None) -> dict:
    ends = [_parse(ev.get('end')) or start for start, _eid, ev in chain]
    end = max(ends)
    # The turn-over point is the last outing's end — the drive home — rather
    # than the last event's end. `final_edges[d_id][last_event_id]` is the
    # solver's own travel_mins for that leg; an absent or malformed edge
    # leaves `end` exactly what it already was.
    if final_edges_for_driver:
        last_ev_id = chain[-1][1]
        edge = final_edges_for_driver.get(last_ev_id) or {}
        travel_mins = edge.get('travel_mins')
        if isinstance(travel_mins, (int, float)) and not isinstance(travel_mins, bool):
            end = end + datetime.timedelta(minutes=travel_mins)
    return {
        'key': f"{d_id}:{chain[0][1]}",
        'driver_id': d_id,
        'event_ids': [eid for _s, eid, _e in chain],
        'start': chain[0][0].isoformat(),
        'end': end.isoformat(),
    }


def packing_for(outing: dict, sched: dict = None, kits: list = None,
                passengers: list = None) -> List[dict]:
    """What one outing needs packed, grouped by kit, with a NEEDED count.

    The count is the point. Prep items are deduped case-insensitively today,
    so two children at one practice see one water bottle — which is a silent
    way to leave one child's bottle at home. Needed is the number of DISTINCT
    PEOPLE the kit covers across the whole outing: the child who needs a
    bottle at soccer and again at band is carrying it between the two and
    needs one, not two.
    """
    from services import prep_kits as _prep
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    if kits is None:
        kits = storage.get_prep_kits()
    if passengers is None:
        passengers = _prep.passenger_objs()

    groups = {}                      # kit_id -> {'kit', 'people': set, 'items': [...]}
    for ev_id in outing.get('event_ids') or []:
        ev = events.get(ev_id)
        if not ev or ev.get('event_type') in ('errand', 'background_trip'):
            continue
        cal_ids = {str(c) for c in (ev.get('calendar_ids') or [])}
        for kit in _prep.match_kits_for_event(ev, kits, passengers):
            kid = str(kit.get('id') or kit.get('name') or '')
            g = groups.setdefault(kid, {
                'kit_id': kid, 'kit': kit.get('name') or 'Bring',
                'per_person': kit.get('per_person') is not False,
                'people': set(),
                'items': [i.strip() for i in (kit.get('items') or []) if i.strip()],
            })
            g['people'].update(_people_on(kit, cal_ids, passengers))

    out = []
    for g in groups.values():
        n = max(1, len(g['people'])) if g['per_person'] else 1
        out.append({
            'kit_id': g['kit_id'], 'kit': g['kit'],
            'people': sorted(g['people']),
            'items': [{'key': f"{g['kit_id']}:{i.lower()}", 'label': i, 'needed': n}
                      for i in g['items']],
        })
    out.sort(key=lambda g: g['kit'].lower())
    return out


def day_in_focus(now: datetime.datetime = None, sched: dict = None) -> datetime.date:
    """The day the household is actually thinking about.

    Today while any outing is still ahead; tomorrow once the last one is home.
    A clock was the first design and it is wrong in both directions — 19:00 is
    too early on a day with a 20:30 pickup, and hours late on a day that ended
    at three. Following the day also makes two rules free: a trip in progress
    can never be hidden, and a day with no outings at all needs no special case.
    """
    now = now or datetime.datetime.now()
    today = now.date()
    for o in outings_for(today, sched, now):
        end = _parse(o.get('end'))
        if end and end > now:
            return today
    return today + datetime.timedelta(days=1)


def _people_on(kit: dict, cal_ids: set, passengers: list) -> set:
    """The members this kit covers who are actually on this event.

    Resolution mirrors the solver's own rule (`does_event_match_rule`): a
    passenger is named by id, by any of their calendar ids, or by name.
    """
    named = [str(p) for p in (kit.get('passenger_ids') or [])]
    if not named:
        return set()
    found = set()
    for p in passengers or []:
        pid, pname = str(getattr(p, 'id', '')), str(getattr(p, 'name', '') or '')
        p_cals = {str(c) for c in (getattr(p, 'calendar_ids', None) or [])}
        if not any(n == pid or n in p_cals or n.lower() == pname.lower() for n in named):
            continue
        if pid in cal_ids or (p_cals & cal_ids):
            found.add(pid)
    return found
