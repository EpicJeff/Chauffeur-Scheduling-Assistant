"""Operations, part 1: walls, joints and rooms (brief .superpowers/sdd/
2026-11-09-house-connected-model-pieces-1-2/task-8-brief.md; spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections
4.1, 4.2, 4.6, 4.6a and 5.3; plan docs/superpowers/plans/2026-11-09-house-
connected-model-pieces-1-2.md Task 8 and Review Focus 2; ledger Rulings R3,
R8, R13).

Module under test: services/twin_model_ops.py
- apply(model, op, actor='person') -> (model, words): the new model and
  plain words.
- class Refused(ValueError), raised with the exact refusal copy.
- Every operation is followed by twin_model.derive, hosts.follow(snapshot),
  roofs.follow_walls, and marking each touched piece src.person when the
  actor is the person.

Operations here (op['op']): move_joint {building, joint, to}, move_wall
{building, wall, by}, add_wall {building, level, from, to, kind?, exterior?},
split_wall {building, wall, at}, draw_room {building, level, polygon, name?},
split_room {building, room, from, to}, move_room {building, room, by},
delete {building, id}.

Readings pinned here (see the report for why):
- move_wall `by` is measured along the wall's left normal: the direction
  joints[0] -> joints[1] turned a quarter turn counter-clockwise. A wall from
  (10,0) to (10,10) with by=+2 lands on x=8.
- split_wall `at` is the distance from the wall's first joint (as an
  opening's `at`, Task 4).
- R3: a wall may not shrink below its widest hosted opening + 1.0 ft
  (MIN_CLEAR each side); exactly that length is allowed.
- R8: delete removes the smaller of two merged rooms before derive, so no
  unclosed flag names it.
- R13: a wall of exactly 1.0 ft survives; shorter is refused.
- R16: drawing across a wall splits both at the crossing; moves that
  would cross are refused; the R3 shrink rule applies to move_joint and
  move_room too.
- A refused operation leaves the model it was given unchanged.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_ops_walls.py
"""
import copy
import math
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_ops_walls_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_model_ops as ops  # noqa: E402

TOL = 1e-6
NOT_CLOSED = "This room isn't closed: a wall is missing here."
CROSS = 'That would cross another wall.'
TOO_SHORT = 'A wall must be at least 1 ft long.'
DOOR_NARROWER = 'That would leave the door narrower than its wall.'
LOT = [[-40, -40], [80, -40], [80, 80], [-40, 80]]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def near(p, q, tol=TOL):
    return close(p[0], q[0], tol) and close(p[1], q[1], tol)


# ---------------------------------------------------------------- fixtures

def _level():
    return {'id': 'L1', 'name': 'main floor', 'elevation': 0, 'ceiling': 9}


def _joint(jid, x, y):
    return {'id': jid, 'level': 'L1', 'at': [x, y]}


def _wall(wid, a, b, exterior=True):
    return {'id': wid, 'level': 'L1', 'joints': [a, b], 'kind': 'solid',
            'thickness': 0.5 if exterior else 0.33, 'exterior': exterior, 'height': 9}


def _room(rid, name, polygon, joints):
    return {'id': rid, 'level': 'L1', 'name': name, 'kind': 'room',
            'polygon': [list(p) for p in polygon], 'joints': list(joints)}


def _door(oid, wall, at, width=3.0, kind='door'):
    sill, head = (0, 7) if kind == 'door' else (3, 7)
    return {'id': oid, 'wall': wall, 'at': at, 'width': width,
            'sill': sill, 'head': head, 'kind': kind}


def _building(joints, walls, rooms, openings=None, roofs=None):
    return {'id': 'B1', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
            'materials': {}, 'levels': [_level()],
            'joints': joints, 'walls': walls, 'rooms': rooms,
            'openings': openings or [], 'anchors': [], 'items': [],
            'roofs': roofs or [], 'dormers': [], 'extensions': [], 'stairs': [],
            'proposals': [], 'flags': []}


def _model(b):
    return {'schema': 'chauffeur.twin.plan/3', 'units': 'ft', 'materials': {},
            'buildings': [b], 'site': {'lot': copy.deepcopy(LOT)}}


def box(w=10, h=10, rid='kitchen', name='Kitchen', openings=None, roofs=None):
    """One room on L1, exterior walls counter-clockwise.

    j4 (0,h) ---n--- j3 (w,h)
     |                  |
     w                  e
     |                  |
    j1 (0,0) ---s--- j2 (w,0)
    """
    joints = [_joint('j1', 0, 0), _joint('j2', w, 0), _joint('j3', w, h), _joint('j4', 0, h)]
    walls = [_wall('s', 'j1', 'j2'), _wall('e', 'j2', 'j3'),
             _wall('n', 'j3', 'j4'), _wall('w', 'j4', 'j1')]
    rooms = [_room(rid, name, [[0, 0], [w, 0], [w, h], [0, h]], ['j1', 'j2', 'j3', 'j4'])]
    return _model(_building(joints, walls, rooms, openings, roofs))


def two_rooms(mid_x=10, openings=None):
    """A 20 x 10 box split by an interior wall `mid` at x = mid_x.

    jf (0,10) --n1-- je (mid,10) --n2-- jd (20,10)
     |                 |                  |
    west    Kitchen   mid    Dining      east
     |                 |                  |
    ja (0,0)  --s1-- jb (mid,0)  --s2-- jc (20,0)

    mid runs jb -> je (upwards), so its left normal points to -x.
    """
    m = mid_x
    joints = [_joint('ja', 0, 0), _joint('jb', m, 0), _joint('jc', 20, 0),
              _joint('jd', 20, 10), _joint('je', m, 10), _joint('jf', 0, 10)]
    walls = [_wall('s1', 'ja', 'jb'), _wall('s2', 'jb', 'jc'), _wall('east', 'jc', 'jd'),
             _wall('n2', 'jd', 'je'), _wall('n1', 'je', 'jf'), _wall('west', 'jf', 'ja'),
             _wall('mid', 'jb', 'je', exterior=False)]
    rooms = [_room('kitchen', 'Kitchen', [[0, 0], [m, 0], [m, 10], [0, 10]], ['ja', 'jb', 'je', 'jf']),
             _room('dining', 'Dining', [[m, 0], [20, 0], [20, 10], [m, 10]], ['jb', 'jc', 'jd', 'je'])]
    return _model(_building(joints, walls, rooms, openings))


