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
SHOTS_DIR = Path(r'E:\repositories\Chauffeur-gutters-g\.gemini-tmp\shots\round1')


def synthetic_plan(gutters_on=True):
    """A synthetic gable+porch house with a hip wing so corners, mitres and downspouts show clearly."""
    poly = [[0, 0], [36, 0], [36, 22], [0, 22]]
    walls = [
        {'id': f'w{i}', 'from': poly[i], 'to': poly[(i + 1) % 4],
         'exterior': True, 'height': 10, 'thickness': 0.5, 'level': 'L1'}
        for i in range(4)
    ]
    edges = [
        {'setting': 'sloped', 'pitch': 6, **({'gutter': True} if gutters_on else {})},
        {'setting': 'gable', 'pitch': 6},
        {'setting': 'sloped', 'pitch': 6, **({'gutter': True} if gutters_on else {})},
        {'setting': 'gable', 'pitch': 6},
    ]
    section = {
        'id': 'r1', 'roof': 'r1', 'kind': 'gable', 'ridge': 'x', 'pitch': 6,
        'plate': 10, 'overhang': 1.25, 'level': 'L1', 'rect': [0, 0, 36, 22],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
        **({'gutters': {'y0': True, 'y1': True}} if gutters_on else {}),
    }
    porch_section = {
        'id': 'r2', 'roof': 'r2', 'kind': 'shed', 'low_side': 'y0', 'pitch': 3,
        'plate': 8.5, 'overhang': 1, 'level': 'L1', 'rect': [6, -8, 22, 0],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
    }
    porch_roof = {
        'id': 'r2', 'area': [[6, -8], [22, -8], [22, 0], [6, 0]], 'overhang': 1,
        'edges': [
            {'setting': 'sloped', 'pitch': 3},
            {'setting': 'gable', 'pitch': 3},
            {'setting': 'gable', 'pitch': 3},
            {'setting': 'gable', 'pitch': 3},
        ],
    }
    building = {
        'id': 'synth-house', 'name': 'Main House', 'position': [0, 0], 'base': 0, 'rotation': 0,
        'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 10, 'outline': poly}],
        'rooms': [{'id': 'rm1', 'name': 'Living', 'level': 'L1', 'polygon': poly}],
        'walls': walls,
        'openings': [
            {'id': 'door1', 'wall': 'w0', 'at': 14, 'width': 3.5, 'sill': 0, 'head': 7, 'kind': 'door'},
            {'id': 'win1', 'wall': 'w0', 'at': 27, 'width': 4, 'sill': 3, 'head': 7, 'kind': 'window'},
        ],
        'porches': [{
            'id': 'front-porch', 'polygon': [[6, -8], [22, -8], [22, 0], [6, 0]],
            'floor': 0.5, 'columns': [{'at': [6.5, -7.5], 'size': 0.5}, {'at': [21.5, -7.5], 'size': 0.5}],
            **({'gutter': True} if gutters_on else {}),
        }],
        'roof': {'sections': [section, porch_section], 'extensions': []},
        'roofs': [{'id': 'r1', 'area': poly, 'overhang': 1.25, 'edges': edges}, porch_roof],
    }
    shed_poly = [[0, 0], [14, 0], [14, 12], [0, 12]]
    shed_walls = [
        {'id': f'sw{i}', 'from': shed_poly[i], 'to': shed_poly[(i + 1) % 4],
         'exterior': True, 'height': 9, 'thickness': 0.5, 'level': 'L1'}
        for i in range(4)
    ]
    shed_section = {
        'id': 'sr1', 'roof': 'sr1', 'kind': 'hip', 'ridge': 'x', 'pitch': 5,
        'plate': 9, 'overhang': 1, 'level': 'L1', 'rect': [0, 0, 14, 12],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
        **({'gutters': {'y0': True, 'x1': True, 'y1': True, 'x0': True}} if gutters_on else {}),
    }
    shed_roof = {
        'id': 'sr1', 'area': shed_poly, 'overhang': 1,
        'edges': [{'setting': 'sloped', 'pitch': 5, **({'gutter': True} if gutters_on else {})} for _ in range(4)],
    }
    shed = {
        'id': 'garden-shed', 'name': 'Garden Shed', 'position': [42, 4], 'base': 0, 'rotation': 0,
        'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 9, 'outline': shed_poly}],
        'rooms': [{'id': 'srm1', 'name': 'Storage', 'level': 'L1', 'polygon': shed_poly}],
        'walls': shed_walls,
        'openings': [{'id': 'sdoor', 'wall': 'sw0', 'at': 7, 'width': 3, 'sill': 0, 'head': 7, 'kind': 'door'}],
        'porches': [],
        'roof': {'sections': [shed_section], 'extensions': []},
        'roofs': [shed_roof],
    }
    return {
        'units': 'ft',
        'buildings': [building, shed],
        'site': {
            'lot': [[-25, -30], [75, -30], [75, 45], [-25, 45]],
            'hardscape': [
                {'id': 'walk1', 'kind': 'walkway', 'polygon': [[12, -25], [16, -25], [16, -8], [12, -8]]},
            ],
            'beds': [
                {'id': 'bed1', 'polygon': [[-3, -4], [5, -4], [5, 0], [-3, 0]], 'elevation': 0},
                {'id': 'bed2', 'polygon': [[31, -4], [39, -4], [39, 0], [31, 0]], 'elevation': 0},
            ],
        },
    }


