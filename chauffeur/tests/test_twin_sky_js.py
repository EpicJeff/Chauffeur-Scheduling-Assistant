"""Real mounted twin clock/light flags and editor dial, in node; no Chromium."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const {lookAt, modelDirection, resolveSite, previewDate} = await import(file('static/twin/sky/look.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createPlace} = await import(file('static/twin/editor/place.js'));
const {mountGlanceSettings} = await import(file('static/twin/live/glance_settings.js'));
await test('continuous colour/intensity at all four band edges', () => {
  for (const edge of [-12,-6,0,6]) {
    const a = lookAt(edge - 1e-6, {altitude:.5,fraction:1}), b = lookAt(edge + 1e-6, {altitude:.5,fraction:1});
    for (const key of ['background','ambient','environment','exposure','sunColor','sun','moon']) {
      const aa = [].concat(a[key]), bb = [].concat(b[key]);
      aa.forEach((v,i) => assert.ok(Math.abs(v-bb[i]) < 1e-5, key + ' at ' + edge));
    }
  }
  for (const edge of [-12,-6,0,6]) {
    const a = lookAt(edge - 1e-6, {altitude:.5,fraction:1}, {shadows:true}), b = lookAt(edge + 1e-6, {altitude:.5,fraction:1}, {shadows:true});
    for (const key of ['ambient','environment','sun']) assert.ok(Math.abs(a[key]-b[key]) < 1e-4, 'shadowed ' + key + ' at ' + edge);
  }
  const flat = lookAt(40), lit = lookAt(40, undefined, {shadows:true});
  assert.deepEqual([flat.sun,flat.ambient,flat.environment],[3,1.8,.65],'views without sun shadows keep their fill');
  assert.deepEqual([lit.sun,lit.ambient,lit.environment],[7,.5,.4],'the sun carries the day where it casts shadows');
  assert.deepEqual(lookAt(-20,undefined,{shadows:true}).ambient,lookAt(-20).ambient,'night is the same either way');
  assert.ok(lookAt(-3.01).lamps); assert.ok(!lookAt(-3).lamps);
  assert.equal(lookAt(-20, {altitude:-.1,fraction:1}).moon, 0);
  assert.equal(lookAt(-20, {altitude:1,fraction:0}).moon, 0);
});
await test('front bearing follows the street normal, plan -y / three +z', () => {
  const street = modelDirection(Math.PI, 0, 180);
  street.forEach((v,i) => assert.ok(Math.abs(v-[0,0,1][i]) < 1e-12));
  // Street south: north is plan +y / three -z, east is plan +x / three +x.
  const east = modelDirection(Math.PI/2, 0, 180);
  east.forEach((v,i) => assert.ok(Math.abs(v-[1,0,0][i]) < 1e-12));
  const a = modelDirection(Math.PI, Math.PI/4, 180);
  const b = modelDirection(Math.PI/2, Math.PI/4, 90);
  assert.deepEqual(a,b);
  const back = modelDirection(0,Math.PI/4,180);
  assert.ok(a[0]*back[0] + a[2]*back[2] < 0);
});
await test('default longitude and previews use the site clock and DST', () => {
  const date = new Date('2026-06-21T17:00:00Z');
  const fallback = resolveSite({source:'default',lat:40,lon:null},date);
  assert.equal(fallback.lon,-date.getTimezoneOffset()/60*15);
  const site = {lat:40,lon:-75,timezone:'America/New_York'};
  assert.equal(previewDate(date,'day',site).toISOString(),'2026-06-21T16:00:00.000Z');
  assert.equal(previewDate(date,'night',site).toISOString(),'2026-06-22T03:00:00.000Z');
  assert.equal(previewDate(date,'now',site).toISOString(),date.toISOString());
  assert.equal(previewDate(date,'day',{lon:-75}).toISOString(),'2026-06-21T17:00:00.000Z');
});
let view, minuteTick;
await test('mounted view keeps every light/environment flag at noon dusk midnight', async () => {
  const oldInterval = globalThis.setInterval;
  globalThis.setInterval = (fn,ms) => { if(ms===60000) minuteTick=fn; return oldInterval(fn,ms); };
  try {
  view = await mountTwin(new Element(), {plan:input.plan,kit:{materials:{}},tier:'low',bake:false,
    site:{lat:40,lon:-75,front_bearing_deg:180,source:'home_location',timezone:'America/New_York'}});
  } finally { globalThis.setInterval=oldInterval; }
  const flags = () => {
    const out = [];
    view.scene.traverse(o => {if(o.isLight) out.push([o.uuid,o.visible,o.castShadow]);});
    return {lights:out,environment:!!view.scene.environment};
  };
  assert.equal(view.state.time,'now');
  let warm = 0; view.onTimeLook = () => warm++;
  view.setClock('2026-06-21T17:00:00Z'); const noon = flags(), env = view.scene.environment;
  const cube = view.scene.background;
  assert.ok(cube.isCubeTexture && env.isPMREMTexture,'the viewer draws and lights with the sky');
  const sun = view.scene.getObjectByName('real-sun'), moon = view.scene.getObjectByName('real-moon');
  assert.ok(sun.intensity>0); assert.equal(moon.castShadow,false);
  sun.shadow.needsUpdate = false;
  view.setClock('2026-06-22T00:40:00Z'); assert.deepEqual(flags(),noon);
  view.setClock('2026-06-22T05:00:00Z'); assert.deepEqual(flags(),noon);
  assert.equal(sun.intensity,0); assert.equal(view.scene.environment,env);
  assert.equal(view.scene.background,cube);
  assert.equal(sun.shadow.needsUpdate,false,'no sun shadow refresh within a minute');
  assert.notEqual(view.renderer3.shadowMap.autoUpdate,false,'HA lamp shadows keep renderer updates');
  assert.ok(warm>=3,'time-look callbacks retained');
  const beforeTick=warm; minuteTick(); assert.equal(warm,beforeTick+1,'registered minute callback exercises the clock path');
  assert.ok(view.roomLights.every(l=>l.intensity>=0));
});
await test('viewer weather updates fixed textures and lights; editor ignores weather', async () => {
  const viewer=await mountTwin(new Element(),{plan:input.plan,kit:{materials:{}},tier:'low',bake:false});
  const host=new Element();host.className='editor-shell';
  const editor=await mountTwin(host,{plan:input.plan,kit:{materials:{}},tier:'low',bake:false});
  let stale=false;const states={'weather.a':{state:'sunny'}};
  try {
    for(const v of [viewer,editor]) {v.live={peek:()=>states,stale:()=>stale,draw(){},stop(){}};v.setTime('day');}
    const cube=viewer.scene.background,env=viewer.scene.environment,sun=viewer.scene.getObjectByName('real-sun');
    const clear=sun.intensity,hemisphere=viewer.scene.children.find(o=>o.isHemisphereLight),fill=hemisphere.intensity,environment=viewer.scene.environmentIntensity;
    states['weather.a'].state='cloudy';states['weather.a'].attributes={cloud_coverage:100};viewer.render();editor.render();
    assert.equal(viewer.scene.background,cube);assert.equal(viewer.scene.environment,env);
    assert.equal(sun.intensity,clear);assert.equal(viewer.clouds.uniforms.cloudCoverage.value,1,'the cloud grid owns extinction');assert.equal(hemisphere.intensity,fill*1.35);assert.equal(viewer.scene.environmentIntensity,environment*1.35);
    assert.equal(editor.scene.getObjectByName('real-sun').intensity,clear,'editor has no live weather');
    states['weather.b']={state:'sunny'};viewer.setWeatherEntity('weather.b');assert.equal(sun.intensity,clear);
    viewer.setWeatherEntity(null);assert.equal(sun.intensity,clear);assert.equal(viewer.clouds.uniforms.cloudCoverage.value,1);
    stale=true;viewer.render();assert.equal(sun.intensity,clear);
    viewer.setTime('night');assert.equal(viewer.scene.background,cube);assert.equal(viewer.scene.environment,env);
    editor.setTime('night');assert.ok(editor.scene.background.isCubeTexture);
    editor.setUnlit(true);assert.equal(editor.scene.environment,null);assert.ok(editor.scene.background.isColor);
    assert.equal(editor.scene.background.getHexString(),'171e27');
    editor.setUnlit(false);assert.ok(editor.scene.background.isCubeTexture);
  } finally {viewer.dispose();editor.dispose();}
});
await test('glance preferences deliver the chosen weather entity to the mounted viewer', async () => {
  const viewer=await mountTwin(new Element(),{plan:input.plan,kit:{materials:{}},tier:'low',bake:false});
  let preferences={weather_entity:'weather.chosen',can_edit:false};
  const settings=mountGlanceSettings(viewer,{configure(){}},{configure(){}},{api:async()=>({ok:true,json:async()=>preferences})});
  try {
    viewer.live={peek:()=>({'weather.first':{state:'sunny',attributes:{friendly_name:'Alpha'}},'weather.chosen':{state:'cloudy',attributes:{friendly_name:'Zulu'}}}),stale:()=>false,draw(){},stop(){}};
    viewer.setTime('day');await settings.reload();
    assert.equal(viewer.scene.getObjectByName('real-sun').intensity,3);assert.equal(viewer.clouds.uniforms.cloudCoverage.value,.85);
    preferences={weather_entity:null,can_edit:false};await settings.reload();
    assert.equal(viewer.scene.getObjectByName('real-sun').intensity,3);
  } finally {settings.stop();viewer.dispose();}
});
await test('preview modes, idle return, minute tick, and clock test hook', async () => {
  const oldTimeout = globalThis.setTimeout, oldClear = globalThis.clearTimeout;
  let idle;
  globalThis.setTimeout = (fn,ms) => ms===120000 ? (idle=fn,12345) : oldTimeout(fn,ms);
  globalThis.clearTimeout = id => id===12345 ? undefined : oldClear(id);
  try {
    view.setTime('day'); assert.equal(view.state.time,'day');
    assert.ok(view.scene.getObjectByName('real-sun').intensity>0);
    view.setTime('night'); assert.equal(view.state.time,'night');
    assert.equal(view.scene.getObjectByName('real-sun').intensity,0);
    idle(); assert.equal(view.state.time,'now');
    view.setTime('day'); view.setTime('now'); assert.equal(view.state.time,'now');
    assert.throws(()=>view.setClock('bad clock'));
    view.setClock(null);
  } finally { globalThis.setTimeout=oldTimeout; globalThis.clearTimeout=oldClear; view.dispose(); }
});
await test('facing dial pointer/keyboard/typed save and reload use the placement path', async () => {
  const el = id => document.getElementById(id), requests=[];
  let sheets = {sources:[],page_roles:[],kinds:[],place:{buildings:[],lot:{front_bearing_deg:180},photo_tags:{}}};
  const place = createPlace({getSheets:()=>sheets,canEdit:()=>true,panel:{message(){}},reload:async()=>{},
    request:async(path,method,body)=>{requests.push({path,method,body});return{};}});
  place.sync(sheets,{});
  const dial=el('place-facing-dial'), degrees=el('place-facing-degrees');
  assert.equal(dial.getAttribute('aria-valuenow'),'180');
  await fire(dial,'keydown',{key:'ArrowRight'}); await fire(dial,'keyup',{key:'ArrowRight'});
  assert.deepEqual(requests.at(-1),{path:'place/lot/placement',method:'PUT',body:{front_bearing_deg:181}});
  degrees.value='90'; await fire(degrees,'input'); await fire(el('place-facing-form'),'submit');
  assert.equal(requests.at(-1).body.front_bearing_deg,90);
  dial.getBoundingClientRect = () => ({left:0,top:0,width:100,height:100});
  await fire(dial,'pointerdown',{pointerId:1,button:0,clientX:50,clientY:0});
  await fire(dial,'pointerup',{pointerId:1}); assert.equal(requests.at(-1).body.front_bearing_deg,0);
  sheets=structuredClone(sheets); sheets.place.lot.front_bearing_deg=271; place.sync(sheets,{});
  assert.equal(degrees.value,'271'); assert.equal(dial.getAttribute('aria-valuenow'),'271');
  assert.equal(el('place-facing-house').style.transform,'rotate(271deg)');
  sheets=structuredClone(sheets); Object.assign(sheets.place.lot,{map_bearing_deg:180,map_bearing_source:'footprint'});
  place.sync(sheets,{site:{front_bearing_deg:180,map_bearing_deg:180,map_bearing_source:'footprint'}});
  assert.equal(degrees.value,'180','map wins over a legacy dial without an override');
  assert.ok(el('place-facing-map-note').textContent.includes('180° (building footprint)'));
  await fire(el('place-facing-map'),'click');
  assert.deepEqual(requests.at(-1),{path:'place/lot/bearing/map',method:'POST',body:{}});
  place.sync(sheets,{site:{front_bearing_deg:271,front_bearing_source:'dial',map_bearing_deg:180,map_bearing_source:'street'}});
  assert.equal(degrees.value,'271','an explicit dial override survives the map');
  assert.ok(el('place-facing-map-note').textContent.includes('nearest street'));
  place.sync(sheets,{site:{front_bearing_deg:210,map_bearing_deg:210,map_bearing_source:'street'}});
  assert.equal(degrees.value,'210','state-only background completion refreshes the dial');
  place.sync(sheets,{site:{front_bearing_deg:271,front_bearing_source:'dial'}});
  assert.equal(el('place-facing-map').disabled,true,'a new location cannot use stale map data from sheets');
  assert.ok(el('place-facing-map-note').textContent.includes('unavailable'));
});
await test('high tier throttles only the sun and invalidates its shadow on rebuild', async () => {
  const previousQuery=location.search; location.search='?test=1&tier=high';
  let high;
  try {
    high = await mountTwin(new Element(), {plan:input.plan,kit:{materials:{}},tier:'high',bake:false});
    const sun=high.scene.getObjectByName('real-sun'), moon=high.scene.getObjectByName('real-moon');
    assert.equal(sun.castShadow,true); assert.equal(sun.shadow.autoUpdate,false);
    assert.equal(moon.castShadow,false); assert.notEqual(high.renderer3.shadowMap.autoUpdate,false);
    sun.shadow.needsUpdate=false;
    high.setClock('2026-06-21T12:00:00Z'); high.setClock('2026-06-22T00:00:00Z');
    assert.equal(sun.shadow.needsUpdate,false);
    high.setView(high.levelKeys()[0]); assert.equal(sun.shadow.needsUpdate,true,'cutaway removes roof shadows');
    sun.shadow.needsUpdate=false;
    high.showLevels([]); assert.equal(sun.shadow.needsUpdate,true,'level visibility invalidates shadow casters');
    sun.shadow.needsUpdate=false;
    await high.rebuild(input.plan); assert.equal(sun.shadow.needsUpdate,true,'changed geometry refreshes shadows');
    sun.shadow.needsUpdate=false;
    high.setTime('day'); assert.equal(sun.shadow.needsUpdate,true,'a chosen time of day shows its shadows at once');
    assert.equal(sun.intensity,7);
    sun.shadow.needsUpdate=false;
    high.setTime('day'); assert.equal(sun.shadow.needsUpdate,false,'the same time again is not a move');
    const texel = 2 * sun.shadow.camera.right / sun.shadow.mapSize.x;
    assert.ok(sun.shadow.radius >= 1 && sun.shadow.radius <= 4);
    assert.ok(sun.shadow.radius * texel <= .0501, 'the soft edge stays within 5 cm');
  } finally { high?.dispose(); location.search=previousQuery; }
});
await test('rooms under a roof take a fraction of the sky, and only where the sun casts shadows', async () => {
  const {disposeObject} = await import(file('static/twin/twin_library.js')), THREE = await import('three');
  const indoor = v => { const out = []; for (const g of Object.values(v.groups.levels)) g.traverse(o => {
    for (const m of [].concat(o.material || [])) if (['interior_wall','floor','ceiling'].includes(m.name)) out.push(m); }); return out; };
  const previousQuery=location.search; location.search='?test=1&tier=high';
  let high, low;
  try {
    high = await mountTwin(new Element(), {plan:input.plan,kit:{materials:{}},tier:'high',bake:false});
    high.setTime('day'); high.render();
    const env = high.scene.environment, rooms = indoor(high);
    assert.ok(env && rooms.length, 'the fixture has rooms and a sky');
    for (const m of rooms) { assert.equal(m.envMap,env); assert.ok(Math.abs(m.envMapIntensity - .3 * .4) < 1e-9); }
    let outdoor = 0; high.scene.traverse(o => { for (const m of [].concat(o.material || [])) if (['siding','roof','trim'].includes(m.name)) { outdoor++; assert.equal(m.envMap,null); } });
    assert.ok(outdoor, 'outside surfaces keep the whole sky');
    high.setTime('night'); high.render();
    for (const m of indoor(high)) assert.ok(Math.abs(m.envMapIntensity - .3 * high.scene.environmentIntensity) < 1e-9);
    await high.rebuild(input.plan); high.setTime('day'); high.render();
    assert.ok(indoor(high).every(m => m.envMap === high.scene.environment), 'a rebuilt house is dimmed again');
    let disposed = 0; env.addEventListener('dispose', () => disposed++);
    const scrap = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial({envMap: env}));
    disposeObject(scrap); assert.equal(disposed,0,'a discarded surface never takes the sky with it');
    location.search='?test=1&tier=low';
    low = await mountTwin(new Element(), {plan:input.plan,kit:{materials:{}},tier:'low',bake:false});
    low.setTime('day'); low.render();
    assert.ok(indoor(low).length && indoor(low).every(m => m.envMap === null), 'low quality is untouched');
  } finally { high?.dispose(); low?.dispose(); location.search=previousQuery; }
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
