"""Hand-made porch acceptance through real Chromium gestures.

Run from chauffeur/: python tests/test_twin_add_porch_live.py [screenshot.png]
Written without launching a browser; Claude runs these scenarios. Every scenario
starts with the real household fixture in scratch storage. Only camera framing,
observations and the explicit orphan fixture use hooks; edits use the real UI.
"""
from contextlib import contextmanager
from copy import deepcopy
import math
import os
from pathlib import Path
import sys
import tempfile
import traceback
from uuid import uuid4

# Select scratch storage BEFORE importing any harness or application services.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_add_porch_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_edit_measure as M
import house_editor_model_harness as H
from live_app import live_app

SERVED = None
TIMEOUT = 40000
QUERY = 'tier=low&test=1&timing=1'


def _settled(page):
    condition = """() => window.__twin?.ready && !window.__twin.__measureWork
        && document.querySelector('#editor-save-state').textContent.trim() === 'Saved'"""
    page.wait_for_function(condition, timeout=TIMEOUT)
    page.evaluate('async () => { await window.__twin.afterNextRender(); await window.__twin.afterNextRender(); }')
    page.wait_for_function(condition, timeout=TIMEOUT)


@contextmanager
def _page(seed=None):
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; Add porch checks skipped') from error
    from services import twin_store

    twin_store.start_over()
    M._prepare(None)  # Real household, auth and library stubs; no credentials read.
    if seed:
        twin_store.update_model(seed, 'build')
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; Add porch checks skipped')
    browser = SERVED.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_default_timeout(TIMEOUT)
            page.set_default_navigation_timeout(TIMEOUT)
            H.signed_in(page)
            page.goto(SERVED.url(f'house/editor?{QUERY}'), timeout=TIMEOUT)
            page.wait_for_function('window.__editor?.ready === true && !!window.__twinEditor', timeout=TIMEOUT)
            page.wait_for_function("window.__twin?.ready && window.__twin.plan?.buildings?.length > 0"
                                   " && window.__twin.pieceIds('main-house').length > 0", timeout=TIMEOUT)
            H.settle(page, 4)
            # Never click through the automatically opened Your place dialog.
            if page.locator('#editor-dialog').is_visible():
                page.click('#editor-dialog-close')
                page.locator('#editor-dialog').wait_for(state='hidden', timeout=TIMEOUT)
            M._dismiss_alert(page)
            M._track_view_work(page)
            page.evaluate('window.__twin.controls.enableDamping = false')
            page.click('#rail-select')
            _settled(page)
            yield page
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; Add porch checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _plan(page):
    return page.evaluate('window.__twin.plan')


def _building(plan, bid='main-house'):
    return H.building(plan, bid)


def _footprint(plan):
    """Eight by six feet outside the main house's leftmost exterior wall.

    Derive the edge from this fixture, rather than screen pixels or a toy house.
    At the global minimum x the negative-x side is outside every room/wall.
    """
    building = _building(plan)
    level = min((l for l in building['levels'] if l.get('state') != 'ghost'),
                key=lambda l: l['elevation'])
    walls = [w for w in building['walls'] if w['level'] == level['id']
             and w.get('exterior') and w.get('kind') != 'separator' and w.get('state') != 'ghost']
    left = min(p[0] for w in walls for p in (w['from'], w['to']))
    candidates = [w for w in walls if all(abs(p[0] - left) < 1e-6 for p in (w['from'], w['to']))
                  and math.dist(w['from'], w['to']) >= 10]
    assert candidates, 'Household main floor has no clear left exterior wall of at least 10 ft'
    wall = max(candidates, key=lambda w: math.dist(w['from'], w['to']))
    y = math.ceil((wall['from'][1] + wall['to'][1]) / 2 - 4)
    start, end = [left, y], [left - 6, y + 8]
    assert min(wall['from'][1], wall['to'][1]) < y < y + 8 < max(wall['from'][1], wall['to'][1])
    return building, level, wall, start, end


def _frame(page):
    building, level, wall, start, end = _footprint(_plan(page))
    key = f'{building["id"]}:{level["id"]}'
    H.choose_floor(page, key)  # The drawn porch must belong to this current floor.
    H.look_down(page, building['id'], (start[0] + end[0]) / 2,
                (start[1] + end[1]) / 2, height=45 + level['elevation'])
    _settled(page)
    return building, level, wall, start, end, key


