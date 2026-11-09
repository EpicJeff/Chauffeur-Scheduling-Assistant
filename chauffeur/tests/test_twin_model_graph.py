"""The wall graph: joints, splits, regions and mitred footprints (brief
.superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-1-brief.md;
spec docs/superpowers/specs/2026-11-09-house-connected-model-design.md
sections 4.1-4.2; plan docs/superpowers/plans/2026-11-09-house-connected-
model-pieces-1-2.md Task 1 and Review Focus 1).

Module under test: services/twin_model_graph.py.

- weld(points, tol=1.0) -> (positions, index per input point).
- split_crossings(joints, walls) -> (joints, walls): every T-junction (a joint
  within 0.05 ft of a wall's interior) and every proper crossing is split; new
  joints are 'j:<n>'; a split wall keeps its id on the first part (from its
  first joint) and the rest are '<id>~2', '<id>~3', each copying every other
  field.
- regions(joints, walls) -> [{joints: ids counter-clockwise, polygon, area}]:
  the bounded faces; solid and separator walls both bound; a dangling wall
  bounds nothing.
- open_ends(joints, walls) -> positions of joints with exactly one wall.
- footprints(joints, walls) -> {wall id: [from_left, to_left, to_right,
  from_right]} for solid walls only; left is to the left of from->to; ends
  are mitred against the neighbouring solid wall's offset line on the same
  side; a free end is square.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_graph.py
"""
import copy
import math
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_graph_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.twin_model_graph import (  # noqa: E402
    footprints, open_ends, regions, split_crossings, weld,
)

T = 0.5   # wall thickness used throughout; half is 0.25


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def same_pt(p, q, tol=1e-6):
    return close(p[0], q[0], tol) and close(p[1], q[1], tol)


def signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def wall(wid, a, b, kind='solid', **extra):
    w = {'id': wid, 'joints': [a, b], 'kind': kind, 'thickness': T, 'exterior': True}
    w.update(extra)
    return w


def by_id(walls):
    return {w['id']: w for w in walls}


def areas(rs):
    return sorted(round(r['area'], 3) for r in rs)


def pt_set(poly):
    return sorted((round(p[0], 6), round(p[1], 6)) for p in poly)


# A 10x8 box, counter-clockwise c0 (0,0) -> c1 (10,0) -> c2 (10,8) -> c3 (0,8),
# plus m0 (5,0) and m1 (5,8) on its bottom and top walls for an interior wall.
BOX_JOINTS = {
    'c0': [0.0, 0.0], 'c1': [10.0, 0.0], 'c2': [10.0, 8.0], 'c3': [0.0, 8.0],
    'm0': [5.0, 0.0], 'm1': [5.0, 8.0],
}
BOX_WALLS = [
    wall('b0', 'c0', 'c1'), wall('b1', 'c1', 'c2'),
    wall('b2', 'c2', 'c3'), wall('b3', 'c3', 'c0'),
]


def box_with_mid(kind='solid'):
    return (copy.deepcopy(BOX_JOINTS),
            copy.deepcopy(BOX_WALLS) + [wall('mid', 'm0', 'm1', kind=kind, exterior=False)])


# ---------------------------------------------------------------- split + regions

def test_t_junction_splits_and_makes_two_rooms():
    # 10x8 box plus an interior wall from (5,0) to (5,8) whose ends lie on the box's walls
    j, w = split_crossings(*box_with_mid())
    r = regions(j, w)
    check(areas(r) == [40.0, 40.0], f'two 40 sq ft rooms, got {areas(r)}')
    ws = by_id(w)
    check(ws['b0']['joints'] == ['c0', 'm0'], f"b0 keeps its id on the first part: {ws['b0']['joints']}")
    check(ws['b0~2']['joints'] == ['m0', 'c1'], f"b0~2 is the rest: {ws.get('b0~2')}")
    check(ws['b2']['joints'] == ['c2', 'm1'], f"b2 first part: {ws['b2']['joints']}")
    check(ws['b2~2']['joints'] == ['m1', 'c3'], f"b2~2: {ws.get('b2~2')}")
    check(sorted(ws) == ['b0', 'b0~2', 'b1', 'b2', 'b2~2', 'b3', 'mid'], f'wall ids {sorted(ws)}')
    check(not any(k.startswith('j:') for k in j), f'a T at an existing joint adds no joint: {sorted(j)}')
    left = [x for x in r if same_pt(sorted(x['polygon'])[0], [0, 0])]
    check(len(left) == 1, f'one region holds (0,0): {r}')
    check(pt_set(left[0]['polygon']) == [(0.0, 0.0), (0.0, 8.0), (5.0, 0.0), (5.0, 8.0)],
          f"left room corners: {left[0]['polygon']}")


