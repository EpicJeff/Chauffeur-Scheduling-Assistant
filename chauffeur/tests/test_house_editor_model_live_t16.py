"""Placement on the lot in the scene, in real Chromium (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md section 5.6
and section 8.3; plan docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md
Part B Task 16 and Review Focus 5; brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-16-brief.md; Ruling R29 for the file layout).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). On top of it this file seeds, in
process and before the server starts:

- A plot plan drawing on the lot (plot.pdf, one page, 1700 x 2200 px at
  10 px per foot, the lot's front-left corner at (300, 1900) px). It is a
  white page with the lot outline in black and three red marks at lot feet
  (25, 105), (25, 147) and (10, 147), clear of every building, tree and bed.
- Its page role (plot, on the lot), then a plot read through the REAL
  twin_place_reads.read_plot with a stub reader. The stub answers the shape of
  the recorded plot answers (tests/fixtures/twin_reads/plot.json and
  recorded/claude/plot-place.json): scale {a, b, feet}, lot, street_edge,
  buildings. It is built here rather than replayed, so that its frame is the
  household's own lot:
  - scale: from the mark at (25, 105) to the mark at (25, 147), 42.0 ft;
  - lot: the household's site lot corners in the same order; street edge
    [2, 1], so the read's lot frame is the plan's lot frame;
  - plot-1 'house': the main house's ground floor outline, 6 ft east of
    where the house stands;
  - plot-2 'pool house': the pool house's ground floor outline (31 x 22 ft)
    turned 4 degrees about its centre and shifted (-3, -2.5) ft: a snap target
    within 7 degrees of the pool house's own turn;
  - plot-3 'shed': a 10 x 10 ft square at (2..12, 98..108), on open lawn.
- One photo on the lot (yard.png), so Your place shows photo tags.

The pool house stands at 270 degrees on the lot (a quarter turn), which is the
rotated building of Review Focus 5. Scenarios that move a building put it
back at its seeded place first (twin_store.update_model), so each one stands
alone.

Test hooks this task adds to window.__twinEditor (under ?test=1, Part B):
- underlay() -> {source, page, opacity, visible} for the plot plan on the
  ground, or null when there is none;
- lotHandles() -> [{kind: 'move'|'turn', building, at: [x, y], screen: [cx, cy]}]
  for the selected building (and for the building of a fit pause): `at` in lot
  feet on the ground, `screen` the client pixel a person presses;
- lotSuggestions() -> [{id, outline: [[x, y], ...], dashed: true}] for every
  open footprint suggestion drawn in the scene, outline in lot feet.
The selection hook is Task 10's selection() ({kind: 'building', id} for a
building). Everything else is asserted on the stored model and place
(twin_store), the posted requests, the pixels on screen and the visible card.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t16.py
"""
import io
import json
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t16_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
FT = H.FT
POOL = 'pool-house'
MAIN = 'main-house'
STATE = {}

# The plot page: lot feet -> page pixels (y up on the lot, down on the page).
PAGE_SIZE = (1700, 2200)
PX_PER_FT = 10.0
LOT_ORIGIN_PX = (300.0, 1900.0)
MARKS = [(25.0, 105.0), (25.0, 147.0), (10.0, 147.0)]   # red marks on the page, lot feet
MARK_RADIUS_PX = 12                                      # 1.2 ft
SCALE_FEET = 42.0                                        # the read's dimension: mark 0 to mark 1
SHED = [[2.0, 98.0], [12.0, 98.0], [12.0, 108.0], [2.0, 108.0]]   # a 10 x 10 ft square on open lawn
MAIN_SHIFT = (6.0, 0.0)          # plot-1 sits 6 ft east of the main house
POOL_TURN = 4.0                  # plot-2 is the pool house turned 4 degrees ...
POOL_SHIFT = (-3.0, -2.5)        # ... and shifted, so a drop near it snaps on
SNAP_MISS = (0.4, -0.3)          # where the drag lets go: 0.5 ft and 4 degrees off plot-2
CAMERA_HEIGHT = 110.0            # feet above the lot for the building scenarios
TOL = 0.5                        # feet


# --- geometry ------------------------------------------------------------------

def _rot(p, degrees):
    a = math.radians(degrees)
    return [math.cos(a) * p[0] - math.sin(a) * p[1], math.sin(a) * p[0] + math.cos(a) * p[1]]


def _to_lot(p, position, rotation):
    q = _rot(p, rotation)
    return [q[0] + position[0], q[1] + position[1]]


def _centroid(points):
    return [sum(p[i] for p in points) / len(points) for i in (0, 1)]


def _bbox_centre(points):
    return [(min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1)]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _turned(points, degrees, about):
    return [[about[0] + q[0], about[1] + q[1]] for q in (_rot([p[0] - about[0], p[1] - about[1]], degrees) for p in points)]


def _shifted(points, by):
    return [[p[0] + by[0], p[1] + by[1]] for p in points]


def _deg(a):
    return a % 360.0


