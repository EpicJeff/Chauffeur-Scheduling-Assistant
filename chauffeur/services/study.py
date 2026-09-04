"""The Study's one read. Twelve furniture signals, every section built in
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
    'monitor': {'clusters': []},
    'map': {'trips': []},
}


def _event_day(e):
    """The local date an event starts on, or None when it cannot be read.
    One parser, because two of them drift and only one of the two is ever
    the one a bug is found in."""
    try:
        return datetime.datetime.fromisoformat(
            str(e.get('start')).replace('Z', '+00:00')).date()
    except (ValueError, TypeError):
        return None


def _event_ts(e):
    """The same start as an epoch float. Naive stamps are read as local, the
    way `datetime.now()` is, so 'in the future' means the same thing on both
    sides of the comparison."""
    try:
        return datetime.datetime.fromisoformat(
            str(e.get('start')).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _board(now, viewer):
    from services import mind, threads as _th
    pins = []
    insights = mind.visible_insights(viewer, now=now)
    # Insights are appended BEFORE threads, and the order is load-bearing:
    # study.js's maybeFly only launches the tray-to-board sheet when an
    # insight pin survived the 14-pin cap below (it counts `kind ==
    # 'insight'` in the payload it is wearing). Threads first would let a
    # busy week spend every slot on threads and silently kill the animation.
    for r in insights:
        pins.append({'id': r['id'], 'kind': 'insight', 'label': r.get('line') or '',
                     'warn': False, 'bad': False, 'changed_ts': r.get('created_ts')})
    stalled = {t['id']: t.get('stall_reason') for t in (_th.stalled(today=now.date()) or [])}
    for t in storage.get_threads(include_closed=False):
        reason = stalled.get(t['id'])
        pins.append({'id': t['id'], 'kind': 'thread', 'label': t.get('title') or '',
                     'warn': bool(reason), 'bad': reason == 'overdue',
                     'changed_ts': t.get('created_at')})
    # `strings` stays in the payload as a permanently empty list so the shape
    # a client normalises against does not change under it. Nothing draws a
    # line between two pins any more: the app stores no insight->thread
    # relation, and a drawn edge is a claim that one exists. A stalled pin
    # grows a decorative dangling thread tail in study.js instead, which
    # claims nothing. Real relation edges wait for a real stored link.
    return {'pins': pins[:14], 'strings': []}


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
    return {'count': len(storage.get_proposals(status='proposed') or [])}


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
        d = _event_day(e)
        return d.isoformat() if d else None

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
    settings = storage.get_settings() or {}

    def _flt(key, default):
        # cars.digest_fuel_notes's own coercion, verbatim (services/cars.py
        # :283-287): a blank or unparsable setting falls back to the default
        # rather than throwing the section into its calm form.
        try:
            return float(settings.get(key) or default)
        except (ValueError, TypeError):
            return default

    batt_warn = _flt('car_battery_warn_pct', cars.DEFAULT_BATTERY_WARN_PCT)
    fuel_warn = _flt('car_fuel_warn_pct', cars.DEFAULT_FUEL_WARN_PCT)
    out = []
    for car in storage.get_all_cars():
        if car.get('is_disabled') or not cars.has_telemetry(car):
            continue
        lv = cars.car_levels(car) or {}
        # The exact shape and precedence of services/cars.py:298-303 — the
        # code that decides whether the family is TOLD a car is low. Battery
        # is asked first and against its own (higher) threshold, because a
        # battery at 28% is genuinely low while 28% of a tank is not; a
        # healthy battery still lets a low tank through the elif, so a plug-in
        # hybrid with both readings is judged on both. Reading one blended
        # percentage against one number, as this did, hung no tag on an EV at
        # 28% and hung one on a petrol car the family was never warned about.
        if lv.get('battery_pct') is not None and lv['battery_pct'] < batt_warn:
            low = True
        elif lv.get('fuel_pct') is not None and lv['fuel_pct'] < fuel_warn:
            low = True
        else:
            low = False
        out.append({'id': car.get('id'), 'name': car.get('name') or 'car',
                    'low': low})
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


def _monitor(now, viewer):
    """Argyle's own screen: one cluster per person, sized by the week they
    are walking into. The node graph the screen animates is DECORATION — the
    dots orbit, the edges are drawn between whatever happens to be near, and
    none of that is a claim. The only thing on the screen that means
    anything is how big each person's cluster is, which is this count.

    An event belongs to a person the way `mind._calendar` already decides it
    does: members own `calendar_ids` and an event carries the ids of the
    calendars it came from. One event can name the same person through two
    of their calendars — that is one thing in their week, not two — so each
    person is counted at most once per event.
    """
    sched = storage.get_cached_schedule() or {}
    horizon = now.date() + datetime.timedelta(days=7)
    members = sorted(storage.get_all_members(),
                     key=lambda m: ((m.get('name') or '').lower(), str(m.get('id'))))
    owner = {}
    for m in members:
        for cid in (m.get('calendar_ids') or []):
            owner.setdefault(str(cid), set()).add(m.get('id'))
    counts = {}
    for e in sched.get('events') or []:
        day = _event_day(e)
        if day is None or not (now.date() <= day <= horizon):
            continue
        theirs = set()
        for cid in (e.get('calendar_ids') or []):
            theirs |= owner.get(str(cid), set())
        for mid in theirs:
            counts[mid] = counts.get(mid, 0) + 1
    # Everybody gets a cluster, including whoever has an empty week. A small
    # quiet cluster is the honest drawing of a quiet week (Law 2); a missing
    # one would read as a missing person.
    return {'clusters': [{'name': m.get('name') or '',
                          'count': counts.get(m.get('id'), 0)}
                         for m in members][:8]}


def _map(now, viewer):
    """Trips as pins on a wall map, each on a string back to home.

    The one relation drawn here is one the app actually stores — a trip has
    a destination and the family leaves from home to reach it — which is
    exactly the test the evidence board's cross-pin strings failed. Where a
    pin SITS on the map is decoration (a hash of its own title, so it stays
    put between polls); the map is not geography and never claims to be.
    """
    from services import scope
    sched = storage.get_cached_schedule() or {}
    starts = {}
    for e in sched.get('events') or []:
        eid = e.get('id')
        if eid is None or str(eid) in starts:
            continue
        ts = _event_ts(e)
        if ts is not None:
            starts[str(eid)] = ts
    rows = []
    for t in storage.get_all_trip_metadata() or []:
        # A trip with a metadata record is 'parents' by default
        # (scope.AUDIENCE_DEFAULTS: a plan is a surprise until somebody says
        # otherwise), and a RESOLVED non-parent viewer is held to that — an
        # adult in the house must not read a surprise off the study wall.
        # `viewer is None` is the ADMIN SURFACE, where /trips itself already
        # lists every trip including the ones the family wall may not show,
        # so the map opens no door that surface did not already have.
        if viewer is not None and not scope.audience_allows(t, 'trip', viewer):
            continue
        ts = t.get('mock_start_date')
        try:
            ts = float(ts) if ts is not None else None
        except (TypeError, ValueError):
            ts = None
        if ts is None:
            ts = starts.get(str(t.get('event_id')))
        rows.append({'id': t.get('id') or t.get('event_id') or '',
                     'title': t.get('title') or '',
                     'location': t.get('location') or '',
                     'start_ts': ts, 'upcoming': False})
    # A trip that already happened is not a plan any more. A trip with no
    # date yet still is one, so it keeps its pin and simply never glows.
    nowts = now.timestamp()
    rows = [r for r in rows if r['start_ts'] is None or r['start_ts'] >= nowts]
    rows.sort(key=lambda r: (r['start_ts'] is None, r['start_ts'] or 0))
    rows = rows[:6]
    for r in rows:                      # the soonest dated one, and only it
        if r['start_ts'] is not None:
            r['upcoming'] = True
            break
    return {'trips': rows}


_SECTIONS = {'board': _board, 'desk': _desk, 'tray': _tray, 'stickies': _stickies,
             'calendar': _calendar, 'window': _window, 'keys': _keys,
             'contracts': _contracts, 'binders': _binders, 'gauges': _gauges,
             'monitor': _monitor, 'map': _map}


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
