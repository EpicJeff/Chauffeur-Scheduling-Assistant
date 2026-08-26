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
    initial_edges = sched.get('initial_edges') or {}

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
        d_initial_edges = initial_edges.get(d_id) or {}
        # The drive OUT for this chain: for the day's first outing the solver
        # records it as an initial edge; for every later one it is the
        # `from_home_mins` of the home waypoint that ended the previous
        # outing. An outing is the whole time out of the house, so both ends
        # of every outing count — not just the first one's start and the last
        # one's end.
        out_mins = None
        chain = []
        for i, (start, ev_id, ev) in enumerate(rows):
            chain.append((start, ev_id, ev))
            # Does the driver pass through home before the next one? The
            # solver says so by hanging a home_waypoint on the edge leaving
            # THIS event; an edge with none means they carried straight on.
            last = i == len(rows) - 1
            waypoint = (edges.get(ev_id) or {}).get('home_waypoint') or None
            went_home = bool(waypoint)
            if last or went_home:
                # Only the chain that IS the driver's actual last outing of
                # the day gets the drive home added — a mid-day outing cut at
                # a home_waypoint already ends when the layover starts at
                # home, and the spec does not touch that.
                out.append(_outing(d_id, chain,
                                   d_final_edges if last else None,
                                   d_initial_edges if out_mins is None else None,
                                   out_mins,
                                   _mins(waypoint, 'to_home_mins') if went_home else None))
                # The next outing leaves from home again, and the waypoint the
                # solver hung on this edge says how long that drive takes.
                out_mins = _mins(waypoint, 'from_home_mins') if went_home else None
                if out_mins is None and went_home:
                    out_mins = 0        # it went home; it just costs nothing
                chain = []
    out.sort(key=lambda o: (o['start'], o['key']))
    return out


def _mins(edge: dict, field: str):
    """A travel number off a solver edge, or None when it is absent or junk."""
    v = (edge or {}).get(field)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return None


def _outing(d_id: str, chain: list, final_edges_for_driver: dict = None,
            initial_edges_for_driver: dict = None,
            out_mins=None, home_mins=None) -> dict:
    ends = [_parse(ev.get('end')) or start for start, _eid, ev in chain]
    end = max(ends)
    start = chain[0][0]
    # An outing is the whole time OUT OF THE HOUSE, so it starts when the car
    # leaves rather than when the first event begins. The end already carried
    # the drive home, and a range that included the way back but not the way
    # there was asymmetric in a way nobody could explain.
    # `initial_edges[d_id][first_event_id]` is the solver's own travel for the
    # leg from home; an absent or malformed edge leaves `start` alone. Only the
    # day's FIRST outing gets it — a later one begins wherever the previous one
    # dropped the driver, which is not this leg.
    if initial_edges_for_driver:
        travel_mins = _mins(initial_edges_for_driver.get(chain[0][1]), 'travel_mins')
        if travel_mins is not None:
            start = start - datetime.timedelta(minutes=travel_mins)
    elif out_mins:
        # A later outing leaves from home too — the previous outing's home
        # waypoint carries how long that drive out takes.
        start = start - datetime.timedelta(minutes=out_mins)
    # The turn-over point is the last outing's end — the drive home — rather
    # than the last event's end. `final_edges[d_id][last_event_id]` is the
    # solver's own travel_mins for that leg; an absent or malformed edge
    # leaves `end` exactly what it already was.
    if final_edges_for_driver:
        last_ev_id = chain[-1][1]
        travel_mins = _mins(final_edges_for_driver.get(last_ev_id), 'travel_mins')
        if travel_mins is not None:
            end = end + datetime.timedelta(minutes=travel_mins)
    # A MID-DAY outing ends by going home, and the waypoint that cut it says
    # how long that drive is. Without this an outing that is not the day's
    # last one reported the last event's end as its own — the drive back
    # silently missing from exactly the trips that have one.
    elif home_mins is not None:
        end = end + datetime.timedelta(minutes=home_mins)
    return {
        'key': f"{d_id}:{chain[0][1]}",
        'driver_id': d_id,
        'event_ids': [eid for _s, eid, _e in chain],
        'start': start.isoformat(),
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
                # WHICH events pulled this kit in. The counts stay outing-wide
                # (a child carrying one bottle between two events needs one),
                # but a surface that lists work event by event needs to know
                # whose work it is.
                'event_ids': [],
            })
            if ev_id not in g['event_ids']:
                g['event_ids'].append(ev_id)
            g['people'].update(_people_on(kit, cal_ids, passengers))

    out = []
    for g in groups.values():
        n = max(1, len(g['people'])) if g['per_person'] else 1
        out.append({
            'kit_id': g['kit_id'], 'kit': g['kit'],
            'people': sorted(g['people']),
            'event_ids': list(g['event_ids']),
            'items': [{'key': f"{g['kit_id']}:{i.lower()}", 'label': i, 'needed': n}
                      for i in g['items']],
        })
    out.sort(key=lambda g: g['kit'].lower())
    return out


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
