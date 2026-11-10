"""A wall panel's room and voice satellite, discovered through Home Assistant."""
import logging
import threading
import time

from services import announce, ha_api, storage, voice_identity

DEFAULT_GREETING = 'How can I help?'

_last_start: dict[str, float] = {}
_start_lock = threading.Lock()


def status(device: dict | None) -> dict:
    """Availability and the satellite's own state, never a fabricated state."""
    if not device or not device.get('area_id'):
        return {'available': False, 'state': None}
    try:
        satellite = satellite_for_panel(device)
        state = (ha_api.get_state_fresh(satellite) or {}).get('state') if satellite else None
        return {'available': state not in (None, 'unavailable', 'unknown'), 'state': state}
    except Exception:
        return {'available': False, 'state': None}


def _offline_message(device: dict) -> str:
    try:
        area = next((a for a in ha_api.get_area_map()
                     if a.get('id') == device.get('area_id')), {})
        name = area.get('name') or 'room'
    except Exception:
        name = 'room'
    return f'The {name} speaker is offline.'


def start(device: dict | None) -> tuple[int, dict]:
    """Start one ordinary HA conversation; the panel supplies no person identity."""
    if not device:
        return 403, {'message': 'Only a paired wall panel can start a conversation.'}
    if not device.get('area_id'):
        return 409, {'message': 'No voice satellite is available for this panel.'}
    try:
        if not ha_api.is_available():
            return 409, {'message': 'Home Assistant is not available.'}
        satellite = satellite_for_panel(device, ha_available=True)
        if not satellite:
            # The resolver excludes unavailable entities. Distinguish an offline
            # room speaker from a room that has no satellite configured at all.
            areas = ha_api.get_area_map()
            area = next((a for a in areas if a.get('id') == device.get('area_id')), {})
            pinned = ((storage.get_settings() or {}).get('announce_targets') or {}).get(device.get('area_id'))
            candidates = [device.get('satellite_id'), pinned, *area.get('entities', [])]
            for entity in candidates:
                if entity and entity.startswith('assist_satellite.'):
                    state = (ha_api.get_state_fresh(entity) or {}).get('state')
                    if state in (None, 'unavailable', 'unknown'):
                        return 502, {'message': _offline_message(device)}
            return 409, {'message': 'No voice satellite is available for this panel.'}
        state = (ha_api.get_state_fresh(satellite) or {}).get('state')
        if state in (None, 'unavailable', 'unknown'):
            return 502, {'message': _offline_message(device)}
        if state in ('listening', 'processing', 'responding'):
            return 409, {'message': 'The room speaker is already in a conversation.'}
        with _start_lock:
            device_id = device['device_id']
            previous = _last_start.get(device_id)
            stamp = time.time()
            if previous is not None and stamp - previous < 5:
                return 429, {'message': 'Please wait a moment before trying again.'}
            _last_start[device_id] = stamp
        started = False
        try:
            greeting = (storage.get_settings().get('panel_talk_greeting') or '').strip()[:200]
            result = ha_api.call_service('assist_satellite', 'start_conversation',
                                         {'entity_id': satellite, 'preannounce': True,
                                          'start_message': greeting or DEFAULT_GREETING}, timeout=15)
            started = result is not None
        finally:
            if not started:
                with _start_lock:
                    if _last_start.get(device_id) == stamp:
                        if previous is None:
                            _last_start.pop(device_id, None)
                        else:
                            _last_start[device_id] = previous
        if result is None:
            return 502, {'message': _offline_message(device)}
        return 200, {'ok': True}
    except Exception:
        logging.exception('Could not start a panel conversation')
        return 502, {'message': _offline_message(device)}


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


def satellite_for_panel(device: dict | None, *, ha_available: bool | None = None) -> str | None:
    """Usable override, satellite announce pin, then the first room satellite.

    An unavailable HA installation or a failed HA read leaves the panel silent.
    """
    try:
        if not device or not (ha_api.is_available() if ha_available is None else ha_available):
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