# ---------------------------------------------------------------- readers

def bld(m):
    return next(b for b in m['buildings'] if b['id'] == 'B1')


def jpos(b):
    return {j['id']: j['at'] for j in b['joints']}


def ends(b, w):
    pos = jpos(b)
    return pos[w['joints'][0]], pos[w['joints'][1]]


def wall_by_id(b, wid):
    return next((w for w in b['walls'] if w['id'] == wid), None)


def length(b, w):
    p, q = ends(b, w)
    return math.hypot(q[0] - p[0], q[1] - p[1])


def on_line(p, a, b, tol=1e-6):
    # p lies on the infinite line through a and b
    dx, dy = b[0] - a[0], b[1] - a[1]
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / math.hypot(dx, dy) <= tol


def walls_on_line(b, a, c):
    """Walls whose two ends lie on the line through a and c, inside the segment a-c."""
    out = []
    for w in b['walls']:
        p, q = ends(b, w)
        if not (on_line(p, a, c) and on_line(q, a, c)):
            continue
        lo_x, hi_x = sorted((a[0], c[0]))
        lo_y, hi_y = sorted((a[1], c[1]))
        if all(lo_x - TOL <= r[0] <= hi_x + TOL and lo_y - TOL <= r[1] <= hi_y + TOL for r in (p, q)):
            out.append(w)
    return out


def overlap(b, w1, w2):
    """Shared length of two collinear walls (0 when they only touch)."""
    p1, q1 = ends(b, w1)
    p2, q2 = ends(b, w2)
    dx, dy = q1[0] - p1[0], q1[1] - p1[1]
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n

    def t(r):
        return (r[0] - p1[0]) * ux + (r[1] - p1[1]) * uy

    a1, b1 = sorted((t(p1), t(q1)))
    a2, b2 = sorted((t(p2), t(q2)))
    return max(0.0, min(b1, b2) - max(a1, a2))


def no_overlaps(b, walls):
    for i in range(len(walls)):
        for k in range(i + 1, len(walls)):
            if overlap(b, walls[i], walls[k]) > 1e-6:
                return False
    return True


def area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def corners(poly):
    """The polygon's corner set, without collinear vertices left by T joints."""
    out = set()
    n = len(poly)
    for i in range(n):
        a, p, c = poly[i - 1], poly[i], poly[(i + 1) % n]
        cross = (p[0] - a[0]) * (c[1] - p[1]) - (p[1] - a[1]) * (c[0] - p[0])
        if abs(cross) > 1e-6:
            out.add((round(p[0], 6), round(p[1], 6)))
    return out


def rect_corners(x0, y0, x1, y1):
    return {(x0, y0), (x1, y0), (x1, y1), (x0, y1)}


def room_by_id(b, rid):
    return next((r for r in b['rooms'] if r['id'] == rid), None)


def rooms_named(b, name):
    return [r for r in b['rooms'] if r.get('name') == name]


def unclosed(b):
    return [f for f in b.get('flags', []) if f.get('text') == NOT_CLOSED]


def opening(b, oid):
    return next(o for o in b['openings'] if o['id'] == oid)


def centre(b, o):
    """The opening's centre on its host wall's centreline, `at` from joints[0]."""
    w = wall_by_id(b, o['wall'])
    check(w is not None, f"opening {o['id']} sits on a wall that is gone: {o['wall']}")
    p, q = ends(b, w)
    n = math.hypot(q[0] - p[0], q[1] - p[1])
    return [p[0] + (q[0] - p[0]) * o['at'] / n, p[1] + (q[1] - p[1]) * o['at'] / n]


def joints_welded(b):
    pts = [j['at'] for j in b['joints'] if j.get('level', 'L1') == 'L1']
    for i in range(len(pts)):
        for k in range(i + 1, len(pts)):
            if math.hypot(pts[i][0] - pts[k][0], pts[i][1] - pts[k][1]) < 1.0:
                return False
    return True


def person(piece):
    return bool((piece.get('src') or {}).get('person'))


def run(m, op, actor=None):
    """apply on a copy; check the words are plain text; return the building."""
    op = dict(op, building='B1')
    if actor is None:
        out, words = ops.apply(copy.deepcopy(m), op)
    else:
        out, words = ops.apply(copy.deepcopy(m), op, actor=actor)
    check(isinstance(words, str) and words.strip(), f'{op["op"]} gave no plain words: {words!r}')
    check(isinstance(out, dict) and out.get('buildings'), f'{op["op"]} gave no model')
    return bld(out)


def refused(m, op, text):
    """apply raises Refused with exactly `text`, and the given model is untouched."""
    op = dict(op, building='B1')
    before = copy.deepcopy(m)
    try:
        result = ops.apply(m, op)
    except ops.Refused as exc:
        check(str(exc) == text, f'{op["op"]} refused with {str(exc)!r}, want {text!r}')
        check(m == before, f'a refused {op["op"]} changed the model it was given')
        return
    raise AssertionError(f'{op["op"]} was accepted, want the refusal {text!r}: {result!r}'[:600])


# ---------------------------------------------------------------- walls and joints

