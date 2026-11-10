"""Operations, part 2: hosted items, roofs, buildings, materials, proposals,
site items, the op route and Argyle (spec docs/superpowers/specs/
2026-11-09-house-connected-model-design.md sections 4.3-4.6 and 5.7; plan
docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md Task 9;
brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-9-brief.md;
global ruling P4 for the yard's plants and furniture).

Modules under test:
- services/twin_model_ops.py: apply(model, op, actor='person') -> (model, words)
  and class Refused(ValueError), with the operations add_opening, move_hosted,
  resize_opening, add_anchor, add_item, draw_roof, roof_over, set_roof_edge,
  move_roof_edge, add_dormer, move_dormer, add_level, move_building,
  rotate_building, set, set_material, accept_proposal, dismiss_proposal,
  move_site_item, delete_site_item and add_site_item.
- services/twin_edit.py: the legacy op names translate to model operations.
- main.py: POST /api/house/editor/op taking {op}; 200 {round, words, plan, model};
  a refusal is 400 {error: words}. Parents only (the /api/house/editor/* rule).
- services/agent_tools_v2.py: house_design accepts every new op name.

Shapes come from the schema-3 brief (task-2-brief.md): joints [{id, level, at}],
walls with joints [a, b], openings {wall, at} where at is the centre's distance
from the wall's first joint, anchors and items with a host, roofs {area, edges},
an edge i running from area[i] to area[i + 1]. A roof drawn from
[[0,0],[20,0],[20,10],[0,10]] has the edges y0, x1, y1, x0 (task-3-brief.md).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_ops_more.py
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_ops_more_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_roof_issues  # noqa: E402
from services import twin_store as ts  # noqa: E402

_MISSING = {}
try:
    from services import twin_model_ops as _ops  # noqa: E402
except ImportError as exc:  # the module does not exist until Task 8 lands
    _ops, _MISSING['twin_model_ops'] = None, exc
try:
    from services import twin_model as _model  # noqa: E402
except ImportError as exc:
    _model, _MISSING['twin_model'] = None, exc
try:
    from services import twin_model_bridge as _bridge  # noqa: E402
except ImportError as exc:
    _bridge, _MISSING['twin_model_bridge'] = None, exc
try:
    from services import twin_model_hosts as _hosts  # noqa: E402
except ImportError as exc:
    _hosts, _MISSING['twin_model_hosts'] = None, exc

HOUSEHOLD = os.path.join(ROOT, 'tests', 'fixtures', 'twin_model', 'household-2026-11-09.json')
TOL = 1e-6

SIDING_A = {'id': 'board_and_batten', 'color': '#c9c4b8'}
SIDING_B = {'id': 'stacked_stone_wall', 'color': '#8a8580'}
TRIM = {'id': 'painted_trim', 'color': '#f2efe6'}
FLOOR = {'id': 'wood_floor', 'color': '#a0784f'}
ROOFING = {'id': 'standing_seam', 'color': '#2f3133'}

NEW_OPS = ('add_opening', 'move_hosted', 'resize_opening', 'add_anchor', 'add_item',
           'draw_roof', 'roof_over', 'set_roof_edge', 'move_roof_edge', 'add_dormer',
           'move_dormer', 'add_level', 'move_building', 'rotate_building', 'set_material',
           'accept_proposal', 'dismiss_proposal', 'move_site_item', 'delete_site_item',
           'add_site_item')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def close_pt(a, b, tol=TOL):
    return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))


def _need(name):
    if name in _MISSING:
        raise _MISSING[name]
    return {'twin_model_ops': _ops, 'twin_model': _model,
            'twin_model_bridge': _bridge, 'twin_model_hosts': _hosts}[name]


def ops():
    return _need('twin_model_ops')


# ---------------------------------------------------------------- fixtures

def _two_rooms(levels=1):
    """A 20 x 10 ft house B1 on L1: Kitchen (x 0-12) and Dining (x 12-20).

    j4 (0,10) -n2- jm1 (12,10) -n1- j3 (20,10)
     |               |                |
     w     Kitchen  mid    Dining     e
     |               |                |
    j1 (0,0)  -s1- jm0 (12,0)  -s2-  j2 (20,0)

    With levels=2 an upper storey L2 (elevation 10, ceiling 8) holds a
    10 x 10 Bedroom over x 0-10 (joints k1..k4, walls u-s, u-e, u-n, u-w).
    """
    def wall(wid, a, b, exterior=True, level='L1'):
        return {'id': wid, 'level': level, 'joints': [a, b], 'kind': 'solid',
                'thickness': 0.5 if exterior else 0.33, 'exterior': exterior, 'height': 9}

    building = {
        'id': 'B1', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
        'materials': {'siding': dict(SIDING_A), 'trim': dict(TRIM)},
        'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9}],
        'joints': [
            {'id': 'j1', 'level': 'L1', 'at': [0, 0]},
            {'id': 'jm0', 'level': 'L1', 'at': [12, 0]},
            {'id': 'j2', 'level': 'L1', 'at': [20, 0]},
            {'id': 'j3', 'level': 'L1', 'at': [20, 10]},
            {'id': 'jm1', 'level': 'L1', 'at': [12, 10]},
            {'id': 'j4', 'level': 'L1', 'at': [0, 10]},
        ],
        'walls': [
            wall('s1', 'j1', 'jm0'), wall('s2', 'jm0', 'j2'), wall('e', 'j2', 'j3'),
            wall('n1', 'j3', 'jm1'), wall('n2', 'jm1', 'j4'), wall('w', 'j4', 'j1'),
            wall('mid', 'jm0', 'jm1', exterior=False),
        ],
        'rooms': [
            {'id': 'kitchen', 'level': 'L1', 'name': 'Kitchen', 'kind': 'room',
             'polygon': [[0, 0], [12, 0], [12, 10], [0, 10]],
             'joints': ['j1', 'jm0', 'jm1', 'j4']},
            {'id': 'dining', 'level': 'L1', 'name': 'Dining', 'kind': 'room',
             'polygon': [[12, 0], [20, 0], [20, 10], [12, 10]],
             'joints': ['jm0', 'j2', 'j3', 'jm1']},
        ],
        'openings': [], 'anchors': [], 'items': [],
        'roofs': [], 'dormers': [], 'extensions': [], 'stairs': [],
        'proposals': [], 'flags': [],
    }
    if levels == 2:
        building['levels'].append({'id': 'L2', 'name': 'Upper floor', 'elevation': 10, 'ceiling': 8})
        building['joints'] += [
            {'id': 'k1', 'level': 'L2', 'at': [0, 0]},
            {'id': 'k2', 'level': 'L2', 'at': [10, 0]},
            {'id': 'k3', 'level': 'L2', 'at': [10, 10]},
            {'id': 'k4', 'level': 'L2', 'at': [0, 10]},
        ]
        building['walls'] += [
            wall('u-s', 'k1', 'k2', level='L2'), wall('u-e', 'k2', 'k3', level='L2'),
            wall('u-n', 'k3', 'k4', level='L2'), wall('u-w', 'k4', 'k1', level='L2'),
        ]
        building['rooms'].append(
            {'id': 'bedroom', 'level': 'L2', 'name': 'Bedroom', 'kind': 'room',
             'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]], 'joints': ['k1', 'k2', 'k3', 'k4']})
    return building


def _model_of(building, site=None):
    raw = {'schema': 'chauffeur.twin.plan/3', 'units': 'ft', 'materials': {},
           'buildings': [building], 'site': site if site is not None else {}}
    model, _ = _need('twin_model').normalize(raw)
    return model


def _house(levels=1, site=None):
    return _model_of(_two_rooms(levels), site)


def _b(model):
    return model['buildings'][0]


def _by_id(items, pid):
    return next((p for p in items if p.get('id') == pid), None)


def _apply(model, op):
    """Apply one operation as the person; the words are plain non-empty text."""
    result = ops().apply(copy.deepcopy(model), op)
    check(isinstance(result, tuple) and len(result) == 2, f'apply returns (model, words): {result!r:.200}')
    out, words = result
    check(isinstance(words, str) and words.strip(), f'plain words for {op["op"]}: {words!r}')
    check(out.get('schema') == 'chauffeur.twin.plan/3', f'still schema 3 after {op["op"]}')
    return out


def _refused(model, op):
    try:
        ops().apply(copy.deepcopy(model), op)
    except ops().Refused as exc:
        return str(exc)
    raise AssertionError(f'expected Refused for {op}')


def _added(before, after, key):
    ids = {p['id'] for p in _b(before)[key]}
    new = [p for p in _b(after)[key] if p['id'] not in ids]
    check(len(new) == 1, f'one new {key} entry: {new}')
    return new[0]


def _person(piece):
    return (piece.get('src') or {}).get('person') is True


def _pts(area):
    return sorted((round(p[0], 6), round(p[1], 6)) for p in area)


def _edge_index(roof, axis, value):
    """The index of the area edge lying on x = value (axis 0) or y = value (axis 1)."""
    area = roof['area']
    for i in range(len(area)):
        a, b = area[i], area[(i + 1) % len(area)]
        if close(a[axis], value) and close(b[axis], value):
            return i
    raise AssertionError(f'no edge on {"xy"[axis]} = {value} in {area}')


def _flat_sections(model):
    flat = _need('twin_model_bridge').flatten(copy.deepcopy(model))
    sections = flat['buildings'][0]['roof']['sections']
    return ([s for s in sections if not s.get('dormer_of')],
            [s for s in sections if s.get('dormer_of')])


def _side_pitch(section, side):
    return (section.get('pitches') or {}).get(side, section.get('pitch'))


# ---------------------------------------------------------------- hosted items

def test_add_window_then_drag_it_to_another_wall_rehosts():
    m0 = _house()
    m1 = _apply(m0, {'op': 'add_opening', 'building': 'B1', 'wall': 's1', 'at': 5, 'kind': 'window'})
    win = _added(m0, m1, 'openings')
    check(win['wall'] == 's1' and close(win['at'], 5) and win['kind'] == 'window', win)
    check(close(win['width'], 3), f"the editor's default width is 3 ft: {win}")
    check(win.get('state') not in ('ghost', 'proposal') and _person(win), win)

    # A door without a width also gets 3 ft.
    m2 = _apply(m1, {'op': 'add_opening', 'building': 'B1', 'wall': 'n2', 'at': 6, 'kind': 'door'})
    door = _added(m1, m2, 'openings')
    check(door['wall'] == 'n2' and door['kind'] == 'door' and close(door['width'], 3), door)

    # Dragged round the corner onto the east wall, 3 ft along it.
    m3 = _apply(m2, {'op': 'move_hosted', 'building': 'B1', 'id': win['id'],
                     'host': {'wall': 'e', 'at': 3.0}, 'at': 3.0})
    moved = _by_id(_b(m3)['openings'], win['id'])
    check(moved is not None and len(_b(m3)['openings']) == 2, _b(m3)['openings'])
    check(moved['wall'] == 'e' and close(moved['at'], 3), f're-hosted on e at 3: {moved}')
    check(moved.get('state') not in ('ghost', 'proposal') and _person(moved), moved)
    check(not [f for f in _b(m3)['flags'] if f.get('piece') == win['id']],
          f'a re-hosted window is not flagged: {_b(m3)["flags"]}')

    # Slid along its new wall without a host: it stays on e.
    m4 = _apply(m3, {'op': 'move_hosted', 'building': 'B1', 'id': win['id'], 'at': 7.0})
    slid = _by_id(_b(m4)['openings'], win['id'])
    check(slid['wall'] == 'e' and close(slid['at'], 7), slid)

    # Resized in place.
    m5 = _apply(m4, {'op': 'resize_opening', 'building': 'B1', 'id': win['id'],
                     'width': 4, 'sill': 2.5, 'head': 7})
    sized = _by_id(_b(m5)['openings'], win['id'])
    check(close(sized['width'], 4) and close(sized['sill'], 2.5) and close(sized['head'], 7)
          and sized['wall'] == 'e' and close(sized['at'], 7), sized)


def test_anchors_and_items_sit_on_their_hosts_and_rehost():
    hosts = _need('twin_model_hosts')
    m0 = _house()
    m1 = _apply(m0, {'op': 'add_anchor', 'building': 'B1', 'kind': 'light',
                     'host': {'ceiling': 'kitchen', 'u': 0.5, 'v': 0.5}})
    light = _added(m0, m1, 'anchors')
    check(light['kind'] == 'light' and light['host'] == {'ceiling': 'kitchen', 'u': 0.5, 'v': 0.5}, light)
    check(close_pt(hosts.world_point(_b(m1), light['host']), [6, 5, 9]),
          hosts.world_point(_b(m1), light['host']))

    switch_host = {'wall': 's1', 'side': 'left', 'at': 2.0, 'z': 4.0}
    m2 = _apply(m1, {'op': 'add_anchor', 'building': 'B1', 'kind': 'switch', 'host': dict(switch_host)})
    switch = _added(m1, m2, 'anchors')
    check(switch['kind'] == 'switch' and switch['host'] == switch_host, switch)

    m3 = _apply(m2, {'op': 'add_item', 'building': 'B1', 'asset': 'mid_century_lounge_chair',
                     'host': {'floor': 'dining', 'u': 0.5, 'v': 0.5}, 'rotation': 90, 'scale': 1.2})
    chair = _added(m2, m3, 'items')
    check(chair['asset'] == 'mid_century_lounge_chair'
          and chair['host'] == {'floor': 'dining', 'u': 0.5, 'v': 0.5}
          and close(chair['rotation'], 90) and close(chair['scale'], 1.2) and _person(chair), chair)
    check(close_pt(hosts.world_point(_b(m3), chair['host']), [16, 5, 0]),
          hosts.world_point(_b(m3), chair['host']))

    # The switch is dragged onto the east wall; the chair into the kitchen.
    m4 = _apply(m3, {'op': 'move_hosted', 'building': 'B1', 'id': switch['id'],
                     'host': {'wall': 'e', 'side': 'left', 'at': 3.0, 'z': 4.0}})
    sw = _by_id(_b(m4)['anchors'], switch['id'])
    check(sw['host']['wall'] == 'e' and close(sw['host']['at'], 3) and close(sw['host']['z'], 4)
          and len(_b(m4)['anchors']) == 2, sw)
    m5 = _apply(m4, {'op': 'move_hosted', 'building': 'B1', 'id': chair['id'],
                     'host': {'floor': 'kitchen', 'u': 0.25, 'v': 0.5}})
    moved = _by_id(_b(m5)['items'], chair['id'])
    check(moved['host'] == {'floor': 'kitchen', 'u': 0.25, 'v': 0.5} and len(_b(m5)['items']) == 1, moved)
    check(close_pt(hosts.world_point(_b(m5), moved['host']), [3, 5, 0]),
          hosts.world_point(_b(m5), moved['host']))


# ---------------------------------------------------------------- roofs

def test_roof_over_rooms_then_set_an_edge_gable_and_a_side_pitch():
    m0 = _house()
    # Over the kitchen alone: the kitchen's region.
    k = _apply(m0, {'op': 'roof_over', 'building': 'B1', 'rooms': ['kitchen']})
    roof_k = _added(m0, k, 'roofs')
    check(_pts(roof_k['area']) == _pts([[0, 0], [12, 0], [12, 10], [0, 10]]), roof_k['area'])

    # Over both rooms: their union, four corners (no corner left at x 12).
    m1 = _apply(m0, {'op': 'roof_over', 'building': 'B1', 'rooms': ['kitchen', 'dining']})
    roof = _added(m0, m1, 'roofs')
    check(_pts(roof['area']) == _pts([[0, 0], [20, 0], [20, 10], [0, 10]]), roof['area'])
    check(len(roof['edges']) == 4 and all(e['setting'] == 'sloped' for e in roof['edges']),
          f'every edge starts sloped: {roof["edges"]}')
    check(all(close(e['pitch'], 6) for e in roof['edges']) and close(roof['overhang'], 1),
          f'default pitch 6 and overhang 1: {roof}')
    check(roof.get('level') == 'L1' and close(roof['plate'], 9), f'bears on L1 at 9 ft: {roof}')

    west = _edge_index(roof, 0, 0)
    south = _edge_index(roof, 1, 0)
    north = _edge_index(roof, 1, 10)
    m2 = _apply(m1, {'op': 'set_roof_edge', 'building': 'B1', 'roof': roof['id'],
                     'edge': west, 'setting': 'gable'})
    m3 = _apply(m2, {'op': 'set_roof_edge', 'building': 'B1', 'roof': roof['id'],
                     'edge': south, 'setting': 'sloped', 'pitch': 10})
    r3 = _by_id(_b(m3)['roofs'], roof['id'])
    check(r3['edges'][west]['setting'] == 'gable', r3['edges'])
    check(r3['edges'][south]['setting'] == 'sloped' and close(r3['edges'][south]['pitch'], 10), r3['edges'])
    check(close(r3['edges'][north]['pitch'], 6), r3['edges'])
    check(_person(r3), f'a roof the person edited is theirs: {r3}')

    mains, _ = _flat_sections(m3)
    check(len(mains) == 1, f'one section for a rectangular roof: {mains}')
    sec = mains[0]
    check(close_pt(sec['rect'], [0, 0, 20, 10]) and sec['ridge'] == 'x', sec)
    check(twin_roof_issues._end_kind(sec, 'x0') == 'gable', f'the west end is a gable: {sec}')
    check(close((sec.get('pitches') or {}).get('y0', -1), 10),
          f"the flattened section's pitches show the side pitch: {sec}")
    check(close(_side_pitch(sec, 'y1'), 6), f'the other side keeps 6: {sec}')

    # A clipped end with its clip height.
    m4 = _apply(m3, {'op': 'set_roof_edge', 'building': 'B1', 'roof': roof['id'],
                     'edge': _edge_index(roof, 0, 20), 'setting': 'clip', 'clip': 1.5})
    east = _by_id(_b(m4)['roofs'], roof['id'])['edges'][_edge_index(roof, 0, 20)]
    check(east['setting'] == 'clip' and close(east['clip'], 1.5), east)


def test_roof_over_the_whole_building_uses_its_top_storey():
    m0 = _house(levels=2)
    m1 = _apply(m0, {'op': 'roof_over', 'building': 'B1', 'rooms': None})
    roof = _added(m0, m1, 'roofs')
    check(_pts(roof['area']) == _pts([[0, 0], [10, 0], [10, 10], [0, 10]]),
          f"the top storey's outline, not the main floor's: {roof['area']}")
    check(roof.get('level') == 'L2' and close(roof['plate'], 18),
          f'bears on L2 at its wall tops (10 + 8): {roof}')


def test_draw_roof_defaults_and_a_bad_area_is_refused():
    m0 = _house()
    area = [[0, 0], [20, 0], [20, 10], [0, 10]]
    m1 = _apply(m0, {'op': 'draw_roof', 'building': 'B1', 'area': area, 'plate': 9})
    roof = _added(m0, m1, 'roofs')
    check(_pts(roof['area']) == _pts(area) and len(roof['edges']) == 4, roof)
    check(all(e['setting'] == 'sloped' and close(e['pitch'], 6) for e in roof['edges'])
          and close(roof['overhang'], 1) and close(roof['plate'], 9), roof)
    m2 = _apply(m0, {'op': 'draw_roof', 'building': 'B1', 'area': area, 'plate': 9,
                     'pitch': 8, 'overhang': 1.5})
    roof2 = _added(m0, m2, 'roofs')
    check(all(close(e['pitch'], 8) for e in roof2['edges']) and close(roof2['overhang'], 1.5), roof2)
    words = _refused(m0, {'op': 'draw_roof', 'building': 'B1', 'plate': 9,
                          'area': [[0, 0], [20, 0], [16, 10], [4, 10]]})
    check(words == 'Roof areas must have square corners.', words)


def test_one_bad_dormer_is_flagged_and_every_other_op_proceeds():
    """M5: a dormer whose edge no longer exists on its roof never makes an
    unrelated op refuse; it is ghosted and flagged where its roof stands."""
    m0 = _house()
    area = [[0, 0], [20, 0], [20, 10], [0, 10]]
    m = _apply(m0, {'op': 'draw_roof', 'building': 'B1', 'area': area, 'plate': 9})
    roof = _added(m0, m, 'roofs')
    before = m
    m = _apply(m, {'op': 'add_dormer', 'building': 'B1', 'roof': roof['id'],
                   'edge': _edge_index(roof, 1, 0), 'at': 10, 'width': 4, 'pitch': 8})
    dormer = _added(before, m, 'dormers')
    stale = copy.deepcopy(m)
    _by_id(_b(stale)['dormers'], dormer['id'])['edge'] = 99
    out = _apply(stale, {'op': 'set', 'building': 'B1', 'id': 'kitchen', 'field': 'name', 'value': 'Galley'})
    check(_by_id(_b(out)['rooms'], 'kitchen')['name'] == 'Galley', _b(out)['rooms'])
    lost = _by_id(_b(out)['dormers'], dormer['id'])
    text = 'This dormer lost its roof; place it again.'
    check(lost is not None and lost.get('state') == 'ghost' and lost.get('why') == text, lost)
    flags = [f for f in _b(out)['flags'] if f.get('piece') == dormer['id']]
    check(len(flags) == 1 and flags[0]['text'] == text and flags[0]['level'] is not None
          and flags[0]['at'] != [0, 0] and 0 <= flags[0]['at'][0] <= 20 and 0 <= flags[0]['at'][1] <= 10,
          flags)
    again = _apply(out, {'op': 'set', 'building': 'B1', 'id': 'dining', 'field': 'name', 'value': 'Eat'})
    check(len([f for f in _b(again)['flags'] if f.get('piece') == dormer['id']]) == 1, _b(again)['flags'])


def test_dormer_reaches_the_roof_whatever_the_pitch():
    # A 20 x 10 gable roof, ridge along x at y 5, gables at x 0 and x 20.
    m0 = _house()
    area = [[0, 0], [20, 0], [20, 10], [0, 10]]
    m = _apply(m0, {'op': 'draw_roof', 'building': 'B1', 'area': area, 'plate': 9})
    roof = _added(m0, m, 'roofs')
    for x in (0, 20):
        m = _apply(m, {'op': 'set_roof_edge', 'building': 'B1', 'roof': roof['id'],
                       'edge': _edge_index(roof, 0, x), 'setting': 'gable'})
    south = _edge_index(roof, 1, 0)
    north = _edge_index(roof, 1, 10)
    before = m
    # A 4 ft dormer centred 10 ft along the south (y0) edge, pitch 8.
    m = _apply(m, {'op': 'add_dormer', 'building': 'B1', 'roof': roof['id'], 'edge': south,
                   'at': 10, 'width': 4, 'pitch': 8})
    dormer = _added(before, m, 'dormers')
    check(dormer['roof'] == roof['id'] and dormer['edge'] == south and close(dormer['at'], 10)
          and close(dormer['width'], 4) and close(dormer['pitch'], 8), dormer)

    def dormer_rect(model):
        mains, dormers = _flat_sections(model)
        check(len(mains) == 1 and len(dormers) == 1, (mains, dormers))
        d = dormers[0]
        check(close_pt(d['dormer_of'], mains[0]['rect']), f'dormer_of is the main rect: {d}')
        check(d['kind'] == 'gable' and d['ridge'] == 'y' and close(d['plate'], 9), d)
        return d

    d = dormer_rect(m)
    check(close_pt(d['rect'], [8, 0, 12, 5]), f'from the eave line up to the main ridge at y 5: {d}')
    check(close(d['pitch'], 8), d)

    # Whatever the main roof's pitch, the dormer still runs up to the ridge.
    for pitch in (4, 9, 12):
        steep = m
        for edge in (south, north):
            steep = _apply(steep, {'op': 'set_roof_edge', 'building': 'B1', 'roof': roof['id'],
                                   'edge': edge, 'setting': 'sloped', 'pitch': pitch})
        d = dormer_rect(steep)
        check(close_pt(d['rect'], [8, 0, 12, 5]), f'main pitch {pitch}: {d}')
        check(len(_b(steep)['dormers']) == 1, f'the dormer survives a pitch change: {_b(steep)["dormers"]}')

    # Whatever the dormer's own pitch.
    m_moved = _apply(m, {'op': 'move_dormer', 'building': 'B1', 'id': dormer['id'], 'at': 6})
    check(close_pt(dormer_rect(m_moved)['rect'], [4, 0, 8, 5]), dormer_rect(m_moved))
    m_wide = _apply(m, {'op': 'move_dormer', 'building': 'B1', 'id': dormer['id'], 'width': 6})
    check(close_pt(dormer_rect(m_wide)['rect'], [7, 0, 13, 5]), dormer_rect(m_wide))
    check(_person(_by_id(_b(m_wide)['dormers'], dormer['id'])), _b(m_wide)['dormers'])


# ---------------------------------------------------------------- buildings, levels, fields

def test_add_level_move_and_rotate_building():
    m0 = _house()
    m1 = _apply(m0, {'op': 'add_level', 'building': 'B1', 'name': 'Attic', 'elevation': 10, 'ceiling': 7})
    level = _added(m0, m1, 'levels')
    check(level['name'] == 'Attic' and close(level['elevation'], 10) and close(level['ceiling'], 7), level)
    check([l['id'] for l in _b(m1)['levels']][:1] == ['L1'], _b(m1)['levels'])

    m2 = _apply(m1, {'op': 'move_building', 'building': 'B1', 'to': [30, 40]})
    check(close_pt(_b(m2)['position'], [30, 40]), _b(m2)['position'])
    check(_b(m2)['joints'] == _b(m1)['joints'], 'joints are building-local and do not move')

    m3 = _apply(m2, {'op': 'rotate_building', 'building': 'B1', 'rotation': 90})
    check(close(_b(m3)['rotation'], 90) and close_pt(_b(m3)['position'], [30, 40]), _b(m3))


def test_set_edits_fields_and_names_a_room():
    m0 = _house()
    m1 = _apply(m0, {'op': 'set', 'building': 'B1', 'id': 'kitchen', 'field': 'name', 'value': 'Pantry'})
    room = _by_id(_b(m1)['rooms'], 'kitchen')
    check(room is not None and room['name'] == 'Pantry', f'the name survives the re-derive: {_b(m1)["rooms"]}')
    m2 = _apply(m1, {'op': 'set', 'building': 'B1', 'id': 's1', 'field': 'height', 'value': 8})
    wall = _by_id(_b(m2)['walls'], 's1')
    check(close(wall['height'], 8) and _person(wall), wall)
    m3 = _apply(m2, {'op': 'set', 'building': 'B1', 'id': 'L1', 'field': 'ceiling', 'value': 10})
    check(close(_by_id(_b(m3)['levels'], 'L1')['ceiling'], 10), _b(m3)['levels'])
    _refused(m0, {'op': 'set', 'building': 'B1', 'id': 's1', 'field': 'level', 'value': 'L2'})


# ---------------------------------------------------------------- materials

def test_set_material_cascade_and_clear():
    m0 = _house()
    m0 = _apply(m0, {'op': 'roof_over', 'building': 'B1', 'rooms': None})
    rid = _b(m0)['roofs'][0]['id']

    def faces(model):
        return {w['id']: {k: v for k, v in (w.get('faces') or {}).items() if v}
                for w in _b(model)['walls']}

    # The whole building: one change, no surface stamped.
    m1 = _apply(m0, {'op': 'set_material', 'building': 'B1',
                     'target': {'building': 'B1', 'role': 'siding'}, 'material': dict(SIDING_B)})
    check(_b(m1)['materials']['siding'] == SIDING_B and _b(m1)['materials']['trim'] == TRIM,
          _b(m1)['materials'])
    check(all(not f for f in faces(m1).values()), f'a building material is inherited, never copied: {faces(m1)}')

    # One wall face overrides only that face.
    m2 = _apply(m1, {'op': 'set_material', 'building': 'B1',
                     'target': {'wall': 's1', 'side': 'left'}, 'material': dict(SIDING_A)})
    f2 = faces(m2)
    check(f2['s1'] == {'left': SIDING_A}, f2['s1'])
    check(all(not f for wid, f in f2.items() if wid != 's1'), f2)
    check(_b(m2)['materials']['siding'] == SIDING_B, _b(m2)['materials'])

    # One room's floor and another room's ceiling.
    m3 = _apply(m2, {'op': 'set_material', 'building': 'B1',
                     'target': {'room': 'kitchen', 'surface': 'floor'}, 'material': dict(FLOOR)})
    m3 = _apply(m3, {'op': 'set_material', 'building': 'B1',
                     'target': {'room': 'dining', 'surface': 'ceiling'}, 'material': dict(TRIM)})
    kitchen, dining = _by_id(_b(m3)['rooms'], 'kitchen'), _by_id(_b(m3)['rooms'], 'dining')
    check(kitchen.get('floor_material') == FLOOR and not kitchen.get('ceiling_material'), kitchen)
    check(dining.get('ceiling_material') == TRIM and not dining.get('floor_material'), dining)

    # One roof.
    m4 = _apply(m3, {'op': 'set_material', 'building': 'B1',
                     'target': {'roof': rid}, 'material': dict(ROOFING)})
    check(_by_id(_b(m4)['roofs'], rid).get('material') == ROOFING, _b(m4)['roofs'])

    # The flat view the generator draws carries the overrides.
    flat = _need('twin_model_bridge').flatten(copy.deepcopy(m4))['buildings'][0]
    check(flat['materials']['siding'] == SIDING_B, flat['materials'])
    check((_by_id(flat['walls'], 's1').get('faces') or {}).get('left') == SIDING_A, _by_id(flat['walls'], 's1'))
    check(not (_by_id(flat['walls'], 's2').get('faces') or {}).get('left'), _by_id(flat['walls'], 's2'))
    check(_by_id(flat['rooms'], 'kitchen').get('floor_material') == FLOOR, _by_id(flat['rooms'], 'kitchen'))

    # Clearing returns each surface to what it inherits.
    m5 = _apply(m4, {'op': 'set_material', 'building': 'B1',
                     'target': {'wall': 's1', 'side': 'left'}, 'material': None})
    check(all(not f for f in faces(m5).values()), faces(m5))
    check(_b(m5)['materials']['siding'] == SIDING_B, 'clearing a face leaves the building alone')
    m6 = _apply(m5, {'op': 'set_material', 'building': 'B1',
                     'target': {'room': 'kitchen', 'surface': 'floor'}, 'material': None})
    check(not _by_id(_b(m6)['rooms'], 'kitchen').get('floor_material'), _by_id(_b(m6)['rooms'], 'kitchen'))
    check(_by_id(_b(m6)['rooms'], 'dining').get('ceiling_material') == TRIM, 'the other room keeps its own')
    m7 = _apply(m6, {'op': 'set_material', 'building': 'B1', 'target': {'roof': rid}, 'material': None})
    check(not _by_id(_b(m7)['roofs'], rid).get('material'), _b(m7)['roofs'])
    m8 = _apply(m7, {'op': 'set_material', 'building': 'B1',
                     'target': {'building': 'B1', 'role': 'siding'}, 'material': None})
    check(not _b(m8)['materials'].get('siding') and _b(m8)['materials']['trim'] == TRIM,
          f'the building role returns to the kit: {_b(m8)["materials"]}')


# ---------------------------------------------------------------- proposals

def _flat_box(east, walls_extra=(), rooms=None):
    def wall(wid, a, b, exterior=False):
        return {'id': wid, 'level': 'L1', 'from': list(a), 'to': list(b), 'exterior': exterior,
                'thickness': 0.5 if exterior else 0.33, 'height': 9}
    walls = [wall('s', (0, 0), (east, 0), True), wall('e', (east, 0), (east, 10), True),
             wall('n', (east, 10), (0, 10), True), wall('w', (0, 10), (0, 0), True)]
    walls += [wall(*spec) for spec in walls_extra]
    if rooms is None:
        rooms = [{'id': 'room-hall', 'level': 'L1', 'name': 'Hall',
                  'polygon': [[0, 0], [east, 0], [east, 10], [0, 10]]}]
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {},
            'site': {'lot': [[-20, -20], [80, -20], [80, 60], [-20, 60]]},
            'buildings': [{'id': 'b1', 'name': 'Test house', 'position': [0, 0], 'rotation': 0,
                           'base': 0,
                           'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9}],
                           'walls': walls, 'openings': [], 'rooms': rooms,
                           'roof': {'sections': [], 'extensions': []},
                           'stairs': [], 'fixtures': [], 'lights': [], 'porches': []}]}


def _wall_ends(building, wall):
    joints = {j['id']: j['at'] for j in building['joints']}
    return joints[wall['joints'][0]], joints[wall['joints'][1]]


def _same_segment(ends, p, q, tol=TOL):
    a, b = ends
    return (close_pt(a, p, tol) and close_pt(b, q, tol)) or (close_pt(a, q, tol) and close_pt(b, p, tol))


def _proposed():
    """The person shortened q (y 5, x 15-25) to end at x 22; a new read says x 25."""
    bridge = _need('twin_model_bridge')
    model0, _ = bridge.assemble(_flat_box(30, [('q', (15, 5), (25, 5))]), None)
    b0 = _b(model0)
    q = _by_id(b0['walls'], 'q')
    q['src'] = {'person': True}
    for jid in q['joints']:
        joint = _by_id(b0['joints'], jid)
        if close_pt(joint['at'], [25, 5]):
            joint['at'] = [22, 5]
    model1, _ = bridge.assemble(_flat_box(30, [('q', (15, 5), (25, 5))]), copy.deepcopy(model0))
    props = _b(model1)['proposals']
    check(len(props) == 1 and props[0].get('against') == 'q', f'the fixture holds one proposal: {props}')
    return model1, props[0]


def _live_on_y5(building):
    return [w for w in building['walls'] if w.get('state') != 'proposal'
            and all(close(p[1], 5) for p in _wall_ends(building, w))]


def test_accept_and_dismiss_a_proposal():
    model, prop = _proposed()
    check(_same_segment(_wall_ends(_b(model), _by_id(_b(model)['walls'], 'q')), [15, 5], [22, 5]),
          "the person's q before any answer")

    accepted = _apply(model, {'op': 'accept_proposal', 'building': 'b1', 'id': prop['id']})
    ba = _b(accepted)
    check(ba['proposals'] == [], f'an accepted proposal is gone: {ba["proposals"]}')
    on_line = _live_on_y5(ba)
    check(len(on_line) == 1, f'one wall on the line, the read replacing the person\'s: {on_line}')
    check(_same_segment(_wall_ends(ba, on_line[0]), [15, 5], [25, 5]), _wall_ends(ba, on_line[0]))
    check(on_line[0].get('state', 'settled') == 'settled' and _person(on_line[0]),
          f'accepting is the person\'s act: {on_line[0]}')

    dismissed = _apply(model, {'op': 'dismiss_proposal', 'building': 'b1', 'id': prop['id']})
    bd = _b(dismissed)
    check(bd['proposals'] == [], f'a dismissed proposal is gone: {bd["proposals"]}')
    on_line = _live_on_y5(bd)
    check(len(on_line) == 1 and on_line[0]['id'] == 'q', on_line)
    check(_same_segment(_wall_ends(bd, on_line[0]), [15, 5], [22, 5]) and _person(on_line[0]),
          f"the person's q stays as they left it: {on_line[0]}")
    check(sorted(w['id'] for w in bd['walls']) == sorted(w['id'] for w in _b(model)['walls']
                                                          if w.get('state') != 'proposal'),
          'dismissing changes no wall')

    _refused(model, {'op': 'accept_proposal', 'building': 'b1', 'id': 'no-such-proposal'})


# ---------------------------------------------------------------- site items (P4)

def test_flag_ok_removes_only_the_index_and_text_and_refuses_replay():
    model = _house()
    first = {'level': 'L1', 'at': [1, 1], 'text': 'Check the first piece.', 'piece': 's1'}
    second = {'level': 'L1', 'at': [2, 2], 'text': 'Check the second piece.', 'piece': 'mid'}
    _b(model)['flags'] = [first, second]
    other = copy.deepcopy(_b(model))
    other['id'] = 'B2'
    model['buildings'].append(other)
    before = copy.deepcopy(model)
    op = {'op': 'set', 'building': 'B1', 'field': 'flag_ok', 'value': {'index': 0, 'text': first['text']}}
    after = _apply(model, op)
    check(_b(after)['flags'] == [second], _b(after)['flags'])
    check(after['buildings'][1] == before['buildings'][1], 'the other building is unchanged')
    check(_b(after)['walls'] == _b(before)['walls'], 'acknowledging keeps every wall')
    check(model == before, 'apply does not mutate its input')
    _refused(after, op)
    check(_b(after)['flags'] == [second], 'a replay never removes the next flag')


def test_flag_ok_rejects_bad_index_or_text():
    model = _house()
    _b(model)['flags'] = [{'at': [1, 1], 'text': 'Check this piece.'}]
    before = copy.deepcopy(model)
    for value in (None, True, {}, {'index': True, 'text': 'Check this piece.'},
                  {'index': -1, 'text': 'Check this piece.'}, {'index': 1, 'text': 'Check this piece.'},
                  {'index': 0.0, 'text': 'Check this piece.'}, {'index': 0},
                  {'index': 0, 'text': 'Another check.'}):
        _refused(model, {'op': 'set', 'building': 'B1', 'field': 'flag_ok', 'value': value})
        check(model == before, ('a refused acknowledgement changes nothing', value))


def test_flag_ok_snapshot_distinguishes_checks_with_the_same_words():
    model = _house()
    first = {'level': 'L1', 'at': [1, 1], 'text': 'Check this piece.'}
    second = {**first, 'at': [2, 2]}
    _b(model)['flags'] = [first, second]
    op = {'op': 'set', 'building': 'B1', 'field': 'flag_ok',
          'value': {'index': 0, 'text': first['text'], 'flag': copy.deepcopy(first)}}
    after = _apply(model, op)
    check(_b(after)['flags'] == [second], 'only the indexed flag is removed when the words repeat')
    _refused(after, op)


def test_flag_ok_migration_separator_stays_cleared_after_normalize_and_reread():
    with open(HOUSEHOLD, encoding='utf-8') as handle:
        flat = json.load(handle)
    bridge = _need('twin_model_bridge')
    model, _ = bridge.assemble(flat)
    b = model['buildings'][0]
    index, flag = next((i, f) for i, f in enumerate(b['flags']) if f.get('separators'))
    walls = copy.deepcopy(b['walls'])
    after = _apply(model, {'op': 'set', 'building': b['id'], 'field': 'flag_ok',
                           'value': {'index': index, 'text': flag['text']}})
    expected = b['flags'][:index] + b['flags'][index + 1:]
    check(after['buildings'][0]['flags'] == expected, 'only the selected grouped flag is removed')
    check(after['buildings'][0]['walls'] == walls, 'all migration separators and their flagged markers stay')
    normalized, _ = _need('twin_model').normalize(after)
    reread, _ = bridge.assemble(bridge.flatten(normalized), previous=normalized)
    check(not any(f['text'] == flag['text'] and f.get('level') == flag['level']
                  for f in reread['buildings'][0]['flags']), 'R37: the acknowledged group is not flagged again')


def test_flag_ok_unclosed_room_stays_checked_and_keeps_its_recovery_record():
    model = _house()
    wall = copy.deepcopy(_by_id(_b(model)['walls'], 'w'))
    _b(model)['walls'].remove(_by_id(_b(model)['walls'], 'w'))
    model, _ = _need('twin_model').normalize(model)
    index, flag = next((i, f) for i, f in enumerate(_b(model)['flags'])
                       if isinstance(f.get('piece'), dict) and f['piece'].get('room', {}).get('id') == 'kitchen')
    after = _apply(model, {'op': 'set', 'building': 'B1', 'field': 'flag_ok',
                           'value': {'index': index, 'text': flag['text']}})
    normalized, _ = _need('twin_model').normalize(after)
    check(flag not in _b(normalized)['flags'], 'the derived room note stays acknowledged on a save')
    check(flag in _b(normalized)['checked_flags'], 'the missing room record is retained')
    _b(normalized)['walls'].append(wall)
    restored, _ = _need('twin_model').normalize(normalized)
    kitchen = _by_id(_b(restored)['rooms'], 'kitchen')
    check(kitchen['name'] == 'Kitchen', 'reclosing the room recovers its name after acknowledging its flag')
    check(flag not in _b(restored)['checked_flags'], 'a repaired room retires its acknowledgement')


def test_flag_ok_unhosted_opening_stays_checked_until_it_is_repaired():
    model = _house()
    model = _apply(model, {'op': 'add_opening', 'building': 'B1', 'wall': 'mid', 'at': 5, 'kind': 'door'})
    model = _apply(model, {'op': 'delete', 'building': 'B1', 'id': 'mid'})
    index, flag = next((i, f) for i, f in enumerate(_b(model)['flags']) if 'lost its wall' in f['text'])
    after = _apply(model, {'op': 'set', 'building': 'B1', 'field': 'flag_ok',
                           'value': {'index': index, 'text': flag['text']}})
    normalized, _ = _need('twin_model').normalize(after)
    check(flag not in _b(after)['flags'] and flag not in _b(normalized)['flags'], 'the unhosted note stays checked')
    door = _by_id(_b(normalized)['openings'], flag['piece'])
    check(door['state'] == 'ghost', 'acknowledging never deletes or falsely settles the door')
    repaired = _apply(normalized, {'op': 'move_hosted', 'building': 'B1', 'id': door['id'],
                                   'host': {'wall': 's1', 'side': 'left', 'at': 5, 'z': 0}})
    check(not _b(repaired).get('checked_flags'), 'rehosting retires the old acknowledgement')


def _household_site():
    with open(HOUSEHOLD, encoding='utf-8') as handle:
        return json.load(handle)['site']


def test_site_items_record_compose_overrides():
    m0 = _house(site=_household_site())
    site0 = copy.deepcopy(m0['site'])
    first, second = site0['planting'][0], site0['planting'][1]
    check(first.get('by') == 'compose' and second.get('by') == 'compose', 'composed shrubs in the fixture')
    to = [first['at'][0] + 1.5, first['at'][1] + 1.0]

    m1 = _apply(m0, {'op': 'move_site_item', 'list': 'planting', 'index': 0, 'at': list(to)})
    check(close_pt(m1['site']['planting'][0]['at'], to) and m1['site']['planting'][0]['id'] == first['id'],
          m1['site']['planting'][0])
    expect = copy.deepcopy(site0)
    expect['planting'][0]['at'] = list(to)
    want = twin_plan.record_compose_overrides({'site': site0}, {'site': expect})['site']['compose_overrides']
    check(m1['site']['compose_overrides'] == want, (m1['site']['compose_overrides'], want))
    check(m1['site']['compose_overrides']['moved'].get(first['id']) == to, m1['site']['compose_overrides'])

    m2 = _apply(m1, {'op': 'delete_site_item', 'list': 'planting', 'index': 1})
    ids = [p['id'] for p in m2['site']['planting']]
    check(second['id'] not in ids and len(ids) == len(site0['planting']) - 1, ids)
    check(second['id'] in m2['site']['compose_overrides']['removed']
          and m2['site']['compose_overrides']['moved'].get(first['id']) == to,
          f'the removal is remembered and the earlier move kept: {m2["site"]["compose_overrides"]}')

    m3 = _apply(m2, {'op': 'add_site_item', 'list': 'furniture',
                     'asset': 'outdoor_table_chair_set_01', 'at': [40, 40]})
    furniture = m3['site']['furniture']
    check(len(furniture) == len(site0['furniture']) + 1, furniture)
    added = furniture[-1]
    check(close_pt(added['at'], [40, 40]) and 'outdoor_table_chair_set_01' in added.values()
          and added.get('by') != 'compose', f'a person-added piece of furniture: {added}')
    check(m3['site']['compose_overrides'] == m2['site']['compose_overrides'],
          'adding an item records no override')


# ---------------------------------------------------------------- the store, the route, Argyle

_real_settings = storage.get_settings
TOKENS = {}


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _people():
    if not TOKENS:
        storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
        storage.add_member({'id': 'k1', 'name': 'Kit', 'role': 'child'})
        TOKENS['parent'] = {'X-Member-Token': storage.create_member_token('p1')}
        TOKENS['child'] = {'X-Member-Token': storage.create_member_token('k1')}
    return TOKENS


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def _seed():
    """A stored 20 x 10 box (walls s, e, n, w) with one room, as a build round."""
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    return ts.push_round(_flat_box(20), 'build')


def test_op_route_round_trip():
    tokens = _people()
    base = _seed()
    c = _client()
    op = {'op': 'add_opening', 'building': 'b1', 'wall': 's', 'at': 6, 'kind': 'window'}
    with _enforced():
        for who in (tokens['child'], {}):
            r = c.post('/api/house/editor/op', headers=who, json={'op': op})
            check(r.status_code in (401, 403), f'parents only: {r.status_code}')
        r = c.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
    check(r.status_code == 200, r.text)
    body = r.json()
    check(isinstance(body.get('round'), int) and body['round'] > base and body['round'] == ts.current_id(),
          f'a new round: {body.get("round")} after {base}')
    check(isinstance(body.get('words'), str) and body['words'].strip(), body.get('words'))
    check(body['plan']['schema'] == 'chauffeur.twin.plan/2', 'plan is the flat view')
    check(body['model']['schema'] == 'chauffeur.twin.plan/3', 'model is schema 3')
    on_s = [o for o in body['model']['buildings'][0]['openings'] if o.get('wall') == 's']
    check(len(on_s) == 1 and close(on_s[0]['at'], 6) and on_s[0]['kind'] == 'window'
          and close(on_s[0]['width'], 3) and _person(on_s[0]), on_s)
    flat_on_s = [o for o in body['plan']['buildings'][0]['openings'] if o.get('wall') == 's']
    check(len(flat_on_s) == 1 and flat_on_s[0]['id'] == on_s[0]['id'], flat_on_s)
    stored = [o for o in ts.current_model()['buildings'][0]['openings'] if o.get('wall') == 's']
    check([o['id'] for o in stored] == [on_s[0]['id']], f'the store holds it: {stored}')
    check([o['id'] for o in ts.current()['buildings'][0]['openings'] if o.get('wall') == 's']
          == [on_s[0]['id']], 'and the flat view of the store')
    fixes = [f for f in ts.fixes() if f['round'] == body['round']]
    check(fixes and all(f['actor_id'] == 'p1' and f['reason'] == body['words'] for f in fixes),
          'without a reason the fix log uses the saved summary and parent')


def test_op_route_rename_uses_the_saved_summary_and_registry():
    tokens = _people()
    _seed()
    old_name = ts.current()['buildings'][0]['name']
    with _enforced():
        response = _client().post('/api/house/editor/op', headers=tokens['parent'], json={'op': {
            'op': 'set', 'building': 'b1', 'id': 'b1', 'field': 'name', 'value': 'Our home'}})
    check(response.status_code == 200, response.text)
    body = response.json()
    check(body['words'] == f'Renamed {old_name} to Our home', body['words'])
    check(body['plan']['buildings'][0]['name'] == body['model']['buildings'][0]['name'] == 'Our home', body)
    check(next(b for b in ts.place()['buildings'] if b['id'] == 'b1')['name'] == 'Our home', ts.place())
    check(ts.rounds()[-1]['note'] == body['words'], ts.rounds()[-1])


def test_op_route_delete_survives_a_sheet_reread_and_logs_the_parent():
    import test_twin_build as engine_tests
    from services import twin_build

    tokens = _people()
    engine_tests._fresh()
    _, _, photo = engine_tests._sources()
    reader = engine_tests.Reader()
    build = twin_build.start(engine_tests._inputs(photo), reader=reader, inline=True)
    engine_tests._run_to(build, 'registration:L2')
    house = ts.current()['buildings'][0]
    wall = next(w for w in house['walls'] if w.get('src', {}).get('step') == 'walls:L1:main')
    reason = 'This wall is not on the drawing.'
    with _enforced():
        response = _client().post('/api/house/editor/op', headers=tokens['parent'], json={
            'op': {'op': 'delete', 'building': house['id'], 'id': wall['id']}, 'reason': reason})
    check(response.status_code == 200, response.text)
    body = response.json()
    check(not any(w['id'] == wall['id'] for w in body['model']['buildings'][0]['walls']), 'deleted in the response')
    stone = next((t for t in ts.tombstones() if t['kind'] == 'wall'
                  and t['geometry'] == {k: wall[k] for k in ('from', 'to')}), None)
    check(stone and stone['src'] == wall['src'] and stone['building'] == house['id'], ts.tombstones())
    fixes = [f for f in ts.fixes() if f['round'] == body['round']]
    check(fixes and all(f['actor_id'] == 'p1' and f['reason'] == reason for f in fixes), fixes)
    check(ts.rounds()[-1]['note'] == body['words'] and ts.rounds()[-1]['kind'] == 'edit', ts.rounds()[-1])

    calls = len(reader.calls)
    twin_build.reread(build, 'walls:L1:main', reader=reader, inline=True)
    check(any(c['step'] == 'walls:L1:main' for c in reader.calls[calls:]), 'the same sheet was read again')
    after = ts.current()['buildings'][0]['walls']
    check(not any(_same_segment((w['from'], w['to']), wall['from'], wall['to']) for w in after),
          'the deleted wall stays gone after the real rebuild merge')


def test_op_route_refusal_is_400_with_words():
    tokens = _people()
    _seed()
    count = len(ts.rounds())
    before = ts.current_model()
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {
            'op': 'add_wall', 'building': 'b1', 'level': 'L1', 'from': [4, 4], 'to': [4.5, 4]}})
    check(r.status_code == 400, f'{r.status_code} {r.text}')
    check(r.json().get('error') == 'A wall must be at least 1 ft long.', r.text)
    check(len(ts.rounds()) == count, 'a refusal stores no round')
    check(ts.current_model() == before, 'a refusal changes nothing')


def test_op_route_flag_ok_clears_a_check_and_refuses_a_replay():
    """Looks right posts flag_ok with no piece id; the route must reach the model op."""
    tokens = _people()
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    with open(HOUSEHOLD, encoding='utf-8') as handle:
        ts.push_round(json.load(handle), 'build')
    before = ts.current_model()
    b = before['buildings'][0]
    index, flag = next((i, f) for i, f in enumerate(b['flags']) if f.get('separators'))
    op = {'op': 'set', 'building': b['id'], 'field': 'flag_ok',
          'value': {'index': index, 'text': flag['text'], 'flag': flag}}
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
        check(r.status_code == 200, f'{r.status_code} {r.text}')
        after = ts.current_model()
        check(after['buildings'][0]['flags'] == b['flags'][:index] + b['flags'][index + 1:],
              'the route removes exactly that check')
        check([o['flags'] for o in after['buildings'][1:]] == [o['flags'] for o in before['buildings'][1:]],
              'the other buildings keep their checks')
        r = c.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
    check(r.status_code == 400, f'a replay is refused: {r.status_code} {r.text}')
    check(ts.current_model() == after, 'a refused replay changes nothing')


def test_house_design_tool_reaches_new_ops():
    from services import agent_tools_v2
    _people()
    _seed()
    parent = storage.get_member('p1')

    def run(edit):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': edit}, actor=parent)
        check(out.get('status') == 'ok' and out.get('changed') is True, f'{edit["op"]}: {out}')
        return out

    run({'op': 'set_material', 'building': 'b1',
         'target': {'building': 'b1', 'role': 'siding'}, 'material': dict(SIDING_B)})
    check(ts.current_model()['buildings'][0]['materials'].get('siding') == SIDING_B,
          ts.current_model()['buildings'][0]['materials'])
    run({'op': 'roof_over', 'building': 'b1', 'rooms': None})
    model = ts.current_model()
    check(len(model['buildings'][0]['roofs']) == 1, model['buildings'][0]['roofs'])
    check(len(ts.current()['buildings'][0]['roof']['sections']) == 1, ts.current()['buildings'][0]['roof'])
    run({'op': 'add_anchor', 'building': 'b1', 'kind': 'light',
         'host': {'ceiling': 'room-hall', 'u': 0.5, 'v': 0.5}})
    anchors = ts.current_model()['buildings'][0]['anchors']
    check(len(anchors) == 1 and anchors[0]['kind'] == 'light', anchors)

    child = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {
        'op': 'roof_over', 'building': 'b1', 'rooms': None}}, actor={'id': 'k1', 'role': 'child'})
    check(child.get('status') == 'refused', child)

    described = json.dumps(agent_tools_v2.TOOL_SCHEMAS['house_design'])
    missing = [name for name in NEW_OPS if name not in described]
    check(not missing, f'the tool description names every operation: missing {missing}')


def test_legacy_edit_ops_still_work():
    # The legacy op names translate to model operations: moving the east wall
    # moves its joints, so the walls on them stretch with it.
    _people()
    _seed()
    from services import twin_edit
    twin_edit.save({'op': 'move', 'piece': 'e', 'by': [2, 0]}, 'p1')
    model = ts.current_model()
    b = _b(model)
    check(_same_segment(_wall_ends(b, _by_id(b['walls'], 'e')), [22, 0], [22, 10]),
          _wall_ends(b, _by_id(b['walls'], 'e')))
    check(_same_segment(_wall_ends(b, _by_id(b['walls'], 's')), [0, 0], [22, 0]),
          f'the south wall stretches with the joint: {_wall_ends(b, _by_id(b["walls"], "s"))}')
    flat = ts.current()['buildings'][0]
    check(_same_segment((_by_id(flat['walls'], 'n')['from'], _by_id(flat['walls'], 'n')['to']),
                        [22, 10], [0, 10]), _by_id(flat['walls'], 'n'))
    twin_edit.save({'op': 'add_opening', 'wall': 's', 'kind': 'door', 'at': 5, 'width': 3}, 'p1')
    check(len([o for o in _b(ts.current_model())['openings'] if o.get('wall') == 's']) == 1,
          _b(ts.current_model())['openings'])

    # The existing legacy suite stays green.
    env = {k: v for k, v in os.environ.items() if k not in ('HA_BASE_URL', 'CHAUFFEUR_DATA_DIR')}
    env['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_edit_legacy_')
    run = subprocess.run([sys.executable, os.path.join('tests', 'test_twin_edit.py')], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=300)
    tail = (run.stdout + run.stderr)[-1500:]
    check(run.returncode == 0, f'tests/test_twin_edit.py exited {run.returncode}: {tail}')


TESTS = (
    test_one_bad_dormer_is_flagged_and_every_other_op_proceeds,
    test_add_window_then_drag_it_to_another_wall_rehosts,
    test_anchors_and_items_sit_on_their_hosts_and_rehost,
    test_roof_over_rooms_then_set_an_edge_gable_and_a_side_pitch,
    test_roof_over_the_whole_building_uses_its_top_storey,
    test_draw_roof_defaults_and_a_bad_area_is_refused,
    test_dormer_reaches_the_roof_whatever_the_pitch,
    test_add_level_move_and_rotate_building,
    test_set_edits_fields_and_names_a_room,
    test_set_material_cascade_and_clear,
    test_accept_and_dismiss_a_proposal,
    test_flag_ok_removes_only_the_index_and_text_and_refuses_replay,
    test_flag_ok_rejects_bad_index_or_text,
    test_flag_ok_snapshot_distinguishes_checks_with_the_same_words,
    test_flag_ok_migration_separator_stays_cleared_after_normalize_and_reread,
    test_flag_ok_unclosed_room_stays_checked_and_keeps_its_recovery_record,
    test_flag_ok_unhosted_opening_stays_checked_until_it_is_repaired,
    test_site_items_record_compose_overrides,
    test_op_route_round_trip,
    test_op_route_rename_uses_the_saved_summary_and_registry,
    test_op_route_delete_survives_a_sheet_reread_and_logs_the_parent,
    test_op_route_refusal_is_400_with_words,
    test_op_route_flag_ok_clears_a_check_and_refuses_a_replay,
    test_house_design_tool_reaches_new_ops,
    test_legacy_edit_ops_still_work,
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
