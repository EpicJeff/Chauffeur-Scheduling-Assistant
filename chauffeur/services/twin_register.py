"""Pure sheet-to-building registration and rigid building placement math.

Sheet pixels run right/down; building feet run right/rear. All angles are
degrees counterclockwise, and all returned points are fresh lists.
"""

import math


def _rotate(point, angle):
    radians = math.radians(angle)
    c, s = math.cos(radians), math.sin(radians)
    x, y = point
    return [c * x - s * y, s * x + c * y]


def make(scale: float, angle: float = 0.0, origin_px=(0, 0), offset=(0, 0)) -> dict:
    """Build a registration with a positive scale in feet per pixel."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Scale must be positive and finite")
    return {"scale": scale, "angle": angle,
            "origin_px": list(origin_px), "offset": list(offset)}


def apply(reg, point_px) -> list:
    """Flip sheet y, scale, rotate, then translate into building feet."""
    ox, oy = reg["origin_px"]
    scale = reg["scale"]
    x, y = _rotate(((point_px[0] - ox) * scale,
                    (oy - point_px[1]) * scale), reg["angle"])
    dx, dy = reg["offset"]
    return [x + dx, y + dy]


def invert(reg, point_ft) -> list:
    """Undo a registration, returning sheet pixels."""
    dx, dy = reg["offset"]
    x, y = _rotate((point_ft[0] - dx, point_ft[1] - dy), -reg["angle"])
    ox, oy = reg["origin_px"]
    return [ox + x / reg["scale"], oy - y / reg["scale"]]


def from_dimension(a_px, b_px, feet) -> float:
    """Find feet per pixel from a measured span of at least one pixel."""
    distance = math.hypot(b_px[0] - a_px[0], b_px[1] - a_px[1])
    if not math.isfinite(distance) or distance < 1:
        raise ValueError("Sheet points must be at least one pixel apart")
    if not math.isfinite(feet) or feet <= 0:
        raise ValueError("Dimension must be positive and finite")
    return feet / distance


def from_two_points(a_px, b_px, a_ft, b_ft) -> dict:
    """Recover scale, rotation and placement from two corresponding points."""
    dx, dy = b_ft[0] - a_ft[0], b_ft[1] - a_ft[1]
    scale = from_dimension(a_px, b_px, math.hypot(dx, dy))
    # The sheet vector must have its y flipped before measuring its angle.
    sheet_angle = math.atan2(a_px[1] - b_px[1], b_px[0] - a_px[0])
    angle = math.degrees(math.atan2(dy, dx) - sheet_angle)
    return make(scale, angle, origin_px=a_px, offset=a_ft)


def from_points(px: list, ft: list) -> tuple[dict, float]:
    """Least-squares similarity fit, with sheet y flipped and RMS in feet."""
    if len(px) != len(ft) or len(px) < 2:
        raise ValueError('At least two corresponding point pairs are needed')
    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in [*px, *ft]):
        raise ValueError('Points must have two finite coordinates')
    origin, offset = _centroid(px), _centroid(ft)
    sheet = [(p[0] - origin[0], origin[1] - p[1]) for p in px]
    feet = [(p[0] - offset[0], p[1] - offset[1]) for p in ft]
    spread = math.fsum(x * x + y * y for x, y in sheet)
    if spread <= 0:
        raise ValueError('Sheet points must be distinct')
    a = math.fsum(x * u + y * v for (x, y), (u, v) in zip(sheet, feet)) / spread
    b = math.fsum(x * v - y * u for (x, y), (u, v) in zip(sheet, feet)) / spread
    reg = make(math.hypot(a, b), math.degrees(math.atan2(b, a)), origin, offset)
    rms = math.sqrt(math.fsum(math.dist(apply(reg, p), q) ** 2 for p, q in zip(px, ft)) / len(px))
    return reg, rms


def _centroid(points):
    return [sum(p[axis] for p in points) / len(points) for axis in (0, 1)]


def _outline_samples(outline, count=256):
    """Sample a closed perimeter uniformly, independent of vertex density."""
    edges = [(p, q, math.hypot(q[0] - p[0], q[1] - p[1]))
             for p, q in zip(outline, outline[1:] + outline[:1])]
    edges = [(p, q, length) for p, q, length in edges if length]
    if not edges:
        return [list(outline[0])]
    step = sum(length for _, _, length in edges) / count
    samples = []
    edge, start = 0, 0.0
    for i in range(count):
        distance = i * step
        while edge < len(edges) - 1 and distance > start + edges[edge][2]:
            start += edges[edge][2]
            edge += 1
        p, q, length = edges[edge]
        fraction = (distance - start) / length
        samples.append([p[0] + fraction * (q[0] - p[0]),
                        p[1] + fraction * (q[1] - p[1])])
    return samples


def _nearest_on_edges(point, edges):
    """Return the closest point on any closed-polygon segment."""
    best, best_error = None, math.inf
    for p, dx, dy, length_squared in edges:
        fraction = (((point[0] - p[0]) * dx + (point[1] - p[1]) * dy)
                    / length_squared) if length_squared else 0.0
        fraction = max(0.0, min(1.0, fraction))
        target = [p[0] + fraction * dx, p[1] + fraction * dy]
        error = (point[0] - target[0]) ** 2 + (point[1] - target[1]) ** 2
        if error < best_error:
            best, best_error = target, error
    return best, best_error


def _merge_collinear(outline):
    """Drop redundant fixed vertices without changing the closed perimeter."""
    def straight(a, b, c):
        ux, uy = b[0] - a[0], b[1] - a[1]
        vx, vy = c[0] - b[0], c[1] - b[1]
        return (ux * vx + uy * vy >= 0
                and abs(ux * vy - uy * vx)
                <= 1e-12 * math.hypot(ux, uy) * math.hypot(vx, vy))

    vertices = []
    for p in outline:
        if vertices and p == vertices[-1]:
            continue
        while len(vertices) > 1 and straight(vertices[-2], vertices[-1], p):
            vertices.pop()
        vertices.append(p)
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    while len(vertices) > 2:
        if straight(vertices[-2], vertices[-1], vertices[0]):
            vertices.pop()
        elif straight(vertices[-1], vertices[0], vertices[1]):
            vertices.pop(0)
        else:
            break
    return vertices


def _edge_tree(edges):
    """Index edge bounds once so dense outlines need fewer exact projections."""
    bounds = (min(min(p[0], p[0] + dx) for p, dx, dy, _ in edges),
              min(min(p[1], p[1] + dy) for p, dx, dy, _ in edges),
              max(max(p[0], p[0] + dx) for p, dx, dy, _ in edges),
              max(max(p[1], p[1] + dy) for p, dx, dy, _ in edges))
    if len(edges) <= 4:
        return bounds, None, None, edges
    axis = 0 if bounds[2] - bounds[0] >= bounds[3] - bounds[1] else 1
    ordered = sorted(edges, key=lambda edge: edge[0][axis] + edge[axis + 1] / 2)
    middle = len(ordered) // 2
    return bounds, _edge_tree(ordered[:middle]), _edge_tree(ordered[middle:]), None


def _bounds_error(point, bounds):
    dx = max(bounds[0] - point[0], 0.0, point[0] - bounds[2])
    dy = max(bounds[1] - point[1], 0.0, point[1] - bounds[3])
    return dx * dx + dy * dy


def _nearest_indexed(point, edges, tree):
    """Exact nearest segment, pruning only bounds farther than the best hit."""
    if tree is None:
        return _nearest_on_edges(point, edges)
    best, best_error = None, math.inf
    pending = [(0.0, tree)]
    while pending:
        lower_bound, node = pending.pop()
        if lower_bound > best_error:
            continue
        _, left, right, leaf = node
        if leaf is not None:
            target, error = _nearest_on_edges(point, leaf)
            if error < best_error:
                best, best_error = target, error
            continue
        left_error = _bounds_error(point, left[0])
        right_error = _bounds_error(point, right[0])
        # Visit the nearer child first, tightening the bound for the other.
        if left_error < right_error:
            pending.extend(((right_error, right), (left_error, left)))
        else:
            pending.extend(((left_error, left), (right_error, right)))
    return best, best_error


def fit_outline(moving_ft: list, fixed_ft: list) -> tuple:
    """Return the preferred rigid perimeter fit and its trimmed RMS in feet."""
    return fit_outline_candidates(moving_ft, fixed_ft)[0]


def fit_outline_candidates(moving_ft: list, fixed_ft: list) -> list:
    """Refine one rigid fit per quarter turn, ordered by trimmed RMS.

    Outlines are ordered, closed polygon boundaries; the closing vertex may
    be omitted. Uniform moving-perimeter samples match fixed edges, retaining
    the closest 80% for both least squares and RMS so a cut corner cannot pull
    the whole trace sideways. RMS ties within 0.05 ft prefer the smallest
    absolute rotation. Inputs are never mutated and scale is never fitted.
    Each outline needs at least three points. Refinement stops below 1e-6 ft
    RMS improvement, with at most 100 iterations per seed.
    """
    if (not moving_ft or not fixed_ft
            or len(moving_ft) < 3 or len(fixed_ft) < 3):
        raise ValueError("Both outlines must contain at least three points")
    if any(not math.isfinite(value)
           for outline in (moving_ft, fixed_ft) for p in outline for value in p):
        raise ValueError("Outline coordinates must be finite")

    moving_samples = _outline_samples(moving_ft)
    moving_center = _centroid(moving_samples)
    fixed_samples = _outline_samples(fixed_ft)
    fixed_center = _centroid(fixed_samples)
    centered = [[p[0] - moving_center[0], p[1] - moving_center[1]]
                for p in moving_samples]
    fixed_vertices = _merge_collinear(fixed_ft)
    edges = []
    for p, q in zip(fixed_vertices, fixed_vertices[1:] + fixed_vertices[:1]):
        dx, dy = q[0] - p[0], q[1] - p[1]
        edges.append((p, dx, dy, dx * dx + dy * dy))
    tree = _edge_tree(edges) if len(edges) > 12 else None
    keep = max(1, math.ceil(len(centered) * 0.8))
    candidates = []

    for seed in (0.0, 90.0, 180.0, 270.0):
        angle = seed
        center = fixed_center[:]
        best_move, best_error = None, math.inf
        previous_rms = math.inf
        for _ in range(100):
            rotated = [_rotate(p, angle) for p in centered]
            placed = [[p[0] + center[0], p[1] + center[1]] for p in rotated]
            matches = [(_nearest_indexed(p, edges, tree), r)
                       for p, r in zip(placed, rotated)]
            matches.sort(key=lambda match: match[0][1])
            retained = matches[:keep]
            targets = [match[0][0] for match in retained]
            sources = [match[1] for match in retained]
            error = sum(match[0][1] for match in retained) / keep
            if error < best_error:
                origin = _rotate(moving_center, angle)
                best_move = {"angle": (angle + 180) % 360 - 180,
                             "offset": [center[0] - origin[0],
                                        center[1] - origin[1]]}
                best_error = error

            rms = math.sqrt(error)
            if previous_rms - rms < 1e-6:
                break
            previous_rms = rms
            source_center, target_center = _centroid(sources), _centroid(targets)
            # Least-squares incremental rotation about the retained centroid.
            cross = dot = 0.0
            for p, q in zip(sources, targets):
                px, py = p[0] - source_center[0], p[1] - source_center[1]
                qx, qy = q[0] - target_center[0], q[1] - target_center[1]
                cross += px * qy - py * qx
                dot += px * qx + py * qy
            delta = math.degrees(math.atan2(cross, dot))
            # Keep each seed in its quarter-turn basin so another seed cannot
            # replace the half-turn alternative with a duplicate of the winner.
            next_angle = max(seed - 45.0, min(seed + 45.0, angle + delta))
            delta = next_angle - angle
            rx, ry = _rotate(source_center, delta)
            next_center = [target_center[0] - rx, target_center[1] - ry]
            shift = math.hypot(next_center[0] - center[0],
                               next_center[1] - center[1])
            if abs(delta) < 1e-12 and shift < 1e-10:
                break
            angle = next_angle
            center = next_center

        rms = round(math.sqrt(best_error), 12)
        # Remove floating-point noise from exact fits, including symmetries.
        candidates.append((best_move, 0.0 if rms < 1e-9 else rms))

    # Symmetric seeds have the same objective, but may converge at slightly
    # different rates. Share the better equivalent fit when RMS ties within
    # 0.05 ft. This preserves actual RMS ordering as well as the smaller-turn
    # preference, without treating unrelated, unequal fits as interchangeable.
    for turn in (90.0, 180.0, 270.0):
        symmetric = True
        for p in fixed_samples + fixed_ft:
            x, y = _rotate((p[0] - fixed_center[0],
                            p[1] - fixed_center[1]), turn)
            _, error = _nearest_indexed((x + fixed_center[0],
                                         y + fixed_center[1]), edges, tree)
            if error > 1e-16:
                symmetric = False
                break
        if not symmetric:
            continue
        for move, rms in candidates[:]:
            angle = (move['angle'] + turn + 180) % 360 - 180
            for i, seed in enumerate((0.0, 90.0, 180.0, 270.0)):
                seed_delta = (angle - seed + 180) % 360 - 180
                if (abs(seed_delta) <= 45.0
                        and 0 < candidates[i][1] - rms <= 0.05):
                    x, y = _rotate((move['offset'][0] - fixed_center[0],
                                    move['offset'][1] - fixed_center[1]), turn)
                    candidates[i] = ({'angle': angle,
                                      'offset': [x + fixed_center[0],
                                                 y + fixed_center[1]]}, rms)

    return sorted(candidates, key=lambda candidate: (candidate[1],
                                                    abs(candidate[0]['angle'])))


def to_world(building, point_local) -> list:
    """Rotate a building-local point, then place it on the lot."""
    x, y = _rotate(point_local, building.get("rotation", 0.0))
    dx, dy = building.get("position", (0, 0))
    return [x + dx, y + dy]


def to_local(building, point_world) -> list:
    """Undo a building's lot placement and rotation."""
    dx, dy = building.get("position", (0, 0))
    return _rotate((point_world[0] - dx, point_world[1] - dy),
                   -building.get("rotation", 0.0))


def feet_inches(ft: float) -> str:
    """Format feet to the nearest whole inch, carrying inches into feet."""
    if not math.isfinite(ft):
        raise ValueError("Feet must be finite")
    total_inches = math.floor(abs(ft) * 12 + 0.5)
    feet, inches = divmod(total_inches, 12)
    sign = "-" if ft < 0 and total_inches else ""
    return f"{sign}{feet}'-{inches}\""
