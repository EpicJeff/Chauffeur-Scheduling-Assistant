"""The snap pass and the joint report (plan docs/superpowers/plans/
2026-11-08-house-editor-whole-building-draft.md, Task 4; spec docs/superpowers/
specs/2026-11-08-house-editor-whole-building-draft-design.md, section 6a
"Joints: everything meets"). Written before the code, as its contract.

services.twin_joints:
  - snap(building) mutates one building in place and returns plain sentences,
    one per kind of move with a count ("Joined 3 wall corners."). It never
    moves a piece a person placed (src.person); a weld between a person piece
    and a read piece moves the read end. A second call returns [] and changes
    nothing.
  - report(building) returns plain sentences for what is still open after
    snap (corners that do not meet, roof edges far from any wall, awnings with
    no wall to hang from), and [] when everything meets. Never a raw id.

Tolerances, exactly (Global Constraints): wall ends weld within 1 ft; square
or straight within 3 degrees; coordinates round to the nearest inch; upper
floor walls onto lower wall lines within 1 ft; roof rect edges (the rect, not
rect plus overhang) onto bearing wall lines within 1.5 ft; plates onto wall
tops within 1.5 ft; meeting plates equalised within 0.5 ft. An awning is
given only an EXTERIOR wall whose level spans its eave height (level
elevation <= eave < level elevation + wall height).

The build half runs a stub-reader build through twin_build.start(...,
inline=True) as tests/test_twin_build_repair.py does; the edit half saves a
twin_edit move through twin_edit.save.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_joints.py
"""
import copy
import math
import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_joints_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_plan as tp  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build_repair as repair  # noqa: E402
from test_twin_build import L1 as PAGE_L1  # noqa: E402

try:
    from services import twin_joints  # noqa: E402
except ImportError as exc:  # the module is written after these tests
    twin_joints = None
    _MISSING = exc

INCH = 1 / 12
READ_SRC = {'sheet': 'sheet-a', 'page': 1, 'step': 'walls:L1'}
LEVELS = [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 10},
          {'id': 'L2', 'name': 'Upper floor', 'elevation': 10.9, 'ceiling': 9}]


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def tj():
    if twin_joints is None:
        raise AssertionError(f'services.twin_joints is missing: {_MISSING}')
    return twin_joints


# --- plan builders -----------------------------------------------------------

_ids = {'n': 0}


def _id(kind):
    # Shaped like the build's ids, so a leaked id in a sentence is easy to spot.
    _ids['n'] += 1
    return f"{kind}:{_ids['n']:010x}"


def wall(a, b, level='L1', height=None, exterior=True, person=False, thickness=0.5):
    if height is None:
        height = next(l['ceiling'] for l in LEVELS if l['id'] == level)
    return {'id': _id('wall'), 'level': level, 'from': list(a), 'to': list(b), 'height': height,
            'thickness': thickness, 'exterior': exterior, 'state': 'settled',
            'src': {'person': True} if person else dict(READ_SRC, step=f'walls:{level}')}


def section(rect, plate=10, kind='gable', ridge='x', overhang=1):
    return {'id': _id('roof'), 'kind': kind, 'rect': list(rect), 'ridge': ridge, 'pitch': 6,
            'plate': plate, 'overhang': overhang, 'pitch_source': 'drawn', 'state': 'settled',
            'src': dict(READ_SRC, step='roof')}


def awning(sec, x0, x1, eave=8.6, depth=3, pitch=3):
    return {'kind': 'awning', 'section': sec['id'], 'x0': x0, 'x1': x1, 'depth': depth,
            'pitch': pitch, 'eave': eave, 'brackets': 2}


def rect_walls(x0, y0, x1, y1, **kw):
    """Four outside walls, counter-clockwise from the front (y0) wall."""
    return [wall([x0, y0], [x1, y0], **kw), wall([x1, y0], [x1, y1], **kw),
            wall([x1, y1], [x0, y1], **kw), wall([x0, y1], [x0, y0], **kw)]


