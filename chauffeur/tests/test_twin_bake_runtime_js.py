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
async function context(tier = 'high', sharedServer = null, placed = null) {
  const out = gen.buildTwin(job.plan, job.kit, tier); await out.ready;
  const renderer = fakeRenderer(); renderer.domElement = new Node('canvas');
  const scene = new THREE.Scene(); scene.add(out.root); scene.updateMatrixWorld(true);
  const controls = new THREE.EventDispatcher(); controls.target = new THREE.Vector3();
  const view = { plan: job.plan, ready: true, scene, tier, renderer3: renderer, controls, render() {} };
  const server = sharedServer || fakeServer(), lights = placed || [k1, k2, h1, c1];
  const api = (path, init) => path === 'api/house/live' ? Promise.resolve(new Response(JSON.stringify({
    markers: lights.map(l => ({ ...l, device_id: l.device, placed: true, kind: 'light' }))
  }), { status: 200 })) : server.api(path, init);
  const controller = mountBake(view, out.root, { host: document.getElementById('twin-controls'), layout: job.layout, api });
  view.bakeSky = () => controller.sky(new THREE.Color(.1, .2, .3), 1);
  return { view, controller, server, out, renderer };
}
let passed = 0, published = null;
async function check(name, fn) {
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + error.stack); }
}
await check('controller_auto_bakes_loads_and_forces_a_second_run', async () => {
  const c = await context();
  try {
    await until(() => !c.controller.state().baking && c.controller.fresh().length === 4,
      'the controller must reach a loaded bake: ' + JSON.stringify(c.controller.state()));
    assert.deepEqual([...c.controller.fresh()].sort(), ['c1', 'h1', 'k1', 'k2']);
    assert.equal(c.controller.state().baked.length, 5);
    assert.equal(c.controller.state().stale.length, 0);
    const key = c.controller.state().key, before = structuredClone(c.server.manifests.get(key));
    c.controller.light('k1', [255, 0, 0], 1); c.controller.light('k1', [255, 0, 0], 0);
    assert.ok(covered(c.out.root).some(m => m.material.userData.lmBefore), 'the runtime actually patched materials');
    await c.controller.now();
    assert.equal(c.controller.state().baked.length, 10, 'force bakes sky and all four lights again');
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
    assert.equal(held.sky.layers, 3, 'every sky page is held');
    const skyPages = 3, unlit = Array.from({ length: bank.pages }, (_, p) => p).filter(p => !bank.lit.includes(p)).map(p => skyPages + p);
    const got = c.server.calls.slice(since).filter(x => x.method === 'GET').map(x => x.path);
    for (const p of unlit) assert.ok(!got.includes(`api/house/bakes/${key}/${p}.png`), `the unlit page ${p} is never fetched: ` + JSON.stringify(got));
    assert.ok(got.includes(`api/house/bakes/${key}/${skyPages + bank.lit[0]}.png`), 'the lit page is fetched');
    assert.deepEqual([...c.controller.fresh()].sort(), ['k1', 'k2']);
    assert.deepEqual(c.server.writes(since), [], 'the panel writes nothing');
  } finally { c.controller.stop(); }
});
console.log(`${passed}/6 passed`); process.exit(passed === 6 ? 0 : 1);
"""


def run():
    job = {'root': pathlib.Path(B.ROOT).as_posix(), 'plan': B.household_pool_house(),
           'kit': {**B.tl.kit('modern_farmhouse'), 'manifest': {}}, 'layout': B.LAYOUT,
           'pool': B.POOL, 'kitchen': B.KITCHEN, 'hall': B.HALL, 'changing': B.CHANGING}
    with tempfile.TemporaryDirectory(prefix='chauffeur_bake_runtime_') as directory:
        driver = pathlib.Path(directory) / 'runtime.mjs'
        data = pathlib.Path(directory) / 'job.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps(job), encoding='utf-8')
        result = subprocess.run([B.node(), str(driver), str(data)], capture_output=True,
                                text=True, encoding='utf-8', timeout=180)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-4000:], end='')
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
