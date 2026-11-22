"""Multiselect and clipboard acceptance in real Chromium (Task 5 of
docs/superpowers/plans/2026-11-19-editor-multiselect-clipboard.md).

Run from chauffeur/: python tests/test_twin_multiselect_live.py

Every scenario starts from a fresh served household (twin_store.start_over and
the household round pushed again) in a fresh browser context. A person's
gestures are real Chromium input: clicks, Ctrl-clicks, marquee drags, gizmo
drags, right-click menus and Ctrl+C/X/V/D/Z keys. The editor hook
(window.__twinEditor) and window.__twin only position the camera and read the
results. Each scenario saves one screenshot into a temp folder printed at start.
"""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from uuid import uuid4

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_multiselect_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_twin_library_assign_live as L  # noqa: E402  (sets its own scratch data dir before any service import)
import twin_edit_measure as M  # noqa: E402
import house_editor_model_harness as H  # noqa: E402
from live_app import live_app  # noqa: E402

SERVED = None
TIMEOUT = 40000
QUERY = 'tier=low&test=1&timing=1'
FT = 0.3048
SHOTS = Path(tempfile.mkdtemp(prefix='multiselect_live_shots_'))
BID = 'main-house'
# Fixture walls on main-house L1 (the flat plan the editor draws); each faces +x, outside.
GARAGE_EAST = 'wall:66d9683b676a4851865c97fed7cf14be'    # [59,0]-[59,22], 22 ft, a 16 ft garage door at 11
WING_EAST = 'wall:6285929ad87644f8a4a5ddc68b8bccf3'      # [70,22]-[70,42], 20 ft, a door and a garage door
NORTH_EAST = 'wall:d6209c7f57c04df191cddae6b3060259~2'   # [59,52.8]-[59,65.3], 12.5 ft, no openings
PORCH_WINDOW_WALL = 'wall:ce253aeb0c0540028a1d4eecf3e551a3'  # [22.7,13.3]-[37,13.3], a 6 ft window at 7.3
EAST = [1, 0]
EAST_EYE, EAST_TARGET = [125, 33, 25], [59, 33, 4]       # building-local feet, out over the driveway
LAWN = [20, 124]                                          # clear lawn in lot feet (west of the pool)


# --- page -------------------------------------------------------------------

def _wait(page, expression, arg=None, timeout=TIMEOUT):
    page.wait_for_function(expression, arg=arg, timeout=timeout, polling=200)


def _settled(page):
    L._settled(page)


def _material(name, tint):
    from services import twin_materials
    return twin_materials.create({'name': f'{name} {uuid4().hex[:5]}', 'params': {
        'tint': tint, 'roughness': 1, 'metalness': 0}}, H.PARENT['id'])


@contextmanager
def _page(seed=None, viewport=(1600, 1000)):
    """Fresh household (plus `seed`), a fresh browser, the editor open with Select."""
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; multiselect checks skipped') from error
    from services import twin_store
    twin_store.start_over()
    M._prepare(None)
    data = seed() if seed else {}
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; multiselect checks skipped')
    browser = SERVED.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
            page.set_default_timeout(TIMEOUT)
            page.set_default_navigation_timeout(TIMEOUT)
            net = {'ops': [], 'reverts': [], 'dialogs': []}

            def record(request):
                url = request.url.split('?')[0]
                if request.method != 'POST':
                    return
                if url.endswith('/api/house/editor/op'):
                    net['ops'].append(request.post_data_json['op'])
                elif url.endswith('/revert'):
                    net['reverts'].append(request.post_data_json)
            page.on('request', record)
            page.on('dialog', lambda dialog: (net['dialogs'].append(dialog.type), dialog.dismiss()))
            H.signed_in(page)
            page.goto(SERVED.url(f'house/editor?{QUERY}'), timeout=TIMEOUT)
            _wait(page, 'window.__editor?.ready === true && !!window.__twinEditor && window.__twin?.ready')
            H.settle(page, 4)
            if page.locator('#editor-dialog').is_visible():
                page.click('#editor-dialog-close')
                page.locator('#editor-dialog').wait_for(state='hidden')
            M._dismiss_alert(page)
            M._track_view_work(page)
            page.evaluate('window.__twin.controls.enableDamping = false')
            page.click('#rail-select')
            _settled(page)
            net['ops'].clear(); net['reverts'].clear()
            yield page, data, net
            assert not net['dialogs'], f'a browser dialog opened: {net["dialogs"]}'
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; multiselect checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _shot(page, name):
    path = SHOTS / f'{name}.png'
    page.screenshot(path=str(path), animations='disabled')
    return path


def _plan(page):
    return page.evaluate('window.__twin.plan')


def _members(page):
    return page.evaluate('window.__twinEditor.selectionStore.members()')


def _status(page):
    return page.inner_text('#editor-status').strip()