def building(walls, sections=(), extensions=(), levels=None):
    """One normalized building, shaped as the build and editor hold it."""
    plan = {'units': 'ft', 'site': {}, 'materials': {},
            'buildings': [{'id': 'house', 'name': 'Main house', 'position': [0, 0], 'rotation': 0,
                           'levels': copy.deepcopy(levels or LEVELS), 'walls': copy.deepcopy(list(walls)),
                           'openings': [], 'rooms': [],
                           'roof': {'sections': copy.deepcopy(list(sections)),
                                    'extensions': copy.deepcopy(list(extensions))}}]}
    normalized, notes = tp.normalize(plan)
    dropped = [n for n in notes if n.startswith('Dropped')]
    check(not dropped, ('the test plan is valid', dropped))
    return normalized['buildings'][0]


def by_id(b, pid):
    return next(p for p in b['walls'] + b['roof']['sections'] if p['id'] == pid)


def same(a, b, tol=1e-9):
    return math.dist(a, b) <= tol


def ids_of(b):
    return [p['id'] for p in b['walls'] + b['roof']['sections'] + b.get('openings', [])]


def no_raw_ids(b, lines):
    leaked = [(pid, line) for line in lines for pid in ids_of(b) if pid in line]
    check(not leaked, ('plain sentences never name a raw id', leaked))


def has(lines, *words):
    return any(all(w.lower() in line.lower() for w in words) for line in lines)


# --- snap: walls -------------------------------------------------------------

def test_weld_close_ends():
    walls = rect_walls(0, 0, 20, 15)
    walls[1]['from'] = [20, 0.8]                    # the right wall stops 0.8 ft short of the corner
    b = building(walls, [section([0, 0, 20, 15])])
    before = copy.deepcopy(b)
    notes = tj().snap(b)
    front, right = by_id(b, walls[0]['id']), by_id(b, walls[1]['id'])
    check(same(front['to'], right['from']), ('ends 0.8 ft apart share one corner', front['to'], right['from']))
    for w in (walls[0], walls[1]):
        for key in ('from', 'to'):
            moved = math.dist(by_id(b, w['id'])[key], by_id(before, w['id'])[key])
            check(moved <= 1 + 1e-9, ('an end moves at most 1 ft', key, moved))
    check(isinstance(notes, list) and all(isinstance(n, str) for n in notes), notes)
    check(has(notes, 'joined', 'corner'), ('one plain note counts the joined corners', notes))
    no_raw_ids(b, notes)
    check(tj().report(b) == [], ('everything meets after the weld', tj().report(b)))


def test_no_weld_beyond_tolerance():
    walls = rect_walls(0, 0, 20, 15)
    walls[1]['from'] = [20, 1.3]                    # 1.3 ft short: past the 1 ft weld
    b = building(walls, [section([0, 0, 20, 15])])
    tj().snap(b)
    front, right = by_id(b, walls[0]['id']), by_id(b, walls[1]['id'])
    gap = math.dist(front['to'], right['from'])
    check(gap > 1.2, ('ends 1.3 ft apart stay apart', front['to'], right['from']))
    lines = tj().report(b)
    check(has(lines, 'corner'), ('the report names the open corner', lines))
    no_raw_ids(b, lines)


def _angle(w):
    return math.degrees(math.atan2(w['to'][1] - w['from'][1], w['to'][0] - w['from'][0]))


def test_square_within_3_degrees():
    t2, t5 = math.tan(math.radians(2)), math.tan(math.radians(5))
    flat2 = wall([0, 0], [20, 20 * t2], exterior=False, thickness=0.33)
    tall2 = wall([40, 0], [40 + 20 * t2, 20], exterior=False, thickness=0.33)
    flat5 = wall([0, 50], [20, 50 + 20 * t5], exterior=False, thickness=0.33)
    b = building([flat2, tall2, flat5])
    tj().snap(b)
    w = by_id(b, flat2['id'])
    check(abs(w['to'][1] - w['from'][1]) <= 1e-9, ('a 2 degree wall is made level', w['from'], w['to']))
    w = by_id(b, tall2['id'])
    check(abs(w['to'][0] - w['from'][0]) <= 1e-9, ('a 2 degree wall is made plumb on the plan', w['from'], w['to']))
    w = by_id(b, flat5['id'])
    check(4 <= abs(_angle(w)) <= 6, ('a 5 degree wall keeps its angle', _angle(w), w['from'], w['to']))


