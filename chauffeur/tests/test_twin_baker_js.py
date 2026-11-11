"""Room-light baker and codec checks with the real atlas, fake GPU and in-memory server.

The pool-house fixture at one texel/ft uses two room pages. Two lights share
each room's region (light 0 in RGB, light 1 in alpha); a third uses a sparse
second bank. Checks preserve channels and neighbours, stable light keys,
freshness, cancellation, buffer ownership, manifest-last publication,
read failures, existence probes, forced refresh and the cross-desk lease.
Only room lights bake. Manifests need no sky to be complete, legacy sky options
are ignored, and a new round can settle without a sky entry.

Run from chauffeur/: python tests/test_twin_baker_js.py [check-name] (HA_BASE_URL unset).
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_baker_js_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402
from services import twin_store  # noqa: E402

HOUSEHOLD = os.path.join(ROOT, 'tests', 'fixtures', 'twin_model', 'household-2026-11-09.json')
LAYOUT = {'room': {'density': 1, 'page': 256, 'gutter': 2}}
POOL = 'pool-house'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
HALL = 'room:f94386f3da524031b4530a0847d7bc75'
CHANGING = 'room:aa3a66806205434ca794927a6d66dd22'

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
    // The app's ES modules load as modules; the vendored Basis wasm glue stays CommonJS.
    if (bare.startsWith('file:') && bare.endsWith('.js') && !/basis/i.test(bare)) return { ...next(url, { ...ctx, format: 'module' }), format: 'module' };
    return next(url, ctx);
  },
});
globalThis.window = globalThis.window || {};
const THREE = await import('three');
const require = createRequire(import.meta.url);
const quiet = { print() {}, printErr() {} };
const E = await require(job.root + '/static/vendor/basis-universal/basis_encoder.js')({ ...quiet, wasmBinary: readFileSync(job.root + '/static/vendor/basis-universal/basis_encoder.wasm') });
const T = await require(job.root + '/static/vendor/three-r187/addons/libs/basis/basis_transcoder.js')({ ...quiet, wasmBinary: readFileSync(job.root + '/static/vendor/three-r187/addons/libs/basis/basis_transcoder.wasm') });
E.initializeBasis(); T.initializeBasis();
const gen = await import(file('static/twin/twin_generator.js'));
const { buildAtlas } = await import(file('static/twin/bake/atlas.js'));
let B = null, missing = null;
try { B = await import(file('static/twin/bake/baker.js')); }
catch (error) { missing = String(error && error.message || error).split('\n')[0]; }
const need = (...names) => {
  assert.ok(B, `static/twin/bake/baker.js is missing or does not load: ${missing}`);
  for (const name of names) assert.equal(typeof B[name], 'function', `baker.js exports ${name}`);
};
const KTX2_MAGIC = [0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a];
const LAYOUT = job.layout;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const withTimeout = (p, ms, what) => Promise.race([p, sleep(ms).then(() => { throw new Error(`${what} did not settle in ${ms} ms`); })]);

// --- the fake GPU ------------------------------------------------------------------------
const FILL = { value: .08, onRead: null };
function fill(buffer, w, h) {
  const per = w > 0 && h > 0 ? Math.round(buffer.length / (w * h)) : 4;
  const v = FILL.value;
  const put = buffer instanceof Float32Array ? x => x
    : buffer instanceof Uint16Array ? x => THREE.DataUtils.toHalfFloat(x)
    : x => Math.round(Math.max(0, Math.min(1, x)) * 255);
  const pv = put(v), one = put(1);
  for (let i = 0; i < buffer.length; i++) buffer[i] = per === 4 && i % 4 === 3 ? one : pv;
}
function fakeRenderer() {
  const log = { renders: 0, reads: 0 };
  let target = null, clearAlpha = 1;
  const clearColor = new THREE.Color(0, 0, 0);
  const read = (rt, x, y, w, h, buffer) => {
    log.reads++; fill(buffer, w, h);
    const hook = FILL.onRead; if (hook) hook();
    return buffer;
  };
  const gl = new Proxy({}, { get: (o, k) => typeof k === 'string' && /^[A-Z0-9_]+$/.test(k) ? 0 : () => null });
  const base = {
    isWebGLRenderer: true, isWebGPURenderer: false, log, coordinateSystem: THREE.WebGLCoordinateSystem,
    domElement: { width: 1400, height: 1000, addEventListener() {}, removeEventListener() {} },
    capabilities: { isWebGL2: true, maxTextureSize: 16384, maxTextures: 16, maxVertexTextures: 16, maxSamples: 4,
      maxAttributes: 16, maxVertexUniforms: 1024, maxFragmentUniforms: 1024, maxVaryings: 30,
      floatFragmentTextures: true, floatVertexTextures: true, precision: 'highp', logarithmicDepthBuffer: false,
      reverseDepthBuffer: false, vertexTextures: true, getMaxAnisotropy: () => 1, getMaxPrecision: () => 'highp',
      textureFormatReadable: () => true, textureTypeReadable: () => true },
    extensions: { has: () => true, get: () => ({}), init() {} },
    shadowMap: { enabled: true, autoUpdate: true, needsUpdate: false, type: THREE.PCFShadowMap },
    xr: { enabled: false, isPresenting: false },
    info: { autoReset: false, render: { calls: 0, triangles: 0, points: 0, lines: 0, frame: 0 }, memory: { geometries: 0, textures: 0 }, programs: [], reset() {} },
    outputColorSpace: THREE.SRGBColorSpace, toneMapping: THREE.NoToneMapping, toneMappingExposure: 1,
    autoClear: true, autoClearColor: true, autoClearDepth: true, autoClearStencil: true, sortObjects: true,
    localClippingEnabled: false, clippingPlanes: [], transmissionResolutionScale: 1,
    state: { reset() {}, buffers: { color: { setMask() {}, setClear() {}, setLocked() {} }, depth: { setTest() {}, setMask() {}, setLocked() {} }, stencil: { setTest() {}, setLocked() {} } } },
    properties: { get: () => ({}), remove() {}, update() {} },
    getContext: () => gl, getContextAttributes: () => ({ alpha: true, antialias: false }),
    getRenderTarget: () => target, setRenderTarget(rt) { target = rt; },
    getActiveCubeFace: () => 0, getActiveMipmapLevel: () => 0,
    getClearColor: c => c.copy(clearColor), setClearColor(c, a) { clearColor.set(c); if (a !== undefined) clearAlpha = a; },
    getClearAlpha: () => clearAlpha, setClearAlpha(a) { clearAlpha = a; },
    clear() {}, clearColor() {}, clearDepth() {}, clearStencil() {},
    render() { log.renders++; },
    readRenderTargetPixels: read,
    readRenderTargetPixelsAsync: async (...args) => read(...args),
    getPixelRatio: () => 1, setPixelRatio() {}, getSize: v => v.set(1400, 1000), setSize() {},
    getDrawingBufferSize: v => v.set(1400, 1000), getViewport: v => v.set(0, 0, 1400, 1000), setViewport() {},
    getScissor: v => v.set(0, 0, 1400, 1000), setScissor() {}, getScissorTest: () => false, setScissorTest() {},
    compile() {}, compileAsync: async () => {}, initTexture() {}, initRenderTarget() {}, copyTextureToTexture() {},
    copyFramebufferToTexture() {}, resetState() {}, dispose() {}, setAnimationLoop() {},
  };
  // A method the fake does not know draws or reads nothing (the GPU's half is the live test's).
  return new Proxy(base, { get: (o, k) => k in o ? o[k]
    : typeof k === 'string' && /^(get|set|clear|copy|init|render|compile|reset|dispose|update|bind|read|blit)/.test(k) ? () => undefined : undefined });
}

// --- the fake bake server ---------------------------------------------------------------
const STEP = { n: 0 };
const KEY_RE = /^[0-9a-f]{16,64}$/;
function checkManifest(body) {   // services/twin_bakes._check_manifest, as of eb342958
  if (!body || typeof body !== 'object' || Array.isArray(body)) return 'not an object';
  const pages = body.pages;
  if (!Number.isInteger(pages) || pages < 1) return 'pages';
  if (!body.lights || typeof body.lights !== 'object' || Array.isArray(body.lights)) return 'lights';
  for (const entry of Object.values(body.lights)) {
    if (!entry || typeof entry !== 'object') return 'an entry without page and channel';
    if (!Number.isInteger(entry.page) || entry.page < 0 || entry.page >= pages) return 'entry page outside the manifest';
    if (!Number.isInteger(entry.channel) || entry.channel < 0 || entry.channel > 3) return 'channel';
  }
  for (const entry of Object.values(body.lights)) if (!KEY_RE.test(String(entry.key))) return 'light key';
  return null;
}
async function bytesOf(body) {
  if (body == null) return new Uint8Array();
  if (typeof body === 'string') return new TextEncoder().encode(body);
  return new Uint8Array(await new Response(body).arrayBuffer());
}
function fakeServer({ leaseRequired = false } = {}) {
  const pages = new Map(), manifests = new Map(), calls = [], bad = [], etags = new Map();
  const lease = { holder: null, granted: 0, overlaps: 0, refused: 0 };
  let fail = null, version = 0;
  const answer = (status, body, type, extra = {}) => new Response(status === 304 ? null : body instanceof Uint8Array ? body.slice() : body,
    { status, headers: { ...(type ? { 'Content-Type': type } : {}), ...extra } });
  const header = (options, name) => {
    const h = options.headers || {};
    return h instanceof Headers ? h.get(name) : Object.entries(h).find(([k]) => k.toLowerCase() === name.toLowerCase())?.[1];
  };
  const api = async (path, options = {}) => {
    const method = String(options.method || 'GET').toUpperCase(), p = String(path).split('?')[0];
    const call = { method, path: p, step: STEP.n, inm: header(options, 'If-None-Match') || null, full: false };
    calls.push(call);
    const injected = fail?.(method, p);
    if (injected) return answer(injected, '{"detail":"injected"}', 'application/json');
    if (!p.startsWith('api/house/bakes/')) { bad.push(p); return answer(404, '{"detail":"Not Found"}', 'application/json'); }
    let m = p.match(/^api\/house\/bakes\/([0-9a-f]{16,64})\/lease$/);
    if (m && method === 'POST') {   // services/twin_bakes.lease (Ruling B17); no clock: leases only end by release
      const body = JSON.parse(new TextDecoder().decode(await bytesOf(options.body)));
      if (body.action === 'check') return answer(200, JSON.stringify({ free: !lease.holder || lease.holder === body.owner }), 'application/json');
      if (body.action === 'release') { if (lease.holder === body.owner) lease.holder = null; return answer(200, '{"held":false}', 'application/json'); }
      if (lease.holder && lease.holder !== body.owner) { lease.refused++; return answer(409, '{"detail":"held"}', 'application/json'); }
      if (!lease.holder) lease.granted++;
      lease.holder = body.owner;
      return answer(200, '{"held":true,"seconds":60}', 'application/json');
    }
    const guard = () => {
      if (!leaseRequired || lease.holder) return null;
      bad.push(`${method} ${p} without the lease`);
      return answer(409, '{"detail":"no lease"}', 'application/json');
    };
    m = p.match(/^api\/house\/bakes\/([0-9a-f]{16,64})\/(\d+)\.(\w+)$/);
    if (m) {
      const id = `${m[1]}/${Number(m[2])}`;
      if (method === 'POST') {
        const refused = guard(); if (refused) return refused;
        const b = await bytesOf(options.body); pages.set(id, b); etags.set(id, `"${++version}-${b.length}"`);
        return answer(200, JSON.stringify({ etag: etags.get(id) }), 'application/json');
      }
      if (method === 'GET') {
        if (!pages.has(id)) return answer(404, '{"detail":"Not Found"}', 'application/json');
        const tags = String(call.inm || '').split(',').map(t => t.trim().replace(/^W\//, ''));
        if (tags.some(t => t === '*' || t === etags.get(id))) return answer(304, null, null, { ETag: etags.get(id) });
        call.full = true;
        return answer(200, pages.get(id), 'application/octet-stream', { ETag: etags.get(id) });
      }
      return answer(405, '{}', 'application/json');
    }
    m = p.match(/^api\/house\/bakes\/([0-9a-f]{16,64})$/);
    if (m) {
      if (method === 'PUT') {
        const refused = guard(); if (refused) return refused;
        let body; try { body = JSON.parse(new TextDecoder().decode(await bytesOf(options.body))); } catch { return answer(400, '{"detail":"bad json"}', 'application/json'); }
        const why = checkManifest(body);
        if (why) { bad.push(`manifest refused: ${why}`); return answer(400, JSON.stringify({ detail: why }), 'application/json'); }
        manifests.set(m[1], structuredClone(body));
        return answer(200, JSON.stringify(body), 'application/json');
      }
      if (method === 'GET') return manifests.has(m[1]) ? answer(200, JSON.stringify(manifests.get(m[1])), 'application/json') : answer(404, '{"detail":"Not Found"}', 'application/json');
      return answer(405, '{}', 'application/json');
    }
    bad.push(p); return answer(404, '{"detail":"Not Found"}', 'application/json');
  };
  // The lease is not bake data: writes() are page uploads and manifest saves.
  const writes = (since = 0) => calls.slice(since).filter(c => c.method !== 'GET' && !c.path.endsWith('/lease'));
  return { api, pages, manifests, calls, bad, writes, lease, etags, set fail(f) { fail = f; }, get fail() { return fail; } };
}

// --- the house, the lights, the codec -----------------------------------------------------
const building = job.plan.buildings.find(b => b.id === job.pool);
const lot = ([x, y, z]) => {
  const a = (building.rotation || 0) * Math.PI / 180, [px, py] = building.position || [0, 0];
  return [Math.cos(a) * x - Math.sin(a) * y + px, Math.sin(a) * x + Math.cos(a) * y + py, z];
};
const light = (device, room, at) => ({ device, building: job.pool, level: 'L1', room, at: lot(at) });
const k1 = light('k1', job.kitchen, [9.3, 5.2, 9.8]);
const k2 = light('k2', job.kitchen, [20, 6, 9.8]);
const k3 = light('k3', job.kitchen, [5, 12, 9.8]);
const h1 = light('h1', job.hall, [21, 15.4, 9.8]);
const c1 = light('c1', job.changing, [27.7, 17, 9.8]);
async function setup(tier = 'high', layout = LAYOUT) {
  const out = gen.buildTwin(job.plan, job.kit, 'high');
  await out.ready; out.root.updateMatrixWorld(true);
  const atlas = buildAtlas(out.root, job.plan, layout);
  const renderer = fakeRenderer(), scene = new THREE.Scene(); scene.add(out.root);
  const camera = new THREE.PerspectiveCamera(38, 1.4, .1, 1000);
  const view = { tier, plan: job.plan, scene, renderer3: renderer, camera, ready: true };
  return { out, atlas, renderer, view, layout };
}
const codec = { encode: async j => B.encodePage(E, j), decode: async bytes => B.decodePage(T, bytes) };
const makeBaker = (ctx, server, lights, extra = {}) => B.createBaker(ctx.view, { renderer: ctx.renderer, atlas: ctx.atlas, layout: ctx.layout, lights, api: server.api, codec, ...extra });
async function bakeAll(baker, limit = 32) {
  const ids = [];
  for (let i = 0; i < limit; i++) {
    STEP.n++;
    const id = await withTimeout(Promise.resolve(baker.bakeNext()), 120000, 'bakeNext()');
    if (!id) return ids;
    ids.push(id);
  }
  throw new Error(`bakeNext() never ran out of work: ${JSON.stringify(ids)}`);
}
const asSet = list => [...new Set(list)].sort();
const isKtx2 = b => b && b.length > 12 && KTX2_MAGIC.every((v, i) => b[i] === v);
function rgba(bytes) {   // the test's own transcode: RGBA32 of level 0
  const k = new T.KTX2File(bytes);
  try {
    assert.ok(k.isValid(), 'a stored page is a valid KTX2 file');
    assert.ok(k.startTranscoding(), 'the stored page transcodes');
    const fmt = T.transcoder_texture_format.cTFRGBA32.value;
    const out = new Uint8Array(k.getImageTranscodedSizeInBytes(0, 0, 0, fmt));
    assert.ok(k.transcodeImage(out, 0, 0, 0, fmt, 0, -1, -1), 'RGBA32 transcode of a stored page');
    return { w: k.getWidth(), h: k.getHeight(), data: out, uastc: !!k.isUASTC(), levels: k.getLevels() };
  } finally { k.close(); k.delete(); }
}
// A channel (0 = R, 1 = A: Ruling B8) over the inside of rects (1 texel in from every edge).
function channelOver(img, rects, channel) {
  const values = [];
  for (const r of rects) for (let y = r.y + 1; y < r.y + r.h - 1; y++) for (let x = r.x + 1; x < r.x + r.w - 1; x++)
    values.push(img.data[(y * img.w + x) * 4 + (channel === 0 ? 0 : 3)]);
  return values;
}
const mean = v => v.reduce((s, x) => s + x, 0) / Math.max(1, v.length);
function compare(a, b) {
  let sum = 0, max = 0;
  for (let i = 0; i < a.length; i++) { const d = Math.abs(a[i] - b[i]); sum += d; max = Math.max(max, d); }
  return { mean: sum / Math.max(1, a.length), max, n: a.length };
}
const roomIndex = (atlas, id) => atlas.room.rooms.findIndex(r => r.building === job.pool && r.id === id);
// Chart rects of a room inside one bank's page set (bank-local page), from packBanks (Ruling B7).
function bankRects(atlas, lights, bank, roomId) {
  const banks = atlas.room.packBanks(lights);
  const b = banks[bank], room = roomIndex(atlas, roomId);
  assert.ok(b, `atlas.room.packBanks has a bank ${bank}`);
  const charts = b.charts.filter(c => c.room === room && c.rect.w >= 3 && c.rect.h >= 3);
  assert.ok(charts.length, `room ${roomId} has charts in bank ${bank}`);
  return { page: charts[0].page, rects: charts.filter(c => c.page === charts[0].page).map(c => c.rect), banks };
}


function lightSamples(packed, id, stored, key) {
  const slot=packed.slots[id], decoded=new Map(), values=[];
  for(const a of slot.assignments) {
    const chart=packed.banks[a.bank].charts.find(c=>c.id===a.chart);
    if(chart.rect.w<3||chart.rect.h<3) continue;
    const page=packed.offsets[a.bank]+chart.page;
    if(!decoded.has(page)) decoded.set(page,rgba(stored.get(`${key}/${page}`)));
    values.push(...channelOver(decoded.get(page),[chart.rect],a.channel));
  }
  assert.ok(values.length,`${id} has sampled owned texels`); return values;
}

const checks = [];
const check = (name, fn) => checks.push([name, fn]);


check('room_only_manifest_is_complete_without_a_sky_pass', async () => {
  // Legacy callers may still send sky options; they must have no effect.
  const ctx = await setup('high', {...LAYOUT, sky: {density: 1, page: 256, gutter: 2}}), server = fakeServer(), lights = [k1, k2];
  const baked = await bakeAll(makeBaker(ctx, server, lights, {round: 42}));
  assert.deepEqual(baked, ['k1', 'k2'], 'no sky pass runs');
  const manifest = server.manifests.get(ctx.atlas.key);
  assert.equal(manifest.complete, true, 'room-only manifest is complete');
  assert.equal(manifest.round, 42);
  assert.ok(!Object.hasOwn(manifest, 'sky'), 'new manifest never publishes sky');
  assert.deepEqual(manifest.densities, {room: LAYOUT.room.density});
  const again = makeBaker(ctx, server, lights, {round: 43});
  assert.equal(await again.settle(), true, 'a new round settles without a sky entry');
  assert.equal(await again.bakeNext(), null, 'no sky work remains');
});


check('stale_lights_are_only_the_changed_ones', async () => {
  const ctx=await setup(),server=fakeServer(),lights=[k1,k2,h1,c1],key=ctx.atlas.key;
  FILL.value=.08;
  const first=makeBaker(ctx,server,lights);
  assert.deepEqual(asSet(await first.staleLights()),['c1','h1','k1','k2']);
  assert.deepEqual(asSet(await bakeAll(first)),['c1','h1','k1','k2']);
  assert.deepEqual(await first.staleLights(),[]);
  assert.deepEqual(server.bad,[]);
  const packed=B.bakeLayout(ctx.atlas,LAYOUT,lights),manifest=structuredClone(server.manifests.get(key));
  for(const id of ['k1','k2','h1','c1']) {
    const e=manifest.lights[id];assert.ok(KEY_RE.test(e.key));
    for(const page of e.pages) assert.ok(server.pages.has(`${key}/${page}`),'every owned bank page was published');
    assert.ok(mean(lightSamples(packed,id,server.pages,key))>5,`${id} writes every chart's own channel`);
  }
  assert.equal(new Set(Object.values(manifest.lights).map(e=>e.key)).size,4);
  for(const data of server.pages.values()) assert.ok(isKtx2(data));
  const again=makeBaker(ctx,server,lights),since=server.calls.length;
  assert.deepEqual(await again.staleLights(),[]);assert.equal(await again.bakeNext(),null);
  assert.deepEqual(server.writes(since),[],'fresh charts cause no writes');

  // A same-key forced refresh isolates channel preservation from re-ranking.
  const before=new Map(server.pages),forced=makeBaker(ctx,server,[h1,k1,k2,c1],{force:true});
  FILL.value=.24;
  assert.equal(await forced.bakeNext(),'h1');
  for(const id of ['k1','k2','c1']) {
    const delta=compare(lightSamples(packed,id,before,key),lightSamples(packed,id,server.pages,key));
    assert.ok(delta.mean<=1.5&&delta.max<=12,`${id}'s owned texels survive another light's multi-bank write: ${JSON.stringify(delta)}`);
  }
  assert.ok(compare(lightSamples(packed,'h1',before,key),lightSamples(packed,'h1',server.pages,key)).mean>=3);
  assert.deepEqual(server.manifests.get(key).lights,manifest.lights,'forced refresh retains every key and entry');
  const ownPages=new Set(manifest.lights.h1.pages);
  for(const [path,bytes] of before) if(!ownPages.has(Number(path.split('/').pop()))) assert.deepEqual(server.pages.get(path),bytes);

  const moved={...h1,at:[h1.at[0]+2,h1.at[1],h1.at[2]]},nextLights=[moved,k1,k2,c1];
  const next=B.bakeLayout(ctx.atlas,LAYOUT,nextLights,manifest.ownership);
  const changed=nextLights.filter(l=>next.entries[l.device].key!==manifest.lights[l.device].key ||
    next.entries[l.device].location!==manifest.lights[l.device].location).map(l=>l.device);
  assert.deepEqual(changed,['h1'],'only the moved light changes below the six-member cap');
  const third=makeBaker(ctx,server,nextLights);
  assert.deepEqual(asSet(await third.staleLights()),asSet(changed),'only changed geometry, reach or slots go stale');
  assert.deepEqual(asSet(await bakeAll(third)),asSet(changed));
  assert.deepEqual(server.manifests.get(key).lights,next.entries);
  const other=await setup('high',{room:{...LAYOUT.room,density:2,page:512}});
  assert.notEqual(other.atlas.key,key);
  assert.deepEqual(asSet(await makeBaker(other,server,nextLights).staleLights()),['c1','h1','k1','k2']);
});

check('a_round_change_cancels_and_uploads_nothing', async () => {
  need('createBaker', 'encodePage', 'decodePage');
  try {
    // The model round changes while the GPU work is in flight: view.plan is replaced.
    const ctx = await setup(), server = fakeServer();
    const baker = makeBaker(ctx, server, [k1, h1]);
    let swapped = false;
    FILL.onRead = () => { if (!swapped) { swapped = true; ctx.view.plan = structuredClone(job.plan); } };
    STEP.n++;
    try { await withTimeout(Promise.resolve(baker.bakeNext()), 120000, 'bakeNext() after a round change'); }
    catch (error) { if (/did not settle/.test(error.message)) throw error; }
    FILL.onRead = null;
    assert.ok(swapped, 'the bake read pixels back from the GPU (readRenderTargetPixels or readRenderTargetPixelsAsync)');
    assert.deepEqual(server.writes(), [], `nothing is uploaded once the round changed: ${JSON.stringify(server.writes())}`);
    STEP.n++;
    let next = null;
    try { next = await withTimeout(Promise.resolve(baker.bakeNext()), 60000, 'bakeNext() on a stale baker'); } catch (error) { if (/did not settle/.test(error.message)) throw error; }
    assert.ok(!next, `a baker for the old round bakes nothing more: ${next}`);
    assert.deepEqual(server.writes(), [], 'still nothing uploaded');

    // cancel() mid-bake does the same.
    const ctx2 = await setup(), server2 = fakeServer();
    const baker2 = makeBaker(ctx2, server2, [k1, h1]);
    let cancelled = false;
    FILL.onRead = () => { if (!cancelled) { cancelled = true; baker2.cancel(); } };
    STEP.n++;
    try { await withTimeout(Promise.resolve(baker2.bakeNext()), 120000, 'bakeNext() after cancel()'); }
    catch (error) { if (/did not settle/.test(error.message)) throw error; }
    FILL.onRead = null;
    assert.ok(cancelled, 'the cancelled bake reached the GPU readback');
    assert.deepEqual(server2.writes(), [], `cancel() mid-bake uploads nothing: ${JSON.stringify(server2.writes())}`);
  } finally { FILL.onRead = null; }
});


check('a_third_light_in_a_room_goes_to_a_second_bank', async () => {
  const ctx=await setup(),server=fakeServer(),lights=[k1,k2,k3,h1],key=ctx.atlas.key;
  FILL.value=.1;
  assert.deepEqual(asSet(await bakeAll(makeBaker(ctx,server,lights))),['h1','k1','k2','k3']);
  const packed=B.bakeLayout(ctx.atlas,LAYOUT,lights),owners=new Map();
  assert.equal(packed.banks.length,3,'bank count is fixed');
  for(const l of lights) {
    assert.ok(mean(lightSamples(packed,l.device,server.pages,key))>5,`${l.device} lands in its own per-chart channels`);
    for(const a of packed.slots[l.device].assignments) {
      const address=`${a.chart}/${a.bank}/${a.channel}`;
      assert.ok(!owners.has(address),'each chart channel has exactly one light');owners.set(address,l.device);
    }
  }
  assert.ok(Object.values(packed.slots).some(s=>s.assignments.some(a=>a.bank===1)),'third/fourth-ranked chart contributions use bank one');
  assert.equal(packed.banks[2].charts.length,0,'four lights never occupy bank two');
  for(let p=0;p<packed.banks[2].pages;p++) {
    const image=rgba(server.pages.get(`${key}/${packed.offsets[2]+p}`));
    assert.ok(mean(image.data.filter((v,i)=>i%4===0))<=2&&mean(image.data.filter((v,i)=>i%4===3))<=2,'reserved bank-two pages remain empty');
  }
  assert.equal([...server.pages.keys()].filter(p=>p.startsWith(key+'/')).length,packed.pages);
});

check('low_tier_never_bakes', async () => {
  need('createBaker');
  const ctx = await setup('low'), server = fakeServer();
  const baker = makeBaker(ctx, server, [k1, h1]);
  if (baker) {
    STEP.n++;
    assert.ok(!(await withTimeout(Promise.resolve(baker.bakeNext()), 30000, 'bakeNext() on low')), 'bakeNext() on low bakes nothing');
    const p = baker.progress?.();
    assert.ok(!p || !p.total, `nothing in progress on low: ${JSON.stringify(p)}`);
  }
  assert.equal(ctx.renderer.log.renders, 0, 'no render pass on low');
  assert.equal(ctx.renderer.log.reads, 0, 'no GPU readback on low');
  assert.deepEqual(server.writes(), [], 'nothing uploaded on low');
});

check('encode_puts_light_1_in_alpha', async () => {
  need('encodePage', 'decodePage');
  const W = 64, H = 64, a = new Uint8Array(W * H), b = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    a[y * W + x] = Math.min(255, x * 4);                       // light 0: a ramp left to right
    b[y * W + x] = (x >> 4) % 2 === (y >> 4) % 2 ? 230 : 20;   // light 1: a checker
  }
  const two = await B.encodePage(E, { width: W, height: H, channels: [a, b] });
  assert.ok(two instanceof Uint8Array && isKtx2(two), 'a KTX2 file');
  const img = rgba(two);
  assert.ok(img.uastc, 'Basis UASTC (Ruling B4)');
  assert.ok(img.levels > 1, `with mipmaps (Ruling B3): ${img.levels} levels`);
  assert.equal(img.w, W); assert.equal(img.h, H);
  const R = [], G = [], A = [];
  for (let i = 0; i < W * H; i++) { R.push(img.data[4 * i]); G.push(img.data[4 * i + 1]); A.push(img.data[4 * i + 3]); }
  const r = compare(R, a), al = compare(A, b);
  assert.ok(r.mean <= 2 && r.max <= 24, `light 0 is in R: ${JSON.stringify(r)}`);
  assert.ok(al.mean <= 2 && al.max <= 24, `light 1 is in A (Ruling B8): ${JSON.stringify(al)}`);
  assert.ok(compare(G, a).mean <= 2, 'light 0 fills RGB (setSwizzle(0,0,0,1)), so G carries light 0 too');
  const dec = await B.decodePage(T, two);
  assert.equal(dec.width, W); assert.equal(dec.height, H);
  assert.ok(compare(dec.channels[0], a).mean <= 2 && compare(dec.channels[1], b).mean <= 2, 'decodePage gives back [R, A] = [light 0, light 1]');
  const one = await B.encodePage(E, { width: W, height: H, channels: [a] });
  assert.ok(isKtx2(one), 'a single-channel codec page is KTX2 too');
  const single = rgba(one), S = [];
  for (let i = 0; i < W * H; i++) S.push(single.data[4 * i]);
  assert.ok(compare(S, a).mean <= 2, 'a one-channel page keeps its channel in R');
});

check('manifest_written_last', async () => {
  need('createBaker', 'encodePage', 'decodePage');
  const ctx = await setup(), server = fakeServer(), lights = [k1, h1, c1], key = ctx.atlas.key;
  FILL.value = .1;
  const baker = makeBaker(ctx, server, lights);
  const done = [];
  for (let i = 0; i < 16; i++) {
    STEP.n++;
    const step = STEP.n, id = await withTimeout(Promise.resolve(baker.bakeNext()), 120000, 'bakeNext()');
    // The B17 lease is not bake data; the step's writes are its page uploads and manifest.
    const writes = server.calls.filter(c => c.step === step && c.method !== 'GET' && !c.path.endsWith('/lease'));
    if (!id) { assert.deepEqual(writes, [], 'a step with nothing to bake writes nothing'); break; }
    done.push(id);
    assert.ok(writes.length >= 2, `${id}: page upload(s) then the manifest: ${JSON.stringify(writes)}`);
    const last = writes.at(-1);
    assert.equal(last.method, 'PUT', `${id}: the manifest PUT is the step's last write: ${JSON.stringify(writes)}`);
    assert.equal(last.path, `api/house/bakes/${key}`, `${id}: the manifest of atlas.key`);
    assert.equal(writes.filter(w => w.method === 'PUT').length, 1, `${id}: one manifest PUT per step`);
    assert.ok(writes.slice(0, -1).every(w => w.method === 'POST' && w.path.startsWith(`api/house/bakes/${key}/`)), `${id}: page POSTs before it`);
    const m = server.manifests.get(key);
    assert.ok(m, `${id}: the manifest landed`);
    assert.deepEqual(asSet(Object.keys(m.lights)), asSet(done), `${id}: the manifest lists exactly the lights baked so far`);
    for (const e of Object.values(m.lights)) for(const page of e.pages || [e.page])
      assert.ok(server.pages.has(`${key}/${page}`), `${id}: every owned bank page exists before the manifest names it`);
  }
  assert.deepEqual(asSet(done), ['c1', 'h1', 'k1'], `every light baked: ${done}`);
  const p = baker.progress();
  assert.ok(p && p.total >= 3 && p.done === p.total, `progress() counts the lights of the run: ${JSON.stringify(p)}`);
});

check('baking_never_frees_the_houses_own_buffers', async () => {
  // I6: three's dispose() deletes the GL buffer of every attribute of a geometry. The bake's
  // proxies must hold their own attribute objects, never the house meshes'.
  need('createBaker');
  const ctx = await setup(), server = fakeServer();
  const house = new Set();
  ctx.out.root.traverse(o => { if (o.geometry) for (const a of Object.values(o.geometry.attributes)) house.add(a); });
  const disposed = [], dispose = THREE.BufferGeometry.prototype.dispose;
  THREE.BufferGeometry.prototype.dispose = function () { disposed.push(this); return dispose.call(this); };
  try {
    FILL.value = .1;
    const baked = await bakeAll(makeBaker(ctx, server, [k1, h1]));
    assert.ok(baked.includes('k1'), `a room light was baked: ${baked}`);
  } finally { THREE.BufferGeometry.prototype.dispose = dispose; }
  assert.ok(disposed.length, 'the bake disposed its proxies');
  const shared = disposed.flatMap(g => Object.entries(g.attributes).filter(([, a]) => house.has(a)).map(([n]) => n));
  assert.deepEqual(shared, [], 'no disposed geometry holds an attribute of the house');
});

check('a_failed_read_aborts_the_step', async () => {
  // I7: only a 404 is "no page". A 502 while the add-on restarts aborts the step: nothing is
  // uploaded and the manifest is untouched; the next run retries.
  need('createBaker');
  const ctx = await setup(), server = fakeServer(), lights = [k1, k2, h1], key = ctx.atlas.key;
  FILL.value = .1;
  await bakeAll(makeBaker(ctx, server, lights));
  const manifest = structuredClone(server.manifests.get(key)), pages = new Map(server.pages);
  const moved = { ...h1, at: [h1.at[0] + 2, h1.at[1], h1.at[2]] };
  const page = manifest.lights.h1.page;
  server.fail = (method, path) => method === 'GET' && path === `api/house/bakes/${key}/${page}.png` && !server.calls.at(-1).inm ? 502 : null;
  const baker = makeBaker(ctx, server, [moved, k1, k2]), since = server.calls.length;
  STEP.n++;
  await assert.rejects(withTimeout(Promise.resolve(baker.bakeNext()), 120000, 'bakeNext() over a 502'), error => !/did not settle/.test(error.message),
    'a page read that fails with 502 throws out of the step');
  assert.deepEqual(server.writes(since), [], `nothing is uploaded: ${JSON.stringify(server.writes(since))}`);
  assert.deepEqual(server.manifests.get(key), manifest, 'the manifest is untouched');
  for (const [id, bytes] of pages) assert.deepEqual(server.pages.get(id), bytes, `page ${id} is untouched`);
  assert.equal(server.lease.holder, null, 'the lease is let go after the failed step');
  server.fail = null;
  STEP.n++;
  assert.equal(await withTimeout(Promise.resolve(baker.bakeNext()), 120000, 'bakeNext() once the server is back'), 'h1', 'the retry bakes the moved light');
  const expected=B.bakeLayout(ctx.atlas,LAYOUT,[moved,k1,k2]);
  assert.ok(mean(lightSamples(expected,'h1',server.pages,key))>5,'retry writes the moved light into its new chart ownership');

  // The readiness probe: a 500 on a page the manifest names is not "missing".
  server.fail = (method, path) => method === 'GET' && /\/\d+\.png$/.test(path) ? 500 : null;
  await assert.rejects(withTimeout(Promise.resolve(makeBaker(ctx, server, lights).staleLights()), 60000, 'staleLights() over a 500'),
    error => !/did not settle/.test(error.message), 'a 500 while checking pages throws');
  server.fail = null;
});

check('existence_is_checked_without_downloading_pages', async () => {
  // M5: the readiness check asks with If-None-Match: * and downloads nothing.
  need('createBaker');
  const ctx = await setup(), server = fakeServer(), lights = [k1, k2, h1, c1], key = ctx.atlas.key;
  FILL.value = .1;
  await bakeAll(makeBaker(ctx, server, lights));
  let since = server.calls.length;
  const again = makeBaker(ctx, server, lights);
  assert.deepEqual([...await again.staleLights()], [], 'nothing stale');
  const full = server.calls.slice(since).filter(c => c.full).map(c => c.path);
  assert.deepEqual(full, [], `the readiness check downloads no page: ${full}`);

});

check('bake_now_keeps_each_light_until_its_new_bake_lands', async () => {
  // M6: a forced run keeps every light in the manifest (same keys) until each
  // one's new bake replaces it; panels never fall back to real-time mid-run.
  need('createBaker');
  const ctx = await setup(), server = fakeServer(), lights = [k1, k2, h1, c1], key = ctx.atlas.key;
  FILL.value = .1;
  await bakeAll(makeBaker(ctx, server, lights));
  const before = structuredClone(server.manifests.get(key));
  const forced = makeBaker(ctx, server, lights, { force: true });
  assert.deepEqual(asSet(await forced.staleLights()), ['c1', 'h1', 'k1', 'k2'], 'a forced run counts every light');
  const seen = [];
  for (let i = 0; i < 16; i++) {
    STEP.n++;
    const id = await withTimeout(Promise.resolve(forced.bakeNext()), 120000, 'bakeNext()');
    if (!id) break;
    seen.push(id);
    const now = server.manifests.get(key);
    assert.deepEqual(asSet(Object.keys(now.lights)), ['c1', 'h1', 'k1', 'k2'], `${id}: every light stays in the manifest`);
    for (const d of Object.keys(before.lights)) assert.equal(now.lights[d].key, before.lights[d].key, `${id}: ${d} keeps its key`);
  }
  assert.deepEqual(asSet(seen), ['c1', 'h1', 'k1', 'k2'], `the forced run re-bakes everything once: ${seen}`);
  assert.deepEqual([...await forced.staleLights()], [], 'nothing left after the forced run');
});

check('two_machines_take_turns_through_the_server_lease', async () => {
  // I8 / Ruling B17: two desks (no shared browser lock) bake one key; the server lease lets
  // one step write at a time, so neither erases the other's channel.
  need('createBaker');
  const a = await setup(), b = await setup(), server = fakeServer({ leaseRequired: true }), key = a.atlas.key;
  assert.equal(b.atlas.key, key, 'fixture: both desks draw the same atlas');
  FILL.value = .1;
  const [ra, rb] = await Promise.all([bakeAll(makeBaker(a, server, [k1, k2, h1])), bakeAll(makeBaker(b, server, [k1, k2, h1]))]);
  assert.deepEqual(server.bad, [], `every write held the lease: ${server.bad}`);
  assert.ok(server.lease.granted >= 2, `steps took the lease: ${JSON.stringify(server.lease)}`);
  assert.equal(server.lease.holder, null, 'the lease is free at the end');
  const m = server.manifests.get(key);
  assert.deepEqual(asSet(Object.keys(m.lights)), ['h1', 'k1', 'k2'], `every light landed: ${JSON.stringify(m.lights)} after ${ra} / ${rb}`);
  const packed=B.bakeLayout(a.atlas,LAYOUT,[k1,k2,h1]);
  for (const id of ['k1', 'k2']) assert.ok(mean(lightSamples(packed,id,server.pages,key))>5,`${id} kept all of its per-chart channels across desks`);
});

const only = process.argv[3] ? process.argv[3].split(',') : null;
let passed = 0, ran = 0;
for (const [name, fn] of checks) {
  if (only && !only.includes(name)) continue;
  ran++;
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 600)); }
  finally { FILL.onRead = null; }
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
           'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}}, 'layout': LAYOUT,
           'pool': POOL, 'kitchen': KITCHEN, 'hall': HALL, 'changing': CHANGING}
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps(job))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix,
                                             prefix='chauffeur_baker_', delete=False) as stream:
                paths.append(pathlib.Path(stream.name))
                stream.write(content)
        args = [exe, str(paths[0]), str(paths[1])] + ([only] if only else [])
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=900)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run(sys.argv[1] if len(sys.argv) > 1 else None) else 0)
