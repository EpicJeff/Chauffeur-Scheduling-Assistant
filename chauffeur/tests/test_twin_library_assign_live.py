"""Slice 6 Chromium acceptance: Library selection, slot rows and scope drops.

Run from chauffeur/: python tests/test_twin_library_assign_live.py
WRITTEN, NOT RUN by Codex. Claude owns browser validation. Every scenario
resets the real household store; all authored actions use the actual UI.
Only camera positioning and read-only observations use the existing hooks.
"""
from contextlib import contextmanager
from io import BytesIO
import base64
import math
import os
from pathlib import Path
import sys
import tempfile
import traceback

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_library_assign_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_edit_measure as M
import house_editor_model_harness as H
from live_app import live_app
from test_twin_objects_live import fixture_glb

SERVED = None
TIMEOUT = 40000
QUERY = 'tier=low&test=1&timing=1'


def _wait(page, expression, arg=None):
    # The view renders on demand; RAF polling can starve its settling work.
    page.wait_for_function(expression, arg=arg, timeout=TIMEOUT, polling=500)


def _settled(page):
    condition = """() => window.__twin?.ready && !window.__twin.__measureWork
        && document.querySelector('#editor-save-state').textContent.trim() === 'Saved'"""
    _wait(page, condition)
    page.evaluate('async () => { await window.__twin.afterNextRender(); await window.__twin.afterNextRender(); }')
    _wait(page, condition)


def _plan(page):
    return page.evaluate('window.__twin.plan')


def _owns_wall(room, wall):
    cycle = room.get('joints', [])
    return wall['id'] in room.get('walls', []) or (
        len(wall.get('joints', [])) == 2 and any(
            set((joint, cycle[(i + 1) % len(cycle)])) == set(wall['joints'])
            for i, joint in enumerate(cycle)))


def _target(plan):
    """A long exterior wall and its real adjoining room, never a toy house."""
    for building in plan['buildings']:
        for wall in sorted(building['walls'], key=lambda w: -math.dist(w['from'], w['to'])):
            if (not wall.get('exterior') or wall.get('state') == 'ghost'
                    or wall.get('kind', 'solid') != 'solid'
                    or math.dist(wall['from'], wall['to']) < 8):
                continue
            room = next((r for r in building['rooms'] if r.get('state') != 'ghost'
                         and r.get('kind') != 'porch' and _owns_wall(r, wall)), None)
            if room:
                return building, wall, room
    raise AssertionError('Household fixture needs an exterior solid wall adjoining a room')


def _seed(model_kinds):
    from services import twin_imports, twin_materials, twin_store
    from PIL import Image

    twin_store.start_over()
    M._prepare(None)
    assets = {}
    for key, name, tint in [('current', 'Slice 6 current ochre', '#dc9c22'),
                            ('selected', 'Slice 6 selected blue', '#143cff'),
                            ('dragged', 'Slice 6 dragged magenta', '#ed167a')]:
        assets[key] = twin_materials.create({'name': name, 'params': {
            'tint': tint, 'roughness': 1, 'metalness': 0}}, H.PARENT['id'])
    # Use the existing real-file GLB fixture, not a catalogue-only fake model.
    # Like the import UI, supply a PNG preview; preview generation is not the
    # subject of these assignment/action-bar scenarios.
    image = BytesIO()
    Image.new('RGB', (16, 32), '#789abc').save(image, format='PNG')
    thumbnail = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode('ascii')
    for kind in model_kinds:
        assets[kind] = twin_imports.create({'fixture.glb': fixture_glb()},
                                           f'Slice 6 {kind} model', kind, thumbnail=thumbnail)
    building, wall, room = _target(twin_store.current())

    def defaults(plan):
        b = next(b for b in plan['buildings'] if b['id'] == building['id'])
        w = next(w for w in b['walls'] if w['id'] == wall['id'])
        # Both face rows have an explicit, strongly contrasting starting look.
        w['faces'] = {side: {'id': assets['current']['id']} for side in ('left', 'right')}
        next(r for r in b['rooms'] if r['id'] == room['id'])['floor_material'] = {'id': assets['current']['id']}
        return plan

    twin_store.update_current(defaults, 'build')
    return assets


