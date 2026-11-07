"""Deterministic, storage-free yard composition in plan feet.

Only compose-owned items are replaced. IDs are assigned before applying edits,
so deleting or moving one item cannot renumber the rest of the generated yard.
All geometry uses simple polygons and standard-library segment mathematics.
"""

from copy import deepcopy
from math import hypot
from random import Random

from services import twin_register


_EPS = 1e-6


def _pairs(poly):
    return zip(poly, poly[1:] + poly[:1])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _along(a, vector, distance):
    return [a[0] + vector[0] * distance, a[1] + vector[1] * distance]


def _segment_distance(p, a, b):
    dx, dy = _sub(b, a)
    length2 = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2)) if length2 else 0
    return hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _inside(p, poly):
    """Boundary-inclusive point-in-polygon."""
    inside = False
    for a, b in _pairs(poly):
        if _segment_distance(p, a, b) <= _EPS:
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
                inside = not inside
    return inside


def _cuts(a, b, c, d):
    """Parameters on a..b at crossings, including collinear overlap ends."""
    v, w, delta = _sub(b, a), _sub(d, c), _sub(c, a)
    denom = _cross(v, w)
    if abs(denom) > _EPS:
        t, u = _cross(delta, w) / denom, _cross(delta, v) / denom
        return [max(0, min(1, t))] if -_EPS <= t <= 1 + _EPS and -_EPS <= u <= 1 + _EPS else []
    length2 = v[0] ** 2 + v[1] ** 2
    if not length2 or abs(_cross(delta, v)) > _EPS:
        return []
    return [max(0, min(1, (_sub(p, a)[0] * v[0] + _sub(p, a)[1] * v[1]) / length2))
            for p in (c, d)
            if _segment_distance(p, a, b) <= _EPS]


def _poly_distance(p, poly):
    return 0 if _inside(p, poly) else min(_segment_distance(p, a, b) for a, b in _pairs(poly))


def _segment_poly_distance(a, b, poly):
    if _inside(a, poly) or _inside(b, poly):
        return 0
    distances = []
    for c, d in _pairs(poly):
        if _cuts(a, b, c, d):
            return 0
        distances.extend((_segment_distance(a, c, d), _segment_distance(b, c, d),
                          _segment_distance(c, a, b), _segment_distance(d, a, b)))
    return min(distances)


def _overlap(left, right):
    """Positive-area overlap; a shared edge or corner is safe for beds."""
    def interior(p, poly):
        return _inside(p, poly) and all(_segment_distance(p, a, b) > _EPS for a, b in _pairs(poly))

    for poly, other in ((left, right), (right, left)):
        for a, b in _pairs(poly):
            cuts = sorted({0, 1} | {t for c, d in _pairs(other) for t in _cuts(a, b, c, d)})
            if any(interior(_along(a, _sub(b, a), (lo + hi) / 2), other)
                   for lo, hi in zip(cuts, cuts[1:])):
                return True
    # The left polygon is a bed rectangle: identical boundaries also overlap.
    return interior([sum(p[i] for p in left) / len(left) for i in (0, 1)], right)


def _pieces(a, b, blockers, lot=None):
    """Split a segment at polygon crossings and retain its lawn intervals."""
    cuts = {0.0, 1.0}
    for poly in blockers + ([lot] if lot else []):
        for c, d in _pairs(poly):
            cuts.update(_cuts(a, b, c, d))
    v = _sub(b, a)
    cuts = sorted(cuts)
    for start, end in zip(cuts, cuts[1:]):
        if (end - start) * hypot(*v) <= _EPS:
            continue
        middle = _along(a, v, (start + end) / 2)
        if (not lot or _inside(middle, lot)) and not any(_inside(middle, p) for p in blockers):
            yield [_along(a, v, start), _along(a, v, end)]


def _loops(walls):
    """Join unordered/reversed exterior wall segments into closed footprints."""
    remaining = [(w['from'], w['to']) for w in walls]
    loops = []
    while remaining:
        a, b = remaining.pop(0)
        loop = [a, b]
        while hypot(*_sub(loop[-1], loop[0])) > _EPS:
            for index, (c, d) in enumerate(remaining):
                if hypot(*_sub(loop[-1], c)) <= _EPS:
                    loop.append(d)
                elif hypot(*_sub(loop[-1], d)) <= _EPS:
                    loop.append(c)
                else:
                    continue
                remaining.pop(index)
                break
            else:
                break
        if len(loop) >= 4 and hypot(*_sub(loop[-1], loop[0])) <= _EPS:
            loops.append(loop[:-1])
    return loops


