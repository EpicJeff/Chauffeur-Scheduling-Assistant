"""Environment slice 4 acceptance in Chromium (authoring dispatch: do not run).

Run from chauffeur/: python tests/test_twin_seasons_live.py [OUT_DIR]
Uses the isolated live harness, fake HA and the viewer's own ground polling.
Browser execution and screenshot review belong to Claude. Importing this file
does not launch a browser; each scenario owns its browser context.
"""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.request

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_seasons_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

H, check = L.H, L.check
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
TIMEOUT = 40000
# Fixture longitude is zero and its local timezone is UTC: 23:00 is local night.
NOON = '2026-06-21T12:00:00Z'
GOLDEN = '2026-06-21T19:05:00Z'
NIGHT = '2026-06-21T23:00:00Z'
SUNRISE = '2026-06-21T04:57:00Z'
TIMES = (('noon', NOON), ('golden', GOLDEN))
SEASONS = (('Spring', 'spring', .5, 0), ('Summer', 'summer', 1, 0),
           ('Autumn', 'autumn', 1, .85), ('Winter', 'winter', 0, 1))


@contextmanager
def fixture():
    served = L.serve()
    if served is None:
        yield None
        return
    L.reset()
    from services import ha_api, storage, twin_store, twin_weather_state as ground
    storage.patch_settings({'home_location': 'Seasons fixture home', 'timezone': 'Etc/UTC',
                            'weather_entity': 'weather.home', 'lawn_grass_type': 'cool',
                            **{key: '' for key in ground.SENSOR_SETTINGS.values()}})
    storage.set_cached_geocode('Seasons fixture home', 40, 0)
    twin_store.set_front_bearing(180)
    with patch.object(ha_api, 'states_unreachable', return_value=False), \
            patch.object(ha_api, 'get_weather_forecast', return_value=[]):
        weather(reset_ground=True)
        yield served


def weather(temperature=20, wind=0, reset_ground=False):
    """External HA observation; no viewer setter, route interception or fake SSE."""
    from services import storage, twin_weather_state as ground
    with ground._lock:
        L.FAKE.states['weather.home'] = {
            'entity_id': 'weather.home', 'state': 'sunny',
            'attributes': {'friendly_name': 'Home', 'cloud_coverage': 0,
                           'temperature': temperature, 'temperature_unit': 'C', 'humidity': 50,
                           'wind_speed': wind, 'wind_speed_unit': 'm/s', 'wind_bearing': 270,
                           'forecast': []}}
        if reset_ground:
            now = time.time()
            forcing, _source, usable = ground.observation(list(L.FAKE.states.values()), storage.get_settings(), now)
            check(usable, 'fake HA weather is usable')
            storage.set_app_state(ground.KEY, dict(ground.advance(None, forcing, now), forcing=forcing))


def ground_route(served, *, grass=None):
    """The editor's exact scoped settings route, or the panel's real read route."""
    headers = {'X-Device-Token': L.STATE['panel']}
    data = None
    path = 'api/house/twin/weather-state'
    if grass is not None:
        path = 'api/house/twin/weather-sources'
        headers = {'X-Member-Token': H.STATE['token'], 'Content-Type': 'application/json'}
        data = json.dumps({'lawn_grass_type': grass}).encode('utf-8')
    request = urllib.request.Request(served.url(path), headers=headers, data=data,
                                     method='PUT' if data is not None else 'GET')
    with urllib.request.urlopen(request, timeout=40) as response:
        check(response.status == 200, ('ground route succeeds', path, response.status))
        return json.loads(response.read().decode('utf-8'))


