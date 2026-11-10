"""Roof editing in real Chromium: Roof over this, Draw roof area, edges set one
by one, edge handles, dormers (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections 4.4,
5.3 (the roof bullet) and 5.5; plan
docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md Part B
Task 14; brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-14-brief.md; roof shapes in task-3-brief.md; ops in task-9-brief.md;
Rulings R18 (move_roof_edge `by` positive is outward, detach clears `wall`),
R23 (attach only on creation, follow_walls after every op), R24, R29 (file
layout), R30 (selection()).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). Every scenario starts from the seeded
round: _fresh() reverts the store to it (twin_store.revert), so one scenario's
edits never reach the next.

Readings this file pins (see the task 14 tests report):
- `#rail-roof` opens two buttons, `Roof over this` and `Draw roof area`. Add
  dormer is a button named `Add dormer` on the selected roof's card or, failing
  that, a third button in the `#rail-roof` choices; it then takes one click on
  a roof surface.
- "The selected rooms": with a room focused, Shift+click on another room's
  floor on the same level adds that room to the selection (rooms-first ghosting
  does not block a Shift+click). Roof over this then posts roof_over with every
  selected room.
- In the exterior view (All floors, a perspective camera) a click on a roof
  surface selects that roof: selection() = {kind: 'roof', id: <roof id>}. A
  dormer selects as {kind: 'dormer', id: <dormer id>}. _select() allows the
  implementation one drill-down click (building, then roof).
- window.__twinEditor.handles() lists the handles the scene shows for the
  selected piece, each {kind, at: [x, y, z]} with `at` in the building's own
  plan feet and z above the building's base (the harness's convention). Kinds:
  'roof_edge' (one per roof edge), 'dormer_middle' (one) and 'dormer_edge'
  (two, one at each side of the dormer). A handle is drawn over the roofs and
  wins the pick. The test matches a roof_edge handle to its edge by distance to
  the edge's midpoint, so the handle may sit on the area line or the eave.
- A drag follows the pointer on the horizontal plane through the handle. A
  click on a roof_edge handle (no movement) opens the edge card. The edge card
  offers Sloped, Gable and Clipped (buttons, radios or a select's options) and
  a pitch input labelled `Pitch` (typed as x in 12, saved on Enter).
- Draw roof area takes clicks on the active floor's plane (twin_view.floorAt),
  closed by clicking the first point again, as Draw room does (Task 13).
- Looks right on a roof card that shows its roof flags (R14: the model flags
  carrying the v2.499.771 roof.flags text) removes those flags from the model.
- Outcomes are read from the stored model (H.model()) and the flattened view
  (H.flat()): edges by geometry (the side whose line is x or y constant), never
  by index, so a re-ordered area still reads right.
- The wall moves in the detach scenario go through POST /api/house/editor/op
  (move_wall `by` along the wall's left normal, as test_twin_model_ops_walls
  pins), from the page, after the drags.

Pieces used (ids after migration):
- POOL_ROOF   roof:c32cf56375f64ea9aeaa8b82fd39b4a9, pool house, area x 0..31,
              y 0..22, plate 11, level L1; x0/x1 sloped at pitch 11, y0/y1 gable;
              y0 on FRONT_WALL (y 0), y1 on BACK_WALL (y 22).
- G_ROOF      roof:905e3819882643e492a49df73a702172, main house 'left front
              roof', area x 0..14.33, y 14.33..25.33, carrying two roof flags.
- WING_ROOMS  the three L1 rooms of the main house's left wing, x 0..14.33,
              together y 14.33..54.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t14.py
"""
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t14_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
POOL = 'pool-house'
MAIN = 'main-house'
POOL_ROOF = 'roof:c32cf56375f64ea9aeaa8b82fd39b4a9'
FRONT_WALL = 'wall:44b42dc9c06144adbeaeb88ce33b0430'   # pool house, y = 0, x 0..31
BACK_WALL = 'wall:066fd0b4f0044afc972a7a5c39a2f883'    # pool house, y = 22, x 31..0
G_ROOF = 'roof:905e3819882643e492a49df73a702172'
G_FLAGS = ('The left front roof: its left end was not visible in the photos; I made it a gable.',
           'The left front roof: its ridge could not line up with its neighbours; please check its slope.')
H_FLAGS = ('The left rear roof: its left end was not visible in the photos; I made it a gable.',
           'The left rear roof: its ridge could not line up with its neighbours; please check its slope.')
