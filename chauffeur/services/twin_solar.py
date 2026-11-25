"""Solar rectangles in a roof's orthonormal plane coordinates (feet).

The exposed face clipping matches twin_roof.js; panel packing matches
twin_solar.js. Nothing here reads HA or stores display preferences.
"""
from copy import deepcopy
from functools import lru_cache
import json
import math
from services.twin_roof_issues import _planes
from services.twin_model_supports import is_supported, frame_point

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


def _boundaries(face):
    """Outward unit normals and supporting lines of a CCW exposed fragment."""
    if 'boundaries' in face:
        yield from face['boundaries']
        return
    poly = face['polygon']
    for a, b in zip(poly, poly[1:]+poly[:1]):
        length = math.dist(a, b)
        if length > EPS:
            n = [(b[1]-a[1])/length, (a[0]-b[0])/length]
            yield n, sum(n[i]*a[i] for i in (0, 1)), a, b


def dock_offsets(face, rect):
    """Each edge's signed inward distance, in feet, to its roof boundary.

    Prefer the nearest parallel edge on that side. Otherwise intersect the
    edge midpoint's outward normal with a boundary segment. The boundary's
    outward normal identifies its counterpart after clipping/vertex reordering.
    """
    out = []
    for edge in range(4):
        axis, sign = edge % 2, -1 if edge < 2 else 1
        tangent = (rect[1-axis]+rect[3-axis])/2
        candidates = []
        for n, c, a, b in _boundaries(face):
            if n[axis]*sign <= EPS:
                continue
            boundary = (c-n[1-axis]*tangent)/n[axis]
            distance = sign*(boundary-rect[edge])
            parallel = abs(n[1-axis]) < EPS
            crosses = min(a[1-axis], b[1-axis])-EPS <= tangent <= max(a[1-axis], b[1-axis])+EPS
            if parallel or crosses:
                separation = max(min(a[1-axis],b[1-axis])-tangent, tangent-max(a[1-axis],b[1-axis]), 0)
                candidates.append((not parallel, math.hypot(distance,separation), n, distance, a, b))
        if not candidates:
            raise ValueError('The roof boundary is missing.')
        _, _, normal, distance, a, b = min(candidates, key=lambda v: v[:2])
        bounds = [min(p[i] for p in face['polygon']) for i in (0,1)]+[max(p[i] for p in face['polygon']) for i in (0,1)]
        location = [((a[i]+b[i])/2-bounds[i])/max(EPS,bounds[i+2]-bounds[i]) for i in (0,1)]
        out.append(dict(normal=normal, distance=distance, location=location))
    return out


def refit(face, offsets):
    """Solve all four dock equations together, including diagonal boundaries."""
    equations = []
    boundaries = list(_boundaries(face))
    for edge, offset in enumerate(offsets):
        axis, sign = edge % 2, -1 if edge < 2 else 1
        candidates = [line for line in boundaries if line[0][axis]*sign > EPS]
        if not candidates:
            raise ValueError('The roof boundary is missing.')
        # Stable under clipping splits and changes to a diagonal's angle.
        bounds = [min(p[i] for p in face['polygon']) for i in (0,1)]+[max(p[i] for p in face['polygon']) for i in (0,1)]
        def score(line):
            n, _, a, b = line
            alignment = sum(n[i]*offset['normal'][i] for i in (0,1))
            location = [((a[i]+b[i])/2-bounds[i])/max(EPS,bounds[i+2]-bounds[i]) for i in (0,1)]
            return (round(alignment,8), -math.dist(location,offset.get('location',location)))
        n, c, _, _ = max(candidates, key=score)
        row = [0.]*5
        row[edge] = n[axis]
        row[1-axis] = row[3-axis] = n[1-axis]/2
        row[4] = c-n[axis]*sign*offset['distance']
        equations.append(row)
    for col in range(4):
        pivot = max(range(col, 4), key=lambda i: abs(equations[i][col]))
        equations[col], equations[pivot] = equations[pivot], equations[col]
        value = equations[col][col]
        if abs(value) < EPS:
            raise ValueError('The roof boundary cannot hold a rectangle.')
        equations[col] = [v/value for v in equations[col]]
        for i in range(4):
            if i != col:
                factor = equations[i][col]
                equations[i] = [v-factor*w for v, w in zip(equations[i], equations[col])]
    return [row[4] for row in equations]


