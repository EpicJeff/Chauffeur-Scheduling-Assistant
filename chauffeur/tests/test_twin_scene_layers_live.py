"""Slice 5 acceptance: Scene/Layers hide and lock through real Chromium UI.

Run from chauffeur/: python tests/test_twin_scene_layers_live.py
Written without launching a browser; Claude runs these acceptance scenarios.
All service imports happen after scratch storage is selected. Camera positioning
uses the existing live-test hooks; authored edits and visibility use real UI.
"""
from contextlib import contextmanager
from io import BytesIO
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import traceback
from uuid import uuid4

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_scene_layers_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_edit_measure as M
import house_editor_model_harness as H
from live_app import live_app

SERVED = None
TIMEOUT = 40000
QUERY = 'tier=low&test=1&timing=1'
TREE_AT = [20, 125]


def _seed(plan):
    x, y = TREE_AT
    for index, (dx, dy) in enumerate(((0, 0), (18, 0), (0, 18))):
        plan['site'].setdefault('planting', []).append({
            'id': 'plant:' + str(uuid4()), 'kind': 'tree',
            'name': f'Scene acceptance tree {index + 1}', 'preset': 'Pine Medium',
            'height': 12, 'seed': 7 + index, 'at': [x + dx, y + dy],
        })
    # Put the first tree inside the pad, away from its corner handles.
    plan['site'].setdefault('terraces', []).append({
        'id': 'pad:' + str(uuid4()), 'name': 'Scene acceptance pad',
        'height': 0, 'blend': 0,
        'polygon': [[x - 8, y - 8], [x + 8, y - 8],
                    [x + 8, y + 8], [x - 8, y + 8]],
    })
    return plan


def _settled(page):
    condition = """() => window.__twin?.ready && !window.__twin.__measureWork
        && document.querySelector('#editor-save-state').textContent.trim() === 'Saved'"""
    page.wait_for_function(condition, timeout=TIMEOUT)
    page.evaluate('async () => { await window.__twin.afterNextRender(); await window.__twin.afterNextRender(); }')
    page.wait_for_function(condition, timeout=TIMEOUT)


def _editor_ready(page):
    page.wait_for_function('window.__editor?.ready === true && !!window.__twinEditor', timeout=TIMEOUT)
    page.wait_for_function("window.__twin?.ready && window.__twin.plan?.buildings?.length > 0"
                           " && window.__twin.pieceIds(window.__twin.plan.buildings[0].id).length > 0",
                           timeout=TIMEOUT)
    # Same shell behaviour as test_house_editor_live._open; never click behind
    # the automatically opened Your place/front-door dialog.
    H.settle(page, 4)
    if page.locator('#editor-dialog').is_visible():
        page.click('#editor-dialog-close')
        page.locator('#editor-dialog').wait_for(state='hidden', timeout=TIMEOUT)
    M._dismiss_alert(page)
    M._track_view_work(page)
    page.evaluate('window.__twin.controls.enableDamping = false')
    _settled(page)


@contextmanager
def _page():
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; Scene/Layers checks skipped') from error
    from services import twin_store

    twin_store.start_over()
    M._prepare(None)
    twin_store.update_current(_seed, 'build')
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; Scene/Layers checks skipped')
    browser = SERVED.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_default_timeout(TIMEOUT)
            page.set_default_navigation_timeout(TIMEOUT)
            H.signed_in(page)
            page.goto(SERVED.url(f'house/editor?{QUERY}'), timeout=TIMEOUT)
            _editor_ready(page)
            page.click('#rail-select')
            yield page
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; Scene/Layers checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _plan(page):
    return page.evaluate('window.__twin.plan')


def _tree(page):
    return next(p for p in _plan(page)['site']['planting'] if p.get('name') == 'Scene acceptance tree 1')