WING_ROOMS = {  # room id -> a building-local floor point (feet) inside it, clear of walls
    'room:070aa0ca32b94170968a5e2cbf0fcc6f': (4.0, 18.0, 0.0),
    'room:6ae35a0dcd044566b9f9956dd1b2b4e3': (4.0, 29.0, 0.0),
    'room:942bc5d1218848bcac98523057e20e11': (4.0, 40.0, 0.0),
}
WING_BOX = (0.0, 14.333, 14.333, 54.0)   # x0, y0, x1, y1 of the wing's three rooms together

# Points on roof surfaces (building-local feet; z on the surface).
POOL_ROOF_POINT = (8.0, 11.0, 18.33)     # the pool roof's x0 slope: 11 + 8 * 11/12
POOL_ROOF_X1_POINT = (23.0, 11.0, 18.33)  # the x1 slope: 11 + (31 - 23) * 11/12
G_ROOF_POINT = (7.17, 18.5, 12.78)        # G's y0 slope: 10 + (18.5 - 14.33) * 8/12
NEW_WING_ROOF_POINT = (6.5, 16.0, 13.25)  # the new wing roof (pitch 6, ridge x 7.17) where it stands above G


def _serve():
    # The first boot of a fresh data dir can outrun live_app's 50 s wait on a
    # busy machine; serve() caches only a served app, so one retry is safe
    # (the retry seeds a second, identical round; _fresh() reverts to the first).
    try:
        return H.serve()
    except AssertionError as exc:
        if 'never came up' not in str(exc):
            raise
        return H.serve()


def _fresh():
    """The served app with the store back on the seeded round (or None: no playwright)."""
    s = _serve()
    if s is None:
        return None
    from services import twin_store
    seed = min(r['id'] for r in twin_store.rounds())
    if twin_store.current_id() != seed:
        twin_store.revert(seed)
    return s


# --- the model ------------------------------------------------------------------

def _roof(model, bid, rid):
    return next((r for r in H.building(model, bid).get('roofs') or [] if r['id'] == rid), None)


def _segments(area):
    return [(area[i], area[(i + 1) % len(area)]) for i in range(len(area))]


def _side(roof, side):
    """Index of a rectangle-like roof's edge on a side: 'x0' the vertical edge of
    least x, 'x1' of greatest x, 'y0' / 'y1' the horizontal edges likewise."""
    vertical = side[0] == 'x'
    found = []
    for i, (a, b) in enumerate(_segments(roof['area'])):
        if vertical and abs(a[0] - b[0]) < 1e-6:
            found.append((a[0], i))
        elif not vertical and abs(a[1] - b[1]) < 1e-6:
            found.append((a[1], i))
    check(found, ('the roof has a side', side, roof['area']))
    found.sort()
    return found[0][1] if side.endswith('0') else found[-1][1]


def _line(roof, side):
    """The constant coordinate of a side's edge line (x for x0/x1, y for y0/y1)."""
    a, _ = _segments(roof['area'])[_side(roof, side)]
    return a[0] if side[0] == 'x' else a[1]


def _edge(roof, side):
    return roof['edges'][_side(roof, side)]


def _box(area):
    xs, ys = [p[0] for p in area], [p[1] for p in area]
    return min(xs), min(ys), max(xs), max(ys)


def _near(a, b, tol=0.05):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _section(flat, bid, rid):
    """The one flattened section of a single-rectangle roof (not a dormer's)."""
    found = [s for s in H.building(flat, bid)['roof']['sections']
             if (s.get('roof') or s.get('id')) == rid and not s.get('dormer_of')]
    check(len(found) == 1, ('one flattened section for the roof', rid, found))
    return found[0]


def _dormer_sections(flat, bid, did):
    return [s for s in H.building(flat, bid)['roof']['sections'] if s.get('dormer_of') and s.get('id') == did]


def _side_pitch(section, end):
    return (section.get('pitches') or {}).get(end, section['pitch'])


def _ridge_at(section):
    """Where a gable's ridge stands across the section, from its per-side pitches
    (the eave-plane intersection twin_roof.js draws; twin_roof_derive._ridge)."""
    axis, ends = (1, ('y0', 'y1')) if section['ridge'] == 'x' else (0, ('x0', 'x1'))
    lo, hi = section['rect'][axis], section['rect'][axis + 2]
    a, b = (_side_pitch(section, end) / 12 for end in ends)
    return (a * lo + b * hi) / (a + b)


def _dormer_centre(roof, dormer):
    a, b = _segments(roof['area'])[dormer['edge']]
    length = math.dist(a, b)
    return [a[i] + (b[i] - a[i]) / length * dormer['at'] for i in (0, 1)]


