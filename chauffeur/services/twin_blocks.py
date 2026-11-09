"""Deterministic rectangular roof footprints from settled storey outlines.

All coordinates are feet in the building frame: x follows the street and
y increases towards the rear. This module neither edits the plan nor reads
roof sections; low interior knee walls identify rooms under a lower roof.
"""

from collections import Counter
from functools import lru_cache
from io import BytesIO


_SNAP = 0.5
_MIN_SIDE = 7.0
_EPS = 1e-8


def _snap_map(values):
    counts = Counter(values)
    groups = []
    for value in sorted(counts):
        if not groups or value - groups[-1][0] > _SNAP + _EPS:
            groups.append([])
        groups[-1].append(value)
    # Frequency preserves the dominant wall line; the larger value breaks ties.
    return {v: max(group, key=lambda n: (counts[n], n))
            for group in groups for v in group}


def _inside(poly, x, y):
    hit = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if ((a[1] > y) != (b[1] > y)
                and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])):
            hit = not hit
    return hit


def _knee_rooms(walls, level):
    """Pair parallel low interior walls with at least four feet in common."""
    knees = sorted((w for w in walls if w.get('level') == level
                    and w.get('state') != 'ghost' and not w.get('exterior')
                    and 0 < w.get('height', 0) < 7),
                   key=lambda w: (tuple(w['from']), tuple(w['to'])))
    used, rooms = set(), []
    for i, a in enumerate(knees):
        if i in used:
            continue
        axis = (1 if abs(a['from'][0] - a['to'][0]) < _EPS else
                0 if abs(a['from'][1] - a['to'][1]) < _EPS else None)
        if axis is None:
            continue
        candidates = []
        for j in range(i + 1, len(knees)):
            b = knees[j]
            if j in used or abs(b['from'][1 - axis] - b['to'][1 - axis]) > _EPS:
                continue
            lo = max(min(a['from'][axis], a['to'][axis]),
                     min(b['from'][axis], b['to'][axis]))
            hi = min(max(a['from'][axis], a['to'][axis]),
                     max(b['from'][axis], b['to'][axis]))
            p, q = sorted((a['from'][1 - axis], b['from'][1 - axis]))
            if hi - lo >= 4 and q - p > _EPS:
                rect = [p, lo, q, hi] if axis else [lo, p, hi, q]
                candidates.append((q - p, j, rect))
        if candidates:
            _, j, rect = min(candidates)
            rooms.append(rect)
            used.update((i, j))
    return rooms


def _area(rect):
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _partition(cells, xs, ys):
    """Fewest exact rectangles, then largest sum of squared rectangle areas.

    A largest-first greedy cover can join distinct wings into one long strip.
    Enumerating rectangles at the first uncovered cell avoids that, while
    caching remaining masks and removing redundant grid lines keeps it small.
    """
    if not cells:
        return []
    nx, ny = len(xs) - 1, len(ys) - 1
    xcuts = [0] + [i for i in range(1, nx)
                   if any(((i - 1, j) in cells) != ((i, j) in cells)
                          for j in range(ny))] + [nx]
    ycuts = [0] + [j for j in range(1, ny)
                   if any(((i, j - 1) in cells) != ((i, j) in cells)
                          for i in range(nx))] + [ny]
    xx, yy = [xs[i] for i in xcuts], [ys[j] for j in ycuts]
    nx, ny = len(xx) - 1, len(yy) - 1
    mask = sum(1 << (i * ny + j) for i in range(nx) for j in range(ny)
               if (xcuts[i], ycuts[j]) in cells)

    @lru_cache(maxsize=None)
    def solve(free):
        if not free:
            return (), 0.0
        first = (free & -free).bit_length() - 1
        i0, j0 = divmod(first, ny)
        candidates = []
        strip = 0
        for j1 in range(j0, ny):
            strip |= 1 << j1
            if free & (strip << (i0 * ny)) != strip << (i0 * ny):
                break
            covered = 0
            for i1 in range(i0, nx):
                column = strip << (i1 * ny)
                if free & column != column:
                    break
                covered |= column
                rect = (xx[i0], yy[j0], xx[i1 + 1], yy[j1 + 1])
                candidates.append((_area(rect), rect, covered))
        best, best_score = None, -1.0
        for area, rect, covered in sorted(candidates, reverse=True):
            if covered == free:
                return (rect,), area * area
            tail, score = solve(free ^ covered)
            score += area * area
            result = (rect,) + tail
            if (best is None or len(result) < len(best)
                    or (len(result) == len(best) and score > best_score + _EPS)):
                best, best_score = result, score
        return best, best_score

    result, _ = solve(mask)
    return [list(rect) for rect in result]


