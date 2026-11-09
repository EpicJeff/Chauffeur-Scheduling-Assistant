"""Pure wall-network geometry, in feet in a single level's frame."""

from collections import Counter, deque
from copy import deepcopy
import math


_EPS = 1e-9
_TOL = 0.05


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _delta(a, b):
    return [b[0] - a[0], b[1] - a[1]]


def weld(points: list[list[float]], tol=1.0, *, separate=()) -> tuple[list[list[float]], list[int]]:
    """Average points strictly within tol, keeping separate index pairs apart.

    Wall-aware callers pass each wall's two endpoint indices in separate (R13).
    """
    owners = list(range(len(points)))
    groups = {i: [i] for i in owners}
    blocked = {frozenset(pair) for pair in separate}
    pairs = sorted((math.dist(a, b), i, j) for i, a in enumerate(points)
                   for j, b in enumerate(points[:i]) if math.dist(a, b) < tol)
    for _, i, j in pairs:
        a, b = owners[i], owners[j]
        if a == b:
            continue
        if any(math.dist(points[k], points[l]) >= tol or frozenset((k, l)) in blocked
               for k in groups[a] for l in groups[b]):
            continue
        a, b = min(a, b), max(a, b)
        for k in groups.pop(b):
            owners[k] = a
            groups[a].append(k)
    positions, indices = [], [0] * len(points)
    for members in groups.values():
        for i in members:
            indices[i] = len(positions)
        positions.append([sum(points[i][axis] for i in members) / len(members)
                          for axis in (0, 1)])
    return positions, indices


def _interior_parameter(point, a, b):
    vector = _delta(a, b)
    length2 = sum(x * x for x in vector)
    if length2 <= _EPS * _EPS:
        return None
    t = sum(x * y for x, y in zip(_delta(a, point), vector)) / length2
    if not _EPS < t < 1 - _EPS:
        return None
    projected = [a[i] + t * vector[i] for i in (0, 1)]
    return t if math.dist(point, projected) <= _TOL + _EPS else None


def split_crossings(joints: dict[str, list], walls: list[dict]) -> tuple[dict, list[dict]]:
    """Split at existing near-interior joints and proper segment crossings."""
    result_joints = deepcopy(joints)
    cuts = []
    for wall in walls:
        a, b = wall['joints']
        parts = {a: 0.0, b: 1.0}
        for jid, point in joints.items():
            if jid not in parts:
                t = _interior_parameter(point, joints[a], joints[b])
                if t is not None:
                    parts[jid] = t
        cuts.append(parts)

    next_joint = 1
    for i, wall in enumerate(walls):
        a, b = [joints[jid] for jid in wall['joints']]
        vector = _delta(a, b)
        for k in range(i):
            c, d = [joints[jid] for jid in walls[k]['joints']]
            other = _delta(c, d)
            denominator = _cross(vector, other)
            if abs(denominator) <= _EPS * math.hypot(*vector) * math.hypot(*other):
                continue
            between = _delta(a, c)
            t = _cross(between, other) / denominator
            u = _cross(between, vector) / denominator
            if not (_EPS < t < 1 - _EPS and _EPS < u < 1 - _EPS):
                continue
            point = [a[axis] + t * vector[axis] for axis in (0, 1)]
            jid = next((jid for jid, p in result_joints.items()
                        if math.dist(point, p) <= _EPS), None)
            if jid is None:
                # A near-end T can also be a proper crossing. Reuse the T's
                # joint rather than leaving a tiny extra wall between them.
                jid = next((jid for jid in cuts[i] if jid in cuts[k]
                            and math.dist(point, result_joints[jid]) <= _TOL + _EPS), None)
            if jid is None:
                while f'j:{next_joint}' in result_joints:
                    next_joint += 1
                jid = f'j:{next_joint}'
                result_joints[jid] = point
                next_joint += 1
            cuts[i].setdefault(jid, t)
            cuts[k].setdefault(jid, u)

    segments = [[(a, b) for a, b in zip(ordered, ordered[1:])
                 if math.dist(result_joints[a], result_joints[b]) > _EPS]
                for ordered in (sorted(parts, key=parts.get) for parts in cuts)]
    counts = Counter(jid for parts in segments for pair in parts for jid in pair)
    result_walls = []
    used_ids = {wall['id'] for wall in walls}
    for wall, parts in zip(walls, segments):
        if len(parts) > 1:
            # Only a split's terminal, free-ended tail is a read overshoot.
            # Real short walls and short pieces between junctions survive.
            parts = [(a, b) for i, (a, b) in enumerate(parts)
                     if not (i in (0, len(parts) - 1)
                             and math.dist(result_joints[a], result_joints[b]) < 1.0
                             and ((counts[a] == 1 and counts[b] >= 3)
                                  or (counts[b] == 1 and counts[a] >= 3)))]
        suffix = 2
        for i, (a, b) in enumerate(parts):
            part = deepcopy(wall)
            part['joints'] = [a, b]
            if i:
                while f"{wall['id']}~{suffix}" in used_ids:
                    suffix += 1
                part['id'] = f"{wall['id']}~{suffix}"
                used_ids.add(part['id'])
                suffix += 1
            result_walls.append(part)
    return result_joints, result_walls


