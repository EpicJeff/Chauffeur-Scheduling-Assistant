"""Bounded Mapbox street lookup and deterministic dollhouse placement.

Only local scene coordinates leave this service. The existing home geocode and
Mapbox accounting are reused; no routing, imagery or model calls are involved.
"""
import hashlib
import json
import math
from statistics import median
from pathlib import Path
import threading
import time

import requests
from services import maps, storage

_lock = threading.Lock()
_TTL = 12 * 3600
_ROADS = {'street', 'street_limited', 'primary', 'secondary', 'tertiary'}
_HOUSE_TYPES = {'building', 'house', 'detached', 'residential', 'bungalow', 'terrace', 'semidetached_house', 'cabin', ''}


def footprint_lots(buildings, project, roads, home=None, diagnostics=None):
    """Keep mapped centers; fit a street-facing oriented box to each outline.

    Building outlines describe walls, not yards. They must never be rejected
    because the illustrative model's garden is larger than its building.
    """
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    stats = diagnostics if diagnostics is not None else {}
    def skipped(reason):
        stats[reason] = stats.get(reason,0)+1
    grouped = {}
    for i, item in enumerate(buildings):
        if not isinstance(item, dict) or item.get('type', 'building') not in _HOUSE_TYPES:
            skipped('nonResidentialOrLegacy')
            continue
        try:
            polygon = Polygon(item['outline']).buffer(0)
            if polygon.is_empty:
                skipped('invalidOutline')
                continue
            grouped.setdefault(str(item.get('id') or f'unknown-{i}'), []).append(polygon)
        except (KeyError, TypeError, ValueError):
            skipped('invalidOutline')
            continue
    possible = []
    for pieces in grouped.values():
        merged = unary_union(pieces)
        for poly in ([merged] if merged.geom_type == 'Polygon' else getattr(merged, 'geoms', [])):
            if poly.geom_type != 'Polygon' or not 30 <= poly.area <= 1200:
                skipped('areaOrGeometry')
                continue
            at = project((poly.centroid.x,poly.centroid.y))
            if max(abs(at[0]),abs(at[1])) > 260:
                skipped('outsideScene')
                continue
            possible.append(poly)
    # Restrict duplicate checks to intersecting bounds, not every building in
    # nine city tiles. Stable source order makes repeated builds deterministic.
    tree = STRtree(possible)
    kept = set()
    outlines = []
    for i,poly in enumerate(possible):
        if any(j in kept and poly.intersection(possible[j]).area > .7*min(poly.area,possible[j].area)
               for j in tree.query(poly)):
            skipped('duplicate')
            continue
        kept.add(i)
        outlines.append(poly)
    lots = []
    for poly in outlines:
        polygon = Polygon([project(p) for p in poly.exterior.coords])
        is_home = polygon.covers(Point(0,0)) or polygon.distance(Point(0,0)) < 2
        rectangle = polygon.minimum_rotated_rectangle
        points = list(rectangle.exterior.coords)[:-1]
        center = rectangle.centroid
        if max(abs(center.x),abs(center.y)) > 230:
            skipped('outsideScene')
            continue
        _, frontage = min((closest((center.x,center.y),a,b) for a,b in roads),key=lambda p:p[0])
        dx, dz = frontage[0]-center.x, frontage[1]-center.y
        a,b = points[:2]
        base = -math.atan2(b[1]-a[1],b[0]-a[0])
        turn = max((base+i*math.pi/2 for i in range(4)),key=lambda r:math.sin(r)*dx+math.cos(r)*dz)
        c,s = math.cos(turn),math.sin(turn)
        u = [p[0]*c-p[1]*s for p in points]
        v = [p[0]*s+p[1]*c for p in points]
        lot = {'x':round(center.x,3),'z':round(center.y,3),'rotation':turn,'scale':1,
                     'footprint':{'width':round(max(u)-min(u),3),'depth':round(max(v)-min(v),3),
                                  'outline':[[round(x,3),round(z,3)] for x,z in polygon.exterior.coords]}}
        if is_home:
            skipped('primaryHome')
            if home is not None:
                home.append(lot)
        else:
            lots.append(lot)
    return lots


