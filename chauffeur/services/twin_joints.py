"""Explicit, in-place joint repair for one building, in feet.

This is a publication pass, not a loader or a normalizer. Person geometry is
an anchor; read geometry may join it even when it is off the inch grid.
"""
from copy import deepcopy
from collections import Counter
import math

from services import twin_plan


_EPS = 1e-9
_SQUARE = math.tan(math.radians(3))


def _person(piece, pinned=()):
    return bool((piece.get('src') or {}).get('person')) or piece.get('id') in pinned


def _inch(value):
    return round(value * 12) / 12


def _roundable(piece):
    # Shell dimensions come from an accepted footprint, not a drawing read.
    return not _person(piece) and (piece.get('src') or {}).get('step') != 'shell'


def _axis(wall, near=False):
    """The coordinate constant along a horizontal or vertical wall."""
    dx, dy = [abs(wall['to'][i] - wall['from'][i]) for i in (0, 1)]
    if dy <= (_SQUARE * dx if near else _EPS):
        return 1
    if dx <= (_SQUARE * dy if near else _EPS):
        return 0
    return None


def _overlap(a, b, c, d):
    return min(max(a, b), max(c, d)) - max(min(a, b), min(c, d))


def _project(point, wall, segment=False):
    a, b = wall['from'], wall['to']
    delta = [b[i] - a[i] for i in (0, 1)]
    length2 = sum(v * v for v in delta)
    t = sum((point[i] - a[i]) * delta[i] for i in (0, 1)) / length2
    if segment:
        t = max(0, min(1, t))
    projected = [a[i] + t * delta[i] for i in (0, 1)]
    return list(point) if math.dist(point, projected) <= _EPS else projected


class _Groups:
    """Small constraint groups, refusing incompatible fixed coordinates."""
    def __init__(self, count, fixed=None):
        self.owner = list(range(count))
        self.members = {i: {i} for i in range(count)}
        self.fixed = dict(fixed or {})

    def join(self, a, b):
        a, b = self.owner[a], self.owner[b]
        if a == b:
            return True
        if a in self.fixed and b in self.fixed and self.fixed[a] != self.fixed[b]:
            return False
        if b in self.fixed:
            self.fixed[a] = self.fixed[b]
        for i in self.members[b]:
            self.owner[i] = a
        self.members[a].update(self.members.pop(b))
        self.fixed.pop(b, None)
        return True