def matching_face(old, zone, candidates):
    """Section/side identity first, then <=10 degree normal + most overlap."""
    from services.twin_model import _overlap
    candidates = [f for f in candidates if f['roof'] == zone['roof']]
    footprint = [point(zone['plane'], uv)[:2] for uv in rectangle(zone['rect'])]
    def overlap(face):
        projected = [project(face['plane'], xy) for xy in footprint]
        return sum(_overlap(projected, p) for p in face.get('polygons',[face['polygon']]))
    identity = [f for f in candidates if f['identity'] == old['identity']]
    if identity:
        return max(identity, key=overlap)
    normal = basis(zone['plane'])[3]
    candidates = [f for f in candidates if sum(a*b for a, b in zip(normal, basis(f['plane'])[3]))
                  >= math.cos(math.radians(10))-EPS and overlap(f) > EPS]
    return max(candidates, key=overlap) if candidates else None


def _hull(points):
    points = sorted(set(tuple(p) for p in points))
    def half(rows):
        out = []
        for p in rows:
            while len(out) >= 2 and ((out[-1][0]-out[-2][0])*(p[1]-out[-2][1])
                   -(out[-1][1]-out[-2][1])*(p[0]-out[-2][0])) <= EPS:
                out.pop()
            out.append(p)
        return out
    return [list(p) for p in half(points)[:-1]+half(list(reversed(points)))[:-1]]


def _fit_union(face, rect, zone, covered):
    """Find a panel across seams when no individual convex fragment holds it."""
    from itertools import permutations
    w,h = dimensions(zone)
    if rect[2]-rect[0] < w-EPS or rect[3]-rect[1] < h-EPS:
        return None
    # A panel centre is forbidden by each hole/notch expanded by half a panel.
    # Its feasible boundary consists of these straight lines and the inset
    # hull/envelope. Vertices and projections therefore include its nearest
    # feasible point, even when the feasible region is a single point.
    outside = [face['polygon']]
    for poly in face['polygons']:
        outside = [part for p in outside for part in subtract(p,poly)]
    limits = [([-1,0],-rect[0]-w/2),([0,-1],-rect[1]-h/2),
              ([1,0],rect[2]-w/2),([0,1],rect[3]-h/2)]
    limits.extend((n,c-abs(n[0])*w/2-abs(n[1])*h/2)
                  for n,c,_,_ in _boundaries({'polygon':face['polygon']}))
    lines = list(limits)
    for poly in outside:
        expanded = _hull([[p[0]+dx,p[1]+dy] for p in poly for dx in (-w/2,w/2) for dy in (-h/2,h/2)])
        lines.extend((n,c) for n,c,_,_ in _boundaries({'polygon':expanded}))
    target = [(rect[i]+rect[i+2])/2 for i in (0,1)]
    points = [target]
    for index,(n,c) in enumerate(lines):
        distance = sum(n[i]*target[i] for i in (0,1))-c
        points.append([target[i]-n[i]*distance for i in (0,1)])
        for m,d in lines[index+1:]:
            det = n[0]*m[1]-n[1]*m[0]
            if abs(det)>EPS:
                points.append([(c*m[1]-n[1]*d)/det,(n[0]*d-c*m[0])/det])
    def panel(p): return [p[0]-w/2,p[1]-h/2,p[0]+w/2,p[1]+h/2]
    points = [p for p in points if all(sum(n[i]*p[i] for i in (0,1)) <= c+EPS for n,c in limits)
              and covered(panel(p))]
    if not points:
        return None
    centre = min(points,key=lambda p:math.dist(p,target))
    candidates = []
    for order in permutations(range(4)):
        r = panel(centre)
        for edge in order:
            start,end = r[edge],rect[edge]
            for _ in range(32):
                mid = (start+end)/2
                candidate = list(r);candidate[edge]=mid
                if covered(candidate):start=mid
                else:end=mid
            r[edge]=start
        candidates.append(r)
    return max(candidates,key=lambda r:(capacity({**zone,'rect':r}),(r[2]-r[0])*(r[3]-r[1])))


