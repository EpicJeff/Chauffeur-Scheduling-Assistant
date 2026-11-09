"""The generator draws the connected model, in real Chromium (brief .superpowers/
sdd/2026-11-09-house-connected-model-pieces-1-2/task-7-brief.md; spec docs/
superpowers/specs/2026-11-09-house-connected-model-design.md sections 4.1-4.3
and 5.7; plan docs/superpowers/plans/2026-11-09-house-connected-model-pieces-
1-2.md Task 7; ledger Ruling R17).

What is pinned:
- a wall with `footprint` [from_left, to_left, to_right, from_right] is
  extruded from that quadrilateral, so corners close at the joints (mitred);
  a wall without one keeps today's path (outside face on the drawn line);
- a `separator` wall is never meshed;
- floors come from room polygons, one per room;
- materials resolve per surface: the wall face (faces.left / faces.right),
  the room (floor_material), the level (`materials`, R17), the building,
  then the kit;
- items load their library model and sit where their host puts them;
- anchors draw, as small discs, only when `view.showAnchors` is true.

The plans are FLAT plans in the shape Task 5's flatten gives the generator
(walls with from/to, joints, kind, footprint, faces; rooms with polygon,
kind, floor_material; anchors and items passing through), hand-built and
small, and handed straight to `window.__twin.rebuild` so nothing here
depends on Task 5's code or the store's normalize. Footprints are what
services/twin_model_graph.footprints (Task 1) gives for the joints.

Corners are read from `window.__twin.worldBox` (the bounds the piece
registry records for each piece before static merging; merged meshes keep
no per-piece vertices). Every wall here is axis-aligned, so each wall's box
is its footprint's box, and at an L joint the two boxes share the
footprint's corner vertex.

Library downloads are stubbed: each material's colour map is a flat colour
chosen per asset (wood_floor red, granite_tile blue, red_brick_03 green), so
a material change shows as a pixel colour; every model is a 1 m cube whose
base sits on its origin.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_generator_model_live.py
"""
import base64
import copy
import io
import json
import os
import struct
import sys
import tempfile
import time
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_generator_model_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app  # noqa: E402
import test_twin_view_live as p0view  # noqa: E402  (stub responses and helpers)

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
FT = 0.3048
T = 0.5            # wall thickness
TOL = 0.01         # ft

RED, BLUE, GREEN = (210, 40, 30), (30, 60, 220), (40, 170, 60)
WOOD = {'id': 'wood_floor', 'color': '#a4835f'}          # stub map: red
GRANITE = {'id': 'granite_tile', 'color': '#2e2f31'}     # stub map: blue
BRICK = {'id': 'red_brick_03', 'color': '#8a4a3a'}       # stub map: green; plain siding, no battens
ITEM_ASSET = 'mid_century_lounge_chair'                   # a manifest model


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- stubs

def _cube_gltf():
    """A 1 m cube, x and z in [-0.5, 0.5], y in [0, 1]: its base on its origin."""
    verts = [(x, y, z) for x in (-0.5, 0.5) for y in (0.0, 1.0) for z in (-0.5, 0.5)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    index = [i for a, b, c, d in quads for i in (a, b, c, a, c, d)]
    data = b''.join(struct.pack('<3f', *v) for v in verts) + struct.pack(f'<{len(index)}H', *index)
    return json.dumps({
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'buffers': [{'byteLength': len(data),
                     'uri': 'data:application/octet-stream;base64,' + base64.b64encode(data).decode('ascii')}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 96, 'target': 34962},
                        {'buffer': 0, 'byteOffset': 96, 'byteLength': len(index) * 2, 'target': 34963}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 8, 'type': 'VEC3',
                       'min': [-0.5, 0, -0.5], 'max': [0.5, 1, 0.5]},
                      {'bufferView': 1, 'componentType': 5123, 'count': len(index), 'type': 'SCALAR'}],
    }).encode()


CUBE = _cube_gltf()


def _stub_urlopen(req, timeout=None):
    url = req.full_url
    if url.endswith('.gltf'):
        return p0view._Resp(CUBE)
    if url.endswith('.hdr'):
        return p0view._Resp(p0view._hdr())
    if '_nor_gl_' in url:
        return p0view._Resp(p0view._jpeg((128, 128, 255)))
    if '_diff_' in url:
        for asset, rgb in (('wood_floor', RED), ('granite_tile', BLUE), ('red_brick_03', GREEN)):
            if f'/{asset}/' in url or f'{asset}_diff' in url:
                return p0view._Resp(p0view._jpeg(rgb))
    return p0view._Resp(p0view._jpeg())


