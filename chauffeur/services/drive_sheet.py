"""The screen a driver has open while they are driving.

One endpoint assembles it (`sheet`), because everything on it already exists
somewhere else and the client should not have to re-derive any of it: the
destination from the leg id, the ETA from the row `Start Drive` wrote, the
passengers from the same three-way binding My Day uses, the prep items from
the kit matcher, the car from its telemetry, the next drive from leave_by.

The part that is genuinely new is the POSITION LANE. Arrival auto-complete
could only ever see `ha_person_entity` and the car's tracker, so a household
without the Home Assistant companion app on the driver's phone never had a
fix and never had a leg complete itself. While this sheet is open the phone
reports one, which is the only window in which the app has any business
knowing where somebody is — and the reason the sheet is worth a wake lock.

See docs/drive_sheet_design.md.
"""
import datetime
import re
from typing import Optional

from services import drive_arrival, storage

# The whole vocabulary of the quick-message row. Canned on purpose: a driver
# cannot type, and the things they need to say from the car are always these.
# `waiting_only` messages are hidden unless somebody is actually standing
# somewhere waiting for this car (drive_arrival.leg_is_toward_waiting) — "I'm
# outside" sent from a drive with the kid already in the back seat is the push
# that teaches a family to ignore pushes.
MESSAGES = [
    {'key': 'outside', 'icon': '🚗', 'label': "I'm outside",
     'body': "{who} is outside for {title}", 'waiting_only': True},
    {'key': 'five_min', 'icon': '⏱️', 'label': 'About 5 minutes',
     'body': "{who} is about 5 minutes away from {title}", 'waiting_only': True},
    {'key': 'come_out', 'icon': '👋', 'label': 'Come on out',
     'body': "{who} is waiting outside for {title} — come on out",
     'waiting_only': True},
    {'key': 'on_my_way', 'icon': '🛣️', 'label': 'On my way',
     'body': "{who} is on the way to {title}", 'waiting_only': False},
]


def _leg_event_id(leg_id) -> str:
    return drive_arrival._leg_event_id(leg_id)


def _event_for_leg(leg_id, events: dict) -> tuple:
    """(event, display title) for a leg, following the split-slice fallback
    the rest of the leg machinery uses: a `_pickup` / `_dropoff` variant may
    not exist as its own row in the events cache."""
    ev_id = _leg_event_id(leg_id)
    ev = events.get(ev_id)
    if ev:
        return ev, (ev.get('title') or 'Your drive')
    base = re.sub(r'_(dropoff|pickup)$', '', str(ev_id))
    ev = events.get(base)
    if not ev:
        return None, None
    title = ev.get('title') or 'Your drive'
    if str(ev_id).endswith('_pickup'):
        title = f"Pick-up from {title}"
    elif str(ev_id).endswith('_dropoff'):
        title = f"Drop-off at {title}"
    return ev, title


def ride_members_for_event(ev, ev_id, sched=None) -> list:
    """Every member riding on this event, not only the children.

    main._kid_members_for_event answers the same question for pushes and
    stops at `role == 'child'`, which is right for a push worded at a kid
    and wrong for a roll call: the sixteen-year-old with a passenger record
    is somebody the driver still has to have in the car."""
    from services import family_digest
    sched = sched or storage.get_cached_schedule() or {}
    matched_rules = sched.get('matched_rules', {}) or {}
    passengers = {p.get('id'): p for p in storage.get_all_passengers()}
    out = []
    for m in storage.get_all_members():
        if m.get('system') or not m.get('passenger_id'):
            continue
        p = passengers.get(m['passenger_id']) or {}
        p_cals = set(p.get('calendar_ids') or [])
        p_tags = {t.lower() for t in (p.get('hashtags') or [])}
        if family_digest._kid_event_match(ev, str(ev_id), m['passenger_id'],
                                          p_cals, p_tags, matched_rules):
            out.append(m)
    return out


def _driver_member(leg_id, sched):
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    ev_id = _leg_event_id(leg_id)
    d_id = assignments.get(ev_id) \
        or assignments.get(re.sub(r'_(dropoff|pickup)$', '', str(ev_id)))
    if not d_id or str(d_id).startswith('ghost_'):
        return None, None
    return storage.get_member_by_driver_id(d_id), d_id


