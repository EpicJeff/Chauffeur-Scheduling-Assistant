"""ICS feed subscriptions (intake arc, phase 1 — docs/roadmap.md).

A feed is a subscribable ICS URL (team schedule, school calendar) bound to ONE
target Google calendar at subscription time — routing is a subscription-level
fact, so no per-event intelligence is needed. Each sync fetches the feed,
expands recurrences inside the sync window, and diffs against the feed's
stored event_map (ICS key -> created GCal event) to create/patch/delete only
events this feed owns. Google Calendar remains the single source of truth the
rest of the pipeline reads; the solver/notification stack needs no changes.

Sync rules:
- Past events are history: never deleted when they drop out of the feed, and
  their map entries are pruned once they age out.
- A future event missing from the feed snapshot is a cancellation -> deleted.
- Fingerprint changes (title/time/location/description) -> patch in place.
- Recurring occurrences are keyed uid::start so one rescheduled/cancelled
  occurrence never disturbs its siblings; single events are keyed by uid so a
  time change is a patch, not a delete+create.
"""
import datetime
import hashlib
import json

import requests

from services import calendar as gcal
from services import storage

# How far ahead we materialize feed events (covers a full school year posted
# in August) and how long a vanished *future* event is still ours to delete.
WINDOW_DAYS_AHEAD = 400
# Events that started more than this long ago are frozen history.
PAST_GRACE = datetime.timedelta(days=2)

FETCH_TIMEOUT = 30
MAX_FEED_BYTES = 10 * 1024 * 1024


def _local_tz():
    return datetime.datetime.now().astimezone().tzinfo


def _fingerprint(item: dict) -> str:
    basis = [item['title'], item['start'], item['end'], item['all_day'],
             item.get('location') or '', item.get('description') or '']
    return hashlib.sha1(json.dumps(basis).encode('utf-8')).hexdigest()


def fetch_ics(url: str) -> bytes:
    """Fetch raw ICS bytes. webcal:// is the https ICS convention."""
    if url.lower().startswith('webcal://'):
        url = 'https://' + url[len('webcal://'):]
    resp = requests.get(url, timeout=FETCH_TIMEOUT, stream=True,
                        headers={'User-Agent': 'Chauffeur-ICS-Sync'})
    resp.raise_for_status()
    content = resp.raw.read(MAX_FEED_BYTES + 1, decode_content=True)
    if len(content) > MAX_FEED_BYTES:
        raise ValueError('ICS feed exceeds size limit')
    return content


def parse_ics(content: bytes, window_start=None, window_end=None) -> dict:
    """Parse ICS bytes into {'name': str|None, 'items': {key: item}}.

    Each item: {key, uid, title, start, end, all_day, location, description,
    fingerprint} with start/end as ISO strings (tz-aware for timed events,
    bare dates for all-day; end date exclusive, matching both specs).
    """
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(content)
    feed_name = cal.get('X-WR-CALNAME')
    feed_name = str(feed_name) if feed_name else None

    tz = _local_tz()
    now = datetime.datetime.now(tz)
    if window_start is None:
        window_start = (now - PAST_GRACE).date()
    if window_end is None:
        window_end = (now + datetime.timedelta(days=WINDOW_DAYS_AHEAD)).date()

    occurrences = recurring_ical_events.of(cal).between(window_start, window_end)

    # uid -> occurrence count decides the key scheme (see module docstring)
    uid_counts = {}
    raw = []
    for ev in occurrences:
        uid = str(ev.get('UID') or '')
        dtstart = ev.decoded('DTSTART')
        if 'DTEND' in ev:
            dtend = ev.decoded('DTEND')
        elif 'DURATION' in ev:
            dtend = dtstart + ev.decoded('DURATION')
        else:
            dtend = dtstart + (datetime.timedelta(days=1)
                               if not isinstance(dtstart, datetime.datetime)
                               else datetime.timedelta(hours=1))

        all_day = not isinstance(dtstart, datetime.datetime)
        if all_day:
            start_iso = dtstart.isoformat()
            end_iso = dtend.isoformat()
            if end_iso <= start_iso:  # zero-length all-day guard
                end_iso = (dtstart + datetime.timedelta(days=1)).isoformat()
        else:
            if dtstart.tzinfo is None:  # floating time -> local
                dtstart = dtstart.replace(tzinfo=tz)
            if isinstance(dtend, datetime.datetime) and dtend.tzinfo is None:
                dtend = dtend.replace(tzinfo=tz)
            start_iso = dtstart.isoformat()
            end_iso = dtend.isoformat()

        title = str(ev.get('SUMMARY') or '(No Title)').strip() or '(No Title)'
        location = str(ev.get('LOCATION') or '').strip() or None
        description = str(ev.get('DESCRIPTION') or '').strip() or None

        uid_counts[uid] = uid_counts.get(uid, 0) + 1
        raw.append({'uid': uid, 'title': title, 'start': start_iso,
                    'end': end_iso, 'all_day': all_day,
                    'location': location, 'description': description})

    items = {}
    for it in raw:
        key = it['uid'] if uid_counts.get(it['uid'], 0) == 1 else f"{it['uid']}::{it['start']}"
        it['key'] = key
        it['fingerprint'] = _fingerprint(it)
        items[key] = it
    return {'name': feed_name, 'items': items}


