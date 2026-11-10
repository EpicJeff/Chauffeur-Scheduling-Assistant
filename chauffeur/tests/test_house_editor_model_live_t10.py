"""Selection you can see, rooms first, in real Chromium (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections 5.1
and 5.2; plan docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md
Part B Task 10; brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-10-brief.md; Ruling R29 for the file layout).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). This file renames one room before the
push: the pool house's 'Pool Lounge' becomes 'Kitchen', so the card titles are
the brief's own words. The pool house is turned 270 degrees on the lot, so a
wall's compass word differs from its direction in the building's own plan:
the compass word comes from the wall's outward normal in lot coordinates
(+x east, +y north), after the building's rotation.

The test hook is window.__twinEditor.selection(), which returns
{kind, id, room, ghosted, tinted: {floor, walls}} (the brief). Nothing
selected reads as kind null, id null, room null, ghosted 0, no tint. The hover
scenario also reads selection().hover ({kind, id} of what a click would select,
or null): the brief's hook has no hover field, and this is the one this file
adds (see the task 10 tests report).

Pieces used (pool-house, level L1, ids after migration):
- Kitchen          room:5d7de10ca48340ae85c407d22337c6f7 ('Pool Lounge' in the read)
- its walls        the seven walls along its joint cycle (read from the model)
- WEST_X0          wall:17ec2a8dad9e47d0aefbfe143524c1c2~2, plan x = 0, faces lot north; hosts
- WINDOW           opening:4009c0058fbc4f09bd0edbc4b2b0e4b5 (10'-8" wide, sill 1'-6", head 8')
- FRONT_Y0         wall:44b42dc9c06144adbeaeb88ce33b0430, plan y = 0, faces lot west
- NEIGHBOUR        room:f94386f3da524031b4530a0847d7bc75, shares two walls with the Kitchen
- CHANGING         room:aa3a66806205434ca794927a6d66dd22
- OUTSIDE_WALL     wall:b139d9a5cf544deca3143a7b369b25cd, between the neighbour and CHANGING

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t10.py
"""
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t10_'))
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
WEST_X0 = 'wall:17ec2a8dad9e47d0aefbfe143524c1c2~2'
FRONT_Y0 = 'wall:44b42dc9c06144adbeaeb88ce33b0430'
OUTSIDE_WALL = 'wall:b139d9a5cf544deca3143a7b369b25cd'
WINDOW = 'opening:4009c0058fbc4f09bd0edbc4b2b0e4b5'

# Building-local points (feet; z above the floor).
KITCHEN_FLOOR = (8.0, 8.0, 0.0)          # open floor in the Kitchen, clear of walls and the stair
NEIGHBOUR_FLOOR = (21.0, 15.4, 0.0)      # middle of the neighbour room
CHANGING_FLOOR = (27.7, 17.0, 0.0)       # middle of CHANGING
WEST_X0_POINT = (0.0, 1.5, 5.5)          # on WEST_X0, clear of the window (which spans y 3.5 to 14.2)
FRONT_Y0_POINT = (16.9, 0.0, 5.5)        # on FRONT_Y0, between the slider and the bifold
OUTSIDE_WALL_POINT = (24.33, 15.4, 5.5)  # on OUTSIDE_WALL
ABOVE = (15.5, 9.0)                      # the camera looks straight down over the Kitchen


def _rename(plan):
    for room in H.building(plan, POOL)['rooms']:
        if room['id'] == KITCHEN:
            room['name'] = 'Kitchen'
    return plan


def _serve():
    return H.serve(_rename)


# --- the household, read from the stored model --------------------------------