def seed_cold_history():
    """Ten days of hourly model steps, starting green at a cold spell's onset.

    There are 240 hourly observations, as in Task 1's model tests. Only the first
    dormancy value is fixture setup; subsequent motion obeys the 14-day rate.
    Server history uses wall time; pin() changes only the browser's solar clock.
    """
    from services import storage, twin_weather_state as ground
    with ground._lock:
        now = time.time()
        forcing, _source, usable = ground.observation(list(L.FAKE.states.values()), storage.get_settings(), now)
        check(usable and forcing['temperature'] == -3, ('cold forcing', forcing))
        record = None
        for hour in range(240):
            stamp = now - (239 - hour) * 3600
            season = ground.advance_season(record, forcing, stamp, 'warm', 40, True)
            record = dict(ground.advance(record, forcing, stamp), forcing=forcing, **season)
            if hour == 0:
                record['lawn_dormancy'] = 0.
        storage.set_app_state(ground.KEY, record)


def open_seasons(page, served, tier='high', size=(1600, 900)):
    page.set_default_timeout(TIMEOUT)
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    # Accelerate ONLY the five-minute ground poll; preview/clock timers stay real.
    page.add_init_script("""(() => { const timer=window.setTimeout.bind(window);
      window.setTimeout=(fn,ms,...args)=>timer(fn,ms===300000?1000:ms,...args); })();""")
    L.open_twin(page, served, query=f'tier={tier}&test=1&panel=true&kiosk=true', live=False)
    wait_weather(page)
    check(page.evaluate('window.__twin.tier') == tier, ('requested panel tier', tier))
    horizon_look(page)


def wait_weather(page, temperature=20, wind=0):
    page.wait_for_function("""want => {
      const w=window.__twin?.weather;
      return w && !w.neutral && w.preview===null && w.condition==='sunny' &&
        w.precip==='none' && w.rate===0 && w.wetness===0 && w.snow_cm===0 &&
        w.clouds.coverage===0 && w.temperatureC===want.temperature &&
        Math.abs(w.windMps-want.wind)<1e-6;
    }""", arg={'temperature': temperature, 'wind': wind}, timeout=TIMEOUT)


def pin(page, iso):
    page.evaluate('(iso) => window.__twin.setClock(iso)', iso)
    H.settle(page, 30)
    page.wait_for_timeout(800)


def horizon_look(page):
    page.evaluate("""() => { const v=window.__twin; v.levels.go({level:'house'},{immediate:true});
      const c=v.controls.target.clone(),d=v.camera.position.clone().sub(c);
      d.y=Math.max(3,d.length()*.08);
      v.setCameraState({position:c.clone().add(d).toArray(),target:c.toArray()}); }""")
    H.settle(page, 10)


def screenshot(page, name):
    if OUT:
        OUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT / name))


def preview_drawer(page):
    page.get_by_role('button', name='House time preview', exact=True).click()
    drawer = page.get_by_role('dialog', name='House settings', exact=True)
    drawer.wait_for(state='visible', timeout=TIMEOUT)
    return drawer


def close_drawer(drawer):
    drawer.get_by_role('button', name='Close settings', exact=True).click()
    drawer.wait_for(state='hidden', timeout=TIMEOUT)


def choose_season(page, name):
    label, name, presence, autumn = next(row for row in SEASONS if row[1] == name)
    drawer = preview_drawer(page)
    before = page.evaluate('Date.now()')
    button = drawer.get_by_role('button', name=label, exact=True)
    button.click()
    page.wait_for_function("""want => {
      const v=window.__twin,s=v.season,u=v.seasons.uniforms;
      return s.preview===want.name && s.presence===want.presence && s.autumn===want.autumn &&
        u.seasonFoliage.value.x===s.presence && u.seasonFoliage.value.y===s.autumn &&
        u.seasonDormancy.value===s.dormancy;
    }""", arg={'name': name, 'presence': presence, 'autumn': autumn}, timeout=TIMEOUT)
    after = page.evaluate('Date.now()')
    deadline = page.evaluate('window.__twin.seasonPreviewDeadline()')
    check(before + 120000 <= deadline <= after + 120000, ('120-second season preview', name, deadline))
    check(button.get_attribute('aria-pressed') == 'true', ('pressed season button', name))
    close_drawer(drawer)
    H.settle(page, 30)


