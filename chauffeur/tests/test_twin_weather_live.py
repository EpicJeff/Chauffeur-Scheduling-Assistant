"""Environment slice 3 in Chromium: weather, surface shaders and precipitation.

Run from chauffeur/: python tests/test_twin_weather_live.py [OUT_DIR]
The shared live-HA harness supplies the household and panel authentication.
No browser work occurs until a scenario is called. The cost scenario includes
the caller-required --disable-gpu-vsync and --disable-frame-rate-limit flags.
"""
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.request

# Set this before importing the harness/services, even if the caller has a data dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_weather_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

H, check = L.H, L.check
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
TIMEOUT = 40000
NOON, GOLDEN, NIGHT = '2026-06-21T12:00:00Z', '2026-06-21T19:05:00Z', '2026-06-22T00:30:00Z'
TIMES = (('noon', NOON), ('golden', GOLDEN), ('night', NIGHT))
WEATHER = {
    'clear': ('sunny', 0, 'none', 0),
    'rainy': ('rainy', 90, 'rain', .45),
    'pouring': ('pouring', 100, 'rain', 1),
    'snowy': ('snowy', 100, 'snow', .5),
    'fog': ('fog', 100, 'none', 0),
    'lightning-rainy': ('lightning-rainy', 100, 'rain', .8),
}
PREVIEWS = (('Clear', 'clear', 'none', 0), ('Rain', 'rain', 'rain', .45),
            ('Pouring', 'pouring', 'rain', 1), ('Snow', 'snow', 'snow', .5),
            ('Fog', 'fog', 'none', 0), ('Thunderstorm', 'thunderstorm', 'rain', .8))


@contextmanager
def fixture():
    served = L.serve()
    if served is None:
        yield None
        return
    L.reset()
    from services import ha_api, storage, twin_store, twin_weather_state
    storage.patch_settings({'home_location': 'Weather fixture home', 'timezone': 'Etc/UTC',
                            'weather_entity': 'weather.home',
                            **{key: '' for key in twin_weather_state.SENSOR_SETTINGS.values()}})
    storage.set_cached_geocode('Weather fixture home', 40, 0)
    twin_store.set_front_bearing(180)
    # FakeHA replaces get_states, but not its real-cache reachability companion.
    with patch.object(ha_api, 'states_unreachable', return_value=False), \
            patch.object(ha_api, 'get_weather_forecast', return_value=[]):
        weather('clear')
        yield served


def weather(kind):
    """An HA observation/event, with the real ground route's backing record seeded.

    Snow uses the real route, not Snow preview or a browser interception. Missing
    temperature prevents accumulation/melt from drifting the fixture's exact 8 cm.
    """
    from services import ha_events, storage, twin_weather_state as ground
    condition, cover, _precip, _rate = WEATHER[kind]
    row = {'entity_id': 'weather.home', 'state': condition,
           'attributes': {'friendly_name': 'Home', 'cloud_coverage': cover,
                          'temperature': None if kind == 'snowy' else 20, 'temperature_unit': 'C',
                          'wind_speed': 15, 'wind_bearing': 270, 'wind_speed_unit': 'km/h',
                          'forecast': []}}
    with ground._lock:
        L.FAKE.states['weather.home'] = row
        now = time.time()
        forcing, _source, usable = ground.observation(list(L.FAKE.states.values()), storage.get_settings(), now)
        check(usable, ('fake weather must be usable', kind))
        storage.set_app_state(ground.KEY, {'snow_cm': 8. if kind == 'snowy' else 0.,
                                         'wetness': 0., 'updated': now, 'last_rain': None,
                                         'forcing': forcing})
    # Drive the same existing SSE path as a real HA event; no view setter/refresh.
    ha_events._publish({'entity_id': 'weather.home', 'new_state': copy.deepcopy(row)})


def ground_state(served):
    request = urllib.request.Request(served.url('api/house/twin/weather-state'),
                                     headers={'X-Device-Token': L.STATE['panel']})
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode('utf-8'))


def open_weather(page, served, tier='high', size=(1600, 900)):
    page.set_default_timeout(TIMEOUT)
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    L.open_twin(page, served, query=f'tier={tier}&test=1&panel=true&kiosk=true')
    wait_weather(page, 'clear')
    horizon_look(page)


