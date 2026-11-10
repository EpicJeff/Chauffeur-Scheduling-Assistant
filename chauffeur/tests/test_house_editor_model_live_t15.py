"""The library of materials and items, in real Chromium (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md section 5.7;
plan docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md
Part B Task 15 and planning ruling P4 (yard plants and furniture); brief
.superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-15-brief.md;
Ruling R17 (a level carries `materials`, between building and room in the
cascade) and R29 (one file per task) in progress.md there; the fixed copy in
global-constraints.md: `{Material name}, from the {building|level|room}` and
`{Material name}, set here`).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). This file renames one room before the
push: the pool house's 'Pool Lounge' becomes 'Family Room', the brief's own
words. The library has no sofa, and the model never invents an asset (spec
section 5.7), so the sofa is the library's lounge chair
(`mid_century_lounge_chair`, the kit's `lounger`).

The panel. `#rail-library` opens `#library-panel`, which has two tab buttons
named `Materials` and `Items`. A material's thumbnail carries
`data-material="<id>"` and an item's carries `data-item="<id>"`, the ids of
GET /api/house/editor/library ({materials: [{id, name, color}], items:
[{id, name, kind}]}). A thumbnail is dragged with a real mouse (press on the
thumbnail, move, release over the scene), which drives pointer and HTML5 drags
alike in Chromium. On a material drop a chooser offers three buttons with the
fixed words `This wall face`, `This room` and `The whole building`.

What is checked after each action: the op the page posted to
/api/house/editor/op (captured from the request), the stored model and flat
view (read in-process), the card's text (`#piece-card`), and for the whole
building the pixels of a face nobody dropped on.

Pieces used (pool-house, level L1, rotation 270 on the lot; ids after migration):
- FAMILY_ROOM   room:5d7de10ca48340ae85c407d22337c6f7 ('Pool Lounge' in the read)
- FRONT_Y0      wall:44b42dc9c06144adbeaeb88ce33b0430, plan (0,0)-(31,0), exterior,
                one piece (no T joints); its outside face is the one away from
                the Family Room
- WEST          wall:17ec2a8dad9e47d0aefbfe143524c1c2, plan (0,22)-(0,0), exterior;
                the scene splits it at the T at y 17.33 (flat id ...~2 for 0..17.33)
Yard (lot feet, +x east, +y north):
- TREE          cmp-tree-1, a composed Pine Medium at (92.7, 6.0); the composer
                regenerates it at the same spot, so a rebuild can be checked
- SHRUB         cmp-shrub-22 at (72.3, 145.0)
- TREE_TARGET   (96, 75): open lawn between the main house and the east lot line
- LAWN          (20, 125): open lawn west of the pool

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t15.py
"""
import io
import json
import math
import os
import sys
import tempfile
import time
import urllib.request

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t15_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
POOL = 'pool-house'
MAIN = 'main-house'
FLOOR_KEY = 'pool-house:L1'
FAMILY_ROOM = 'room:5d7de10ca48340ae85c407d22337c6f7'
FRONT_Y0 = 'wall:44b42dc9c06144adbeaeb88ce33b0430'
WEST = 'wall:17ec2a8dad9e47d0aefbfe143524c1c2'
SOFA = 'mid_century_lounge_chair'
PLANTER = 'planter_box_01'
BRICK = 'red_brick_03'
TREE = 'cmp-tree-1'
SHRUB = 'cmp-shrub-22'
TREE_TARGET = (96.0, 75.0)
LAWN = (20.0, 125.0)
SCOPES = ('This wall face', 'This room', 'The whole building')

# Building-local points (feet; z above the floor).
FAMILY_FLOOR = (8.0, 8.0, 0.0)          # open floor in the Family Room, clear of walls and the stair
FRONT_POINT = (16.9, 0.0, 5.5)          # on FRONT_Y0, between the slider (ends 15.08) and the bifold (starts 18.67)
FRONT_EYE = (16.9, -25.0, 6.5)          # outside, facing FRONT_Y0
WEST_POINT = (0.0, 1.5, 5.5)            # on WEST, clear of its window (y 3.5 to 14.2)
WEST_FACE = (0.0, 16.0, 5.5)            # on WEST's outside face, between the window and the T
CORNER_EYE = (-30.0, -30.0, 10.0)       # outside the corner of FRONT_Y0 and WEST: sees both faces
CORNER_TARGET = (0.0, 0.0, 5.0)
ABOVE = (15.5, 9.0)                     # the camera looks straight down over the Family Room