def test_shared_wall_drag_resizes_both_rooms():
    """Dragging the wall between Kitchen and Dining resizes both rooms; the
    rooms keep their ids and names, and the walls joined to it stretch."""
    check(issubclass(ops.Refused, ValueError), 'Refused must be a ValueError')

    b = run(two_rooms(), {'op': 'move_wall', 'wall': 'mid', 'by': 2})
    mid = wall_by_id(b, 'mid')
    check(mid is not None, 'the dragged wall kept its id')
    p, q = ends(b, mid)
    check(close(p[0], 8) and close(q[0], 8), f'by +2 along the left normal puts mid on x=8: {p}, {q}')
    check({round(p[1], 6), round(q[1], 6)} == {0, 10}, f'mid still spans y 0..10: {p}, {q}')
    kitchen, dining = room_by_id(b, 'kitchen'), room_by_id(b, 'dining')
    check(kitchen and kitchen['name'] == 'Kitchen', b['rooms'])
    check(dining and dining['name'] == 'Dining', b['rooms'])
    check(close(area(kitchen['polygon']), 80), f"Kitchen 8 x 10: {kitchen['polygon']}")
    check(close(area(dining['polygon']), 120), f"Dining 12 x 10: {dining['polygon']}")
    check(corners(kitchen['polygon']) == rect_corners(0, 0, 8, 10), kitchen['polygon'])
    check(corners(dining['polygon']) == rect_corners(8, 0, 20, 10), dining['polygon'])
    check(close(length(b, wall_by_id(b, 's1')), 8) and close(length(b, wall_by_id(b, 's2')), 12),
          'the walls on mid\'s joints stretch')
    check(len(b['rooms']) == 2 and not unclosed(b), (b['rooms'], b['flags']))

    # The other way: by -2 puts mid on x=12.
    b = run(two_rooms(), {'op': 'move_wall', 'wall': 'mid', 'by': -2})
    check(close(area(room_by_id(b, 'kitchen')['polygon']), 120), b['rooms'])
    check(close(area(room_by_id(b, 'dining')['polygon']), 80), b['rooms'])


def test_move_joint_moves_every_wall_on_it():
    """Moving the T joint jb to (12, 0) moves s1, s2 and mid with it: Kitchen
    becomes a 110 sq ft trapezoid and Dining 90."""
    b = run(two_rooms(), {'op': 'move_joint', 'joint': 'jb', 'to': [12, 0]})
    check(near(jpos(b)['jb'], [12, 0]), jpos(b))
    check(close(length(b, wall_by_id(b, 's1')), 12), 's1 stretched to 12')
    check(close(length(b, wall_by_id(b, 's2')), 8), 's2 shrank to 8')
    p, q = ends(b, wall_by_id(b, 'mid'))
    check({(round(p[0], 6), round(p[1], 6)), (round(q[0], 6), round(q[1], 6))} == {(12, 0), (10, 10)},
          f'mid now runs (12,0)-(10,10): {p}, {q}')
    check(close(area(room_by_id(b, 'kitchen')['polygon']), 110), room_by_id(b, 'kitchen'))
    check(close(area(room_by_id(b, 'dining')['polygon']), 90), room_by_id(b, 'dining'))
    check(not unclosed(b), b['flags'])


def test_move_wall_carries_its_roof_edge():
    """roofs.follow_walls runs after an operation: the east wall moves out
    2 ft and the roof edge attached to it moves 2 ft with it."""
    roof = {'id': 'roof1', 'level': 'L1', 'area': [[0, 0], [10, 0], [10, 10], [0, 10]],
            'edges': [{'setting': 'sloped', 'pitch': 6, 'wall': 's'},
                      {'setting': 'sloped', 'pitch': 6, 'wall': 'e'},
                      {'setting': 'sloped', 'pitch': 6, 'wall': 'n'},
                      {'setting': 'sloped', 'pitch': 6, 'wall': 'w'}],
            'plate': 9, 'overhang': 1}
    b = run(box(roofs=[roof]), {'op': 'move_wall', 'wall': 'e', 'by': -2})
    p, q = ends(b, wall_by_id(b, 'e'))
    check(close(p[0], 12) and close(q[0], 12), f'e moved to x=12: {p}, {q}')
    got = b['roofs'][0]
    want = {(0, 0), (12, 0), (12, 10), (0, 10)}
    check({(round(x, 6), round(y, 6)) for x, y in got['area']} == want, got['area'])
    check(got['edges'][1].get('wall') == 'e', got['edges'])
    check(close(area(room_by_id(b, 'kitchen')['polygon']), 120), b['rooms'])


def test_move_wall_too_far_past_a_door_is_refused():
    """Review Focus 2 with R3: the east wall is pushed in past a 3 ft door on
    the south wall. The door clamps onto the shortened wall; the wall may
    shrink to 3 + 1.0 = 4 ft and no further."""
    m = box(openings=[_door('d1', 's', 8)])

    # In 3 ft: s is 7 long; the door keeps 8 ft from j1 and clamps to 7 - 0.5 - 1.5.
    b = run(m, {'op': 'move_wall', 'wall': 'e', 'by': 3})
    check(close(length(b, wall_by_id(b, 's')), 7), 's is 7 ft')
    d = opening(b, 'd1')
    check(d['wall'] == 's' and d.get('state') != 'ghost', d)
    check(close(d['at'], 5), f'door clamped onto the 7 ft wall at 5: {d}')

    # In 6 ft: s is exactly 4 ft, door width + 1.0, allowed; the door sits at 2.
    b = run(m, {'op': 'move_wall', 'wall': 'e', 'by': 6})
    check(close(length(b, wall_by_id(b, 's')), 4), 's is 4 ft')
    d = opening(b, 'd1')
    check(d['wall'] == 's' and d.get('state') != 'ghost' and close(d['at'], 2), d)
    check(close(d['width'], 3), 'the door keeps its width')

    # In 6.25 ft: s would be 3.75 ft, under 4: refused, nothing changes.
    refused(m, {'op': 'move_wall', 'wall': 'e', 'by': 6.25}, DOOR_NARROWER)


def test_a_move_that_crosses_a_wall_is_refused():
    """Dragging corner j1 to (12, 5) would make the west wall cross the east wall."""
    refused(box(), {'op': 'move_joint', 'joint': 'j1', 'to': [12, 5]}, CROSS)


def test_a_wall_under_1_ft_is_refused():
    """R13: a wall of exactly 1.0 ft is kept; anything shorter is refused,
    whether drawn, split off or squeezed by a joint drag."""
    refused(box(), {'op': 'add_wall', 'level': 'L1', 'from': [3, 3], 'to': [3.5, 3]}, TOO_SHORT)
    refused(box(), {'op': 'split_wall', 'wall': 's', 'at': 0.5}, TOO_SHORT)
    refused(box(), {'op': 'split_wall', 'wall': 's', 'at': 9.5}, TOO_SHORT)
    refused(box(), {'op': 'move_joint', 'joint': 'j2', 'to': [0.5, 0]}, TOO_SHORT)

    b = run(box(), {'op': 'add_wall', 'level': 'L1', 'from': [0, 5], 'to': [1, 5]})
    stub = [w for w in b['walls'] if {tuple(map(lambda v: round(v, 6), r)) for r in ends(b, w)}
            == {(0, 5), (1, 5)}]
    check(len(stub) == 1 and close(length(b, stub[0]), 1.0), f'the 1 ft wall survives: {b["walls"]}')


