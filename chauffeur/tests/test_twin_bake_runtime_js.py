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
const { mountBake, lightsOf } = await import(file('static/twin/bake/runtime.js'));
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
const until = async (fn, what, timeout = 40000) => {
  const start = Date.now();
  while (!fn() && Date.now() - start < timeout) await sleep(50);
  assert.ok(fn(), what);
};
const liveLayout = list => ({ markers: list.map(l => ({ ...l, device_id: l.device, placed: true, kind: 'light' })) });
async function context(tier = 'high', sharedServer = null, placed = null, extra = {}) {
  const out = gen.buildTwin(job.plan, job.kit, tier); await out.ready;
  let plan = job.plan;
  if (extra.farSurface) {
    plan=structuredClone(job.plan);
    plan.buildings.push({id:'far',position:[1000,0],levels:[{id:'L1',elevation:0,ceiling:10}],
      rooms:[{id:'far',level:'L1',polygon:[[0,0],[254,0],[254,254],[0,254]]}]});
    const m = new THREE.Mesh(new THREE.PlaneGeometry(254,254).rotateX(-Math.PI/2).translate(127,0,-127),
      new THREE.MeshStandardMaterial({name:'ground'}));
    m.userData={merged:true,buildingId:'far'}; m.scale.setScalar(gen.FT); m.position.x=1000*gen.FT; out.root.add(m);
  }
  const renderer = fakeRenderer(); renderer.domElement = new Node('canvas');
  const scene = new THREE.Scene(); scene.add(out.root); scene.updateMatrixWorld(true);
  const controls = new THREE.EventDispatcher(); controls.target = new THREE.Vector3();
  const view = { plan, ready: true, scene, tier, renderer3: renderer, controls, render() {} };
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
await check('yard_and_fire_pit_lights_are_not_baked', async () => {
  // Yard-room and fire-pit lights have no building: baked light lands indoors only, and a
  // building-less light never baked, so the bake never settled (user, 2026-11-13).
  const layout={markers:[
    {device_id:'indoor',kind:'light',placed:true,at:[1,2,8],room:'r',building:'b',level:'L1'},
    {device_id:'yard',kind:'light',placed:true,at:[30,40,8],room:'yard_rooms:1',building:null,level:null},
    {device_id:'pit',kind:'light',placed:true,at:[5,5,2],room:null,building:null,level:null},
    {device_id:'unplaced',kind:'light',placed:false,at:[1,1,8],room:'r',building:'b',level:'L1'}]};
  assert.deepEqual(lightsOf(layout).map(l=>l.device),['indoor']);
});
await check('worker_failures_are_visible_in_state_and_console', async () => {
  const Worker=globalThis.Worker, db=globalThis.indexedDB, log=console.error, timeout=globalThis.setTimeout, errors=[];
  let c;
  try {
    console.error=(...args)=>errors.push(args);
    for (const mode of ['throw','reject','error','unreadable','hang']) {
      globalThis.setTimeout=(fn,ms,...args)=>timeout(fn,ms===30000&&mode==='hang'?0:ms,...args);
      globalThis.indexedDB=fakeIndexedDB();
      globalThis.Worker=class {
        constructor() { if(mode==='throw') throw new Error('worker module cannot resolve three'); }
        postMessage() { if(mode==='hang') return; setImmediate(()=> mode==='reject' ? this.onmessage({data:{error:'worker reach build rejected'}})
          : mode==='error' ? this.onerror({message:'worker failed importing three'}) : this.onmessageerror()); }
        terminate() {}
      };
      c=await context();
      await until(()=>c.controller.state().error,'worker failure is exposed',5000);
      const reason=c.controller.state().error;
      assert.match(reason,mode==='throw' ? /cannot resolve three/ : mode==='reject' ? /reach build rejected/
        : mode==='error' ? /failed importing three/ : mode==='hang' ? /timed out/ : /unreadable/);
      assert.equal(c.controller.state().key,null);assert.equal(c.controller.state().baking,false);
      assert.ok(errors.some(args=>args.some(x=>(x?.message||String(x)).includes(reason))),'console includes the actual reason');
      assert.deepEqual(c.controller.fresh(),[],'failed atlas keeps real-time fallback');
      c.controller.stop();c=null;
    }
  } finally {c?.controller.stop();globalThis.Worker=Worker;globalThis.indexedDB=db;console.error=log;globalThis.setTimeout=timeout;}
});
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
    const meshes = covered(c.out.root), material = meshes[0].material;
    const shader = { uniforms: {}, vertexShader: '#include <begin_vertex>', fragmentShader: '#include <lights_fragment_end>' };
    material.onBeforeCompile(shader, c.renderer);
    const data = shader.uniforms.lmTints.value.image;
    const p = B.bakeLayout(buildAtlas(await house(), job.plan, job.layout), job.layout, [k1, k2, h1, c1]);
    const slot = p.slots.k1;
    const assignment=slot.assignments.find(a=>p.banks[a.bank].charts.some(c=>c.id===a.chart&&c.room!==slot.room));
    const neighbour=assignment && p.banks[assignment.bank].charts.find(c=>c.id===assignment.chart);
    assert.ok(neighbour !== undefined, 'k1 has neighbouring receiving groups');
    const version = material.version, keyBefore = material.customProgramCacheKey(), programs = c.renderer.info.programs.length;
    c.controller.light('k1', [255, 0, 0], .75);
    const regionTexture=shader.uniforms.lmRegions.value.image;
    const address=neighbour.id*p.banks.length+assignment.bank;
    const owners=regionTexture.data[address*4+3];
    const owner=assignment.channel ? Math.floor(owners/4096) : owners%4096;
    const at = (owner-1)*4;
    assert.equal(owner,1,'neighbour chart points to k1 in the global tint texture');
    assert.equal(data.data[at], .75, 'the neighbouring chart receives the same tint');
    c.controller.light('k1', [255, 0, 0], 0);
    assert.equal(data.data[at], 0, 'toggle clears neighbouring texels');
    assert.equal(material.version, version); assert.equal(material.customProgramCacheKey(), keyBefore);
    assert.equal(c.renderer.info.programs.length, programs, 'toggle compiles nothing');
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
  const second = B.bakeLayout(atlas, job.layout, [k1, k2, k3, h1, { ...h1, device: 'h2' }, { ...h1, device: 'h3' }],first.ownership);
  assert.deepEqual(first.banks[0].rooms.map(r => r.room).sort(),
    atlas.room.rooms.flatMap((r, i) => r.region ? [i] : []).sort(), 'B12: bank zero includes rooms with no lights');
  const ranking=s=>JSON.stringify(s.assignments.map(a=>[a.chartKey,a.bank,a.channel]).sort((a,b)=>a[0].localeCompare(b[0])));
  for(const id of ['k1','k2','k3']) assert.equal(second.entries[id].key===first.entries[id].key,
    ranking(second.slots[id])===ranking(first.slots[id]),'a key changes exactly when that light\'s own chart slot changes');
  for(const id of ['k1','k2','k3']) assert.equal(second.entries[id].key,first.entries[id].key,'new members below the cap cannot displace survivors');
  assert.equal(second.banks.length,3);
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
  // A distant room guarantees an unlit reserved page after nearby light spill
  // began covering several pages. That page is neither fetched nor held.
  const desk = await context('high', null, [c1], {farSurface:true});
  let key;
  try {
    await until(() => !desk.controller.state().baking && desk.controller.fresh().length === 1,
      'the Kitchen bake lands: ' + JSON.stringify(desk.controller.state()));
    key = desk.controller.state().key;
  } finally { desk.controller.stop(); }
  const since = desk.server.calls.length, c = await context('low', desk.server, [c1], {farSurface:true});
  try {
    await until(() => c.controller.fresh().length === 1, 'a panel draws the Changing room bake');
    const held = c.controller.held(), bank = held.banks[0];
    assert.equal(held.banks.length, 3);
    assert.ok(held.banks.slice(1).every(b=>b.lit.length===0&&b.size===4&&b.layers===1),'unoccupied banks hold only a compressed placeholder');
    assert.ok(bank.pages >= bank.lit.length, 'sparse banks reserve no extra GPU layers: ' + JSON.stringify(bank));
    assert.ok(bank.lit.length >= 1, 'the Kitchen lights hold all their reach pages: ' + JSON.stringify(bank));
    assert.equal(bank.layers, bank.lit.length, 'only lit pages are layers on the GPU: ' + JSON.stringify(bank));
    assert.equal(bank.size, job.layout.room.page, 'the lit layer is a whole page');
    const unlit = Array.from({ length: bank.pages }, (_, p) => p).filter(p => !bank.lit.includes(p));
    const baseline=await context('high',null,[c1]);
    try {
      await until(()=>!baseline.controller.state().baking&&baseline.controller.fresh().length===1,'baseline light bake lands');
      assert.deepEqual(held.banks,baseline.controller.held().banks,'adding a distant unlit room allocates no additional bank pages or GPU layers');
    } finally {baseline.controller.stop();}
    const got = c.server.calls.slice(since).filter(x => x.method === 'GET').map(x => x.path);
    for (const p of unlit) assert.ok(!got.includes(`api/house/bakes/${key}/${p}.png`), `the unlit page ${p} is never fetched: ` + JSON.stringify(got));
    assert.ok(got.includes(`api/house/bakes/${key}/${bank.lit[0]}.png`), 'the lit page is fetched');
    assert.deepEqual([...c.controller.fresh()].sort(), ['c1']);
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
    const atlas=buildAtlas(await house(),job.plan,job.layout);
    const before=B.bakeLayout(atlas,job.layout,[k1,k2,h1,c1]),next=B.bakeLayout(atlas,job.layout,[k1,k2,moved,c1],wall.server.manifests.get(wall.controller.state().key).ownership);
    const own=(p,id)=>JSON.stringify(p.slots[id].assignments.map(a=>[a.chartKey,a.bank,a.channel]));
    const expected=['k1','k2','c1'].filter(id=>own(before,id)===own(next,id));
    assert.deepEqual(expected.slice().sort(),['c1','k1','k2'],'the three unmoved lights retain every slot');
    wall.view.live = { refresh: async () => {}, layout: () => liveLayout([k1, k2, moved, c1]) };
    await wall.controller.refresh();
    assert.deepEqual([...wall.controller.fresh()].sort(), expected.sort(), 'only unchanged chart assignments stay fresh');
    assert.ok(!wall.controller.fresh().includes('h1'),'the moved light stops drawing its old bake');
    assert.deepEqual(wall.controller.state().stale.sort(),['k1','k2','h1','c1'].filter(id=>!expected.includes(id)).sort());
  } finally { wall.controller.stop(); }
});
await check('a_reopened_panel_uses_persisted_slots_instead_of_sorting_again', async () => {
  const {encodeSlots}=await import(file('static/twin/bake/slots.js'));
  const atlas=buildAtlas(await house(),job.plan,job.layout),list=[k1,k2,h1,c1],first=B.bakeLayout(atlas,job.layout,list);
  // This is a valid surviving slot from an earlier six-member assignment.
  // Its old neighbours are gone; it must keep the hole rather than compact.
  const assignment=first.slots.k1.assignments[0];assignment.bank=2;assignment.channel=1;
  const ownership=encodeSlots(first.slots,atlas.room.charts.length),server=fakeServer();
  server.manifests.set(atlas.key,{pages:first.pages,lights:{},densities:{room:job.layout.room.density},ownership});
  const desk=await context('high',server);let saved;
  try {
    await until(()=>!desk.controller.state().baking&&desk.controller.fresh().length===4,'desk uses historical channels');
    saved=structuredClone(server.manifests.get(atlas.key));
    assert.ok(desk.controller.held().banks[2].lit.length,'the surviving bank-two slot is really allocated');
  } finally {desk.controller.stop();}
  const panel=await context('low',server);
  try {
    await until(()=>panel.controller.fresh().length===4,'reopened panel reads all four historical slots');
    assert.equal(panel.renderer.log.renders,0,'the panel never re-bakes');
    assert.ok(panel.controller.held().banks[2].lit.length,'reload keeps the non-default slot');
    assert.deepEqual(server.manifests.get(atlas.key),saved,'panel read changes no history or keys');
  } finally {panel.controller.stop();}
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
await check('a_missing_secondary_reach_page_keeps_the_light_real_time', async () => {
  const desk = await context(); let key;
  try {
    await until(() => !desk.controller.state().baking && desk.controller.fresh().length === 4, 'desk bake lands');
    key=desk.controller.state().key;
  } finally { desk.controller.stop(); }
  const manifest=desk.server.manifests.get(key), entry=manifest.lights.k1;
  assert.ok(entry.pages.length>1,'fixture: k1 crosses multiple pages');
  const missing=entry.pages[1]; desk.server.pages.delete(`${key}/${missing}`);
  const wall=await context('low',desk.server);
  try {
    await until(() => wall.controller.held() !== null, 'wall atlas loaded'); await sleep(1000);
    assert.ok(!wall.controller.fresh().includes('k1'),'a first page alone cannot make a light fresh');
    assert.ok(wall.controller.state().stale.includes('k1'));
    assert.equal(wall.renderer.log.renders,0,'panel uses the unchanged real-time fallback');
  } finally { wall.controller.stop(); }
});
await check('crowded_charts_keep_all_lights_baked_somewhere', async () => {
  const placed=Array.from({length:40},(_,i)=>({...k1,device:'cap-'+String(i).padStart(2,'0')}));
  const desk=await context('high',null,placed);
  try {
    const expected=B.bakeLayout(buildAtlas(await house(),job.plan,job.layout),job.layout,placed);
    assert.equal(Object.keys(expected.entries).length,40,'coincident equal contributors all own charts somewhere');
    await until(()=>!desk.controller.state().baking&&desk.controller.fresh().length===40,
      'all lights finish their owned chart bakes',120000);
    const fresh=new Set(desk.controller.fresh());
    assert.equal(desk.controller.held().banks.length,3);
    assert.equal(desk.controller.state().baked.length,40);
    assert.equal(desk.controller.state().stale.length,0);
    assert.deepEqual([...fresh].sort(),placed.map(l=>l.device));
    const mesh=covered(desk.out.root)[0],shader={uniforms:{},vertexShader:'#include <begin_vertex>',fragmentShader:'#include <lights_fragment_end>'};
    mesh.material.onBeforeCompile(shader,desk.renderer);
    const owners=shader.uniforms.lmRegions.value.image.data;
    const indices=new Set();
    for(let i=3;i<owners.length;i+=4) {indices.add(owners[i]%4096);indices.add(Math.floor(owners[i]/4096));}
    indices.delete(0);assert.equal(indices.size,40,'every light owns chart texels, beyond the six-light local cap');
    assert.ok(mesh.geometry.attributes.lmRoom.array instanceof Int16Array,'compact chart indices are used when they fit');
    assert.equal(mesh.geometry.attributes.lmLightPage,undefined,'the unused base page attribute is released');
  } finally {desk.controller.stop();}
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
                                text=True, encoding='utf-8', timeout=280)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-4000:], end='')
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