def test_split_parts_copy_every_other_field():
    # the box's bottom wall carries extra fields; both its parts keep them
    jj, ww = box_with_mid()
    ww[0].update({'height': 9.0, 'faces': {'left': 'brick'}, 'level': 'L1', 'src': {'person': True}})
    j, w = split_crossings(jj, ww)
    ws = by_id(w)
    for wid in ('b0', 'b0~2'):
        part = ws[wid]
        for field, value in (('kind', 'solid'), ('thickness', T), ('exterior', True), ('height', 9.0),
                             ('faces', {'left': 'brick'}), ('level', 'L1'), ('src', {'person': True})):
            check(part.get(field) == value, f'{wid}.{field} = {part.get(field)!r}, want {value!r}')


def test_wall_split_twice_numbers_parts_in_order():
    # 10x8 box with interior walls at x=3 and x=7: the bottom wall becomes b0, b0~2, b0~3 from (0,0)
    j = copy.deepcopy(BOX_JOINTS)
    del j['m0'], j['m1']
    j.update({'p0': [3.0, 0.0], 'p1': [3.0, 8.0], 'q0': [7.0, 0.0], 'q1': [7.0, 8.0]})
    w = copy.deepcopy(BOX_WALLS) + [wall('p', 'p0', 'p1'), wall('q', 'q0', 'q1')]
    j2, w2 = split_crossings(j, w)
    ws = by_id(w2)
    check(ws['b0']['joints'] == ['c0', 'p0'], f"b0: {ws['b0']['joints']}")
    check(ws['b0~2']['joints'] == ['p0', 'q0'], f"b0~2: {ws.get('b0~2')}")
    check(ws['b0~3']['joints'] == ['q0', 'c1'], f"b0~3: {ws.get('b0~3')}")
    check(ws['b2']['joints'] == ['c2', 'q1'], f"b2 runs right to left: {ws['b2']['joints']}")
    check(ws['b2~2']['joints'] == ['q1', 'p1'] and ws['b2~3']['joints'] == ['p1', 'c3'],
          f"b2 parts: {ws.get('b2~2')} {ws.get('b2~3')}")
    check(areas(regions(j2, w2)) == [24.0, 24.0, 32.0], f'three rooms: {areas(regions(j2, w2))}')


def test_crossing_walls_split_into_four_rooms():   # Review Focus 1
    # a plus sign of two walls inside a 10x10 box, sharing no joint:
    # h (0,5)->(10,5) and v (5,0)->(5,10), each ending on the box's walls
    J = {'c0': [0.0, 0.0], 'c1': [10.0, 0.0], 'c2': [10.0, 10.0], 'c3': [0.0, 10.0],
         'h0': [0.0, 5.0], 'h1': [10.0, 5.0], 'v0': [5.0, 0.0], 'v1': [5.0, 10.0]}
    W = [wall('b0', 'c0', 'c1'), wall('b1', 'c1', 'c2'), wall('b2', 'c2', 'c3'), wall('b3', 'c3', 'c0'),
         wall('h', 'h0', 'h1', exterior=False), wall('v', 'v0', 'v1', exterior=False)]
    j, w = split_crossings(J, W)
    check(sorted(round(x['area'], 3) for x in regions(j, w)) == [25.0] * 4,
          f'four 25 sq ft rooms, got {areas(regions(j, w))}')
    new = [k for k in j if k.startswith('j:')]
    check(len(new) == 1, f'one new joint at the crossing: {sorted(j)}')
    jc = new[0]
    check(same_pt(j[jc], [5, 5]), f'crossing joint at (5,5): {j[jc]}')
    ws = by_id(w)
    check(ws['h']['joints'] == ['h0', jc] and ws['h~2']['joints'] == [jc, 'h1'],
          f"h parts: {ws['h']} {ws.get('h~2')}")
    check(ws['v']['joints'] == ['v0', jc] and ws['v~2']['joints'] == [jc, 'v1'],
          f"v parts: {ws['v']} {ws.get('v~2')}")
    check(ws['h~2'].get('exterior') is False and ws['h~2'].get('thickness') == T, 'h~2 copies fields')


