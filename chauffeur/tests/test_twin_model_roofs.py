"""Roofs are areas with an edge setting per edge (spec docs/superpowers/specs/
2026-11-09-house-connected-model-design.md section 4.4; plan docs/superpowers/
plans/2026-11-09-house-connected-model-pieces-1-2.md Task 3; brief
.superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-3-brief.md).

Module under test: services/twin_model_roofs.py
- from_section(section) -> roof {id, area, edges[{setting, pitch?, clip?, wall?}],
  plate, overhang}. A rect [x0,y0,x1,y1] gives the area
  [[x0,y0],[x1,y0],[x1,y1],[x0,y1]], so the edges are y0, x1, y1, x0.
- to_sections(roof) -> schema-2 sections (maximal rectangles of a rectilinear
  area, each carrying roof: <roof id>); to_sections(from_section(s)) equals s
  on every form field. An angled area is refused with
  'Roof areas must have square corners.'
- attach_edges(roof, walls, joints) / follow_walls(roof, walls, joints): an
  edge within overhang + 0.5 ft of a parallel exterior wall line on the
  roof's bearing storey records wall: <id> and follows that wall.
- dormer_from_section(section, parent_roof) / dormer_sections(dormer, roof):
  a dormer_of section becomes a hosted dormer and comes back as the same
  cross-gable section.

Form fields are compared as the generator draws them: an end missing from
`ends` is the section's kind (twin_roof_issues._end_kind), and a side's pitch
is pitches[side] or pitch. The drawn planes (twin_roof_issues._planes, which
matches twin_roof.js) are compared as well.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_roofs.py
"""
import copy
import json
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_roofs_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_roof_issues  # noqa: E402

try:
    from services import twin_model_roofs as _roofs_module  # noqa: E402
    _IMPORT_ERROR = None
except ImportError as exc:  # the module does not exist until Task 3 lands
    _roofs_module, _IMPORT_ERROR = None, exc

HOUSEHOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'fixtures', 'twin_model', 'household-2026-11-09.json')
SIDES = ('x0', 'x1', 'y0', 'y1')
EPS = 1e-6


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def roofs():
    if _roofs_module is None:
        raise _IMPORT_ERROR
    return _roofs_module


def close(a, b, tol=EPS):
    return abs(a - b) <= tol


def same_points(a, b):
    return len(a) == len(b) and all(close(p[0], q[0]) and close(p[1], q[1]) for p, q in zip(a, b))


def same_rect(a, b):
    return len(a) == 4 and all(close(p, q) for p, q in zip(a, b))


def _sloped_sides(s):
    """The sides the generator draws a plane on (twin_roof_issues._planes)."""
    if s['kind'] == 'flat':
        return []
    if s['kind'] == 'shed':
        return [s['low_side']]
    ridge = s['ridge']
    across = ('x0', 'x1') if ridge == 'y' else ('y0', 'y1')
    ends = (ridge + '0', ridge + '1')
    end_kind = {e: twin_roof_issues._end_kind(s, e) for e in ends}
    sides = list(across) if s['kind'] == 'gable' else list(SIDES)
    sides = [side for side in sides if side not in ends or end_kind[side] != 'gable']
    sides += [e for e in ends if end_kind[e] != 'gable' and e not in sides]
    return sorted(sides)


def form(s):
    """A section's form as the generator reads it."""
    out = {'kind': s['kind'], 'plate': s['plate'], 'overhang': s['overhang']}
    if s['kind'] in ('gable', 'hip'):
        out['ridge'] = s['ridge']
        out['ends'] = {e: twin_roof_issues._end_kind(s, e) for e in (s['ridge'] + '0', s['ridge'] + '1')}
    if s['kind'] == 'shed':
        out['low_side'] = s['low_side']
    pitches = s.get('pitches') or {}
    out['pitch_by_side'] = {side: (0 if s['kind'] == 'flat' else pitches.get(side, s['pitch']))
                            for side in _sloped_sides(s)}
    return out


