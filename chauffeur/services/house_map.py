"""Bounded Mapbox street lookup and deterministic dollhouse placement.

Only local scene coordinates leave this service. The existing home geocode and
Mapbox accounting are reused; no routing, imagery or model calls are involved.
"""
import hashlib
import json
import math
from pathlib import Path
import threading
import time

import requests
from services import maps, storage

_lock = threading.Lock()
_TTL = 12 * 3600
_ROADS = {'street', 'street_limited', 'primary', 'secondary', 'tertiary'}


def _cached(path, key):
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if cached['key'] == key and cached['until'] > time.time():
            return cached['layout']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def closest(point, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dz * dz
    t = max(0, min(1, ((point[0]-a[0])*dx + (point[1]-a[1])*dz) / length)) if length else 0
    q = (a[0]+t*dx, a[1]+t*dz)
    return math.dist(point, q), q


def parcel(lot):
    c, s = math.cos(lot['rotation']), math.sin(lot['rotation'])
    return [(lot['x']+x*c+z*s, lot['z']-x*s+z*c)
            for x, z in ((-26,-18),(26,-18),(26,26),(-26,26))]


def parcels_overlap(a, b):
    """Separating-axis check for rotated authored yards, including the home."""
    for polygon in (a, b):
        for p, q in zip(polygon, polygon[1:]+polygon[:1]):
            axis = (p[1]-q[1], q[0]-p[0])
            pa = [x*axis[0]+z*axis[1] for x, z in a]
            pb = [x*axis[0]+z*axis[1] for x, z in b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


def street_crosses_parcel(lot, roads):
    c, s = math.cos(lot['rotation']), math.sin(lot['rotation'])
    for a, b in roads:
        points = [((p[0]-lot['x'])*c-(p[1]-lot['z'])*s,
                   (p[0]-lot['x'])*s+(p[1]-lot['z'])*c) for p in (a, b)]
        lo, hi = 0., 1.
        for axis, bounds in enumerate(((-28.5,28.5),(-20.5,28.5))):
            start, end = points[0][axis], points[1][axis]
            d = end-start
            if abs(d) < 1e-9:
                if not bounds[0] <= start <= bounds[1]:
                    hi = -1
            else:
                t0, t1 = sorted(((bounds[0]-start)/d, (bounds[1]-start)/d))
                lo, hi = max(lo,t0), min(hi,t1)
        if hi >= lo:
            return True
    return False


def compile_layout(lines, buildings=()):
    """Input: east/south meters about home. Preserve street shape and handedness.

    Rotate the closest street to the facade, uniformly scale to the authored
    parcel, then pack non-overlapping synthetic exteriors beside the streets.
    Footprints suggest frontage positions, not house designs or exact parcels.
    """
    segments = [(a, b) for line in lines for a, b in zip(line, line[1:]) if math.dist(a, b) > .1]
    if not segments:
        return None
    distance, q, a, b = min(((*closest((0, 0), a, b), a, b) for a, b in segments), key=lambda v: v[0])
    if distance < 3 or distance > 100:
        return None  # Street/city pins cannot establish which side the home faces.
    normal = (q[0]/distance, q[1]/distance)
    tangent = (normal[1], -normal[0])
    scale = 28.5 / distance
    if not .45 <= scale <= 4:
        return None

    def project(p):
        return [round((p[0]*tangent[0]+p[1]*tangent[1])*scale, 3),
                round((p[0]*normal[0]+p[1]*normal[1])*scale, 3)]

    # Clip each segment, including those with both endpoints outside the scene.
    roads, seen = [], set()
    for a, b in segments:
        a, b = project(a), project(b)
        dx, dz = b[0]-a[0], b[1]-a[1]
        lo, hi = 0., 1.
        for p, v in ((a[0], dx), (a[1], dz)):
            if abs(v) < 1e-9:
                if abs(p) > 265:
                    hi = -1
            else:
                t0, t1 = sorted(((-265-p)/v, (265-p)/v))
                lo, hi = max(lo, t0), min(hi, t1)
        if hi <= lo:
            continue
        ends = [[round(a[0]+dx*t, 2), round(a[1]+dz*t, 2)] for t in (lo, hi)]
        key = tuple(sorted(tuple(p) for p in ends))
        if key not in seen:
            roads.append(ends)
            seen.add(key)
    if not roads or len(roads) > 800:
        return None

    candidates = []
    # Existing buildings help choose frontage along a street. Our 50-unit
    # authored lots still require packing; do not pretend footprints are lots.
    for center in buildings:
        center = project(center)
        d, frontage, a, b = min(((*closest(center, a, b), a, b) for a, b in roads), key=lambda v: v[0])
        if d > 70 or d < 4:
            continue
        nx, nz = (center[0]-frontage[0])/d, (center[1]-frontage[1])/d
        candidates.append((frontage[0]+nx*29, frontage[1]+nz*29, math.atan2(-nx, -nz)))
    # Fill unmapped buildings and the outer ring from frontage, never a grid.
    for a, b in roads:
        length = math.dist(a, b)
        nx, nz = -(b[1]-a[1])/length, (b[0]-a[0])/length
        # A yard is 52 units wide. Rounding UP the count makes candidates
        # narrower than their own collision envelope and drops alternate lots.
        count = max(1, math.floor(length/54))
        for step in range(count):
            t = (step+.5)/count
            for side in (-1, 1):
                candidates.append((a[0]+(b[0]-a[0])*t+nx*29*side,
                                   a[1]+(b[1]-a[1])*t+nz*29*side,
                                   math.atan2(-nx*side, -nz*side)))
    candidates.sort(key=lambda p: (math.hypot(p[0], p[1]), p))
    lots = []
    parcels = [parcel({'x': 0, 'z': 0, 'rotation': 0})]
    for x, z, turn in candidates:
        if max(abs(x), abs(z)) > 230:
            continue
        if min(closest((x, z), a, b)[0] for a, b in roads) < 27:
            continue  # Keep yards and roofs clear of junctions/other streets.
        lot = {'x': round(x, 2), 'z': round(z, 2), 'rotation': turn,
               'detail': 'near' if len(lots) < 8 else 'far'}
        shape = parcel(lot)
        if any(parcels_overlap(shape, p) for p in parcels) or street_crosses_parcel(lot, roads):
            continue
        lots.append(lot)
        parcels.append(shape)
        if len(lots) == 48:
            break
    if not lots:
        return None
    return {'source': 'mapbox', 'roads': roads, 'lots': lots}


def _fetch(lat, lon, token):
    import mapbox_vector_tile
    # At most four tiles, at a latitude-adjusted zoom; roads remain detailed.
    zoom = min(15, max(8, int(math.log2(40075016.686*math.cos(math.radians(lat))/1200))))
    n = 2**zoom
    cx = (lon+180)/360*n
    cy = (1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
    meters = 40075016.686*math.cos(math.radians(lat))/n
    radius = 500/meters
    lines, buildings = [], []
    for tx in range(math.floor(cx-radius), math.floor(cx+radius)+1):
        for ty in range(math.floor(cy-radius), math.floor(cy+radius)+1):
            if not maps.check_usage_limits_and_spikes('vector_tiles', 1):
                raise ValueError('Map allowance reached')
            with requests.get(f'https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/{zoom}/{tx % n}/{ty}.mvt',
                              params={'access_token': token}, timeout=(3, 5)) as response:
                response.raise_for_status()
                if len(response.content) > 4_000_000:
                    raise ValueError('Tile too large')
                tile = mapbox_vector_tile.decode(response.content, default_options={'y_coord_down': True})
            for name in ('road', 'building'):
                layer = tile.get(name, {})
                extent = layer.get('extent', 4096)
                def local(p):
                    return ((tx+p[0]/extent-cx)*meters, (ty+p[1]/extent-cy)*meters)
                for feature in layer.get('features', []):
                    props, geo = feature.get('properties', {}), feature['geometry']
                    if name == 'road':
                        if props.get('class') not in _ROADS or props.get('structure') in ('bridge', 'tunnel'):
                            continue
                        parts = [geo['coordinates']] if geo['type'] == 'LineString' else geo['coordinates'] if geo['type'] == 'MultiLineString' else []
                        lines.extend([[local(p) for p in part] for part in parts])
                    elif geo['type'] == 'Polygon' and geo['coordinates']:
                        ring = geo['coordinates'][0][:-1]
                        if ring:
                            buildings.append(local((sum(p[0] for p in ring)/len(ring), sum(p[1] for p in ring)/len(ring))))
    return compile_layout(lines, buildings)


def neighborhood_layout(cached_only=False):
    """One lookup per home/12h, failure cooldown 1h, serialized across clients.

    A local hashed key invalidates on home/key changes. Cache contains only
    projected geometry, never the address, token or geographic coordinates.
    """
    home, token = maps.get_home_location(), maps.get_mapbox_api_key()
    if not home or not token or maps.get_map_option('disable_mapbox', False):
        return {'source': 'generated'}
    key = hashlib.sha256((home+'|'+token+'|2').encode()).hexdigest()
    path = Path(storage.DB_PATH).with_name('house_map.json')
    cached = _cached(path, key)
    if cached is not None or cached_only:
        return cached or {'source': 'generated'}
    with _lock:
        cached = _cached(path, key)
        if cached is not None:
            return cached
        layout = {'source': 'generated'}
        try:
            coords = maps.geocode_address(home)
            cached = storage.get_cached_geocode(maps.extract_street_address(home))
            if coords and cached and cached.get('precision', 'exact') == 'exact':
                lat, lon = coords
                if math.isfinite(lat) and math.isfinite(lon) and abs(lat) < 80 and abs(lon) <= 180:
                    layout = _fetch(lat, lon, token) or layout
        except Exception:
            # Do not log provider exceptions: request URLs contain credentials.
            pass
        try:
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'key': key, 'until': time.time()+(_TTL if layout['source'] == 'mapbox' else 3600), 'layout': layout}), encoding='utf-8')
            temp.replace(path)
        except OSError:
            pass
        return layout
