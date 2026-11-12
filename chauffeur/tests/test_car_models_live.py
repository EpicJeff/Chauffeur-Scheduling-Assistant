"""Browser acceptance for imported household car models and derived LODs.

WRITTEN ONLY: Codex must not launch Chromium. Claude may run from chauffeur/:
    env -u HA_BASE_URL timeout 300 python tests/test_car_models_live.py

Uses the existing isolated household/HA harness and an in-memory 319,200
triangle ellipsoid GLB with UVs and normals. No user's model or data is read.
"""
from array import array
import copy
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
import house_twin_live_harness as L

CAR = 'lod-family-ev'
NAME = 'Family model EV'
MODEL_NAME = 'Dense car acceptance'
SPOT_AT = [12, -24]


def heavy_car_glb(segments=400, rings=400):
    """Closed, curved geometry gives the real simplifier meaningful work."""
    positions, normals, uvs, indices = array('f'), array('f'), array('f'), array('I')
    for row in range(rings + 1):
        v = row / rings
        phi = v * math.pi
        for column in range(segments + 1):
            u = column / segments
            theta = u * math.tau
            x, y, z = -math.cos(theta) * math.sin(phi), math.cos(phi), math.sin(theta) * math.sin(phi)
            positions.extend((x, .8 + y * .8, z * 2.6))
            n = (x, y / .8, z / 2.6)
            length = math.sqrt(sum(value * value for value in n))
            normals.extend(value / length for value in n)
            uvs.extend((u, 1 - v))
    for row in range(rings):
        for column in range(segments):
            a = row * (segments + 1) + column + 1
            b, c, d = a - 1, a + segments, a + segments + 1
            if row:
                indices.extend((a, b, d))
            if row != rings - 1:
                indices.extend((b, c, d))
    if sys.byteorder != 'little':
        for values in (positions, normals, uvs, indices):
            values.byteswap()
    binary, views = bytearray(), []
    for values in (positions, normals, uvs, indices):
        raw = values.tobytes()
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw)})
        binary.extend(raw)
    vertices = (rings + 1) * (segments + 1)
    doc = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [.15, .4, .75, 1], 'metallicFactor': .2, 'roughnessFactor': .4}}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2}, 'indices': 3, 'material': 0}]}],
        'buffers': [{'byteLength': len(binary)}], 'bufferViews': views,
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': vertices, 'type': 'VEC3', 'min': [-1, 0, -2.6], 'max': [1, 1.6, 2.6]},
            {'bufferView': 1, 'componentType': 5126, 'count': vertices, 'type': 'VEC3'},
            {'bufferView': 2, 'componentType': 5126, 'count': vertices, 'type': 'VEC2'},
            {'bufferView': 3, 'componentType': 5125, 'count': len(indices), 'type': 'SCALAR'},
        ],
    }
    text = json.dumps(doc).encode()
    text += b' ' * (-len(text) % 4)
    total = 28 + len(text) + len(binary)
    return b'glTF' + struct.pack('<II', 2, total) + struct.pack('<II', len(text), 0x4E4F534A) + text + struct.pack('<II', len(binary), 0x004E4942) + binary


def setup():
    served = L.serve()
    if served is None:
        raise RuntimeError('These acceptance scenarios require Playwright and Chromium.')
    L.reset()
    from services import storage, twin_store, twin_model_ops
    storage.add_driver({'id': H.PARENT['id'], 'name': H.PARENT['name'], 'color_code': '#2244cc',
                        'group': 'primary', 'calendar_ids': [], 'hashtags': []})
    storage.add_car({'id': CAR, 'name': NAME, 'allowed_driver_ids': [H.PARENT['id']],
                     'ha_battery_entity': 'sensor.lod_family_battery', 'ha_device_tracker': 'device_tracker.lod_family'})
    for eid, state in [('sensor.lod_family_battery', '78'), ('device_tracker.lod_family', 'home')]:
        L.FAKE.states[eid] = {'entity_id': eid, 'state': state, 'attributes': {'unit_of_measurement': '%'} if eid.startswith('sensor.') else {}}
    def park(model):
        return twin_model_ops.apply(copy.deepcopy(model), {
            'op': 'add_equipment', 'building': L.POOL, 'kind': 'parking', 'car': CAR,
            'rotation': 30, 'width': 9, 'depth': 18, 'host': {'ground': True, 'at': SPOT_AT},
        })[0]
    twin_store.update_model(park, 'edit', note='Car model browser parking fixture')
    return served