def _building_geometry(buildings, notes):
    footprints, porches, sides = [], [], []
    for building in buildings:
        ground = min((level['elevation'] for level in building['levels']), default=0)
        levels = {level['id'] for level in building['levels'] if level['elevation'] == ground}
        walls = deepcopy([w for w in building['walls'] if w.get('exterior') and w['level'] in levels])
        for wall in walls:
            for key in ('from', 'to'):
                wall[key] = twin_register.to_world(building, wall[key])
        loops = _loops(walls)
        footprints.extend(loops)
        porch = building.get('porch') or {}
        if porch.get('polygon'):
            porches.append([twin_register.to_world(building, p) for p in porch['polygon']])
        for wall in walls:
            a, b = wall['from'], wall['to']
            length = hypot(*_sub(b, a))
            u = [(b[0] - a[0]) / length, (b[1] - a[1]) / length]
            n, half = [u[1], -u[0]], wall['thickness'] / 2
            # Include wall thickness and square end caps in clearance geometry.
            start, end = _along(a, u, -half), _along(b, u, half)
            footprints.append([_along(start, n, half), _along(end, n, half),
                               _along(end, n, -half), _along(start, n, -half)])
            middle = _along(a, u, length / 2)
            plus = any(_inside(_along(middle, n, half + _EPS * 10), p) for p in loops)
            minus = any(_inside(_along(middle, n, -half - _EPS * 10), p) for p in loops)
            if plus == minus:
                notes.append(f"Skipped foundation wall {wall['id']}: no unambiguous closed exterior footprint.")
                continue
            if plus:
                n = [-n[0], -n[1]]
            sides.append((wall, u, n, length, building.get('openings', [])))
    return footprints + porches, porches, sides


