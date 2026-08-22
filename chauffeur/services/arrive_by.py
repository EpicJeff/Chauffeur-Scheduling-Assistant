"""Arrive By — what time the family has to be standing there.

A buffer routing rule has always worked and has never been visible: the solver
spaces conflicts by it and the drive plan leaves earlier for it, and no surface
in the app has ever said so out loud. A constraint the family cannot see is one
they cannot trust, check, or correct.

The fix is not "show the buffer". It is to name the thing a buffer is one way
of answering — **what time do we need to be there?** — because a named answer
is something every surface can render, while a buffer is arithmetic every
surface would have to do for itself.

Three times per event, and they are not interchangeable
(docs/arrive_by_design.md):

    leave by / be ready   at home, before the drive     (services/leave_by.py)
    ARRIVE BY / be there  at the destination            (here)
    starts                the whistle blows             (the event itself)

Two rules carry the whole design:

**The earliest arrival wins — max, not precedence.** A household that set a
30-minute rule set it *because* clubs say 15 and they want more; precedence
would silently undo the reason the rule exists. Max never makes anybody later
than a source said. A typed override is the one exception: it replaces
everything, because a person overruling the app must not be argued with.

**The start time is never replaced.** This module returns an arrival ALONGSIDE
the start; every caller renders both, start dominant. If the app says 10:00 and
means warm-up, running late at 10:05 feels like missing a game that has not
started — which is the specific anxiety this feature exists to remove.

Derived, never stored (except the override): a stored copy drifts the moment a
rule changes, and a stale arrival time is a missed warm-up.
"""
import datetime
from typing import Any, List, Optional

from services import storage

DEFAULT_REASON = 'Warm-up'
# A rule asking for half a day is a typo, not a warm-up.
MAX_LEAD_MINS = 240


class _Shim:
    """Just enough event for `does_event_match_rule`.

    The matcher reads `title`, `description`, `calendar_ids`, `location`,
    `start` and `end`. Reusing it — rather than reimplementing the matching —
    is the whole point: the chip must state what the solver ACTUALLY did, and
    a second copy of the matching rules is a second thing to drift.
    """

    __slots__ = ('title', 'description', 'calendar_ids', 'location', 'start', 'end')

    def __init__(self, title, description, calendar_ids, location, start, end):
        self.title = title or ''
        self.description = description or ''
        self.calendar_ids = calendar_ids or []
        self.location = location or ''
        self.start = start
        self.end = end


def _attr(ev, name, default=None):
    if isinstance(ev, dict):
        return ev.get(name, default)
    return getattr(ev, name, default)


def _dt(v):
    if isinstance(v, datetime.datetime):
        return v
    if not v:
        return None
    try:
        return datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _shim(ev):
    start, end = _dt(_attr(ev, 'start')), _dt(_attr(ev, 'end'))
    if not start:
        return None
    cal_ids = _attr(ev, 'calendar_ids') or []
    if isinstance(cal_ids, str):
        cal_ids = [cal_ids]
    return _Shim(_attr(ev, 'title'), _attr(ev, 'description'),
                 [str(c) for c in cal_ids], _attr(ev, 'location'),
                 start, end or start)


def clock(when: datetime.datetime) -> str:
    """The family's own clock format, so a chip never contradicts the row it
    sits on."""
    try:
        if (storage.get_settings() or {}).get('time_format_24h'):
            return when.strftime('%H:%M')
    except Exception:
        pass
    return when.strftime('%I:%M %p').lstrip('0')


def _buffer_rules(event, rules=None, passengers=None) -> List[Any]:
    """Every buffer rule this event matches, by the solver's own matching."""
    from solver.matcher import does_event_match_rule
    shim = _shim(event)
    if shim is None:
        return []
    if rules is None:
        from models.schemas import Rule
        rules = []
        for r in storage.get_all_rules():
            try:
                rules.append(Rule(**r) if isinstance(r, dict) else r)
            except Exception:
                continue
    out = []
    for r in rules:
        if getattr(r, 'constraint_type', '') != 'buffer':
            continue
        if getattr(r, 'is_enabled', True) is False:
            continue
        try:
            if does_event_match_rule(shim, r, passengers):
                out.append(r)
        except Exception:
            # A malformed rule must never cost the family the whole chip —
            # and it must never be silently treated as a match either.
            continue
    return out


def _clamp(mins) -> int:
    try:
        return max(0, min(MAX_LEAD_MINS, int(mins)))
    except (TypeError, ValueError):
        return 0


