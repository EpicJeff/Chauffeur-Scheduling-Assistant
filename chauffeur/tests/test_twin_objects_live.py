"""Browser acceptance scenarios for slice 4a. WRITTEN, NOT RUN by Codex.

Run from chauffeur/: python tests/test_twin_objects_live.py
Uses the existing isolated live server, parent session and household fixture.
The generated fixture is a 1 x 2 x .1 metre GLB, with no external resources.
"""
import json
import io
import struct
import sys
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H


def fixture_glb():
    # One thin box; non-indexed triangles keep this fixture self-contained.
    corners = [(-.5, 0, -.05), (.5, 0, -.05), (.5, 2, -.05), (-.5, 2, -.05),
               (-.5, 0, .05), (.5, 0, .05), (.5, 2, .05), (-.5, 2, .05)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (3, 7, 6), (3, 6, 2), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    positions = [v for face in faces for i in face for v in corners[i]]
    binary = struct.pack('<' + 'f' * len(positions), *positions)
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}], 'buffers': [{'byteLength': len(binary)}],
           'bufferViews': [{'buffer': 0, 'byteLength': len(binary)}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 36, 'type': 'VEC3', 'min': [-.5, 0, -.05], 'max': [.5, 2, .05]}]}
    data = json.dumps(doc).encode(); data += b' ' * (-len(data) % 4)
    return b'glTF' + struct.pack('<II', 2, 28 + len(data) + len(binary)) + struct.pack('<II', len(data), 0x4E4F534A) + data + struct.pack('<II', len(binary), 0x004E4942) + binary


def import_model(page, name, kind):
    if page.locator('#library-panel').is_hidden():
        page.click('#rail-library')
    page.locator('#library-import-files').set_input_files({'name': name + '.glb', 'mimeType': 'model/gltf-binary', 'buffer': fixture_glb()})
    dialog = page.locator('.object-import'); dialog.wait_for(state='visible', timeout=30000)
    dialog.locator('input').fill(name); dialog.locator('select').select_option(kind)
    dialog.get_by_role('button', name='Add to library').click()
    page.locator('#library-entries button[data-item]').filter(has_text=name).wait_for()
    from services import twin_imports
    return next(e['id'] for e in twin_imports.catalog() if e['name'] == name)


def scenario_import_place_scale_rotate_undo_reload_and_programs():
    served = H.serve()
    if served is None:
        raise RuntimeError('Chromium acceptance requires the existing live harness.')
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served); H.choose_floor(page, 'pool-house:L1'); H.look_down(page, 'pool-house', 8, 8, height=35)
        asset = import_model(page, 'Imported chair', 'furniture')
        # The same press, nudge, travel and release as the editor's own library drag test (t15).
        thumb = page.locator(f'#library-panel [data-item="{asset}"]').first
        thumb.wait_for(state='visible', timeout=10000); thumb.scroll_into_view_if_needed(); start = thumb.bounding_box()
        end = H.screen_of_world(page, 8, 8, 0, 'pool-house'); H._on_canvas(page, *end)
        x, y = start['x'] + start['width'] / 2, start['y'] + start['height'] / 2
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 6, y + 6, steps=2)
        page.mouse.move(*end, steps=16); page.mouse.up(); H.settle(page)
        page.wait_for_function('(asset) => window.__twin.plan.buildings.some(b => b.items.some(i => i.asset === asset))', arg=asset)
        item = next(p for b in H.model()['buildings'] for p in b['items'] if p.get('asset') == asset)
        if page.locator('#library-panel').is_visible(): page.click('#rail-library')
        H.click_world(page, 8, 8, 1, 'pool-house')
        page.locator('#piece-card label').filter(has_text='Size').locator('input').fill('150')
        page.locator('#piece-card label').filter(has_text='Size').locator('input').press('Tab')
        page.wait_for_function('(id) => window.__twin.plan.buildings.some(b => b.items.some(i => i.id === id && i.scale === 1.5))', arg=item['id'])
        page.locator('#piece-card label').filter(has_text='Turn').locator('input').fill('90')
        page.locator('#piece-card label').filter(has_text='Turn').locator('input').press('Tab')
        page.wait_for_function('(id) => window.__twin.plan.buildings.some(b => b.items.some(i => i.id === id && i.rotation === 90))', arg=item['id'])
        page.click('#rail-undo')
        page.wait_for_function('(id) => window.__twin.plan.buildings.some(b => b.items.some(i => i.id === id && !i.rotation && i.scale === 1.5))', arg=item['id'])
        page.click('#rail-redo')
        page.wait_for_function('(id) => window.__twin.plan.buildings.some(b => b.items.some(i => i.id === id && i.rotation === 90))', arg=item['id'])
        page.reload(); page.wait_for_function('window.__editor?.ready === true', timeout=90000)
        persisted = next(p for b in H.model()['buildings'] for p in b['items'] if p['id'] == item['id'])
        H.check(persisted['scale'] == 1.5 and persisted['rotation'] == 90, persisted)
        H.choose_floor(page, 'pool-house:L1'); H.look_down(page, 'pool-house', 8, 8)
        # First show can compile imported materials. A warmed second orbit cannot.
        page.evaluate("() => { const v=window.__twin; v.setCamera('orbit'); v.renderer3.render(v.scene,v.camera); }")
        H.settle(page, 5)
        before = page.evaluate('window.__twin.renderer3.info.programs.length')
        page.evaluate("() => { const v=window.__twin; v.camera.position.x += 2; v.controls.update(); v.renderer3.render(v.scene,v.camera); }")
        H.settle(page, 5)
        H.check(page.evaluate('window.__twin.renderer3.info.programs.length') == before, 'Second orbit compiled a program')
        page.screenshot(path=str(Path(__file__).parent / 'objects-editor-live.png'))


