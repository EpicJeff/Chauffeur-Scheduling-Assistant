"""Handles for walls, corners, rooms, openings and hosted items, in real
Chromium (spec docs/superpowers/specs/2026-11-09-house-connected-model-design.md
section 5.3; plan docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md
Part B Task 12; brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-12-brief.md; Rulings R3 and R16 for the refusals, R29 for the file layout).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). As in Task 10's file, the pool house's
'Pool Lounge' is renamed 'Kitchen' before the push. Every scenario starts by
putting the seeded model back (twin_store.update_model), because a drag that
works changes the stored house for the next scenario.

What each handle must give (the brief, spec 5.3):
- a wall dragged across its direction posts one `move_wall`;
- the dot at a corner of the focused room posts one `move_joint`;
- the focused room's floor dragged posts one `move_room`;
- an opening: the middle posts `move_hosted` along its wall; a left or right
  edge posts `resize_opening` (width and at; the other edge stays put); the
  top or bottom posts `resize_opening` with head or sill;
- an anchor slides on its surface (`move_hosted`), and crossing onto the
  neighbouring wall under the pointer posts `move_hosted` with a new `host`.
The op is read from the request the editor posts to /api/house/editor/op
(body {op}, Task 10's api.op), and the outcome from the stored model.

Refusals (R16, R3; Task 8's copy): a drag that would make a wall cross another
shows 'That would cross another wall.'; a drag that would shrink a wall below
its door plus half a foot clear each side shows 'That would leave the door
narrower than its wall.'. Both through showGlobalAlert (#cc-alert-message),
and the stored house does not change.

Drags are made with a real mouse: press, move in steps, release. Distances are
pinned loosely where the drag plane is the implementation's choice (a straight
down perspective camera maps a screen move onto the floor, or onto the plane
of the grab point: up to 12% apart), and exactly where the model rule decides
(the op's numbers must equal what is stored; the rooms' areas must follow).

Pieces used (pool-house, level L1; plan feet):
- KITCHEN    room:5d7de10c..., L-shaped: (0,0) (31,0) (31,12.17) (17.75,12.17) (17.75,17.33) (0,17.33)
- NEIGHBOUR  room:f94386f3..., x 17.75..24.33, y 12.17..18.67 (shares SHARED and CROSSER with the Kitchen)
- CHANGING   room:aa3a6680..., x 24.33..31, y 12.17..22
- SHARED     wall 9adea4c3..., y = 12.17, x 17.75 -> 24.33 (Kitchen | neighbour)
- SHARED_2   wall 9adea4c3...~2, y = 12.17, x 24.33 -> 31 (Kitchen | CHANGING)
- CROSSER    wall b46a9502..., x = 17.75, y 12.17 -> 17.33 (Kitchen | neighbour)
- DOOR_WALL  wall 5ddee7b8..., x = 31, y 0 -> 12.17, holds DOOR (2'-8" wide, at 10.33)
- WEST_X0    wall 17ec2a8d...~2, x = 0, from (0,17.33) to (0,0), holds WINDOW
- WINDOW     opening:4009c005..., at 8.50 from (0,17.33), 10'-8" wide, sill 1'-6", head 8'
- NORTH_IN   wall d60289b4..., y = 17.33, from (0,17.33) to (17.75,17.33)
- SWITCH     anchor:t12-switch, added by this file: on WEST_X0, the Kitchen side
             ('left'), at 2.5, z 4

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t12.py
"""
import copy
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t12_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
POOL = 'pool-house'
FLOOR_KEY = 'pool-house:L1'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
NEIGHBOUR = 'room:f94386f3da524031b4530a0847d7bc75'
CHANGING = 'room:aa3a66806205434ca794927a6d66dd22'
NORTH_WEST = 'room:a80d7712a6724446a8f023e76e90bb7c'
SHARED = 'wall:9adea4c38eb2430697cf47d4ddee9d2a'
SHARED_2 = 'wall:9adea4c38eb2430697cf47d4ddee9d2a~2'
CROSSER = 'wall:b46a95026995451d86e283a019b71367'
CROSSER_2 = 'wall:b46a95026995451d86e283a019b71367~2'
DOOR_WALL = 'wall:5ddee7b8c6774d5e963194b44eb8126c'
DOOR = 'opening:d3aebbe0b48e4d37a4027d3815a68bde'
WEST_X0 = 'wall:17ec2a8dad9e47d0aefbfe143524c1c2~2'
NORTH_IN = 'wall:d60289b4c26b487db5145bdeb22d530e'
WINDOW = 'opening:4009c0058fbc4f09bd0edbc4b2b0e4b5'
SWITCH = 'anchor:t12-switch'