def test_add_wall_from_a_wall_splits_it_at_a_T():
    """A wall drawn from the south wall to the north wall splits both at new
    joints shared with it, and splits the room: the larger part keeps the
    identity, the other is named Room. kind defaults to solid."""
    b = run(box(w=10, h=8, rid='liv', name='Living'),
            {'op': 'add_wall', 'level': 'L1', 'from': [6, 0], 'to': [6, 8]})
    new = walls_on_line(b, [6, 0], [6, 8])
    check(len(new) == 1 and new[0].get('kind', 'solid') == 'solid', new)
    south = walls_on_line(b, [0, 0], [10, 0])
    check(sorted(round(length(b, w), 6) for w in south) == [4, 6], f'the south wall split at x=6: {south}')
    check(no_overlaps(b, south), south)
    shared = set(new[0]['joints']) & {j for w in south for j in w['joints']}
    check(len(shared) == 1 and near(jpos(b)[shared.pop()], [6, 0]), 'the T joint is shared, not a near miss')
    check(joints_welded(b), [j['at'] for j in b['joints']])
    living = room_by_id(b, 'liv')
    check(living and living['name'] == 'Living' and close(area(living['polygon']), 48), b['rooms'])
    others = [r for r in b['rooms'] if r['id'] != 'liv']
    check(len(others) == 1 and others[0]['name'] == 'Room' and close(area(others[0]['polygon']), 32),
          b['rooms'])


def test_add_wall_across_a_wall_splits_both():
    """R16: a wall drawn across mid, from the west wall to the east wall,
    splits mid and itself at the crossing (10, 5); four 50 sq ft rooms, and
    the door on mid stays where it was."""
    m = two_rooms(openings=[_door('dm', 'mid', 7, width=2)])
    b = run(m, {'op': 'add_wall', 'level': 'L1', 'from': [0, 5], 'to': [20, 5]})
    across = walls_on_line(b, [0, 5], [20, 5])
    check(sorted(round(length(b, w), 6) for w in across) == [10, 10], f'the new wall split at x=10: {across}')
    check(no_overlaps(b, across), across)
    upright = walls_on_line(b, [10, 0], [10, 10])
    check(sorted(round(length(b, w), 6) for w in upright) == [5, 5], f'mid split at y=5: {upright}')
    cross = [jid for jid, at in jpos(b).items() if near(at, [10, 5])]
    check(len(cross) == 1, f'one joint at the crossing: {cross}')
    check(sum(cross[0] in w['joints'] for w in b['walls']) == 4, 'four walls meet at the crossing')
    check(joints_welded(b), [j['at'] for j in b['joints']])
    check(len(b['rooms']) == 4 and all(close(area(r['polygon']), 50) for r in b['rooms']), b['rooms'])
    kitchen, dining = room_by_id(b, 'kitchen'), room_by_id(b, 'dining')
    check(kitchen and kitchen['name'] == 'Kitchen' and all(x <= 10 + TOL for x, _ in kitchen['polygon']),
          f'Kitchen keeps a left quarter: {kitchen}')
    check(dining and dining['name'] == 'Dining' and all(x >= 10 - TOL for x, _ in dining['polygon']),
          f'Dining keeps a right quarter: {dining}')
    check(len(rooms_named(b, 'Room')) == 2, b['rooms'])
    d = opening(b, 'dm')
    check(d.get('state') != 'ghost' and near(centre(b, d), [10, 7]), d)
    check(not unclosed(b), b['flags'])


def test_move_joint_that_shrinks_a_door_wall_is_refused():
    """R16: the R3 shrink rule holds for move_joint and move_room too. A 3 ft
    door's wall may shrink to 4 ft and no further."""
    m = box(openings=[_door('d1', 's', 8)])
    b = run(m, {'op': 'move_joint', 'joint': 'j2', 'to': [4, 0]})
    check(close(length(b, wall_by_id(b, 's')), 4), 's is exactly 4 ft')
    d = opening(b, 'd1')
    check(d['wall'] == 's' and d.get('state') != 'ghost' and close(d['at'], 2), d)
    refused(m, {'op': 'move_joint', 'joint': 'j2', 'to': [3.75, 0]}, DOOR_NARROWER)

    # move_room: Kitchen slides 6.25 ft east, squeezing s2 (and its door) to 3.75 ft.
    m = two_rooms(openings=[_door('d2', 's2', 5)])
    refused(m, {'op': 'move_room', 'room': 'kitchen', 'by': [6.25, 0]}, DOOR_NARROWER)
    b = run(m, {'op': 'move_room', 'room': 'kitchen', 'by': [6, 0]})
    check(close(length(b, wall_by_id(b, 's2')), 4), 's2 is exactly 4 ft')
    check(opening(b, 'd2').get('state') != 'ghost', opening(b, 'd2'))


def test_split_wall_keeps_the_door_where_it_was():
    """split_wall at 4 makes a joint at (4, 0) and two walls of 4 and 6 ft;
    the door centred 8 ft along stays at (8, 0) on the half that holds it."""
    b = run(box(openings=[_door('d1', 's', 8)]), {'op': 'split_wall', 'wall': 's', 'at': 4})
    south = walls_on_line(b, [0, 0], [10, 0])
    check(sorted(round(length(b, w), 6) for w in south) == [4, 6], south)
    check(any(near(p, [4, 0]) for p in jpos(b).values()), 'a joint at (4, 0)')
    d = opening(b, 'd1')
    check(d.get('state') != 'ghost', d)
    check(d['wall'] in {w['id'] for w in south}, d)
    check(near(centre(b, d), [8, 0]), f'the door did not move: {centre(b, d)}')
    check(len(b['rooms']) == 1 and close(area(b['rooms'][0]['polygon']), 100), b['rooms'])
    check(not unclosed(b), b['flags'])