def _car_for(ev_id, sched) -> Optional[dict]:
    """The assigned car with its levels, and a warning when one is low — the
    same thresholds the car pushes use, on the one screen where a low tank is
    still actionable."""
    car_id = (sched.get('car_assignments') or {}).get(ev_id)
    if not car_id:
        return None
    car = next((c for c in storage.get_all_cars()
                if str(c.get('id')) == str(car_id)), None)
    if not car:
        return None
    from services import cars as cars_svc
    levels = cars_svc.car_levels(car)
    settings = storage.get_settings() or {}

    def _flt(key, default):
        try:
            return float(settings.get(key) or default)
        except (ValueError, TypeError):
            return default

    warn = None
    fuel, batt = levels.get('fuel_pct'), levels.get('battery_pct')
    if fuel is not None and fuel <= _flt('car_fuel_warn_pct',
                                         cars_svc.DEFAULT_FUEL_WARN_PCT):
        warn = f"Fuel {round(fuel)}%"
    elif batt is not None and batt <= _flt('car_battery_warn_pct',
                                           cars_svc.DEFAULT_BATTERY_WARN_PCT):
        warn = f"Charge {round(batt)}%"
    return {'id': str(car.get('id')), 'name': car.get('name'),
            'icon': car.get('icon') or '🚗', 'image': car.get('image'),
            'range': levels.get('range'), 'warn': warn}


def _next_drive(leg_id, driver_id, sched, now=None) -> tuple:
    """(the drive AFTER this one, whether the day is done) — what a driver
    wants to know while they are parked at the destination.

    **Today only.** The schedule cache holds days either side, and a sheet
    held at six in the evening answering with tomorrow morning's school run
    is worse than answering nothing: it reads as "you are not finished" to
    somebody who is. The day is the CURRENT DRIVE's own date rather than the
    wall clock's, so a drive that crosses midnight keeps talking about the
    night it belongs to.

    Display only — it deliberately does not return a leg id, because deriving
    one for an arbitrary next event means guessing which edge shape the
    solver used, and a tap that opens the wrong sheet is worse than a line of
    text that is simply true."""
    if not driver_id:
        return None, False           # nothing known: the sheet says nothing
    now = now or datetime.datetime.now()
    from services import leave_by
    this_ev_id = _leg_event_id(leg_id)
    assignments = dict(sched.get('assignments') or {})
    mine = []
    for ev in sched.get('events') or []:
        ev_id = str(ev.get('id'))
        if assignments.get(ev_id) != driver_id:
            continue
        try:
            start = datetime.datetime.fromisoformat(
                str(ev['start'])).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            continue
        mine.append((start, ev_id, ev))
    mine.sort(key=lambda t: t[0])
    this_start = next((s for s, i, _ in mine if i == this_ev_id), None)
    today = (this_start or now).date()
    for start, ev_id, ev in mine:
        if ev_id == this_ev_id or start < (this_start or now):
            continue
        if start.date() != today:
            break                    # sorted: everything past here is later still
        run = leave_by.for_run(sched, driver_id, ev_id, start, live=True, now=now)
        return {'event_id': ev_id, 'title': ev.get('title') or 'your next drive',
                'location': ev.get('location'),
                'leave_label': (run or {}).get('leave_label'),
                'start_label': leave_by.clock(start)}, False
    return None, True                # this is the last drive of the day


def _base_event_id(ev_id) -> str:
    """Prep confirmations are stored against the PARENT event instance — the
    client strips leg suffixes before posting and this must match."""
    return re.sub(r'_(dropoff|pickup)$', '', str(ev_id))


def sheet(leg_id: str, now=None) -> dict:
    """Everything the drive sheet draws, in one call."""
    now = now or datetime.datetime.now()
    from services import leave_by
    sched = storage.get_cached_schedule() or {}
    events = {str(e.get('id')): e for e in (sched.get('events') or [])}
    ev, title = _event_for_leg(leg_id, events)
    ev_id = _leg_event_id(leg_id)
    row = storage.get_drive_status(leg_id) or {}
    driver, driver_id = _driver_member(leg_id, sched)
    is_home = str(leg_id).startswith('final_')

    roll = storage.get_roll_call(leg_id)
    passengers = []
    if ev is not None:
        for m in ride_members_for_event(ev, ev_id, sched):
            passengers.append({'member_id': m.get('id'), 'name': m.get('name'),
                               'is_child': m.get('role') == 'child',
                               'aboard': roll.get(str(m.get('id')))})

    prep_items = []
    if ev is not None and ev.get('event_type') not in ('errand', 'background_trip'):
        try:
            from services import prep_kits
            prep_items = prep_kits.items_for_event(ev, None, None) or []
        except Exception as e:
            print(f"drive sheet prep failed: {e}")

    waiting = drive_arrival.leg_is_toward_waiting(leg_id)
    next_drive, day_done = _next_drive(leg_id, driver_id, sched, now)
    eta_ts = row.get('eta_ts')
    return {
        'leg_id': leg_id,
        'event_id': ev_id,
        'status': row.get('status') or 'pending',
        'destination': {'label': 'Home' if is_home else (title or 'Your stop'),
                        'address': drive_arrival._dest_address(leg_id, events)},
        'eta_ts': eta_ts,
        'eta_label': leave_by.clock_label(eta_ts) if eta_ts else None,
        'toward_waiting': waiting,
        'driver_name': (driver or {}).get('name'),
        'passengers': passengers,
        'prep': {'items': prep_items,
                 'confirmed': _base_event_id(ev_id) in set(storage.get_confirmed_preps())},
        'car': _car_for(ev_id, sched),
        'next_drive': next_drive,
        'day_done': day_done,
        'messages': [{'key': m['key'], 'icon': m['icon'], 'label': m['label']}
                     for m in MESSAGES if waiting or not m['waiting_only']],
        'audience': [m.get('name') for m in _message_audience(leg_id, sched)],
    }