def _rename(plan):
    for room in H.building(plan, POOL)['rooms']:
        if room['id'] == FAMILY_ROOM:
            room['name'] = 'Family Room'
    return plan


def _serve():
    return H.serve(_rename)


# --- the household, read from the stored model ----------------------------------

def _inside(polygon, p):
    inside = False
    for i in range(len(polygon)):
        (x1, y1), (x2, y2) = polygon[i], polygon[i - 1]
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _by_id(items, pid):
    return next((item for item in items if item.get('id') == pid), None)


def _faces(model):
    """{(building, wall): {side: material}} for every wall face that carries an override."""
    out = {}
    for b in model['buildings']:
        for w in b['walls']:
            faces = {k: v for k, v in (w.get('faces') or {}).items() if v}
            if faces:
                out[(b['id'], w['id'])] = faces
    return out


def _outside_side(model, bid, room_id, wall_id):
    """'left' or 'right' of joints[0] -> joints[1]: the side away from the room."""
    room = _by_id(H.building(model, bid)['rooms'], room_id)
    (ax, ay), (bx, by) = H.wall_line(model, bid, wall_id)
    length = math.hypot(bx - ax, by - ay)
    lx, ly = -(by - ay) / length, (bx - ax) / length
    mid = ((ax + bx) / 2, (ay + by) / 2)
    return 'right' if _inside(room['polygon'], (mid[0] + 0.25 * lx, mid[1] + 0.25 * ly)) else 'left'


def _kit():
    from services import twin_library
    return twin_library.kit('modern_farmhouse')


def _compose(flat):
    """The yard composer as the build runs it (twin_build: modern_farmhouse, seed 1)."""
    from services import twin_compose
    return twin_compose.compose(json.loads(json.dumps(flat)), _kit(), seed=1)[0]


def _planting(plan, pid):
    return _by_id(plan['site'].get('planting') or [], pid)


def _near(p, q, tol):
    return p is not None and q is not None and math.hypot(p[0] - q[0], p[1] - q[1]) <= tol


def _facts():
    """The ids and shapes this file relies on, checked against the migrated house."""
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    pool = H.building(model, POOL)
    room = _by_id(pool['rooms'], FAMILY_ROOM)
    check(room is not None and room['name'] == 'Family Room', ('the renamed room survives migration', room))
    front = _by_id(pool['walls'], FRONT_Y0)
    check(front is not None and front.get('exterior') and H.wall_line(model, POOL, FRONT_Y0) == [[0.0, 0.0], [31.0, 0.0]],
          ('FRONT_Y0 is the exterior wall along plan y 0', front))
    check(_by_id(pool['walls'], WEST) is not None, 'the plan-west wall survives migration')
    check(_outside_side(model, POOL, FAMILY_ROOM, FRONT_Y0) == 'right', 'FRONT_Y0 runs +x, so its outside is its right')
    flat = H.flat()
    tree, shrub = _planting(flat, TREE), _planting(flat, SHRUB)
    check(tree is not None and tree['kind'] == 'tree' and _near(tree['at'], (92.7, 6.0), 0.1), tree)
    check(shrub is not None and shrub['kind'] == 'shrub', shrub)
    # The target is ground the composer keeps a moved tree on (lot, clear of
    # buildings, hardscape and the pool), and the tree is regenerated by a rebuild.
    trial = json.loads(json.dumps(flat))
    trial['site'].setdefault('compose_overrides', {'removed': [], 'moved': {}})['moved'][TREE] = list(TREE_TARGET)
    check(_near((_planting(_compose(trial), TREE) or {}).get('at'), TREE_TARGET, 1e-6),
          'the composer keeps a tree moved to TREE_TARGET (fixture check)')
    site = flat['site']
    blocked = [h['polygon'] for h in site.get('hardscape', [])] + [b['polygon'] for b in site.get('beds', [])] \
        + [site['pool']['polygon']]
    check(_inside(site['lot'], LAWN) and not any(_inside(poly, LAWN) for poly in blocked), 'LAWN is open ground')
    return model


# --- the library and the page ----------------------------------------------------

def _library(served):
    request = urllib.request.Request(served.url('api/house/editor/library'),
                                     headers={'X-Member-Token': H.STATE['token']})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read())
            break
        except urllib.error.HTTPError as exc:
            raise AssertionError(f'GET /api/house/editor/library answered {exc.code}') from None
        except urllib.error.URLError:
            if attempt == 2:
                raise
    check(isinstance(body.get('materials'), list) and isinstance(body.get('items'), list), body)
    return body


