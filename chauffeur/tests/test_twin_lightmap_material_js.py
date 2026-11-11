"""Room-light material, texture formats and worker-cache checks in node.

Fixed room/slot tint textures toggle lights without recompiles. The material
adds room irradiance through uv3/lmRoom, preserves three's ambient term and
has no sky uniforms. Desktop BC5, Pi EAC RG11 and RGBA fallback preserve both
room-light channels. Worker transport matches the direct atlas, cached
geometry is applied only when ready, and IndexedDB keeps the last two atlases.
The live rig keeps lights real-time until their room bake is fresh.

Run from chauffeur/: python tests/test_twin_lightmap_material_js.py [check-name] (HA_BASE_URL unset).
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_lightmap_js_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402
from services import twin_store  # noqa: E402

HOUSEHOLD = os.path.join(ROOT, 'tests', 'fixtures', 'twin_model', 'household-2026-11-09.json')
LAYOUT = {'room': {'density': 1, 'page': 256, 'gutter': 2}}
POOL = 'pool-house'

DRIVER = r"""
import assert from 'node:assert/strict';
import { registerHooks, createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
const job = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const file = p => pathToFileURL(job.root + '/' + p).href;
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === 'three') return { url: file('static/vendor/three-r187/three.module.js'), shortCircuit: true };
    if (spec.startsWith('three/addons/')) return { url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true };
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    const bare = url.split('?')[0];
    if (!(bare.startsWith('file:') && bare.endsWith('.js')) || /basis/i.test(bare)) return next(url, ctx);
    const loaded = next(url, { ...ctx, format: 'module' });
    const worker = new URL(url).searchParams.get('__w');
    if (!worker) return { ...loaded, format: 'module' };
    // A fake worker's module: its own `self` (the worker scope), as a real worker has.
    const source = typeof loaded.source === 'string' ? loaded.source : new TextDecoder().decode(loaded.source);
    return { ...loaded, format: 'module', source: `const self = globalThis.__workerScopes[${JSON.stringify(worker)}];\n` + source };
  },
});

// --- a DOM just big enough for the live layer (tests/test_twin_real_lights_js.py's) -------------
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
const require = createRequire(import.meta.url);
const quiet = { print() {}, printErr() {} };
const E = await require(job.root + '/static/vendor/basis-universal/basis_encoder.js')({ ...quiet, wasmBinary: readFileSync(job.root + '/static/vendor/basis-universal/basis_encoder.wasm') });
const T = await require(job.root + '/static/vendor/three-r187/addons/libs/basis/basis_transcoder.js')({ ...quiet, wasmBinary: readFileSync(job.root + '/static/vendor/three-r187/addons/libs/basis/basis_transcoder.wasm') });
E.initializeBasis(); T.initializeBasis();
const gen = await import(file('static/twin/twin_generator.js'));
const { buildAtlas } = await import(file('static/twin/bake/atlas.js'));
const { mountLive } = await import(file('static/twin/live/live.js'));
const LM_URL = file('static/twin/bake/lightmap_material.js');
let M = null, missing = null;
try { M = await import(LM_URL); }
catch (error) { missing = String(error && error.message || error).split('\n')[0]; }
const need = (...names) => {
  assert.ok(M, `static/twin/bake/lightmap_material.js is missing or does not load: ${missing}`);
  for (const name of names) assert.equal(typeof M[name], 'function', `lightmap_material.js exports ${name}`);
};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const withTimeout = (p, ms, what) => Promise.race([p, sleep(ms).then(() => { throw new Error(`${what} did not settle in ${ms} ms`); })]);
const FT = .3048;