def _inside(polygon, p):
    inside = False
    for i in range(len(polygon)):
        (x1, y1), (x2, y2) = polygon[i], polygon[i - 1]
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def compass(model, bid, room_id, wall_id):
    """The compass word of a room's wall: its outward normal, turned onto the lot."""
    b = H.building(model, bid)
    room = next(r for r in b['rooms'] if r['id'] == room_id)
    (ax, ay), (bx, by) = H.wall_line(model, bid, wall_id)
    length = math.hypot(bx - ax, by - ay)
    dx, dy = (bx - ax) / length, (by - ay) / length
    nx, ny = dy, -dx
    mid = ((ax + bx) / 2, (ay + by) / 2)
    if _inside(room['polygon'], (mid[0] + 0.25 * nx, mid[1] + 0.25 * ny)):
        nx, ny = -nx, -ny
    a = math.radians(b.get('rotation') or 0)
    lx, ly = math.cos(a) * nx - math.sin(a) * ny, math.sin(a) * nx + math.cos(a) * ny
    if abs(lx) >= abs(ly):
        return 'east' if lx > 0 else 'west'
    return 'north' if ly > 0 else 'south'


def _facts():
    """The ids and shapes this file relies on, checked against the migrated house."""
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    b = H.building(model, POOL)
    rooms = {r['id']: r for r in b['rooms']}
    check(rooms.get(KITCHEN, {}).get('name') == 'Kitchen', ('the renamed room survives migration', rooms.get(KITCHEN)))
    for rid in (NEIGHBOUR, CHANGING):
        check(rid in rooms, f'{rid} survives migration')
    walls = H.room_walls(model, POOL, KITCHEN)
    check(len(walls) == 7 and WEST_X0 in walls and FRONT_Y0 in walls and OUTSIDE_WALL not in walls, walls)
    flat = H.building(H.flat(), POOL)
    window = next(o for o in flat['openings'] if o['id'] == WINDOW)
    check(window['kind'] == 'window' and window['wall'] == WEST_X0, window)
    check(compass(model, POOL, KITCHEN, WEST_X0) == 'north', 'the plan-west wall faces lot north at 270 degrees')
    check(compass(model, POOL, KITCHEN, FRONT_Y0) == 'west', 'the plan-front wall faces lot west at 270 degrees')
    wall = next(w for w in flat['walls'] if w['id'] == WEST_X0)
    length = math.hypot(wall['to'][0] - wall['from'][0], wall['to'][1] - wall['from'][1])
    t = window['at'] / length
    centre = [wall['from'][i] + (wall['to'][i] - wall['from'][i]) * t for i in (0, 1)]
    outside_walls = [w for w in b['walls'] if w['level'] == 'L1' and w.get('kind') != 'separator' and w['id'] not in walls]
    other_rooms = [r for r in b['rooms'] if r['level'] == 'L1' and r.get('kind', 'room') == 'room' and r['id'] != KITCHEN]
    return {'model': model, 'walls': walls, 'window_centre': (centre[0], centre[1], (window['sill'] + window['head']) / 2),
            'outside_count': len(outside_walls) + len(other_rooms)}


# --- page helpers ---------------------------------------------------------------

def _selection(page, until=None, timeout=3.0):
    """selection(), polled until `until(sel)` holds (or the timeout), then returned."""
    deadline = time.time() + timeout
    while True:
        sel = H.editor_state(page, 'selection')
        if until is None or until(sel) or time.time() > deadline:
            return sel
        page.wait_for_timeout(50)


def _is(kind, pid):
    return lambda sel: bool(sel) and sel.get('kind') == kind and sel.get('id') == pid


def _nothing(sel):
    return sel is None or (sel.get('kind') is None and sel.get('id') is None and sel.get('room') is None
                           and not sel.get('ghosted') and not (sel.get('tinted') or {}).get('floor')
                           and not (sel.get('tinted') or {}).get('walls'))


def _hover(sel):
    hover = (sel or {}).get('hover')
    return hover and (hover.get('kind'), hover.get('id'))


def _opacity(page, pid):
    info = page.evaluate('([p, b]) => window.__twin.pieceInfo(p, b)', [pid, POOL])
    check(info is not None, f'{pid} is a piece in the scene')
    return info['opacity']


def _floor_view(page, served):
    H.open_editor(page, served)
    H.choose_floor(page, FLOOR_KEY)
    H.look_down(page, POOL, *ABOVE)


