"""Roof areas and hosted cross gables, adapted to the section renderer."""

from copy import deepcopy
import math

from services import twin_blocks, twin_joints, twin_roof_issues
from services.twin_model_supports import is_supported, carry_fields, wall_axis


_EPS = 1e-8
_SIDES = ('y0', 'x1', 'y1', 'x0')


def _segments(area):
    return list(zip(area, area[1:] + area[:1]))


def _edge(a, b):
    axis = 0 if abs(a[0] - b[0]) <= _EPS else 1
    return axis, a[axis], min(a[1 - axis], b[1 - axis]), max(a[1 - axis], b[1 - axis])


def _metadata(piece, excluded):
    return {key: deepcopy(value) for key, value in piece.items() if key not in excluded}


def from_section(section: dict) -> dict:
    """Convert a rectangular section without changing its drawn roof planes."""
    roof = _metadata(section, {'rect', 'ends', 'pitches', 'low_side', 'dormer_of', 'plane_edges',
                               'gutters', 'downspouts'})
    if 'plane_edges' in section and 'plane_materials' in roof:
        # A section becomes a canonical rectangle, whose edge order may differ
        # from the authored area's (and whose other sections have other edges).
        refs = roof['plane_materials']
        roof['plane_materials'] = {str(i): deepcopy(refs[str(section['plane_edges'][side])])
                                  for i, side in enumerate(_SIDES)
                                  if str(section['plane_edges'].get(side)) in refs}
        if not roof['plane_materials']:
            roof.pop('plane_materials')
    x0, y0, x1, y1 = section['rect']
    roof['area'] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    kind = section['kind']
    ridge = section.get('ridge', 'x')
    ends = (ridge + '0', ridge + '1')
    pitches = section.get('pitches') or {}
    roof['edges'] = []
    for index, side in enumerate(_SIDES):
        setting = 'sloped'
        if kind == 'shed':
            setting = 'sloped' if side == section['low_side'] else 'gable'
        elif kind in ('gable', 'hip') and side in ends:
            setting = section.get('ends', {}).get(side, kind)
            if setting == 'hip':
                setting = 'sloped'
        roof['edges'].append({'setting': setting,
                              'pitch': 0 if kind == 'flat' else pitches.get(side, section['pitch'])})
        authored = section.get('edges', [])
        if isinstance(authored, list) and index < len(authored) and isinstance(authored[index], dict):
            roof['edges'][-1].update(_metadata(authored[index], {'gutters', 'downspouts', 'setting', 'pitch'}))
        if section.get('gutters', {}).get(side) is True:
            roof['edges'][-1]['gutter'] = True
        if side in section.get('downspouts', {}):
            roof['edges'][-1]['downspouts'] = deepcopy(section['downspouts'][side])
    return roof


def _rectangles(area):
    if len(area) < 4 or any(
            (abs(a[0] - b[0]) > _EPS and abs(a[1] - b[1]) > _EPS)
            or math.dist(a, b) <= _EPS for a, b in _segments(area)):
        raise ValueError('Roof areas must have square corners.')
    xs = sorted({p[0] for p in area})
    ys = sorted({p[1] for p in area})
    cells = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1)
             if twin_blocks._inside(area, (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2)}
    seeds = twin_blocks._partition(cells, xs, ys)
    pending = [(xs.index(r[0]), ys.index(r[1]), xs.index(r[2]), ys.index(r[3])) for r in seeds]
    seen, maximal = set(), set()
    while pending:
        rect = pending.pop()
        if rect in seen:
            continue
        seen.add(rect)
        i0, j0, i1, j1 = rect
        extensions = []
        for candidate in ((i0 - 1, j0, i1, j1), (i0, j0 - 1, i1, j1),
                          (i0, j0, i1 + 1, j1), (i0, j0, i1, j1 + 1)):
            a, b, c, d = candidate
            if (0 <= a < c < len(xs) and 0 <= b < d < len(ys)
                    and all((i, j) in cells for i in range(a, c) for j in range(b, d))):
                extensions.append(candidate)
        if extensions:
            pending.extend(extensions)
        else:
            maximal.add(rect)
    return [[xs[a], ys[b], xs[c], ys[d]] for a, b, c, d in sorted(maximal)]


def _rectangle_edge_indices(roof, rect):
    """Map each section side to its authored area edge, or None for an interior side."""
    x0, y0, x1, y1 = rect
    points = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    result = {}
    for side, (a, b) in zip(_SIDES, _segments(points)):
        axis, line, start, end = _edge(a, b)
        candidates = []
        for i, (p, q) in enumerate(_segments(roof['area'])):
            other, value, lo, hi = _edge(p, q)
            overlap = min(end, hi) - max(start, lo)
            if axis == other and abs(value - line) <= _EPS and overlap > _EPS:
                candidates.append((overlap, -i))
        # Extended rectangles normally meet a boundary on all four sides.
        result[side] = -max(candidates)[1] if candidates else None
    return result


