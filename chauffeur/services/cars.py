"""Car telemetry (C2, docs/car_telemetry_design.md).

Reads the HA entities mapped on Car records and produces family-map entries,
readiness warnings (charge/fuel before upcoming drives), and away-from-home
warnings. Telemetry informs humans and creates errands; it NEVER moves solver
assignments. Every read degrades to None when HA is absent, and a car with no
HA fields is untouched by everything here (the C1 inertness rule extends).
"""
import datetime

_BAD_STATES = ('unknown', 'unavailable', 'None', '')

AWAY_LOOKAHEAD_HOURS = 3
UPCOMING_WINDOW_HOURS = 24
DEFAULT_BATTERY_WARN_PCT = 30.0
DEFAULT_FUEL_WARN_PCT = 25.0


def _get(car, key):
    return (car.get(key) if isinstance(car, dict) else getattr(car, key, None)) or None


def _state_obj(entity_id):
    if not entity_id:
        return None
    try:
        from services import ha_api
        st = ha_api.get_state(str(entity_id).strip())
        if not st or str(st.get('state')) in _BAD_STATES:
            return None
        return st
    except Exception:
        return None


def _num(entity_id):
    st = _state_obj(entity_id)
    if st is None:
        return None
    try:
        return float(str(st['state']).replace('%', '').strip())
    except (ValueError, TypeError):
        return None


def has_telemetry(car):
    return any(_get(car, k) for k in (
        'ha_device_tracker', 'ha_battery_entity', 'ha_fuel_entity', 'ha_range_entity'))


def car_location(car):
    """{state, latitude, longitude, gps_accuracy, last_updated} or None."""
    st = _state_obj(_get(car, 'ha_device_tracker'))
    if st is None:
        return None
    attrs = st.get('attributes') or {}
    return {
        'state': st.get('state'),
        'latitude': attrs.get('latitude'),
        'longitude': attrs.get('longitude'),
        'gps_accuracy': attrs.get('gps_accuracy'),
        'last_updated': st.get('last_updated'),
    }


def car_levels(car):
    return {
        'battery_pct': _num(_get(car, 'ha_battery_entity')),
        'fuel_pct': _num(_get(car, 'ha_fuel_entity')),
        'range': _num(_get(car, 'ha_range_entity')),
    }


