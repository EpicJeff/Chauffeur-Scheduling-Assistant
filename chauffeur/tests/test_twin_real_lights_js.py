"""Node checks for real lights in the 3D house's Lights mode (brief
.superpowers/sdd/2026-11-10-house-real-lights/brief.md; the browser half is
tests/test_house_twin_real_lights_live.py).

Lights mode used to lay a flat translucent sheet over each lit room's floor.
Now every light that is on gets a real THREE.PointLight at its marker, in its
colour, as bright as its brightness, from a fixed pool per tier; the fixture
glows; Day/Night keeps control of the time look; `All` releases the lamps.

What this file assumes (the implementer matches these):

static/twin/live/real_lights.js, importable in node (no DOM at module load):
  lightColor(attributes) -> [r, g, b], integers 0-255:
      rgb_color when given (it wins over a colour temperature); else
      color_temp_kelvin; else color_temp (mireds, kelvin = 1e6 / mireds); else
      warm white #fff1c9 = [255, 241, 201]. 2700 K is a warm orange (red full,
      red > green > blue); 6500 K is near white; 10000 K leans blue.
  lightIntensity(attributes) -> 0..1: brightness / 255, clamped; a light that
      is on without a brightness reads 1.
  pickReal(candidates, target, cap) -> iterable of device ids, at most `cap`:
      candidates [{device, at: [x, y, z] lot feet, intensity}]; target [x, y, z]
      lot feet. Nearest to the target first (3D distance); at an equal distance
      the brighter; a candidate with intensity 0 is never picked.
  createRealLights(view, {tier}) -> {stop(), ...}: adds a fixed pool of
      THREE.PointLight to view.scene at once, its size the tier's cap (low 4,
      medium 8, high 16, max 16); on high and max exactly 2 of them cast
      shadows, on low none; stop() removes them.
static/twin/twin_tiers.js: TIERS.low.realLights === 4, TIERS.high.realLights === 16
  (and 8 / 16 on medium / max if those tiers exist).

Through mountLive (static/twin/live/live.js), which builds the rig from view.tier:
  - live.lights() -> [{device, at, rgb, intensity, real}]: one row per light marker
    that is on (a light that is off, unavailable or stale is either absent or has
    intensity 0 and real false); `at` is the marker's `at`; rgb lightColor's;
    intensity lightIntensity's; real whether it holds a pool PointLight now.
  - In Lights mode each real light's PointLight sits at its marker's world spot
    (x and z equal; y the marker's, or at most a foot under it; Ruling R1: a light
    standing on the floor is a floor lamp, its PointLight and its glowing fixture
    4.5 ft above the floor, straight over the marker), intensity > 0,
    decay 2, a finite distance near the room's larger span (0.5x to 2.5x).
    Unused pool lights have intensity 0. Choice is redone on draw() when the
    camera target moves.
  - The pool is made once at mount: the PointLight count and the objects never
    change after that (three.js recompiles every material when it does).
  - The fixture glow: an object tagged userData.bulb = device_id per light marker,
    shown in Lights mode while the light is on, in its colour (emissive or color).
  - The fallback wash: an object tagged userData.lightWash = {building, room}
    per linked room, shown in Lights mode only for a room holding a light that is
    on but over the budget.
  - Lamp ownership goes through view.setLiveLamps(true/false). Entering or
    leaving Lights never calls setTime or the retired setEvening time-look path.
  - In All mode every pool light has intensity 0 and every wash is hidden.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_real_lights_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root} = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(root + '/' + p).href;
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: file('static/vendor/three-r187/three.module.js'), shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});

class Node extends EventTarget {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.style = {}; this.attrs = {}; this.hidden = false; this.scrollTop = 0; this.text = ''; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(n => n.textContent).join(' '); }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  replaceChildren(...nodes) { this.children = []; this.text = ''; this.append(...nodes); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this); }
  get lastChild() { return this.children.at(-1); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  querySelectorAll(selector) {
    const matches = node => selector.split(',').map(s => s.trim()).some(s => s === '[data-device-id]' ? node.dataset.deviceId : s === node.tagName.toLowerCase());
    return this.children.flatMap(n => [...(matches(n) ? [n] : []), ...n.querySelectorAll(selector)]);
  }
  closest() { for (let n = this; n; n = n.parentElement) if (n.dataset.deviceId) return n; return null; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return {left:0, top:0, right:1400, bottom:1000, width:1400, height:1000}; }
  getContext() { return new Proxy({measureText: text => ({width:text.length * 6})}, {get: (o, key) => o[key] ?? (() => {})}); }
}
const body = new Node('body'), controls = new Node('div'); controls.id = 'twin-controls'; body.append(controls);
globalThis.document = Object.assign(new EventTarget(), {body, activeElement:null, createElement: tag => new Node(tag),
  // The Energy check builds text nodes (energy_check.js); a text node is a Node with text.
  createTextNode: text => Object.assign(new Node('#text'), {textContent: String(text)}),
  createElementNS: (ns, tag) => new Node(tag),
  getElementById(id) { const find = n => n.id === id ? n : n.children.map(find).find(Boolean); return find(body); }});
globalThis.window = {chfBase:'../'};
globalThis.location = {search:''};
globalThis.requestAnimationFrame = callback => setImmediate(callback);
const THREE = await import('three');
const {mountLive} = await import(file('static/twin/live/live.js'));
const {TIERS} = await import(file('static/twin/twin_tiers.js'));
let R = null, missing = null;
try { R = await import(file('static/twin/live/real_lights.js')); }
catch (error) { missing = String(error && error.message || error).split('\n')[0]; }
const need = (...names) => {
  assert.ok(R, `static/twin/live/real_lights.js is missing or does not load: ${missing}`);
  for (const name of names) assert.equal(typeof R[name], 'function', `real_lights.js exports ${name}`);
};
const FT = .3048;

// --- the house the mounted checks use -------------------------------------------------
// Building b at the lot origin, no rotation. Room A 20 x 10 ft holds four lights, room B
// (34 ft east) two, room C one that is off. A lock in A is the one light-less marker.
const square = (x0, y0, x1, y1) => [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
const roomsPlan = [{id:'A',level:'L1',polygon:square(0,0,20,10)}, {id:'B',level:'L1',polygon:square(40,0,50,10)},
  {id:'C',level:'L1',polygon:square(0,30,10,40)}];
const light = (id, room, at, state, attrs = {}) => ({id, room, at, entity:`light.${id}`, kind:'light', state, attrs});
const fixture = [
  light('a1','A',[2,2,9],'on',{brightness:255}),
  light('a2','A',[6,5,9],'on',{brightness:128}),
  light('a3','A',[10,5,9],'on',{brightness:200,rgb_color:[255,0,0],color_mode:'rgb'}),
  light('a4','A',[14,5,9],'on',{brightness:255,color_temp_kelvin:2700,color_mode:'color_temp'}),
  light('b1','B',[42,5,9],'on',{brightness:255}),
  light('b2','B',[48,5,9],'on',{brightness:64}),
  light('c1','C',[5,35,9],'off',{}),
  {id:'lock',room:'A',at:[1,1,0],entity:'lock.back',kind:'lock',state:'locked',attrs:{}},
];
const initialStates = () => Object.fromEntries(fixture.map(f => [f.entity, {state:f.state, attributes:structuredClone(f.attrs)}]));
let states = initialStates();
const area = room => ({A:'area_a',B:'area_b',C:'area_c'})[room];
const layout = {available:true,
  rooms: roomsPlan.map(r => ({building:'b',room:r.id,level:'L1',name:'Room '+r.id,area_id:area(r.id),
    lights: fixture.filter(f => f.room === r.id && f.kind === 'light').map(f => f.entity)})),
  devices: fixture.map(f => ({device_id:f.id,name:f.id,entity_id:f.entity,entities:[f.entity],kind:f.kind,offered:true,area_id:area(f.room)})),
  markers: fixture.map(f => ({device_id:f.id,name:f.id,entity_id:f.entity,entities:[f.entity],kind:f.kind,offered:true,
    area_id:area(f.room),building:'b',level:'L1',room:f.room,at:f.at,placed:true}))};
let reachable = true;
const api = async path => ({ok:true,json:async () => structuredClone(path === 'api/house/live' ? layout : {states,reachable})});
const lampOwnership = [], timeChanges = [];
function makeView(tier) {
  const canvas = new Node('canvas'), host = new Node('main'); host.append(canvas); body.append(host);
  const camera = new THREE.PerspectiveCamera(38,1.4,.1,1000); camera.position.set(8*FT,50*FT,-5*FT); camera.lookAt(8*FT,0,-5*FT);
  const level = new THREE.Group();
  return {ready:true,tier,scene:new THREE.Scene(),renderer3:{domElement:canvas,shadowMap:{enabled:tier !== 'low'}},camera,
    controls:{target:new THREE.Vector3(8*FT,0,-5*FT)},groups:{levels:{'b:L1':level}},
    plan:{buildings:[{id:'b',position:[0,0],rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:10}],rooms:roomsPlan,stairs:[]}]},
    pick: () => null, render() { this.live?.draw(); }, setLiveLamps(on) { lampOwnership.push(!!on); }, setEvening() { timeChanges.push('evening'); }, setTime() { timeChanges.push('time'); }};
}
const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
const pool = view => { const out = []; view.scene.traverse(o => { if (o.isPointLight) out.push(o); }); return out; };
const allLights = view => { const out = []; view.scene.traverse(o => { if (o.isLight) out.push(o); }); return out; };
const tagged = (view, key) => { const out = []; view.scene.traverse(o => { if (o.userData && o.userData[key] !== undefined) out.push(o); }); return out; };
const markerSpot = (view, id) => { let spot = null; view.scene.traverse(o => { if (o.isSprite && o.userData.deviceId === id) spot = o.getWorldPosition(new THREE.Vector3()); }); return spot; };
// The pool light lighting a marker: on, x and z on the marker, y at most a foot under it.
// A floor lamp's (Ruling R1: a light on the floor) hangs 4.5 ft above the floor its marker is on.
const LAMP_HEIGHT = 4.5;
const lampAt = (view, id, floorLamp = false) => {
  const spot = markerSpot(view, id); assert.ok(spot, `the marker sprite of ${id}`);
  return pool(view).filter(l => l.intensity > 0 && shown(l)).find(l => {
    const p = l.getWorldPosition(new THREE.Vector3());
    if (Math.abs(p.x - spot.x) >= .05 || Math.abs(p.z - spot.z) >= .05) return false;
    return floorLamp ? Math.abs(p.y - (spot.y + LAMP_HEIGHT * FT)) < .05 : p.y <= spot.y + .05 && p.y >= spot.y - FT - .05;
  }) || null;
};
const row = (live, id) => live.lights().find(r => r.device === id) || null;
const isOff = r => !r || (r.intensity === 0 && r.real === false);
const realSet = live => live.lights().filter(r => r.real).map(r => r.device).sort();
const washShown = (view, room) => tagged(view, 'lightWash').filter(o => o.userData.lightWash.room === room).some(shown);
const bulb = (view, id) => tagged(view, 'bulb').filter(o => o.userData.bulb === id);
const tint = object => {
  const m = object.material || {}, e = m.emissive, c = m.color;
  return e && Math.max(e.r, e.g, e.b) > 0 ? e : c;
};
const setTarget = (view, x, y) => { view.controls.target.set(x*FT, 0, -y*FT); view.camera.position.set(x*FT, 50*FT, -y*FT); view.camera.lookAt(x*FT, 0, -y*FT); };
async function mounted(tier = 'low') {
  states = initialStates(); reachable = true; lampOwnership.length = 0; timeChanges.length = 0;
  const view = makeView(tier);
  const live = await mountLive(view, {api});
  assert.ok(live, 'the live layer mounts on the fake view');
  assert.equal(typeof live.lights, 'function', 'live.lights() exists');
  return {view, live};
}

const checks = [];
const check = (name, fn) => checks.push([name, fn]);


check('lights_mode_never_requests_a_time_look_change', async () => {
  const {view, live} = await mounted('low');
  try {
    live.setMode('lights'); live.draw(); await live.refresh();
    assert.deepEqual(timeChanges, [], 'lighting(true) must never change the time look');
    assert.equal(lampOwnership.at(-1), true, 'Lights owns the lamps');
    live.setMode('security');
    assert.deepEqual(timeChanges, [], 'leaving Lights must never change the time look');
    assert.equal(lampOwnership.at(-1), false, 'a mode without lighting releases the lamps');
  } finally { live.stop(); }
});

check('color_from_rgb_kelvin_mireds_and_default', async () => {
  need('lightColor');
  const {lightColor} = R;
  const close = (a, b, tol, msg) => assert.ok(a.every((v, i) => Math.abs(v - b[i]) <= tol), `${msg}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`);
  assert.deepEqual(lightColor({rgb_color:[0,0,255]}), [0,0,255], 'rgb_color is used as given');
  assert.deepEqual(lightColor({rgb_color:[12,200,40], color_temp_kelvin:2700}), [12,200,40], 'rgb_color wins over a colour temperature');
  assert.deepEqual(lightColor({}), [255,241,201], 'no colour: warm white #fff1c9');
  assert.deepEqual(lightColor(undefined), [255,241,201], 'no attributes: warm white');
  assert.deepEqual(lightColor({brightness:120, rgb_color:null}), [255,241,201], 'a null rgb_color is no colour');
  const warm = lightColor({color_temp_kelvin:2700});
  assert.ok(warm.every(v => Number.isInteger(v) && v >= 0 && v <= 255), `integers 0-255: ${warm}`);
  assert.ok(warm[0] >= 250 && warm[0] > warm[1] && warm[1] > warm[2] && warm[2] < 140, `2700 K is warm orange: ${warm}`);
  const day = lightColor({color_temp_kelvin:6500});
  assert.ok(day.every(v => v >= 230), `6500 K is near white: ${day}`);
  const cold = lightColor({color_temp_kelvin:10000});
  assert.ok(cold[2] > cold[0], `10000 K leans blue: ${cold}`);
  close(lightColor({color_temp:370}), warm, 6, '370 mireds is about 2700 K');
  close(lightColor({color_temp:154}), day, 6, '154 mireds is about 6500 K');
  close(lightColor({color_temp_kelvin:2700, color_temp:154}), warm, 0, 'kelvin wins over mireds');

  // Mounted: the pool light and the fixture take the light's colour.
  const {view, live} = await mounted();
  try {
    live.setMode('lights');
    assert.deepEqual(row(live, 'a3')?.rgb, [255,0,0], 'live.lights() carries rgb_color');
    assert.deepEqual(row(live, 'a1')?.rgb, [255,241,201], 'live.lights() falls back to warm white');
    const red = lampAt(view, 'a3'); assert.ok(red, 'a red light has a pool light at its marker');
    assert.ok(red.color.r > .9 && red.color.g < .05 && red.color.b < .05, `the pool light is red: ${red.color.toArray()}`);
    const amber = lampAt(view, 'a4'); assert.ok(amber, 'a 2700 K light has a pool light');
    assert.ok(amber.color.r > amber.color.g && amber.color.g > amber.color.b, `the 2700 K pool light is warm: ${amber.color.toArray()}`);
    const glow = bulb(view, 'a3'); assert.equal(glow.length, 1, 'one glowing fixture per light (userData.bulb)');
    assert.ok(shown(glow[0]), 'the red fixture glows in Lights mode');
    const t = tint(glow[0]); assert.ok(t && t.r > .9 && t.g < .1 && t.b < .1, `the fixture glows red: ${t && t.toArray()}`);
  } finally { live.stop(); }
});

check('intensity_follows_brightness', async () => {
  need('lightIntensity');
  const {lightIntensity} = R;
  assert.equal(lightIntensity({brightness:255}), 1);
  assert.ok(Math.abs(lightIntensity({brightness:128}) - 128/255) < .005, 'brightness / 255');
  assert.equal(lightIntensity({brightness:0}), 0);
  assert.equal(lightIntensity({brightness:300}), 1, 'clamped');
  assert.equal(lightIntensity({}), 1, 'on without a brightness reads full');
  assert.equal(lightIntensity({brightness:null}), 1, 'a null brightness reads full');

  const {view, live} = await mounted();
  try {
    live.setMode('lights');
    assert.ok(Math.abs(row(live, 'a2').intensity - 128/255) < .01, `live.lights() intensity: ${JSON.stringify(row(live, 'a2'))}`);
    const full = lampAt(view, 'a1'), half = lampAt(view, 'a2');
    const halfIntensity = half?.intensity;
    assert.ok(full && half, 'both white lights hold a pool light');
    assert.ok(full.intensity > half.intensity && half.intensity > 0, `255 is brighter than 128: ${full.intensity} vs ${half.intensity}`);
    assert.equal(full.decay, 2, 'physically based decay');
    assert.ok(Number.isFinite(full.distance) && full.distance > 0, `a finite range: ${full.distance}`);
    assert.ok(full.distance >= .5 * 20 * FT && full.distance <= 2.5 * 20 * FT, `the range is about room A's larger span (20 ft): ${full.distance} m`);
    states['light.a2'].attributes.brightness = 255; await live.refresh();
    const raised = lampAt(view, 'a2');
    assert.ok(raised && Math.abs(raised.intensity - lampAt(view, 'a1').intensity) < 1e-6, 'the same brightness, the same intensity');
    states['light.a2'].attributes.brightness = 26; await live.refresh();
    assert.ok(lampAt(view, 'a2').intensity < halfIntensity, `dimmer at 26: ${lampAt(view, 'a2').intensity} vs ${halfIntensity}`);
  } finally { live.stop(); }
});

check('budget_picks_nearest_then_brightest_per_tier', async () => {
  need('pickReal', 'createRealLights');
  const {pickReal, createRealLights} = R;
  const ids = it => [...it].sort();
  const c = (device, x, intensity = 1) => ({device, at:[x,0,9], intensity});
  // Nearest first, whatever the brightness.
  assert.deepEqual(ids(pickReal([c('far',30,1), c('near',2,.1), c('mid',10,.5)], [0,0,9], 2)), ['mid','near']);
  // At an equal distance the brighter one.
  assert.deepEqual(ids(pickReal([c('dim',-5,.2), c('bright',5,.9), c('close',1,.1)], [0,0,9], 2)), ['bright','close']);
  // A light at intensity 0 is never picked; fewer candidates than the cap is fine.
  assert.deepEqual(ids(pickReal([c('off',1,0), c('on',20,.4)], [0,0,9], 4)), ['on']);
  assert.deepEqual(ids(pickReal([], [0,0,9], 4)), []);
  // The cap per tier, and shadows only on high and max, on 2 lights.
  for (const [tier, cap, shadows] of [['low',4,0], ['medium',8,0], ['high',16,2], ['max',16,2]]) {
    const scene = new THREE.Scene();
    const rig = createRealLights({scene, tier, renderer3:{shadowMap:{enabled:shadows > 0}}}, {tier});
    const lights = pool({scene});
    assert.equal(lights.length, cap, `${tier}: a pool of ${cap} PointLights at once`);
    assert.ok(lights.every(l => l.intensity === 0), `${tier}: unused pool lights are dark`);
    assert.equal(lights.filter(l => l.castShadow).length, shadows, `${tier}: ${shadows} shadow casters`);
    rig.stop();
    assert.equal(pool({scene}).length, 0, `${tier}: stop() removes the pool`);
  }
  assert.equal(TIERS.low.realLights, 4, 'twin_tiers.js: TIERS.low.realLights');
  assert.equal(TIERS.high.realLights, 16, 'twin_tiers.js: TIERS.high.realLights');
  if (TIERS.medium) assert.equal(TIERS.medium.realLights, 8);
  if (TIERS.max) assert.equal(TIERS.max.realLights, 16);

  // Mounted on low: the four nearest the camera target (room A) are real.
  const {view, live} = await mounted('low');
  try {
    live.setMode('lights');
    assert.deepEqual(realSet(live), ['a1','a2','a3','a4'], `the four nearest the target: ${JSON.stringify(live.lights())}`);
    assert.equal(pool(view).filter(l => l.intensity > 0).length, 4, 'four pool lights lit');
    for (const id of ['a1','a2','a3','a4']) assert.ok(lampAt(view, id), `a pool light at ${id}`);
    assert.deepEqual(row(live, 'a1').at, [2,2,9], 'at is the marker\'s at');
  } finally { live.stop(); }
});

check('fixed_light_pool_never_changes_count', async () => {
  const {view, live} = await mounted('low');
  try {
    const first = pool(view), uuids = first.map(l => l.uuid).sort(), count = allLights(view).length;
    assert.equal(first.length, 4, 'the low pool exists from mount on, before Lights mode');
    const same = step => {
      const now = pool(view);
      assert.equal(now.length, 4, `${step}: still four PointLights`);
      assert.deepEqual(now.map(l => l.uuid).sort(), uuids, `${step}: the same PointLight objects`);
      assert.equal(allLights(view).length, count, `${step}: no light of any kind added or removed`);
      assert.equal(now.filter(l => l.castShadow).length, 0, `${step}: no shadow caster appears on low`);
    };
    live.setMode('lights'); same('Lights mode');
    states['light.a1'].state = 'off'; await live.refresh(); same('a light turned off');
    for (const f of fixture) if (f.kind === 'light') states[f.entity].state = 'off';
    await live.refresh(); same('every light off');
    assert.ok(pool(view).every(l => l.intensity === 0), 'every light off: the pool is dark');
    states = initialStates(); states['light.c1'].state = 'on'; states['light.c1'].attributes = {brightness:255};
    await live.refresh(); same('seven lights on');
    setTarget(view, 45, 5); live.draw(); view.render(); same('the camera moved');
    live.setMode(null); same('All');
    live.setMode('lights'); same('Lights again');
  } finally { live.stop(); }
  assert.equal(pool(view).length, 0, 'stop() takes the pool away');
  assert.equal(view.scene.children.length, 0, 'stop() leaves the scene as it found it');
});

check('over_budget_lights_fall_back_to_glow_and_wash', async () => {
  const {view, live} = await mounted('low');
  try {
    live.setMode('lights');
    const rows = Object.fromEntries(live.lights().map(r => [r.device, r]));
    for (const id of ['b1','b2']) {
      assert.ok(rows[id] && rows[id].real === false && rows[id].intensity > 0, `${id} is on but over the budget: ${JSON.stringify(rows[id])}`);
      assert.equal(lampAt(view, id), null, `${id} holds no pool light`);
      assert.equal(bulb(view, id).length, 1, `${id} has its fixture`);
      assert.ok(shown(bulb(view, id)[0]), `${id}'s fixture glows`);
    }
    assert.ok(isOff(rows.c1), `c1 is off: ${JSON.stringify(rows.c1)}`);
    assert.ok(!bulb(view, 'c1').some(shown), 'an off light\'s fixture does not glow');
    assert.ok(tagged(view, 'lightWash').length >= 2, 'a wash per linked room (userData.lightWash)');
    assert.equal(washShown(view, 'B'), true, 'room B (over budget) gets the soft floor wash');
    assert.equal(washShown(view, 'A'), false, 'room A (all real) has no wash');
    assert.equal(washShown(view, 'C'), false, 'room C (dark) has no wash');

    // The camera moves to room B: B is real now, two of A fall back.
    setTarget(view, 45, 5); live.draw(); view.render();
    assert.deepEqual(realSet(live), ['a3','a4','b1','b2'], `nearest to room B, then brighter: ${JSON.stringify(live.lights())}`);
    assert.ok(lampAt(view, 'b1') && lampAt(view, 'b2'), 'room B is lit by real lights');
    assert.equal(washShown(view, 'B'), false, 'room B loses its wash');
    assert.equal(washShown(view, 'A'), true, 'room A gets the wash for the lights it lost');
    assert.ok(shown(bulb(view, 'a1')[0]), 'an over-budget fixture still glows');
  } finally { live.stop(); }
});

// Slice 2c-2 (user, 2026-11-12): All is every visualization at once, so it lights rooms as
// Lights does. A mode without lighting (Security) is where the look is released.
check('all_mode_lights_and_other_modes_release_lighting', async () => {
  const {view, live} = await mounted('low');
  try {
    assert.equal(lampOwnership.at(-1), true, 'mounting in All takes lamp ownership: view.setLiveLamps(true)');
    live.setMode('lights');
    assert.equal(lampOwnership.at(-1), true, 'Lights keeps lamp ownership');
    assert.ok(pool(view).some(l => l.intensity > 0), 'Lights mode lights the pool');
    live.setMode('security');
    assert.equal(lampOwnership.at(-1), false, 'Security releases lamp ownership: view.setLiveLamps(false)');
    assert.ok(pool(view).every(l => l.intensity === 0), 'Security: every pool light is dark');
    assert.equal(tagged(view, 'lightWash').some(shown), false, 'Security: no wash');
    // A poll while in Security mode lights nothing.
    states['light.c1'] = {state:'on', attributes:{brightness:255}}; await live.refresh();
    assert.ok(pool(view).every(l => l.intensity === 0), 'Security: a poll lights nothing');
    assert.equal(lampOwnership.at(-1), false, 'Security: a poll does not dim the scene');
    live.setMode(null);
    assert.equal(lampOwnership.at(-1), true, 'All takes lamp ownership again');
    assert.ok(pool(view).some(l => l.intensity > 0), 'All lights the pool like Lights');
    live.setMode('lights');
  } finally { live.stop(); }
  assert.equal(lampOwnership.at(-1), false, 'stopping the layer gives the look back');
});

check('floor_lamp_light_hangs_at_lamp_height', async () => {
  // Ruling R1: a light standing on the floor of room C is a floor lamp.
  const lamp = light('d1','C',[3,33,0],'on',{brightness:255});
  const marker = {device_id:'d1',name:'d1',entity_id:'light.d1',entities:['light.d1'],kind:'light',offered:true,
    area_id:'area_c',building:'b',level:'L1',room:'C',at:[3,33,0],placed:true};
  fixture.push(lamp); layout.markers.push(marker);
  layout.devices.push({device_id:'d1',name:'d1',entity_id:'light.d1',entities:['light.d1'],kind:'light',offered:true,area_id:'area_c'});
  try {
    const {view, live} = await mounted('high');
    try {
      live.setMode('lights');
      assert.ok(row(live, 'd1')?.real === true, `the floor lamp is real on high: ${JSON.stringify(row(live, 'd1'))}`);
      assert.deepEqual(row(live, 'd1').at, [3,33,0], 'live.lights() keeps the at of the marker');
      const hung = lampAt(view, 'd1', true);
      assert.ok(hung, `the floor lamp's light is 4.5 ft above the floor: ${JSON.stringify(pool(view).filter(l => l.intensity > 0).map(l => l.position.toArray().map(v => v / FT)))}`);
      assert.equal(lampAt(view, 'd1'), null, 'not at the marker on the floor');
      const glow = bulb(view, 'd1')[0], at = glow.getWorldPosition(new THREE.Vector3());
      assert.ok(Math.abs(at.y - LAMP_HEIGHT * FT) < .05, `the fixture glows at the bulb, 4.5 ft up: ${at.y / FT} ft`);
      assert.ok(lampAt(view, 'a1'), 'a light 9 ft up keeps the marker height rule');
    } finally { live.stop(); }
  } finally {
    fixture.splice(fixture.indexOf(lamp), 1); layout.markers.splice(layout.markers.indexOf(marker), 1);
    layout.devices.splice(layout.devices.findIndex(d => d.device_id === 'd1'), 1);
  }
});

let passed = 0;
for (const [name, fn] of checks) {
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 400)); }
}
console.log(`${passed}/${checks.length} passed`);
process.exit(passed === checks.length ? 0 : 1);
"""


def run():
    node = shutil.which('node')
    if not node:
        print('  skip  node is unavailable')
        return 0
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix()}))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix,
                                             prefix='chauffeur_real_lights_', delete=False) as stream:
                paths.append(Path(stream.name))
                stream.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1])], capture_output=True,
                                text=True, encoding='utf-8', timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