def test_t_junction_tolerance_is_five_hundredths():
    # the interior wall's bottom end sits 0.04 ft above the bottom wall: it splits it
    j, w = box_with_mid()
    j['m0'] = [5.0, 0.04]
    _, w2 = split_crossings(j, w)
    check('b0~2' in by_id(w2), f'0.04 ft off splits b0: {sorted(by_id(w2))}')
    # 0.2 ft above: no split of the bottom wall (the top end still splits b2)
    j, w = box_with_mid()
    j['m0'] = [5.0, 0.2]
    _, w3 = split_crossings(j, w)
    ids = sorted(by_id(w3))
    check('b0~2' not in ids and 'b2~2' in ids, f'0.2 ft off leaves b0 whole: {ids}')


def test_nothing_to_split_returns_the_same_graph():
    # the bare box: four walls, four joints, one 80 sq ft room
    j = {k: v for k, v in BOX_JOINTS.items() if k.startswith('c')}
    j2, w2 = split_crossings(copy.deepcopy(j), copy.deepcopy(BOX_WALLS))
    check(sorted(j2) == ['c0', 'c1', 'c2', 'c3'], f'joints unchanged: {sorted(j2)}')
    check([x['id'] for x in w2] == ['b0', 'b1', 'b2', 'b3'], f'walls unchanged: {[x["id"] for x in w2]}')
    check(areas(regions(j2, w2)) == [80.0], f'one room: {areas(regions(j2, w2))}')


def test_regions_are_counter_clockwise_and_match_their_joints():
    # the split box: each region's joints are ids in CCW order and its polygon is their positions
    j, w = split_crossings(*box_with_mid())
    r = regions(j, w)
    check(len(r) == 2, f'two regions: {r}')
    for x in r:
        check(len(x['polygon']) == len(x['joints']), f'polygon matches joints: {x}')
        for jid, p in zip(x['joints'], x['polygon']):
            check(same_pt(j[jid], p), f'{jid} at {j[jid]} vs polygon point {p}')
        check(signed_area(x['polygon']) > 0, f"counter-clockwise: {x['polygon']}")
        check(close(signed_area(x['polygon']), x['area'], 1e-6), f"area is the polygon's: {x}")


def test_separator_bounds_rooms_like_a_wall():
    # the same box with 'mid' as kind 'separator': two regions; footprints() has no 'mid'
    j, w = split_crossings(*box_with_mid(kind='separator'))
    check(areas(regions(j, w)) == [40.0, 40.0], f'separator makes two rooms: {areas(regions(j, w))}')
    fp = footprints(j, w)
    check('mid' not in fp, f'a separator has no footprint: {sorted(fp)}')
    check(sorted(fp) == ['b0', 'b0~2', 'b1', 'b2', 'b2~2', 'b3'], f'every solid wall has one: {sorted(fp)}')


def test_gap_leaves_no_region_and_reports_open_ends():
    # a 10x8 box whose top wall stops 2 ft short: (10,8) -> (2,8), leaving (0,8)..(2,8) open
    j = {'c0': [0.0, 0.0], 'c1': [10.0, 0.0], 'c2': [10.0, 8.0], 'g': [2.0, 8.0], 'c3': [0.0, 8.0]}
    w = [wall('b0', 'c0', 'c1'), wall('b1', 'c1', 'c2'), wall('b2', 'c2', 'g'), wall('b3', 'c3', 'c0')]
    j2, w2 = split_crossings(j, w)
    check(regions(j2, w2) == [], f'no region: {regions(j2, w2)}')
    ends = sorted([round(p[0], 6), round(p[1], 6)] for p in open_ends(j2, w2))
    check(ends == [[0.0, 8.0], [2.0, 8.0]], f'the two gap ends: {ends}')


