"""Errands with common sense: the kind table, what a steer teaches, how a
learned preference is weighted, scored and said.

Spec: docs/superpowers/specs/2026-10-22-errands-common-sense-design.md.
Everything here is a constant or a pure function except `learn_from_steer`,
which writes through storage.upsert_errand_preference. The solver pass reads
this module; nothing here reads the solver.
"""
import math
import re
import time as _time
import uuid
from datetime import time
from typing import Optional

from models.schemas import ERRAND_KINDS

KIND_KEYWORDS = {
    'groceries': ['grocery', 'groceries', 'market', 'supermarket', 'food', 'costco', "sam's", 'sams club',
                  'kroger', 'aldi', 'publix', 'meijer', 'wegmans', 'trader joe', 'whole foods', 'walmart',
                  'target run', 'h-e-b', 'heb', 'safeway', 'giant', 'harris teeter', 'fresh market'],
    'pharmacy': ['pharmacy', 'prescription', 'rx', 'walgreens', 'cvs', 'rite aid', 'meds'],
    'return': ['return', 'drop off', 'drop-off', 'dropoff', 'mail', 'ship', 'ups', 'fedex', 'post office', 'usps'],
    'pickup': ['pick up', 'pickup', 'pick-up', 'collect', 'fetch'],
    'service': ['haircut', 'barber', 'salon', 'nails', 'oil change', 'car wash', 'tires', 'vet', 'dentist',
                'doctor', 'appointment'],
}
KIND_ORDER = ('groceries', 'pharmacy', 'return', 'pickup', 'service')
HOME_BOUND_KINDS = frozenset({'groceries', 'pharmacy'})

STEER_BANDS = {
    'morning': ('08:00', '12:00'), 'midday': ('11:00', '14:00'),
    'afternoon': ('14:00', '17:00'), 'evening': ('17:00', '20:00'),
}
DEDICATED_START_WEEKDAY = time(9, 0)
DEDICATED_START_WEEKEND = time(10, 0)
DEDICATED_END = time(17, 0)
ESTIMATE_SURCHARGE_MINS = 10

PREF_STEP_MINS = 5
PREF_CAP_MINS = 30
PREF_MAX_WEIGHT = 6
PREF_HALF_LIFE_DAYS = 90
PREF_PRUNE_BELOW = 0.5

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
KIND_LABELS = {'groceries': 'groceries', 'pharmacy': 'pharmacy runs', 'return': 'returns',
               'pickup': 'pickups', 'service': 'appointments', 'other': 'errands', '*': 'errands'}
BAND_PHRASES = {'morning': 'in the morning', 'midday': 'at midday',
                'afternoon': 'in the afternoon', 'evening': 'in the evening'}


# ------------------------------------------------------------------ kinds

def _has_phrase(text: str, phrases) -> bool:
    for p in phrases:
        if re.search(r'(?<![a-z0-9])' + re.escape(p) + r'(?![a-z0-9])', text):
            return True
    return False


def errand_kind(errand: dict, lists: Optional[list] = None) -> str:
    """§1: override, then a bound shopping list, then tags, then the title."""
    k = (errand.get('kind') or '').strip().lower()
    if k in ERRAND_KINDS:
        return k
    if lists is None:
        try:
            from services import storage
            lists = storage.find_shopping_lists_for_errand(errand)
        except Exception:
            lists = []
    if lists:
        return 'groceries'
    tags = ' '.join(str(t) for t in (errand.get('tags') or [])).lower()
    title = (errand.get('title') or '').lower()
    for kind in KIND_ORDER:
        if tags and _has_phrase(tags, KIND_KEYWORDS[kind]):
            return kind
    for kind in KIND_ORDER:
        if title and _has_phrase(title, KIND_KEYWORDS[kind]):
            return kind
    return 'other'


def is_home_bound(errand: dict, kind: Optional[str] = None) -> bool:
    hb = errand.get('home_bound')
    if hb is not None:
        return bool(hb)
    return (kind or errand_kind(errand)) in HOME_BOUND_KINDS


# ------------------------------------------------------------------ bands

def _mins(hhmm: str) -> int:
    h, m = map(int, str(hhmm).split(':')[:2])
    return h * 60 + m


def band_for(start: Optional[str], end: Optional[str]) -> Optional[str]:
    """§4.2: the band equal to the pin, else the first band holding its midpoint."""
    if not start and not end:
        return None
    for name, (b0, b1) in STEER_BANDS.items():
        if start == b0 and end == b1:
            return name
    if start and end:
        mid = (_mins(start) + _mins(end)) // 2
    else:
        mid = _mins(start or end)
    for name, (b0, b1) in STEER_BANDS.items():
        if _mins(b0) <= mid < _mins(b1):
            return name
    return 'morning' if mid < _mins(STEER_BANDS['morning'][0]) else 'evening'