// --- the live layer's fixture (tests/test_twin_real_lights_js.py's house) ----------------------
const square = (x0, y0, x1, y1) => [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
const roomsPlan = [{id:'A',level:'L1',polygon:square(0,0,20,10)}, {id:'B',level:'L1',polygon:square(40,0,50,10)},
  {id:'C',level:'L1',polygon:square(0,30,10,40)}];
const fx = (id, room, at, state, attrs = {}) => ({id, room, at, entity:`light.${id}`, kind:'light', state, attrs});
const fixture = [
  fx('a1','A',[2,2,9],'on',{brightness:255}),
  fx('a2','A',[6,5,9],'on',{brightness:128}),
  fx('a3','A',[10,5,9],'on',{brightness:200,rgb_color:[255,0,0],color_mode:'rgb'}),
  fx('a4','A',[14,5,9],'on',{brightness:255,color_temp_kelvin:2700,color_mode:'color_temp'}),
  fx('b1','B',[42,5,9],'on',{brightness:255}),
  fx('b2','B',[48,5,9],'on',{brightness:64}),
  fx('c1','C',[5,35,9],'off',{}),
];
const initialStates = () => Object.fromEntries(fixture.map(f => [f.entity, {state:f.state, attributes:structuredClone(f.attrs)}]));
let states = initialStates();
const area = room => ({A:'area_a',B:'area_b',C:'area_c'})[room];
const layout = {available:true,
  rooms: roomsPlan.map(r => ({building:'b',room:r.id,level:'L1',name:'Room '+r.id,area_id:area(r.id),
    lights: fixture.filter(f => f.room === r.id).map(f => f.entity)})),
  devices: fixture.map(f => ({device_id:f.id,name:f.id,entity_id:f.entity,entities:[f.entity],kind:f.kind,offered:true,area_id:area(f.room)})),
  markers: fixture.map(f => ({device_id:f.id,name:f.id,entity_id:f.entity,entities:[f.entity],kind:f.kind,offered:true,
    area_id:area(f.room),building:'b',level:'L1',room:f.room,at:f.at,placed:true}))};
const liveApi = async path => ({ok:true,json:async () => structuredClone(path === 'api/house/live' ? layout : {states,reachable:true})});
function makeView(tier, bake) {
  const canvas = new Node('canvas'), host = new Node('main'); host.append(canvas); body.append(host);
  const camera = new THREE.PerspectiveCamera(38,1.4,.1,1000); camera.position.set(8*FT,50*FT,-5*FT); camera.lookAt(8*FT,0,-5*FT);
  const view = {ready:true,tier,scene:new THREE.Scene(),renderer3:{domElement:canvas,shadowMap:{enabled:tier !== 'low'}},camera,
    controls:{target:new THREE.Vector3(8*FT,0,-5*FT)},groups:{levels:{'b:L1':new THREE.Group()}},
    plan:{buildings:[{id:'b',position:[0,0],rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:10}],rooms:roomsPlan,stairs:[]}]},
    pick: () => null, render() { this.live?.draw(); }, setEvening() {}};
  if (bake) view.bake = bake;
  return view;
}
function fakeBake(fresh = []) {
  const calls = [], set = new Set(fresh);
  return { calls, set, fresh: () => [...set], light(device, rgb, intensity) { calls.push({ device, rgb: [...rgb], intensity }); },
    state: () => ({ key: null, baking: false, paused: false, done: 0, total: 0, baked: [], stale: [] }) };
}
const lastCall = (bake, device) => [...bake.calls].reverse().find(c => c.device === device) || null;
const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
const pool = view => { const out = []; view.scene.traverse(o => { if (o.isPointLight) out.push(o); }); return out; };
const tagged = (view, key) => { const out = []; view.scene.traverse(o => { if (o.userData && o.userData[key] !== undefined) out.push(o); }); return out; };
const markerSpot = (view, id) => { let spot = null; view.scene.traverse(o => { if (o.isSprite && o.userData.deviceId === id) spot = o.getWorldPosition(new THREE.Vector3()); }); return spot; };
const lampAt = (view, id) => {
  const spot = markerSpot(view, id); assert.ok(spot, `the marker sprite of ${id}`);
  return pool(view).filter(l => l.intensity > 0 && shown(l)).find(l => {
    const p = l.getWorldPosition(new THREE.Vector3());
    return Math.abs(p.x - spot.x) < .05 && Math.abs(p.z - spot.z) < .05 && p.y <= spot.y + .05 && p.y >= spot.y - FT - .05;
  }) || null;
};
const row = (live, id) => live.lights().find(r => r.device === id) || null;
const realSet = live => live.lights().filter(r => r.real).map(r => r.device).sort();
const bakedSet = live => live.lights().filter(r => r.baked === true).map(r => r.device).sort();
const washShown = (view, room) => tagged(view, 'lightWash').filter(o => o.userData.lightWash.room === room).some(shown);
const bulb = (view, id) => tagged(view, 'bulb').filter(o => o.userData.bulb === id);
async function mounted(tier, bake) {
  states = initialStates();
  const view = makeView(tier, bake);
  const live = await mountLive(view, {api: liveApi});
  assert.ok(live, 'the live layer mounts on the fake view');
  return {view, live};
}

// --- a module Worker and IndexedDB, faked ------------------------------------------------------
const ErrorEv = globalThis.ErrorEvent || class extends Event { constructor(type, init = {}) { super(type); Object.assign(this, init); } };
const WORKERS = [];
let workerCount = 0;
globalThis.__workerScopes = {};
class FakeWorker extends EventTarget {
  constructor(url, options) {
    super();
    const n = String(++workerCount);
    this.url = url instanceof URL ? url.href : new URL(String(url), LM_URL).href;
    this.options = options; this.posted = []; this.onmessage = null; this.onerror = null;
    WORKERS.push(this);
    const scope = new EventTarget();
    scope.onmessage = null;
    scope.postMessage = (data, transfer) => {
      const list = Array.isArray(transfer) ? transfer : transfer?.transfer || [];
      const copy = structuredClone(data, { transfer: list });
      setImmediate(() => this.deliver(copy));
    };
    scope.close = () => {};
    globalThis.__workerScopes[n] = scope; this.scope = scope;
    const target = new URL(this.url); target.searchParams.set('__w', n);
    this.loaded = import(target.href).catch(error => { setImmediate(() => this.fail(error)); throw error; });
  }
  postMessage(data, transfer) {
    const list = Array.isArray(transfer) ? transfer : transfer?.transfer || [];
    this.posted.push({ data, transfer: list });
    this.receive(structuredClone(data, { transfer: list }));
  }
  receive(copy) {
    this.loaded.then(() => {
      const event = new MessageEvent('message', { data: copy });
      return Promise.resolve().then(() => this.scope.onmessage?.(event)).then(() => this.scope.dispatchEvent(event));
    }).catch(error => this.fail(error));
  }
  deliver(data) { if (this.terminated) return; const event = new MessageEvent('message', { data }); this.onmessage?.(event); this.dispatchEvent(event); }
  fail(error) { if (this.terminated) return; const event = new ErrorEv('error', { error, message: String(error && error.message || error) }); this.onerror?.(event); this.dispatchEvent(event); }
  terminate() { this.terminated = true; }
}
class HeldWorker extends FakeWorker { receive() {} }                       // never answers
class ErrorWorker extends FakeWorker { receive() { setImmediate(() => this.fail(new Error('the worker died'))); } }
class NoWorker { constructor() { throw new Error('this screen has no workers'); } }