def _rectangle_edges(roof, rect):
    return {side: roof['edges'][index] if index is not None else {
        'setting': 'sloped', 'pitch': roof.get('pitch', 8)}
        for side, index in _rectangle_edge_indices(roof, rect).items()}


def _section(roof, rect, edges):
    section = _metadata(roof, {'area', 'edges', 'kind', 'pitch', 'ridge'})
    section.update(rect=list(rect), roof=roof['id'])
    sloped = {side: e.get('pitch', roof.get('pitch', 8)) for side, e in edges.items()
              if e['setting'] != 'gable'}
    gables = [side for side, e in edges.items() if e['setting'] in ('gable', 'clip', 'clipped')]
    ridge = (gables[0][0] if gables else roof.get('ridge')) or (
        'x' if rect[2] - rect[0] >= rect[3] - rect[1] else 'y')
    if len(sloped) == 4 and all(abs(p) <= _EPS for p in sloped.values()):
        section.update(kind='flat', pitch=0)
        return section
    if len(sloped) == 1:
        side, pitch = next(iter(sloped.items()))
        section.update(kind='shed', low_side=side, pitch=pitch)
        return section
    kind = 'gable' if gables else 'hip'
    across = ('y0', 'y1') if ridge == 'x' else ('x0', 'x1')
    # Schema 2 can label the same mixed-end planes either hip or gable.
    # Retain that source label only while it still describes these planes.
    if roof.get('kind') in ('gable', 'hip') and all(edges[s]['setting'] == 'sloped' for s in across):
        kind = roof['kind']
    section.update(kind=kind, ridge=ridge,
                   pitch=roof.get('pitch', next(iter(sloped.values()), 8)))
    section['ends'] = {side: ('hip' if edges[side]['setting'] == 'sloped' else
                              'clip' if edges[side]['setting'] in ('clip', 'clipped') else 'gable')
                       for side in (ridge + '0', ridge + '1')}
    if sloped and (len(set(sloped.values())) > 1 or any(p != section['pitch'] for p in sloped.values())):
        section['pitches'] = sloped
    elif sloped:
        section['pitch'] = next(iter(sloped.values()))
    return section


def eave_edge_indices(roof: dict) -> set[int]:
    """Authored indices of the actual horizontal eaves, matching gutters.js.

    Resolve through the same partition and plane_edges as the flat view; a
    sloped label alone does not make a shed's high side an eave.
    """
    result = set()
    for section in to_sections(roof):
        for side, index in section['plane_edges'].items():
            if index is None or roof['edges'][index]['setting'] != 'sloped':
                continue
            kind = section['kind']
            if (kind == 'flat' or kind == 'shed' and section['low_side'] == side
                    or kind in ('hip', 'gable') and (side[0] != section['ridge']
                        or section.get('ends', {}).get(side, kind) == 'hip')):
                result.add(index)
    return result


def to_sections(roof: dict) -> list[dict]:
    """Extend partition rectangles to the boundary, inheriting edge settings."""
    rectangles = _rectangles(roof['area'])
    sections = []
    for i, rect in enumerate(rectangles):
        edges = _rectangle_edges(roof, rect)
        section = _section(roof, rect, edges)
        # Keep opt-in edge data without adding fields to legacy flat sections.
        known = {'setting', 'pitch', 'wall', 'wall_offset', 'gutter', 'downspouts', 'gutter_ack'}
        if any(set(e) - known for e in edges.values()):
            section['edges'] = [deepcopy(edges[side]) for side in _SIDES]
        section['plane_edges'] = _rectangle_edge_indices(roof, rect)
        carry_fields(roof, section, overwrite=True)
        if 'edges' in section:
            corners = [[rect[0], rect[1]], [rect[2], rect[1]], [rect[2], rect[3]], [rect[0], rect[3]]]
            for index, side in enumerate(_SIDES):
                origin = section['plane_edges'][side]
                if origin is None:
                    continue
                axis = _edge(*_segments(roof['area'])[origin])[0]
                for key, coordinate in (('wall_offset', axis), ('wall_along_offset', 1-axis)):
                    value = section['edges'][index].get(key)
                    if type(value) in (int, float):
                        section['edges'][index][key] = value + corners[index][coordinate] - roof['area'][origin][coordinate]
        for field, key in (('gutters', 'gutter'), ('downspouts', 'downspouts')):
            values = {side: deepcopy(roof['edges'][index][key])
                      for side, index in section['plane_edges'].items()
                      if index is not None and key in roof['edges'][index]
                      and (roof['edges'][index][key] is True if key == 'gutter'
                           else isinstance(roof['edges'][index][key], list))}
            if values:
                section[field] = values
        section['id'] = roof['id'] if len(rectangles) == 1 else f"{roof['id']}~{i + 1}"
        sections.append(section)
    return sections