@contextmanager
def _page(model_kinds=()):
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; Library assignment checks skipped') from error
    assets = _seed(model_kinds)
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; Library assignment checks skipped')
    browser = SERVED.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_viewport_size({'width': 1600, 'height': 1000})
            page.set_default_timeout(TIMEOUT)
            page.set_default_navigation_timeout(TIMEOUT)
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
            yield page, assets
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; Library assignment checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _mount_row(page, host, row):
    """The slice-5 tree virtualizes large expanded branches."""
    if not row.count():
        host.get_by_role('treeitem').first.press('Home')
        H.settle(page)
        for _ in range(120):
            if row.count():
                break
            box = host.bounding_box()
            assert box and box['height'] > 0, 'Scene tree has no visible scroll viewport'
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.wheel(0, max(36, box['height'] * .65))
            H.settle(page, 3)
    assert row.count() == 1, f'Scene row missing or ambiguous: {row}'
    row.scroll_into_view_if_needed()
    return row


def _select_piece(page, building, piece, kind):
    page.click('#dock-tab-scene')
    host = page.locator('#scene-tree')
    # Read the actual ownership chain; hosted openings need not carry a level,
    # and ownership may differ from the first geometrically adjoining room.
    # Only the following disclosure clicks expand the real Scene tree.
    ancestors = page.evaluate('''async ({bid,id}) => {
        const {sceneRows}=await import(window.chfBase+'static/twin/editor/scene_tree.js');
        const row=sceneRows(window.__twin.plan).find(r=>r.id===id && r.building===bid);
        if (!row) throw Error('Missing Scene record: '+bid+'/'+id);
        const parents=[];
        for (let p=row.parent;p;p=p.parent) parents.unshift({id:p.id,floor:p.floorKey});
        return parents;
    }''', {'bid': building['id'], 'id': piece['id']})
    for ancestor in ancestors:
        parent = (host.locator(f'[data-floor="{ancestor["floor"]}"]').locator('..')
                  if ancestor.get('floor') else host.locator(f'[data-scene-id="{ancestor["id"]}"]'))
        parent = _mount_row(page, host, parent)
        disclosure = parent.locator('[data-row-disclosure][aria-expanded="false"]')
        if disclosure.count():
            disclosure.click()
        assert parent.get_attribute('aria-expanded') == 'true', f'Scene ancestor did not expand: {ancestor}'
    row = _mount_row(page, host, host.locator(f'[data-scene-id="{piece["id"]}"]'))
    row.locator('[data-scene-select]').click()
    _wait(page, '(id) => window.__twinEditor.selection().id === id', piece['id'])
    _settled(page)


def _library(page, tab='materials'):
    page.click('#dock-tab-library')
    page.locator(f'[data-library-tab="{tab}"]').click()
    _wait(page, '(tab) => document.querySelector(`[data-library-tab="${tab}"]`).getAttribute("aria-selected") === "true"', tab)


def _tile(page, asset, material=True):
    key = 'material' if material else 'item'
    tile = page.locator(f'#library-entries [data-{key}="{asset["id"]}"]')
    tile.wait_for(state='visible')
    tile.scroll_into_view_if_needed()
    return tile


def _select_asset(page, asset, material=True):
    _tile(page, asset, material).click()
    _wait(page, 'id => document.querySelector(`[data-material="${id}"], [data-item="${id}"]`)?.getAttribute("aria-pressed") === "true"', asset['id'])


def _slot(page, label):
    return page.locator(f'#piece-card [data-library-slot="{label}"]')