def _on_inch(v):
    return abs(v - round(v * 12) / 12) <= 1e-9


def test_round_to_inch():
    corners = [[0.03, 0.04], [23.37, 0.02], [23.41, 15.13], [0.02, 15.11]]
    walls = [wall(a, b) for a, b in zip(corners, corners[1:] + corners[:1])]
    levels = copy.deepcopy(LEVELS)
    levels[0]['outline'] = copy.deepcopy(corners)
    b = building(walls, [section([0.01, 0.03, 23.38, 15.14])], levels=levels)
    tj().snap(b)
    values = [('wall', w['id'], v) for w in b['walls'] for key in ('from', 'to') for v in w[key]]
    values += [('roof', s['id'], v) for s in b['roof']['sections'] for v in s['rect']]
    values += [('outline', l['id'], v) for l in b['levels'] for p in l.get('outline') or [] for v in p]
    off = [item for item in values if not _on_inch(item[2])]
    check(not off, ('every coordinate is a whole inch', off))


def test_upper_wall_onto_lower_line():
    lower = rect_walls(0, 0, 30, 20)
    near = wall([2, 0.7], [28, 0.7], level='L2')    # 0.7 ft inside the front wall line
    far = wall([28.5, 2], [28.5, 18], level='L2')   # 1.5 ft inside the right wall line
    b = building(lower + [near, far])
    tj().snap(b)
    w = by_id(b, near['id'])
    check(abs(w['from'][1]) <= 1e-9 and abs(w['to'][1]) <= 1e-9,
          ('an upper wall 0.7 ft inside a lower wall line moves onto it', w['from'], w['to']))
    w = by_id(b, far['id'])
    check(abs(w['from'][0] - 28.5) <= 1e-9 and abs(w['to'][0] - 28.5) <= 1e-9,
          ('an upper wall 1.5 ft inside stays where it was read', w['from'], w['to']))
    w = by_id(b, lower[0]['id'])
    check(same(w['from'], [0, 0]) and same(w['to'], [30, 0]), ('the lower wall stays', w))


# --- snap: roof ---------------------------------------------------------------

def test_roof_edge_onto_wall():
    walls = rect_walls(0, 0, 30, 20)
    near = section([0, 0, 31.2, 20])                # the right edge 1.2 ft past the right wall line
    b = building(walls, [near])
    tj().snap(b)
    rect = by_id(b, near['id'])['rect']
    check(abs(rect[2] - 30) <= 1e-9, ('a rect edge 1.2 ft from its wall line moves onto it', rect))
    check(all(abs(v - w) <= 1e-9 for v, w in zip(rect, [0, 0, 30, 20])), ('the other edges stay', rect))
    check(tj().report(b) == [], tj().report(b))

    walls = rect_walls(0, 0, 30, 20)
    far = section([0, 0, 32, 20])                   # 2 ft past: beyond 1.5 ft
    b = building(walls, [far])
    tj().snap(b)
    rect = by_id(b, far['id'])['rect']
    check(abs(rect[2] - 32) <= 1e-9, ('a rect edge 2 ft from any wall stays', rect))
    lines = tj().report(b)
    check(has(lines, 'roof edge'), ('the report names the roof edge', lines))
    no_raw_ids(b, lines)


def test_plate_onto_wall_top():
    near = section([0, 0, 30, 20], plate=10.9)      # L1 walls top out at 0 + 10
    b = building(rect_walls(0, 0, 30, 20), [near])
    tj().snap(b)
    plate = by_id(b, near['id'])['plate']
    check(abs(plate - 10.0) <= 1e-9, ('a plate 0.9 ft over the wall tops comes down onto them', plate))

    far = section([0, 0, 30, 20], plate=12.0)       # 2 ft over: beyond 1.5 ft
    b = building(rect_walls(0, 0, 30, 20), [far])
    tj().snap(b)
    plate = by_id(b, far['id'])['plate']
    check(abs(plate - 12.0) <= 1e-9, ('a plate 2 ft over the wall tops stays', plate))