def _wall_pair(page):
    """Two built, joined walls on one level of the real household fixture."""
    for building in _plan(page)['buildings']:
        walls = [w for w in building['walls'] if w.get('state') != 'ghost'
                 and w.get('kind', 'solid') == 'solid' and math.dist(w['from'], w['to']) > 6]
        for wall in sorted(walls, key=lambda w: -math.dist(w['from'], w['to'])):
            neighbour = next((w for w in walls if w['id'] != wall['id'] and w['level'] == wall['level']
                              and any(math.dist(a, b) < .01 for a in (wall['from'], wall['to'])
                                      for b in (w['from'], w['to']))), None)
            if neighbour:
                return building, wall, neighbour
    raise AssertionError('The built fixture has no pair of joined solid walls')


def _mount_row(page, host, row):
    """Scroll the real tree to mount a row outside the virtual window."""
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


def _row(page, piece_id):
    """Open a wall's ancestors by real UI, then scroll to its virtual row."""
    page.click('#dock-tab-scene')
    host = page.locator('#scene-tree')
    row = host.locator(f'[data-scene-id="{piece_id}"]')
    if not row.count():
        # Rooms now start collapsed. Read only the fixture's ownership here;
        # every expansion still presses the real accessible disclosure button.
        for building in _plan(page)['buildings']:
            wall = next((w for w in building.get('walls', []) if w['id'] == piece_id), None)
            if wall is None:
                continue
            def owns_wall(room):
                joints = room.get('joints', [])
                return wall['id'] in room.get('walls', []) or (
                    len(wall.get('joints', [])) == 2 and any(
                        set((joint, joints[(i + 1) % len(joints)])) == set(wall['joints'])
                        for i, joint in enumerate(joints)))

            owner = next((r for r in building.get('rooms', []) if owns_wall(r)), None)
            ancestors = [building['id'], wall['level']] + ([owner['id']] if owner else [])
            for ancestor in ancestors:
                parent = host.locator(f'[data-scene-id="{ancestor}"]')
                if ancestor == wall['level']:
                    parent = host.locator(f'[data-floor="{building["id"]}:{ancestor}"]').locator('..')
                parent = _mount_row(page, host, parent)
                toggle = parent.locator('[data-row-disclosure][aria-expanded="false"]')
                if toggle.count():
                    toggle.click()
            break
    return _mount_row(page, host, row)


def _name(row):
    return row.locator('[data-row-label]').inner_text().strip()


def _toggle(page, piece_id, action):
    row = _row(page, piece_id)
    name = _name(row)
    row.get_by_role('button', name=f'{action} {name}', exact=True).click()
    H.settle(page, 4)
    reverse = {'Hide': 'Show', 'Show': 'Hide', 'Lock': 'Unlock', 'Unlock': 'Lock'}[action]
    button = _row(page, piece_id).get_by_role('button', name=f'{reverse} {name}', exact=True)
    assert button.get_attribute('aria-pressed') == str(action in ('Hide', 'Lock')).lower()
    return name


def _select_row(page, piece_id):
    _row(page, piece_id).locator('[data-scene-select]').click()
    _settled(page)


# Read real merged buffers, rather than pick proxies (which survive hiding).
WALL_RANGES = """([id, building]) => {
    const rows = [];
    window.__twin.scene.traverse(o => {
        const p = o.geometry?.attributes.position;
        if (!p) return;
        for (const r of o.userData.snapRanges || o.geometry.userData.snapRanges || []) {
            if (r.pieceId !== id || r.kind !== 'wall' || r.buildingId && r.buildingId !== building || !r.count) continue;
            rows.push({start:r.start, count:r.count,
                       positions:Array.from(p.array.slice(r.start*3,(r.start+r.count)*3))});
        }
    });
    return rows;
}"""


def _ranges(page, building, wall):
    rows = page.evaluate(WALL_RANGES, [wall['id'], building['id']])
    assert rows, f'No merged wall ranges for {building["id"]}/{wall["id"]}'
    return rows


