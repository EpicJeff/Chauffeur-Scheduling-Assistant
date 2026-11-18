"""Slice 3a picking acceptance: real Chromium mouse gestures, scratch data only.

Run from chauffeur/: python tests/test_twin_picking_live.py
Written by Codex; Claude runs the browser checks. Missing Playwright/Chromium
prints a skip. No production hook or source change is needed by these checks.
"""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import sys
import tempfile
import traceback
from uuid import uuid4

# Set scratch storage before importing any harness or service (including when
# the calling shell inherited a real household's data directory).
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_picking_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_edit_measure as M
import house_editor_model_harness as H
from live_app import live_app

SERVED = None
TREE_AT = [20, 125]  # Clear lawn inside the fixture's lot, away from buildings.


def _seed(plan, case):
    """Seed through the store, before opening the page or counting requests."""
    x, y = TREE_AT
    if case == 'line':
        # A flat round does not own light fixtures; _page writes them on the model.
        pass
    else:
        plan['site']['planting'].append({
            'id': 'plant:' + str(uuid4()), 'kind': 'tree', 'preset': 'Pine Medium',
            'height': 12, 'seed': 7, 'at': list(TREE_AT),
        })
    if case == 'pad':
        plan['site'].setdefault('terraces', []).append({
            'id': 'pad:' + str(uuid4()), 'height': 0, 'blend': 0,
            'polygon': [[x, y], [x + 16, y], [x + 16, y + 16], [x, y + 16]],
        })
    elif case == 'bed':
        plan['site']['beds'].append({
            'id': 'bed:' + str(uuid4()), 'material': 'mulch',
            'polygon': [[x - 8, y - 8], [x + 8, y - 8],
                        [x + 8, y + 8], [x - 8, y + 8]],
        })
    return plan


@contextmanager
def _page(case='tree'):
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; picking checks skipped') from error
    from services import twin_store

    # Reset even the first scenario. Later scenarios must never inherit earlier
    # moves, pads, selection, camera state, or queued operations.
    twin_store.start_over()
    M._prepare(None)
    twin_store.update_current(lambda plan: _seed(plan, case), 'build')
    if case == 'line':
        x, y = TREE_AT
        line = {'id': 'fixture:' + str(uuid4()), 'shape': 'line', 'ref': 'absolute',
                'path': [[x - 8, y, 2], [x, y, 2], [x + 8, y, 2]],
                'facing': 'down', 'width_in': .5, 'share': 1}
        twin_store.update_model(lambda model: {**model, 'light_fixtures': {'light.picking_live': [line]}}, 'edit', note='seed')
        assert twin_store.current_model().get('light_fixtures'), 'the store dropped the line light'
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; picking checks skipped')
    browser = SERVED.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_default_timeout(15000)
            H.open_editor(page, SERVED, query='tier=low&test=1&timing=1')
            M._dismiss_alert(page)
            M._track_view_work(page)
            H.all_floors(page)
            page.click('#rail-select')
            page.evaluate('window.__twin.controls.enableDamping = false')
            M._wait_settled(page)
            assert H.editor_state(page, 'selection')['id'] is None
            yield page
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; picking checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _plan(page):
    return page.evaluate('window.__twin.plan')


def _tree(page):
    trees = [p for p in _plan(page)['site']['planting']
             if p['kind'] == 'tree' and p['at'] == TREE_AT]
    assert len(trees) == 1, trees
    return trees[0]


def _item(page, collection, item_id):
    return next(p for p in _plan(page)['site'][collection] if p['id'] == item_id)


def _look(page, at, orbit=False):
    """Lot-space feet; an oblique eye makes orbit displacement measurable."""
    x, y = at[:2]
    page.evaluate("""([x,y,orbit]) => {
        const v = window.__twin, ft = .3048;
        v.setCamera('front');
        v.setCameraState({position:[x*ft,70*ft,-(y-(orbit?45:.01))*ft],
                          target:[x*ft,0,-y*ft]});
        v.camera.updateMatrixWorld(true);
    }""", [x, y, orbit])
    H.settle(page)


