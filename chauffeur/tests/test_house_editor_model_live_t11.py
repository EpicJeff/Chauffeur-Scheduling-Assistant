"""Dragging, snapping and dimensions, in real Chromium (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections 5.3,
5.4 and 6 "Live dragging must run in the browser at frame rate"; plan
docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md Part B
Task 11 and plan rulings P2 (walls, floors, ceilings and hosted items update
live; roofs on release) and P3 (at most 33 ms per drag update on the
household's migrated house in Chromium on the dev GPU); brief
.superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-11-brief.md;
Ruling R29 for the file layout).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). These scenarios work on the MAIN house,
the heavier building (60 walls, 25 rooms), on its main floor L1. It is turned
357.6 degrees on the lot; every helper takes building-local plan feet.

What a drag is here. With a room focused (Task 10), a wall of that room is
selected with a click, then pressed and dragged across its own direction with
a real mouse (spec 5.3: "A wall: drag it across its own direction"; 5.2: the
room's walls "respond directly, with no second mode"). During the drag the
editor previews on a copy of the flat plan and rebuilds only that level
(twin_view.rebuildLevel); on release it posts ONE op through api.op to
/api/house/editor/op: move_wall {building, wall, by} for a wall (Task 8's op;
Task 12's wall handle names the same op).

Observables.
- window.__twinEditor.lastDragFrameMs: the time of the last drag update, in ms
  (brief test hook).
- window.__twin.worldBox(id, building): a piece's box in lot feet. During a
  drag it must follow the preview, so rebuildLevel keeps the scene's piece
  records (pieceBounds) for the rebuilt level current.
- Dimension labels: DOM elements carrying a data-dimension attribute, drawn by
  dimensions.show for the selected piece and kept live during its drag. Each
  label's text holds one length in feet and inches (cards.js feetInches style,
  for example 12'-0"). A distance label sits between the piece and the
  neighbouring wall it measures to; its value is the centre-line distance or
  the clear distance between faces (either is accepted, to the inch). The size
  label reads the wall's length (centre line or clear).
- The typed value goes in through promptInput (#cc-input-modal, its field and
  OK button, from templates/components/control_center.html), never prompt.
- The stored model (H.model()) and the requests the page sends.

Pieces used (main-house, level L1, ids after migration; shapes re-checked in
_facts() against the stored model):
- WALL        wall:738a2cbddd52469a968bac0b57b29ebc, (0, 26.33) to (14.33, 26.33);
              its ends are T joints on the x = 0 and x = 14.33 walls, no openings
- ROOM_A      room:070aa0ca32b94170968a5e2cbf0fcc6f, 14.33 x 12 between y 14.33 and WALL
- ROOM_B      room:6ae35a0dcd044566b9f9956dd1b2b4e3, 14.33 x 9.34 between WALL and y 35.67
- SOUTH_WALL  wall:04dec8d079704999b6ceddac5686d4bd, y = 14.33 (ROOM_A's far wall)
- NORTH_WALL  wall:872e7c2f5f9043d5aff504d2e52443a1, y = 35.67 (ROOM_B's far wall)
- PERF_WALL   wall:27baac0e440145c2aaeab79271823cba, (46.33, 43.42) to (59, 43.42)
- PERF_ROOM   room:b3fc2ad6ea584ed3a9ac77f47983dd61, below PERF_WALL
- PERF_NEXT   room:e7b4abf892a4489ba8142fe31395d15c, above PERF_WALL

The scenarios share one served house and run in order: the frame-rate drag
moves PERF_WALL, the release scenario moves WALL by about 1 ft, and the
dimension scenario reads WALL where it then is. Each reads its starting
geometry from the stored model.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t11.py
"""
import math
import os
import re
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t11_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
B = 'main-house'
FLOOR_KEY = 'main-house:L1'
WALL = 'wall:738a2cbddd52469a968bac0b57b29ebc'
ROOM_A = 'room:070aa0ca32b94170968a5e2cbf0fcc6f'
ROOM_B = 'room:6ae35a0dcd044566b9f9956dd1b2b4e3'
SOUTH_WALL = 'wall:04dec8d079704999b6ceddac5686d4bd'
NORTH_WALL = 'wall:872e7c2f5f9043d5aff504d2e52443a1'
PERF_WALL = 'wall:27baac0e440145c2aaeab79271823cba'
PERF_ROOM = 'room:b3fc2ad6ea584ed3a9ac77f47983dd61'
PERF_NEXT = 'room:e7b4abf892a4489ba8142fe31395d15c'

