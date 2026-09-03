"""The Study's one read. Eleven furniture signals, every section built in
its own try/except (a provider that raises contributes its calm form and
never sinks the room), all sources read-only. See
docs/superpowers/specs/2026-09-03-argyle-study-design.md."""
import datetime
import logging
import time
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

# The calm form of every section — what an empty, healthy household shows,
# and what a broken provider degrades to. Law 2: quiet is success.
_CALM = {
    'board': {'pins': [], 'strings': []},
    'desk': [],
    'tray': {'count': 0},
    'stickies': {'count': 0, 'worst': None},
    'calendar': {'days': []},
    'window': {'ready': False, 'worse': [], 'label': ''},
    'keys': [],
    'contracts': {'count': 0},
    'binders': [],
    'gauges': {'think': None, 'think_cap': None, 'research': None,
               'research_cap': None, 'ingest_errors': 0},
}


def _board(now, viewer):
    from services import mind, threads as _th
    pins, strings = [], []
    insights = mind.visible_insights(viewer, now=now)
    for r in insights:
        pins.append({'id': r['id'], 'kind': 'insight', 'label': r.get('line') or '',
                     'warn': False, 'bad': False, 'changed_ts': r.get('created_ts')})
    stalled = {t['id']: t.get('stall_reason') for t in (_th.stalled(today=now.date()) or [])}
    for t in storage.get_threads(include_closed=False):
        reason = stalled.get(t['id'])
        pins.append({'id': t['id'], 'kind': 'thread', 'label': t.get('title') or '',
                     'warn': bool(reason), 'bad': reason == 'overdue',
                     'changed_ts': t.get('created_at')})
    # Strings: insight pins connect to thread pins round-robin so the board
    # reads as one investigation. Real relations are a later slice; drawing
    # invented specifics would violate honesty, so strings only join pins
    # that EXIST, by index, and carry no claim beyond "same household".
    ins_ids = [p['id'] for p in pins if p['kind'] == 'insight']
    th_ids = [p['id'] for p in pins if p['kind'] == 'thread']
    for i, tid in enumerate(th_ids):
        if ins_ids:
            strings.append([ins_ids[i % len(ins_ids)], tid])
    return {'pins': pins[:14], 'strings': strings[:10]}


def _desk(now, viewer):
    from services import mind
    out = []
    for r in storage.get_mind_insights(state='in_hand'):
        steps = (r.get('plan_json') or {}).get('steps') or []
        open_steps = [s for s in steps if s.get('status') == 'open']
        if viewer is None or viewer.get('role') != 'parent':
            if r.get('sensitivity') == 'sensitive':
                continue
        out.append({'id': r['id'], 'open_steps': len(open_steps),
                    'due': bool(mind.steps_due(r, now.date())),
                    'changed_ts': r.get('created_ts')})
    return out[:6]


def _tray(now, viewer):
    return {'count': len(storage.get_proposals(status='pending') or [])}


def _stickies(now, viewer):
    from services import findings
    rows = findings.open_findings() or []
    # Real severities are decide/approve/fyi (services/findings.py:49 --
    # `severity: str = 'fyi'  # decide | approve | fyi`), not high/medium/low.
    # decide is the most urgent -- open_findings's own sort (line 75) puts it
    # first -- so it carries the highest weight here too.
    order = {'decide': 2, 'approve': 1, 'fyi': 0}
    worst = max(rows, key=lambda r: order.get(r.get('severity'), 0))['severity'] \
        if rows else None
    return {'count': len(rows), 'worst': worst}


def _calendar(now, viewer):
    sched = storage.get_cached_schedule() or {}
    days = [(now.date() + datetime.timedelta(days=i)) for i in range(7)]
    counts = {d.isoformat(): 0 for d in days}
    events_by_id = {e.get('id'): e for e in (sched.get('events') or [])}

    def _event_date(e):
        try:
            return datetime.datetime.fromisoformat(
                str(e.get('start')).replace('Z', '+00:00')).date().isoformat()
        except (ValueError, TypeError):
            return None

    # storage.get_cached_schedule()['events'] is all_events_for_ui (main.py
    # ~17375, ~17524) -- the family's WHOLE calendar, written before the
    # is_display_only_event() gate (main.py ~17068-17088, applied ~17532).
    # An all-day 'No School Today' event lives in `events` and was never a
    # driving need. The schedule's own `true_unassigned` id list (aliased as
    # `unassigned`, both written at main.py ~18280/~18288) does NOT have
    # this problem: it is built solely from daily_events_to_solve (main.py
    # ~18479, unassigned/true_unassigned computed ~18603-18623), which comes
    # from events_to_solve -- the set the display-only gate already emptied
    # of all-day events before the solver ever ran. Joining THAT id list to
    # `events` (for each id's own date) is what keeps a display-only event
    # from ever counting as an uncovered ride.
    unassigned_ids = sched.get('true_unassigned')
    if unassigned_ids is None:
        unassigned_ids = sched.get('unassigned')

    if unassigned_ids is not None:
        for eid in set(unassigned_ids):
            e = events_by_id.get(eid)
            if not e:
                continue
            d = _event_date(e)
            if d in counts:
                counts[d] += 1
    else:
        # Old cache shape, neither id list present: fall back to the
        # assigned/ghost-covered comparison, but skip display-only rows by
        # hand -- the same two fields is_display_only_event() itself reads
        # (main.py ~17068-17088): `all_day` true and `event_type` not
        # `background_trip` (a background trip IS scheduling information,
        # so it is deliberately not excluded here either).
        assignments = dict(sched.get('assignments') or {})
        assignments.update(sched.get('ghost_assignments') or {})
        for e in sched.get('events') or []:
            if e.get('all_day') and e.get('event_type') != 'background_trip':
                continue
            d = _event_date(e)
            if d in counts and not assignments.get(e.get('id')):
                counts[d] += 1

    return {'days': [{'date': d.isoformat(), 'unassigned': counts[d.isoformat()]}
                     for d in days]}