def fetch_and_parse(url: str) -> dict:
    return parse_ics(fetch_ics(url))


def _event_body(feed_id: str, item: dict) -> dict:
    if item['all_day']:
        start = {'date': item['start']}
        end = {'date': item['end']}
    else:
        start = {'dateTime': item['start']}
        end = {'dateTime': item['end']}
    body = {
        'summary': item['title'],
        'start': start,
        'end': end,
        'extendedProperties': {'private': {
            'ics_feed_id': feed_id,
            'ics_key': item['key'],
        }},
    }
    if item.get('location'):
        body['location'] = item['location']
    if item.get('description'):
        body['description'] = item['description']
    return body


def _entry_start_dt(entry: dict):
    """Aware datetime for an event_map entry's stored start (date or datetime)."""
    s = entry.get('start') or ''
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return dt


def sync_feed(feed: dict) -> dict:
    """Sync one feed dict (as stored). Persists the updated feed doc and
    returns {'added','updated','removed','total','error'}."""
    feed_id = feed['id']
    summary = {'added': 0, 'updated': 0, 'removed': 0, 'total': 0, 'error': None}
    now = datetime.datetime.now(_local_tz())

    try:
        parsed = fetch_and_parse(feed['url'])
    except Exception as e:
        summary['error'] = str(e)
        storage.update_ics_feed(feed_id, {
            'last_synced': now.isoformat(),
            'last_status': f'error: {e}',
        })
        return summary

    items = parsed['items']
    summary['total'] = len(items)
    cal_id = feed['calendar_id']
    event_map = dict(feed.get('event_map') or {})
    new_map = {}

    # Prune history: entries whose event started before the grace window stay
    # in Google Calendar forever but stop being tracked (and can't be deleted
    # by the feed dropping past events, which most feeds do).
    cutoff = now - PAST_GRACE
    for key, entry in list(event_map.items()):
        start_dt = _entry_start_dt(entry)
        if start_dt is not None and start_dt < cutoff and key not in items:
            event_map.pop(key)

    for key, item in items.items():
        entry = event_map.pop(key, None)
        if entry is None:
            gid = gcal.insert_event(cal_id, _event_body(feed_id, item))
            if gid:
                summary['added'] += 1
                new_map[key] = {'gid': gid, 'fp': item['fingerprint'], 'start': item['start']}
            # insert failure: not tracked, retried next sync
        elif entry.get('fp') != item['fingerprint']:
            ok = gcal.patch_event(cal_id, entry['gid'], _event_body(feed_id, item))
            if ok:
                summary['updated'] += 1
                new_map[key] = {'gid': entry['gid'], 'fp': item['fingerprint'], 'start': item['start']}
            else:
                new_map[key] = entry  # keep old fp so the patch retries
        else:
            new_map[key] = entry

    # Whatever is left in event_map vanished from the feed: cancel future ones.
    for key, entry in event_map.items():
        start_dt = _entry_start_dt(entry)
        if start_dt is None or start_dt < now:
            new_map[key] = entry  # past or unparseable: keep as history
            continue
        if gcal.remove_event(cal_id, entry['gid']):
            summary['removed'] += 1
        else:
            new_map[key] = entry  # transient failure: retry next sync

    status = f"ok: {summary['total']} events"
    changes = []
    if summary['added']:
        changes.append(f"{summary['added']} added")
    if summary['updated']:
        changes.append(f"{summary['updated']} updated")
    if summary['removed']:
        changes.append(f"{summary['removed']} removed")
    if changes:
        status += ' (' + ', '.join(changes) + ')'

    storage.update_ics_feed(feed_id, {
        'event_map': new_map,
        'event_count': summary['total'],
        'last_synced': now.isoformat(),
        'last_status': status,
    })
    return summary


def sync_all_feeds() -> dict:
    """Sync every enabled feed. Returns {'changed': bool, 'results': {id: summary}}."""
    results = {}
    changed = False
    for feed in storage.get_ics_feeds():
        if not feed.get('enabled', True):
            continue
        res = sync_feed(feed)
        results[feed['id']] = res
        if res['added'] or res['updated'] or res['removed']:
            changed = True
    return {'changed': changed, 'results': results}


def remove_feed_events(feed: dict) -> int:
    """Delete all FUTURE events this feed created (used on feed deletion when
    the user opts to clean up). Past events stay as history."""
    now = datetime.datetime.now(_local_tz())
    removed = 0
    for entry in (feed.get('event_map') or {}).values():
        start_dt = _entry_start_dt(entry)
        if start_dt is not None and start_dt >= now:
            if gcal.remove_event(feed['calendar_id'], entry['gid']):
                removed += 1
    return removed