# ---------------------------------------------------------------- flat plans

def _building(joints, walls, rooms, **extra):
    """walls: [(id, a, b, kind, exterior)], joints: {id: [x, y]} on L1."""
    from services.twin_model_graph import footprints
    shaped = [{'id': wid, 'joints': [a, b], 'kind': kind, 'thickness': 0 if kind == 'separator' else T}
              for wid, a, b, kind, _ in walls]
    fp = footprints({k: list(v) for k, v in joints.items()}, shaped)
    flat = []
    for (wid, a, b, kind, exterior), s in zip(walls, shaped):
        w = {'id': wid, 'level': 'L1', 'from': list(joints[a]), 'to': list(joints[b]),
             'joints': [a, b], 'kind': kind, 'thickness': s['thickness'], 'height': 9,
             'exterior': exterior}
        if wid in fp:
            w['footprint'] = fp[wid]
        flat.append(w)
    b = {'id': 'house', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
         'materials': {},
         'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9}],
         'walls': flat, 'openings': [], 'stairs': [],
         'rooms': [{'id': rid, 'level': 'L1', 'name': name, 'kind': 'room', 'polygon': poly}
                   for rid, name, poly in rooms],
         'roof': {'sections': [], 'extensions': []},
         'lights': [], 'fixtures': [], 'anchors': [], 'items': [], 'proposals': [], 'flags': []}
    b.update(extra)
    return b


def _plan(building):
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {'siding': BRICK},
            'site': {'lot': [[-30, -30], [60, -30], [60, 50], [-30, 50]]},
            'buildings': [building]}


def _l_house():
    # An L: 20 x 10 along the south, 10 x 10 up the west side; CCW, exterior.
    #   f(0,20)--e(10,20)
    #   |          |
    #   |          d(10,10)--c(20,10)
    #   |                     |
    #   a(0,0)---------------b(20,0)
    joints = {'a': [0, 0], 'b': [20, 0], 'c': [20, 10], 'd': [10, 10], 'e': [10, 20], 'f': [0, 20]}
    walls = [(w, w[0], w[1], 'solid', True) for w in ('ab', 'bc', 'cd', 'de', 'ef', 'fa')]
    return _building(joints, walls, [('r-hall', 'Hall', [[0, 0], [20, 0], [20, 10], [10, 10], [10, 20], [0, 20]])])


def _box(width=10, depth=10, **extra):
    # One room r1, width x depth; walls s, e, n, w run CCW (left = inside).
    joints = {'j1': [0, 0], 'j2': [width, 0], 'j3': [width, depth], 'j4': [0, depth]}
    walls = [('s', 'j1', 'j2', 'solid', True), ('e', 'j2', 'j3', 'solid', True),
             ('n', 'j3', 'j4', 'solid', True), ('w', 'j4', 'j1', 'solid', True)]
    return _building(joints, walls, [('r1', 'Kitchen', [[0, 0], [width, 0], [width, depth], [0, depth]])], **extra)


def _two_rooms(divider='solid'):
    # A 20 x 10 box split at x = 10 by `mid` into rA (west) and rB (east).
    joints = {'j1': [0, 0], 'm1': [10, 0], 'j2': [20, 0], 'j3': [20, 10], 'm2': [10, 10], 'j4': [0, 10]}
    walls = [('s1', 'j1', 'm1', 'solid', True), ('s2', 'm1', 'j2', 'solid', True),
             ('e', 'j2', 'j3', 'solid', True), ('n1', 'j3', 'm2', 'solid', True),
             ('n2', 'm2', 'j4', 'solid', True), ('w', 'j4', 'j1', 'solid', True),
             ('mid', 'm1', 'm2', divider, False)]
    return _building(joints, walls, [('rA', 'Kitchen', [[0, 0], [10, 0], [10, 10], [0, 10]]),
                                     ('rB', 'Dining', [[10, 0], [20, 0], [20, 10], [10, 10]])])


# ---------------------------------------------------------------- harness

def _seed():
    from services import twin_library, twin_plan, twin_store
    twin_library._urlopen = _stub_urlopen
    plan = twin_plan.normalize(_plan(_box()))[0]
    twin_store.push_round(plan, 'build')
    return plan


SERVED = None


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(_seed)
    return SERVED


def _open(page, served):
    # The boot is the stage, not the subject: on this dev box about one cold
    # page in eight loses a request to ERR_CONNECTION_RESET or never settles
    # (seen 2026-11-09 with the twin page alone), so a boot gets one reload.
    url = served.url('house/twin?tier=high&test=1')
    try:
        page.goto(url)
        page.wait_for_function('window.__twin && window.__twin.ready === true', timeout=30000)
    except Exception:
        page.goto(url)
        page.wait_for_function('window.__twin && window.__twin.ready === true', timeout=60000)
    time.sleep(1.0)