def _message_audience(leg_id, sched=None) -> list:
    """Who hears a quick message: the people riding, plus (when the riders
    include a child) the parents who are not driving — the same audience
    shape as the on-the-way push, so the family never learns two different
    rules for who gets told what about a drive."""
    sched = sched or storage.get_cached_schedule() or {}
    events = {str(e.get('id')): e for e in (sched.get('events') or [])}
    ev, _title = _event_for_leg(leg_id, events)
    if ev is None:
        return []
    ev_id = _leg_event_id(leg_id)
    riders = ride_members_for_event(ev, ev_id, sched)
    driver, _d = _driver_member(leg_id, sched)
    driver_mid = (driver or {}).get('id')
    out = [m for m in riders if m.get('id') != driver_mid]
    if any(m.get('role') == 'child' for m in riders):
        seen = {m.get('id') for m in out}
        for m in storage.get_all_members():
            if m.get('role') == 'parent' and not m.get('system') \
                    and m.get('id') != driver_mid and m.get('id') not in seen:
                out.append(m)
    return out


def send_quick_message(leg_id: str, key: str, sender_member: dict) -> dict:
    """One canned line, into each recipient's DM with the driver.

    A DM rather than a bare push on purpose: the push is how they hear it,
    the message is how they can look at it again thirty seconds later while
    they are pulling their shoes on. The chat fan-out sends the push, so
    there is no second notification to send from here."""
    spec = next((m for m in MESSAGES if m['key'] == key), None)
    if not spec:
        return {'status': 'error', 'message': f"Unknown message '{key}'"}
    if not (sender_member or {}).get('id'):
        return {'status': 'error', 'message': 'No sender for this message.'}
    sched = storage.get_cached_schedule() or {}
    events = {str(e.get('id')): e for e in (sched.get('events') or [])}
    _ev, title = _event_for_leg(leg_id, events)
    if str(leg_id).startswith('final_'):
        title = 'home'
    body = spec['body'].format(who=sender_member.get('name') or 'Your driver',
                               title=title or 'your ride')
    audience = _message_audience(leg_id, sched)
    if not audience:
        return {'status': 'error', 'message': 'Nobody to tell about this drive.'}
    # Family-network S12: the message carries its drive as CONTEXT — the DM
    # is the durable container, the chip over this run of messages is the
    # drive. Label denormalised at send time (a chip is display; the ids are
    # the truth).
    ctx_label = title or 'this drive'
    try:
        st = (_ev or {}).get('start')
        if st:
            clock = datetime.datetime.fromisoformat(st).strftime('%I:%M %p').lstrip('0')
            ctx_label = f"{ctx_label} · {clock}"
    except (ValueError, TypeError):
        pass
    context = {'kind': 'drive',
               'event_id': str((_ev or {}).get('id') or leg_id),
               'leg_id': str(leg_id), 'label': ctx_label}
    from services.agent_tools_v2 import _post_chat_message
    sent = []
    for m in audience:
        try:
            dm = storage.get_or_create_dm(sender_member['id'], m['id'])
            _post_chat_message(dm, sender_member, body, context=context)
            sent.append(m.get('name'))
        except Exception as e:
            print(f"drive sheet message to {m.get('id')} failed: {e}")
    if not sent:
        return {'status': 'error', 'message': 'Message could not be sent.'}
    return {'status': 'ok', 'body': body, 'sent_to': sent}


def record_ping(member_id: str, leg_id: str, lat, lng, accuracy=None,
                now_ts: float = None) -> dict:
    """A position from the driving phone: stored, then used immediately to
    ask whether this leg is finished.

    Deliberately the PASSIVE arrival test rather than the tap check — the tap
    check prices a fresh ETA through the Directions API, which is a perfectly
    good thing to do on a human's tap and a bill to pay every forty-five
    seconds. A ping either completes the leg or says nothing."""
    now_ts = now_ts if now_ts is not None else datetime.datetime.now().timestamp()
    if member_id and lat is not None and lng is not None:
        storage.set_member_position(member_id, lat, lng, accuracy, now_ts)
    if not leg_id:
        return {'status': 'ok', 'completed': False}
    done = drive_arrival.check_leg_at(leg_id, lat, lng, accuracy, now_ts)
    return {'status': 'ok', 'completed': bool(done), 'arrival': done or None}
