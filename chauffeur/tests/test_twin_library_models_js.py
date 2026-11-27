"""Library page Models tab event paths, levels, parts, conflicts, ownership and preview."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
globalThis.ProgressEvent = class { constructor(type, values) { Object.assign(this, values); } };
globalThis.FileReader = class {
  readAsArrayBuffer(blob) { blob.arrayBuffer().then(value => { this.result = value; this.onloadend?.(); }); }
  readAsDataURL(blob) {
    blob.arrayBuffer().then(value => {
      this.result = 'data:' + blob.type + ';base64,' + Buffer.from(value).toString('base64');
      this.onloadend?.();
    });
  }
};
globalThis.requestIdleCallback = fn => setTimeout(fn, 0);
globalThis.cancelIdleCallback = clearTimeout;
window.location = globalThis.location;

const THREE = await import('three');
const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');
THREE.TextureLoader.prototype.load = function(url, done) {
  const t = new THREE.Texture({ width: 32, height: 32 });
  queueMicrotask(() => done(t));
  return t;
};

// Same four-part test model generator as tests/test_model_parts_pipeline_js.py.
async function makeFourPartGlb() {
  const source = new THREE.Group();
  for (const [i, name] of ['Wood', '', 'Wood', 'Glass'].entries()) {
    const g = new THREE.SphereGeometry(.2, 12, 12);
    if (i === 1) g.deleteAttribute('uv');
    const m = new THREE.MeshStandardMaterial({ name, transparent: name === 'Glass', opacity: name === 'Glass' ? .4 : 1 });
    const mesh = new THREE.Mesh(g, m);
    mesh.position.set(i * .5, .2, 0);
    source.add(mesh);
  }
  const bytes = await new GLTFExporter().parseAsync(source, { binary: true });
  return { source, bytes };
}

const { bytes: FOUR_PART_BYTES } = await makeFourPartGlb();
const FOUR_PARTS = [
  { key: 'Wood', name: 'Wood', triangles: 264, has_uv: true, opaque: true },
  { key: 'unnamed', name: 'unnamed', triangles: 264, has_uv: false, opaque: true },
  { key: 'Wood~2', name: 'Wood', triangles: 264, has_uv: true, opaque: true },
  { key: 'Glass', name: 'Glass', triangles: 264, has_uv: true, opaque: false },
];

const lib = await import(file('static/twin/twin_library.js'));
const { frameThumbnailCamera } = await import(file('static/twin/model_thumbnails.js'));
const { mountLibraryPage } = await import(file('static/twin/library_page/page.js'));
const { mountModels } = await import(file('static/twin/library_page/models.js'));

const clone = x => structuredClone(x);
const pause = ms => new Promise(r => setTimeout(r, ms));
const edit = (input, type, fields) => { Object.assign(input, fields); return fire(input, type); };

const MODEL_ID = 'import-' + 'a1'.repeat(16);
const MODEL_B_ID = 'import-' + 'e5'.repeat(16);
const LEGACY_ID = 'import-' + 'b2'.repeat(16);
const BUILTIN_ID = 'mid_century_lounge_chair';
const IMPORTED_ID = 'import-' + 'c3'.repeat(16);

const matParams = { tint: '#a87c4f', roughness: .7, metalness: 0, normal_scale: 1, normal_convention: 'gl',
  ao_intensity: 1, tile_ft: [4, 4], rotation_deg: 0, random_offset: false, alpha_mode: 'opaque', opacity: 1, alpha_cutoff: .5 };
const makeMaterial = (id, name, tint = '#a87c4f') => ({
  id, name, source: 'user', revision: 1, maps: {}, params: { ...clone(matParams), tint }, licence: 'CC0',
});
const makeModel = (id, overrides = {}) => ({
  id, name: 'Test chair', kind: 'furniture', builtin: false, revision: 3,
  model: 'original.glb', files: { 'original.glb': true, 'lod1.glb': true, 'lod2.glb': true },
  size: [1.9, .4, .4], triangles: 1056,
  lod_percent: [100, 25, 5],
  lods: [
    { name: 'lod1.glb', triangles: 264, bytes: 12000, percent: 25, revision: 1 },
    { name: 'lod2.glb', triangles: 64, bytes: 4800, percent: 5, revision: 1 },
  ],
  fix: { turn: 0 },
  materials: {},
  parts: clone(FOUR_PARTS),
  parts_version: 1,
  ...overrides,
});

function createHarness({ initialSearch = '?model=' + MODEL_ID, models: seedModels, extraManifest = {}, hooks = {} } = {}) {
  const host = document.createElement('main');
  document.body.append(host);
  const calls = [], alerts = [];
  const materials = new Map([
    ['material-oak', makeMaterial('material-oak', 'Oak', '#a87c4f')],
    ['material-walnut', makeMaterial('material-walnut', 'Walnut', '#5c3d28')],
  ]);
  const models = new Map((seedModels || [
    makeModel(MODEL_ID),
    makeModel(BUILTIN_ID, {
      name: 'Mid-century lounge chair', builtin: true, revision: 1,
      model: 'chair.gltf', files: { 'chair.gltf': true }, lods: [],
    }),
  ]).map(m => [m.id, clone(m)]));
  const history = new Map();
  for (const id of models.keys()) history.set(id, { undo: [], redo: [] });
  window.twinManifest = {
    ...Object.fromEntries([...materials.values()].map(m => [
      m.id, { kind: 'material', household: true, revision: m.revision, params: clone(m.params), maps: { base_color: `materials/${m.id}/base.png` } },
    ])),
    ...clone(extraManifest),
  };
  window.twinKit = { materials: {}, manifest: window.twinManifest };
  window.showGlobalAlert = msg => alerts.push(msg);
  window.promptConfirm = async () => true;
  window.promptChoice = async () => '0';
  for (const name of ['alert', 'confirm', 'prompt']) window[name] = () => { throw Error('browser dialog'); };

  const uploads = new Map();
  let uploadSeq = 0;

  globalThis.fetch = async (input) => {
    const url = typeof input === 'string' ? input : input.url;
    const m = url.match(/\/api\/house\/models\/([^/?]+)$/);
    if (m) {
      const rec = models.get(decodeURIComponent(m[1]));
      return new Response(JSON.stringify(rec || { detail: 'No such model.' }), { status: rec ? 200 : 404 });
    }
    return new Response(FOUR_PART_BYTES, { status: 200, headers: { 'Content-Length': String(FOUR_PART_BYTES.byteLength) } });
  };

  const api = async (path, method = 'GET', body) => {
    calls.push({ path, method, body: body instanceof Blob ? body : clone(body) });
    if (hooks.api) {
      const overridden = await hooks.api(path, method, body, { models, materials, uploads });
      if (overridden !== undefined) return overridden;
    }
    if (path === 'materials' && method === 'GET') {
      // Real GET /api/house/materials returns summary rows without maps/params and omits archived materials.
      return { materials: [...materials.values()].map(m => ({ id: m.id, name: m.name, source: m.source, revision: m.revision, color: m.params.tint, builtin: m.source === 'builtin' })) };
    }
    if (path === 'materials' && method === 'POST') {
      const entry = makeMaterial('material-gltf-new', body.name || 'Wood');
      materials.set(entry.id, entry);
      return clone(entry);
    }
    if (path.startsWith('materials/') && method === 'GET') {
      return clone(materials.get(decodeURIComponent(path.slice(10))));
    }
    if (path.startsWith('materials/') && method === 'PATCH') {
      const id = decodeURIComponent(path.slice(10)), mat = materials.get(id);
      if (hooks.materialPatch) await hooks.materialPatch(id, body, mat);
      mat.params = { ...mat.params, ...body.params };
      if (body.name) mat.name = body.name;
      mat.revision += 1;
      return clone(mat);
    }
    if (path === 'models' && method === 'GET') {
      return { models: [...models.values()].map(clone) };
    }
    const modelAction = path.match(/^models\/([^/]+)\/(undo|redo|reset)$/);
    if (modelAction && method === 'POST') {
      const id = decodeURIComponent(modelAction[1]), op = modelAction[2];
      const rec = models.get(id);
      if (body?.revision !== rec.revision) {
        throw Object.assign(new Error('This model changed in another tab.'), { status: 409, record: clone(rec) });
      }
      const h = history.get(id) || { undo: [], redo: [] };
      const snap = r => ({ lod_percent: clone(r.lod_percent), fix: clone(r.fix), materials: clone(r.materials) });
      if (op === 'undo') {
        const prev = h.undo.pop();
        if (!prev) throw Object.assign(new Error('No model undo is available.'), { status: 400 });
        h.redo.push(snap(rec));
        Object.assign(rec, prev);
      } else if (op === 'redo') {
        const next = h.redo.pop();
        if (!next) throw Object.assign(new Error('No model redo is available.'), { status: 400 });
        h.undo.push(snap(rec));
        Object.assign(rec, next);
      } else if (op === 'reset') {
        h.undo.push(snap(rec)); h.redo = [];
        rec.lod_percent = [100, 25, 5]; rec.fix = { turn: 0 }; rec.materials = {};
      }
      rec.revision += 1;
      return clone(rec);
    }
    const modelPath = path.match(/^models\/([^/]+)$/);
    if (modelPath) {
      const id = decodeURIComponent(modelPath[1]), rec = models.get(id);
      if (!rec) throw Object.assign(new Error('No such model.'), { status: 404 });
      if (method === 'GET') return clone(rec);
      if (method === 'PATCH') {
        if (hooks.patch) {
          const custom = await hooks.patch(id, body, rec);
          if (custom !== undefined) return custom;
        }
        if (body.revision !== rec.revision) {
          throw Object.assign(new Error('This model changed in another tab. Reload its current record.'), { status: 409, record: clone(rec) });
        }
        const h = history.get(id) || { undo: [], redo: [] };
        h.undo.push({ lod_percent: clone(rec.lod_percent), fix: clone(rec.fix), materials: clone(rec.materials) });
        h.redo = [];
        if ('parts' in body) rec.parts = clone(body.parts);
        if ('parts_version' in body) rec.parts_version = body.parts_version;
        if ('lod_percent' in body) {
          const old = rec.lod_percent;
          rec.lod_percent = clone(body.lod_percent);
          ['lod0.glb', 'lod1.glb', 'lod2.glb'].forEach((name, i) => {
            if (old[i] !== rec.lod_percent[i] || (i === 0 && rec.lod_percent[0] === 100)) {
              rec.lods = rec.lods.filter(l => l.name !== name);
              if (i === 0 && rec.lod_percent[0] === 100) delete rec.files['lod0.glb'];
            }
          });
        }
        if ('fix' in body) rec.fix = clone(body.fix);
        if ('materials' in body) rec.materials = clone(body.materials);
        rec.revision += 1;
        return clone(rec);
      }
    }
    if (path === 'editor/imports/uploads' && method === 'POST') {
      const uid = 'up-' + (++uploadSeq);
      uploads.set(uid, { meta: clone(body), chunks: [] });
      return { upload_id: uid, chunk_bytes: 4 * 1024 * 1024 };
    }
    const chunkPath = path.match(/^editor\/imports\/uploads\/([^/]+)\/(\d+)$/);
    if (chunkPath && method === 'PUT') {
      uploads.get(chunkPath[1])?.chunks.push(body);
      return { ok: true };
    }
    const finishPath = path.match(/^editor\/imports\/uploads\/([^/]+)\/finish$/);
    if (finishPath && method === 'POST') {
      const up = uploads.get(finishPath[1]);
      if (hooks.finishUpload) {
        const custom = await hooks.finishUpload(up.meta, models);
        if (custom !== undefined) return custom;
      }
      if (up.meta.lod && up.meta.asset_id) {
        const rec = models.get(up.meta.asset_id);
        const idx = ['lod0.glb', 'lod1.glb', 'lod2.glb'].indexOf(up.meta.lod);
        if (rec.lod_percent[idx] !== up.meta.percent) {
          throw Object.assign(new Error('These detail percentages changed. Rebuild the current level.'), { status: 409, record: clone(rec) });
        }
        const prevRev = rec.lods.find(l => l.name === up.meta.lod)?.revision || 0;
        rec.lods = rec.lods.filter(l => l.name !== up.meta.lod);
        rec.lods.push({ name: up.meta.lod, triangles: Math.max(12, Math.round(1056 * up.meta.percent / 100)), bytes: up.meta.size || 2048, percent: up.meta.percent, revision: prevRev + 1 });
        rec.files[up.meta.lod] = true;
        rec.revision += 1;
        return clone(rec);
      }
      const created = makeModel(IMPORTED_ID, {
        name: up.meta.name || 'Imported', revision: 1, lods: [], parts: [], parts_version: undefined,
        files: { 'original.glb': true },
      });
      models.set(created.id, created);
      history.set(created.id, { undo: [], redo: [] });
      return clone(created);
    }
    const cancelPath = path.match(/^editor\/imports\/uploads\/([^/]+)$/);
    if (cancelPath && method === 'DELETE') { uploads.delete(cancelPath[1]); return { ok: true }; }
    const importPath = path.match(/^editor\/imports\/([^/]+)$/);
    if (importPath && method === 'PATCH') {
      const id = decodeURIComponent(importPath[1]), rec = models.get(id);
      if (body.name) rec.name = body.name;
      if (body.kind) rec.kind = body.kind;
      if (body.size) rec.size = body.size;
      if (body.triangles != null) rec.triangles = body.triangles;
      if (body.thumbnail) { rec.thumbnail = '.thumbnail.png'; rec.files['.thumbnail.png'] = true; }
      rec.revision += 1;
      return clone(rec);
    }
    if (importPath && method === 'DELETE') {
      models.delete(decodeURIComponent(importPath[1]));
      return { ok: true };
    }
    throw Object.assign(new Error(`Unhandled test route: ${method} ${path}`), { status: 404 });
  };

  for (const id of [MODEL_ID, MODEL_B_ID, LEGACY_ID, BUILTIN_ID, IMPORTED_ID]) lib.forgetImport(id);
  location.search = initialSearch;
  return { host, api, calls, alerts, models, materials, cleanup(page) { page?.stop(); host.remove(); } };
}

await test('tab_and_deeplink', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  assert.equal(c.host.querySelector('[data-library-tab="models"]').getAttribute('aria-selected'), 'true');
  assert.equal(c.host.querySelector('[data-library-tab="materials"]').getAttribute('aria-selected'), 'false');
  assert.equal(c.host.querySelector(`[data-model="${MODEL_ID}"]`).getAttribute('aria-pressed'), 'true');
  assert.equal(window.twinManifest['material-oak'].maps.base_color, 'materials/material-oak/base.png', 'summary rows preserve manifest maps');
  await click(c.host.querySelector('[data-library-tab="materials"]'));
  await pause(30);
  assert.equal(c.host.querySelector('[data-library-tab="materials"]').getAttribute('aria-selected'), 'true');
  assert.ok(c.host.querySelector('[data-material="material-oak"]'), 'Materials tab shows materials grid');
  c.cleanup(page);
});

await test('import_on_models_tab', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  const glbFile = new File([FOUR_PART_BYTES], 'new_chair.glb', { type: 'model/gltf-binary' });
  const right = c.host.querySelector('.library-properties');
  assert.ok(right, 'Models right panel exists');
  await fire(right, 'drop', { dataTransfer: { files: [glbFile], types: ['Files'] } });
  for (let i = 0; i < 80 && (c.models.get(IMPORTED_ID)?.lods?.length || 0) < 2; i++) {
    tick();
    await pause(15);
  }
  assert.ok(c.calls.some(x => x.path === 'editor/imports/uploads' && x.method === 'POST'), 'chunked upload started');
  assert.ok(c.calls.some(x => x.path.startsWith('editor/imports/uploads/') && x.method === 'PUT'), 'chunk uploaded');
  assert.ok(c.calls.some(x => x.path === `models/${IMPORTED_ID}` && x.method === 'PATCH' && x.body.parts_version === 1), 'parts stamped via buildLevels');
  assert.equal(c.models.get(IMPORTED_ID).lods.length, 2, 'mid and far levels uploaded');

  await click(c.host.querySelector('[data-library-tab="materials"]'));
  await pause(30);
  c.calls.length = 0;
  const matRight = c.host.querySelector('.library-properties');
  await fire(matRight, 'drop', { dataTransfer: { files: [glbFile], types: ['Files'] } });
  await pause(40);
  assert.ok(c.calls.some(x => x.path === 'materials' && x.method === 'POST'), 'Materials tab drop calls importGltf');
  assert.equal(c.calls.some(x => x.path === 'editor/imports/uploads'), false, 'Materials tab drop does not call model chunked upload');
  c.cleanup(page);
});

await test('last_percent_wins', async () => {
  // Schedule two edits 10 ms apart independently of build progress, with a stale 409 from the first build.
  let stale409Count = 0;
  const c = createHarness({
    initialSearch: '?model=' + MODEL_ID,
    hooks: {
      async finishUpload(meta, models) {
        if (meta.lod === 'lod1.glb' && meta.percent === 40) {
          await pause(40);
          stale409Count++;
          const rec = models.get(meta.asset_id);
          throw Object.assign(new Error('These detail percentages changed. Rebuild the current level.'), { status: 409, record: clone(rec) });
        }
        return undefined;
      },
    },
  });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  const midInput = c.host.querySelector('[data-lod-percent="1"]');
  assert.ok(midInput, 'Mid percentage input exists');
  // Fire edit 1, pause 10 ms (independent of build progress), fire edit 2.
  const firstEdit = edit(midInput, 'change', { value: '40' });
  await pause(10);
  const secondEdit = edit(midInput, 'change', { value: '30' });
  await Promise.all([firstEdit, secondEdit]);
  for (let i = 0; i < 80 && c.models.get(MODEL_ID).lods.find(l => l.name === 'lod1.glb')?.percent !== 30; i++) {
    tick();
    await pause(15);
  }
  assert.deepEqual(c.models.get(MODEL_ID).lod_percent, [100, 30, 5]);
  assert.equal(c.models.get(MODEL_ID).lods.find(l => l.name === 'lod1.glb')?.percent, 30);
  assert.equal(c.alerts.length, 0, 'stale 409 from superseded percent build is silently ignored');
  // Switch to Mid and verify the final displayed level reflects the 30% level.
  await click(c.host.querySelector('[data-model-level="1"]'));
  await pause(30);
  assert.match(c.host.querySelector('[data-level-stats]').textContent, /Mid \(30%\)/);
  assert.equal(page.modelsView.preview.currentModel.userData.modelMaterialKey[1], 'lod1.glb');
  assert.ok(stale409Count <= 1);
  c.cleanup(page);
});

await test('conflict_reloads', async () => {
  let rejectOnce = true;
  const c = createHarness({
    initialSearch: '?model=' + MODEL_ID,
    hooks: {
      async patch(id, body, rec) {
        if (rejectOnce) {
          rejectOnce = false;
          rec.revision += 1;
          rec.fix = { turn: 180 };
          throw Object.assign(new Error('This model changed in another tab. Reload its current record.'), { status: 409, record: clone(rec) });
        }
        return undefined;
      },
    },
  });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  await click(c.host.querySelector('[data-turn="90"]'));
  await pause(40);
  assert.equal(c.alerts.length, 1, 'calls showGlobalAlert once on 409');
  assert.equal(c.host.querySelector('[data-turn="180"]').getAttribute('aria-pressed'), 'true', 'reloaded record applied to UI');
  c.cleanup(page);
});

await test('part_rows', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  const rows = c.host.querySelectorAll('[data-model-part]');
  assert.equal(rows.length, 4, 'four rows for four-part fixture');
  const woodRow = c.host.querySelector('[data-model-part="Wood"]');
  const noUvRow = c.host.querySelector('[data-model-part="unnamed"]');
  assert.equal(noUvRow.querySelector('[data-part-texture="model"]').disabled, true, 'no-uv row has Models own disabled');
  assert.equal(woodRow.querySelector('[data-part-texture="model"]').disabled, false, 'uv row enables Models own');
  assert.equal(shown(woodRow.querySelector('[data-part-tiles]')), false, 'Tiles hidden in Real size mode');
  await click(c.host.querySelector('[data-palette-material="material-oak"]'));
  await click(woodRow.querySelector('[data-slot-use]'));
  await pause(40);
  assert.equal(c.models.get(MODEL_ID).materials.Wood.material, 'material-oak');
  assert.equal(shown(woodRow.querySelector('[data-part-tiles]')), false, 'Tiles still hidden in Real size');
  await click(woodRow.querySelector('[data-part-texture="model"]'));
  await pause(40);
  assert.equal(c.models.get(MODEL_ID).materials.Wood.texture, 'model');
  assert.equal(shown(woodRow.querySelector('[data-part-tiles]')), true, 'Tiles shown in Models own');
  await click(woodRow.querySelector('[data-slot-clear]'));
  await pause(40);
  assert.equal('Wood' in c.models.get(MODEL_ID).materials, false, 'Clear sends materials without that key');
  c.cleanup(page);
});

await test('size_and_turn', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  const axis = c.host.querySelector('[data-fix-axis]');
  const feet = c.host.querySelector('[data-fix-feet]');
  const inches = c.host.querySelector('[data-fix-inches]');
  axis.value = 'height_m';
  feet.value = '2';
  await edit(inches, 'change', { value: '6' });
  await pause(40);
  const fixPatch = c.calls.filter(x => x.path === `models/${MODEL_ID}` && x.method === 'PATCH' && x.body.fix).at(-1);
  assert.ok(Math.abs(fixPatch.body.fix.height_m - 0.762) < 1e-6, '2 ft 6 in height PATCHes height_m 0.762');
  await click(c.host.querySelector('[data-action="turn-90"]'));
  await pause(40);
  const turnPatch = c.calls.filter(x => x.path === `models/${MODEL_ID}` && x.method === 'PATCH' && x.body.fix).at(-1);
  assert.equal(turnPatch.body.fix.turn, 90, 'quarter turn sends turn: 90');
  c.cleanup(page);
});

await test('builtin_no_levels', async () => {
  const c = createHarness({ initialSearch: '?model=' + BUILTIN_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  const levelsSection = c.host.querySelector('[data-model-levels]');
  assert.ok(!levelsSection || !shown(levelsSection), 'built-in hides Detail levels');
  const delBtn = c.host.querySelector('[data-action="delete"]');
  assert.ok(!delBtn || !shown(delBtn), 'built-in hides Delete');
  assert.ok(shown(c.host.querySelector('[data-model-parts]')), 'built-in shows Parts');
  assert.ok(shown(c.host.querySelector('[data-model-fix]')), 'built-in shows Size');
  c.cleanup(page);
});

await test('old_import_regenerates', async () => {
  const legacy = makeModel(LEGACY_ID, {
    name: 'Legacy chair', revision: 1, parts: [], parts_version: undefined,
    lods: [{ name: 'lod1.glb', triangles: 264, bytes: 12000, percent: 25, revision: 0 }],
  });
  const c = createHarness({ initialSearch: '?model=' + LEGACY_ID, models: [legacy] });
  let buildCalls = 0;
  const progressSeen = [];
  const host = document.createElement('div'); document.body.append(host);
  const view = mountModels(host, {
    api: c.api,
    initialModelId: LEGACY_ID,
    buildLevels: async (rec, src, opts) => {
      buildCalls++;
      opts.progress('Making lighter versions… 1 of 2');
      progressSeen.push(host.querySelector('[data-model-progress]')?.textContent || '');
      return await opts.patch({ parts: clone(FOUR_PARTS), parts_version: 1 });
    },
  });
  await view.ready;
  await pause(40);
  assert.equal(buildCalls, 1, 'calls buildLevels once for record without parts_version');
  assert.ok(progressSeen.some(t => /Making lighter versions/.test(t)), 'shows rebuild progress');
  assert.equal(host.querySelectorAll('[data-model-part]').length, 4, 'parts appear after stamp');
  view.stop(); host.remove(); c.host.remove();
});

await test('undo_redo_reset_buttons', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  await click(c.host.querySelector('[data-turn="90"]'));
  await pause(40);
  const revAfterTurn = c.models.get(MODEL_ID).revision;
  await click(c.host.querySelector('[data-action="undo"]'));
  await pause(40);
  const undoCall = c.calls.find(x => x.path === `models/${MODEL_ID}/undo` && x.method === 'POST');
  assert.deepEqual(undoCall.body, { revision: revAfterTurn });
  assert.equal(c.host.querySelector('[data-turn="0"]').getAttribute('aria-pressed'), 'true');
  const revAfterUndo = c.models.get(MODEL_ID).revision;
  await click(c.host.querySelector('[data-action="redo"]'));
  await pause(40);
  const redoCall = c.calls.find(x => x.path === `models/${MODEL_ID}/redo` && x.method === 'POST');
  assert.deepEqual(redoCall.body, { revision: revAfterUndo });
  assert.equal(c.host.querySelector('[data-turn="90"]').getAttribute('aria-pressed'), 'true');
  const revAfterRedo = c.models.get(MODEL_ID).revision;
  await click(c.host.querySelector('[data-action="reset"]'));
  await pause(40);
  const resetCall = c.calls.find(x => x.path === `models/${MODEL_ID}/reset` && x.method === 'POST');
  assert.deepEqual(resetCall.body, { revision: revAfterRedo });
  assert.equal(c.host.querySelector('[data-turn="0"]').getAttribute('aria-pressed'), 'true');
  c.cleanup(page);
});

await test('thumbnail_rerenders', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  // Spy on canvas.toDataURL so we prove the captured preview thumbnail (not the constant fallback) is sent.
  const canvas = c.host.querySelector('.library-preview canvas');
  let captureCount = 0;
  canvas.toDataURL = () => `data:image/png;base64,SPIED_CAPTURE_${++captureCount}`;

  c.calls.length = 0;
  await click(c.host.querySelector('[data-turn="90"]'));
  await pause(60);
  const thumbPatch = c.calls.find(x => x.path === `editor/imports/${MODEL_ID}` && x.method === 'PATCH' && x.body?.thumbnail);
  assert.ok(thumbPatch, 'fix change sends new thumbnail through PATCH editor/imports/{id}');
  assert.equal(thumbPatch.body.thumbnail, 'data:image/png;base64,SPIED_CAPTURE_1', 'spied preview capture sent for fix');

  c.calls.length = 0;
  await click(c.host.querySelector('[data-palette-material="material-oak"]'));
  await click(c.host.querySelector('[data-model-part="Wood"] [data-slot-use]'));
  await pause(60);
  const thumbPatch2 = c.calls.find(x => x.path === `editor/imports/${MODEL_ID}` && x.method === 'PATCH' && x.body?.thumbnail);
  assert.ok(thumbPatch2, 'parts change sends new thumbnail through PATCH editor/imports/{id}');
  assert.equal(thumbPatch2.body.thumbnail, 'data:image/png;base64,SPIED_CAPTURE_2', 'spied preview capture sent for part change');
  c.cleanup(page);
});

await test('preview_part_at_highlight_wireframe_and_drop', async () => {
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(40);
  tick();
  const preview = page.modelsView.preview;
  const canvas = c.host.querySelector('.library-preview canvas');
  const pt = preview.partScreenPoint('Wood');
  assert.ok(pt && Number.isFinite(pt.x) && Number.isFinite(pt.y), 'partScreenPoint resolves Wood');
  assert.equal(preview.partAt(pt.x, pt.y), 'Wood', 'partAt raycasts the Wood part');

  preview.setWireframe(true);
  assert.equal(preview.isWireframe(), true);
  preview.setWireframe(false);

  // Dispatch real dragstart -> dragover (highlight) -> drop (override saved) on the canvas.
  const store = {};
  const dt = {
    types: ['application/x-chauffeur-material'],
    setData(k, v) { store[k] = v; },
    getData(k) { return store[k] || ''; },
  };
  const oakTile = c.host.querySelector('[data-palette-material="material-oak"]');
  await fire(oakTile, 'dragstart', { dataTransfer: dt });
  await fire(canvas, 'dragover', { clientX: pt.x, clientY: pt.y, dataTransfer: dt });
  assert.equal(preview.highlightedPart(), 'Wood', 'dragover highlights Wood part');
  await fire(canvas, 'drop', { clientX: pt.x, clientY: pt.y, dataTransfer: dt });
  await fire(oakTile, 'dragend', { dataTransfer: dt });
  await pause(50);
  assert.equal(preview.highlightedPart(), null, 'drop clears highlight');
  assert.equal(c.models.get(MODEL_ID).materials.Wood?.material, 'material-oak', 'drop saves Oak on Wood');
  c.cleanup(page);
});

// Regression 1: percentage edits immediately reconcile displayed level (including 60% -> 100% Full).
await test('percent_edit_reconciles_preview', async () => {
  const full60 = makeModel(MODEL_ID, {
    lod_percent: [60, 25, 5],
    files: { 'original.glb': true, 'lod0.glb': true, 'lod1.glb': true, 'lod2.glb': true },
    lods: [
      { name: 'lod0.glb', triangles: 630, bytes: 24000, percent: 60, revision: 1 },
      { name: 'lod1.glb', triangles: 264, bytes: 12000, percent: 25, revision: 1 },
      { name: 'lod2.glb', triangles: 64, bytes: 4800, percent: 5, revision: 1 },
    ],
  });
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID, models: [full60] });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(40);
  assert.equal(page.modelsView.preview.currentModel.userData.modelMaterialKey[1], 'lod0.glb', 'initially displays lod0.glb at 60%');

  // Change Full from 60% back to 100%: server removes lod0.glb and no build runs; preview must immediately switch to original.glb.
  const fullInput = c.host.querySelector('[data-lod-percent="0"]');
  await edit(fullInput, 'change', { value: '100' });
  await pause(50);
  assert.equal(page.modelsView.preview.currentModel.userData.modelMaterialKey[1], 'original.glb', '100% Full immediately reloads original.glb');

  // Switch to Mid (25%), then edit Mid to 40%: preview must immediately fall back to valid Full while Mid rebuilds.
  await click(c.host.querySelector('[data-model-level="1"]'));
  await pause(40);
  assert.equal(page.modelsView.preview.currentModel.userData.modelMaterialKey[1], 'lod1.glb');
  const midInput = c.host.querySelector('[data-lod-percent="1"]');
  await edit(midInput, 'change', { value: '40' });
  await pause(40);
  assert.equal(c.host.querySelector('[data-model-level="0"]').getAttribute('aria-pressed'), 'true', 'falls back to Full while Mid rebuilds');
  assert.equal(page.modelsView.preview.currentModel.userData.modelMaterialKey[1], 'original.glb');
  c.cleanup(page);
});

// Regression 2: archived household material present in page_manifest (without archived flag) falls back to original and warns once.
await test('archived_material_falls_back_and_warns_once', async () => {
  const archivedId = 'material-archived-oak';
  const rec = makeModel(MODEL_ID, {
    materials: { Wood: { material: archivedId, texture: 'real' } },
  });
  const c = createHarness({
    initialSearch: '?model=' + MODEL_ID,
    models: [rec],
    // Mirror services/twin_materials.py:page_manifest(), which omits archived:true on archived household materials.
    extraManifest: {
      [archivedId]: { kind: 'material', household: true, revision: 1, params: clone(matParams), maps: {} },
    },
  });
  const warns = [];
  const origWarn = console.warn;
  console.warn = (...args) => warns.push(args.join(' '));
  try {
    const page = mountLibraryPage(c.host, { api: c.api });
    await page.ready;
    await pause(40);
    const woodMesh = () => {
      let found = null;
      page.modelsView.preview.currentModel.traverse(o => { if (o.isMesh && o.userData.partKey === 'Wood') found = o; });
      return found;
    };
    assert.equal(woodMesh().material.name, 'Wood', 'archived override falls back to original material');
    // Reload via Mid level and verify original stays and warning fires only once total.
    await click(c.host.querySelector('[data-model-level="1"]'));
    await pause(40);
    assert.equal(woodMesh().material.name, 'Wood', 'repeated load keeps original material');
    assert.equal(warns.filter(w => w.includes('Wood')).length, 1, 'warns once across repeated loads');
    c.cleanup(page);
  } finally {
    console.warn = origWarn;
  }
});

// Regression 3: preview disposes every preview-owned geometry on swap/stop and never disposes shared cache materials while live.
await test('preview_disposes_owned_resources_and_keeps_shared_cache', async () => {
  const recA = makeModel(MODEL_ID, { thumbnail: '.thumbnail.png', materials: { Wood: { material: 'material-oak', texture: 'real' } } });
  const recB = makeModel(MODEL_B_ID, { name: 'Second chair', thumbnail: '.thumbnail.png' });
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID, models: [recA, recB] });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(40);

  const trackedGeos = new Set(), disposedGeos = new Set();
  const trackCurrent = () => {
    const m = page.modelsView.preview.currentModel;
    assert.ok(m, 'current model loaded');
    m.traverse(o => {
      if (o.isMesh && o.geometry && !trackedGeos.has(o.geometry)) {
        trackedGeos.add(o.geometry);
        o.geometry.addEventListener('dispose', () => disposedGeos.add(o.geometry));
      }
    });
  };
  let sharedMat = null, sharedMatDisposedBeforeStop = 0, sharedMatDisposedTotal = 0;
  page.modelsView.preview.currentModel.traverse(o => {
    if (o.isMesh && o.userData.partKey === 'Wood') sharedMat = o.material;
  });
  assert.ok(sharedMat, 'Wood uses shared material from cache');
  sharedMat.addEventListener('dispose', () => { sharedMatDisposedTotal++; });

  trackCurrent(); // Full of A (4 geometries)
  await click(c.host.querySelector('[data-model-level="1"]'));
  await pause(40);
  trackCurrent(); // Mid of A (4 more geometries)
  sharedMatDisposedBeforeStop = sharedMatDisposedTotal;
  assert.equal(sharedMatDisposedBeforeStop, 0, 'shared cache material not disposed while swapping levels');

  await click(c.host.querySelector(`[data-model="${MODEL_B_ID}"]`));
  await pause(40);
  trackCurrent(); // Full of B (4 more geometries)
  assert.equal(sharedMatDisposedTotal, 0, 'shared cache material not disposed while switching models');
  assert.equal(trackedGeos.size, 12, '12 preview geometries tracked across Full -> Mid -> Model B');

  c.cleanup(page);
  assert.equal(disposedGeos.size, trackedGeos.size, 'every preview-owned geometry disposed by stop');
  assert.equal(sharedMatDisposedTotal, 1, 'shared cache material disposed cleanly on teardown');
});

// Regression R1-1: refreshing a material while a Mid preview load is in flight ends on the new revision
// and disposes every retired material (including any late material allocated by the superseded load).
await test('material_refresh_during_preview_load_uses_new_revision_and_disposes_retired', async () => {
  const rec = makeModel(MODEL_ID, {
    thumbnail: '.thumbnail.png',
    materials: { Wood: { material: 'material-oak', texture: 'real' } },
  });
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID, models: [rec] });
  // Set Oak revision 1 to brown.
  c.materials.get('material-oak').params.tint = '#8b4513';
  window.twinManifest['material-oak'].params.tint = '#8b4513';

  let releaseHeldMid, heldMidStarted = false;
  const heldMidGate = new Promise(r => { releaseHeldMid = r; });
  const createdMaterials = new Set(), disposedMaterials = new Set();
  const trackMaterials = obj => {
    obj?.traverse(o => {
      const mat = o.isMesh ? o.material : null;
      if (mat && !createdMaterials.has(mat)) {
        createdMaterials.add(mat);
        mat.addEventListener('dispose', () => disposedMaterials.add(mat));
      }
    });
  };
  let midLoadCount = 0;
  const host = document.createElement('div'); document.body.append(host);
  const view = mountModels(host, {
    api: c.api,
    initialModelId: MODEL_ID,
    materials: [...c.materials.values()].map(clone),
    loadModel: async (id, kit, onLate, opts) => {
      if (opts?.lodName === 'lod1.glb' && ++midLoadCount === 1) {
        heldMidStarted = true;
        await heldMidGate;
      }
      const loaded = await lib.loadModel(id, kit, onLate, opts);
      trackMaterials(loaded);
      return loaded;
    },
  });
  await view.ready;
  await pause(40);
  trackMaterials(view.preview.currentModel);
  const woodMat = () => {
    let mat = null;
    view.preview.currentModel?.traverse(o => { if (o.isMesh && o.userData.partKey === 'Wood') mat = o.material; });
    return mat;
  };
  assert.equal(woodMat().userData.materialRevision, 1, 'initial Full uses Oak rev 1');

  // Start Mid load (held in flight with rev 1 brown kit).
  const midClick = click(host.querySelector('[data-model-level="1"]'));
  for (let i = 0; i < 30 && !heldMidStarted; i++) await pause(10);
  assert.equal(heldMidStarted, true, 'first Mid load is held in flight');

  // Refresh Oak to revision 2 (green) while the first Mid load is still pending.
  const oakRev2 = { ...clone(c.materials.get('material-oak')), revision: 2, params: { ...clone(matParams), tint: '#22aa44' }, maps: {} };
  window.twinManifest['material-oak'] = { kind: 'material', household: true, revision: 2, params: clone(oakRev2.params), maps: {} };
  view.setMaterials([oakRev2, clone(c.materials.get('material-walnut'))]);
  await pause(50);
  trackMaterials(view.preview.currentModel);
  assert.equal(woodMat().userData.materialRevision, 2, 'restarted Mid load renders Oak rev 2');
  assert.equal(woodMat().color.getHexString(), '22aa44', 'preview shows rev 2 green');

  // Now release the stale held Mid load from rev 1.
  releaseHeldMid();
  await midClick;
  await pause(50);
  assert.equal(woodMat().userData.materialRevision, 2, 'late rev 1 load must not revert preview');
  assert.equal(woodMat().color.getHexString(), '22aa44', 'preview stays on rev 2 green');

  // Every retired rev-1 material and rev-2 material must be disposed by stop().
  view.stop();
  host.remove();
  c.host.remove();
  assert.ok(createdMaterials.size >= 4, 'tracked multiple materials across loads');
  assert.equal(disposedMaterials.size, createdMaterials.size, 'every retired and active material disposed by stop');
});

// Regression R2-1 (inverse completion order): holding both the first rev-1 Mid load and the restarted
// rev-2 Mid load, then releasing the stale rev-1 Mid load first, must not dispose any material of the
// displayed Full mesh while Full is still on screen; rev-1 disposes once Mid rev-2 replaces Full.
await test('material_refresh_inverse_completion_keeps_displayed_materials_alive', async () => {
  const rec = makeModel(MODEL_ID, {
    thumbnail: '.thumbnail.png',
    materials: { Wood: { material: 'material-oak', texture: 'real' } },
  });
  const c = createHarness({ initialSearch: '?model=' + MODEL_ID, models: [rec] });
  c.materials.get('material-oak').params.tint = '#8b4513';
  window.twinManifest['material-oak'].params.tint = '#8b4513';

  let releaseFirstMid, releaseSecondMid, firstMidStarted = false, secondMidStarted = false;
  const firstMidGate = new Promise(r => { releaseFirstMid = r; });
  const secondMidGate = new Promise(r => { releaseSecondMid = r; });
  const createdMaterials = new Set(), disposedMaterials = new Set();
  const trackMaterials = obj => {
    obj?.traverse(o => {
      const mat = o.isMesh ? o.material : null;
      if (mat && !createdMaterials.has(mat)) {
        createdMaterials.add(mat);
        mat.addEventListener('dispose', () => disposedMaterials.add(mat));
      }
    });
  };
  const liveMaterialsOf = obj => {
    const out = new Set();
    obj?.traverse(o => { if (o.isMesh && o.material) out.add(o.material); });
    return out;
  };
  let midLoadCount = 0;
  const host = document.createElement('div'); document.body.append(host);
  const view = mountModels(host, {
    api: c.api,
    initialModelId: MODEL_ID,
    materials: [...c.materials.values()].map(clone),
    loadModel: async (id, kit, onLate, opts) => {
      if (opts?.lodName === 'lod1.glb') {
        const n = ++midLoadCount;
        if (n === 1) { firstMidStarted = true; await firstMidGate; }
        else if (n === 2) { secondMidStarted = true; await secondMidGate; }
      }
      const loaded = await lib.loadModel(id, kit, onLate, opts);
      trackMaterials(loaded);
      return loaded;
    },
  });
  await view.ready;
  await pause(40);
  const initialFull = view.preview.currentModel;
  trackMaterials(initialFull);
  const woodMat = () => {
    let mat = null;
    view.preview.currentModel?.traverse(o => { if (o.isMesh && o.userData.partKey === 'Wood') mat = o.material; });
    return mat;
  };
  const rev1Wood = woodMat();
  assert.equal(rev1Wood.userData.materialRevision, 1, 'initial Full uses Oak rev 1');

  // Hold first Mid load (rev 1), refresh Oak to rev 2, and hold restarted Mid load (rev 2).
  const midClick = click(host.querySelector('[data-model-level="1"]'));
  for (let i = 0; i < 30 && !firstMidStarted; i++) await pause(10);
  assert.equal(firstMidStarted, true, 'first Mid load held');

  const oakRev2 = { ...clone(c.materials.get('material-oak')), revision: 2, params: { ...clone(matParams), tint: '#22aa44' }, maps: {} };
  window.twinManifest['material-oak'] = { kind: 'material', household: true, revision: 2, params: clone(oakRev2.params), maps: {} };
  view.setMaterials([oakRev2, clone(c.materials.get('material-walnut'))]);
  for (let i = 0; i < 30 && !secondMidStarted; i++) await pause(10);
  assert.equal(secondMidStarted, true, 'restarted Mid load held');

  // Release stale rev-1 Mid load BEFORE restarted rev-2 Mid load finishes.
  releaseFirstMid();
  await midClick;
  await pause(40);
  assert.equal(view.preview.currentModel, initialFull, 'original Full remains displayed while replacement Mid is pending');
  for (const mat of liveMaterialsOf(initialFull)) {
    assert.equal(disposedMaterials.has(mat), false, 'no displayed mesh material may be disposed while Full is on screen');
  }
  assert.equal(disposedMaterials.has(rev1Wood), false, 'displayed Oak rev-1 material stays undisposed');

  // Now release the restarted rev-2 Mid load: Full detaches, Mid rev-2 displays, and retired rev-1 disposes.
  releaseSecondMid();
  await pause(50);
  trackMaterials(view.preview.currentModel);
  assert.notEqual(view.preview.currentModel, initialFull, 'Mid rev-2 replaced Full');
  const rev2Wood = woodMat();
  assert.equal(rev2Wood.userData.materialRevision, 2, 'preview moved to Oak rev 2');
  assert.equal(rev2Wood.color.getHexString(), '22aa44', 'preview shows rev 2 green');
  assert.equal(disposedMaterials.has(rev2Wood), false, 'active rev 2 material stays undisposed');
  assert.equal(disposedMaterials.has(rev1Wood), true, 'retired rev 1 material disposed once Full detached');

  view.stop();
  host.remove();
  c.host.remove();
  assert.equal(disposedMaterials.size, createdMaterials.size, 'every created material disposed by stop');
});

// Regression R2-1 (replacement failure variants): if the restarted replacement load throws, is cancelled,
// or returns null after the stale rev-1 load finishes, the displayed Full mesh stays undisposed and usable
// until stop(), when every material is disposed cleanly.
await test('material_refresh_replacement_failure_keeps_displayed_mesh_usable_and_disposes_at_stop', async () => {
  for (const mode of ['throw', 'cancelled', 'null']) {
    const rec = makeModel(MODEL_ID, {
      thumbnail: '.thumbnail.png',
      materials: { Wood: { material: 'material-oak', texture: 'real' } },
    });
    const c = createHarness({ initialSearch: '?model=' + MODEL_ID, models: [rec] });
    c.materials.get('material-oak').params.tint = '#8b4513';
    window.twinManifest['material-oak'].params.tint = '#8b4513';

    let releaseFirstMid, releaseSecondMid, firstMidStarted = false, secondMidStarted = false;
    const firstMidGate = new Promise(r => { releaseFirstMid = r; });
    const secondMidGate = new Promise(r => { releaseSecondMid = r; });
    const createdMaterials = new Set(), disposedMaterials = new Set();
    const trackMaterials = obj => {
      obj?.traverse(o => {
        const mat = o.isMesh ? o.material : null;
        if (mat && !createdMaterials.has(mat)) {
          createdMaterials.add(mat);
          mat.addEventListener('dispose', () => disposedMaterials.add(mat));
        }
      });
    };
    const liveMaterialsOf = obj => {
      const out = new Set();
      obj?.traverse(o => { if (o.isMesh && o.material) out.add(o.material); });
      return out;
    };
    let midLoadCount = 0;
    const host = document.createElement('div'); document.body.append(host);
    const view = mountModels(host, {
      api: c.api,
      initialModelId: MODEL_ID,
      materials: [...c.materials.values()].map(clone),
      loadModel: async (id, kit, onLate, opts) => {
        if (opts?.lodName === 'lod1.glb') {
          const n = ++midLoadCount;
          if (n === 1) { firstMidStarted = true; await firstMidGate; }
          else if (n === 2) {
            secondMidStarted = true;
            await secondMidGate;
            if (mode === 'throw') throw new Error('replacement mid load failed');
            if (mode === 'cancelled') throw Object.assign(new Error('cancelled'), { cancelled: true });
            return null;
          }
        }
        const loaded = await lib.loadModel(id, kit, onLate, opts);
        trackMaterials(loaded);
        return loaded;
      },
    });
    await view.ready;
    await pause(40);
    const initialFull = view.preview.currentModel;
    trackMaterials(initialFull);
    const woodMat = () => {
      let mat = null;
      view.preview.currentModel?.traverse(o => { if (o.isMesh && o.userData.partKey === 'Wood') mat = o.material; });
      return mat;
    };
    const rev1Wood = woodMat();
    assert.equal(rev1Wood.userData.materialRevision, 1, `${mode}: initial Full uses Oak rev 1`);

    const midClick = click(host.querySelector('[data-model-level="1"]'));
    for (let i = 0; i < 30 && !firstMidStarted; i++) await pause(10);
    assert.equal(firstMidStarted, true, `${mode}: first Mid load held`);

    const oakRev2 = { ...clone(c.materials.get('material-oak')), revision: 2, params: { ...clone(matParams), tint: '#22aa44' }, maps: {} };
    window.twinManifest['material-oak'] = { kind: 'material', household: true, revision: 2, params: clone(oakRev2.params), maps: {} };
    view.setMaterials([oakRev2, clone(c.materials.get('material-walnut'))]);
    for (let i = 0; i < 30 && !secondMidStarted; i++) await pause(10);
    assert.equal(secondMidStarted, true, `${mode}: restarted Mid load held`);

    // Release stale rev-1 Mid load first, then settle the replacement with the failure mode.
    releaseFirstMid();
    await midClick;
    await pause(30);
    releaseSecondMid();
    await pause(50);

    assert.equal(view.preview.currentModel, initialFull, `${mode}: original Full stays displayed`);
    assert.equal(woodMat(), rev1Wood, `${mode}: Full Wood mesh still holds its rev-1 material`);
    for (const mat of liveMaterialsOf(initialFull)) {
      assert.equal(disposedMaterials.has(mat), false, `${mode}: displayed mesh materials remain undisposed`);
    }
    // Displayed mesh remains interactive/usable (wireframe toggle + part hit-testing).
    view.preview.setWireframe(true);
    assert.equal(view.preview.isWireframe(), true, `${mode}: preview remains usable`);
    view.preview.setWireframe(false);

    // Everything is disposed cleanly at stop().
    view.stop();
    host.remove();
    c.host.remove();
    assert.equal(disposedMaterials.has(rev1Wood), true, `${mode}: displayed rev-1 material disposed at stop`);
    assert.equal(disposedMaterials.size, createdMaterials.size, `${mode}: all tracked materials disposed at stop`);
  }
});

// Regression R1-3: projected bounds of wide, tall, long-thin and four-part models fill 70%-95% of the limiting dimension.
await test('thumbnail_framing_fills_70_to_95_percent', () => {
  const shapes = [
    ['wide', [4, 0.4, 0.5]],
    ['tall', [0.4, 4, 0.5]],
    ['long_thin', [6, 0.15, 0.15]],
    ['four_part', [1.94, 0.44, 0.44]],
  ];
  for (const [aspectW, aspectH] of [[112, 96], [160, 128]]) {
    for (const [label, [w, h, d]] of shapes) {
      const box = new THREE.Box3(new THREE.Vector3(-w / 2, 0, -d / 2), new THREE.Vector3(w / 2, h, d / 2));
      const camera = new THREE.PerspectiveCamera(36, aspectW / aspectH, 0.01, 100);
      const metrics = frameThumbnailCamera(box, camera);
      assert.ok(metrics.limiting >= 0.70 && metrics.limiting <= 0.95,
        `${label} (${aspectW}x${aspectH}) fills ${Math.round(metrics.limiting * 100)}% (want 70%-95%)`);
      assert.ok(metrics.maxAbs <= 0.98, `${label} stays inside viewport (maxAbs=${metrics.maxAbs.toFixed(3)})`);
    }
  }
});

// Regression 4: quick consecutive part edits preserve both overrides inside writeChain.
await test('quick_part_edits_preserve_both', async () => {
  let releaseFirst;
  const firstGate = new Promise(r => { releaseFirst = r; });
  let patchCount = 0;
  const c = createHarness({
    initialSearch: '?model=' + MODEL_ID,
    hooks: {
      async patch(id, body) {
        if (++patchCount === 1) await firstGate;
        return undefined;
      },
    },
  });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  await click(c.host.querySelector('[data-palette-material="material-oak"]'));
  // Click Use selected on Wood (delayed), then immediately click Use selected on Glass while Wood's PATCH is in flight.
  const firstClick = click(c.host.querySelector('[data-model-part="Wood"] [data-slot-use]'));
  await pause(10);
  const secondClick = click(c.host.querySelector('[data-model-part="Glass"] [data-slot-use]'));
  await pause(10);
  releaseFirst();
  await Promise.all([firstClick, secondClick]);
  await pause(50);
  assert.equal(c.models.get(MODEL_ID).materials.Wood?.material, 'material-oak', 'first override preserved');
  assert.equal(c.models.get(MODEL_ID).materials.Glass?.material, 'material-oak', 'second override preserved');
  assert.equal(c.alerts.length, 0);
  c.cleanup(page);
});

// Regression 5: a late PATCH reply for model A does not re-select A or overwrite model B's properties.
await test('late_reply_does_not_reselect_old_model', async () => {
  let releaseTurnA;
  const gateA = new Promise(r => { releaseTurnA = r; });
  const recA = makeModel(MODEL_ID, { name: 'Chair A', fix: { turn: 0 } });
  const recB = makeModel(MODEL_B_ID, { name: 'Chair B', fix: { turn: 180 } });
  const c = createHarness({
    initialSearch: '?model=' + MODEL_ID,
    models: [recA, recB],
    hooks: {
      async patch(id) {
        if (id === MODEL_ID) await gateA;
        return undefined;
      },
    },
  });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  // Start a delayed turn PATCH on A, then select B before A's reply returns.
  const turnA = click(c.host.querySelector('[data-turn="90"]'));
  await pause(10);
  await click(c.host.querySelector(`[data-model="${MODEL_B_ID}"]`));
  await pause(30);
  assert.equal(c.host.querySelector(`[data-model="${MODEL_B_ID}"]`).getAttribute('aria-pressed'), 'true');
  assert.equal(c.host.querySelector('[data-model-field="name"]').value, 'Chair B');
  releaseTurnA();
  await turnA;
  await pause(50);
  assert.equal(c.host.querySelector(`[data-model="${MODEL_B_ID}"]`).getAttribute('aria-pressed'), 'true', 'B stays selected');
  assert.equal(c.host.querySelector(`[data-model="${MODEL_ID}"]`).getAttribute('aria-pressed'), 'false', 'A is not re-selected');
  assert.equal(c.host.querySelector('[data-model-field="name"]').value, 'Chair B', 'B properties stay intact');
  assert.equal(c.host.querySelector('[data-turn="180"]').getAttribute('aria-pressed'), 'true', 'B turn stays 180');
  assert.equal(c.models.get(MODEL_ID).fix.turn, 90, 'A change still saved on server');
  c.cleanup(page);
});

// Regression 6: rapid Materials -> Models -> Materials tab switch while a material PATCH is delayed ends on Materials.
await test('tab_switch_race_keeps_latest_tab', async () => {
  let releaseMatPatch;
  const matGate = new Promise(r => { releaseMatPatch = r; });
  const c = createHarness({
    initialSearch: '?material=material-oak',
    hooks: {
      async materialPatch() { await matGate; },
    },
  });
  const page = mountLibraryPage(c.host, { api: c.api });
  await page.ready;
  await pause(30);
  // Edit material so flush(context) has a pending PATCH that blocks switchTab('models').
  await edit(c.host.querySelector('[data-param="normal_scale"][type="number"]'), 'input', { value: '2' });
  const toModels = click(c.host.querySelector('[data-library-tab="models"]'));
  await pause(10);
  const backToMaterials = click(c.host.querySelector('[data-library-tab="materials"]'));
  await pause(10);
  releaseMatPatch();
  await Promise.all([toModels, backToMaterials]);
  await pause(40);
  assert.equal(c.host.querySelector('[data-library-tab="materials"]').getAttribute('aria-selected'), 'true');
  assert.ok(c.host.querySelector('[data-material="material-oak"]'), 'Materials grid is attached');
  assert.equal(c.host.querySelector('[data-model-grid]'), null, 'Models grid is not attached');
  c.cleanup(page);
});

// Regression 7: built-ins render thumbnails locally and refresh on visual edits without saving to the server.
await test('builtin_thumbnail_generated_and_refreshed_without_server_save', async () => {
  const origRender = Renderer.prototype.render;
  let thumbRenderCount = 0;
  Renderer.prototype.render = function(scene, camera) {
    if (this.domElement && !this.domElement.toDataURL) {
      this.domElement.toDataURL = () => `data:image/png;base64,GENERATED_THUMB_${++thumbRenderCount}`;
    }
    return origRender.call(this, scene, camera);
  };
  try {
    const c = createHarness({ initialSearch: '?model=' + BUILTIN_ID });
    const page = mountLibraryPage(c.host, { api: c.api });
    await page.ready;
    await pause(50);
    const canvas = c.host.querySelector('.library-preview canvas');
    canvas.toDataURL = () => `data:image/png;base64,BUILTIN_LIVE_${++thumbRenderCount}`;
    const builtinImg = () => c.host.querySelector(`[data-model="${BUILTIN_ID}"] img`);
    // Initial thumbnail generated on the detached canvas (or live preview) for the built-in with no saved thumbnail.
    const initialSrc = builtinImg().src || '';
    assert.match(initialSrc, /^data:image\/png;base64,/, 'built-in card has generated thumbnail');
    // Edit built-in turn -> refreshes its card thumbnail locally WITHOUT calling PATCH editor/imports/...
    c.calls.length = 0;
    await click(c.host.querySelector('[data-turn="90"]'));
    await pause(50);
    const updatedSrc = builtinImg().src || '';
    assert.match(updatedSrc, /^data:image\/png;base64,BUILTIN_LIVE_/, 'built-in thumbnail refreshed after visual edit');
    assert.notEqual(updatedSrc, initialSrc);
    assert.equal(c.calls.some(x => x.path.startsWith('editor/imports/')), false, 'never saves generated built-in thumbnail to server');
    c.cleanup(page);
  } finally {
    Renderer.prototype.render = origRender;
  }
});

finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