def seed_plan(plan):
    from services import twin_plan, twin_store
    from services.twin_model_bridge import assemble
    norm, _ = twin_plan.normalize(copy.deepcopy(plan))
    model, _ = assemble(norm)
    twin_store.update_model(lambda _: copy.deepcopy(model), kind='build')


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
              const x = 36 * FT, y = 0.16, z = 1.01;
              const target = [x, y + 0.05, z - 0.10];
              const pos = [x + 1.15, y + 0.55, z + 1.05];
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
              return {
                programs: v.renderer3.info.programs.length,
                gutterRanges,
                gutterMeshTagged,
                eavesCount: v.eaves.data.eaves.length,
                streamInstances,
                pourInstances,
                visible: v.eaves.group.visible,
                drawn: v.eaves.streams?.geometry?.instanceCount || 0,
              };
            }""")
            print('GUTTERS_ON', json.dumps(on_info))
            check(on_info['gutterRanges'] > 0, ('gutter snapRanges present when on', on_info))
            check(on_info['gutterMeshTagged'] == 0, ('merged fascia+gutter batch must NOT be tagged gutter at mesh level', on_info))
            check(on_info['eavesCount'] == 0 and on_info['streamInstances'] == 0,
                  ('no stream instances on guttered edges', on_info))
            check(on_info['pourInstances'] > 0 and on_info['visible'] and on_info['drawn'] == on_info['pourInstances'],
                  ('pours are visible', on_info))
            check(on_info['programs'] == off_info['programs'],
                  ('program count unchanged vs gutters off', off_info['programs'], on_info['programs']))

            # 3) Save screenshots under round1/: overview, building focus, and real close-ups (<= 2.5 m).
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

            # Hide rain streak particles for close-ups so the gutter outlet/elbows and arching pour are unmistakable.
            # Close-up 1: <= 2.2 m from front-right corner downspout top (gutter outlet, fascia, soffit & offset elbows).
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              const pours = (v.eaves.data.instances || []).filter(i => i.pour);
              const pour = pours.find(p => p.mount === 'wall' && p.top[0] > 9 && p.top[0] < 12 && p.top[2] > -2) || pours[0];
              if (!pour) return;
              const sTop = pour.spout.top; // [x, y, z] at gutter outlet
              const target = [sTop[0] - 0.15, sTop[1] - 0.22, sTop[2] - 0.18];
              const pos = [target[0] + 1.15, target[1] - 0.35, target[2] + 1.15];
              v.setCameraState({ position: pos, target });
            }""")
            H.settle(page, 20)
            cam_info = page.evaluate("""() => {
              const v = window.__twin, c = v.cameraState();
              const d = Math.hypot(c.position[0] - c.target[0], c.position[1] - c.target[1], c.position[2] - c.target[2]);
              return { ...c, dist: d };
            }""")
            check(cam_info['dist'] <= 2.5, ('outlet close-up camera within 2.5 m', cam_info))
            page.screenshot(path=str(SHOTS_DIR / 'corner_outlet_elbows.png'))

            # Close-up 2: <= 2.0 m from the kick-out outlet & arching pour (particles off, eaveFlow=1).
            page.evaluate("""() => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              const pours = (v.eaves.data.instances || []).filter(i => i.pour);
              const pour = pours.find(p => p.mount === 'wall' && p.top[0] > 9 && p.top[0] < 12 && p.top[2] > -2) || pours[0];
              if (!pour) return;
              const [x, y, z] = pour.top;
              const target = [x, y + 0.05, z - 0.10];
              const pos = [x + 1.15, y + 0.55, z + 1.05];
              v.setCameraState({ position: pos, target });
            }""")
            H.settle(page, 20)
            kick_info = page.evaluate("""() => {
              const v = window.__twin, c = v.cameraState();
              const d = Math.hypot(c.position[0] - c.target[0], c.position[1] - c.target[1], c.position[2] - c.target[2]);
              return { ...c, dist: d, eaveFlow: v.eaves.uniforms.eaveFlow.value };
            }""")
            check(kick_info['dist'] <= 2.5, ('kickout close-up camera within 2.5 m', kick_info))
            page.screenshot(path=str(SHOTS_DIR / 'kickout_pour_day.png'))
            print('CLOSEUP_CAMS', json.dumps({'outlet': cam_info, 'kickout': kick_info}))
            L.no_errors(served)


SCENARIOS = [scenario_gutters_pours_and_programs]

if __name__ == '__main__':
    H.run(SCENARIOS)