def _operation(page, name, action):
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and r.url.split('?')[0].endswith('/api/house/editor/op'),
                              timeout=TIMEOUT) as pending:
        action()
    response = pending.value
    assert response.status == 200, (response.status, response.text())
    operation = response.request.post_data_json['op']
    assert operation['op'] == name, operation
    _settled(page)
    return operation


def _drag(page, start, end, key):
    # Projection includes the current floor, building position/rotation and camera.
    pixels = page.evaluate("""([a,b,key]) => [a,b].map(p => window.__twin.screenOfFloor(...p,key))""",
                           [start, end, key])
    assert all(p and all(math.isfinite(v) for v in p) for p in pixels), pixels
    for point in pixels:
        H._on_canvas(page, *point)
    page.mouse.move(*pixels[0])
    page.mouse.down()
    try:
        page.mouse.move(*pixels[1], steps=16)
        H.settle(page, 2)  # A real preview frame before the pointer release.
    finally:
        page.mouse.up()


def _assert_porch(page, bid, rid, level):
    from services.twin_porches import DEFAULT

    building = _building(H.model(), bid)
    room = next(r for r in building['rooms'] if r['id'] == rid)
    details = [p for p in building.get('porches_detail', []) if p['id'] == rid]
    assert room['kind'] == 'porch' and room['level'] == level, room
    assert room['foundation'] == DEFAULT, room
    assert len(details) == 1 and details[0]['polygon'] == room['polygon'], details
    assert details[0]['level'] == level and details[0]['columns'], details
    drawn = _building(_plan(page), bid)
    assert next(r for r in drawn['rooms'] if r['id'] == rid)['kind'] == 'porch'
    assert any(p['id'] == rid for p in drawn.get('porches', [])), drawn.get('porches')
    return room


def _assert_card(page, rid, bid):
    selected = H.editor_state(page, 'selection')
    assert selected['id'] == rid and selected['building'] == bid, selected
    card = page.locator('#properties-content #piece-card')
    assert card.is_visible(), 'Selected porch has no Properties card'
    assert card.get_by_role('combobox', name='Type', exact=True).input_value() == 'porch'
    foundation = card.get_by_role('combobox', name='Foundation', exact=True)
    assert foundation.is_visible() and foundation.input_value() == 'posts'


def _add_porch(page):
    building, level, wall, start, end, key = _frame(page)
    before = H.model()
    old = _building(before, building['id'])
    page.get_by_role('button', name='Add porch', exact=True).click()
    assert page.get_by_role('button', name='Add porch', exact=True).get_attribute('aria-pressed') == 'true'
    options = page.locator('#properties-content #draw-options')
    options.get_by_role('combobox', name='Roof', exact=True).select_option(label='Shed')
    operation = _operation(page, 'add_porch', lambda: _drag(page, start, end, key))
    assert operation['building'] == building['id'] and operation['level'] == level['id'], operation
    assert operation['roof'] == 'shed' and operation['host_wall'] == wall['id'], operation
    old_ids = {r['id'] for r in old['rooms']}
    added = [r for r in _building(H.model(), building['id'])['rooms'] if r['id'] not in old_ids]
    assert len(added) == 1, added
    rid = added[0]['id']
    page.wait_for_function("""id => window.__twin.plan.buildings.some(b =>
        b.rooms.some(r => r.id === id && r.kind === 'porch'))
        && window.__twinEditor.selection().id === id""", arg=rid, timeout=TIMEOUT)
    _settled(page)
    room = _assert_porch(page, building['id'], rid, level['id'])
    _assert_card(page, rid, building['id'])
    old_roofs = {r['id'] for r in old['roofs']}
    roofs = [r for r in _building(H.model(), building['id'])['roofs'] if r['id'] not in old_roofs]
    assert len(roofs) == 1, roofs
    roof = roofs[0]
    assert roof['level'] == level['id'] and roof['pitch'] == 3 and roof['overhang'] == 1, roof
    assert sorted(roof['area']) == sorted(room['polygon']), (roof, room)
    sections = [s for s in _building(_plan(page), building['id'])['roof']['sections'] if s.get('roof') == roof['id']]
    assert sections and all(s['kind'] == 'shed' for s in sections), sections
    return building['id'], rid, roof['id'], before


# Generator meshes may be merged. Inspect both their attributed vertex ranges
# and unmerged meshes, rather than just asking whether selection forgot the id.
PORCH_MESHES = """([bid,id]) => {
    const found = {room:0, porch:0}, v = window.__twin;
    v.scene.traverse(o => {
        if (!o.isMesh) return;
        const ranges = o.userData.snapRanges || o.geometry?.userData.snapRanges;
        for (const d of ranges || [o.userData]) {
            if (d.buildingId === bid && d.pieceId === id && d.kind in found)
                found[d.kind] += d.count ?? o.geometry?.attributes.position?.count ?? 0;
        }
    });
    return found;
}"""


