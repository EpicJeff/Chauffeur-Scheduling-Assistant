"""Event cancellations — "practice is off" as a first-class fact.

Deleting the event in Google Calendar was the old workflow, and it failed
three ways at once: no record survives (nothing to reschedule from), an
ICS-fed event quietly resurrects on the next sync, and nobody who was
counting on the event hears anything. A cancellation here is the opposite of
all three:

  * a RECORD — occurrence-keyed row with a reason, kept forever (restoring
    marks it restored, never deletes it);
  * a TOMBSTONE — the stamp runs every refresh, so however many times the
    feed re-adds the occurrence it comes back canceled;
  * an ANNOUNCEMENT — the assigned driver and the kids on the event are told
    once, with the reason, at cancel time (and told again if it comes back).

The Google side is mirrored, not abandoned: for events we can write, the
title gains a "CANCELED " prefix and availability goes Free — the same
convention several league/team systems already use — so every screen that
shows Google directly agrees with the app. That same convention read the
OTHER way is the detector: a feed occurrence arriving with a canceled-style
title becomes a Chauffeur cancellation automatically, pushes included, for
cancellations nobody typed into this app.

Keying mirrors optional_events: instance google id first, series id as
fallback, plus the occurrence date — cancel THIS Tuesday, never next
Tuesday's sibling. Solver-side, a canceled event leaves the optimisation
exactly the way a skipped optional does: not assignable, not unassigned,
nothing chased. Still drawn, struck through, wearing its reason.
"""
import datetime
import re

from services import storage
from services.optional_events import candidate_google_ids, _event_date

# Title-start only, both spellings, optional brackets/colon — "CANCELED
# Practice", "Cancelled: Swim", "[CANCELED] Game". A mid-title mention
# ("discuss canceled game") must never trip it.
_PREFIX_RE = re.compile(r'^\s*\[?\s*cancell?ed\s*\]?\s*[:\-–]*\s+', re.IGNORECASE)

FEED_REASON = "Canceled by the organizer"


def is_canceled_title(title) -> bool:
    return bool(_PREFIX_RE.match(title or ''))


def strip_cancel_prefix(title) -> str:
    return _PREFIX_RE.sub('', title or '').strip()


def cancellation_for(ev):
    """The active cancellation record for this occurrence, or None."""
    date = _event_date(ev)
    if not date:
        return None
    return storage.get_event_cancellation(candidate_google_ids(ev), date)


def stamp_cancellations(events) -> None:
    """Refresh-pipeline pass (mirrors optional_events.stamp_decisions): flag
    every canceled occurrence before unrolling, so every copy carries it.
    This stamp IS the resurrection defence — the feed may re-add the
    occurrence forever; it re-arrives canceled every time."""
    for e in events:
        rec = cancellation_for(e)
        if rec:
            e.canceled = True
            e.cancel_reason = rec.get('reason') or None


def _sources(ev) -> list:
    """(calendar_id, google_event_id) pairs this event is written as."""
    get = ev.get if isinstance(ev, dict) else lambda k, d=None: getattr(ev, k, d)
    out = []
    for src in (get('source_event_ids') or []):
        parts = str(src).split('::')
        if len(parts) == 2 and parts[0] and parts[1]:
            out.append((parts[0], parts[1]))
    return out


def _title_of(ev) -> str:
    get = ev.get if isinstance(ev, dict) else lambda k, d=None: getattr(ev, k, d)
    return get('title') or 'Event'


def _mirror_to_google(ev, cancel: bool, original_title: str) -> None:
    """Write the convention back to every writable source event: prefix +
    availability Free on cancel, both restored on un-cancel. Source ids are
    instance-level for recurring instances, so a single occurrence patch
    never renames its siblings. A read-only calendar (ICS subscription)
    simply fails the patch and the tombstone carries the whole load."""
    from services import calendar as _cal
    clean = strip_cancel_prefix(original_title)
    body = ({'summary': f'CANCELED {clean}', 'transparency': 'transparent'}
            if cancel else
            {'summary': clean, 'transparency': 'opaque'})
    for cal_id, gid in _sources(ev):
        try:
            _cal.patch_event(cal_id, gid, body)
        except Exception as ex:
            print(f"Cancel mirror to {cal_id} failed (tombstone still holds): {ex}")


def _notify(ev, reason: str, restored: bool) -> None:
    """Tell the people the event was FOR, once, at the moment it changes:
    the assigned driver (or whoever the solve had), and the kids on the
    event in their own words. Quiet hours and scope ride the existing lanes.
    Never raises — a push failure must not fail the cancel."""
    try:
        import main as _m
        get = ev.get if isinstance(ev, dict) else lambda k, d=None: getattr(ev, k, d)
        ev_id = str(get('id') or '')
        title = strip_cancel_prefix(_title_of(ev))
        when = ''
        try:
            start = datetime.datetime.fromisoformat(str(get('start')))
            when = ' (' + start.strftime('%I:%M %p').lstrip('0') + ')'
        except Exception:
            pass
        tail = f" — {reason}" if reason else ""
        # A same-day cancel outranks quiet hours — the driver may already be
        # reaching for keys. Tomorrow-or-later waits for the waking day.
        urgent = _event_date(ev) == datetime.date.today().isoformat()
        sched = storage.get_cached_schedule() or {}
        assignments = dict(sched.get('assignments') or {})
        assignments.update(sched.get('ghost_assignments') or {})
        d_id = assignments.get(ev_id)
        told = set()
        if d_id:
            drv_member = storage.get_member_by_driver_id(d_id)
            if drv_member:
                told.add(drv_member['id'])
                _m._notify_member_lanes(
                    drv_member,
                    ("🔁 Back on" if restored else "❌ Canceled") + f": {title}{when}",
                    (f"{title} is back on the schedule." if restored
                     else f"No need to drive — {title} was canceled{tail}."),
                    urgent=urgent, facet='schedule.assignment')
        for kid in _m._kid_members_for_event(ev if isinstance(ev, dict)
                                             else ev.model_dump(mode='json'),
                                             ev_id, sched):
            if kid['id'] in told:
                continue
            told.add(kid['id'])
            _m._notify_member_lanes(
                kid,
                (f"🔁 {title} is back on!" if restored
                 else f"❌ No {title} today"),
                (f"{title}{when} is happening after all."
                 if restored else f"{title} was canceled{tail}."),
                urgent=urgent, facet='calendar.events')
    except Exception as ex:
        print(f"Cancellation notify failed: {ex}")