def _shared_edge(a, b):
    vertical = (max(0, min(a[3], b[3]) - max(a[1], b[1]))
                if abs(a[0] - b[2]) < _EPS or abs(a[2] - b[0]) < _EPS else 0)
    horizontal = (max(0, min(a[2], b[2]) - max(a[0], b[0]))
                  if abs(a[1] - b[3]) < _EPS or abs(a[3] - b[1]) < _EPS else 0)
    return vertical + horizontal


def _merge_slivers(rects):
    """Absorb thin pieces into touching neighbours, keeping every covered point.

    The rectangular envelope can bridge a small concave setback or extend
    under a higher roof. Prefer the merge adding the least area. A genuinely
    isolated narrow wing is retained rather than silently losing its roof.
    """
    rects = sorted(rects, key=lambda r: (_area(r), r))
    while True:
        choices = []
        for i, a in enumerate(rects):
            if min(a[2] - a[0], a[3] - a[1]) >= _MIN_SIDE - _EPS:
                continue
            for j, b in enumerate(rects):
                if i == j:
                    continue
                edge = _shared_edge(a, b)
                if edge <= _EPS:
                    continue
                merged = [min(a[0], b[0]), min(a[1], b[1]),
                          max(a[2], b[2]), max(a[3], b[3])]
                narrow = min(merged[2] - merged[0], merged[3] - merged[1])
                overlap = (max(0, min(a[2], b[2]) - max(a[0], b[0]))
                           * max(0, min(a[3], b[3]) - max(a[1], b[1])))
                added = _area(merged) - _area(a) - _area(b) + overlap
                choices.append((narrow < _MIN_SIDE - _EPS, added, -edge,
                                merged, i, j))
        if not choices:
            return rects
        _, _, _, merged, i, j = min(choices)
        rects = [r for k, r in enumerate(rects) if k not in (i, j)] + [merged]
        # An envelope may have swallowed another rectangle completely.
        rects = [r for r in rects if r is merged or not (
            merged[0] <= r[0] and merged[1] <= r[1]
            and r[2] <= merged[2] and r[3] <= merged[3])]


def _letter(index):
    result = ''
    while index >= 0:
        index, digit = divmod(index, 26)
        result = chr(65 + digit) + result
        index -= 1
    return result


