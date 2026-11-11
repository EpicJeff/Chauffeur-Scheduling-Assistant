"""Reach, visibility inputs, local keys and room bounce in node; no browser/GPU."""
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_twin_baker_js as B

DRIVER = B.DRIVER[:B.DRIVER.index('// --- the fake GPU')]
DRIVER += B.DRIVER[B.DRIVER.index('// --- the fake GPU'):B.DRIVER.index('// --- the fake bake server')]
DRIVER += B.DRIVER[B.DRIVER.index('// --- the fake bake server'):B.DRIVER.index('// --- the house, the lights')]
DRIVER += r"""
const { reachLights, lightSource } = await import(file('static/twin/bake/reach.js'));
const { assignChannels, CHANNEL_FALLBACK } = await import(file('static/twin/bake/atlas.js'));
const { chartLightmapUniforms, chartAddress, setLightTint, patchLightmaps } = await import(file('static/twin/bake/lightmap_material.js'));
const { occluders, addRoomBounce, addRoomBounceAcrossPages, renderPage } = await import(file('static/twin/bake/bake_pass.js'));
const FT = gen.FT, options = {room: {density: 2, page: 128, gutter: 2}};
function house(wall = false, wallX = 10, remote = 100) {
  const plan = { buildings: [{ id: 'b', position: [0,0], levels: [{id:'L1', elevation:0, ceiling:10}],
    rooms: [{id:'a', level:'L1', polygon:[[0,0],[10,0],[10,10],[0,10]]},
      {id:'b', level:'L1', polygon:[[10,0],[20,0],[20,10],[10,10]]}] }] };
  const root = new THREE.Group(); root.scale.setScalar(FT); root.userData.buildingId = 'b';
  const mesh = (geometry, name, transparent = false) => {
    const m = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({name, transparent, side:THREE.DoubleSide}));
    m.userData.merged = true; root.add(m); return m;
  };
  mesh(new THREE.PlaneGeometry(40,10).rotateX(-Math.PI/2).translate(10,0,-5), 'floor');
  if (wall) mesh(new THREE.BoxGeometry(.2,10,10).translate(wallX,5,-5), 'interior_wall');
  // A glazed west opening with solid wall on either side and above/below it.
  mesh(new THREE.BoxGeometry(.2,2,10).translate(0,1,-5), 'exterior_wall');
  mesh(new THREE.BoxGeometry(.2,2,10).translate(0,9,-5), 'exterior_wall');
  mesh(new THREE.BoxGeometry(.2,6,2).translate(0,5,-1), 'exterior_wall');
  mesh(new THREE.BoxGeometry(.2,6,2).translate(0,5,-9), 'exterior_wall');
  mesh(new THREE.PlaneGeometry(6,6).rotateY(Math.PI/2).translate(0,5,-5), 'glass', true);
  mesh(new THREE.BoxGeometry(.2,10,10).translate(remote,5,-5), 'exterior_wall');
  root.updateMatrixWorld(true);
  return { root, plan, atlas:buildAtlas(root,plan,options) };
}
const lamp = {device:'lamp', building:'b', level:'L1', room:'a', at:[3,5,5]};
const reached = ctx => reachLights(ctx.atlas.room,[lamp])[0];
const blocked = (ctx, from, to) => {
  const blockers = occluders({scene:ctx.root}); blockers.updateMatrixWorld(true);
  const a = new THREE.Vector3(...from).multiplyScalar(FT), b = new THREE.Vector3(...to).multiplyScalar(FT);
  const ray = new THREE.Raycaster(a,b.clone().sub(a).normalize(),.001,a.distanceTo(b)-.025);
  return ray.intersectObjects(blockers.children,false).length > 0;
};
let passed=0, ran=0;
async function check(name, fn) { ran++; try { await fn(); passed++; console.log('  ok   '+name); }
  catch(e) {console.log('  FAIL '+name+' '+e.stack);} }
await check('invisible_separator_reaches_the_neighbour_floor', () => {
  const ctx=house(), l=reached(ctx);
  assert.ok(l.receivers.includes(1));
  const p=B.bakeLayout(ctx.atlas,options,[lamp]);
  assert.equal(ctx.atlas.room.packBanks([lamp]).length,3,'direct atlas callers also get three banks');
  assert.ok(p.banks[p.slots.lamp.bank].charts.some(c => c.room===1));
});
await check('solid_wall_blocks_the_same_cube_depth_rays', () => {
  const ctx=house(true);
  assert.equal(blocked(ctx,[3,5,-5],[14,0,-5]),true, 'solid wall is in the depth pass');
  assert.equal(blocked(house(),[3,5,-5],[14,0,-5]),false, 'separator has no physical occluder');
});
await check('bake_entry_point_shadows_far_side_with_zero_room_fill', async () => {
  const ctx=house(true), packed=B.bakeLayout(ctx.atlas,options,[lamp]);
  const slot=packed.slots.lamp, charts=packed.banks[slot.bank].charts.filter(c=>c.room===1);
  const renderer=fakeRenderer(); let depthScene=null, receiverScene=null;
  renderer.render=(scene)=>{
    if(scene.overrideMaterial?.uniforms.depthCube) receiverScene=scene;
    else depthScene=scene;
  };
  renderer.readRenderTargetPixelsAsync=async (rt,x,y,w,h,raw)=>{
    assert.ok(depthScene?.children.length && receiverScene?.children.length);
    const shader=receiverScene.overrideMaterial;
    assert.ok(shader.fragmentShader.includes('step(d - 0.025, stored)'));
    assert.ok(shader.fragmentShader.includes('if (d >= reach) discard'));
    const point=new THREE.Vector3(14,0,-5).multiplyScalar(FT), source=shader.uniforms.source.value;
    const ray=new THREE.Raycaster(source,point.clone().sub(source).normalize(),.001,source.distanceTo(point)-.025);
    depthScene.updateMatrixWorld(true);
    const visible=ray.intersectObjects(depthScene.children,false).length===0;
    // The fake GPU executes the cube-depth visibility decision at this sample.
    raw.fill(0); for(let i=0;i<raw.length;i+=4) {raw[i]=THREE.DataUtils.toHalfFloat(visible?.3:0);raw[i+3]=THREE.DataUtils.toHalfFloat(1);}
  };
  const pixels=await renderPage({scene:ctx.root,plan:ctx.plan},renderer,charts,options.room.page,lamp,options,ctx.atlas);
  assert.ok(charts.length);
  assert.equal(pixels.some((v,i)=>i%4===0&&v>0),false,'solid wall leaves the far-side room direct and bounced texels zero');
});
await check('glazed_opening_reaches_outdoor_ground', () => {
  const ctx=house(), l=reached(ctx);
  assert.ok(l.receivers.some(r => ctx.atlas.room.rooms[r].outdoor));
  assert.equal(blocked(ctx,[3,5,-5],[-3,0,-5]),false, 'glass does not block a ray through the opening');
  assert.equal(blocked(ctx,[3,5,-1],[-3,0,-1]),true, 'the solid wall alongside still blocks');
});
await check('far_surfaces_reserve_no_channels', () => {
  const ctx=house(), l=reached(ctx);
  const remote = ctx.atlas.room.charts.filter(c => {
    const pos=c.mesh.geometry.attributes.position;
    return c.faces.every(f => [0,1,2].every(k => pos.getX(f*3+k)>90));
  });
  assert.ok(remote.length);
  for(const c of remote) assert.ok(!l.receivers.includes(c.room));
});
await check('nearby_wall_changes_key_and_remote_wall_does_not', () => {
  const key=ctx => B.bakeLayout(ctx.atlas,options,[lamp]).entries.lamp.key;
  const a=house(true,10,100), b=house(true,11,100), c=house(true,10,110);
  assert.notEqual(key(a),key(b)); assert.equal(key(a),key(c));
  assert.notEqual(a.atlas.key,c.atlas.key,'global atlas key still tracks all geometry');
});
await check('overlapping_lights_have_independent_channels_in_every_group', () => {
  const ctx=house(), other={...lamp,device:'other',room:'b',at:[12,5,5]};
  const p=B.bakeLayout(ctx.atlas,options,[lamp,other]);
  assert.ok(p.slots.lamp.receivers.includes(1) && p.slots.other.receivers.includes(0));
  for(const a of p.slots.lamp.assignments) {
    const b=p.slots.other.assignments.find(b=>b.chart===a.chart);
    if(b) assert.notEqual(a.bank*2+a.channel,b.bank*2+b.channel);
  }
});
await check('distant_rooms_share_a_channel_over_disjoint_chart_reaches', () => {
  const ctx=house();
  ctx.plan.buildings[0].rooms.push({id:'far',level:'L1',polygon:[[90,0],[110,0],[110,10],[90,10]]});
  ctx.atlas=buildAtlas(ctx.root,ctx.plan,options);
  const other={...lamp,device:'far',room:'far',at:[100,5,5]};
  const p=B.bakeLayout(ctx.atlas,options,[lamp,other]);
  assert.ok(p.slots.lamp && p.slots.far);
  assert.equal(p.slots.lamp.bank,p.slots.far.bank);
  assert.equal(p.slots.lamp.channel,p.slots.far.channel);
  assert.ok(!p.slots.lamp.receivingCharts.some(c=>p.slots.far.receivingCharts.includes(c)));
});
await check('keys_track_own_slots_but_not_unrelated_lights', () => {
  const ctx=house();ctx.plan.buildings[0].rooms.push({id:'far',level:'L1',polygon:[[90,0],[110,0],[110,10],[90,10]]});
  ctx.atlas=buildAtlas(ctx.root,ctx.plan,options);
  const key=list=>B.bakeLayout(ctx.atlas,options,list).entries.lamp.key;
  const baseline=key([lamp]),far={...lamp,device:'far',room:'far',at:[100,5,5]};
  assert.equal(key([lamp,far]),baseline,'an unrelated chart owner cannot change this key');
  const neighbour={...lamp,device:'aaa-neighbour',room:'b',at:[12,5,5]};
  assert.notEqual(key([lamp,neighbour]),baseline,'a different first-assignment slot changes this key');
  const previous=B.bakeLayout(ctx.atlas,options,[lamp]);
  assert.equal(B.bakeLayout(ctx.atlas,options,[lamp,neighbour],previous.ownership).entries.lamp.key,baseline,'a newcomer cannot shuffle a surviving owner');
});
await check('an_isolated_move_rebakes_only_it_and_preserves_other_texels', async () => {
  const ctx=house();
  ctx.plan.buildings[0].rooms.push({id:'far',level:'L1',polygon:[[90,0],[110,0],[110,10],[90,10]]});
  for (const [x,size] of [[100,2],[160,8]]) {
    const m=new THREE.Mesh(new THREE.BoxGeometry(size,size,size).translate(x,5,-5),new THREE.MeshStandardMaterial({name:'wall'}));
    m.userData.merged=true;ctx.root.add(m);
  }
  const distant=new THREE.Mesh(new THREE.PlaneGeometry(124,124).rotateY(Math.PI/2).translate(160,65,-5),
    new THREE.MeshStandardMaterial({name:'wall'}));
  distant.userData.merged=true;ctx.root.add(distant);
  ctx.atlas=buildAtlas(ctx.root,ctx.plan,options);
  const near=[lamp,{...lamp,device:'a-near-2'},{...lamp,device:'b-near-3'}];
  const remote={...lamp,device:'remote',room:'far',at:[100,5,5]},moved={...remote,at:[160,5,5]},before=[...near,remote],after=[...near,moved];
  const first=B.bakeLayout(ctx.atlas,options,before),second=B.bakeLayout(ctx.atlas,options,after);
  const ownership=p=>p.slots.lamp.assignments.map(a=>[a.chartKey,a.bank,a.channel]);
  assert.deepEqual(ownership(first),ownership(second),'the near lamp has unchanged ownership');
  assert.equal(first.entries.lamp.key,second.entries.lamp.key,'unchanged physical light key');
  assert.equal(first.entries.lamp.location,second.entries.lamp.location,'moving a remote lamp cannot repack the near lamp');
  assert.deepEqual(first.entries.lamp.pages,second.entries.lamp.pages,'stable page addresses');
  assert.ok(second.banks[0].pages>first.banks[0].pages,'the move activates a previously unlit trailing page');
  assert.deepEqual(first.offsets,second.offsets,'fixed geometry strides preserve later banks');
  assert.ok(first.slots.lamp.assignments.some(a=>a.bank===1),'the untouched lamp owns texels in a later bank');
  const renderer=fakeRenderer(),view={plan:ctx.plan,scene:ctx.root,tier:'high'},server=fakeServer();
  const codec={encode:async j=>B.encodePage(E,j),decode:async bytes=>B.decodePage(T,bytes)};
  const make=list=>B.createBaker(view,{atlas:ctx.atlas,layout:options,lights:list,renderer,api:server.api,codec});
  const initial=make(before);while(await initial.bakeNext()) {}
  const saved=structuredClone(server.manifests.get(ctx.atlas.key).lights.lamp);
  const decode=async p=>(await codec.decode(server.pages.get(ctx.atlas.key+'/'+p))).channels;
  const samples=async()=>{
    const decoded=new Map();for(const p of saved.pages) decoded.set(p,await decode(p));
    return first.slots.lamp.assignments.flatMap(a=>{const c=first.banks[a.bank].charts.find(c=>c.id===a.chart),bytes=decoded.get(first.offsets[a.bank]+c.page)[a.channel],out=[];
      for(let y=c.rect.y;y<c.rect.y+c.rect.h;y++) for(let x=c.rect.x;x<c.rect.x+c.rect.w;x++) out.push(bytes[y*options.room.page+x]);return out;});
  };
  const oldPixels=await samples(),next=make(after);
  assert.deepEqual(await next.staleLights(),['remote'],'only the isolated moved light goes stale');
  assert.equal(await next.bakeNext(),'remote');assert.equal(await next.bakeNext(),null);
  assert.deepEqual(server.manifests.get(ctx.atlas.key).lights.lamp,saved,'untouched manifest entry is identical');
  const newPixels=await samples();
  assert.ok(oldPixels.length&&oldPixels.some(x=>x>0));
  assert.ok(oldPixels.every((x,i)=>Math.abs(x-newPixels[i])<=2),'unchanged owned channels survive compressed page updates');
});
await check('a_crowded_chart_drops_its_dimmest_light_without_dropping_it_elsewhere', () => {
  const rooms=[{id:'a',building:'b'}];
  const lights=Array.from({length:7},(_,i)=>({...lamp,device:'lamp-'+i,
    receivers:[0],receivingCharts:i===6?[0,1]:[0],scores:{0:7-i,1:1},distances:{0:i+1},range:100}));
  const slots=assignChannels(rooms,lights), reverse=assignChannels(rooms,[...lights].reverse());
  assert.equal(Object.keys(slots).length,7);
  assert.equal(slots['lamp-6'].assignments.some(a=>a.chart===0),false);
  assert.equal(slots['lamp-6'].assignments.some(a=>a.chart===1),true);
  assert.deepEqual(slots[CHANNEL_FALLBACK],[]);
  for(const l of lights) assert.deepEqual(slots[l.device].assignments,reverse[l.device].assignments,'ranking is independent of input order');
});
await check('rank_changes_do_not_change_slots_or_keys_below_the_cap', () => {
  const rooms=[{id:'a',building:'b'}];
  const lights=Array.from({length:4},(_,i)=>({...lamp,device:'member-'+i,reach:'unchanged',receivers:[0],
    receivingCharts:[0],chartKeys:{0:'stable-chart'},scores:{0:4-i},range:10}));
  const first=assignChannels(rooms,lights),next=assignChannels(rooms,lights.map((l,i)=>({...l,scores:{0:i+1}})));
  for(const l of lights) {
    assert.deepEqual(first[l.device].assignments.map(a=>[a.bank,a.channel]),next[l.device].assignments.map(a=>[a.bank,a.channel]));
    assert.equal(B.lightKey({key:'atlas'},l,first[l.device]),B.lightKey({key:'atlas'},l,next[l.device]),'rank is not freshness');
  }
});
await check('a_seventh_light_reuses_only_its_evicted_members_slot_across_reload', async () => {
  const ctx=house(),scores=[7,1,6,5,4,3,0];
  const firstLights=scores.map((score,i)=>({...lamp,device:'member-'+i,reach:'fixed-geometry',receivers:[0],
    receivingCharts:[0,...([1,6].includes(i)?[1]:[])],chartKeys:{0:ctx.atlas.room.charts[0].key,1:ctx.atlas.room.charts[1].key},scores:{0:score,1:1}}));
  const renderer=fakeRenderer(),view={plan:ctx.plan,scene:ctx.root,tier:'high'},server=fakeServer();
  const codec={encode:async j=>B.encodePage(E,j),decode:async bytes=>B.decodePage(T,bytes)};
  const make=list=>B.createBaker(view,{atlas:ctx.atlas,layout:options,lights:list,renderer,api:server.api,codec});
  async function finish(baker) {
    const baked=[];for(let i=0;i<8;i++) {const stale=await baker.staleLights();if(!stale.length)return baked.sort();
      FILL.value=(Number(stale[0].split('-')[1])+1)*.06;baked.push(await baker.bakeNext());}
    throw new Error('baker did not finish');
  }
  const first=B.bakeLayout(ctx.atlas,options,firstLights);
  assert.deepEqual(await finish(make(firstLights)),firstLights.map(l=>l.device).sort());
  const manifest=structuredClone(server.manifests.get(ctx.atlas.key));
  const survivors=['member-0','member-2','member-3','member-4','member-5'];
  const pixels=async (p,id)=>{
    const decoded=new Map();for(const page of p.entries[id].pages) decoded.set(page,(await codec.decode(server.pages.get(ctx.atlas.key+'/'+page))).channels);
    return p.slots[id].assignments.map(a=>{const c=p.banks[a.bank].charts.find(c=>c.id===a.chart);
      return decoded.get(p.offsets[a.bank]+c.page)[a.channel][(c.rect.y+Math.floor(c.rect.h/2))*options.room.page+c.rect.x+Math.floor(c.rect.w/2)];});
  };
  const oldPixels=new Map();for(const id of survivors) oldPixels.set(id,await pixels(first,id));
  const moved=firstLights.map((l,i)=>i===6?{...l,at:[4,5,5],scores:{0:8,1:1}}:l);
  const next=B.bakeLayout(ctx.atlas,options,moved,manifest.ownership);
  const on=(p,id)=>p.slots[id].assignments.find(a=>a.chart===0);
  const newcomer=on(next,'member-6'),evicted=on(first,'member-1');
  assert.equal(newcomer.bank*2+newcomer.channel,evicted.bank*2+evicted.channel,'newcomer takes the middle slot of the evicted light');
  const changed=firstLights.filter(l=>first.entries[l.device].key!==next.entries[l.device].key).map(l=>l.device).sort();
  assert.deepEqual(changed,['member-1','member-6']);
  for(const id of survivors) {
    assert.deepEqual([on(first,id).bank,on(first,id).channel],[on(next,id).bank,on(next,id).channel]);
    assert.deepEqual(next.entries[id],first.entries[id],'surviving light retains its complete entry');
  }
  const rebaker=make(moved);
  assert.deepEqual((await rebaker.staleLights()).sort(),changed);
  assert.deepEqual(await finish(rebaker),changed,'a new baker adopts persisted sticky slots');
  const published=server.manifests.get(ctx.atlas.key),reloaded=B.bakeLayout(ctx.atlas,options,moved,published.ownership);
  assert.deepEqual(reloaded.entries,next.entries,'a new page derives exactly the persisted owners');
  assert.deepEqual(await make(moved).staleLights(),[],'reload does not re-bake the five survivors');
  for(const id of survivors) {
    const after=await pixels(next,id);assert.ok(oldPixels.get(id).every((x,i)=>Math.abs(x-after[i])<=2),'unchanged slot texels survive the eviction');
  }
  for(const id of firstLights.map(l=>l.device).filter(id=>!changed.includes(id))) assert.deepEqual(published.lights[id],manifest.lights[id]);
  const {decodeSlots}=await import(file('static/twin/bake/slots.js'));
  assert.throws(()=>decodeSlots({...published.ownership,charts:-1},ctx.atlas.room.charts.length),/ownership history/);
  assert.throws(()=>decodeSlots({version:1,charts:1,lights:{bad:btoa(String.fromCharCode(15))}},1),/ownership history/);
  FILL.value=.08;
});
await check('shared_channel_uses_the_correct_light_tint_at_each_chart', () => {
  const lights=[{device:'near'},{device:'far'}], charts=[0,1].map(id=>({id,page:0,
    rect:{x:id*8,y:0,w:4,h:4},sourceRegion:{x:0,y:0,w:4,h:4}}));
  const packed={banks:[{charts}],slots:{near:{assignments:[{chart:0,bank:0,channel:0},{chart:1,bank:0,channel:1}]},
    far:{assignments:[{chart:1,bank:0,channel:0},{chart:0,bank:0,channel:1}]}}};
  const u=chartLightmapUniforms(2,packed,lights,128,[[0]]);
  const tint=chart=>{const [x,y]=chartAddress(chart,0,1),owner=u.lmRegions.value.image.data[(y*1024+x)*4+3]%4096;
    return [...u.lmTints.value.image.data.slice((owner-1)*4,(owner-1)*4+3)];};
  setLightTint(u,0,0,[255,0,0],1);setLightTint(u,0,1,[0,0,255],.5);
  assert.deepEqual(tint(0),[1,0,0]); assert.deepEqual(tint(1),[0,0,.5]);
  const secondTint=chart=>{const [x,y]=chartAddress(chart,0,1),owner=Math.floor(u.lmRegions.value.image.data[(y*1024+x)*4+3]/4096);
    return [...u.lmTints.value.image.data.slice((owner-1)*4,(owner-1)*4+3)];};
  assert.deepEqual(secondTint(0),[0,0,.5]);assert.deepEqual(secondTint(1),[1,0,0]);
  const material=new THREE.MeshStandardMaterial(), texture=new THREE.DataArrayTexture(new Uint8Array(16),2,2,1);
  patchLightmaps([material],{banks:[texture]},u);
  const version=material.version,key=material.customProgramCacheKey();
  setLightTint(u,0,0,[255,0,0],0);
  assert.deepEqual(tint(0),[0,0,0]);assert.deepEqual(tint(1),[0,0,.5]);
  assert.equal(material.version,version);assert.equal(material.customProgramCacheKey(),key);
  const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};
  material.onBeforeCompile(shader,{});
  assert.ok(shader.vertexShader.includes('vLmRoom = lmRoom'));
  assert.ok(shader.fragmentShader.includes('lmOwnerTint(mod(region0.w, 4096.0))'));
});
await check('bounce_uses_each_rooms_direct_energy_and_respects_range_mask', () => {
  const pixels=new Uint8Array(8*8*4), material={color:new THREE.Color(1,1,1)};
  const charts=[0,1,2].map(room=>({room,outdoor:room===2,mesh:{material},rect:{x:room*2,y:0,w:2,h:2}}));
  for(const c of charts) for(let y=0;y<2;y++) for(let x=c.rect.x;x<c.rect.x+2;x++) {
    const p=(y*8+x)*4; pixels[p]=c.room===1?0:100; pixels[p+3]=255;
  }
  pixels[4]=0; pixels[7]=0; // Out of range, inside the same receiving chart.
  addRoomBounce(pixels,charts,8);
  assert.ok(pixels[0]>100); assert.equal(pixels[4],0);
  assert.equal(pixels[2*4],0,'no direct energy means no room fill');
  assert.equal(pixels[4*4],100,'outdoor shadows receive no uniform bounce');
});
await check('room_bounce_is_shared_across_sparse_pages', () => {
  const a=new Uint8Array([120,0,0,255]),b=new Uint8Array([0,0,0,255]);
  const chart={room:0,mesh:{material:{color:new THREE.Color(1,1,1)}},rect:{x:0,y:0,w:1,h:1}};
  addRoomBounceAcrossPages([{bytes:a,charts:[chart]},{bytes:b,charts:[chart]}],1);
  assert.ok(a[0]>120&&b[0]>0,'room energy crosses page boundaries without crossing room boundaries');
});
console.log(`${passed}/${ran} passed`); process.exit(passed===ran?0:1);
"""