def _material(library, mid):
    found = [m for m in library['materials'] if m['id'] == mid]
    check(found, f'{mid} is in the library')
    return {'id': found[0]['id'], 'color': found[0]['color']}


def _names(library, mid):
    return {m['name'] for m in library['materials'] if m['id'] == mid}


def _hex(color):
    color = color.lstrip('#')
    return [int(color[i:i + 2], 16) for i in (0, 2, 4)]


def _far_from(library, color, avoid):
    """A library material (with a unique id) whose colour is farthest from `color`."""
    ids = [m['id'] for m in library['materials']]
    pool = [m for m in library['materials'] if ids.count(m['id']) == 1 and m['id'] not in avoid]
    best = max(pool, key=lambda m: sum((a - b) ** 2 for a, b in zip(_hex(m['color']), _hex(color))))
    return {'id': best['id'], 'color': best['color']}


def _ops(page):
    """Capture every op the page posts to /api/house/editor/op (the body's `op`)."""
    posted = []

    def seen(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('api/house/editor/op'):
            try:
                posted.append((request.post_data_json or {}).get('op'))
            except Exception:
                posted.append(None)
    page.on('request', seen)
    return posted


def _until(read, until, what, timeout=20.0):
    deadline = time.time() + timeout
    while True:
        value = read()
        if until(value):
            return value
        if time.time() > deadline:
            raise AssertionError(f'{what}: never happened; last {json.dumps(value, default=str)[:400]}')
        time.sleep(0.1)


def _selection(page, until=None, timeout=3.0):
    deadline = time.time() + timeout
    while True:
        sel = H.editor_state(page, 'selection')
        if until is None or until(sel) or time.time() > deadline:
            return sel
        page.wait_for_timeout(50)


def _is(kind, pid):
    return lambda sel: bool(sel) and sel.get('kind') == kind and sel.get('id') == pid


def _card_text(page):
    if not page.locator('#piece-card').is_visible():
        return ''
    return ' '.join(page.inner_text('#piece-card').split())


def _clears(page):
    return page.locator('#piece-card button:text-is("Clear")').count()


def _open_library(page, tab):
    if not page.locator('#library-panel').is_visible():
        page.click('#rail-library')
        page.wait_for_selector('#library-panel', state='visible', timeout=10000)
    page.click(f'#library-panel button:text-is("{tab}")')
    H.settle(page)


def _close_library(page):
    """#rail-library toggles the panel; close it so it covers none of the scene."""
    if page.locator('#library-panel').is_visible():
        page.click('#rail-library')
        H.settle(page)


def _drag_thumb(page, selector, sx, sy):
    """Press on a library thumbnail, move over the scene, release at (sx, sy)."""
    thumb = page.locator(selector).first
    thumb.wait_for(state='visible', timeout=10000)
    thumb.scroll_into_view_if_needed()
    box = thumb.bounding_box()
    H._on_canvas(page, sx, sy)
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] / 2 + 6, box['y'] + box['height'] / 2 + 6, steps=2)
    page.mouse.move(sx, sy, steps=16)
    page.mouse.up()
    H.settle(page)


def _choose(page, scope):
    button = page.get_by_role('button', name=scope, exact=True)
    button.wait_for(state='visible', timeout=5000)
    for other in SCOPES:
        check(page.get_by_role('button', name=other, exact=True).is_visible(),
              f'the chooser offers "{other}" on a wall face drop')
    button.click()
    H.settle(page)


def _drag_world(page, start, end):
    """A real mouse drag between two client pixels."""
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] + 4, start[1] + 4, steps=2)
    page.mouse.move(*end, steps=16)
    page.mouse.up()
    H.settle(page)


def _lot_scene(page, eye, target):
    """Point the perspective camera from `eye` at `target` (lot [x, y, z] feet)."""
    page.evaluate("""([eye, target, ft]) => {
        const view = window.__twin, s = p => [p[0] * ft, p[2] * ft, -p[1] * ft];
        if (view.cameraKind() !== 'perspective') view.setCamera('front');
        view.setCameraState({ position: s(eye), target: s(target) });
    }""", [list(eye), list(target), H.FT])
    H.settle(page)


def _lot_down(page, x, y, height):
    _lot_scene(page, (x, y - 0.01, height), (x, y, 0.0))