def _frames(page):
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


def _rebuild(page, plan, show_anchors=None):
    if show_anchors is not None:
        page.evaluate('(on) => { window.__twin.showAnchors = on; }', show_anchors)
    # page.evaluate has no timeout of its own: a rebuild that never settles
    # must fail the scenario, not hang the run.
    done = page.evaluate("""(plan) => Promise.race([
        window.__twin.rebuild(plan).then(() => 'built', e => 'failed: ' + e),
        new Promise(r => setTimeout(() => r('timed out'), 60000))])""", plan)
    check(done == 'built', f'the rebuild {done}')
    page.wait_for_function('window.__twin.ready === true', timeout=60000)
    time.sleep(0.5)
    _frames(page)


def _box_of(page, pid):
    return page.evaluate('(id) => window.__twin.worldBox(id, "house")', pid)


def _sample(png, x, y, r=3):
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert('RGB')
    px = [img.getpixel((int(round(x)) + dx, int(round(y)) + dy)) for dx in range(-r, r + 1) for dy in range(-r, r + 1)]
    return tuple(sum(p[i] for p in px) / len(px) for i in range(3))


def _hue(rgb):
    r, g, b = rgb
    if r > g + 25 and r > b + 25:
        return 'red'
    if b > r + 25 and b > g + 15:
        return 'blue'
    if g > r + 25 and g > b + 25:
        return 'green'
    return 'other'


def _floor_colours(page, points):
    """Colour of the L1 floor at each plan point, seen straight down."""
    page.evaluate("() => { window.__twin.setView('house:L1'); window.__twin.setPlanCamera('house:L1'); }")
    _frames(page)
    coords = [page.evaluate('([x, y]) => window.__twin.screenOfFloor(x, y, "house:L1")', list(p)) for p in points]
    png = page.screenshot()
    return [_sample(png, *c) for c in coords]


def _face_colours(page, pieces):
    """Colour at each wall piece's screen centre from the front (south-west) camera."""
    page.evaluate("() => { window.__twin.setView('ext'); window.__twin.setCamera('front'); }")
    _frames(page)
    coords = [page.evaluate('(id) => window.__twin.screenOf(id, "house")', pid) for pid in pieces]
    png = page.screenshot()
    return [_sample(png, *c) for c in coords]


def _xy_corners(box):
    return [(x, y) for x in (box['min'][0], box['max'][0]) for y in (box['min'][1], box['max'][1])]


def _has_corner(box, point):
    return any(close(x, point[0]) and close(y, point[1]) for x, y in _xy_corners(box))


# ---------------------------------------------------------------- scenarios

def scenario_household_corners_are_closed():
    # The L house stands in for the migrated household (see the report): every
    # wall is drawn from its mitred footprint, and at each L joint the two
    # walls' boxes share the footprint's corner vertex.
    want = {   # footprint boxes, by hand: x0, y0, x1, y1
        'ab': (-0.25, -0.25, 20.25, 0.25), 'bc': (19.75, -0.25, 20.25, 10.25),
        'cd': (9.75, 9.75, 20.25, 10.25), 'de': (9.75, 9.75, 10.25, 20.25),
        'ef': (-0.25, 19.75, 10.25, 20.25), 'fa': (-0.25, -0.25, 0.25, 20.25),
    }
    corners = {   # joint: (the two walls, the vertex they share: outside at convex, inside at concave d)
        'a': ('fa', 'ab', (-0.25, -0.25)), 'b': ('ab', 'bc', (20.25, -0.25)),
        'c': ('bc', 'cd', (20.25, 10.25)), 'd': ('cd', 'de', (9.75, 9.75)),
        'e': ('de', 'ef', (10.25, 20.25)), 'f': ('ef', 'fa', (-0.25, 20.25)),
    }
    plan = _plan(_l_house())
    for w in plan['buildings'][0]['walls']:   # the fixture is what Task 1 gives
        xs, ys = [p[0] for p in w['footprint']], [p[1] for p in w['footprint']]
        check(all(close(a, b, 1e-6) for a, b in zip((min(xs), min(ys), max(xs), max(ys)), want[w['id']])),
              ('fixture footprint', w['id'], w['footprint']))
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _rebuild(page, plan)
        boxes = {wid: _box_of(page, wid) for wid in want}
        for wid, (x0, y0, x1, y1) in want.items():
            box = boxes[wid]
            check(box is not None, f'wall {wid} drew nothing')
            got = (box['min'][0], box['min'][1], box['max'][0], box['max'][1])
            check(all(close(a, b) for a, b in zip(got, (x0, y0, x1, y1))),
                  f'wall {wid} is not its footprint: drawn {got}, footprint {(x0, y0, x1, y1)}')
            check(close(box['min'][2], 0) and close(box['max'][2], 9), f'wall {wid} height {box}')
        for joint, (a, b, vertex) in corners.items():
            check(_has_corner(boxes[a], vertex) and _has_corner(boxes[b], vertex),
                  f'corner {joint}: {a} and {b} do not meet at {vertex}: {boxes[a]} {boxes[b]}')
    check(not p0view._unexpected(s.errors()), s.errors())


