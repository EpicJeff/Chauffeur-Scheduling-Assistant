"""Hosted items follow their surface (brief .superpowers/sdd/2026-11-09-house-
connected-model-pieces-1-2/task-4-brief.md; spec docs/superpowers/specs/
2026-11-09-house-connected-model-design.md section 4.3; plan docs/superpowers/
plans/2026-11-09-house-connected-model-pieces-1-2.md Task 4 and Review Focus 2;
ledger Ruling R3).

Module under test: services/twin_model_hosts.py
- snapshot(building) -> dict, taken before an operation;
- follow(building, before) -> list[str], applies section 4.3 after the
  geometry changed and returns the plain notes;
- rehost(building, piece_id, host) -> None;
- world_point(building, host, offset=0) -> [x, y, z] in building-local feet;
- MIN_CLEAR = 0.5.

Rules pinned here:
- A wall item keeps its distance from the end that did not move; both ends
  moved by the same vector keeps `at`; both moved differently keeps the
  fraction along the wall.
- Then it is clamped so that at +/- width/2 lies in [MIN_CLEAR, length -
  MIN_CLEAR].
- Floor and ceiling items keep u, v as fractions of the room's bounding box.
- An item whose host is gone becomes state 'ghost' and is flagged
  `This {kind} lost its wall; place it again.` (`lost its surface` for a
  floor, ceiling or roof host). It is never deleted.

Fixtures are schema 3 buildings (task-2-brief.md): joints [{id, level, at}],
walls with joints [a, b], rooms with a polygon cache, openings {wall, at,
width, ...} where `at` is the centre's distance from the wall's first joint,
anchors/items with a host. Each test changes the geometry the way an
operation and twin_model.derive would (joints moved in place, room polygon
caches rewritten) and then calls follow.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_hosts.py
"""
import copy
import math
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_hosts_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_model_hosts as hosts  # noqa: E402

TOL = 1e-6
THICK = 0.5


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def close_pt(a, b, tol=TOL):
    return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))


def _box():
    """A 10 x 10 ft room r1 on L1 (elevation 0, ceiling 9).

    j4 (0,10) --n-- j3 (10,10)
     |                  |
     w                  e
     |                  |
    j1 (0,0)  --s-- j2 (10,0)

    Walls run s: j1->j2, e: j2->j3, n: j3->j4, w: j4->j1.
    """
    return {
        'id': 'B1', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
        'materials': {},
        'levels': [{'id': 'L1', 'name': 'main floor', 'elevation': 0, 'ceiling': 9}],
        'joints': [
            {'id': 'j1', 'level': 'L1', 'at': [0, 0]},
            {'id': 'j2', 'level': 'L1', 'at': [10, 0]},
            {'id': 'j3', 'level': 'L1', 'at': [10, 10]},
            {'id': 'j4', 'level': 'L1', 'at': [0, 10]},
        ],
        'walls': [
            {'id': 's', 'level': 'L1', 'joints': ['j1', 'j2'], 'kind': 'solid',
             'thickness': THICK, 'exterior': True, 'height': 9},
            {'id': 'e', 'level': 'L1', 'joints': ['j2', 'j3'], 'kind': 'solid',
             'thickness': THICK, 'exterior': True, 'height': 9},
            {'id': 'n', 'level': 'L1', 'joints': ['j3', 'j4'], 'kind': 'solid',
             'thickness': THICK, 'exterior': True, 'height': 9},
            {'id': 'w', 'level': 'L1', 'joints': ['j4', 'j1'], 'kind': 'solid',
             'thickness': THICK, 'exterior': True, 'height': 9},
        ],
        'rooms': [
            {'id': 'r1', 'level': 'L1', 'name': 'Kitchen', 'kind': 'room',
             'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]],
             'joints': ['j1', 'j2', 'j3', 'j4']},
        ],
        'openings': [], 'anchors': [], 'items': [],
        'roofs': [], 'dormers': [], 'extensions': [], 'stairs': [],
        'proposals': [], 'flags': [],
    }


def _door(id_, wall, at, width=3.0, kind='door'):
    sill, head = (0, 7) if kind == 'door' else (3, 7)
    return {'id': id_, 'wall': wall, 'at': at, 'width': width,
            'sill': sill, 'head': head, 'kind': kind}


def _joint(b, jid):
    return next(j for j in b['joints'] if j['id'] == jid)


def _move_joints(b, moves):
    # In place, as an operation would: the snapshot must have copied the old ends.
    for jid, to in moves.items():
        _joint(b, jid)['at'][:] = list(to)


