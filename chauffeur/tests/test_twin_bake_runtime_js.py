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
const { mountBake, lightsOf, bakeLights } = await import(file('static/twin/bake/runtime.js'));
let observeEncode = null;
class CodecWorker {
  postMessage(job) {
    if(job.kind==='encode')observeEncode?.(job.job);
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
  const out = gen.buildTwin(extra.plan || job.plan, job.kit, tier); await out.ready;
  if (extra.materialRole) {
    const {applyMaterialParams}=await import(file('static/twin/twin_library.js'));
    for (const material of out.materials.values()) if (material.name===extra.materialRole)
      applyMaterialParams(material,{household:true,revision:1,params:{tint:'#123456'},maps:{}},{id:'material-baked'},extra.materialRole,tier);
  }
  let plan = extra.plan || job.plan;
  if (extra.farSurface) {
    plan=structuredClone(plan);
    plan.buildings.push({id:'far',position:[1000,0],levels:[{id:'L1',elevation:0,ceiling:10}],
      rooms:[{id:'far',level:'L1',polygon:[[0,0],[254,0],[254,254],[0,254]]}]});
    const m = new THREE.Mesh(new THREE.PlaneGeometry(254,254).rotateX(-Math.PI/2).translate(127,0,-127),
      new THREE.MeshStandardMaterial({name:'ground'}));
    m.userData={merged:true,buildingId:'far'}; m.scale.setScalar(gen.FT); m.position.x=1000*gen.FT; out.root.add(m);
    if(extra.farLamp) {
      m.scale.setScalar(1);m.position.x=1000;
      plan.buildings.at(-1).rooms.push({id:'far-lamp',level:'L1',polygon:[[0,0],[10,0],[10,10],[0,10]]});
    }
  }
  const renderer = fakeRenderer(); renderer.domElement = new Node('canvas');
  if (extra.maxArrayLayers !== undefined) renderer.getContext = () => ({MAX_ARRAY_TEXTURE_LAYERS: 0x88ff,
    getParameter: name => {assert.equal(name, 0x88ff); return extra.maxArrayLayers;}});
  const scene = new THREE.Scene(); scene.add(out.root); scene.updateMatrixWorld(true);
  const controls = new THREE.EventDispatcher(); controls.target = new THREE.Vector3();
  const view = Object.assign(extra.view || {}, { plan, ready: true, scene, tier, renderer3: renderer, controls, render() {},
    ...(extra.compileBehind ? { compileBehind: () => extra.compileBehind(out.root) } : {}) });
  const server = sharedServer || fakeServer(), lights = placed || [k1, k2, h1, c1];
  const defaultApi = (path, init) => path === 'api/house/live' ? Promise.resolve(new Response(JSON.stringify({...liveLayout(lights), ...extra.fixtureLayout}), { status: 200 }))
    : extra.deny && path.endsWith('/lease') ? Promise.resolve(new Response('{"detail":"Requires parent"}', { status: 403 }))
    : server.api(path, init);
  const api = extra.api ? (path,init)=>extra.api(path,init,defaultApi) : defaultApi;
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
await check('merged_array_layer_limit_keeps_lights_real_time_and_accepts_the_boundary', async () => {
  const limited = await context('high',null,null,{maxArrayLayers:1,poll:0});
  let count;
  try {
    await until(()=>!!limited.controller.state().error,'layer overflow is observable');
    count=limited.controller.packing().layers.reduce((n,l)=>n+l.length,0);
    assert.ok(count>1);
    assert.match(limited.controller.state().error,/this GPU supports 1.*Using real-time lighting/);
    assert.equal(limited.controller.held(),null,'no oversized array allocated');
    assert.equal(limited.controller.materialsChanged(),false,'material edits can rebuild safely without baked uniforms');
    assert.deepEqual(limited.controller.fresh(),[],'no light loses its live fallback');
    assert.deepEqual(limited.controller.state().stale.sort(),['c1','h1','k1','k2']);
    await limited.controller.now();
    assert.equal(limited.renderer.log.renders,0,'no pointless bake starts');
    assert.equal(limited.controller.state().baking,false);
    assert.ok(!limited.server.calls.some(c=>c.path.endsWith('.png')),'no page fetched or published');
  } finally {limited.controller.stop();}
  const fits=await context('high',null,null,{maxArrayLayers:count,poll:0});
  try {
    await until(()=>!fits.controller.state().baking&&fits.controller.fresh().length===4,'exact layer limit fits');
    assert.equal(fits.controller.held().textures.banks[0].image.depth,count);
    assert.equal(fits.controller.state().error,null);
  } finally {fits.controller.stop();}
});
await check('invalid_ownership_rebuilds_instead_of_throwing_or_trusting_old_pages', async () => {
  const first=await context('high',null,null,{poll:0});let panel,repair;
  try {
    await until(()=>first.controller.fresh().length===4&&!first.controller.state().baking,'initial bake');
    const key=first.controller.state().key,server=first.server;
    first.controller.stop();
    const manifest=structuredClone(server.manifests.get(key));
    manifest.ownership.charts++;
    server.manifests.set(key,manifest);
    panel=await context('low',server,null,{poll:0});
    await until(()=>!!panel.controller.packing(),'reader recovers a layout');
    await panel.controller.refresh();await panel.controller.refresh();
    assert.deepEqual(panel.controller.fresh(),[],'even matching old publications are untrusted on repeated polls');
    panel.controller.stop();
    repair=await context('high',server,null,{poll:0});
    await until(()=>repair.controller.fresh().length===4&&!repair.controller.state().baking,'invalid ownership is rebuilt');
    assert.deepEqual([...repair.controller.state().baked].sort(),['c1','h1','k1','k2']);
    assert.equal(server.manifests.get(key).ownership.charts,manifest.ownership.charts-1);
    assert.ok(server.manifests.get(key).complete);
  } finally {first.controller.stop();panel?.controller.stop();repair?.controller.stop();}
});
await check('one_wall_reuses_stored_pages_and_rebakes_only_reaching_lights', async () => {
  const plan=structuredClone(job.plan),remote=[{device:'remote',building:'far',level:'L1',room:'far-lamp',at:[1005,5,6]}];
  const list=[k1,k2,h1,c1,...remote];
  const desk=await context('high',null,list,{plan,poll:0,farSurface:true,farLamp:true});let next;
  try {
    await until(()=>desk.controller.fresh().length===list.length&&!desk.controller.state().baking,'initial separated-building bake');
    const key=desk.controller.state().key,before=structuredClone(desk.server.manifests.get(key)),bytes=new Map(desk.server.pages);
    const edited=structuredClone(plan),wall=edited.buildings[0].walls[0];
    wall.faces={left:{color:'#224466'},right:{color:'#224466'}};
    desk.controller.stop();const since=desk.server.calls.length;
    next=await context('high',desk.server,list,{plan:edited,view:desk.view,poll:0,farSurface:true,farLamp:true});
    await until(()=>next.controller.state().key===key&&next.controller.packing(),'same stored atlas opens');
    const packed=next.controller.packing();
    const dirty=Object.keys(packed.entries).filter(id=>before.lights[id]?.key!==packed.entries[id].key);
    assert.ok(dirty.length>0&&dirty.length<list.length,'only physical reach becomes stale: '+JSON.stringify(dirty));
    assert.ok(remote.every(l=>!dirty.includes(l.device)),'remote lights remain fresh');
    const changedPages=new Set(dirty.flatMap(id=>packed.entries[id].pages));
    const untouched=[...new Set(remote.flatMap(l=>before.lights[l.device].pages))].filter(p=>!changedPages.has(p));
    assert.ok(untouched.length,'fixture has untouched stored pages: '+JSON.stringify({dirty,changedPages:[...changedPages],remote:remote.map(l=>before.lights[l.device]),pages:before.pages}));
    await until(()=>next.controller.fresh().length===list.length&&!next.controller.state().baking,'local rebake settles');
    assert.deepEqual([...next.controller.state().baked].sort(),dirty.sort(),'no unrelated light rebakes');
    for(const page of untouched) {
      assert.deepEqual(desk.server.pages.get(`${key}/${page}`),bytes.get(`${key}/${page}`),'untouched page bytes');
      assert.ok(!desk.server.calls.slice(since).some(c=>c.path===`api/house/bakes/${key}/${page}.png`&&c.full),'untouched page is not downloaded');
      assert.ok(!desk.server.calls.slice(since).some(c=>c.path===`api/house/bakes/${key}/${page}.png`&&c.method==='POST'),'untouched page is not rebaked');
    }
    console.log('  counts '+JSON.stringify({lights:list.length,rebaked:dirty.length,pages:before.pages,untouchedPages:untouched.length,dirtyPages:changedPages.size}));
  } finally {next?.controller.stop();desk.controller.stop();}
});
await check('material_revision_invalidates_bake_and_refreshes_affected_clones', async () => {
  const desk = await context('high',null,null,{materialRole:'interior_wall'});
  try {
    await until(() => desk.controller.fresh().length === 4 && !desk.controller.state().baking, 'initial bake');
    const mesh = covered(desk.out.root).find(m => m.material.userData.materialId === 'material-baked');
    const clone = mesh.material;
    assert.equal(clone.userData.materialRevision,1,'metadata is present before the initial bake');
    assert.equal(desk.controller.materialsChanged(['unused']), false);
    assert.ok(desk.controller.fresh().length === 4);
    const {applyMaterialParams}=await import(file('static/twin/twin_library.js'));
    // Production updates the retained source first, then refreshes bake clones.
    for (const material of desk.out.materials.values()) if (material.name === mesh.material.name) {
      applyMaterialParams(material,{household:true,revision:2,params:{tint:'#56789a'},maps:{}},{id:'material-baked'},material.name,'high');
    }
    assert.equal(desk.controller.materialsChanged(['material-baked']), true);
    assert.ok(desk.controller.state().stale.length, 'revision marks existing stale state');
    assert.equal(mesh.material,clone);assert.equal(mesh.material.color.getHexString(),'56789a');
    await desk.controller.refresh();
    assert.ok(desk.controller.state().stale.length,'the old publication cannot make the revision fresh again');
  } finally { desk.controller.stop(); }
});

await check('lightmapped_programs_compile_before_any_frame_draws_them', async () => {
  // The first baked light swaps lightmapped copies onto the house. Drawn before
  // their programs compiled, a full house froze the page for seconds.
  let originals = null, release = null, compiled = null;
  const desk = await context('high', null, null, { compileBehind(root) {
    compiled = covered(root).map(m => m.material);
    return new Promise(resolve => { release = resolve; });
  } });
  try {
    originals = covered(desk.out.root).map(m => m.material);
    await until(() => release, 'the first landed light compiles its programs');
    assert.ok(compiled.every((m, i) => m !== originals[i]), 'the compile sees the lightmapped copies');
    const meshes = covered(desk.out.root);
    assert.ok(meshes.every((m, i) => m.material === originals[i]), 'the plain materials stay on screen meanwhile');
    release();
    await until(() => meshes.every((m, i) => m.material === compiled[i]), 'the copies go on once compiled');
  } finally { release?.(); desk.controller.stop(); }
});

await check('every_placed_light_bakes_including_yard_and_fire_pit', async () => {
  // v2.499.839 left yard-room and fire-pit lights out of the bake: yard surfaces were not in
  // the atlas, so they never settled. The yard now bakes (user, 2026-11-13: "It seems silly to
  // have some lights baked and some not"), so they are in.
  const layout={markers:[
    {device_id:'indoor',kind:'light',placed:true,at:[1,2,8],room:'r',building:'b',level:'L1'},
    {device_id:'yard',kind:'light',placed:true,at:[30,40,8],room:'yard_rooms:1',building:null,level:null,yard:true},
    {device_id:'pit-light',kind:'light',placed:true,entity_id:'light.pit',at:[5,5,2],room:'r',building:'b',level:'L1'},
    {device_id:'nowhere',kind:'light',placed:true,at:[5,5,2],room:null,building:null,level:null},
    {device_id:'unplaced',kind:'light',placed:false,at:[1,1,8],room:'r',building:'b',level:'L1'}]};
  assert.deepEqual(lightsOf(layout).map(l=>l.device),['indoor','yard','pit-light']);
  assert.equal(lightsOf(layout)[1].yard,true);
  // Object lamps come from the scene, as live modes.js makes them. A fire pit owns its
  // light-domain marker's light; a lamp object with a marker stays that marker.
  const root=new THREE.Group(), pit=new THREE.Group(); pit.position.set(3,0,-4); root.add(pit);
  const flame=new THREE.MeshStandardMaterial(); flame.userData.objectLight={id:'fire_pit:f',entity:'light.pit',fire:true,fireLightAt:[0,1,0]};
  pit.add(new THREE.Mesh(new THREE.BoxGeometry(1,1,1),flame));
  const lamp=new THREE.MeshStandardMaterial(); lamp.userData.objectLight={id:'b:lamp1',entity:'light.lamp'};
  root.add(new THREE.Mesh(new THREE.BoxGeometry(1,2,1).translate(10,1,-10),lamp));
  const free=new THREE.MeshStandardMaterial(); free.userData.objectLight={id:'b:glow',entity:null};
  root.add(new THREE.Mesh(new THREE.BoxGeometry(1,1,1).translate(-6,.5,6),free));
  const withLamp={markers:[...layout.markers,{device_id:'lamp-marker',kind:'light',placed:true,entity_id:'light.lamp',at:[1,1,4],room:'r',building:'b',level:'L1'}]};
  const all=bakeLights(withLamp,root), ids=all.map(l=>l.device);
  assert.deepEqual(ids,['indoor','yard','lamp-marker','object:fire_pit:f','object:b:glow'],JSON.stringify(ids));
  const fire=all.find(l=>l.device==='object:fire_pit:f');
  assert.equal(fire.absolute,true);assert.equal(fire.range,18);
  assert.deepEqual(fire.at.map(v=>+v.toFixed(6)),[3/FT,4/FT,1/FT].map(v=>+v.toFixed(6)),'the fire light point in lot feet');
});
await check('auto_placed_light_does_not_change_legacy_bake', async () => {
  const atlas=buildAtlas(await house(),job.plan,job.layout),original=liveLayout([k1,k2,h1,c1]);
  const withAuto=structuredClone(original);
  withAuto.markers.push({...original.markers[0],device_id:'auto',entity_id:'light.auto',placed:false});
  const before=bakeLights(original,null,job.plan),after=bakeLights(withAuto,null,job.plan);
  assert.deepEqual(after,before);
  const a=B.bakeLayout(atlas,job.layout,before),b=B.bakeLayout(atlas,job.layout,after);
  assert.deepEqual(b.entries,a.entries);assert.deepEqual(b.ownership,a.ownership);
});
await check('transcode_failure_is_observable_once_per_page_and_keeps_live_fallback', async () => {
  const desk=await context();
  try {await until(()=>!desk.controller.state().baking&&desk.controller.fresh().length===4,'publish legacy bake');}
  finally {desk.controller.stop();}
  const Worker=globalThis.Worker,log=console.error,errors=[];let wall;
  try {
    console.error=(...args)=>errors.push(args);
    globalThis.Worker=class {constructor(url,options) {
      if(!String(url).includes('codec_worker'))return new Worker(url,options);
      return {postMessage(job){setImmediate(()=>this.onmessage({data:{id:job.id,error:'codec transcode import broke'}}));},terminate(){}};
    }};
    wall=await context('low',desk.server,null,{poll:0});
    await until(()=>wall.controller.state().error,'transcode rejection is exposed');
    await wall.controller.refresh();
    const count=errors.length;assert.ok(count>0);
    assert.match(wall.controller.state().error,/codec transcode import broke/);
    assert.deepEqual(wall.controller.fresh(),[]);assert.equal(wall.renderer.log.renders,0);
    await wall.controller.refresh();await wall.controller.refresh();
    assert.equal(errors.length,count,'polling does not repeat page diagnostics');
  } finally {wall?.controller.stop();globalThis.Worker=Worker;console.error=log;}
});
await check('desk_page_error_survives_run_and_clears_after_successful_transcode', async () => {
  const publisher=await context();
  try {await until(()=>!publisher.controller.state().baking&&publisher.controller.fresh().length===4,'publish stored bake');}
  finally {publisher.controller.stop();}
  const Worker=globalThis.Worker,log=console.error,errors=[];let desk,broken=true;
  try {
    console.error=(...args)=>errors.push(args);
    globalThis.Worker=class {constructor(url,options) {
      if(!String(url).includes('codec_worker'))return new Worker(url,options);
      const worker=new CodecWorker(),post=worker.postMessage;
      worker.postMessage=function(job) {
        if(broken&&job.kind==='transcode')setImmediate(()=>this.onmessage({data:{id:job.id,error:'damaged desk page'}}));
        else post.call(this,job);
      };return worker;
    }};
    desk=await context('high',publisher.server,null,{poll:0});
    await until(()=>desk.controller.state().key&&desk.controller.state().error&&!desk.controller.state().baking,'desk finished automatic run');
    await desk.controller.now(); // run() clears job errors, but must retain page errors.
    assert.match(desk.controller.state().error,/damaged desk page/);
    const output=document.getElementById('twin-bake-controls').children.find(n=>n.tagName==='OUTPUT');
    assert.match(output.textContent,/damaged desk page/);assert.ok(!output.hidden);
    assert.ok(!output.textContent.includes('Try Bake lighting now'));
    const count=errors.length;await desk.controller.refresh();assert.equal(errors.length,count,'page diagnostics are deduplicated on a desk too');
    broken=false;await desk.controller.refresh();
    assert.equal(desk.controller.fresh().length,4);assert.equal(desk.controller.state().error,null);
    assert.ok(!output.textContent.includes('damaged desk page'));
  } finally {desk?.controller.stop();globalThis.Worker=Worker;console.error=log;}
});
await check('failed_mount_retries_from_existing_poll_and_finds_stored_bake',async()=>{
  const desk=await context();
  try {await until(()=>!desk.controller.state().baking&&desk.controller.fresh().length===4,'publish for retrying wall');}
  finally {desk.controller.stop();}
  const log=console.error,errors=[];console.error=(...args)=>errors.push(args);
  try {
    for(const step of ['live','manifest']) {
      let attempts=0,wall;
      const api=async(path,init,next)=>{
        if((step==='live'?path==='api/house/live':/^api\/house\/bakes\/[^/]+$/.test(path))&&++attempts===1)
          throw new TypeError('Failed to fetch '+step);
        return next(path,init);
      };
      try {
        wall=await context('low',desk.server,null,{poll:200,api});
        await until(()=>wall.controller.state().error,'mount failure reported');
        await until(()=>wall.controller.fresh().length===4,'later poll retries '+step+' and reads stored pages');
        assert.ok(attempts>=2);assert.equal(wall.controller.state().error,null);
      } finally {wall?.controller.stop();}
    }
    const Worker=globalThis.Worker;let published=false,throws=0,late;
    try {
      globalThis.Worker=class {constructor(url,options) {
        if(String(url).includes('codec_worker')&&++throws===1)throw new Error('codec mount failed');
        return new Worker(url,options);
      }};
      late=await context('low',desk.server,null,{poll:200,api:async(path,init,next)=>
        !published&&/^api\/house\/bakes\/[^/]+$/.test(path)?new Response(null,{status:404}):next(path,init)});
      await until(()=>late.controller.state().key,'wall waits for stored bake');published=true;
      await until(()=>late.controller.state().error==='codec mount failed','late begin failure is reported by poll');
      await until(()=>late.controller.fresh().length===4,'next poll retries failed begin after pending was cleared');
      assert.equal(late.controller.state().key,desk.controller.state().key,'retry retains the applied atlas and stored bake key');
      assert.equal(late.controller.state().error,null);assert.ok(throws>=2);
    } finally {late?.controller.stop();globalThis.Worker=Worker;}
    let broken=false,wall;
    try {
      wall=await context('low',desk.server,null,{poll:200,api:async(path,init,next)=>{
        if(broken&&/^api\/house\/bakes\/[^/]+$/.test(path))throw new SyntaxError('unexpected manifest structure');
        return next(path,init);
      }});
      await until(()=>wall.controller.fresh().length===4,'wall mounted');broken=true;
      await until(()=>wall.controller.state().error==='unexpected manifest structure','poll reports non-network failure');
      assert.ok(errors.some(args=>args.some(e=>e?.message==='unexpected manifest structure')));
    } finally {wall?.controller.stop();}
    let down=false,dropped=0,quiet;
    try {
      quiet=await context('low',desk.server,null,{poll:200,api:async(path,init,next)=>{
        if(down){++dropped;throw new TypeError('Failed to fetch');}
        return next(path,init);
      }});
      await until(()=>quiet.controller.fresh().length===4,'wall mounted before the network drops');
      const before=errors.length;down=true;
      await until(()=>dropped>=3,'polls continue while offline');
      assert.equal(quiet.controller.state().error,null,'an offline poll is not a bake failure');
      assert.equal(errors.length,before,'an offline poll logs nothing');
      assert.equal(quiet.controller.fresh().length,4,'the last complete pages stay lit');
      down=false;const seen=dropped;
      await new Promise(resolve=>setTimeout(resolve,700));
      assert.equal(dropped,seen);assert.equal(quiet.controller.state().error,null);assert.equal(quiet.controller.fresh().length,4);
    } finally {quiet?.controller.stop();}
  } finally {console.error=log;}
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
    assert.ok(held.banks.slice(1).every(b=>b.lit.length===0&&b.layers===0),'unoccupied banks allocate no layers');
    assert.equal(held.textures.banks.length,1,'all logical banks use one physical texture');
    assert.equal(held.textures.banks[0].image.depth,held.banks.reduce((n,b)=>n+b.layers,0));
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
    assert.deepEqual(changed.updates.banks[0], [changed.banks[0].base + changed.banks[0].lit.indexOf(page)], 'only the changed page\'s merged layer uploads');
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
    const held = desk.controller.held(), packing = desk.controller.packing(), texture = held.textures.banks[0];
    assert.equal(held.textures.banks.length,1,'three logical banks share one physical texture');
    assert.equal(shader.uniforms.lmBanks.value,texture);
    assert.equal(texture.image.depth,packing.layers.reduce((n,l)=>n+l.length,0));
    assert.equal((shader.fragmentShader.match(/uniform\s+highp\s+sampler2DArray\s+/g)||[]).length,1);
    for (let b=0;b<packing.banks.length;b++) {
      for (const [chart,page] of packing.banks[b].charts) {
        const [x,y]=M.chartAddress(chart,b,packing.banks.length);
        assert.equal(shader.uniforms.lmRegions.value.image.data[(y*1024+x)*4+2],
          held.banks[b].base+Math.max(0,packing.layers[b].indexOf(page)),'chart regions use merged layers');
      }
      for (let layer=0;layer<packing.layers[b].length;layer++) {
        const offset=packing.offsets[b]; // Server page addresses do not change.
        const bytes=desk.server.pages.get(`${desk.controller.state().key}/${offset+packing.layers[b][layer]}`);
        const decoded=await M.transcodePage(T,bytes,texture.format);
        for(let mip=0;mip<texture.mipmaps.length;mip++) {
          const per=decoded.mipmaps[mip].data.length,start=(held.banks[b].base+layer)*per;
          assert.deepEqual(texture.mipmaps[mip].data.slice(start,start+per),decoded.mipmaps[mip].data,
            `bank ${b} layer ${layer}, mip ${mip}: unchanged page bytes at the merged layer`);
        }
      }
    }
    const owners=shader.uniforms.lmRegions.value.image.data;
    const indices=new Set();
    for(let i=3;i<owners.length;i+=4) {indices.add(owners[i]%4096);indices.add(Math.floor(owners[i]/4096));}
    indices.delete(0);assert.equal(indices.size,40,'every light owns chart texels, beyond the six-light local cap');
    assert.ok(mesh.geometry.attributes.lmRoom.array instanceof Int16Array,'compact chart indices are used when they fit');
    assert.equal(mesh.geometry.attributes.lmLightPage,undefined,'the unused base page attribute is released');
    const b=held.banks.findLastIndex(bank=>bank.layers>0), layer=held.banks[b].layers-1;
    assert.ok(b>0,'update exercises a later bank');
    const page=packing.offsets[b]+packing.layers[b][layer],key=desk.controller.state().key,version=texture.version;
    texture.clearLayerUpdates();
    await desk.server.api(`api/house/bakes/${key}/${page}.png`,{method:'POST',body:desk.server.pages.get(`${key}/${page}`)});
    await desk.controller.refresh();
    assert.ok(texture.version>version);
    assert.deepEqual([...texture.layerUpdates],[held.banks[b].base+layer],'later-bank ETag update uploads only its merged layer');
    const snapshot=desk.controller.snapshot(),since=desk.server.calls.length;
    desk.controller.stop();
    const panel=await context('low',desk.server,placed,{view:{bake:{snapshot:()=>snapshot}},poll:0});
    try {
      await until(()=>panel.controller.fresh().length===40,'retained multi-bank pages stay fresh');
      const copy=panel.controller.held().textures.banks[0];
      assert.notEqual(copy.uuid,texture.uuid);
      assert.deepEqual(copy.mipmaps,texture.mipmaps,'every retained merged layer and mip is copied');
      assert.deepEqual(panel.controller.snapshot().bankBase,snapshot.bankBase);
      assert.ok(!desk.server.calls.slice(since).some(c=>c.method==='GET'&&c.path.endsWith('.png')),
        'retained pages with unchanged signatures need no page fetch');
    } finally {panel.controller.stop();}
  } finally {desk.controller.stop();}
});

await check('fixture_groups_bake_twice_settle_and_populate_shape_rows', async () => {
  const {lightSource}=await import(file('static/twin/bake/reach.js'));
  const source=lightSource(job.plan,k1).source, at=[source.x/gen.FT,-source.z/gen.FT,source.y/gen.FT];
  const point=(id,x=0)=>({id:'fixture:'+id,shape:'point',ref:'absolute',at:[at[0]+x,at[1],at[2]]});
  const fixtureLayout={light_fixtures:{
    'light.spot':[{...point('s'),shape:'spot',aim:[at[0]+2,at[1],0],cone_deg:60,softness:.3}],
    'light.rect':[{...point('a'),shape:'area',size_ft:[2,2],facing:'down'}],
    'light.sum':[point('one',-1),point('two',1)]}};
  const desk=await context('high',null,[],{fixtureLayout});
  try {
    await until(()=>desk.controller.fresh().length===3&&!desk.controller.state().baking,'fixture groups bake');
    assert.deepEqual(desk.controller.state().stale,[]);
    assert.equal(desk.controller.state().baked.length,3,'one publication per entity');
    const mesh=covered(desk.out.root)[0],shader={uniforms:{},vertexShader:'#include <begin_vertex>',fragmentShader:'#include <lights_fragment_end>'};
    mesh.material.onBeforeCompile(shader,desk.renderer);
    const t=shader.uniforms.lmTints.value;assert.equal(t.image.height,17);assert.equal(t.image.width,3);
    assert.deepEqual([t.image.data[24],t.image.data[28],t.image.data[32]],[1,2,3]);
    assert.ok(t.image.data[34]>0,'the sum scale reaches the shader');
    const manifest=desk.server.manifests.get(desk.controller.state().key);
    const atlas=buildAtlas(await house(),job.plan,job.layout);
    assert.equal(atlas.key,desk.controller.state().key,'second baker uses the identical receiver geometry');
    const again=B.createBaker(desk.view,{renderer:desk.renderer,atlas,layout:job.layout,
      lights:bakeLights(fixtureLayout,null,job.plan),api:desk.server.api,codec:{}});
    assert.deepEqual(await again.staleLights(),[],'second sum run has nothing to bake');
    const reads=desk.renderer.log.reads;
    assert.equal(await again.bakeNext(),null);assert.equal(desk.renderer.log.reads,reads);again.cancel();
    assert.equal(t.image.data[34],Math.fround(manifest.lights['light.sum'].scale),'decode scale is the published manifest value');
    desk.controller.light('light.spot',[255,100,50],1);assert.ok(t.image.data[0]>0);
    await desk.controller.now();
    assert.deepEqual(desk.controller.state().stale,[]);assert.equal(desk.controller.state().baked.length,6);
    assert.deepEqual(desk.controller.fresh().sort(),['light.rect','light.spot','light.sum']);
  } finally {desk.controller.stop();}
});
await check('rect_cap_changes_shading_only',async()=>{
  const {TIERS}=await import(file('static/twin/twin_tiers.js'));
  const {createHash}=await import('node:crypto');
  const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
  const {lightSource}=await import(file('static/twin/bake/reach.js'));
  const source=lightSource(job.plan,k1).source,at=[source.x/gen.FT,-source.z/gen.FT,source.y/gen.FT];
  const fixtureLayout={light_fixtures:Object.fromEntries(Array.from({length:3},(_,i)=>['light.rect'+i,
    [{id:'fixture:a'+i,shape:'area',ref:'absolute',at:[at[0]+i*.1,at[1],at[2]],size_ft:[2,2],facing:'down'}]]))};
  const cap=TIERS.high.bakedRects,server=fakeServer();let c;
  try {
    const captures=[];
    for(const limit of [2,16]) {
      TIERS.high.bakedRects=limit;
      // Give both caps the identical empty bake store. Re-encoding an older
      // lossy page would measure compression drift rather than a tier input.
      server.pages.clear();server.manifests.clear();server.etags.clear();
      const channels=[];observeEncode=job=>channels.push(job.channels.map(hash));
      c=await context('high',server,[],{fixtureLayout,poll:0});
      await until(()=>c.controller.fresh().length===3&&!c.controller.state().baking,'all rect entities land');
      const mesh=covered(c.out.root)[0],shader={uniforms:{},vertexShader:'#include <begin_vertex>',fragmentShader:'#include <lights_fragment_end>'};
      mesh.material.onBeforeCompile(shader,c.renderer);
      const data=[...shader.uniforms.lmTints.value.image.data],key=c.controller.state().key;
      captures.push({inputs:bakeLights(fixtureLayout,null,job.plan),packing:structuredClone(c.controller.packing()),
        manifest:JSON.stringify(server.manifests.get(key)),pages:[...server.pages].map(([key,bytes])=>[key,hash(bytes)]),channels,data});
      c.controller.stop();c=null;
    }
    const [low,high]=captures;
    assert.deepEqual(high.inputs,low.inputs);assert.deepEqual(high.packing.entries,low.packing.entries);
    assert.deepEqual(high.packing.slots,low.packing.slots);assert.deepEqual(high.packing.banks,low.packing.banks);
    assert.equal(high.manifest,low.manifest,'manifest text is independent of the cap');assert.deepEqual(high.pages,low.pages);assert.deepEqual(high.channels,low.channels);
    assert.notDeepEqual(high.data,low.data,'the shader uniform list changes');
    const flags=t=>Array.from({length:3},(_,i)=>t[(2*3+i)*4+3]);
    assert.equal(flags(low.data).reduce((a,b)=>a+b,0),2);assert.equal(flags(high.data).reduce((a,b)=>a+b,0),3);
  } finally {c?.controller.stop();TIERS.high.bakedRects=cap;observeEncode=null;}
});
await check('five_mixed_entries_become_fresh_and_force_bake_again',async()=>{
  const {lightSource}=await import(file('static/twin/bake/reach.js'));
  const source=lightSource(job.plan,k1).source,at=[source.x/gen.FT,-source.z/gen.FT,source.y/gen.FT];
  const point=(id,dx=0)=>({id:'fixture:'+id,shape:'point',ref:'absolute',at:[at[0]+dx,at[1],at[2]]});
  const fixtureLayout={light_fixtures:{
    'light.spot':[{...point('s'),shape:'spot',aim:[at[0],at[1],0],cone_deg:60,softness:.3}],
    'light.panel':[{...point('a'),shape:'area',size_ft:[3,2],facing:'down'}],
    'light.line':[{id:'fixture:l',shape:'line',ref:'absolute',path:[at,[at[0]+9,at[1],at[2]]],facing:'down',width_in:.5}],
    'light.sum':[point('one',-1),point('two',1)]}};
  const desk=await context('high',null,[k2],{fixtureLayout,poll:0});
  try {
    await until(()=>desk.controller.fresh().length===5&&!desk.controller.state().baking,'all five entries fresh');
    assert.equal(desk.controller.state().baked.length,5);assert.deepEqual(desk.controller.state().stale,[]);
    for(let i=0;i<3;i++)await desk.controller.refresh();
    assert.equal(desk.controller.state().baked.length,5,'unchanged refresh does not restart the bake');
    const key=desk.controller.state().key,m=desk.server.manifests.get(key);
    const sumScale=m.lights['light.sum'].scale;assert.ok(sumScale>0);
    m.lights['light.sum'].scale*=2;
    const sumPages=m.lights['light.sum'].pages;
    desk.server.fail=(method,path)=>method==='GET'&&sumPages.some(p=>path.endsWith('/'+p+'.png'))?500:null;
    try {
      await desk.controller.refresh();
      assert.ok(desk.controller.state().stale.includes('light.sum'),'old held bytes cannot become fresh with a new scale while replacements are offline');
    } finally {desk.server.fail=null;}
    delete m.lights['light.sum'].scale;
    await desk.controller.refresh();assert.ok(desk.controller.state().stale.includes('light.sum'),'missing scale leaves sum real-time');
    const wall=await context('low',desk.server,[k2],{fixtureLayout,poll:0});
    try {
      await until(()=>wall.controller.fresh().length===4,'reader refuses a sum with no scale');
      assert.ok(wall.controller.state().stale.includes('light.sum'));
    }finally{wall.controller.stop();}
    const oldFill=FILL.value;FILL.value*=4;
    try {
    await desk.controller.now();
    assert.equal(desk.controller.state().baked.length,10);assert.deepEqual(desk.controller.state().stale,[]);
    assert.equal(desk.controller.fresh().length,5);
    const nextScale=desk.server.manifests.get(key).lights['light.sum'].scale;
    assert.ok(nextScale>sumScale,'a later rendered bake publishes its new scale');
    const panel=await context('low',desk.server,[k2],{fixtureLayout,poll:0});
    try {await until(()=>panel.controller.fresh().length===5,'reopened reader adopts rendered scale');}
    finally {panel.controller.stop();}
    } finally {FILL.value=oldFill;}
  }finally{desk.controller.stop();}
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
        try:
            result = subprocess.run([B.node(), str(driver), str(data), *sys.argv[1:]], capture_output=True,
                                    text=True, encoding='utf-8', timeout=420)
        except subprocess.TimeoutExpired as exc:
            print((exc.stdout or b'').decode('utf-8', errors='replace'), end='')
            raise
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-4000:], end='')
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