def _drag(page, tile, point=None, *, row=None):
    tile.scroll_into_view_if_needed()
    if row is not None:
        # Resolve after scrolling the source: scrollIntoView may move outer
        # ancestors too. A nonempty bounding box alone does not prove a hit.
        target = row.locator('[data-slot-name]')
        box = target.bounding_box()
        assert box and box['width'] > 0 and box['height'] > 0, 'Slot name has no hit area'
        point = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        assert target.evaluate('''(node,[x,y]) => node.closest('[data-library-slot]') ===
            document.elementFromPoint(x,y)?.closest('[data-library-slot]')''', list(point)), 'Slot name is clipped or covered before drag'
    box = tile.bounding_box()
    assert box and box['width'] > 0 and box['height'] > 0
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    try:
        page.mouse.move(*point, steps=20)
        H.settle(page, 3)
        if row is not None:
            assert 'editor-slot-dragover' in (row.get_attribute('class') or ''), 'Captured Library drag did not reach the visible slot row'
    finally:
        page.mouse.up()


def _wall_view(page, building, wall, room):
    """Face the outside of the wall; sample only real, unobstructed wall hits."""
    H.choose_floor(page, f'{building["id"]}:{wall["level"]}')
    middle = [(a + b) / 2 for a, b in zip(wall['from'], wall['to'])]
    dx, dy = [b - a for a, b in zip(wall['from'], wall['to'])]
    length = math.hypot(dx, dy)
    normal = [-dy / length, dx / length]
    centre = [sum(p[i] for p in room['polygon']) / len(room['polygon']) for i in (0, 1)]
    side = 'left'
    if sum(normal[i] * (centre[i] - middle[i]) for i in (0, 1)) > 0:
        normal = [-v for v in normal]
        side = 'right'
    level = next(l for l in building['levels'] if l['id'] == wall['level'])
    z = level.get('elevation', 0) + wall.get('height', level.get('ceiling', 8)) * .55
    H.look_at(page, building['id'], [middle[0] + normal[0] * 24,
                                    middle[1] + normal[1] * 24, z + 2], [*middle, z])
    page.locator('#editor-view-menu > summary').click()
    page.click('[data-editor-lighting="day"]')
    page.locator('#editor-view-menu > summary').click()
    _settled(page)
    points = []
    for height in (.55, .8, .3, .94):
        for fraction in (.5, .3, .7, .15, .85):
            local = [wall['from'][i] + (wall['to'][i] - wall['from'][i]) * fraction
                     + normal[i] * ((wall.get('thickness') or .33) / 2 + .01) for i in (0, 1)]
            point = H.screen_of_world(page, *local,
                                      level.get('elevation', 0) + wall.get('height', 8) * height,
                                      building['id'])
            point = [round(v) for v in point]
            if page.evaluate("""({point,id,bid}) => {
                const v=window.__twin, [x,y]=point, hit=v.pick(x,y);
                return document.elementFromPoint(x,y)===v.renderer3.domElement
                    && hit?.kind==='wall' && (hit.id||hit.pieceId)===id
                    && (hit.building||hit.buildingId)===bid;
            }""", {'point': point, 'id': wall['id'], 'bid': building['id']}):
                points.append(point)
    assert points, f'No unobstructed face pixels for {wall["id"]}'
    return side, points


def _pixels(page, points):
    from PIL import Image
    image = Image.open(BytesIO(page.screenshot(animations='disabled', scale='css'))).convert('RGB')
    return [image.getpixel(tuple(point)) for point in points]


def _stored_building(bid):
    from services import twin_store
    return next(b for b in twin_store.current()['buildings'] if b['id'] == bid)


