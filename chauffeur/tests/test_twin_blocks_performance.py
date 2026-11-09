"""Large outlines stay bounded; fallback coverage is exact and deterministic."""
import os
import sys
from time import perf_counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import twin_blocks


def _bays():
    width, depth = 60, 40
    points = [(0, 0)]
    for i in range(4):
        x = (i + 1) * width / 5 - 3
        points += [(x, 0), (x, -2), (x + 6, -2), (x + 6, 0)]
    points.append((width, 0))
    for i in range(2):
        y = (i + 1) * depth / 3 - 3
        points += [(width, y), (width + 2, y), (width + 2, y + 6), (width, y + 6)]
    points.append((width, depth))
    for i in range(3):
        x = width - (i + 1) * width / 4 + 4
        points += [(x, depth), (x, depth + 3), (x - 8, depth + 3), (x - 8, depth)]
    points.append((0, depth))
    for i in range(2):
        y = depth - (i + 1) * depth / 3 + 3
        points += [(0, y), (-2, y), (-2, y - 6), (0, y - 6)]
    assert len(points) == 48
    return points


def _check(outline):
    building = {'levels': [{'id': 'L1', 'elevation': 0, 'ceiling': 9, 'outline': outline}], 'walls': []}
    started = perf_counter()
    result = twin_blocks.blocks(building)
    elapsed = perf_counter() - started
    assert elapsed < 2, elapsed
    assert result == twin_blocks.blocks(building), 'stable fallback geometry and ids'
    for i, a in enumerate(result):
        for b in result[i + 1:]:
            assert twin_blocks._overlap(a['rect'], b['rect']) < 1e-6, (a, b)
    # Exact union area is preserved for these outlines (their jogs exceed 1 ft).
    area = abs(sum(a[0] * b[1] - a[1] * b[0]
                   for a, b in zip(outline, outline[1:] + outline[:1]))) / 2
    assert abs(sum(twin_blocks._area(b['rect']) for b in result) - area) < 1e-6, result
    return elapsed


def test_48_vertex_outline_under_two_seconds():
    print('48 vertices:', round(_check(_bays()), 3), 's')


def test_fourteen_step_staircase_under_two_seconds():
    outline = [(0, 0), (140, 0)]
    for i in range(14):
        outline += [(140 - i * 10, (i + 1) * 10), (130 - i * 10, (i + 1) * 10)]
    print('14 steps:', round(_check(outline), 3), 's')


if __name__ == '__main__':
    for test in (test_48_vertex_outline_under_two_seconds, test_fourteen_step_staircase_under_two_seconds):
        test()
        print('  ok ', test.__name__)
