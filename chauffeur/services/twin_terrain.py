"""Terrain invariants shared by reads and connected-model operations."""
import math


def number(v):
    return type(v) in (int, float) and -1e5 <= v <= 1e5 and math.isfinite(v)


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def intersects(a, b, c, d):
    def on(a, b, p):
        return abs(cross(a, b, p)) < 1e-8 and all(min(a[i], b[i])-1e-8 <= p[i] <= max(a[i], b[i])+1e-8 for i in (0, 1))
    return (cross(a, b, c)*cross(a, b, d) < 0 and cross(c, d, a)*cross(c, d, b) < 0
            or any((on(a, b, c), on(a, b, d), on(c, d, a), on(c, d, b))))


def pad_error(pad):
    from services import twin_plan
    poly = pad.get('polygon')
    if not twin_plan._polygon(poly) or len(poly) > 200:
        return 'Draw a pad with 3 to 200 corners.'
    if any(not number(v) for p in poly for v in p):
        return 'Use finite lot coordinates within 100000 feet.'
    for i, a in enumerate(poly):
        b = poly[(i+1) % len(poly)]
        if math.dist(a, b) < 1e-6:
            return 'Pad corners must be distinct.'
        for j in range(i+1, len(poly)):
            if j == i+1 or i == 0 and j == len(poly)-1:
                continue
            if intersects(a, b, poly[j], poly[(j+1) % len(poly)]):
                return 'Pad edges cannot cross.'
    if abs(sum(cross([0, 0], a, poly[(i+1) % len(poly)]) for i, a in enumerate(poly))) < 1e-6:
        return 'A pad must enclose an area.'
    if not number(pad.get('height')) or not -50 <= pad['height'] <= 50:
        return 'Choose a pad height from -50 to 50 feet.'
    pad.setdefault('blend', 6)
    if not number(pad['blend']) or not 0 <= pad['blend'] <= 50:
        return 'Choose a blend from 0 to 50 feet.'
    pad.setdefault('edges', [{'edge': 'slope'} for _ in poly])
    if (not isinstance(pad['edges'], list) or len(pad['edges']) != len(poly)
            or any(not isinstance(e, dict) or e.get('edge') not in ('sharp', 'slope') for e in pad['edges'])):
        return 'Choose slope or sharp for each pad edge.'
    return None


def foundation_error(value):
    if not isinstance(value, dict) or value.get('mode') not in ('auto', 'fixed'):
        return 'Choose Auto or Fixed for the foundation.'
    for field, default, low, high in (('offset_ft', 0, -50, 50), ('thickness_ft', 1, 0, 50)):
        value.setdefault(field, default)
        if not number(value[field]) or not low <= value[field] <= high:
            return f'Choose {field} from {low} to {high} feet.'
    return None


def normalize_foundation(building, notes):
    value = building.setdefault('foundation', {'mode': 'fixed', 'offset_ft': 0, 'thickness_ft': 1})
    error = foundation_error(value)
    if error:
        building['foundation'] = {'mode': 'fixed', 'offset_ft': 0, 'thickness_ft': 1}
        notes.append('Defaulted invalid foundation: ' + error)
    if not number(building.get('base', 0)) or not -50 <= building.get('base', 0) <= 50:
        building['base'] = 0


def footprint(b):
    levels = sorted(b.get('levels', []), key=lambda l: l['elevation'])
    poly = levels[0].get('outline', []) if levels else []
    if not poly:
        points = [p for r in b.get('rooms', []) for p in r.get('polygon', [])]
        joints = {j['id']: j['at'] for j in b.get('joints', [])}
        points += [p for w in b.get('walls', []) for p in
                   ([w['from'], w['to']] if 'from' in w else [joints[j] for j in w.get('joints', [])])]
        if not points:
            return []
        x0, y0 = [min(p[i] for p in points) for i in (0, 1)]
        x1, y1 = [max(p[i] for p in points) for i in (0, 1)]
        poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    a, pos = math.radians(b.get('rotation', 0)), b.get('position', [0, 0])
    return [[pos[0]+p[0]*math.cos(a)-p[1]*math.sin(a), pos[1]+p[0]*math.sin(a)+p[1]*math.cos(a)] for p in poly]


