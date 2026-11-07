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


def _centroid(points):
    return [sum(p[axis] for p in points) / len(points) for axis in (0, 1)]


def _nearest(point, fixed):
    return min(fixed, key=lambda q: (point[0] - q[0]) ** 2
                                   + (point[1] - q[1]) ** 2)


def fit_outline(moving_ft: list, fixed_ft: list) -> tuple:
    """Fit moving points to fixed points using rotation and translation only.

    Each quarter-turn seed starts with aligned centroids. Nearest-point
    correspondences supply centroid shifts and small-angle least-squares
    updates. RMS is the moving-to-fixed nearest-point distance in feet;
    point order and the number of points need not match. Symmetric outlines
    can have equally good placements; the first best candidate wins.
    """
    if not moving_ft or not fixed_ft:
        raise ValueError("Both outlines must contain points")
    if any(not math.isfinite(value)
           for outline in (moving_ft, fixed_ft) for p in outline for value in p):
        raise ValueError("Outline coordinates must be finite")

    moving_center = _centroid(moving_ft)
    fixed_center = _centroid(fixed_ft)
    centered = [[p[0] - moving_center[0], p[1] - moving_center[1]]
                for p in moving_ft]
    energy = sum(x * x + y * y for x, y in centered)
    best_move, best_error = None, math.inf

    for seed in (0.0, 90.0, 180.0, 270.0):
        angle = seed
        center = fixed_center[:]
        for _ in range(100):
            rotated = [_rotate(p, angle) for p in centered]
            placed = [[p[0] + center[0], p[1] + center[1]] for p in rotated]
            targets = [_nearest(p, fixed_ft) for p in placed]
            error = sum((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                        for p, q in zip(placed, targets)) / len(placed)
            if error < best_error:
                origin = _rotate(moving_center, angle)
                best_move = {"angle": (angle + 180) % 360 - 180,
                             "offset": [center[0] - origin[0],
                                        center[1] - origin[1]]}
                best_error = error

            target_center = _centroid(targets)
            # Linearize R(delta) * p as p + delta * [-p.y, p.x].
            cross = sum(p[0] * (q[1] - target_center[1])
                        - p[1] * (q[0] - target_center[0])
                        for p, q in zip(rotated, targets))
            delta = cross / energy if energy else 0.0
            shift = math.hypot(target_center[0] - center[0],
                               target_center[1] - center[1])
            if abs(delta) < 1e-12 and shift < 1e-10:
                break
            angle += math.degrees(delta)
            center = target_center

    return best_move, math.sqrt(best_error)


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
    total_inches = math.floor(abs(ft) * 12 + 0.5)
    feet, inches = divmod(total_inches, 12)
    sign = "-" if ft < 0 and total_inches else ""
    return f"{sign}{feet}'-{inches}\""