def _angle_off(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _inside(polygon, p):
    inside = False
    for i in range(len(polygon)):
        (x1, y1), (x2, y2) = polygon[i], polygon[i - 1]
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _segment_distance(p, a, b):
    d = [b[0] - a[0], b[1] - a[1]]
    n = d[0] ** 2 + d[1] ** 2
    t = max(0.0, min(1.0, ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / n)) if n else 0.0
    return _dist(p, [a[0] + t * d[0], a[1] + t * d[1]])


def _boundary_distance(polygon, p):
    return min(_segment_distance(p, polygon[i], polygon[(i + 1) % len(polygon)]) for i in range(len(polygon)))


def _ground_outline(building):
    """The building's lowest level outline, building-local feet."""
    level = min(building['levels'], key=lambda level: level.get('elevation', 0))
    return [list(p) for p in level['outline']]


def _footprint(building):
    """The lowest level outline on the lot (lot feet), as the plot fit uses it."""
    return [_to_lot(p, building.get('position') or [0, 0], building.get('rotation') or 0) for p in _ground_outline(building)]


def _placed(bid):
    """{position, rotation, footprint, walls_box, centre, centres} of a building in the stored flat plan.

    footprint: the lowest level outline on the lot; walls_box: the bounding box of
    every wall, on the lot (the pool house's porch walls reach past its outline);
    centre: the outline's box centre on the lot; centres: that and the walls' box centre."""
    b = H.building(H.flat(), bid)
    position, rotation = b.get('position') or [0, 0], b.get('rotation') or 0
    outline = _ground_outline(b)
    ends = [p for w in b['walls'] for p in (w['from'], w['to'])] or outline
    (x0, x1), (y0, y1) = [(min(p[i] for p in ends), max(p[i] for p in ends)) for i in (0, 1)]
    box = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return {'position': list(position), 'rotation': rotation,
            'footprint': _footprint(b),
            'walls_box': [_to_lot(p, position, rotation) for p in box],
            'centre': _to_lot(_bbox_centre(outline), position, rotation),
            'centres': [_to_lot(_bbox_centre(outline), position, rotation), _to_lot(_bbox_centre(ends), position, rotation)]}


def _corners_match(a, b, tol=TOL):
    return len(a) == len(b) and all(min(_dist(p, q) for q in b) <= tol for p in a)


def _uv(p):
    """Full-page uv of a lot point on the plot page."""
    x = LOT_ORIGIN_PX[0] + p[0] * PX_PER_FT
    y = LOT_ORIGIN_PX[1] - p[1] * PX_PER_FT
    return [round(x / PAGE_SIZE[0], 6), round(y / PAGE_SIZE[1], 6)]


def _page_px(p):
    return [LOT_ORIGIN_PX[0] + p[0] * PX_PER_FT, LOT_ORIGIN_PX[1] - p[1] * PX_PER_FT]


def _matrix_point(matrix, uv):
    """read.matrix (SVG affine, full-page uv -> lot feet) applied to a uv point."""
    a, b, c, d, e, f = matrix
    return [a * uv[0] + c * uv[1] + e, b * uv[0] + d * uv[1] + f]


# --- the seed ----------------------------------------------------------------------

def _plot_pdf(lot):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', PAGE_SIZE, 'white')
    draw = ImageDraw.Draw(image)
    draw.polygon([tuple(_page_px(p)) for p in lot], outline=(0, 0, 0), width=3)
    for p in MARKS:
        x, y = _page_px(p)
        draw.ellipse([x - MARK_RADIUS_PX, y - MARK_RADIUS_PX, x + MARK_RADIUS_PX, y + MARK_RADIUS_PX], fill=(255, 0, 0))
    out = io.BytesIO()
    image.save(out, 'PDF', resolution=200)
    return out.getvalue()


def _photo_png():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (64, 48), (120, 140, 160)).save(out, format='PNG')
    return out.getvalue()


def _seed():
    H.seed()
    from services import twin_place_reads, twin_store
    flat = H.flat()
    lot = [list(p) for p in flat['site']['lot']]
    main, pool = H.building(flat, MAIN), H.building(flat, POOL)
    STATE['seeded'] = {b['id']: {'position': list(b['position']), 'rotation': b['rotation']} for b in (main, pool)}
    pool_footprint = _footprint(pool)
    outlines = {
        'plot-1': _shifted(_footprint(main), MAIN_SHIFT),
        'plot-2': _shifted(_turned(pool_footprint, POOL_TURN, _centroid(pool_footprint)), POOL_SHIFT),
        'plot-3': [list(p) for p in SHED],
    }
    STATE['outlines'] = outlines
    STATE['lot'] = lot
    source = twin_store.save_source('drawing', 'plot.pdf', _plot_pdf(lot), part='lot')
    twin_store.set_page_roles([{'source': source, 'page': 1, 'role': 'plot', 'level': None, 'box': None,
                                'building': 'lot'}])
    fragment = {'scale': {'a': _uv(MARKS[0]), 'b': _uv(MARKS[1]), 'feet': SCALE_FEET},
                'lot': [_uv(p) for p in lot], 'street_edge': [2, 1],
                'buildings': [{'name': 'house', 'outline': [_uv(p) for p in outlines['plot-1']]},
                              {'name': 'pool house', 'outline': [_uv(p) for p in outlines['plot-2']]},
                              {'name': 'shed', 'outline': [_uv(p) for p in outlines['plot-3']]}],
                'confidence': 0.8}
    twin_place_reads.read_plot(reader=lambda kind, images, context, **kw: json.loads(json.dumps(fragment)))
    STATE['plot_source'] = source
    STATE['photo'] = twin_store.save_source('photo', 'yard.png', _photo_png(), part='lot')

    def unflag(model):
        # Ruling R50: a needs-checking roof opens its own card, so the pool house roof's flag is cleared before a click selects the building.
        pool_model = H.building(model, POOL)
        pool_model['flags'] = [f for f in pool_model.get('flags', []) if f.get('block_rect') != [0, 0, 31, 22]]
        return model
    twin_store.update_model(unflag, 'edit', 'Test: the pool house roof has been checked (Ruling R50).')


