"""Node checks for the 3D house's live layer hearing Home Assistant's pushed state
(Task 2 of docs/superpowers/plans/2026-11-11-twin-device-controls.md; spec
docs/superpowers/specs/2026-11-11-twin-device-controls-design.md decision 5;
Review Focus 1).

static/twin/live/live.js mountLive(view, {api}) runs in node against the same
small fake DOM tests/test_twin_live_control_js.py uses; three resolves to the
vendored r187.

The hook assumed (kept to the browser's own API, nothing new to pass in):
- When `EventSource` exists, mountLive opens ONE
  `new EventSource(url)` where url is
  `window.chfAuthUrl(base() + 'api/ha/stream?entities=<ids joined by ",">')`
  (chfAuthUrl when the page has it: EventSource cannot set headers, so the
  wall's token rides the query). The ids are every entity the layer draws.
- Each message (`onmessage` or a 'message' listener; unnamed SSE events) has
  `data` = JSON `{entity_id, state}` where state is HA's state object (or null).
  The layer applies it to its states and redraws at once, without asking
  api/ha/card/states. An id the layer does not draw, or data that is not JSON,
  changes nothing and throws nothing.
- The 10 s poll stays armed with the stream up, and is the only path once the
  stream errors or closes; a dropped stream is not Home Assistant being away,
  so the markers do not go stale over it. live.stop() closes the EventSource.
- With no `EventSource` (the existing node tests), the layer behaves as today.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_live_stream_js.py
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

// A throw inside a frame callback, a timer or a stream handler must not take node down: record it.
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
// The wall's token rides the query, exactly as nav.html's chfAuthUrl does it.
window.chfAuthUrl = url => url + (url.includes('?') ? '&' : '?') + 'device_token=panel-tok';

// The browser's EventSource, faked: every one opened is kept so a check can push or drop it.
const sources = [];
class FakeEventSource extends EventTarget {
  static CONNECTING = 0; static OPEN = 1; static CLOSED = 2;
  constructor(url, init) {
    super(); this.url = String(url); this.init = init; this.readyState = 1; this.closed = false;
    this.onmessage = null; this.onerror = null; this.onopen = null; sources.push(this);
  }
  close() { this.closed = true; this.readyState = 2; }
  emit(data) {
    if (this.closed) return;
    const event = new Event('message'); event.data = typeof data === 'string' ? data : JSON.stringify(data);
    if (typeof this.onmessage === 'function') this.onmessage(event);
    this.dispatchEvent(event);
  }
  fail() {
    this.readyState = 2;
    const event = new Event('error');
    if (typeof this.onerror === 'function') this.onerror(event);
    this.dispatchEvent(event);
  }
}
globalThis.EventSource = FakeEventSource;
window.EventSource = FakeEventSource;

// The live layer's 10 s poll clock, captured so a check fires it by hand.
const realSetTimeout = globalThis.setTimeout;
let ticks = [];
globalThis.setTimeout = (callback, delay, ...args) => {
  if (delay === 10000) { ticks.push(callback); return 0; }
  return realSetTimeout(callback, delay, ...args);
};
const wait = ms => new Promise(resolve => realSetTimeout(resolve, ms));
const settles = (promise, ms = 2000) => Promise.race([
  Promise.resolve(promise).then(() => true, () => true), wait(ms).then(() => false)]);

const THREE = await import('three');
const {mountLive} = await import(file('static/twin/live/live.js'));

const polygon = [[0,0],[10,0],[10,10],[0,10]];
const DEVICES = [
  {device_id:'lock', name:'Back door', entity_id:'lock.back_door', kind:'lock', state:'locked', attributes:{}},
  {device_id:'garage', name:'Garage door', entity_id:'cover.garage_door', kind:'garage', state:'closed', attributes:{device_class:'garage'}},
  {device_id:'lamp', name:'Counter lamp', entity_id:'light.counter_lamp', kind:'light', state:'off', attributes:{}},
];

async function mount() {
  ticks = []; sources.length = 0; escaped.length = 0;
  const states = Object.fromEntries(DEVICES.map(d => [d.entity_id, {entity_id:d.entity_id, state:d.state, attributes:{...d.attributes}}]));
  const devices = DEVICES.map(d => ({device_id:d.device_id, name:d.name, entity_id:d.entity_id, entities:[d.entity_id],
    kind:d.kind, offered:true, area_id:'kitchen'}));
  const layout = {available:true,
    rooms:[{building:'b', room:'r', level:'L1', name:'Kitchen', area_id:'kitchen', lights:['light.counter_lamp']}],
    devices, markers:devices.map((d, i) => ({...d, building:'b', level:'L1', room:'r', at:[i * 3, 1, 2], placed:true}))};
  const t = {states, requests:[], calls:[], alerts:[]};
  window.showGlobalAlert = message => t.alerts.push(message);
  window.promptConfirm = async () => true;
  window.chfControlFetch = async (url, options) => {
    const call = JSON.parse(options.body); t.calls.push({url, ...call});
    const row = states[call.data.entity_id];
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
    render() { this.live?.draw(); }};
  t.live = await mountLive(view, {api});
  assert.ok(t.live, 'mountLive mounts');
  t.cleanup = () => { try { t.live.stop(); } catch {} host.remove(); };
  return t;
}
const statePolls = t => t.requests.filter(p => p.startsWith('api/ha/card/states'));
const marker = (t, id) => t.live.markers().find(m => m.device_id === id);
const look = (t, id) => marker(t, id).look;

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('live_layer_subscribes_and_updates_without_waiting_for_the_poll', async () => {
  const t = await mount();
  try {
    assert.equal(look(t, 'lamp'), 'off', 'the first poll was drawn');
    assert.equal(sources.length, 1, `the layer opens one stream (${sources.length})`);
    const es = sources[0];
    assert.ok(!es.closed, 'and leaves it open');
    const url = new URL(es.url, 'http://house.test/twin/');
    assert.ok(url.pathname.endsWith('/api/ha/stream'), `the stream route: ${es.url}`);
    assert.ok(es.url.startsWith('../api/ha/stream?'), `fetched page-relative through base(), never root-relative: ${es.url}`);
    const asked = (url.searchParams.get('entities') || '').split(',').filter(Boolean).sort();
    assert.deepEqual(asked, DEVICES.map(d => d.entity_id).sort(), `it asks for exactly the entities it draws: ${es.url}`);
    assert.equal(url.searchParams.get('device_token'), 'panel-tok', `the wall's token rides the query: ${es.url}`);
    assert.ok(ticks.length >= 1, 'the 10 s poll stays armed with the stream up');

    let heard = 0;
    t.live.subscribe(() => { heard++; });
    const polls = statePolls(t).length, armed = ticks.length;
    es.emit({entity_id:'light.counter_lamp', state:{entity_id:'light.counter_lamp', state:'on', attributes:{brightness:180}}});
    await wait(60);
    assert.equal(look(t, 'lamp'), 'on', 'the pushed state is drawn at once');
    assert.equal(t.live.states()['light.counter_lamp']?.attributes?.brightness, 180, 'and kept with its attributes');
    assert.ok(heard >= 1, 'listeners (the room panel, the modes) hear it');
    assert.equal(statePolls(t).length, polls, `without asking api/ha/card/states (${statePolls(t).length - polls} polls)`);
    assert.equal(ticks.length, armed, 'and without firing the 10 s clock');

    es.emit({entity_id:'lock.back_door', state:{entity_id:'lock.back_door', state:'unlocked', attributes:{}}});
    await wait(60);
    assert.equal(look(t, 'lock'), 'attention', 'an unlocked lock shows at once');

    // Somebody else's device, and a garbled line: nothing changes and nothing throws.
    const before = JSON.stringify(t.live.markers().map(m => [m.device_id, m.look, m.label]));
    es.emit({entity_id:'light.elsewhere', state:{entity_id:'light.elsewhere', state:'on', attributes:{}}});
    es.emit('not json at all');
    es.emit({entity_id:'light.counter_lamp'});
    await wait(60);
    assert.equal(JSON.stringify(t.live.markers().map(m => [m.device_id, m.look, m.label])), before,
      'an id the layer does not draw, or a malformed message, changes nothing');
    assert.deepEqual(escaped, [], 'and throws nothing');

    // The layer is stopped: its stream goes with it.
    t.live.stop();
    assert.ok(es.closed, 'live.stop() closes the stream');
  } finally { t.cleanup(); }
});

check('live_layer_falls_back_to_poll_when_stream_drops', async () => {
  const t = await mount();
  try {
    assert.equal(look(t, 'lamp'), 'off');
    const es = sources.at(-1);
    assert.ok(es, 'a stream was opened');
    es.fail();
    await wait(30);
    assert.equal(marker(t, 'lamp').stale, false, 'a dropped stream is not Home Assistant away: the markers stay live');
    assert.deepEqual(t.alerts, [], 'and nobody is told anything');

    // The change arrives the old way: the next 10 s poll.
    t.states['light.counter_lamp'].state = 'on';
    assert.ok(ticks.length >= 1, 'the 10 s poll is still armed');
    const polls = statePolls(t).length, armed = ticks.length;
    assert.ok(await settles(Promise.resolve().then(() => ticks.at(-1)())), 'the poll settles');
    await wait(60);
    assert.ok(statePolls(t).length > polls, 'the 10 s poll asks api/ha/card/states');
    assert.equal(look(t, 'lamp'), 'on', 'and draws its answer');
    assert.ok(ticks.length > armed, 'and arms the next one');

    // A control while the stream is down (Review Focus 1): confirmed through the poll, nothing hangs.
    let result;
    assert.ok(await settles(t.live.control('light.counter_lamp', 'toggle').then(r => { result = r; })),
      'a toggle with the stream down settles');
    assert.equal(result, true, 'and reports success');
    assert.equal(t.calls.filter(c => c.service === 'toggle').length, 1, 'sent once');
    assert.ok(statePolls(t).some(p => p.includes('fresh=1')), 'confirmed by a fresh poll');
    assert.equal(look(t, 'lamp'), 'off', 'the marker shows the confirmed state');
    assert.deepEqual(escaped, [], 'nothing threw');
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
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_live_stream_',
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