function fakeIndexedDB() {
  const dbs = new Map(), log = { puts: 0, gets: 0, opens: 0 };
  const later = f => setImmediate(f);
  const keyOf = k => typeof k === 'string' ? 's:' + k : 'j:' + JSON.stringify(k);
  class Req extends EventTarget {
    constructor(source = null, transaction = null) {
      super(); this.result = undefined; this.error = null; this.readyState = 'pending'; this.source = source; this.transaction = transaction;
      for (const type of ['success', 'error', 'upgradeneeded', 'blocked']) this.addEventListener(type, e => this['on' + type]?.(e));
    }
    succeed(value) { this.result = value; this.readyState = 'done'; this.dispatchEvent(new Event('success')); }
  }
  function connection(name) {
    const db = dbs.get(name);
    const names = () => [...db.stores.keys()];
    const conn = new EventTarget();
    Object.assign(conn, {
      name, get version() { return db.version; },
      get objectStoreNames() { const list = names(); return Object.assign([...list], { contains: n => list.includes(n), item: i => list[i] ?? null }); },
      createObjectStore(store, options = {}) { db.stores.set(store, { keyPath: options.keyPath ?? null, data: new Map() }); return storeHandle(store, null); },
      deleteObjectStore(store) { db.stores.delete(store); },
      transaction(storeNames, mode = 'readonly') {
        const tx = new EventTarget(); let pending = 0, finished = false;
        for (const type of ['complete', 'error', 'abort']) tx.addEventListener(type, e => tx['on' + type]?.(e));
        tx.mode = mode; tx.db = conn; tx.error = null;
        const settle = () => later(() => { if (!pending && !finished) { finished = true; tx.dispatchEvent(new Event('complete')); } });
        tx.track = run => { pending++; later(() => { run(); pending--; settle(); }); };
        tx.objectStore = store => storeHandle(store, tx);
        tx.commit = () => {}; tx.abort = () => { finished = true; tx.dispatchEvent(new Event('abort')); };
        settle();
        return tx;
      },
      close() {},
    });
    function storeHandle(storeName, tx) {
      const store = () => { const s = db.stores.get(storeName); if (!s) throw new Error(`no object store ${storeName}`); return s; };
      const op = fn => { const req = new Req(null, tx); const run = () => req.succeed(fn()); if (tx) tx.track(run); else later(run); return req; };
      const keyFor = (value, key) => key !== undefined ? key : store().keyPath ? value[store().keyPath] : undefined;
      return {
        name: storeName, get keyPath() { return store().keyPath; },
        put(value, key) { log.puts++; const k = keyFor(value, key), copy = structuredClone(value); return op(() => { store().data.set(keyOf(k), copy); return k; }); },
        add(value, key) { return this.put(value, key); },
        get(key) { log.gets++; return op(() => { const v = store().data.get(keyOf(key)); return v === undefined ? undefined : structuredClone(v); }); },
        getAll() { return op(() => [...store().data.values()].map(v => structuredClone(v))); },
        getAllKeys() { return op(() => [...store().data.keys()].map(k => k.startsWith('s:') ? k.slice(2) : JSON.parse(k.slice(2)))); },
        count() { return op(() => store().data.size); },
        delete(key) { return op(() => { store().data.delete(keyOf(key)); }); },
        clear() { return op(() => { store().data.clear(); }); },
      };
    }
    return conn;
  }
  return {
    log, records: () => [...dbs.values()].reduce((n, db) => n + [...db.stores.values()].reduce((m, s) => m + s.data.size, 0), 0),
    open(name, version) {
      log.opens++;
      const req = new Req();
      later(() => {
        const old = dbs.get(name)?.version || 0, next = version || Math.max(1, old);
        if (!dbs.has(name)) dbs.set(name, { version: 0, stores: new Map() });
        const conn = connection(name);
        req.result = conn;
        if (next > old) {
          dbs.get(name).version = next;
          const tx = conn.transaction([], 'versionchange'); req.transaction = tx;
          const event = new Event('upgradeneeded'); Object.assign(event, { oldVersion: old, newVersion: next });
          req.dispatchEvent(event);
        }
        later(() => req.succeed(conn));
      });
      return req;
    },
    deleteDatabase(name) { const req = new Req(); later(() => { dbs.delete(name); req.succeed(undefined); }); return req; },
  };
}