def _serve():
    """The harness's served app, seeded with the household plus this file's plot read."""
    if 'served' not in H._SERVED:
        from live_app import live_app
        H._SERVED['served'] = live_app(_seed)
    return H._SERVED['served']


def _put(bid):
    """Put a building back at its seeded place on the lot (a direct model round)."""
    from services import twin_store
    want = STATE['seeded'][bid]
    now = _placed(bid)
    if _dist(now['position'], want['position']) < 1e-6 and _angle_off(now['rotation'], want['rotation']) < 1e-6:
        return

    def mutate(model):
        b = H.building(model, bid)
        b['position'] = list(want['position'])
        b['rotation'] = want['rotation']
        return model
    twin_store.update_model(mutate, 'edit', 'Test: put the building back where it was seeded.')


def _facts():
    """The seeded plot read, checked against the store."""
    from services import twin_store
    place = twin_store.place()
    read = (place.get('lot') or {}).get('read')
    check(read is not None, 'the seed made a plot read (place.lot.read)')
    check(read['source'] == STATE['plot_source'] and read['page'] == 1, ('the read is of plot.pdf page 1', read['source'], read['page']))
    check(len(read['lot']) == 4 and all(_dist(p, q) < 0.01 for p, q in zip(read['lot'], STATE['lot'])),
          ('the read lot is the household lot, corner for corner', read['lot'], STATE['lot']))
    suggestions = {s['id']: s for s in read['suggestions']}
    check(sorted(suggestions) == ['plot-1', 'plot-2', 'plot-3'], sorted(suggestions))
    for sid, outline in STATE['outlines'].items():
        check(all(_dist(p, q) < 0.01 for p, q in zip(suggestions[sid]['outline'], outline)), (sid, suggestions[sid]['outline'], outline))
    marks = [_matrix_point(read['matrix'], _uv(p)) for p in MARKS]
    check(all(_dist(m, p) < 0.01 for m, p in zip(marks, MARKS)), ('read.matrix puts the marks where they were drawn', marks))
    check(abs(_dist(marks[0], marks[1]) - SCALE_FEET) < 0.01, 'the scale dimension is 42 ft')
    check(abs(_deg(STATE['seeded'][POOL]['rotation']) - 270) < 1e-6, 'the pool house stands at a quarter turn')
    return {'read': read, 'suggestions': suggestions, 'marks': marks}


# --- page helpers ------------------------------------------------------------------

def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


def _screen(page, x, y, z=0.0):
    """Client pixel of a lot point (feet; z above the ground)."""
    return page.evaluate("""([p, FT]) => {
        const view = window.__twin, camera = view.camera;
        camera.updateMatrixWorld(true);
        const v = camera.position.clone().set(p[0] * FT, p[2] * FT, -p[1] * FT).project(camera);
        const r = view.renderer3.domElement.getBoundingClientRect();
        return [r.left + (v.x + 1) * r.width / 2, r.top + (1 - v.y) * r.height / 2];
    }""", [[x, y, z], FT])


def _ground(page, sx, sy):
    """The lot point (feet) on the ground plane under a client pixel."""
    return page.evaluate("""([sx, sy, FT]) => {
        const view = window.__twin, camera = view.camera;
        camera.updateMatrixWorld(true);
        const r = view.renderer3.domElement.getBoundingClientRect();
        const nx = (sx - r.left) / r.width * 2 - 1, ny = 1 - (sy - r.top) / r.height * 2;
        const near = camera.position.clone().set(nx, ny, -1).unproject(camera);
        const far = camera.position.clone().set(nx, ny, 1).unproject(camera);
        const t = near.y / (near.y - far.y);
        return [(near.x + (far.x - near.x) * t) / FT, -(near.z + (far.z - near.z) * t) / FT];
    }""", [sx, sy, FT])


def _look_down(page, x, y, height):
    """A perspective camera straight above a lot point, looking down."""
    page.evaluate("""([eye, target]) => {
        const view = window.__twin;
        if (view.cameraKind() !== 'perspective') view.setCamera('front');
        view.setCameraState({ position: eye, target });
    }""", [[x * FT, height * FT, -(y - 0.01) * FT], [x * FT, 0, -y * FT]])
    H.settle(page)


def _poll(page, read, until, timeout=5.0):
    """read(), polled (with the page's event loop running) until until(value) holds or the timeout."""
    deadline = time.time() + timeout
    while True:
        value = read()
        if until(value) or time.time() > deadline:
            return value
        page.wait_for_timeout(100)


def _record(page, pattern, method=None):
    """Record the JSON bodies of requests matching a URL pattern; the requests still go through."""
    bodies = []

    def handle(route):
        request = route.request
        if method is None or request.method == method:
            try:
                bodies.append(json.loads(request.post_data or 'null'))
            except ValueError:
                bodies.append(request.post_data)
        route.continue_()
    page.route(pattern, handle)
    return bodies