# The parent needs the page's Three aliases to generate the scene. Its worker
# deliberately runs in a separate isolate without those resolver hooks.
MEASURE_PREFIX = B.DRIVER[:B.DRIVER.index('const require =')]
MEASURE_PREFIX += r"""
const gen = await import(file('static/twin/twin_generator.js'));
const B = await import(file('static/twin/bake/baker.js'));
const { atlasJob, buffers, applyAtlas } = await import(file('static/twin/bake/atlas_transport.js'));
const { Worker } = await import('node:worker_threads');
const { resourceUsage } = await import('node:process');
"""

MEASURE = r"""
const out=gen.buildTwin(job.plan,job.kit,'high'); await out.ready;
const originals=new Map();out.root.traverse(m=>{if(m.isMesh&&m.userData.merged&&!m.layers.isEnabled(31))
  originals.set(m,(m.geometry.index?.count||m.geometry.attributes.position.count)/3);});
const layout={room:{density:8,page:2048,gutter:2}}, start=performance.now(), memory=[process.memoryUsage()];
const task=atlasJob(out.root,job.plan,layout), jobMs=performance.now()-start;
const bootstrap=`import { parentPort } from 'node:worker_threads';
  import { resourceUsage } from 'node:process';
  import { registerHooks } from 'node:module';
  registerHooks({resolve(spec,ctx,next){
    if(!spec.startsWith('.')&&!spec.startsWith('file:')&&!spec.startsWith('node:'))
      throw new Error('Module worker cannot use the page import map: '+spec);
    return next(spec,ctx);
  }});
  let start;
  globalThis.self={postMessage(data,transfer){parentPort.postMessage({...data,
    metrics:{workerMs:performance.now()-start,memory:process.memoryUsage(),peakRss:resourceUsage().maxRSS*1024}},transfer);}};
  await import(${JSON.stringify(file('static/twin/bake/atlas_worker.js'))});
  parentPort.on('message',data=>{start=performance.now();self.onmessage({data});});`;
const worker=new Worker(new URL('data:text/javascript,'+encodeURIComponent(bootstrap)),
  {type:'module',execArgv:[]});
let data;
try {
  data=await new Promise((resolve,reject)=>{
    worker.once('error',reject);worker.once('message',resolve);
    worker.postMessage(task,buffers(task.meshes));
  });
  assert.ok(!data.error,data.error);
} finally {await worker.terminate();}
memory.push(data.metrics.memory);
const applyStart=performance.now(), atlas=applyAtlas(data,out.root,layout), applyMs=performance.now()-applyStart;
data.geometries=null;
const pool=job.plan.buildings.find(b=>b.id==='pool-house');
const at=(b,x,y,z)=>{const a=(b.rotation||0)*Math.PI/180,p=b.position||[0,0];
  return [p[0]+Math.cos(a)*x-Math.sin(a)*y,p[1]+Math.sin(a)*x+Math.cos(a)*y,(b.base||0)+z];};
const ids=['room:5d7de10ca48340ae85c407d22337c6f7','room:f94386f3da524031b4530a0847d7bc75','room:aa3a66806205434ca794927a6d66dd22'];
// The live harness's four placed lamps, using its floor/ceiling host UVs.
const hostAt=(room,u,v,z)=>{const r=pool.rooms.find(r=>r.id===room),xs=r.polygon.map(p=>p[0]),ys=r.polygon.map(p=>p[1]);
  return at(pool,Math.min(...xs)+(Math.max(...xs)-Math.min(...xs))*u,
    Math.min(...ys)+(Math.max(...ys)-Math.min(...ys))*v,z);};
const lamps=[[ids[0],.3,.3,10],[ids[0],.4,.3,0],[ids[1],.5,.5,0],[ids[2],.5,.5,0]].map(([room,u,v,z],i)=>
  ({device:'fixture-'+i,building:pool.id,level:'L1',room,at:hostAt(room,u,v,z)}));
const main=job.plan.buildings.find(b=>b.id==='main-house');
for(const r of main.rooms.filter(r=>r.polygon?.length>=3).slice(0,3)) for(let n=0;n<2;n++) {
  const xs=r.polygon.map(p=>p[0]),ys=r.polygon.map(p=>p[1]),l=main.levels.find(l=>l.id===r.level);
  lamps.push({device:'fixture-'+lamps.length,building:main.id,level:r.level,room:r.id,
    at:at(main,(Math.min(...xs)+Math.max(...xs))/2+n,(Math.min(...ys)+Math.max(...ys))/2,l.elevation+l.ceiling)});
}
const count=job.count,list=lamps.slice(0,Math.min(count,10));
if(count===40) for(let n=10;n<40;n++) list.push({...lamps[n%10],device:'stress-'+n});
const packStart=performance.now(),p=B.bakeLayout(atlas,layout,list),layoutMs=performance.now()-packStart,
  totalMs=performance.now()-start;
memory.push(process.memoryUsage());
assert.ok(totalMs<=(count===40?10000:5000),`${count} lights: full atlas, reach, ranking and packing took ${totalMs.toFixed(0)} ms`);
assert.equal(p.banks.length,3,'physical layouts always have three banks');
const peakRss=Math.max(resourceUsage().maxRSS*1024,data.metrics.peakRss,...memory.map(m=>m.rss));
// Includes scene generation and both isolates, rather than only retained atlas
// arrays. Bound the whole cold process well below the old >1 GiB growth.
assert.ok(peakRss<640*1024*1024,'cold atlas process stays under 640 MiB RSS: '+peakRss);
const { applyChartIndices,chartLightmapUniforms } = await import(file('static/twin/bake/lightmap_material.js'));
applyChartIndices(atlas);
let geometryBytes=0;out.root.traverse(m=>{if(m.isMesh&&m.userData.merged&&!m.layers.isEnabled(31)) {
  for(const a of Object.values(m.geometry.attributes)) geometryBytes+=a.array.byteLength;
  geometryBytes+=m.geometry.index?.array.byteLength||0;
}});
const held=p.banks.map((b,i)=>new Set(Object.values(p.entries).flatMap(e=>e.pages).filter(n=>n>=p.offsets[i]&&n<p.offsets[i]+b.pages)).size),
  pages=held.reduce((a,b)=>a+b,0),placeholders=held.filter(n=>!n).length*48;
const pageBytes=rgba=>{let bytes=0;for(let n=2048;n>=1;n=Math.floor(n/2)) bytes+=rgba?n*n*4:Math.ceil(n/4)**2*16;return bytes;};
const u=chartLightmapUniforms(atlas.room.charts.length,p,list,2048,p.banks.map(b=>Array.from({length:b.pages},(_,i)=>i))),
  uniforms=u.lmRegions.value.image.data.byteLength+u.lmTints.value.image.data.byteLength;
const positivelyLit=Object.values(p.slots).filter(s=>s.assignments.some(a=>a.score>0)).length;
const manifestBytes=new TextEncoder().encode(JSON.stringify({pages:p.pages,lights:p.entries,ownership:p.ownership,densities:p.densities,formats:Array(p.pages).fill('ktx2')})).length;
assert.ok(manifestBytes<=1024*1024,'sticky ownership fits the existing 1 MiB manifest limit');
if(count===40) assert.ok(positivelyLit>=38,'at least 38 stress lights own a positive-contribution chart: '+positivelyLit);
console.log(JSON.stringify({lights:count,atlasKey:atlas.key,charts:atlas.room.charts.length,basePages:atlas.room.pages,
  inputTriangles:[...originals.values()].reduce((a,b)=>a+b,0),
  atlasTriangles:[...originals.keys()].reduce((sum,m)=>sum+(m.geometry.index?.count||m.geometry.attributes.position.count)/3,0),
  jobMs,workerMs:data.metrics.workerMs,applyMs,layoutMs,totalMs,peakRss,manifestBytes,
  sampledHeapUsed:Math.max(...memory.map(m=>m.heapUsed)),sampledArrayBuffers:Math.max(...memory.map(m=>m.arrayBuffers)),
  baked:Object.keys(p.entries).length,fallback:p.fallback.length,banks:p.banks.length,reservedPages:p.pages,heldPages:held,geometryBytes,
  positivelyLit,worstDroppedFraction:p.ranking.worstDroppedFraction,droppedCharts:p.ranking.droppedCharts,
  compressedTextureBytes:pages*pageBytes(false)+placeholders,compressedGpuBytes:geometryBytes+pages*pageBytes(false)+placeholders+uniforms,
  rgbaGpuBytes:geometryBytes+pages*pageBytes(true)+placeholders+uniforms}));
u.lmRegions.value.dispose();u.lmTints.value.dispose();
"""



