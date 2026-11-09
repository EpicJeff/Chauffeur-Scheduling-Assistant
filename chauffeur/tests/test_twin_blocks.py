"""Blocks from the walls (brief
.superpowers/sdd/2026-11-08-house-editor-roofs-from-photos/task-1-brief.md;
design docs/superpowers/specs/2026-11-08-house-editor-roofs-from-photos-design.md
section 1).

services.twin_blocks.blocks(building) splits each storey's outline into
rectangular roof blocks: {id, rect [x0, y0, x1, y1], storey 'upper'|'lower',
level 'L1'|'L2'.., plate}. Upper blocks are the upper storey's outline; lower
blocks are the ground floor not under an upper block. Knee-wall rooms
(storey-and-a-half, low interior walls on the upper level) stay inside the
lower block beneath them. Slivers narrower than 7 ft merge into a neighbour.
Ids run A, B, C... in order of area, largest first.
A block may reach up to 1.0 ft past its level's outline (ruling R5: inside a
standard 1 ft roof overhang, so a 1 ft front jog stays one block).

services.twin_blocks.block_diagram(building, blocks) draws a PNG top view.

What the recorded data shows (draft-main-house.json, build 1, normalized
through twin_plan.normalize; the spike's partition in scratchpad
spike_roof/blocks.json):
- upper middle block 14.33-37.33 x 14.33-52 (the drawing's r_main says
  y0 13.33; the L2 outline has a 1 ft step there, so either is accepted);
- upper right block 37.33-59 x 19.33-43;
- lower left wing 0-14.33 x 14.33-54;
- lower garage front 37.33-59 x 0-19.33 (L1 says x 37, L2 says 37.33);
- lower third garage 59-70 x 22-43 (L1 says y 42, L2 says 43);
- the spike also found two breakfast slivers, 37.33-43.33 x 43-59 (6 ft) and
  31-37.33 x 52-59 (6.33 ft); they must merge away (no block under 7 ft).
- Knee-wall rooms: walls k1/k2 (3 ft, x 41 and x 55, y 0-19.33) close the
  bonus room 41-55 x 0-19.33; walls k3/k4 (5.17 / 6.33 ft, y 44.67 and
  y 25.33, x 0-14.33) close the left bedroom 0-14.33 x 25.33-44.67.
- Plates: L1 elevation 0 + ceiling 10 = 10; L2 elevation 11 + ceiling 9 = 20.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_blocks.py
"""
import json
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_blocks_')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURE = os.path.join(HERE, 'fixtures', 'twin_reads', 'recorded', 'claude', 'draft-main-house.json')

TOL = 1.0
UPPER_MIDDLE = [14.33, 13.33, 37.33, 52]
UPPER_RIGHT = [37.33, 19.33, 59, 43]
LOWER_LEFT_WING = [0, 14.33, 14.33, 54]
LOWER_GARAGE_FRONT = [37.33, 0, 59, 19.33]
LOWER_THIRD_GARAGE = [59, 22, 70, 43]
BONUS_ROOM = [41, 0, 55, 19.33]
LEFT_BEDROOM = [0, 25.33, 14.33, 44.67]


def _building():
    from services import twin_plan
    with open(FIXTURE, encoding='utf-8') as fh:
        fragment = json.load(fh)
    plan, _notes = twin_plan.normalize({'units': 'ft', 'buildings': [fragment['building']]})
    return plan['buildings'][0]


def _blocks(building=None):
    from services import twin_blocks
    return twin_blocks.blocks(building if building is not None else _building())


def _near(rect, want, tol=TOL):
    return len(rect) == 4 and all(abs(float(a) - float(b)) <= tol for a, b in zip(rect, want))


def _area(rect):
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _contains(outer, inner, tol=0.5):
    return (outer[0] <= inner[0] + tol and outer[1] <= inner[1] + tol
            and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0)


def _show(blocks):
    return '; '.join(f"{b.get('id')} {b.get('storey')} {b.get('rect')}" for b in blocks)


def test_household_blocks():
    blocks = _blocks()
    assert blocks, 'no blocks for the household draft'
    for b in blocks:
        assert b['storey'] in ('upper', 'lower'), b
        r = b['rect']
        assert len(r) == 4 and r[0] < r[2] and r[1] < r[3], b
    upper = [b for b in blocks if b['storey'] == 'upper']
    lower = [b for b in blocks if b['storey'] == 'lower']
    assert any(_near(b['rect'], UPPER_MIDDLE) for b in upper), \
        f'no upper middle block near {UPPER_MIDDLE}: {_show(blocks)}'
    assert any(_near(b['rect'], UPPER_RIGHT) for b in upper), \
        f'no upper right block near {UPPER_RIGHT}: {_show(blocks)}'
    for name, want in (('left wing', LOWER_LEFT_WING), ('garage front', LOWER_GARAGE_FRONT),
                       ('third garage', LOWER_THIRD_GARAGE)):
        assert any(_near(b['rect'], want) for b in lower), \
            f'no lower {name} block near {want}: {_show(blocks)}'
    for b in blocks:
        r = b['rect']
        narrow = min(r[2] - r[0], r[3] - r[1])
        if narrow < 7 - 1e-6:
            assert b.get('sliver') is True, f"block {b['id']} {r} is {narrow:.2f} ft wide and not flagged sliver"
        if not b.get('sliver'):
            assert r[2] - r[0] >= 7 - 1e-6 and r[3] - r[1] >= 7 - 1e-6,                 f"block {b['id']} {r} is under 7 ft without the sliver flag"
    kept = [b for b in blocks if _near(b['rect'], [37.33, 43, 43.33, 59])]
    assert kept, f'the rear low-slope sliver [37.33, 43, 43.33, 59] is missing: {_show(blocks)}'
    assert all(b['storey'] == 'lower' for b in kept), f'rear sliver is not lower: {_show(blocks)}'