def _building(plan, bid=BID):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _wall(plan, wall_id, bid=BID):
    return next(w for w in _building(plan, bid)['walls'] if w['id'] == wall_id)


def _openings(plan, wall_id, bid=BID):
    return [o for o in _building(plan, bid)['openings'] if o.get('wall') == wall_id]


def _planting(plan, pid):
    return next((p for p in plan['site']['planting'] if p['id'] == pid), None)


# --- pointer and keys ---------------------------------------------------------

def _look_lot(page, at, height=70.0):
    """A camera straight above a lot point (lot feet), looking down."""
    page.evaluate("""([x, y, h]) => {
        const v = window.__twin, ft = .3048;
        if (v.cameraKind() !== 'perspective') v.setCamera('front');
        v.setCameraState({position: [x * ft, h * ft, -(y - .01) * ft], target: [x * ft, 0, -y * ft]});
        v.camera.updateMatrixWorld(true);
    }""", [at[0], at[1], height])
    H.settle(page, 3)


def _pixel_lot(page, point):
    return page.evaluate("""p => {
        const v = window.__twin, r = v.renderer3.domElement.getBoundingClientRect();
        v.camera.updateMatrixWorld(true);
        const q = v.camera.position.clone().set(p[0] * .3048, (p[2] || 0) * .3048, -p[1] * .3048).project(v.camera);
        return [r.left + (q.x + 1) * r.width / 2, r.top + (1 - q.y) * r.height / 2];
    }""", list(point))


def _click(page, pixel, ctrl=False, button='left'):
    H._on_canvas(page, *pixel)
    if ctrl:
        page.keyboard.down('Control')
    try:
        page.mouse.click(*pixel, button=button)
    finally:
        if ctrl:
            page.keyboard.up('Control')
    H.settle(page, 2)


def _key(page, combo):
    page.keyboard.press(combo)
    H.settle(page, 2)


def _quiet(page):
    page.wait_for_timeout(350)
    _settled(page)


def _await_op(page, action):
    """Run `action` and wait for the editor op response; returns the response."""
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and r.url.split('?')[0].endswith('/api/house/editor/op'), timeout=TIMEOUT) as pending:
        action()
    response = pending.value
    assert response.status == 200, (response.status, response.text())
    _quiet(page)
    return response


def _undo(page, net):
    """One real Ctrl+Z after the step is on the undo stack; waits for its revert to show."""
    _wait(page, "() => !document.getElementById('rail-undo').disabled")
    before = H.scene_signature(page)
    reverts = len(net['reverts'])
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/revert'),
                              timeout=TIMEOUT) as pending:
        page.keyboard.press('Control+z')
    assert pending.value.status == 200, pending.value.text()
    H.wait_rebuilt(page, before)
    _quiet(page)
    assert len(net['reverts']) == reverts + 1, net['reverts']


def _wall_pixel(page, wall_id, normal, fractions=(.5, .4, .6, .3, .7, .2, .8, .15, .85), heights=(.5, .7, .3, .85),
                bid=BID):
    """A client pixel on a wall's face (building-local normal) where the view picks that wall."""
    plan = _plan(page)
    b, w = _building(plan, bid), _wall(plan, wall_id, bid)
    level = next(l for l in b['levels'] if l['id'] == w['level'])
    height = w.get('height') or level.get('ceiling', 8)
    off = (w.get('thickness') or .33) / 2 + .02
    for fraction in fractions:
        for h in heights:
            local = [w['from'][i] + (w['to'][i] - w['from'][i]) * fraction + normal[i] * off for i in (0, 1)]
            pixel = H.screen_of_world(page, *local, level.get('elevation', 0) + height * h, bid)
            pixel = [round(v) for v in pixel]
            if page.evaluate("""({p, id, bid}) => {
                const v = window.__twin, [x, y] = p, r = v.renderer3.domElement.getBoundingClientRect();
                if (x < r.left + 4 || x > r.right - 4 || y < r.top + 4 || y > r.bottom - 4) return false;
                const hit = v.pick(x, y);
                return document.elementFromPoint(x, y) === v.renderer3.domElement && hit?.kind === 'wall'
                    && (hit.id || hit.pieceId) === id && (hit.building || hit.buildingId) === bid;
            }""", {'p': pixel, 'id': wall_id, 'bid': bid}):
                return pixel, fraction
    raise AssertionError(f'no visible pixel on {wall_id}')


def _floor_view(page, key=f'{BID}:L1'):
    H.choose_floor(page, key)
    _settled(page)


def _library_select(page, asset):
    L._library(page)
    L._select_asset(page, asset)


# --- 1. Ctrl-click three walls, one Library material, one undo ------------------