def scenario_a_wall_without_a_footprint_keeps_todays_path():
    # Regression guard: the same L with no footprints draws as today, the
    # outside face on the drawn line and the thickness inside it.
    plan = _plan(_l_house())
    for w in plan['buildings'][0]['walls']:
        w.pop('footprint')
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _rebuild(page, plan)
        ab, fa = _box_of(page, 'ab'), _box_of(page, 'fa')
        check(ab and close(ab['min'][1], 0) and close(ab['max'][1], T), f'ab outside face on y = 0: {ab}')
        check(fa and close(fa['min'][0], 0) and close(fa['max'][0], T), f'fa outside face on x = 0: {fa}')


def scenario_separator_draws_nothing():
    plan = _plan(_two_rooms('separator'))
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _rebuild(page, plan)
        ids = page.evaluate('() => window.__twin.pieceIds("house")')
        check('s1' in ids and 'mid' not in ids, f'the separator has no piece: {sorted(ids)}')
        check(_box_of(page, 'mid') is None, f'the separator has no mesh: {_box_of(page, "mid")}')
        page.evaluate("() => window.__twin.setPlanCamera('house:L1')")
        _frames(page)
        x, y = page.evaluate('() => window.__twin.screenOfFloor(10, 5, "house:L1")')
        hit = page.evaluate(f'() => window.__twin.pick({x}, {y})')
        check(not hit or hit.get('pieceId') != 'mid', f'nothing to pick where the separator runs: {hit}')
    check(not p0view._unexpected(s.errors()), s.errors())


def scenario_room_floor_override_changes_only_that_room():
    plan = _plan(_two_rooms('solid'))
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _rebuild(page, plan)
        a0, b0 = _floor_colours(page, [(5, 5), (15, 5)])
        check(_hue(a0) == 'red' and _hue(b0) == 'red', f'both floors start as the kit floor (wood, red): {a0} {b0}')
        plan = copy.deepcopy(plan)
        next(r for r in plan['buildings'][0]['rooms'] if r['id'] == 'rA')['floor_material'] = GRANITE
        _rebuild(page, plan)
        a1, b1 = _floor_colours(page, [(5, 5), (15, 5)])
        check(_hue(a1) == 'blue', f'rA takes its own floor (granite, blue): {a0} -> {a1}')
        check(_hue(b1) == 'red' and all(abs(p - q) <= 12 for p, q in zip(b0, b1)),
              f'rB is untouched: {b0} -> {b1}')
    check(not p0view._unexpected(s.errors()), s.errors())


def scenario_floor_material_cascades_room_level_building():
    # Ruling R17: room over level over building over kit; clearing the room's
    # override returns it to what it inherits.
    base = _plan(_two_rooms('solid'))
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        plan = copy.deepcopy(base)
        plan['buildings'][0]['materials'] = {'floor': GRANITE}
        _rebuild(page, plan)
        got = [_hue(c) for c in _floor_colours(page, [(5, 5), (15, 5)])]
        check(got == ['blue', 'blue'], f'the building floor (granite) is on both rooms: {got}')
        plan['buildings'][0]['levels'][0]['materials'] = {'floor': WOOD}
        _rebuild(page, plan)
        got = [_hue(c) for c in _floor_colours(page, [(5, 5), (15, 5)])]
        check(got == ['red', 'red'], f'the level floor (wood) wins over the building: {got}')
        rooms = plan['buildings'][0]['rooms']
        rooms[0]['floor_material'] = GRANITE
        _rebuild(page, plan)
        got = [_hue(c) for c in _floor_colours(page, [(5, 5), (15, 5)])]
        check(got == ['blue', 'red'], f'the room floor wins over the level, in rA only: {got}')
        rooms[0].pop('floor_material')
        _rebuild(page, plan)
        got = [_hue(c) for c in _floor_colours(page, [(5, 5), (15, 5)])]
        check(got == ['red', 'red'], f'clearing the room returns it to the level floor: {got}')
    check(not p0view._unexpected(s.errors()), s.errors())


