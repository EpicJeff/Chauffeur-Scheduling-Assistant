"""Task 8 Chromium scenarios on the household fixture, real imports and editor bake.

Run from chauffeur/: python tests/test_house_twin_model_light_live.py [scenario ...]
Pixel ratios are measured in linear scene output (tone mapping disabled only for
the measurement), so half the lamp term means half the irradiance, not half sRGB.
"""
import copy
import json
import os
from pathlib import Path
import struct
import sys

import test_house_twin_bake_live as B

L, H, RL, check = B.L, B.H, B.RL, B.check

WALL_SAMPLE_LOCAL = (0.25, 15.8, 4.75)


def shot(page, name):
    out = os.environ.get('MODEL_LIGHT_SHOTS_DIR')
    if not out:
        return
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    # Move pointer off mode buttons so tooltips don't obscure the room.
    page.mouse.move(10, 10)
    H.settle(page, 2)
    page.screenshot(path=str(folder / name))


def fixture(far_lamp=False):
    s = L.serve()
    if s is None:
        raise RuntimeError('Chromium scenarios require Playwright')
    L.reset()
    B.clear_bakes()
    L.FAKE.devices[:] = [d for d in L.FAKE.devices if d['id'] != 'grid-far-lamp']
    L.FAKE.areas[:] = [a for a in L.FAKE.areas if a['area_id'] != 'grid-far']
    if far_lamp:
        L.FAKE.areas.append({'area_id': 'grid-far', 'name': 'Grid far room', 'floor_id': 'ground'})
        L.FAKE.devices.append({'id': 'grid-far-lamp', 'name': 'Far lamp', 'area_id': 'grid-far',
                              'entities': [('light.grid_far', 'off', {'brightness': 255})]})
        L.FAKE.states['light.grid_far'] = {'entity_id': 'light.grid_far', 'state': 'off',
                                          'attributes': {'friendly_name': 'Far lamp', 'brightness': 255}}
    from services import twin_imports, twin_store
    # A small opaque cube, loaded through the real import/model/merge path.
    vertices = [(-.3048, 0, -.3048), (.3048, 0, -.3048), (.3048, .6096, -.3048), (-.3048, .6096, -.3048),
                (-.3048, 0, .3048), (.3048, 0, .3048), (.3048, .6096, .3048), (-.3048, .6096, .3048)]
    triangles = [0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
                 3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5]
    pos = struct.pack('<24f', *(v for p in vertices for v in p))
    idx = struct.pack('<36H', *triangles)
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [.7, .7, .7, 1], 'metallicFactor': 0, 'roughnessFactor': .8}}],
           'buffers': [{'uri': 'mesh.bin', 'byteLength': len(pos) + len(idx)}],
           'bufferViews': [{'buffer': 0, 'byteLength': len(pos)}, {'buffer': 0, 'byteOffset': len(pos), 'byteLength': len(idx)}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 8, 'type': 'VEC3',
                          'min': [-.3048, 0, -.3048], 'max': [.3048, .6096, .3048]},
                         {'bufferView': 1, 'componentType': 5123, 'count': 36, 'type': 'SCALAR'}]}
    imported = twin_imports.create({'model.gltf': json.dumps(doc).encode(), 'mesh.bin': pos + idx}, 'Grid test cube', 'furniture')

    def place(before):
        model = copy.deepcopy(before)
        building = H.building(model, L.POOL)
        building.setdefault('items', []).extend([
            {'id': 'grid-near', 'asset': imported['id'], 'host': {'floor': L.KITCHEN, 'u': .3, 'v': 5.2 / 17.33}, 'scale': 1},
            {'id': 'grid-next', 'asset': imported['id'], 'host': {'floor': L.CHANGING, 'u': .5, 'v': .5}, 'scale': 1}])
        if far_lamp:
            import math
            main = H.building(model, 'main-house')
            a = math.radians(main.get('rotation', 0))
            # Northernmost main-house room is well outside the pool-house
            # item's reach; assert the actual runtime range again in the test.
            def north(room):
                x = sum(p[0] for p in room['polygon']) / len(room['polygon'])
                y = sum(p[1] for p in room['polygon']) / len(room['polygon'])
                return main.get('position', [0, 0])[1] + x * math.sin(a) + y * math.cos(a)
            room = min((r for r in main['rooms'] if r.get('polygon')), key=north)
            room['name'], room['ha_area'] = 'Grid far room', 'grid-far'
            main.setdefault('devices', []).append({'id': 'anchor:grid-far', 'device': 'grid-far-lamp',
                                                  'host': {'floor': room['id'], 'u': .5, 'v': .5},
                                                  'offset': 0, 'src': {'person': True}})
        return model
    twin_store.update_model(place, 'edit', note='model grid lighting fixture')
    return s