CAMERA_HEIGHT = 60.0      # about 24 px per ft over the main floor
PRESS_X = 2.5             # where WALL is pressed: clear of its ends and its middle
PERF_PRESS_X = 50.0       # where PERF_WALL is pressed
FRAME_BUDGET_MS = 33.0    # P3
INCH = 1 / 12
POLY_TOL = 0.01          # stored room polygons are rounded to 0.01 ft; joints are exact
AREA_TOL = 0.25          # 0.01 ft of rounding along a 14 ft side, both ways


# --- the stored house ------------------------------------------------------------

def _wall(model, wid):
    return next(w for w in H.building(model, B)['walls'] if w['id'] == wid)


def _room(model, rid):
    return next(r for r in H.building(model, B)['rooms'] if r['id'] == rid)


def _area(polygon):
    return abs(sum(polygon[i - 1][0] * polygon[i][1] - polygon[i][0] * polygon[i - 1][1]
                   for i in range(len(polygon)))) / 2


def _ys(polygon):
    return [p[1] for p in polygon]


def _line(model, wid):
    return H.wall_line(model, B, wid)


def _facts():
    """The pieces and shapes this file relies on, read from the stored model."""
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    b = H.building(model, B)
    rooms = {r['id'] for r in b['rooms']}
    walls = {w['id'] for w in b['walls']}
    for pid in (ROOM_A, ROOM_B, PERF_ROOM, PERF_NEXT):
        check(pid in rooms, f'{pid} survives migration')
    for pid in (WALL, SOUTH_WALL, NORTH_WALL, PERF_WALL):
        check(pid in walls, f'{pid} survives migration')
    (ax, ay), (bx, by) = _line(model, WALL)
    check(abs(ay - by) < 1e-6 and abs(min(ax, bx)) < 1e-6 and abs(max(ax, bx) - 14.33) < 0.01,
          ('WALL runs along plan x from 0 to 14.33', _line(model, WALL)))
    y_south = _line(model, SOUTH_WALL)[0][1]
    y_north = _line(model, NORTH_WALL)[0][1]
    check(abs(y_south - 14.33) < 0.01 and abs(y_north - 35.67) < 0.01, (y_south, y_north))
    check(y_south + 2 < ay < y_north - 2, ('WALL lies between its neighbours', ay))
    check(not any(o.get('wall') == WALL for o in H.building(H.flat(), B)['openings']), 'WALL hosts no opening')
    width = abs(bx - ax)
    for rid, lo, hi in ((ROOM_A, y_south, ay), (ROOM_B, ay, y_north)):
        polygon = _room(model, rid)['polygon']
        check(abs(_area(polygon) - width * (hi - lo)) < AREA_TOL, (rid, 'is the rectangle between its walls', polygon))
    (px, py), (qx, qy) = _line(model, PERF_WALL)
    check(abs(py - qy) < 1e-6, ('PERF_WALL runs along plan x', _line(model, PERF_WALL)))
    rotation = H.building(model, B).get('rotation') or 0
    return {'model': model, 'y': ay, 'x': sorted([ax, bx]), 'width': width, 'y_south': y_south, 'y_north': y_north,
            't_wall': _wall(model, WALL).get('thickness') or 0, 't_south': _wall(model, SOUTH_WALL).get('thickness') or 0,
            't_north': _wall(model, NORTH_WALL).get('thickness') or 0, 'rotation': rotation,
            'names': {rid: _room(model, rid).get('name') for rid in (ROOM_A, ROOM_B)}}