def import_and_judge_versions(page, served):
    H.open_editor(page, served, query='tier=high&test=1&library=1')
    page.locator('#library-panel').wait_for(state='visible')
    binary = heavy_car_glb()
    page.set_input_files('#library-import-files', {'name': 'dense-car.glb', 'mimeType': 'model/gltf-binary', 'buffer': binary})
    dialog = page.get_by_role('dialog', name='Import model', exact=True)
    dialog.wait_for(state='visible', timeout=60000)
    # Naming and kind selection remain live while optional LOD work progresses.
    dialog.locator('input').fill(MODEL_NAME)
    dialog.locator('select').select_option('car')
    page.wait_for_function("() => document.querySelectorAll('.object-import figure').length===3", timeout=90000)
    previews = dialog.locator('figure')
    H.check(previews.count() == 3, 'Original, LOD1 and LOD2 are shown together')
    counts = page.evaluate("""() => [...document.querySelectorAll('.object-import figcaption')].map(node => {
        const [name,count]=node.textContent.split(':');return {name,triangles:Number(count.replace(/[^0-9]/g,''))};
    })""")
    H.check([row['name'] for row in counts] == ['Original', 'LOD1', 'LOD2'], counts)
    original = counts[0]['triangles']
    H.check(original == 319200, counts)
    H.check(.20 <= counts[1]['triangles'] / original <= .35 and .02 <= counts[2]['triangles'] / original <= .12, counts)
    page.wait_for_function("() => [...document.querySelectorAll('.object-import figure img')].every(image=>image.complete && image.naturalWidth>0)")
    H.check(dialog.locator('input').input_value() == MODEL_NAME, 'Generation overwrote the name')
    H.check(dialog.locator('select').input_value() == 'car', 'Generation overwrote the kind')
    dialog.get_by_role('button', name='Add to library', exact=True).click()
    page.wait_for_function("() => document.querySelector('#library-status').textContent.startsWith('Model added')")
    from services import twin_imports
    entry = next(entry for entry in twin_imports.catalog() if entry['name'] == MODEL_NAME)
    H.check({lod['name'] for lod in entry['lods']} == {'lod1.glb', 'lod2.glb'}, entry)
    H.check(all(0 < lod['bytes'] < len(binary) for lod in entry['lods']), entry)
    return entry


def assign_in_drive_setup(page, served, entry):
    page.goto(served.url('dashboard_v2'), wait_until='networkidle')
    page.click('#page-settings-gear')
    page.wait_for_selector('[data-settings-for~="drives"][data-open]')
    cars = page.locator('#cars')
    cars.scroll_into_view_if_needed()
    cars.get_by_role('button', name='Edit', exact=True).click()
    picker = cars.get_by_role('group', name='3D model in the house')
    choice = picker.get_by_role('button', name=MODEL_NAME, exact=True)
    choice.wait_for(state='visible')
    H.check(choice.locator('img').count() == 1, 'The car picker includes the import thumbnail')
    H.check(cars.get_by_role('link', name='Import a model').get_attribute('href').endswith('house/editor?library=1'), 'Import link opens the existing editor library')
    choice.click()
    H.check(choice.get_attribute('aria-pressed') == 'true', 'Model is selected')
    cars.get_by_role('button', name='Save Car', exact=True).click()
    page.wait_for_function("() => !Alpine.$data(document.querySelector('[x-data^=driveSetup]')).showCarForm")
    from services import storage
    H.check(next(car for car in storage.get_all_cars() if car['id'] == CAR)['twin_model'] == entry['id'], 'Drive save did not persist the chosen import')
    cars.get_by_role('button', name='Edit', exact=True).click()
    H.check(picker.get_by_role('button', name=MODEL_NAME, exact=True).get_attribute('aria-pressed') == 'true', 'Reopening the editor lost the choice')