def test_meeting_plates_equal():
    # Walls 8 ft tall, so neither plate is within 1.5 ft of a wall top.
    left, right = section([0, 0, 15, 20], plate=10.9), section([15, 0, 30, 20], plate=10.6)
    b = building(rect_walls(0, 0, 30, 20, height=8), [left, right])
    tj().snap(b)
    a, c = by_id(b, left['id'])['plate'], by_id(b, right['id'])['plate']
    check(abs(a - c) <= 1e-9, ('two meeting sections 0.3 ft apart share one plate', a, c))
    check(10.6 - 1e-9 <= a <= 10.9 + 1e-9, ('the shared plate is one of theirs or between them', a))


# --- snap: awnings ------------------------------------------------------------

def test_awning_gets_wall():
    walls = rect_walls(0, 0, 30, 20)
    roof = section([0, 0, 30, 20])
    over = awning(roof, 10, 20)                     # over the front (y0) wall
    b = building(walls, [roof], [over])
    tj().snap(b)
    ext = b['roof']['extensions'][0]
    check(ext.get('wall') == walls[0]['id'], ('the awning hangs from the front wall', ext))
    check(tj().report(b) == [], tj().report(b))

    walls = rect_walls(0, 0, 30, 20)
    roof = section([0, 0, 30, 20])
    b = building(walls, [roof], [awning(roof, 100, 110)])   # over nothing
    tj().snap(b)
    ext = b['roof']['extensions'][0]
    check(not ext.get('wall'), ('an awning over nothing gets no wall', ext))
    lines = tj().report(b)
    check(has(lines, 'awning'), ('the report names the awning with no wall', lines))
    no_raw_ids(b, lines)


def test_awning_takes_the_wall_of_its_floor():
    # An L2 wall on the same line as the L1 front wall, listed first. An
    # awning at eave 8.6 hangs on L1 (0 <= 8.6 < 10); one at eave 12 on L2
    # (10.9 <= 12 < 19.9).
    upper = wall([0, 0], [30, 0], level='L2')
    lower = rect_walls(0, 0, 30, 20)
    roof = section([0, 0, 30, 20], plate=19.9)
    low, high = awning(roof, 10, 20, eave=8.6), awning(roof, 10, 20, eave=12)
    b = building([upper] + lower, [roof], [low, high])
    tj().snap(b)
    low_ext, high_ext = b['roof']['extensions']
    check(low_ext.get('wall') == lower[0]['id'],
          ('an awning at eave 8.6 hangs from the L1 wall, not the L2 wall on its line',
           low_ext.get('wall'), upper['id'], lower[0]['id']))
    check(high_ext.get('wall') == upper['id'], ('an awning at eave 12 hangs from the L2 wall', high_ext.get('wall')))


# --- snap: a person's pieces --------------------------------------------------

def test_person_piece_never_moves():
    walls = rect_walls(0, 0, 20, 15)
    walls[1] = wall([20, 0.6], [20, 15], person=True)   # a person moved this end 0.6 ft off the corner
    b = building(walls, [section([0, 0, 20, 15])])
    person_before = copy.deepcopy(by_id(b, walls[1]['id']))
    tj().snap(b)
    person = by_id(b, walls[1]['id'])
    check(person == person_before, ('the person wall is never moved', person_before, person))
    front = by_id(b, walls[0]['id'])
    check(same(front['to'], [20, 0.6]), ('the read end moves to the person end', front['to']))


def test_idempotent():
    walls = rect_walls(0, 0, 30, 20)
    walls[1]['from'] = [30.3, 0.8]
    walls[2]['to'] = [0.04, 20.6]
    skew = wall([10, 2], [10 + 16 * math.tan(math.radians(2)), 18], exterior=False, thickness=0.33)
    roof = section([0.02, 0, 31.2, 20.4], plate=10.9)
    b = building(walls + [skew, wall([2, 0.7], [28, 0.7], level='L2')], [roof], [awning(roof, 10, 20)])
    first = tj().snap(b)
    check(first, ('the first pass moves something', first))
    settled = copy.deepcopy(b)
    second = tj().snap(b)
    check(second == [], ('a second snap reports nothing', second))
    check(b == settled, ('a second snap changes nothing', tp.diff_paths({'b': settled}, {'b': b})))