def _pixel(page, point):
    return page.evaluate("""p => {
        const v = window.__twin, r = v.renderer3.domElement.getBoundingClientRect();
        v.camera.updateMatrixWorld(true);
        const q = v.camera.position.clone().set(p[0]*.3048,(p[2]||0)*.3048,-p[1]*.3048).project(v.camera);
        return [r.left+(q.x+1)*r.width/2,r.top+(1-q.y)*r.height/2];
    }""", point)


def _click(page, pixel):
    H._on_canvas(page, *pixel)
    page.mouse.click(*pixel)
    H.settle(page)


def _selected(page, kind, item_id):
    selection = H.editor_state(page, 'selection')
    assert selection['kind'] == kind and selection['id'] == item_id, selection
    assert not selection.get('building'), selection


def _posted(page):
    operations = []

    def record(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op'):
            operations.append(request.post_data_json['op'])

    page.on('request', record)
    return operations


def _quiet(page):
    # Include event-loop time so an erroneously queued/debounced save cannot
    # pass a negative assertion made immediately after pointerup.
    page.wait_for_timeout(350)
    M._wait_settled(page)


def _saved_drag(page, start, end, posted, expected_op):
    # Wait for the real response as well as the shown house. Pad/fixture saves
    # need not have the queue's drag timing record used by wall/plant saves.
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and r.url.split('?')[0].endswith('/api/house/editor/op')) as pending:
        M._mouse_release(page, start, end)
    response = pending.value
    assert response.status == 200, (response.status, response.text())
    _quiet(page)
    assert len(posted) == 1 and posted[0]['op'] == expected_op, posted
    return posted[0]


def _navigate_over_tree(page, tree, posted):
    _look(page, tree['at'], orbit=True)
    start = _pixel(page, tree['at'])
    before = _plan(page)
    camera = page.evaluate('window.__twin.camera.position.toArray()')
    M._mouse_release(page, start, [start[0] + 120, start[1]])
    _quiet(page)
    after_camera = page.evaluate('window.__twin.camera.position.toArray()')
    assert math.dist(camera, after_camera) > .1, (camera, after_camera)
    assert _plan(page) == before, 'Navigation changed the house plan'
    assert posted == [], posted
    assert H.editor_state(page, 'selection')['id'] is None
    assert page.evaluate('window.__twin.controls.enabled')


def drag_over_a_tree_only_turns_the_camera():
    with _page() as page:
        tree = _tree(page)
        _navigate_over_tree(page, tree, _posted(page))


def pad_corner_under_a_tree_moves_the_corner():
    with _page('pad') as page:
        tree = _tree(page)
        pad = next(p for p in _plan(page)['site']['terraces'] if p['polygon'][0] == tree['at'])
        page.get_by_role('button', name='Ground and yard', exact=True).click()
        page.locator(f'#terrain-card [data-pad-id="{pad["id"]}"]').click()
        _look(page, tree['at'])
        # The look moved the camera without a controls change event; redraw first.
        handles = page.evaluate('(window.__twinEditor.terrain.refresh(), window.__twinEditor.terrain.handles())')
        corner = next(h for h in handles if h['index'] == 0 and not h.get('insert'))
        assert corner['at'] == tree['at'], (corner, tree)
        start = corner['screen']
        destination = [corner['at'][0] + 1.5, corner['at'][1]]
        # Move by the projected difference from the drawn handle, so the pad's
        # own drawn height (ground plus pad) cancels out of the screen offset.
        a = _pixel(page, [*corner['at'], pad['height'] + .08]); b = _pixel(page, [*destination, pad['height'] + .08])
        end = [start[0] + b[0] - a[0], start[1] + b[1] - a[1]]
        posted = _posted(page)
        op = _saved_drag(page, start, end, posted, 'update_pad')
        assert op['id'] == pad['id'], op
        assert math.dist(op['polygon'][0], destination) < .03, op
        assert op['polygon'][1:] == pad['polygon'][1:], op
        after = _item(page, 'terraces', pad['id'])
        assert math.dist(after['polygon'][0], destination) < .03, after
        assert after['polygon'][1:] == pad['polygon'][1:], after
        assert _item(page, 'planting', tree['id'])['at'] == tree['at']
        assert H.editor_state(page, 'selection')['id'] is None, 'Tree became selected'
        assert page.locator('#terrain-card').is_visible()
        assert 'Terrace pad' in page.locator('#terrain-card h3').all_inner_texts(), page.locator('#terrain-card h3').all_inner_texts()
        chosen_corners = page.evaluate('window.__twinEditor.terrain.handles().filter(h => !h.insert).map(h => h.at)')
        assert chosen_corners == after['polygon'], 'The moved pad did not stay chosen'


