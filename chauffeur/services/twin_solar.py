"""Solar rectangles in a roof's orthonormal plane coordinates (feet).

The exposed face clipping matches twin_roof.js; panel packing matches
twin_solar.js. Nothing here reads HA or stores display preferences.
"""
import math
from services.twin_roof_issues import _planes

EPS = 1e-7
DEFAULTS = dict(panel_width=65/12, panel_height=39/12, orientation='portrait',
                gap=1/12, setback=0, count=None, entity=None)


def area(poly):
    # A local origin avoids cancellation on small, translated roof fragments.
    if not poly:
        return 0
    x, y = poly[0]
    return sum((a[0]-x)*(b[1]-y)-(a[1]-y)*(b[0]-x)
               for a, b in zip(poly[1:], poly[2:])) / 2


def clip(poly, line):
    if not poly:
        return []
    scale = math.hypot(*line[:2])
    if scale == 0:
        return poly if line[2] >= 0 else []
    def distance(p):
        value = (p[0]*line[0]+p[1]*line[1]+line[2])/scale
        return 0 if abs(value) < 1e-9 else value
    out = []
    for a, b in zip(poly, poly[1:]+poly[:1]):
        da, db = distance(a), distance(b)
        if da >= 0:
            out.append(a)
        if (da < 0) != (db < 0):
            t = da/(da-db)
            out.append([a[i]+t*(b[i]-a[i]) for i in (0, 1)])
    # An intersection can equal a retained endpoint. Such an edge would emit
    # the entire polygon as an outside slice in subtract(), counting it twice.
    out = [p for i, p in enumerate(out) if math.dist(p, out[i-1]) > 1e-9]
    return out if area(out) > 1e-10 else []


def subtract(poly, cutter):
    if not cutter:
        return [poly]
    edges = [[a[1]-b[1], b[0]-a[0], b[1]*a[0]-b[0]*a[1]]
             for a, b in zip(cutter, cutter[1:]+cutter[:1])]
    overlap = poly
    for edge in edges:
        overlap = clip(overlap, edge)
    if not overlap:
        return [poly]
    out, remainder = [], poly
    for edge in edges:
        outside = clip(remainder, [-v for v in edge])
        if outside:
            out.append(outside)
        remainder = clip(remainder, edge)
    return out


def basis(plane):
    a, b, c = plane
    length = math.sqrt(a*a+b*b+1)
    n = [-a/length, -b/length, 1/length]
    u = [1-n[0]*n[0], -n[0]*n[1], -n[0]*n[2]]
    size = math.sqrt(sum(v*v for v in u))
    u = [v/size for v in u]
    v = [n[1]*u[2]-n[2]*u[1], n[2]*u[0]-n[0]*u[2], n[0]*u[1]-n[1]*u[0]]
    return [0, 0, c], u, v, n


def point(plane, uv):
    origin, u, v, _ = basis(plane)
    return [origin[i]+u[i]*uv[0]+v[i]*uv[1] for i in range(3)]


def project(plane, xy):
    origin, u, v, _ = basis(plane)
    p = [*xy, plane[0]*xy[0]+plane[1]*xy[1]+plane[2]]
    return [sum((p[i]-origin[i])*axis[i] for i in range(3)) for axis in (u, v)]


def rectangle(rect):
    x, y, X, Y = rect
    return [[x, y], [X, y], [X, Y], [x, Y]]


def faces(building):
    from services import twin_model_roofs as roofs
    sections = [s for r in building.get('roofs', []) if r.get('state') != 'ghost'
                for s in roofs.to_sections(r)]
    for d in building.get('dormers', []):
        roof = next((r for r in building['roofs'] if r['id'] == d['roof']), None)
        if roof and d.get('state') != 'ghost':
            sections.extend(roofs.dormer_sections(d, roof))
    all_faces = []
    for index, section in enumerate(sections):
        planes = list(dict.fromkeys(_planes(section)))
        h = section.get('overhang', 0)
        rect = [v+(-h if i < 2 else h) for i, v in enumerate(section['rect'])]
        for plane in planes:
            poly = rectangle(rect)
            for other in planes:
                poly = clip(poly, [other[i]-plane[i] for i in range(3)])
            if poly:
                all_faces.append(dict(plane=plane, polygon=poly, section=index,
                                      roof=section.get('roof', section['id'])))
    exposed = []
    for face in all_faces:
        pieces = [face['polygon']]
        for other in all_faces:
            if other['section'] == face['section']:
                continue
            same = all(abs(a-b) < EPS for a, b in zip(other['plane'], face['plane']))
            if same and other['section'] > face['section']:
                continue
            cutter = other['polygon'] if same else clip(other['polygon'],
                [other['plane'][i]-face['plane'][i] for i in range(3)])
            pieces = [p for piece in pieces for p in subtract(piece, cutter)]
        exposed.extend({**face, 'polygon': [project(face['plane'], p) for p in poly]} for poly in pieces)
    return exposed