def regions(joints, walls) -> list[dict]:
    """Walk half-edges clockwise at each joint, retaining bounded CCW faces."""
    neighbours = {jid: set() for jid in joints}
    for wall in walls:
        a, b = wall['joints']
        if a != b and math.dist(joints[a], joints[b]) > _EPS:
            neighbours[a].add(b)
            neighbours[b].add(a)

    # A free-ended branch must not appear as an excursion in a room polygon.
    leaves = deque(jid for jid, edges in neighbours.items() if len(edges) == 1)
    while leaves:
        a = leaves.popleft()
        if len(neighbours[a]) != 1:
            continue
        b = neighbours[a].pop()
        neighbours[b].remove(a)
        if len(neighbours[b]) == 1:
            leaves.append(b)

    ordered = {a: sorted(edges, key=lambda b: math.atan2(
        joints[b][1] - joints[a][1], joints[b][0] - joints[a][0]))
        for a, edges in neighbours.items()}
    following = {(a, b): (b, ordered[b][(ordered[b].index(a) - 1) % len(ordered[b])])
                 for a, edges in ordered.items() for b in edges}
    visited, result = set(), []
    for start in following:
        if start in visited:
            continue
        edge, ids = start, []
        while edge not in visited:
            visited.add(edge)
            ids.append(edge[0])
            edge = following[edge]
        polygon = [list(joints[jid]) for jid in ids]
        area = sum(_cross(a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1])) / 2
        if area > _EPS:
            result.append({'joints': ids, 'polygon': polygon, 'area': area})
    return result


def open_ends(joints, walls) -> list[list[float]]:
    """Positions of joints incident to exactly one wall."""
    counts = Counter(jid for wall in walls for jid in set(wall['joints']))
    return [list(point) for jid, point in joints.items() if counts[jid] == 1]


def _offset(point, direction, width, side):
    return [point[0] - side * direction[1] * width,
            point[1] + side * direction[0] * width]


def _intersection(a, direction, b, other):
    denominator = _cross(direction, other)
    if abs(denominator) <= _EPS:
        return list(a)
    t = _cross(_delta(a, b), other) / denominator
    return [a[i] + t * direction[i] for i in (0, 1)]


def _opposite(a, b):
    return (abs(_cross(a, b)) <= math.sin(math.radians(3)) + _EPS
            and sum(x * y for x, y in zip(a, b)) < 0)


def footprints(joints, walls) -> dict[str, list[list[float]]]:
    """Offset solid walls, joining corners and butting stems per ruling R6."""
    outgoing = {jid: [] for jid in joints}
    solids = []
    for wall in walls:
        if wall.get('kind', 'solid') != 'solid':
            continue
        a, b = wall['joints']
        vector = _delta(joints[a], joints[b])
        length = math.hypot(*vector)
        if length <= _EPS:
            continue
        direction = [x / length for x in vector]
        width = wall.get('thickness', 0.5) / 2
        solids.append(wall)
        outgoing[a].append((wall['id'], direction, width))
        outgoing[b].append((wall['id'], [-x for x in direction], width))
    for edges in outgoing.values():
        edges.sort(key=lambda edge: math.atan2(edge[1][1], edge[1][0]))

    def end(jid, wid):
        edges = outgoing[jid]
        index = next(i for i, edge in enumerate(edges) if edge[0] == wid)
        _, direction, width = edges[index]
        point = joints[jid]
        square = [_offset(point, direction, width, side) for side in (1, -1)]

        def meet(offset, other, other_width, side):
            face = _offset(point, other, other_width, side)
            corner = _intersection(offset, direction, face, other)
            # Widths are half-thicknesses; limit to twice the larger thickness.
            return corner if math.dist(point, corner) <= 4 * max(width, other_width) else offset

        if len(edges) == 1:
            return square
        continuation = next((edge for edge in edges if edge[0] != wid
                             and _opposite(direction, edge[1])), None)
        if continuation is not None:
            # Same-face intersections close a slightly kinked through wall at
            # its bisector. Exact collinearity retains the square R6 ends.
            _, other, other_width = continuation
            return [meet(offset, other, other_width, -side)
                    for side, offset in zip((1, -1), square)]
        through = next((edge for i, edge in enumerate(edges)
                        if any(_opposite(edge[1], other[1]) for other in edges[i + 1:])), None)
        if through is not None:
            _, other, other_width = through
            side = 1 if _cross(other, direction) > 0 else -1
            return [meet(offset, other, other_width, side) for offset in square]
        corners = []
        for side, offset in zip((1, -1), square):
            _, other, other_width = edges[(index + side) % len(edges)]
            corners.append(meet(offset, other, other_width, -side))
        return corners

    result = {}
    for wall in solids:
        a, b = wall['joints']
        from_left, from_right = end(a, wall['id'])
        # At the far end the outgoing direction reverses left and right.
        to_right, to_left = end(b, wall['id'])
        result[wall['id']] = [from_left, to_left, to_right, from_right]
    return result