def _focus_kitchen(page):
    H.click_world(page, *KITCHEN_FLOOR, POOL)
    sel = _selection(page, _is('room', KITCHEN))
    check(_is('room', KITCHEN)(sel), ('a click on the Kitchen floor selects the Kitchen', sel))
    return sel


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


# --- scenarios -------------------------------------------------------------------

def scenario_click_floor_tints_room_and_its_walls():
    s = _serve()
    if s is None:
        return
    facts = _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s)
        sel = _focus_kitchen(page)
        check(sel['room'] == KITCHEN, ('the room is focused', sel))
        tinted = sel.get('tinted') or {}
        check(tinted.get('floor') == KITCHEN, ('the floor takes tint A', tinted))
        check(sorted(tinted.get('walls') or []) == sorted(facts['walls']),
              ('exactly the room\'s seven walls take tint B', tinted, facts['walls']))
        check(H.card_title(page) == 'Kitchen', ('the card names the room', H.card_title(page)))
        _no_errors(s)


def scenario_outside_pieces_are_ghosted_and_unpickable():
    s = _serve()
    if s is None:
        return
    facts = _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s)
        before = _opacity(page, OUTSIDE_WALL)
        check(abs(before - 0.25) > 1e-3, ('nothing is ghosted before a room is focused', before))
        sel = _focus_kitchen(page)
        check(isinstance(sel.get('ghosted'), int) and sel['ghosted'] >= facts['outside_count'],
              ('every piece outside the room is ghosted: at least the level\'s other walls and rooms',
               sel.get('ghosted'), facts['outside_count']))
        check(abs(_opacity(page, OUTSIDE_WALL) - 0.25) < 1e-6, ('an outside wall is ghosted at 0.25', _opacity(page, OUTSIDE_WALL)))
        check(abs(_opacity(page, WEST_X0) - 0.25) > 1e-3, ('the room\'s own wall is not ghosted', _opacity(page, WEST_X0)))

        # The neighbour's floor cannot be clicked while the Kitchen is focused:
        # the click is outside the room and steps back out to nothing.
        H.click_world(page, *NEIGHBOUR_FLOOR, POOL)
        sel = _selection(page, _nothing)
        check(_nothing(sel), ('a ghosted floor is not selected; the click steps out', sel))
        check(abs(_opacity(page, OUTSIDE_WALL) - before) < 1e-6, ('stepping out lifts the ghosting', _opacity(page, OUTSIDE_WALL)))
        H.click_world(page, *NEIGHBOUR_FLOOR, POOL)
        sel = _selection(page, _is('room', NEIGHBOUR))
        check(_is('room', NEIGHBOUR)(sel), ('with nothing focused the same click selects the neighbour', sel))

        # An outside wall is not pickable either.
        H.press(page, 'Escape')
        _focus_kitchen(page)
        H.click_world(page, *OUTSIDE_WALL_POINT, POOL)
        sel = _selection(page, _nothing)
        check(_nothing(sel) and (sel or {}).get('id') != OUTSIDE_WALL, ('a ghosted wall is not selected', sel))
        _no_errors(s)


def scenario_escape_steps_out():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s)
        _focus_kitchen(page)
        H.click_world(page, *WEST_X0_POINT, POOL)
        sel = _selection(page, _is('wall', WEST_X0))
        check(_is('wall', WEST_X0)(sel) and sel['room'] == KITCHEN, ('a wall of the focused room is selected directly', sel))
        check((sel.get('tinted') or {}).get('floor') == KITCHEN, ('the room stays focused', sel))

        H.press(page, 'Escape')
        sel = _selection(page, _is('room', KITCHEN))
        check(_is('room', KITCHEN)(sel) and sel['room'] == KITCHEN, ('Escape steps from the piece to the room', sel))
        H.press(page, 'Escape')
        sel = _selection(page, _nothing)
        check(_nothing(sel), ('Escape steps from the room to nothing', sel))
        check(H.card_title(page) is None, ('no card with nothing selected', H.card_title(page)))

        # A click outside the room steps out the same way.
        _focus_kitchen(page)
        H.click_world(page, *WEST_X0_POINT, POOL)
        _selection(page, _is('wall', WEST_X0))
        H.click_world(page, *CHANGING_FLOOR, POOL)
        sel = _selection(page, _is('room', KITCHEN))
        check(_is('room', KITCHEN)(sel), ('a click outside steps from the piece to the room', sel))
        H.click_world(page, *CHANGING_FLOOR, POOL)
        sel = _selection(page, _nothing)
        check(_nothing(sel), ('a second click outside steps from the room to nothing', sel))
        _no_errors(s)


