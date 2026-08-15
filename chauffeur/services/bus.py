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
  whose state reads as a place; blank uses HCTB's `sensor.{first}_bus_address`.
  Absent, the chip simply says the bus is on the way without saying where,
  which is most of the value.

WITH HERE COMES THE BUS, THE ONLY REQUIRED FIELD IS `bus_am_stop_time`, and it
is required for two reasons rather than one. It is the OPT-IN — nothing else
tells this app which children ride a bus, and guessing from the presence of
sensors would turn one HA integration into a claim about a child's morning.
And it is the BASELINE: HCTB's arrival sensors answer while the bus is out and
say nothing at 8pm on a Sunday, so without a static time there is no evening
digest line, no leave-by over the summer, and — because lateness is
live-minus-static — no way to know the bus is late at all. Everything else
about HCTB is discovered from the child's first name.
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


# Every name a "the bus is out" entity has been seen under. ORDER MATTERS
# only in that the first one that EXISTS wins — not the first one that is on.
#
# This list is longer than it looks like it should be, and the reason is worth
# keeping. The original pair was composed from the integration's own naming
# rule and probed nothing else — so on a house whose entity is named even
# slightly differently, `bus_active` answered False forever, which silently
# disables the ENTIRE live layer: no live stop estimate, no chip, no
# route-start event, no "nearly here". Nothing reports it, because a bus that
# is never out and a bus we cannot see produce identical silence. A guessed
# name that is wrong is not a small miss here; it is the whole feature off.
_ACTIVE_CANDIDATES = (
    # CONFIRMED on a live install: this is the entity the household's own
    # Home Assistant automation triggers on. `_ignition_on`, not `_ignition`,
    # which is what the composed guess had.
    'binary_sensor.{p}_bus_ignition_on',
    'binary_sensor.{p}_bus_in_service',
    'binary_sensor.{p}_bus_ignition',
    'sensor.{p}_bus_ignition_on',
    'sensor.{p}_bus_in_service',
    'sensor.{p}_bus_ignition',
    'sensor.{p}_ignition_on',
    'binary_sensor.{p}_ignition_on',
)
# member id -> the candidate that actually exists here. Probing six entities
# per member every thirty seconds to learn the same answer is wasteful; the
# first hit is remembered for the life of the process and re-probed if it ever
# stops answering (an integration reload can rename things).
_active_entity_cache = {}

_ON_STATES = ('on', 'true', 'running', 'active')


def active_entity(member):
    """The entity that answers "is the bus out" for this child, or None."""
    explicit = (member.get('bus_active_entity') or '').strip()
    if explicit:
        return explicit
    from services import ha_api
    mid = member.get('id')
    cached = _active_entity_cache.get(mid)
    if cached and ha_api.get_state(cached):
        return cached
    for tpl in _ACTIVE_CANDIDATES:
        ent = tpl.format(p=_prefix(member))
        if ha_api.get_state(ent):
            _active_entity_cache[mid] = ent
            return ent
    return None


def bus_active(member):
    """True while the tracker says the bus is actually out.

    An explicit `bus_active_entity` is authoritative on any platform; failing
    that the name is discovered, because districts and integration versions
    disagree about both the domain and the wording. Live estimates and every
    B3 event are only trusted while this holds.
    """
    try:
        from services import ha_api
        ent = active_entity(member)
        if not ent:
            return False
        st = ha_api.get_state(ent)
        return bool(st and str(st.get('state')).lower() in _ON_STATES)
    except Exception:
        return False


def _entity(member, field, default_suffix):
    """An explicit per-member entity, else HCTB's composed name. The one
    ladder every live reading in this module walks."""
    return (member.get(field) or '').strip() \
        or f"{default_suffix}".format(prefix=_prefix(member))