def scenario_use_selected_assigns_a_wall_face():
    with _page() as (page, assets):
        building, wall, room = _target(_plan(page))
        side, points = _wall_view(page, building, wall, room)
        _library(page)
        _select_asset(page, assets['selected'])
        # Scene selection must preserve the independent Library selection.
        _select_piece(page, building, wall, 'wall')
        row = _slot(page, 'Outside')
        row.get_by_role('button', name=f'Use {assets["selected"]["name"]}', exact=True).wait_for()
        page.mouse.move(10, 70)
        _settled(page)
        before = _pixels(page, points)
        row.get_by_role('button', name=f'Use {assets["selected"]["name"]}', exact=True).click()
        _wait(page, """({bid,id,side,mid}) => window.__twin.plan.buildings.find(b=>b.id===bid)
            ?.walls.find(w=>w.id===id)?.faces?.[side]?.id===mid""",
              {'bid': building['id'], 'id': wall['id'], 'side': side, 'mid': assets['selected']['id']})
        _settled(page)
        after = _pixels(page, points)
        assert any(max(abs(a - b) for a, b in zip(old, new)) > 10
                   for old, new in zip(before, after)), (points, before, after)
        stored = next(w for w in _stored_building(building['id'])['walls'] if w['id'] == wall['id'])
        assert stored['faces'][side] == {'id': assets['selected']['id']}
        other = 'right' if side == 'left' else 'left'
        assert stored['faces'][other] == {'id': assets['current']['id']}


def scenario_drag_tile_onto_a_floor_row():
    with _page() as (page, assets):
        building, _, room = _target(_plan(page))
        _select_piece(page, building, room, 'room')
        _library(page)
        _select_asset(page, assets['selected'])
        row = _slot(page, 'Floor')
        row.scroll_into_view_if_needed()
        tile = _tile(page, assets['dragged'])
        assert row.count() == 1, 'Selected room must expose exactly one Floor row'
        _drag(page, tile, row=row)
        _wait(page, """({bid,id,mid}) => window.__twin.plan.buildings.find(b=>b.id===bid)
            ?.rooms.find(r=>r.id===id)?.floor_material?.id===mid""",
              {'bid': building['id'], 'id': room['id'], 'mid': assets['dragged']['id']})
        _settled(page)
        assert _tile(page, assets['selected']).get_attribute('aria-pressed') == 'true'
        assert _tile(page, assets['dragged']).get_attribute('aria-pressed') == 'false'
        row.get_by_role('button', name=f'Use {assets["selected"]["name"]}', exact=True).wait_for()
        assert page.locator('#material-chooser').count() == 0
        stored = next(r for r in _stored_building(building['id'])['rooms'] if r['id'] == room['id'])
        assert stored['floor_material'] == {'id': assets['dragged']['id']}


def scenario_swatch_reveals_current_material():
    with _page() as (page, assets):
        building, _, room = _target(_plan(page))
        _select_piece(page, building, room, 'room')
        _library(page)
        page.locator('#library-search').fill('no such slice six material')
        _wait(page, '() => !document.querySelector("#library-entries [data-material]")')
        page.locator('[data-library-tab="items"]').click()
        _wait(page, '() => document.querySelector("[data-library-tab=items]").getAttribute("aria-selected")==="true"')
        page.click('#dock-tab-scene')
        before = _plan(page)
        _slot(page, 'Floor').get_by_role('button', name='Show the floor material in the Library', exact=True).click()
        _wait(page, """id => {
            const pane=document.querySelector('#dock-pane-library'), host=document.querySelector('#library-entries');
            const tile=host.querySelector(`[data-material="${id}"]`);
            if(pane.hidden || !tile || document.querySelector('[data-library-tab=materials]').getAttribute('aria-selected')!=='true')return false;
            // The dock pane owns scrolling; #library-entries itself has
            // overflow:visible. Check its clipped visible box, not the full grid.
            const r=tile.getBoundingClientRect(), h=host.getBoundingClientRect(), p=pane.getBoundingClientRect();
            return r.width>0 && r.height>0 && r.top>=Math.max(h.top,p.top,0)-1
                && r.bottom<=Math.min(h.bottom,p.bottom,innerHeight)+1
                && r.left>=Math.max(h.left,p.left,0)-1
                && r.right<=Math.min(h.right,p.right,innerWidth)+1
                && tile.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
        }""", assets['current']['id'])
        assert page.locator('#library-search').input_value() == ''
        # Do not call _tile here: its scroll helper would mask a reveal failure.
        tile = page.locator(f'#library-entries [data-material="{assets["current"]["id"]}"]')
        assert tile.get_attribute('aria-pressed') == 'false'
        assert page.locator('#library-entries [aria-pressed="true"]').count() == 0
        assert page.locator('#library-actions').is_hidden()
        assert _plan(page) == before, 'Revealing a swatch authored an edit'