def _wall_y(model, bid, wid):
    (ax, ay), (bx, by) = H.wall_line(model, bid, wid)
    return (ay + by) / 2 if abs(ay - by) < 1e-6 else None


def _until(pred, what, timeout=20.0):
    """Poll the stored model until pred(model) is truthy; return the model."""
    deadline = time.time() + timeout
    model = None
    while time.time() < deadline:
        model = H.model()
        try:
            if pred(model):
                return model
        except (KeyError, IndexError, TypeError, StopIteration):
            pass
        time.sleep(0.2)
    raise AssertionError(f'{what} (timed out)')


def _facts():
    """The pieces this file relies on, checked against the migrated house."""
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    roof = _roof(model, POOL, POOL_ROOF)
    check(roof and _near(_box(roof['area']), (0, 0, 31, 22)) and len(roof['area']) == 4, ('the pool roof', roof))
    check(roof['plate'] == 11 and roof.get('level') == 'L1', roof)
    for side, setting in (('x0', 'sloped'), ('x1', 'sloped'), ('y0', 'gable'), ('y1', 'gable')):
        check(_edge(roof, side)['setting'] == setting, (side, roof['edges']))
    check(_edge(roof, 'x0')['pitch'] == 11 and _edge(roof, 'x1')['pitch'] == 11, roof['edges'])
    check(_edge(roof, 'y0').get('wall') == FRONT_WALL and _edge(roof, 'y1').get('wall') == BACK_WALL,
          ('the pool roof\'s gable edges sit on the front and back walls', roof['edges']))
    front, back = _wall_y(model, POOL, FRONT_WALL), _wall_y(model, POOL, BACK_WALL)
    check(front is not None and abs(front) < 1e-6 and back is not None and abs(back - 22) < 1e-6,
          (H.wall_line(model, POOL, FRONT_WALL), H.wall_line(model, POOL, BACK_WALL)))
    check(not H.building(model, POOL).get('dormers'), 'the pool house has no dormer yet')
    g = _roof(model, MAIN, G_ROOF)
    check(g and _near(_box(g['area']), (0, 14.333, 14.333, 25.333)), ('the left front roof', g))
    texts = [f['text'] for f in H.building(model, MAIN).get('flags') or []]
    for text in G_FLAGS + H_FLAGS:
        check(texts.count(text) == 1, ('the roof flag is a model flag (R14)', text, texts))
    rooms = {r['id']: r for r in H.building(model, MAIN)['rooms']}
    boxes = []
    for rid in WING_ROOMS:
        check(rid in rooms and rooms[rid]['level'] == 'L1', ('a left wing room', rid))
        boxes.append(_box(rooms[rid]['polygon']))
    union = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    check(_near(union, WING_BOX), ('the wing\'s rooms together', union))
    return model


# --- page helpers ---------------------------------------------------------------

def _selection(page, until=None, timeout=3.0):
    deadline = time.time() + timeout
    while True:
        sel = H.editor_state(page, 'selection')
        if until is None or until(sel) or time.time() > deadline:
            return sel
        page.wait_for_timeout(50)


def _is(kind, pid):
    return lambda sel: bool(sel) and sel.get('kind') == kind and sel.get('id') == pid


def _exterior(page):
    """All floors, in a perspective camera that picks roofs."""
    page.click('[data-editor-camera="orbit"]')
    H.settle(page)
    H.all_floors(page)


def _select(page, bid, kind, pid, point):
    """Select a piece by clicking a point on it, looking straight down at it;
    one extra click is allowed for a drill-down (building, then the piece)."""
    for _ in range(3):
        if _is(kind, pid)(_selection(page)):
            return
        H.look_down(page, bid, point[0], point[1], height=point[2] + 45)
        H.click_world(page, *point, bid)
        _selection(page, _is(kind, pid))
    sel = _selection(page)
    check(_is(kind, pid)(sel), (f'a click on the {kind} selects it', pid, sel))


def _handles(page, kind=None):
    handles = H.editor_state(page, 'handles')
    check(isinstance(handles, list), ('__twinEditor.handles() lists the shown handles', handles))
    return [h for h in handles if kind is None or h.get('kind') == kind]


def _edge_handle(page, roof, side):
    """The roof_edge handle of a side: the one nearest that edge's midpoint."""
    handles = _handles(page, 'roof_edge')
    check(len(handles) == len(roof['edges']), ('a selected roof shows a handle on each edge', handles, roof['area']))
    a, b = _segments(roof['area'])[_side(roof, side)]
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    best = min(handles, key=lambda h: math.hypot(h['at'][0] - mid[0], h['at'][1] - mid[1]))
    check(math.hypot(best['at'][0] - mid[0], best['at'][1] - mid[1]) < 2.5, ('a handle at the edge', side, mid, handles))
    return tuple(best['at'])


