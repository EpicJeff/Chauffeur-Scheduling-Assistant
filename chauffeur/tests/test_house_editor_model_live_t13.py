"""Drawing tools, undo and redo, and Plan mode retired, in real Chromium (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections 3
item 9, 4.1, 4.2, 4.7 and 5.5; plan docs/superpowers/plans/2026-11-09-house-
connected-model-pieces-1-2.md Part B Task 13, ruling P5 and Review Focus 4;
brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-13-brief.md; Ruling R29 for the file layout, R16 and R20 for splits).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). As in the Task 10 file, the pool
house's 'Pool Lounge' is renamed 'Kitchen' before the push. Every scenario
starts from that seeded house: _reset() reverts the store to the seed round
(an exact copy, ids kept), and each scenario opens its own page, so each has
a fresh per-session undo stack (P5).

The pool house, level L1, in its own plan feet (rotation 270 on the lot):
- outer walls: y = 0 (front, slider 3.08-15.08 and bifold 18.67-28.67),
  x = 31, y = 22 (north, no wall openings), x = 0 (window 3.5-14.17);
- the Kitchen: (0,0)-(31,0)-(31,12.17)-(17.75,12.17)-(17.75,17.33)-(0,17.33);
- wall y = 12.1667 from x 17.75 to 31; wall y = 17.3333 from x 0 to 17.75;
- room a80d ('Room'): x 0-17.75, y 17.33-22.
Every point a scenario draws at is at least 1 ft from any joint and clear of
every opening, so no snap or door rule other than the one named interferes.

The rail (brief): #rail-select, #rail-draw-room, #rail-draw-wall,
#rail-split-room, #rail-add-door, #rail-add-window, #rail-add-anchor,
#rail-add-level, #rail-delete, #rail-undo, #rail-redo, and the existing
#rail-sheet. #rail-plan is gone and plan_view.js is never loaded.

Readings (see the task 13 tests report):
- Draw room: a rectangle by press-drag-release, or a polygon by clicks closed
  by a click on its first point.
- Draw wall: a click chain, ended with Escape or a double click.
- Split room: with the room focused (a click on its floor), the tool takes
  two clicks, the separator's two ends, each on one of the room's walls.
  Then promptInput asks the new room's name; Skip (the dialog's cancel
  button) keeps 'Room'. A drawing gesture that happens to split a room may
  also ask; _skip_prompt() answers that Skip and nothing here requires it.
- Undo is one step per gesture: the split and the name typed for the new
  room are undone together by one undo (the round before the gesture).
  Undo and redo move the store by POST /api/house/twin/revert (P5), so the
  restored model equals the earlier round exactly and the latest round's kind
  is 'revert'.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t13.py
"""
import json
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t13_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
POOL = 'pool-house'
FLOOR_KEY = 'pool-house:L1'
LEVEL = 'L1'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
NORTH_ROOM = 'room:a80d7712a6724446a8f023e76e90bb7c'   # 'Room', x 0-17.75, y 17.33-22
NORTH_WALL = 'wall:066fd0b4f0044afc972a7a5c39a2f883'   # y = 22, x 0-31
FRONT_WALL = 'wall:44b42dc9c06144adbeaeb88ce33b0430'   # y = 0, x 0-31
WEST_WALL = 'wall:17ec2a8dad9e47d0aefbfe143524c1c2'    # x = 0, y 0-22
EAST_WALL = 'wall:5ddee7b8c6774d5e963194b44eb8126c'    # x = 31, y 0-22
MID_WALL = 'wall:9adea4c38eb2430697cf47d4ddee9d2a'     # y = 12.1667, x 17.75-31
LOUNGE_NORTH = 'wall:d60289b4c26b487db5145bdeb22d530e' # y = 17.3333, x 0-17.75
Y_MID = 12.166666666666666
Y_LOUNGE = 17.333333333333332
KITCHEN_FLOOR = (8.0, 8.0, 0.0)

RAIL = ['rail-select', 'rail-draw-room', 'rail-draw-wall', 'rail-split-room', 'rail-add-door', 'rail-add-window',
        'rail-add-anchor', 'rail-add-level', 'rail-delete', 'rail-undo', 'rail-redo']
VIEWPORT = {'width': 1600, 'height': 900}
_SEED = {}


def _rename(plan):
    for room in H.building(plan, POOL)['rooms']:
        if room['id'] == KITCHEN:
            room['name'] = 'Kitchen'
    return plan


def _serve():
    s = H.serve(_rename)
    if s is not None:
        _reset()
    return s


def _reset():
    """Put the store back on the seeded house (a revert to the seed round)."""
    from services import twin_store
    if 'round' not in _SEED:
        # The first call comes before any scenario has changed the house.
        _SEED['round'] = min(r['id'] for r in twin_store.rounds())
        _SEED['model'] = twin_store.current_model()
    if twin_store.current_model() != _SEED['model']:
        twin_store.revert(_SEED['round'])


# --- the model, read from the store ----------------------------------------------