// --- the house for the atlas ---------------------------------------------------------------------
async function house() {
  const out = gen.buildTwin(job.plan, job.kit, 'high');
  await out.ready; out.root.updateMatrixWorld(true);
  return out.root;
}
const covered = root => { const list = []; root.traverse(o => { if (o.isMesh && o.userData.merged && !o.layers.isEnabled(31) && !Array.isArray(o.material) && !o.material.transparent && o.material.name !== 'fixture') list.push(o); }); return list; };
const ATTRS = ['position', 'uv2', 'uv3', 'lmRoom', 'lmSkyPage', 'lmLightPage'];
function sameAttributes(a, b, why) {
  const ma = covered(a), mb = covered(b);
  assert.equal(mb.length, ma.length, `${why}: the same covered meshes`);
  ma.forEach((m, i) => {
    for (const name of ATTRS) {
      const x = m.geometry.attributes[name], y = mb[i].geometry.attributes[name];
      assert.equal(!!y, !!x, `${why}: mesh ${i} (${m.material.name}) has ${name} exactly when buildAtlas gives it`);
      if (!x) continue;
      assert.equal(y.itemSize, x.itemSize, `${why}: mesh ${i} ${name} itemSize`);
      assert.equal(y.array.length, x.array.length, `${why}: mesh ${i} ${name} length (clipped geometry comes back)`);
      for (let k = 0; k < x.array.length; k++) if (x.array[k] !== y.array[k]) assert.fail(`${why}: mesh ${i} ${name}[${k}] ${y.array[k]} vs buildAtlas ${x.array[k]}`);
    }
  });
}
const roomsOf = atlas => atlas.room.rooms.map(r => ({ building: r.building, level: r.level, id: r.id, region: r.region }));

// --- KTX2 inputs made here (Ruling B8's encoding, independent of baker.js) ----------------------
const W = 64;
const ch0 = new Uint8Array(W * W), ch1 = new Uint8Array(W * W);
for (let y = 0; y < W; y++) for (let x = 0; x < W; x++) { ch0[y * W + x] = Math.min(255, x * 4); ch1[y * W + x] = (x >> 4) % 2 === (y >> 4) % 2 ? 230 : 20; }
function encodeTest(two) {
  const px = new Uint8Array(W * W * 4);
  for (let i = 0; i < W * W; i++) { px[4 * i] = ch0[i]; px[4 * i + 1] = two ? ch1[i] : 0; px[4 * i + 3] = 255; }
  const e = new E.BasisEncoder();
  e.setCreateKTX2File(true); e.setKTX2UASTCSupercompression(false); e.setUASTC(true);
  e.setPerceptual(false); e.setMipSRGB(false); e.setKTX2SRGBTransferFunc(false); e.setMipGen(true);
  if (two) { e.setSwizzle(0, 0, 0, 1); e.setForceAlpha(true); } else e.setCheckForAlpha(false);
  e.setSliceSourceImage(0, px, W, W, false);
  const out = new Uint8Array(1 << 20), n = e.encode(out); e.delete();
  return out.slice(0, n);
}
const RGTC = 'EXT_texture_compression_rgtc', ETC = 'WEBGL_compressed_texture_etc';
const extensions = (...names) => ({ has: n => names.includes(n), get: n => names.includes(n) ? {} : null });

// --- patched shaders -------------------------------------------------------------------------------
const fakeGL = { capabilities: { isWebGL2: true }, extensions: extensions(RGTC) };
function compile(material) {
  const shader = { uniforms: THREE.UniformsUtils.clone(THREE.ShaderLib.standard.uniforms),
    vertexShader: THREE.ShaderLib.standard.vertexShader, fragmentShader: THREE.ShaderLib.standard.fragmentShader,
    defines: {}, shaderName: 'MeshStandardMaterial', shaderType: 'MeshStandardMaterial' };
  material.onBeforeCompile(shader, fakeGL);
  return shader;
}
function arrayPage(format, layers = 1) {
  if (format === THREE.RGBAFormat) { const t = new THREE.DataArrayTexture(new Uint8Array(4 * 4 * 4 * layers), 4, 4, layers); t.needsUpdate = true; return t; }
  const t = new THREE.CompressedArrayTexture([{ data: new Uint8Array(16 * layers), width: 4, height: 4 }], 4, 4, layers, format);
  t.needsUpdate = true; return t;
}
function tintAt(uniforms, slots, room, slot) {
  const data = uniforms.lmTints.value.image.data, i = (room * slots + slot) * 4;
  const read = v => data instanceof Uint16Array ? THREE.DataUtils.fromHalfFloat(v) : v;
  return [read(data[i]), read(data[i + 1]), read(data[i + 2])];
}