def scenario_season_previews_look_and_programs():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_seasons(page, served)
            passes = []
            for pass_index in range(2):
                counts = []
                for _label, name, _presence, _autumn in SEASONS:
                    for clock_name, iso in TIMES:
                        pin(page, iso)
                        choose_season(page, name)
                        if pass_index == 0:
                            screenshot(page, f'season_{name}_{clock_name}.png')
                        count = page.evaluate('window.__twin.renderer3.info.programs.length')
                        counts.append((name, clock_name, count))
                        if pass_index:
                            check(count == passes[0][-1][2], ('no new programs after full first pass', name, clock_name, count, passes))
                passes.append(counts)
                print(f'SEASON_PROGRAMS pass={pass_index + 1} {json.dumps(counts)}')
            # Now is a person action too: it must clear the independent season timer.
            drawer = preview_drawer(page)
            drawer.get_by_role('button', name='Now', exact=True).click()
            page.wait_for_function("""() => window.__twin.season.preview===null &&
              window.__twin.seasonPreviewDeadline()===null && window.__twin.state.time==='now'""", timeout=TIMEOUT)
            check(drawer.locator('[data-season-preview][aria-pressed="true"]').count() == 0, 'Now unpresses seasons')
            close_drawer(drawer)
            L.no_errors(served)


def scenario_warm_lawn_in_winter():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_seasons(page, served)
            pin(page, '2026-01-15T12:00:00Z')
            before = page.evaluate('window.__twin.seasons.uniforms.seasonDormancy.value')
            body = ground_route(served, grass='warm')
            check(body['lawn']['grass_type'] == 'warm', ('editor settings route saves warm grass', body))
            weather(temperature=-3)
            seed_cold_history()
            body = ground_route(served)
            from services import storage, twin_weather_state as ground
            record = storage.get_app_state(ground.KEY)
            check(record['lawn_target'] == 1, ('cold history targets warm-lawn dormancy', record))
            check(body['lawn']['source'] == 'history' and body['lawn']['grass_type'] == 'warm' and
                  body['season']['avg_temp_c'] == -3 and body['season']['history_days'] == 10, body)
            check(before < body['lawn']['dormancy'] < 1, ('gradual dormancy rises after ten cold days', before, body))
            wait_weather(page, temperature=-3)
            page.wait_for_function("""before => {
              const v=window.__twin,s=v.season,u=v.seasons.uniforms.seasonDormancy.value;
              return s.preview===null && s.grassType==='warm' && s.source==='history' &&
                s.historyDays===10 && s.avgTempC===-3 && s.presence===0 &&
                u===s.dormancy && u>before+.4 && u<1;
            }""", arg=before, timeout=TIMEOUT)
            screenshot(page, 'season_warm_lawn_winter.png')
            L.no_errors(served)


PARTICLES_JS = r"""kind => {
  const v=window.__twin,o=v.seasonTouches.objects[kind],g=o.geometry,a=g.attributes;
  let visible=0;const positions=[],shapes=[];
  for(let i=0;i<g.instanceCount;i++){
    const p=v.camera.position.clone().fromBufferAttribute(a.touchPosition,i);
    positions.push(...p.toArray());shapes.push(...Array.from(a.touchShape.array.slice(i*4,i*4+4)));
    const eye=p.clone().applyMatrix4(v.camera.matrixWorldInverse),q=p.clone().project(v.camera);
    const u=o.material.uniforms,anchor=u.touchAnchor.value;
    if(eye.z<0 && Math.abs(q.x)<1 && Math.abs(q.y)<1 && Math.abs(q.z)<1 &&
      a.touchShape.getZ(i)>.01 && Math.hypot(p.x-anchor.x,p.z-anchor.z)<u.touchExtent.value*.8 &&
      Math.hypot(p.x-u.touchCentre.value.x,p.z-u.touchCentre.value.y)<u.touchRadius.value)visible++;
  }
  return {enabled:o.visible && v.seasonTouches.group.visible,count:g.instanceCount,visible,positions,shapes};
}"""

