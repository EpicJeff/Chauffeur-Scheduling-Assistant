"""Task 3 live Chromium test: gutters, downspouts, stream suppression, pours and program count.

Run from chauffeur/: python tests/test_twin_gutters_live.py
"""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_gutters_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

H, check = L.H, L.check
TIMEOUT = 40000
NOON = '2026-06-21T12:00:00Z'
SHOTS_DIR = Path(r'E:\repositories\Chauffeur-gutters-g\.gemini-tmp\shots\elbow')


from tools.demo_seed import GUTTER_OUTLET_CAMERA, synthetic_plan as demo_plan  # shared synthetic fixture


def seed_plan(plan):
    from services import twin_plan, twin_store
    from services.twin_model_bridge import assemble
    norm, _ = twin_plan.normalize(copy.deepcopy(plan))
    model, _ = assemble(norm)
    twin_store.update_model(lambda _: copy.deepcopy(model), kind='build')


def synthetic_plan(gutters_on=True):
    """The demo awning has no gutter; its eave would stream in both states."""
    plan = demo_plan(gutters_on=gutters_on)
    main = plan['buildings'][0]
    main['roofs'] = [r for r in main['roofs'] if r['id'] != 'demo-awning']
    main['roof']['sections'] = [s for s in main['roof']['sections'] if s['id'] != 'demo-awning']
    return plan


def set_pouring():
    from services import storage, twin_weather_state as ground
    row = {
        'entity_id': 'weather.home', 'state': 'pouring',
        'attributes': {'friendly_name': 'Home', 'cloud_coverage': 100,
                       'temperature': None, 'temperature_unit': 'C',
                       'wind_speed': 10, 'wind_bearing': 240, 'wind_speed_unit': 'km/h',
                       'forecast': []},
    }
    with ground._lock:
        L.FAKE.states['weather.home'] = row
        now = time.time()
        forcing, _source, usable = ground.observation(list(L.FAKE.states.values()), storage.get_settings(), now)
        check(usable, 'pouring weather usable')
        storage.set_app_state(ground.KEY, {
            'snow_cm': 0.0, 'wetness': 1.0, 'updated': now, 'last_rain': now, 'forcing': forcing,
        })


@contextmanager
def fixture():
    served = L.serve()
    if served is None:
        yield None
        return
    L.reset()
    from services import ha_api, storage, twin_store, twin_weather_state
    storage.patch_settings({
        'home_location': 'Gutters fixture home', 'timezone': 'Etc/UTC',
        'weather_entity': 'weather.home',
        **{key: '' for key in twin_weather_state.SENSOR_SETTINGS.values()},
    })
    storage.set_cached_geocode('Gutters fixture home', 40, 0)
    twin_store.set_front_bearing(180)
    with patch.object(ha_api, 'states_unreachable', return_value=False), \
            patch.object(ha_api, 'get_weather_forecast', return_value=[]):
        set_pouring()
        yield served


def open_rainy_view(page, served):
    page.set_default_timeout(TIMEOUT)
    page.set_viewport_size({'width': 1600, 'height': 900})
    page.add_init_script("""(() => { const timer=window.setTimeout.bind(window);
      window.setTimeout=(fn,ms,...args)=>timer(fn,ms===300000?1000:ms,...args); })();""")
    L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true', live=False)
    page.evaluate("""(iso) => {
      const v = window.__twin;
      v.setClock(iso);
      v.levels.go({ level: 'house' }, { immediate: true });
      v.setCameraState({ position: [14, 10, 16], target: [5.5, 2.2, -3.3] });
    }""", NOON)
    H.settle(page, 10)
    try:
        page.wait_for_function("""() => {
          const v = window.__twin, w = v?.weather;
          return w && w.precip === 'rain' && w.rate >= 0.99 && w.wetness >= 0.99 && v.eaves?.group?.visible;
        }""", timeout=15000)
    except Exception:
        diag = page.evaluate("""() => {
          const v = window.__twin;
          return {
            weather: v?.weather,
            eavesVisible: v?.eaves?.group?.visible,
            eavesLen: v?.eaves?.data?.instances?.length,
            eaveFlow: v?.eaves?.uniforms?.eaveFlow?.value,
            eaveWet: v?.eaves?.uniforms?.eaveWet?.value,
            level: v?.levels?.snapshot?.(),
            unlit: v?.state?.unlit,
            planBuildings: v?.plan?.buildings?.length,
            roofSections: v?.plan?.buildings?.[0]?.roof?.sections?.length,
          };
        }""")
        print('RAINY_DIAG', json.dumps(diag), flush=True)
        raise
    H.settle(page, 25)
    # Wait for asynchronous reflection-probe compiles to settle so program counts match deterministically.
    page.wait_for_function("""() => {
      const n = window.__twin?.renderer3?.info?.programs?.length ?? 0;
      if (window.__progLast === n) { window.__progStable = (window.__progStable || 0) + 1; }
      else { window.__progLast = n; window.__progStable = 0; }
      return window.__progStable >= 15;
    }""", timeout=TIMEOUT)