def scenario_ctrl_click_walls_assign_material_one_undo():
    seed = lambda: {'blue': _material('MS wall blue', '#1840ff')}
    with _page(seed) as (page, data, net):
        H.look_at(page, BID, EAST_EYE, EAST_TARGET)
        walls = [GARAGE_EAST, WING_EAST, NORTH_EAST]
        before = {wid: _wall(_plan(page), wid).get('faces') for wid in walls}
        for wid in walls:
            pixel, _ = _wall_pixel(page, wid, EAST)
            _click(page, pixel, ctrl=True)
        members = _members(page)
        assert sorted(m['pieceId'] for m in members) == sorted(walls) and all(m['kind'] == 'wall' for m in members), members
        assert page.inner_text('#piece-card h3').strip() == 'Selected pieces'
        assert page.inner_text('#piece-card [data-selection-summary]').strip() == '3 walls'
        assert net['ops'] == [], f'selecting sent an edit: {net["ops"]}'
        _library_select(page, data['blue'])
        row = page.locator('#piece-card [data-library-slot^="Outside"]')
        assert row.count() == 1, page.locator('#piece-card [data-library-slot]').evaluate_all('n => n.map(x => x.dataset.librarySlot)')
        use = row.get_by_role('button', name=f'Use {data["blue"]["name"]}', exact=True)
        _await_op(page, use.click)
        assert len(net['ops']) == 1 and net['ops'][0]['op'] == 'batch', net['ops']
        assert len(net['ops'][0]['ops']) == 3, net['ops'][0]
        plan = _plan(page)
        for wid in walls:
            faces = _wall(plan, wid).get('faces') or {}
            blue = [side for side, ref in faces.items() if (ref or {}).get('id') == data['blue']['id']]
            assert len(blue) == 1, (wid, faces)
        _shot(page, '01_three_walls_blue')
        _undo(page, net)
        plan = _plan(page)
        assert {wid: _wall(plan, wid).get('faces') for wid in walls} == before, 'one undo did not restore all three walls'
        assert len(net['ops']) == 1, net['ops']


# --- 2. Marquee plants, gizmo drag, one undo ------------------------------------

def _seed_shrub_grid():
    """Twelve shrubs (4 x 3, 4 ft apart) on clear lawn, copied from a household shrub."""
    from services import twin_store
    ids = []

    def add(plan):
        shrub = next(p for p in plan['site']['planting'] if p['kind'] == 'shrub')
        for row in range(3):
            for col in range(4):
                pid = f'plant:ms-grid-{row}{col}-{uuid4().hex[:6]}'
                plan['site']['planting'].append({**shrub, 'id': pid, 'at': [LAWN[0] - 6 + 4 * col, LAWN[1] - 4 + 4 * row]})
                ids.append(pid)
        return plan
    twin_store.update_current(add, 'build')
    return {'grid': ids}


def scenario_marquee_plants_gizmo_drag_one_undo():
    with _page(_seed_shrub_grid) as (page, data, net):
        plan = _plan(page)
        row = [_planting(plan, pid) for pid in data['grid']]
        assert all(row), row
        centre = [LAWN[0], LAWN[1]]
        _look_lot(page, centre, height=75)
        start, end = _pixel_lot(page, [LAWN[0] - 13, LAWN[1] - 11]), _pixel_lot(page, [LAWN[0] + 13, LAWN[1] + 11])
        for point in (start, end):
            H._on_canvas(page, *point)
        page.mouse.move(*start)
        page.mouse.down()
        try:
            page.mouse.move(*end, steps=12)
            H.settle(page, 2)
            assert page.get_attribute('#editor-drag-outline', 'points'), 'the marquee rectangle was not drawn'
        finally:
            page.mouse.up()
        _quiet(page)
        members = _members(page)
        assert sorted(m['pieceId'] for m in members) == sorted(p['id'] for p in row), members
        assert net['ops'] == [], net['ops']
        page.click('#rail-move')
        H.settle(page, 4)
        box = page.locator('[data-gizmo="gizmo_move_x"]').first.bounding_box()
        assert box, 'no Move gizmo for the set'
        grip = [box['x'] + box['width'] / 2, box['y'] + box['height'] / 2]
        a, b = _pixel_lot(page, centre), _pixel_lot(page, [centre[0] + 6, centre[1]])
        target = [grip[0] + b[0] - a[0], grip[1] + b[1] - a[1]]
        frames = []

        def drag():
            page.mouse.move(*grip)
            page.mouse.down()
            for k in range(1, 11):
                page.mouse.move(grip[0] + (target[0] - grip[0]) * k / 10, grip[1] + (target[1] - grip[1]) * k / 10)
                H.settle(page, 1)
                value = H.editor_state(page, 'lastDragFrameMs')
                if isinstance(value, (int, float)) and math.isfinite(value):
                    frames.append(value)
            assert net['ops'] == [], f'a drag frame sent an edit: {net["ops"]}'
            page.mouse.up()
        _await_op(page, drag)
        assert len(net['ops']) == 1 and net['ops'][0]['op'] == 'batch' and len(net['ops'][0]['ops']) == len(row), net['ops']
        moved = _plan(page)
        deltas = []
        for p in row:
            now = _planting(moved, p['id'])
            deltas.append(now['at'][0] - p['at'][0])
            assert abs(now['at'][1] - p['at'][1]) < 1e-6, (p, now)
        assert max(deltas) - min(deltas) < 1e-6 and 5 <= deltas[0] <= 7 and abs(deltas[0] * 2 - round(deltas[0] * 2)) < 1e-6, deltas
        assert frames and max(frames) < 33, f'drag frames {frames}'
        print(f'       marquee drag: {len(row)} plants moved {deltas[0]:.1f} ft, worst drag frame {max(frames):.1f} ms')
        _shot(page, '02_marquee_plants_moved')
        _undo(page, net)
        back = _plan(page)
        for p in row:
            assert _planting(back, p['id'])['at'] == p['at'], (p['id'], _planting(back, p['id'])['at'], p['at'])
        assert len(net['ops']) == 1, net['ops']