def blocks(building: dict) -> list[dict]:
    """Split exposed storeys into stable, area-ordered rectangular roof blocks.

    Input is a normalized building. Its settled level outlines supply the
    exterior wall footprint; paired knee walls and half-storeys stay beneath
    the roof of the storey below. Porches and existing roofs are not blocks.
    """
    levels = sorted((lv for lv in building.get('levels', [])
                     if lv.get('state') != 'ghost' and lv.get('outline')),
                    key=lambda lv: (lv['elevation'], lv['id']))
    if not levels:
        return []
    rooms = {lv['id']: _knee_rooms(building.get('walls', []), lv['id'])
             for lv in levels[1:]}
    points = [p for lv in levels for p in lv['outline']]
    points += [p for rects in rooms.values() for r in rects
               for p in ((r[0], r[1]), (r[2], r[3]))]
    sx, sy = _snap_map(p[0] for p in points), _snap_map(p[1] for p in points)
    xs, ys = sorted(set(sx.values())), sorted(set(sy.values()))
    occupied = []
    for index, lv in enumerate(levels):
        poly = [(sx[x], sy[y]) for x, y in lv['outline']]
        knees = [[sx[r[0]], sy[r[1]], sx[r[2]], sy[r[3]]]
                 for r in rooms.get(lv['id'], [])]
        cells = set()
        if index == 0 or not lv.get('half'):
            for i in range(len(xs) - 1):
                for j in range(len(ys) - 1):
                    x, y = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
                    if (_inside(poly, x, y) and not any(
                            r[0] < x < r[2] and r[1] < y < r[3] for r in knees)):
                        cells.add((i, j))
        occupied.append(cells)
    result, above = [], set()
    for index in range(len(levels) - 1, -1, -1):
        lv = levels[index]
        rects = _merge_slivers(_partition(occupied[index] - above, xs, ys))
        for rect in rects:
            result.append({'rect': rect, 'storey': 'lower' if index == 0 else 'upper',
                           'level': lv['id'], 'plate': float(lv['elevation'] + lv['ceiling'])})
        # Subtract final envelopes too: a merged upper sliver owns its roof area.
        above.update((i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1)
                     if any(r[0] <= (xs[i] + xs[i + 1]) / 2 <= r[2]
                            and r[1] <= (ys[j] + ys[j + 1]) / 2 <= r[3] for r in rects))
    result.sort(key=lambda b: (-_area(b['rect']), b['rect'], b['level']))
    for index, block in enumerate(result):
        block['id'] = _letter(index)
    return result


def block_diagram(building: dict, blocks: list) -> bytes:
    """PNG top view with block letters, sizes in feet and the street at y=0."""
    from PIL import Image, ImageDraw, ImageFont

    width, height, margin = 1100, 1000, 80
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)

    def font(size):
        for name in ('DejaVuSans.ttf', 'arial.ttf'):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
        return ImageFont.load_default()

    points = [p for lv in building.get('levels', []) for p in lv.get('outline', [])]
    points += [p for b in blocks for p in (b['rect'][:2], b['rect'][2:])]
    points = points or [(0, 0), (1, 1)]
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(0, min(p[1] for p in points)), max(0, max(p[1] for p in points))
    scale = min((width - 2 * margin) / max(x1 - x0, 1),
                (height - 2 * margin - 60) / max(y1 - y0, 1))
    left = (width - (x1 - x0) * scale) / 2

    def point(x, y):
        return left + (x - x0) * scale, height - margin - (y - y0) * scale

    draw.text((width / 2, 24), 'Roof blocks - top view (feet)',
              font=font(24), fill='#222222', anchor='mt')
    # Draw lower roofs first so higher storeys remain visible over merged edges.
    for b in sorted(blocks, key=lambda b: (b['plate'], b['id'])):
        a, c = b['rect'][:2], b['rect'][2:]
        draw.rectangle([point(a[0], c[1]), point(c[0], a[1])],
                       fill='#9ecae1' if b['storey'] == 'upper' else '#fdd0a2',
                       outline='#333333', width=2)
    for b in blocks:
        a, c = b['rect'][:2], b['rect'][2:]
        cx, cy = point((a[0] + c[0]) / 2, (a[1] + c[1]) / 2)
        size = f'{c[0] - a[0]:.1f} x {c[1] - a[1]:.1f} ft'
        label_font = font(18)
        for n in range(18, 8, -1):
            label_font = font(n)
            if draw.textlength(size, font=label_font) < (c[0] - a[0]) * scale - 8:
                break
        draw.text((cx, cy - 16), b['id'], font=font(32), fill='black', anchor='mm')
        draw.text((cx, cy + 15), size, font=label_font, fill='black', anchor='mm')
        draw.text((cx, cy + 35), b['level'], font=font(12), fill='#333333', anchor='mm')
    street_y = point(x0, 0)[1]
    draw.line([(margin, street_y), (width - margin, street_y)], fill='#555555', width=2)
    draw.text((width / 2, street_y + 14), 'STREET / FRONT (y = 0)',
              font=font(22), fill='black', anchor='mt')
    draw.text((width / 2, height - 22), 'Blue: upper storey    Orange: lower storey',
              font=font(16), fill='#333333', anchor='mm')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()