const checks = [];
const check = (name, fn) => checks.push([name, fn]);


check('material_leaves_ambient_alone_without_sky_uniforms', async () => {
  const uniforms = M.lightmapUniforms(3, 2);
  assert.ok(!Object.hasOwn(uniforms, 'skyTint'), 'no skyTint uniform');
  const material = new THREE.MeshStandardMaterial();
  M.patchLightmaps([material], {banks: [arrayPage(THREE.RG11_EAC_Format)]}, uniforms);
  const shader = compile(material);
  assert.ok(!Object.hasOwn(shader.uniforms, 'lmSky'), 'no lmSky sampler');
  assert.ok(!/skyTint|lmSky|uv2/.test(shader.vertexShader + shader.fragmentShader), 'no sky shader terms');
  assert.ok(!/irradiance\s*\*=|iblIrradiance\s*\*=/.test(shader.fragmentShader), 'three ambient is unmodified');
  assert.ok(material.customProgramCacheKey().includes('|lm-4|'), 'new shader program cache key');
});

check('fixed_uniforms_never_recompile', async () => {
  need('lightmapUniforms', 'setLightTint', 'patchLightmaps');
  const rooms = 3, slots = 4, uniforms = M.lightmapUniforms(rooms, slots);
  const tints = uniforms.lmTints?.value;
  assert.ok(tints && tints.isDataTexture, 'uniforms.lmTints holds a DataTexture (Ruling B2: tints never live in per-light uniforms)');
  assert.equal(tints.image.width, slots, 'one texel column per slot'); assert.equal(tints.image.height, rooms, 'one row per room');
  const materials = [new THREE.MeshStandardMaterial({ name: 'floor' }), new THREE.MeshStandardMaterial({ name: 'interior_wall' })];
  const pages = { banks: [arrayPage(THREE.RG11_EAC_Format, 1), arrayPage(THREE.RG11_EAC_Format, 1)] };
  M.patchLightmaps(materials, pages, uniforms);
  const first = materials.map(compile), keys = materials.map(m => m.customProgramCacheKey()), versions = materials.map(m => m.version);
  first.forEach((shader, i) => {
    assert.equal(shader.uniforms.lmTints, uniforms.lmTints, `${materials[i].name}: the shader shares uniforms.lmTints (the same object)`);
    assert.ok(/\buv3\b/.test(shader.vertexShader) && /\blmRoom\b/.test(shader.vertexShader), `${materials[i].name}: the vertex shader reads uv3 and lmRoom`);
    assert.notEqual(shader.fragmentShader, THREE.ShaderLib.standard.fragmentShader, `${materials[i].name}: the fragment shader adds the baked light`);
  });
  const version = tints.version;
  M.setLightTint(uniforms, 1, 0, [255, 0, 0], 1);
  const red = tintAt(uniforms, slots, 1, 0);
  assert.ok(red[0] > 0 && red[1] === 0 && red[2] === 0, `a red light's tint is red: ${red}`);
  assert.ok(tints.version > version, 'the tint texture is flagged for upload');
  M.setLightTint(uniforms, 1, 0, [255, 0, 0], .5);
  const half = tintAt(uniforms, slots, 1, 0);
  assert.ok(Math.abs(half[0] - red[0] / 2) <= red[0] * .01, `the tint is proportional to brightness: ${half[0]} vs ${red[0]}`);
  M.setLightTint(uniforms, 2, 3, [255, 241, 201], 1);
  const warm = tintAt(uniforms, slots, 2, 3);
  assert.ok(warm[0] >= warm[1] && warm[1] >= warm[2] && warm[2] > 0, `warm white: ${warm}`);
  assert.deepEqual(tintAt(uniforms, slots, 1, 1), [0, 0, 0], 'a slot never set stays dark');
  M.setLightTint(uniforms, 1, 0, [255, 0, 0], 0);
  assert.deepEqual(tintAt(uniforms, slots, 1, 0), [0, 0, 0], 'off is zero');
  materials.forEach((m, i) => {
    assert.equal(m.version, versions[i], `${m.name}: toggling, dimming and colour never flag the material for a recompile`);
    assert.equal(m.customProgramCacheKey(), keys[i], `${m.name}: the program key never changes with the lights`);
  });
  const again = materials.map(compile);
  again.forEach((shader, i) => {
    assert.equal(shader.fragmentShader, first[i].fragmentShader, `${materials[i].name}: the same fragment shader whatever the lights`);
    assert.equal(shader.vertexShader, first[i].vertexShader, `${materials[i].name}: the same vertex shader`);
  });
});