def same_form(got, want):
    """Compare two sections on every form field; return the first mismatch or None."""
    if not same_rect(got.get('rect', []), want['rect']):
        return f"rect {got.get('rect')} != {want['rect']}"
    a, b = form(got), form(want)
    for key in ('kind', 'plate', 'overhang', 'ridge', 'ends', 'low_side'):
        if a.get(key) != b.get(key):
            return f'{key} {a.get(key)!r} != {b.get(key)!r}'
    if sorted(a['pitch_by_side']) != sorted(b['pitch_by_side']) or not all(
            close(a['pitch_by_side'][k], b['pitch_by_side'][k]) for k in b['pitch_by_side']):
        return f"pitches by side {a['pitch_by_side']} != {b['pitch_by_side']}"
    if not want.get('pitches') and not close(got.get('pitch', -1), 0 if want['kind'] == 'flat' else want['pitch']):
        return f"pitch {got.get('pitch')} != {want['pitch']}"
    planes_a = sorted(tuple(round(v, 6) for v in p) for p in twin_roof_issues._planes(got))
    planes_b = sorted(tuple(round(v, 6) for v in p) for p in twin_roof_issues._planes(want))
    if planes_a != planes_b:
        return f'drawn planes {planes_a} != {planes_b}'
    return None


def household_sections():
    with open(HOUSEHOLD, encoding='utf-8') as handle:
        plan = json.load(handle)
    return [(b['id'], s) for b in plan['buildings'] for s in b['roof']['sections']]


# ---------------------------------------------------------------- from_section

def test_from_section_sets_each_edge_by_kind():
    """Edge order y0, x1, y1, x0; hip all sloped; gable ends gable or clip;
    shed only its low side; flat all sloped at pitch 0; side pitches apply."""
    m = roofs()
    rect = [0, 0, 40, 20]
    area = [[0, 0], [40, 0], [40, 20], [0, 20]]

    hip = m.from_section({'id': 'r-hip', 'kind': 'hip', 'ridge': 'x', 'rect': list(rect),
                          'pitch': 8, 'plate': 10, 'overhang': 1})
    check(same_points(hip['area'], area), hip['area'])
    check([e['setting'] for e in hip['edges']] == ['sloped'] * 4, hip['edges'])
    check([e['pitch'] for e in hip['edges']] == [8] * 4, hip['edges'])
    check(hip['plate'] == 10 and hip['overhang'] == 1, hip)

    # A ridge along x: the x0 and x1 edges cross the ridge; x1 is clipped.
    gable = m.from_section({'id': 'r-gable', 'kind': 'gable', 'ridge': 'x', 'rect': list(rect),
                            'pitch': 8, 'pitches': {'y0': 6}, 'plate': 10, 'overhang': 1.5,
                            'ends': {'x1': 'clip'}})
    check([e['setting'] for e in gable['edges']] == ['sloped', 'clip', 'sloped', 'gable'], gable['edges'])
    check(gable['edges'][0]['pitch'] == 6 and gable['edges'][2]['pitch'] == 8, gable['edges'])
    check(gable['overhang'] == 1.5, gable)

    # A ridge along y with no ends given: both y edges are gable.
    gable_y = m.from_section({'id': 'r-gy', 'kind': 'gable', 'ridge': 'y', 'rect': list(rect),
                              'pitch': 8, 'plate': 10, 'overhang': 1})
    check([e['setting'] for e in gable_y['edges']] == ['gable', 'sloped', 'gable', 'sloped'], gable_y['edges'])

    shed = m.from_section({'id': 'r-shed', 'kind': 'shed', 'low_side': 'x1', 'rect': list(rect),
                           'pitch': 3, 'plate': 9.35, 'overhang': 1})
    check([e['setting'] for e in shed['edges']] == ['gable', 'sloped', 'gable', 'gable'], shed['edges'])
    check(shed['edges'][1]['pitch'] == 3 and shed['plate'] == 9.35, shed)

    flat = m.from_section({'id': 'r-flat', 'kind': 'flat', 'rect': list(rect),
                           'pitch': 0, 'plate': 10, 'overhang': 0.5})
    check([e['setting'] for e in flat['edges']] == ['sloped'] * 4, flat['edges'])
    check([e['pitch'] for e in flat['edges']] == [0] * 4, flat['edges'])