def _walls_on_level(walls, lower, counts, pinned):
    ends = [(w, key) for w in walls for key in ('from', 'to')]
    points = [list(w[key]) for w, key in ends]
    corners = _Groups(len(ends))
    pairs = sorted((math.dist(a, b), i, j) for i, a in enumerate(points)
                   for j, b in enumerate(points[:i])
                   if ends[i][0] is not ends[j][0] and math.dist(a, b) <= 1 + _EPS)
    for _, i, j in pairs:
        a, b = corners.owner[i], corners.owner[j]
        if a == b:
            continue
        members = corners.members[a] | corners.members[b]
        # No chain of near ends may drag a distant end into a weld, or fold a
        # short wall onto itself. Distinct person corners remain distinct.
        if len({id(ends[k][0]) for k in members}) != len(members):
            continue
        if any(math.dist(points[k], points[l]) > 1 + _EPS for k in members for l in members):
            continue
        anchors = {tuple(points[k]) for k in members if _person(ends[k][0], pinned)}
        if len(anchors) > 1:
            continue
        corners.join(i, j)
    joined = [members for members in corners.members.values()
              if len({tuple(points[k]) for k in members}) > 1]

    diagonal = {}
    for n, wall in enumerate(walls):
        if _person(wall, pinned) or not wall.get('exterior'):
            continue
        delta = [wall['to'][i] - wall['from'][i] for i in (0, 1)]
        candidates = []
        for support in lower:
            if not support.get('exterior') or _axis(support) is not None:
                continue
            vector = [support['to'][i] - support['from'][i] for i in (0, 1)]
            cross = abs(delta[0] * vector[1] - delta[1] * vector[0])
            if cross > math.sin(math.radians(3)) * math.hypot(*delta) * math.hypot(*vector):
                continue
            projected = [_project(p, support) for p in (wall['from'], wall['to'])]
            distance = max(math.dist(p, q) for p, q in zip((wall['from'], wall['to']), projected))
            along = 0 if abs(vector[0]) >= abs(vector[1]) else 1
            if distance <= 1 + _EPS and _overlap(projected[0][along], projected[1][along], support['from'][along], support['to'][along]) > _EPS:
                candidates.append((distance, projected))
        if candidates:
            distance, projected = min(candidates, key=lambda row: row[0])
            diagonal.update({2 * n: projected[0], 2 * n + 1: projected[1]})
            if distance > _EPS:
                counts['upper'].add(id(wall))
    coordinates = []
    for axis in (0, 1):
        fixed = {i: p[axis] for i, p in enumerate(points) if _person(ends[i][0], pinned)}
        # A diagonal bearing line can also be off the inch grid. As with a
        # person end, the joint takes precedence over coordinate rounding.
        fixed.update({i: p[axis] for i, p in diagonal.items()})
        groups = _Groups(len(ends), fixed)
        for members in corners.members.values():
            first = min(members)
            for i in members:
                groups.join(first, i)
        for n, wall in enumerate(walls):
            if not _person(wall, pinned) and _axis(wall, near=True) == axis:
                groups.join(2 * n, 2 * n + 1)
        # Lower floors have already settled. Only the floor immediately below
        # supplies anchors, and only overlapping parallel exterior walls do.
        for n, wall in enumerate(walls):
            if _person(wall, pinned) or not wall.get('exterior') or _axis(wall, near=True) != axis:
                continue
            other = 1 - axis
            candidates = [w for w in lower if w.get('exterior') and _axis(w) == axis
                          and _overlap(w['from'][other], w['to'][other],
                                       wall['from'][other], wall['to'][other]) > _EPS
                          and max(abs(p[axis] - w['from'][axis])
                                  for p in (wall['from'], wall['to'])) <= 1 + _EPS]
            if candidates:
                support = min(candidates, key=lambda w: sum(abs(p[axis] - w['from'][axis])
                                                           for p in (wall['from'], wall['to'])))
                roots = {groups.owner[2 * n], groups.owner[2 * n + 1]}
                value = support['from'][axis]
                if all(r not in groups.fixed or groups.fixed[r] == value for r in roots):
                    for r in roots:
                        groups.fixed[r] = value
                    if any(abs(p[axis] - value) > _EPS for p in (wall['from'], wall['to'])):
                        counts['upper'].add(id(wall))
        values = {}
        for root, members in groups.members.items():
            value = sum(points[i][axis] for i in members) / len(members)
            if all(_roundable(ends[i][0]) for i in members):
                value = _inch(value)
            elif len({points[i][axis] for i in members}) == 1:
                value = points[min(members)][axis]
            values[root] = (groups.fixed[root] if root in groups.fixed else
                            value)
        coordinates.append([values[groups.owner[i]] for i in range(len(ends))])
    for i, (wall, key) in enumerate(ends):
        if not _person(wall, pinned):
            wall[key] = [coordinates[axis][i] for axis in (0, 1)]
    for members in joined:
        if len({tuple(ends[i][0][ends[i][1]]) for i in members}) == 1:
            counts['corners'].add(tuple(sorted((id(ends[i][0]), ends[i][1]) for i in members)))
    for n, wall in enumerate(walls):
        if not _person(wall, pinned) and points[2 * n:2 * n + 2] != [wall['from'], wall['to']]:
            axis = _axis(wall)
            if axis is not None and points[2 * n][axis] != points[2 * n + 1][axis]:
                counts['square'].add(id(wall))


def _edges(section):
    x0, y0, x1, y1 = section['rect']
    return [(0, x0, y0, y1), (1, y0, x0, x1),
            (0, x1, y0, y1), (1, y1, x0, x1)]