def fit_inside(face, rect, zone):
    """Trim corner overflows inward, refusing only if one panel cannot fit.

    Midpoint docks on a changing diagonal can conflict at the corners. Keep
    the docked envelope, find a feasible panel centre from its half-planes,
    then grow toward its four docks in every order and retain the best fit.
    """
    from itertools import permutations
    if 'polygons' in face:
        from services.twin_model import _overlap
        def covered(r):
            return (r[2] > r[0] and r[3] > r[1] and
                    sum(_overlap(rectangle(r),p) for p in face['polygons']) >= (r[2]-r[0])*(r[3]-r[1])-EPS)
        if covered(rect):
            return rect
        # Try the full plane first, then its clear convex pieces. Never accept
        # a hull candidate over a real notch, hole or a higher roof.
        candidates = [fit_inside({'polygon':p},rect,zone) for p in [face['polygon'],*face['polygons']]]
        candidates = [r for r in candidates if r is not None and covered(r)]
        # A strip across seams (beside a new dormer, say) can hold more panels
        # than any single convex piece, so it always competes.
        union = _fit_union(face,rect,zone,covered)
        if union is not None:
            candidates.append(union)
        return (max(candidates,key=lambda r:(capacity({**zone,'rect':r}),(r[2]-r[0])*(r[3]-r[1])))
                if candidates else None)
    lines = list(_boundaries(face))
    if all(sum(n[i]*p[i] for i in (0, 1)) <= c+EPS
           for n, c, _, _ in lines for p in rectangle(rect)):
        return rect
    w, h = dimensions(zone)
    if rect[2]-rect[0] < w-EPS or rect[3]-rect[1] < h-EPS:
        return rect
    limits = [(n, c-abs(n[0])*w/2-abs(n[1])*h/2) for n, c, _, _ in lines]
    limits.extend([([-1,0], -rect[0]-w/2), ([0,-1], -rect[1]-h/2),
                   ([1,0], rect[2]-w/2), ([0,1], rect[3]-h/2)])
    target = [(rect[i]+rect[i+2])/2 for i in (0, 1)]
    centres = [target]
    for index, (n, c) in enumerate(limits):
        distance = sum(n[i]*target[i] for i in (0, 1))-c
        centres.append([target[i]-n[i]*distance for i in (0, 1)])
        for m, d in limits[index+1:]:
            determinant = n[0]*m[1]-n[1]*m[0]
            if abs(determinant) > EPS:
                centres.append([(c*m[1]-n[1]*d)/determinant, (n[0]*d-c*m[0])/determinant])
    centres = [p for p in centres if all(sum(n[i]*p[i] for i in (0, 1)) <= c+EPS for n, c in limits)]
    if not centres:
        return None
    centre = min(centres, key=lambda p: math.dist(p, target))
    fitted = []
    for order in permutations(range(4)):
        r = [centre[0]-w/2, centre[1]-h/2, centre[0]+w/2, centre[1]+h/2]
        for edge in order:
            axis, sign = edge % 2, -1 if edge < 2 else 1
            bounds = [rect[edge]]
            for n, c, _, _ in lines:
                if n[axis]*sign > EPS:
                    other = r[3-axis if n[1-axis] > 0 else 1-axis]
                    bounds.append((c-n[1-axis]*other)/n[axis])
            r[edge] = min(bounds) if sign > 0 else max(bounds)
        fitted.append(r)
    return max(fitted, key=lambda r: (capacity({**zone, 'rect':r}), (r[2]-r[0])*(r[3]-r[1])))


def _face_identity(section, plane):
    # Across/end sides keep their role when a person turns the ridge.
    if section['kind'] == 'flat':
        side = 'flat'
    else:
        side = ('x0' if plane[0] > EPS else 'x1' if plane[0] < -EPS else
                'y0' if plane[1] > EPS else 'y1')
        across = 'x' if section.get('ridge') == 'y' else 'y'
        side = ('across' if side[0] == across else 'end')+side[1]
    return [section['id'], side]


def faces(building):
    """Reuse roof clipping by value, keeping cached faces private to callers."""
    dormers = [d for d in building.get('dormers', []) if d.get('state') != 'ghost']
    parents = {d['roof'] for d in dormers}
    # A live dormer can still use a ghost parent's geometry in the existing
    # clipping path. Keep that dependency; unrelated ghosts contribute nothing.
    roof_input = dict(roofs=[r for r in building.get('roofs', [])
                            if r.get('state') != 'ghost' or r['id'] in parents],
                      dormers=dormers)
    key = json.dumps(roof_input, sort_keys=True, separators=(',', ':'))
    return deepcopy(_cached_faces(key))