def frame_samples(page):
    """Focus pool-house L1 and fit the perspective camera to both models and the Kitchen wall sample."""
    wall_lot = L.lot_of_local(page, WALL_SAMPLE_LOCAL[0], WALL_SAMPLE_LOCAL[1]) + [WALL_SAMPLE_LOCAL[2]]
    page.evaluate("""async wallLot => {
      const THREE = await import('three'), v = window.__twin;
      v.levels.go({building: 'pool-house', floor: 'L1'}, {immediate: true});
      v.scene.updateMatrixWorld(true);
      const boxes = [];
      v.scene.traverse(o => {
        if (!o.isMesh || !o.geometry?.userData?.bakeExcluded) return;
        const pos = o.geometry.attributes.position, pt = new THREE.Vector3();
        const ranges = o.userData.snapRanges || [{start: 0, count: pos.count, pieceId: o.userData.pieceId}];
        for (const r of ranges) {
          if (r.pieceId !== 'grid-near' && r.pieceId !== 'grid-next') continue;
          const b = new THREE.Box3();
          const end = Math.min(pos.count, r.start + r.count);
          for (let i = r.start; i < end; i++) b.expandByPoint(pt.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld));
          if (!b.isEmpty()) boxes.push(b);
        }
      });
      if (boxes.length < 2) throw new Error('Expected grid-near and grid-next bounds in scene');
      const wallW = new THREE.Vector3(wallLot[0] * .3048, wallLot[2] * .3048, -wallLot[1] * .3048);
      boxes.push(new THREE.Box3().setFromCenterAndSize(wallW, new THREE.Vector3(1.2, 1.2, 1.2)));
      const fit = new THREE.Box3();
      for (const b of boxes) fit.union(b);
      const center = fit.getCenter(new THREE.Vector3());
      const pool = v.plan.buildings.find(b => b.id === 'pool-house');
      const a = (pool.rotation || 0) * Math.PI / 180;
      // Angled overhead direction in pool-house local space (+x east, +y south, +z up)
      // kept steep enough that all three rays clear the 10 ft walls of Kitchen and Changing.
      const lx = 0.22, ly = 0.15, lz = 0.964;
      const wx = Math.cos(a) * lx - Math.sin(a) * ly;
      const wy = Math.sin(a) * lx + Math.cos(a) * ly;
      const dir = new THREE.Vector3(wx, lz, -wy).normalize();
      const cam = v.camera;
      const inv = new THREE.Quaternion().setFromRotationMatrix(
        new THREE.Matrix4().lookAt(dir, new THREE.Vector3(), cam.up)).invert();
      const tanY = Math.tan(cam.fov * Math.PI / 360) / (cam.zoom || 1);
      const tanX = tanY * (cam.aspect || 1);
      const pad = 1.35;
      const corners = [];
      for (const b of boxes) {
        for (const x of [b.min.x, b.max.x])
          for (const y of [b.min.y, b.max.y])
            for (const z of [b.min.z, b.max.z]) corners.push(new THREE.Vector3(x, y, z));
      }
      let dist = 4;
      for (const p of corners) {
        const q = p.clone().sub(center).applyQuaternion(inv);
        dist = Math.max(dist, q.z + Math.max(cam.near * 2, Math.abs(q.x) * pad / tanX, Math.abs(q.y) * pad / tanY));
      }
      // levels.go locks controls to top-down; relax limits so the angled fit holds.
      v.controls.minPolarAngle = 0;
      v.controls.maxPolarAngle = Math.PI / 2;
      v.controls.minDistance = 0;
      v.controls.maxDistance = 1e6;
      const eye = center.clone().addScaledVector(dir, dist);
      v.setCameraState({position: eye.toArray(), target: center.toArray()});
    }""", wall_lot)
    H.settle(page, 3)


def prepare(page, s):
    B.desk_baked(s, page)
    page.evaluate("() => { const v=window.__twin; v.levels.go({building:'pool-house',floor:'L1'},{immediate:true}); v.setTime('night'); v.setNightBrightness(0,{persist:false}); }")
    RL.lights_mode(page)
    page.wait_for_function("() => window.__twin.bake.models?.stats().bricks >= 2", timeout=90000)
    frame_samples(page)
    print('model-light budget:', page.evaluate('() => window.__twin.bake.models.stats()'))