def _cached(path, key):
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if cached['key'] == key and cached['until'] > time.time():
            return cached['layout']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def address_lots(addresses, buildings, project, roads, mapped, home, excluded=()):
    """Fill a missing outline only where a map house-number point exists.

    Size is an estimate from nearby real houses, never a measured footprint.
    All source buildings reserve space, including nonresidential buildings.
    """
    from shapely.geometry import Polygon, Point, LineString
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    occupied = list(excluded)
    for item in buildings:
        if not isinstance(item,dict):
            continue
        try:
            poly = Polygon([project(p) for p in item['outline']]).buffer(0)
            if not poly.is_empty:
                occupied.append(poly)
        except (KeyError,TypeError,ValueError):
            continue
    street = unary_union([LineString([a,b]).buffer(2.5) for a,b in roads])
    tree = STRtree(occupied)
    estimates = []
    samples = mapped+home
    result = []
    points = sorted(set(tuple(project(p)) for p in addresses),key=lambda p:(math.hypot(*p),p))
    for x,z in points:
        if max(abs(x),abs(z))>230:
            continue
        point = Point(x,z)
        if len(tree.query(point.buffer(2),predicate='intersects')) or any(p.distance(point)<2 for p in estimates):
            continue
        donors = sorted((p for p in samples if math.hypot(p['x']-x,p['z']-z)<80),
                        key=lambda p:math.hypot(p['x']-x,p['z']-z))[:5]
        if not donors:
            continue  # No local residential size evidence.
        width = median(p['footprint']['width'] for p in donors)
        depth = median(p['footprint']['depth'] for p in donors)
        distance,front = min((closest((x,z),a,b) for a,b in roads),key=lambda p:p[0])
        if not 4<=distance<=70:
            continue
        turn = math.atan2(front[0]-x,front[1]-z)
        c,s = math.cos(turn),math.sin(turn)
        for size in (1,.85,.7):
            w,d = width*size,depth*size
            outline = [(x+u*c+v*s,z-u*s+v*c) for u,v in ((-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2))]
            polygon = Polygon(outline)
            if polygon.intersects(street) or len(tree.query(polygon,predicate='intersects')) or any(polygon.intersects(p) for p in estimates):
                continue
            estimates.append(polygon)
            result.append({'x':x,'z':z,'rotation':turn,'scale':1,'placementSource':'house-number',
                           'footprint':{'width':round(w,3),'depth':round(d,3),'estimated':True,
                                        'outline':[[round(a,3),round(b,3)] for a,b in outline+[outline[0]]]}})
            break
    return result