check('fresh_bake_frees_the_pool_slot', async () => {
  const bake = fakeBake(['a1', 'a2']);
  const {view, live} = await mounted('low', bake);
  try {
    const count = pool(view).length;
    live.setMode('lights');
    for (const id of ['a1', 'a2']) {
      const r = row(live, id);
      assert.ok(r && r.baked === true && r.real === false && r.intensity > 0, `${id} draws from its bake: ${JSON.stringify(r)}`);
      assert.equal(lampAt(view, id), null, `${id} holds no pool PointLight`);
      assert.ok(bulb(view, id).some(shown), `${id}'s fixture still glows`);
    }
    assert.deepEqual(realSet(live), ['a3', 'a4', 'b1', 'b2'], `the freed slots go to the next nearest: ${JSON.stringify(live.lights())}`);
    for (const id of ['a3', 'a4', 'b1', 'b2']) assert.ok(lampAt(view, id), `a pool light at ${id}`);
    assert.equal(pool(view).filter(l => l.intensity > 0).length, 4, 'four pool lights lit');
    assert.equal(washShown(view, 'A'), false, 'room A needs no wash'); assert.equal(washShown(view, 'B'), false, 'room B is real now: no wash');
    assert.deepEqual(lastCall(bake, 'a1'), { device: 'a1', rgb: [255, 241, 201], intensity: 1 }, 'a1 is told its live colour and brightness');
    assert.ok(Math.abs(lastCall(bake, 'a2').intensity - 128 / 255) < .01, `a2 at 128: ${JSON.stringify(lastCall(bake, 'a2'))}`);
    assert.ok(!bake.calls.some(c => !['a1', 'a2'].includes(c.device) && c.intensity > 0), 'only baked lights are given a tint');

    states['light.a1'].state = 'off'; await live.refresh();
    assert.equal(lastCall(bake, 'a1').intensity, 0, 'turned off: its tint goes to 0');
    assert.ok(!bulb(view, 'a1').some(shown), 'and its fixture stops glowing');
    states['light.a1'] = { state: 'on', attributes: { brightness: 255, rgb_color: [0, 255, 0], color_mode: 'rgb' } }; await live.refresh();
    assert.deepEqual(lastCall(bake, 'a1'), { device: 'a1', rgb: [0, 255, 0], intensity: 1 }, 'the colour follows live');
    assert.equal(pool(view).length, count, 'the pool keeps its size');

    live.setMode(null);
    for (const id of ['a1', 'a2']) assert.equal(lastCall(bake, id).intensity, 0, `All mode: ${id}'s bake is dark`);
    assert.ok(pool(view).every(l => l.intensity === 0), 'All mode: the pool is dark');

    live.setMode('lights');
    bake.set.clear(); await live.refresh();
    assert.deepEqual(bakedSet(live), [], 'no fresh bake: nothing draws baked');
    assert.deepEqual(realSet(live), ['a1', 'a2', 'a3', 'a4'], `no fresh bake: v2.499.783's choice: ${JSON.stringify(live.lights())}`);
    assert.equal(pool(view).length, count, 'the pool never changes size');
  } finally { live.stop(); }
});

check('transcode_picks_rgtc_on_desktop_and_eac_on_pi', async () => {
  need('pickTranscode', 'transcodePage');
  const pick = M.pickTranscode;
  assert.equal(pick(extensions(RGTC), 2), THREE.RED_GREEN_RGTC2_Format, 'desktop, a light page: BC5');
  assert.equal(pick(extensions(RGTC), 1), THREE.RED_RGTC1_Format, 'desktop, a single-channel texture: BC4');
  assert.equal(pick(extensions(ETC), 2), THREE.RG11_EAC_Format, 'Pi, a light page: EAC RG11');
  assert.equal(pick(extensions(ETC), 1), THREE.R11_EAC_Format, 'Pi, a single-channel texture: EAC R11');
  assert.equal(pick(extensions(RGTC, ETC), 2), THREE.RED_GREEN_RGTC2_Format, 'both: RGTC');
  assert.equal(pick(extensions(), 2), THREE.RGBAFormat, 'neither: the uncompressed fallback');
  assert.equal(pick(extensions(), 1), THREE.RGBAFormat, 'neither, single channel: the uncompressed fallback');
  const two = encodeTest(true), one = encodeTest(false);
  for (const [format, perPixel, src, name] of [[THREE.RED_GREEN_RGTC2_Format, 1, two, 'BC5'], [THREE.RG11_EAC_Format, 1, two, 'RG11'],
    [THREE.RED_RGTC1_Format, .5, one, 'BC4'], [THREE.R11_EAC_Format, .5, one, 'R11'], [THREE.RGBAFormat, 4, two, 'RGBA32']]) {
    const t = await M.transcodePage(T, src, format);
    assert.equal(t.format, format, `${name}: the texture's format`);
    assert.equal(t.width, W); assert.equal(t.height, W);
    assert.equal(t.mipmaps.length, 7, `${name}: every mip level (64 down to 1)`);
    assert.equal(t.mipmaps[0].data.byteLength, W * W * perPixel, `${name}: level 0 is ${W * W * perPixel} bytes (${name}'s block size)`);
    assert.ok(t.mipmaps.every((m, i) => m.width === Math.max(1, W >> i) && m.height === Math.max(1, W >> i)), `${name}: mip sizes`);
    if (format === THREE.RGBAFormat) {
      const d = t.mipmaps[0].data;
      let r = 0, a = 0;
      for (let i = 0; i < W * W; i++) { r += Math.abs(d[4 * i] - ch0[i]); a += Math.abs(d[4 * i + 3] - ch1[i]); }
      assert.ok(r / (W * W) <= 2 && a / (W * W) <= 2, `the RGBA32 fallback keeps light 0 in R and light 1 in A: ${r / (W * W)}, ${a / (W * W)}`);
    }
  }
});