def _screen_lot(page, x, y, z=0.0):
    return page.evaluate("""([p, ft]) => {
        const view = window.__twin, camera = view.camera;
        camera.updateMatrixWorld(true);
        const v = camera.position.clone().set(p[0] * ft, p[2] * ft, -p[1] * ft).project(camera);
        const r = view.renderer3.domElement.getBoundingClientRect();
        return [r.left + (v.x + 1) * r.width / 2, r.top + (1 - v.y) * r.height / 2];
    }""", [[x, y, z], H.FT])


def _pixels(page, sx, sy, half=4):
    """Mean RGB of a small square of the page around (sx, sy)."""
    from PIL import Image
    clip = {'x': sx - half, 'y': sy - half, 'width': 2 * half + 1, 'height': 2 * half + 1}
    image = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert('RGB')
    data = list(image.getdata())
    return [sum(p[i] for p in data) / len(data) for i in range(3)]


def _floor_view(page, served):
    H.open_editor(page, served)
    H.choose_floor(page, FLOOR_KEY)
    H.look_down(page, POOL, *ABOVE)


def _focus_family_room(page):
    H.look_down(page, POOL, *ABOVE)
    H.click_world(page, *FAMILY_FLOOR, POOL)
    sel = _selection(page, _is('room', FAMILY_ROOM))
    check(_is('room', FAMILY_ROOM)(sel), ('a click on the Family Room floor selects it', sel))


def _select_front_wall(page):
    """Rooms first: focus the Family Room from above, then click FRONT_Y0 from outside."""
    H.press(page, 'Escape')
    H.press(page, 'Escape')
    _focus_family_room(page)
    H.look_at(page, POOL, FRONT_EYE, FRONT_POINT)
    H.click_world(page, *FRONT_POINT, POOL)
    sel = _selection(page, _is('wall', FRONT_Y0))
    check(_is('wall', FRONT_Y0)(sel), ('the front wall is selected', sel))


def _select_west_wall(page):
    H.press(page, 'Escape')
    H.press(page, 'Escape')
    _focus_family_room(page)
    H.click_world(page, *WEST_POINT, POOL)
    sel = _selection(page, lambda v: bool(v) and v.get('kind') == 'wall' and str(v.get('id')).startswith(WEST))
    check(sel and sel.get('kind') == 'wall' and str(sel.get('id')).startswith(WEST), ('the west wall is selected', sel))


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


# --- scenarios ----------------------------------------------------------------------

def scenario_drop_siding_on_one_face_sets_here():
    s = _serve()
    if s is None:
        return
    model = _facts()
    library = _library(s)
    brick = _material(library, BRICK)
    pool = H.building(model, POOL)
    inherited = pool['materials']['siding']
    outside = _outside_side(model, POOL, FAMILY_ROOM, FRONT_Y0)
    before_faces = _faces(model)
    check((POOL, FRONT_Y0) not in before_faces, ('FRONT_Y0 starts with no override', before_faces))
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops(page)
        _floor_view(page, s)
        _select_front_wall(page)
        text = _card_text(page)
        check(any(f'{n}, from the building' in text for n in _names(library, inherited['id'])),
              ('the wall card reads its siding from the building', text, _names(library, inherited['id'])))
        check(_clears(page) == 0, ('nothing is set here, so no Clear', text))

        _open_library(page, 'Materials')
        sx, sy = H.screen_of_world(page, *FRONT_POINT, POOL)
        signature = H.scene_signature(page)
        _drag_thumb(page, f'#library-panel [data-material="{BRICK}"]', sx, sy)
        _choose(page, 'This wall face')
        after = _until(H.model, lambda m: (POOL, FRONT_Y0) in _faces(m), 'the face override reaches the store')

        sets = [op for op in posted if op and op.get('op') == 'set_material']
        check(len(sets) == 1, ('one set_material is posted', posted))
        op = sets[0]
        check(op.get('building') == POOL and str(op['target'].get('wall', '')).startswith(FRONT_Y0)
              and op['target'].get('side') == outside and op.get('material') == brick, op)
        faces = _faces(after)
        check(faces[(POOL, FRONT_Y0)] == {outside: brick}, ('only the outside face is set', faces[(POOL, FRONT_Y0)]))
        check({k: v for k, v in faces.items() if k != (POOL, FRONT_Y0)} == before_faces,
              ('no other face changes', faces, before_faces))
        check(H.building(after, POOL)['materials']['siding'] == inherited, 'the building keeps its siding')
        flat_wall = _by_id(H.building(H.flat(), POOL)['walls'], FRONT_Y0)
        check((flat_wall.get('faces') or {}).get(outside) == brick, ('the flat view the scene draws carries it', flat_wall))

        # The card says it is set here and offers Clear; Clear returns it.
        H.wait_rebuilt(page, signature)
        _close_library(page)
        _select_front_wall(page)
        brick_names = _names(library, BRICK)
        text = _card_text(page)
        check(any(f'{n}, set here' in text for n in brick_names), ('the card reads set here', text, brick_names))
        check(_clears(page) == 1, ('one Clear, for the one face set here', text))
        signature = H.scene_signature(page)
        page.click('#piece-card button:text-is("Clear")')
        cleared = _until(H.model, lambda m: (POOL, FRONT_Y0) not in _faces(m), 'Clear reaches the store')
        check(_faces(cleared) == before_faces, _faces(cleared))
        clears = [op for op in posted if op and op.get('op') == 'set_material' and op.get('material') is None]
        check(len(clears) == 1 and op['target'] == clears[0]['target'], ('Clear posts set_material with null', posted))
        H.wait_rebuilt(page, signature)
        _select_front_wall(page)
        text = _card_text(page)
        check('set here' not in text, ('the card drops "set here"', text))
        check(any(f'{n}, from the building' in text for n in _names(library, inherited['id'])),
              ('cleared, the face inherits again', text))
        check(_clears(page) == 0, text)
        _no_errors(s)