def _look_at_handle(page, bid, at):
    H.look_down(page, bid, at[0], at[1], height=at[2] + 40)


def _drag(page, bid, start, end, steps=12):
    """A real mouse drag between two building-local points (feet)."""
    sx, sy = H.screen_of_world(page, *start, bid)
    H._on_canvas(page, sx, sy)
    ex, ey = H.screen_of_world(page, *end, bid)
    page.mouse.move(sx, sy)
    page.mouse.down()
    for k in range(1, steps + 1):
        page.mouse.move(sx + (ex - sx) * k / steps, sy + (ey - sy) * k / steps)
    page.mouse.up()
    H.settle(page)


def _edge_card(page):
    card = page.locator('#piece-card')
    card.wait_for(state='visible', timeout=10000)
    words = page.evaluate("""() => [...document.querySelectorAll('#piece-card button, #piece-card option, #piece-card label')]
        .map(node => node.textContent.trim())""")
    for word in ('Sloped', 'Gable', 'Clipped'):
        check(any(w == word or w.startswith(word) for w in words), ('the edge card offers', word, words))
    check(card.get_by_label('Pitch').count() > 0, ('the edge card has a pitch input', card.inner_text()))
    return card


def _choose(page, word):
    card = page.locator('#piece-card')
    for role in ('button', 'radio'):
        found = card.get_by_role(role, name=word, exact=True)
        if found.count():
            if role == 'radio':
                found.first.check()
            else:
                found.first.click()
            return
    found = card.locator('select').filter(has=page.locator('option', has_text=word))
    check(found.count() > 0, ('the edge card offers', word, card.inner_text()))
    found.first.select_option(label=word)


def _type_pitch(page, value):
    field = page.locator('#piece-card').get_by_label('Pitch').first
    field.fill(str(value))
    field.press('Enter')


def _rail_roof(page):
    page.click('#rail-roof')
    for name in ('Roof over this', 'Draw roof area'):
        button = page.get_by_role('button', name=name, exact=True)
        button.first.wait_for(state='visible', timeout=5000)


def _start_add_dormer(page):
    card = page.locator('#piece-card').get_by_role('button', name='Add dormer', exact=True)
    if card.count() and card.first.is_visible():
        card.first.click()
        return
    page.click('#rail-roof')
    page.get_by_role('button', name='Add dormer', exact=True).first.click()


def _op(page, op):
    """POST /api/house/editor/op from the page (the editor's session)."""
    answer = page.evaluate("""async (op) => {
        const r = await fetch(window.chfBase + 'api/house/editor/op', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op})});
        return {status: r.status, body: await r.json().catch(() => null)};
    }""", op)
    check(answer['status'] == 200, ('the op route takes the op', op, answer))
    return answer['body']


def _move_wall_y(page, model, bid, wid, dy):
    """move_wall by `dy` feet in plan y, as `by` along the wall's left normal."""
    (ax, ay), (bx, by_) = H.wall_line(model, bid, wid)
    length = math.hypot(bx - ax, by_ - ay)
    normal = (-(by_ - ay) / length, (bx - ax) / length)
    return _op(page, {'op': 'move_wall', 'building': bid, 'wall': wid, 'by': dy * normal[1]})


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


# --- scenarios -------------------------------------------------------------------