def from_description(text: str, start: datetime.datetime = None) -> Optional[dict]:
    """V3's hook. Deliberately inert in V1.

    The club's own words are ALREADY in the database — ics_sync copies the ICS
    DESCRIPTION onto the Google event — so this is a parse and not a capture.
    It stays unimplemented until V3 so that the shape of the derivation is
    settled first, and it returns None rather than raising so every caller is
    already written for the day it starts answering.
    """
    return None


def derive(event, rules=None, passengers=None, config=None) -> Optional[dict]:
    """When to be there, or None when the question does not apply.

    None is the right answer more often than not, and it must stay cheap to
    say: an event with no location has no arriving to do, and an all-day event
    has no minute to be early to. Silence beats a guess — a missed arrival
    costs a rule typed once, an invented one costs trust in every chip after.
    """
    start = _dt(_attr(event, 'start'))
    if start is None:
        return None
    if _attr(event, 'all_day'):
        return None
    if not (_attr(event, 'location') or '').strip():
        return None

    if config is None:
        gid = _attr(event, 'id')
        config = (storage.get_event_config(str(gid)) or {}) if gid else {}

    # 1. The typed override REPLACES everything. Somebody looked at this event
    #    and said a time; the app does not get to add to it.
    override = _clamp((config or {}).get('arrive_lead_mins'))
    if override:
        return _out(start, override, 'override',
                    (config or {}).get('arrive_reason') or None)

    # 2. The club's own words (V3).
    best_mins, best_source, best_reason = 0, None, None
    parsed = from_description(_attr(event, 'description'), start)
    if parsed and parsed.get('lead_mins'):
        best_mins = _clamp(parsed['lead_mins'])
        best_source, best_reason = 'description', parsed.get('reason')

    # 3. The family's standing rules. MAX, not precedence: a 30-minute rule
    #    exists because clubs say 15 and this family wants more than that.
    for r in _buffer_rules(event, rules, passengers):
        mins = _clamp(getattr(r, 'buffer_before_mins', 0))
        if mins > best_mins:
            best_mins = mins
            best_source = 'rule'
            best_reason = (getattr(r, 'buffer_reason', None) or '').strip() or None

    if not best_mins:
        return None
    return _out(start, best_mins, best_source, best_reason)


def _out(start: datetime.datetime, mins: int, source: str,
         reason: str = None) -> dict:
    when = start - datetime.timedelta(minutes=mins)
    return {'arrive_at': when.isoformat(), 'arrive_label': clock(when),
            'lead_mins': mins, 'source': source,
            'reason': (reason or DEFAULT_REASON)}


def depart_after(event, rules=None, passengers=None) -> Optional[dict]:
    """The mirror: stay this long after the end.

    Same shape, same silence rules, and deliberately NOT folded into `derive`
    — "be there by" and "you are not leaving yet" are different sentences and
    a surface may well want one without the other.
    """
    end = _dt(_attr(event, 'end'))
    if end is None or _attr(event, 'all_day'):
        return None
    if not (_attr(event, 'location') or '').strip():
        return None
    best, reason = 0, None
    for r in _buffer_rules(event, rules, passengers):
        mins = _clamp(getattr(r, 'buffer_after_mins', 0))
        if mins > best:
            best = mins
            reason = (getattr(r, 'buffer_reason', None) or '').strip() or None
    if not best:
        return None
    when = end + datetime.timedelta(minutes=best)
    return {'depart_at': when.isoformat(), 'depart_label': clock(when),
            'trail_mins': best, 'source': 'rule',
            'reason': (reason or DEFAULT_REASON)}


def annotate(events: List[Any], rules=None, passengers=None) -> List[dict]:
    """Stamp a whole day's events in one pass.

    The rules are loaded ONCE for the batch: this runs inside the solve, which
    already holds them, and a per-event storage read would turn a display
    nicety into a table scan per event.
    """
    if rules is None:
        from models.schemas import Rule
        rules = []
        for r in storage.get_all_rules():
            try:
                rules.append(Rule(**r) if isinstance(r, dict) else r)
            except Exception:
                continue
    out = []
    for ev in events:
        row = dict(ev) if isinstance(ev, dict) else ev
        try:
            arrive = derive(row, rules, passengers)
            trail = depart_after(row, rules, passengers)
        except Exception as e:
            print(f"[arrive_by] skipped {_attr(row, 'id')}: {e}")
            arrive = trail = None
        if isinstance(row, dict):
            if arrive:
                row['arrive_by'] = arrive
            if trail:
                row['depart_after'] = trail
        out.append(row)
    return out