def _coords_of(entity_id):
    """(lat, lon) from any entity carrying them as attributes — a
    device_tracker, a person, a zone — or None."""
    try:
        from services import ha_api
        st = ha_api.get_state(entity_id) or {}
        attrs = st.get('attributes') or {}
        lat, lon = attrs.get('latitude'), attrs.get('longitude')
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (TypeError, ValueError, Exception):
        return None


def bus_position(member):
    """Where the bus is, as (lat, lon), or None. HCTB's device_tracker by
    default; any tracker on any platform via the override."""
    return _coords_of(_entity(member, 'bus_tracker_entity',
                              'device_tracker.{prefix}_bus_location'))


def stop_position(member):
    """The child's stop, as (lat, lon), or None.

    NO default entity, deliberately, and this is the one live reading in this
    module that does not guess. The stop is usually an HA **zone** a parent
    drew on a map — `zone.bus_stop`, or whatever they called it — and a zone's
    name is a household's own word, not something an integration composes from
    a child's first name. Guessing one would be inventing a name again, which
    is exactly how the address sensor went wrong.

    Any entity carrying `latitude`/`longitude` works: a zone, a device_tracker
    on a platform that publishes stops, even a person. Blank simply means the
    stop is not drawn.

    Per CHILD, necessarily: two kids at different schools have different
    stops, so this is a member field like every other bus setting rather than
    anything household-wide.

    Falls back to the "nearly here" zone, because in most houses they are the
    same circle on the same map and asking for it twice is asking somebody to
    keep two fields in agreement forever.
    """
    ent = (member.get('bus_stop_entity') or '').strip() \
        or (member.get('bus_near_zone') or '').strip()
    return _coords_of(ent) if ent else None


def _haversine_m(lat1, lon1, lat2, lon2):
    import math
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _home_coords():
    """The household's home, geocoded through the existing cache. None when
    no home address is set — the proximity trigger then simply never fires,
    which is the right answer rather than a guess about where a family lives."""
    try:
        from services import maps, storage
        addr = (maps.get_home_location() or '').strip()
        if not addr:
            return None
        g = storage.get_cached_geocode(addr)
        if not g or g.get('precision') == 'failed':
            got = maps.geocode_address(addr)
            return (float(got[0]), float(got[1])) if got else None
        return float(g['lat']), float(g['lon'])
    except Exception:
        return None


def metres_from_home(member):
    """How far the bus is from the house, or None when either end is unknown.

    HOME rather than the stop, deliberately: the question this answers is
    "should we be walking out of the door", and the door is the thing the
    family is standing behind. A stop-centred radius would fire while the bus
    is still three streets the other side of it.
    """
    bus = bus_position(member)
    home = _home_coords()
    if not bus or not home:
        return None
    return _haversine_m(bus[0], bus[1], home[0], home[1])


def _zone(entity_id):
    """(lat, lon, radius_m) for an HA zone, or None. A zone already carries
    its own radius, which is the whole reason to prefer one here."""
    try:
        from services import ha_api
        st = ha_api.get_state(entity_id) or {}
        attrs = st.get('attributes') or {}
        lat, lon = attrs.get('latitude'), attrs.get('longitude')
        if lat is None or lon is None:
            return None
        return float(lat), float(lon), float(attrs.get('radius') or 0)
    except (TypeError, ValueError, Exception):
        return None


def bus_is_near(member):
    """True when the bus has come inside this child's "nearly here" geofence.

    A ZONE first, because a zone is already a geofence: a parent drags a
    circle onto a map in Home Assistant and the radius comes with it, so
    there is no number to type and no unit to get wrong. Whichever zone they
    point at is the trigger — the stop, the corner, the end of the street —
    and the app has no business insisting which.

    Falling back to a radius around HOME keeps the version that needs no zone
    at all. Both blank is off, like every other bus field.
    """
    zone_ent = (member.get('bus_near_zone') or '').strip()
    if zone_ent:
        z = _zone(zone_ent)
        bus = bus_position(member)
        if not z or not bus:
            return False
        # A zone with no radius is a pin, not a fence. Rather than treat that
        # as "never", fall through to the typed radius if there is one.
        if z[2] > 0:
            return _haversine_m(bus[0], bus[1], z[0], z[1]) <= z[2]
    radius = int(member.get('bus_near_radius_m') or 0)
    if radius <= 0:
        return False
    d = metres_from_home(member)
    return d is not None and d <= radius