# ---------------------------------------------------------------- round trip

def test_round_trip_is_identity_for_every_household_section():
    """Every household section (both buildings, including the shed sections,
    the side-pitched gables, the gable+hip-ended porch and the dormer_of
    cross gable) comes back as itself on kind, rect, ridge, pitch(es), ends,
    plate, overhang and low_side."""
    m = roofs()
    sections = household_sections()
    check(len(sections) == 16, f'fixture has {len(sections)} sections')
    failures = []
    for building, section in sections:
        roof = m.from_section(copy.deepcopy(section))
        check(len(roof['edges']) == 4, (section['id'], roof['edges']))
        back = m.to_sections(copy.deepcopy(roof))
        if len(back) != 1:
            failures.append(f"{building} {section['id']}: {len(back)} sections back")
            continue
        if back[0].get('roof') != roof.get('id') or not roof.get('id'):
            failures.append(f"{building} {section['id']}: roof link {back[0].get('roof')!r} vs {roof.get('id')!r}")
        problem = same_form(back[0], section)
        if problem:
            failures.append(f"{building} {section['id']}: {problem}")
    check(not failures, failures)


def test_round_trip_keeps_hip_clip_and_flat_forms():
    """The forms the household lacks: a hip, a clipped gable end and a flat."""
    m = roofs()
    forms = [
        {'id': 'r-hip', 'kind': 'hip', 'ridge': 'x', 'rect': [0, 0, 40, 20],
         'pitch': 8, 'plate': 10, 'overhang': 1},
        {'id': 'r-clip', 'kind': 'gable', 'ridge': 'x', 'rect': [0, 0, 40, 20], 'pitch': 8,
         'pitches': {'y1': 12}, 'plate': 10, 'overhang': 1, 'ends': {'x0': 'gable', 'x1': 'clip'}},
        {'id': 'r-flat', 'kind': 'flat', 'rect': [5, 5, 15, 12], 'pitch': 0, 'plate': 9, 'overhang': 0.5},
    ]
    for section in forms:
        back = m.to_sections(m.from_section(copy.deepcopy(section)))
        check(len(back) == 1, (section['id'], back))
        problem = same_form(back[0], section)
        check(problem is None, (section['id'], problem, back[0]))


def test_per_edge_pitch_survives():
    """An edge pitch of 6 on y0 and 10 on y1 comes back as exactly those pitches."""
    m = roofs()
    # A 30 x 20 side gable: gable ends on x1 and x0, sloped front (y0) and back (y1).
    roof = {'id': 'roof-a', 'area': [[0, 0], [30, 0], [30, 20], [0, 20]],
            'edges': [{'setting': 'sloped', 'pitch': 6}, {'setting': 'gable'},
                      {'setting': 'sloped', 'pitch': 10}, {'setting': 'gable'}],
            'plate': 10, 'overhang': 1}
    back = m.to_sections(copy.deepcopy(roof))
    check(len(back) == 1, back)
    section = back[0]
    check(same_rect(section['rect'], [0, 0, 30, 20]), section)
    check(section['kind'] == 'gable' and section['ridge'] == 'x', section)
    check(section.get('pitches') == {'y0': 6, 'y1': 10}, section.get('pitches'))
    check(section['roof'] == 'roof-a' and section['plate'] == 10 and section['overhang'] == 1, section)

    # The same through a schema-2 section: the card's side pitches survive.
    source = {'id': 'roof-b', 'kind': 'gable', 'ridge': 'x', 'rect': [0, 0, 30, 20], 'pitch': 8,
              'pitches': {'y0': 6, 'y1': 10}, 'plate': 10, 'overhang': 1, 'ends': {'x0': 'gable', 'x1': 'gable'}}
    made = m.from_section(copy.deepcopy(source))
    check(made['edges'][0]['pitch'] == 6 and made['edges'][2]['pitch'] == 10, made['edges'])
    again = m.to_sections(made)
    check(len(again) == 1 and again[0].get('pitches') == {'y0': 6, 'y1': 10}, again)


# ---------------------------------------------------------------- rectilinear areas