# --- 3. Select all using a material, swap it, one undo -----------------------------

def _seed_source_material():
    """Two outside walls (both faces) and one room floor use one household material."""
    from services import twin_store
    source, swap = _material('MS source ochre', '#d0901c'), _material('MS swap green', '#10b040')
    held = {}

    def paint(plan):
        b = _building(plan)
        for w in b['walls']:
            if w['id'] in (WING_EAST, NORTH_EAST):
                w['faces'] = {'left': {'id': source['id']}, 'right': {'id': source['id']}}
        room = next(r for r in b['rooms'] if r.get('level') == 'L1' and r.get('kind', 'room') == 'room' and r.get('state') != 'ghost')
        room['floor_material'] = {'id': source['id']}
        held['room'] = room['id']
        return plan
    twin_store.update_current(paint, 'build')
    return {'source': source, 'swap': swap, 'room': held['room']}


def scenario_right_click_names_the_material():
    """A fresh editor's right-click menu offers Select all using <the material's name>."""
    with _page(_seed_source_material) as (page, data, net):
        H.look_at(page, BID, EAST_EYE, EAST_TARGET)
        pixel, _ = _wall_pixel(page, NORTH_EAST, EAST)
        _click(page, pixel, button='right')
        menu = page.locator('#editor-context-menu')
        menu.wait_for(state='visible')
        items = menu.get_by_role('menuitem').all_inner_texts()
        _shot(page, '03b_right_click_material_menu')
        page.keyboard.press('Escape')
        assert f'Select all using {data["source"]["name"]}' in items, (
            f'the right-click menu does not name {data["source"]["name"]!r} ({data["source"]["id"]}): {items}')


def scenario_select_by_material_swap_one_undo():
    with _page(_seed_source_material) as (page, data, net):
        holder = data
        H.look_at(page, BID, EAST_EYE, EAST_TARGET)
        pixel, _ = _wall_pixel(page, NORTH_EAST, EAST)
        _click(page, pixel, ctrl=True)
        assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('wall', NORTH_EAST)], _members(page)
        own = page.locator(f'#piece-card [data-library-slot="{data["source"]["name"]} × 2 surfaces"]')
        own.wait_for(state='visible')
        own.get_by_role('button', name='Select all using it', exact=True).click()
        menu = page.locator('#editor-context-menu')
        menu.wait_for(state='visible')
        item = menu.get_by_role('menuitem', name=f'Select all using {data["source"]["name"]}', exact=True)
        assert item.count() == 1, menu.get_by_role('menuitem').all_inner_texts()
        item.click()
        H.settle(page, 3)
        members = _members(page)
        got = sorted((m['kind'], m['pieceId']) for m in members)
        assert got == sorted([('wall', WING_EAST), ('wall', NORTH_EAST), ('room', holder['room'])]), members
        assert net['ops'] == [], net['ops']
        summary = page.inner_text('#piece-card [data-selection-summary]').strip()
        assert sorted(summary.split(' · ')) == ['1 room (moves with its building)', '2 walls'], summary
        _library_select(page, data['swap'])
        entry = page.locator(f'#piece-card [data-library-slot^="{data["source"]["name"]} × "]')
        assert entry.count() == 1, page.locator('#piece-card [data-library-slot]').evaluate_all('n => n.map(x => x.dataset.librarySlot)')
        label = entry.get_attribute('data-library-slot')
        assert label == f'{data["source"]["name"]} × 5 surfaces', label
        _await_op(page, entry.get_by_role('button', name=f'Use {data["swap"]["name"]}', exact=True).click)
        assert len(net['ops']) == 1 and net['ops'][0]['op'] == 'batch' and len(net['ops'][0]['ops']) == 5, net['ops']
        plan = _plan(page)
        for wid in (WING_EAST, NORTH_EAST):
            assert _wall(plan, wid)['faces'] == {'left': {'id': data['swap']['id']}, 'right': {'id': data['swap']['id']}}, _wall(plan, wid)['faces']
        room = next(r for r in _building(plan)['rooms'] if r['id'] == holder['room'])
        assert room['floor_material'] == {'id': data['swap']['id']}, room['floor_material']
        _shot(page, '03_material_swapped')
        _undo(page, net)
        plan = _plan(page)
        for wid in (WING_EAST, NORTH_EAST):
            assert _wall(plan, wid)['faces'] == {'left': {'id': data['source']['id']}, 'right': {'id': data['source']['id']}}, _wall(plan, wid)['faces']
        room = next(r for r in _building(plan)['rooms'] if r['id'] == holder['room'])
        assert room['floor_material'] == {'id': data['source']['id']}, room['floor_material']
        assert len(net['ops']) == 1, net['ops']