def scenario_whole_building_scope_recolours_all_faces():
    s = _serve()
    if s is None:
        return
    model = _facts()
    library = _library(s)
    pool, main = H.building(model, POOL), H.building(model, MAIN)
    old = pool['materials']['siding']
    chosen = _far_from(library, old['color'], {old['id']})
    before_faces = _faces(model)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops(page)
        H.open_editor(page, s)
        H.choose_floor(page, FLOOR_KEY)
        _open_library(page, 'Materials')
        H.look_at(page, POOL, CORNER_EYE, CORNER_TARGET)
        page.wait_for_timeout(1000)
        face_px = H.screen_of_world(page, *WEST_FACE, POOL)
        H._on_canvas(page, *face_px)
        before_px = _pixels(page, *face_px)

        sx, sy = H.screen_of_world(page, *FRONT_POINT, POOL)
        signature = H.scene_signature(page)
        _drag_thumb(page, f'#library-panel [data-material="{chosen["id"]}"]', sx, sy)
        _choose(page, 'The whole building')
        after = _until(H.model, lambda m: H.building(m, POOL)['materials'].get('siding') == chosen,
                       'the building siding reaches the store')

        sets = [op for op in posted if op and op.get('op') == 'set_material']
        check(len(sets) == 1 and sets[0].get('building') == POOL and sets[0]['target'].get('role') == 'siding'
              and sets[0].get('material') == chosen, ('one building-scope set_material', posted))
        materials = H.building(after, POOL)['materials']
        check({k: v for k, v in materials.items() if k != 'siding'} == {k: v for k, v in pool['materials'].items() if k != 'siding'},
              ('only the siding role changes', materials))
        check(_faces(after) == before_faces, ('inherited, never stamped on a face', _faces(after), before_faces))
        check(H.building(after, MAIN)['materials'] == main['materials'], 'the other building is untouched')
        check(H.building(H.flat(), POOL)['materials']['siding'] == chosen, 'the flat view the scene draws carries it')

        # A face nobody dropped on now looks different.
        H.wait_rebuilt(page, signature)
        H.press(page, 'Escape')
        H.press(page, 'Escape')
        H.look_at(page, POOL, CORNER_EYE, CORNER_TARGET)
        page.wait_for_timeout(1000)
        face_px = H.screen_of_world(page, *WEST_FACE, POOL)
        after_px = _pixels(page, *face_px)
        change = sum(abs(a - b) for a, b in zip(before_px, after_px)) / 3
        check(change > 12, ('the west face is recoloured too', before_px, after_px, chosen))

        # And its card reads the new siding from the building.
        _close_library(page)
        H.choose_floor(page, FLOOR_KEY)
        _select_west_wall(page)
        text = _card_text(page)
        check(any(f'{n}, from the building' in text for n in _names(library, chosen['id'])),
              ('another wall reads the new siding from the building', text))
        check(_clears(page) == 0, text)
        _no_errors(s)