def _red_marks(page, points, timeout=15.0):
    """Centroids (client pixels) of the red page marks near the expected lot points, or None per mark."""
    from PIL import Image
    deadline = time.time() + timeout
    while True:
        shot = Image.open(io.BytesIO(page.screenshot())).convert('RGB')
        k = shot.width / page.viewport_size['width']
        pixels, found = shot.load(), []
        for p in points:
            sx, sy = _screen(page, p[0], p[1], 0.0)
            ex, ey = _screen(page, p[0] + 4.0, p[1], 0.0)
            reach = max(8.0, math.hypot(ex - sx, ey - sy))        # 4 ft around the expected point
            sum_x = sum_y = count = 0
            for X in range(max(0, int((sx - reach) * k)), min(shot.width, int((sx + reach) * k) + 1)):
                for Y in range(max(0, int((sy - reach) * k)), min(shot.height, int((sy + reach) * k) + 1)):
                    r, g, b = pixels[X, Y]
                    if r >= 120 and r - g >= 60 and r - b >= 60:
                        sum_x += X + 0.5
                        sum_y += Y + 0.5
                        count += 1
            found.append((sum_x / count / k, sum_y / count / k) if count >= 40 else None)
        if all(found) or time.time() > deadline:
            return found
        page.wait_for_timeout(300)


def _measure_marks(page, facts):
    """Measure the plot marks on the ground in the scene; returns their lot points."""
    middle = _bbox_centre(facts['marks'])
    _look_down(page, middle[0], middle[1], 120.0)
    for p in facts['marks']:
        H._on_canvas(page, *_screen(page, p[0], p[1], 0.0))
    centroids = _red_marks(page, facts['marks'])
    check(all(centroids), ('every red mark of the plot page shows on the ground near where the read puts it', centroids))
    return [_ground(page, *c) for c in centroids]


def _check_true_scale(measured, facts):
    for got, want in zip(measured, facts['marks']):
        check(_dist(got, want) <= TOL, ('a plot mark lies where read.matrix maps it, in lot feet', got, want))
    scale = _dist(measured[0], measured[1])
    check(abs(scale - SCALE_FEET) <= TOL,
          ('the plot\'s dimension measured in the scene equals the read\'s 42 ft', round(scale, 2)))
    across = _dist(measured[1], measured[2])
    want = _dist(facts['marks'][1], facts['marks'][2])
    check(abs(across - want) <= TOL, ('and across the page, at the same scale', round(across, 2), round(want, 2)))


def _underlay(page):
    return H.editor_state(page, 'underlay')


def _selection(page, until=None, timeout=3.0):
    return _poll(page, lambda: H.editor_state(page, 'selection'), until or (lambda sel: True), timeout)


def _is_building(bid):
    return lambda sel: bool(sel) and sel.get('kind') == 'building' and sel.get('id') == bid


def _handles(page, bid, timeout=5.0):
    """{'move': handle, 'turn': handle} for a building, from lotHandles()."""
    def read():
        return {h['kind']: h for h in (H.editor_state(page, 'lotHandles') or []) if h.get('building') == bid}
    handles = _poll(page, read, lambda hs: 'move' in hs and 'turn' in hs, timeout)
    check('move' in handles and 'turn' in handles, ('a selected building has a move handle and a turn handle', handles))
    return handles


def _select_building(page, bid, height=CAMERA_HEIGHT):
    """Look straight down on a building in the All floors view and click its roof: the building is selected."""
    centre = _placed(bid)['centre']
    _look_down(page, centre[0], centre[1], height)
    sx, sy = _screen(page, centre[0], centre[1], 0.0)
    H._on_canvas(page, sx, sy)
    page.mouse.click(sx, sy)
    H.settle(page)
    sel = _selection(page, _is_building(bid))
    check(_is_building(bid)(sel), ('a click on the building from above selects the building (Task 10)', sel))
    return _handles(page, bid)


def _handles_now(page, bid):
    """The building's handles if it is still selected, else select it again."""
    handles = {h['kind']: h for h in (H.editor_state(page, 'lotHandles') or []) if h.get('building') == bid}
    return handles if 'move' in handles and 'turn' in handles else _select_building(page, bid)


def _drag(page, path, during=None):
    """A real mouse drag along client pixels; `during()` runs halfway, with the button held."""
    page.mouse.move(*path[0])
    page.mouse.down()
    middle = len(path) // 2
    seen = None
    for i, p in enumerate(path[1:], 1):
        page.mouse.move(*p)
        if during is not None and i == middle:
            H.settle(page)
            seen = during()
    page.mouse.up()
    H.settle(page)
    return seen


def _line(a, b, steps=12):
    return [[a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps] for i in range(steps + 1)]


def _move_on_ground(page, start_px, by_ft, during=None):
    """Drag from a pixel so that the pointer's ground point moves by `by_ft` (lot feet).

    Returns (the ground displacement the pointer really made, what during() saw)."""
    g0 = _ground(page, *start_px)
    end = _screen(page, g0[0] + by_ft[0], g0[1] + by_ft[1], 0.0)
    path = [start_px] + [_screen(page, *p, 0.0) for p in _line(g0, [g0[0] + by_ft[0], g0[1] + by_ft[1]])[1:]]
    path[-1] = end
    seen = _drag(page, path, during)
    g1 = _ground(page, *end)
    return [g1[0] - g0[0], g1[1] - g0[1]], seen


def _wait_model(page, bid, until, timeout=15.0, what=''):
    placed = _poll(page, lambda: _placed(bid), until, timeout)
    check(until(placed), (what or 'the stored building changed', placed))
    return placed