def _bearing(building, section, edge):
    axis, _, start, end = edge
    levels = {l['id']: l for l in building.get('levels', [])}
    candidates = [w for w in building.get('walls', [])
                  if w.get('state') != 'ghost' and w.get('exterior') and _axis(w) == axis
                  and levels[w['level']]['elevation'] < section['plate']
                  and (not section.get('level') or section['level'] == w['level'])
                  and _overlap(start, end, w['from'][1 - axis], w['to'][1 - axis]) > _EPS]
    if not candidates:
        return []
    # A lower roof must not attach to a wall upstairs on the same plan line.
    distance = min(abs(levels[w['level']]['elevation'] + w['height'] - section['plate'])
                   for w in candidates)
    return [w for w in candidates
            if abs(levels[w['level']]['elevation'] + w['height'] - section['plate']) <= distance + _EPS]


def _meeting(a, b):
    for axis, line, start, end in _edges(a):
        for other_axis, other_line, c, d in _edges(b):
            if axis == other_axis and abs(line - other_line) <= _EPS and _overlap(start, end, c, d) > _EPS:
                return True
    return False


def _roof(building, counts, pinned):
    sections = [s for s in building.get('roof', {}).get('sections', []) if s.get('state') != 'ghost']
    for section in sections:
        if _person(section, pinned):
            continue
        rect = [_inch(v) for v in section['rect']] if _roundable(section) else list(section['rect'])
        for i, edge in enumerate(_edges(section)):
            axis, line, _, _ = edge
            candidates = [w for w in _bearing(building, section, edge)
                          if abs(w['from'][axis] - line) <= 1.5 + _EPS]
            if candidates:
                support = min(candidates, key=lambda w: abs(w['from'][axis] - line))
                rect[i] = support['from'][axis]
                if abs(rect[i] - line) > _EPS:
                    counts['edges'].add((id(section), i))
        if rect[0] < rect[2] and rect[1] < rect[3]:
            section['rect'] = rect
    # Solve plate joints together, so wall-top snapping and equalising neighbours
    # cannot undo one another on the next pass.
    groups = _Groups(len(sections), {i: s['plate'] for i, s in enumerate(sections) if _person(s, pinned)})
    for i, a in enumerate(sections):
        for j, b in enumerate(sections[:i]):
            if abs(a['plate'] - b['plate']) <= .5 + _EPS and _meeting(a, b):
                members = groups.members[groups.owner[i]] | groups.members[groups.owner[j]]
                if max(sections[k]['plate'] for k in members) - min(sections[k]['plate'] for k in members) <= .5 + _EPS:
                    groups.join(i, j)
    levels = {l['id']: l for l in building.get('levels', [])}
    for root, members in groups.members.items():
        if root in groups.fixed:
            value = groups.fixed[root]
        else:
            tops = [levels[w['level']]['elevation'] + w['height']
                    for i in members for edge in _edges(sections[i])
                    for w in _bearing(building, sections[i], edge)
                    if abs(w['from'][edge[0]] - edge[1]) <= _EPS]
            tops = [top for top in tops if all(abs(top - sections[i]['plate']) <= 1.5 + _EPS for i in members)]
            value = (min(tops, key=lambda top: sum(abs(top - sections[i]['plate']) for i in members))
                     if tops else sections[min(members)]['plate'])
        for i in members:
            if not _person(sections[i], pinned) and sections[i]['plate'] != value:
                sections[i]['plate'] = value
                counts['plates'].add(id(sections[i]))


def _awning_walls(building, awning):
    levels = {l['id']: l for l in building.get('levels', [])}
    return [w for w in building.get('walls', []) if w.get('exterior') and w.get('state') != 'ghost'
            and levels[w['level']]['elevation'] <= awning['eave'] < levels[w['level']]['elevation'] + w['height']]


