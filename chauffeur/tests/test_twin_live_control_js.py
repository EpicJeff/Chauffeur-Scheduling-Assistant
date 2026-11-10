"""Node checks for the 3D house's shared control path and its poll loop (piece 3 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; Task 6 review
findings I1 and M3 in .superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-6-review.md).

static/twin/live/live.js mountLive(view, {api}) runs in node against a small fake
DOM (the same shape tests/test_twin_live_rooms_js.py uses); three resolves to the
vendored r187.

I1. The confirm before an unlock, an open or a disarm lives in the shared control
path, not in one surface's button. The hook: the object mountLive returns (the
page puts the same object on window.__twin.live, and Task 7's room panel calls it):

    live.control(entityId, service, data = {}) -> Promise<bool>

- control('lock.*', 'unlock'), control('cover.*', 'open_cover') and
  control('alarm_control_panel.*', 'alarm_disarm') call
  window.promptConfirm(title, message, okLabel, cancelLabel) exactly once, even
  with no sheet or panel open; the title or message names the device.
  Cancel (promptConfirm resolves false) sends nothing and resolves false;
  OK sends the service once through window.chfControlFetch.
- lock, close_cover, alarm_arm_home and a light's toggle ask nothing.
- The room panel's Unlock button (Task 7) asks once, not twice.

M3. One thrown exception inside a poll never stops the polls that follow:
- a subscriber (live.subscribe(listener)) that throws once: the next
  live.refresh() still asks api/ha/card/states and draws the new answer, and the
  10 s poll timer (a setTimeout of 10000 ms; this file captures those and fires
  them by hand) is armed again after the poll that threw;
- view.render() throwing once inside the frame a poll waits for: that refresh
  still settles (it does not hang) and the next one polls.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_live_control_js.py
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

// A throw inside a frame callback or a timer must not take node down: record it instead.
const escaped = [];
process.on('uncaughtException', error => escaped.push(String(error && error.message || error)));
process.on('unhandledRejection', error => escaped.push(String(error && error.message || error)));

class Node extends EventTarget {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.style = {}; this.attrs = {}; this.hidden = false; this.scrollTop = 0; this.text = ''; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(n => n.textContent).join(' '); }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  prepend(...nodes) { for (const node of nodes) node.parentElement = this; this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = []; this.text = ''; this.append(...nodes); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this); }
  get lastChild() { return this.children.at(-1); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  removeAttribute(key) { delete this.attrs[key]; }
  querySelectorAll(selector) {
    const matches = node => selector.split(',').map(s => s.trim()).some(s => s === '[data-device-id]' ? node.dataset.deviceId : s === node.tagName.toLowerCase());
    return this.children.flatMap(n => [...(matches(n) ? [n] : []), ...n.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest() { for (let n = this; n; n = n.parentElement) if (n.dataset.deviceId) return n; return null; }
  contains(node) { for (let n = node; n; n = n.parentElement) if (n === this) return true; return false; }
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

// The live layer's 10 s poll clock, captured so a check fires it by hand.
const realSetTimeout = globalThis.setTimeout, realClearTimeout = globalThis.clearTimeout;
let ticks = [];
// The live keeper's clocks (I2): pending[id] = {delay, callback}; clearTimeout drops one.
const pending = new Map();
let nextTimer = 1e6;
globalThis.setTimeout = (callback, delay, ...args) => {
  if (delay === 10000) { ticks.push(callback); return 0; }
  if (delay === 45000 || delay === 300000) { const id = ++nextTimer; pending.set(id, {delay, callback}); return id; }
  return realSetTimeout(callback, delay, ...args);
};
globalThis.clearTimeout = id => { if (pending.has(id)) pending.delete(id); else realClearTimeout(id); };
const armed = () => [...pending.values()].map(t => t.delay).sort();
async function fire(delay) {
  const [id, timer] = [...pending.entries()].find(([, t]) => t.delay === delay) || [];
  assert.ok(timer, `a ${delay} ms timer is armed: ${JSON.stringify(armed())}`);
  pending.delete(id); timer.callback();
  await wait(60);
}
const wait = ms => new Promise(resolve => realSetTimeout(resolve, ms));
const settles = (promise, ms = 2000) => Promise.race([
  Promise.resolve(promise).then(() => true, () => true), wait(ms).then(() => false)]);

const THREE = await import('three');
const {mountLive, keepLive} = await import(file('static/twin/live/live.js'));

const polygon = [[0,0],[10,0],[10,10],[0,10]];
const DEVICES = [
  {device_id:'lock', name:'Back door', entity_id:'lock.back_door', kind:'lock', state:'locked', attributes:{}},
  {device_id:'garage', name:'Garage door', entity_id:'cover.garage_door', kind:'garage', state:'closed', attributes:{device_class:'garage'}},
  {device_id:'alarm', name:'House alarm', entity_id:'alarm_control_panel.house', kind:'alarm', state:'armed_home', attributes:{}},
  {device_id:'lamp', name:'Counter lamp', entity_id:'light.counter_lamp', kind:'light', state:'off', attributes:{}},
];

async function mount({render} = {}) {
  ticks = [];
  const states = Object.fromEntries(DEVICES.map(d => [d.entity_id, {entity_id:d.entity_id, state:d.state, attributes:{...d.attributes}}]));
  const devices = DEVICES.map(d => ({device_id:d.device_id, name:d.name, entity_id:d.entity_id, entities:[d.entity_id],
    kind:d.kind, offered:true, area_id:'kitchen'}));
  const layout = {available:true,
    rooms:[{building:'b', room:'r', level:'L1', name:'Kitchen', area_id:'kitchen', lights:['light.counter_lamp']}],
    devices, markers:devices.map((d, i) => ({...d, building:'b', level:'L1', room:'r', at:[i * 3, 1, 2], placed:true}))};
  const t = {states, requests:[], calls:[], confirms:[], alerts:[], confirm:false};
  window.showGlobalAlert = message => t.alerts.push(message);
  window.promptConfirm = async (...args) => { t.confirms.push(args); return t.confirm; };
  window.chfControlFetch = async (url, options) => {
    const call = JSON.parse(options.body); t.calls.push({url, ...call});
    const row = states[call.data.entity_id];
    const next = {unlock:'unlocked', lock:'locked', open_cover:'open', close_cover:'closed',
      alarm_disarm:'disarmed', alarm_arm_home:'armed_home'}[call.service];
    if (row && next) row.state = next;
    if (row && call.service === 'toggle') row.state = row.state === 'on' ? 'off' : 'on';
    return {ok:true, status:200, json:async () => ({})};
  };
  const api = async path => {
    t.requests.push(path);
    return {ok:true, json:async () => structuredClone(path === 'api/house/live' ? layout : {states})};
  };
  const canvas = new Node('canvas'), host = new Node('main'); host.append(canvas); body.append(host);
  const camera = new THREE.PerspectiveCamera(38, 1.4, .1, 1000); camera.position.set(0, 50, 0); camera.lookAt(0, 0, 0);
  const view = {ready:true, scene:new THREE.Scene(), renderer3:{domElement:canvas}, camera, controls:{target:new THREE.Vector3()},
    groups:{levels:{'b:L1':new THREE.Group()}},
    plan:{buildings:[{id:'b', position:[0,0], rotation:0, base:0, levels:[{id:'L1', elevation:0}],
      rooms:[{id:'r', level:'L1', polygon}], stairs:[]}]},
    pick: () => ({kind:'room', building:'b', id:'r'}),
    render() { if (render) render(); this.live?.draw(); }};
  t.live = await mountLive(view, {api});
  assert.ok(t.live && typeof t.live.control === 'function', 'mountLive returns the live object with control()');
  t.cleanup = () => { try { t.live.stop(); } catch {} host.remove(); };
  return t;
}
const statePolls = t => t.requests.filter(p => p.startsWith('api/ha/card/states'));
const look = (t, id) => t.live.markers().find(m => m.device_id === id).look;

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('shared_control_confirms_unlock_open_and_disarm', async () => {
  const t = await mount();
  try {
    assert.equal(look(t, 'lock') === 'unavailable', false, 'the first poll was drawn');
    const asks = [['lock.back_door', 'unlock', 'Back door'], ['cover.garage_door', 'open_cover', 'Garage door'],
                  ['alarm_control_panel.house', 'alarm_disarm', 'House alarm']];
    // No sheet, no panel: the call comes straight into the shared path. Cancel sends nothing.
    t.confirm = false;
    for (const [entity, service, name] of asks) {
      const confirms = t.confirms.length, calls = t.calls.length;
      const result = await t.live.control(entity, service);
      assert.equal(t.confirms.length, confirms + 1,
        `live.control('${entity}', '${service}') asks promptConfirm first, even outside the sheet (asked ${t.confirms.length - confirms} times; sent ${t.calls.length - calls})`);
      assert.equal(t.calls.length, calls, `a cancelled ${service} sends nothing: ${JSON.stringify(t.calls.slice(calls))}`);
      assert.notEqual(result, true, `a cancelled ${service} does not report success`);
      const [title, message] = t.confirms.at(-1);
      assert.ok(typeof title === 'string' && `${title} ${message}`.includes(name),
        `the confirm names the device: ${JSON.stringify(t.confirms.at(-1))}`);
    }
    // OK: one confirm, then the service once.
    t.confirm = true;
    for (const [entity, service] of asks) {
      const confirms = t.confirms.length, calls = t.calls.length;
      await t.live.control(entity, service);
      assert.equal(t.confirms.length, confirms + 1, `${service}: one confirm`);
      assert.equal(t.calls.length, calls + 1, `${service}: sent once after OK`);
      const call = t.calls.at(-1);
      assert.equal(call.domain, entity.split('.')[0]); assert.equal(call.service, service);
      assert.equal(call.data.entity_id, entity);
    }
    // Locking, closing, arming and a light's toggle ask nothing.
    t.confirm = false;
    for (const [entity, service] of [['lock.back_door', 'lock'], ['cover.garage_door', 'close_cover'],
                                     ['alarm_control_panel.house', 'alarm_arm_home'], ['light.counter_lamp', 'toggle']]) {
      const confirms = t.confirms.length, calls = t.calls.length;
      await t.live.control(entity, service);
      assert.equal(t.confirms.length, confirms, `${entity} ${service} asks nothing`);
      assert.equal(t.calls.length, calls + 1, `${entity} ${service} is sent`);
    }
  } finally { t.cleanup(); }
});

check('room_panel_unlock_asks_once', async () => {
  const t = await mount();
  try {
    t.live.openRoom('b', 'r');
    const panel = document.getElementById('twin-room-panel');
    assert.ok(panel && !panel.hidden, 'the Kitchen room panel opens');
    const row = panel.querySelectorAll('[data-device-id]').find(n => n.dataset.deviceId === 'lock');
    assert.ok(row, 'the panel lists the lock');
    const unlock = row.querySelectorAll('button').find(n => n.textContent === 'Unlock');
    assert.ok(unlock, 'the offered lock has an Unlock button in the room panel');
    t.confirm = true;
    unlock.dispatchEvent(new Event('click'));
    await wait(60);
    assert.equal(t.confirms.length, 1, `Unlock in the room panel asks once, not twice (${t.confirms.length})`);
    assert.equal(t.calls.filter(c => c.service === 'unlock').length, 1, 'and sends lock.unlock once');
  } finally { t.cleanup(); }
});

check('a_throwing_listener_does_not_stop_later_polls', async () => {
  const t = await mount();
  try {
    assert.equal(look(t, 'lamp'), 'off');
    let boom = 0;
    t.live.subscribe(() => { if (boom) { boom--; throw new Error('a room listener broke'); } });

    // A direct refresh whose listener throws; the next refresh still polls and draws.
    boom = 1;
    await settles(t.live.refresh());
    t.states['light.counter_lamp'].state = 'on';
    const before = statePolls(t).length;
    assert.ok(await settles(t.live.refresh()), 'the next refresh settles');
    assert.ok(statePolls(t).length > before, `the next refresh asks api/ha/card/states again (${statePolls(t).length - before} new polls)`);
    assert.equal(look(t, 'lamp'), 'on', 'and draws the new answer');

    // The 10 s clock: the poll that throws still arms the next one, and that one polls.
    assert.ok(ticks.length >= 1, 'the 10 s poll is scheduled after mounting');
    boom = 1;
    const armed = ticks.length;
    await settles(Promise.resolve().then(() => ticks.at(-1)()));
    await wait(30);
    assert.ok(ticks.length > armed, `a poll that threw arms the next 10 s poll (${ticks.length - armed} armed)`);
    t.states['light.counter_lamp'].state = 'off';
    const polls = statePolls(t).length;
    await settles(Promise.resolve().then(() => ticks.at(-1)()));
    await wait(30);
    assert.ok(statePolls(t).length > polls, 'the next 10 s poll asks again');
    assert.equal(look(t, 'lamp'), 'off', 'and draws its answer');
  } finally { t.cleanup(); }
});

check('a_throwing_frame_does_not_hang_polling', async () => {
  let boom = 0;
  const t = await mount({render: () => { if (boom) { boom--; throw new Error('render broke'); } }});
  try {
    boom = 1;
    assert.ok(await settles(t.live.refresh()), 'a refresh whose frame throws still settles (it never hangs)');
    t.states['light.counter_lamp'].state = 'on';
    const before = statePolls(t).length;
    assert.ok(await settles(t.live.refresh()), 'the next refresh settles');
    assert.ok(statePolls(t).length > before, 'the next refresh asks api/ha/card/states again');
    assert.equal(look(t, 'lamp'), 'on', 'and draws the new answer');
  } finally { t.cleanup(); }
});

// ---------------------------------------------------------------- final review I2
// A wall that loaded while Home Assistant was down recovers with no reload, and a mounted
// layer re-reads the layout on a slow clock; one timer at a time; stop ends it.
function keeperRig() {
  pending.clear();
  const t = {available: false, failing: false, requests: [], extra: false};
  const devices = DEVICES.map(d => ({device_id:d.device_id, name:d.name, entity_id:d.entity_id, entities:[d.entity_id],
    kind:d.kind, offered:true, area_id:'kitchen'}));
  const states = Object.fromEntries(DEVICES.map(d => [d.entity_id, {entity_id:d.entity_id, state:d.state, attributes:{...d.attributes}}]));
  const layout = () => {
    const rows = t.extra ? [...devices, {device_id:'fan', name:'Ceiling fan', entity_id:'fan.ceiling', entities:['fan.ceiling'],
      kind:'fan', offered:true, area_id:'kitchen'}] : devices;
    return {available:t.available, rooms:[{building:'b', room:'r', level:'L1', name:'Kitchen', area_id:'kitchen', lights:[]}],
      devices:t.available ? rows : [],
      markers:t.available ? rows.map((d, i) => ({...d, building:'b', level:'L1', room:'r', at:[i * 3, 1, 2], placed:true})) : []};
  };
  t.api = async path => {
    t.requests.push(path);
    if (t.failing) throw new TypeError('Failed to fetch');
    return {ok:true, json:async () => structuredClone(path === 'api/house/live' ? layout() : {states})};
  };
  const canvas = new Node('canvas'), host = new Node('main'); host.append(canvas); body.append(host);
  const camera = new THREE.PerspectiveCamera(38, 1.4, .1, 1000); camera.position.set(0, 50, 0); camera.lookAt(0, 0, 0);
  t.view = {ready:true, scene:new THREE.Scene(), renderer3:{domElement:canvas}, camera, controls:{target:new THREE.Vector3()},
    groups:{levels:{'b:L1':new THREE.Group()}},
    plan:{buildings:[{id:'b', position:[0,0], rotation:0, base:0, levels:[{id:'L1', elevation:0}],
      rooms:[{id:'r', level:'L1', polygon}], stairs:[]}]},
    pick: () => ({kind:'room', building:'b', id:'r'}), render() { this.live?.draw(); }};
  t.layoutReads = () => t.requests.filter(p => p === 'api/house/live').length;
  t.cleanup = () => { try { t.keeper?.stop(); } catch {} try { t.view.live?.stop(); } catch {} host.remove(); pending.clear(); };
  return t;
}

check('i2_keeper_retries_until_home_assistant_answers', async () => {
  assert.equal(typeof keepLive, 'function', 'live.js exports keepLive(view, {api})');
  const t = keeperRig();
  try {
    t.keeper = keepLive(t.view, {api: t.api});
    await wait(60);
    assert.ok(!t.view.live, 'Home Assistant away at load: no layer');
    assert.deepEqual(armed(), [45000], 'one retry armed, 45 s out');
    t.failing = true;
    await fire(45000);
    assert.ok(!t.view.live, 'a failed read is no layer either');
    assert.deepEqual(armed(), [45000], 'and the next retry is armed, never two');
    t.failing = false; t.available = true;
    await fire(45000);
    assert.ok(t.view.live, 'Home Assistant back: the layer mounts with no reload');
    assert.equal(t.view.live.markers().length, DEVICES.length, 'with its markers');
    assert.deepEqual(armed(), [300000], 'mounted: only the slow layout re-read is armed');
    await t.keeper.check(); await t.keeper.check();
    assert.deepEqual(armed(), [300000], 'an extra check never doubles the clock');
    t.keeper.stop();
    assert.deepEqual(armed(), [], 'stop clears the clock');
  } finally { t.cleanup(); }
});

check('i2_keeper_rereads_the_layout_and_remounts_only_on_change', async () => {
  const t = keeperRig();
  t.available = true;
  try {
    t.keeper = keepLive(t.view, {api: t.api});
    await wait(60);
    const first = t.view.live;
    assert.ok(first, 'mounted');
    let reads = t.layoutReads();
    await fire(300000);
    assert.equal(t.layoutReads(), reads + 1, 'the slow clock reads the layout once');
    assert.equal(t.view.live, first, 'an unchanged layout keeps the layer (an open room stays open)');
    assert.deepEqual(armed(), [300000]);
    // A device placed in the editor today: the next re-read draws it.
    t.extra = true; reads = t.layoutReads();
    await fire(300000);
    assert.notEqual(t.view.live, first, 'a changed layout remounts');
    assert.equal(t.layoutReads(), reads + 1, 'one read: the remount uses the layout it read');
    assert.ok(t.view.live.markers().some(m => m.device_id === 'fan'), 'the new device has its marker');
    assert.equal(first.markers().length, DEVICES.length, 'the old layer was left as it was');
    assert.deepEqual(armed(), [300000]);
    // Home Assistant away at a re-read: the layer stays (its poll already dims it).
    const second = t.view.live; t.failing = true;
    await fire(300000);
    assert.equal(t.view.live, second, 'a failed re-read keeps the layer');
    assert.deepEqual(armed(), [300000]);
  } finally { t.cleanup(); }
});

check('i2_keeper_stopped_mid_mount_leaves_no_layer', async () => {
  const t = keeperRig();
  t.available = true;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const slow = t.api;
  t.api = async (path, options) => { if (path === 'api/house/live') await gate; return slow(path, options); };
  try {
    t.keeper = keepLive(t.view, {api: t.api});
    await wait(20);
    t.keeper.stop();
    release(); await wait(80);
    assert.ok(!t.view.live, 'a page that left while the layer mounted keeps no layer');
    assert.deepEqual(armed(), [], 'and no clock');
  } finally { t.cleanup(); }
});

let passed = 0;
for (const [name, fn] of checks) {
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 500)); }
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
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_live_control_',
                                             delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1])], capture_output=True, text=True,
                                encoding='utf-8', timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