def compose(plan: dict, kit: dict, seed: int = 1) -> tuple[dict, list[str]]:
    """Return a composed copy, retaining foreign items and recorded edits.

    Plans are normalized Task 1 plans, kits supply the composition rule values.
    Recorded moves apply where current lot and obstacle clearances permit.
    """
    result, notes, rng = deepcopy(plan), [], Random(seed)
    site, rules = result['site'], kit['composition']
    for name in ('beds', 'planting', 'edges'):
        site[name] = [item for item in site.get(name, []) if item.get('by') != 'compose']
    overrides = site.setdefault('compose_overrides', {'removed': [], 'moved': {}})
    removed, moved = set(overrides.get('removed', [])), overrides.get('moved', {})
    counts = {'bed': 0, 'shrub': 0, 'tree': 0, 'edge': 0}
    generated = {name: [] for name in ('beds', 'planting', 'edges')}

    def item(rule, **fields):
        counts[rule] += 1
        return {'id': f'cmp-{rule}-{counts[rule]}', 'by': 'compose', **fields}

    lot = site.get('lot') or []
    if len(lot) < 3:
        notes.append('Skipped yard composition: site.lot needs a polygon.')
        return result, notes
    footprint, porches, sides = _building_geometry(result['buildings'], notes)
    hardscape = [h['polygon'] for h in site.get('hardscape', []) if h.get('polygon')]
    pool = (site.get('pool') or {}).get('polygon') or []
    depth = rules['foundation_bed_depth_ft']
    bed_axes = []
    for wall, u, n, length, openings in sides:
        a = _along(wall['from'], n, wall['thickness'] / 2)
        b = _along(a, u, length)
        beds = [b['polygon'] for b in site['beds'] + generated['beds'] if b.get('polygon')]
        # An isolated corner touch does not suppress an adjacent wall's bed.
        free = sum(hypot(*_sub(p[1], p[0])) for p in _pieces(a, b, hardscape + porches + beds))
        if free < length - _EPS:
            continue
        spans = [(0, length)]
        for opening in openings:
            if opening.get('wall') != wall['id'] or opening['sill'] != 0:
                continue
            low = opening['at'] - opening['width'] / 2 - rules['door_clearance_ft']
            high = opening['at'] + opening['width'] / 2 + rules['door_clearance_ft']
            spans = [(lo, hi) for start, end in spans
                     for lo, hi in ((start, min(end, low)), (max(start, high), end)) if hi - lo > _EPS]
        for start, end in spans:
            p, q = _along(a, u, start), _along(a, u, end)
            polygon = [p, q, _along(q, n, depth), _along(p, n, depth)]
            if any(_overlap(polygon, poly) for poly in footprint + hardscape + beds):
                continue
            if pool and (any(_inside(pt, polygon) for pt in pool)
                         or any(_segment_poly_distance(a, b, pool) < rules['pool_clearance_ft'] - _EPS
                                for a, b in _pairs(polygon))):
                continue
            if any(abs(sum(hypot(*_sub(part[1], part[0])) for part in _pieces(a, b, [], lot))
                       - hypot(*_sub(b, a))) > _EPS for a, b in _pairs(polygon)):
                continue
            bed = item('bed', polygon=polygon, material='mulch')
            generated['beds'].append(bed)
            # Canonical increasing long axis keeps any partial group at the end.
            if end - start >= depth:
                p, q = _along(p, n, depth / 2), _along(q, n, depth / 2)
            else:
                p = _along(p, u, (end - start) / 2)
                q = _along(p, n, depth)
            if (p[0], p[1]) > (q[0], q[1]):
                p, q = q, p
            bed_axes.append((bed, p, q))

    obstacles = footprint + hardscape
    occupied = list(site['planting'])

    def clear_ground(at):
        if not _inside(at, lot) or any(_inside(at, p) for p in obstacles):
            return False
        if pool and _poly_distance(at, pool) < rules['pool_clearance_ft'] + _EPS:
            return False
        return True

    def placeable(at, kind):
        if not clear_ground(at):
            return False
        for plant in occupied:
            if 'at' not in plant:
                continue
            # Four feet for trees, one foot for shrubs (below shrub spacing).
            radius = 4 if kind == 'tree' or plant.get('kind') == 'tree' else 1
            if hypot(*_sub(at, plant['at'])) < radius - _EPS:
                return False
        return True

    def plant(kind, at, preset, height):
        # Generate with the same collision occupancy even when overridden. This
        # preserves the IDs and random stream of all later candidates.
        if placeable(at, kind):
            candidate = item(kind, kind=kind, at=at, preset=preset,
                             height=height, seed=rng.randrange(2 ** 31))
            generated['planting'].append(candidate)
            occupied.append(candidate)

    for bed, a, b in bed_axes:
        length = hypot(*_sub(b, a))
        u = [(b[0] - a[0]) / length, (b[1] - a[1]) / length]
        spacing = rules['shrub_spacing_ft']
        distance, remaining, previous = spacing / 2, 0, None
        while distance < length:
            at = _along(a, u, distance)
            if not placeable(at, 'shrub'):
                distance += spacing
                continue
            if remaining == 0:
                choices = [p for p in kit['shrubs'] if p != previous] or kit['shrubs']
                previous = rng.choice(choices)
                remaining = rng.choice(rules['group_sizes'])
            plant('shrub', at, previous, rng.uniform(*rules['shrub_height_ft']))
            remaining -= 1
            distance += spacing

    # A lot edge qualifies only if its ENTIRE segment clears all footprints.
    area2 = sum(_cross(a, b) for a, b in _pairs(lot))
    lot_edges = list(_pairs(lot))
    qualifies = [all(_segment_poly_distance(a, b, p) >= rules['backdrop_min_building_ft'] - _EPS
                     for p in footprint) for a, b in lot_edges]
    corner_margin = 6 + (rules['backdrop_rows'] - 1) * rules['backdrop_row_gap_ft'] + 4 + _EPS * 10
    for index, (a, b) in enumerate(lot_edges):
        if not qualifies[index]:
            continue
        length = hypot(*_sub(b, a))
        if length <= _EPS:
            continue
        u = [(b[0] - a[0]) / length, (b[1] - a[1]) / length]
        inward = [-u[1], u[0]] if area2 > 0 else [u[1], -u[0]]
        for row in range(rules['backdrop_rows']):
            origin = _along(a, inward, 6 + row * rules['backdrop_row_gap_ft'])
            distance = rules['backdrop_spacing_ft'] / 2
            if qualifies[index - 1]:
                distance = max(distance, corner_margin)
            end = length - (corner_margin if qualifies[(index + 1) % len(lot_edges)] else 0)
            while distance < end:
                at = _along(origin, u, distance)
                if all(_poly_distance(at, p) >= rules['backdrop_min_building_ft'] - _EPS for p in footprint):
                    plant('tree', at, rng.choice(kit['backdrop_trees']), rng.uniform(*rules['backdrop_height_ft']))
                distance += rules['backdrop_spacing_ft'] + rng.uniform(-rules['backdrop_jitter_ft'], rules['backdrop_jitter_ft'])

    # Generate every rule before applying overrides; even bed deletions must
    # leave other items' numbering unchanged. Beds, shrubs and edges are
    # independently editable items rather than an implicit deletion cascade.
    bed_polygons = [b['polygon'] for b in site['beds'] + generated['beds'] if b.get('polygon')]
    for index, poly in enumerate(hardscape):
        blockers = footprint + bed_polygons + hardscape[:index] + hardscape[index + 1:]
        if pool:
            blockers = blockers + [pool]
        for a, b in _pairs(poly):
            for points in _pieces(a, b, blockers, lot):
                generated['edges'].append(item('edge', points=points))
    for index, poly in enumerate(bed_polygons):
        blockers = obstacles + bed_polygons[:index] + bed_polygons[index + 1:]
        if pool:
            blockers = blockers + [pool]
        for a, b in _pairs(poly):
            for points in _pieces(a, b, blockers, lot):
                generated['edges'].append(item('edge', points=points))

    for name, items in generated.items():
        for entry in items:
            if entry['id'] in removed:
                continue
            if 'at' in entry and entry['id'] in moved:
                target = moved[entry['id']]
                if clear_ground(target):
                    entry['at'] = deepcopy(target)
                else:
                    notes.append(f"Skipped move for {entry['id']}: outside the lot or blocked "
                                 'by a building, porch, hardscape or pool clearance.')
            site[name].append(entry)
    return result, notes