def _assert_absent(page, bid, rid):
    for plan in (H.model(), _plan(page)):
        building = _building(plan, bid)
        assert all(r['id'] != rid for r in building['rooms']), building['rooms']
        for key in ('porches_detail', 'porches'):
            assert all(p['id'] != rid for p in building.get(key, [])), (key, rid)
        assert (building.get('porch') or {}).get('id') != rid
    assert page.evaluate(PORCH_MESHES, [bid, rid]) == {'room': 0, 'porch': 0}, 'Porch slab/posts remain in the scene'


def _mount_row(page, host, row):
    if not row.count():
        host.get_by_role('treeitem').first.press('Home')
        H.settle(page)
        for _ in range(120):
            if row.count():
                break
            box = host.bounding_box()
            assert box and box['height'] > 0, 'Scene tree has no scroll viewport'
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.wheel(0, max(36, box['height'] * .65))
            H.settle(page, 3)
    assert row.count() == 1, 'Scene row missing or ambiguous'
    row.scroll_into_view_if_needed(timeout=TIMEOUT)
    return row


def _select_scene(page, bid, level, rid):
    page.click('#dock-tab-scene')
    host = page.locator('#scene-tree')
    for parent in (host.locator(f'[data-scene-id="{bid}"]'),
                   host.locator(f'[data-floor="{bid}:{level}"]').locator('..')):
        parent = _mount_row(page, host, parent)
        disclosure = parent.locator('[data-row-disclosure][aria-expanded="false"]')
        if disclosure.count():
            disclosure.click()
    row = _mount_row(page, host, host.locator(f'[data-scene-id="{rid}"]'))
    row.locator('[data-scene-select]').click()
    _settled(page)
    assert H.editor_state(page, 'selection')['id'] == rid


def _delete(page, bid, rid):
    page.locator('#properties-content #piece-card').get_by_role('button', name='Delete', exact=True).click()
    dialog = page.locator('#cc-confirm-modal')
    dialog.wait_for(state='visible', timeout=TIMEOUT)
    operation = _operation(page, 'delete', lambda: dialog.get_by_role('button', name='Delete', exact=True).click())
    assert operation['building'] == bid and operation['id'] == rid, operation
    page.wait_for_function("""([bid,id]) => {
        const b = window.__twin.plan.buildings.find(b => b.id === bid);
        return !b.rooms.some(r => r.id === id) && !(b.porches || []).some(p => p.id === id);
    }""", arg=[bid, rid], timeout=TIMEOUT)
    _settled(page)
    assert not page.locator('#cc-alert-modal').is_visible(), 'Delete raised an error alert'
    _assert_absent(page, bid, rid)


def scenario_add_porch_with_shed_roof():
    with _page() as page:
        bid, rid, _, _ = _add_porch(page)
        geometry = page.evaluate(PORCH_MESHES, [bid, rid])
        assert geometry['room'] > 0 and geometry['porch'] > 0, geometry
        if len(sys.argv) > 1:
            screenshot = Path(sys.argv[1]).expanduser().resolve()
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True, animations='disabled')
            assert screenshot.is_file() and screenshot.stat().st_size > 0, screenshot
            print(f'Screenshot: {screenshot}')


def scenario_undo_removes_porch_and_roof():
    with _page() as page:
        bid, rid, roof_id, before = _add_porch(page)
        page.get_by_role('button', name='Undo', exact=True).click()  # Exactly once.
        page.wait_for_function("""([bid,id]) => !window.__twin.plan.buildings
            .find(b => b.id === bid).rooms.some(r => r.id === id)""", arg=[bid, rid], timeout=TIMEOUT)
        _settled(page)
        _assert_absent(page, bid, rid)
        assert all(r['id'] != roof_id for r in _building(H.model(), bid)['roofs'])
        assert H.model() == before, 'One Undo did not restore the entire pre-porch model'
        assert not any(s.get('roof') == roof_id for s in _building(_plan(page), bid)['roof']['sections'])