FIREFLY_PLACEMENT_JS = r"""async () => {
  const url=path=>new URL(window.chfBase+'static/twin/'+path,location.href).href;
  const {buildingFootprint,inPolygon,edgeDistance,groundAt}=await import(url('twin_ground.js'));
  const {grassCovers}=await import(url('yard_grass.js'));
  const v=window.__twin,plan=v.plan,o=v.seasonTouches.objects.fireflies,a=o.geometry.attributes;
  const covers=grassCovers(plan),bad=[],projected=[];
  for(let i=0;i<o.geometry.instanceCount;i++){
    const p=v.camera.position.clone().fromBufferAttribute(a.touchPosition,i),x=p.x/.3048,y=-p.z/.3048;
    const insideBuildings=[];
    for(const b of plan.buildings||[]){
      const angle=(b.rotation||0)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
      const dx=x-(b.position?.[0]||0),dy=y-(b.position?.[1]||0);
      // Project world XZ into every building's rotated local footprint, not its AABB.
      if(inPolygon(buildingFootprint(b),dx*c+dy*s,-dx*s+dy*c))insideBuildings.push(b.id);
    }
    const covered=covers.some(c=>inPolygon(c.polygon,x,y)||c.polygon.some((p,j)=>
      edgeDistance([x,y],p,c.polygon[(j+1)%c.polygon.length])<(c.margin||0)));
    const height=p.y-groundAt(plan,x,y)*.3048;
    if(!inPolygon(plan.site.lot,x,y)||insideBuildings.length||covered||height<.299||height>1.501)
      bad.push({i,world:p.toArray(),insideBuildings,covered,height});
    projected.push({i,world:p.toArray(),ndc:p.clone().project(v.camera).toArray(),height});
  }
  return {count:o.geometry.instanceCount,buildings:(plan.buildings||[]).length,bad,projected};
}"""


def assert_moving_particles(page, kind):
    page.wait_for_function('kind => { const o=window.__twin?.seasonTouches.objects[kind]; return o?.visible && o.geometry.instanceCount>0; }',
                           arg=kind, timeout=TIMEOUT)
    before = page.evaluate(PARTICLES_JS, kind)
    page.wait_for_timeout(700)
    after = page.evaluate(PARTICLES_JS, kind)
    check(before['enabled'] and before['visible'] > 0 and after['visible'] > 0,
          ('particles project into the visible frame with nonzero alpha', kind, before['visible'], after['visible']))
    check(before['count'] == after['count'] and any(abs(a - b) > .0001 for a, b in zip(before['positions'], after['positions'])),
          ('particle positions really move', kind, before['count'], after['count']))
    return after


def scenario_autumn_leaves_and_fireflies():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_seasons(page, served)
            pin(page, NOON)
            weather(wind=8)
            wait_weather(page, wind=8)
            choose_season(page, 'autumn')
            assert_moving_particles(page, 'leaves')
            screenshot(page, 'season_autumn_leaves.png')
            weather(temperature=20, wind=0)
            wait_weather(page)
            pin(page, NIGHT)
            choose_season(page, 'summer')
            assert_moving_particles(page, 'fireflies')
            for _ in range(2):
                placement = page.evaluate(FIREFLY_PLACEMENT_JS)
                check(placement['count'] > 0 and placement['buildings'] > 0 and not placement['bad'],
                      ('every moving firefly is over lawn, outside every building, .3-1.5m high', placement))
                page.wait_for_timeout(700)
            screenshot(page, 'season_fireflies.png')
            L.no_errors(served)


FACE_SUN_JS = """facing => {
  const v=window.__twin,sun=v.scene.getObjectByName('real-sun');
  if(!sun)throw new Error('real-sun missing');
  const d=sun.position.clone().sub(sun.target.position).normalize(),c=v.controls.target.clone();
  const distance=Math.max(30,v.camera.position.distanceTo(c)),flat=d.clone();flat.y=0;flat.normalize();
  const p=c.clone().addScaledVector(flat,facing?-distance:distance);p.y=c.y+distance*.08;
  v.setCameraState({position:p.toArray(),target:c.toArray()});
  const point=v.camera.position.clone().addScaledVector(d,10000).project(v.camera);
  return {altitude:Math.asin(d.y)*180/Math.PI,uv:[point.x*.5+.5,point.y*.5+.5]};
}"""