def _collapsed(rows):
    return all(all(values[i:i + 3] == values[:3] for i in range(0, len(values), 3))
               for values in (row['positions'] for row in rows))


def _assert_collapsed(page, building, wall):
    rows = _ranges(page, building, wall)
    assert _collapsed(rows), f'Hidden wall still has noncollapsed geometry: {wall["id"]}'


def _wall_view(page, building, wall):
    H.choose_floor(page, f'{building["id"]}:{wall["level"]}')
    middle = [(a + b) / 2 for a, b in zip(wall['from'], wall['to'])]
    level = next(l for l in building['levels'] if l['id'] == wall['level'])
    H.look_down(page, building['id'], *middle, height=35 + level.get('elevation', 0))
    # Unlit keeps the sampled wall independent of moving sun/shadows.
    page.locator('#editor-view-menu > summary').click()
    page.click('[data-editor-lighting="unlit"]')
    page.locator('#editor-view-menu > summary').click()
    _settled(page)


def _wall_pixels(page, building, wall):
    """Interior centroids of upward-facing wall triangles, before collapse.

    Sampling several cap triangles avoids hard-coding one pixel into an opening
    or an occluding neighbour; at least one must change and return below.
    """
    points = page.evaluate("""([id,bid]) => {
        const v=window.__twin, points=new Map(), rect=v.renderer3.domElement.getBoundingClientRect();
        v.scene.updateMatrixWorld(true); v.camera.updateMatrixWorld(true);
        v.scene.traverse(o => {
            if (!o.isMesh || !o.visible || !o.geometry?.attributes.position) return;
            for (let parent=o.parent;parent;parent=parent.parent) if (!parent.visible) return;
            const p=o.geometry.attributes.position;
            for (const r of o.userData.snapRanges || o.geometry.userData.snapRanges || []) {
                if(r.pieceId!==id || r.kind!=='wall' || r.buildingId && r.buildingId!==bid) continue;
                for(let i=r.start;i+2<r.start+r.count;i+=3) {
                    const a=v.camera.position.clone().fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);
                    const b=a.clone().fromBufferAttribute(p,i+1).applyMatrix4(o.matrixWorld);
                    const c=a.clone().fromBufferAttribute(p,i+2).applyMatrix4(o.matrixWorld);
                    const normal=b.clone().sub(a).cross(c.clone().sub(a)).normalize();
                    if(normal.y<.8) continue;
                    const q=a.add(b).add(c).multiplyScalar(1/3).project(v.camera);
                    const x=Math.round(rect.left+(q.x+1)*rect.width/2), y=Math.round(rect.top+(1-q.y)*rect.height/2);
                    if(q.z>=-1 && q.z<=1 && document.elementFromPoint(x,y)===v.renderer3.domElement)
                        points.set(x+','+y,[x,y]);
                }
            }
        }); return [...points.values()].slice(0,80);
    }""", [wall['id'], building['id']])
    assert points, 'No unobstructed wall-cap screen positions to sample'
    return points


def _pixels(page, points):
    from PIL import Image
    image = Image.open(BytesIO(page.screenshot(animations='disabled', scale='css'))).convert('RGB')
    return [image.getpixel(tuple(p)) for p in points]


def _look_at_tree(page, tree):
    x, y = tree['at']
    page.evaluate("""([x,y]) => {
        const v=window.__twin, ft=.3048;
        v.setCamera('front');
        v.setCameraState({position:[x*ft,70*ft,-(y-.01)*ft], target:[x*ft,0,-y*ft]});
        v.camera.updateMatrixWorld(true);
    }""", [x, y])
    H.settle(page, 4)
    return page.evaluate("""([x,y]) => {
        const v=window.__twin, r=v.renderer3.domElement.getBoundingClientRect();
        const q=v.camera.position.clone().set(x*.3048,0,-y*.3048).project(v.camera);
        return [r.left+(q.x+1)*r.width/2,r.top+(1-q.y)*r.height/2];
    }""", [x, y])