CROSS = 'That would cross another wall.'
DOOR_NARROWER = 'That would leave the door narrower than its wall.'
NOT_CLOSED = "This room isn't closed: a wall is missing here."

KITCHEN_FLOOR = (8.0, 8.0, 0.0)   # open Kitchen floor, clear of walls and the stair
ABOVE = (15.5, 9.0)               # Task 10's camera over the Kitchen
SY = 12.0 + 1.0 / 6.0             # the line of SHARED and SHARED_2 (12'-2")
NY = 17.0 + 1.0 / 3.0             # the line of NORTH_IN (17'-4")
SEED = {}


def _rename(plan):
    for room in H.building(plan, POOL)['rooms']:
        if room['id'] == KITCHEN:
            room['name'] = 'Kitchen'
    return plan


def _serve():
    served = H.serve(_rename)
    if served is not None and 'model' not in SEED:
        SEED['model'] = copy.deepcopy(H.model())
    return served


def _with_switch(model):
    b = H.building(model, POOL)
    b.setdefault('anchors', []).append({'id': SWITCH, 'kind': 'switch', 'offset': 0, 'device': None,
                                        'host': {'wall': WEST_X0, 'side': 'left', 'at': 2.5, 'z': 4.0}})


def _reset(change=None):
    """Put the seeded house back as the current round (plus `change`)."""
    from services import twin_store

    def mutate(_before):
        model = copy.deepcopy(SEED['model'])
        if change:
            change(model)
        return model
    twin_store.update_model(mutate, 'edit', note='t12 reset')


# --- the stored house -----------------------------------------------------------

def _b(model=None):
    return H.building(model or H.model(), POOL)


def _room(model, rid):
    return next((r for r in _b(model)['rooms'] if r['id'] == rid), None)


def _area(polygon):
    return abs(sum(polygon[i - 1][0] * polygon[i][1] - polygon[i][0] * polygon[i - 1][1]
                   for i in range(len(polygon)))) / 2


def _room_area(model, rid):
    room = _room(model, rid)
    check(room is not None, f'{rid} is still a room')
    return _area(room['polygon'])


def _joints(model):
    return {j['id']: list(j['at']) for j in _b(model)['joints']}


def _joint_at(model, point, level='L1'):
    found = [j['id'] for j in _b(model)['joints']
             if j['level'] == level and math.dist(j['at'], point) < 0.02 and not j.get('derived')]
    check(len(found) == 1, ('one joint at', point, found))
    return found[0]


def _piece(model, name, pid):
    return next((p for p in _b(model).get(name, []) if p['id'] == pid), None)


def _close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b)) and len(a) == len(b)


def _line(model, wid):
    return H.wall_line(model, POOL, wid)


def _opening_centre(model, oid):
    """Plan point of an opening's centre on its wall line (at from joints[0])."""
    o = _piece(model, 'openings', oid)
    (ax, ay), (bx, by) = _line(model, o['wall'])
    length = math.hypot(bx - ax, by - ay)
    return [ax + (bx - ax) * o['at'] / length, ay + (by - ay) * o['at'] / length]


def _not_closed(model):
    return sum(1 for f in _b(model).get('flags', []) if f.get('text') == NOT_CLOSED)


def _store():
    from services import twin_store
    return {'round': twin_store.current_id(), 'rounds': len(twin_store.rounds()), 'model': H.model()}