def click_twice_reaches_the_thing_beneath():
    with _page('bed') as page:
        tree = _tree(page)
        bed = next(p for p in _plan(page)['site']['beds']
                   if p['polygon'][0] == [tree['at'][0] - 8, tree['at'][1] - 8])
        _look(page, tree['at'])
        pixel = _pixel(page, tree['at'])
        before, posted = _plan(page), _posted(page)
        _click(page, pixel)
        _selected(page, 'planting', tree['id'])
        assert H.card_title(page) == (tree.get('name') or tree['preset']), H.card_title(page)
        _click(page, pixel)  # Exactly the same client pixel, without a rebuild.
        _selected(page, 'beds', bed['id'])
        assert 'planting bed' in (H.card_title(page) or '').lower(), H.card_title(page)
        _quiet(page)
        assert _plan(page) == before
        assert posted == [], posted


def move_tool_never_selects_and_moves():
    with _page() as page:
        tree = _tree(page)
        page.click('#rail-move')
        assert page.get_attribute('#rail-move', 'aria-pressed') == 'true'
        posted = _posted(page)
        _navigate_over_tree(page, tree, posted)
        # Restore the camera after navigation; use a click to select, then a
        # separate body drag. The two-foot destination is lot-space feet.
        _look(page, tree['at'])
        start = _pixel(page, tree['at'])
        before = _plan(page)
        _click(page, start)
        _selected(page, 'planting', tree['id'])
        _quiet(page)
        assert _plan(page) == before and posted == [], posted
        destination = [tree['at'][0] + 2, tree['at'][1]]
        op = _saved_drag(page, start, _pixel(page, destination), posted, 'move_site_item')
        assert op['list'] == 'planting', op
        assert before['site']['planting'][op['index']]['id'] == tree['id'], op
        assert math.dist(op['at'], destination) < .03, op
        assert math.dist(_item(page, 'planting', tree['id'])['at'], destination) < .03
        _selected(page, 'planting', tree['id'])