def _ops_of(bodies, name):
    return [b.get('op') for b in bodies if isinstance(b, dict) and isinstance(b.get('op'), dict) and b['op'].get('op') == name]


def _all_floors_view(page, served):
    H.open_editor(page, served)
    H.all_floors(page)


# --- scenarios -------------------------------------------------------------------

def scenario_plot_underlay_is_at_true_scale():
    s = _serve()
    if s is None:
        return
    facts = _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _all_floors_view(page, s)
        under = _poll(page, lambda: _underlay(page), lambda u: bool(u) and u.get('visible'), 10.0)
        check(under and under.get('source') == STATE['plot_source'] and under.get('page') == 1,
              ('the plot page lies on the ground', under))
        check(under.get('visible') is True and abs((under.get('opacity') or 0) - 0.6) < 1e-6,
              ('at 0.6 opacity', under))
        _check_true_scale(_measure_marks(page, facts), facts)
        _no_errors(s)


def scenario_rotated_building_follows_the_pointer():
    # Review Focus 5: the pool house stands at 270 degrees; a drag moves it
    # with the pointer on the ground plane, never along a turned axis.
    s = _serve()
    if s is None:
        return
    _facts()
    _put(POOL)
    before = _placed(POOL)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _all_floors_view(page, s)
        ops = _record(page, '**/api/house/editor/op', 'POST')
        handles = _select_building(page, POOL)
        move = handles['move']
        check(min(_dist(move['at'], c) for c in before['centres']) <= 1.5,
              ("the move handle sits at the building's centre", move['at'], before['centres']))
        turn_at = handles['turn']['at']
        check(_dist(move['at'], turn_at) > 5.0
              and min(_boundary_distance(before['footprint'], turn_at), _boundary_distance(before['walls_box'], turn_at)) <= 1.5,
              ("the turn handle sits on the outline's edge, away from the centre", turn_at, before['footprint']))
        start = move['screen']
        moved, seen = _move_on_ground(page, start, (-10.0, -6.0), during=lambda: {
            'ops': len(ops), 'move': next((h for h in H.editor_state(page, 'lotHandles') or []
                                           if h.get('building') == POOL and h.get('kind') == 'move'), None)})
        check(seen['ops'] == 0, ('nothing is posted while the drag is under way', seen['ops']))
        # Halfway, the pointer's ground point has moved (-5, -3) ft.
        halfway = [move['at'][0] - 5.0, move['at'][1] - 3.0]
        check(seen['move'] is not None and _dist(seen['move']['at'], halfway) <= TOL,
              ('halfway through, the building follows the pointer on the ground, not a turned axis',
               seen['move'], halfway))
        want = [before['position'][0] + moved[0], before['position'][1] + moved[1]]
        after = _wait_model(page, POOL, lambda p: _dist(p['position'], before['position']) > 1.0, what='the drag moved the pool house')
        check(_dist(after['position'], want) <= TOL,
              ('the house lands where the pointer put it, in lot feet', after['position'], want, moved))
        check(_angle_off(after['rotation'], before['rotation']) < 1e-6, ('a move keeps the turn', after['rotation']))
        sent = _ops_of(ops, 'move_building')
        check(len(ops) == 1 and len(sent) == 1 and sent[0].get('building') == POOL
              and _dist(sent[0].get('to') or [1e9, 1e9], want) <= TOL,
              ('one move_building op on release, to the new position', ops))
        drawn = _poll(page, lambda: page.evaluate("() => (window.__twin.plan.buildings.find(b => b.id === 'pool-house') || {}).position"),
                      lambda p: bool(p) and _dist(p, after['position']) < 1e-3)
        check(drawn and _dist(drawn, after['position']) < 1e-3, ('and the scene draws it there', drawn, after['position']))
        _no_errors(s)


def scenario_turn_handle_snaps_to_quarter_turns():
    # The turn handle posts rotate_building, snapped by snapRotation (7 degrees
    # of a quarter turn); the house turns about its centre and stays in place.
    s = _serve()
    if s is None:
        return
    _facts()
    _put(POOL)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _all_floors_view(page, s)
        ops = _record(page, '**/api/house/editor/op', 'POST')
        _select_building(page, POOL)
        for sweep, want in ((-88.0, 180.0), (88.0, 270.0)):
            before = _placed(POOL)
            handles = _handles_now(page, POOL)
            pivot, start = handles['move']['at'], handles['turn']['screen']
            g0 = _ground(page, *start)
            arm = [g0[0] - pivot[0], g0[1] - pivot[1]]
            path = [start] + [_screen(page, *[pivot[i] + _rot(arm, sweep * k / 16)[i] for i in (0, 1)], 0.0) for k in range(1, 17)]
            count = len(ops)
            _drag(page, path)
            after = _wait_model(page, POOL, lambda p: _angle_off(p['rotation'], before['rotation']) > 1.0,
                                what=f'the turn handle turned the pool house by {sweep} degrees')
            check(_angle_off(after['rotation'], want) < 1e-6,
                  (f'{_deg(before["rotation"]) + sweep:.0f} degrees snaps to {want:.0f}', after['rotation']))
            turned = _ops_of(ops[count:], 'rotate_building')
            check(turned and turned[-1].get('building') == POOL and _angle_off(turned[-1].get('rotation', 1e9), want) < 1e-6,
                  ('the turn posts rotate_building with the snapped angle', ops[count:]))
            centre = _handles_now(page, POOL)['move']['at']
            check(_dist(centre, pivot) <= 1.0, ('the house turns about its centre and stays in place', pivot, centre))
        _no_errors(s)