def test_knee_wall_rooms_stay_in_lower_block():
    blocks = _blocks()
    for name, room in (('bonus room', BONUS_ROOM), ('left bedroom', LEFT_BEDROOM)):
        for b in blocks:
            assert not _near(b['rect'], room), \
                f"block {b['id']} {b['rect']} is only the {name} {room}: {_show(blocks)}"
        holders = [b for b in blocks if b['storey'] == 'lower' and _contains(b['rect'], room)]
        assert holders, f'the {name} {room} sits inside no lower block: {_show(blocks)}'
        for b in blocks:
            if b['storey'] == 'upper':
                assert _overlap(b['rect'], room) <= 0.05 * _area(room), \
                    f"upper block {b['id']} {b['rect']} covers the {name} {room}"


def test_plate_from_storey():
    building = _building()
    levels = {lv['id']: lv for lv in building['levels']}
    l1 = levels['L1']['elevation'] + levels['L1']['ceiling']
    l2 = levels['L2']['elevation'] + levels['L2']['ceiling']
    assert (l1, l2) == (10, 20), (l1, l2)
    blocks = _blocks(building)
    lower = [b for b in blocks if b['storey'] == 'lower']
    upper = [b for b in blocks if b['storey'] == 'upper']
    assert lower and upper, _show(blocks)
    for b in lower:
        assert b['level'] == 'L1', b
        assert abs(float(b['plate']) - l1) < 1e-6, b
    for b in upper:
        assert b['level'] == 'L2', b
        assert abs(float(b['plate']) - l2) < 1e-6, b


def test_stable_ids():
    building = _building()
    first = _blocks(building)
    second = _blocks(json.loads(json.dumps(building)))
    assert [(b['id'], list(b['rect'])) for b in first] == [(b['id'], list(b['rect'])) for b in second], \
        f'{_show(first)} != {_show(second)}'
    ids = [b['id'] for b in first]
    assert ids == [chr(ord('A') + i) for i in range(len(ids))], ids
    areas = [_area(b['rect']) for b in first]
    assert all(a >= b - 1e-6 for a, b in zip(areas, areas[1:])), \
        f'ids are not in order of area, largest first: {list(zip(ids, areas))}'


def test_diagram_png():
    from services import twin_blocks
    building = _building()
    png = twin_blocks.block_diagram(building, twin_blocks.blocks(building))
    assert isinstance(png, (bytes, bytearray)), type(png)
    assert png[:8] == b'\x89PNG\r\n\x1a\n', png[:8]
    assert len(png) > 1000, len(png)


def _in_poly(poly, x, y):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _dist_to_poly(poly, x, y):
    best = float('inf')
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / seg))
        best = min(best, ((x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2) ** 0.5)
    return best


def test_no_blocks_overlap():
    blocks = _blocks()
    for i, a in enumerate(blocks):
        for b in blocks[i + 1:]:
            ov = _overlap(a['rect'], b['rect'])
            assert ov <= 0.25,                 f"blocks {a['id']} {a['rect']} and {b['id']} {b['rect']} overlap by {ov:.2f} sq ft: {_show(blocks)}"


def test_blocks_lie_within_their_footprint():
    building = _building()
    levels = [lv for lv in building['levels'] if lv.get('state') != 'ghost' and lv.get('outline')]
    levels.sort(key=lambda lv: (lv['elevation'], lv['id']))
    ground = levels[0]
    by_id = {lv['id']: lv for lv in levels}
    blocks = _blocks(building)
    for b in blocks:
        lv = ground if b['storey'] == 'lower' else by_id[b['level']]
        poly = [tuple(map(float, p)) for p in lv['outline']]
        x0, y0, x1, y1 = b['rect']
        nx, ny = int((x1 - x0) / 0.5), int((y1 - y0) / 0.5)
        for i in range(nx + 1):
            for j in range(ny + 1):
                x, y = x0 + i * 0.5, y0 + j * 0.5
                assert _in_poly(poly, x, y) or _dist_to_poly(poly, x, y) <= 1.0 + 1e-6, (
                    f"block {b['id']} {b['rect']} covers ({x:.2f}, {y:.2f}) outside the {lv['id']} outline: {_show(blocks)}")


TESTS = (
    test_household_blocks,
    test_knee_wall_rooms_stay_in_lower_block,
    test_plate_from_storey,
    test_stable_ids,
    test_diagram_png,
    test_no_blocks_overlap,
    test_blocks_lie_within_their_footprint,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