def scenario_door_model_row():
    with _page(('door', 'window')) as (page, assets):
        building, door = next((b, o) for b in _plan(page)['buildings'] for o in b['openings']
                              if o['kind'] == 'door' and o.get('state') != 'ghost')
        _select_piece(page, building, door, 'opening')
        _library(page)
        _select_asset(page, assets['selected'])
        model = _slot(page, 'Model')
        assert model.get_by_role('button', name='Use selected', exact=True).is_disabled()
        _library(page, 'items')
        _select_asset(page, assets['window'], material=False)
        assert model.get_by_role('button', name='Use selected', exact=True).is_disabled()
        _select_asset(page, assets['door'], material=False)
        model.get_by_role('button', name=f'Use {assets["door"]["name"]}', exact=True).click()
        _wait(page, """({bid,id,asset}) => window.__twin.plan.buildings.find(b=>b.id===bid)
            ?.openings.find(o=>o.id===id)?.model===asset""",
              {'bid': building['id'], 'id': door['id'], 'asset': assets['door']['id']})
        _settled(page)
        assert next(o for o in _stored_building(building['id'])['openings'] if o['id'] == door['id'])['model'] == assets['door']['id']
        model.get_by_text(assets['door']['name'], exact=True).wait_for()
        model.get_by_role('button', name='Clear the door model', exact=True).click()
        _wait(page, """({bid,id}) => !window.__twin.plan.buildings.find(b=>b.id===bid)
            ?.openings.find(o=>o.id===id)?.model""", {'bid': building['id'], 'id': door['id']})
        _settled(page)
        model.get_by_text('Generated', exact=True).wait_for()
        stored = next(o for o in _stored_building(building['id'])['openings'] if o['id'] == door['id'])
        assert not stored.get('model')
        assert all(stored[k] == door[k] for k in ('wall', 'at', 'width', 'sill', 'head'))


def scenario_action_bar_rename_and_delete():
    with _page(('furniture',)) as (page, assets):
        asset = assets['furniture']
        _library(page, 'items')
        _select_asset(page, asset, material=False)
        actions = page.locator('#library-actions')
        actions.get_by_role('button', name=f'Rename {asset["name"]}', exact=True).click()
        page.locator('#cc-input-modal').wait_for(state='visible')
        assert page.locator('#cc-input-title').inner_text() == 'Model name'
        assert page.locator('#cc-input-field').input_value() == asset['name']
        renamed = 'Slice 6 renamed model'
        page.locator('#cc-input-field').fill(renamed)
        page.click('#cc-input-ok-btn')
        page.locator('#cc-input-modal').wait_for(state='hidden')
        page.locator(f'#library-entries [data-item="{asset["id"]}"]').get_by_text(renamed, exact=True).wait_for()
        assert _tile(page, asset, material=False).get_attribute('aria-label') == renamed
        assert _tile(page, asset, material=False).get_attribute('aria-pressed') == 'true'
        from services import twin_imports
        assert twin_imports.get(asset['id'])['name'] == renamed
        actions.get_by_role('button', name=f'Delete {renamed}', exact=True).click()
        page.locator('#cc-confirm-modal').wait_for(state='visible')
        assert page.locator('#cc-confirm-title').inner_text() == f'Delete {renamed}?'
        assert page.locator('#cc-confirm-execute-btn').inner_text() == 'Delete'
        page.click('#cc-confirm-execute-btn')
        page.locator('#cc-confirm-modal').wait_for(state='hidden')
        page.locator(f'#library-entries [data-item="{asset["id"]}"]').wait_for(state='detached')
        actions.wait_for(state='hidden')
        assert page.locator('#library-entries [aria-pressed="true"]').count() == 0
        assert not any(e['id'] == asset['id'] and not e.get('archived') for e in twin_imports.catalog())