def scenario_card_reads_from_the_building():
    s = _serve()
    if s is None:
        return
    model = _facts()
    library = _library(s)
    pool = H.building(model, POOL)
    siding, floor = pool['materials']['siding'], pool['materials']['floor']
    level_siding = _far_from(library, siding['color'], {siding['id']})
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s)
        _focus_family_room(page)
        text = _card_text(page)
        check(any(f'{n}, from the building' in text for n in _names(library, floor['id'])),
              ('the room card reads its floor from the building', text, _names(library, floor['id'])))
        check(_clears(page) == 0, text)

        _select_west_wall(page)
        text = _card_text(page)
        check(any(f'{n}, from the building' in text for n in _names(library, siding['id'])),
              ('the wall card reads its siding from the building', text, _names(library, siding['id'])))
        check('set here' not in text and _clears(page) == 0, text)

    # A level's material sits between the building and the room (R17).
    from services import twin_store

    def level_material(material):
        def mutate(m):
            level = _by_id(H.building(m, POOL)['levels'], 'L1')
            if material is None:
                level.pop('materials', None)
            else:
                level['materials'] = {'siding': dict(material)}
            return m
        twin_store.update_model(mutate, 'edit', 'test: level siding')

    level_material(level_siding)
    try:
        stored = _by_id(H.building(H.model(), POOL)['levels'], 'L1')
        check((stored.get('materials') or {}).get('siding') == level_siding, ('a level keeps its materials (R17)', stored))
        with s.browser(launch_args=H.GPU_ARGS) as page:
            _floor_view(page, s)
            _select_west_wall(page)
            text = _card_text(page)
            check(any(f'{n}, from the level' in text for n in _names(library, level_siding['id'])),
                  ('the level outranks the building', text, _names(library, level_siding['id'])))
            check(_clears(page) == 0, text)
            _no_errors(s)
    finally:
        level_material(None)


def scenario_drop_sofa_on_the_family_room_floor():
    s = _serve()
    if s is None:
        return
    model = _facts()
    library = _library(s)
    check(any(i['id'] == SOFA for i in library['items']), 'the lounge chair is a library item')
    before = {i['id'] for i in H.building(model, POOL).get('items') or []}
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops(page)
        _floor_view(page, s)
        _open_library(page, 'Items')
        H.look_down(page, POOL, FAMILY_FLOOR[0], FAMILY_FLOOR[1], 60.0)
        sx, sy = H.screen_of_world(page, *FAMILY_FLOOR, POOL)
        _drag_thumb(page, f'#library-panel [data-item="{SOFA}"]', sx, sy)
        after = _until(H.model, lambda m: len(H.building(m, POOL).get('items') or []) > len(before),
                       'the sofa reaches the store')
        added = [i for i in H.building(after, POOL)['items'] if i['id'] not in before]
        check(len(added) == 1 and added[0]['asset'] == SOFA, ('one item, the dropped asset', added))
        item = added[0]
        host = item['host']
        check(host.get('floor') == FAMILY_ROOM, ('hosted on the Family Room floor', host))
        check((item.get('src') or {}).get('person') is True, ('the person placed it', item))
        room = _by_id(H.building(after, POOL)['rooms'], FAMILY_ROOM)
        xs, ys = [p[0] for p in room['polygon']], [p[1] for p in room['polygon']]
        at = (min(xs) + host['u'] * (max(xs) - min(xs)), min(ys) + host['v'] * (max(ys) - min(ys)))
        check(_near(at, FAMILY_FLOOR, 0.75), ('it sits where it was dropped', at, host))
        adds = [op for op in posted if op and op.get('op') == 'add_item']
        check(len(adds) == 1 and adds[0].get('building') == POOL and adds[0].get('asset') == SOFA
              and (adds[0].get('host') or {}).get('floor') == FAMILY_ROOM, ('one add_item is posted', posted))
        check(not [op for op in posted if op and op.get('op') == 'add_site_item'], ('a floor drop is not a yard item', posted))
        _no_errors(s)