def pin(page, iso):
    # Test clock only. Now/preview choices made by a person use real buttons below.
    page.evaluate('(iso) => window.__twin.setClock(iso)', iso)
    H.settle(page, 30)
    page.wait_for_timeout(800)


def horizon_look(page):
    page.evaluate("""() => { const v = window.__twin; v.levels.go({level:'house'},{immediate:true});
      const c = v.controls.target.clone(), p = v.camera.position.clone();
      const d = p.clone().sub(c); d.y = Math.max(3, d.length() * .08);
      v.setCameraState({position:c.clone().add(d).toArray(), target:c.toArray()}); }""")
    H.settle(page, 10)


def screenshot(page, name):
    if OUT:
        OUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT / name))


def wait_weather(page, kind):
    condition, cover, precip, rate = WEATHER[kind]
    page.wait_for_function("""want => {
      const w=window.__twin?.weather;
      return w && w.preview===null && !w.neutral && w.condition===want.condition &&
        w.precip===want.precip && Math.abs(w.rate-want.rate)<1e-6 &&
        Math.abs(w.clouds.coverage-want.coverage)<.02 &&
        (want.condition!=='snowy' || Math.abs(w.snow_cm-8)<1e-6) &&
        (want.condition!=='fog' || w.fog===1);
    }""", arg={'condition': condition, 'coverage': cover / 100, 'precip': precip, 'rate': rate}, timeout=TIMEOUT)
    assert_particles(page, precip, rate)
    # The render loop consumes the latest object, including the real ground state.
    page.wait_for_function("""() => {
      const v=window.__twin,w=v.weather,u=v.weatherSurface.uniforms.weatherSurface.value;
      return Math.abs(u.x-w.wetness)<1e-6 && Math.abs(u.y-Math.min(1,w.snow_cm/8))<1e-6 &&
        Math.abs(u.z-w.puddles)<1e-6 && Math.floor(u.w)===Math.round((w.precip==='rain'?w.rate:0)*255);
    }""", timeout=TIMEOUT)


def assert_particles(page, precip, rate):
    page.wait_for_function("""({precip,rate}) => {
      const v=window.__twin,p=v?.precipitation;
      if(!p || !p.group.visible)return false;
      const capacity={low:1500,medium:4000,high:8000,max:12000}[v.tier];
      for(const kind of ['rain','snow','hail']) {
        const count=kind===precip?Math.floor(capacity*({rain:1,snow:.5,hail:.3}[kind])*rate):0;
        const o=p.objects[kind];
        if(o.visible!==(count>0) || o.geometry.instanceCount!==count)return false;
      }
      return precip==='rain' || (!p.objects.splash.visible && p.objects.splash.geometry.instanceCount===0);
    }""", arg={'precip': precip, 'rate': rate}, timeout=TIMEOUT)


def preview_drawer(page):
    page.get_by_role('button', name='House time preview', exact=True).click()
    drawer = page.get_by_role('dialog', name='House settings', exact=True)
    drawer.wait_for(state='visible', timeout=TIMEOUT)
    return drawer


def click_preview(page, drawer, label, name, precip, rate):
    before = page.evaluate('Date.now()')
    drawer.get_by_role('button', name=label, exact=True).click()
    page.wait_for_function('(name) => window.__twin.weather.preview===name', arg=name, timeout=TIMEOUT)
    after = page.evaluate('Date.now()')
    deadline = page.evaluate('window.__twin.weatherPreviewDeadline()')
    check(isinstance(deadline, (int, float)) and before + 120000 <= deadline <= after + 120000,
          ('preview deadline is 120 seconds from its real click', name, before, deadline, after))
    check(drawer.get_by_role('button', name=label, exact=True).get_attribute('aria-pressed') == 'true',
          ('selected preview is pressed', name))
    assert_particles(page, precip, rate)


def click_now(page, drawer):
    drawer.get_by_role('button', name='Now', exact=True).click()
    wait_weather(page, 'clear')
    check(page.evaluate('window.__twin.weatherPreviewDeadline()') is None, 'Now clears the weather deadline')
    check(page.evaluate('window.__twin.state.time') == 'now', 'Now restores the live clock mode')
    check(drawer.locator('[data-weather-preview][aria-pressed="true"]').count() == 0,
          'Now unpresses every weather preview')