def _area(polygon):
    return abs(sum(polygon[i][0] * polygon[i - 1][1] - polygon[i - 1][0] * polygon[i][1]
                   for i in range(len(polygon)))) / 2


def _walls(model, level=LEVEL):
    b = H.building(model, POOL)
    joints = {j['id']: j['at'] for j in b['joints']}
    out = []
    for w in b['walls']:
        if w.get('level') != level:
            continue
        a, c = joints[w['joints'][0]], joints[w['joints'][1]]
        out.append({'id': w['id'], 'kind': w.get('kind', 'solid'), 'joints': list(w['joints']),
                    'a': list(a), 'b': list(c), 'thickness': w.get('thickness'), 'src': w.get('src') or {}})
    return out


def _joint_at(model, joint_id):
    return next(j['at'] for j in H.building(model, POOL)['joints'] if j['id'] == joint_id)


def _rooms(model, level=LEVEL):
    return {r['id']: r for r in H.building(model, POOL)['rooms'] if r.get('level') == level}


def _on_y(walls, y, tol=1e-6):
    return [w for w in walls if abs(w['a'][1] - y) < tol and abs(w['b'][1] - y) < tol]


def _on_x(walls, x, tol=1e-6):
    return [w for w in walls if abs(w['a'][0] - x) < tol and abs(w['b'][0] - x) < tol]


def _covered_once(walls, axis, lo, hi):
    """Walls on one line cover [lo, hi] exactly once: no gap and no overlap."""
    spans = sorted((min(w['a'][axis], w['b'][axis]), max(w['a'][axis], w['b'][axis])) for w in walls)
    inside = [(max(a, lo), min(b, hi)) for a, b in spans if min(b, hi) - max(a, lo) > 1e-6]
    total = sum(b - a for a, b in inside)
    reach = lo
    for a, b in inside:
        if a > reach + 1e-6:
            return False, ('a gap from', reach, 'to', a, spans)
        reach = max(reach, b)
    if abs(total - (hi - lo)) > 1e-6 or reach < hi - 1e-6:
        return False, ('covered', total, 'of', hi - lo, spans)
    return True, spans


def _near(p, q, tol):
    return math.hypot(p[0] - q[0], p[1] - q[1]) <= tol


def _new_walls(before, after):
    old = {(w['id'], tuple(w['a']), tuple(w['b'])) for w in before}
    return [w for w in after if (w['id'], tuple(w['a']), tuple(w['b'])) not in old]


def _ends_at(wall, point, tol):
    return _near(wall['a'], point, tol) or _near(wall['b'], point, tol)


def _facts():
    """The seeded pool house as this file relies on it."""
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    rooms = _rooms(model)
    check(rooms.get(KITCHEN, {}).get('name') == 'Kitchen', ('the renamed room survives migration', rooms.get(KITCHEN)))
    check(NORTH_ROOM in rooms, 'the north room survives migration')
    walls = _walls(model)
    for axis, value, lo, hi in ((1, 22.0, 0.0, 31.0), (1, 0.0, 0.0, 31.0), (0, 0.0, 0.0, 22.0), (0, 31.0, 0.0, 22.0)):
        line = (_on_y if axis == 1 else _on_x)(walls, value)
        ok, why = _covered_once([w for w in line if w['kind'] != 'separator'], 1 - axis, lo, hi)
        check(ok, ('the outer wall is whole', axis, value, why))
    return model


# --- the page -----------------------------------------------------------------------

def _open(page, served):
    dialogs = []
    page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
    page.set_viewport_size(VIEWPORT)
    H.open_editor(page, served)
    H.choose_floor(page, FLOOR_KEY)
    return dialogs


def _no_errors(served, dialogs):
    check(not dialogs, ('no browser dialogs; use promptInput and showGlobalAlert', dialogs))
    errors = H.unexpected(served.errors())
    check(not errors, errors)


def _tool(page, name):
    """Turn a rail tool on (leave it on when it already is)."""
    button = page.locator(f'#rail-{name}')
    check(button.count() == 1, f'#rail-{name} is on the rail')
    check(button.is_enabled(), f'#rail-{name} can be pressed')
    if button.get_attribute('aria-pressed') != 'true':
        button.click()
    H.settle(page)


def _blur(page):
    page.evaluate('() => document.activeElement && document.activeElement.blur && document.activeElement.blur()')


def _prompt_shown(page):
    return page.locator('#cc-input-modal').is_visible()


def _skip_prompt(page, wait=1.0):
    """Answer Skip if the name prompt shows within `wait` seconds (never required)."""
    deadline = time.time() + wait
    while time.time() < deadline:
        if _prompt_shown(page):
            page.click('#cc-input-cancel-btn')
            H.settle(page)
            return True
        page.wait_for_timeout(50)
    return False


