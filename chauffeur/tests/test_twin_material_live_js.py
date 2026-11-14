"""Catalogue updates through real mounted views, renderer caches and bake reach."""
import json
import sys
from pathlib import Path
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
globalThis.buildCalls=0;
registerHooks({resolve(spec,ctx,next){
 if(spec==='./twin_generator.js'&&ctx.parentURL.endsWith('/twin_view.js'))return {url:data(`export * from '${file('static/twin/twin_generator.js')}';import {buildTwin as build} from '${file('static/twin/twin_generator.js')}';export function buildTwin(...args){globalThis.buildCalls++;if(globalThis.failBuild)throw Error('injected builder failure');return build(...args);}`),shortCircuit:true};
 if(spec==='./lightmap_material.js'&&ctx.parentURL.endsWith('/bake/runtime.js'))return {url:data(`export * from '${file('static/twin/bake/lightmap_material.js')}';import {loadAtlas as load} from '${file('static/twin/bake/lightmap_material.js')}';export function loadAtlas(...args){return globalThis.testAtlas?globalThis.testAtlas(...args):load(...args);}`),shortCircuit:true};
 return next(spec,ctx);
}});
const THREE = await import('three');
const lib = await import(file('static/twin/twin_library.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {yardPartKeys,YARD_PARTS} = await import(file('static/twin/twin_yard.js'));
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
const loaded=[];
THREE.TextureLoader.prototype.load=function(url,done) {
 const t=new THREE.Texture({width:32,height:32,url});t.name=url;loaded.push(t);queueMicrotask(()=>done(t));return t;
};
const id='material-live', other='material-other';
const record=(revision=1,tint='#123456',file='aaaaaaaaaaaa.jpg')=>({id,revision,source:'user',params:{tint},maps:{base_color:'maps/'+file}});
const entry=r=>({kind:'material',household:true,revision:r.revision,params:r.params,maps:Object.fromEntries(Object.entries(r.maps).map(([s,p])=>[s,`materials/${r.id}/${p}`]))});
let current=record(),reads=0;
const api=async path=>{reads++;assert.equal(path,'api/house/twin/materials/manifest');return new Response(JSON.stringify({revision:current.revision,entries:{[id]:entry(current),[other]:entry({...record(),id:other})}}));};
const kit=()=>({materials:{siding:{id},trim:{id:other}},manifest:{[id]:entry(record()),[other]:entry({...record(),id:other})}});
const plan=()=>{const p=structuredClone(input.plan);p.materials={};p.buildings[0].materials={};p.site={lot:[[0,0],[6,0],[6,6],[0,6]],planting:[]};return p;};
async function mount(k,editor=true){const host=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(host);}return mountTwin(host,{plan:plan(),kit:k,tier:'low',bake:false});}
const materials=v=>{const s=new Set();v.scene.traverse(o=>{for(const m of o.material?[].concat(o.material):[])s.add(m);});return [...s];};
const siding=v=>materials(v).find(m=>m.name==='siding');
const settle=async()=>{for(let n=0;n<25;n++)await new Promise(r=>setTimeout(r,5));};
await test('new_map_url_after_replace',async()=>{
 current=record();const k=kit(),v=await mount(k);let watch;
 try {const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));watch=watchMaterialCatalogue(v,{api});await watch.check();
  assert.ok(siding(v).map.image.url.endsWith('aaaaaaaaaaaa.jpg'));
  current=record(2,'#123456','bbbbbbbbbbbb.jpg');await watch.check();
  assert.ok(siding(v).map.image.url.endsWith('bbbbbbbbbbbb.jpg'));assert.equal(k.manifest[id].revision,2);
 }finally{watch?.stop();v.dispose();}
});
await test('tint_edit_reaches_two_views',async()=>{
 current=record();const k=kit(),a=await mount(k),b=await mount(k,false);const watchers=[];
 try {const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));
  watchers.push(watchMaterialCatalogue(a,{api}),watchMaterialCatalogue(b,{api}));await Promise.all(watchers.map(w=>w.check()));
  current=record(3,'#abcdef');document.dispatchEvent(new CustomEvent('chf-server-update'));await settle();
  assert.equal(siding(a).color.getHexString(),'abcdef');assert.equal(siding(b).color.getHexString(),'abcdef');
 }finally{watchers.forEach(w=>w.stop());a.dispose();b.dispose();}
});
await test('unrelated_materials_untouched',async()=>{
 current=record();const v=await mount(kit());let watch;
 try {const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));watch=watchMaterialCatalogue(v,{api});await watch.check();
  const trim=materials(v).find(m=>m.name==='trim');let disposed=0;trim.addEventListener('dispose',()=>disposed++);
  current=record(4,'#fedcba');await watch.check();assert.ok(materials(v).includes(trim));assert.equal(disposed,0);
  const before=siding(v);await watch.check();assert.equal(siding(v),before);
 }finally{watch?.stop();v.dispose();}
});
await test('revision_updates_materials_in_place',async()=>{
 for(const editor of [true,false]) {
  current=record();const k=kit(),v=await mount(k,editor);let watch;
  try {const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));watch=watchMaterialCatalogue(v,{api});await watch.check();
   const mesh=v.scene.getObjectByProperty('material',siding(v)),m=mesh.material,geometry=mesh.geometry,levels=v.levels,calls=buildCalls;
   current=record(20,'#abc123','eeeeeeeeeeee.jpg');await watch.check();
   assert.equal(buildCalls,calls,'no buildTwin call');assert.equal(mesh.material,m);assert.equal(mesh.geometry,geometry);assert.equal(v.levels,levels);
   assert.equal(m.color.getHexString(),'abc123');assert.ok(m.map.image.url.endsWith('eeeeeeeeeeee.jpg'));
   await v.refreshMaterials([id]);assert.equal(mesh.material,m);assert.equal(buildCalls,calls,'current revision is skipped');
  }finally{watch?.stop();v.dispose();}
 }
});
await test('changed_cutout_pattern_falls_back_with_a_reason',async()=>{
 const k=kit(),v=await mount(k),warn=console.warn,warnings=[];console.warn=(...args)=>warnings.push(args.join(' '));
 try {const m=siding(v),calls=buildCalls;k.materials.siding.pattern='lattice';m.userData.materialRef.pattern='lattice';k.manifest[id]=entry(record(31));
  await v.refreshMaterials([id]);assert.equal(buildCalls,calls+1);assert.equal(siding(v).alphaTest,.5);
  assert.ok(warnings.some(s=>s.includes('alpha/cutout pattern')));
 }finally{console.warn=warn;v.dispose();}
});
await test('building_roles_revalidate_revision_with_retained_cache',async()=>{
 const k=kit(),p=plan(),first=buildTwin(p,k,'low');await first.ready;
 const old=[...first.materials.values()].find(m=>m.name==='siding'),trim=[...first.materials.values()].find(m=>m.name==='trim');
 k.manifest[id]=entry(record(5,'#aabbcc'));
 const next=buildTwin(p,k,'low',{reuseMaterials:first.materials});await next.ready;
 assert.notEqual([...next.materials.values()].find(m=>m.name==='siding'),old);
 assert.ok([...next.materials.values()].includes(trim));
 for(const m of new Set([...first.materials.values(),...next.materials.values()]))m.dispose();
 first.root.traverse(o=>o.geometry?.dispose());next.root.traverse(o=>o.geometry?.dispose());
});
await test('material_refresh_waits_for_an_inflight_editor_rebuild',async()=>{
 const k=kit(),v=await mount(k);
 try {const next=structuredClone(v.plan);next.buildings[0].position=[11,12];
  const editing=v.rebuild(next);k.manifest[id]=entry(record(12,'#556677'));
  const refreshing=v.refreshMaterials([id]);await Promise.all([editing,refreshing]);
  assert.deepEqual(v.plan.buildings[0].position,[11,12],'catalogue refresh must retain the edit being adopted');
  assert.equal(siding(v).color.getHexString(),'556677');
 }finally{v.dispose();}
});
await test('yard_revision_changes_only_parts_reading_role_or_slot',()=>{
 for(const slot of [false,true]) {const p=plan(),k=kit();k.materials.fence={id};
  p.site.fence=[{polyline:[[0,0],[3,0]],height:3,...(slot?{materials:{boards:{id}}}:{})}];
  if(slot)k.materials.fence={color:'#ffffff'};
  const before=yardPartKeys(p,k,'low');k.manifest[id]=entry(record(6));const after=yardPartKeys(p,k,'low');
  assert.deepEqual(YARD_PARTS.filter(n=>before[n]!==after[n]),['fences']);
 }
});
await test('retired_map_urls_are_evicted_and_live_clones_survive',async()=>{
 const k=kit(),m=lib.kitMaterial('siding',k,'low');await m.userData.ready;const map=m.map,master=loaded.at(-1);
 let freed=0;master.addEventListener('dispose',()=>freed++);
 k.manifest[id]=entry(record(7,'#123456','cccccccccccc.jpg'));
 assert.equal(typeof lib.refreshMaterials,'function');lib.refreshMaterials([id]);
 assert.equal(map.image.url.endsWith('aaaaaaaaaaaa.jpg'),true,'an existing owner retains its pixels');
 m.dispose();await settle();assert.equal(freed,1,'retired master disposed once');
 const count=loaded.length;const again=lib.kitMaterial('siding',kit(),'low');await again.userData.ready;
 assert.equal(loaded.length,count+1,'old content URL is fetched again after eviction');again.dispose();
});
await test('retired_inflight_failure_cannot_evict_a_new_request_for_the_same_url',async()=>{
 const load=THREE.TextureLoader.prototype.load,pending=[];const freshKit=kit();
 freshKit.manifest[id]=entry(record(1,'#123456','dddddddddddd.jpg'));
 THREE.TextureLoader.prototype.load=function(url,done,progress,error){const t=new THREE.Texture({width:16,height:16,url});pending.push({done,error,t});return t;};
 const a=lib.kitMaterial('siding',freshKit,'low');lib.refreshMaterials([id]);
 const b=lib.kitMaterial('siding',freshKit,'low');
 try {assert.equal(pending.length,2);pending[0].error(Error('old request failed'));await a.userData.ready;
  const c=lib.kitMaterial('siding',freshKit,'low');
  try {assert.equal(pending.length,2,'new tier/master cache survives retired failure');pending[1].done(pending[1].t);await Promise.all([b.userData.ready,c.userData.ready]);}
  finally{c.dispose();}
 }finally{a.dispose();b.dispose();THREE.TextureLoader.prototype.load=load;}
});
await test('bake_marked_stale_on_material_revision',async()=>{
 const {reachLights,invalidateMaterialReach}=await import(file('static/twin/bake/reach.js'));
 assert.equal(typeof invalidateMaterialReach,'function');
 for(const heightfield of [false,true]) {
  const m=lib.kitMaterial('siding',kit(),'low');await m.userData.ready;
  const mesh=new THREE.Mesh(new THREE.PlaneGeometry(4,4).rotateX(-Math.PI/2),m);mesh.updateMatrixWorld(true);
  const c={id:0,key:'chart',room:0,mesh,faces:[0,1],density:1,heightfield,field:[-2,-2,2,2]};
  const layout={plan:{site:{}},charts:[c]},lights=[{device:'yard',at:[0,0,2],absolute:true,range:18}];
  const old=reachLights(layout,lights)[0].reach;
  assert.equal(invalidateMaterialReach(layout,[other]),false);
  lib.applyMaterialParams(m,entry(record(8)),{id},'siding','low');await m.userData.ready;
  assert.equal(invalidateMaterialReach(layout,[id]),true);
  assert.notEqual(reachLights(layout,lights)[0].reach,old,'revision alone changes indoor and outdoor freshness');m.dispose();
 }
});
await test('bake_proxy_material_revision_invalidates_its_host',async()=>{
 const {reachLights,invalidateMaterialReach}=await import(file('static/twin/bake/reach.js'));
 const m=new THREE.MeshStandardMaterial(),proxyMaterial=lib.kitMaterial('trim',{...kit(),materials:{trim:{id}}},'low');await proxyMaterial.userData.ready;
 const mesh=new THREE.Mesh(new THREE.PlaneGeometry(4,4).rotateX(-Math.PI/2),m),proxy=new THREE.Mesh(mesh.geometry,proxyMaterial);mesh.updateMatrixWorld(true);
 const layout={plan:{site:{}},charts:[{id:0,key:'host',room:0,mesh,faces:[0,1],density:1,proxies:[{mesh:proxy,faces:[0]}]}]};
 const lights=[{device:'yard',at:[0,0,2],absolute:true,range:18}],before=reachLights(layout,lights)[0].reach;
 proxyMaterial.userData.materialRevision++;
 assert.equal(invalidateMaterialReach(layout,[id]),true);assert.notEqual(reachLights(layout,lights)[0].reach,before);
 proxyMaterial.dispose();m.dispose();mesh.geometry.dispose();
});
await test('watcher_focus_poll_failure_retry_and_stop',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));
 const saved=globalThis.setInterval,cleared=globalThis.clearInterval;let poll,period,calls=0;
 globalThis.setInterval=(fn,ms)=>{poll=fn;period=ms;return 987;};globalThis.clearInterval=()=>{};
 const v=await mount(kit());let w;
 try {w=watchMaterialCatalogue(v,{api:async p=>{calls++;if(calls===1)throw new TypeError('Failed to fetch');return api(p);}});await w.check();
  assert.equal(period,60000);current=record(9,'#778899');window.dispatchEvent(new Event('focus'));await settle();assert.equal(siding(v).color.getHexString(),'778899');
  current=record(10,'#8899aa');await poll();await settle();assert.equal(siding(v).color.getHexString(),'8899aa');
  w.stop();const n=calls;window.dispatchEvent(new Event('focus'));document.dispatchEvent(new CustomEvent('chf-server-update'));await settle();assert.equal(calls,n);
 }finally{w?.stop();v.dispose();globalThis.setInterval=saved;globalThis.clearInterval=cleared;}
});
await test('busy_signal_runs_again_after_the_inflight_read',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));current=record();const v=await mount(kit());let w,release,calls=0;
 try {w=watchMaterialCatalogue(v,{api:async p=>{calls++;if(calls===1){const snapshot=await api(p);return new Promise(r=>release=()=>r(snapshot));}return api(p);}});
  while(!release)await Promise.resolve();current=record(21,'#aabbdd');const checking=w.check();release();await checking;await settle();
  assert.ok(calls>=2);assert.equal(siding(v).color.getHexString(),'aabbdd');
 }finally{w?.stop();v.dispose();}
});
await test('failed_refresh_does_not_wedge_watcher',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));current=record();const v=await mount(kit());let w;const errors=[],log=console.error,refresh=v.refreshMaterials;
 console.error=(...args)=>errors.push(args);
 try {w=watchMaterialCatalogue(v,{api});await w.check();let once=true;v.refreshMaterials=async ids=>{if(once){once=false;throw Error('refresh broke');}return refresh(ids);};
  current=record(22,'#aabbcc');await w.check();assert.ok(errors.some(args=>args.some(e=>String(e).includes('refresh broke'))));
  await w.check();assert.equal(siding(v).color.getHexString(),'aabbcc');
  globalThis.failBuild=true;await assert.rejects(v.rebuild(v.plan),/injected builder failure/);assert.equal(v.ready,true,'failed rebuild restores readiness');
  globalThis.failBuild=false;current=record(23,'#ccddee');await w.check();assert.equal(siding(v).color.getHexString(),'ccddee');
 }finally{globalThis.failBuild=false;console.error=log;w?.stop();v.dispose();}
});
await test('refused_read_stops_polling_and_stream',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));
 const native=globalThis.EventSource,interval=globalThis.setInterval,clear=globalThis.clearInterval,streams=[];let poll,clears=0;
 globalThis.EventSource=class{constructor(){streams.push(this);}close(){this.closed=true;}};
 globalThis.setInterval=fn=>{poll=fn;return 1;};globalThis.clearInterval=()=>clears++;
 const v=await mount(kit());v.materialWatcher.stop();let w,calls=0;
 try {w=watchMaterialCatalogue(v,{api:async()=>{calls++;return new Response('',{status:403});}});await w.check();const n=calls;
  await poll();await w.check();window.dispatchEvent(new Event('focus'));await settle();assert.equal(calls,n);assert.ok(clears);assert.equal(streams.at(-1).closed,true);
 }finally{w?.stop();v.dispose();globalThis.EventSource=native;globalThis.setInterval=interval;globalThis.clearInterval=clear;}
});
await test('panel_uses_forwarded_push_without_another_stream',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));const native=globalThis.EventSource;let opened=0;
 globalThis.EventSource=class{constructor(){opened++;}close(){}};current=record();const v=await mount(kit());v.materialWatcher.stop();location.search='?panel=true&kiosk=true';let w;
 try {const before=opened;w=watchMaterialCatalogue(v,{api});await w.check();assert.equal(opened,before);
  current=record(24,'#1122aa');document.dispatchEvent(new CustomEvent('chf-server-update'));await settle();assert.equal(siding(v).color.getHexString(),'1122aa');
 }finally{w?.stop();v.dispose();location.search='?test=1';globalThis.EventSource=native;}
});
await test('ordinary_editor_receives_existing_server_stream_and_closes_it',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));
 const native=globalThis.EventSource,streams=[];globalThis.EventSource=class {
  constructor(url){this.url=url;streams.push(this);}close(){this.closed=true;}
 };
 window.chfAuthUrl=url=>url+'?person=token';current=record();const v=await mount(kit());let w;
 try {w=watchMaterialCatalogue(v,{api});await w.check();const stream=streams.at(-1);assert.ok(stream,'ordinary editor has an update subscription');
  assert.equal(stream.url,'/api/stream?person=token');current=record(11,'#667788');const before=reads;
  for(let i=0;i<4;i++)stream.onmessage({data:'update'});await settle();assert.equal(reads,before,'stream is debounced');
  await new Promise(r=>setTimeout(r,1550));await settle();
  assert.equal(siding(v).color.getHexString(),'667788');w.stop();assert.equal(stream.closed,true);
 }finally{w?.stop();v.dispose();globalThis.EventSource=native;delete window.chfAuthUrl;}
});
await test('mounted_bake_chain_stales_only_lights_reaching_the_changed_material',async()=>{
 const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
 const {bakeLayout}=await import(file('static/twin/bake/baker.js'));
 const nativeFetch=globalThis.fetch,nativeWorker=globalThis.Worker;let v,publication;
 const lights=[{device:'used',building:'one',level:'L1',room:'r',at:[2,2,6]},
  {device:'unrelated',building:'two',level:'L1',room:'r',at:[102,2,6]}];
 const p=plan();p.site={};p.buildings=['one','two'].map((building,index)=>({...p.buildings[0],id:building,
  position:[index*100,0],rotation:0,materials:{},walls:[],openings:[],anchors:[],furniture:[],roof:{sections:[]},
  levels:[{id:'L1',elevation:0,ceiling:8,outline:[[0,0],[4,0],[4,4],[0,4]]}],
  rooms:[{id:'r',level:'L1',state:'settled',polygon:[[0,0],[4,0],[4,4],[0,4]],floor_material:{id:index?other:id}}]}));
 current=record();const k=kit();
 // Real atlas and packing; only worker transport and compressed pixels are doubled.
 globalThis.testAtlas=async(root,plan,layout)=>{
  layout.room.page=64;layout.room.density=1;const atlas=buildAtlas(root,plan,layout);
  const packed=bakeLayout(atlas,layout,lights);publication={lights:packed.entries,ownership:packed.ownership};
  return {key:atlas.key,apply:()=>atlas};
 };
 globalThis.Worker=class {postMessage(job){const mipmaps=[];for(let n=64;n>=1;n=Math.floor(n/2))mipmaps.push({width:n,height:n,data:new Uint8Array(n*n*4)});
  queueMicrotask(()=>this.onmessage({data:{id:job.id,result:{mipmaps,format:job.format}}}));}terminate(){}};
 globalThis.Renderer.prototype.extensions={has:()=>false};
 globalThis.fetch=async url=>{
  if(url==='/api/house/twin/materials/manifest')return api('api/house/twin/materials/manifest');
  if(url==='/api/house/live')return new Response(JSON.stringify({markers:lights.map(l=>({...l,device_id:l.device,kind:'light',placed:true}))}));
  if(url.includes('/api/house/bakes/'))return url.endsWith('.png')?new Response(new Uint8Array([1]),{headers:{etag:'seed'}}):new Response(JSON.stringify(publication));
  throw Error('unexpected integration request '+url);
 };
 try {v=await mountTwin(new Element(),{plan:p,kit:k,tier:'low',bake:true});
  for(let i=0;i<200&&v.bake.fresh().length!==2;i++)await new Promise(r=>setTimeout(r,5));
  const controller=v.bake;assert.deepEqual(controller.fresh().sort(),['unrelated','used']);
  const meshes=[];v.scene.traverse(o=>{if(o.isMesh&&o.material?.userData.materialId===id)meshes.push(o);});
  const mesh=meshes.find(o=>o.material.userData.lmOriginalKey!==undefined);assert.ok(mesh);
  const material=mesh.material,geometry=mesh.geometry,levels=v.levels,calls=buildCalls,arrays=controller.held().ids;
  current=record(30,'#8899aa','ffffffffffff.jpg');await v.materialWatcher.check();
  assert.equal(v.bake,controller,'no bake remount');assert.equal(v.levels,levels);assert.equal(buildCalls,calls);
  assert.equal(mesh.material,material);assert.equal(mesh.geometry,geometry);assert.equal(material.color.getHexString(),'8899aa');
  assert.ok(material.map.image.url.endsWith('ffffffffffff.jpg'));assert.deepEqual(controller.held().ids,arrays);
  assert.deepEqual(controller.state().stale,['used']);assert.deepEqual(controller.fresh(),['unrelated']);
  await controller.refresh();assert.deepEqual(controller.state().stale,['used'],'old publication stays stale');
 }finally{v?.dispose();globalThis.fetch=nativeFetch;globalThis.Worker=nativeWorker;delete globalThis.testAtlas;delete globalThis.Renderer.prototype.extensions;}
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