# The old name, kept because the loop and the tests both read better with it
# and renaming a predicate is not worth a migration.
near_home = bus_is_near


def bus_number(member):
    """The bus's own number/name, or None. HCTB publishes it per student, so
    two siblings on one bus report the SAME number — which is what makes
    "these children share a bus" answerable rather than guessed at."""
    try:
        from services import ha_api
        st = ha_api.get_state(_entity(member, 'bus_number_entity',
                                      'sensor.{prefix}_bus_number')) or {}
        raw = str(st.get('state') or '').strip()
        if not raw or raw.lower() in ('unknown', 'unavailable', 'none'):
            return None
        return raw
    except Exception:
        return None


def bus_key(member):
    """An identity for the VEHICLE, so siblings on one bus are one bus.

    The tracker entity cannot be it: HCTB creates one per STUDENT, so two
    children on the same bus have two entities reporting the same vehicle at
    the same coordinates — and the wall would draw two pins on top of each
    other and the kitchen would say the same sentence twice.

    The bus number is the honest key when the platform publishes one. Failing
    that, position: two trackers at the same coordinates are the same bus, and
    rounding to ~10m absorbs the jitter between two students' updates. Failing
    both, the entity itself, which at least never merges two real buses.
    """
    num = bus_number(member)
    if num:
        return f"num:{num}"
    pos = bus_position(member)
    if pos:
        return f"at:{round(pos[0], 4)},{round(pos[1], 4)}"
    return f"ent:{_entity(member, 'bus_tracker_entity', 'device_tracker.{prefix}_bus_location')}"


def _first_names(members):
    out = []
    for m in members if isinstance(members, (list, tuple)) else [members]:
        n = ((m.get('name') or '').split() or [''])[0]
        if n and n not in out:
            out.append(n)
    return out


def _and_list(names):
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    return ', '.join(names[:-1]) + ' and ' + names[-1]


def route_start_message(members):
    """What a route starting is worth saying. An EVENT the tracker reports,
    not a clock — which is the whole reason this replaced a countdown against
    a time somebody typed months ago.

    Takes a LIST because one bus can be several children's bus: the push is
    per child (it goes to their own phone) but the spoken form names everyone
    it is for, since a kitchen saying the same sentence twice is worse than
    saying it once.
    """
    who = _and_list(_first_names(members))
    return ("🚌 Bus has started",
            "The bus has started its route — time to get ready.",
            f"{who + ', the' if who else 'The'} bus has started its route. "
            f"Time to get ready.")


def near_message(members):
    """The second and sharper event: the bus is nearly here."""
    who = _and_list(_first_names(members))
    return ("🚌 Bus is close",
            "The bus is nearly here — head out to the stop.",
            f"{who + ', the' if who else 'The'} bus is nearly here. "
            f"Time to head out to the stop.")


def announce_room(member):
    """The HA area to speak into for this child, or None. Blank means the
    pushes go out silently — a house with a sleeping baby in it should not
    have to accept a talking kitchen to get a phone notification."""
    return (member.get('bus_announce_room') or '').strip() or None


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
        # `_bus_address`, verified against the integration rather than guessed:
        # HCTB names the DEVICE "{First} Bus" and the entity key is `address`,
        # so HA builds `sensor.{first}_bus_address` — the same shape B1's ETA
        # and in-service entities take. A first cut of this defaulted to
        # `_bus_location`, a name nothing publishes, so the chip would have
        # silently never carried a location for the one integration this arc
        # was built for.
        ent = (member.get('bus_location_entity') or '').strip() \
            or f"sensor.{_prefix(member)}_bus_address"
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