def test_l_shaped_area_gives_two_overlapping_rects_with_inherited_edges():
    """An L is solved as its two maximal rectangles, each overlapping the other
    in the corner square, each side taking the setting of the area edge it lies on."""
    m = roofs()
    # L: a 30 x 10 front wing along x and a 10 x 25 side wing along y, sharing [0,0,10,10].
    #   e0 y=0  0..30   sloped 6
    #   e1 x=30 0..10   gable          (front wing's end)
    #   e2 y=10 30..10  sloped 8       (inside of the L)
    #   e3 x=10 10..25  sloped 9       (inside of the L)
    #   e4 y=25 10..0   gable          (side wing's end)
    #   e5 x=0  25..0   sloped 7
    roof = {'id': 'roof-l',
            'area': [[0, 0], [30, 0], [30, 10], [10, 10], [10, 25], [0, 25]],
            'edges': [{'setting': 'sloped', 'pitch': 6}, {'setting': 'gable'},
                      {'setting': 'sloped', 'pitch': 8}, {'setting': 'sloped', 'pitch': 9},
                      {'setting': 'gable'}, {'setting': 'sloped', 'pitch': 7}],
            'plate': 10, 'overhang': 1}
    back = m.to_sections(copy.deepcopy(roof))
    check(len(back) == 2, back)
    front = next((s for s in back if same_rect(s['rect'], [0, 0, 30, 10])), None)
    side = next((s for s in back if same_rect(s['rect'], [0, 0, 10, 25])), None)
    check(front is not None and side is not None, [s['rect'] for s in back])
    for section in back:
        check(section['roof'] == 'roof-l' and section['plate'] == 10 and section['overhang'] == 1, section)

    # Front wing: ridge along x, gable at x1, the x0 end (open side, e5) slopes at 7;
    # its back side (y1) inherits the inside edge e2.
    want_front = {'kind': 'gable', 'ridge': 'x', 'rect': [0, 0, 30, 10], 'plate': 10, 'overhang': 1,
                  'pitch': 6, 'pitches': {'y0': 6, 'y1': 8, 'x0': 7}, 'ends': {'x0': 'hip', 'x1': 'gable'}}
    # Side wing: ridge along y, gable at y1, the y0 end (e0) slopes at 6;
    # its x1 side inherits the inside edge e3.
    want_side = {'kind': 'gable', 'ridge': 'y', 'rect': [0, 0, 10, 25], 'plate': 10, 'overhang': 1,
                 'pitch': 7, 'pitches': {'x0': 7, 'x1': 9, 'y0': 6}, 'ends': {'y0': 'hip', 'y1': 'gable'}}
    for got, want in ((front, want_front), (side, want_side)):
        check(got['ridge'] == want['ridge'], (got, want))
        check({e: twin_roof_issues._end_kind(got, e) for e in want['ends']} == want['ends'], got)
        pitches = got.get('pitches') or {}
        check({k: pitches.get(k, got['pitch']) for k in want['pitches']} == want['pitches'], got)
        planes = sorted(tuple(round(v, 6) for v in p) for p in twin_roof_issues._planes(got))
        expect = sorted(tuple(round(v, 6) for v in p) for p in twin_roof_issues._planes(want))
        check(planes == expect, (got, planes, expect))


def test_rect_area_with_angled_edge_is_refused():
    m = roofs()
    # A trapezoid: the x0 edge runs from (0,0) up to (5,20).
    roof = {'id': 'roof-bad', 'area': [[0, 0], [30, 0], [30, 20], [5, 20]],
            'edges': [{'setting': 'sloped', 'pitch': 6}] * 4, 'plate': 10, 'overhang': 1}
    try:
        result = m.to_sections(copy.deepcopy(roof))
    except Exception as exc:  # noqa: BLE001 - the words are the contract
        check(str(exc) == 'Roof areas must have square corners.', repr(exc))
    else:
        raise AssertionError(f'angled area was accepted: {result}')


# ---------------------------------------------------------------- walls carry edges