def scenario_move_a_yard_tree_and_it_stays_after_rebuild():
    s = _serve()
    if s is None:
        return
    _facts()
    index = next(i for i, p in enumerate(H.flat()['site']['planting']) if p['id'] == TREE)
    tree = H.flat()['site']['planting'][index]
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops(page)
        H.open_editor(page, s)
        H.all_floors(page)
        # Straight above the tree, high enough to see the target: the pixel of
        # the tree's base is its trunk axis, and the ground under it is the base.
        _lot_down(page, tree['at'][0], tree['at'][1], 300.0)
        start = _screen_lot(page, *tree['at'])
        H._on_canvas(page, *start)
        page.mouse.click(*start)
        H.settle(page)
        sel = _selection(page, _is('planting', TREE))
        check(_is('planting', TREE)(sel), ('a click on a yard tree selects it', sel))
        check(_card_text(page), 'the tree has a card')

        end = _screen_lot(page, *TREE_TARGET)
        H._on_canvas(page, *end)
        _drag_world(page, start, end)
        after = _until(H.flat, lambda f: not _near(_planting(f, TREE)['at'], tree['at'], 0.5),
                       'the tree move reaches the store')
        moved = _planting(after, TREE)
        check(_near(moved['at'], TREE_TARGET, 1.0), ('the tree is where it was dropped', moved['at']))
        check(after['site']['planting'][index]['id'] == TREE, 'the tree keeps its place in the list')
        check(_near(after['site']['compose_overrides']['moved'].get(TREE), moved['at'], 1e-6),
              ('the move is recorded for the composer', after['site']['compose_overrides']))
        moves = [op for op in posted if op and op.get('op') == 'move_site_item']
        check(len(moves) == 1 and moves[0].get('list') == 'planting' and moves[0].get('index') == index
              and _near(moves[0].get('at'), moved['at'], 1e-6), ('one move_site_item is posted', posted))
        model_tree = _planting(H.model(), TREE)
        check(_near(model_tree['at'], moved['at'], 1e-6), model_tree)

        # A rebuild of the yard keeps it there.
        rebuilt = _planting(_compose(H.flat()), TREE)
        check(rebuilt is not None and _near(rebuilt['at'], moved['at'], 1e-6), ('the composer keeps the move', rebuilt))

        # So does the page, opened afresh: the tree is drawn and picked at its new spot.
        H.open_editor(page, s)
        H.all_floors(page)
        drawn = page.evaluate('(id) => (window.__twin.plan.site.planting || []).find(p => p.id === id)', TREE)
        check(drawn and _near(drawn['at'], moved['at'], 1e-6), ('the scene draws it at the new spot', drawn))
        _lot_down(page, moved['at'][0], moved['at'][1], 300.0)
        spot = _screen_lot(page, *moved['at'])
        page.mouse.click(*spot)
        H.settle(page)
        sel = _selection(page, _is('planting', TREE))
        check(_is('planting', TREE)(sel), ('the tree answers at its new spot', sel))
        _no_errors(s)


def scenario_drop_a_planter_on_the_lawn_adds_a_site_item():
    # Brief: on the lot ground an item drop posts add_site_item (P4).
    s = _serve()
    if s is None:
        return
    _facts()
    library = _library(s)
    check(any(i['id'] == PLANTER for i in library['items']), 'the planter is a library item')
    before = len(H.flat()['site'].get('furniture') or [])
    items_before = {b['id']: len(b.get('items') or []) for b in H.model()['buildings']}
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops(page)
        H.open_editor(page, s)
        H.all_floors(page)
        _open_library(page, 'Items')
        _lot_down(page, *LAWN, 60.0)
        sx, sy = _screen_lot(page, *LAWN)
        _drag_thumb(page, f'#library-panel [data-item="{PLANTER}"]', sx, sy)
        after = _until(H.flat, lambda f: len(f['site'].get('furniture') or []) > before, 'the planter reaches the store')
        added = after['site']['furniture'][before:]
        check(len(added) == 1 and PLANTER in added[0].values(), ('one yard item carrying the asset', added))
        check(_near(added[0].get('at'), LAWN, 1.0), ('it sits where it was dropped', added[0]))
        check({b['id']: len(b.get('items') or []) for b in H.model()['buildings']} == items_before,
              'no building item is added')
        sites = [op for op in posted if op and op.get('op') == 'add_site_item']
        check(len(sites) == 1 and sites[0].get('list') == 'furniture' and sites[0].get('asset') == PLANTER
              and _near(sites[0].get('at'), LAWN, 1.0), ('one add_site_item is posted', posted))
        check(not [op for op in posted if op and op.get('op') == 'add_item'], posted)
        _no_errors(s)


