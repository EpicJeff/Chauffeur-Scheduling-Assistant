"""When you actually have to leave.

The one number a family standing in the kitchen wants, and the app has always
had it — the solver computes the travel into every drive it assigns, and the
kid digest has printed "🚀 Leave by 8:47 AM with Vovo" since arc K5. It lived
inside `main.member_day`, so the wall panel's hero could not reach it and was
left saying "in 2 hr 26 min" about a start time nobody sets an alarm for.

The rule, unchanged from K5: **start − travel − the driver's buffer**, and
**no travel time means no leave time**. A guessed departure is worse than none:
it is the kind of number a household plans around once, gets burned by, and
then stops trusting the whole board over.

Two edges can carry that travel, and which of them applies is the difference
between two honest sentences:

- an **initial** edge is the driver setting out FROM HOME for this drive, which
  is what "leave by" means to somebody standing in their kitchen;
- a **route** edge is the driver arriving from wherever they already are, so
  the departure is real but it is not this household's front door.

`from_home_only=True` keeps the second out — the kid digest wants the first
sense and only the first, because a child reading "leave by 4:20" is being told
when to put their shoes on.
"""

import datetime
from typing import Optional


def travel_into(sched: dict, driver_id: str, event_id: str,
                from_home_only: bool = False) -> Optional[dict]:
    """`{'travel_mins', 'buffer_mins', 'from_home'}` for the drive INTO
    `event_id`, or None when the schedule does not know.

    Initial edges are keyed by the event being driven to; route edges are keyed
    by the event being driven FROM, so the one that matters here is found by
    its `to_event`. Both shapes are the solver's, and both are read this way by
    the Drives timeline.
    """
    if not driver_id or not event_id or str(driver_id).startswith('ghost_'):
        return None

    def as_lead(edge, from_home):
        try:
            mins = int(edge.get('travel_mins') or 0)
        except (TypeError, ValueError):
            return None
        if mins <= 0:
            return None
        try:
            buffer_mins = int(edge.get('buffer_before_mins') or 0)
        except (TypeError, ValueError):
            buffer_mins = 0
        return {'travel_mins': mins, 'buffer_mins': buffer_mins,
                'from_home': from_home}

    initial = ((sched.get('initial_edges') or {}).get(driver_id) or {})
    # `{id}_dropoff` is the split-leg key the ride cards use; member_day has
    # always looked under both.
    for key in (event_id, f"{event_id}_dropoff"):
        edge = initial.get(key)
        if edge:
            lead = as_lead(edge, True)
            if lead:
                return lead
    if from_home_only:
        return None

    for edge in ((sched.get('route_edges') or {}).get(driver_id) or {}).values():
        if not edge or edge.get('to_event') not in (event_id, f"{event_id}_dropoff"):
            continue
        lead = as_lead(edge, False)
        if lead:
            return lead
    return None


def leave_at(start: datetime.datetime, lead: dict) -> Optional[datetime.datetime]:
    """The departure itself. `lead` is what `travel_into` returned."""
    if not start or not lead:
        return None
    return start - datetime.timedelta(
        minutes=lead['travel_mins'] + lead.get('buffer_mins', 0))


def clock(dt: datetime.datetime) -> str:
    """4:20 PM. Built with %I and stripped rather than %-I, which is glibc-only
    and raises on Windows, where this is developed."""
    return dt.strftime('%I:%M %p').lstrip('0')


def for_run(sched: dict, driver_id: str, event_id: str,
            start: datetime.datetime, from_home_only: bool = False) -> Optional[dict]:
    """Everything a surface needs to say it: `leave_at`, `leave_label`,
    `travel_mins`, `from_home`. None when the schedule cannot support the
    claim."""
    lead = travel_into(sched, driver_id, event_id, from_home_only)
    when = leave_at(start, lead) if lead else None
    if not when:
        return None
    return {'leave_at': when.isoformat(), 'leave_label': clock(when),
            'travel_mins': lead['travel_mins'], 'from_home': lead['from_home']}