def test_wall_drawn_over_an_existing_wall_merges_into_one():
    """Spec 4.1: a wall drawn over an existing wall merges with it, so there
    is one wall per line, and the door on it stays where it was."""
    m = box(openings=[_door('d1', 's', 3)])

    # Exactly over s.
    b = run(m, {'op': 'add_wall', 'level': 'L1', 'from': [0, 0], 'to': [10, 0]})
    check(len(b['walls']) == 4, f'no second wall: {[w["id"] for w in b["walls"]]}')
    check(len(walls_on_line(b, [0, 0], [10, 0])) == 1, b['walls'])
    d = opening(b, 'd1')
    check(d.get('state') != 'ghost' and near(centre(b, d), [3, 0]), d)

    # Drawn a little off, within the 1 ft weld of j1 and j2: still the same wall.
    b = run(m, {'op': 'add_wall', 'level': 'L1', 'from': [0.4, 0.3], 'to': [9.7, -0.2]})
    check(len(b['walls']) == 4, f'welded onto s, merged: {b["walls"]}')
    check(near(jpos(b)['j1'], [0, 0]) and near(jpos(b)['j2'], [10, 0]),
          f'the existing joints win over the drawn ends, never averaged: {jpos(b)}')
    check(joints_welded(b), [j['at'] for j in b['joints']])
    check(near(centre(b, opening(b, 'd1')), [3, 0]), opening(b, 'd1'))

    # Half over s and half past the corner: one run along y=0, nothing doubled.
    b = run(m, {'op': 'add_wall', 'level': 'L1', 'from': [5, 0], 'to': [15, 0]})
    line = walls_on_line(b, [0, 0], [15, 0])
    check(no_overlaps(b, line), f'walls overlap on y=0: {line}')
    check(close(sum(length(b, w) for w in line), 15), f'y=0 covered once, 15 ft: {line}')
    check(joints_welded(b), [j['at'] for j in b['joints']])
    d = opening(b, 'd1')
    check(d.get('state') != 'ghost' and near(centre(b, d), [3, 0]), d)
    check(close(area(room_by_id(b, 'kitchen')['polygon']), 100), b['rooms'])


# ---------------------------------------------------------------- rooms

def test_draw_room_beside_a_room_shares_one_wall():
    """A room drawn against Kitchen's east wall reuses it: one wall on the
    shared line, the window on it stays hosted, and the corners weld."""
    m = box(openings=[_door('win', 'e', 5, kind='window')])
    b = run(m, {'op': 'draw_room', 'level': 'L1', 'name': 'Dining',
                'polygon': [[10, 0], [20, 0], [20, 10], [10, 10]]})
    shared = walls_on_line(b, [10, 0], [10, 10])
    check(len(shared) == 1, f'one wall on the shared line, got {len(shared)}: {shared}')
    check(len(b['walls']) == 7, f'4 + 3 new walls: {[w["id"] for w in b["walls"]]}')
    check(joints_welded(b), [j['at'] for j in b['joints']])
    win = opening(b, 'win')
    check(win.get('state') != 'ghost' and near(centre(b, win), [10, 5]), win)
    kitchen = room_by_id(b, 'kitchen')
    check(kitchen['name'] == 'Kitchen' and close(area(kitchen['polygon']), 100), b['rooms'])
    dining = rooms_named(b, 'Dining')
    check(len(dining) == 1 and dining[0]['id'] != 'kitchen', b['rooms'])
    check(corners(dining[0]['polygon']) == rect_corners(10, 0, 20, 10), dining[0]['polygon'])
    check(len(b['rooms']) == 2 and not unclosed(b), (b['rooms'], b['flags']))


def test_draw_room_partly_against_a_wall_splits_it_not_doubles_it():
    """A 6 x 6 room drawn against the middle of Kitchen's east wall splits it
    at (10, 2) and (10, 8) instead of laying a second wall over it."""
    m = box(openings=[_door('win', 'e', 5, kind='window')])
    b = run(m, {'op': 'draw_room', 'level': 'L1', 'name': 'Study',
                'polygon': [[10, 2], [16, 2], [16, 8], [10, 8]]})
    line = walls_on_line(b, [10, 0], [10, 10])
    check(no_overlaps(b, line), f'walls overlap on x=10: {line}')
    check(close(sum(length(b, w) for w in line), 10), f'x=10 covered once: {line}')
    check(sorted(round(length(b, w), 6) for w in line) == [2, 2, 6], line)
    check(joints_welded(b), [j['at'] for j in b['joints']])
    win = opening(b, 'win')
    check(win.get('state') != 'ghost' and near(centre(b, win), [10, 5]), win)
    check(close(area(room_by_id(b, 'kitchen')['polygon']), 100), b['rooms'])
    study = rooms_named(b, 'Study')
    check(len(study) == 1 and close(area(study[0]['polygon']), 36), b['rooms'])


def test_split_room_adds_a_separator_and_a_room_named_Room():
    """split_room adds one invisible separator across Living; Living keeps
    its id on the larger 48 sq ft part and the 32 sq ft part is named Room."""
    b = run(box(w=10, h=8, rid='liv', name='Living'),
            {'op': 'split_room', 'room': 'liv', 'from': [6, 0], 'to': [6, 8]})
    seps = [w for w in b['walls'] if w.get('kind') == 'separator']
    check(len(seps) == 1, f'one separator: {seps}')
    p, q = ends(b, seps[0])
    check({(round(p[0], 6), round(p[1], 6)), (round(q[0], 6), round(q[1], 6))} == {(6, 0), (6, 8)},
          f'the separator runs (6,0)-(6,8): {p}, {q}')
    check(close(seps[0].get('thickness', 0), 0), f'a separator has no thickness: {seps[0]}')
    check(len([w for w in b['walls'] if w.get('kind', 'solid') == 'solid']) == 6,
          'the south and north walls split at the separator, nothing else')
    check(joints_welded(b), [j['at'] for j in b['joints']])
    living = room_by_id(b, 'liv')
    check(living['name'] == 'Living' and close(area(living['polygon']), 48), b['rooms'])
    check(corners(living['polygon']) == rect_corners(0, 0, 6, 8), living['polygon'])
    other = [r for r in b['rooms'] if r['id'] != 'liv']
    check(len(other) == 1 and other[0]['name'] == 'Room', b['rooms'])
    check(close(area(other[0]['polygon']), 32), other[0])
    check(not unclosed(b), b['flags'])


