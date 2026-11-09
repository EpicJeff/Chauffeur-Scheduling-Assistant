"""Pure geometry warnings for the draft roof check (feet, building frame)."""
import math


_EPS = 1e-9


def _planes(section):
    """Match twin_roof.js: signed side planes, including below-plate eaves."""
    x0, y0, x1, y1 = section['rect']
    plate = section['plate']
    pitches = section.get('pitches') or {}
    slopes = {side: pitches.get(side, section['pitch']) / 12
              for side in ('x0', 'x1', 'y0', 'y1')}
    edges = {'x0': (slopes['x0'], 0, plate - slopes['x0'] * x0),
             'x1': (-slopes['x1'], 0, plate + slopes['x1'] * x1),
             'y0': (0, slopes['y0'], plate - slopes['y0'] * y0),
             'y1': (0, -slopes['y1'], plate + slopes['y1'] * y1)}
    if section['kind'] == 'flat':
        return [(0, 0, plate)]
    if section['kind'] == 'shed':
        return [edges[section['low_side']]]
    sides = (('x0', 'x1') if section.get('ridge') == 'y' else ('y0', 'y1'))
    return [edges[side] for side in (sides if section['kind'] == 'gable' else edges)]


def _cut_length(wall, top, roofs):
    """Integrate exactly along the outside face (the drawn exterior line).

    Coverage edges and plane/threshold crossings partition the wall into
    intervals on which the visible envelope stays above or below top - 2.
    No roof means no surface cutting the wall.
    """
    start, end = wall['from'], wall['to']
    delta = [end[i] - start[i] for i in (0, 1)]
    length = math.hypot(*delta)
    if length < 3:
        return 0
    threshold = top - 2
    cuts = {0., 1.}
    for bounds, planes in roofs:
        for axis in (0, 1):
            if abs(delta[axis]) > _EPS:
                cuts.update((edge - start[axis]) / delta[axis]
                            for edge in (bounds[axis], bounds[axis + 2]))
        for a, b, c in planes:
            slope = a * delta[0] + b * delta[1]
            if abs(slope) > _EPS:
                cuts.add((threshold - a * start[0] - b * start[1] - c) / slope)
    cuts = sorted(t for t in cuts if 0 <= t <= 1)
    cut = 0
    for lo, hi in zip(cuts, cuts[1:]):
        t = (lo + hi) / 2
        x, y = [start[i] + delta[i] * t for i in (0, 1)]
        heights = [min(a * x + b * y + c for a, b, c in planes)
                   for (x0, y0, x1, y1), planes in roofs
                   if x0 <= x <= x1 and y0 <= y <= y1]
        if heights and max(heights) < threshold - _EPS:
            cut += (hi - lo) * length
    return cut


def _inside(point, polygon):
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def _distance(point, wall):
    start, end = wall['from'], wall['to']
    delta = [end[i] - start[i] for i in (0, 1)]
    length2 = sum(d * d for d in delta)
    t = max(0, min(1, sum((point[i] - start[i]) * delta[i] for i in (0, 1)) / length2)) if length2 else 0
    return math.dist(point, [start[i] + t * delta[i] for i in (0, 1)])


def _full_height(wall):
    return wall.get('exterior') is True and wall.get('height', 0) >= 6


def _bearing_area(rect, level, walls):
    """One-foot cells, weighted at the edges, over the full-height area only.

    Draft rooms are not read yet. Use the nearest wall to distinguish a
    knee-wall wing from the full-height block in a shared level outline;
    ties with a knee wall stay exempt.
    """
    outline = level.get('outline') or []
    if level.get('half') or not outline or not any(_full_height(w) for w in walls):
        return 0
    x0 = max(rect[0], min(p[0] for p in outline))
    y0 = max(rect[1], min(p[1] for p in outline))
    x1 = min(rect[2], max(p[0] for p in outline))
    y1 = min(rect[3], max(p[1] for p in outline))
    if x1 <= x0 or y1 <= y0:
        return 0
    area = 0
    for ix in range(math.floor(x0), math.ceil(x1)):
        left, right = max(ix, x0), min(ix + 1, x1)
        for iy in range(math.floor(y0), math.ceil(y1)):
            front, rear = max(iy, y0), min(iy + 1, y1)
            point = ((left + right) / 2, (front + rear) / 2)
            if not _inside(point, outline):
                continue
            distances = [(_distance(point, w), w) for w in walls]
            nearest = min(d for d, _ in distances)
            if all(_full_height(w) for d, w in distances if d <= nearest + _EPS):
                area += (right - left) * (rear - front)
    return area


def roof_issues(building) -> list[dict]:
    """Find contradictions without changing the building or deciding its roof."""
    levels = building.get('levels', [])
    sections = [s for s in building.get('roof', {}).get('sections', []) if s.get('state') != 'ghost']
    walls = [w for w in building.get('walls', []) if w.get('state') != 'ghost']
    ground = min((l['elevation'] for l in levels), default=0)
    upper = [l for l in levels if l['elevation'] > ground]
    roofs = []
    for section in sections:
        x0, y0, x1, y1 = section['rect']
        overhang = section.get('overhang', 0)
        roofs.append(((x0 - overhang, y0 - overhang, x1 + overhang, y1 + overhang), _planes(section)))
    issues = []
    for level in upper:
        polygon = level.get('outline') or [w[key] for w in walls for key in ('from', 'to')]
        if not polygon:
            continue
        for index, wall in enumerate(walls):
            if wall.get('level') != level['id'] or not _full_height(wall):
                continue
            if _cut_length(wall, level['elevation'] + wall['height'], roofs) < 3 - _EPS:
                continue
            axis = 0 if abs(wall['to'][0] - wall['from'][0]) < abs(wall['to'][1] - wall['from'][1]) else 1
            line = (wall['from'][axis] + wall['to'][axis]) / 2
            side = (('left', 'right') if axis == 0 else ('front', 'rear'))[
                abs(line - max(p[axis] for p in polygon)) < abs(line - min(p[axis] for p in polygon))]
            issues.append({'id': f"upper_walls_cut:{level['id']}:{wall.get('id', index)}",
                           'kind': 'upper_walls_cut',
                           'from': list(wall['from']), 'to': list(wall['to']),
                           'text': f"The upper floor's wall along the {side} stands above the roof there; "
                                   "the roof over it should rest at the upper floor's height."})
    for section in sections:
        sid = section['id']
        width, depth = [section['rect'][i + 2] - section['rect'][i] for i in (0, 1)]
        short, long = sorted((width, depth))
        across_short = width < depth if section.get('ridge') == 'x' else depth < width
        if section['kind'] == 'hip' and across_short and long - short >= .25 * short - _EPS:
            issues.append({'id': f'hip_point:{sid}', 'section': sid, 'kind': 'hip_point',
                           'text': f'Section {sid} is a hip with its ridge across its shorter side, so it comes to a point; '
                                   "check the ridge direction and the section's extent against the roof plan."})
        for level in upper:
            if section['plate'] > level['elevation']:
                continue
            level_walls = [w for w in walls if w.get('level') == level['id']]
            if _bearing_area(section['rect'], level, level_walls) + _EPS < width * depth / 2:
                continue
            issues.append({'id': f"bears_below_floor:{sid}:{level['id']}", 'section': sid,
                           'kind': 'bears_below_floor',
                           'text': f"The roof over the {level.get('name') or 'upper floor'} rests at or below "
                                   "that floor, beneath its full-height outside walls."})
    return issues