def scenario_gutters_pours_and_programs():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            # 1) Measure program count with gutters OFF in heavy rain, and capture kickout_pour_off.png.
            seed_plan(synthetic_plan(gutters_on=False))
            open_rainy_view(page, served)
            off_info = page.evaluate("""() => {
              const v = window.__twin;
              let gutterRanges = 0, gutterMeshTagged = 0;
              v.scene.traverse(o => {
                if (!o.isMesh) return;
                if (o.userData?.surfaceKind === 'gutter') gutterMeshTagged++;
                gutterRanges += (o.userData?.snapRanges || []).filter(r => r.surfaceKind === 'gutter').length;
              });
              return {
                programs: v.renderer3.info.programs.length,
                gutterRanges,
                gutterMeshTagged,
                eavesCount: v.eaves.data.eaves.length,
                instances: v.eaves.data.instances.length,
                drawn: v.eaves.streams?.geometry?.instanceCount || 0,
              };
            }""")
            print('GUTTERS_OFF', json.dumps(off_info))
            check(off_info['gutterRanges'] == 0 and off_info['gutterMeshTagged'] == 0, ('no gutter geometry when off', off_info))
            check(off_info['eavesCount'] > 0 and off_info['instances'] > 0, ('streams present when off', off_info))

            # Capture gutters-OFF close-up at the exact front-right corner kick-out camera for off/on comparison.
            SHOTS_DIR.mkdir(parents=True, exist_ok=True)
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              const FT = 0.3048;
              const x = 36 * FT, y = 0.14, z = 1.01;
              const target = [x, y + 0.04, z - 0.12];
              const pos = [x + 1.35, y + 0.32, z + 0.90];
              v.setCameraState({ position: pos, target });
            }""")
            H.settle(page, 20)
            page.screenshot(path=str(SHOTS_DIR / 'kickout_pour_off.png'))

            # 2) Reload with gutters ON all eaves in heavy rain.
            seed_plan(synthetic_plan(gutters_on=True))
            open_rainy_view(page, served)
            on_info = page.evaluate("""() => {
              const v = window.__twin;
              let gutterRanges = 0, gutterMeshTagged = 0;
              v.scene.traverse(o => {
                if (!o.isMesh) return;
                if (o.userData?.surfaceKind === 'gutter') gutterMeshTagged++;
                gutterRanges += (o.userData?.snapRanges || []).filter(r => r.surfaceKind === 'gutter').length;
              });
              const instances = v.eaves.data.instances || [];
              const streamInstances = instances.filter(i => !i.pour).length;
              const pourInstances = instances.filter(i => i.pour).length;
              const blockedPours = instances.filter(i => i.pour && (i.spout?.flags || []).includes('outlet-blocked')).length;
              const postPours = instances.filter(i => i.pour && i.mount === 'post').length;
              return {
                programs: v.renderer3.info.programs.length,
                gutterRanges,
                gutterMeshTagged,
                eavesCount: v.eaves.data.eaves.length,
                streamInstances,
                pourInstances,
                blockedPours,
                postPours,
                visible: v.eaves.group.visible,
                drawn: v.eaves.streams?.geometry?.instanceCount || 0,
              };
            }""")
            print('GUTTERS_ON', json.dumps(on_info))
            check(on_info['gutterRanges'] > 0, ('gutter snapRanges present when on', on_info))
            check(on_info['gutterMeshTagged'] == 0, ('merged fascia+gutter batch must NOT be tagged gutter at mesh level', on_info))
            check(on_info['eavesCount'] == 0 and on_info['streamInstances'] == 0,
                  ('no stream instances on guttered edges', on_info))
            check(on_info['pourInstances'] == 8 and on_info['visible'] and on_info['drawn'] == on_info['pourInstances'],
                  ('exact drawn pours visible', on_info))
            check(on_info['blockedPours'] == 1, ('fixture includes 1 outlet-blocked spill', on_info))
            check(on_info['postPours'] == 1, ('fixture includes 1 porch-post downspout', on_info))
            check(on_info['programs'] == off_info['programs'],
                  ('program count unchanged vs gutters off', off_info['programs'], on_info['programs']))

            # 3) Save screenshots under round2/: overview, building focus, and full close-up set (<= 2.5 m).
            # Overview
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              v.setCameraState({ position: [18, 12, 20], target: [8.0, 2.2, -3.3] });
            }""")
            H.settle(page, 20)
            page.screenshot(path=str(SHOTS_DIR / 'overview.png'))

            # Building focus (exterior view framed tightly on Main House with gutters and downspouts)
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              v.setCameraState({ position: [12.5, 4.8, 12.0], target: [5.5, 2.0, -2.5] });
            }""")
            H.settle(page, 20)
            page.screenshot(path=str(SHOTS_DIR / 'building_focus.png'))

            # Close-up 1: <= 2.2 m from front-right corner gutter bottom outlet & offset elbows (particles off).
            page.evaluate(GUTTER_OUTLET_CAMERA)
            H.settle(page, 20)
            cam_outlet = page.evaluate("""() => {
              const v = window.__twin, c = v.cameraState();
              return { ...c, dist: Math.hypot(c.position[0]-c.target[0], c.position[1]-c.target[1], c.position[2]-c.target[2]) };
            }""")
            check(cam_outlet['dist'] <= 2.5, ('outlet close-up within 2.5 m', cam_outlet))
            page.screenshot(path=str(SHOTS_DIR / 'corner_outlet_elbows.png'))

            # Close-up 2a: ~1.5 m side profile of corner downspout curved elbow & pour in overcast heavy rain (rain particles ON).
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = true;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              const pours = (v.eaves.data.instances || []).filter(i => i.pour);
              const pour = pours.find(p => p.mount === 'wall' && p.top[0] > 9 && p.top[0] < 12 && p.top[2] > -2) || pours[0];
              if (!pour) return;
              const [x, y, z] = pour.top;
              const target = [x, y + 0.04, z - 0.06];
              const pos = [x + 1.42, y + 0.18, z + 0.36];
              v.setCameraState({ position: pos, target });
            }""")
            H.settle(page, 20)
            cam_kick = page.evaluate("""() => {
              const v = window.__twin, c = v.cameraState();
              return { ...c, dist: Math.hypot(c.position[0]-c.target[0], c.position[1]-c.target[1], c.position[2]-c.target[2]), eaveFlow: v.eaves.uniforms.eaveFlow.value };
            }""")
            check(cam_kick['dist'] <= 2.5, ('elbow close-up within 2.5 m', cam_kick))
            page.screenshot(path=str(SHOTS_DIR / 'corner_elbow_overcast_rain.png'))

            # Close-up 2b: same ~1.5 m side-profile elbow camera in bright day with rain particles off so the curve reads crisply.
            page.evaluate("""() => {
              const v = window.__twin;
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              if (v.weather) {
                v.__savedWeather = { ...v.weather };
                v.weather.cloud = 0.12;
                v.weather.sun = 1.0;
                v.weather.sunClear = 1.0;
              }
              v.setClock('2026-06-21T12:00:00Z');
            }""")
            H.settle(page, 20)
            page.screenshot(path=str(SHOTS_DIR / 'corner_elbow_side.png'))
            page.evaluate("""() => {
              const v = window.__twin;
              if (v.__savedWeather && v.weather) Object.assign(v.weather, v.__savedWeather);
              v.setClock('2026-06-21T12:00:00Z');
            }""")

            # Close-up 3: ~1.5 m porch-post downspout bottom curved elbow & pour (particles off).
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              const pours = (v.eaves.data.instances || []).filter(i => i.pour);
              const post = pours.find(p => p.mount === 'post');
              if (!post) return;
              const [ox, oy, oz] = post.top;
              const target = [ox, oy + 0.04, oz - 0.08];
              const pos = [target[0] - 1.28, target[1] + 0.22, target[2] + 0.68];
              v.setCameraState({ position: pos, target });
            }""")
            H.settle(page, 20)
            cam_post = page.evaluate("""() => {
              const v = window.__twin, c = v.cameraState();
              return { ...c, dist: Math.hypot(c.position[0]-c.target[0], c.position[1]-c.target[1], c.position[2]-c.target[2]) };
            }""")
            check(cam_post['dist'] <= 2.5, ('porch-post close-up within 2.5 m', cam_post))
            page.screenshot(path=str(SHOTS_DIR / 'porch_post_elbow.png'))

            # Close-up 4: <= 2.0 m outlet-blocked spill (jammed gutter over flat carport roof -> outlet hole + short spill).
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              const pours = (v.eaves.data.instances || []).filter(i => i.pour);
              const blocked = pours.find(p => (p.spout?.flags || []).includes('outlet-blocked'));
              if (!blocked) return;
              const [bx, by, bz] = blocked.top;
              const target = [bx, by + 0.04, bz - 0.05];
              const pos = [bx + 0.90, by + 0.72, bz + 0.85];
              v.setCameraState({ position: pos, target });
            }""")
            H.settle(page, 20)
            cam_blocked = page.evaluate("""() => {
              const v = window.__twin, c = v.cameraState();
              return { ...c, dist: Math.hypot(c.position[0]-c.target[0], c.position[1]-c.target[1], c.position[2]-c.target[2]) };
            }""")
            check(cam_blocked['dist'] <= 2.5, ('outlet-blocked close-up within 2.5 m', cam_blocked))
            page.screenshot(path=str(SHOTS_DIR / 'outlet_blocked_spill.png'))

            print('CLOSEUP_CAMS', json.dumps({'outlet': cam_outlet, 'kickout': cam_kick, 'post': cam_post, 'blocked': cam_blocked}))
            L.no_errors(served)


SCENARIOS = [scenario_gutters_pours_and_programs]

if __name__ == '__main__':
    H.run(SCENARIOS)