# --- 4 and 5. Copy a window, paste at a right-click or onto a selected wall ------------

def _copy_window(page):
    plan = _plan(page)
    window = next(o for o in _openings(plan, PORCH_WINDOW_WALL) if o['kind'] == 'window')
    L._select_piece(page, _building(plan), window, 'opening')
    assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('opening', window['id'])], _members(page)
    _key(page, 'Control+c')
    assert _status(page) == 'Copied 1 piece.', _status(page)
    return window


def _assert_pasted_window(page, net, window, wall_id, at, tolerance):
    assert len(net['ops']) == 1 and net['ops'][0]['op'] == 'batch', net['ops']
    ops = net['ops'][0]['ops']
    assert len(ops) == 1 and ops[0]['op'] == 'add_opening' and ops[0]['wall'] == wall_id, ops
    plan = _plan(page)
    fresh = [o for o in _openings(plan, wall_id) if o['id'] == ops[0]['id']]
    assert len(fresh) == 1, _openings(plan, wall_id)
    pasted = fresh[0]
    assert pasted['id'] != window['id'] and abs(pasted['at'] - at) <= tolerance, (pasted, at)
    for field in ('kind', 'width', 'sill', 'head'):
        assert pasted[field] == window[field], (field, pasted, window)
    original = next(o for o in _building(plan)['openings'] if o['id'] == window['id'])
    assert original['wall'] == window['wall'] and original['at'] == window['at'], original
    assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('opening', pasted['id'])], _members(page)
    assert _status(page) == 'Pasted 1 piece.', _status(page)
    return pasted


def scenario_copy_window_paste_at_right_click():
    with _page() as (page, data, net):
        _floor_view(page)
        window = _copy_window(page)
        H.look_at(page, BID, EAST_EYE, EAST_TARGET)
        pixel, fraction = _wall_pixel(page, NORTH_EAST, EAST, fractions=(.3, .28, .32, .26, .34))
        wall = _wall(_plan(page), NORTH_EAST)
        along = fraction * math.dist(wall['from'], wall['to'])
        _click(page, pixel, button='right')
        menu = page.locator('#editor-context-menu')
        menu.wait_for(state='visible')
        paste = menu.get_by_role('menuitem', name='Paste', exact=True)
        assert paste.is_enabled(), paste.get_attribute('title')
        _await_op(page, paste.click)
        pasted = _assert_pasted_window(page, net, window, NORTH_EAST, along, .35)
        assert abs(pasted['at'] - math.dist(wall['from'], wall['to']) / 2) > 1, 'a right-click paste landed centred, not at the click'
        _shot(page, '04_window_pasted_at_click')


def scenario_select_wall_ctrl_v_centres_window():
    with _page() as (page, data, net):
        _floor_view(page)
        window = _copy_window(page)
        H.look_at(page, BID, EAST_EYE, EAST_TARGET)
        pixel, _ = _wall_pixel(page, NORTH_EAST, EAST, fractions=(.8, .75, .85, .7))
        _click(page, pixel)
        assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('wall', NORTH_EAST)], _members(page)
        wall = _wall(_plan(page), NORTH_EAST)
        _await_op(page, lambda: page.keyboard.press('Control+v'))
        _assert_pasted_window(page, net, window, NORTH_EAST, math.dist(wall['from'], wall['to']) / 2, .01)
        _shot(page, '05_window_centred_on_wall')


# --- 6 and 7. Tree copy/paste offsets, Ctrl+D ----------------------------------

def _select_tree(page, data):
    """Click the seeded lawn tree from straight above (a household tree's crown overlaps its neighbours)."""
    tree = _planting(_plan(page), data['trees'][0])
    _look_lot(page, tree['at'], height=70)
    _click(page, _pixel_lot(page, tree['at']))
    assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('planting', tree['id'])], _members(page)
    return tree