def scenario_hover_highlights_before_click():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s)
        before = _selection(page)
        H.hover_world(page, *KITCHEN_FLOOR, POOL)
        sel = _selection(page, lambda v: _hover(v) == ('room', KITCHEN))
        check(_hover(sel) == ('room', KITCHEN), ('hovering the floor pre-highlights the room', sel))
        check((sel or {}).get('kind') == (before or {}).get('kind') and (sel or {}).get('id') == (before or {}).get('id')
              and (sel or {}).get('kind') != 'room', ('hovering selects nothing', before, sel))

        _focus_kitchen(page)
        H.hover_world(page, *WEST_X0_POINT, POOL)
        sel = _selection(page, lambda v: _hover(v) == ('wall', WEST_X0))
        check(_hover(sel) == ('wall', WEST_X0), ('with the room focused, hovering its wall pre-highlights the wall', sel))
        check(_is('room', KITCHEN)(sel), ('the selection stays the room while hovering', sel))

        H.hover_world(page, *CHANGING_FLOOR, POOL)
        sel = _selection(page, lambda v: not _hover(v))
        check(not _hover(sel), ('a ghosted floor outside the room never highlights', sel))
        check(_is('room', KITCHEN)(sel), ('and the room stays selected', sel))
        _no_errors(s)


def scenario_card_names_the_wall_by_compass():
    s = _serve()
    if s is None:
        return
    facts = _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _floor_view(page, s)
        _focus_kitchen(page)
        check(H.card_title(page) == 'Kitchen', H.card_title(page))

        H.click_world(page, *WEST_X0_POINT, POOL)
        _selection(page, _is('wall', WEST_X0))
        check(H.card_title(page) == 'Kitchen, north wall',
              ('the compass word is the lot direction, not the plan side', H.card_title(page)))

        H.click_world(page, *FRONT_Y0_POINT, POOL)
        sel = _selection(page, _is('wall', FRONT_Y0))
        check(_is('wall', FRONT_Y0)(sel) and sel['room'] == KITCHEN, sel)
        check(H.card_title(page) == 'Kitchen, west wall', H.card_title(page))

        # Face the window from outside the house; the ray meets the window
        # before (and inside) its wall, and the window answers.
        cx, cy, cz = facts['window_centre']
        H.look_at(page, POOL, (cx - 25.0, cy, cz + 1.0), (cx, cy, cz))
        H.click_world(page, cx, cy, cz, POOL)
        sel = _selection(page, _is('opening', WINDOW))
        check(_is('opening', WINDOW)(sel) and sel['room'] == KITCHEN, ('an opening of the focused room is selected directly', sel))
        check(H.card_title(page) == 'Window, kitchen north wall', H.card_title(page))
        _no_errors(s)


def scenario_building_and_level_get_their_cards():
    # Brief: with nothing focused, a click on a building in the exterior view
    # selects the building, and a floor button selects that level.
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        H.all_floors(page)
        check(_nothing(_selection(page)), _selection(page))
        H.look_at(page, POOL, (15.5, -60.0, 30.0), (15.5, 11.0, 8.0))
        H.click_world(page, 15.5, 11.0, 8.0, POOL)
        sel = _selection(page, _is('building', POOL))
        check(_is('building', POOL)(sel), ('a click on the building from outside selects the building', sel))
        check(H.card_title(page) == 'Pool House', H.card_title(page))

        H.choose_floor(page, FLOOR_KEY)
        sel = _selection(page, _is('level', 'L1'))
        check(_is('level', 'L1')(sel), ('the floor button selects its level', sel))
        check('main floor' in (H.card_title(page) or '').lower(), ('the level gets its card', H.card_title(page)))
        _no_errors(s)