def _event_start(e):
    raw = e.get('start') if isinstance(e, dict) else getattr(e, 'start', None)
    if isinstance(raw, datetime.datetime):
        dt = raw
    else:
        try:
            dt = datetime.datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def upcoming_car_events(cars, hours=UPCOMING_WINDOW_HOURS, now=None):
    """Per-car upcoming solver drives within the window, from the daily-cache
    car_assignments. Returns ({car_id: [{id,title,start}]}, {event_id: car_id})."""
    from services import storage
    now = now or datetime.datetime.now().astimezone()
    horizon = now + datetime.timedelta(hours=hours)
    car_ids = {str(_get(c, 'id')) for c in cars}
    by_car, car_by_event = {}, {}
    for day_offset in range(0, 2 + hours // 24):
        d = (now + datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        cache = storage.get_cached_daily_schedule(d)
        sched = (cache or {}).get('schedule') or {}
        ca = sched.get('car_assignments') or {}
        if not ca:
            continue
        ev_by_id = {}
        for e in sched.get('events') or []:
            eid = e.get('id') if isinstance(e, dict) else getattr(e, 'id', None)
            if eid:
                ev_by_id[eid] = e
        for eid, cid in ca.items():
            if str(cid) not in car_ids:
                continue
            e = ev_by_id.get(eid)
            if not e:
                continue
            start = _event_start(e)
            if start is None or not (now <= start <= horizon):
                continue
            title = (e.get('title') if isinstance(e, dict) else getattr(e, 'title', '')) or 'a drive'
            by_car.setdefault(str(cid), []).append({'id': eid, 'title': title, 'start': start})
            car_by_event[eid] = str(cid)
    for lst in by_car.values():
        lst.sort(key=lambda x: x['start'])
    return by_car, car_by_event


def readiness_warnings(cars, levels_by_car, upcoming_by_car,
                       battery_warn=DEFAULT_BATTERY_WARN_PCT,
                       fuel_warn=DEFAULT_FUEL_WARN_PCT):
    """Pure. Warn only for cars that someone actually needs soon — a low car
    with no upcoming drives is not worth a push. Battery beats fuel when a
    hybrid trips both (one push per car per day; charging is the cheaper ask)."""
    out = []
    for c in cars:
        cid = str(_get(c, 'id'))
        events = upcoming_by_car.get(cid) or []
        if not events:
            continue
        lv = levels_by_car.get(cid) or {}
        b, f = lv.get('battery_pct'), lv.get('fuel_pct')
        if b is not None and b < battery_warn:
            out.append({'car': c, 'kind': 'battery', 'level': b, 'events': events})
        elif f is not None and f < fuel_warn:
            out.append({'car': c, 'kind': 'fuel', 'level': f, 'events': events})
    return out


def away_warnings(cars, locations_by_car, upcoming_by_car, in_progress_car_ids=(),
                  lookahead_hours=AWAY_LOOKAHEAD_HOURS, now=None):
    """Pure. A car with a drive starting soon that isn't home — and isn't out
    on an in-progress drive right now — needs a human to notice."""
    now = now or datetime.datetime.now().astimezone()
    horizon = now + datetime.timedelta(hours=lookahead_hours)
    out = []
    for c in cars:
        cid = str(_get(c, 'id'))
        if cid in in_progress_car_ids:
            continue
        loc = locations_by_car.get(cid)
        if not loc or not loc.get('state') or str(loc['state']).lower() == 'home':
            continue
        ev = next((e for e in (upcoming_by_car.get(cid) or [])
                   if now <= e['start'] <= horizon), None)
        if ev:
            out.append({'car': c, 'state': loc['state'], 'event': ev})
    return out


def in_progress_car_ids():
    """Cars currently out on an in-progress drive leg (today's cache)."""
    from services import storage
    try:
        legs = storage.get_in_progress_drives()
    except Exception:
        return set()
    if not legs:
        return set()
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    cache = storage.get_cached_daily_schedule(today)
    ca = ((cache or {}).get('schedule') or {}).get('car_assignments') or {}
    out = set()
    for leg in legs:
        eid = str(leg)
        for suffix in ('_dropoff', '_pickup'):
            if eid.endswith(suffix):
                eid = eid[:-len(suffix)]
        for k in (str(leg), eid):
            if k in ca:
                out.add(str(ca[k]))
    return out


def ensure_fuel_errand(car, settings):
    """Create the auto fuel-up errand unless an active one for this car already
    exists. The solver's errand pass places it into someone's free window.
    Returns the new doc_id or None. EVs never get an errand — charging happens
    at home, so battery warnings stay push-only."""
    from services import storage
    from models.schemas import Errand
    cid = str(_get(car, 'id'))
    for er in storage.get_all_errands():
        tags = er.get('tags') or []
        if 'auto_car_fuel' in tags and cid in tags \
                and not er.get('is_completed') and er.get('status') != 'completed':
            return None
    loc = (str(settings.get('car_fuel_station') or '')).strip()
    if not loc:
        try:
            from services import maps
            loc = maps.get_home_location() or ''
        except Exception:
            loc = ''
    if not loc:
        return None
    errand = Errand(
        title=f"⛽ Fuel up {_get(car, 'name') or 'the car'}",
        duration_mins=15, location=loc, priority=2, window_days=2,
        tags=['auto_car_fuel', cid],
        allowed_drivers=[str(x) for x in (_get(car, 'allowed_driver_ids') or [])],
    )
    return storage.add_errand(errand.model_dump())


def run_sweep(send, now=None):
    """One readiness pass. `send(member, title, body)` delivers a push to one
    member. Dedupe markers live in app_state and are set BEFORE sending (the
    push-loop convention: a half-failing send must not retry every cycle).
    Returns the marker keys acted on (for logs/tests)."""
    from services import storage
    cars = [c for c in storage.get_all_cars()
            if not c.get('is_disabled') and has_telemetry(c)]
    if not cars:
        return []
    settings = storage.get_settings()
    now = now or datetime.datetime.now().astimezone()
    today = now.strftime('%Y-%m-%d')

    def _flt(key, default):
        try:
            return float(settings.get(key) or default)
        except (ValueError, TypeError):
            return default

    battery_warn = _flt('car_battery_warn_pct', DEFAULT_BATTERY_WARN_PCT)
    fuel_warn = _flt('car_fuel_warn_pct', DEFAULT_FUEL_WARN_PCT)
    auto_errand = str(settings.get('car_auto_errand') or '').lower() in ('1', 'true', 'yes', 'on')

    upcoming, _ = upcoming_car_events(cars, now=now)
    levels = {str(c.get('id')): car_levels(c) for c in cars}
    locations = {str(c.get('id')): car_location(c) for c in cars}

    members = storage.get_all_members()

    def targets(car):
        dd = car.get('default_driver_id')
        if dd:
            m = next((m for m in members if m.get('driver_id') == dd), None)
            if m:
                return [m]
        return [m for m in members if m.get('role') == 'parent']

    sent = storage.get_app_state('car_push_markers') or {}
    changed = False
    actions = []

    def fire(key, car, title, body):
        nonlocal changed
        sent[key] = now.timestamp()
        changed = True
        for m in targets(car):
            try:
                send(m, title, body)
            except Exception:
                pass
        actions.append(key)

    for w in readiness_warnings(cars, levels, upcoming, battery_warn, fuel_warn):
        car = w['car']
        key = f"car_ready:{car.get('id')}:{today}"
        if key in sent:
            continue
        nm = car.get('name') or 'the car'
        first = w['events'][0]
        when = first['start'].strftime('%I:%M %p').lstrip('0')
        n = len(w['events'])
        drives = f"{n} drive{'s' if n != 1 else ''}"
        if w['kind'] == 'battery':
            title = f"🔌 Charge the {nm}"
            body = f"Battery at {int(w['level'])}% with {drives} in the next 24h (first: {first['title']} at {when}). Plug it in."
        else:
            title = f"⛽ Fuel up the {nm}"
            body = f"Fuel at {int(w['level'])}% with {drives} in the next 24h (first: {first['title']} at {when})."
            if auto_errand and ensure_fuel_errand(car, settings):
                body += " Added a fuel-up errand to the schedule."
        fire(key, car, title, body)

    for w in away_warnings(cars, locations, upcoming, in_progress_car_ids(), now=now):
        car = w['car']
        ev = w['event']
        key = f"car_away:{car.get('id')}:{ev['id']}"
        if key in sent:
            continue
        when = ev['start'].strftime('%I:%M %p').lstrip('0')
        state = str(w['state']).replace('_', ' ')
        fire(key, car, f"🚗 {car.get('name') or 'A car'} isn't home",
             f"It's at {state}, but {ev['title']} at {when} assumes it's available.")

    if changed:
        cutoff = now.timestamp() - 2 * 86400
        storage.set_app_state('car_push_markers',
                              {k: v for k, v in sent.items() if v >= cutoff})
    return actions