def _wait_model(page, changed, timeout=20.0):
    """Poll the stored model until changed(model) holds; pumps the page's events while waiting."""
    deadline = time.time() + timeout
    while True:
        model = H.model()
        if changed(model):
            return model
        if time.time() > deadline:
            return model
        page.wait_for_timeout(100)


# --- lengths, as people read and type them -----------------------------------------

_FEET_INCHES = re.compile(r'(-?\d+(?:\.\d+)?)\s*(?:\'|ft|feet|foot)\s*-?\s*(?:(\d+(?:\.\d+)?)\s*(?:"|in|inches|inch)?)?', re.I)


def parse_length(text):
    """The first feet-and-inches length in a label's text (11'-0", 11 ft 0 in), in feet; None if none."""
    text = (text or '').replace('′', "'").replace('’', "'").replace('″', '"') \
        .replace('“', '"').replace('”', '"')
    m = _FEET_INCHES.search(text)
    if not m:
        return None
    feet = float(m.group(1))
    return math.copysign(abs(feet) + float(m.group(2) or 0) / 12, feet if feet else 1)


def feet_inches(value):
    inches = round(abs(value) * 12)
    return f"{'-' if value < 0 else ''}{inches // 12}'-{inches % 12}\""


def _reads(value, centre, clear):
    """Which reading a label's value matches to the inch: 'centre', 'clear' or None."""
    if value is None:
        return None
    if abs(value - centre) <= INCH / 2 + 0.005:
        return 'centre'
    if abs(value - clear) <= INCH / 2 + 0.005:
        return 'clear'
    return None


# --- the page ---------------------------------------------------------------------

def _selection(page, until=None, timeout=3.0):
    deadline = time.time() + timeout
    while True:
        sel = H.editor_state(page, 'selection')
        if until is None or until(sel) or time.time() > deadline:
            return sel
        page.wait_for_timeout(50)


def _is(kind, pid):
    return lambda sel: bool(sel) and sel.get('kind') == kind and sel.get('id') == pid


def _watch_requests(page):
    """Every POST the page sends to the op route or the legacy edit route, in order."""
    sent = []

    def on_request(request):
        if request.method != 'POST':
            return
        path = request.url.split('?')[0]
        if path.endswith('api/house/editor/op'):
            try:
                body = request.post_data_json
            except Exception:
                body = request.post_data
            sent.append(('op', body))
        elif path.endswith('api/house/editor/edit'):
            sent.append(('edit', request.post_data))
    page.on('request', on_request)
    return sent


def _floor_view(page, served, x, y):
    H.open_editor(page, served)
    H.choose_floor(page, FLOOR_KEY)
    H.look_down(page, B, x, y, CAMERA_HEIGHT)


def _focus_and_select(page, room, room_point, wall, wall_point):
    """Click a room's floor (focus), then one of its walls (select)."""
    H.click_world(page, *room_point, B)
    sel = _selection(page, _is('room', room))
    check(_is('room', room)(sel), ('a click on the floor focuses the room', room, sel))
    H.click_world(page, *wall_point, B)
    sel = _selection(page, _is('wall', wall))
    check(_is('wall', wall)(sel) and sel.get('room') == room, ('a click on the room\'s wall selects it', wall, sel))


def _press(page, point):
    """Mouse down at a building-local point, which must be on the scene."""
    sx, sy = H.screen_of_world(page, *point, B)
    H._on_canvas(page, sx, sy)
    page.mouse.move(sx, sy)
    page.mouse.down()
    H.settle(page)


def _move(page, point):
    sx, sy = H.screen_of_world(page, *point, B)
    page.mouse.move(sx, sy)
    H.settle(page)


def _centre(page, pid):
    box = page.evaluate('([p, b]) => window.__twin.worldBox(p, b)', [pid, B])
    check(box is not None, f'{pid} is a piece in the scene')
    return [(box['min'][i] + box['max'][i]) / 2 for i in (0, 1)], box


def _to_plan(world_delta, rotation):
    """A lot-feet displacement turned back into the building's plan axes."""
    a = math.radians(rotation)
    dx, dy = world_delta
    return [math.cos(a) * dx + math.sin(a) * dy, -math.sin(a) * dx + math.cos(a) * dy]