def _awning_support(building, awning):
    candidates = _awning_walls(building, awning)
    existing = next((w for w in candidates if w['id'] == awning.get('wall')), None)
    if existing:
        return existing
    section = next((s for s in building.get('roof', {}).get('sections', [])
                    if s['id'] == awning.get('section')), None)
    if not section:
        return None
    ranked = []
    for wall in candidates:
        axis = _axis(wall, near=True)
        if axis is None:
            continue
        along = 1 - axis
        if min(wall['from'][along], wall['to'][along]) > awning['x0'] + _EPS or max(wall['from'][along], wall['to'][along]) < awning['x1'] - _EPS:
            continue
        line = (wall['from'][axis] + wall['to'][axis]) / 2
        # The section locates the awning's face; a projecting bay wall within
        # the roof-edge tolerance wins by proximity. Side spans run along y.
        distance = min(abs(line - section['rect'][axis]), abs(line - section['rect'][axis + 2]))
        if distance <= 1.5 + _EPS:
            front_distance = abs(line - section['rect'][1]) if axis == 1 else math.inf
            ranked.append((distance, front_distance, axis != 1, wall))
    return min(ranked, key=lambda row: row[:3])[3] if ranked else None


def _snap(building, pinned_walls, pinned_roofs):
    before = deepcopy(building)
    counts = {key: set() for key in ('corners', 'square', 'upper', 'edges', 'plates', 'awnings')}
    levels = sorted(building.get('levels', []), key=lambda l: l['elevation'])
    for level in levels:
        if _roundable(level):
            for key in ('outline', 'enclosed_outline'):
                if level.get(key):
                    level[key] = [[_inch(v) for v in p] for p in level[key]]
    # Resolve newly coincident constraints before publication, rather than
    # needing a second call to finish a corner exposed by squaring/rounding.
    for _ in range(len(building.get('walls', [])) + len(building.get('roof', {}).get('sections', [])) + 2):
        previous = deepcopy(building)
        lower = []
        for level in levels:
            walls = [w for w in building.get('walls', []) if w['level'] == level['id'] and w.get('state') != 'ghost']
            _walls_on_level(walls, lower, counts, pinned_walls)
            lower = walls
        _roof(building, counts, pinned_roofs)
        if building == previous:
            break
    for awning in building.get('roof', {}).get('extensions', []):
        if awning.get('kind') == 'awning' and not _person(awning):
            support = _awning_support(building, awning)
            if support and awning.get('wall') != support['id']:
                awning['wall'] = support['id']
                counts['awnings'].add(id(awning))
    if before == building:
        return []
    phrases = {'corners': ('Joined', 'wall corner'), 'square': ('Squared', 'wall'),
               'upper': ('Lined up', 'upper-floor wall'), 'edges': ('Lined up', 'roof edge'),
               'plates': ('Levelled', 'roof plate'), 'awnings': ('Attached', 'awning')}
    notes = [f'{verb} {len(counts[key])} {noun}' + ('' if len(counts[key]) == 1 else 's') +
             (' with their walls.' if key == 'edges' else '.')
             for key, (verb, noun) in phrases.items() if counts[key]]
    if not notes:
        notes.append('Rounded 1 building to the nearest inch.')
    return notes


def snap(building: dict) -> list[str]:
    """Repair building joints in place; return counted, plain-sentence notes."""
    before = deepcopy(building)
    original_walls = {w['id']: w for w in before.get('walls', [])}
    centres = {}
    for opening in before.get('openings', []):
        wall = original_walls.get(opening.get('wall'))
        if wall:
            length = math.dist(wall['from'], wall['to'])
            if length > _EPS:
                centres[opening['id']] = [wall['from'][i] + opening['at'] *
                                          (wall['to'][i] - wall['from'][i]) / length for i in (0, 1)]
    pinned_walls, pinned_roofs = set(), set()
    # Publication normalizes again. Do not let a shorter carrier silently
    # delete an existing window or door, including one placed by a person.
    while True:
        notes = _snap(building, pinned_walls, pinned_roofs)
        walls = {w['id']: w for w in building.get('walls', [])}
        # `at` is measured from the carrier's from end. Keep the opening's
        # world centre even when its provenance differs from the moved wall.
        # Reproject from the original centre on every retry, never cumulatively.
        for opening in building.get('openings', []):
            centre = centres.get(opening['id'])
            wall = walls.get(opening.get('wall'))
            if centre is None or wall is None:
                continue
            original = original_walls[wall['id']]
            if all(wall[key] == original[key] for key in ('from', 'to')):
                continue
            length = math.dist(wall['from'], wall['to'])
            if length > _EPS:
                at = sum((centre[i] - wall['from'][i]) * (wall['to'][i] - wall['from'][i])
                         for i in (0, 1)) / length
                opening['at'] = max(0, min(length, at))
        roofs = {s['id']: s for s in building.get('roof', {}).get('sections', [])}
        invalid = [o for o in building.get('openings', [])
                   if twin_plan._opening_error(o, walls, roofs)]
        new_walls = {o['wall'] for o in invalid if 'wall' in o} - pinned_walls
        new_walls.update(w['id'] for w in walls.values()
                         if math.dist(w['from'], w['to']) <= _EPS and w['id'] not in pinned_walls)
        new_roofs = {o['section'] for o in invalid if 'section' in o} - pinned_roofs
        if not new_walls and not new_roofs:
            return notes
        pinned_walls.update(new_walls)
        pinned_roofs.update(new_roofs)
        building.clear()
        building.update(deepcopy(before))


