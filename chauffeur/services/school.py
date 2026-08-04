"""School-calendar awareness.

`school_in_session(day)` is the single primitive every school-day feature
gates on (bus launch lines, the dismissal/pickup push). Three layers:

1. Weekends are never school days.
2. Optional YEAR BOUNDS — settings `school_year_start`/`school_year_end`
   (YYYY-MM-DD, updated once a year). Outside them school is out: that is
   how summer is known WITHOUT guessing from event titles.
3. An optional DESIGNATED school calendar — settings `school_calendar_id`,
   any Google calendar already in the system (including an ICS-fed district
   calendar): an ALL-DAY event on the day whose title contains a no-school
   keyword (settings `school_closed_keywords`) marks school out. Timed
   events never close a school day.

Nothing configured → plain weekday behavior, exactly as before the feature
existed.

The calendar lookup is cached (6h TTL over a ~10-week window) because the
callers are hot paths (member_day requests, the 30s push scheduler), with a
10-minute retry backoff after a failed fetch. Failures serve the stale
cache when one covers the day, and finally FAIL OPEN (assume in session) —
a broken calendar fetch must never silently kill every school-day feature.
"""
import datetime
import threading
import time

from services import storage

DEFAULT_CLOSED_KEYWORDS = ('no school, holiday, break, closed, '
                           'teacher workday, staff development, conferences')
_CACHE_TTL_S = 6 * 3600
_FAIL_BACKOFF_S = 600
_WINDOW_BEHIND_DAYS = 7
_WINDOW_AHEAD_DAYS = 63

_lock = threading.Lock()
_cache = {'ts': 0.0, 'fail_ts': 0.0, 'cal_id': None,
          'start': None, 'end': None, 'dates': set()}


def _reset_cache():
    """Test hook."""
    with _lock:
        _cache.update({'ts': 0.0, 'fail_ts': 0.0, 'cal_id': None,
                       'start': None, 'end': None, 'dates': set()})


def _keywords(settings):
    raw = settings.get('school_closed_keywords') or DEFAULT_CLOSED_KEYWORDS
    return [k.strip().lower() for k in raw.split(',') if k.strip()]


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _fetch_no_school_dates(cal_id, start, end, keywords):
    """The set of ISO dates covered by an all-day no-school event on the
    designated calendar, or None when the fetch failed."""
    from services import calendar as gcal
    local_tz = datetime.datetime.now().astimezone().tzinfo
    time_min = datetime.datetime.combine(start, datetime.time.min, tzinfo=local_tz).isoformat()
    time_max = datetime.datetime.combine(end, datetime.time.max, tzinfo=local_tz).isoformat()
    _, events = gcal._fetch_single_calendar(cal_id, time_min, time_max)
    if events is None:
        return None
    dates = set()
    for e in events:
        title = (e.get('summary') or '').lower()
        if not any(k in title for k in keywords):
            continue
        s = (e.get('start') or {}).get('date')
        if not s:
            continue  # timed event: doesn't close the school day
        d = _parse_date(s)
        # Google all-day ends are exclusive; single-day events may omit end.
        d_end = _parse_date((e.get('end') or {}).get('date'))
        if d is None:
            continue
        if d_end is None or d_end <= d:
            d_end = d + datetime.timedelta(days=1)
        while d < d_end:
            dates.add(d.isoformat())
            d += datetime.timedelta(days=1)
    return dates


def school_in_session(day) -> bool:
    """True when `day` (date or ISO string) is a school day. Fails open."""
    if isinstance(day, str):
        day = _parse_date(day)
    if day is None:
        return True
    if day.weekday() >= 5:
        return False

    settings = storage.get_settings() or {}
    ys = _parse_date(settings.get('school_year_start'))
    ye = _parse_date(settings.get('school_year_end'))
    if ys and day < ys:
        return False
    if ye and day > ye:
        return False

    cal_id = (settings.get('school_calendar_id') or '').strip()
    if not cal_id:
        return True

    now = time.time()
    with _lock:
        covered = (_cache['cal_id'] == cal_id and _cache['start'] is not None
                   and _cache['start'] <= day <= _cache['end'])
        fresh = covered and (now - _cache['ts'] <= _CACHE_TTL_S)
        if not fresh and (now - _cache['fail_ts'] > _FAIL_BACKOFF_S):
            today = datetime.date.today()
            start = min(today - datetime.timedelta(days=_WINDOW_BEHIND_DAYS), day)
            end = max(today + datetime.timedelta(days=_WINDOW_AHEAD_DAYS), day)
            dates = _fetch_no_school_dates(cal_id, start, end, _keywords(settings))
            if dates is not None:
                _cache.update({'ts': now, 'fail_ts': 0.0, 'cal_id': cal_id,
                               'start': start, 'end': end, 'dates': dates})
                covered = True
            else:
                _cache['fail_ts'] = now
        if not covered:
            return True  # no usable data — fail open, never kill the features
        return day.isoformat() not in _cache['dates']