def _box(level='L1', prefix='', ids=('s', 'e', 'n', 'w'), height=10):
    """A 30 x 20 box of 0.5 ft exterior walls with joints at its corners."""
    corners = [[0, 0], [30, 0], [30, 20], [0, 20]]
    joints = [{'id': f'{prefix}j{i + 1}', 'level': level, 'at': list(p)} for i, p in enumerate(corners)]
    walls = [{'id': f'{prefix}w-{name}', 'level': level,
              'joints': [f'{prefix}j{i + 1}', f'{prefix}j{(i + 1) % 4 + 1}'],
              'kind': 'solid', 'thickness': 0.5, 'exterior': True, 'height': height}
             for i, name in enumerate(ids)]
    return walls, joints


def _edge_walls(roof):
    return [e.get('wall') for e in roof['edges']]


def test_attached_edge_follows_its_wall():
    """The south wall moves +2 ft in y: the main roof's south edge moves +2 ft
    with it, and the awning's edge on that wall moves too, while the awning's
    free (unattached) edge stays where it was drawn."""
    m = roofs()
    walls, joints = _box()
    # Main roof on the wall lines, as from_section gives it (overhang drawn by the generator).
    main = {'id': 'roof-main', 'area': [[0, 0], [30, 0], [30, 20], [0, 20]],
            'edges': [{'setting': 'sloped', 'pitch': 8}, {'setting': 'gable'},
                      {'setting': 'sloped', 'pitch': 8}, {'setting': 'gable'}],
            'plate': 10, 'overhang': 1}
    # An awning hung off the south wall: 12 ft wide, 6 ft deep, its back edge on the wall.
    awning = {'id': 'roof-awning', 'area': [[8, -6], [20, -6], [20, 0], [8, 0]],
              'edges': [{'setting': 'sloped', 'pitch': 3}, {'setting': 'gable'},
                        {'setting': 'gable'}, {'setting': 'gable'}],
              'plate': 8, 'overhang': 0.5}

    main = m.attach_edges(copy.deepcopy(main), walls, joints)
    awning = m.attach_edges(copy.deepcopy(awning), walls, joints)
    check(_edge_walls(main) == ['w-s', 'w-e', 'w-n', 'w-w'], _edge_walls(main))
    check(_edge_walls(awning) == [None, None, 'w-s', None], _edge_walls(awning))

    # Nothing moved: following changes nothing.
    still = m.follow_walls(copy.deepcopy(main), walls, joints)
    check(same_points(still['area'], [[0, 0], [30, 0], [30, 20], [0, 20]]), still['area'])

    moved = copy.deepcopy(joints)
    for joint in moved:
        if joint['id'] in ('j1', 'j2'):
            joint['at'][1] += 2
    main2 = m.follow_walls(copy.deepcopy(main), walls, moved)
    awning2 = m.follow_walls(copy.deepcopy(awning), walls, moved)
    check(same_points(main2['area'], [[0, 2], [30, 2], [30, 20], [0, 20]]), main2['area'])
    check(main2['edges'][0].get('wall') == 'w-s', main2['edges'])
    check(same_points(awning2['area'], [[8, -6], [20, -6], [20, 2], [8, 2]]), awning2['area'])
    check(awning2['edges'][0].get('wall') is None, awning2['edges'])


def test_attach_tolerance_is_overhang_plus_half_a_foot():
    """An edge attaches within overhang + 0.5 ft of the wall line, and not past it."""
    m = roofs()
    walls, joints = _box()

    def south_wall_of(y0, overhang):
        roof = {'id': 'roof-t', 'area': [[0, y0], [30, y0], [30, 20], [0, 20]],
                'edges': [{'setting': 'sloped', 'pitch': 6}] * 4, 'plate': 10, 'overhang': overhang}
        return m.attach_edges(copy.deepcopy(roof), walls, joints)['edges'][0].get('wall')

    check(south_wall_of(-1.2, 1) == 'w-s', 'within 1.5 ft with a 1 ft overhang')
    check(south_wall_of(-2.5, 1) is None, 'past 1.5 ft with a 1 ft overhang')
    check(south_wall_of(-0.2, 0) == 'w-s', 'within 0.5 ft with no overhang')
    check(south_wall_of(-0.9, 0) is None, 'past 0.5 ft with no overhang')