def _open_corners(walls):
    ends = [(wall, key) for wall in walls for key in ('from', 'to')
            if not any(other is not wall and math.dist(wall[key], _project(wall[key], other, segment=True)) <= _EPS
                       for other in walls)]
    # Two separated ends approaching the same intersection are one open
    # corner. Match the nearest such pair first; do not pair a wall with itself
    # or ends whose intersection is back inside either wall's span.
    pairs = []
    for i, (wall, key) in enumerate(ends):
        p = wall[key]
        u = [p[k] - wall['to' if key == 'from' else 'from'][k] for k in (0, 1)]
        for j, (other, other_key) in enumerate(ends[:i]):
            if other is wall:
                continue
            q = other[other_key]
            v = [q[k] - other['to' if other_key == 'from' else 'from'][k] for k in (0, 1)]
            delta = [q[k] - p[k] for k in (0, 1)]
            cross = u[0] * v[1] - u[1] * v[0]
            if abs(cross) > _EPS:
                t = (delta[0] * v[1] - delta[1] * v[0]) / cross
                s = (delta[0] * u[1] - delta[1] * u[0]) / cross
                if t < -_EPS or s < -_EPS:
                    continue
                distance = t * math.hypot(*u) + s * math.hypot(*v)
            else:
                if abs(delta[0] * u[1] - delta[1] * u[0]) > _EPS:
                    continue
                if sum(delta[k] * u[k] for k in (0, 1)) < -_EPS or sum(-delta[k] * v[k] for k in (0, 1)) < -_EPS:
                    continue
                distance = math.dist(p, q)
            pairs.append((distance, i, j))
    paired = set()
    count = len(ends)
    for _, i, j in sorted(pairs):
        if i not in paired and j not in paired:
            paired.update((i, j))
            count -= 1
    return count


def _bounds(building):
    points = [w[key] for w in building.get('walls', []) if w.get('exterior') and w.get('state') != 'ghost'
              for key in ('from', 'to')]
    if not points:
        points = [p for level in building.get('levels', []) for p in level.get('outline') or []]
    if not points:
        points = [s['rect'][i:i + 2] for s in building.get('roof', {}).get('sections', []) for i in (0, 2)]
    return [min((p[i] for p in points), default=0) for i in (0, 1)] + [
        max((p[i] for p in points), default=0) for i in (0, 1)]


def _side(bounds, axis, line):
    return (('left', 'right') if axis == 0 else ('front', 'rear'))[
        abs(line - bounds[axis + 2]) < abs(line - bounds[axis])]