def scenario_wall_face_override_paints_only_that_face():
    # s runs west to east, so its right face is the south (outside) face the
    # front camera sees; w is the west wall beside it.
    plan = _plan(_box(20, 12))
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _rebuild(page, plan)
        s0, w0 = _face_colours(page, ['s', 'w'])
        check(_hue(s0) == 'green' and _hue(w0) == 'green', f'both faces start as the siding (brick, green): {s0} {w0}')
        plan = copy.deepcopy(plan)
        next(w for w in plan['buildings'][0]['walls'] if w['id'] == 's')['faces'] = {'right': GRANITE}
        _rebuild(page, plan)
        s1, w1 = _face_colours(page, ['s', 'w'])
        check(_hue(s1) == 'blue', f"s's right face takes its override (granite, blue): {s0} -> {s1}")
        check(_hue(w1) == 'green', f'the west wall keeps the siding: {w0} -> {w1}')
    check(not p0view._unexpected(s.errors()), s.errors())


def scenario_item_sits_on_its_host():
    # A 1 m cube model on the floor of r1 at its centre; the room then grows
    # to 14 ft and the item stays centred (u, v are fractions of the room).
    item = {'id': 'chair1', 'asset': ITEM_ASSET, 'rotation': 0, 'scale': 1,
            'host': {'floor': 'r1', 'u': 0.5, 'v': 0.5}}
    side = 1 / FT
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        for width, centre in ((10, (5, 5)), (14, (7, 5))):
            _rebuild(page, _plan(_box(width, 10, items=[copy.deepcopy(item)])))
            try:
                page.wait_for_function('() => !!window.__twin.worldBox("chair1", "house")', timeout=20000)
            except Exception:
                raise AssertionError(f'the item never drew in a {width} ft room (no piece chair1 after 20 s)')
            box = _box_of(page, 'chair1')
            mid = [(box['min'][i] + box['max'][i]) / 2 for i in (0, 1)]
            check(close(mid[0], centre[0], 0.05) and close(mid[1], centre[1], 0.05),
                  f'the item sits at its host point {centre} in a {width} ft room: {box}')
            check(close(box['min'][2], 0, 0.05), f'the item stands on the floor: {box}')
            check(all(close(box['max'][i] - box['min'][i], side, 0.05) for i in (0, 1, 2)),
                  f'the model is drawn at its size (1 m = {side:.3f} ft): {box}')
    check(not p0view._unexpected(s.errors()), s.errors())


def scenario_anchors_draw_only_when_shown():
    # A switch on s (inside face, 4 ft along, 4 ft up). Hidden by default, a
    # small disc on the face when the editor sets view.showAnchors.
    anchor = {'id': 'sw1', 'kind': 'switch', 'offset': 0, 'device': None,
              'host': {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0}}
    plan = _plan(_box(anchors=[anchor]))
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _rebuild(page, plan)
        check(_box_of(page, 'sw1') is None, f'no anchor disc by default: {_box_of(page, "sw1")}')
        _rebuild(page, plan, show_anchors=True)
        box = _box_of(page, 'sw1')
        check(box is not None, 'the anchor draws when showAnchors is on')
        mid = [(box['min'][i] + box['max'][i]) / 2 for i in range(3)]
        check(close(mid[0], 4, 0.15) and close(mid[2], 4, 0.15) and 0.2 <= abs(mid[1]) <= 0.5,
              f'the disc sits on the face of s at 4 ft along and 4 ft up: {box}')
        check(all(box['max'][i] - box['min'][i] <= 1.0 for i in range(3)), f'the disc is small: {box}')
        _rebuild(page, plan, show_anchors=False)
        check(_box_of(page, 'sw1') is None, 'switching showAnchors off hides it again')
    check(not p0view._unexpected(s.errors()), s.errors())


SCENARIOS = (
    scenario_household_corners_are_closed,
    scenario_a_wall_without_a_footprint_keeps_todays_path,
    scenario_separator_draws_nothing,
    scenario_room_floor_override_changes_only_that_room,
    scenario_floor_material_cascades_room_level_building,
    scenario_wall_face_override_paints_only_that_face,
    scenario_item_sits_on_its_host,
    scenario_anchors_draw_only_when_shown,
)


if __name__ == '__main__':
    only = sys.argv[1:]
    run = [fn for fn in SCENARIOS if not only or fn.__name__ in only]
    failed = []
    for fn in run:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:600])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(run) - len(failed)}/{len(run)} passed')
    sys.exit(1 if failed else 0)