def scenario_drop_menu_unchanged():
    with _page() as (page, assets):
        building, wall, room = _target(_plan(page))
        _, points = _wall_view(page, building, wall, room)
        _library(page)
        # Keep the chooser away from its documented viewport-edge clamp.
        viewport = page.viewport_size
        point = next((p for p in points if 96 <= p[0] <= viewport['width'] - 240
                      and 74 <= p[1] <= viewport['height'] - 240), None)
        assert point, 'Wall has no visible drop point inside the chooser clamp'
        operations = []
        page.on('request', lambda request: operations.append(request.post_data_json['op'])
                if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op') else None)
        before = _plan(page)
        _drag(page, _tile(page, assets['selected']), point)
        chooser = page.locator('#material-chooser')
        chooser.wait_for(state='visible')
        assert chooser.get_by_role('button').all_text_contents() == [
            'This wall face', 'This room', 'This floor', 'The whole building', 'Cancel']
        box = chooser.bounding_box()
        assert box and abs(box['x'] - point[0]) <= 2 and abs(box['y'] - point[1]) <= 2, (point, box)
        assert not operations and _plan(page) == before, 'Drop applied before scope choice'
        chooser.get_by_role('button', name='This room', exact=True).click()
        chooser.wait_for(state='detached')
        _wait(page, """({bid,id,mid}) => window.__twin.plan.buildings.find(b=>b.id===bid)
            ?.rooms.find(r=>r.id===id)?.wall_material?.id===mid""",
              {'bid': building['id'], 'id': room['id'], 'mid': assets['selected']['id']})
        _settled(page)
        assert operations == [{'op': 'set_material', 'building': building['id'],
                               'target': {'room': room['id'], 'surface': 'walls'},
                               'material': {'id': assets['selected']['id']}}], operations
        assert next(r for r in _stored_building(building['id'])['rooms'] if r['id'] == room['id'])['wall_material'] == {'id': assets['selected']['id']}
        before = _plan(page)
        count = len(operations)
        _drag(page, _tile(page, assets['dragged']), point)
        chooser.wait_for(state='visible')
        page.keyboard.press('Escape')
        chooser.wait_for(state='detached')
        _settled(page)
        page.wait_for_timeout(750)
        assert len(operations) == count, 'Escape sent a second material operation'
        assert _plan(page) == before, 'Escape changed the house'


def main():
    scenarios = [scenario_use_selected_assigns_a_wall_face,
                 scenario_drag_tile_onto_a_floor_row,
                 scenario_swatch_reveals_current_material,
                 scenario_door_model_row,
                 scenario_action_bar_rename_and_delete,
                 scenario_drop_menu_unchanged]
    passed = failed = 0
    try:
        for scenario in scenarios:
            try:
                scenario()
            except M.MeasurementSkipped as error:
                print('  skip ', error)
                print(f'{passed}/{len(scenarios)} passed; remaining scenarios skipped')
                return int(failed > 0)
            except Exception:
                failed += 1
                traceback.print_exc(limit=8)
                print('FAIL', scenario.__name__)
            else:
                passed += 1
                print('ok  ', scenario.__name__)
        print(f'{passed}/{len(scenarios)} passed')
        return int(failed > 0)
    finally:
        if SERVED is not None:
            SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())