def cancel_occurrence(ev, reason: str = '', canceled_by: str = None,
                      source: str = 'manual') -> dict:
    """Cancel one occurrence: record, Google mirror, announcements."""
    date = _event_date(ev)
    ids = candidate_google_ids(ev)
    if not date or not ids:
        return {'status': 'error', 'message': 'Event has no usable id or date.'}
    if storage.get_event_cancellation(ids, date):
        return {'status': 'success',
                'message': f"{strip_cancel_prefix(_title_of(ev))} on {date} "
                           f"is already canceled."}
    title = _title_of(ev)
    storage.add_event_cancellation({
        'google_id': ids[0], 'date': date,
        'reason': (reason or '').strip() or None,
        'canceled_by': canceled_by, 'source': source,
        'original_title': strip_cancel_prefix(title),
    })
    # The feed already wears the convention when the detector brought us
    # here — only a Chauffeur-initiated cancel needs to write it out.
    if source == 'manual':
        _mirror_to_google(ev, cancel=True, original_title=title)
    _notify(ev, (reason or '').strip(), restored=False)
    clean = strip_cancel_prefix(title)
    return {'status': 'success', 'date': date, 'google_id': ids[0],
            'message': f"{clean} on {date} is canceled"
                       + (f" — {reason.strip()}" if (reason or '').strip() else "")
                       + ". The driver and the kids are being told."}


def restore_occurrence(ev, restored_by: str = None, source: str = 'manual') -> dict:
    """Un-cancel: the row stays as history, marked restored."""
    date = _event_date(ev)
    ids = candidate_google_ids(ev)
    rec = storage.restore_event_cancellation(ids, date)
    if not rec:
        return {'status': 'error',
                'message': f"{_title_of(ev)} on {date} isn't canceled."}
    if source == 'manual':
        _mirror_to_google(ev, cancel=False,
                          original_title=rec.get('original_title') or _title_of(ev))
    _notify(ev, '', restored=True)
    return {'status': 'success', 'date': date,
            'message': f"{rec.get('original_title') or _title_of(ev)} on {date} "
                       f"is back on. Everyone's being told."}


def detect_feed_cancellations(events) -> None:
    """The convention read inbound, both directions. Runs every refresh,
    BEFORE the stamp; idempotent by record existence.

    Forward: an occurrence arriving with a canceled-style title and no
    record AT ALL gains a feed-sourced cancellation, pushes included —
    league-system cancellations nobody typed here. A restored row blocks
    re-cancelling: a person's deliberate un-cancel outranks a stale title.

    Reverse: an active FEED-sourced record whose occurrence now arrives
    clean-titled restores itself ("back on"). Manual records never
    auto-restore — only the person un-cancels those. Loop-safe against our
    own mirror: the manual record exists before the prefixed title ever
    comes back around, so the detector skips it."""
    by_key = {}
    for e in events:
        date = _event_date(e)
        for gid in candidate_google_ids(e):
            by_key.setdefault((gid, date), e)
        if is_canceled_title(_title_of(e)) \
                and not storage.any_event_cancellation(candidate_google_ids(e), date):
            cancel_occurrence(e, reason=FEED_REASON, source='feed')
    for rec in storage.get_event_cancellations(active_only=True):
        if rec.get('source') != 'feed':
            continue
        ev = by_key.get((rec.get('google_id'), rec.get('date')))
        if ev is not None and not is_canceled_title(_title_of(ev)):
            restore_occurrence(ev, source='feed')


def cancel_by_title(event_name: str, target_date: str, reason: str = '',
                    acting_member: dict = None, restore: bool = False) -> dict:
    """Agent path (both stacks): resolve by fuzzy title + date, then act.
    Calling an event off is a parent/adult act — a kid asking Argyle to
    cancel practice is refused out loud."""
    role = (acting_member or {}).get('role')
    if role in ('child', 'helper', 'guest'):
        return {'status': 'error',
                'message': "Only a parent or adult can cancel or restore an "
                           "event — ask one of them."}
    from services.agent_tools_v2 import _find_event_fuzzy
    ev, err = _find_event_fuzzy(event_name, target_date or 'today')
    if err:
        return {'status': 'error', 'message': err}
    if restore:
        res = restore_occurrence(ev, restored_by=(acting_member or {}).get('id'))
    else:
        res = cancel_occurrence(ev, reason=reason,
                                canceled_by=(acting_member or {}).get('id'))
    if res.get('status') == 'success':
        try:
            import main as _m
            _m.trigger_background_refresh()
        except Exception:
            pass
    return res
