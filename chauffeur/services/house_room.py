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


def _mudroom() -> dict:
    """Backpacks on the bench: one per active child. Honest decor data —
    attention stays the DOOR zone's business, so the mudroom itself is
    always calm."""
    bags = len([m for m in storage.get_all_members() or []
                if (m.get('role') or '') == 'child'])
    return {'calm': True, 'bags': bags}


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