def samples_rgb(page):
    """Read linear float RGB and luminance for [grid-near top, grid-next top, Kitchen west wall]."""
    # Float output avoids saturation/byte quantisation corrupting the 50% ratio.
    local = [(9.3, 5.2, 2.0), (27.7, 17.1, 2.0), WALL_SAMPLE_LOCAL]
    points = [L.lot_of_local(page, x, y) + [z] for x, y, z in local]
    rows = page.evaluate("""async points => {
      const THREE=await import('three'),v=window.__twin,r=v.renderer3,c=r.domElement;
      v.scene.updateMatrixWorld(true);v.camera.updateMatrixWorld(true);
      const shown=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;};
      const meshes=[];v.scene.traverse(o=>{if(o.isMesh&&shown(o)&&!o.layers.isEnabled(31))meshes.push(o);});
      const ray=new THREE.Raycaster();
      const target=new THREE.WebGLRenderTarget(c.width,c.height,{type:THREE.FloatType});
      const previous=r.getRenderTarget(),tone=r.toneMapping,hidden=[];
      v.scene.traverse(o=>{if(o.isSprite&&o.visible){hidden.push(o);o.visible=false;}});
      try {
        r.toneMapping=THREE.NoToneMapping;r.setRenderTarget(target);r.render(v.scene,v.camera);
        return points.map((at,idx)=>{
          const w=new THREE.Vector3(at[0]*.3048,at[2]*.3048,-at[1]*.3048);
          const p=w.clone().project(v.camera);
          if(Math.abs(p.x)>.95||Math.abs(p.y)>.95||p.z>1)
            throw new Error('Model/wall sample '+idx+' is outside camera: '+JSON.stringify([p.x,p.y,p.z]));
          ray.setFromCamera(new THREE.Vector2(p.x,p.y),v.camera);
          const hit=ray.intersectObjects(meshes,false)[0];
          let piece=hit?.object.userData?.pieceId||null;
          if(!piece&&hit?.object.userData?.snapRanges&&hit.face){
            const vi=hit.face.a,sr=hit.object.userData.snapRanges.find(q=>vi>=q.start&&vi<q.start+q.count);
            piece=sr?sr.pieceId:null;
          }
          const x=Math.round((p.x+1)*c.width/2),y=Math.round((p.y+1)*c.height/2),pixels=new Float32Array(7*7*4);
          r.readRenderTargetPixels(target,x-3,y-3,7,7,pixels);
          let rr=0,gg=0,bb=0;
          for(let i=0;i<49;i++){rr+=pixels[i*4];gg+=pixels[i*4+1];bb+=pixels[i*4+2];}
          rr/=49;gg/=49;bb/=49;
          return {rgb:[rr,gg,bb],lum:.2126*rr+.7152*gg+.0722*bb,piece,mat:hit?.object.material?.name||null,
                  ndc:[p.x,p.y,p.z],dist:hit?hit.point.distanceTo(w):null};
        });
      } finally {r.setRenderTarget(previous);r.toneMapping=tone;target.dispose();for(const o of hidden)o.visible=true;}
    }""", points)
    check(rows[0]['piece'] == 'grid-near', ('sample 0 hits grid-near', rows[0]))
    check(rows[1]['piece'] == 'grid-next', ('sample 1 hits grid-next', rows[1]))
    check(rows[2]['mat'] == 'interior_wall' and (rows[2]['dist'] is not None and rows[2]['dist'] < 0.05),
          ('sample 2 hits interior Kitchen wall', rows[2]))
    return rows


def samples(page):
    return [row['lum'] for row in samples_rgb(page)]


def scenario_model_lit_by_room_lamp():
    s = fixture()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        prepare(page, s)
        B.only_on(page, None)
        off = samples(page)
        shot(page, 'scenario_model_lit_by_room_lamp_off.png')
        B.only_on(page, 'light.ceiling_light', brightness=255, rgb_color=[255, 255, 255])
        on = samples(page)
        shot(page, 'scenario_model_lit_by_room_lamp.png')
        print(f'lit_by_room_lamp: off={off[0]:.5f} on={on[0]:.5f} ratio={on[0]/max(off[0],1e-6):.2f}x')
        check('dev-k-ceiling' in B.fresh(page), 'ceiling lamp is fresh')
        check(on[0] >= 3 * off[0], ('model luminance rises >=3x', off, on))
        L.no_errors(s)


