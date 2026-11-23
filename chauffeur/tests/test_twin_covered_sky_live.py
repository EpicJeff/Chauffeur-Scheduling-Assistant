"""Covered-sky browser check: porch top on the household fixture reads neutral (b/r < 1.25) with sun off.

Run from chauffeur/: python tests/test_twin_covered_sky_live.py
"""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_covered_sky_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_twin_live_harness as L

H, check = L.H, L.check

PROBE_JS = r"""
const THREE = await import('three');
const base = new URL(window.chfBase + 'static/twin/', location.href);
const { groundAt } = await import(new URL('twin_ground.js', base));
const FT = .3048, v = window.__twin;
const b = v.plan.buildings.find(x => x.id === 'main-house');
const toPlan = (x, y) => {
  const a = (b.rotation || 0) * Math.PI / 180;
  return [b.position[0] + x * Math.cos(a) - y * Math.sin(a),
          b.position[1] + x * Math.sin(a) + y * Math.cos(a)];
};
const meshes = () => {
  const list = [];
  v.scene.traverse(o => {
    if (!o.isMesh || o.layers.isEnabled(31)) return;
    for (let p = o; p; p = p.parent) if (!p.visible) return;
    list.push(o);
  });
  return list;
};
const ray = new THREE.Raycaster();
function floorY(x, y) {
  const [X, Y] = toPlan(x, y), g = groundAt(v.plan, X, Y) * FT;
  ray.set(new THREE.Vector3(X * FT, g + 2.4, -Y * FT), new THREE.Vector3(0, -1, 0));
  const hit = ray.intersectObjects(meshes(), false)[0];
  return hit ? hit.point.y : g;
}
let sun = null;
v.scene.traverse(o => { if (o.isDirectionalLight && o.name === 'real-sun') sun = o; });
const W = (x, y, h) => { const [X, Y] = toPlan(x, y); return [X * FT, h, -Y * FT]; };

window.__covSky = {
  aimPorch(sunOff = false) {
    const fy = floorY(25, 11);
    v.cancelCameraMotion?.();
    v.controls.minDistance = 0; v.controls.maxDistance = Infinity;
    v.controls.minPolarAngle = 0; v.controls.maxPolarAngle = Math.PI / 2;
    v.setCameraState({ position: W(25, -4, fy + 2.4), target: W(25, 11, fy) });
    if (sunOff) sun.color.setRGB(0, 0, 0);
    sun.shadow.needsUpdate = true;
    v.render();
    v.camera.updateMatrixWorld();
    const samples = {};
    for (const [name, lx, ly] of [['porch_deep', 18.5, 12.0], ['porch_mid', 25.0, 11.2], ['porch_right', 29.0, 11.0]]) {
      const [X, Y] = toPlan(lx, ly), y = floorY(lx, ly);
      const world = new THREE.Vector3(X * FT, y, -Y * FT);
      const ndc = world.clone().project(v.camera);
      const rect = v.renderer3.domElement.getBoundingClientRect();
      const sx = rect.left + (ndc.x + 1) / 2 * rect.width;
      const sy = rect.top + (1 - ndc.y) / 2 * rect.height;
      ray.setFromCamera(new THREE.Vector2(ndc.x, ndc.y), v.camera);
      const hit = ray.intersectObjects(meshes(), false)[0];
      const n = hit ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : null;
      const wo = hit?.object.geometry.attributes.weatherOpen;
      const open = wo ? (wo.getX(hit.face.a) + wo.getX(hit.face.b) + wo.getX(hit.face.c)) / 3 : null;
      samples[name] = { sx, sy, normalY: n ? +n.y.toFixed(2) : null, open: open !== null ? +open.toFixed(2) : null };
    }
    return samples;
  },
  roofLiftUniform() {
    let lift = null;
    v.scene.traverse(o => {
      if (lift !== null) return;
      for (const m of [].concat(o.material || [])) {
        const u = v.renderer3.properties.get(m)?.uniforms?.stageRing?.value;
        if (u) { lift = u[23]; break; }
      }
    });
    return lift;
  },
};
"""


def patch_mean(img, x, y, r=4):
    px = []
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            xx, yy = int(round(x)) + dx, int(round(y)) + dy
            if 0 <= xx < img.width and 0 <= yy < img.height:
                px.append(img.getpixel((xx, yy))[:3])
    if not px:
        return None
    return [round(sum(p[k] for p in px) / len(px)) for k in range(3)]