def scenario_roof_over_the_left_wing_then_gable_both_ends():
    """Focus one wing room, Shift+click the other two, Roof over this: one new
    roof over the union of the three, every edge sloped at the defaults. Then
    the two short ends, one edge card each: Gable. The flattened section is a
    gable with its ridge along the wing and both ends gable."""
    s = _fresh()
    if s is None:
        return
    model = _facts()
    before = {r['id'] for r in H.building(model, MAIN)['roofs']}
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        H.choose_floor(page, f'{MAIN}:L1')
        H.look_down(page, MAIN, 7.17, 34.0, height=90)
        first, *others = list(WING_ROOMS.items())
        H.click_world(page, *first[1], MAIN)
        sel = _selection(page, _is('room', first[0]))
        check(_is('room', first[0])(sel), ('a click on the wing room focuses it', sel))
        page.keyboard.down('Shift')
        try:
            for _, point in others:
                H.click_world(page, *point, MAIN)
        finally:
            page.keyboard.up('Shift')
        _rail_roof(page)
        page.get_by_role('button', name='Roof over this', exact=True).first.click()

        model = _until(lambda m: {r['id'] for r in H.building(m, MAIN)['roofs']} - before,
                       'Roof over this adds a roof')
        new = [r for r in H.building(model, MAIN)['roofs'] if r['id'] not in before]
        check(len(new) == 1, ('exactly one new roof', new))
        roof = new[0]
        check(len(roof['area']) == 4 and _near(_box(roof['area']), WING_BOX),
              ('the roof covers the three selected rooms together, not just the focused one', roof['area']))
        check(roof.get('level') == 'L1' and abs(roof['plate'] - 10) < 1e-6 and roof['overhang'] == 1,
              ('on the wing\'s storey at its plate, overhang 1', roof.get('level'), roof['plate'], roof['overhang']))
        check(all(e['setting'] == 'sloped' and e.get('pitch') == 6 for e in roof['edges']),
              ('every edge starts sloped at pitch 6', roof['edges']))

        _exterior(page)
        for side in ('y0', 'y1'):
            _select(page, MAIN, 'roof', roof['id'], NEW_WING_ROOF_POINT)
            roof = _roof(H.model(), MAIN, roof['id'])
            at = _edge_handle(page, roof, side)
            _look_at_handle(page, MAIN, at)
            H.click_world(page, *at, MAIN)
            _edge_card(page)
            _choose(page, 'Gable')
            _until(lambda m: _edge(_roof(m, MAIN, roof['id']), side)['setting'] == 'gable',
                   f'the {side} end becomes a gable')

        roof = _roof(H.model(), MAIN, roof['id'])
        check(_near(_box(roof['area']), WING_BOX), ('setting edges never moves the area', roof['area']))
        for side, setting in (('y0', 'gable'), ('y1', 'gable'), ('x0', 'sloped'), ('x1', 'sloped')):
            check(_edge(roof, side)['setting'] == setting, (side, roof['edges']))
        check(_edge(roof, 'x0').get('pitch') == 6 and _edge(roof, 'x1').get('pitch') == 6, roof['edges'])
        check((roof.get('src') or {}).get('person') is True, ('the person\'s roof', roof.get('src')))
        section = _section(H.flat(), MAIN, roof['id'])
        check(section['kind'] == 'gable' and section['ridge'] == 'y', ('a gable along the wing', section))
        check(_near(section['rect'], list(WING_BOX)), section['rect'])
        check((section.get('ends') or {}).get('y0') == 'gable' and (section.get('ends') or {}).get('y1') == 'gable',
              ('both ends gable', section.get('ends')))
        _no_errors(s)


def scenario_one_side_pitch_differs():
    """The pool roof's x0 edge card takes pitch 14; x1 stays 11. The flattened
    section carries the side pitch, and its ridge stands nearer the steeper x0
    side: (14 * 0 + 11 * 31) / (14 + 11) = 13.64 ft, not the middle 15.5."""
    s = _fresh()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        _exterior(page)
        _select(page, POOL, 'roof', POOL_ROOF, POOL_ROOF_POINT)
        roof = _roof(H.model(), POOL, POOL_ROOF)
        at = _edge_handle(page, roof, 'x0')
        _look_at_handle(page, POOL, at)
        H.click_world(page, *at, POOL)
        _edge_card(page)
        _type_pitch(page, 14)
        model = _until(lambda m: _edge(_roof(m, POOL, POOL_ROOF), 'x0').get('pitch') == 14, 'the x0 edge takes pitch 14')

        roof = _roof(model, POOL, POOL_ROOF)
        check(_edge(roof, 'x0')['setting'] == 'sloped', roof['edges'])
        check(_edge(roof, 'x1')['setting'] == 'sloped' and _edge(roof, 'x1')['pitch'] == 11,
              ('the other side keeps its pitch', roof['edges']))
        check(_edge(roof, 'y0')['setting'] == 'gable' and _edge(roof, 'y1')['setting'] == 'gable', roof['edges'])
        check(_near(_box(roof['area']), (0, 0, 31, 22)), roof['area'])
        section = _section(H.flat(), POOL, POOL_ROOF)
        check(section['kind'] == 'gable' and section['ridge'] == 'y', section)
        check(_side_pitch(section, 'x0') == 14 and _side_pitch(section, 'x1') == 11,
              ('the flattened section carries the side pitch', section.get('pitches'), section.get('pitch')))
        ridge = _ridge_at(section)
        check(abs(ridge - 31 * 11 / 25) < 0.01 and ridge < 15.5,
              ('the ridge moves toward the steeper side', ridge))
        _no_errors(s)