def error(building, zone, others=()):
    from services.twin_plan import _number
    if (not isinstance(zone.get('roof'), str) or not isinstance(zone.get('plane'), (list, tuple))
            or len(zone['plane']) != 3 or not all(_number(v) for v in zone['plane'])):
        return 'Choose a roof plane for the solar zone.'
    rect = zone.get('rect')
    if (not isinstance(rect, list) or len(rect) != 4 or not all(_number(v) for v in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]):
        return 'Give the solar zone a positive width and height.'
    z = {**DEFAULTS, **zone}
    if (any(not _number(z[k]) or z[k] <= 0 for k in ('panel_width', 'panel_height'))
            or any(not _number(z[k]) or z[k] < 0 for k in ('gap', 'setback'))
            or z['orientation'] not in ('portrait', 'landscape')
            or z['count'] is not None and (type(z['count']) is not int or not 0 <= z['count'] <= 10000)):
        return 'Use positive panel sizes, nonnegative spacing and a whole panel count.'
    import re
    if z['entity'] is not None and (not isinstance(z['entity'], str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', z['entity'])):
        return 'Choose a production sensor or leave it empty.'
    from services.twin_model import _overlap
    covered = sum(_overlap(rectangle(rect), f['polygon']) for f in faces(building)
                  if f['roof'] == zone['roof'] and all(abs(a-b) < EPS for a, b in zip(f['plane'], zone['plane'])))
    if covered < (rect[2]-rect[0])*(rect[3]-rect[1])-1e-5:
        return 'The solar zone must fit on one clear roof plane. Move it inside the roof edges.'
    for other in others:
        if (other.get('id') == zone.get('id') or other.get('state') == 'ghost'
                or other.get('roof') != zone['roof'] or other.get('plane') != zone['plane']):
            continue
        r = other['rect']
        if min(r[2], rect[2])-max(r[0], rect[0]) > EPS and min(r[3], rect[3])-max(r[1], rect[1]) > EPS:
            return 'There is already a solar zone there. Pick a clear part of the roof.'
    # Bound work on malformed or extreme imported dimensions.
    if capacity(z) > 10000:
        return 'Use a smaller zone or larger panels (up to 10000 panels per zone).'
    return None


def dimensions(zone):
    z = {**DEFAULTS, **zone}
    w, h = sorted([z['panel_width'], z['panel_height']])
    return (w, h) if z['orientation'] == 'portrait' else (h, w)


def capacity(zone):
    w, h = dimensions(zone)
    r, g, s = zone['rect'], zone.get('gap', DEFAULTS['gap']), zone.get('setback', 0)
    return max(0, math.floor((r[2]-r[0]-2*s+g+EPS)/(w+g))) * max(0, math.floor((r[3]-r[1]-2*s+g+EPS)/(h+g)))


def layout(zone):
    z = {**DEFAULTS, **zone}
    w, h = dimensions(z)
    r, g, s = z['rect'], z['gap'], z['setback']
    cols = max(0, math.floor((r[2]-r[0]-2*s+g+EPS)/(w+g)))
    rows = max(0, math.floor((r[3]-r[1]-2*s+g+EPS)/(h+g)))
    count = min(cols*rows, z['count'] if z['count'] is not None else cols*rows, 10000)
    if not count:
        return []
    rows = math.ceil(count/cols)
    y = (r[1]+r[3]-(rows*h+(rows-1)*g))/2
    out = []
    for row in range(rows):
        n = min(cols, count-len(out))
        x = (r[0]+r[2]-(n*w+(n-1)*g))/2
        out.extend([[x+i*(w+g), y+row*(h+g), x+i*(w+g)+w, y+row*(h+g)+h] for i in range(n)])
    return out