def test_move_room_stretches_the_neighbour_not_tears():
    """Moving Dining 3 ft east moves all four of its joints; Kitchen's walls
    on the shared joints stretch, so the two rooms still share one wall and
    Kitchen grows to 13 x 10. Doors keep their places by the follow rule."""
    m = two_rooms(openings=[_door('dk', 's1', 3), _door('dd', 'east', 4)])
    b = run(m, {'op': 'move_room', 'room': 'dining', 'by': [3, 0]})
    pos = jpos(b)
    check(near(pos['ja'], [0, 0]) and near(pos['jf'], [0, 10]), 'Kitchen\'s own corners stay')
    for jid, want in (('jb', [13, 0]), ('jc', [23, 0]), ('jd', [23, 10]), ('je', [13, 10])):
        check(near(pos[jid], want), f'{jid} moved to {want}: {pos[jid]}')
    check(len(b['walls']) == 7, [w['id'] for w in b['walls']])
    check(len(walls_on_line(b, [13, 0], [13, 10])) == 1, 'one shared wall, not two')
    kitchen, dining = room_by_id(b, 'kitchen'), room_by_id(b, 'dining')
    check(kitchen['name'] == 'Kitchen' and corners(kitchen['polygon']) == rect_corners(0, 0, 13, 10),
          kitchen['polygon'])
    check(dining['name'] == 'Dining' and corners(dining['polygon']) == rect_corners(13, 0, 23, 10),
          dining['polygon'])
    check(close(area(kitchen['polygon']), 130) and close(area(dining['polygon']), 100), b['rooms'])
    check(not unclosed(b), b['flags'])
    check(close(opening(b, 'dk')['at'], 3) and near(centre(b, opening(b, 'dk')), [3, 0]),
          f"Kitchen's door keeps 3 ft from the end that stayed: {opening(b, 'dk')}")
    check(close(opening(b, 'dd')['at'], 4) and near(centre(b, opening(b, 'dd')), [23, 4]),
          f"Dining's door rides along with its wall: {opening(b, 'dd')}")


def test_delete_wall_merges_two_rooms_keeping_the_larger_name():
    """Deleting the wall between two rooms leaves one 200 sq ft room with the
    larger room's id and name; R8: the smaller room is removed, not flagged."""
    b = run(two_rooms(mid_x=12), {'op': 'delete', 'id': 'mid'})
    check(wall_by_id(b, 'mid') is None, 'mid is gone')
    check(len(b['rooms']) == 1, b['rooms'])
    r = b['rooms'][0]
    check(r['id'] == 'kitchen' and r['name'] == 'Kitchen', f'Kitchen (120) outranks Dining (80): {r}')
    check(close(area(r['polygon']), 200), r['polygon'])
    check(not unclosed(b), f'R8: no unclosed flag after a deliberate merge: {b["flags"]}')
    check('Dining' not in repr(b.get('flags', [])), b['flags'])

    # The other way round: Dining is the larger and keeps the merged room.
    b = run(two_rooms(mid_x=8), {'op': 'delete', 'id': 'mid'})
    check(len(b['rooms']) == 1, b['rooms'])
    r = b['rooms'][0]
    check(r['id'] == 'dining' and r['name'] == 'Dining', f'Dining (120) outranks Kitchen (80): {r}')
    check(close(area(r['polygon']), 200) and not unclosed(b), (r, b['flags']))


def test_delete_wall_keeps_its_door_as_a_flagged_ghost():
    """hosts.follow runs after delete: the door on the deleted wall is kept,
    turned ghost and flagged, never deleted with it."""
    b = run(two_rooms(mid_x=12, openings=[_door('dm', 'mid', 5)]), {'op': 'delete', 'id': 'mid'})
    d = opening(b, 'dm')
    check(d.get('state') == 'ghost', d)
    check(close(d['width'], 3) and d['kind'] == 'door', d)
    flags = [f for f in b['flags'] if f.get('text') == 'This door lost its wall; place it again.']
    check(len(flags) == 1 and flags[0].get('piece') == 'dm', b['flags'])


# ---------------------------------------------------------------- ownership

def test_ops_mark_touched_walls_person_owned():
    """Spec 4.6a: every wall a person's operation touched is the person's,
    including the walls stretched by a joint drag; untouched walls are not,
    and the reader's operations mark nothing."""
    b = run(two_rooms(), {'op': 'move_joint', 'joint': 'jb', 'to': [12, 0]})
    owned = {w['id'] for w in b['walls'] if person(w)}
    check(owned == {'s1', 's2', 'mid'}, f'the three walls on jb, no others: {owned}')

    b = run(two_rooms(), {'op': 'move_wall', 'wall': 'mid', 'by': 2})
    owned = {w['id'] for w in b['walls'] if person(w)}
    check(owned == {'mid', 's1', 's2', 'n1', 'n2'}, f'mid and the four walls it stretched: {owned}')

    b = run(box(w=10, h=8, rid='liv', name='Living'),
            {'op': 'add_wall', 'level': 'L1', 'from': [6, 0], 'to': [6, 8]})
    new = walls_on_line(b, [6, 0], [6, 8])
    check(len(new) == 1 and person(new[0]), f'a drawn wall is the person\'s: {new}')
    check(not person(wall_by_id(b, 'e')) and not person(wall_by_id(b, 'w')), 'e and w untouched')

    b = run(two_rooms(), {'op': 'move_joint', 'joint': 'jb', 'to': [12, 0]}, actor='reader')
    check(near(jpos(b)['jb'], [12, 0]), 'the reader\'s move still applies')
    owned = [w['id'] for w in b['walls'] if person(w)]
    check(owned == [], f'a reader operation marks nothing: {owned}')


def household():
    from test_twin_model_bridge import _migrated
    return copy.deepcopy(_migrated()[0])