def _new_trees(page, before_ids):
    return [p for p in _plan(page)['site']['planting'] if p['id'] not in before_ids]


def _same_tree(copy, tree):
    for field in ('kind', 'preset', 'height', 'seed'):
        assert copy.get(field) == tree.get(field), (field, copy, tree)


def scenario_tree_copy_paste_steps_one_grid():
    with _page(_seed_lawn(trees=1, pad=False)) as (page, data, net):
        tree = _select_tree(page, data)
        ids = {p['id'] for p in _plan(page)['site']['planting']}
        _key(page, 'Control+c')
        assert _status(page) == 'Copied 1 piece.', _status(page)
        assert net['ops'] == [], net['ops']
        copies = []
        for n in (1, 2):
            _await_op(page, lambda: page.keyboard.press('Control+v'))
            assert len(net['ops']) == n and net['ops'][-1]['op'] == 'batch' and [o['op'] for o in net['ops'][-1]['ops']] == ['add_site_item'], net['ops']
            fresh = [p for p in _new_trees(page, ids) if p['id'] not in {c['id'] for c in copies}]
            assert len(fresh) == 1, fresh
            copy = fresh[0]
            copies.append(copy)
            _same_tree(copy, tree)
            # Top-down camera: the view's right is +x and its down is -y in lot feet.
            expected = [tree['at'][0] + .5 * n, tree['at'][1] - .5 * n]
            assert math.dist(copy['at'], expected) < .02, (n, copy['at'], expected)
            assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('planting', copy['id'])], _members(page)
            assert _status(page) == 'Pasted 1 piece.', _status(page)
        assert _planting(_plan(page), tree['id'])['at'] == tree['at']
        _shot(page, '06_tree_pasted_twice')


def scenario_ctrl_d_duplicates_without_dialog():
    with _page(_seed_lawn(trees=1, pad=False)) as (page, data, net):
        tree = _select_tree(page, data)
        ids = {p['id'] for p in _plan(page)['site']['planting']}
        assert page.locator('#rail-paste').is_disabled(), 'the clipboard is not empty before any copy'
        _await_op(page, lambda: page.keyboard.press('Control+d'))
        assert len(net['ops']) == 1 and [o['op'] for o in net['ops'][0]['ops']] == ['add_site_item'], net['ops']
        fresh = _new_trees(page, ids)
        assert len(fresh) == 1, fresh
        _same_tree(fresh[0], tree)
        assert math.dist(fresh[0]['at'], [tree['at'][0] + .5, tree['at'][1] - .5]) < .02, fresh[0]['at']
        assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('planting', fresh[0]['id'])], _members(page)
        assert _status(page) == 'Pasted 1 piece.', _status(page)
        assert net['dialogs'] == [], net['dialogs']
        assert page.locator('#rail-paste').is_disabled(), 'Duplicate filled the clipboard'
        assert page.url.split('?')[0].endswith('/house/editor'), page.url
        _shot(page, '07_ctrl_d_duplicate')


# --- 8. Cut and paste a device anchor ---------------------------------------------

DEVICE = 'ms-live-device-1'


def _seed_anchor():
    from services import twin_model_ops, twin_store
    op = {'op': 'add_anchor', 'building': BID, 'kind': 'sensor', 'name': 'Garage sensor', 'device': DEVICE,
          'host': {'wall': NORTH_EAST, 'at': 11, 'z': 5, 'side': 'right'}}
    twin_store.update_model(lambda model: twin_model_ops.apply(model, op, ha_catalogue={'available': False})[0], 'edit', note='seed')
    anchors = [a for a in _building(twin_store.current_model()).get('anchors', []) if a.get('device') == DEVICE]
    assert len(anchors) == 1, anchors
    return {'anchor': anchors[0]}