def scenario_model_next_room_stays_dark():
    s = fixture()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        prepare(page, s)
        B.only_on(page, None)
        off = samples(page)
        B.only_on(page, 'light.ceiling_light', brightness=255)
        on = samples(page)
        shot(page, 'scenario_model_next_room_stays_dark.png')
        rel = abs(on[1] - off[1]) / max(off[1], 1e-6)
        print(f'next_room_stays_dark: near_off={off[0]:.5f} near_on={on[0]:.5f} next_off={off[1]:.5f} next_on={on[1]:.5f} rel={rel:.4%}')
        check(on[0] >= 3 * off[0], ('kitchen model is lit by the toggled lamp', off, on))
        check(rel < .1, ('next room changes <10%', off, on))
        L.no_errors(s)


def scenario_tint_follows_lamp():
    s = fixture()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        prepare(page, s)
        B.only_on(page, None)
        off_rows = samples_rgb(page)
        B.only_on(page, 'light.ceiling_light', brightness=255, rgb_color=[255, 255, 255])
        full_rows = samples_rgb(page)
        B.only_on(page, 'light.ceiling_light', brightness=128, rgb_color=[255, 255, 255])
        half_rows = samples_rgb(page)
        off = [r['lum'] for r in off_rows]
        full = [r['lum'] for r in full_rows]
        half = [r['lum'] for r in half_rows]
        ratios = [(half[i] - off[i]) / max(full[i] - off[i], 1e-6) for i in (0, 2)]
        B.only_on(page, 'light.ceiling_light', brightness=255, rgb_color=[255, 0, 0])
        red_rows = samples_rgb(page)
        shot(page, 'scenario_tint_follows_lamp_red.png')
        B.only_on(page, 'light.ceiling_light', brightness=255, rgb_color=[0, 0, 255])
        blue_rows = samples_rgb(page)
        shot(page, 'scenario_tint_follows_lamp.png')

        def delta_rgb(rows, idx):
            return [rows[idx]['rgb'][c] - off_rows[idx]['rgb'][c] for c in range(3)]

        m_red, w_red = delta_rgb(red_rows, 0), delta_rgb(red_rows, 2)
        m_blue, w_blue = delta_rgb(blue_rows, 0), delta_rgb(blue_rows, 2)
        print('tint_follows_lamp:',
              f'model_off={off[0]:.5f} model_full={full[0]:.5f} model_half={half[0]:.5f}',
              f'wall_off={off[2]:.5f} wall_full={full[2]:.5f} wall_half={half[2]:.5f}',
              f'ratios={[round(r, 4) for r in ratios]}',
              f'model_off_rgb={[round(c, 4) for c in off_rows[0]["rgb"]]}',
              f'model_red_rgb={[round(c, 4) for c in red_rows[0]["rgb"]]}',
              f'model_blue_rgb={[round(c, 4) for c in blue_rows[0]["rgb"]]}',
              f'model_red_delta={[round(c, 4) for c in m_red]}',
              f'model_blue_delta={[round(c, 4) for c in m_blue]}',
              f'wall_red_delta={[round(c, 4) for c in w_red]}',
              f'wall_blue_delta={[round(c, 4) for c in w_blue]}')
        check(all(abs(r - .5) <= .05 for r in ratios), ('model and wall lamp terms halve within 10%', ratios, off, full, half))
        check(abs(ratios[0] - ratios[1]) <= .05, ('model and wall follow same ratio', ratios))
        check(m_red[0] > 0.5 and m_red[0] > 10 * max(abs(m_red[1]), abs(m_red[2]), 1e-4),
              ('model tint turns red with red lamp', m_red))
        check(m_blue[2] > 0.5 and m_blue[2] > 10 * max(abs(m_blue[0]), abs(m_blue[1]), 1e-4),
              ('model tint turns blue with blue lamp', m_blue))
        check(w_red[0] > 0.05 and w_red[0] > 10 * max(abs(w_red[1]), abs(w_red[2]), 1e-4),
              ('wall tint turns red with red lamp', w_red))
        check(w_blue[2] > 0.05 and w_blue[2] > 10 * max(abs(w_blue[0]), abs(w_blue[1]), 1e-4),
              ('wall tint turns blue with blue lamp', w_blue))
        L.no_errors(s)


def _wait_programs_settled(page, stable_seconds=3, max_seconds=45):
    """Wait until reflection probes are idle and the shader program key set is stable."""
    last_keys = None
    stable = 0
    snap = None
    for _ in range(max_seconds):
        snap = page.evaluate("""() => {
          const v = window.__twin;
          const refl = v.reflectionInfo ? v.reflectionInfo() : {pending: false, probes: []};
          const programs = (v.renderer3.info.programs || []).map(p => ({
            id: p.id, name: p.name, key: p.cacheKey, used: p.usedTimes,
          }));
          return {pending: !!refl.pending, probes: refl.probes.map(p => [p.id, p.fresh, p.captures]), programs};
        }""")
        keys = frozenset(p['key'] for p in snap['programs'])
        if not snap['pending'] and keys == last_keys:
            stable += 1
            if stable >= stable_seconds:
                return snap, True
        else:
            stable = 0
            last_keys = keys
        page.wait_for_timeout(1000)
    return snap, False