def _answer_prompt(page, name):
    """The name prompt must show (promptInput); type `name`, or Skip when None."""
    page.wait_for_selector('#cc-input-modal', state='visible', timeout=15000)
    words = (page.inner_text('#cc-input-title') + ' ' + page.inner_text('#cc-input-message')).lower()
    check('name' in words, ('the prompt asks for the new room\'s name', words))
    if name is None:
        page.click('#cc-input-cancel-btn')
    else:
        page.fill('#cc-input-field', name)
        page.click('#cc-input-ok-btn')
    page.wait_for_selector('#cc-input-modal', state='hidden', timeout=5000)
    H.settle(page)
    _blur(page)


def _wait_model(pred, what, timeout=20.0):
    deadline = time.time() + timeout
    model = None
    while time.time() < deadline:
        model = H.model()
        if pred(model):
            return model
        time.sleep(0.1)
    raise AssertionError(f'the stored house never showed: {what}')


def _round_id():
    from services import twin_store
    return twin_store.current_id()


def _rounds():
    from services import twin_store
    return twin_store.rounds()


def _still(model_before, page, wait=1.5):
    """Nothing reaches the store for `wait` seconds."""
    count = len(_rounds())
    page.wait_for_timeout(int(wait * 1000))
    check(len(_rounds()) == count, ('no new round', _rounds()[count:]))
    check(H.model() == model_before, 'the stored house did not change')


def _scene_rooms(page):
    return page.evaluate("""(bid) => {
        const b = (window.__twin.plan.buildings || []).find(item => item.id === bid);
        return (b ? b.rooms : []).map(r => ({ id: r.id, name: r.name, level: r.level }));
    }""", POOL)