PLANT_STATE = """() => {
    const v=window.__twin, rows=[];
    const owner = o => {
        for(let p=o;p;p=p.parent) if(p.userData.kind==='planting' && p.userData.pieceId) return p.userData.pieceId;
        return null;
    };
    const visible = o => { for(let p=o;p;p=p.parent) if(!p.visible) return false; return true; };
    v.scene.updateMatrixWorld(true);
    v.scene.traverse(o => {
        if(!o.isMesh || !v.camera.layers.test(o.layers)) return;
        if(o.isInstancedMesh && (o.userData.instances || o.userData.instancePiece)) {
            for(let i=0;i<o.count;i++) {
                const p=o.userData.instances?.[i] || o.userData.instancePiece?.(i);
                if(p?.kind!=='planting') continue;
                const matrix=Array.from(o.instanceMatrix.array.slice(i*16,(i+1)*16));
                const zero=[0,1,2,4,5,6,8,9,10].every(k=>matrix[k]===0);
                rows.push({id:p.pieceId || p.id, key:o.uuid+':'+i, matrix, drawn:visible(o)&&!zero});
            }
        } else {
            const id=owner(o); if(!id) return;
            const matrix=o.matrixWorld.toArray();
            const zero=[0,1,2,4,5,6,8,9,10].every(k=>matrix[k]===0);
            rows.push({id, key:o.uuid, matrix, drawn:visible(o)&&!zero});
        }
    }); return rows;
}"""


def _plants(page):
    rows = page.evaluate(PLANT_STATE)
    expected = {p['id'] for p in _plan(page)['site']['planting']
                if p.get('at') and p.get('preset') and p.get('height', 0) > 0 and p.get('state') != 'ghost'}
    assert expected and expected <= {row['id'] for row in rows}, (expected, rows)
    return rows


def scenario_hidden_wall_leaves_and_returns():
    with _page() as page:
        building, wall, _ = _wall_pair(page)
        _wall_view(page, building, wall)
        before = _ranges(page, building, wall)
        assert not _collapsed(before), 'Wall started collapsed'
        points = _wall_pixels(page, building, wall)
        pixels = _pixels(page, points)
        _toggle(page, wall['id'], 'Hide')
        _assert_collapsed(page, building, wall)
        hidden = _pixels(page, points)
        changed = [i for i, (a, b) in enumerate(zip(pixels, hidden))
                   if max(abs(x - y) for x, y in zip(a, b)) > 15]
        assert changed, (points, pixels, hidden)
        _toggle(page, wall['id'], 'Show')
        assert _ranges(page, building, wall) == before, 'Show did not restore exact position arrays'
        restored = _pixels(page, points)
        assert all(max(abs(a - b) for a, b in zip(pixels[i], restored[i])) <= 3 for i in changed), (
            pixels, hidden, restored)


def scenario_locked_tree_lets_clicks_through():
    with _page() as page:
        tree = _tree(page)
        pad = next(p for p in _plan(page)['site']['terraces'] if p.get('name') == 'Scene acceptance pad')
        H.all_floors(page)
        pixel = _look_at_tree(page, tree)
        # Positive control: this exact ray really can select the tree before lock.
        H._on_canvas(page, *pixel)
        page.mouse.click(*pixel)
        H.settle(page)
        selection = H.editor_state(page, 'selection')
        assert selection['kind'] == 'planting' and selection['id'] == tree['id'], selection
        page.keyboard.press('Escape')
        _toggle(page, tree['id'], 'Lock')
        for _ in range(8):  # Same-client-pixel clicks are the shared picker's cycle gesture.
            H._on_canvas(page, *pixel)
            page.mouse.click(*pixel)
            H.settle(page, 3)
            selection = H.editor_state(page, 'selection')
            assert selection.get('id') != tree['id'], selection
            # Terrain owns pad selection separately from scene selection. Bare
            # lawn clears it; neither path may leave the previous tree selected.
            assert selection.get('id') in (None, pad['id']), selection
            assert selection.get('kind') in (None, 'terraces', 'pad'), selection
        assert page.locator('#terrain-card').is_visible(), 'Click never reached the pad beneath the locked tree'
        assert 'Terrace pad' in page.locator('#terrain-card h3').all_inner_texts()
        _select_row(page, tree['id'])
        assert H.editor_state(page, 'selection')['id'] == tree['id']
        assert H.card_title(page) == tree['name'], H.card_title(page)
        assert page.locator('#properties-content #piece-card').is_visible()
        for tool in ('select', 'move', 'rotate', 'scale'):
            page.click(f'#rail-{tool}')
            H.settle(page, 4)
            assert H.editor_state(page, 'handles') == [], f'Locked tree has handles under {tool}'
            assert page.locator('.editor-handle:visible, [data-gizmo]:visible').count() == 0