def scenario_six_mb_chunk_zip_survives_one_mb_ingress_and_places_heavy_car():
    """WRITTEN ONLY: the route hook simulates ingress, never a production bypass."""
    triangles = 300001
    positions = struct.pack('<9f', -.5, 0, -.1, .5, 0, -.1, 0, 2, .1)
    indices = struct.pack('<3H', 0, 1, 2) * triangles
    binary = positions + indices
    binary += bytes(6 * 1048576 - len(binary))
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
           'buffers': [{'uri': 'scene.bin', 'byteLength': len(binary)}],
           'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions)},
                           {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(indices)}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [-.5, 0, -.1], 'max': [.5, 2, .1]},
                         {'bufferView': 1, 'componentType': 5123, 'count': triangles * 3, 'type': 'SCALAR'}]}
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('scene.gltf', json.dumps(doc)); archive.writestr('scene.bin', binary)
    served = H.serve()
    with served.browser(launch_args=H.GPU_ARGS) as page:
        attempts = []
        def ingress_limit(route):
            body = route.request.post_data_buffer or b''
            if route.request.method == 'PUT':
                attempts.append((route.request.url.rsplit('/', 1)[-1], len(body)))
            if len(body) > 1048576:
                route.fulfill(status=413, content_type='text/plain', body='test ingress limit')
            else:
                route.continue_()
        page.route('**/api/house/editor/imports/uploads/*/*', ingress_limit)
        H.open_editor(page, served); H.choose_floor(page, 'pool-house:L1'); H.look_down(page, 'pool-house', 8, 8, height=35)
        page.evaluate("""() => { window.__uploadProgress=[]; new MutationObserver(() => {
            window.__uploadProgress.push(document.getElementById('library-status').textContent);
        }).observe(document.getElementById('library-status'),{childList:true}); }""")
        page.set_input_files('#library-import-files', {'name': 'heavy-car.zip', 'mimeType': 'application/zip', 'buffer': packed.getvalue()})
        dialog = page.locator('.object-import'); dialog.wait_for(state='visible', timeout=90000)
        H.check('Heavy model: 300k triangles' in dialog.inner_text(), dialog.inner_text())
        H.check('wall panel shows a simple stand-in' in dialog.inner_text(), dialog.inner_text())
        dialog.locator('input').fill('Chunked car'); dialog.locator('select').select_option('car')
        dialog.get_by_role('button', name='Add to library').click()
        from services import twin_imports
        page.locator('#library-status').filter(has_text='Model added').wait_for(timeout=30000)
        entry = next(e for e in twin_imports.catalog() if e['name'] == 'Chunked car')
        H.check(entry['triangles'] == triangles and entry['kind'] == 'car', entry)
        H.check(attempts[:3] == [('0', 4194304), ('0', 2097152), ('0', 1048576)], attempts)
        H.check(page.evaluate("window.__uploadProgress.some(text => text.startsWith('Uploading 1 of '))"), 'No byte progress')
        thumb = page.locator(f'#library-panel [data-item="{entry["id"]}"]').first
        thumb.wait_for(state='visible', timeout=10000); thumb.scroll_into_view_if_needed(); start = thumb.bounding_box()
        end = H.screen_of_world(page, 8, 8, 0, 'pool-house'); H._on_canvas(page, *end)
        x, y = start['x'] + start['width'] / 2, start['y'] + start['height'] / 2
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 6, y + 6, steps=2)
        page.mouse.move(*end, steps=16); page.mouse.up(); H.settle(page)
        page.wait_for_function('(asset) => window.__twin.plan.buildings.some(b => b.items.some(i => i.asset === asset))', arg=entry['id'])


def scenario_assign_window_model_and_fit_persists():
    served = H.serve()
    with served.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, served)
        asset = import_model(page, 'Imported window', 'window')
        if page.locator('#library-panel').is_visible():
            page.click('#rail-library')
        b = H.building(H.flat(), 'pool-house'); opening = next(o for o in b['openings'] if o['kind'] == 'window' and o.get('wall'))
        H.choose_floor(page, 'pool-house:L1')
        page.evaluate('([id,bid]) => window.__editor.clickPiece(id,bid)', [opening['id'], b['id']])
        page.locator('.object-model-grid').get_by_role('button', name='Imported window').click()
        page.wait_for_function('([id,asset]) => window.__twin.plan.buildings.some(b => b.openings.some(o => o.id === id && o.model === asset))', arg=[opening['id'], asset])
        fitted = next(o for o in H.building(H.model(), b['id'])['openings'] if o['id'] == opening['id'])
        H.check(all(fitted[k] == opening[k] for k in ('width', 'head', 'sill')), fitted)
        # CPU fitting tests prove dimensions/depth; this scenario also demands pixels.
        page.screenshot(path=str(Path(__file__).parent / 'objects-window-live.png'))
        page.reload(); page.wait_for_function('window.__editor?.ready === true', timeout=90000)
        H.check(next(o for o in H.building(H.model(), b['id'])['openings'] if o['id'] == opening['id'])['model'] == asset, 'Model did not persist')


if __name__ == '__main__':
    # The scenarios share one served house: the heavy car lands where the chair scenario
    # clicks, so it runs last.
    scenario_import_place_scale_rotate_undo_reload_and_programs()
    scenario_assign_window_model_and_fit_persists()
    scenario_six_mb_chunk_zip_survives_one_mb_ingress_and_places_heavy_car()