def test_lower_roof_bears_on_its_own_storey_and_exterior_walls_only():
    """The bearing rule of twin_joints._bearing: a porch roof on the ground
    storey never attaches to the upstairs wall on the same plan line, the
    upper roof takes the upstairs wall, and an interior wall never carries
    a roof edge."""
    m = roofs()
    down, down_joints = _box('L1', 'a', height=10)
    up, up_joints = _box('L2', 'b', height=9)
    # An interior screen wall on the porch's west side line, ground storey.
    screen_joints = [{'id': 'c1', 'level': 'L1', 'at': [5, -6]}, {'id': 'c2', 'level': 'L1', 'at': [5, 0]}]
    screen = {'id': 'w-screen', 'level': 'L1', 'joints': ['c1', 'c2'], 'kind': 'solid',
              'thickness': 0.33, 'exterior': False, 'height': 10}
    walls = down + up + [screen]
    joints = down_joints + up_joints + screen_joints

    # Porch: 20 ft along the south face, 6 ft deep, back edge on the wall line.
    porch = {'id': 'roof-porch', 'level': 'L1', 'area': [[5, -6], [25, -6], [25, 0], [5, 0]],
             'edges': [{'setting': 'sloped', 'pitch': 4}, {'setting': 'gable'},
                       {'setting': 'gable'}, {'setting': 'gable'}],
             'plate': 9, 'overhang': 1}
    upper = {'id': 'roof-upper', 'level': 'L2', 'area': [[0, 0], [30, 0], [30, 20], [0, 20]],
             'edges': [{'setting': 'sloped', 'pitch': 8}] * 4, 'plate': 20, 'overhang': 1}
    porch = m.attach_edges(copy.deepcopy(porch), walls, joints)
    upper = m.attach_edges(copy.deepcopy(upper), walls, joints)
    check(_edge_walls(porch) == [None, None, 'aw-s', None], _edge_walls(porch))
    check(_edge_walls(upper) == ['bw-s', 'bw-e', 'bw-n', 'bw-w'], _edge_walls(upper))


# ---------------------------------------------------------------- dormers

def test_household_dormer_comes_back_as_its_cross_gable():
    """The household's dormer_of section becomes a dormer hosted on the middle
    block's roof, and dormer_sections gives back the same cross gable."""
    m = roofs()
    sections = dict((s['id'], s) for _, s in household_sections())
    dormer_section = sections['roof:f1f3ece25959462e93d48fb341b3ce3b']
    parent_section = sections['roof:c8d939d2e6974824af1367e641db38f5']
    check(dormer_section['dormer_of'] == parent_section['rect'], 'fixture: the dormer sits on the middle block')

    parent = m.from_section(copy.deepcopy(parent_section))
    dormer = m.dormer_from_section(copy.deepcopy(dormer_section), parent)
    check(dormer['roof'] == parent['id'], dormer)
    check(close(dormer['width'], 12), dormer)          # 21 .. 33 along the eave
    check(close(dormer['pitch'], 10), dormer)

    back = m.dormer_sections(dormer, parent)
    check(len(back) == 1, back)
    got = back[0]
    check(same_rect(got['dormer_of'], parent_section['rect']), got.get('dormer_of'))
    # The cross gable runs from the y0 eave up to the main ridge at y = 32.67.
    problem = same_form(got, dormer_section)
    check(problem is None, (problem, got))


TESTS = (
    test_from_section_sets_each_edge_by_kind,
    test_round_trip_is_identity_for_every_household_section,
    test_round_trip_keeps_hip_clip_and_flat_forms,
    test_per_edge_pitch_survives,
    test_l_shaped_area_gives_two_overlapping_rects_with_inherited_edges,
    test_rect_area_with_angled_edge_is_refused,
    test_attached_edge_follows_its_wall,
    test_attach_tolerance_is_overhang_plus_half_a_foot,
    test_lower_roof_bears_on_its_own_storey_and_exterior_walls_only,
    test_household_dormer_comes_back_as_its_cross_gable,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