def scenario_dormer_added_reaches_the_main_roof():
    """Add dormer, then a click on the pool roof's x0 slope at y 11: a dormer on
    the x0 edge, centred on the click. Its flattened cross gable runs from the
    eave line x 0 to the main ridge (15.5). With the x1 side set to pitch 4
    the ridge moves to 31 * 4 / 15 = 8.27 ft, and the dormer still reaches it."""
    s = _fresh()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        _exterior(page)
        _select(page, POOL, 'roof', POOL_ROOF, POOL_ROOF_POINT)
        _start_add_dormer(page)
        H.look_down(page, POOL, 6.0, 11.0, height=60)
        H.click_world(page, 6.0, 11.0, 11 + 6.0 * 11 / 12, POOL)
        model = _until(lambda m: H.building(m, POOL).get('dormers'), 'a click on the roof adds a dormer')

        dormers = H.building(model, POOL)['dormers']
        check(len(dormers) == 1, dormers)
        dormer, roof = dormers[0], _roof(model, POOL, POOL_ROOF)
        check(dormer['roof'] == POOL_ROOF and dormer['edge'] == _side(roof, 'x0'),
              ('the dormer sits on the edge whose slope was under the pointer', dormer, roof['area']))
        centre = _dormer_centre(roof, dormer)
        check(_near(centre, [0, 11], 0.15), ('centred where the pointer was, on the eave line', centre))
        width = dormer['width']
        check(width > 0 and 1 <= dormer['pitch'] <= 24, dormer)

        found = _dormer_sections(H.flat(), POOL, dormer['id'])
        check(len(found) == 1, ('one cross gable for the dormer', H.building(H.flat(), POOL)['roof']['sections']))
        section = found[0]
        check(section['kind'] == 'gable' and section['ridge'] == 'x' and abs(section['plate'] - 11) < 1e-6, section)
        check(_near(section['dormer_of'], [0, 0, 31, 22]), section['dormer_of'])
        main = _section(H.flat(), POOL, POOL_ROOF)
        check(_near(section['rect'], [0, centre[1] - width / 2, _ridge_at(main), centre[1] + width / 2]),
              ('the dormer runs from the eave to the main ridge', section['rect'], _ridge_at(main)))

        # Whatever the pitch: the x1 side at 4 moves the ridge, and the dormer follows it.
        _select(page, POOL, 'roof', POOL_ROOF, POOL_ROOF_X1_POINT)
        at = _edge_handle(page, _roof(H.model(), POOL, POOL_ROOF), 'x1')
        _look_at_handle(page, POOL, at)
        H.click_world(page, *at, POOL)
        _edge_card(page)
        _type_pitch(page, 4)
        _until(lambda m: _edge(_roof(m, POOL, POOL_ROOF), 'x1').get('pitch') == 4, 'the x1 edge takes pitch 4')
        main = _section(H.flat(), POOL, POOL_ROOF)
        ridge = _ridge_at(main)
        check(abs(ridge - 31 * 4 / 15) < 0.01, ('the main ridge moved toward x0', ridge))
        section = _dormer_sections(H.flat(), POOL, dormer['id'])[0]
        check(_near(section['rect'], [0, centre[1] - width / 2, ridge, centre[1] + width / 2]),
              ('the dormer reaches the moved ridge', section['rect'], ridge))
        _no_errors(s)


