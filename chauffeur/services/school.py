"""School-calendar awareness.

`school_in_session(day)` is the single primitive every school-day feature
gates on (bus launch lines, the dismissal/pickup push). Layers:

1. Weekends are never school days.
2. YEAR BOUNDS — auto-detected from the designated calendar's own
   "First Day of School" / "Last Day of School" events (family feedback
   2026-08-03: the dates are already on the calendar, don't make a parent
   transcribe them). Consecutive first→last markers pair into school-year
   intervals; a first day with no published last day yet gets an open-ended
   ~11-month interval. Days outside every interval (summer!) are out.
   Settings `school_year_start`/`school_year_end` survive as a MANUAL
   OVERRIDE: setting either one disables auto-detection entirely (the
   parent has taken control) — and they are also the fallback when the
   calendar has no recognizable markers.
3. NO-SCHOOL DAYS — an ALL-DAY event on the designated calendar whose
   title contains a closure keyword (settings `school_closed_keywords`)
   marks the day out. Timed events never close a school day.

Nothing configured → plain weekday behavior, exactly as before the feature
existed.

One calendar fetch covers everything (closures + year markers) over a
±370-day window, cached 6h — callers are hot paths (member_day requests,
the 30s push scheduler) — with a 10-minute retry backoff after a failed
fetch. Failures serve the stale cache when one covers the day, and finally
FAIL OPEN (assume in session): a broken calendar fetch must never silently
kill every school-day feature.
"""
import datetime
import threading
import time

from services import storage

DEFAULT_CLOSED_KEYWORDS = ('no school, holiday, break, closed, '
                           'teacher workday, staff development, conferences')
# Year-bound markers: matched against event titles (all-day OR timed — some
# districts put "First Day of School" on a timed event). Broad on purpose;
# the manual settings are the escape hatch for an unrecognizable calendar.
FIRST_DAY_KEYWORDS = ('first day of school', 'first day for students',
                      'first day of classes', 'first day of class',
                      'school begins', 'school starts', 'classes begin',
                      '1st day of school')
LAST_DAY_KEYWORDS = ('last day of school', 'last day for students',
                     'last day of classes', 'last day of class',
                     'school ends', 'classes end', 'end of school year')
# A first day with no last-day event published yet: assume ~11 months.
OPEN_YEAR_DAYS = 330

_CACHE_TTL_S = 6 * 3600
_FAIL_BACKOFF_S = 600
_WINDOW_DAYS = 370

_lock = threading.Lock()
_cache = {'ts': 0.0, 'fail_ts': 0.0, 'cal_id': None,
          'start': None, 'end': None, 'dates': set(), 'intervals': []}


def _reset_cache():
    """Test hook."""
    with _lock:
        _cache.update({'ts': 0.0, 'fail_ts': 0.0, 'cal_id': None,
                       'start': None, 'end': None, 'dates': set(),
                       'intervals': []})


def _keywords(settings):
    raw = settings.get('school_closed_keywords') or DEFAULT_CLOSED_KEYWORDS
    return [k.strip().lower() for k in raw.split(',') if k.strip()]


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _event_date(e):
    """The (start) date of an event, all-day or timed."""
    start = e.get('start') or {}
    return _parse_date(start.get('date') or start.get('dateTime'))


def _pair_intervals(firsts, lasts):
    """Pair sorted first-day dates with the next last-day date after each
    into (start, end, end_estimated) school-year intervals; unpaired firsts
    get an open-ended interval whose end is a synthetic estimate, never a
    real event. Firsts inside an existing interval are ignored."""
    intervals = []
    for f in sorted(firsts):
        if any(s <= f <= e for s, e, _ in intervals):
            continue
        nxt = next((l for l in sorted(lasts) if l >= f), None)
        intervals.append((f, nxt or f + datetime.timedelta(days=OPEN_YEAR_DAYS),
                          nxt is None))
    return intervals