def _labels(page):
    """The visible dimension labels: text, value, client centre and the plan point under it."""
    rows = page.evaluate("""(key) => [...document.querySelectorAll('[data-dimension]')].map((node, index) => {
        const r = node.getBoundingClientRect(), style = getComputedStyle(node);
        const shown = r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
            && Number(style.opacity) > 0 && !node.closest('[hidden]');
        const centre = [r.left + r.width / 2, r.top + r.height / 2];
        return { index, text: (node.textContent || '').trim(), shown, centre,
                 plan: shown ? window.__twin.floorAt(centre[0], centre[1], key) : null };
    }).filter(row => row.shown)""", FLOOR_KEY)
    for row in rows:
        row['value'] = parse_length(row['text'])
    return rows


def _between(row, lo, hi, x_range):
    plan = row.get('plan')
    return bool(plan) and lo < plan[1] < hi and x_range[0] - 1 <= plan[0] <= x_range[1] + 1


def _gap_label(rows, lo, hi, x_range, centre, clear):
    """The label between two parallel walls that reads their distance; (row, reading) or (None, None)."""
    for row in rows:
        reading = _reads(row['value'], centre, clear)
        if _between(row, lo, hi, x_range) and reading:
            return row, reading
    return None, None


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


# --- scenarios ----------------------------------------------------------------------