def closest(point, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dz * dz
    t = max(0, min(1, ((point[0]-a[0])*dx + (point[1]-a[1])*dz) / length)) if length else 0
    q = (a[0]+t*dx, a[1]+t*dz)
    return math.dist(point, q), q


def parcel(lot):
    size = lot.get('scale', 1)
    c, s = math.cos(lot['rotation'])*size, math.sin(lot['rotation'])*size
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
        size = lot.get('scale', 1)
        # Scale the yard, but retain the street's full asphalt half-width.
        for axis, bounds in enumerate(((-26*size-2.5,26*size+2.5),(-18*size-2.5,26*size+2.5))):
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


def terrain_shapes(features, project):
    """Merge tile seams and clip mapped land cover, retaining polygon holes."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    grouped = {}
    for feature in features:
        try:
            rings = [[project(p) for p in ring] for ring in feature['rings']]
            poly = Polygon(rings[0],rings[1:]).buffer(0).intersection(box(-265,-265,265,265))
            if not poly.is_empty:
                grouped.setdefault(feature['kind'],[]).append(poly)
        except (KeyError,TypeError,ValueError):
            continue
    result = []
    budget = 20000
    for kind in ('grass','crop','snow','park','scrub','wood','water'):
        if kind not in grouped:
            continue
        merged = unary_union(grouped[kind]).simplify(.35,preserve_topology=True)
        polys = [merged] if merged.geom_type=='Polygon' else getattr(merged,'geoms',[])
        for poly in sorted((p for p in polys if p.geom_type=='Polygon'),key=lambda p:-p.area):
            rings = [list(poly.exterior.coords)]+[list(r.coords) for r in poly.interiors]
            count = sum(map(len,rings))
            if poly.area<2 or count>budget or len(result)>=128:
                continue
            budget -= count
            result.append({'kind':kind,'rings':[[[round(x,3),round(z,3)] for x,z in r] for r in rings]})
    return result


def compile_layout(lines, buildings=(), coverage=(), addresses=(), terrain=()):
    """Input: east/south meters about home. Preserve street shape and handedness.

    Rotate the closest street to the facade and preserve mapped wall outlines.
    Fit illustrative houses to those outlines; pack synthetic yards only where
    footprint coverage is unavailable. Building outlines are not parcel lines.
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

    from shapely.geometry import Point, Polygon
    land = terrain_shapes(terrain,project)
    water = [Polygon(f['rings'][0],f['rings'][1:]) for f in land if f['kind']=='water']
    home, diagnostics = [], {}
    mapped = footprint_lots(buildings,project,roads,home,diagnostics)
    footprint_count = len(mapped)
    address_fill = address_lots(addresses,buildings,project,roads,mapped,home,water) if addresses else []
    mapped.extend(address_fill)
    footprint_mode = any(isinstance(b,dict) and b.get('outline') for b in buildings)
    mapped_coverage = [Polygon([project(p) for p in ring]) for ring in coverage]
    candidates = []
    # Existing buildings help choose frontage along a street. Our 50-unit
    # authored lots still require packing; do not pretend footprints are lots.
    for center in buildings:
        if isinstance(center,dict):
            continue
        center = project(center)
        d, frontage, a, b = min(((*closest(center, a, b), a, b) for a, b in roads), key=lambda v: v[0])
        if d > 70 or d < 4:
            continue
        nx, nz = (center[0]-frontage[0])/d, (center[1]-frontage[1])/d
        candidates.append((frontage[0]+nx*29, frontage[1]+nz*29, math.atan2(-nx, -nz), 0))
    # Fill unmapped buildings and the outer ring from frontage, never a grid.
    for a, b in roads:
        length = math.dist(a, b)
        nx, nz = -(b[1]-a[1])/length, (b[0]-a[0])/length
        # These are search positions, not prescribed lot centers. Sparse
        # midpoints miss usable frontage beside the home and at junctions.
        count = max(1, math.ceil(length/2))
        for step in range(count):
            t = (step+.5)/count
            for side in (-1, 1):
                candidates.append((a[0]+(b[0]-a[0])*t+nx*29*side,
                                   a[1]+(b[1]-a[1])*t+nz*29*side,
                                   math.atan2(-nx*side, -nz*side), 1))
    candidates.sort(key=lambda p: (p[3], math.hypot(p[0], p[1]), p))
    mapped.sort(key=lambda p:(math.hypot(p['x'],p['z']),p['x'],p['z']))
    lots = mapped[:128]
    parcels = [parcel({'x': 0, 'z': 0, 'rotation': 0})]
    parcels.extend(lot['footprint']['outline'][:-1] for lot in lots)
    # Preserve mapped frontages before adding illustrative fill. Prefer full
    # size, then fill remaining usable gaps with modestly smaller exteriors.
    # The active home's size and every street coordinate remain unchanged.
    for priority in (0, 1):
        for size in (1, .85, .7):
            for bx, bz, turn, source in candidates:
                if len(lots) >= (128 if footprint_mode else 48):
                    break
                if source != priority:
                    continue
                setback = 26*size+3
                x = bx+(29-setback)*math.sin(turn)
                z = bz+(29-setback)*math.cos(turn)
                if max(abs(x), abs(z)) > 230:
                    continue
                if footprint_mode and (not mapped_coverage or any(p.covers(Point(x,z)) for p in mapped_coverage)):
                    continue  # Do not invent houses in mapped parks/empty lots.
                lot = {'x': round(x, 2), 'z': round(z, 2), 'rotation': turn, 'scale': size}
                shape = parcel(lot)
                if any(Polygon(shape).intersects(p) for p in water):
                    continue
                if any(parcels_overlap(shape, p) for p in parcels) or street_crosses_parcel(lot, roads):
                    continue
                lots.append(lot)
                parcels.append(shape)
            if len(lots) >= (128 if footprint_mode else 48):
                break
        if len(lots) >= (128 if footprint_mode else 48):
            break
    lots.sort(key=lambda p: (math.hypot(p['x'], p['z']), p['x'], p['z']))
    for i, lot in enumerate(lots):
        lot['detail'] = 'near' if i < 8 else 'far'
    if not lots and not footprint_mode:
        return None
    return {'source': 'mapbox', 'roads': roads, 'lots': lots,
            'terrain':land,
            'home': min(home,key=lambda p:math.hypot(p['x'],p['z'])) if home else None,
            'buildingDiagnostics':dict(diagnostics,emitted=len(mapped[:128]),overLimit=max(0,len(mapped)-128)),
            'placement': 'footprints' if footprint_mode else 'frontage',
            'footprintCount':footprint_count,'addressCount':len(address_fill),
            'footprintCoverage':[[list(p) for p in shape.exterior.coords] for shape in mapped_coverage]}


def _fetch(lat, lon, token):
    import mapbox_vector_tile
    # Up to four road tiles plus nine building tiles; seventeen requests maximum including four land-cover tiles.
    zoom = min(15, max(8, int(math.log2(40075016.686*math.cos(math.radians(lat))/1200))))
    n = 2**zoom
    cx = (lon+180)/360*n
    cy = (1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
    meters = 40075016.686*math.cos(math.radians(lat))/n
    radius = 500/meters
    lines, buildings, coverage, addresses, terrain = [], [], [], [], []

    def tile_at(z, x, y, tileset='mapbox.mapbox-streets-v8'):
        if not maps.check_usage_limits_and_spikes('vector_tiles', 1):
            raise ValueError('Map allowance reached')
        with requests.get(f'https://api.mapbox.com/v4/{tileset}/{z}/{x % (2**z)}/{y}.mvt',
                          params={'access_token': token}, timeout=(3, 5)) as response:
            response.raise_for_status()
            if len(response.content) > 4_000_000:
                raise ValueError('Tile too large')
            return mapbox_vector_tile.decode(response.content, default_options={'y_coord_down': True})

    def collect_land(tile,names,tx,ty,factor=1):
        for name in names:
            land = tile.get(name,{})
            land_extent = land.get('extent',4096)
            for feature in land.get('features',[]):
                kind = 'water' if name=='water' else feature.get('properties',{}).get('class')
                if kind not in ('water','wood','grass','park','scrub','crop','snow'):
                    continue
                geo = feature.get('geometry',{})
                polygons = [geo['coordinates']] if geo.get('type')=='Polygon' else geo.get('coordinates',[]) if geo.get('type')=='MultiPolygon' else []
                for polygon in polygons:
                        terrain.append({'kind':kind,'rings':[[(((tx+p[0]/land_extent)*factor-cx)*meters,((ty+p[1]/land_extent)*factor-cy)*meters) for p in ring] for ring in polygon]})

    for tx in range(math.floor(cx-radius), math.floor(cx+radius)+1):
        for ty in range(math.floor(cy-radius), math.floor(cy+radius)+1):
            tile = tile_at(zoom,tx,ty)
            layer = tile.get('road',{})
            collect_land(tile,('landuse','water'),tx,ty)
            extent = layer.get('extent',4096)
            for feature in layer.get('features',[]):
                props, geo = feature.get('properties',{}), feature['geometry']
                if props.get('class') not in _ROADS or props.get('structure') in ('bridge','tunnel'):
                    continue
                parts = [geo['coordinates']] if geo['type']=='LineString' else geo['coordinates'] if geo['type']=='MultiLineString' else []
                lines.extend([[( (tx+p[0]/extent-cx)*meters, (ty+p[1]/extent-cy)*meters) for p in part] for part in parts])

    # Small houses are filtered out below z16. Fetch the home tile and its
    # eight neighbors at z16, keeping the entire wall outlines and tile coverage.
    # Source: Mapbox Streets v8 building layer (all buildings at z16 and up).
    ratio = 2**(16-zoom)
    hx, hy, hm = cx*ratio, cy*ratio, meters/ratio
    tiles = [(math.floor(hx)+dx,math.floor(hy)+dy) for dx in (-1,0,1) for dy in (-1,0,1)]
    tiles.sort(key=lambda t:(t[0]+.5-hx)**2+(t[1]+.5-hy)**2)
    for tx,ty in tiles:
        try:
            tile = tile_at(16,tx,ty)
            layer = tile.get('building',{})
        except Exception:
            break  # Preserve roads and successful tiles; no retry storm.
        collect_land(tile,('landuse','water'),tx,ty,1/ratio)
        extent = layer.get('extent',4096)
        def local(p):
            return ((tx+p[0]/extent-hx)*hm,(ty+p[1]/extent-hy)*hm)
        coverage.append([local(p) for p in ((0,0),(extent,0),(extent,extent),(0,extent))])
        labels = tile.get('housenum_label',{})
        label_extent = labels.get('extent',4096)
        for feature in labels.get('features',[]):
            geo = feature.get('geometry',{})
            if geo.get('type')=='Point' and feature.get('properties',{}).get('house_num'):
                p = geo['coordinates']
                addresses.append(((tx+p[0]/label_extent-hx)*hm,(ty+p[1]/label_extent-hy)*hm))
        for feature in layer.get('features',[]):
            props, geo = feature.get('properties',{}), feature['geometry']
            if props.get('type') == 'building:part':
                continue
            polygons = [geo['coordinates']] if geo['type']=='Polygon' else geo['coordinates'] if geo['type']=='MultiPolygon' else []
            for polygon in polygons:
                if polygon and len(polygon[0])>=4:
                    buildings.append({'id':feature.get('id'), 'type':props.get('type','building'),
                                      'outline':[local(p) for p in polygon[0]]})
    land_zoom = min(zoom,14)
    factor = 2**(zoom-land_zoom)
    land_tiles = sorted({(x//factor,y//factor) for x in range(math.floor(cx-radius),math.floor(cx+radius)+1)
                        for y in range(math.floor(cy-radius),math.floor(cy+radius)+1)})
    land_count = 0
    for tx,ty in land_tiles:
        try:
            tile = tile_at(land_zoom,tx,ty,'mapbox.mapbox-terrain-v2')
        except Exception:
            break  # Optional vegetation cannot discard houses or water.
        collect_land(tile,('landcover',),tx,ty,factor)
        land_count += 1
    result = compile_layout(lines, buildings, coverage, addresses, terrain)
    if result is not None:
        result['terrainStatus'] = 'available' if land_count==len(land_tiles) else 'partial' if land_count else 'unavailable'
        result['footprintStatus'] = 'available' if len(coverage)==9 else 'partial' if coverage else 'unavailable'
    return result



def neighborhood_layout(cached_only=False):
    """One lookup per home/12h, failure cooldown 1h, serialized across clients.

    A local hashed key invalidates on home/key changes. Cache contains only
    projected geometry, never the address, token or geographic coordinates.
    """
    home, token = maps.get_home_location(), maps.get_mapbox_api_key()
    if not home or not token or maps.get_map_option('disable_mapbox', False):
        return {'source': 'generated'}
    key = hashlib.sha256((home+'|'+token+'|7').encode()).hexdigest()
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