def scenario_delete_a_yard_shrub_from_its_card():
    # P4: the card's Delete button removes a yard plant, and a rebuild keeps it gone.
    s = _serve()
    if s is None:
        return
    _facts()
    index = next(i for i, p in enumerate(H.flat()['site']['planting']) if p['id'] == SHRUB)
    shrub = H.flat()['site']['planting'][index]
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops(page)
        H.open_editor(page, s)
        H.all_floors(page)
        _lot_down(page, shrub['at'][0], shrub['at'][1], 40.0)
        spot = _screen_lot(page, *shrub['at'])
        H._on_canvas(page, *spot)
        page.mouse.click(*spot)
        H.settle(page)
        sel = _selection(page, _is('planting', SHRUB))
        check(_is('planting', SHRUB)(sel), ('a click on a yard shrub selects it', sel))
        page.click('#piece-card button:text-is("Delete")')
        try:
            page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=3000)
            page.click('#cc-confirm-execute-btn')
        except Exception:
            pass
        after = _until(H.flat, lambda f: _planting(f, SHRUB) is None, 'the delete reaches the store')
        check(SHRUB in after['site']['compose_overrides']['removed'], after['site']['compose_overrides'])
        deletes = [op for op in posted if op and op.get('op') == 'delete_site_item']
        check(len(deletes) == 1 and deletes[0].get('list') == 'planting' and deletes[0].get('index') == index,
              ('one delete_site_item is posted', posted))
        check(_planting(_compose(H.flat()), SHRUB) is None, 'a rebuild of the yard keeps it removed')
        _no_errors(s)


_CONTEXTS = """
(() => {
  const seen = new WeakSet(); window.__glContexts = 0;
  const wrap = proto => {
    if (!proto) return;
    const original = proto.getContext;
    proto.getContext = function (type, ...rest) {
      const context = original.call(this, type, ...rest);
      if (context && /^webgl/.test(String(type)) && !seen.has(this)) { seen.add(this); window.__glContexts += 1; }
      return context;
    };
  };
  wrap(window.HTMLCanvasElement && HTMLCanvasElement.prototype);
  wrap(window.OffscreenCanvas && OffscreenCanvas.prototype);
})();
"""


def scenario_library_panel_shows_thumbnails_from_one_renderer():
    # Brief: tabs Materials and Items; thumbnails rendered in the browser by one
    # shared offscreen renderer, cached in memory; nothing fetched beyond the library.
    s = _serve()
    if s is None:
        return
    _facts()
    library = _library(s)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        page.add_init_script(_CONTEXTS)
        H.open_editor(page, s)
        page.wait_for_timeout(500)
        contexts = page.evaluate('() => window.__glContexts')
        requests = []
        page.on('request', lambda r: requests.append(r.url))

        _open_library(page, 'Materials')
        for m in library['materials']:
            check(page.locator(f'#library-panel [data-material="{m["id"]}"]').count() >= 1, f'a thumbnail for {m["id"]}')
        _open_library(page, 'Items')
        for i in library['items']:
            check(page.locator(f'#library-panel [data-item="{i["id"]}"]').count() >= 1, f'a thumbnail for {i["id"]}')
        page.wait_for_timeout(3000)
        drawn = page.evaluate("""() => [...document.querySelectorAll('#library-panel [data-item]')].map(node => {
            const img = node.querySelector('img'), canvas = node.querySelector('canvas');
            return (img && img.complete && img.naturalWidth > 0) || (canvas && canvas.width > 0);
        })""")
        check(drawn and all(drawn), ('every item thumbnail shows a rendered picture', drawn))
        added = page.evaluate('() => window.__glContexts') - contexts
        check(added <= 1, ('the thumbnails share one renderer', added))

        allowed = ('api/house/editor/library', 'api/house/twin/library/', 'api/house/editor/state')
        strangers = [u for u in requests if not u.startswith(s.url('')) or
                     ('/api/' in u and not any(a in u for a in allowed))]
        check(not strangers, ('nothing is fetched beyond the library', strangers))

        # Browsing again fetches nothing more and makes no new renderer.
        requests.clear()
        _open_library(page, 'Materials')
        _open_library(page, 'Items')
        page.wait_for_timeout(1000)
        refetched = [u for u in requests if 'library' in u]
        check(not refetched, ('thumbnails are cached in memory', refetched))
        check(page.evaluate('() => window.__glContexts') - contexts <= 1, 'still one renderer')
        _no_errors(s)


SCENARIOS = [
    scenario_drop_siding_on_one_face_sets_here,
    scenario_whole_building_scope_recolours_all_faces,
    scenario_card_reads_from_the_building,
    scenario_drop_sofa_on_the_family_room_floor,
    scenario_move_a_yard_tree_and_it_stays_after_rebuild,
    scenario_drop_a_planter_on_the_lawn_adds_a_site_item,
    scenario_delete_a_yard_shrub_from_its_card,
    scenario_library_panel_shows_thumbnails_from_one_renderer,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