def _awning_location(building, awning, bounds):
    section = next((s for s in building.get('roof', {}).get('sections', [])
                    if s['id'] == awning.get('section')), None)
    wall = next((w for w in building.get('walls', []) if w['id'] == awning.get('wall')), None)
    # An unassigned awning uses its section's y0 face in the renderer. Even
    # when no wall spans its eave, an opening below can still identify it.
    if wall is None and section:
        wall = next((w for w in building.get('walls', []) if w.get('exterior') and w.get('state') != 'ghost'
                     and _axis(w, near=True) == 1
                     and abs(w['from'][1] - section['rect'][1]) <= 1.5 + _EPS
                     and _overlap(w['from'][0], w['to'][0], awning['x0'], awning['x1']) > _EPS), None)
    axis = _axis(wall, near=True) if wall else None
    axis = 1 if axis is None else axis
    line = sum(wall[key][axis] for key in ('from', 'to')) / 2 if wall else section['rect'][1] if section else bounds[1]
    side = _side(bounds, axis, line)
    if wall:
        length = math.dist(wall['from'], wall['to'])
        for opening in building.get('openings', []):
            if opening.get('wall') != wall['id'] or length <= _EPS:
                continue
            along = wall['from'][1 - axis] + opening['at'] * (wall['to'][1 - axis] - wall['from'][1 - axis]) / length
            if awning['x0'] <= along <= awning['x1']:
                return f'over the {opening["kind"]} on the {side}'
    return f'on the {side}'


def _feet(value):
    return f'{value:.1f}'.removesuffix('.0')


def report(building: dict) -> list[str]:
    """Describe remaining open corners, unsupported roof edges and awnings."""
    messages = Counter()
    bounds = _bounds(building)

    def add(singular, plural, count=1):
        messages[singular, plural] += count

    walls = [w for w in building.get('walls', []) if w.get('exterior') and w.get('state') != 'ghost']
    for level in building.get('levels', []):
        floor = [w for w in walls if w['level'] == level['id']]
        corners = _open_corners(floor)
        if corners:
            name = level.get('name') or 'floor'
            add(f'1 outside corner on the {name} does not meet.',
                f'{{count}} outside corners on the {name} do not meet.', corners)
    sections = [s for s in building.get('roof', {}).get('sections', []) if s.get('state') != 'ghost']
    for section in sections:
        tops = []
        for edge in _edges(section):
            axis, line, start, end = edge
            # An internal edge shared with another roof is a roof joint, not
            # an unsupported eave. A partial overlap does not hide an open end.
            if any(other is not section and any(a == axis and abs(c - line) <= _EPS
                       and lo <= start + _EPS and hi >= end - _EPS
                       for a, c, lo, hi in _edges(other)) for other in sections):
                continue
            candidates = _bearing(building, section, edge)
            levels = {l['id']: l for l in building.get('levels', [])}
            tops.extend(levels[w['level']]['elevation'] + w['height'] for w in candidates
                        if abs(w['from'][axis] - line) <= _EPS)
            distance = min((abs(w['from'][axis] - line) for w in candidates), default=None)
            side = _side(bounds, axis, line)
            if distance is None:
                add(f'A roof edge over the {side} has no wall beneath it.',
                    f'{{count}} roof edges over the {side} have no wall beneath them.')
            elif distance > 1 / 12 + _EPS:
                add(f'A roof edge over the {side} is {_feet(distance)} ft from any wall.',
                    f'{{count}} roof edges over the {side} are {_feet(distance)} ft from any wall.')
        if tops:
            top = min(tops, key=lambda value: abs(value - section['plate']))
            gap = section['plate'] - top
            if abs(gap) > 1 / 12 + _EPS:
                direction = 'above' if gap > 0 else 'below'
                edge = min(_edges(section), key=lambda e: (
                    min(abs(e[1] - bounds[e[0]]), abs(e[1] - bounds[e[0] + 2])), e[0] != 1))
                side = _side(bounds, edge[0], edge[1])
                add(f'A roof plate over the {side} is {_feet(abs(gap))} ft {direction} its wall tops.',
                    f'{{count}} roof plates over the {side} are {_feet(abs(gap))} ft {direction} their wall tops.')
    for awning in building.get('roof', {}).get('extensions', []):
        if awning.get('kind') == 'awning' and not any(w['id'] == awning.get('wall') for w in _awning_walls(building, awning)):
            location = _awning_location(building, awning, bounds)
            add(f'The awning {location} has no wall to hang from.',
                f'{{count}} awnings {location} have no wall to hang from.')
    return [singular if count == 1 else plural.replace('{count}', str(count))
            for (singular, plural), count in messages.items()]