def _set_room(b, rid, polygon):
    # What twin_model.derive would leave in the room's polygon cache.
    next(r for r in b['rooms'] if r['id'] == rid)['polygon'] = [list(p) for p in polygon]


def _opening(b, oid):
    return next(o for o in b['openings'] if o['id'] == oid)


def _anchor(b, aid):
    return next(a for a in b['anchors'] if a['id'] == aid)


def _centre_xy(b, wall_id, at):
    """The centreline point `at` feet from the wall's first joint, from the fixture."""
    wall = next(w for w in b['walls'] if w['id'] == wall_id)
    a, c = _joint(b, wall['joints'][0])['at'], _joint(b, wall['joints'][1])['at']
    length = math.hypot(c[0] - a[0], c[1] - a[1])
    return [a[0] + (c[0] - a[0]) * at / length, a[1] + (c[1] - a[1]) * at / length]


def test_min_clear_is_half_a_foot():
    check(hosts.MIN_CLEAR == 0.5, hosts.MIN_CLEAR)


def test_door_keeps_distance_from_the_fixed_end():
    # The east wall moves out 4 ft: s grows at its second joint, j1 stays.
    b = _box()
    b['openings'].append(_door('d1', 's', 3.0))
    before = hosts.snapshot(b)
    _move_joints(b, {'j2': [14, 0], 'j3': [14, 10]})
    _set_room(b, 'r1', [[0, 0], [14, 0], [14, 10], [0, 10]])
    notes = hosts.follow(b, before)
    check(isinstance(notes, list) and all(isinstance(n, str) for n in notes), notes)
    check(close(_opening(b, 'd1')['at'], 3.0), _opening(b, 'd1'))
    check(close_pt(_centre_xy(b, 's', _opening(b, 'd1')['at']), [3, 0]), _opening(b, 'd1'))

    # The west wall moves out 4 ft: s grows at its first joint, j2 stays.
    # The door was 7 ft from j2 and stays 7 ft from it: at = 14 - 7 = 7.
    b = _box()
    b['openings'].append(_door('d1', 's', 3.0))
    before = hosts.snapshot(b)
    _move_joints(b, {'j1': [-4, 0], 'j4': [-4, 10]})
    _set_room(b, 'r1', [[-4, 0], [10, 0], [10, 10], [-4, 10]])
    hosts.follow(b, before)
    check(close(_opening(b, 'd1')['at'], 7.0), _opening(b, 'd1'))
    check(close_pt(_centre_xy(b, 's', _opening(b, 'd1')['at']), [3, 0]), _opening(b, 'd1'))
    check(_opening(b, 'd1').get('state') != 'ghost', _opening(b, 'd1'))


def test_wall_moved_sideways_carries_its_window():
    # The east wall moves +4 ft in x: both its joints by the same vector.
    b = _box()
    b['openings'].append(_door('w1', 'e', 5.0, width=3.0, kind='window'))
    before = hosts.snapshot(b)
    _move_joints(b, {'j2': [14, 0], 'j3': [14, 10]})
    _set_room(b, 'r1', [[0, 0], [14, 0], [14, 10], [0, 10]])
    hosts.follow(b, before)
    check(close(_opening(b, 'w1')['at'], 5.0), _opening(b, 'w1'))
    check(_opening(b, 'w1')['wall'] == 'e', _opening(b, 'w1'))
    check(close_pt(_centre_xy(b, 'e', _opening(b, 'w1')['at']), [14, 5]), _opening(b, 'w1'))


def test_both_ends_moved_differently_keeps_the_fraction():
    # s stretches both ways: j1 to (-2,0), j2 to (16,0); length 10 -> 18.
    # The window sat at 4 of 10 (0.4), so it lands at 0.4 x 18 = 7.2.
    b = _box()
    b['openings'].append(_door('w1', 's', 4.0, width=2.0, kind='window'))
    before = hosts.snapshot(b)
    _move_joints(b, {'j1': [-2, 0], 'j2': [16, 0]})
    hosts.follow(b, before)
    check(close(_opening(b, 'w1')['at'], 7.2), _opening(b, 'w1'))