def test_household_crossing_rooms_can_move():
    for prefix in ('room:48bcc328', 'room:70e732ca', 'room:ef8bd041'):
        m = household()
        b = next(b for b in m['buildings'] if b['id'] == 'main-house')
        room = next(r for r in b['rooms'] if r['id'].startswith(prefix))
        names = {r['id']: r['name'] for r in b['rooms']}
        original = copy.deepcopy(m)
        out, _ = ops.apply(m, {'op': 'move_room', 'building': b['id'],
                               'room': room['id'], 'by': [1, 0]})
        got = next(b for b in out['buildings'] if b['id'] == 'main-house')
        check({r['id']: r['name'] for r in got['rooms']} == names, got['rooms'])
        check(not unclosed(got), got['flags'])
        check(m == original, 'successful promotion mutated its input')


def test_household_crossing_wall_moves_without_tearing_a_room():
    m, _ = ops.twin_model.normalize(household())
    before = next(b for b in m['buildings'] if b['id'] == 'main-house')
    neighbour_id = 'room:48bcc32861704cc6b6edc5291031c3f8'
    polygon = room_by_id(before, neighbour_id)['polygon']
    expected_area = area(polygon) + 0.5 * (max(x for x, _ in polygon) - min(x for x, _ in polygon))
    out, _ = ops.apply(m, {'op': 'move_wall', 'building': 'main-house',
                           'wall': 'wall:203cf0d790da46f9a96eebc1fded5485', 'by': 0.5})
    b = next(b for b in out['buildings'] if b['id'] == 'main-house')
    check(not unclosed(b), b['flags'])
    small = room_by_id(b, 'room:70e732ca372344819e70454c92e85918')
    neighbour = room_by_id(b, neighbour_id)
    check(small is not None and neighbour is not None, b['rooms'])
    check(close(area(neighbour['polygon']), expected_area), neighbour['polygon'])


def crossing_nub():
    m = two_rooms()
    b = bld(m)
    b['joints'].extend([_joint('left', 0, 5), _joint('nub', 10.17, 5)])
    b['walls'].append(_wall('cross', 'left', 'nub', exterior=False))
    return ops.twin_model.normalize(m)[0]


def test_move_joint_promotes_crossings_only_on_its_incident_walls():
    m = crossing_nub()
    b = run(m, {'op': 'move_joint', 'joint': 'jb', 'to': [11, 0]})
    check(len(b['rooms']) == 3 and not unclosed(b), (b['rooms'], b['flags']))
    crossing = [j['id'] for j in b['joints'] if near(j['at'], [10, 5])]
    check(len(crossing) == 1, b['joints'])
    check(sum(crossing[0] in w['joints'] for w in b['walls']) == 3, b['walls'])
    unrelated = run(m, {'op': 'move_joint', 'joint': 'jc', 'to': [21, 0]})
    check(not any(near(j['at'], [10, 5]) for j in unrelated['joints']), unrelated['joints'])


def test_untouched_reader_window_keeps_its_position_ghost_flag_and_owner():
    for actor in ('person', 'reader'):
        m = household()
        b = next(b for b in m['buildings'] if b['id'] == 'main-house')
        window = next(p for p in b['openings'] if p['id'].startswith('opening:f244c24e'))
        flags = [f for f in b['flags'] if f.get('piece') == window['id']]
        out, _ = ops.apply(m, {'op': 'move_wall', 'building': 'main-house',
                               'wall': 'wall:203cf0d790da46f9a96eebc1fded5485', 'by': 0.5}, actor)
        got = next(b for b in out['buildings'] if b['id'] == 'main-house')
        check(opening(got, window['id']) == window, opening(got, window['id']))
        check([f for f in got['flags'] if f.get('piece') == window['id']] == flags, got['flags'])


def test_delete_changing_removes_exclusive_edges_and_flags_surface_items():
    m = household()
    b = next(b for b in m['buildings'] if b['id'] == 'pool-house')
    room = next(r for r in b['rooms'] if r['name'] == 'CHANGING')
    before_rooms = {r['id'] for r in b['rooms']}
    shared = {w['id'] for w in b['walls'] if set(w['joints']) in
              [set(pair) for other in b['rooms'] if other is not room
               for pair in zip(other['joints'], other['joints'][1:] + other['joints'][:1])]}
    b['anchors'].append({'id': 'changing-light', 'kind': 'light',
                          'host': {'ceiling': room['id'], 'u': 0.5, 'v': 0.5}})
    b['items'].append({'id': 'changing-table', 'asset': 'table',
                       'host': {'floor': room['id'], 'u': 0.5, 'v': 0.5}})
    out, words = ops.apply(m, {'op': 'delete', 'building': 'pool-house', 'id': room['id']})
    got = next(b for b in out['buildings'] if b['id'] == 'pool-house')
    check(wall_by_id(got, 'wall:066fd0b4f0044afc972a7a5c39a2f883') is None, got['walls'])
    check(shared <= {w['id'] for w in got['walls']}, 'a shared edge was removed')
    check({r['id'] for r in got['rooms']} == before_rooms - {room['id']}, got['rooms'])
    check(words.startswith('Deleted the CHANGING.'), words)
    for name, pid, kind in (('anchors', 'changing-light', 'light'), ('items', 'changing-table', 'table')):
        piece = next(p for p in got[name] if p['id'] == pid)
        check(piece.get('state') == 'ghost', piece)
        check(any(f.get('piece') == pid and f.get('text') ==
                  f'This {kind} lost its surface; place it again.' for f in got['flags']), got['flags'])


def test_delete_room_sharing_every_edge_is_refused():
    # Use a 3-by-3 grid so every inner boundary has a neighbour.
    model = box(w=30, h=30)
    for x in (10, 20):
        model, _ = ops.apply(model, {'op': 'add_wall', 'building': 'B1', 'level': 'L1',
                                     'from': [x, 0], 'to': [x, 30]})
    for y in (10, 20):
        model, _ = ops.apply(model, {'op': 'add_wall', 'building': 'B1', 'level': 'L1',
                                     'from': [0, y], 'to': [30, y]})
    inner = next(r for r in bld(model)['rooms'] if corners(r['polygon']) == rect_corners(10, 10, 20, 20))
    refused(model, {'op': 'delete', 'id': inner['id']},
            'This room shares every wall; delete a wall to merge it.')