HARNESS_DRIVER = B.DRIVER[:B.DRIVER.index('// --- the house, the lights')]
HARNESS_DRIVER += r"""
const out=gen.buildTwin(job.plan,job.kit,'high');await out.ready;
const atlas=buildAtlas(out.root,job.plan,job.layout),atlasKey=atlas.key;
"""
HARNESS_DRIVER += MEASURE[MEASURE.index('const pool='):MEASURE.index('const main=')]
HARNESS_DRIVER += r"""
const names=['dev-k-ceiling','dev-k-lamp','dev-hall-light','dev-changing-light'];
lamps.forEach((l,i)=>l.device=names[i]);
const own=(p,id)=>JSON.stringify((p.slots[id]?.assignments||[]).map(a=>[a.chartKey,a.bank,a.channel]));
const predicted=(before,after,moved)=>names.filter(id=>id===moved || own(before,id)!==own(after,id)).sort();
const renderer=fakeRenderer(),view={plan:job.plan,scene:out.root,tier:'high'},server=fakeServer();
const codec={encode:async j=>B.encodePage(E,j),decode:async bytes=>B.decodePage(T,bytes)};
const make=list=>B.createBaker(view,{atlas,layout:job.layout,lights:list,renderer,api:server.api,codec});
async function bakeAll(baker) {
  const baked=[];
  for(let i=0;i<5;i++){const id=await baker.bakeNext();if(!id)return baked.sort();baked.push(id);}
  throw new Error('baker did not finish');
}
let lights=lamps,previous=B.bakeLayout(atlas,job.layout,lights);
assert.deepEqual(await bakeAll(make(lights)),names.slice().sort());
for(const [device,at] of [['dev-k-ceiling',hostAt(ids[0],.35,.3,10)],['dev-hall-light',hostAt(ids[1],.25,.3,0)]]) {
  const nextLights=lights.map(l=>l.device===device?{...l,at}:l),next=B.bakeLayout(atlas,job.layout,nextLights,server.manifests.get(atlasKey).ownership);
  const expected=[device],before=structuredClone(server.manifests.get(atlasKey));
  assert.deepEqual(predicted(previous,next,device),expected,'movement changes no other light ownership');
  const moving=new Set(previous.slots[device].assignments.map(a=>a.chart));
  const shared=Object.fromEntries(names.filter(id=>id!==device).map(id=>[id,
    previous.slots[id].assignments.filter(a=>moving.has(a.chart)).length]));
  if(device==='dev-k-ceiling') {
    assert.ok(shared['dev-hall-light']>0&&shared['dev-changing-light']>0,'harness Hall and Changing really share ceiling receiving charts');
  }
  for(const id of names.filter(id=>!expected.includes(id))) {
    assert.equal(next.entries[id].key,previous.entries[id].key,'untouched ownership keeps its key: '+id);
    assert.equal(next.entries[id].location,previous.entries[id].location,'untouched ownership keeps its addresses: '+id);
  }
  const baker=make(nextLights);
  assert.deepEqual((await baker.staleLights()).sort(),expected,'staleness is predicted from ownership, not from production keys');
  const actual=await bakeAll(baker);
  assert.deepEqual(actual,expected,'actual bake calls equal moved + changed ownership');
  assert.equal(atlas.key,atlasKey,'movement leaves the geometry namespace unchanged');
  for(const id of names.filter(id=>!expected.includes(id)))
    assert.deepEqual(server.manifests.get(atlasKey).lights[id],before.lights[id],'untouched stored entry stays identical');
  console.log(JSON.stringify({moved:device,sharedCharts:shared,predicted:expected,rebaked:actual}));
  lights=nextLights;previous=next;
}
console.log('  ok   harness_moved_lights_rebake_only_the_moved_light');
console.log('1/1 passed');process.exit(0);
"""