def scenario_cut_paste_device_anchor_keeps_binding():
    with _page(_seed_anchor) as (page, data, net):
        anchor = next(a for a in _building(_plan(page)).get('anchors', []) if a['id'] == data['anchor']['id'])
        assert anchor.get('device') == DEVICE, anchor
        _floor_view(page)
        L._select_piece(page, _building(_plan(page)), anchor, 'anchor')
        assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('anchor', anchor['id'])], _members(page)
        _await_op(page, lambda: page.keyboard.press('Control+x'))
        assert _status(page) == 'Cut 1 piece. Paste keeps their identity.', _status(page)
        assert not any(a['id'] == anchor['id'] for a in _building(_plan(page)).get('anchors', [])), 'the cut anchor is still there'
        assert _members(page) == [], _members(page)
        _await_op(page, lambda: page.keyboard.press('Control+v'))
        assert _status(page) == 'Pasted 1 piece.', _status(page)
        assert len(net['ops']) == 2, net['ops']
        cut, paste = net['ops']
        assert cut['op'] == 'batch' and len(cut['ops']) == 1, cut
        assert paste['op'] == 'batch' and len(paste['ops']) == 1 and paste['ops'][0]['op'] == 'add_anchor', paste
        assert paste['ops'][0]['id'] == anchor['id'] and paste['ops'][0].get('device') == DEVICE, paste
        back = next((a for a in _building(_plan(page)).get('anchors', []) if a['id'] == anchor['id']), None)
        assert back and back.get('device') == DEVICE, back
        assert back['host']['wall'] == anchor['host']['wall'] and abs(back['host']['at'] - anchor['host']['at']) < .05, (back, anchor)
        stored = [a for a in _building(H.model()).get('anchors', []) if a['id'] == anchor['id']]
        assert len(stored) == 1 and stored[0].get('device') == DEVICE, stored
        assert [(m['kind'], m['pieceId']) for m in _members(page)] == [('anchor', anchor['id'])], _members(page)
        _shot(page, '08_anchor_cut_paste')


# --- 9 and 10. Mixed set summary, narrowing; keep place on Ctrl-click --------------

def _seed_lawn(trees=2, pad=True):
    def seed():
        from services import twin_store
        ids = {'trees': [f'plant:ms-{i}-{uuid4().hex[:8]}' for i in range(trees)], 'pad': f'pad:ms-{uuid4().hex[:8]}'}
        x, y = LAWN

        def add(plan):
            for i, pid in enumerate(ids['trees']):
                plan['site']['planting'].append({'id': pid, 'kind': 'tree', 'preset': 'Pine Medium', 'height': 12,
                                                 'seed': 7 + i, 'at': [x - 6 + 6 * i, y - 4]})
            if pad:
                plan['site'].setdefault('terraces', []).append({'id': ids['pad'], 'height': 0, 'blend': 0, 'polygon': [
                    [x - 6, y + 4], [x + 6, y + 4], [x + 6, y + 12], [x - 6, y + 12]]})
            return plan
        twin_store.update_current(add, 'build')
        return ids
    return seed


def _summary_buttons(page):
    return page.locator('#piece-card [data-selection-summary] button').all_inner_texts()


def scenario_mixed_summary_and_narrowing():
    with _page(_seed_lawn(trees=2, pad=True)) as (page, data, net):
        plan = _plan(page)
        trees = [_planting(plan, pid) for pid in data['trees']]
        _look_lot(page, [LAWN[0], LAWN[1] + 2], height=60)
        _click(page, _pixel_lot(page, trees[0]['at']))
        _click(page, _pixel_lot(page, trees[1]['at']), ctrl=True)
        _click(page, _pixel_lot(page, [LAWN[0], LAWN[1] + 8]), ctrl=True)
        got = sorted((m['kind'], m['pieceId']) for m in _members(page))
        assert got == sorted([('planting', t['id']) for t in trees] + [('terraces', data['pad'])]), _members(page)
        summary = page.inner_text('#piece-card [data-selection-summary]').strip()
        assert sorted(summary.split(' · ')) == ['1 pad', '2 plants'], summary
        narrow = page.locator('#piece-card button', has_text='Narrow to')
        assert sorted(narrow.all_inner_texts()) == ['Narrow to pad (1)', 'Narrow to plants (2)'], narrow.all_inner_texts()
        _shot(page, '09_mixed_summary')
        # Ctrl-click removes a kind; a plain click narrows to one.
        page.keyboard.down('Control')
        try:
            page.locator('#piece-card [data-selection-summary] button', has_text='1 pad').click()
        finally:
            page.keyboard.up('Control')
        H.settle(page, 2)
        assert sorted(m['pieceId'] for m in _members(page)) == sorted(t['id'] for t in trees), _members(page)
        assert _summary_buttons(page) == ['2 plants'], _summary_buttons(page)
        _click(page, _pixel_lot(page, [LAWN[0], LAWN[1] + 8]), ctrl=True)
        assert len(_members(page)) == 3, _members(page)
        page.locator('#piece-card [data-selection-summary] button', has_text='2 plants').click()
        H.settle(page, 2)
        assert sorted((m['kind'], m['pieceId']) for m in _members(page)) == sorted(('planting', t['id']) for t in trees), _members(page)
        assert _summary_buttons(page) == ['2 plants'], _summary_buttons(page)
        assert net['ops'] == [], f'selecting and narrowing sent edits: {net["ops"]}'