def scenario_building_snaps_to_its_footprint():
    # A drag that lets go within 2 ft and 7 degrees of a footprint suggestion
    # snaps the building onto it; a person can still move it off again.
    s = _serve()
    if s is None:
        return
    facts = _facts()
    _put(POOL)
    target = facts['suggestions']['plot-2']['outline']
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _all_floors_view(page, s)
        ops = _record(page, '**/api/house/editor/op', 'POST')
        before = _placed(POOL)
        handles = _select_building(page, POOL)
        # Let go with the outline's centre 0.5 ft from plot-2's, still at 270 degrees (plot-2 is at 274).
        aim = [_centroid(target)[0] + SNAP_MISS[0] - _centroid(before['footprint'])[0],
               _centroid(target)[1] + SNAP_MISS[1] - _centroid(before['footprint'])[1]]
        moved, _ = _move_on_ground(page, handles['move']['screen'], aim)
        dropped = _shifted(before['footprint'], moved)
        check(max(min(_dist(p, q) for q in target) for p in dropped) < 2.0, ('the drop is within 2 ft of plot-2', dropped, target))
        snapped = _wait_model(page, POOL, lambda p: _dist(p['position'], before['position']) > 1.0, what='the drag moved the pool house')
        check(_corners_match(snapped['footprint'], target, 0.25),
              ('the pool house snaps onto the footprint the plot read found', snapped['footprint'], target))
        check(_angle_off(snapped['rotation'], 270.0 + POOL_TURN) < 0.5, ('it takes the footprint\'s turn too', snapped['rotation']))

        # Move it off: 8 ft east is beyond any snap.
        handles = _handles_now(page, POOL)
        moved, _ = _move_on_ground(page, handles['move']['screen'], (8.0, 0.0))
        off = _wait_model(page, POOL, lambda p: _dist(p['position'], snapped['position']) > 1.0, what='the second drag moved it off')
        want = [snapped['position'][0] + moved[0], snapped['position'][1] + moved[1]]
        check(_dist(off['position'], want) <= TOL, ('a person can still move it off the footprint', off['position'], want))
        check(_angle_off(off['rotation'], snapped['rotation']) < 1e-6 and not _corners_match(off['footprint'], target, 2.0),
              ('it stays where it was let go', off))
        check(_ops_of(ops, 'move_building'), ('the moves are move_building ops', ops))
        _no_errors(s)


def _click_point(outline, avoid, lot):
    """A point 0.3 ft inside an outline's edge, on the edge farthest from the buildings in `avoid`
    (polygons) and from the lot's own edges (which a click would offer as the street)."""
    best = None
    for i in range(len(outline)):
        a, b = outline[i], outline[(i + 1) % len(outline)]
        length = _dist(a, b) or 1.0
        mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
        normal = [-(b[1] - a[1]) / length, (b[0] - a[0]) / length]
        p = [mid[0] + 0.3 * normal[0], mid[1] + 0.3 * normal[1]]
        if not _inside(outline, p):
            p = [mid[0] - 0.3 * normal[0], mid[1] - 0.3 * normal[1]]
        clear = min([(-_boundary_distance(poly, p) if _inside(poly, p) else _boundary_distance(poly, p)) for poly in avoid]
                    + [_boundary_distance(lot, p)])
        if best is None or clear > best[0]:
            best = (clear, p)
    check(best[0] > 2.0, ("a clear point on the suggestion's outline to click", best))
    return best[1]


def _open_suggestion(page, outline):
    avoid = [_placed(MAIN)['walls_box'], _placed(POOL)['walls_box']]
    p = _click_point(outline, avoid, STATE['lot'])
    _look_down(page, p[0], p[1], 70.0)
    sx, sy = _screen(page, p[0], p[1], 0.0)
    H._on_canvas(page, sx, sy)
    page.mouse.click(sx, sy)
    H.settle(page)
    accept = page.get_by_role('button', name='Accept', exact=True)
    dismiss = page.get_by_role('button', name='Dismiss', exact=True)
    accept.wait_for(state='visible', timeout=5000)
    check(accept.count() == 1 and dismiss.count() == 1 and dismiss.is_visible(),
          ('clicking a suggestion opens a card with Accept and Dismiss', accept.count(), dismiss.count()))
    match = page.get_by_label('Match to')
    check(match.count() >= 1 and match.first.is_visible(), 'and Match to building')
    return accept, dismiss, match.first


def _suggestion(sid):
    from services import twin_store
    return next(s for s in twin_store.place()['lot']['read']['suggestions'] if s['id'] == sid)


def _place_building(bid):
    from services import twin_store
    return next((b for b in twin_store.place()['buildings'] if b['id'] == bid), None)


