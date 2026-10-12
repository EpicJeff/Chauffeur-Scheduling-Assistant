"""Registry-validated metadata; older HA can map a device to a satellite entity."""
import json
import time
import uuid


async def metadata(hass, user_input, mapping=None):
    from homeassistant.helpers import device_registry, entity_registry, instance_id
    devices = device_registry.async_get(hass)
    entities = entity_registry.async_get(hass)
    device = getattr(user_input, 'device_id', None)
    satellite = getattr(user_input, 'satellite_id', None)
    try:
        aliases = json.loads(mapping) if isinstance(mapping, str) else (mapping or {})
    except (ValueError, TypeError):
        aliases = {}
    if not satellite and isinstance(aliases, dict):
        satellite = aliases.get(device)
    entry = entities.async_get(satellite) if satellite else None
    if not entry or not isinstance(satellite, str) or not satellite.startswith('assist_satellite.') or (device and entry.device_id != device):
        satellite = None
    if entry and satellite and not device:
        device = entry.device_id
    device_entry = devices.async_get(device) if device else None
    if device and device_entry is None:
        device = None
        satellite = None
    return {'ha_instance_id': await instance_id.async_get(hass), 'satellite_id': satellite,
            'device_id': device, 'request_id': uuid.uuid4().hex, 'observed_at': time.time(),
            'label': (getattr(entry, 'name', None) or getattr(device_entry, 'name_by_user', None)
                      or getattr(device_entry, 'name', None) or getattr(entry, 'original_name', None)) if satellite else None}