def esc_mid_drag_restores():
    with _page() as page:
        tree = _tree(page)
        page.click('#rail-move')
        _look(page, tree['at'])
        start = _pixel(page, tree['at'])
        _click(page, start)
        _selected(page, 'planting', tree['id'])
        before, posted = _plan(page), _posted(page)
        outline_box = """() => {
            const o = window.__twin.scene.children.find(o => o.type === 'Box3Helper' && o.visible);
            return o ? [o.box.min.toArray(), o.box.max.toArray()] : null;
        }"""
        original_outline = page.evaluate(outline_box)
        assert original_outline is not None, 'Selected tree outline is missing'
        end = _pixel(page, [tree['at'][0] + 2, tree['at'][1]])
        for point in (start, end):
            H._on_canvas(page, *point)
        assert math.dist(start, end) >= 3
        # This one gesture is split explicitly: Escape must happen while the
        # real mouse is down, before _mouse_release would release it.
        page.mouse.move(*start)
        page.mouse.down()
        try:
            page.mouse.move(*end, steps=10)
            H.settle(page)
            assert not page.evaluate('window.__twin.controls.enabled'), 'No drag was acquired'
            assert page.evaluate(outline_box) != original_outline, 'Tree preview never moved'
            page.keyboard.press('Escape')
            H.settle(page)
            assert page.evaluate('window.__twin.controls.enabled'), 'Escape did not restore orbit'
            assert page.evaluate(outline_box) == original_outline, 'Escape did not restore the tree preview'
            assert page.locator('#editor-drag-hint').is_hidden()
            assert page.get_attribute('#editor-drag-outline', 'points') == ''
            _selected(page, 'planting', tree['id'])
        finally:
            page.mouse.up()
        _quiet(page)
        assert _plan(page) == before, 'Escape committed the cancelled preview'
        assert posted == [], posted
        # Also prove a subsequent unowned mouse drag can navigate again.
        camera = page.evaluate('window.__twin.camera.position.toArray()')
        M._mouse_release(page, [start[0] + 160, start[1]], [start[0] + 220, start[1] - 50])
        _quiet(page)
        assert math.dist(camera, page.evaluate('window.__twin.camera.position.toArray()')) > .1
        assert _plan(page) == before and posted == [], posted


def line_light_point_drag():
    with _page('line') as page:
        # Resolve entity and fixture ids from the shown plan, not seed ids.
        entity, fixture = next((entity, f) for entity, rows in _plan(page)['light_fixtures'].items()
                               for f in rows if f['shape'] == 'line' and not f.get('snap')
                               and f['path'] == [[12, 125, 2], [20, 125, 2], [28, 125, 2]])
        _look(page, fixture['path'][1])
        _click(page, _pixel(page, fixture['path'][1]))
        row = page.locator(f'#piece-card [data-fixture-id="{fixture["id"]}"]')
        assert row.is_visible() and row.evaluate('row => row.open'), 'Fixture card is not selected/open'
        handles = page.locator('[data-fixture-point]')
        assert handles.count() == 3, handles.count()
        handle = page.locator('[data-fixture-point="1"]').bounding_box()
        assert handle is not None, 'Middle point handle is missing'
        start = [handle['x'] + handle['width']/2, handle['y'] + handle['height']/2]
        destination = [fixture['path'][1][0], fixture['path'][1][1] + 2, fixture['path'][1][2]]
        posted = _posted(page)
        op = _saved_drag(page, start, _pixel(page, destination), posted, 'update_light_fixture')
        assert op['entity_id'] == entity and op['id'] == fixture['id'], op
        assert set(op['change']) == {'path'}, op
        path = op['change']['path']
        assert path[0] == fixture['path'][0] and path[2] == fixture['path'][2], op
        assert math.dist(path[1], destination) < .03, op
        after = next(f for f in _plan(page)['light_fixtures'][entity] if f['id'] == fixture['id'])
        assert after['path'][0] == fixture['path'][0] and after['path'][2] == fixture['path'][2], after
        assert math.dist(after['path'][1], destination) < .03, after
        assert {k: v for k, v in after.items() if k != 'path'} == {
            k: v for k, v in fixture.items() if k != 'path'}, (fixture, after)


def main():
    scenarios = [drag_over_a_tree_only_turns_the_camera, pad_corner_under_a_tree_moves_the_corner,
                 click_twice_reaches_the_thing_beneath, move_tool_never_selects_and_moves,
                 esc_mid_drag_restores, line_light_point_drag]
    passed = 0
    try:
        for scenario in scenarios:
            try:
                scenario()
            except M.MeasurementSkipped as error:
                print('  skip ', error)
                print(f'{passed}/{len(scenarios)} passed; remaining scenarios skipped')
                return 0
            except Exception:
                traceback.print_exc(limit=8)
                print('FAIL', scenario.__name__)
            else:
                passed += 1
                print('ok  ', scenario.__name__)
        print(f'{passed}/{len(scenarios)} passed')
        return int(passed != len(scenarios))
    finally:
        if SERVED is not None:
            SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())