def scenario_suggestion_accept_in_scene():
    # Footprint suggestions draw as dashed outlines; clicking one opens a card
    # with Accept, Match to building and Dismiss, which are today's
    # suggestion endpoints (POST place/plot/suggestions/{id}).
    s = _serve()
    if s is None:
        return
    facts = _facts()
    _put(POOL)
    _put(MAIN)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _all_floors_view(page, s)
        answers = _record(page, '**/api/house/editor/place/plot/suggestions/**', 'POST')
        drawn = _poll(page, lambda: H.editor_state(page, 'lotSuggestions') or [], lambda v: len(v) == 3, 10.0)
        check(sorted(d['id'] for d in drawn) == ['plot-1', 'plot-2', 'plot-3'] and all(d.get('dashed') is True for d in drawn),
              ('the open suggestions draw as dashed outlines', drawn))
        for d in drawn:
            want = facts['suggestions'][d['id']]['outline']
            check(_corners_match(d['outline'], want, 0.01), ('drawn where the read found it', d['id'], d['outline'], want))

        # The shed: Accept as a new building.
        accept, _, _ = _open_suggestion(page, facts['suggestions']['plot-3']['outline'])
        accept.click()
        shed = _poll(page, lambda: _suggestion('plot-3'), lambda v: v['state'] == 'accepted', 10.0)
        check(shed['state'] == 'accepted' and shed['building'], ('Accept answers the suggestion', shed))
        building = _place_building(shed['building'])
        check(building is not None and _corners_match(building['footprint'], facts['suggestions']['plot-3']['outline'], 1e-6)
              and building['footprint_from'] == 'plot', ('a new building on the shed\'s footprint', building))
        check(answers and answers[-1].get('action') == 'accept' and 'building' not in answers[-1]
              and answers[-1].get('read') == facts['read']['id'], ('today\'s accept as a new building', answers))
        drawn = _poll(page, lambda: H.editor_state(page, 'lotSuggestions') or [], lambda v: len(v) == 2)
        check(sorted(d['id'] for d in drawn) == ['plot-1', 'plot-2'], ('an answered suggestion leaves the scene', drawn))

        # The house: Match to Main House, then Accept.
        accept, _, match = _open_suggestion(page, facts['suggestions']['plot-1']['outline'])
        match.select_option(label='Main House')
        accept.click()
        house = _poll(page, lambda: _suggestion('plot-1'), lambda v: v['state'] == 'accepted', 10.0)
        check(house['state'] == 'accepted' and house['building'] == MAIN, ('matched to the main house', house))
        check(_corners_match(_place_building(MAIN)['footprint'], facts['suggestions']['plot-1']['outline'], 1e-6),
              ('the main house takes the footprint', _place_building(MAIN)['footprint']))
        check(answers[-1].get('action') == 'accept' and answers[-1].get('building') == MAIN, answers[-1])
        check(len(_place_building_ids()) == 3, ('matching adds no building', _place_building_ids()))

        # The pool house suggestion: Dismiss.
        _, dismiss, _ = _open_suggestion(page, facts['suggestions']['plot-2']['outline'])
        dismiss.click()
        pool = _poll(page, lambda: _suggestion('plot-2'), lambda v: v['state'] == 'dismissed', 10.0)
        check(pool['state'] == 'dismissed', ('Dismiss answers the suggestion', pool))
        check(answers[-1].get('action') == 'dismiss', answers[-1])
        drawn = _poll(page, lambda: H.editor_state(page, 'lotSuggestions') or [], lambda v: len(v) == 0)
        check(drawn == [], ('no open suggestion is left in the scene', drawn))
        _no_errors(s)


def _place_building_ids():
    from services import twin_store
    return [b['id'] for b in twin_store.place()['buildings']]


def scenario_street_edge_set_in_scene():
    # Clicking a lot edge offers 'This edge is the street', which is today's
    # PUT place/lot/placement with street_edge.
    s = _serve()
    if s is None:
        return
    facts = _facts()
    lot = facts['read']['lot']
    a, b = lot[0], lot[1]                          # edge 0: the east side of the lot
    mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _all_floors_view(page, s)
        sent = _record(page, '**/api/house/editor/place/lot/placement', 'PUT')
        _look_down(page, mid[0] - 10.0, mid[1], 80.0)
        sx, sy = _screen(page, mid[0], mid[1], 0.0)
        H._on_canvas(page, sx, sy)
        page.mouse.click(sx, sy)
        H.settle(page)
        street = page.get_by_role('button', name='This edge is the street', exact=True)
        street.wait_for(state='visible', timeout=5000)
        check(not sent, ('clicking the edge only offers; nothing is saved yet', sent))
        street.click()
        from services import twin_store
        placement = _poll(page, lambda: (twin_store.place()['lot'] or {}).get('placement'),
                          lambda v: bool(v) and sorted(v.get('street_edge') or []) == [0, 1], 10.0)
        check(sent and sorted(sent[-1].get('street_edge') or []) == [0, 1],
              ('the street edge goes through today\'s placement route', sent))
        check(placement and sorted(placement['street_edge']) == [0, 1] and placement['confirmed'] is True,
              ('the clicked edge is the street', placement))
        check(sorted(twin_store.place()['lot']['read']['street_edge']) == [0, 1], 'the read takes the new street')
        _no_errors(s)


def _fit_build(transform):
    return {'id': 'b-fit', 'state': 'paused', 'part': POOL, 'seq': 1, 'events': [], 'cost': 0.1, 'next': None,
            'steps': [{'id': 'fit', 'status': 'paused', 'label': 'Fit Pool House onto the lot'}],
            'pause': {'kind': 'lot_placement', 'step': 'fit', 'why': 'This building has no footprint on the lot yet. Drag it into place.',
                      'transform': transform,
                      'registration': {'scale': 1, 'angle': 0, 'origin_px': [0, 0], 'offset': [0, 0]}}}