def band_holds(name: str, t: time) -> bool:
    b0, b1 = STEER_BANDS[name]
    m = t.hour * 60 + t.minute
    return _mins(b0) <= m < _mins(b1)


# ------------------------------------------------------------------ weights

def effective_weight(row: dict, now: Optional[float] = None) -> float:
    now = _time.time() if now is None else now
    age_days = max(0.0, (now - float(row.get('last_seen') or now)) / 86400.0)
    return float(row.get('weight') or 0.0) * (0.5 ** (age_days / PREF_HALF_LIFE_DAYS))


def _row_matches(row: dict, driver_id, kind, day_date, start_dt) -> bool:
    if row.get('scope') not in ('*', str(driver_id)):
        return False
    if row.get('kind') not in ('*', kind):
        return False
    dim, val = row.get('dimension'), str(row.get('value'))
    if dim == 'weekday':
        return val == str(day_date.weekday())
    if dim == 'time_band':
        return val in STEER_BANDS and band_holds(val, start_dt.timetz())
    if dim == 'driver':
        return val == str(driver_id)
    return False


def preference_cost(rows, driver_id, kind, day_date, start_dt, now=None):
    """§4.3: Σ ±5×weight over matching rows, clamped to [-30, +30]."""
    total, hit = 0.0, []
    for row in rows or []:
        if not _row_matches(row, driver_id, kind, day_date, start_dt):
            continue
        w = effective_weight(row, now)
        total += (-1 if row.get('polarity') == 'prefer' else 1) * PREF_STEP_MINS * w
        hit.append(row.get('id'))
    total = max(-PREF_CAP_MINS, min(PREF_CAP_MINS, total))
    return int(round(total)), hit


# ------------------------------------------------------------------ teaching

def _iso_weekday(date_str: str) -> Optional[str]:
    try:
        from datetime import date
        return str(date.fromisoformat(str(date_str)).weekday())
    except Exception:
        return None


def learn_from_steer(before: dict, after: dict, placement: Optional[dict] = None, now=None) -> list:
    """§4.2: the rows one steer teaches, written through storage. Returns them."""
    from services import storage
    now = _time.time() if now is None else now
    kind = errand_kind(after)
    scope = ((placement or {}).get('driver') or {}).get('id') or after.get('once_driver_id') or '*'
    scope = str(scope)
    rows = []

    def row(sc, dim, val, pol):
        if val is None:
            return
        rows.append({'scope': sc, 'kind': kind, 'dimension': dim, 'value': str(val),
                     'polarity': pol, 'source': 'steer'})

    gained = [d for d in (after.get('skip_dates') or []) if d not in (before.get('skip_dates') or [])]
    for d in gained:
        row(scope, 'weekday', _iso_weekday(d), 'avoid')
    if after.get('pinned_date') and after.get('pinned_date') != before.get('pinned_date'):
        row(scope, 'weekday', _iso_weekday(after['pinned_date']), 'prefer')
    if (after.get('pinned_start') or after.get('pinned_end')) and (
            after.get('pinned_start') != before.get('pinned_start')
            or after.get('pinned_end') != before.get('pinned_end')):
        row(scope, 'time_band', band_for(after.get('pinned_start'), after.get('pinned_end')), 'prefer')
    if after.get('once_driver_id') and after.get('once_driver_id') != before.get('once_driver_id'):
        row('*', 'driver', after['once_driver_id'], 'prefer')
    return [storage.upsert_errand_preference(r, now=now) for r in rows]


# ------------------------------------------------------------------ words

def describe(row: dict, people: dict) -> str:
    scope = row.get('scope')
    who = 'Anyone' if scope == '*' else (people.get(scope) or 'Someone')
    label = KIND_LABELS.get(row.get('kind') or '*', 'errands')
    n = max(1, int(round(float(row.get('weight') or 1))))
    tail = f" (learned from {n} steer{'s' if n != 1 else ''})"
    dim, val, avoid = row.get('dimension'), str(row.get('value')), row.get('polarity') == 'avoid'
    if dim == 'weekday':
        day = DAY_NAMES[int(val)] if val.isdigit() and int(val) < 7 else val
        return f"{who}: {label} {'not ' if avoid else ''}on {day}s{tail}"
    if dim == 'time_band':
        return f"{who}: {label} {'not ' if avoid else ''}{BAND_PHRASES.get(val, val)}{tail}"
    if dim == 'driver':
        name = people.get(val) or 'Someone'
        return f"{name} {'does not run' if avoid else 'runs'} {label}{tail}"
    return f"{who}: {label}{tail}"