def _wall_lines(walls, joints):
    points = {j['id']: j['at'] for j in joints} if isinstance(joints, list) else joints
    result = []
    for wall in walls:
        ids = wall.get('joints', [])
        if len(ids) == 2 and all(j in points for j in ids):
            result.append(dict(wall, **{'from': points[ids[0]], 'to': points[ids[1]]}))
    return result


def attach_edges(roof: dict, walls: list, joints) -> dict:
    """Record wall references and signed offsets, leaving migrated areas fixed."""
    roof = deepcopy(roof)
    roof['edges'] = [deepcopy(edge) for edge in roof['edges']]
    lines = _wall_lines(walls, joints)
    if is_supported(roof):
        host = roof.get('host')
        roof.pop('host', None)
        candidates = []
        for i, (a, b) in enumerate(_segments(roof['area'])):
            axis, line, start, end = _edge(a, b)
            for wall in lines:
                if wall.get('level') != roof.get('level') or wall_axis(wall['from'], wall['to']) != axis:
                    continue
                named = ((isinstance(host, dict) and host.get('wall') == wall['id'] and host.get('edge') == i)
                         or roof['edges'][i].get('wall') == wall['id'])
                overlap = twin_joints._overlap(start, end, wall['from'][1-axis], wall['to'][1-axis])
                distance = abs(wall['from'][axis] - line)
                if named or (wall.get('exterior') and wall.get('state') != 'ghost'
                             and overlap > _EPS
                             and distance <= roof.get('overhang', 1) + .5 + _EPS):
                    candidates.append((not named, distance, -overlap, i, wall['id'], axis, line, wall))
        if candidates:
            _, _, _, i, _, axis, line, wall = min(candidates, key=lambda c: c[:5])
            roof['host'] = {'wall': wall['id'], 'edge': i}
            roof['edges'][i].update(wall=wall['id'], wall_offset=line-wall['from'][axis],
                                   wall_along_offset=roof['area'][i][1-axis]-wall['from'][1-axis])
        return roof
    # The caller has resolved the bearing level (R10). This API has no level
    # elevations; neutral heights let _bearing apply its plan-line, storey,
    # exterior and settled-wall filters without inventing floor elevations.
    floor = roof['plate'] - 1
    building = {'levels': [{'id': lid, 'elevation': floor} for lid in {w['level'] for w in lines}],
                'walls': [dict(w, height=1) for w in lines]}
    for edge, (a, b) in zip(roof['edges'], _segments(roof['area'])):
        axis, line, start, end = _edge(a, b)
        candidates = [w for w in twin_joints._bearing(building, roof, (axis, line, start, end))
                      if abs(w['from'][axis] - line) <= roof['overhang'] + .5 + _EPS]
        if candidates:
            wall = min(candidates, key=lambda w: (abs(w['from'][axis] - line),
                        -twin_joints._overlap(start, end, w['from'][1 - axis], w['to'][1 - axis]), w['id']))
            edge.update(wall=wall['id'], wall_offset=line - wall['from'][axis])
        else:
            edge.pop('wall', None)
            edge.pop('wall_offset', None)
    return roof


def follow_walls(roof: dict, walls: list, joints) -> dict:
    """Keep each attached edge's original offset as its wall line moves."""
    roof = deepcopy(roof)
    lines = {w['id']: w for w in _wall_lines(walls, joints)}
    if is_supported(roof):
        host = roof.get('host', {})
        wall = lines.get(host.get('wall'))
        index = host.get('edge')
        if wall is not None and wall.get('level') != roof.get('level'):
            roof.pop('host', None)
            return roof
        if wall is not None and type(index) is int and 0 <= index < len(roof['area']):
            a, b = _segments(roof['area'])[index]
            axis, line, _, _ = _edge(a, b)
            if wall_axis(wall['from'], wall['to']) == axis:
                edge = roof['edges'][index]
                delta = [0, 0]
                delta[axis] = wall['from'][axis] + edge.get('wall_offset', 0) - line
                delta[1-axis] = wall['from'][1-axis] + edge.get('wall_along_offset', a[1-axis]-wall['from'][1-axis]) - a[1-axis]
                for point in roof['area']:
                    for k in (0, 1):
                        point[k] += delta[k]
                for point in roof['support'].get('at', {}).values():
                    for k in (0, 1):
                        point[k] += delta[k]
                if roof.get('roof_frame'):
                    for k in (0, 1):
                        roof['roof_frame']['origin'][k] += delta[k]
        return roof
    for i, (edge, (a, b)) in enumerate(zip(roof['edges'], _segments(deepcopy(roof['area'])))):
        wall = lines.get(edge.get('wall'))
        if wall is None or 'wall_offset' not in edge:
            continue
        axis, _, _, _ = _edge(a, b)
        if twin_joints._axis(wall) != axis:
            continue
        value = wall['from'][axis] + edge['wall_offset']
        roof['area'][i][axis] = value
        roof['area'][(i + 1) % len(roof['area'])][axis] = value
    return roof


