"""School-bus support (bus arc B1 — docs/roadmap.md).

Bus kids are the majority case the kid arc's car-centric launch/dismissal
machinery skipped. Chauffeur does NOT track buses — Here Comes The Bus
already does (surfaced in HA by the pcartwright81 integration); this module
is the TRANSLATION layer: static per-member stop times are the always-works
baseline, and the HCTB sensors — auto-discovered through the HA bridge by
the kid's first name — upgrade the times to live estimates when the bus is
actually running. The bus never enters the solver: it is kid-facing info,
like weather, and every helper degrades to the static answer (or None) when
HA or the integration is absent.

Member fields (children, set in Config → People next to school hours):
- bus_am_stop_time   'HH:MM' — morning pickup at the stop; the OPT-IN switch
  for the whole feature (no value → Chauffeur says nothing about buses)
- bus_pm_stop_time   'HH:MM' — usual afternoon drop-off (optional)
- bus_walk_mins      int     — walk to the stop (default 5)
- bus_entity_prefix  str     — HCTB entity prefix override; defaults to the
  member's lowercase first name (HCTB entities are sensor.{first}_bus_*)
- bus_am_eta_entity / bus_pm_eta_entity / bus_active_entity — EXPLICIT HA
  entity ids for districts on OTHER tracking platforms (Traversa, Edulog,
  Zonar, …): any integration exposing a stop-ETA sensor (HH:MM or ISO
  timestamp state) and an "is running" binary sensor plugs in here; blank
  = HCTB auto-discovery.
"""
import datetime

DEFAULT_WALK_MINS = 5
# Live estimates only count as "late" beyond this many minutes — HCTB
# estimates jitter, and a 2-minute wobble is not news a kid needs.
LATE_THRESHOLD_MINS = 4


def _prefix(member):
    p = (member.get('bus_entity_prefix') or '').strip().lower()
    if p:
        return p
    return ((member.get('name') or '').split() or [''])[0].lower()


def _parse_hhmm(s):
    try:
        hh, mm = [int(x) for x in str(s).split(':')[:2]]
        return datetime.time(hh, mm)
    except (ValueError, TypeError):
        return None


def _fmt(t):
    return t.strftime('%I:%M %p').lstrip('0')


def _parse_time_state(s):
    """A sensor state as a local time-of-day: 'HH:MM[:SS]' or a full ISO
    timestamp (device_class timestamp platforms), else None."""
    s = str(s).strip()
    if 'T' in s:
        try:
            dt = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
            if dt.tzinfo:
                dt = dt.astimezone()
            return dt.time().replace(second=0, microsecond=0)
        except ValueError:
            return None
    return _parse_hhmm(s)


def live_stop_time(member, period='am'):
    """The tracker's stop-arrival estimate as datetime.time, or None (no HA,
    no integration, sensor unknown/unavailable). Explicit entity override
    first (any platform), else HCTB auto-discovery. Never raises."""
    try:
        from services import ha_api
        ent = (member.get(f'bus_{period}_eta_entity') or '').strip() \
            or f"sensor.{_prefix(member)}_bus_{period}_stop_arrival_time"
        st = ha_api.get_state(ent)
        if not st or str(st.get('state')) in ('unknown', 'unavailable', 'None', ''):
            return None
        return _parse_time_state(st['state'])
    except Exception:
        return None


def bus_active(member):
    """True while the tracker says the bus is actually out. An explicit
    bus_active_entity (any platform) is authoritative when set; else the
    HCTB in-service/ignition pair. Live estimates are only trusted while
    this holds."""
    try:
        from services import ha_api
        explicit = (member.get('bus_active_entity') or '').strip()
        if explicit:
            st = ha_api.get_state(explicit)
            return bool(st and st.get('state') == 'on')
        for key in ('in_service', 'ignition'):
            st = ha_api.get_state(f"binary_sensor.{_prefix(member)}_bus_{key}")
            if st and st.get('state') == 'on':
                return True
    except Exception:
        pass
    return False


def morning_launch(member, date_str, rides=None):
    """A launch dict (member_day's shape, plus bus keys) for a school-morning
    bus ride, or None. Static stop time is the baseline; the live HCTB
    estimate wins when the bus is actually running TODAY. Skips weekends and
    mornings where a car ride already covers the school run — a bus line
    under a "Dad is driving you" card would contradict it."""
    static_t = _parse_hhmm(member.get('bus_am_stop_time'))
    if not static_t:
        return None
    try:
        day = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
    # school_in_session covers weekends AND — when the family configured
    # them — the school-year bounds and no-school calendar days, so the bus
    # line disappears over summer, breaks, and teacher workdays.
    from services import school
    if not school.school_in_session(day):
        return None
    school_start = _parse_hhmm(member.get('school_hours_start')) or datetime.time(9, 30)
    for r in (rides or []):
        try:
            st = datetime.datetime.fromisoformat(r['start'])
        except (ValueError, TypeError, KeyError):
            continue
        if st.time() <= school_start:
            return None

    stop_t, live = static_t, False
    if day == datetime.date.today() and bus_active(member):
        lt = live_stop_time(member, 'am')
        if lt:
            stop_t, live = lt, True

    walk = int(member.get('bus_walk_mins') or DEFAULT_WALK_MINS)
    leave_dt = datetime.datetime.combine(day, stop_t) - datetime.timedelta(minutes=walk)
    late = None
    if live:
        delta = (datetime.datetime.combine(day, stop_t)
                 - datetime.datetime.combine(day, static_t)).total_seconds() / 60
        if delta >= LATE_THRESHOLD_MINS:
            late = int(delta)
    return {
        'leave_at': leave_dt.isoformat(),
        'leave_label': _fmt(leave_dt.time()),
        'travel_mins': walk,
        'title': f"🚌 Bus at {_fmt(stop_t)}",
        'driver': None,
        'bus': True,
        'bus_stop_label': _fmt(stop_t),
        'bus_live': live,
        'bus_late_mins': late,
    }


def digest_line(launch):
    """The kid-digest/kiosk wording for a bus launch dict. Lateness is
    framed as PERMISSION TO RELAX, never urgency."""
    line = (f"🚌 Bus at {launch['bus_stop_label']}"
            f" — out the door by {launch['leave_label']}")
    if launch.get('bus_late_mins'):
        line += f" (running ~{launch['bus_late_mins']} min late — no rush)"
    return line


def dismissal_line(member):
    """Body for the dismissal push when NO car ride follows school — the bus
    IS the answer then. None when the member has no bus config, so the
    original silence rule stands for non-bus kids."""
    if not (member.get('bus_am_stop_time') or member.get('bus_pm_stop_time')):
        return None
    if bus_active(member):
        lt = live_stop_time(member, 'pm')
        if lt:
            return f"Today's bus should reach your stop around {_fmt(lt)}."
    static_pm = _parse_hhmm(member.get('bus_pm_stop_time'))
    if static_pm:
        return f"It usually drops you off around {_fmt(static_pm)}."
    return "You're riding the bus home today."