def _window(now, viewer):
    from services import vitals
    res = vitals.read(now)
    worse = [r['label'] for r in (res.get('household') or []) if r.get('worse')]
    label = 'steady week' if res.get('ready') and not worse else \
        ('early days' if not res.get('ready') else 'a strained week')
    return {'ready': bool(res.get('ready')), 'worse': worse[:3], 'label': label}


def _keys(now, viewer):
    from services import cars
    out = []
    for car in storage.get_all_cars():
        if car.get('is_disabled') or not cars.has_telemetry(car):
            continue
        lv = cars.car_levels(car) or {}
        pct = lv.get('fuel_pct') if lv.get('fuel_pct') is not None else lv.get('battery_pct')
        out.append({'id': car.get('id'), 'name': car.get('name') or 'car',
                    'low': pct is not None and pct <= 25})
    return out[:4]


def _contracts(now, viewer):
    # Deals still waiting on an answer are 'draft' (found, nobody asked yet)
    # or 'asking' (requests are out) -- the two non-terminal values of
    # Deal.state (models/schemas.py Deal class: "draft: found, nobody asked
    # yet. asking: requests are out. applying: ... applied: ... dead: ...
    # expired: nobody answered in time."). negotiation.propose() calls this
    # exact pair "open" when it decides whether to reuse a deal rather than
    # re-searching (services/negotiation.py: `if existing.get('state') in
    # ('draft', 'asking')`), and watchers._deal_line treats only this pair as
    # a LIVE deal, letting dead/expired fall through to the coverage ladder.
    rows = storage.get_deals() or []
    openish = [d for d in rows if d.get('state') in ('draft', 'asking')]
    return {'count': len(openish)}


def _binders(now, viewer):
    from services import programs
    out = []
    for p in storage.get_programs(state='active') or []:
        pulled = False
        try:
            # weekday_shortfall returns None when no weekday is meaningfully
            # behind, or a populated dict describing the worst one -- it has
            # no 'short' key of its own (services/programs.py:1139-1186), so
            # the signal is whether it came back at all.
            pulled = programs.weekday_shortfall(p, now=now) is not None
        except Exception:
            pass
        out.append({'id': p.get('id'), 'title': p.get('title') or '',
                    'pulled': pulled})
    return out[:5]


def _gauges(now, viewer):
    from services import web
    settings = storage.get_settings() or {}
    day = now.date().isoformat()
    calls = dict(storage.get_app_state(f'mind_calls:{day}') or {})
    errors = sum(1 for r in (storage.get_ingest_log(limit=10) or [])
                 if 'error' in str(r.get('outcome') or '').lower())
    return {'think': int(calls.get('think', 0)),
            'think_cap': int(settings.get('mind_cap_think', 20)),
            'research': web._month_count(),
            'research_cap': int(settings.get('web_research_cap') or web.DEFAULT_MONTHLY_CAP),
            'ingest_errors': errors}


_SECTIONS = {'board': _board, 'desk': _desk, 'tray': _tray, 'stickies': _stickies,
             'calendar': _calendar, 'window': _window, 'keys': _keys,
             'contracts': _contracts, 'binders': _binders, 'gauges': _gauges}


def state(viewer: Optional[dict], now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now()
    furniture = {}
    for key, fn in _SECTIONS.items():
        try:
            furniture[key] = fn(now, viewer)
        except Exception as e:
            logger.warning(f'[study] section {key} failed: {e}')
            furniture[key] = _CALM[key]
    return {'furniture': furniture, 'generated_ts': time.time()}
