"""Execute the live room controls and mode lifecycle without a browser/GPU.

This complements, and does not replace, test_house_twin_live_rooms.py's real
pointer, WebGL pixel and wall layout checks.
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
  getElementById(id) { const find = n => n.id === id ? n : n.children.map(find).find(Boolean); return find(body); }});
globalThis.window = {chfBase:'../'};
globalThis.location = {search:''};
globalThis.requestAnimationFrame = callback => setImmediate(callback);
const THREE = await import('three');
const {mountLive} = await import(file('static/twin/live/live.js'));
const {roomStates} = await import(file('static/twin/live/modes.js'));
const {deviceActions} = await import(file('static/twin/live/room_panel.js'));
const polygon = [[0,0],[10,0],[10,10],[0,10]];
const makeDevice = (id, kind, state, attrs = {}, offered = true, area = 'kitchen') => ({
  device: {device_id:id, name:id, entity_id:`${kind === 'garage' ? 'cover' : kind}.${id}`, entities:[`${kind === 'garage' ? 'cover' : kind}.${id}`], kind, offered, area_id:area},
  state: {state, attributes:attrs},
});
const fixture = [makeDevice('lamp','light','on',{brightness:128}), makeDevice('pendant','light','on',{brightness:255}),
  makeDevice('fan','fan','off'), makeDevice('plug','switch','off'), makeDevice('lock','lock','locked',{},false),
  makeDevice('garage','garage','closed',{},false), makeDevice('thermo','climate','heat',{current_temperature:70,temperature:68,target_temp_step:1}),
  makeDevice('temp','sensor','71.2'), makeDevice('blue','light','on',{brightness:153,rgb_color:[0,0,255]},true,'changing')];
let states = Object.fromEntries(fixture.map(f => [f.device.entity_id, f.state]));
const rooms = [{building:'b',room:'r',level:'L1',name:'Kitchen',area_id:'kitchen',lights:['light.lamp','light.pendant']},
  {building:'b',room:'blue',level:'L1',name:'Changing',area_id:'changing',lights:['light.blue']},
  {building:'b',room:'hall',level:'L1',name:'Hall',area_id:'hall',lights:[]}];
const layout = {available:true,rooms,devices:fixture.map(f => f.device),markers:fixture.filter(f => f.device.device_id !== 'pendant').map((f,i) => ({
  ...f.device, building:'b',level:'L1',room:'r',at:[i,1,2],placed:true,
}))};
const requests = [], alerts = [], calls = [], confirms = [];
let away = false, reachable = true, frozen = false, confirm = false;
window.showGlobalAlert = message => alerts.push(message);
window.promptConfirm = async (...args) => { confirms.push(args); return confirm; };
window.chfControlFetch = async (url, options) => {
  const call = JSON.parse(options.body); calls.push({url,...call});
  if (!frozen) {
    const state = states[call.data.entity_id];
    if (call.service === 'toggle') state.state = state.state === 'on' ? 'off' : 'on';
    if (call.data.brightness_pct !== undefined) state.attributes.brightness = call.data.brightness_pct * 255 / 100;
    if (call.data.temperature !== undefined) state.attributes.temperature = call.data.temperature;
  }
  return {ok:true,status:200};
};
const api = async path => { requests.push(path); return {ok:true,json:async () => structuredClone(path === 'api/house/live' ? layout : {states:away ? {} : states,reachable})}; };
const canvas = new Node('canvas'), host = new Node('main'); host.append(canvas); body.append(host);
const camera = new THREE.PerspectiveCamera(38,1.4,.1,1000); camera.position.set(0,50,0); camera.lookAt(0,0,0);
const level = new THREE.Group();
const view = {ready:true,scene:new THREE.Scene(),renderer3:{domElement:canvas},camera,controls:{target:new THREE.Vector3()},
  groups:{levels:{'b:L1':level}},plan:{buildings:[{id:'b',position:[100,50],rotation:90,base:2,levels:[{id:'L1',elevation:0}],rooms:rooms.map(r => ({id:r.room,level:'L1',polygon})),stairs:[]}]},
  pick: () => ({kind:'room',building:'b',id:'r'}), render() { this.live?.draw(); }};
const live = await mountLive(view,{api});
const row = id => document.getElementById('twin-room-panel').querySelectorAll('[data-device-id]').find(n => n.dataset.deviceId === id);
const button = (node, text) => node.querySelectorAll('button').find(n => n.textContent === text);
const toggle = id => row(id).querySelectorAll('button').find(n => n.getAttribute('role') === 'switch');
const click = async node => { assert.ok(node,'control exists'); node.dispatchEvent(new Event('click')); await new Promise(resolve => setTimeout(resolve,15)); };
const checks = [];
const check = (name, fn) => checks.push([name,fn]);

check('floor_tap_lists_area_devices_including_unplaced', async () => {
  for (const type of ['pointerdown','pointerup']) canvas.dispatchEvent(Object.assign(new Event(type), {clientX:5,clientY:5,pointerId:1}));
  const panel = document.getElementById('twin-room-panel');
  assert.equal(panel.hidden,false); assert.equal(panel.querySelectorAll('h2')[0].textContent,'Kitchen');
  assert.equal(panel.querySelectorAll('[data-device-id]').length,8); assert.ok(row('pendant')); assert.equal(row('blue'),undefined);
  assert.match(row('temp').textContent,/71.2/); assert.match(row('thermo').textContent,/70.*68/);
  assert.equal(calls.length,0);
});
check('controls_use_guarded_service_and_confirmed_state', async () => {
  assert.equal(toggle('lamp').getAttribute('aria-checked'),'true');
  await click(toggle('lamp')); assert.equal(calls.at(-1).url,'../api/ha/card/service');
  assert.equal(calls.at(-1).domain,'light'); assert.equal(calls.at(-1).service,'toggle');
  assert.equal(toggle('lamp').getAttribute('aria-checked'),'false'); assert.ok(requests.includes('api/ha/card/states?fresh=1'));
  frozen = true; await click(toggle('lamp')); assert.equal(toggle('lamp').getAttribute('aria-checked'),'false'); frozen = false;
  await click(toggle('fan')); assert.equal(calls.at(-1).domain,'fan');
  await click(button(row('thermo'),'Raise')); assert.equal(calls.at(-1).data.temperature,69);
  const slider = row('lamp').querySelectorAll('input')[0]; slider.value = '40'; slider.dispatchEvent(new Event('change'));
  await new Promise(resolve => setTimeout(resolve,15));
  assert.equal(calls.at(-1).service,'turn_on'); assert.equal(calls.at(-1).data.brightness_pct,40);
  assert.equal(row('lamp').querySelectorAll('input')[0].value,'40'); assert.equal(row('plug').querySelectorAll('input').length,0);
});
check('grid_and_explicit_lock_actions', async () => {
  assert.equal(row('lock').querySelectorAll('button,input').length,0); assert.match(row('lock').textContent,/locked/);
  assert.equal(row('garage').querySelectorAll('button,input').length,0);
  const lock = deviceActions({...layout.devices.find(d => d.kind === 'lock'),offered:true},null,async (...args) => calls.push(args));
  const before = calls.length; await click(button(lock,'Unlock')); assert.equal(calls.length,before); assert.equal(confirms.length,1);
  confirm = true; await click(button(lock,'Unlock')); assert.deepEqual(calls.at(-1),['lock.lock','unlock',{}]);
  await click(button(lock,'Lock')); assert.deepEqual(calls.at(-1),['lock.lock','lock',{}]); assert.equal(confirms.length,2);
  const garage = deviceActions({...layout.devices.find(d => d.kind === 'garage'),offered:true},null,async (...args) => calls.push(args));
  await click(button(garage,'Open')); assert.deepEqual(calls.at(-1),['cover.garage','open_cover',{}]);
});
check('a_smart_plug_outlet_toggles_like_a_switch', async () => {
  // Final review M1: a switch with device_class outlet is kind outlet; it keeps its On/Off control.
  const outlet = deviceActions({device_id:'kettle',name:'Kettle plug',entity_id:'switch.kettle',entities:['switch.kettle'],kind:'outlet',offered:true,area_id:'kitchen'},
    {state:'off',attributes:{device_class:'outlet'}},async (...args) => calls.push(args));
  const node = outlet.querySelectorAll('button').find(n => n.getAttribute('role') === 'switch');
  assert.ok(node, 'an outlet has the same On/Off switch a switch has');
  await click(node); assert.deepEqual(calls.at(-1),['switch.kettle','toggle',{}]);
});
check('lights_mode_builds_transformed_floor_glow_and_restores_all', async () => {
  states['light.lamp'] = {state:'on',attributes:{brightness:128}}; await live.refresh();
  const summary = live.rooms(); assert.ok(Math.abs(summary[0].glow - (128/255+1)/2)<.001);
  assert.equal(summary[1].glow,.6); assert.deepEqual(summary[1].rgb,[0,0,255]); assert.equal(summary[2].glow,0);
  const strip = document.getElementById('twin-modes'); await click(button(strip,'Lights'));
  assert.ok(live.markers().every(m => m.dim === (m.kind !== 'light')));
  const floors = view.scene.children.filter(n => n.children[0]?.isMesh);
  assert.equal(floors.length,3); assert.equal(floors.filter(n => n.visible).length,2);
  assert.ok(floors[0].children[0].material.opacity > .6); assert.deepEqual(floors[0].position.toArray(),[30.48,.6096,-15.24]);
  assert.ok(Math.abs(floors[0].rotation.y - Math.PI/2)<.001); assert.equal(floors[1].children[0].material.color.b,1);
  level.visible = false; live.draw(); assert.ok(floors.every(n => !n.visible)); level.visible = true;
  await click(button(strip,'All')); assert.ok(live.markers().every(m => !m.dim)); assert.ok(floors.every(n => !n.visible));
});
check('outage_keeps_state_and_blocks_room_control', async () => {
  const before = calls.length; away = true; await live.refresh();
  assert.ok(live.markers().every(m => m.stale && m.dim)); await click(toggle('lamp'));
  assert.equal(calls.length,before); assert.equal(alerts.at(-1),'Home Assistant is not reachable.');
  away = false; await live.refresh(); assert.ok(live.markers().every(m => !m.stale));
  reachable = false; await live.refresh(); assert.ok(live.markers().every(m => m.stale && m.dim));
  reachable = true; await live.refresh(); assert.ok(live.markers().every(m => !m.stale));
  document.dispatchEvent(Object.assign(new Event('keydown'),{key:'Escape'}));
  assert.equal(document.getElementById('twin-room-panel').hidden,true);
});
check('stop_disposes_modes_panel_and_subscriptions', async () => {
  live.stop(); assert.equal(document.getElementById('twin-room-panel'),undefined); assert.equal(document.getElementById('twin-modes'),undefined);
  assert.equal(view.scene.children.length,0);
  assert.deepEqual(roomStates(rooms,{}).map(r => r.glow),[0,0,0]);
});
let passed = 0;
try {
  for (const [name,fn] of checks) {
    try { await fn(); passed++; console.log('  ok   '+name); }
    catch(error) { console.error('  FAIL '+name, error); }
  }
} finally { live.stop(); }
console.log(`${passed}/${checks.length} passed`); process.exit(passed === checks.length ? 0 : 1);
"""


def run():
    node = shutil.which('node')
    if not node:
        print('skip: node is unavailable')
        return 0
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix()}))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix,
                                             prefix='chauffeur_room_js_', delete=False) as stream:
                paths.append(Path(stream.name))
                stream.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1])], capture_output=True,
                                text=True, encoding='utf-8', timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(run())