def _facts():
    """The ids and shapes this file relies on, checked against the seeded house."""
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    check((_room(model, KITCHEN) or {}).get('name') == 'Kitchen', ('the renamed room', _room(model, KITCHEN)))
    for rid in (NEIGHBOUR, CHANGING, NORTH_WEST):
        check(_room(model, rid) is not None, f'{rid} survives migration')
    expect = {SHARED: [[17.75, SY], [24.0 + 1 / 3, SY]], SHARED_2: [[24.0 + 1 / 3, SY], [31.0, SY]],
              CROSSER: [[17.75, SY], [17.75, NY]], CROSSER_2: [[17.75, NY], [17.75, 18.67]], DOOR_WALL: [[31.0, 0.0], [31.0, SY]],
              WEST_X0: [[0.0, NY], [0.0, 0.0]], NORTH_IN: [[0.0, NY], [17.75, NY]]}
    for wid, line in expect.items():
        got = _line(model, wid)
        check(_close(got[0], line[0], 0.01) and _close(got[1], line[1], 0.01), (wid, got, line))
    kitchen_walls = H.room_walls(model, POOL, KITCHEN)
    neighbour_walls = H.room_walls(model, POOL, NEIGHBOUR)
    check(all(w in kitchen_walls for w in (SHARED, SHARED_2, CROSSER, DOOR_WALL, WEST_X0, NORTH_IN)), kitchen_walls)
    check(SHARED in neighbour_walls and CROSSER in neighbour_walls, neighbour_walls)
    window = _piece(model, 'openings', WINDOW)
    check(window['wall'] == WEST_X0 and abs(window['width'] - 10.67) < 1e-6 and window['sill'] == 1.5
          and window['head'] == 8 and abs(window['at'] - 8.5033) < 0.01, window)
    door = _piece(model, 'openings', DOOR)
    check(door['wall'] == DOOR_WALL and abs(door['width'] - 2.67) < 1e-6, door)
    return model


# --- page helpers ----------------------------------------------------------------