def face_sun(page, facing=True):
    result = page.evaluate(FACE_SUN_JS, facing)
    H.settle(page, 30)
    check(2 <= result['altitude'] <= 6, ('fixture pins sun at about four degrees', result))
    return result


def sun_patch(page, uv):
    """Displayed brightness near the sun, using a real screenshot (no GL readback)."""
    from PIL import Image, ImageStat
    box = page.locator('#twin-canvas canvas').bounding_box()
    check(box is not None, 'viewer canvas has screen bounds')
    x = box['x'] + box['width'] * uv[0]
    y = box['y'] + box['height'] * (1 - uv[1])
    radius = min(box['width'], box['height']) * .06
    clip = {'x': max(box['x'], x-radius), 'y': max(box['y'], y-radius),
            'width': min(radius*2, box['x']+box['width']-max(box['x'], x-radius)),
            'height': min(radius*2, box['y']+box['height']-max(box['y'], y-radius))}
    rgb = ImageStat.Stat(Image.open(io.BytesIO(page.screenshot(clip=clip))).convert('RGB')).mean
    return .2126*rgb[0] + .7152*rgb[1] + .0722*rgb[2]


def scenario_light_shafts_at_sunrise():
    with fixture() as served:
        if served is None:
            return
        for tier in ('high', 'low'):
            with served.browser(launch_args=L.GPU_ARGS) as page:
                open_seasons(page, served, tier=tier)
                pin(page, SUNRISE)
                projection = face_sun(page)
                if tier == 'low':
                    check(page.evaluate('window.__twin.post===null || !window.__twin.post.shafts'), 'low tier has no shaft pass')
                else:
                    page.wait_for_function("""() => { const p=window.__twin.post,s=p?.shafts;
                      return p.info().passes.includes('LightShaftPass') && s?.ready && !s.error &&
                        s.strength>0 && s.needsSwap && s.uniforms.strength.value>0; }""", timeout=TIMEOUT)
                    check(all(.1 < value < .9 for value in projection['uv']), ('sun projects well inside frame', projection))
                    on = sun_patch(page, projection['uv'])
                    screenshot(page, 'season_shafts.png')
                    # No test-only shaft toggle exists: use the prescribed camera
                    # fallback. This checks the combined sun/shaft look, not isolated gain.
                    face_sun(page, False)
                    page.wait_for_function('() => window.__twin.post.shafts.strength===0 && !window.__twin.post.shafts.needsSwap', timeout=TIMEOUT)
                    behind = sun_patch(page, projection['uv'])
                    check(on > behind + .5, ('sun-facing patch is brighter than sun-behind patch', on, behind, projection))
                    print(f'SEASON_SHAFTS sun_on={on:.3f} sun_behind={behind:.3f} uv={projection["uv"]}')
                L.no_errors(served)