def scenario_dormer_handles_move_and_widen():
    """A selected dormer (4 ft wide on the pool roof's x0 edge, centred at y 11)
    has a middle handle and two edge handles. Dragging the middle 3 ft along
    the eave moves it (centre y 8, width 4); dragging the lower edge 1 ft
    outward widens it to 5 with the other side staying at y 10."""
    s = _fresh()
    if s is None:
        return
    model = _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        edge = _side(_roof(model, POOL, POOL_ROOF), 'x0')
        _op(page, {'op': 'add_dormer', 'building': POOL, 'roof': POOL_ROOF, 'edge': edge, 'at': 11, 'width': 4, 'pitch': 8})
        dormer = H.building(H.model(), POOL)['dormers'][0]
        H.open_editor(page, s)
        _exterior(page)
        # On the dormer's own roof near the eave, where it stands above the main
        # slope: dormer 11 + (2 - 0.8) * 8/12 = 11.8 against main 11 + 0.3 * 11/12.
        _select(page, POOL, 'dormer', dormer['id'], (0.3, 11.8, 11.8))
        middles, edges = _handles(page, 'dormer_middle'), _handles(page, 'dormer_edge')
        check(len(middles) == 1 and len(edges) == 2, ('a selected dormer has a middle and two edge handles', _handles(page)))

        at = tuple(middles[0]['at'])
        _look_at_handle(page, POOL, at)
        _drag(page, POOL, at, (at[0], at[1] - 3.0, at[2]))
        model = _until(lambda m: abs(_dormer_centre(_roof(m, POOL, POOL_ROOF), H.building(m, POOL)['dormers'][0])[1] - 8) < 0.15,
                       'the middle handle moves the dormer along its eave')
        moved = H.building(model, POOL)['dormers'][0]
        check(moved['id'] == dormer['id'] and moved['edge'] == edge and abs(moved['width'] - 4) < 1e-6,
              ('moved, same edge, same width', moved))

        lower = min(_handles(page, 'dormer_edge'), key=lambda h: h['at'][1])
        at = tuple(lower['at'])
        check(abs(at[1] - 6) < 0.3, ('the lower edge handle sits at the dormer\'s side', lower))
        _look_at_handle(page, POOL, at)
        _drag(page, POOL, at, (at[0], at[1] - 1.0, at[2]))
        model = _until(lambda m: abs(H.building(m, POOL)['dormers'][0]['width'] - 5) < 0.2,
                       'the edge handle widens the dormer')
        wide = H.building(model, POOL)['dormers'][0]
        centre = _dormer_centre(_roof(model, POOL, POOL_ROOF), wide)
        check(abs(centre[1] + wide['width'] / 2 - 10) < 0.15 and abs(centre[1] - wide['width'] / 2 - 5) < 0.15,
              ('the dragged side moved and the other side stayed', centre, wide['width']))
        section = _dormer_sections(H.flat(), POOL, dormer['id'])[0]
        check(_near(section['rect'], [0, 5, 15.5, 10], 0.2), ('the cross gable follows', section['rect']))
        _no_errors(s)


def scenario_detached_edge_stops_following_its_wall():
    """The pool roof's back (y1) edge sits on BACK_WALL. A 0.6 ft drag of its
    handle leaves it attached (not more than 1 ft from its wall line); a 3 ft
    drag outward detaches it (R18: its `wall` is cleared). Moving BACK_WALL out
    2 ft then leaves the edge where it was dragged, while moving FRONT_WALL out
    2 ft carries the still-attached front edge with it."""
    s = _fresh()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        _exterior(page)
        _select(page, POOL, 'roof', POOL_ROOF, POOL_ROOF_POINT)

        roof = _roof(H.model(), POOL, POOL_ROOF)
        at = _edge_handle(page, roof, 'y1')
        _look_at_handle(page, POOL, at)
        _drag(page, POOL, at, (at[0], at[1] + 0.6, at[2]))
        page.wait_for_timeout(2000)
        roof = _roof(H.model(), POOL, POOL_ROOF)
        check(_edge(roof, 'y1').get('wall') == BACK_WALL and 21.99 <= _line(roof, 'y1') <= 22.75,
              ('within 1 ft of its wall line the edge stays attached', roof['edges'], roof['area']))

        _select(page, POOL, 'roof', POOL_ROOF, POOL_ROOF_POINT)
        start = _line(roof, 'y1')
        at = _edge_handle(page, roof, 'y1')
        _look_at_handle(page, POOL, at)
        _drag(page, POOL, at, (at[0], at[1] + 3.0, at[2]))
        model = _until(lambda m: not _edge(_roof(m, POOL, POOL_ROOF), 'y1').get('wall'),
                       'dragged more than 1 ft from its wall line, the edge detaches')
        roof = _roof(model, POOL, POOL_ROOF)
        dragged = _line(roof, 'y1')
        check(abs(dragged - (start + 3)) < 0.15, ('the edge moved out with the drag', start, dragged))
        check(_edge(roof, 'y0').get('wall') == FRONT_WALL and abs(_line(roof, 'y0')) < 0.01,
              ('the other edges stay put and attached', roof['edges'], roof['area']))
        check(abs(_line(roof, 'x0')) < 0.01 and abs(_line(roof, 'x1') - 31) < 0.01, roof['area'])

        _move_wall_y(page, model, POOL, BACK_WALL, 2.0)
        model = _until(lambda m: abs(_wall_y(m, POOL, BACK_WALL) - 24) < 1e-6, 'the back wall moves out to y 24')
        roof = _roof(model, POOL, POOL_ROOF)
        check(abs(_line(roof, 'y1') - dragged) < 0.01 and not _edge(roof, 'y1').get('wall'),
              ('a detached edge stays where it was dragged', dragged, roof['area'], roof['edges']))

        _move_wall_y(page, model, POOL, FRONT_WALL, -2.0)
        model = _until(lambda m: abs(_wall_y(m, POOL, FRONT_WALL) + 2) < 1e-6, 'the front wall moves out to y -2')
        roof = _roof(model, POOL, POOL_ROOF)
        check(abs(_line(roof, 'y0') + 2) < 0.01 and _edge(roof, 'y0').get('wall') == FRONT_WALL,
              ('an attached edge still follows its wall', roof['area'], roof['edges']))
        check(abs(_line(roof, 'y1') - dragged) < 0.01, roof['area'])
        _no_errors(s)


