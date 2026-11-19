"""Owner weather acceptance checks in Chromium. WRITTEN, NOT RUN by Codex.

From chauffeur/: python tests/test_twin_weather_owner_live.py [OUT_DIR]
Claude owns browser execution and screenshot review. Importing this module never
opens a browser. Camera/clock placement and external HA/house fixture setup are
the only synthetic inputs; every preview and navigation choice uses real clicks.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch

# Must precede ALL harness/service imports. Never use the household's data dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_owner_weather_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_twin_live_harness as L

H, check = L.H, L.check
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
TIMEOUT, RAMP_TIMEOUT = 40000, 140000
NOON = '2026-06-21T12:00:00Z'
FURNITURE = ('owner-sofa', 'owner-rug')


@contextmanager
def fixture(*, furniture=False):
    served = L.serve()
    if served is None:
        yield None
        return
    L.reset()
    from services import ha_api, storage, twin_store, twin_weather_state as ground
    storage.patch_settings({'home_location': 'Owner weather fixture', 'timezone': 'Etc/UTC',
                            'weather_entity': 'weather.home', 'lawn_grass_type': 'cool',
                            **{key: '' for key in ground.SENSOR_SETTINGS.values()}})
    storage.set_cached_geocode('Owner weather fixture', 40, 0)
    twin_store.set_front_bearing(180)
    if furniture:
        seed_furniture()
    with patch.object(ha_api, 'states_unreachable', return_value=False), \
            patch.object(ha_api, 'get_weather_forecast', return_value=[]):
        weather()
        yield served


def seed_furniture():
    """Two imported box receivers in the real lounge, through the real loader.

    The checked-in household has no indoor items. These are fixture geometry,
    not a test-only product hook or an intercepted asset request.
    """
    from services import twin_imports, twin_store
    corners = [(-1, 0, -.5), (1, 0, -.5), (1, .8, -.5), (-1, .8, -.5),
               (-1, 0, .5), (1, 0, .5), (1, .8, .5), (-1, .8, .5)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (3, 7, 6), (3, 6, 2), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    vertices = [v for face in faces for i in face for v in corners[i]]
    binary = struct.pack('<' + 'f' * len(vertices), *vertices)
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
           'buffers': [{'uri': 'mesh.bin', 'byteLength': len(binary)}],
           'bufferViews': [{'buffer': 0, 'byteLength': len(binary)}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 36, 'type': 'VEC3',
                          'min': [-1, 0, -.5], 'max': [1, .8, .5]}]}
    asset = twin_imports.create({'model.gltf': json.dumps(doc).encode(), 'mesh.bin': binary},
                                'Owner weather indoor receivers', 'furniture')['id']

    def place(model):
        b = H.building(model, L.POOL)
        b.setdefault('items', []).extend([
            {'id': FURNITURE[0], 'asset': asset, 'host': {'floor': L.KITCHEN, 'u': .45, 'v': .45}},
            {'id': FURNITURE[1], 'asset': asset, 'host': {'floor': L.KITCHEN, 'u': .6, 'v': .45},
             'scale_axes': [1, .02, 1]}])
        return model
    twin_store.update_model(place, 'edit', note='owner weather test fixture furniture')


def weather(condition='sunny', *, wind=0, visibility=None, snow_cm=0):
    """An external HA observation and isolated persisted ground state, as in siblings.

    Missing temperature holds the seeded 8 cm steady instead of melting it.
    Rain previews start dry and use their unmodified real 90-second ramp.
    """
    from services import storage, twin_weather_state as ground
    with ground._lock:
        attrs = {'friendly_name': 'Home', 'cloud_coverage': 0 if condition == 'sunny' else 100,
                 'temperature': None, 'temperature_unit': 'C', 'humidity': 50,
                 'wind_speed': wind, 'wind_speed_unit': 'm/s', 'wind_bearing': 270, 'forecast': []}
        if visibility is not None:
            attrs['visibility'] = visibility  # HA's weather attribute is kilometres.
        L.FAKE.states['weather.home'] = {'entity_id': 'weather.home', 'state': condition, 'attributes': attrs}
        now = time.time()
        forcing, _source, usable = ground.observation(list(L.FAKE.states.values()), storage.get_settings(), now)
        check(usable, ('fake weather is usable', condition))
        storage.set_app_state(ground.KEY, {'snow_cm': float(snow_cm), 'wetness': 0.,
                                         'updated': now, 'last_rain': None, 'forcing': forcing})


POLL_JS = """(() => { const timer=window.setTimeout.bind(window);
  window.setTimeout=(fn,ms,...args)=>timer(fn,ms===300000?1000:ms,...args); })();"""


def open_owner(page, served, *, size=(1600, 900)):
    page.set_default_timeout(TIMEOUT)
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    # Only accelerate the five-minute ground poll; ramp, leaves and previews use
    # real time. live=False matches both existing environment browser suites.
    page.add_init_script(POLL_JS)
    L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true', live=False)
    wait_live_weather(page, 'sunny')
    check(page.evaluate('window.__twin.tier') == 'high', 'owner checks use high tier')
    pin(page, NOON)
    choose_preview(page, 'Summer', 'summer', season=True)


def wait_live_weather(page, condition, *, wind=0, snow_cm=0, visibility=None):
    page.wait_for_function("""want => {
      const w=window.__twin?.weather;
      return w && !w.neutral && w.preview===null && w.condition===want.condition &&
        Math.abs(w.windMps-want.wind)<1e-6 && Math.abs(w.snow_cm-want.snow)<1e-6 &&
        (want.visibility===null || Math.abs(w.visibilityM-want.visibility*1000)<1e-6);
    }""", arg={'condition': condition, 'wind': wind, 'snow': snow_cm, 'visibility': visibility}, timeout=TIMEOUT)
    H.settle(page, 10)


def pin(page, iso):
    page.evaluate('(iso) => window.__twin.setClock(iso)', iso)
    H.settle(page, 30)
    page.wait_for_timeout(800)


def choose_preview(page, label, name, *, season=False):
    page.get_by_role('button', name='House time preview', exact=True).click()
    drawer = page.get_by_role('dialog', name='House settings', exact=True)
    drawer.wait_for(state='visible', timeout=TIMEOUT)
    before = page.evaluate('Date.now()')
    button = drawer.get_by_role('button', name=label, exact=True)
    button.click()
    page.wait_for_function("""({name,season}) => {
      const v=window.__twin;return (season?v.season:v.weather).preview===name;
    }""", arg={'name': name, 'season': season}, timeout=TIMEOUT)
    after = page.evaluate('Date.now()')
    deadline = page.evaluate('season => { const v=window.__twin; return season?v.seasonPreviewDeadline():v.weatherPreviewDeadline(); }', season)
    check(before + 120000 <= deadline <= after + 120000, ('real 120-second preview', name, deadline))
    check(button.get_attribute('aria-pressed') == 'true', ('pressed preview button', label))
    drawer.get_by_role('button', name='Close settings', exact=True).click()
    drawer.wait_for(state='hidden', timeout=TIMEOUT)
    # Return the actual click origin, not a timestamp after drawer/settle delays.
    return deadline - 120000


def now(page):
    page.get_by_role('button', name='House time preview', exact=True).click()
    drawer = page.get_by_role('dialog', name='House settings', exact=True)
    drawer.get_by_role('button', name='Now', exact=True).click()
    page.wait_for_function('() => window.__twin.weather.preview===null && window.__twin.season.preview===null', timeout=TIMEOUT)
    drawer.get_by_role('button', name='Close settings', exact=True).click()
    drawer.wait_for(state='hidden', timeout=TIMEOUT)


CAMERA_JS = r"""async kind => {
  const {buildingFootprint,buildingBase,groundAt}=await import(new URL(window.chfBase+'static/twin/twin_ground.js',location.href));
  const v=window.__twin,p=v.plan,ft=.3048,b=p.buildings.find(b=>b.id==='pool-house');
  if(!b || !p.site.pool?.polygon?.length)throw new Error('real household pool house and pool required');
  const world=(b,[x,y])=>{const a=(b.rotation||0)*Math.PI/180;
    return [(b.position?.[0]||0)+x*Math.cos(a)-y*Math.sin(a),(b.position?.[1]||0)+x*Math.sin(a)+y*Math.cos(a)];};
  const bounds=points=>{const lo=[0,1].map(i=>Math.min(...points.map(q=>q[i]))),hi=[0,1].map(i=>Math.max(...points.map(q=>q[i])));
    return {lo,hi,centre:lo.map((x,i)=>(x+hi[i])/2)};};
  const house=bounds(buildingFootprint(b).map(q=>world(b,q))),pool=bounds(p.site.pool.polygon);
  const all=bounds([...p.buildings.flatMap(b=>buildingFootprint(b).map(q=>world(b,q))),...p.site.pool.polygon]);
  let position,target,eyeGround=null,facadeDistance=null;
  if(kind==='eye'){
    const d=pool.centre.map((x,i)=>x-house.centre[i]),length=Math.hypot(...d);d.forEach((x,i)=>d[i]=x/length);
    // Ray from the pool-house bounds' centre toward the pool: stop at its near
    // facade, then continue 12.5 m. The pool is between eye and pool house.
    const edge=Math.min(...d.map((x,i)=>Math.abs(x)>1e-9?(house.hi[i]-house.lo[i])/2/Math.abs(x):Infinity));
    const eye=house.centre.map((x,i)=>x+d[i]*(edge+12.5/ft));
    eyeGround=groundAt(p,...eye)*ft;
    position=[eye[0]*ft,eyeGround+1.6,-eye[1]*ft];
    target=[house.centre[0]*ft,eyeGround,-house.centre[1]*ft];
  }else if(kind==='floor'){
    const l=b.levels.find(l=>l.id==='L1'),box=bounds(l.outline.map(q=>world(b,q))),c=box.centre;
    const h=(buildingBase(p,b)+l.elevation)*ft,span=Math.max(...box.hi.map((x,i)=>(x-box.lo[i])*ft));
    target=[c[0]*ft,h,-c[1]*ft];position=[target[0],h+span*1.8,target[2]+.0001];
  }else{
    const points=kind==='yard'?[...p.site.lot,...(p.site.planting||[]).map(q=>q.at).filter(Boolean)]:null;
    const box=points?.length?bounds(points):all,c=box.centre,span=Math.max(...box.hi.map((x,i)=>(x-box.lo[i])*ft));
    const h=groundAt(p,...c)*ft;target=[c[0]*ft,h,-c[1]*ft];
    position=kind==='yard'?[target[0],h+span*1.1,target[2]+.0001]:[target[0]+span*.65,h+span*.65,target[2]+span*.8];
  }
  // Test camera setup: the overview's fitted orbit bounds otherwise clamp an
  // exact owner eye pose. Navigation still comes exclusively from real clicks.
  v.cancelCameraMotion?.();v.controls.minDistance=0;v.controls.maxDistance=Infinity;
  v.controls.minPolarAngle=0;v.controls.maxPolarAngle=Math.PI/2;
  v.setCameraState({position,target});
  if(kind==='eye'){
    const eye=[v.camera.position.x/ft,-v.camera.position.z/ft];
    facadeDistance=Math.hypot(...eye.map((x,i)=>Math.max(house.lo[i]-x,0,x-house.hi[i])))*ft;
  }
  return {position,target,eyeGround,facadeDistance,actual:v.camera.position.toArray(),level:v.levels.snapshot()};
}"""


def camera(page, kind):
    result = page.evaluate(CAMERA_JS, kind)
    H.settle(page, 30)
    actual = page.evaluate('window.__twin.camera.position.toArray()')
    check(all(abs(a-b) < .01 for a, b in zip(actual, result['position'])), ('camera retains owner pose', kind, result, actual))
    if kind == 'eye':
        check(abs(actual[1] - result['eyeGround'] - 1.6) < .01 and 10 <= result['facadeDistance'] <= 15,
              ('1.6 m eye, 10-15 m from pool-house facade', result))
    return result


def screenshot(page, name):
    if OUT:
        OUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT / name), timeout=TIMEOUT)


PACKED_JS = """() => { const v=window.__twin;return {preview:v.weather.preview,
  packed:v.weatherSurface.uniforms.weatherSurface.value.toArray(),programs:v.renderer3.info.programs.map(p=>p.id)}; }"""

WATER_JS = r"""() => {
  const v=window.__twin,r=v.renderer3,gl=r.getContext(),rows=[];
  v.scene.traverse(o=>{if(!o.isMesh || o.userData.part!=='water')return;
    for(const m of [].concat(o.material||[])){
      const props=r.properties.get(m),program=props.currentProgram;
      const location=program&&gl.getUniformLocation(program.program,'weatherSurface');
      const packed=location===null||location===undefined?null:Array.from(gl.getUniform(program.program,location));
      rows.push({piece:o.userData.pieceId,material:m.name,water:!!(m.userData.waterSurface||m.userData.litWater),packed});
    }});return rows;
}"""


def scenario_rain_build_up_at_the_pool():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_owner(page, served)
            page.set_default_timeout(RAMP_TIMEOUT)
            camera(page, 'eye')
            # Two real UI passes warm precipitation, water and reflection programs.
            for _ in range(2):
                for label, name in (('Rain', 'rain'), ('Pouring', 'pouring'), ('Clear', 'clear')):
                    choose_preview(page, label, name)
                    H.settle(page, 60)
                    page.wait_for_timeout(1500)
            warmed = set(page.evaluate(PACKED_JS)['programs'])
            started = choose_preview(page, 'Rain', 'rain')
            samples = []
            for seconds in (0, 30, 60, 90):
                page.wait_for_function('stamp => Date.now()>=stamp', arg=started+seconds*1000, timeout=RAMP_TIMEOUT)
                row = page.evaluate(PACKED_JS)
                elapsed = (page.evaluate('Date.now()')-started)/1000
                check(row['preview'] == 'rain' and seconds <= elapsed < seconds+8, ('real ramp checkpoint', seconds, elapsed, row))
                check(abs(row['packed'][0]-min(1, elapsed/90)) < .035, ('packed wetness follows the ramp', elapsed, row))
                check(set(row['programs']) <= warmed, ('no new program after warm-up', seconds, row))
                samples.append(row['packed'][0])
                screenshot(page, f'owner_rain_{seconds}.png')
            check(samples[0] < .1 and samples[-1] > .98 and all(a < b for a, b in zip(samples, samples[1:])),
                  ('packed wetness rises from dry to wet', samples))
            choose_preview(page, 'Pouring', 'pouring')
            H.settle(page, 30)
            water = page.evaluate(WATER_JS)
            check(water and all(r['water'] and r['packed'] and int(r['packed'][3]) == 255 for r in water),
                  ('rendered pool water receives nonzero pouring rain/ring state', water))
            check(set(page.evaluate(PACKED_JS)['programs']) <= warmed, 'Pouring adds no program after warm-up')
            screenshot(page, 'owner_pouring_pool.png')
            print('OWNER_RAIN_BUILD_UP ' + json.dumps(samples))
            L.no_errors(served)


INDOOR_JS = r"""async () => {
  const {inPolygon}=await import(new URL(window.chfBase+'static/twin/twin_ground.js',location.href));
  const v=window.__twin,b=v.plan.buildings.find(b=>b.id==='pool-house'),angle=(b.rotation||0)*Math.PI/180;
  const rooms=b.rooms.filter(r=>r.level==='L1'&&r.kind!=='porch'&&r.state!=='ghost');
  const rows=[],bad=[];v.scene.updateMatrixWorld(true);
  const visible=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;};
  v.scene.traverse(o=>{
    if(!o.isMesh || !visible(o) || o.layers.isEnabled(31) || !o.geometry?.attributes.position)return;
    const a=o.geometry.attributes,pos=a.position;
    for(const range of o.userData.snapRanges||[{start:0,count:pos.count,...o.userData}]){
      const furniture=['owner-sofa','owner-rug'].includes(range.pieceId);
      if(range.buildingId!=='pool-house'||!(furniture||['floor','room'].includes(range.kind)&&range.part!=='ceiling'))continue;
      let count=0,min=Infinity,max=-Infinity;
      for(let i=range.start;i<range.start+range.count;i++){
        const p=v.camera.position.clone().fromBufferAttribute(pos,i).applyMatrix4(o.matrixWorld);
        const dx=p.x/.3048-b.position[0],dy=-p.z/.3048-b.position[1];
        const x=dx*Math.cos(angle)+dy*Math.sin(angle),y=-dx*Math.sin(angle)+dy*Math.cos(angle);
        if(!furniture&&!rooms.some(r=>inPolygon(r.polygon,x,y)))continue;
        const value=a.weatherOpen?.getX(a.weatherOpen.isInstancedBufferAttribute?0:i);
        count++;min=Math.min(min,value);max=Math.max(max,value);
        if(value!==0&&bad.length<12)bad.push({piece:range.pieceId,i,value,world:p.toArray()});
      }
      if(count)rows.push({piece:range.pieceId,kind:range.kind,part:range.part,count,min,max});
    }
  });return {rows,bad};
}"""


def assert_floor(page):
    page.wait_for_function("""() => {const v=window.__twin,p=v.precipitation;
      return v.levels.snapshot().level==='floor' && Object.values(p.objects).every(o=>!o.visible&&o.geometry.instanceCount===0);
    }""", timeout=TIMEOUT)
    result = page.evaluate(INDOOR_JS)
    check(result['rows'] and not result['bad'] and all(r['min'] == r['max'] == 0 for r in result['rows']),
          ('rendered indoor floor/furniture weatherOpen values are zero', result))
    check(any(r['kind'] == 'room' for r in result['rows']) and
          all(any(r['piece'] == piece for r in result['rows']) for piece in FURNITURE),
          ('floor and both imported furniture buffers actually exercised', result))


def scenario_floor_view_has_no_weather_indoors():
    with fixture(furniture=True) as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_owner(page, served)
            page.locator(f'[data-level-building="{L.POOL}"]:not([data-level-floor])').click()
            page.locator(f'[data-level-building="{L.POOL}"][data-level-floor="L1"]').click()
            page.wait_for_function("() => window.__twin.levels.snapshot().level==='floor' && window.__twin.state.view==='pool-house:L1'", timeout=TIMEOUT)
            H.settle(page, 30)
            camera(page, 'floor')
            choose_preview(page, 'Pouring', 'pouring')
            assert_floor(page)
            screenshot(page, 'owner_floor_rain.png')
            weather('snowy', snow_cm=8)
            now(page)
            wait_live_weather(page, 'snowy', snow_cm=8)
            pin(page, NOON)
            choose_preview(page, 'Snow', 'snow')
            page.wait_for_function('() => window.__twin.weather.snow_cm===8 && window.__twin.weatherSurface.uniforms.weatherSurface.value.y===1', timeout=TIMEOUT)
            assert_floor(page)
            screenshot(page, 'owner_floor_snow.png')
            L.no_errors(served)


FOG_JS = r"""() => {
  const v=window.__twin,rows=[],seen=new Set();
  v.scene.traverse(o=>{
    if(!o.isMesh||o.layers.isEnabled(31))return;
    for(let p=o;p;p=p.parent)if(!p.visible)return;
    for(const m of [].concat(o.material||[])){
      if(seen.has(m))continue;seen.add(m);
      // Read the compiled rendered material's shared binding, excluding dormant
      // warm-up variants whose GL uniforms have never been uploaded.
      const props=v.renderer3.properties.get(m),u=props.uniforms;
      if(!props.currentProgram||!u?.stageRing||!u.stageRadius)continue;
      rows.push({material:m.name,k:u.stageRing.value[0].w,radius:u.stageRadius.value});
    }
  });return rows;
}"""


def scenario_fog_from_the_camera():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_owner(page, served)
            camera(page, 'overview')
            clear = page.evaluate(FOG_JS)
            check(clear and all(r['radius'] > 0 and abs(r['k']) < 1e-8 for r in clear), ('clear stage uniform baseline', clear))
            radius = clear[0]['radius']
            weather('fog', visibility=.3)
            wait_live_weather(page, 'fog', visibility=.3)
            for pose, filename in (('overview', 'owner_fog_overview.png'), ('eye', 'owner_fog_eye.png')):
                camera(page, pose)
                rows = page.evaluate(FOG_JS)
                check(rows and all(abs(r['k']-3.912/300) < 1e-6 and abs(r['radius']-radius) < 1e-6 for r in rows),
                      ('rendered stageRing[0].w is camera extinction; radius stays clear', pose, rows, radius))
                screenshot(page, filename)
            L.no_errors(served)


LEAVES_JS = r"""async () => {
  const {buildingFootprint,inPolygon}=await import(new URL(window.chfBase+'static/twin/twin_ground.js',location.href));
  const {createSkyCover}=await import(new URL(window.chfBase+'static/twin/sky/sky_cover.js',location.href));
  const v=window.__twin,p=v.plan,info=v.seasonTouches.info(),cover=createSkyCover(p,v.roofSurfaces),bad=[];
  const water=[p.site.pool.polygon,...(p.site.pool.features||[]).filter(f=>f.kind==='spa').map(f=>f.polygon)];
  for(const leaf of info.resting){
    const [wx,h,wz]=leaf.position,x=wx/.3048,y=-wz/.3048,reasons=[];
    if(water.some(poly=>inPolygon(poly,x,y)))reasons.push('water');
    for(const b of p.buildings){
      const angle=(b.rotation||0)*Math.PI/180,dx=x-b.position[0],dy=y-b.position[1];
      const u=dx*Math.cos(angle)+dy*Math.sin(angle),w=-dx*Math.sin(angle)+dy*Math.cos(angle);
      if(inPolygon(buildingFootprint(b),u,w))reasons.push('footprint:'+b.id);
    }
    // Actual generated triangles also include awnings outside the footprint.
    const roof=cover.roofHeight(wx,h,wz);
    if(Number.isFinite(roof)&&h>=roof-.02)reasons.push('roof');
    if(cover.blocked(wx,h,wz))reasons.push('covered');
    if(!leaf.position.every(Number.isFinite))reasons.push('nonfinite');
    if(reasons.length)bad.push({id:leaf.id,position:leaf.position,reasons});
  }
  return {resting:info.resting.length,falling:info.falling.length,sources:info.sources.length,bad,
    distinct:new Set(info.resting.map(l=>l.position.filter((_,i)=>i!==1).map(x=>x.toFixed(2)).join(','))).size,
    draws:info.batches.filter(b=>b.object.visible&&b.object.geometry.instanceCount>0).length};
}"""


def scenario_autumn_leaves_scatter_and_collect():
    with fixture() as served:
        if served is None:
            return
        with served.browser(launch_args=L.GPU_ARGS) as page:
            open_owner(page, served)
            weather(wind=6)
            wait_live_weather(page, 'sunny', wind=6)
            camera(page, 'overview')
            started = choose_preview(page, 'Autumn', 'autumn', season=True)
            before = page.evaluate(LEAVES_JS)
            page.wait_for_function('stamp => Date.now()>=stamp', arg=started+30000, timeout=TIMEOUT)
            middle = page.evaluate(LEAVES_JS)
            check(not middle['bad'], ('overview leaves avoid excluded receivers', middle))
            camera(page, 'yard')
            page.wait_for_function('stamp => Date.now()>=stamp', arg=started+60000, timeout=TIMEOUT)
            after = page.evaluate(LEAVES_JS)
            check(after['resting'] > before['resting'] and after['resting'] >= middle['resting'] and not after['bad'],
                  ('resting leaves grow over 60 real seconds; none on water, roof or footprint', before, middle, after))
            check(after['draws'] > 0, ('resting/falling leaf batches are rendered', after))
            check(after['distinct'] > 1, ('leaves collect at distinct ground positions', after))
            screenshot(page, 'owner_leaves_top.png')
            camera(page, 'eye')
            eye = page.evaluate(LEAVES_JS)
            check(not eye['bad'], ('eye-level resting leaves remain safe', eye))
            screenshot(page, 'owner_leaves_eye.png')
            print('OWNER_LEAVES ' + json.dumps({'before': before, 'middle': middle, 'after': after}))
            L.no_errors(served)


FRAME_MS_JS = """() => new Promise(done => {
  const times=[];let last;
  const step=now=>{if(last!==undefined)times.push(now-last);last=now;
    if(times.length<90)requestAnimationFrame(step);
    else {times.sort((a,b)=>a-b);done((times[44]+times[45])/2);}};
  requestAnimationFrame(step);
})"""


def scenario_owner_fixes_cost():
    with fixture() as served:
        if served is None:
            return
        args = [*L.GPU_ARGS, '--disable-gpu-vsync', '--disable-frame-rate-limit']
        with served.browser(launch_args=args, device_scale_factor=1) as page:
            open_owner(page, served, size=(1920, 1080))
            camera(page, 'eye')
            check(page.evaluate("""() => {const c=window.__twin.renderer3.domElement;
              return c.width===1920&&c.height===1080;}"""), 'cost drawing buffer is 1920x1080')
            # Warm the rain path before the samples. Leaf slots are allocated by
            # mount's warm-up; emitting leaves here would contaminate the clear
            # baseline because resting cards intentionally persist for 480 s.
            choose_preview(page, 'Pouring', 'pouring')
            H.settle(page, 90)
            now(page)
            pin(page, NOON)
            weather(wind=6)
            wait_live_weather(page, 'sunny', wind=6)
            choose_preview(page, 'Summer', 'summer', season=True)
            page.wait_for_function("""() => {const t=window.__twin.seasonTouches;
              return Object.entries(t.objects).filter(([k])=>k.startsWith('leaves')).every(([,o])=>!o.visible);}
            """, timeout=TIMEOUT)
            page.wait_for_timeout(5000)
            clear = page.evaluate(FRAME_MS_JS)
            choose_preview(page, 'Pouring', 'pouring')
            page.wait_for_timeout(5000)
            pouring = page.evaluate(FRAME_MS_JS)
            now(page)
            wait_live_weather(page, 'sunny', wind=6)
            pin(page, NOON)
            choose_preview(page, 'Autumn', 'autumn', season=True)
            page.wait_for_function('() => window.__twin.seasonTouches.info().falling.length>0', timeout=TIMEOUT)
            page.wait_for_timeout(5000)
            autumn = page.evaluate(FRAME_MS_JS)
            check(all(ms > 0 for ms in (clear, pouring, autumn)), ('positive 90-frame medians', clear, pouring, autumn))
            print(f'OWNER_FIX_COST clear={clear:.2f} pouring_eye={pouring:.2f} autumn_leaves={autumn:.2f} '
                  f'pouring_delta={pouring-clear:.2f} leaves_delta={autumn-clear:.2f} '
                  'frames=90 size=1920x1080 tier=high')
            # Total frame costs across looks, not isolated GPU pass timings.
            L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_rain_build_up_at_the_pool, scenario_floor_view_has_no_weather_indoors,
           scenario_fog_from_the_camera, scenario_autumn_leaves_scatter_and_collect,
           scenario_owner_fixes_cost])