def scenario_drag_preview_is_under_33ms():
    """P3: every drag update on the household's main floor takes at most 33 ms, and it is a real preview."""
    s = H.serve()
    if s is None:
        return
    facts = _facts()
    (x0, y0), (x1, _) = sorted(_line(facts['model'], PERF_WALL))
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s, (x0 + x1) / 2, y0)
        _focus_and_select(page, PERF_ROOM, (52.5, y0 - 5.0, 0.0), PERF_WALL, ((x0 + x1) / 2, y0, 0.0))
        start, _ = _centre(page, PERF_WALL)
        _press(page, (PERF_PRESS_X, y0, 0.0))
        samples = []
        for step in range(1, 13):                       # 12 updates, 3 in each, 3 ft across the wall
            _move(page, (PERF_PRESS_X, y0 + 0.25 * step, 0.0))
            samples.append(H.editor_state(page, 'lastDragFrameMs'))
        moved, _ = _centre(page, PERF_WALL)
        page.mouse.up()
        H.settle(page)
        check(all(isinstance(v, (int, float)) and v > 0 for v in samples),
              ('lastDragFrameMs is a measured time after every drag update', samples))
        check(len(set(samples)) >= len(samples) // 2, ('each update is measured, not one stale value', samples))
        shift = _to_plan([moved[0] - start[0], moved[1] - start[1]], facts['rotation'])
        check(abs(shift[0]) < 0.2 and abs(shift[1] - 3.0) < 0.3,
              ('the preview moved the wall with the pointer, about 3 ft across it', shift))
        worst = max(samples[1:])
        check(worst <= FRAME_BUDGET_MS,
              (f'every drag update after the first stays within {FRAME_BUDGET_MS} ms (P3)', worst, samples))
        check(samples[0] <= 3 * FRAME_BUDGET_MS, ('the first update warms caches but is not a stall', samples[0]))
        _wait_model(page, lambda m: abs(_line(m, PERF_WALL)[0][1] - y0) > 0.5)
        _no_errors(s)


def scenario_release_posts_one_op_and_rooms_rederive():
    """P2 during the drag; on release one move_wall op, and both rooms re-derive around the moved wall."""
    s = H.serve()
    if s is None:
        return
    facts = _facts()
    y0, (xw, xe) = facts['y'], facts['x']
    target = y0 - 1.0                                   # 1 ft toward ROOM_A
    with s.browser(launch_args=H.GPU_ARGS) as page:
        sent = _watch_requests(page)
        _floor_view(page, s, 7.0, y0)
        _focus_and_select(page, ROOM_A, (7.0, facts['y_south'] + 3.0, 0.0), WALL, (PRESS_X, y0, 0.0))
        wall_start, _ = _centre(page, WALL)
        _, a_box = _centre(page, ROOM_A)
        _, b_box = _centre(page, ROOM_B)
        before = H.scene_signature(page)
        _press(page, (PRESS_X, y0, 0.0))
        for step in range(1, 9):
            _move(page, (PRESS_X, y0 - step / 8.0, 0.0))

        # Mid-drag, the mouse still down: nothing is posted, the level previews.
        check(sent == [], ('nothing is posted while the drag is under way', sent))
        wall_now, _ = _centre(page, WALL)
        shift = _to_plan([wall_now[0] - wall_start[0], wall_now[1] - wall_start[1]], facts['rotation'])
        check(abs(shift[0]) < 0.1 and abs(shift[1] + 1.0) < 0.25,
              ('the wall follows the pointer live, about 1 ft toward ROOM_A (P2)', shift))
        preview_y = y0 + shift[1]
        cos_a = math.cos(math.radians(facts['rotation']))
        _, a_now = _centre(page, ROOM_A)
        _, b_now = _centre(page, ROOM_B)
        a_change = (a_now['max'][1] - a_now['min'][1]) - (a_box['max'][1] - a_box['min'][1])
        b_change = (b_now['max'][1] - b_now['min'][1]) - (b_box['max'][1] - b_box['min'][1])
        check(abs(a_change - shift[1] * cos_a) < 0.1 and abs(b_change + shift[1] * cos_a) < 0.1,
              ('both floors follow the wall live: ROOM_A shrinks and ROOM_B grows by the move (P2)', a_change, b_change, shift))
        rows = _labels(page)
        gap = preview_y - facts['y_south']
        label, _ = _gap_label(rows, facts['y_south'], preview_y, facts['x'], gap,
                              gap - (facts['t_south'] + facts['t_wall']) / 2)
        check(label is not None, ('a live label shows the distance to the neighbouring wall during the drag',
                                  gap, [(r['text'], r['plan']) for r in rows]))

        page.mouse.up()
        H.settle(page)
        model = _wait_model(page, lambda m: abs(_line(m, WALL)[0][1] - y0) > 0.25)
        page.wait_for_timeout(500)                      # any second post would have left by now

        ops = [body for kind, body in sent if kind == 'op']
        check(len(ops) == 1 and not [1 for kind, _ in sent if kind == 'edit'],
              ('release posts exactly one op, through the op route', sent))
        op = (ops[0] or {}).get('op') if isinstance(ops[0], dict) else None
        check(isinstance(op, dict) and op.get('op') == 'move_wall' and op.get('wall') == WALL and op.get('building') == B,
              ('the op is move_wall on the dragged wall', ops[0]))

        (ax, ay), (bx, by) = _line(model, WALL)
        check(abs(ay - by) < 1e-6 and abs(min(ax, bx) - xw) < 1e-6 and abs(max(ax, bx) - xe) < 1e-6,
              ('the wall moved across its direction only, its ends sliding along their walls', _line(model, WALL)))
        check(abs(ay - target) < 0.25, ('the stored wall is where it was dropped', ay, target))
        check(abs(ay - preview_y) <= INCH + 1e-6, ('what the preview showed is what is stored', ay, preview_y))

        width = xe - xw
        a_poly, b_poly = _room(model, ROOM_A)['polygon'], _room(model, ROOM_B)['polygon']
        check(abs(max(_ys(a_poly)) - ay) < POLY_TOL and abs(_area(a_poly) - width * (ay - facts['y_south'])) < AREA_TOL,
              ('ROOM_A re-derives to end at the moved wall', a_poly))
        check(abs(min(_ys(b_poly)) - ay) < POLY_TOL and abs(_area(b_poly) - width * (facts['y_north'] - ay)) < AREA_TOL,
              ('ROOM_B re-derives to start at the moved wall', b_poly))
        for rid in (ROOM_A, ROOM_B):
            check(_room(model, rid).get('name') == facts['names'][rid], ('rooms keep their ids and names', rid))

        H.wait_rebuilt(page, before)
        drawn = page.evaluate('([b, r]) => window.__twin.plan.buildings.find(x => x.id === b).rooms.find(x => x.id === r)',
                              [B, ROOM_A])
        check(drawn and abs(max(_ys(drawn['polygon'])) - ay) < POLY_TOL, ('the scene draws the re-derived room', drawn))
        _no_errors(s)


def scenario_dimension_label_click_types_a_value():
    """A selected wall shows its distances and size; clicking a distance asks through promptInput and moves the wall."""
    s = H.serve()
    if s is None:
        return
    facts = _facts()
    y0, x_range = facts['y'], facts['x']
    with s.browser(launch_args=H.GPU_ARGS) as page:
        page.add_init_script('window.__promptCalls = []; window.prompt = (...args) => { window.__promptCalls.push(args.map(String)); return null; };')
        sent = _watch_requests(page)
        _floor_view(page, s, 7.0, y0)
        _focus_and_select(page, ROOM_A, (7.0, facts['y_south'] + 3.0, 0.0), WALL, (PRESS_X, y0, 0.0))

        south_gap, north_gap = y0 - facts['y_south'], facts['y_north'] - y0
        south_clear = south_gap - (facts['t_south'] + facts['t_wall']) / 2
        north_clear = north_gap - (facts['t_north'] + facts['t_wall']) / 2
        deadline, rows, south, north, size = time.time() + 5.0, [], (None, None), (None, None), None
        while time.time() < deadline:
            rows = _labels(page)
            south = _gap_label(rows, facts['y_south'], y0, x_range, south_gap, south_clear)
            north = _gap_label(rows, y0, facts['y_north'], x_range, north_gap, north_clear)
            size = next((r for r in rows if _reads(r['value'], facts['width'], facts['width'] - facts['t_wall'])), None)
            if south[0] and north[0] and size:
                break
            page.wait_for_timeout(100)
        seen = [(r['text'], r['plan']) for r in rows]
        check(south[0] is not None, ('a label between the wall and its southern neighbour reads their distance', south_gap, seen))
        check(north[0] is not None, ('a label between the wall and its northern neighbour reads their distance', north_gap, seen))
        check(size is not None, ('a label reads the wall\'s own length', facts['width'], seen))

        label, reading = south
        typed = label['value'] - 1.0
        page.locator('[data-dimension]').nth(label['index']).click()
        page.wait_for_function("() => { const m = document.getElementById('cc-input-modal');"
                               " return !!m && !m.classList.contains('hidden'); }", timeout=5000)
        page.fill('#cc-input-field', feet_inches(typed))
        page.click('#cc-input-ok-btn')
        model = _wait_model(page, lambda m: abs(_line(m, WALL)[0][1] - y0) > 0.25)
        page.wait_for_timeout(500)

        check(page.evaluate('() => window.__promptCalls.length') == 0, 'the label never calls prompt()')
        ops = [body for kind, body in sent if kind == 'op']
        check(len(ops) == 1 and not [1 for kind, _ in sent if kind == 'edit'],
              ('the typed value posts exactly one op, through the op route', sent))
        op = (ops[0] or {}).get('op') if isinstance(ops[0], dict) else None
        check(isinstance(op, dict) and op.get('op') == 'move_wall' and op.get('wall') == WALL and op.get('building') == B,
              ('the op is move_wall on the selected wall', ops[0]))

        (ax, ay), (bx, by) = _line(model, WALL)
        offset = 0.0 if reading == 'centre' else (facts['t_south'] + facts['t_wall']) / 2
        want = facts['y_south'] + offset + round(typed * 12) / 12
        check(abs(ay - by) < 1e-6 and abs(ay - want) < 0.01,
              ('the wall now stands exactly the typed distance from its neighbour', feet_inches(typed), reading, ay, want))
        a_poly = _room(model, ROOM_A)['polygon']
        check(abs(max(_ys(a_poly)) - ay) < POLY_TOL, ('ROOM_A re-derives to the typed wall', a_poly))
        _no_errors(s)


SCENARIOS = [
    scenario_drag_preview_is_under_33ms,
    scenario_release_posts_one_op_and_rooms_rederive,
    scenario_dimension_label_click_types_a_value,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
