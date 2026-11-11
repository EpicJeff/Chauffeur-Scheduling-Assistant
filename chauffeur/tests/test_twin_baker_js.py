"""The baker's logic, in node (Task 3 of docs/superpowers/plans/2026-11-10-house-baked-lights.md,
as amended by Rulings B2-B10 in .superpowers/sdd/2026-11-10-house-baked-lights/progress.md;
the GPU half runs in Chromium in tests/test_house_twin_bake_live.py).

The house is the household's pool house (tests/fixtures/twin_model/household-2026-11-09.json
pushed through twin_store.push_round and read back with twin_store.current(), the
other buildings dropped), built with static/twin/twin_generator.js at tier 'high'
with the modern_farmhouse kit and an empty manifest, and atlased with
static/twin/bake/atlas.js at a small layout so the real Basis encoder stays fast:

    LAYOUT = {sky: {density: 1, page: 256, gutter: 2}, room: {density: 1, page: 256, gutter: 2}}

(3 sky pages and 2 room pages; the Kitchen and the Hall share room page 0, the
Changing room is on page 1). The GPU is a fake: a three.js WebGLRenderer
look-alike whose render() draws nothing and whose readRenderTargetPixels /
readRenderTargetPixelsAsync fill the buffer with one value (FILL.value in 0..1;
RGB = value and A = 1 when the buffer holds four channels per texel). The Basis
encoder and transcoder are the real vendored wasm (static/vendor/basis-universal,
static/vendor/three-r187/addons/libs/basis), loaded in node with wasmBinary.

What this file pins (the implementer matches these):

static/twin/bake/baker.js, importable in node (no DOM, no Worker at module load):
  encodePage(encoder, {width, height, channels}) -> Uint8Array (or a promise of one):
      a KTX2 file, Basis UASTC, with mipmaps (Ruling B3), from the initialised
      basis_encoder module. channels are Uint8Arrays of width*height. Two channels
      (a light bank) put channel 0 in RGB and channel 1 in A (Ruling B8:
      setSwizzle(0,0,0,1) + setForceAlpha(true)); one channel (sky) goes in R.
  decodePage(transcoder, bytes) -> {width, height, channels: [r, a]} (or a promise):
      level 0 transcoded to RGBA32 with the initialised basis_transcoder module,
      R and A as Uint8Arrays (the uncompressed fallback reads .r/.a, Ruling B8).
  createBaker(view, {renderer, atlas, layout, lights, api, codec})
      -> {staleLights(), bakeNext(), cancel(), progress()}
    view      {tier, plan, scene, renderer3, camera}: tier 'low' never bakes. The
              baker treats `view.plan` being replaced by another object (what
              twin_view's rebuild and rebuildLevel do when the model round
              changes) as a round change: the bake in flight is thrown away and
              this baker uploads nothing more (Review Focus 1).
    renderer  the WebGLRenderer the passes run on (here the fake).
    atlas     buildAtlas(group, plan, layout)'s answer; layout the {sky, room}
              options it was built with (page sizes come from there).
    lights    [{device, building, level, room, at: [x, y, z] lot feet}] in the
              order assignChannels and atlas.room.packBanks take them.
    api       (path, options) -> a fetch Response; path relative ('api/house/bakes/...',
              never root-relative). Routes as services/twin_bakes.py serves them:
                GET/PUT 'api/house/bakes/{atlas.key}'            the manifest
                POST/GET 'api/house/bakes/{atlas.key}/{page}.{ext}' a page (any ext)
              The fake server here mirrors twin_bakes._check_manifest (pages,
              lights {device: {page, channel, key}}, sky {page, channel}).
    codec     {encode(job) -> Promise<bytes>, decode(bytes) -> Promise<{width, height, channels}>};
              the test passes encodePage/decodePage over the real wasm. The page's
              own default may run them in a worker.
  staleLights() -> device ids (array, or a promise of one) whose bake is missing
      from the manifest or whose stored light key no longer matches (the key covers
      atlas.key and the light's spot).
  bakeNext() -> promise of the id it baked: 'sky' for the sky pass (baked first
      when the manifest has no sky for this key), a device id for a light, or a
      falsy value when nothing is left (or on 'low', or after a round change).
      Each step that bakes ends with exactly one manifest PUT, after the page
      POSTs it needs, so lights land one by one ("manifest written last").
  Pages and channels: the manifest's light entry {page, channel, key}; page is the
  index in the page URL; channel 0 is R and channel 1 is A of the stored page
  (Ruling B8). Light slots follow assignChannels (slot k: bank floor(k/2),
  channel k%2) and every bank is laid out by atlas.room.packBanks(lights)
  (Ruling B7: a bank holds only the rooms that need it). Rewriting a page keeps
  the other channels' data (Review Focus 4).

Skips (rather than fails) when node is unavailable.
Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_baker_js.py
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
LAYOUT = {'sky': {'density': 1, 'page': 256, 'gutter': 2}, 'room': {'density': 1, 'page': 256, 'gutter': 2}}
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
  for (const entry of [body.sky, ...Object.values(body.lights)]) {
    if (!entry || typeof entry !== 'object') return 'an entry without page and channel (the sky is required)';
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
function fakeServer() {
  const pages = new Map(), manifests = new Map(), calls = [], bad = [];
  const answer = (status, body, type) => new Response(body instanceof Uint8Array ? body.slice() : body, { status, headers: type ? { 'Content-Type': type } : {} });
  const api = async (path, options = {}) => {
    const method = String(options.method || 'GET').toUpperCase(), p = String(path).split('?')[0];
    calls.push({ method, path: p, step: STEP.n });
    if (!p.startsWith('api/house/bakes/')) { bad.push(p); return answer(404, '{"detail":"Not Found"}', 'application/json'); }
    let m = p.match(/^api\/house\/bakes\/([0-9a-f]{16,64})\/(\d+)\.(\w+)$/);
    if (m) {
      const id = `${m[1]}/${Number(m[2])}`;
      if (method === 'POST') { const b = await bytesOf(options.body); pages.set(id, b); return answer(200, JSON.stringify({ etag: `"${pages.size}-${b.length}"` }), 'application/json'); }
      if (method === 'GET') return pages.has(id) ? answer(200, pages.get(id), 'application/octet-stream') : answer(404, '{"detail":"Not Found"}', 'application/json');
      return answer(405, '{}', 'application/json');
    }
    m = p.match(/^api\/house\/bakes\/([0-9a-f]{16,64})$/);
    if (m) {
      if (method === 'PUT') {
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
  const writes = (since = 0) => calls.slice(since).filter(c => c.method !== 'GET');
  return { api, pages, manifests, calls, bad, writes };
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
const makeBaker = (ctx, server, lights) => B.createBaker(ctx.view, { renderer: ctx.renderer, atlas: ctx.atlas, layout: ctx.layout, lights, api: server.api, codec });
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
  const banks = atlas.room.packBanks(lights.map(l => ({ device: l.device, building: l.building, room: l.room })));
  const b = banks[bank], room = roomIndex(atlas, roomId);
  assert.ok(b, `atlas.room.packBanks has a bank ${bank}`);
  const charts = b.charts.filter(c => c.room === room && c.rect.w >= 3 && c.rect.h >= 3);
  assert.ok(charts.length, `room ${roomId} has charts in bank ${bank}`);
  return { page: charts[0].page, rects: charts.filter(c => c.page === charts[0].page).map(c => c.rect), banks };
}

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('stale_lights_are_only_the_changed_ones', async () => {
  need('createBaker', 'encodePage', 'decodePage');
  const ctx = await setup(), server = fakeServer(), lights = [k1, k2, h1, c1], key = ctx.atlas.key;
  const first = makeBaker(ctx, server, lights);
  assert.deepEqual(asSet(await first.staleLights()), ['c1', 'h1', 'k1', 'k2'], 'nothing baked yet: every light is stale');
  FILL.value = .08;
  const baked = await bakeAll(first);
  assert.ok(baked.includes('sky'), `the sky is baked too: ${JSON.stringify(baked)}`);
  assert.deepEqual(asSet(baked.filter(id => id !== 'sky')), ['c1', 'h1', 'k1', 'k2'], `each light baked: ${JSON.stringify(baked)}`);
  assert.equal(baked.length, new Set(baked).size, `nothing baked twice: ${JSON.stringify(baked)}`);
  assert.deepEqual([...await first.staleLights()], [], 'after the bake nothing is stale');
  assert.deepEqual(server.bad, [], `every request is a relative api/house/bakes/ path the server accepts: ${server.bad}`);
  const m1 = server.manifests.get(key);
  assert.ok(m1, `the manifest is stored under atlas.key ${key}: ${[...server.manifests.keys()]}`);
  for (const id of ['k1', 'k2', 'h1', 'c1']) {
    const e = m1.lights[id];
    assert.ok(e && Number.isInteger(e.page) && [0, 1].includes(e.channel) && KEY_RE.test(e.key), `manifest entry for ${id}: ${JSON.stringify(e)}`);
    assert.ok(server.pages.has(`${key}/${e.page}`), `${id}'s page ${e.page} was uploaded`);
  }
  assert.equal(new Set(['k1', 'k2', 'h1', 'c1'].map(id => m1.lights[id].key)).size, 4, 'every light has its own key');
  assert.equal(m1.lights.k1.page, m1.lights.k2.page, 'the two Kitchen lights share a page (one bank)');
  assert.deepEqual(asSet([m1.lights.k1.channel, m1.lights.k2.channel]), [0, 1], 'the Kitchen lights take channels 0 and 1');
  for (const b of server.pages.values()) assert.ok(isKtx2(b), 'every stored page is KTX2 (Ruling B4)');
  const kitchen = bankRects(ctx.atlas, lights, 0, job.kitchen), hall = bankRects(ctx.atlas, lights, 0, job.hall);
  assert.equal(kitchen.page, hall.page, 'fixture: the Kitchen and the Hall share bank 0\'s page');
  assert.equal(m1.lights.h1.page, m1.lights.k1.page, 'so the Hall light is on the Kitchen lights\' page');
  const before = new Map(server.pages);

  // A second page, nothing moved: nothing to bake, nothing written.
  const again = makeBaker(ctx, server, lights);
  assert.deepEqual([...await again.staleLights()], [], 'a fresh baker reads the manifest: nothing stale');
  const since = server.calls.length; STEP.n++;
  assert.ok(!(await again.bakeNext()), 'bakeNext() has nothing to do');
  assert.deepEqual(server.writes(since), [], 'and writes nothing');

  // The Hall light moves two feet: only it is stale, only its page is rewritten.
  const moved = { ...h1, at: [h1.at[0] + 2, h1.at[1], h1.at[2]] }, lights2 = [k1, k2, moved, c1];
  const third = makeBaker(ctx, server, lights2);
  assert.deepEqual([...await third.staleLights()], ['h1'], 'moving the Hall light makes only it stale');
  FILL.value = .24;
  const since3 = server.calls.length;
  assert.deepEqual(await bakeAll(third), ['h1'], 'only the moved light re-bakes (not the sky)');
  const posted = asSet(server.writes(since3).filter(c => c.method === 'POST').map(c => Number(c.path.split('/').pop().split('.')[0])));
  const m3 = server.manifests.get(key);
  assert.deepEqual(posted, [m3.lights.h1.page], `only the Hall light's page is uploaded again: ${posted}`);
  assert.notEqual(m3.lights.h1.key, m1.lights.h1.key, 'the Hall light has a new key');
  for (const id of ['k1', 'k2', 'c1']) assert.deepEqual(m3.lights[id], m1.lights[id], `${id} is untouched in the manifest`);
  const page = `${key}/${m3.lights.h1.page}`, old = rgba(before.get(page)), now = rgba(server.pages.get(page));
  for (const [id, ch] of [['k1', m1.lights.k1.channel], ['k2', m1.lights.k2.channel]]) {
    const a = channelOver(old, kitchen.rects, ch), b = channelOver(now, kitchen.rects, ch);
    assert.ok(mean(a) > 5, `${id} was baked into the page (channel ${ch} mean ${mean(a).toFixed(1)})`);
    const d = compare(a, b);
    assert.ok(d.mean <= 1.5 && d.max <= 12, `${id}'s channel keeps its data when the page is rewritten (Review Focus 4): ${JSON.stringify(d)}`);
  }
  const hallBefore = channelOver(old, hall.rects, m1.lights.h1.channel), hallAfter = channelOver(now, hall.rects, m3.lights.h1.channel);
  assert.ok(compare(hallBefore, hallAfter).mean >= 3, `the moved light's channel holds its new bake: ${JSON.stringify(compare(hallBefore, hallAfter))}`);
  for (const [id, bytes] of before) if (id !== page) assert.deepEqual(server.pages.get(id), bytes, `page ${id} is not rewritten`);

  // Other geometry (another atlas key): every light is stale again.
  const other = await setup('high', { sky: LAYOUT.sky, room: { ...LAYOUT.room, density: 2, page: 512 } });
  assert.notEqual(other.atlas.key, key, 'fixture: another layout is another atlas key');
  assert.deepEqual(asSet(await makeBaker(other, server, lights2).staleLights()), ['c1', 'h1', 'k1', 'k2'], 'a new atlas key makes every light stale');
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
  need('createBaker', 'encodePage', 'decodePage');
  const ctx = await setup(), server = fakeServer(), lights = [k1, k2, k3, h1], key = ctx.atlas.key;
  FILL.value = .1;
  const baked = await bakeAll(makeBaker(ctx, server, lights));
  assert.deepEqual(asSet(baked.filter(id => id !== 'sky')), ['h1', 'k1', 'k2', 'k3'], `every light baked: ${baked}`);
  const m = server.manifests.get(key), L = m.lights;
  assert.equal(L.k1.page, L.k2.page, 'the first two Kitchen lights share bank 0\'s page');
  assert.deepEqual(asSet([L.k1.channel, L.k2.channel]), [0, 1], 'and take its two channels');
  assert.notEqual(L.k3.page, L.k1.page, `the third Kitchen light goes to another page (a second bank): ${JSON.stringify(L)}`);
  assert.equal(L.k3.channel, 0, 'the first channel of the second bank');
  assert.equal(L.h1.page, L.k1.page, 'the Hall light stays in bank 0 (on the Kitchen\'s page in this layout)');
  assert.equal(L.h1.channel, 0, 'the Hall light is its room\'s first light');
  // Bank 1 is sparse (Ruling B7): only the Kitchen, laid out by packBanks.
  const second = bankRects(ctx.atlas, lights, 1, job.kitchen);
  assert.deepEqual(second.banks[1].rooms.map(r => r.room), [roomIndex(ctx.atlas, job.kitchen)], 'fixture: bank 1 holds the Kitchen only');
  const img = rgba(server.pages.get(`${key}/${L.k3.page}`));
  assert.ok(mean(channelOver(img, second.rects, 0)) > 5, 'the third light is baked at the Kitchen\'s place in bank 1 (packBanks), channel R');
  assert.ok(mean(channelOver(img, second.rects, 1)) <= 2, 'bank 1\'s second channel is empty: the Kitchen has no fourth light');
  const hall = bankRects(ctx.atlas, lights, 0, job.hall), page0 = rgba(server.pages.get(`${key}/${L.h1.page}`));
  assert.ok(mean(channelOver(page0, hall.rects, 0)) > 5, 'the Hall light is baked at the Hall\'s place in bank 0');
  assert.ok(mean(channelOver(page0, hall.rects, 1)) <= 2, 'the Hall has no second light: its A stays empty');
  const files = [...server.pages.keys()].filter(id => id.startsWith(key + '/'));
  const expected = ctx.atlas.sky.pages + second.banks.reduce((n, b) => n + b.pages, 0);
  assert.equal(files.length, expected, `pages stored = sky pages + each sparse bank's pages (${expected}): ${files}`);
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
  assert.ok(isKtx2(one), 'a one-channel (sky) page is KTX2 too');
  const sky = rgba(one), S = [];
  for (let i = 0; i < W * H; i++) S.push(sky.data[4 * i]);
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
    const writes = server.calls.filter(c => c.step === step && c.method !== 'GET');
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
    assert.deepEqual(asSet(Object.keys(m.lights)), asSet(done.filter(d => d !== 'sky')), `${id}: the manifest lists exactly the lights baked so far`);
    for (const e of [m.sky, ...Object.values(m.lights)]) assert.ok(server.pages.has(`${key}/${e.page}`), `${id}: every page the manifest names exists before it is named: ${JSON.stringify(e)}`);
  }
  assert.equal(done[0], 'sky', `the sky is baked first (the manifest needs it): ${done}`);
  assert.deepEqual(asSet(done.filter(d => d !== 'sky')), ['c1', 'h1', 'k1'], `every light baked: ${done}`);
  const p = baker.progress();
  assert.ok(p && p.total >= 3 && p.done === p.total, `progress() counts the lights of the run: ${JSON.stringify(p)}`);
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