def crossing_error(model):
    pads = model.get('site', {}).get('terraces', [])
    if not pads:
        return None
    for b in model.get('buildings', []):
        if b.get('foundation', {}).get('mode') == 'auto':
            continue
        if b.get('base', 0) >= 0 and all(p['height'] <= b.get('base', 0) for p in pads):
            continue
        poly = footprint(b)
        if len(poly) < 3:
            continue
        # Check the actual surface, including blend bands and later-pad
        # precedence. A fixed plinth handles lower ground, never ground which
        # cuts above its top. Auto deliberately follows the highest sample.
        candidates = list(poly)
        for i, p in enumerate(poly):
            q = poly[(i+1) % len(poly)]
            count = max(1, math.ceil(math.dist(p, q)))
            candidates += [[p[k]+(q[k]-p[k])*j/count for k in (0, 1)] for j in range(count)]
        x0, y0 = [min(p[i] for p in poly) for i in (0, 1)]
        x1, y1 = [max(p[i] for p in poly) for i in (0, 1)]
        for x in range(math.floor(x0), math.ceil(x1)+1):
            for y in range(math.floor(y0), math.ceil(y1)+1):
                if inside(poly, [x, y]):
                    candidates.append([x, y])
        candidates += [p for pad in pads for p in pad['polygon'] if inside(poly, p)]
        for pad in pads:
            for i, a in enumerate(pad['polygon']):
                z = pad['polygon'][(i+1) % len(pad['polygon'])]
                for j, c in enumerate(poly):
                    d = poly[(j+1) % len(poly)]
                    v, w = [z[k]-a[k] for k in (0, 1)], [d[k]-c[k] for k in (0, 1)]
                    den = v[0]*w[1]-v[1]*w[0]
                    if abs(den) < 1e-10:
                        continue
                    delta = [c[k]-a[k] for k in (0, 1)]
                    t, u = (delta[0]*w[1]-delta[1]*w[0])/den, (delta[0]*v[1]-delta[1]*v[0])/den
                    if 0 <= t <= 1 and 0 <= u <= 1:
                        candidates.append([a[k]+t*v[k] for k in (0, 1)])
        for p in candidates:
            if ground_at(pads, p) > b.get('base', 0)+1e-6:
                return 'That pad cuts through a fixed building. Choose Auto foundation or raise its fixed base first.'
    return None


def distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = dx*dx+dy*dy
    t = min(1, max(0, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)) if length else 0
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def inside(poly, p):
    result = False
    for i, a in enumerate(poly):
        b = poly[(i+1) % len(poly)]
        if distance(p, a, b) < 1e-9:
            return True
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            result = not result
    return result


def ground_at(pads, p):
    def smooth(t):
        t = min(1, max(0, t))
        return t*t*(3-2*t)

    height = 0
    for pad in pads:
        poly = pad['polygon']
        if inside(poly, p):
            height = pad['height']
            continue
        blend = pad.get('blend', 6)
        if not blend:
            continue
        ds = [distance(p, a, poly[(i+1) % len(poly)]) for i, a in enumerate(poly)]
        edges = pad.get('edges', [{'edge': 'slope'}]*len(poly))
        d = min((v for i, v in enumerate(ds) if edges[i]['edge'] != 'sharp'), default=math.inf)
        if d >= blend:
            continue
        weight = smooth(1-d/blend)
        winding = 1 if sum(cross([0, 0], a, poly[(i+1) % len(poly)]) for i, a in enumerate(poly)) > 0 else -1
        for i, a in enumerate(poly):
            if edges[i]['edge'] != 'sharp':
                continue
            b = poly[(i+1) % len(poly)]
            inward = winding*cross(a, b, p)/math.dist(a, b)
            # Match twin_ground.js: a continuous sharp-corner taper which
            # reaches full weight at slope boundaries, even on concave pads.
            clearance = max(0, inward) + max(0, ds[i]-d)
            weight *= smooth(clearance/d)
        height += weight*(pad['height']-height)
    return height


def validate_reads(buildings, site, notes):
    if not crossing_error({'buildings': buildings, 'site': site}):
        return
    kept = []
    for pad in site.get('terraces', []):
        error = crossing_error({'buildings': buildings, 'site': {'terraces': kept + [pad]}})
        if error:
            notes.append('Dropped pad: ' + error)
        else:
            kept.append(pad)
    site['terraces'] = kept