def _record_ops(page):
    """Every op the editor posts to /api/house/editor/op, in order."""
    posted = []

    def on_request(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op'):
            try:
                body = request.post_data_json
            except Exception:
                body = None
            posted.append((body or {}).get('op') if isinstance(body, dict) else body)
    page.on('request', on_request)
    return posted


def _selection(page, until=None, timeout=3.0):
    deadline = time.time() + timeout
    while True:
        sel = H.editor_state(page, 'selection')
        if until is None or until(sel) or time.time() > deadline:
            return sel
        page.wait_for_timeout(50)


def _is(kind, pid):
    return lambda sel: bool(sel) and (kind is None or sel.get('kind') == kind) and sel.get('id') == pid


def _floor_view(page, served):
    H.open_editor(page, served)
    H.choose_floor(page, FLOOR_KEY)
    H.look_down(page, POOL, *ABOVE)


def _focus_kitchen(page):
    H.click_world(page, *KITCHEN_FLOOR, POOL)
    sel = _selection(page, _is('room', KITCHEN))
    check(_is('room', KITCHEN)(sel), ('a click on the Kitchen floor focuses the Kitchen', sel))


def _select(page, point, kind, pid):
    H.click_world(page, *point, POOL)
    sel = _selection(page, _is(kind, pid))
    check(_is(kind, pid)(sel), (f'a click selects {pid}', sel))
    page.wait_for_timeout(700)   # the next press is a new gesture, never a double click


def _drag(page, points, steps=10):
    """Press at points[0], move through the rest in steps, release (building-local feet)."""
    pixels = [H.screen_of_world(page, *p, POOL) for p in points]
    for sx, sy in pixels:
        H._on_canvas(page, sx, sy)
    page.mouse.move(*pixels[0])
    H.settle(page)
    page.mouse.down()
    for sx, sy in pixels[1:]:
        page.mouse.move(sx, sy, steps=steps)
        H.settle(page)
    page.mouse.up()
    H.settle(page)


def _committed(page, posted, before, signature, timeout=20.0):
    """Wait for the one op of a drag to land as one new round; return the op."""
    from services import twin_store
    deadline = time.time() + timeout
    while time.time() < deadline and twin_store.current_id() == before['round']:
        page.wait_for_timeout(100)
    check(twin_store.current_id() != before['round'],
          ('releasing the drag stored nothing (no new round)', posted, _alert(page)))
    page.wait_for_timeout(500)
    check(len(posted) == 1, ('one drag posts exactly one op', posted))
    check(len(twin_store.rounds()) == before['rounds'] + 1, 'one drag adds exactly one round')
    H.wait_rebuilt(page, signature)
    return posted[0]


def _alert(page):
    if not page.locator('#cc-alert-modal').is_visible():
        return None
    return page.inner_text('#cc-alert-message').strip()


def _refused(page, posted, before, words, timeout=20.0):
    """Wait for the refusal's words; the store must not change."""
    from services import twin_store
    deadline = time.time() + timeout
    while time.time() < deadline and _alert(page) is None:
        page.wait_for_timeout(100)
    check(_alert(page) == words, ('the refusal shows its words through showGlobalAlert', _alert(page), words, posted))
    check(len(posted) == 1, ('the drag posted its one op, which the house refused', posted))
    check(twin_store.current_id() == before['round'] and len(twin_store.rounds()) == before['rounds'],
          'a refused drag stores nothing')


def _scene_wall(page, wid):
    """[from, to] of a wall in the plan the scene last drew."""
    return page.evaluate("""([bid, wid]) => {
        const b = (window.__twin.plan.buildings || []).find(item => item.id === bid);
        const w = b && (b.walls || []).find(item => item.id === wid);
        return w ? [w.from, w.to] : null;
    }""", [POOL, wid])


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


# --- scenarios -------------------------------------------------------------------

def scenario_drag_shared_wall_updates_both_rooms():
    # The wall between the Kitchen and its neighbour, dragged 2 ft across its
    # direction into the Kitchen. Both of its joints move; the neighbour grows by
    # the wall's length times the move, the Kitchen loses that plus the triangle
    # its stretched continuation (SHARED_2, now sloping) cuts off, which CHANGING gains.
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    mid = 21.0 + 1.0 / 24.0
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        H.look_down(page, POOL, mid, SY)
        _select(page, (mid, SY, 0.0), 'wall', SHARED)
        before, signature = _store(), H.scene_signature(page)
        _drag(page, [(mid, SY, 0.0), (mid, SY - 1.0, 0.0), (mid, SY - 2.0, 0.0)])
        op = _committed(page, posted, before, signature)
        check(op.get('op') == 'move_wall' and op.get('wall') == SHARED and op.get('building') == POOL,
              ('a wall dragged across its direction posts move_wall', op))

        model = H.model()
        (ax, ay), (bx, by) = _line(model, SHARED)
        (ax0, ay0), (bx0, by0) = _line(model0, SHARED)
        dy = ay - ay0
        check(abs(ax - ax0) < 1e-6 and abs(bx - bx0) < 1e-6 and abs((by - by0) - dy) < 1e-6,
              ('both joints move straight across the wall, by the same amount', _line(model, SHARED)))
        check(-2.3 <= dy <= -1.7, ('the wall lands about 2 ft into the Kitchen', dy))
        check(abs(abs(op.get('by', 0)) - abs(dy)) < 0.01, ('the posted by is the stored move', op, dy))
        stretched = _line(model, SHARED_2)
        check(_close(stretched[0], [bx, by], 1e-6) and _close(stretched[1], [31.0, SY], 0.01),
              ('the wall joined at its end stretches to follow', stretched))

        shared_len, rest_len = bx0 - ax0, 31.0 - bx0
        move = abs(dy)
        expect = {NEIGHBOUR: _room_area(model0, NEIGHBOUR) + shared_len * move,
                  KITCHEN: _room_area(model0, KITCHEN) - shared_len * move - rest_len * move / 2,
                  CHANGING: _room_area(model0, CHANGING) + rest_len * move / 2}
        for rid, area in expect.items():
            check(abs(_room_area(model, rid) - area) < 0.05, ('the room follows the wall', rid, _room_area(model, rid), area))
        check(_room(model, KITCHEN)['name'] == 'Kitchen', 'the Kitchen keeps its name')
        check(SHARED in H.room_walls(model, POOL, KITCHEN) and SHARED in H.room_walls(model, POOL, NEIGHBOUR),
              'the wall still bounds both rooms')
        check(_not_closed(model) == _not_closed(model0), 'no room comes unclosed')

        drawn = _scene_wall(page, SHARED)
        check(drawn and abs(drawn[0][1] - ay) < 0.01 and abs(drawn[1][1] - by) < 0.01,
              ('the scene draws the wall where it was stored', drawn))
        sel = _selection(page, _is('wall', SHARED))
        check(_is('wall', SHARED)(sel) and sel.get('room') == KITCHEN, ('the dragged wall stays selected', sel))
        _no_errors(s)


def scenario_corner_dot_drags_the_joint():
    # The dot at the Kitchen's inner corner (17.75, 17.33), dragged freely to
    # about (19.25, 16.33): the three walls on that joint all follow it.
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    corner = [17.75, NY]
    joint = _joint_at(model0, corner)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        H.look_down(page, POOL, *corner)
        page.wait_for_timeout(700)
        before, signature = _store(), H.scene_signature(page)
        _drag(page, [(corner[0], corner[1], 0.0), (corner[0] + 0.75, corner[1] - 0.5, 0.0),
                     (corner[0] + 1.5, corner[1] - 1.0, 0.0)])
        op = _committed(page, posted, before, signature)
        check(op.get('op') == 'move_joint' and op.get('joint') == joint and op.get('building') == POOL,
              ('the corner dot posts move_joint for that joint', op, joint))
        to = op.get('to') or [0, 0]
        check(_close(to, [corner[0] + 1.5, corner[1] - 1.0], 0.3), ('the joint goes where it was dragged', to))

        model = H.model()
        at = _joints(model)[joint]
        check(_close(at, to, 0.01), ('the stored joint is the posted point', at, to))
        check(_close(_line(model, NORTH_IN)[1], at, 1e-6), ('the wall along the top follows', _line(model, NORTH_IN)))
        check(_close(_line(model, CROSSER)[1], at, 1e-6), ('the shared wall follows', _line(model, CROSSER)))
        check(_close(_line(model, CROSSER_2)[0], at, 1e-6), ('its continuation follows', _line(model, CROSSER_2)))
        for rid in (KITCHEN, NEIGHBOUR, NORTH_WEST):
            poly = _room(model, rid)['polygon']
            check(any(_close(p, at, 0.01) for p in poly), ('every room on the corner takes the new point', rid, poly))
        check(_room(model, KITCHEN)['name'] == 'Kitchen', 'the Kitchen keeps its name')
        _no_errors(s)


def scenario_window_middle_moves_edges_resize():
    # From outside, facing the Kitchen's west window. The middle slides it 2 ft
    # along the wall; an edge widens it 1 ft with the other edge fixed; the
    # other edge narrows it back; the top raises the head; the bottom lowers the sill.
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    w0 = _piece(model0, 'openings', WINDOW)
    cy0 = NY - w0['at']                      # plan y of the window's centre (WEST_X0 runs from y 17.33 down)
    cz = (w0['sill'] + w0['head']) / 2
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        H.look_at(page, POOL, (-25.0, cy0, cz + 1.0), (0.0, cy0, cz))
        _select(page, (0.0, cy0, cz), 'opening', WINDOW)

        def step(points):
            del posted[:]
            before, signature = _store(), H.scene_signature(page)
            _drag(page, points)
            op = _committed(page, posted, before, signature)
            page.wait_for_timeout(700)
            return op, _piece(H.model(), 'openings', WINDOW)

        # The middle: slide 2 ft towards (0, 0), so `at` grows by 2.
        op, w1 = step([(0.0, cy0, cz), (0.0, cy0 - 1.0, cz), (0.0, cy0 - 2.0, cz)])
        check(op.get('op') == 'move_hosted' and op.get('id') == WINDOW, ('the middle posts move_hosted', op))
        check(w1['wall'] == WEST_X0 and abs(w1['at'] - (w0['at'] + 2.0)) < 0.15,
              ('the window slides along its wall', w1['at'], w0['at']))
        check(w1['width'] == w0['width'] and w1['sill'] == w0['sill'] and w1['head'] == w0['head'],
              ('sliding keeps its size', w1))

        # The edge nearer (0, 17.33): drag it 1 ft further that way. The far edge stays.
        near, far = w1['at'] - w1['width'] / 2, w1['at'] + w1['width'] / 2
        op, w2 = step([(0.0, NY - near, cz), (0.0, NY - near + 0.5, cz), (0.0, NY - near + 1.0, cz)])
        check(op.get('op') == 'resize_opening' and op.get('id') == WINDOW, ('an edge posts resize_opening', op))
        check(abs((w2['at'] + w2['width'] / 2) - far) < 0.02, ('the other edge stays put', w2, far))
        check(abs(w2['width'] - (w1['width'] + 1.0)) < 0.15, ('the window is 1 ft wider', w2['width'], w1['width']))
        check(w2['wall'] == WEST_X0 and w2['sill'] == w1['sill'] and w2['head'] == w1['head'], w2)

        # The far edge: drag it 1 ft back towards the middle. The near edge stays.
        near, far = w2['at'] - w2['width'] / 2, w2['at'] + w2['width'] / 2
        op, w3 = step([(0.0, NY - far, cz), (0.0, NY - far + 0.5, cz), (0.0, NY - far + 1.0, cz)])
        check(op.get('op') == 'resize_opening' and op.get('id') == WINDOW, ('the other edge posts resize_opening', op))
        check(abs((w3['at'] - w3['width'] / 2) - near) < 0.02, ('the near edge stays put', w3, near))
        check(abs(w3['width'] - (w2['width'] - 1.0)) < 0.15, ('the window is 1 ft narrower', w3['width'], w2['width']))

        # The top: raise the head 6 in. Width, place and sill stay.
        cy3 = NY - w3['at']
        op, w4 = step([(0.0, cy3, w3['head']), (0.0, cy3, w3['head'] + 0.25), (0.0, cy3, w3['head'] + 0.5)])
        check(op.get('op') == 'resize_opening' and op.get('id') == WINDOW and 'head' in op,
              ('the top posts resize_opening with head', op))
        check(abs(w4['head'] - (w3['head'] + 0.5)) < 0.1, ('the head rises', w4['head'], w3['head']))
        check(w4['sill'] == w3['sill'] and w4['width'] == w3['width'] and abs(w4['at'] - w3['at']) < 1e-6, w4)

        # The bottom: lower the sill 6 in.
        op, w5 = step([(0.0, cy3, w4['sill']), (0.0, cy3, w4['sill'] - 0.25), (0.0, cy3, w4['sill'] - 0.5)])
        check(op.get('op') == 'resize_opening' and op.get('id') == WINDOW and 'sill' in op,
              ('the bottom posts resize_opening with sill', op))
        check(abs(w5['sill'] - (w4['sill'] - 0.5)) < 0.1, ('the sill drops', w5['sill'], w4['sill']))
        check(w5['head'] == w4['head'] and w5['width'] == w4['width'] and abs(w5['at'] - w4['at']) < 1e-6, w5)

        sel = _selection(page, _is('opening', WINDOW))
        check(_is('opening', WINDOW)(sel), ('the window stays selected through its drags', sel))
        check(H.card_title(page) == 'Window, kitchen north wall', H.card_title(page))
        _no_errors(s)


def scenario_switch_dragged_round_the_corner_rehosts():
    # A switch on the Kitchen side of the west wall. Slid along its wall it keeps
    # its host; dragged round the inside corner onto the wall along the top it is
    # re-hosted there, on the Kitchen side ('right' of NORTH_IN, which runs +x).
    s = _serve()
    if s is None:
        return
    _reset(_with_switch)
    model0 = _facts()
    from services import twin_model_hosts
    switch0 = _piece(model0, 'anchors', SWITCH)
    check(switch0 is not None and switch0['host']['wall'] == WEST_X0, ('the switch is seeded', switch0))
    p0 = twin_model_hosts.world_point(_b(model0), switch0['host'], switch0.get('offset', 0))
    check(_close(p0, [0.25, NY - 2.5, 4.0], 0.01), ('the switch sits on the inside face', p0))
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        H.look_at(page, POOL, (7.0, 11.0, 5.0), (0.5, 16.6, 4.0))
        _select(page, tuple(p0), None, SWITCH)

        # Slide along the same face, 1.5 ft towards the corner.
        before, signature = _store(), H.scene_signature(page)
        _drag(page, [tuple(p0), (0.25, NY - 1.75, 4.0), (0.25, NY - 1.0, 4.0)])
        op = _committed(page, posted, before, signature)
        check(op.get('op') == 'move_hosted' and op.get('id') == SWITCH, ('sliding posts move_hosted', op))
        switch1 = _piece(H.model(), 'anchors', SWITCH)
        host1 = switch1['host']
        check(host1.get('wall') == WEST_X0 and host1.get('side') == 'left', ('sliding keeps the host', host1))
        check(abs(host1['at'] - 1.0) < 0.15 and abs(host1.get('z', 0) - 4.0) < 0.15, ('the switch slid', host1))
        page.wait_for_timeout(700)

        # Round the corner onto NORTH_IN's Kitchen face (y = 17.33 - 0.25).
        del posted[:]
        model1 = H.model()
        p1 = twin_model_hosts.world_point(_b(model1), host1, switch1.get('offset', 0))
        face = NY - 0.25
        before, signature = _store(), H.scene_signature(page)
        _drag(page, [tuple(p1), (0.25, NY - 0.45, 4.0), (0.6, face, 4.0), (1.5, face, 4.0)])
        op = _committed(page, posted, before, signature)
        check(op.get('op') == 'move_hosted' and op.get('id') == SWITCH and (op.get('host') or {}).get('wall') == NORTH_IN,
              ('crossing onto the next wall posts move_hosted with the new host', op))
        model2 = H.model()
        switches = [a for a in _b(model2).get('anchors', []) if a['id'] == SWITCH]
        check(len(switches) == 1, ('the same switch moves; none is copied or lost', switches))
        switch2 = switches[0]
        host2 = switch2['host']
        check(host2.get('wall') == NORTH_IN and host2.get('side') == 'right', ('re-hosted on the Kitchen face', host2))
        check(abs(host2['at'] - 1.5) < 0.2 and abs(host2.get('z', 0) - 4.0) < 0.15, ('where it was dropped', host2))
        check(switch2.get('offset', 0) == switch0.get('offset', 0) and switch2['kind'] == 'switch', switch2)
        p2 = twin_model_hosts.world_point(_b(model2), host2, switch2.get('offset', 0))
        check(_close(p2, [1.5, face, 4.0], 0.2), ('it sits on the new face', p2))
        check(not any(f.get('piece') == SWITCH for f in _b(model2).get('flags', [])), 'no flag for a re-hosted switch')
        sel = _selection(page, _is(None, SWITCH))
        check(_is(None, SWITCH)(sel), ('the switch stays selected', sel))
        _no_errors(s)


def scenario_move_room_carries_its_window():
    # The Kitchen's floor dragged 2 ft towards plan y = 0. Every Kitchen joint
    # moves by the same step; the west wall slides along itself with its window;
    # the neighbour stretches by the shared wall's length times the move.
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    kitchen0 = _room(model0, KITCHEN)
    joints0 = _joints(model0)
    window0 = _piece(model0, 'openings', WINDOW)
    centre0 = _opening_centre(model0, WINDOW)
    west0 = _line(model0, WEST_X0)
    shared_len = _line(model0, SHARED)[1][0] - _line(model0, SHARED)[0][0]
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        page.wait_for_timeout(700)
        before, signature = _store(), H.scene_signature(page)
        _drag(page, [(10.0, 6.0, 0.0), (10.0, 5.0, 0.0), (10.0, 4.0, 0.0)])
        op = _committed(page, posted, before, signature)
        check(op.get('op') == 'move_room' and op.get('room') == KITCHEN and op.get('building') == POOL,
              ('dragging the floor posts move_room', op))

        model = H.model()
        joints = _joints(model)
        moves = {j: [joints[j][0] - joints0[j][0], joints[j][1] - joints0[j][1]] for j in kitchen0['joints']}
        dx, dy = moves[kitchen0['joints'][0]]
        check(all(_close(m, [dx, dy], 0.01) for m in moves.values()), ('every Kitchen joint moves by one step', moves))
        check(abs(dx) < 0.15 and -2.3 <= dy <= -1.7, ('the room moves about 2 ft', dx, dy))
        check(_close(op.get('by') or [], [dx, dy], 0.01), ('the posted by is the stored move', op, dx, dy))
        check(abs(_room_area(model, KITCHEN) - _area(kitchen0['polygon'])) < 0.05, 'the Kitchen keeps its size')
        check(_room(model, KITCHEN)['name'] == 'Kitchen', 'the Kitchen keeps its name')

        window = _piece(model, 'openings', WINDOW)
        check(window['wall'] == WEST_X0, ('the window stays on its wall', window))
        check(abs(window['at'] - window0['at']) < 0.01 and window['width'] == window0['width']
              and window['sill'] == window0['sill'] and window['head'] == window0['head'],
              ('the window keeps its place on the wall and its size', window, window0))
        centre = _opening_centre(model, WINDOW)
        check(_close(centre, [centre0[0] + dx, centre0[1] + dy], 0.02), ('the window travels with the room', centre, centre0))

        check(abs(_room_area(model, NEIGHBOUR) - (_room_area(model0, NEIGHBOUR) + shared_len * abs(dy))) < 0.05,
              ('the neighbour stretches rather than tears', _room_area(model, NEIGHBOUR)))
        check(_not_closed(model) == _not_closed(model0), 'no room comes unclosed')
        drawn = _scene_wall(page, WEST_X0)
        check(drawn and _close(drawn[0], [west0[0][0] + dx, west0[0][1] + dy], 0.01)
              and _close(drawn[1], [west0[1][0] + dx, west0[1][1] + dy], 0.01),
              ('the scene draws the moved wall', drawn))
        _no_errors(s)


def scenario_wall_drag_that_would_cross_is_refused():
    # R16: CROSSER dragged from x 17.75 to about x 26 would carry the top wall
    # across the wall at x 24.33. The house refuses it and nothing changes.
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    grab = (17.75, 14.75, 0.0)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        H.look_down(page, POOL, 21.9, 14.75)
        _select(page, grab, 'wall', CROSSER)
        before = _store()
        _drag(page, [grab, (22.0, 14.75, 0.0), (26.0, 14.75, 0.0)])
        _refused(page, posted, before, CROSS)
        op = posted[0] or {}
        check(op.get('op') == 'move_wall' and op.get('wall') == CROSSER, ('the drag asked for move_wall', op))
        check(_line(H.model(), CROSSER) == _line(model0, CROSSER), 'the stored wall did not move')
        drawn = _scene_wall(page, CROSSER)
        check(drawn and abs(drawn[0][0] - 17.75) < 0.01 and abs(drawn[1][0] - 17.75) < 0.01,
              ('the scene puts the wall back', drawn))
        _no_errors(s)


def scenario_wall_drag_that_squeezes_a_door_is_refused():
    # R3 (and R16: it holds for every move): SHARED_2 dragged from y 12.17 down to
    # about y 2.67 would shorten DOOR_WALL below the door's 2'-8" plus 6 in each
    # side (3'-8"). Refused with Task 8's words; nothing changes.
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    grab = (27.67, SY, 0.0)
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _floor_view(page, s)
        _focus_kitchen(page)
        H.look_down(page, POOL, 27.67, 7.5)
        _select(page, grab, 'wall', SHARED_2)
        before = _store()
        _drag(page, [grab, (27.67, 7.5, 0.0), (27.67, 2.67, 0.0)])
        _refused(page, posted, before, DOOR_NARROWER)
        op = posted[0] or {}
        check(op.get('op') == 'move_wall' and op.get('wall') == SHARED_2, ('the drag asked for move_wall', op))
        model = H.model()
        check(_line(model, DOOR_WALL) == _line(model0, DOOR_WALL), 'the door\'s wall keeps its length')
        check(_piece(model, 'openings', DOOR) == _piece(model0, 'openings', DOOR), 'the door is untouched')
        drawn = _scene_wall(page, SHARED_2)
        check(drawn and abs(drawn[0][1] - SY) < 0.01 and abs(drawn[1][1] - SY) < 0.01,
              ('the scene puts the wall back', drawn))
        _no_errors(s)


SCENARIOS = [
    scenario_drag_shared_wall_updates_both_rooms,
    scenario_corner_dot_drags_the_joint,
    scenario_window_middle_moves_edges_resize,
    scenario_switch_dragged_round_the_corner_rehosts,
    scenario_move_room_carries_its_window,
    scenario_wall_drag_that_would_cross_is_refused,
    scenario_wall_drag_that_squeezes_a_door_is_refused,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
