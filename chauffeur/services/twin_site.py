"""The twin's site: cached household geocode only, never a network request."""
import math
import json
from pathlib import Path
import threading

from services import house_map, storage, twin_store

_job_lock = threading.Lock()
_jobs = {}
_results = {}


def start_bearing_job():
    """Schedule once per map cache key; page/state requests never fetch tiles.

    A separate small cache retains attempts beyond the scene cache's 12h TTL.
    Only hashes and bearings are persisted, never addresses or credentials.
    """
    _, _, key = house_map.lookup_context()
    path = Path(storage.DB_PATH).with_name('house_map_bearing.json')
    identity = (str(path),key)
    with _job_lock:
        if key is None:
            twin_store.set_map_bearing(None)
            return
        if identity in _results:
            twin_store.set_map_bearing(_results[identity])
            return
        if identity in _jobs:
            return
        try:
            cached = json.loads(path.read_text(encoding='utf-8'))
            if cached['key'] == key:
                twin_store.set_map_bearing(cached['bearing'])
                _results[identity] = cached['bearing']
                return
        except (OSError,ValueError,KeyError,TypeError):
            pass
        twin_store.set_map_bearing(None)

        def run():
            bearing = None
            try:
                bearing = house_map.neighborhood_layout().get('bearing')
            except Exception:
                pass  # Provider exceptions may contain credentials.
            with _job_lock:
                _results[identity] = bearing
                # A home changed during the fetch must not inherit old north.
                if house_map.lookup_context()[2] == key:
                    twin_store.set_map_bearing(bearing)
                    try:
                        temp = path.with_suffix('.tmp')
                        temp.write_text(json.dumps({'key':key,'bearing':bearing}),encoding='utf-8')
                        temp.replace(path)
                    except OSError:
                        pass

        job = threading.Thread(target=run,name='twin-map-bearing',daemon=True)
        _jobs[identity] = job
        job.start()


def site():
    settings = storage.get_settings()
    lot = twin_store.place().get('lot', {})
    bearing = lot.get('front_bearing_deg', 180)
    bearing_source = 'dial' if 'front_bearing_deg' in lot else 'default'
    mapped = lot.get('map_bearing_deg')
    if type(mapped) not in (int,float) or not math.isfinite(mapped) or not 0 <= mapped < 360:
        mapped = None
    if not lot.get('front_bearing_override') and mapped is not None:
        bearing, bearing_source = mapped, 'map'
    result = {'lat': 40, 'lon': None, 'front_bearing_deg': bearing, 'source': 'default',
              'front_bearing_source': bearing_source, 'timezone': settings.get('timezone') or None}
    if mapped is not None:
        result.update(map_bearing_deg=mapped, map_bearing_source=lot.get('map_bearing_source'))
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
