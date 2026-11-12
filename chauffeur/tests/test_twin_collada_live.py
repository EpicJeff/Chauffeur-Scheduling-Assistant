"""WRITTEN ONLY: Collada and KMZ chunked imports, textured preview and placement.

Run from chauffeur/: python tests/test_twin_collada_live.py
No Chromium was launched by Codex for this task.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
from collada_fixture import dae, packed, PNG


def scenario_textured_collada_and_kmz_chunk_import_and_place():
    served = H.serve()
    with served.browser(launch_args=H.GPU_ARGS) as page:
        errors, chunks, confirms = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
        def observe(request):
            if '/imports/uploads/' in request.url and request.method == 'PUT':
                chunks.append(request.url)
            if '/editor/imports/import-' in request.url and request.method == 'PATCH':
                confirms.append(request.post_data_json)
        page.on('request', observe)
        H.open_editor(page, served)
        H.choose_floor(page, 'pool-house:L1')
        H.look_down(page, 'pool-house', 8, 8, height=35)
        if page.locator('#library-panel').is_hidden():
            page.click('#rail-library')
        files = {'models/scene.dae': dae('../textures/texture.png'), 'textures/texture.png': PNG}
        kmz = packed({**files, 'doc.kml': b'<kml><Placemark><Model><Link><href>models/scene.dae</href></Link></Model></Placemark></kml>'})
        # Loose picker files share a directory; KMZ exercises nested relative paths.
        loose = [{'name': 'scene.dae', 'mimeType': 'model/vnd.collada+xml', 'buffer': dae('texture.png')},
                 {'name': 'texture.png', 'mimeType': 'image/png', 'buffer': PNG}]
        for name, upload in [('Textured Collada', loose), ('Textured KMZ', {'name': 'scene.kmz', 'mimeType': 'application/vnd.google-earth.kmz', 'buffer': kmz})]:
            page.set_input_files('#library-import-files', upload)
            dialog = page.locator('.object-import')
            dialog.wait_for(state='visible', timeout=60000)
            H.check(dialog.locator('img').evaluate('(img) => img.complete && img.naturalWidth > 0'), 'Missing model thumbnail')
            dialog.locator('input').fill(name)
            dialog.locator('select').select_option('furniture')
            dialog.get_by_role('button', name='Add to library').click()
            page.locator('#library-status').filter(has_text='Model added').wait_for(timeout=30000)
        from services import twin_imports
        entries = [e for e in twin_imports.catalog() if e['name'] in ('Textured Collada', 'Textured KMZ')]
        H.check(len(entries) == 2 and all(e['triangles'] == 1 for e in entries), entries)
        H.check(len(chunks) >= 2 and len(confirms) == 2 and all(c['triangles'] == 1 for c in confirms), (chunks, confirms))
        asset = next(e['id'] for e in entries if e['name'] == 'Textured KMZ')
        thumb = page.locator(f'#library-panel [data-item="{asset}"]').first
        thumb.scroll_into_view_if_needed()
        start = thumb.bounding_box()
        end = H.screen_of_world(page, 8, 8, 0, 'pool-house')
        H._on_canvas(page, *end)
        x, y = start['x'] + start['width'] / 2, start['y'] + start['height'] / 2
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 6, y + 6, steps=2)
        page.mouse.move(*end, steps=16); page.mouse.up(); H.settle(page)
        page.wait_for_function('(asset) => window.__twin.plan.buildings.some(b => b.items.some(i => i.asset === asset))', arg=asset)
        H.check(not errors, errors)


if __name__ == '__main__':
    scenario_textured_collada_and_kmz_chunk_import_and_place()