def scenario_sign_in_survives_a_failed_navigation():
    # Final wave M2 (R56): the harness's sign-in init script runs in every
    # document, Chromium's error page after a loopback reset included, and must
    # not throw there; on the app it still signs the parent in.
    import socket
    s = _serve()
    if s is None:
        return
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.signed_in(page)
        try:
            page.goto(f'http://127.0.0.1:{port}/', timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(300)
        check(not any('localStorage' in e for e in s.errors()), s.errors())
        H.open_editor(page, s)
        check(page.evaluate("() => localStorage.getItem('chauffeur_admin_token')") == H.STATE['token'],
              'the app page is still signed in')
        _no_errors(s)


def scenario_default_camera_sees_the_house_past_the_trees():
    # Final wave M3: the editor opens looking from the street toward the house,
    # and no yard plant stands between the eye and the house. Checked with the
    # scene's own geometry: rays from the eye to the house's middle and half-way
    # to each corner meet a building before any tree.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        result = page.evaluate("""async () => {
            const THREE = await import('three');
            const { Tree } = await import('@dgreenheck/ez-tree');
            const view = window.__twin, state = view.cameraState(), FT = 0.3048;
            const eye = new THREE.Vector3().fromArray(state.position);
            const points = (view.plan.buildings || []).flatMap(b => {
              const a = (b.rotation || 0) * Math.PI / 180;
              return (b.walls || []).flatMap(w => [w.from, w.to]).map(p => [Math.cos(a) * p[0] - Math.sin(a) * p[1] + b.position[0],
                Math.sin(a) * p[0] + Math.cos(a) * p[1] + b.position[1]]);
            });
            const lo = [0, 1].map(i => Math.min(...points.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...points.map(p => p[i])));
            const mid = [0, 1].map(i => (lo[i] + hi[i]) / 2);
            const sights = [mid, [lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]
              .map((p, i) => i ? [(p[0] + mid[0]) / 2, (p[1] + mid[1]) / 2] : p);
            let trees = 0;
            for (let wait = 0; wait < 300 && !trees; wait++) {
              view.scene.traverse(o => { if (o instanceof Tree) trees++; });
              if (!trees) await new Promise(r => setTimeout(r, 100));
            }
            const shown = o => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
            const out = [];
            for (const [x, y] of sights) {
              const target = new THREE.Vector3(x * FT, 8 * FT, -y * FT);
              const ray = new THREE.Raycaster(eye, target.clone().sub(eye).normalize(), 0, eye.distanceTo(target) + 30 * FT);
              let first = null;
              for (const hit of ray.intersectObjects(view.scene.children, true)) {
                let tree = false, building = false;
                for (let o = hit.object; o; o = o.parent) {
                  if (o instanceof Tree) tree = true;
                  if (o.userData?.buildingId) building = true;
                }
                if (!shown(hit.object)) continue;
                if (tree || building) { first = tree ? 'tree' : 'building'; break; }
              }
              out.push(first);
            }
            return { eye: [eye.x / FT, -eye.z / FT, eye.y / FT], mid, lo, out, trees };
        }""")
        check(result['trees'] > 0, ('the yard has its trees in the scene', result))
        check(all(hit != 'tree' for hit in result['out']) and result['out'][0] == 'building',
              ('no tree stands between the first view and the house', result))
        check(result['eye'][1] < result['mid'][1], ('the first view looks from the street side', result))
        _no_errors(s)


SCENARIOS = [
    scenario_sign_in_survives_a_failed_navigation,
    scenario_default_camera_sees_the_house_past_the_trees,
    scenario_click_floor_tints_room_and_its_walls,
    scenario_outside_pieces_are_ghosted_and_unpickable,
    scenario_escape_steps_out,
    scenario_hover_highlights_before_click,
    scenario_card_names_the_wall_by_compass,
    scenario_building_and_level_get_their_cards,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