CENSUS_JS = r"""() => {
  const v=window.__twin,r=v.renderer3,gl=r.getContext(),owners=new Map();
  const samplerTypes=new Set(['SAMPLER_2D','SAMPLER_CUBE','SAMPLER_3D','SAMPLER_2D_SHADOW',
    'SAMPLER_2D_ARRAY','SAMPLER_2D_ARRAY_SHADOW','SAMPLER_CUBE_SHADOW','INT_SAMPLER_2D',
    'INT_SAMPLER_3D','INT_SAMPLER_CUBE','INT_SAMPLER_2D_ARRAY','UNSIGNED_INT_SAMPLER_2D',
    'UNSIGNED_INT_SAMPLER_3D','UNSIGNED_INT_SAMPLER_CUBE','UNSIGNED_INT_SAMPLER_2D_ARRAY']
    .map(k=>gl[k]).filter(k=>typeof k==='number'));
  const category=(o,m)=>m.userData.seasonFoliage && o.geometry?.getAttribute('seasonLeaf') &&
    (m.name==='leaves'||m.name.startsWith('plant card:')) ? (m.name.startsWith('plant card:')?'card':'leaf') :
    m.userData.seasonLawn && (m.name==='lawn'||m.userData.materialRole==='lawn')?'lawn':
    m.userData.seasonLawn && (m.name==='yard blades'||m.name==='edge grass')?'grass':'other';
  const note=(m,owner)=>{
    const props=r.properties.get(m),programs=new Set([
      ...(props.programs?.values()||[]),...(props.programVariants?.values()||[])]);
    for(const p of programs){
      if(!owners.has(p.id))owners.set(p.id,[]);
      owners.get(p.id).push({...owner,material:m.name,type:m.type});
    }
  };
  v.scene.traverse(o=>{
    const materials=[].concat(o.material||[]),categories=materials.map(m=>category(o,m));
    materials.forEach((m,i)=>note(m,{object:o.name,category:categories[i]}));
    for(const m of [o.customDepthMaterial,o.customDistanceMaterial])if(m)
      note(m,{object:o.name,category:categories.every(c=>c==='leaf'||c==='card')?'foliage-shadow':'other'});
  });
  return r.info.programs.map(p=>{
    const source=gl.getShaderSource(p.fragmentShader);
    if(!source)throw new Error('Missing fragment source for '+p.id);
    const count=gl.getProgramParameter(p.program,gl.ACTIVE_UNIFORMS),samplerUniforms=[];
    let samplers=0,slots=0;
    for(let i=0;i<count;i++){
      const u=gl.getActiveUniform(p.program,i);
      if(!u)throw new Error('Missing active uniform '+i+' in '+p.id);
      slots+=u.size;
      if(samplerTypes.has(u.type)){samplers+=u.size;samplerUniforms.push([u.name,u.size]);}
    }
    const season=/uniform\s+(?:float\s+seasonDormancy|vec3\s+seasonFoliage)\b/.test(source);
    return {id:p.id,name:p.name,type:p.type,linked:gl.getProgramParameter(p.program,gl.LINK_STATUS),
      samplers,samplerUniforms,activeUniforms:count,uniformSlots:slots,season,owners:owners.get(p.id)||[]};
  });
}"""


def scenario_census_in_chromium():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_seasons(page, served)
            pin(page, NOON)
            for name in ('winter', 'autumn'):
                choose_season(page, name)
            rows = page.evaluate(CENSUS_JS)
            check(rows and all(row['linked'] for row in rows), ('every GPU program links', rows))
            for row in sorted(rows, key=lambda row: (row['samplers'], row['uniformSlots']), reverse=True)[:8]:
                print('SEASON_CENSUS_TOP ' + json.dumps(row, sort_keys=True))
            check(all(row['samplers'] <= 16 for row in rows), ('no program exceeds 16 samplers, including arrays', rows))
            seasonal = [row for row in rows if row['season']]
            check(seasonal, 'actual fragment programs contain season uniforms')
            allowed = {'leaf', 'card', 'lawn', 'grass', 'foliage-shadow'}
            check(all(row['owners'] and all(owner['category'] in allowed for owner in row['owners']) for row in seasonal),
                  ('season uniforms belong only to vegetation and its depth/distance variants', seasonal))
            categories = {owner['category'] for row in seasonal for owner in row['owners']}
            check({'leaf', 'lawn', 'grass'} <= categories, ('census really exercises high vegetation', categories))
            print(f'SEASON_CENSUS programs={len(rows)} season={len(seasonal)} categories={sorted(categories)}')
            L.no_errors(served)


FRAME_MS_JS = """() => new Promise(done => {
  const times=[];let last;
  const step=now=>{
    if(last!==undefined)times.push(now-last);
    last=now;
    if(times.length<90)requestAnimationFrame(step);
    else {times.sort((a,b)=>a-b);done((times[44]+times[45])/2);}
  };
  requestAnimationFrame(step);
})"""


