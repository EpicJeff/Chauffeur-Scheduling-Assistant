"""The Home ROOM — the dollhouse the panel lives in.

Spec: docs/superpowers/specs/2026-09-08-house-design.md. The kitchen room
scaled to the whole house. H1 delegated the kitchen's eight sections
verbatim; H2 adds the garage (the family's real cars: shape, presence,
charge/fuel warnings) and the curb (the school bus, while it is actually
out). All kitchen laws inherited and pinned by tests/test_house_state.py:
reads only, per-section calm, family-safe by construction.

Warn thresholds: the cars module's own defaults, overridable by the same
settings keys cars.py reads (car_battery_warn_pct / car_fuel_warn_pct).
"""
import datetime
import logging

from services import kitchen_room, storage

logger = logging.getLogger(__name__)


def _calm(**extra):
    return {'calm': True, **extra}


def _garage() -> dict:
    """The fleet, straight from cars.fleet_status — the same rows the board's
    own cars card draws, so the plaque over a car in the bay and the row for
    it on the lean-in card can never disagree."""
    from services import cars as cars_svc
    out = cars_svc.fleet_status()
    if not out:
        return _calm(cars=[])
    return {'calm': (not any(c['warn'] for c in out)), 'cars': out}


def _curb(now=None) -> dict:
    """Show a bus at the curb only when a school bus is actually nearby."""
    from services import bus, school
    day = (now.date() if isinstance(now, datetime.datetime)
           else datetime.date.today())
    if not school.school_in_session(day):
        return _calm(bus=False)
    near = False
    for m in storage.get_all_members() or []:
        if (m.get('role') or '') != 'child':
            continue
        try:
            if bus.bus_active(m) and bus.bus_is_near(m):
                near = True
                break
        except Exception:
            continue
    if not near:
        return _calm(bus=False)
    return {'calm': False, 'bus': True}


def _packs(now, sched: dict):
    """(packs, due) — one entry per PACKING GROUP on the day in focus: a
    kit's name, how much of it is claimed, and whether it is done. `due` is
    true when some group is still short AND its window is already open.

    A group, not a child: claims are filed against (outing_key, item_key)
    with no member read back, so "Maya's bottle is packed" is not something
    this data can say. "1 of 2 packed" is. The bench draws what the data
    knows and no more.
    """
    from services import family_day, outings, prep_kits
    target = family_day.day_in_focus(now, sched)
    kits, people = storage.get_prep_kits(), prep_kits.passenger_objs()
    claims = {}
    for row in storage.get_packing_claims(target.isoformat()) or []:
        k = (row.get('outing_key'), row.get('item_key'))
        claims[k] = claims.get(k, 0) + 1
    out, due = [], False
    for o in outings.outings_for(target, sched, now):
        # Once the outing is over, an old unclaimed kit is not today's work.
        try:
            ended = datetime.datetime.fromisoformat(o.get('end') or '')
            local_now = now
            if ended.tzinfo is not None and local_now.tzinfo is None:
                local_now = local_now.astimezone()
            elif ended.tzinfo is None and local_now.tzinfo is not None:
                local_now = local_now.astimezone().replace(tzinfo=None)
            if ended <= local_now:
                continue
        except (TypeError, ValueError):
            pass
        # An unpacked bag for next Tuesday is not an alarm; tonight's is.
        # pack_window_opens is the same moment the Family Day card starts
        # wearing its own "N to pack" pill.
        opens, open_now = family_day.pack_window_opens(o.get('start') or ''), False
        if opens:
            try:
                open_now = datetime.datetime.fromisoformat(opens) <= now
            except (TypeError, ValueError):
                open_now = False
        for g in outings.packing_for(o, sched, kits, people):
            needed = packed = 0
            for item in g.get('items') or []:
                n = int(item.get('needed') or 0)
                needed += n
                packed += min(n, claims.get((o.get('key'),
                                             item.get('key')), 0))
            if not needed:
                continue        # a kit with no items is nothing to carry
            ready = packed >= needed
            due = due or (open_now and not ready)
            out.append({'name': str(g.get('kit') or 'Bring'),
                        'packed': packed, 'needed': needed, 'ready': ready,
                        'attention': open_now and not ready})
    return out, due


def _mudroom(now=None) -> dict:
    """The bench: one backpack per packing group for the day in focus, OPEN
    while it is still short and closed once it is done. With no kits to
    match — most households, most days — the fallback is the old honest
    decor: one school bag per active child.

    Attention stays the DOOR zone's business, so the room is calm by
    design. The one honest exception is a pack that is still short with
    its own packing window already open.
    """
    try:
        bags = len([m for m in storage.get_all_members() or []
                    if (m.get('role') or '') == 'child'])
    except Exception:
        bags = 0
    packs, due, known = [], False, True
    try:
        packs, due = _packs(now or datetime.datetime.now(),
                            storage.get_cached_schedule() or {})
    except Exception as e:
        logger.debug(f"[house] mudroom packs fell back to the roster: {e}")
        packs, due = [], False
        known = False
    if packs:
        bags = len(packs)
    return {'calm': (not due), 'bags': bags, 'packs': packs, 'packing_known': known}


def state(since_ts: float = 0, now=None) -> dict:
    from services import house_attention
    out = kitchen_room.state(since_ts=since_ts, now=now)
    out['attention'] = house_attention.state(now)
    for name, build in (('garage', _garage), ('curb', lambda: _curb(now)),
                        ('mudroom', lambda: _mudroom(now))):
        try:
            out[name] = build()
        except Exception as e:
            logger.debug(f"[house] {name} fell to calm: {e}")
            out[name] = _calm()
    return out