def scenario_roof_flags_show_on_the_card_with_looks_right():
    """The left front roof's two v2.499.771 flags show on its card, and only
    its own (not the left rear roof's). Looks right removes them from the
    model; the other roofs' flags and the roof's edges stay."""
    s = _fresh()
    if s is None:
        return
    model = _facts()
    edges = _roof(model, MAIN, G_ROOF)['edges']
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        _exterior(page)
        _select(page, MAIN, 'roof', G_ROOF, G_ROOF_POINT)
        card = page.locator('#piece-card')
        card.wait_for(state='visible', timeout=10000)
        page.wait_for_function("t => document.querySelector('#piece-card').innerText.includes(t)",
                               arg=G_FLAGS[0], timeout=10000)
        text = card.inner_text()
        check(all(t in text for t in G_FLAGS), ('the roof card shows its flags', text))
        check(not any(t in text for t in H_FLAGS), ('and only its own', text))

        card.get_by_role('button', name='Looks right', exact=True).click()
        model = _until(lambda m: not ({f['text'] for f in H.building(m, MAIN).get('flags') or []} & set(G_FLAGS)),
                       'Looks right clears the roof\'s flags')
        texts = [f['text'] for f in H.building(model, MAIN).get('flags') or []]
        check(all(texts.count(t) == 1 for t in H_FLAGS), ('the other roof keeps its flags', texts))
        check(any(t.startswith('The middle upper roof') for t in texts), texts)
        check(_roof(model, MAIN, G_ROOF)['edges'] == edges, ('Looks right changes no edge', _roof(model, MAIN, G_ROOF)['edges']))
        page.wait_for_function("t => !document.querySelector('#piece-card').innerText.includes(t)",
                               arg=G_FLAGS[0], timeout=10000)
        _no_errors(s)


def scenario_draw_roof_area_over_the_porch():
    """Draw roof area on the pool house's main floor: clicks at the porch's four
    corners, closed on the first, give draw_roof with that area; every edge
    starts sloped at pitch 6, overhang 1."""
    s = _fresh()
    if s is None:
        return
    model = _facts()
    before = {r['id'] for r in H.building(model, POOL)['roofs']}
    corners = [(31.0, 0.0), (38.0, 0.0), (38.0, 22.0), (31.0, 22.0)]
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        H.choose_floor(page, f'{POOL}:L1')
        H.look_down(page, POOL, 34.5, 11.0, height=70)
        _rail_roof(page)
        page.get_by_role('button', name='Draw roof area', exact=True).first.click()
        for x, y in corners + corners[:1]:
            H.click_world(page, x, y, 0.0, POOL)
        model = _until(lambda m: {r['id'] for r in H.building(m, POOL)['roofs']} - before, 'Draw roof area adds a roof')
        new = [r for r in H.building(model, POOL)['roofs'] if r['id'] not in before]
        check(len(new) == 1, new)
        roof = new[0]
        got = sorted((round(x, 2), round(y, 2)) for x, y in roof['area'])
        check(got == sorted(corners), ('the drawn area', roof['area']))
        check(all(e['setting'] == 'sloped' and e.get('pitch') == 6 for e in roof['edges']) and roof['overhang'] == 1,
              ('draw_roof defaults', roof['edges'], roof['overhang']))
        check((roof.get('src') or {}).get('person') is True, roof.get('src'))
        _no_errors(s)


SCENARIOS = [
    scenario_roof_over_the_left_wing_then_gable_both_ends,
    scenario_one_side_pitch_differs,
    scenario_dormer_added_reaches_the_main_roof,
    scenario_dormer_handles_move_and_widen,
    scenario_detached_edge_stops_following_its_wall,
    scenario_roof_flags_show_on_the_card_with_looks_right,
    scenario_draw_roof_area_over_the_porch,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