def test_light_centred_in_a_room_stays_centred_when_the_room_grows():
    # A ceiling light at the centre and a floor item a quarter across; the
    # east wall moves out 4 ft, so the room is 14 x 10.
    b = _box()
    b['anchors'].append({'id': 'l1', 'kind': 'light', 'offset': 0, 'device': None,
                         'host': {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}})
    b['items'].append({'id': 'i1', 'asset': 'table', 'rotation': 0, 'scale': 1,
                       'host': {'floor': 'r1', 'u': 0.25, 'v': 0.5}})
    check(close_pt(hosts.world_point(b, _anchor(b, 'l1')['host']), [5, 5, 9]),
          hosts.world_point(b, _anchor(b, 'l1')['host']))
    check(close_pt(hosts.world_point(b, b['items'][0]['host']), [2.5, 5, 0]),
          hosts.world_point(b, b['items'][0]['host']))
    before = hosts.snapshot(b)
    _move_joints(b, {'j2': [14, 0], 'j3': [14, 10]})
    _set_room(b, 'r1', [[0, 0], [14, 0], [14, 10], [0, 10]])
    hosts.follow(b, before)
    light = _anchor(b, 'l1')
    check(light['host'].get('ceiling') == 'r1' and close(light['host']['u'], 0.5)
          and close(light['host']['v'], 0.5), light)
    check(close_pt(hosts.world_point(b, light['host']), [7, 5, 9]),
          hosts.world_point(b, light['host']))
    item = b['items'][0]
    check(item['host'].get('floor') == 'r1' and close(item['host']['u'], 0.25), item)
    check(close_pt(hosts.world_point(b, item['host']), [3.5, 5, 0]),
          hosts.world_point(b, item['host']))


def test_shrinking_wall_clamps_the_door_onto_it():
    # Review Focus 2: a room-resizing drag pushes the east wall in from x=10
    # to x=7, past a 3 ft door at 8 on the perpendicular south wall. The door
    # keeps its 8 ft from j1, then clamps: 8 + 1.5 > 7 - 0.5, so at = 5.
    b = _box()
    b['openings'].append(_door('d1', 's', 8.0, width=3.0))
    before = hosts.snapshot(b)
    _move_joints(b, {'j2': [7, 0], 'j3': [7, 10]})
    _set_room(b, 'r1', [[0, 0], [7, 0], [7, 10], [0, 10]])
    notes = hosts.follow(b, before)
    door = _opening(b, 'd1')
    check(isinstance(notes, list), notes)
    check(door['wall'] == 's' and door.get('state') != 'ghost', door)
    check(close(door['at'], 7 - hosts.MIN_CLEAR - 1.5), door)
    check(door['at'] - door['width'] / 2 >= hosts.MIN_CLEAR - TOL, door)

    # The other end: the west wall pushed in from x=0 to x=3 (j2 fixed). A
    # door at 2 was 8 ft from j2; 7 - 8 = -1 clamps up to 0.5 + 1.5 = 2.
    b = _box()
    b['openings'].append(_door('d1', 's', 2.0, width=3.0))
    before = hosts.snapshot(b)
    _move_joints(b, {'j1': [3, 0], 'j4': [3, 10]})
    _set_room(b, 'r1', [[3, 0], [10, 0], [10, 10], [3, 10]])
    hosts.follow(b, before)
    door = _opening(b, 'd1')
    check(close(door['at'], hosts.MIN_CLEAR + 1.5), door)
    check(close_pt(_centre_xy(b, 's', door['at']), [5, 0]), door)


def test_rehost_moves_a_switch_to_the_other_wall():
    # A switch on the south wall is dragged round the corner onto the east wall.
    b = _box()
    b['anchors'].append({'id': 'sw1', 'kind': 'switch', 'offset': 0, 'device': None,
                         'host': {'wall': 's', 'side': 'left', 'at': 2.0, 'z': 4.0}})
    hosts.rehost(b, 'sw1', {'wall': 'e', 'side': 'left', 'at': 3.0, 'z': 4.0})
    sw = _anchor(b, 'sw1')
    check(sw['host']['wall'] == 'e' and close(sw['host']['at'], 3.0)
          and close(sw['host']['z'], 4.0) and sw['host']['side'] == 'left', sw)
    check(len(b['anchors']) == 1, b['anchors'])
    p = hosts.world_point(b, sw['host'])
    check(close(p[1], 3.0) and close(p[2], 4.0) and abs(p[0] - 10) <= THICK / 2 + TOL, p)

    # Now hosted by e, it rides e when e moves +2 ft in x.
    before = hosts.snapshot(b)
    _move_joints(b, {'j2': [12, 0], 'j3': [12, 10]})
    _set_room(b, 'r1', [[0, 0], [12, 0], [12, 10], [0, 10]])
    hosts.follow(b, before)
    q = hosts.world_point(b, _anchor(b, 'sw1')['host'])
    check(close_pt(q, [p[0] + 2, p[1], p[2]]), (p, q))