def dormer_from_section(section: dict, parent_roof: dict) -> dict:
    """Locate a stored cross gable along its parent's eave."""
    axis = 0 if section['ridge'] == 'x' else 1
    rect = section['rect']
    centre = (rect[1 - axis] + rect[3 - axis]) / 2
    candidates = []
    for i, (a, b) in enumerate(_segments(parent_roof['area'])):
        other, line, lo, hi = _edge(a, b)
        if other == axis and lo - _EPS <= centre <= hi + _EPS:
            distance = min(abs(line - rect[axis]), abs(line - rect[axis + 2]))
            candidates.append((distance, i, a, b))
    if not candidates:
        raise ValueError('The dormer needs a roof edge beneath it.')
    _, edge, a, b = min(candidates)
    direction = 1 if b[1 - axis] > a[1 - axis] else -1
    dormer = _metadata(section, {'rect', 'kind', 'ridge', 'dormer_of', 'level', 'plate'})
    dormer.update(roof=parent_roof['id'], edge=edge, at=(centre - a[1 - axis]) * direction,
                  width=rect[3 - axis] - rect[1 - axis],
                  plate_offset=section['plate'] - parent_roof['plate'])
    return dormer


def dormer_sections(dormer: dict, roof: dict) -> list[dict]:
    """Run a cross gable from the hosted eave to the main roof's crest."""
    a, b = _segments(roof['area'])[dormer['edge']]
    length = math.dist(a, b)
    tangent = [(b[i] - a[i]) / length for i in (0, 1)]
    centre = [a[i] + tangent[i] * dormer['at'] for i in (0, 1)]
    orientation = sum(p[0] * q[1] - p[1] * q[0] for p, q in _segments(roof['area']))
    sign = 1 if orientation > 0 else -1
    inward = [-tangent[1] * sign, tangent[0] * sign]
    axis = 0 if abs(inward[0]) > .5 else 1
    parents = [s for s in to_sections(roof)
               if all(s['rect'][i] - _EPS <= centre[i] <= s['rect'][i + 2] + _EPS for i in (0, 1))]
    if not parents:
        return []
    parent = max(parents, key=lambda s: twin_blocks._area(s['rect']))
    far = parent['rect'][axis + 2] if inward[axis] > 0 else parent['rect'][axis]
    depth = abs(far - centre[axis])
    planes = [(p[0] * inward[0] + p[1] * inward[1],
               p[0] * centre[0] + p[1] * centre[1] + p[2]) for p in twin_roof_issues._planes(parent)]
    stops = {0, depth}
    for i, (slope, height) in enumerate(planes):
        for other_slope, other_height in planes[i + 1:]:
            if abs(slope - other_slope) > _EPS:
                at = (other_height - height) / (slope - other_slope)
                if 0 <= at <= depth:
                    stops.add(at)
    depth = max(stops, key=lambda t: (min(s * t + h for s, h in planes), -t))
    end = centre[axis] + inward[axis] * depth
    rect = [0, 0, 0, 0]
    rect[axis], rect[axis + 2] = sorted((centre[axis], end))
    rect[1 - axis] = centre[1 - axis] - dormer['width'] / 2
    rect[3 - axis] = centre[1 - axis] + dormer['width'] / 2
    section = _metadata(dormer, {'roof', 'edge', 'at', 'width', 'plate_offset'})
    section.update(kind='gable', ridge='xy'[axis], rect=rect, dormer_of=list(parent['rect']),
                   plate=roof['plate'] + dormer.get('plate_offset', 0),
                   overhang=dormer.get('overhang', roof['overhang']), roof=roof['id'])
    if 'level' in roof:
        section['level'] = roof['level']
    if 'support' in roof:
        section['support'] = deepcopy(roof['support'])
    return [section]