def test_dangling_wall_bounds_nothing():
    # the closed 10x8 box plus a stub from (5,0) up to (5,3) with a free end
    j = {k: v for k, v in BOX_JOINTS.items() if k.startswith('c')}
    j.update({'s0': [5.0, 0.0], 's1': [5.0, 3.0]})
    w = copy.deepcopy(BOX_WALLS) + [wall('stub', 's0', 's1', exterior=False)]
    j2, w2 = split_crossings(j, w)
    r = regions(j2, w2)
    check(areas(r) == [80.0], f'the stub does not divide the room: {areas(r)}')
    check(not any(same_pt(p, [5, 3]) for p in r[0]['polygon']),
          f"the stub's free end is not on the room's outline: {r[0]['polygon']}")
    check('s1' not in r[0]['joints'], f"the free end joint is not a room joint: {r[0]['joints']}")
    ends = [[round(p[0], 6), round(p[1], 6)] for p in open_ends(j2, w2)]
    check(ends == [[5.0, 3.0]], f'one open end at the stub tip: {ends}')


def test_closed_box_has_no_open_ends():
    j, w = split_crossings(*box_with_mid())
    check(open_ends(j, w) == [], f'no open ends: {open_ends(j, w)}')


def test_split_overshoot_shorter_than_one_foot_is_dropped():
    # R15 applies at either end of a split wall, including a proper crossing.
    for reverse in (False, True):
        for overshoot in (0.4, 0.999, 1.0, 1.4):
            j = {k: v for k, v in BOX_JOINTS.items() if k.startswith('c')}
            j['tip'] = [10 + overshoot, 8.0]
            top = ['c3', 'tip'] if reverse else ['tip', 'c3']
            w = copy.deepcopy(BOX_WALLS)
            w[2] = wall('b2', *top)
            j2, w2 = split_crossings(j, w)
            check(areas(regions(j2, w2)) == [80.0], f'one room: {w2}')
            ends = open_ends(j2, w2)
            if overshoot < 1.0:
                check(ends == [], f'{overshoot} ft overshoot must leave no open end: {ends}')
                check(len(w2) == 4 and 'b2' in by_id(w2), f'keeps the retained wall id: {w2}')
                check('tip' not in {jid for part in w2 for jid in part['joints']}, w2)
                check(split_crossings(j2, w2) == (j2, w2), 'trimming is stable on repeat')
            else:
                check(ends == [j['tip']], f'{overshoot} ft overshoot stays: {ends}')
    # Both walls run past the intersection, so the corner is a proper crossing.
    j = {'a': [0, 0], 'b': [10, 0], 'c': [10, 8.4], 'd': [0, 8], 'tip': [10.4, 8]}
    w = [wall('b0', 'a', 'b'), wall('b1', 'b', 'c'),
         wall('b2', 'tip', 'd'), wall('b3', 'd', 'a')]
    j2, w2 = split_crossings(j, w)
    check(areas(regions(j2, w2)) == [80.0], f'one room at the crossing: {w2}')
    check(open_ends(j2, w2) == [], f'neither crossing overshoot is open: {w2}')


def test_short_walls_and_connected_split_parts_survive():
    # R13/R15: a real short wall is not a split overshoot, and a short piece
    # between two junctions is not dangling.
    for length in (0.4, 1.0):
        j = {'a': [0, 0], 'b': [length, 0]}
        w = [wall('short', 'a', 'b')]
        check(split_crossings(j, w) == (j, w), f'real {length} ft wall survives')
    j = {'a': [0, 0], 'b': [10, 0], 'p': [5, 0], 'q': [5.4, 0],
         'e': [5, 6], 'f': [5.4, 6]}
    w = [wall('t', 'a', 'b'), wall('s1', 'p', 'e'), wall('s2', 'q', 'f')]
    j2, w2 = split_crossings(j, w)
    check(by_id(w2)['t~2']['joints'] == ['p', 'q'], f'connected short piece survives: {w2}')