def scenario_properties_keeps_place_on_ctrl_click():
    with _page(_seed_lawn(trees=4, pad=False), viewport=(1280, 720)) as (page, data, net):
        plan = _plan(page)
        trees = [_planting(plan, pid) for pid in data['trees']]
        _look_lot(page, [LAWN[0] + 3, LAWN[1] - 4], height=60)
        _click(page, _pixel_lot(page, trees[0]['at']))
        _click(page, _pixel_lot(page, trees[1]['at']), ctrl=True)
        assert len(_members(page)) == 2, _members(page)
        scroller = page.evaluate_handle("""() => {
            for (let n = document.querySelector('#piece-card'); n; n = n.parentElement) {
                const s = getComputedStyle(n); if (/(auto|scroll)/.test(s.overflowY + ' ' + s.overflow)) return n;
            }
            return null;
        }""")
        room = page.evaluate('s => s && s.scrollHeight - s.clientHeight', scroller)
        assert room and room > 40, f'Properties does not scroll at this size (room {room})'
        box = page.locator('#piece-card').bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + min(box['height'], 200) / 2)
        page.mouse.wheel(0, room)
        H.settle(page, 3)
        top = page.evaluate('s => s.scrollTop', scroller)
        assert top > 20, f'Properties did not scroll ({top})'
        field = page.locator('#piece-card input[data-field]:not([type="checkbox"])').last
        key = field.get_attribute('data-field')
        field.click()
        H.settle(page, 2)
        top = page.evaluate('s => s.scrollTop', scroller)
        assert page.evaluate("() => document.activeElement?.dataset?.field") == key
        # A Ctrl-click in the view: the browser moves focus out of the field (to the page),
        # and Properties rebuilds for the same kinds without jumping to the top.
        _click(page, _pixel_lot(page, trees[2]['at']), ctrl=True)
        _quiet(page)
        assert len(_members(page)) == 3, _members(page)
        assert _summary_buttons(page) == ['3 plants'], _summary_buttons(page)
        after = page.evaluate('s => s.scrollTop', scroller)
        assert abs(after - top) <= 2, f'Properties scroll moved from {top} to {after} on a same-kind Ctrl-click'
        stolen = page.evaluate("() => document.activeElement?.closest?.('#piece-card') ? document.activeElement.outerHTML.slice(0, 120) : null")
        assert stolen is None, f'the rebuilt card took focus: {stolen}'
        # Focus inside Properties survives a same-kind member arriving while the person is
        # in the field (the only way focus can be in the card at that rebuild; the member is
        # added through the selection store, as the Scene tree or another source would).
        field = page.locator(f'#piece-card input[data-field="{key}"]')
        field.click()
        H.settle(page, 2)
        top = page.evaluate('s => s.scrollTop', scroller)
        page.evaluate("id => window.__twinEditor.selectionStore.add({kind: 'planting', pieceId: id})", trees[3]['id'])
        _quiet(page)
        assert _summary_buttons(page) == ['4 plants'], _summary_buttons(page)
        after = page.evaluate('s => s.scrollTop', scroller)
        focused = page.evaluate("() => ({field: document.activeElement?.dataset?.field || null, inCard: !!document.activeElement?.closest?.('#piece-card')})")
        _shot(page, '10_properties_kept_place')
        assert abs(after - top) <= 2, f'Properties scroll moved from {top} to {after}'
        assert focused['inCard'] and focused['field'] == key, f'Properties focus moved: {focused} (was {key})'
        assert net['ops'] == [], net['ops']


SCENARIOS = [
    scenario_ctrl_click_walls_assign_material_one_undo,
    scenario_marquee_plants_gizmo_drag_one_undo,
    scenario_select_by_material_swap_one_undo,
    scenario_right_click_names_the_material,
    scenario_copy_window_paste_at_right_click,
    scenario_select_wall_ctrl_v_centres_window,
    scenario_tree_copy_paste_steps_one_grid,
    scenario_ctrl_d_duplicates_without_dialog,
    scenario_cut_paste_device_anchor_keeps_binding,
    scenario_mixed_summary_and_narrowing,
    scenario_properties_keeps_place_on_ctrl_click,
]


def main(argv=None):
    names = set((argv if argv is not None else sys.argv[1:]) or [])
    scenarios = [s for s in SCENARIOS if not names or s.__name__ in names or s.__name__.replace('scenario_', '') in names]
    print(f'screenshots: {SHOTS}')
    passed = failed = 0
    began = time.time()
    try:
        for scenario in scenarios:
            started = time.time()
            try:
                scenario()
            except M.MeasurementSkipped as error:
                print('  skip ', error)
                print(f'{passed}/{len(scenarios)} passed; remaining scenarios skipped')
                return int(failed > 0)
            except Exception:
                failed += 1
                traceback.print_exc(limit=8)
                print(f'FAIL {scenario.__name__} ({time.time() - started:.1f} s)')
            else:
                passed += 1
                print(f'ok   {scenario.__name__} ({time.time() - started:.1f} s)')
        print(f'{passed}/{len(scenarios)} passed in {time.time() - began:.0f} s')
        return int(failed > 0)
    finally:
        if SERVED is not None:
            SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())
