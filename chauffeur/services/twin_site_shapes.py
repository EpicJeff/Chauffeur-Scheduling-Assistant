"""Validation for authored yard edits; polygon topology is owned by terrain."""
import math
from services import twin_terrain as terrain


KINDS = ('beds', 'hardscape', 'edges', 'pool', 'fire_pit', 'fence')


def validate(name, piece):
    key = next((k for k in ('polygon', 'points', 'polyline') if k in piece), None)
    closed = name in ('beds', 'hardscape', 'pool') or key == 'polygon'
    if name == 'fire_pit':
        points = [piece.get('at')]
    else:
        points = piece.get(key) if key else None
    if (not isinstance(points, list) or not (1 if name == 'fire_pit' else 3 if closed else 2) <= len(points) <= 200
            or any(not isinstance(p, (list, tuple)) or len(p) != 2 or not all(terrain.number(v) for v in p) for p in points)):
        raise ValueError('Use finite lot points: 3 to 200 corners for polygons, 2 to 200 for lines.')
    if closed:
        error = terrain.pad_error({'polygon': points, 'height': 0})
        if error:
            raise ValueError(error)
    elif any(math.dist(a, b) < .01 for a, b in zip(points, points[1:])):
        raise ValueError('Keep line points at least 0.01 feet apart.')
    sizes = [max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1)]
    if max(sizes) > 2000 or closed and min(sizes) < .01:
        raise ValueError('Keep shapes between 0.01 and 2000 feet across.')
    for field, default, low, high in [('rotation', 0, -360, 360),
            *([('depth', 5, 2, 12), ('coping', 1, 0, 3)] if name == 'pool' else []),
            *([('radius', 2, .1, 100)] if name == 'fire_pit' else []),
            *([('height', 6, .1, 50)] if name == 'fence' else [])]:
        value = piece.get(field, default)
        if not terrain.number(value) or not low <= value <= high:
            raise ValueError(f'Choose {field} from {low} to {high}.')
    if 'style' in piece and (not isinstance(piece['style'], str) or not 1 <= len(piece['style'].strip()) <= 80):
        raise ValueError('Use a fence style of 1 to 80 characters.')
    return points


def update(name, piece, change, lot):
    if name not in KINDS:
        raise ValueError('Choose a yard shape.')
    geometry = next((k for k in ('polygon', 'points', 'polyline') if k in piece), None)
    allowed = {geometry, 'rotation'} if geometry else {'rotation'}
    if name == 'pool':
        allowed |= {'depth', 'coping'}
    if name == 'fire_pit':
        allowed |= {'at', 'radius'}
    if name == 'fence':
        allowed |= {'height'} | ({'style'} if 'style' in piece else set())
    if not change or set(change) - allowed:
        raise ValueError('Choose a supported property of this yard shape.')
    if 'rotation' in change and geometry and geometry not in change:
        validate(name, {**piece, **change})
        angle = change['rotation']
        if not terrain.number(angle) or not -360 <= angle <= 360:
            raise ValueError('Choose rotation from -360 to 360.')
        points = piece[geometry]
        origin = [sum(p[i] for p in points)/len(points) for i in (0, 1)]
        if geometry == 'polygon':
            areas = [terrain.cross([0, 0], p, points[(j+1) % len(points)]) for j, p in enumerate(points)]
            area = sum(areas)
            if abs(area) > 1e-9:
                origin = [sum((p[i]+points[(j+1) % len(points)][i])*areas[j] for j, p in enumerate(points))/(3*area) for i in (0, 1)]
        previous = piece.get('rotation', 0)
        a = math.radians(angle-(previous if terrain.number(previous) else 0))
        change[geometry] = [[round(origin[0]+(p[0]-origin[0])*math.cos(a)-(p[1]-origin[1])*math.sin(a), 9),
                             round(origin[1]+(p[0]-origin[0])*math.sin(a)+(p[1]-origin[1])*math.cos(a), 9)] for p in points]
    piece.update(change)
    points = validate(name, piece)
    # Lots need not be rectangular. Check edges too, including a segment
    # crossing a concave boundary even when both endpoints are inside.
    outside = False
    if lot:
        from services.twin_terrain import inside, intersects
        outside = any(not inside(lot, p) for p in points)
        segments = list(zip(points, points[1:] + (points[:1] if geometry == 'polygon' else [])))
        for a, b in segments:
            for c, d in zip(lot, lot[1:] + lot[:1]):
                crosses = terrain.cross(a, b, c)*terrain.cross(a, b, d) < 0 and terrain.cross(c, d, a)*terrain.cross(c, d, b) < 0
                if crosses or intersects(a, b, c, d) and not all(inside(lot, p) for p in [a, b, [(a[i]+b[i])/2 for i in (0, 1)]]):
                    outside = True
        if name == 'fire_pit':
            radius = piece.get('radius', 2)
            outside |= any(not inside(lot, [points[0][0]+radius*math.cos(a*math.pi/32), points[0][1]+radius*math.sin(a*math.pi/32)]) for a in range(64))
    return 'Changed the yard shape.' + (' Warning: this shape extends outside the lot.' if outside else '')