def _follow_fit(page, transform):
    answers = []

    def route(r):
        if r.request.method == 'POST':
            answers.append(json.loads(r.request.post_data or '{}'))
            return r.fulfill(status=200, headers={'Content-Type': 'application/json'}, body='{}')
        return r.fulfill(status=200, headers={'Content-Type': 'application/json'}, body=json.dumps(_fit_build(transform)))
    page.route('**/api/house/editor/build/b-fit**', route)
    page.evaluate("() => window.__editor.followBuild('b-fit')")
    page.wait_for_selector('#pause-card', state='visible', timeout=10000)
    H.settle(page)
    return answers


def scenario_fit_pause_shows_the_underlay():
    s = _serve()
    if s is None:
        return
    facts = _facts()
    _put(POOL)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        _follow_fit(page, {'position': list(STATE['seeded'][POOL]['position']), 'rotation': 270})
        under = _poll(page, lambda: _underlay(page), lambda u: bool(u) and u.get('visible'), 10.0)
        check(under and under.get('visible') is True and under.get('source') == STATE['plot_source'],
              ('the plot plan lies under the fit pause', under))
        _check_true_scale(_measure_marks(page, facts), facts)
        check(page.locator('#pause-card').is_visible(), 'the pause is still open')
        _no_errors(s)


def scenario_fit_pause_moves_with_the_handle():
    # The fit step's lot_placement pause uses the same move handle; Looks right
    # answers the pause with where the handle put the building, and no op is posted.
    s = _serve()
    if s is None:
        return
    _facts()
    _put(POOL)
    start = {'position': list(STATE['seeded'][POOL]['position']), 'rotation': 270}
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        ops = _record(page, '**/api/house/editor/op', 'POST')
        _follow_fit(page, start)
        centre = _placed(POOL)['centre']
        _look_down(page, centre[0], centre[1], CAMERA_HEIGHT)
        handles = _handles(page, POOL)
        moved, _ = _move_on_ground(page, handles['move']['screen'], (-5.0, 4.0))
        page.click('#pause-accept')
        page.wait_for_function('() => window.__editor.lastAnswer() !== null', timeout=10000)
        decision = page.evaluate('() => window.__editor.lastAnswer().decision')
        want = [start['position'][0] + moved[0], start['position'][1] + moved[1]]
        check(decision and decision.get('transform') and _dist(decision['transform']['position'], want) <= TOL,
              ('Looks right sends where the handle put the building, in lot feet', decision, want))
        check(_angle_off(decision['transform'].get('rotation', 0), 270) < 1e-6, ('the turn is kept', decision))
        check(not ops, ('a pause answer is not an op', ops))
        check(_dist(_placed(POOL)['position'], start['position']) < 1e-6, 'the stored house waits for the build')
        _no_errors(s)


def scenario_place_map_svg_is_gone():
    # Spec 8.3: the Your place SVG map is retired once its street edge,
    # suggestions and moves live in the scene; the dialog keeps the buildings,
    # uploads and photo tags.
    s = _serve()
    if s is None:
        return
    _facts()
    from services import twin_store
    photo = STATE['photo']
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        page.click('#editor-menu')
        page.click('#editor-manage-sources')
        page.wait_for_selector('#place-view', state='visible', timeout=10000)
        for selector in ('#place-map', '[data-place-footprint]', '[data-place-edge]'):
            check(page.locator(selector).count() == 0, (selector, 'the SVG map and its handlers are gone'))
        for bid in (MAIN, POOL):
            check(page.locator(f'[data-place-building="{bid}"]').is_visible(), (bid, 'every building keeps its card'))
        check(page.locator('[data-place-upload="lot"]').count() == 1 and page.locator(f'[data-place-upload="{POOL}"]').count() == 1,
              'uploads stay')
        tag = page.locator(f'[data-place-photo="{photo}"] [data-place-tag="{POOL}"]')
        check(tag.count() == 1 and tag.get_attribute('aria-pressed') == 'false', 'the photo has its tags')
        tag.click()
        tags = _poll(page, lambda: twin_store.place()['photo_tags'].get(photo) or [], lambda v: POOL in v, 10.0)
        check(sorted(tags) == sorted(['lot', POOL]), ('a photo tag still saves', tags))
        page.set_input_files(f'[data-place-upload="{POOL}"]', files=[{'name': 'porch.png', 'mimeType': 'image/png',
                                                                     'buffer': _photo_png()}])
        added = _poll(page, lambda: [x for x in twin_store.sources() if x['filename'] == 'porch.png'], bool, 30.0)
        check(added and twin_store.place()['photo_tags'].get(added[0]['id']) == [POOL], ('an upload still lands on its building', added))
        _no_errors(s)


SCENARIOS = [
    scenario_plot_underlay_is_at_true_scale,
    scenario_rotated_building_follows_the_pointer,
    scenario_turn_handle_snaps_to_quarter_turns,
    scenario_building_snaps_to_its_footprint,
    scenario_suggestion_accept_in_scene,
    scenario_fit_pause_shows_the_underlay,
    scenario_fit_pause_moves_with_the_handle,
    scenario_place_map_svg_is_gone,
    scenario_street_edge_set_in_scene,       # last: a new street re-frames the read
]


if __name__ == '__main__':
    H.run(SCENARIOS)