check('fallback_reads_r_and_a', async () => {
  need('lightSwizzle', 'lightmapUniforms', 'patchLightmaps');
  assert.equal(M.lightSwizzle(THREE.RGBAFormat), 'ra', 'the RGBA32 fallback reads R and A (Ruling B8)');
  assert.equal(M.lightSwizzle(THREE.RG11_EAC_Format), 'rg', 'EAC RG11 reads R and G');
  assert.equal(M.lightSwizzle(THREE.RED_GREEN_RGTC2_Format), 'rg', 'BC5 reads R and G');
  const uniforms = M.lightmapUniforms(3, 4);
  const fallback = new THREE.MeshStandardMaterial({ name: 'floor' }), compressed = new THREE.MeshStandardMaterial({ name: 'floor' });
  M.patchLightmaps([fallback], { banks: [arrayPage(THREE.RGBAFormat)] }, uniforms);
  M.patchLightmaps([compressed], { banks: [arrayPage(THREE.RG11_EAC_Format)] }, uniforms);
  const a = compile(fallback).fragmentShader.split('\n').map(s => s.trim()), b = compile(compressed).fragmentShader.split('\n').map(s => s.trim());
  const onlyA = a.filter(line => !b.includes(line)), onlyB = b.filter(line => !a.includes(line));
  assert.ok(onlyA.length && onlyB.length, 'RGBA and RG bank pages compile to different shader text (the swizzle is compiled in)');
  assert.ok(onlyA.some(line => /\.(r?a)\b/.test(line)), `the fallback's shader reads light 1 from .a: ${JSON.stringify(onlyA)}`);
  assert.ok(onlyB.some(line => /\.(r?g)\b/.test(line)), `the compressed shader reads light 1 from .g: ${JSON.stringify(onlyB)}`);
  assert.notEqual(fallback.customProgramCacheKey(), compressed.customProgramCacheKey(),
    'their program keys differ, or three.js would hand one the other\'s program');
});

check('atlas_runs_in_a_worker_and_is_cached', async () => {
  need('loadAtlas');
  const reference = await house(), direct = buildAtlas(reference, job.plan, job.layout);
  const idb = fakeIndexedDB(), started = WORKERS.length;
  const root = await house();
  const atlas = await withTimeout(M.loadAtlas(root, job.plan, job.layout, { Worker: FakeWorker, indexedDB: idb }), 60000, 'loadAtlas()');
  const mine = WORKERS.slice(started);
  assert.ok(mine.length >= 1, 'a Worker is started');
  assert.ok(mine.every(w => /\/static\/twin\/bake\/[^/]+\.js$/.test(w.url.split('?')[0])), `the worker is a module next to the bake code: ${mine.map(w => w.url)}`);
  const jobs = mine.flatMap(w => w.posted);
  assert.ok(jobs.some(p => p.transfer.some(x => x instanceof ArrayBuffer)), 'the mesh buffers go to the worker in the transfer list');
  assert.equal(atlas.key, direct.key, 'the same atlas key as buildAtlas in place');
  assert.equal(atlas.room.pages, direct.room.pages, 'the same room pages');
  assert.deepEqual(roomsOf(atlas), roomsOf(direct), 'the same rooms and regions');
  sameAttributes(reference, root, 'from the worker');
  assert.ok(idb.records() >= 1 && idb.log.puts >= 1, 'the result is stored in IndexedDB');

  const later = WORKERS.length, again = await house();
  const cached = await withTimeout(M.loadAtlas(again, job.plan, job.layout, { Worker: FakeWorker, indexedDB: idb }), 60000, 'loadAtlas() from the cache');
  assert.deepEqual(WORKERS.slice(later).flatMap(w => w.posted), [], 'a cached atlas starts no worker job');
  assert.equal(cached.key, direct.key, 'the cached key');
  assert.deepEqual(roomsOf(cached), roomsOf(direct), 'the cached rooms and regions');
  sameAttributes(reference, again, 'from IndexedDB');
});