def scenario_no_bake_no_new_programs():
    s = fixture()
    snapshots = []
    # Same view with the new controller replaced by a no-op is the main-path
    # reference. No grid means the real module must compile exactly that set.
    for reference in (True, False):
        with s.browser(launch_args=L.GPU_ARGS) as page:
            if reference:
                page.route('**/bake/model_lighting.js', lambda route: route.fulfill(content_type='text/javascript', body=
                    'export function mountModelLighting(){return {update:async()=>{},setTint(){},rebuild(){},stop(){}}}'))
            B.open_desk(page, s)
            # Let initial exterior reflection probes settle before switching views so
            # both pages compile the exact same exterior probe variants.
            _, ext_ok = _wait_programs_settled(page, stable_seconds=2)
            check(ext_ok, ('exterior programs settle before camera aim', reference))
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            RL.calm(page)
            snap, settled = _wait_programs_settled(page, stable_seconds=3)
            check(settled, ('program set settles for >=2s before comparison', reference, len(snap['programs'])))
            snapshots.append(snap)
    ref_map = {p['key']: p for p in snapshots[0]['programs']}
    real_map = {p['key']: p for p in snapshots[1]['programs']}
    only_ref = sorted(set(ref_map) - set(real_map))
    only_real = sorted(set(real_map) - set(ref_map))
    print(f'no_bake_programs: ref={len(snapshots[0]["programs"])} real={len(snapshots[1]["programs"])} '
          f'ref_unique={len(ref_map)} real_unique={len(real_map)} '
          f'only_ref={len(only_ref)} only_real={len(only_real)}')
    for k in only_ref:
        print('  only_in_ref:', ref_map[k]['name'], k)
    for k in only_real:
        print('  only_in_real:', real_map[k]['name'], k)
    check(not only_real and not only_ref and len(snapshots[0]['programs']) == len(snapshots[1]['programs']),
          ('no grid adds no programs against reference',
           [len(snapshots[0]['programs']), len(snapshots[1]['programs'])],
           [(ref_map[k]['name'], k[:160]) for k in only_ref],
           [(real_map[k]['name'], k[:160]) for k in only_real]))


def scenario_moved_item_keeps_other_lamps_fresh():
    s = fixture(far_lamp=True)
    from services import twin_store
    with s.browser(launch_args=L.GPU_ARGS) as page:
        prepare(page, s)
        before = B.fresh(page)
        # Derive out-of-range lamps using the same public reach/key contract.
        far = page.evaluate("""async () => {
          const v=window.__twin, base=window.chfBase;
          const {bakeLights}=await import(base+'static/twin/bake/runtime.js');
          const {lightSource}=await import(base+'static/twin/bake/reach.js');
          const p=v.plan.buildings.find(b=>b.id==='pool-house'),a=(p.rotation||0)*Math.PI/180;
          const point=[((p.position?.[0]||0)+9.3*Math.cos(a)-5.2*Math.sin(a))*.3048,
            (p.base||0)*.3048,-((p.position?.[1]||0)+9.3*Math.sin(a)+5.2*Math.cos(a))*.3048];
          return bakeLights(v.live.layout(),v.scene,v.plan).filter(l=>{
            const {source,range}=lightSource(v.plan,l);return Math.hypot(source.x-point[0],source.y-point[1],source.z-point[2])>range+5.3048;
          }).map(l=>l.device);
        }""")
        far = set(far) & before
        check(far, 'fixture must have at least one fresh lamp outside model reach')

        def move(before_model):
            model = copy.deepcopy(before_model)
            item = next(i for i in H.building(model, L.POOL)['items'] if i['id'] == 'grid-near')
            item['host']['u'] += .5 / 31
            return model
        twin_store.update_model(move, 'edit', note='move and save grid model')
        B.reopen(page)
        B.wait_until(page, lambda: far <= B.fresh(page), 90, ('out of range lamps remain fresh', far))
        L.no_errors(s)


SCENARIOS = [scenario_model_lit_by_room_lamp, scenario_model_next_room_stays_dark,
             scenario_tint_follows_lamp, scenario_no_bake_no_new_programs,
             scenario_moved_item_keeps_other_lamps_fresh]

if __name__ == '__main__':
    wanted = sys.argv[1:]
    L.run([fn for fn in SCENARIOS if not wanted or fn.__name__ in wanted])
