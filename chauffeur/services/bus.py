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

B2 adds the LIVE morning layer, and its fields are per-member for the same
reason every other bus field is: the bus is a fact about one child, and this
family's fifteen-year-old does not want the nudge their seven-year-old needs.

- bus_ready_lead_mins  int — minutes before the leave-by time to send the
  "get ready" push. BLANK OR 0 IS OFF, which is the whole opt-in: a separate
  enable switch beside a number is two ways to say the same thing, and the
  one that ships off is the one people forget to look at.
- bus_late_push        bool — send one "running late, no rush" push on a
  morning the tracker says the bus is behind. Separate from the nudge above
  because they are different kinds of message: one is a routine, the other
  is news, and a family may well want the news and not the routine.
- bus_location_entity  str — where the bus IS, for the live chip. Any sensor
  whose state reads as a place; blank guesses HCTB's. Absent, the chip simply
  says the bus is on the way without saying where, which is most of the value.
"""
import datetime

DEFAULT_WALK_MINS = 5
# Live estimates only count as "late" beyond this many minutes — HCTB
# estimates jitter, and a 2-minute wobble is not news a kid needs.
LATE_THRESHOLD_MINS = 4
# The morning window the live layer runs in. Outside it the trackers are
# either idle or doing the afternoon route, and a chip about a bus that is
# taking somebody else home is noise on a kitchen wall.
AM_WINDOW = (6, 9)


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


def bus_where(member):
    """Where the bus is right now, as a short human phrase, or None.

    Explicit entity first, HCTB's guessed name after — the same ladder every
    other live reading in this module walks. Deliberately forgiving about what
    it finds: a district's sensor might hold a cross-street, a road name or a
    stop number, and all three are useful printed after "on the way". Anything
    that is obviously not a place (a bare number, a timestamp, a state word)
    is dropped rather than shown, because "🚌 on the way · 42" answers nothing.
    """
    try:
        from services import ha_api
        ent = (member.get('bus_location_entity') or '').strip() \
            or f"sensor.{_prefix(member)}_bus_location"
        st = ha_api.get_state(ent)
        if not st:
            return None
        raw = str(st.get('state') or '').strip()
        if not raw or raw.lower() in ('unknown', 'unavailable', 'none', 'off', 'on'):
            return None
        if len(raw) > 60 or raw.replace('.', '').replace('-', '').isdigit():
            return None
        return raw
    except Exception:
        return None


def in_am_window(now=None):
    """Is it the morning run? The live layer costs HA reads, and a wall panel
    asking about buses at four in the afternoon is asking about somebody
    else's route."""
    now = now or datetime.datetime.now()
    return AM_WINDOW[0] <= now.hour < AM_WINDOW[1]


def live_chip(member, launch, now=None):
    """The kiosk's live line for a bus morning, or None.

    Only while the tracker says the bus is actually rolling AND it is the
    morning run — a chip that says "on the way" about a parked bus is worse
    than no chip, because somebody will believe it. Lateness rides along in
    the same voice B1 fixed: permission to relax, never urgency.
    """
    if not launch or not launch.get('bus') or not launch.get('bus_live'):
        return None
    if not in_am_window(now):
        return None
    line = f"🚌 On the way · stop ~{launch['bus_stop_label']}"
    where = launch.get('bus_where')
    if where:
        line += f" · {where}"
    if launch.get('bus_late_mins'):
        line += f" · ~{launch['bus_late_mins']} min late, no rush"
    return line


def ready_push(member, launch, now):
    """(title, body) for the "get ready" nudge, or None when it is not due.

    Due inside a WINDOW that opens at leave-by minus the member's lead and
    closes at the leave-by time itself — never after. The background loop runs
    every 30 seconds but a panel can be asleep, a container can restart, and a
    nudge to leave for a bus that has gone is the one thing this must never
    send. Same shape as the dismissal push's own 45-minute ceiling, tighter
    because the deadline here is the point.
    """
    lead = int(member.get('bus_ready_lead_mins') or 0)
    if lead <= 0 or not launch or not launch.get('bus'):
        return None
    try:
        leave = datetime.datetime.fromisoformat(launch['leave_at'])
    except (ValueError, TypeError, KeyError):
        return None
    if not (leave - datetime.timedelta(minutes=lead) <= now <= leave):
        return None
    mins = max(0, int((leave - now).total_seconds() // 60))
    when = "now" if mins <= 1 else f"in {mins} min"
    body = f"Head out {when} — bus at {launch['bus_stop_label']}."
    if launch.get('bus_late_mins'):
        # The nudge and the lateness are one message when both are true. Two
        # pushes a minute apart about the same bus is how a phone gets muted.
        body += f" It's running ~{launch['bus_late_mins']} min late, so no rush."
    return ("🚌 Bus soon", body)


def late_push(member, launch):
    """(title, body) for the "running late" heads-up, or None.

    News, not a countdown: it fires once, it says how late, and it says the
    only useful thing about being late for a bus that is also late — that
    there is no need to hurry.
    """
    if not member.get('bus_late_push') or not launch or not launch.get('bus'):
        return None
    late = launch.get('bus_late_mins')
    if not late:
        return None
    return ("🚌 Bus running late",
            f"The bus is about {late} min behind — no rush. "
            f"It should reach your stop around {launch['bus_stop_label']}.")


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

    stop_t, live, where = static_t, False, None
    if day == datetime.date.today() and bus_active(member):
        lt = live_stop_time(member, 'am')
        if lt:
            stop_t, live = lt, True
            # Only asked for when the bus is actually out: a location sensor
            # read on every board poll, all day, for a bus that is parked is
            # an HA request per panel per minute for nothing.
            where = bus_where(member)

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
        'bus_where': where,
    }


def digest_line(launch):
    """The kid-digest/kiosk wording for a bus launch dict. Lateness is
    framed as PERMISSION TO RELAX, never urgency."""
    line = (f"🚌 Bus at {launch['bus_stop_label']}"
            f" — out the door by {launch['leave_label']}")
    if launch.get('bus_late_mins'):
        line += f" (running ~{launch['bus_late_mins']} min late — no rush)"
    # Where it is, only ever as a tail on the line that already exists. The
    # evening digest reads this too, and a location is meaningless twelve
    # hours early — but `bus_where` is only ever set while the bus is out, so
    # the evening copy never has one.
    elif launch.get('bus_where'):
        line += f" (on the way · {launch['bus_where']})"
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
