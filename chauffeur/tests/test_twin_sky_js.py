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
await test('continuous colour/intensity at all four band edges', () => {
  for (const edge of [-12,-6,0,6]) {
    const a = lookAt(edge - 1e-6, {altitude:.5,fraction:1}), b = lookAt(edge + 1e-6, {altitude:.5,fraction:1});
    for (const key of ['background','ambient','environment','exposure','sunColor','sun','moon']) {
      const aa = [].concat(a[key]), bb = [].concat(b[key]);
      aa.forEach((v,i) => assert.ok(Math.abs(v-bb[i]) < 1e-5, key + ' at ' + edge));
    }
  }
  assert.ok(lookAt(-3.01).lamps); assert.ok(!lookAt(-3).lamps);
  assert.equal(lookAt(-20, {altitude:-.1,fraction:1}).moon, 0);
  assert.equal(lookAt(-20, {altitude:1,fraction:0}).moon, 0);
});
await test('front bearing follows the actual Front camera ray', () => {
  const a = modelDirection(Math.PI, Math.PI/4, 180), length = Math.hypot(41,69);
  assert.ok(Math.abs(a[0] / Math.cos(Math.PI/4) + 41/length) < 1e-12);
  assert.ok(Math.abs(a[2] / Math.cos(Math.PI/4) - 69/length) < 1e-12);
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
  const sun = view.scene.getObjectByName('real-sun'), moon = view.scene.getObjectByName('real-moon');
  assert.ok(sun.intensity>0); assert.equal(moon.castShadow,false);
  sun.shadow.needsUpdate = false;
  view.setClock('2026-06-22T00:40:00Z'); assert.deepEqual(flags(),noon);
  view.setClock('2026-06-22T05:00:00Z'); assert.deepEqual(flags(),noon);
  assert.equal(sun.intensity,0); assert.equal(view.scene.environment,env);
  assert.equal(sun.shadow.needsUpdate,false,'no sun shadow refresh within a minute');
  assert.notEqual(view.renderer3.shadowMap.autoUpdate,false,'HA lamp shadows keep renderer updates');
  assert.ok(warm>=3,'time-look callbacks retained');
  const beforeTick=warm; minuteTick(); assert.equal(warm,beforeTick+1,'registered minute callback exercises the clock path');
  assert.ok(view.roomLights.every(l=>l.intensity>=0));
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
  } finally { high?.dispose(); location.search=previousQuery; }
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
