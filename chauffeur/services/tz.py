"""One answer to "what time zone is this family in".

User report (2026-09-22): events Chauffeur created from email intake showed
up pinned to GMT when opened later in Google Calendar's editor. Two things
were true at once. An event whose start is an offset-only ISO string
("2026-09-23T15:00:00-05:00") is a correct instant, but with no
`timeZone` beside it Google pins the event to a fixed "GMT-05:00"
pseudo-zone in the edit UI. Intake approval and chat already stamped the
calendar's own zone -- but only when the lookup succeeded, and the other
writers (ICS sync, programs, trip stays, POIs) never stamped anything.

So there is now ONE reader of "which zone", and every calendar write goes
through `stamp`. The zone is, in order:

  1. the family's own `timezone` setting (Config -> Family calendars),
     when set and valid;
  2. the calendar's own zone, as Google reports it (`get_calendar_timezone`,
     cached per process) -- the default calendar when no calendar is named;
  3. the box's `TZ` (Home Assistant's supervisor hands every add-on the
     house's zone this way).

Nothing here writes. A blank setting means "follow the calendar", which
is what almost every household wants and what the edit UI shows cleanest
(an event in its calendar's own zone carries no zone label at all).
"""
import datetime
import os
from typing import Optional


def _valid(name: str) -> Optional[str]:
    """`name` when zoneinfo knows it, else None -- a typo in the setting
    must fall through to the calendar, never become a zone Google rejects."""
    name = (name or '').strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
        return name
    except Exception:
        return None


def _setting() -> Optional[str]:
    try:
        from services import storage
        return _valid((storage.get_settings() or {}).get('timezone') or '')
    except Exception:
        return None


def _calendar_zone(calendar_id: Optional[str]) -> Optional[str]:
    try:
        from services import storage
        cid = calendar_id
        if not cid:
            s = storage.get_settings() or {}
            cid = s.get('default_calendar_id') or ((s.get('calendar_ids') or [None])[0])
        if not cid:
            return None
        from services import calendar as gcal
        return _valid(gcal.get_calendar_timezone(cid) or '')
    except Exception:
        return None


def zone_name(calendar_id: Optional[str] = None) -> Optional[str]:
    """The IANA zone name events are written in, or None when nothing on
    this box can say (no setting, no readable calendar, no TZ)."""
    return _setting() or _calendar_zone(calendar_id) or _valid(os.environ.get('TZ') or '')


def localize(dt: datetime.datetime, calendar_id: Optional[str] = None) -> datetime.datetime:
    """A naive clock time ("the email says 3:00 PM") read in the family's
    zone. An aware datetime is returned untouched. With no zone known at
    all, the box's own local zone stands, as it always did."""
    if dt.tzinfo is not None:
        return dt
    name = zone_name(calendar_id)
    if name:
        from zoneinfo import ZoneInfo
        return dt.replace(tzinfo=ZoneInfo(name))
    return dt.astimezone()


def stamp(body: dict, calendar_id: Optional[str] = None) -> dict:
    """Name the zone on a Google event body's start/end. Only `dateTime`
    entries (an all-day `date` has no zone), only where the caller has not
    already named one, and only when a zone is actually known -- an
    offset-only dateTime with no zone is still a correct instant, so the
    field is omitted rather than guessed."""
    if not isinstance(body, dict):
        return body
    entries = [body.get(k) for k in ('start', 'end')]
    wants = [e for e in entries if isinstance(e, dict) and e.get('dateTime') and not e.get('timeZone')]
    if not wants:
        return body
    name = zone_name(calendar_id)
    if name:
        for e in wants:
            e['timeZone'] = name
    return body