def test_world_point_on_a_wall_side_sits_on_its_face():
    # Wall s runs along y=0 with thickness 0.5: a point on either side is
    # thickness/2 + offset off the centreline, the two sides opposite.
    b = _box()
    left = hosts.world_point(b, {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0})
    right = hosts.world_point(b, {'wall': 's', 'side': 'right', 'at': 4.0, 'z': 4.0})
    check(close(left[0], 4) and close(right[0], 4) and close(left[2], 4) and close(right[2], 4),
          (left, right))
    check(close(abs(left[1]), THICK / 2) and close(left[1], -right[1]), (left, right))
    off = hosts.world_point(b, {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0}, 0.25)
    check(close(abs(off[1]), THICK / 2 + 0.25) and off[1] * left[1] > 0, (left, off))


def test_deleted_wall_leaves_a_flagged_ghost_not_a_deletion():
    # The north wall (j3 (10,10) -> j4 (0,10)) is deleted under a window at
    # 3 ft from j3, i.e. at (7, 10), and a switch.
    b = _box()
    b['openings'].append(_door('w1', 'n', 3.0, width=3.0, kind='window'))
    b['anchors'].append({'id': 'sw1', 'kind': 'switch', 'offset': 0, 'device': None,
                         'host': {'wall': 'n', 'side': 'left', 'at': 5.0, 'z': 4.0}})
    before = hosts.snapshot(b)
    b['walls'] = [w for w in b['walls'] if w['id'] != 'n']
    notes = hosts.follow(b, before)
    check([o['id'] for o in b['openings']] == ['w1'], b['openings'])
    window = _opening(b, 'w1')
    check(window.get('state') == 'ghost', window)
    check(window['width'] == 3.0 and window['kind'] == 'window', window)
    text = 'This window lost its wall; place it again.'
    flags = [f for f in b['flags'] if f.get('text') == text]
    check(len(flags) == 1, b['flags'])
    check(flags[0].get('piece') == 'w1' and flags[0].get('level') == 'L1', flags[0])
    check(close_pt(flags[0]['at'], [7, 10], 0.01), flags[0])
    check(text in notes, notes)

    # Following again (the next operation) keeps one flag, not two.
    hosts.follow(b, hosts.snapshot(b))
    check(len([f for f in b['flags'] if f.get('text') == text]) == 1, b['flags'])
    check(_opening(b, 'w1').get('state') == 'ghost', _opening(b, 'w1'))

    sw = _anchor(b, 'sw1')
    check(sw.get('state') == 'ghost', sw)
    sw_text = 'This switch lost its wall; place it again.'
    check(len([f for f in b['flags'] if f.get('text') == sw_text and f.get('piece') == 'sw1']) == 1,
          b['flags'])


def test_light_whose_room_is_gone_lost_its_surface():
    # The room record r1 is gone (as derive leaves it when the region closes up
    # into another); its ceiling light is kept as a flagged ghost.
    b = _box()
    b['anchors'].append({'id': 'l1', 'kind': 'light', 'offset': 0, 'device': None,
                         'host': {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}})
    before = hosts.snapshot(b)
    b['rooms'] = []
    notes = hosts.follow(b, before)
    check(len(b['anchors']) == 1 and _anchor(b, 'l1').get('state') == 'ghost', b['anchors'])
    text = 'This light lost its surface; place it again.'
    check(len([f for f in b['flags'] if f.get('text') == text and f.get('piece') == 'l1']) == 1,
          b['flags'])
    check(text in notes, notes)


def test_nothing_moved_changes_nothing():
    # follow with no geometry change leaves every hosted piece as it was.
    b = _box()
    b['openings'].append(_door('d1', 's', 3.0))
    b['anchors'].append({'id': 'l1', 'kind': 'light', 'offset': 0, 'device': None,
                         'host': {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}})
    want = copy.deepcopy(b)
    notes = hosts.follow(b, hosts.snapshot(b))
    check(b == want, b)
    check(notes == [], notes)


TESTS = (
    test_min_clear_is_half_a_foot,
    test_door_keeps_distance_from_the_fixed_end,
    test_wall_moved_sideways_carries_its_window,
    test_both_ends_moved_differently_keeps_the_fraction,
    test_light_centred_in_a_room_stays_centred_when_the_room_grows,
    test_shrinking_wall_clamps_the_door_onto_it,
    test_rehost_moves_a_switch_to_the_other_wall,
    test_world_point_on_a_wall_side_sits_on_its_face,
    test_deleted_wall_leaves_a_flagged_ghost_not_a_deletion,
    test_light_whose_room_is_gone_lost_its_surface,
    test_nothing_moved_changes_nothing,
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