def _fetch_school_data(cal_id, start, end, keywords):
    """One pass over the designated calendar: (no_school_dates, year
    intervals), or None on fetch failure."""
    from services import calendar as gcal
    local_tz = datetime.datetime.now().astimezone().tzinfo
    time_min = datetime.datetime.combine(start, datetime.time.min, tzinfo=local_tz).isoformat()
    time_max = datetime.datetime.combine(end, datetime.time.max, tzinfo=local_tz).isoformat()
    _, events = gcal._fetch_single_calendar(cal_id, time_min, time_max)
    if events is None:
        return None

    dates = set()
    firsts, lasts = [], []
    for e in events:
        title = (e.get('summary') or '').lower()
        d = _event_date(e)
        if d is None:
            continue
        if any(k in title for k in FIRST_DAY_KEYWORDS):
            firsts.append(d)
        elif any(k in title for k in LAST_DAY_KEYWORDS):
            lasts.append(d)
        if not any(k in title for k in keywords):
            continue
        s = (e.get('start') or {}).get('date')
        if not s:
            continue  # timed event: doesn't close the school day
        # Google all-day ends are exclusive; single-day events may omit end.
        d_end = _parse_date((e.get('end') or {}).get('date'))
        if d_end is None or d_end <= d:
            d_end = d + datetime.timedelta(days=1)
        cur = d
        while cur < d_end:
            dates.add(cur.isoformat())
            cur += datetime.timedelta(days=1)
    return dates, _pair_intervals(firsts, lasts)


def _ensure_cache(cal_id, settings, day):
    """Refresh the cache when stale or not covering `day`. Returns True when
    the cache holds usable data for `day`. Callers hold no lock."""
    now = time.time()
    with _lock:
        covered = (_cache['cal_id'] == cal_id and _cache['start'] is not None
                   and _cache['start'] <= day <= _cache['end'])
        fresh = covered and (now - _cache['ts'] <= _CACHE_TTL_S)
        if not fresh and (now - _cache['fail_ts'] > _FAIL_BACKOFF_S):
            today = datetime.date.today()
            start = min(today - datetime.timedelta(days=_WINDOW_DAYS), day)
            end = max(today + datetime.timedelta(days=_WINDOW_DAYS), day)
            data = _fetch_school_data(cal_id, start, end, _keywords(settings))
            if data is not None:
                dates, intervals = data
                _cache.update({'ts': now, 'fail_ts': 0.0, 'cal_id': cal_id,
                               'start': start, 'end': end, 'dates': dates,
                               'intervals': intervals})
                covered = True
            else:
                _cache['fail_ts'] = now
        return covered


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
    manual_bounds = bool(ys or ye)
    if ys and day < ys:
        return False
    if ye and day > ye:
        return False

    cal_id = (settings.get('school_calendar_id') or '').strip()
    if not cal_id:
        return True
    if not _ensure_cache(cal_id, settings, day):
        return True  # no usable data — fail open, never kill the features

    with _lock:
        # Auto bounds only when the parent hasn't taken manual control.
        if not manual_bounds and _cache['intervals'] \
                and not any(s <= day <= e for s, e, _ in _cache['intervals']):
            return False
        return day.isoformat() not in _cache['dates']


def status():
    """Config-page diagnostics: what the school system currently believes.
    Detected years let a parent SEE that marker detection worked instead of
    discovering a silent miss in August."""
    settings = storage.get_settings() or {}
    cal_id = (settings.get('school_calendar_id') or '').strip()
    today = datetime.date.today()
    out = {
        'today': today.isoformat(),
        'in_session_today': school_in_session(today),
        'calendar_configured': bool(cal_id),
        'manual_start': settings.get('school_year_start') or None,
        'manual_end': settings.get('school_year_end') or None,
        'detected_years': [],
        'no_school_days_cached': 0,
    }
    if cal_id and _ensure_cache(cal_id, settings, today):
        with _lock:
            out['detected_years'] = [[s.isoformat(), e.isoformat(), bool(est)]
                                     for s, e, est in _cache['intervals']]
            out['no_school_days_cached'] = len(_cache['dates'])
    return out