def open_parked_car(page, served, tier):
    # Keep the parent's existing session for both the manual editor and viewer.
    page.goto(served.url(f'house/twin?tier={tier}&test=1'), wait_until='domcontentloaded')
    page.wait_for_function('() => window.__twin?.ready && window.__twin.live', timeout=90000)
    page.wait_for_function('(id) => window.__twin.cars?.snapshot().some(row=>row.id===id && row.visible && row.modelVisible)', arg=CAR, timeout=60000)
    H.look_at(page, L.POOL, [SPOT_AT[0], SPOT_AT[1] - 32, 24], [*SPOT_AT, 3])
    label = page.locator(f'[data-car-label="{CAR}"]')
    H.check(label.is_visible() and NAME in label.inner_text() and '78%' in label.inner_text(), 'Parked car retains its name and battery label')
    page.locator(f'[data-car-icon="{CAR}"]').click()
    card = page.locator(f'[data-car-card="{CAR}"]')
    H.check(card.is_visible() and '78%' in card.inner_text(), 'Model icon opens the existing car card')
    card.get_by_role('button', name='Close', exact=True).click()
    # A pointer on the model itself follows the same card path as its icon.
    H.click_world(page, *SPOT_AT, 3, L.POOL)
    H.check(card.is_visible(), 'Tapping the model mesh did not open its car card')
    card.get_by_role('button', name='Close', exact=True).click()
    H.check(page.evaluate("""id=>{let top=-Infinity,icon=null;window.__twin.scene.traverse(o=>{
        if(o.userData.carModel===id && o.isMesh){o.geometry.computeBoundingBox();for(const y of [o.geometry.boundingBox.min.y,o.geometry.boundingBox.max.y]){
          const p=o.position.clone().set(0,y,0).applyMatrix4(o.matrixWorld);top=Math.max(top,p.y);}}
        if(o.isSprite && o.userData.twinCar===id)icon=o;
      });return icon && icon.position.y>top;}""", CAR), 'The status icon hovers above the model')


def switch_lod(page, level):
    return page.evaluate("""([id,level]) => {
      const v=window.__twin;let lod;v.scene.traverse(o=>{if(o.isLOD && o.userData.carModel===id)lod=o;});
      if(!lod)throw new Error('Car has no THREE.LOD');
      const centre=lod.getWorldPosition(v.camera.position.clone());
      const distance=level===0?lod.levels[1].distance*.5:level===1?(lod.levels[1].distance+lod.levels[2].distance)*.5:lod.levels[2].distance*1.5;
      v.controls.target.copy(centre);v.camera.position.copy(centre).add(centre.clone().set(0,distance*.25,distance));v.controls.update();
      v.camera.updateMatrixWorld(true);lod.update(v.camera);v.renderer3.render(v.scene,v.camera);
      return {level:lod.getCurrentLevel(),programs:v.renderer3.info.programs.length};
    }""", [CAR, level])


def scenario_import_assign_render_low_lod_and_second_switch_programs():
    served = setup()
    with served.browser(launch_args=H.GPU_ARGS) as page:
        entry = import_and_judge_versions(page, served)
        assign_in_drive_setup(page, served, entry)
        open_parked_car(page, served, 'high')
        # Warm each real level once, then require a complete second cycle to
        # reuse programs, including the return from the far model to near.
        first = [switch_lod(page, level) for level in (0, 1, 2)]
        H.check([row['level'] for row in first] == [0, 1, 2], first)
        programs = first[-1]['programs']
        second = [switch_lod(page, level) for level in (0, 1, 2, 0)]
        H.check([row['level'] for row in second] == [0, 1, 2, 0], second)
        H.check(all(row['programs'] == programs for row in second), ('Second LOD cycle compiled programs', first, second))
        downloaded = []
        page.on('request', lambda request: downloaded.append(request.url))
        open_parked_car(page, served, 'low')
        H.check(any(f"/{entry['id']}/lod2.glb" in url for url in downloaded), ('Low tier did not fetch the actual LOD2', downloaded))
        H.check(not any(f"/{entry['id']}/lod1.glb" in url or f"/{entry['id']}/dense-car.glb" in url for url in downloaded), 'Low tier downloaded a heavier car version')
        low_triangles = page.evaluate("""id=>{let count=0;window.__twin.scene.traverse(o=>{
            if(o.isMesh && o.userData.carModel===id)count+=(o.geometry.index?.count || o.geometry.attributes.position.count)/3;
          });return count;}""", CAR)
        H.check(low_triangles == next(lod['triangles'] for lod in entry['lods'] if lod['name'] == 'lod2.glb'), ('Low tier mesh is the real LOD2', low_triangles, entry['lods']))
        from services import ha_events
        tracker = copy.deepcopy(L.FAKE.states['device_tracker.lod_family'])
        tracker['state'] = 'away'
        L.FAKE.states[tracker['entity_id']] = tracker
        ha_events._publish({'entity_id': tracker['entity_id'], 'new_state': tracker})
        page.wait_for_function('(id)=>window.__twin.cars.snapshot().some(row=>row.id===id && !row.visible && !row.modelVisible)', arg=CAR)
        H.check(page.locator(f'[data-car-label="{CAR}"]').is_hidden(), 'Away car label remained visible')
        L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_import_assign_render_low_lod_and_second_switch_programs])