def _scene_shows(page, pred, what, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred(_scene_rooms(page)):
            H.settle(page)
            return
        page.wait_for_timeout(100)
    raise AssertionError(f'the scene never showed: {what}')


def _drag(page, start, end):
    """A real press, move and release between two building-local points (z 0)."""
    sx, sy = H.screen_of_world(page, *start, 0.0, POOL)
    ex, ey = H.screen_of_world(page, *end, 0.0, POOL)
    H._on_canvas(page, sx, sy)
    H._on_canvas(page, ex, ey)
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move((sx + ex) / 2, (sy + ey) / 2, steps=6)
    page.mouse.move(ex, ey, steps=6)
    page.mouse.up()
    H.settle(page)


def _click(page, x, y):
    H.click_world(page, x, y, 0.0, POOL)


def _dblclick(page, x, y):
    sx, sy = H.screen_of_world(page, x, y, 0.0, POOL)
    H._on_canvas(page, sx, sy)
    page.mouse.dblclick(sx, sy)
    H.settle(page)


def _focus_kitchen(page):
    H.look_down(page, POOL, 14.0, 8.7, height=50.0)
    H.click_world(page, *KITCHEN_FLOOR, POOL)
    deadline = time.time() + 3
    sel = None
    while time.time() < deadline:
        sel = H.editor_state(page, 'selection')
        if sel and sel.get('kind') == 'room' and sel.get('id') == KITCHEN:
            return
        page.wait_for_timeout(50)
    raise AssertionError(('a click on the Kitchen floor focuses the Kitchen', sel))


SPLIT_FROM = (16.0, 0.0)          # on the front wall, between the slider (to 15.08) and the bifold (from 18.67)
SPLIT_TO = (16.0, Y_LOUNGE)       # on the lounge's north wall (x 0-17.75), 1.75 ft from its end joint


def _split_kitchen(page, name):
    """Focus the Kitchen, split it at x = 16 from wall to wall, answer the name prompt."""
    _focus_kitchen(page)
    _tool(page, 'split-room')
    _click(page, *SPLIT_FROM)
    _click(page, *SPLIT_TO)
    _answer_prompt(page, name)


def _split_done(model):
    walls = _walls(model)
    return any(w['kind'] == 'separator' and abs(w['a'][0] - 16.0) < 0.1 and abs(w['b'][0] - 16.0) < 0.1
               for w in walls) and len(_rooms(model)) == 7


def _check_split(before, after, new_name):
    """The split: one separator wall to wall, the Kitchen keeps the larger part, the other is new_name."""
    walls_before, walls_after = _walls(before), _walls(after)
    added = [w for w in _new_walls(walls_before, walls_after) if w['kind'] == 'separator']
    check(len(added) == 1, ('one new separator', added))
    sep = added[0]
    check(sep['thickness'] in (0, 0.0), ('a separator has no thickness', sep))
    ends = sorted([sep['a'], sep['b']], key=lambda p: p[1])
    check(abs(ends[0][1] - 0.0) < 1e-6 and abs(ends[1][1] - Y_LOUNGE) < 1e-6,
          ('the separator runs from the front wall to the lounge wall, snapped onto both lines', ends))
    check(abs(ends[0][0] - 16.0) < 0.1 and abs(ends[1][0] - 16.0) < 0.1 and abs(ends[0][0] - ends[1][0]) < 0.1,
          ('the separator is where it was drawn', ends))
    # Both walls it lands on are split at its ends (a T each), still covering their lines once.
    for joint_id in sep['joints']:
        users = [w for w in walls_after if joint_id in w['joints']]
        check(len(users) == 3, ('the separator end is a T joint on a split wall', _joint_at(after, joint_id),
                                [u['id'] for u in users]))
    for y, lo, hi in ((0.0, 0.0, 31.0), (Y_LOUNGE, 0.0, 17.75)):
        line = [w for w in _on_y(walls_after, y) if w['kind'] != 'separator']
        ok, why = _covered_once(line, 0, lo, hi)
        check(ok, ('the split wall still covers its line once', y, why))
    rooms_before, rooms_after = _rooms(before), _rooms(after)
    check(set(rooms_before) <= set(rooms_after), ('every room keeps its id', set(rooms_before) - set(rooms_after)))
    new_ids = set(rooms_after) - set(rooms_before)
    check(len(new_ids) == 1, ('one new room', new_ids))
    new = rooms_after[new_ids.pop()]
    kitchen = rooms_after[KITCHEN]
    check(kitchen['name'] == 'Kitchen', ('the larger part keeps the Kitchen\'s name', kitchen['name']))
    check(new['name'] == new_name, ('the other part is named as answered', new['name'], new_name))
    whole = _area(rooms_before[KITCHEN]['polygon'])
    west = 16.0 * Y_LOUNGE
    check(abs(_area(kitchen['polygon']) - west) < 2.5, ('the Kitchen is the west part', _area(kitchen['polygon']), west))
    check(abs(_area(new['polygon']) - (whole - west)) < 2.5, ('the new room is the east part', _area(new['polygon']), whole - west))
    check(abs(_area(kitchen['polygon']) + _area(new['polygon']) - whole) < 0.5,
          ('the two parts make the whole Kitchen', _area(kitchen['polygon']), _area(new['polygon']), whole))
    for rid, room in rooms_before.items():
        if rid != KITCHEN:
            check(rooms_after[rid].get('name') == room.get('name'), ('other rooms keep their names', rid))
    return new


def _diff(a, b):
    """Short description of where two models differ (for failure messages)."""
    if a == b:
        return None
    out = []
    for ba, bb in zip(a.get('buildings', []), b.get('buildings', [])):
        for key in sorted(set(ba) | set(bb)):
            if ba.get(key) != bb.get(key):
                out.append(f"{ba.get('id')}.{key}")
    keys = [k for k in sorted(set(a) | set(b)) if k != 'buildings' and a.get(k) != b.get(k)]
    return out + keys


# --- scenarios --------------------------------------------------------------------------

def scenario_draw_room_beside_room_shares_a_wall():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        H.look_down(page, POOL, 8.0, 27.0, height=40.0)
        before = H.model()
        # A 12 x 10 ft room outside the north wall (y = 22). The drag starts
        # 0.3 ft off the wall line and snaps onto it.
        _tool(page, 'draw-room')
        _drag(page, (2.0, 22.3), (14.0, 32.0))
        _skip_prompt(page)
        after = _wait_model(lambda m: len(_rooms(m)) == len(_rooms(before)) + 1, 'a new room on L1')
        walls = _walls(after)

        line = [w for w in _on_y(walls, 22.0) if w['kind'] != 'separator']
        ok, why = _covered_once(line, 0, 0.0, 31.0)
        check(ok, ('the shared line y = 22 has one wall wherever it runs, never two', why))
        check(any(abs(w['a'][0] - 2.0) < 0.1 or abs(w['b'][0] - 2.0) < 0.1 for w in line)
              and any(abs(w['a'][0] - 14.0) < 0.1 or abs(w['b'][0] - 14.0) < 0.1 for w in line),
              ('the north wall is split where the new room meets it', [(w['a'], w['b']) for w in line]))

        added = [w for w in _new_walls(_walls(before), walls) if w not in line]
        outside = [w for w in added if max(w['a'][1], w['b'][1]) > 22.5]
        check(len(outside) == 3, ('three new walls for the room\'s three free sides', [(w['a'], w['b']) for w in outside]))
        for w in outside:
            check(w['kind'] == 'solid', ('drawn walls are solid', w))
        sides = sorted(outside, key=lambda w: (min(w['a'][0], w['b'][0]), min(w['a'][1], w['b'][1])))
        check(any(abs(w['a'][0] - 2.0) < 0.1 and abs(w['b'][0] - 2.0) < 0.1 for w in sides)
              and any(abs(w['a'][0] - 14.0) < 0.1 and abs(w['b'][0] - 14.0) < 0.1 for w in sides)
              and any(abs(w['a'][1] - 32.0) < 0.1 and abs(w['b'][1] - 32.0) < 0.1 for w in sides),
              ('the sides at x 2, x 14 and y 32', [(w['a'], w['b']) for w in sides]))
        for w in sides:
            low = w['a'] if w['a'][1] < w['b'][1] else w['b']
            if low[1] < 22.5:
                check(abs(low[1] - 22.0) < 1e-6, ('a side wall starts exactly on the north wall (snapped)', w))

        rooms = _rooms(after)
        new_id = (set(rooms) - set(_rooms(before))).pop()
        new = rooms[new_id]
        check(new['name'] == 'Room', ('a drawn room is named Room', new['name']))
        check(abs(_area(new['polygon']) - 120.0) < 2.0, ('the new room is 12 x 10 ft', _area(new['polygon'])))
        check(all(abs(p[1] - 22.0) < 0.02 or abs(p[1] - 32.0) < 0.1 for p in new['polygon']), new['polygon'])
        check(rooms[NORTH_ROOM]['name'] == 'Room'
              and abs(_area(rooms[NORTH_ROOM]['polygon']) - _area(_rooms(before)[NORTH_ROOM]['polygon'])) < 0.05,
              ('the room behind the shared wall keeps its id and its size', rooms[NORTH_ROOM]))
        check(rooms[KITCHEN]['name'] == 'Kitchen', 'the Kitchen is untouched')
        check(all(w['src'].get('person') for w in outside), ('drawn walls are the person\'s', [w['src'] for w in outside]))

        _scene_shows(page, lambda rs: any(r['id'] == new_id for r in rs), 'the new room in the scene')
        _no_errors(s, dialogs)


def scenario_draw_room_polygon_closes_on_its_first_point():
    # Brief: draw room is also a polygon by clicks, closed on its first point.
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        H.look_down(page, POOL, -4.0, 18.0, height=40.0)
        before = H.model()
        # An L outside the west wall (x = 0), between the window (to y 14.17)
        # and the lounge wall's joint (y 17.33) / the corner (y 22).
        corners = [(0.0, 15.0), (-8.0, 15.0), (-8.0, 21.0), (-4.0, 21.0), (-4.0, 19.0), (0.0, 19.0)]
        count = len(_rounds())
        _tool(page, 'draw-room')
        for x, y in corners:
            _click(page, x, y)
        page.wait_for_timeout(500)
        check(len(_rounds()) == count and H.model() == before, 'nothing is stored before the polygon closes')
        _click(page, *corners[0])
        _skip_prompt(page)
        after = _wait_model(lambda m: len(_rooms(m)) == len(_rooms(before)) + 1, 'a new room on L1')
        rooms = _rooms(after)
        new = rooms[(set(rooms) - set(_rooms(before))).pop()]
        check(new['name'] == 'Room', new['name'])
        check(abs(_area(new['polygon']) - 40.0) < 2.0, ('the L is 8 x 4 plus 4 x 2 ft', _area(new['polygon'])))
        check(len(new['polygon']) == 6, ('six corners', new['polygon']))
        for corner in corners:
            check(any(_near(p, corner, 0.12) for p in new['polygon']), ('each clicked corner', corner, new['polygon']))
        walls = _walls(after)
        line = [w for w in _on_x(walls, 0.0) if w['kind'] != 'separator']
        ok, why = _covered_once(line, 1, 0.0, 22.0)
        check(ok, ('the west wall line has one wall wherever it runs, never two', why))
        window = next(o for o in H.building(after, POOL)['openings'] if o['id'] == 'opening:4009c0058fbc4f09bd0edbc4b2b0e4b5')
        host = next(w for w in walls if w['id'] == window['wall'])
        check(abs(host['a'][0]) < 1e-6 and abs(host['b'][0]) < 1e-6 and min(host['a'][1], host['b'][1]) < 3.5
              and max(host['a'][1], host['b'][1]) > 14.1, ('the west window keeps a wall that holds it', host))
        check(rooms[KITCHEN]['name'] == 'Kitchen' and rooms[NORTH_ROOM]['name'] == 'Room', 'neighbours keep their names')
        _no_errors(s, dialogs)


def scenario_draw_wall_chain_joins_corners():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        before = H.model()
        kitchen_area = _area(_rooms(before)[KITCHEN]['polygon'])

        # Chain 1, ended with Escape: from the middle wall (y 12.17) down to
        # (22, 4) and across to the east wall (x 31), cutting a 9 x 8.17 ft
        # corner off the Kitchen.
        H.look_down(page, POOL, 25.0, 8.0, height=40.0)
        p1, p2, p3 = (22.0, Y_MID), (22.0, 4.0), (31.0, 4.0)
        _tool(page, 'draw-wall')
        _click(page, *p1)
        _click(page, *p2)
        _click(page, *p3)
        _skip_prompt(page)
        H.press(page, 'Escape')
        _skip_prompt(page)
        after = _wait_model(lambda m: len(_new_walls(_walls(before), _walls(m))) >= 2
                            and len(_rooms(m)) == len(_rooms(before)) + 1, 'the chain closes a room')
        walls = _walls(after)
        first = [w for w in walls if _ends_at(w, p1, 0.1) and _ends_at(w, p2, 0.1)]
        second = [w for w in walls if _ends_at(w, p2, 0.1) and _ends_at(w, p3, 0.1)]
        check(len(first) == 1 and len(second) == 1, ('one wall per segment', first, second))
        check(first[0]['kind'] == 'solid' and second[0]['kind'] == 'solid', 'drawn walls are solid')
        shared = set(first[0]['joints']) & set(second[0]['joints'])
        check(len(shared) == 1, ('the chain\'s corner is one joint both walls share', first[0]['joints'], second[0]['joints']))
        corner = _joint_at(after, shared.pop())
        check(_near(corner, p2, 0.1), ('the corner is where it was clicked', corner))
        start = next(j for j in first[0]['joints'] if j not in second[0]['joints'])
        end = next(j for j in second[0]['joints'] if j not in first[0]['joints'])
        check(abs(_joint_at(after, start)[1] - Y_MID) < 1e-6, ('the chain starts on the middle wall', _joint_at(after, start)))
        check(abs(_joint_at(after, end)[0] - 31.0) < 1e-6, ('the chain ends on the east wall', _joint_at(after, end)))
        for joint_id, what in ((start, 'middle'), (end, 'east')):
            users = [w for w in walls if joint_id in w['joints']]
            check(len(users) == 3, (f'the chain T-joins the {what} wall, which splits there', [u['id'] for u in users]))
        for line, axis, lo, hi in ((_on_y(walls, Y_MID), 0, 17.75, 31.0), (_on_x(walls, 31.0), 1, 0.0, 22.0)):
            ok, why = _covered_once([w for w in line if w['kind'] != 'separator'], axis, lo, hi)
            check(ok, ('a split wall still covers its line once', why))
        rooms = _rooms(after)
        new = rooms[(set(rooms) - set(_rooms(before))).pop()]
        cut = 9.0 * (Y_MID - 4.0)
        check(abs(_area(new['polygon']) - cut) < 2.0, ('the cut corner is a room', _area(new['polygon']), cut))
        check(new['name'] == 'Room', new['name'])
        check(rooms[KITCHEN]['name'] == 'Kitchen' and abs(_area(rooms[KITCHEN]['polygon']) - (kitchen_area - cut)) < 2.0,
              ('the Kitchen keeps its name on the larger part', _area(rooms[KITCHEN]['polygon']), kitchen_area - cut))

        # Chain 2, ended with a double click: one wall across the north room
        # at x = 2. Escape ended chain 1, so nothing joins p3 to q1.
        middle = H.model()
        H.look_down(page, POOL, 6.0, 19.5, height=40.0)
        q1, q2 = (2.0, Y_LOUNGE), (2.0, 22.0)
        _tool(page, 'draw-wall')
        _click(page, *q1)
        _dblclick(page, *q2)
        _skip_prompt(page)
        after2 = _wait_model(lambda m: len(_rooms(m)) == len(_rooms(middle)) + 1, 'the double-clicked wall splits the north room')
        added = _new_walls(_walls(middle), _walls(after2))
        drawn = [w for w in added if _ends_at(w, q1, 0.1) and _ends_at(w, q2, 0.1)]
        check(len(drawn) == 1, ('one wall from q1 to q2', [(w['a'], w['b']) for w in added]))
        check(not any(_ends_at(w, p3, 0.1) and _ends_at(w, q1, 0.5) for w in added), 'Escape ended the first chain')
        check(all(math.hypot(w['b'][0] - w['a'][0], w['b'][1] - w['a'][1]) >= 1.0 for w in _walls(after2)),
              'the double click adds no zero-length wall')
        north = _rooms(after2)[NORTH_ROOM]
        check(north['name'] == 'Room' and abs(_area(north['polygon']) - 15.75 * (22.0 - Y_LOUNGE)) < 1.5,
              ('the north room keeps its id on its larger part', _area(north['polygon'])))

        # The double click ended chain 2: a further click adds no wall.
        settled = H.model()
        _click(page, 8.0, 19.0)
        _still(settled, page)
        H.press(page, 'Escape')
        _no_errors(s, dialogs)


def scenario_split_room_makes_two_rooms():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        before = H.model()
        _split_kitchen(page, None)   # Skip keeps 'Room'
        after = _wait_model(_split_done, 'the Kitchen split in two')
        new = _check_split(before, after, 'Room')
        _scene_shows(page, lambda rs: any(r['id'] == new['id'] for r in rs), 'the new room in the scene')
        _no_errors(s, dialogs)


def scenario_undo_restores_walls_rooms_and_names_after_a_split():
    # Review Focus 4: undo after an operation that split walls and re-derived
    # rooms brings the walls, rooms and names back exactly.
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        before, before_round = H.model(), _round_id()
        _split_kitchen(page, 'Pantry')
        after = _wait_model(lambda m: any(r.get('name') == 'Pantry' for r in _rooms(m).values()), 'the new room named Pantry')
        _check_split(before, after, 'Pantry')
        _scene_shows(page, lambda rs: any(r['name'] == 'Pantry' for r in rs), 'Pantry in the scene')

        page.click('#rail-undo')
        _blur(page)
        restored = _wait_model(lambda m: not any(r.get('name') == 'Pantry' for r in _rooms(m).values())
                               and not _split_done(m), 'the split undone')
        page.wait_for_timeout(500)
        restored = H.model()
        check(restored == before, ('one undo brings the house back exactly', _diff(restored, before)))
        check(_round_id() != before_round and _rounds()[-1]['kind'] == 'revert',
              ('undo reverts to the earlier round as a new round (P5)', _rounds()[-1]))
        check(_walls(restored) == _walls(before), 'the walls, their joints and ids are back')
        check({rid: r.get('name') for rid, r in _rooms(restored).items()} == {rid: r.get('name') for rid, r in _rooms(before).items()},
              'the rooms and their names are back')
        _scene_shows(page, lambda rs: not any(r['name'] == 'Pantry' for r in rs)
                     and {r['id'] for r in rs if r['level'] == LEVEL} == set(_rooms(before)), 'the scene back on the old rooms')
        _no_errors(s, dialogs)


def scenario_redo_reapplies():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        before = H.model()
        _split_kitchen(page, None)
        split = _wait_model(_split_done, 'the Kitchen split in two')
        page.wait_for_timeout(500)
        split = H.model()
        _check_split(before, split, 'Room')

        steps = [('Control+z', before, 'Ctrl+Z undoes'), ('Control+y', split, 'Ctrl+Y redoes'),
                 ('Control+z', before, 'Ctrl+Z undoes again'), ('Control+Shift+Z', split, 'Ctrl+Shift+Z redoes'),
                 ('Control+z', before, 'and undoes once more'), ('#rail-redo', split, 'the Redo button redoes')]
        for key, want, what in steps:
            count = len(_rounds())
            _blur(page)
            if key.startswith('#'):
                page.click(key)
            else:
                H.press(page, key)
            got = _wait_model(lambda m, want=want: m == want and len(_rounds()) > count, what)
            check(got == want, (what, _diff(got, want)))
            check(_rounds()[-1]['kind'] == 'revert', (what, 'through a revert (P5)', _rounds()[-1]))
        _scene_shows(page, lambda rs: len([r for r in rs if r['level'] == LEVEL]) == 7, 'the redone split in the scene')

        # Nothing left to redo: Ctrl+Y does nothing.
        _blur(page)
        H.press(page, 'Control+y')
        _still(split, page)
        _no_errors(s, dialogs)


def scenario_undo_is_off_while_a_build_runs():
    # Brief and P5: the undo keys and buttons are off while a build is active
    # (api.active). The build is faked in the page, as the older editor
    # scenarios do; the server sees no build, so only the editor can refuse.
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        before = H.model()
        _split_kitchen(page, None)
        _wait_model(_split_done, 'the Kitchen split in two')
        page.wait_for_timeout(500)
        split = H.model()

        def build(state):
            body = json.dumps({'id': 'b-t13', 'state': state, 'steps': [], 'events': [], 'seq': 0, 'cost': 0})
            page.unroute('**/api/house/editor/build/b-t13**')
            page.route('**/api/house/editor/build/b-t13**', lambda route: route.fulfill(
                status=200, headers={'Content-Type': 'application/json'}, body=body))

        page.route('**/api/house/editor/build/b-t13**', lambda route: route.fulfill(status=404, body='{}'))
        build('running')
        page.evaluate("() => window.__editor.followBuild('b-t13')")
        page.wait_for_function("() => window.__editor.build() && window.__editor.build().state === 'running'", timeout=10000)
        H.settle(page)
        check(page.is_disabled('#rail-undo'), 'the Undo button is off while a build runs')
        _blur(page)
        H.press(page, 'Control+z')
        _still(split, page)

        build('stopped')
        page.wait_for_function("() => !window.__editor.build() || window.__editor.build().state === 'stopped'", timeout=15000)
        H.settle(page)
        check(page.is_enabled('#rail-undo'), 'the Undo button is back once the build stops')
        _blur(page)
        H.press(page, 'Control+z')
        got = _wait_model(lambda m: m == before, 'the split undone after the build stopped')
        check(got == before, _diff(got, before))
        _no_errors(s, dialogs)


CHANGED_SINCE = 'Something else changed the house since; use the timeline to go back.'


def scenario_undo_refuses_after_another_change():
    # Final wave I5: a round the editor did not make (Argyle, a build, another
    # parent) since the step: undo and redo refuse in words and never revert
    # over it; the timeline keeps every round.
    from services import twin_edit
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        _split_kitchen(page, None)
        _wait_model(_split_done, 'the Kitchen split in two')
        page.wait_for_timeout(500)
        twin_edit.save({'op': 'set', 'building': POOL, 'id': NORTH_ROOM, 'field': 'name', 'value': 'Studio'},
                       'p1', 'Argyle renamed it')
        later = H.model()
        check(_rooms(later)[NORTH_ROOM]['name'] == 'Studio', 'the outside change is stored')
        for key in ('Control+z', '#rail-undo'):
            _blur(page)
            if key.startswith('#'):
                page.click(key)
            else:
                H.press(page, key)
            deadline = time.time() + 10
            while time.time() < deadline and not page.locator('#cc-alert-modal').is_visible():
                page.wait_for_timeout(100)
            check(page.locator('#cc-alert-modal').is_visible()
                  and page.inner_text('#cc-alert-message').strip() == CHANGED_SINCE,
                  ('undo refuses in words', key, page.locator('#cc-alert-modal').is_visible()))
            _still(later, page)
            page.evaluate("() => { const m = document.getElementById('cc-alert-modal'); m.classList.add('hidden'); m.classList.remove('flex'); }")
        check(_rooms(H.model())[NORTH_ROOM]['name'] == 'Studio' and _split_done(H.model()),
              'the later change and the split both stand')
        _no_errors(s, dialogs)


def scenario_plan_mode_is_gone_and_top_camera_draws():
    s = _serve()
    if s is None:
        return
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        requests = []
        page.on('request', lambda r: requests.append(r.url))
        dialogs = _open(page, s)
        check(page.locator('#rail-plan').count() == 0, 'the Plan button is gone')
        check(page.locator('#plan-tools').count() == 0 and page.locator('[id^="plan-add-"]').count() == 0,
              'the Plan mode tools are gone')
        for rid in RAIL + ['rail-sheet']:
            check(page.locator(f'#{rid}').count() == 1 and page.locator(f'#{rid}').is_visible(), f'#{rid} is on the rail')
        check(not any('plan_view.js' in url for url in requests), ('plan_view.js is never loaded', [u for u in requests if 'plan_view' in u]))
        check('plan_view' not in page.evaluate("() => [...document.querySelectorAll('script[type=importmap]')].map(s => s.textContent).join('')"),
              'plan_view is not in the import map')

        page.click('#editor-cameras [data-editor-camera="top"]')
        H.settle(page)
        check(page.evaluate('() => window.__twin.state.camera') == 'top', 'the Top camera is on')
        H.look_down(page, POOL, 8.5, 11.0, height=40.0)
        check(page.evaluate('() => window.__twin.state.camera') == 'top', 'still the Top camera, framed on the Kitchen')
        before = H.model()

        # Plan mode's Add wall, now Draw wall from the Top camera: a free wall
        # in the Kitchen, straightened by the right-angle snap.
        _tool(page, 'draw-wall')
        _click(page, 5.0, 6.0)
        _dblclick(page, 12.0, 6.3)
        _skip_prompt(page)
        after = _wait_model(lambda m: len(_new_walls(_walls(before), _walls(m))) == 1, 'the drawn wall')
        wall = _new_walls(_walls(before), _walls(after))[0]
        check(wall['kind'] == 'solid', wall)
        check(abs(wall['a'][1] - wall['b'][1]) < 1e-6, ('snapped straight', wall))
        check(_ends_at(wall, (5.0, 6.0), 0.12) and _ends_at(wall, (12.0, 6.0), 0.12), ('where it was drawn', wall))
        H.press(page, 'Escape')

        # Plan mode's Add window: a click on the new wall drops a 3 ft window on it.
        _tool(page, 'add-window')
        _click(page, 8.5, 6.0)
        after = _wait_model(lambda m: len(H.building(m, POOL)['openings']) == len(H.building(before, POOL)['openings']) + 1,
                            'the added window')
        opening = next(o for o in H.building(after, POOL)['openings']
                       if o['id'] not in {x['id'] for x in H.building(before, POOL)['openings']})
        check(opening['kind'] == 'window' and opening.get('wall') == wall['id'] and abs(opening['width'] - 3.0) < 1e-6,
              ('a 3 ft window on the drawn wall', opening))
        along = math.hypot(8.5 - wall['a'][0], 6.0 - wall['a'][1])
        check(abs(opening['at'] - along) < 0.3, ('dropped where it was clicked', opening['at'], along))

        # Plan mode's Add door, on an existing wall: the lounge's north wall.
        _tool(page, 'add-door')
        _click(page, 8.0, Y_LOUNGE)
        known = {o['id'] for o in H.building(after, POOL)['openings']}
        later = _wait_model(lambda m: len(H.building(m, POOL)['openings']) == len(known) + 1, 'the added door')
        door = next(o for o in H.building(later, POOL)['openings'] if o['id'] not in known)
        host = next(w for w in _walls(later) if w['id'] == door.get('wall'))
        check(door['kind'] == 'door' and abs(door['width'] - 3.0) < 1e-6, ('a 3 ft door', door))
        check(abs(host['a'][1] - Y_LOUNGE) < 1e-6 and abs(host['b'][1] - Y_LOUNGE) < 1e-6,
              ('on the lounge\'s north wall', host))
        along = abs(8.0 - host['a'][0])
        check(abs(door['at'] - along) < 0.3, ('dropped where it was clicked', door['at'], along))
        _no_errors(s, dialogs)


SCENARIOS = [
    scenario_draw_room_beside_room_shares_a_wall,
    scenario_draw_room_polygon_closes_on_its_first_point,
    scenario_draw_wall_chain_joins_corners,
    scenario_split_room_makes_two_rooms,
    scenario_undo_restores_walls_rooms_and_names_after_a_split,
    scenario_redo_reapplies,
    scenario_undo_is_off_while_a_build_runs,
    scenario_undo_refuses_after_another_change,
    scenario_plan_mode_is_gone_and_top_camera_draws,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