def scenario_weather_looks_and_programs():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_weather(page, served)
            # First FULL weather/time pass warms every variant; second must add none.
            passes = []
            for pass_index in range(2):
                counts = []
                for kind in WEATHER:
                    weather(kind)
                    body = ground_state(served)
                    check(body['source']['entity'] == 'weather.home' and not body['source']['stale'], body)
                    if kind == 'snowy':
                        check(body['snow_cm'] == 8, ('real ground route reports 8 cm', body))
                    wait_weather(page, kind)
                    for name, iso in TIMES:
                        pin(page, iso)
                        if pass_index == 0:
                            screenshot(page, f'weather_{kind}_{name}.png')
                        if pass_index:
                            check(page.evaluate('window.__twin.renderer3.info.programs.length') == passes[0][-1][1],
                                  ('no new program after full warm-up', kind, name))
                    counts.append((kind, page.evaluate('window.__twin.renderer3.info.programs.length')))
                passes.append(counts)
                print(f'WEATHER_PROGRAMS pass={pass_index + 1} {json.dumps(counts)}')
            check(all(count == passes[0][-1][1] for _kind, count in passes[1]),
                  ('program count stable after first full pass', passes))
            L.no_errors(served)


def scenario_previews_return_to_live():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_weather(page, served)
            pin(page, NOON)
            drawer = preview_drawer(page)
            for label, name, precip, rate in PREVIEWS:
                click_preview(page, drawer, label, name, precip, rate)
                click_now(page, drawer)
            L.no_errors(served)


CENSUS_JS = r"""() => {
  const v=window.__twin,gl=v.renderer3.getContext();
  const samplerTypes=new Set(['SAMPLER_2D','SAMPLER_CUBE','SAMPLER_3D','SAMPLER_2D_SHADOW',
    'SAMPLER_2D_ARRAY','SAMPLER_2D_ARRAY_SHADOW','SAMPLER_CUBE_SHADOW','INT_SAMPLER_2D',
    'INT_SAMPLER_3D','INT_SAMPLER_CUBE','INT_SAMPLER_2D_ARRAY','UNSIGNED_INT_SAMPLER_2D',
    'UNSIGNED_INT_SAMPLER_3D','UNSIGNED_INT_SAMPLER_CUBE','UNSIGNED_INT_SAMPLER_2D_ARRAY']
    .map(k=>gl[k]).filter(k=>typeof k==='number'));
  const litTypes=new Set(['MeshStandardMaterial','MeshPhysicalMaterial','MeshLambertMaterial',
    'MeshPhongMaterial','MeshToonMaterial']);
  return v.renderer3.info.programs.map(p=>{
    const source=gl.getShaderSource(p.fragmentShader);
    if(!source)throw new Error('Missing compiled fragment source for '+p.id);
    const active=gl.getProgramParameter(p.program,gl.ACTIVE_UNIFORMS);
    let samplers=0,slots=0;const samplerUniforms=[];
    for(let i=0;i<active;i++) {
      const u=gl.getActiveUniform(p.program,i);
      if(!u)throw new Error('Missing active uniform '+i+' in '+p.id);
      slots+=u.size; // Active uniform array ELEMENTS, not fragment vec4 registers.
      if(samplerTypes.has(u.type)){samplers+=u.size;samplerUniforms.push([u.name,u.size]);}
    }
    const surface=source.includes('weatherSurface');
    // Authored water/steam shaders use the scene's sky light rather than Three's
    // light chunks. Recognize their actual light/glow declaration AND usage.
    const customLit=p.type==='ShaderMaterial' && /uniform\s+float\s+light\s*;/.test(source) &&
      /uniform\s+vec3\s+glow\s*;/.test(source) && /\blight\s*\+\s*glow\b/.test(source);
    return {id:p.id,name:p.name,type:p.type,linked:gl.getProgramParameter(p.program,gl.LINK_STATUS),
      activeUniforms:active,uniformSlots:slots,samplers,samplerUniforms,surface,
      lit:litTypes.has(p.type)||customLit,customLit};
  });
}"""