def test_delete_straight_joint_merges_walls_and_keeps_hosts():
    m = box(openings=[_door('win', 's', 8, width=2, kind='window')])
    out, _ = ops.apply(m, {'op': 'split_wall', 'building': 'B1', 'wall': 's', 'at': 4})
    joint = next(j['id'] for j in bld(out)['joints'] if near(j['at'], [4, 0]))
    b = run(out, {'op': 'delete', 'id': joint})
    check(len(b['walls']) == 4 and joint not in jpos(b), b['walls'])
    check(len(b['rooms']) == 1 and close(area(b['rooms'][0]['polygon']), 100), b['rooms'])
    check(near(centre(b, opening(b, 'win')), [8, 0]) and opening(b, 'win').get('state') != 'ghost',
          opening(b, 'win'))
    check(not unclosed(b), b['flags'])


def test_delete_corner_and_T_joint_are_refused():
    text = 'Only a straight joint between two walls can be removed.'
    refused(box(), {'op': 'delete', 'id': 'j1'}, text)
    refused(two_rooms(), {'op': 'delete', 'id': 'jb'}, text)


def test_delete_joint_between_different_kinds_is_refused():
    """M6: merging keeps one wall's kind; a solid wall never turns invisible."""
    m = box()
    out, _ = ops.apply(m, {'op': 'split_wall', 'building': 'B1', 'wall': 's', 'at': 4})
    b = bld(out)
    joint = next(j['id'] for j in b['joints'] if near(j['at'], [4, 0]))
    halves = [w for w in b['walls'] if joint in w['joints']]
    check(len(halves) == 2, halves)
    halves[1]['kind'], halves[1]['thickness'] = 'separator', 0
    refused(out, {'op': 'delete', 'id': joint},
            'Only a joint between two walls of the same kind can be removed.')
    halves[1].update(kind='solid', thickness=0.5, exterior=False)
    refused(out, {'op': 'delete', 'id': joint},
            'Only a joint between two walls of the same kind can be removed.')
    halves[1]['exterior'] = True
    b2 = run(out, {'op': 'delete', 'id': joint})
    check(len(b2['walls']) == 4 and joint not in jpos(b2), b2['walls'])


def test_household_overshoot_corner_drags():
    """M7: joint-67 is a read overshoot's free end; the drag moves the crossing
    that ends the wall once promotion prunes the short tail."""
    m = household()
    main = next(b for b in m['buildings'] if b['id'] == 'main-house')
    start = next(j['at'] for j in main['joints'] if j['id'] == 'joint-67')
    to = [start[0] + 0.5, start[1]]
    out, words = ops.apply(m, {'op': 'move_joint', 'building': 'main-house',
                               'joint': 'joint-67', 'to': to})
    check(words.startswith('Moved the corner.'), words)
    got = next(b for b in out['buildings'] if b['id'] == 'main-house')
    check(any(near(j['at'], to, 1e-6) for j in got['joints']), 'a corner stands where it was dragged')
    check(not unclosed(got), got['flags'])


def test_drawn_T_inside_a_window_span_stays_derived():
    """R55: a wall drawn to meet another inside a window's span leaves that wall
    whole; the window stays settled on it, and a T outside the span splits."""
    m = box(w=20, openings=[_door('win', 's', 6, width=4, kind='window')])
    b = run(m, {'op': 'add_wall', 'level': 'L1', 'from': [5, 0], 'to': [5, 10], 'kind': 'solid'})
    south = [w for w in b['walls'] if w['id'].split('~')[0] == 's']
    check(len(south) == 1, ('the wall under the window stays whole', south))
    win = opening(b, 'win')
    check(win['wall'] == 's' and close(win['at'], 6) and win.get('state') != 'ghost', win)
    check(not any(f.get('piece') == 'win' for f in b['flags']), b['flags'])
    b = run(m, {'op': 'add_wall', 'level': 'L1', 'from': [12, 0], 'to': [12, 10], 'kind': 'solid'})
    south = [w for w in b['walls'] if w['id'].split('~')[0] == 's']
    check(len(south) == 2, ('a T clear of the window splits', south))
    check(opening(b, 'win').get('state') != 'ghost', opening(b, 'win'))


TESTS = (
    test_delete_joint_between_different_kinds_is_refused,
    test_household_overshoot_corner_drags,
    test_drawn_T_inside_a_window_span_stays_derived,
    test_shared_wall_drag_resizes_both_rooms,
    test_move_joint_moves_every_wall_on_it,
    test_move_wall_carries_its_roof_edge,
    test_move_wall_too_far_past_a_door_is_refused,
    test_a_move_that_crosses_a_wall_is_refused,
    test_a_wall_under_1_ft_is_refused,
    test_add_wall_from_a_wall_splits_it_at_a_T,
    test_add_wall_across_a_wall_splits_both,
    test_move_joint_that_shrinks_a_door_wall_is_refused,
    test_split_wall_keeps_the_door_where_it_was,
    test_wall_drawn_over_an_existing_wall_merges_into_one,
    test_draw_room_beside_a_room_shares_one_wall,
    test_draw_room_partly_against_a_wall_splits_it_not_doubles_it,
    test_split_room_adds_a_separator_and_a_room_named_Room,
    test_move_room_stretches_the_neighbour_not_tears,
    test_delete_wall_merges_two_rooms_keeping_the_larger_name,
    test_delete_wall_keeps_its_door_as_a_flagged_ghost,
    test_ops_mark_touched_walls_person_owned,
    test_household_crossing_rooms_can_move,
    test_household_crossing_wall_moves_without_tearing_a_room,
    test_move_joint_promotes_crossings_only_on_its_incident_walls,
    test_untouched_reader_window_keeps_its_position_ghost_flag_and_owner,
    test_delete_changing_removes_exclusive_edges_and_flags_surface_items,
    test_delete_room_sharing_every_edge_is_refused,
    test_delete_straight_joint_merges_walls_and_keeps_hosts,
    test_delete_corner_and_T_joint_are_refused,
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