def scenario_room_type_to_porch():
    with _page() as page:
        building, level, _, start, end, key = _frame(page)
        bid = building['id']
        old_ids = {r['id'] for r in _building(H.model(), bid)['rooms']}
        page.get_by_role('button', name='Draw room', exact=True).click()
        _operation(page, 'draw_room', lambda: _drag(page, start, end, key))
        added = [r for r in _building(H.model(), bid)['rooms'] if r['id'] not in old_ids]
        assert len(added) == 1 and added[0].get('kind', 'room') == 'room', added
        room = deepcopy(added[0])
        rid = room['id']
        page.keyboard.press('Escape')
        _select_scene(page, bid, level['id'], rid)
        card = page.locator('#properties-content #piece-card')
        for kind, label in (('porch', 'Porch'), ('room', 'Room')):
            operation = _operation(page, 'set_room_kind', lambda: card.get_by_role(
                'combobox', name='Type', exact=True).select_option(label=label))
            assert operation == {'op': 'set_room_kind', 'building': bid, 'room': rid, 'kind': kind}, operation
            page.wait_for_function("""([bid,id,kind]) => window.__twin.plan.buildings
                .find(b => b.id === bid).rooms.find(r => r.id === id)?.kind === kind""",
                                   arg=[bid, rid, kind], timeout=TIMEOUT)
            _settled(page)
            if kind == 'porch':
                _assert_porch(page, bid, rid, level['id'])
                _assert_card(page, rid, bid)
            else:
                current = _building(H.model(), bid)
                restored = next(r for r in current['rooms'] if r['id'] == rid)
                assert restored['kind'] == 'room' and 'foundation' not in restored, restored
                assert all(p['id'] != rid for p in current.get('porches_detail', []))
                assert restored['polygon'] == room['polygon'] and restored['name'] == room['name']
                assert not card.get_by_role('combobox', name='Foundation', exact=True).count()


def scenario_delete_porch_removes_all():
    with _page() as page:
        bid, rid, roof_id, _ = _add_porch(page)  # Same gesture/assertions as scenario 1.
        geometry = page.evaluate(PORCH_MESHES, [bid, rid])
        assert geometry['room'] > 0 and geometry['porch'] > 0, geometry
        _delete(page, bid, rid)
        # Task 1b ruling: the ordinary roof remains for separate editing.
        assert any(r['id'] == roof_id for r in _building(H.model(), bid)['roofs'])


def scenario_leftover_porch_record_can_be_deleted():
    rid = 'porch:live-leftover-' + uuid4().hex

    def seed(model):
        # Direct canonical store mutation deliberately models the broken legacy
        # state; a flat-plan push would assemble a new room for this detail.
        building = _building(model)
        detail = deepcopy(building['porches_detail'][0])
        room = next(r for r in building['rooms'] if r['id'] == detail['id'])
        detail.update(id=rid, name='Leftover porch acceptance', level=room['level'])
        # Keep it clear of existing rooms so the generator must draw the
        # orphan's own slab as well as its columns (polygon fallback included).
        dx = min(j['at'][0] for j in building['joints']) - max(p[0] for p in detail['polygon']) - 8
        detail['polygon'] = [[p[0] + dx, p[1]] for p in detail['polygon']]
        for column in detail['columns']:
            column['at'][0] += dx
        building['porches_detail'].append(detail)
        return model

    with _page(seed=seed) as page:
        building = _building(H.model())
        detail = next(p for p in building['porches_detail'] if p['id'] == rid)
        assert all(r['id'] != rid for r in building['rooms']), 'Orphan fixture unexpectedly has a room'
        assert page.evaluate(PORCH_MESHES, [building['id'], rid])['porch'] > 0, 'Orphan fixture has no geometry'
        _select_scene(page, building['id'], detail['level'], rid)
        assert H.card_title(page) == 'Leftover porch acceptance'
        _delete(page, building['id'], rid)


def main():
    scenarios = [scenario_add_porch_with_shed_roof,
                 scenario_undo_removes_porch_and_roof,
                 scenario_room_type_to_porch,
                 scenario_delete_porch_removes_all,
                 scenario_leftover_porch_record_can_be_deleted]
    passed = failed = skipped = 0
    try:
        for scenario in scenarios:
            try:
                scenario()
            except M.MeasurementSkipped as error:
                skipped += 1
                print('skip', scenario.__name__, error)
            except Exception:
                failed += 1
                traceback.print_exc(limit=8)
                print('FAIL', scenario.__name__)
            else:
                passed += 1
                print('ok  ', scenario.__name__)
        print(f'{passed}/{len(scenarios)} passed; {skipped} skipped; {failed} failed')
        return int(failed > 0)
    finally:
        if SERVED is not None:
            SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())
