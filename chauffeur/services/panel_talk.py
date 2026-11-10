"""A wall panel's room and voice satellite, discovered through Home Assistant."""
from services import announce, ha_api, storage, voice_identity


def _known_satellites(states: dict) -> dict:
    """Configured satellites remain known when HA has no state row for them."""
    known = {s['satellite_id']: s.get('label') or s['satellite_id']
             for s in voice_identity.configuration().get('satellites', [])
             if (s.get('satellite_id') or '').startswith('assist_satellite.')}
    for eid, state in states.items():
        if eid and eid.startswith('assist_satellite.'):
            known[eid] = (state.get('attributes') or {}).get('friendly_name') or known.get(eid) or eid
    return {eid: name for eid, name in known.items()
            if eid not in states or announce._usable(states, eid)}


def satellite_for_panel(device: dict | None) -> str | None:
    """Usable override, satellite announce pin, then the first room satellite.

    An unavailable HA installation or a failed HA read leaves the panel silent.
    """
    try:
        if not device or not ha_api.is_available():
            return None
        states = announce._states_by_id()
        override = device.get('satellite_id')
        if override and override in _known_satellites(states):
            return override
        area_id = device.get('area_id')
        if not area_id:
            return None
        pinned = ((storage.get_settings() or {}).get('announce_targets') or {}).get(area_id)
        if pinned and pinned.startswith('assist_satellite.') and announce._usable(states, pinned):
            return pinned
        area = next((a for a in ha_api.get_area_map() if a.get('id') == area_id), {})
        satellites = sorted(e for e in area.get('entities', [])
                            if e.startswith('assist_satellite.') and announce._usable(states, e))
        return satellites[0] if satellites else None
    except Exception:
        return None


def rooms() -> dict:
    """Picker rows; HA absence or failure is an empty, usable response."""
    empty = {'areas': [], 'satellites': []}
    try:
        if not ha_api.is_available():
            return empty
        areas = ha_api.get_area_map()
        states = announce._states_by_id()
        area_by_entity = {e: a['id'] for a in areas for e in a.get('entities', [])}
        known = _known_satellites(states)
        return {
            'areas': [{'id': a['id'], 'name': a['name']} for a in areas],
            'satellites': [{'id': eid, 'name': known[eid], 'area_id': area_by_entity.get(eid)}
                           for eid in sorted(known)],
        }
    except Exception:
        return empty