def docking_faces(building):
    """Cancel coplanar clipping seams; only the exposed plane's edges dock.

    subtract() partitions an exposed surface into disjoint convex polygons.
    A zone may span those artificial seams. Split collinear edges at every
    endpoint, then cancel reversed pairs. Keep every clear polygon for exact
    coverage, including real notches and holes.
    """
    groups = {}
    for face in faces(building):
        key = (face['roof'], tuple(face['identity']), tuple(face['plane']))
        groups.setdefault(key, []).append(face)
    result = []
    for pieces in groups.values():
        if len(pieces)==1:
            result.extend(pieces)
            continue
        points = [p for f in pieces for p in f['polygon']]
        segments = {}
        for face in pieces:
            for n,c,a,b in _boundaries(face):
                delta = [b[i]-a[i] for i in (0,1)]
                length2 = sum(v*v for v in delta)
                cuts = {0.,1.}
                for p in points:
                    if abs(sum(n[i]*p[i] for i in (0,1))-c) < EPS:
                        t = sum((p[i]-a[i])*delta[i] for i in (0,1))/length2
                        if EPS < t < 1-EPS: cuts.add(t)
                cuts = sorted(cuts)
                for lo,hi in zip(cuts,cuts[1:]):
                    start,end = [[a[i]+t*delta[i] for i in (0,1)] for t in (lo,hi)]
                    if math.dist(start,end) < EPS: continue
                    key = tuple(sorted(tuple(round(v,7) for v in p) for p in (start,end)))
                    if key in segments and sum(x*y for x,y in zip(segments[key][0],n)) < 0:
                        del segments[key]
                    else:
                        segments[key] = (n,c,start,end)
        result.append({**pieces[0], 'polygon':_hull(points), 'polygons':[p['polygon'] for p in pieces],
                       'boundaries':list(segments.values())})
    return result


@lru_cache(maxsize=32)
def _cached_faces(key):
    building = json.loads(key)
    from services import twin_model_roofs as roofs
    sections = [s for r in building.get('roofs', []) if r.get('state') != 'ghost'
                for s in roofs.to_sections(r)]
    for d in building.get('dormers', []):
        roof = next((r for r in building['roofs'] if r['id'] == d['roof']), None)
        if roof and d.get('state') != 'ghost':
            sections.extend(roofs.dormer_sections(d, roof))
    all_faces = []
    for index, section in enumerate(sections):
        local_planes = list(dict.fromkeys(_planes(section)))
        frame = section.get('roof_frame')
        if frame:
            cosine, sine = math.cos(frame['angle']), math.sin(frame['angle'])
            ox, oy = frame['origin']
            planes = []
            for a, b, c in local_planes:
                x, y = a*cosine-b*sine, a*sine+b*cosine
                planes.append((x, y, c+a*ox+b*oy-x*ox-y*oy))
        else:
            planes = local_planes
        h = section.get('overhang', 0)
        edges = section.get('edges', [])
        overhangs = [edges[i].get('overhang_ft', h) if i < len(edges) else h for i in (3, 0, 1, 2)]
        rect = [v+(-overhangs[i] if i < 2 else overhangs[i]) for i, v in enumerate(section['rect'])]
        for local_plane, plane in zip(local_planes, planes):
            poly = ([frame_point(section, p) for p in rectangle(rect)] if frame else rectangle(rect))
            for other in planes:
                poly = clip(poly, [other[i]-plane[i] for i in range(3)])
            if poly:
                all_faces.append(dict(plane=plane, polygon=poly, section=index,
                                      identity=_face_identity(section, local_plane),
                                      roof=section.get('roof', section['id'])))
    exposed = []
    for face in all_faces:
        pieces = [face['polygon']]
        for other in all_faces:
            if other['section'] == face['section']:
                continue
            current, candidate = sections[face['section']], sections[other['section']]
            # Walled roofs share today's envelope. Each supported roof (and
            # its dormers) has its own, even beneath or above the house roof.
            if ((is_supported(current) or is_supported(candidate)) and
                    current.get('roof', current['id']) != candidate.get('roof', candidate['id'])):
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