def scenario_plants_layer_hides_every_plant():
    with _page() as page:
        H.all_floors(page)
        before = _plants(page)
        assert all(row['drawn'] for row in before), 'A planting started hidden'
        page.click('#dock-tab-layers')
        page.locator('#layer-kinds').get_by_role('button', name='Hide Plants', exact=True).click()
        H.settle(page, 4)
        show = page.locator('#layer-kinds').get_by_role('button', name='Show Plants', exact=True)
        assert show.get_attribute('aria-pressed') == 'true'
        hidden = _plants(page)
        assert {r['key'] for r in hidden} == {r['key'] for r in before}
        assert all(not row['drawn'] for row in hidden), hidden
        show.click()
        H.settle(page, 4)
        assert page.locator('#layer-kinds').get_by_role('button', name='Hide Plants', exact=True).get_attribute('aria-pressed') == 'false'
        assert _plants(page) == before, 'Showing Plants did not restore every object/matrix'


def _hide_and_lock(page):
    building, wall, _ = _wall_pair(page)
    tree = _tree(page)
    _toggle(page, wall['id'], 'Hide')
    _toggle(page, tree['id'], 'Lock')
    _assert_collapsed(page, building, wall)
    return building, wall, tree


def scenario_state_survives_reload():
    with _page() as page:
        building, wall, tree = _hide_and_lock(page)
        page.reload(timeout=TIMEOUT, wait_until='domcontentloaded')
        _editor_ready(page)
        for piece, action in ((wall, 'Show'), (tree, 'Unlock')):
            row = _row(page, piece['id'])
            assert row.get_by_role('button', name=f'{action} {_name(row)}', exact=True).get_attribute('aria-pressed') == 'true'
        _assert_collapsed(page, building, wall)
        pixel = _look_at_tree(page, tree)
        H._on_canvas(page, *pixel)
        page.mouse.click(*pixel)
        H.settle(page)
        assert H.editor_state(page, 'selection').get('id') != tree['id']


def scenario_viewer_draws_everything():
    with _page() as page:
        building, wall, tree = _hide_and_lock(page)
        storage = page.evaluate('JSON.stringify(localStorage)')
        # Navigate the SAME page/context: no clearing or rewriting editor storage.
        page.goto(SERVED.url('house/twin?tier=low&test=1'), timeout=TIMEOUT)
        page.wait_for_function('window.__twin?.ready && !!window.__twin.plan', timeout=TIMEOUT)
        page.evaluate('async () => { await window.__twin.afterNextRender(); await window.__twin.afterNextRender(); }')
        assert not _collapsed(_ranges(page, building, wall)), 'Viewer inherited the editor wall mask'
        plants = [p for p in _plants(page) if p['id'] == tree['id']]
        assert plants and all(p['drawn'] for p in plants), 'Viewer inherited hidden/locked planting state'
        assert page.evaluate("""([id,bid]) => {
            let drawn=false;
            window.__twin.scene.traverse(o => {
                if(!o.isMesh || !window.__twin.camera.layers.test(o.layers)) return;
                for(let p=o;p;p=p.parent) if(!p.visible) return;
                if((o.userData.snapRanges || o.geometry?.userData.snapRanges || [])
                    .some(r=>r.kind==='wall' && r.pieceId===id && (!r.buildingId || r.buildingId===bid))) drawn=true;
            }); return drawn;
        }""", [wall['id'], building['id']]), 'Viewer wall has no visible render mesh'
        # The viewer has structural pick()/pickAll(), but no planting picker:
        # twin_view.pickIntersections reads twin.pickObjects, while editor-only
        # library.siteHits supplies plant candidates (editor.js). Drawing is the
        # applicable viewer assertion; calling structural picking cannot hit a tree.
        # Viewer settings may write their own keys; editor's persisted masks must survive.
        editor_storage = {k: v for k, v in json.loads(storage).items() if k.startswith('chauffeur.editor.visibility.')}
        assert editor_storage, 'No editor visibility state was persisted'
        assert page.evaluate('keys => Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)]))', list(editor_storage)) == editor_storage