# ---------------------------------------------------------------- weld

def test_weld_merges_within_one_foot_only():
    pts, idx = weld([[0, 0], [0.9, 0], [2.5, 0]])
    check(idx[0] == idx[1] and idx[2] != idx[0], f'first two merge, third apart: {idx}')
    check(len(pts) == 2, f'two welded joints: {pts}')
    check(same_pt(pts[idx[2]], [2.5, 0]), f'the lone point keeps its place: {pts[idx[2]]}')
    m = pts[idx[0]]
    check(abs(m[0] - 0) <= 1.0 and abs(m[0] - 0.9) <= 1.0 and close(m[1], 0),
          f'the merged joint lies within a foot of both: {m}')
    pts2, idx2 = weld([[0, 0], [1.1, 0]])
    check(idx2[0] != idx2[1] and len(pts2) == 2, f'1.1 ft apart stays apart: {pts2} {idx2}')


def test_weld_tolerance_is_a_parameter():
    pts, idx = weld([[0, 0], [0.9, 0]], tol=0.5)
    check(idx[0] != idx[1] and len(pts) == 2, f'0.9 apart stays apart at tol 0.5: {pts} {idx}')
    pts, idx = weld([[0, 0], [0, 1.8]], tol=2.0)
    check(idx[0] == idx[1] and len(pts) == 1, f'1.8 apart merges at tol 2: {pts} {idx}')


def test_weld_tolerance_is_strict():
    for tol in (0.5, 1.0, 2.0):
        pts, idx = weld([[0, 0], [tol, 0]], tol=tol)
        check(idx[0] != idx[1] and len(pts) == 2, f'exactly {tol} apart stays apart: {pts}')


def test_weld_never_merges_a_walls_own_ends():
    # Index pairs identify the two ends of each wall. A third nearby point
    # must not let complete-link clustering merge those ends indirectly.
    points = [[0, 0], [0.8, 0], [0.4, 0], [3, 0]]
    pts, idx = weld(points, separate=[(0, 1), (2, 3)])
    check(idx[0] != idx[1] and idx[2] != idx[3], f'wall endpoints stay separate: {idx}')
    check(idx[2] in (idx[0], idx[1]) and len(pts) == 3, f'unrelated nearby ends still weld: {idx}')
    check(points == [[0, 0], [0.8, 0], [0.4, 0], [3, 0]], 'welding preserves the inputs')


# ---------------------------------------------------------------- footprints

def test_l_corner_footprints_meet_without_a_gap():
    # walls (0,0)->(10,0) and (10,0)->(10,8), both 0.5 thick:
    # the outer corner of the first equals the outer corner of the second within 1e-6, likewise the inner corners
    j = {'a': [0.0, 0.0], 'b': [10.0, 0.0], 'c': [10.0, 8.0]}
    w = [wall('w1', 'a', 'b'), wall('w2', 'b', 'c')]
    fp = footprints(j, w)
    f1, f2 = fp['w1'], fp['w2']
    check(len(f1) == 4 and len(f2) == 4, f'four points each: {fp}')
    # w1 runs +x so its left is +y; w2 runs +y so its left is -x. Inner corner (9.75, 0.25), outer (10.25, -0.25).
    check(same_pt(f1[1], f2[0]), f'inner corners meet: w1 to_left {f1[1]} vs w2 from_left {f2[0]}')
    check(same_pt(f1[2], f2[3]), f'outer corners meet: w1 to_right {f1[2]} vs w2 from_right {f2[3]}')
    check(same_pt(f1[1], [9.75, 0.25]), f'inner corner at (9.75, 0.25): {f1[1]}')
    check(same_pt(f1[2], [10.25, -0.25]), f'outer corner at (10.25, -0.25): {f1[2]}')
    # free ends are square
    check(same_pt(f1[0], [0, 0.25]) and same_pt(f1[3], [0, -0.25]), f'w1 free end square: {f1}')
    check(same_pt(f2[1], [9.75, 8]) and same_pt(f2[2], [10.25, 8]), f'w2 free end square: {f2}')