def _opening_centre(b, opening):
    carrier = by_id(b, opening['wall'])
    length = math.dist(carrier['from'], carrier['to'])
    return [carrier['from'][i] + opening['at'] *
            (carrier['to'][i] - carrier['from'][i]) / length for i in (0, 1)]


def test_weld_preserves_person_and_read_opening_centres():
    walls = rect_walls(0, 0, 20, 15)
    walls[1]['from'] = [20, 0.8]
    b = building(walls)
    b['openings'] = [
        {'id': _id('opening'), 'kind': 'window', 'wall': walls[1]['id'],
         'at': at, 'width': 2, 'sill': 3, 'head': 7,
         'src': {'person': True} if person else dict(READ_SRC)}
        for at, person in ((5, True), (10, False))]
    before = [_opening_centre(b, o) for o in b['openings']]
    notes = tj().snap(b)
    check(has(notes, 'joined', 'corner'), notes)
    for centre, opening in zip(before, b['openings']):
        check(same(centre, _opening_centre(b, opening), 0.01),
              ('welding keeps each opening at its world centre', centre, opening))
    normalized, _ = tp.normalize({'units': 'ft', 'buildings': [b]})
    check(len(normalized['buildings'][0]['openings']) == 2, 'both openings survive publication')
    settled = copy.deepcopy(b)
    check(tj().snap(b) == [] and b == settled, 'opening reprojection is idempotent')


def test_awning_prefers_front_with_rear_wall_first():
    walls = rect_walls(0, 0, 30, 20)
    roof = section([0, 0, 30, 20])
    b = building([walls[2], walls[1], walls[0], walls[3]], [roof], [awning(roof, 10, 20)])
    tj().snap(b)
    check(b['roof']['extensions'][0].get('wall') == walls[0]['id'],
          ('the y0 wall wins a front/rear tie regardless of list order', b['roof']['extensions']))
    b['roof']['extensions'][0]['wall'] = walls[2]['id']
    tj().snap(b)
    check(b['roof']['extensions'][0]['wall'] == walls[2]['id'], 'an explicit valid rear wall is retained')


def test_report_counts_corners_instead_of_wall_ends():
    walls = rect_walls(0, 0, 20, 15)
    walls[1]['from'] = [20, 1.3]
    b = building(walls)
    tj().snap(b)
    check(tj().report(b) == ['1 outside corner on the Main floor does not meet.'], tj().report(b))
    b['walls'][3]['from'] = [0, 13.7]
    check(tj().report(b) == ['2 outside corners on the Main floor do not meet.'], tj().report(b))


def test_report_names_rear_and_formats_feet():
    for distance in (2, 12.5, 100):
        b = building(rect_walls(0, 0, 30, 20), [section([0, 0, 30, 20 + distance])])
        tj().snap(b)
        expected = f'A roof edge over the rear is {distance} ft from any wall.'
        check(tj().report(b) == [expected], (expected, tj().report(b)))
        no_raw_ids(b, tj().report(b))
    b = building(rect_walls(0, 0, 30, 20), [section([0, 0, 30, 20], plate=110)])
    check(has(tj().report(b), 'roof plate', 'front', '100 ft above'), tj().report(b))


def test_report_collapses_identical_roof_lines():
    b = building(rect_walls(0, 0, 30, 20),
                 [section([0, 0, 10, 22]), section([20, 0, 30, 22])])
    lines = tj().report(b)
    rear = [line for line in lines if 'roof edge' in line and 'rear' in line]
    check(rear == ['2 roof edges over the rear are 2 ft from any wall.'], lines)


def test_report_locates_unsupported_awning_and_covered_opening():
    walls = rect_walls(0, 0, 30, 20)
    roof = section([0, 0, 30, 20])
    # Too high for L1: it cannot attach, but the front window still locates it.
    b = building(walls, [roof], [awning(roof, 10, 20, eave=12)])
    b['openings'] = [{'id': _id('opening'), 'kind': 'window', 'wall': walls[0]['id'],
                      'at': 15, 'width': 3, 'sill': 3, 'head': 7, 'src': {'person': True}}]
    before = copy.deepcopy(b)
    expected = 'The awning over the window on the front has no wall to hang from.'
    check(tj().report(b) == [expected], tj().report(b))
    check(b == before, 'report is read-only')
    b['roof']['extensions'].append(copy.deepcopy(b['roof']['extensions'][0]))
    check(tj().report(b) == ['2 awnings over the window on the front have no wall to hang from.'],
          tj().report(b))
    b['openings'].clear()
    lines = tj().report(b)
    check(lines == ['2 awnings on the front have no wall to hang from.'], lines)
    no_raw_ids(b, lines)