def scenario_edit_next_to_hidden_wall_keeps_it_hidden():
    with _page() as page:
        building, wall, neighbour = _wall_pair(page)
        _wall_view(page, building, neighbour)
        _toggle(page, wall['id'], 'Hide')
        _assert_collapsed(page, building, wall)
        _select_row(page, neighbour['id'])
        page.click('#rail-move')
        H.settle(page, 4)
        handle = next(h for h in H.editor_state(page, 'handles')
                      if h['kind'] == 'wall' and h['id'] == neighbour['id'])
        dx, dy = [b - a for a, b in zip(neighbour['from'], neighbour['to'])]
        length = math.hypot(dx, dy)
        start = H.screen_of_world(page, *handle['at'], building['id'])
        end = H.screen_of_world(page, handle['at'][0] - dy / length,
                                handle['at'][1] + dx / length, handle['at'][2], building['id'])
        # Same midpoint-handle gesture as twin_edit_measure._wall_drag, with
        # explicit tree selection replacing that helper's programmatic selection.
        page.evaluate('window.__twinEditTiming.length = 0')
        with page.expect_response(lambda r: r.request.method == 'POST'
                                  and r.url.split('?')[0].endswith('/api/house/editor/op'), timeout=TIMEOUT) as pending:
            M._mouse_release(page, start, end)
        response = pending.value
        assert response.status == 200, (response.status, response.text())
        operation = response.request.post_data_json['op']
        assert operation['op'] == 'move_wall' and operation['wall'] == neighbour['id'], operation
        # The editor publishes this record after the saved answer has settled
        # and its rendered frame/state refresh have completed (M._release_record).
        # Do not mistake the POST response or a local preview for that barrier.
        page.wait_for_function("""() => window.__twinEditTiming.some(record =>
            record.op === 'move_wall' && Number.isFinite(record.settle))""", timeout=TIMEOUT)
        M._wait_settled(page)
        after_building = next(b for b in _plan(page)['buildings'] if b['id'] == building['id'])
        after = next(w for w in after_building['walls'] if w['id'] == neighbour['id'])
        assert after['from'] != neighbour['from'] or after['to'] != neighbour['to'], 'Drag did not edit the level'
        _assert_collapsed(page, building, wall)
        row = _row(page, wall['id'])
        assert row.get_by_role('button', name=f'Show {_name(row)}', exact=True).get_attribute('aria-pressed') == 'true'
        # A further rendered frame must not undo the reapplied visibility mask.
        H.settle(page, 6)
        _assert_collapsed(page, building, wall)


def main():
    scenarios = [scenario_hidden_wall_leaves_and_returns,
                 scenario_locked_tree_lets_clicks_through,
                 scenario_plants_layer_hides_every_plant,
                 scenario_state_survives_reload,
                 scenario_viewer_draws_everything,
                 scenario_edit_next_to_hidden_wall_keeps_it_hidden]
    passed = 0
    failed = 0
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