def test_free_wall_footprint_is_a_square_ended_rectangle():
    # one lone wall (2,1)->(2,7), 0.5 thick: left of +y is -x
    fp = footprints({'a': [2.0, 1.0], 'b': [2.0, 7.0]}, [wall('w', 'a', 'b')])
    want = [[1.75, 1], [1.75, 7], [2.25, 7], [2.25, 1]]
    check(all(same_pt(p, q) for p, q in zip(fp['w'], want)), f'[from_left, to_left, to_right, from_right]: {fp["w"]}')


def test_t_junction_end_is_square_against_the_through_wall():
    # the stem's end at the joint lies on the through wall's face, not its centre line:
    # through wall t (0,0)->(10,0), stem s (5,0)->(5,6), both 0.5 thick
    j = {'a': [0.0, 0.0], 'b': [10.0, 0.0], 'm': [5.0, 0.0], 'e': [5.0, 6.0]}
    w = [wall('t', 'a', 'b'), wall('s', 'm', 'e', exterior=False)]
    j2, w2 = split_crossings(j, w)
    check(sorted(by_id(w2)) == ['s', 't', 't~2'], f'the through wall splits at the stem: {sorted(by_id(w2))}')
    s = footprints(j2, w2)['s']
    # s runs +y so its left is -x: from_left (4.75, 0.25), from_right (5.25, 0.25) on the face y = 0.25
    check(same_pt(s[0], [4.75, 0.25]), f'stem from_left on the face: {s[0]}')
    check(same_pt(s[3], [5.25, 0.25]), f'stem from_right on the face: {s[3]}')
    check(same_pt(s[1], [4.75, 6]) and same_pt(s[2], [5.25, 6]), f'stem free end square: {s}')


def test_t_junction_leaves_no_hole():
    # Ruling R6: through wall t (0,0)->(10,0) split at (5,0) by a stem s (5,0)->(5,6), all 0.5 thick.
    # A wall with a collinear continuation ends square at the joint on both faces; the stem butts into the face.
    j = {'a': [0.0, 0.0], 'b': [10.0, 0.0], 'm': [5.0, 0.0], 'e': [5.0, 6.0]}
    w = [wall('t', 'a', 'b'), wall('s', 'm', 'e', exterior=False)]
    fp = footprints(*split_crossings(j, w))
    t1, t2, s = fp['t'], fp['t~2'], fp['s']
    check(same_pt(t1[1], [5, 0.25]) and same_pt(t1[2], [5, -0.25]),
          f't ends square at x=5 on both faces: to_left {t1[1]}, to_right {t1[2]}')
    check(same_pt(t2[0], [5, 0.25]) and same_pt(t2[3], [5, -0.25]),
          f't~2 starts square at x=5 on both faces: from_left {t2[0]}, from_right {t2[3]}')
    check(same_pt(t1[0], [0, 0.25]) and same_pt(t2[1], [10, 0.25]), f'free ends untouched: {t1} {t2}')
    check(close(s[0][1], 0.25) and close(s[3][1], 0.25), f"the stem ends on the through wall's face y=0.25: {s}")
    check(same_pt(s[0], [4.75, 0.25]) and same_pt(s[3], [5.25, 0.25]), f'stem end corners: {s}')


def test_four_way_crossing_ends_meet_at_the_faces():
    # the 10x10 plus-sign box, all walls 0.5 thick: h's first part (0,5)->(5,5)
    # starts on the left box wall's inner face (h is a stem there; b3 runs on through it).
    # At the crossing h has a collinear continuation h~2, so by Ruling R6 it ends square at x=5.
    J = {'c0': [0.0, 0.0], 'c1': [10.0, 0.0], 'c2': [10.0, 10.0], 'c3': [0.0, 10.0],
         'h0': [0.0, 5.0], 'h1': [10.0, 5.0], 'v0': [5.0, 0.0], 'v1': [5.0, 10.0]}
    W = [wall('b0', 'c0', 'c1'), wall('b1', 'c1', 'c2'), wall('b2', 'c2', 'c3'), wall('b3', 'c3', 'c0'),
         wall('h', 'h0', 'h1', exterior=False), wall('v', 'v0', 'v1', exterior=False)]
    j, w = split_crossings(J, W)
    h = footprints(j, w)['h']
    want = [[0.25, 5.25], [5, 5.25], [5, 4.75], [0.25, 4.75]]
    check(all(same_pt(p, q) for p, q in zip(h, want)) and len(h) == 4,
          f'h footprint [from_left, to_left, to_right, from_right]: {h}')