def scenario_porch_top_is_neutral_with_sun_off():
    served = L.serve()
    if served is None:
        return
    L.reset()
    from PIL import Image
    from services import ha_api, storage, twin_weather_state as ground
    storage.patch_settings({
        'home_location': 'Covered sky fixture', 'timezone': 'Etc/UTC',
        'weather_entity': 'weather.home', 'lawn_grass_type': 'cool',
        **{key: '' for key in ground.SENSOR_SETTINGS.values()},
    })
    storage.set_cached_geocode('Covered sky fixture', 40, 0)

    with patch.object(ha_api, 'states_unreachable', return_value=False), \
            patch.object(ha_api, 'get_weather_forecast', return_value=[]):
        attrs = {'friendly_name': 'Home', 'cloud_coverage': 0, 'temperature': 20, 'temperature_unit': 'C',
                 'humidity': 45, 'wind_speed': 0, 'wind_speed_unit': 'm/s', 'wind_bearing': 270, 'forecast': []}
        L.FAKE.states['weather.home'] = {'entity_id': 'weather.home', 'state': 'sunny', 'attributes': attrs}
        now = time.time()
        forcing, _s, _u = ground.observation(list(L.FAKE.states.values()), storage.get_settings(), now)
        storage.set_app_state(ground.KEY, {'snow_cm': 0., 'wetness': 0., 'updated': now, 'last_rain': now - 86400 * 3, 'forcing': forcing})

        with served.browser(launch_args=L.GPU_ARGS) as page:
            page.set_default_timeout(90000)
            page.set_viewport_size({'width': 1280, 'height': 720})
            L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true', live=False)
            deadline = time.time() + 60
            while True:
                w = page.evaluate('() => { const w=window.__twin?.weather; return w?{c:w.condition,n:w.neutral}:null; }')
                if w and w['c'] == 'sunny' and not w['n']:
                    break
                check(time.time() < deadline, ('weather arrived', w))
                page.wait_for_timeout(300)
            page.evaluate("() => window.__twin.setClock('2026-06-21T12:00:00Z')")
            H.settle(page, 25)
            page.wait_for_timeout(1200)
            page.add_script_tag(content=PROBE_JS, type='module')
            page.wait_for_function('() => !!window.__covSky', timeout=30000)

            # 1. June noon with sun ON: covered porch top gets sunlit-ground bounce (neutral-warm, brighter than sun off).
            samples_on = page.evaluate('() => window.__covSky.aimPorch(false)')
            H.settle(page, 15)
            page.wait_for_timeout(800)
            shot_on = Path(tempfile.gettempdir()) / 'covered_sky_live_porch_sun_on.png'
            page.screenshot(path=str(shot_on))
            img_on = Image.open(shot_on).convert('RGB')
            sun_on_rgb = {}
            for name, info in samples_on.items():
                check(info['normalY'] is not None and info['normalY'] > 0.9, ('upward porch face', name, info))
                check(info['open'] is not None and info['open'] < 0.05, ('covered porch face', name, info))
                rgb = patch_mean(img_on, info['sx'], info['sy'])
                check(rgb is not None and max(rgb) > 25, ('sunlit-bounce porch sample', name, rgb))
                br = rgb[2] / max(rgb[0], 1)
                print(f'  sun_on  {name}: rgb={rgb} b/r={br:.3f}')
                check(0.85 <= br <= 1.15, ('sun-on covered porch neutral-warm (0.85 <= b/r <= 1.15)', name, rgb, round(br, 3)))
                sun_on_rgb[name] = rgb

            # 2. June noon with sun OFF: covered porch top drops back to dim neutral bounce (b/r < 1.25).
            samples = page.evaluate('() => window.__covSky.aimPorch(true)')
            H.settle(page, 15)
            page.wait_for_timeout(800)
            shot = Path(tempfile.gettempdir()) / 'covered_sky_live_porch.png'
            page.screenshot(path=str(shot))
            img = Image.open(shot).convert('RGB')

            checked = 0
            for name, info in samples.items():
                check(info['normalY'] is not None and info['normalY'] > 0.9, ('upward porch face', name, info))
                check(info['open'] is not None and info['open'] < 0.05, ('covered porch face', name, info))
                rgb = patch_mean(img, info['sx'], info['sy'])
                check(rgb is not None and max(rgb) > 10, ('non-black sample', name, rgb))
                br = rgb[2] / max(rgb[0], 1)
                print(f'  sun_off {name}: rgb={rgb} b/r={br:.3f}')
                check(br < 1.25, ('covered porch top neutral (b/r < 1.25)', name, rgb, round(br, 3)))
                check(sum(sun_on_rgb[name]) > sum(rgb) + 20, ('sun-on bounce brighter than sun-off', name, sun_on_rgb[name], rgb))
                checked += 1
            check(checked == 3, ('all three porch samples checked', checked))

            # Roof on => stageRing[5].w == 0; lifting roof via floor view => stageRing[5].w == 1.
            lift_on = page.evaluate('() => window.__covSky.roofLiftUniform()')
            check(lift_on is not None and abs(lift_on) < 0.01, ('roof on sets roof lift to 0', lift_on))
            page.evaluate("() => window.__twin.levels.go({level:'floor', building:'main-house', floor:'L1'}, {immediate:true})")
            H.settle(page, 20)
            page.wait_for_timeout(600)
            lift_off = page.evaluate('() => window.__covSky.roofLiftUniform()')
            check(lift_off is not None and abs(lift_off - 1.0) < 0.01, ('lifted roof sets roof lift to 1', lift_off))
            L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_porch_top_is_neutral_with_sun_off])
