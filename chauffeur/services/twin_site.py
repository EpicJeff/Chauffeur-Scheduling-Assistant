"""The twin's site: cached household geocode only, never a network request."""
import math

from services import storage, twin_store


def site():
    settings = storage.get_settings()
    bearing = twin_store.place().get('lot', {}).get('front_bearing_deg', 180)
    result = {'lat': 40, 'lon': None, 'front_bearing_deg': bearing, 'source': 'default',
              'timezone': settings.get('timezone') or None}
    # Longitude stays null until the browser supplies its UTC offset. Sending a
    # server offset would put an unconfigured household at the add-on's location.
    address = settings.get('home_location')
    if not isinstance(address, str) or not address.strip():
        return result
    try:
        cached = storage.get_cached_geocode(address)
        lat, lon = float(cached['lat']), float(cached['lon'])
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            result.update(lat=lat, lon=lon, source='home_location')
    except (KeyError, TypeError, ValueError, OSError, RuntimeError):
        pass
    return result