def scenario_touches_cost():
    with fixture() as served:
        if served is None:
            return
        args = [*L.GPU_ARGS, '--disable-gpu-vsync', '--disable-frame-rate-limit']
        with served.browser(launch_args=args, device_scale_factor=1) as page:
            open_seasons(page, served, size=(1920, 1080))
            check(page.evaluate("""() => { const c=window.__twin.renderer3.domElement;
              return c.width===1920 && c.height===1080; }"""), 'cost uses a 1920x1080 drawing buffer')
            # Warm all three looks before measuring; keep one camera for the samples.
            pin(page, GOLDEN)
            face_sun(page)
            choose_season(page, 'autumn')
            page.wait_for_timeout(5000)
            pin(page, NOON)
            choose_season(page, 'summer')
            page.wait_for_timeout(5000)
            check(page.evaluate("""() => { const v=window.__twin;return !v.seasonTouches.objects.leaves.visible &&
              !v.seasonTouches.objects.fireflies.visible && v.post.shafts.strength===0; }"""), 'Summer noon has no nature touches')
            summer = page.evaluate(FRAME_MS_JS)
            choose_season(page, 'autumn')
            assert_moving_particles(page, 'leaves')
            page.wait_for_timeout(5000)
            autumn = page.evaluate(FRAME_MS_JS)
            choose_season(page, 'summer')
            pin(page, GOLDEN)
            page.wait_for_function('() => window.__twin.post.shafts.strength>0 && window.__twin.post.shafts.needsSwap', timeout=TIMEOUT)
            page.wait_for_timeout(5000)
            shafts = page.evaluate(FRAME_MS_JS)
            check(all(value > 0 for value in (summer, autumn, shafts)), ('positive 90-frame medians', summer, autumn, shafts))
            print(f'SEASON_COST summer_noon={summer:.2f} autumn_leaves={autumn:.2f} golden_shafts={shafts:.2f} '
                  f'leaves_delta={autumn-summer:.2f} shafts_delta={shafts-summer:.2f} frames=90 size=1920x1080 tier=high')
            # These are total frame costs across looks, not isolated GPU pass timings.
            L.no_errors(served)


CARDS_JS = """() => {
  const v=window.__twin,presence=v.seasons.uniforms.seasonFoliage.value.x,rows=[];
  v.scene.traverse(o=>{
    if(!o.geometry)return;
    const a=o.geometry.getAttribute('seasonLeaf');
    if(!a)return;
    const materials=[].concat(o.material||[]);
    if(!materials.some(m=>m.userData.seasonFoliage && m.name.startsWith('plant card:')))return;
    let surviving=0;for(let i=0;i<a.count;i++)if(a.getX(i)<presence)surviving++;
    rows.push({uuid:o.uuid,vertices:a.count,surviving});
  });
  return {presence,rows,total:rows.reduce((n,r)=>n+r.surviving,0)};
}"""


def scenario_low_tier_seasons():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_seasons(page, served, tier='low', size=(1920, 1080))
            pin(page, NOON)
            choose_season(page, 'autumn')
            autumn = page.evaluate(CARDS_JS)
            check(autumn['rows'] and autumn['total'] > 0, ('low tier actually has deciduous cards', autumn))
            choose_season(page, 'winter')
            winter = page.evaluate(CARDS_JS)
            check(winter['presence'] == 0 and winter['total'] == 0 and winter['total'] < autumn['total'],
                  ('winter thins the actual cards using their baked alpha thresholds', autumn, winter))
            check([(r['uuid'], r['vertices']) for r in winter['rows']] == [(r['uuid'], r['vertices']) for r in autumn['rows']],
                  'season changes retain card geometry')
            screenshot(page, 'season_low_winter.png')
            choose_season(page, 'autumn')
            restored = page.evaluate(CARDS_JS)
            check(restored == autumn, ('Autumn restores the same cards', autumn, restored))
            screenshot(page, 'season_low_autumn.png')
            L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_season_previews_look_and_programs, scenario_warm_lawn_in_winter,
           scenario_autumn_leaves_and_fireflies, scenario_light_shafts_at_sunrise,
           scenario_census_in_chromium, scenario_touches_cost, scenario_low_tier_seasons])
