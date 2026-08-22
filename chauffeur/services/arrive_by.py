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
import re
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


# --- V3: the club's own words -----------------------------------------------
#
# The text is ALREADY in the database. `ics_sync` copies the ICS DESCRIPTION
# onto the Google event, so "arrive by 10:00" from Playmetrics or TeamSnap has
# been sitting in the event body all along, unread. This is a parse, not a
# capture.
#
# Deliberately regex and not an LLM, for three reasons: ics_sync is
# zero-LLM by design, this runs on every event on every sync, and a model that
# reads "arrive 15 minutes before" correctly 95% of the time produces a
# SILENTLY WRONG arrival the other 5% — which is worse than not reading it at
# all, because a wrong arrival time is indistinguishable from a right one
# until the family is standing in an empty car park.
#
# Every pattern here fails CLOSED. The cost of missing one is a rule typed
# once; the cost of inventing one is trust in every chip after it.

_CLOCK = r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?'
_RELATIVE = re.compile(
    r'\b(?:please\s+)?(?:arrive|be\s+(?:there|at\s+the\s+\w+)|report|check\s*[- ]?in|'
    r'players?\s+arrive)\b[^.\n]{0,30}?\b(\d{1,3})\s*(?:min(?:ute)?s?|mins)\b'
    r'[^.\n]{0,20}?\b(?:before|prior|early|ahead)\b', re.I)
_ABSOLUTE = re.compile(
    r'\b(?:please\s+)?(?:arrive|arrival|be\s+there|report|check\s*[- ]?in|'
    r'players?\s+arrive)\b[^.\n]{0,20}?\b(?:by|at|no\s+later\s+than)\s+' + _CLOCK,
    re.I)
# The forms that say a time with no "by"/"at" between: "Arrival 9:45am".
_ABSOLUTE_BARE = re.compile(
    r'\b(?:arrival|arrive|report|check\s*[- ]?in)\s*[:\-]?\s*' + _CLOCK, re.I)

# Phrases that LOOK like an arrival and are not. Checked first, and each one
# is here because it would otherwise produce a confident wrong answer.
_NOT_ARRIVAL = re.compile(
    r'\b(?:gates?|doors?|field|park(?:ing)?|concessions?|store|office)\s+'
    r'(?:open|opens)\b|\bdeparts?\b|\bbus\s+leaves\b|\bpick\s*-?\s*up\b', re.I)


def _minutes_before(start, hour, minute, meridiem) -> Optional[int]:
    """A clock time turned into a lead, against THIS event's start."""
    if start is None:
        return None
    h = int(hour) % 12
    if (meridiem or '').lower().startswith('p'):
        h += 12
    when = start.replace(hour=h, minute=int(minute or 0), second=0, microsecond=0)
    lead = int((start - when).total_seconds() // 60)
    # An "arrival" at or after kick-off is not an arrival instruction, and one
    # four hours earlier is a different day's sentence caught by accident.
    if lead <= 0 or lead > MAX_LEAD_MINS:
        return None
    return lead


def from_description(text: str, start: datetime.datetime = None) -> Optional[dict]:
    """An arrival instruction the source stated, or None.

    Reads only the FIRST few lines: club descriptions trail off into league
    rules, refund policies and directions, and a "30 minutes before" buried in
    a cancellation policy is not this game's arrival time.
    """
    raw = (text or '').strip()
    if not raw:
        return None
    head = '\n'.join(raw.splitlines()[:6])[:600]

    for pat in (_RELATIVE, _ABSOLUTE, _ABSOLUTE_BARE):
        for m in pat.finditer(head):
            # The disqualifiers are checked against the SENTENCE the match sits
            # in, not the whole text: "gates open at 9:30, players arrive 9:45"
            # is a real arrival instruction sharing a line with a red herring.
            lo = head.rfind('.', 0, m.start()) + 1
            hi = head.find('.', m.end())
            sentence = head[lo:hi if hi != -1 else len(head)]
            if _NOT_ARRIVAL.search(sentence):
                continue
            if pat is _RELATIVE:
                lead = _clamp(m.group(1))
                if not lead:
                    continue
            else:
                lead = _minutes_before(start, m.group(1), m.group(2), m.group(3))
                if not lead:
                    continue
            return {'lead_mins': lead,
                    # The club's own phrasing, trimmed — it is more useful
                    # than any word this app would choose, and it is what
                    # makes the chip verifiable against the email.
                    'reason': ' '.join(sentence.split())[:60] or None}
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
    reason = (reason or DEFAULT_REASON)
    # ONE canonical string, built here, rendered verbatim by every surface.
    # The alternative — each page concatenating a time and a reason its own
    # way — is how the wall and the phone end up describing the same game
    # differently, and a family that catches the app contradicting itself
    # about kick-off does not go back to trusting it.
    # A parsed reason is the club's WHOLE SENTENCE, because that is what makes
    # the chip checkable against the email it came from — and a whole sentence
    # does not fit in a chip. So the label carries the reason only when it is
    # short enough to be a label; the sentence still travels, and the event
    # detail is where there is room to print it.
    short = reason if len(reason) <= 24 else None
    return {'arrive_at': when.isoformat(), 'arrive_label': clock(when),
            'lead_mins': mins, 'source': source, 'reason': reason,
            'label': f"Arrive {clock(when)} · {short}" if short
                     else f"Arrive {clock(when)}",
            'short_label': f"Arrive {clock(when)}"}


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
    reason = (reason or DEFAULT_REASON)
    return {'depart_at': when.isoformat(), 'depart_label': clock(when),
            'trail_mins': best, 'source': 'rule', 'reason': reason,
            'label': f"Leave {clock(when)} · {reason}",
            'short_label': f"Leave {clock(when)}"}


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