def scenario_census_in_chromium():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_weather(page, served)
            weather('rainy')
            wait_weather(page, 'rainy')
            for _name, iso in TIMES:
                pin(page, iso)
            rows = page.evaluate(CENSUS_JS)
            check(rows and all(row['linked'] for row in rows), ('all census programs link', rows))
            top = sorted(rows, key=lambda row: (row['samplers'], row['uniformSlots']), reverse=True)[:8]
            for row in top:
                print('WEATHER_CENSUS_TOP ' + json.dumps(row, sort_keys=True))
            surfaces = [row for row in rows if row['surface']]
            print(f'WEATHER_CENSUS programs={len(rows)} lit={sum(row["lit"] for row in rows)} '
                  f'weatherSurface={len(surfaces)} surface_lit={sum(row["lit"] for row in surfaces)} '
                  f'surface_custom_lit={sum(row["customLit"] for row in surfaces)}')
            check(all(row['samplers'] <= 16 for row in rows),
                  ('no program exceeds 16 sampler units (arrays count by size)',
                   [row for row in rows if row['samplers'] > 16]))
            check(surfaces, 'census must exercise weatherSurface programs')
            check(all(row['lit'] for row in surfaces),
                  ('weatherSurface occurs only in lit programs', [row for row in surfaces if not row['lit']]))
            L.no_errors(served)


FRAME_MS_JS = """() => new Promise(done => {
  const times=[]; let last;
  const step=now=>{
    if(last!==undefined)times.push(now-last);
    last=now;
    if(times.length<90)requestAnimationFrame(step);
    else { times.sort((a,b)=>a-b);done((times[44]+times[45])/2); }
  };
  requestAnimationFrame(step);
})"""


def scenario_precipitation_cost():
    with fixture() as served:
        if served is None:
            return
        args = [*L.GPU_ARGS, '--disable-gpu-vsync', '--disable-frame-rate-limit']
        with served.browser(launch_args=args) as page:
            open_weather(page, served, size=(1920, 1080))
            pin(page, NOON)
            # Let GPU noise generation, captures and both looks settle before timing.
            weather('pouring')
            wait_weather(page, 'pouring')
            page.wait_for_timeout(15000)
            weather('clear')
            wait_weather(page, 'clear')
            page.wait_for_timeout(5000)
            clear = page.evaluate(FRAME_MS_JS)
            weather('pouring')
            wait_weather(page, 'pouring')
            page.wait_for_timeout(5000)
            pouring = page.evaluate(FRAME_MS_JS)
            check(clear > 0 and pouring > 0, ('positive frame medians', clear, pouring))
            print(f'WEATHER_COST clear={clear:.2f} pouring={pouring:.2f} delta={pouring-clear:.2f}')
            # This is total weather cost (clouds/surface/particles), not isolated rain GPU time.
            L.no_errors(served)


def scenario_low_tier_shows_rain_and_snow():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_weather(page, served, tier='low', size=(1920, 1080))
            check(page.evaluate('window.__twin.tier') == 'low', 'panel uses low tier')
            pin(page, NOON)
            for label, name, precip, rate, count in (('Rain', 'rain', 'rain', .45, 675),
                                                    ('Snow', 'snow', 'snow', .5, 375)):
                drawer = preview_drawer(page)
                click_preview(page, drawer, label, name, precip, rate)
                check(page.evaluate('(kind)=>window.__twin.precipitation.objects[kind].geometry.instanceCount', precip) == count,
                      ('specified low-tier preview count', name, count))
                drawer.get_by_role('button', name='Close settings', exact=True).click()
                drawer.wait_for(state='hidden', timeout=TIMEOUT)
                H.settle(page, 30)
                screenshot(page, f'weather_low_{name}.png')
                drawer = preview_drawer(page)
                click_now(page, drawer)
                drawer.get_by_role('button', name='Close settings', exact=True).click()
                drawer.wait_for(state='hidden', timeout=TIMEOUT)
            L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_weather_looks_and_programs, scenario_previews_return_to_live,
           scenario_census_in_chromium, scenario_precipitation_cost,
           scenario_low_tier_shows_rain_and_snow])
