"""Run the bake controller entry point with the existing GPU/worker/server fakes.

This covers failures hidden by runtime.js's graceful-fallback catch. The GPU
pixels and browser worker glue still require test_house_twin_bake_live.py.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_twin_baker_js as B
import test_twin_lightmap_material_js as M

DRIVER = M.DRIVER[:M.DRIVER.index('const checks = [];')]
DRIVER = DRIVER.replace("globalThis.window = {chfBase:'../'};", "globalThis.window = Object.assign(new EventTarget(), {chfBase:'../'});")
DRIVER += B.DRIVER[B.DRIVER.index('// --- the fake GPU'):B.DRIVER.index('// --- the house, the lights')]
DRIVER += B.DRIVER[B.DRIVER.index('const building ='):B.DRIVER.index('async function setup')]
DRIVER += r"""
const B = await import(file('static/twin/bake/baker.js'));
const { mountBake } = await import(file('static/twin/bake/runtime.js'));
class CodecWorker {
  postMessage(job) {
    setImmediate(async () => {
      try {
        const result = job.kind === 'encode' ? B.encodePage(E, job.job) : job.kind === 'decode' ?
          B.decodePage(T, job.bytes) : M.transcodePage(T, job.bytes, job.format);
        this.onmessage?.({ data: { id: job.id, result } });
      } catch (error) { this.onmessage?.({ data: { id: job.id, error: error.message } }); }
    });
  }
  terminate() {}
}
globalThis.Worker = class { constructor(url, options) {
  return String(url).includes('codec_worker') ? new CodecWorker() : new FakeWorker(url, options);
}};
globalThis.indexedDB = fakeIndexedDB();
const until = async (fn, what) => {
  const start = Date.now();
  while (!fn() && Date.now() - start < 40000) await sleep(50);
  assert.ok(fn(), what);
};
const liveLayout = list => ({ markers: list.map(l => ({ ...l, device_id: l.device, placed: true, kind: 'light' })) });
async function context(tier = 'high', sharedServer = null, placed = null, extra = {}) {
  const out = gen.buildTwin(job.plan, job.kit, tier); await out.ready;
  const renderer = fakeRenderer(); renderer.domElement = new Node('canvas');
  const scene = new THREE.Scene(); scene.add(out.root); scene.updateMatrixWorld(true);
  const controls = new THREE.EventDispatcher(); controls.target = new THREE.Vector3();
  const view = { plan: job.plan, ready: true, scene, tier, renderer3: renderer, controls, render() {} };
  const server = sharedServer || fakeServer(), lights = placed || [k1, k2, h1, c1];
  const api = (path, init) => path === 'api/house/live' ? Promise.resolve(new Response(JSON.stringify(liveLayout(lights)), { status: 200 }))
    : extra.deny && path.endsWith('/lease') ? Promise.resolve(new Response('{"detail":"Requires parent"}', { status: 403 }))
    : server.api(path, init);
  const host = extra.host || document.getElementById('twin-controls');
  const controller = mountBake(view, out.root, { host, layout: job.layout, api, ...(extra.poll !== undefined ? { poll: extra.poll } : {}) });
  return { view, controller, server, out, renderer, host };
}
let passed = 0, ran = 0, published = null;
const only = process.argv[3];
async function check(name, fn) {
  if (only && name !== only) return;
  ran++;
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + error.stack); }
}
await check('controller_auto_bakes_loads_and_forces_a_second_run', async () => {
  const c = await context();
  try {
    await until(() => !c.controller.state().baking && c.controller.fresh().length === 4,
      'the controller must reach a loaded bake: ' + JSON.stringify(c.controller.state()));
    assert.deepEqual([...c.controller.fresh()].sort(), ['c1', 'h1', 'k1', 'k2']);
    assert.equal(c.controller.state().baked.length, 4);
    assert.equal(c.controller.state().stale.length, 0);
    const key = c.controller.state().key, before = structuredClone(c.server.manifests.get(key));
    c.controller.light('k1', [255, 0, 0], 1); c.controller.light('k1', [255, 0, 0], 0);
    assert.ok(covered(c.out.root).some(m => m.material.userData.lmBefore), 'the runtime actually patched materials');
    await c.controller.now();
    assert.equal(c.controller.state().baked.length, 8, 'force bakes all four room lights again');
    assert.deepEqual(c.server.manifests.get(key).lights, before.lights, 'keys and slots stay the same');
    assert.deepEqual(c.server.bad, []);
    assert.ok(c.renderer.log.renders && c.renderer.log.reads, 'the controller ran the GPU entry point');
    published = c.server;
  } finally { c.controller.stop(); }
});
await check('controller_pauses_for_pointer_and_two_seconds_still', async () => {
  const c = await context();
  try {
    const event = type => Object.assign(new Event(type), { pointerId: 1 });
    c.renderer.domElement.dispatchEvent(event('pointerdown'));
    await until(() => c.controller.state().baking, 'an automatic run starts');
    assert.equal(c.controller.state().paused, true);
    await sleep(2200);
    assert.equal(c.renderer.log.renders, 0, 'no GPU work while dragging');
    window.dispatchEvent(event('pointerup')); await sleep(1000);
    assert.equal(c.controller.state().paused, true, 'still paused after one second');
    await until(() => !c.controller.state().baking && c.controller.fresh().length === 4, 'resumes after two seconds');
  } finally { c.controller.stop(); }
});
await check('low_controller_and_tier_keys', async () => {
  const c = await context('low');
  try {
    await until(() => c.controller.state().key !== null, 'the atlas worker returns');
    await sleep(1500);
    assert.deepEqual(c.controller.fresh(), []);
    assert.equal(c.renderer.log.renders, 0);
    assert.deepEqual(c.server.writes(), []);
    // B11: identical layouts must have identical keys on the desktop and Pi.
    const high = gen.buildTwin(job.plan, job.kit, 'high'); await high.ready;
    const low = gen.buildTwin(job.plan, job.kit, 'low'); await low.ready;
    assert.equal(buildAtlas(high.root, job.plan, job.layout).key, buildAtlas(low.root, job.plan, job.layout).key);
  } finally { c.controller.stop(); }
});
await check('bank_zero_reserves_unlit_rooms_and_only_changed_banks_expire', async () => {
  const root = await house(), atlas = buildAtlas(root, job.plan, job.layout);
  const first = B.bakeLayout(atlas, job.layout, [k1, k2, k3]);
  const second = B.bakeLayout(atlas, job.layout, [k1, k2, k3, h1, { ...h1, device: 'h2' }, { ...h1, device: 'h3' }]);
  assert.deepEqual(first.banks[0].rooms.map(r => r.room).sort(),
    atlas.room.rooms.flatMap((r, i) => r.region ? [i] : []).sort(), 'B12: bank zero includes rooms with no lights');
  assert.deepEqual(second.entries.k1, first.entries.k1);
  assert.deepEqual(second.entries.k2, first.entries.k2);
  assert.notEqual(second.entries.k3.key, first.entries.k3.key, 'only bank one changes when Hall needs bank one');
});
await check('partial_bake_loads_on_low_without_writes', async () => {
  assert.ok(published, 'the earlier controller published a bake');
  for (const m of published.manifests.values()) delete m.lights.c1;
  const since = published.writes().length, c = await context('low', published);
  try {
    await until(() => c.controller.fresh().length === 3, 'a panel loads the three complete lights');
    assert.deepEqual(c.controller.fresh().sort(), ['h1', 'k1', 'k2']);
    assert.deepEqual(c.controller.state().stale, ['c1']);
    assert.equal(c.renderer.log.renders, 0);
    assert.equal(published.writes().length, since);
  } finally { c.controller.stop(); }
});
await check('a_bank_page_with_no_light_is_never_held', async () => {
  // Only the Kitchen has lights: bank zero still lays out every room (B12),
  // but a bank page no placed light writes to is neither fetched nor held.
  const desk = await context('high', null, [k1, k2]);
  let key;
  try {
    await until(() => !desk.controller.state().baking && desk.controller.fresh().length === 2,
      'the Kitchen bake lands: ' + JSON.stringify(desk.controller.state()));
    key = desk.controller.state().key;
  } finally { desk.controller.stop(); }
  const since = desk.server.calls.length, c = await context('low', desk.server, [k1, k2]);
  try {
    await until(() => c.controller.fresh().length === 2, 'a panel draws the Kitchen bake');
    const held = c.controller.held(), bank = held.banks[0];
    assert.equal(held.banks.length, 1);
    assert.ok(bank.pages > bank.lit.length, 'the fixture has a bank-zero page with no light: ' + JSON.stringify(bank));
    assert.equal(bank.lit.length, 1, 'the Kitchen lights share one page: ' + JSON.stringify(bank));
    assert.equal(bank.layers, 1, 'only the lit page is a layer on the GPU: ' + JSON.stringify(bank));
    assert.equal(bank.size, job.layout.room.page, 'the lit layer is a whole page');
    const unlit = Array.from({ length: bank.pages }, (_, p) => p).filter(p => !bank.lit.includes(p));
    const got = c.server.calls.slice(since).filter(x => x.method === 'GET').map(x => x.path);
    for (const p of unlit) assert.ok(!got.includes(`api/house/bakes/${key}/${p}.png`), `the unlit page ${p} is never fetched: ` + JSON.stringify(got));
    assert.ok(got.includes(`api/house/bakes/${key}/${bank.lit[0]}.png`), 'the lit page is fetched');
    assert.deepEqual([...c.controller.fresh()].sort(), ['k1', 'k2']);
    assert.deepEqual(c.server.writes(since), [], 'the panel writes nothing');
  } finally { c.controller.stop(); }
});
await check('a_wall_opened_before_the_bake_picks_it_up', async () => {
  // I1: a wall that mounts before any bake polls the key the desk will bake and draws the
  // bake when it lands, without a reload. M1: until then it keeps its own geometry.
  const server = fakeServer(), wall = await context('low', server, null, { poll: 300 });
  try {
    await until(() => wall.controller.state().key !== null, 'the wall computes its atlas key');
    await sleep(1000);
    assert.deepEqual(wall.controller.fresh(), [], 'no bake yet');
    assert.ok(covered(wall.out.root).every(m => !m.geometry.attributes.lmRoom), 'M1: with no bake the wall keeps its own geometry');
    const desk = await context('high', server);
    try {
      await until(() => !desk.controller.state().baking && desk.controller.fresh().length === 4, 'the desk bakes');
      assert.equal(wall.controller.state().key, desk.controller.state().key, 'the wall polls the key the desk bakes');
    } finally { desk.controller.stop(); }
    await until(() => wall.controller.fresh().length === 4, 'the wall picks the bake up without a reload: ' + JSON.stringify(wall.controller.state()));
    assert.ok(covered(wall.out.root).every(m => m.geometry.attributes.lmRoom), 'the atlas is applied once a bake exists');
    assert.equal(wall.renderer.log.renders, 0, 'the wall never bakes');
  } finally { wall.controller.stop(); }
});
let wallServer = null;
async function bakedWall(extra = {}) {
  if (!wallServer) {
    const desk = await context('high', null, [k1, k2, h1, c1]);
    try { await until(() => !desk.controller.state().baking && desk.controller.fresh().length === 4, 'the desk bakes'); }
    finally { desk.controller.stop(); }
    wallServer = desk.server;
  }
  const wall = await context('low', wallServer, [k1, k2, h1, c1], { poll: 0, ...extra });
  await until(() => wall.controller.fresh().length === 4, 'the wall draws the bake');
  return wall;
}
await check('a_poll_with_nothing_new_rebuilds_nothing', async () => {
  // I2: an unchanged manifest and 304 pages rebuild, re-upload and redraw nothing; a
  // changed page updates only its own layer of the array it lives in.
  const wall = await bakedWall(), server = wall.server;
  try {
    let renders = 0, refreshes = 0;
    wall.view.render = () => { renders++; };
    wall.view.live = { refresh: async () => { refreshes++; }, layout: () => liveLayout([k1, k2, h1, c1]) };
    const before = wall.controller.held(), since = server.calls.length;
    await wall.controller.refresh();
    const after = wall.controller.held();
    assert.deepEqual(after.versions, before.versions, 'no array texture is re-uploaded');
    assert.deepEqual(after.ids, before.ids, 'no array texture is replaced');
    assert.equal(renders, 0, 'nothing is redrawn'); assert.equal(refreshes, 0, 'the live layer is not refreshed');
    const gets = server.calls.slice(since).filter(c => c.method === 'GET' && c.path.endsWith('.png'));
    assert.ok(gets.length && gets.every(c => c.inm && !c.full), `every page is asked with its ETag and answers 304: ${JSON.stringify(gets)}`);
    const key = wall.controller.state().key, page = server.manifests.get(key).lights.k1.page;
    // What a render does: the GPU took every flagged layer.
    const arrays = wall.controller.held().textures;
    arrays.banks.forEach(t => t.clearLayerUpdates());
    await server.api(`api/house/bakes/${key}/${page}.png`, { method: 'POST', body: server.pages.get(`${key}/${page}`) });
    await wall.controller.refresh();
    const changed = wall.controller.held();
    assert.deepEqual(changed.ids, before.ids, 'a changed page keeps its array texture');
    assert.ok(changed.versions.banks[0] > before.versions.banks[0], 'the bank array is flagged');
    assert.deepEqual(changed.updates.banks[0], [changed.banks[0].lit.indexOf(page)], 'only the changed page\'s layer uploads');
    assert.deepEqual([...wall.controller.fresh()].sort(), ['c1', 'h1', 'k1', 'k2']);
  } finally { wall.controller.stop(); }
});
await check('lights_moved_while_open_follow_the_layout', async () => {
  // M3: the light list follows the live layer's layout: a light moved while the wall is
  // up stops drawing its old bake at once.
  const wall = await bakedWall();
  try {
    const moved = { ...h1, at: [h1.at[0] + 2, h1.at[1], h1.at[2]] };
    wall.view.live = { refresh: async () => {}, layout: () => liveLayout([k1, k2, moved, c1]) };
    await wall.controller.refresh();
    assert.deepEqual([...wall.controller.fresh()].sort(), ['c1', 'k1', 'k2'], 'the moved light is no longer drawn baked');
    assert.deepEqual(wall.controller.state().stale, ['h1'], 'it waits to re-bake');
  } finally { wall.controller.stop(); }
});
await check('window_glow_inverts_each_mesh_once', async () => {
  // M2: the window glow looks up charts by room and inverts each mesh's matrix once.
  let inverts = 0;
  const invert = THREE.Matrix4.prototype.invert;
  THREE.Matrix4.prototype.invert = function () { inverts++; return invert.call(this); };
  let wall;
  try { wall = await bakedWall(); } finally { THREE.Matrix4.prototype.invert = invert; }
  try {
    let meshes = 0; wall.out.root.traverse(o => { if (o.isMesh) meshes++; });
    assert.ok(inverts <= meshes * 2, `matrix inversions ${inverts} for ${meshes} meshes`);
  } finally { wall.controller.stop(); }
});
await check('a_child_never_bakes', async () => {
  // M4: the bake lease is parents-only; a child's High view shows no button and never bakes.
  const host = new Node('div');
  const c = await context('high', null, null, { deny: true, host });
  try {
    await until(() => c.controller.state().key !== null, 'the atlas key');
    await sleep(2500);
    assert.equal(c.controller.state().baking, false, 'no run starts');
    assert.equal(c.renderer.log.renders, 0, 'no GPU work');
    assert.deepEqual(c.server.writes(), [], 'nothing is uploaded');
    const find = n => n.id === 'twin-bake-controls' || n.children.some(find);
    assert.ok(!find(host), 'no Bake lighting now for a child');
  } finally { c.controller.stop(); }
});