check('lights_draw_real_time_until_the_atlas_is_ready', async () => {
  need('loadAtlas');
  // A worker that has not answered yet: loadAtlas waits on it, the main thread builds nothing.
  const held = WORKERS.length, root = await house();
  let settled = false;
  const pending = M.loadAtlas(root, job.plan, job.layout, { Worker: HeldWorker, indexedDB: fakeIndexedDB() });
  pending.then(() => { settled = true; }, () => { settled = true; });
  await sleep(1500);
  assert.ok(WORKERS.slice(held).some(w => w.posted.length), 'the job went to the worker');
  assert.equal(settled, false, 'no atlas until the worker answers (it is never built on the main thread)');
  // A worker that cannot start, or dies: the atlas fails, so the caller draws real-time.
  await assert.rejects(withTimeout(M.loadAtlas(await house(), job.plan, job.layout, { Worker: NoWorker, indexedDB: fakeIndexedDB() }), 10000, 'loadAtlas() with no worker'),
    error => !/did not settle/.test(error.message), 'a worker that cannot start rejects');
  await assert.rejects(withTimeout(M.loadAtlas(await house(), job.plan, job.layout, { Worker: ErrorWorker, indexedDB: fakeIndexedDB() }), 10000, 'loadAtlas() with a dying worker'),
    error => !/did not settle/.test(error.message), 'a worker that errors rejects');
  // Meanwhile the runtime has nothing fresh: Lights mode is v2.499.783's.
  const {view, live} = await mounted('low', fakeBake([]));
  try {
    live.setMode('lights');
    assert.deepEqual(realSet(live), ['a1', 'a2', 'a3', 'a4'], `every light real-time while no bake is ready: ${JSON.stringify(live.lights())}`);
    assert.deepEqual(bakedSet(live), [], 'nothing drawn baked');
    assert.equal(pool(view).filter(l => l.intensity > 0).length, 4, 'four pool lights lit');
    assert.equal(washShown(view, 'B'), true, 'room B over budget gets its wash, as before');
  } finally { live.stop(); }
});

check('indexeddb_keeps_the_last_two_atlases', async () => {
  // I3: every geometry change is a new atlas of about 14 MB in Home Assistant's origin. A
  // browser keeps the two it used last and deletes the rest.
  need('loadAtlas');
  const idb = fakeIndexedDB(), keys = [];
  for (const density of [1, 1.5, 2]) {
    const layout = { room: { ...job.layout.room, density } };
    const atlas = await withTimeout(M.loadAtlas(await house(), job.plan, layout, { Worker: FakeWorker, indexedDB: idb }), 60000, 'loadAtlas()');
    keys.push(atlas.key);
  }
  assert.equal(new Set(keys).size, 3, 'fixture: three layouts, three atlas keys');
  const held = [];
  const db = await new Promise(resolve => { const r = idb.open('twin-lightmap-atlases', 1); r.onsuccess = () => resolve(r.result); });
  await new Promise(resolve => {
    const tx = db.transaction('atlases', 'readonly'), r = tx.objectStore('atlases').getAllKeys();
    r.onsuccess = () => held.push(...r.result); tx.oncomplete = resolve;
  });
  const atlases = held.filter(k => keys.includes(k));
  assert.deepEqual(atlases.sort(), keys.slice(1).sort(), `only the last two atlases stay: ${held}`);
  assert.equal(held.filter(k => String(k).startsWith('input:')).length, 2, `and the fingerprints pointing at them: ${held}`);
  // A cache hit makes an atlas the newest again.
  const first = { room: { ...job.layout.room, density: 1.5 } };
  await M.loadAtlas(await house(), job.plan, first, { Worker: FakeWorker, indexedDB: idb });
  await M.loadAtlas(await house(), job.plan, { room: { ...job.layout.room, density: .75 } }, { Worker: FakeWorker, indexedDB: idb });
  const after = [];
  await new Promise(resolve => {
    const tx = db.transaction('atlases', 'readonly'), r = tx.objectStore('atlases').getAllKeys();
    r.onsuccess = () => after.push(...r.result); tx.oncomplete = resolve;
  });
  assert.ok(after.includes(keys[1]) && !after.includes(keys[2]), `the atlas used last survives: ${after}`);
});

const only = process.argv[3] ? process.argv[3].split(',') : null;
let passed = 0, ran = 0;
for (const [name, fn] of checks) {
  if (only && !only.includes(name)) continue;
  ran++;
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 600)); }
}
console.log(`${passed}/${ran} passed`);
process.exit(passed === ran ? 0 : 1);
"""


def node():
    return shutil.which('node')


def household_pool_house():
    with open(HOUSEHOLD, encoding='utf-8') as f:
        twin_store.push_round(json.load(f), 'build')
    plan = copy.deepcopy(twin_store.current())
    plan['buildings'] = [b for b in plan['buildings'] if b['id'] == POOL]
    return plan


def run(only=None):
    exe = node()
    if not exe:
        print('  skip  node is unavailable')
        return 0
    job = {'root': pathlib.Path(ROOT).as_posix(), 'plan': household_pool_house(),
           'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}}, 'layout': LAYOUT}
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps(job))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix,
                                             prefix='chauffeur_lightmap_', delete=False) as stream:
                paths.append(pathlib.Path(stream.name))
                stream.write(content)
        args = [exe, str(paths[0]), str(paths[1])] + ([only] if only else [])
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=600)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run(sys.argv[1] if len(sys.argv) > 1 else None) else 0)