def test_near_collinear_t_junction_leaves_no_hole():
    def contains(poly, p):
        # Convex footprints include their boundaries.
        crosses = [(b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
                   for a, b in zip(poly, poly[1:] + poly[:1])]
        return min(crosses) >= -1e-9 or max(crosses) <= 1e-9

    for displacement in (-0.03, 0.03):
        for reverse in (False, True):
            j = {'a': [0, 0], 'b': [10, 0], 'm': [5, displacement], 'e': [5, 6]}
            w = [wall('t', *(['b', 'a'] if reverse else ['a', 'b'])),
                 wall('s', 'm', 'e', exterior=False)]
            fp = footprints(*split_crossings(j, w))
            t1, t2 = fp['t'], fp['t~2']
            check(same_pt(t1[1], t2[0]) and same_pt(t1[2], t2[3]),
                  f'continuation faces meet at their bisector: {t1} {t2}')
            # Sample the joint's thickness-square at cell centres, so the
            # slight tilt of the outside faces does not count as a hole.
            for ix in range(50):
                for iy in range(50):
                    p = [5 - T / 2 + T * (ix + 0.5) / 50,
                         displacement - T / 2 + T * (iy + 0.5) / 50]
                    check(any(contains(poly, p) for poly in fp.values()),
                          f'joint square has an uncovered point {p}: {fp}')


def test_two_degree_mitres_fall_back_to_square_ends():
    for thickness in (T, 0.75):
        for reverse in (False, True):
            angle = math.radians(2)
            j = {'a': [0, 0], 'm': [10, 0],
                 'b': [10 - 6 * math.cos(angle), 6 * math.sin(angle)]}
            w = [wall('a', 'a', 'm'), wall('b', 'm', 'b', thickness=thickness)]
            if reverse:
                for part in w:
                    part['joints'].reverse()
            fp = footprints(j, w)
            for part in w:
                at_start = part['joints'][0] == 'm'
                corners = [fp[part['id']][i] for i in ((0, 3) if at_start else (1, 2))]
                other = j[part['joints'][1 if at_start else 0]]
                direction = [other[i] - j['m'][i] for i in (0, 1)]
                for p in corners:
                    check(math.dist(p, j['m']) <= 2 * max(T, thickness), f'mitre spike: {p}')
                    check(close(sum((p[i] - j['m'][i]) * direction[i] for i in (0, 1)), 0),
                          f'limited side ends square: {p}')


TESTS = (
    test_t_junction_splits_and_makes_two_rooms,
    test_split_parts_copy_every_other_field,
    test_wall_split_twice_numbers_parts_in_order,
    test_crossing_walls_split_into_four_rooms,
    test_t_junction_tolerance_is_five_hundredths,
    test_nothing_to_split_returns_the_same_graph,
    test_regions_are_counter_clockwise_and_match_their_joints,
    test_separator_bounds_rooms_like_a_wall,
    test_gap_leaves_no_region_and_reports_open_ends,
    test_dangling_wall_bounds_nothing,
    test_closed_box_has_no_open_ends,
    test_split_overshoot_shorter_than_one_foot_is_dropped,
    test_short_walls_and_connected_split_parts_survive,
    test_weld_merges_within_one_foot_only,
    test_weld_tolerance_is_a_parameter,
    test_weld_tolerance_is_strict,
    test_weld_never_merges_a_walls_own_ends,
    test_l_corner_footprints_meet_without_a_gap,
    test_free_wall_footprint_is_a_square_ended_rectangle,
    test_t_junction_end_is_square_against_the_through_wall,
    test_t_junction_leaves_no_hole,
    test_four_way_crossing_ends_meet_at_the_faces,
    test_near_collinear_t_junction_leaves_no_hole,
    test_two_degree_mitres_fall_back_to_square_ends,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