await check('legacy_sky_metadata_is_ignored_without_fetch_or_gpu_storage', async () => {
  const desk = await context();
  try {
    await until(() => !desk.controller.state().baking && desk.controller.fresh().length === 4, 'room bake completes');
  } finally { desk.controller.stop(); }
  const key = desk.controller.state().key, manifest = desk.server.manifests.get(key);
  // A legacy field must have no influence on light keys, requested pages or textures.
  manifest.sky = {page: 63, channel: 0, pages: 1};
  manifest.densities.sky = 1;
  const since = desk.server.calls.length, wall = await context('low', desk.server, null, {poll: 0});
  try {
    await until(() => wall.controller.fresh().length === 4, 'legacy manifest loads all room lights');
    const held = wall.controller.held();
    for (const section of [held, held.textures, held.versions, held.ids, held.updates])
      assert.ok(!Object.hasOwn(section, 'sky'), 'no sky GPU storage');
    assert.ok(!desk.server.calls.slice(since).some(c => c.path === `api/house/bakes/${key}/63.png`), 'legacy sky page never fetched');
    assert.equal(wall.renderer.log.renders, 0);
  } finally { wall.controller.stop(); }
});

console.log(`${passed}/${ran} passed`); process.exit(passed === ran ? 0 : 1);
"""


def run():
    job = {'root': pathlib.Path(B.ROOT).as_posix(), 'plan': B.household_pool_house(),
           'kit': {**B.tl.kit('modern_farmhouse'), 'manifest': {}},
           'layout': {**B.LAYOUT, 'sky': {'density': 1, 'page': 256, 'gutter': 2}},
           'pool': B.POOL, 'kitchen': B.KITCHEN, 'hall': B.HALL, 'changing': B.CHANGING}
    with tempfile.TemporaryDirectory(prefix='chauffeur_bake_runtime_') as directory:
        driver = pathlib.Path(directory) / 'runtime.mjs'
        data = pathlib.Path(directory) / 'job.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps(job), encoding='utf-8')
        result = subprocess.run([B.node(), str(driver), str(data), *sys.argv[1:]], capture_output=True,
                                text=True, encoding='utf-8', timeout=180)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-4000:], end='')
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