def harness_house():
    """Use the live harness's seed, migration, room naming and linked model.

    No server or browser is started; B has already isolated the data directory.
    """
    import house_twin_live_harness as H
    B.twin_store.push_round(H._names(H.H.household_plan()), 'build')
    model = B.twin_store.current_model()
    H._linked(model)
    B.twin_store.update_model(lambda _before: model, 'edit', note='node atlas timing fixture')
    return B.twin_store.current()


def run():
    with tempfile.TemporaryDirectory(prefix='twin_reach_') as directory:
        driver = pathlib.Path(directory) / 'reach.mjs'
        job = pathlib.Path(directory) / 'job.json'
        payload = {'root': pathlib.Path(B.ROOT).as_posix()}
        if '--measure' not in sys.argv:
            driver.write_text(DRIVER, encoding='utf-8')
            job.write_text(json.dumps(payload), encoding='utf-8')
            result = subprocess.run([B.node(), str(driver), str(job)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=280)
            print(result.stdout, end='')
            if result.returncode:
                print(result.stderr[-4000:], end='')
                return result.returncode
        payload.update(plan=harness_house(), kit={**B.tl.kit('modern_farmhouse'), 'manifest': {}})
        driver.write_text(MEASURE_PREFIX + MEASURE, encoding='utf-8')
        results = []
        # Each row has a fresh Node process, worker and uncached reach/ranking.
        for count in ([4, 10, 40] if '--measure' in sys.argv else [10]):
            job.write_text(json.dumps({**payload, 'count': count}), encoding='utf-8')
            result = subprocess.run([B.node(), str(driver), str(job)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=60)
            if result.returncode:
                print(result.stdout + result.stderr)
                return result.returncode
            results.append(json.loads(result.stdout))
        if '--measure' in sys.argv:
            print(json.dumps(results, indent=2))
        else:
            print(f"  ok   browser_like_worker_and_cold_ten_light_timing ({results[0]['totalMs']:.0f} ms)")
            job.write_text(json.dumps({**payload, 'layout': {'room': {'density': 1, 'page': 512, 'gutter': 2}}}), encoding='utf-8')
            driver.write_text(HARNESS_DRIVER, encoding='utf-8')
            result = subprocess.run([B.node(), str(driver), str(job)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=280)
            print(result.stdout, end='')
            if result.returncode:
                print(result.stderr[-4000:], end='')
                return result.returncode
            print('18/18 passed (16 reach checks + worker/timing + harness rebake integration)')
        return 0


if __name__ == '__main__':
    sys.exit(run())
