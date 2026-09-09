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


def _warn_floats():
    from services import cars as cars_svc
    b, f = cars_svc.DEFAULT_BATTERY_WARN_PCT, cars_svc.DEFAULT_FUEL_WARN_PCT
    try:
        s = storage.get_settings() or {}
        b = float(s.get('car_battery_warn_pct') or b)
        f = float(s.get('car_fuel_warn_pct') or f)
    except Exception:
        pass
    return b, f


def _garage() -> dict:
    from services import cars as cars_svc
    batt_warn, fuel_warn = _warn_floats()
    out = []
    any_warn = False
    for c in storage.get_all_cars() or []:
        if c.get('is_disabled'):
            continue
        try:
            lv = cars_svc.car_levels(c) or {}
        except Exception:
            lv = {}
        try:
            loc = cars_svc.car_location(c)
        except Exception:
            loc = None
        present = (loc is None) or (str(loc.get('state') or 'home') == 'home')
        warn = False
        if lv.get('battery_pct') is not None and lv['battery_pct'] < batt_warn:
            warn = True
        if lv.get('fuel_pct') is not None and lv['fuel_pct'] < fuel_warn:
            warn = True
        any_warn = any_warn or warn
        out.append({'id': c.get('id') or str(c.get('doc_id') or ''),
                    'name': c.get('name') or 'Car',
                    'color': c.get('color_code') or '',
                    'body': c.get('body_type') or '',
                    'seats': int(c.get('seat_capacity') or 4),
                    'present': present,
                    'battery_pct': lv.get('battery_pct'),
                    'fuel_pct': lv.get('fuel_pct'),
                    'range': lv.get('range'),
                    'warn': warn})
    if not out:
        return _calm(cars=[])
    return {'calm': (not any_warn), 'cars': out}


def _curb() -> dict:
    from services import bus
    near = False
    for m in storage.get_all_members() or []:
        try:
            if bus.bus_active(m):
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
                        'packed': packed, 'needed': needed, 'ready': ready})
    return out, due


def _mudroom() -> dict:
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
    packs, due = [], False
    try:
        packs, due = _packs(datetime.datetime.now(),
                            storage.get_cached_schedule() or {})
    except Exception as e:
        logger.debug(f"[house] mudroom packs fell back to the roster: {e}")
        packs, due = [], False
    if packs:
        bags = len(packs)
    return {'calm': (not due), 'bags': bags, 'packs': packs}


def state(since_ts: float = 0, now=None) -> dict:
    out = kitchen_room.state(since_ts=since_ts, now=now)
    for name, build in (('garage', _garage), ('curb', _curb),
                        ('mudroom', _mudroom)):
        try:
            out[name] = build()
        except Exception as e:
            logger.debug(f"[house] {name} fell to calm: {e}")
            out[name] = _calm()
    return out