# --- the build and the editor run it ------------------------------------------

def test_build_runs_snap():
    _, sheet = repair._place()
    corners = PAGE_L1
    segments = [(a, b, True) for a, b in repair.edges(corners)]
    short = [corners[1][0] - 0.5 * repair.U, corners[1][1]]   # the front wall stops 0.5 ft short
    segments[0] = (corners[0], short, True)
    reader = repair.StepReader({'outline': repair._outline(corners),
                                ('walls', 'L1'): repair.page_walls(segments)})
    b, st = repair._build('house', reader)
    house = repair._building('house')
    l1 = [w for w in house['walls'] if w['level'] == 'L1' and w.get('state') != 'ghost']
    check(len(l1) == 4, ('the four outside walls settle', [(w['from'], w['to'], w.get('state')) for w in l1]))
    for corner in corners:
        at = repair._world(sheet, 1, 'L1', corner)
        ends = [w[k] for w in l1 for k in ('from', 'to') if math.dist(w[k], at) <= 1.5]
        check(len(ends) == 2 and same(ends[0], ends[1], 1e-6),
              ('every corner settles welded, including the one read 0.5 ft open', at, ends))
    logs = [e['text'] for e in st['events'] if e['type'] == 'log']
    check(any('Joined' in text for text in logs), ('the build log says the corner was joined', logs))


def _seed(plan):
    storage.patch_settings({'house_twin': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    ts.push_round(plan, 'build')


def test_edit_runs_snap():
    walls = rect_walls(0, 0, 40, 30)
    plan, _ = tp.normalize({'units': 'ft', 'site': {}, 'materials': {},
                            'buildings': [{'id': 'house', 'name': 'Main house', 'position': [0, 0],
                                           'rotation': 0, 'levels': copy.deepcopy(LEVELS), 'walls': walls,
                                           'openings': [], 'rooms': [],
                                           'roof': {'sections': [], 'extensions': []}}]})
    _seed(plan)
    front, right, rear = (w['id'] for w in walls[:3])
    twin_edit.save({'op': 'move', 'piece': right, 'by': [0.4, 0]}, 'person-1')
    house = ts.current()['buildings'][0]
    moved = next(w for w in house['walls'] if w['id'] == right)
    check(moved.get('src', {}).get('person') is True, moved)
    check(same(moved['from'], [40.4, 0]) and same(moved['to'], [40.4, 30]),
          ('the person-moved wall keeps where the person put it', moved['from'], moved['to']))
    f = next(w for w in house['walls'] if w['id'] == front)
    r = next(w for w in house['walls'] if w['id'] == rear)
    check(same(f['to'], moved['from']), ('the front wall end 0.4 ft away is saved welded', f['to'], moved['from']))
    check(same(r['from'], moved['to']), ('the rear wall end 0.4 ft away is saved welded', r['from'], moved['to']))


SCENARIOS = (
    test_weld_close_ends,
    test_no_weld_beyond_tolerance,
    test_square_within_3_degrees,
    test_round_to_inch,
    test_upper_wall_onto_lower_line,
    test_roof_edge_onto_wall,
    test_plate_onto_wall_top,
    test_meeting_plates_equal,
    test_awning_gets_wall,
    test_awning_takes_the_wall_of_its_floor,
    test_person_piece_never_moves,
    test_idempotent,
    test_weld_preserves_person_and_read_opening_centres,
    test_awning_prefers_front_with_rear_wall_first,
    test_report_counts_corners_instead_of_wall_ends,
    test_report_names_rear_and_formats_feet,
    test_report_collapses_identical_roof_lines,
    test_report_locates_unsupported_awning_and_covered_opening,
    test_build_runs_snap,
    test_edit_runs_snap,
)


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)
