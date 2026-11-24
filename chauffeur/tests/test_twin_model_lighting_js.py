"""Run viewer model-light wiring with real Three geometry and gzip chunks in Node."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {gridLayout} = await import(file('static/twin/bake/grid_layout.js'));
const {encodeGridChunk} = await import(file('static/twin/bake/grid_chunk.js'));
const {mountModelLighting} = await import(file('static/twin/bake/model_lighting.js'));
const {MODEL_LIGHT_LAYOUT:L} = await import(file('static/twin/bake/model_bricks.js'));
const plan = {buildings:[{id:'b',position:[0,0],levels:[{id:'l',elevation:0,ceiling:8}],
  rooms:[{id:'r',level:'l',polygon:[[0,0],[10,0],[10,10],[0,10]]}],walls:[]}],site:{}};
const layout = gridLayout(plan), indices = Uint32Array.from({length:layout.count},(_,i)=>i);
const lamp = {device:'a',absolute:true,at:[5,5,6],range:20};
const bytes = await encodeGridChunk({layoutHash:layout.hash,device:'a',emitters:1,indices,
  values:new Uint8Array(layout.count).fill(254)});
function merged() {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([
    .3,.3,-.3, .7,.3,-.3, .3,.7,-.3, 1,.3,-1, 1.4,.3,-1, 1,.7,-1],3));
  g.computeVertexNormals(); g.userData.bakeExcluded=true;
  const m = new THREE.Mesh(g,new THREE.MeshStandardMaterial());
  m.userData.snapRanges=[{start:0,count:3,pieceId:'one',buildingId:'b',kind:'item'},
    {start:3,count:3,pieceId:'two',buildingId:'b',kind:'opening'}];
  return m;
}
function setup(mesh=merged(), entries={a:{grid:'chunk',gridLayout:layout.hash,fill:[.2]}}) {
  const scene=new THREE.Scene();scene.add(mesh);
  const host=new EventTarget(); let palette=[], listener, requests=0;
  const view={scene,plan,renderer3:{domElement:{parentElement:host}},render(){},
    live:{paletteLines:()=>palette,subscribe(fn){listener=fn;return()=>{listener=null;}}}};
  const api=async path=>{requests++;assert.equal(path,'api/house/bakes/atlas/grid/chunk.bin');return new Response(bytes);};
  const models=mountModelLighting(view,{manifest:{key:'atlas',lights:entries},layout,
    fresh:new Set(['a']),tints:new Map([['a',new THREE.Color(1,1,1)]]),api,lights:[lamp]});
  return {mesh,models,scene,host,view,requests:()=>requests,palette(value){palette=value;listener?.();}};
}
const meta=(s,i,row)=>{const t=s.models.textures, w=t.mvSize.z;
 return Array.from(t.lamps.image.data.slice(((t.mvSize.w+Math.floor(i/w)*L.BRICK_ROWS+row)*w+i%w)*4,
 ((t.mvSize.w+Math.floor(i/w)*L.BRICK_ROWS+row)*w+i%w)*4+4));};
const emitter=(models,i)=>{const t=models.textures,w=t.mvSize.z;
 const off=((Math.floor(i/w)*L.EMITTER_ROWS+L.EMITTER_ROW_COLOR_SCALE)*w+i%w)*4;
 return Array.from(t.lamps.image.data.slice(off,off+4));};
{
 const s=setup();await s.models.update(['a']);
 const material=s.mesh.material,key=material.customProgramCacheKey();
 const shader={uniforms:{},vertexShader:'#include <project_vertex>',fragmentShader:'#include <lights_fragment_end>'};
 material.onBeforeCompile(shader,{});
 const textures=s.models.textures;let disposed=0;
 for(const texture of [textures.bricks,textures.lamps])texture.addEventListener('dispose',()=>disposed++);
 assert.equal(shader.uniforms.mvBricks.value,textures.bricks);assert.equal(shader.uniforms.mvLamps.value,textures.lamps);
 s.models.stop();
 assert.equal(disposed,2);assert.equal(shader.uniforms.mvBricks.value,null);assert.equal(shader.uniforms.mvLamps.value,null);
 assert.ok(s.mesh.geometry.attributes.mvBrick.array.every(v=>v===0),'a frame between mounts takes the no-model-light shader branch');
 assert.deepEqual(material.defaultAttributeValues.mvBrick,[0]);
 assert.ok(shader.fragmentShader.indexOf('if (vMvBrick > 0.5)')<shader.fragmentShader.indexOf('texelFetch(mvLamps'));
 assert.equal(material.customProgramCacheKey(),key,'stop keeps the same program for the next mount');
 const nextShader={uniforms:{},vertexShader:'#include <project_vertex>',fragmentShader:'#include <lights_fragment_end>'};
 material.onBeforeCompile(nextShader,{});
 assert.equal(nextShader.uniforms.mvBricks.value,null);assert.equal(nextShader.uniforms.mvLamps.value,null);
 s.models.stop();assert.equal(disposed,2);
 console.log('Passed: test_stop_releases_shader_texture_bindings');
}
{
 const s=setup();await s.models.update(['a']);
 const attr=s.mesh.geometry.attributes.mvBrick,version=attr.version,values=Array.from(attr.array),before=s.models.stats();
 await s.models.update(['a'],undefined,[{...lamp,at:[4,5,6]}]);
 assert.equal(s.models.stats().builds,before.builds+1,'lamp metadata rebuilds the bricks');
 assert.equal(s.models.stats().collections,before.collections);
 assert.equal(s.mesh.geometry.attributes.mvBrick,attr);assert.deepEqual(Array.from(attr.array),values);
 assert.equal(attr.version-version,0,'lamp-only rebuilds make zero mvBrick uploads');
 s.models.stop();console.log('Passed: test_lamp_only_rebuild_does_not_write_indices');
}
{
 const mesh=merged(),old=new THREE.Float32BufferAttribute(new Float32Array(5).fill(9),1);
 mesh.geometry.setAttribute('mvBrick',old);const s=setup(mesh);await s.models.update(['a']);
 const attr=mesh.geometry.attributes.mvBrick;
 assert.notEqual(attr,old);assert.equal(attr.count,mesh.geometry.attributes.position.count);
 assert.deepEqual(Array.from(attr.array),[1,1,1,2,2,2]);
 s.models.stop();console.log('Passed: test_wrong_vertex_count_reallocates_attribute');
}
{
 const s=setup();await s.models.update(['a']);
 assert.ok(s.models.stats().loadedSignature,'the completed build records a signature');
 s.mesh.removeFromParent();s.host.dispatchEvent(new Event('twinrebuilt'));
 assert.equal(s.models.stats().bricks,0);
 assert.equal(s.models.stats().loadedSignature,'','the no-models branch clears the prior signature');
 s.models.stop();console.log('Passed: test_no_models_resets_loaded_signature');
}
{
 const mesh=merged(),scene=new THREE.Scene();scene.add(mesh);let calls=0;
 const host=new EventTarget(),view={scene,plan,renderer3:{domElement:{parentElement:host}},render(){}};
 const bBytes=await encodeGridChunk({layoutHash:layout.hash,device:'b',emitters:1,indices,values:new Uint8Array(layout.count).fill(254)});
 const manifest={key:'atlas',lights:{a:{grid:'chunk',gridLayout:layout.hash,fill:[.2]},
  b:{grid:'b-chunk',gridLayout:layout.hash,fill:[.3]},fill:{fill:[.4]}}};
 const lights=[lamp,{...lamp,device:'b'}];
 const options={manifest,layout,fresh:['a','b','fill'],lights,tints:new Map([['a',new THREE.Color(1,1,1)],['b',new THREE.Color(1,1,1)]]),
  api:async path=>{calls++;return new Response(path.endsWith('/b-chunk.bin')?bBytes:bytes);}};
 const models=mountModelLighting(view,options);
 assert.doesNotThrow(()=>models.rebuild(),'rebuild before update is harmless');
 models.setTint('fill',new THREE.Color(1,1,1));
 await models.update(['a','b','fill']);
 const attr=mesh.geometry.attributes.mvBrick,brickVersion=models.textures.bricks.version,builds=models.stats().builds;
 const bColor=emitter(models,1),traverse=scene.traverse;let walks=0;
 scene.traverse=function(fn){walks++;return traverse.call(this,fn);};
 const stale=models.update(['b','fill']);
 assert.equal(mesh.geometry.attributes.mvBrick,attr);assert.ok(attr.array.every(v=>v>0),'fresh lamps never go dark');
 assert.deepEqual(emitter(models,0).slice(0,3),[0,0,0]);assert.deepEqual(emitter(models,1),bColor);
 await stale;assert.equal(models.stats().builds,builds);assert.equal(models.textures.bricks.version,brickVersion);
 assert.equal(walks,0,'freshness-only updates never walk geometry');
 models.setTint('a',new THREE.Color(.25,.5,.75));assert.deepEqual(emitter(models,0).slice(0,3),[0,0,0],'stale rows stay off despite new tint');
 models.setTint('fill',new THREE.Color(.5,.5,.5));
 assert.ok(Math.abs(meta({models},0,L.BRICK_ROW_FILL)[0]-.5)<1e-6,'fill-only devices retain their tint');
 await models.update(['a','b','fill']);assert.equal(emitter(models,0)[0],emitter(models,0)[3]*.25);
 assert.equal(mesh.geometry.attributes.mvBrick,attr);assert.equal(walks,0);
 scene.traverse=traverse;models.stop();
 const remount=mountModelLighting(view,{...options,api:async()=>{throw new Error('cache must prevent a fetch');}});
 const loaded=remount.update(['a','b','fill']);
 assert.ok(remount.textures,'remount installs cached grids before yielding');await loaded;
 assert.equal(mesh.geometry.attributes.mvBrick,attr,'remount reuses the GL attribute');
 assert.equal(emitter(remount,0)[0],emitter(remount,0)[3]*.25,'last-known tint survives remount');
 assert.equal(calls,2);remount.stop();
 console.log('Passed: test_mixed_freshness_fill_tints_and_cached_remount');
}
{
 const s=setup();await s.models.update(['a']);
 const attr=s.mesh.geometry.attributes.mvBrick,values=Array.from(attr.array),version=s.models.textures.bricks.version;
 const d={...lamp,device:'d'},dBytes=await encodeGridChunk({layoutHash:layout.hash,device:'d',emitters:1,indices,values:new Uint8Array(layout.count).fill(254)});
 let release,requests=0;
 const manifest={key:'atlas',lights:{a:{grid:'chunk',gridLayout:layout.hash,fill:[.2]},d:{grid:'d',gridLayout:layout.hash,fill:[.1]}}};
 // Reuse the view cache, then hold the one new grid while lamp a stays lit.
 s.models.stop();
 const m=mountModelLighting(s.view,{manifest,layout,fresh:['a'],lights:[lamp,d],tints:new Map(),
  api:()=>{requests++;return new Promise(resolve=>{release=resolve;});}});
 await m.update(['a']);m.setTint('d',new THREE.Color(.5,.25,.75));
 const original=emitter(m,0),builds=m.stats().builds,collections=m.stats().collections;
 manifest.lights.a.fill[0]=.4; // Fill metadata must not retire an otherwise fresh direct row.
 const work=m.update(['a','d']);await Promise.resolve();
 assert.deepEqual(Array.from(attr.array),values,'pending download never blanks other models');
 assert.deepEqual(emitter(m,0),original,'existing fresh emitter is unchanged');
 assert.equal(m.stats().builds,builds);assert.equal(m.stats().collections,collections);
 release(new Response(dBytes));await work;
 assert.equal(m.stats().collections,collections);assert.equal(s.mesh.geometry.attributes.mvBrick,attr);
 assert.equal(emitter(m,1)[0],emitter(m,1)[3]*.5,'new emitter starts from its pre-download tint');
 const next={key:'atlas',lights:{d:manifest.lights.d}};
 await m.update(['d'],next,[d]);assert.equal(m.stats().cachedChunks,1,'deleted grid keys are pruned');
 m.stop();console.log('Passed: test_pending_grid_keeps_fresh_lamp_and_prunes_cache');
}
{
 const s=setup(), original=s.mesh.material, wall=new THREE.Mesh(new THREE.BoxGeometry(),original);
 const wallKey=wall.material.customProgramCacheKey();s.scene.add(wall);
 await s.models.update(new Set(['a']));
 assert.deepEqual(Array.from(s.mesh.geometry.attributes.mvBrick.array),[1,1,1,2,2,2]);
 assert.ok(s.mesh.material.customProgramCacheKey().includes('|mv-1'));
 assert.equal(s.models.stats().bricks,2);assert.equal(s.requests(),1);
 assert.equal(wall.material,original);assert.equal(wall.material.customProgramCacheKey(),wallKey);
 assert.equal(wall.geometry.attributes.mvBrick,undefined);
 const unchanged=s.models.stats().builds;await s.models.update(['a']);
 assert.equal(s.models.stats().builds,unchanged,'unchanged polls do not rebuild');
 const n=s.models.stats().builds, version=s.models.textures.bricks.version;
 s.models.setTint('a',new THREE.Color(.5,.25,0));
 assert.ok(Math.abs(meta(s,0,L.BRICK_ROW_FILL)[0]-.1)<1e-6);
 s.models.setTint('a',0);assert.equal(meta(s,0,L.BRICK_ROW_FILL)[0],0);
 assert.equal(s.models.stats().builds,n);assert.equal(s.models.textures.bricks.version,version);
 s.host.dispatchEvent(new Event('twinrebuilt'));assert.equal(s.models.stats().builds,n+1);
 await s.models.update(new Set());assert.ok(s.mesh.geometry.attributes.mvBrick.array.every(v=>v>0));
 assert.deepEqual(emitter(s.models,0).slice(0,3),[0,0,0]);
 s.models.stop();console.log('Passed: test_bricks_assigned_per_copy_range');
}
{
 const s=setup(),g=s.mesh.geometry,attr=new THREE.Float32BufferAttribute(new Float32Array(6).fill(9),1);
 g.setAttribute('mvBrick',attr);s.mesh.userData.snapRanges[1].ghost=true;
 await s.models.update(['a']);assert.equal(g.attributes.mvBrick,attr);
 assert.deepEqual(Array.from(attr.array),[1,1,1,0,0,0],'a reused buffer is cleared before writing owned ranges');
 s.models.stop();console.log('Passed: test_reused_attribute_clears_unowned_ranges');
}
{
 const g=new THREE.BoxGeometry(.4,.4,.4);g.userData.bakeExcluded=true;
 const a=new THREE.Mesh(g,new THREE.MeshStandardMaterial()),b=new THREE.Mesh(g,a.material);
 a.userData.modelLod=b.userData.modelLod=true;a.position.set(.6,.6,-.6);b.position.set(1.2,.6,-1.2);
 const group=new THREE.Group();group.add(a,b);const s=setup(group);await s.models.update(['a']);
 assert.notEqual(a.geometry,g);assert.notEqual(a.geometry,b.geometry);
 assert.equal(a.geometry.attributes.position,g.attributes.position);assert.equal(a.geometry.index,g.index);
 assert.notEqual(a.geometry.attributes.mvBrick,b.geometry.attributes.mvBrick);
 assert.equal(g.attributes.mvBrick,undefined);
 const own=a.geometry; s.models.rebuild();assert.equal(a.geometry,own);
 s.models.stop();assert.ok(own.attributes.mvBrick.array.every(v=>v===0));
 console.log('Passed: test_lod_copy_gets_own_geometry');
}
{
 const s=setup();await s.models.update([]);assert.equal(s.requests(),0);
 assert.equal(s.models.textures,null);assert.equal(s.mesh.geometry.attributes.mvBrick,undefined);
 s.models.stop();console.log('Passed: test_stale_light_not_in_table');
}
{
 for(const entries of [{},{a:{grid:'chunk',gridLayout:'old'}}]){
  const s=setup(merged(),entries),key=s.mesh.material.customProgramCacheKey();await s.models.update(['a']);
  assert.equal(s.requests(),0);assert.equal(s.models.textures,null);
  assert.equal(s.mesh.geometry.attributes.mvBrick,undefined);assert.equal(s.mesh.material.customProgramCacheKey(),key);s.models.stop();
 }
 console.log('Passed: test_no_fresh_grid_patches_nothing');
}
{
 const s=setup();await s.models.update(['a']);s.palette(['a']);
 assert.deepEqual(emitter(s.models,0).slice(0,3),[0,0,0]);
 s.palette([]);await s.models.update(['a']);assert.ok(s.mesh.geometry.attributes.mvBrick.array.every(v=>v>0));
 const t=s.models.textures;let disposed=0;t.bricks.addEventListener('dispose',()=>disposed++);
 s.models.stop();s.host.dispatchEvent(new Event('twinyardrebuilt'));assert.equal(disposed,1);
 console.log('Passed: test_palette_changes_and_stop');
}
{
 const mesh=merged(),scene=new THREE.Scene();scene.add(mesh);
 let attempts=0,release;
 const now=Date.now,warn=console.warn;let clock=now(),warnings=0;
 Date.now=()=>clock;console.warn=()=>warnings++;
 const view={scene,plan,renderer3:{domElement:{}},render(){}};
 const models=mountModelLighting(view,{manifest:{key:'atlas',lights:{a:{grid:'chunk',gridLayout:layout.hash}}},
  layout,fresh:['a'],tints:new Map(),lights:[lamp],api:async()=>++attempts<3?new Response('',{status:attempts===1?404:401}):new Response(bytes)});
 await models.update(['a']);assert.equal(mesh.geometry.attributes.mvBrick,undefined);
 await models.update(['a']);assert.equal(attempts,1,'404 reads back off');
 clock+=5000;await models.update(['a']);assert.equal(attempts,2);
 clock+=9999;await models.update(['a']);assert.equal(attempts,2,'401 reads double the retry delay');
 clock++;await models.update(['a']);assert.equal(attempts,3);assert.ok(mesh.geometry.attributes.mvBrick);
 assert.equal(warnings,1,'one warning for the outage');Date.now=now;console.warn=warn;
 models.stop();
 const late=mountModelLighting({...view},{manifest:{key:'atlas',lights:{a:{grid:'chunk',gridLayout:layout.hash}}},
  layout,fresh:['a'],tints:new Map(),lights:[lamp],api:()=>new Promise(resolve=>{release=resolve;})});
 const work=late.update(['a']);await Promise.resolve();late.stop();release(new Response(bytes));await work;
 assert.equal(late.textures,null,'stopped downloads never patch');
 console.log('Passed: test_failed_chunk_retry_and_stopped_download');
}
{
 const scene=new THREE.Scene();scene.add(merged());
 const now=Date.now,warn=console.warn;let clock=now(),attempts=0,warnings=0;
 Date.now=()=>clock;console.warn=()=>warnings++;
 const view={scene,plan,renderer3:{domElement:{}},render(){}};
 const models=mountModelLighting(view,{manifest:{key:'atlas',lights:{a:{grid:'chunk',gridLayout:layout.hash}}},
  layout,fresh:['a'],tints:new Map(),lights:[lamp],api:async()=>{attempts++;return new Response('',{status:401});}});
 try {
  await models.update(['a']);
  for(let i=0;i<8;i++){
   const count=attempts,delay=Math.min(300000,5000*2**Math.min(i,6));
   clock+=delay-1;await models.update(['a']);assert.equal(attempts,count);
   clock++;await models.update(['a']);assert.equal(attempts,count+1);
  }
  assert.equal(warnings,1);assert.equal(models.textures,null);
 }finally{models.stop();Date.now=now;console.warn=warn;}
 console.log('Passed: test_chunk_backoff_caps_at_five_minutes');
}
{
 const s=setup(),original=s.mesh.material,wall=new THREE.Mesh(new THREE.BoxGeometry(),original);s.scene.add(wall);
 await s.models.update(['a']);const disposed=s.mesh.material;disposed.dispose();s.mesh.material=original;
 s.host.dispatchEvent(new Event('twinrebuilt'));
 assert.notEqual(s.mesh.material,disposed,'disposed shared-material clones are evicted');
 assert.equal(wall.material,original);s.models.stop();
 console.log('Passed: test_disposed_material_clone_is_not_reused');
}
{
 const scene=new THREE.Scene(),mesh=merged();scene.add(mesh);
 const view={scene,plan,renderer3:{domElement:{}},render(){},bake:{state:()=>({key:'atlas'})},live:{layout:()=>({markers:[{
  device_id:'a',kind:'light',placed:true,at:[5,5,6],building:'b',level:'l',room:'r'}]})}};
 const models=mountModelLighting(view,{manifest:{lights:{a:{grid:'chunk',gridLayout:layout.hash}}},
  layout,fresh:['a'],tints:new Map(),api:async()=>new Response(bytes)});
 await models.update(['a']);assert.equal(models.stats().emitters,1);assert.equal(models.stats().bricks,2);
 models.stop();console.log('Passed: test_public_interface_resolves_live_lamps');
}
{
 const s=setup(),original=s.mesh.material,other=merged();other.userData.snapRanges.forEach(r=>r.pieceId='one');s.scene.add(other);
 await s.models.update(['a']);assert.equal(s.models.stats().bricks,2,'one placement shares bounds across materials');
 assert.equal(s.mesh.material,original,'dedicated model materials retain live emissive/texture ownership');
 assert.ok(other.geometry.attributes.mvBrick.array.every(v=>v===1));
 s.mesh.position.set(50,0,50);other.position.copy(s.mesh.position);s.host.dispatchEvent(new Event('twinrebuilt'));
 assert.equal(meta(s,0,L.BRICK_ROW_FILL)[0],0,'outside every room has no fill');
 assert.equal(meta(s,1,L.BRICK_ROW_FILL)[0],0);
 s.models.stop();console.log('Passed: test_shared_copy_bounds_and_outside_fill');
}
{
 const s=setup();s.mesh.removeFromParent();await s.models.update(['a']);
 assert.equal(s.requests(),0,'scenes without models do not download grids');
 s.models.setTint('a',new THREE.Color(.25,.5,.75));
 s.scene.add(s.mesh);s.host.dispatchEvent(new Event('twinyardrebuilt'));await s.models.update(['a']);
 assert.ok(s.mesh.geometry.attributes.mvBrick,'late yard models load and receive bricks');
 assert.equal(emitter(s.models,0)[0],emitter(s.models,0)[3]*.25,'late model is seeded from the last tint');
 const attr=s.mesh.geometry.attributes.mvBrick,builds=s.models.stats().builds;
 s.mesh.removeFromParent();s.host.dispatchEvent(new Event('twinyardrebuilt'));
 assert.equal(s.models.stats().bricks,0);assert.ok(attr.array.every(v=>v===0));
 s.scene.add(s.mesh);s.host.dispatchEvent(new Event('twinyardrebuilt'));
 assert.equal(s.models.stats().builds,builds+1,'return after the no-models branch rebuilds from cache');
 assert.equal(s.mesh.geometry.attributes.mvBrick,attr);assert.equal(s.requests(),1);
 s.models.stop();console.log('Passed: test_late_yard_models_fetch_grids');
}

// A renderer that refuses to draw an unready model program. Each pending
// light-state compile must resolve independently before a clone reaches scene.
const tick=()=>new Promise(r=>setTimeout(r,0));
async function waitFor(test){for(let n=0;n<100&&!test();n++)await tick();assert.ok(test(),'async warm-up starts');}
function asyncRig(){
 const s=setup(),queue=[],ready=new Set(),owned=new Set();let inClick=false,frames=0;
 s.view.camera=new THREE.PerspectiveCamera(60,1,.01,100);s.view.camera.position.set(0,0,5);s.view.camera.lookAt(0,0,0);
 const pool=new THREE.PointLight();pool.visible=false;s.scene.add(pool);
 const program=(m,state,side=m.side)=>`${m.customProgramCacheKey()}|pool:${state}|side:${side}`;
 s.view.live.warm=compile=>{const shown=pool.visible;pool.visible=true;try{return compile();}finally{pool.visible=shown;}};
 s.view.renderer3.compileAsync=(root,camera,scene)=>{
  assert.equal(inClick,false,'no compile inside a switch handler');assert.notEqual(root,s.scene);assert.equal(scene,s.scene);assert.equal(camera,s.view.camera);
  const materials=[];root.traverse(o=>{if(o.material)materials.push(...[].concat(o.material));});
  assert.ok(materials.length);for(const m of materials){owned.add(m);assert.ok(m.customProgramCacheKey().includes('|mv-1'));}
  const state=pool.visible;
  return new Promise((resolve,reject)=>queue.push({materials,pool:state,resolve(){materials.forEach(m=>ready.add(program(m,state,m.transparent&&m.side===THREE.DoubleSide&&!m.forceSinglePass?THREE.FrontSide:m.side)));resolve();},reject}));
 };
 // setup's original CPU controller was created before compileAsync existed.
 s.models.stop();s.models=mountModelLighting(s.view,{manifest:{key:'atlas',lights:{a:{grid:'chunk',gridLayout:layout.hash}}},layout,fresh:['a'],tints:new Map(),lights:[lamp],api:async()=>new Response(bytes)});
 s.view.render=()=>{frames++;s.scene.traverseVisible(o=>{for(const m of o.material?[].concat(o.material):[])if(m.customProgramCacheKey().includes('|mv-1'))for(const side of m.transparent&&m.side===THREE.DoubleSide&&!m.forceSinglePass?[THREE.FrontSide,THREE.BackSide]:[m.side])assert.ok(ready.has(program(m,pool.visible,side)),'frame-stall detector: program not compiled for the state being drawn');});};
 return {...s,queue,owned,pool,frames:()=>frames,switch(){inClick=true;try{pool.visible=!pool.visible;s.view.render();}finally{inClick=false;}}};
}

{
 const s=asyncRig(),compile=s.view.renderer3.compileAsync;let held=0;
 s.view.renderer3.compileAsync=()=>{held++;throw Error('live-scene hold used');};
 s.view.compileModelMaterials=root=>compile(root,s.view.camera,s.scene);
 const original=s.mesh.material,work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);
 s.view.render();s.view.render();assert.equal(s.mesh.material,original);assert.equal(held,0,'detached compile bypasses the live-scene hold');
 s.queue.forEach(q=>q.resolve());await work;s.view.render();s.models.stop();
 console.log('Passed: test_detached_warmup_keeps_original_frames_running');
}
{
 const s=asyncRig(),original=s.mesh.material,work=s.models.update(['a']);
 await waitFor(()=>s.queue.length===2);assert.equal(s.mesh.material,original);s.view.render();
 assert.notEqual(s.queue[0].materials[0],s.queue[1].materials[0],'pending variants cannot overwrite material.currentProgram');
 s.queue[0].resolve();await tick();assert.equal(s.mesh.material,original,'wait for pool-on too');s.switch();
 s.queue[1].resolve();await work;assert.notEqual(s.mesh.material,original);s.view.render();
 const compiled=s.queue.length;await s.models.update(['a']);s.switch();assert.equal(s.queue.length,compiled,'unchanged update/click compiles nothing');
 original.emissiveIntensity=3;assert.equal(s.mesh.material.emissiveIntensity,3,'live emissive owner survives clone');
 s.models.stop();assert.equal(s.mesh.material,original);console.log('Passed: test_async_compile_before_live_swap_and_no_click_compile');
}
{
 const s=asyncRig(),original=s.mesh.material,work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);
 let disposed=0;for(const m of s.owned)m.addEventListener('dispose',()=>disposed++);
 s.models.stop();await work;assert.equal(s.mesh.material,original);assert.equal(disposed,0,'never dispose a linking program');
 s.queue[0].resolve();await tick();assert.equal(disposed,0,'wait for every compile to settle');
 s.queue[1].resolve();await tick();assert.equal(disposed,s.owned.size,'settled cancelled clones released exactly once');assert.equal(s.mesh.material,original);console.log('Passed: test_pending_model_compile_stop_disposes_clones');
}

{
 const s=asyncRig(),original=s.mesh.material,warn=console.warn;let warnings=0;
 const work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);console.warn=()=>warnings++;
 try{s.queue[0].reject(new Error('link failed'));await tick();assert.equal(s.mesh.material,original);s.queue[1].resolve();await work;assert.equal(warnings,1);assert.equal(s.mesh.material,original);}
 finally{console.warn=warn;s.models.stop();}
 console.log('Passed: test_failed_compile_keeps_unpatched_models');
}
{
 const s=asyncRig(),original=s.mesh.material,work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);
 const next=s.models.update([], {key:'atlas',lights:{}});await next;await work;
 s.queue.forEach(q=>q.resolve());await tick();assert.equal(s.mesh.material,original);s.models.stop();console.log('Passed: test_grid_change_cancels_pending_model_swap');
}
{
 const s=asyncRig(),hidden=merged();hidden.material=new THREE.MeshStandardMaterial({color:'red'});hidden.position.x=2;
 hidden.userData.snapRanges.forEach(r=>r.pieceId='hidden-'+r.pieceId);const gate=new THREE.Group();gate.visible=false;gate.add(hidden);s.scene.add(gate);
 const original=hidden.material,work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);
 assert.ok([...s.owned].every(m=>m.color.getHex()!==original.color.getHex()),'hidden material is not cloned/compiled');
 s.queue.forEach(q=>q.resolve());await work;assert.equal(hidden.material,original);
 gate.visible=true;s.host.dispatchEvent(new Event('twinviewchange'));assert.equal(s.queue.length,2,'visibility handler only schedules');
 await waitFor(()=>s.queue.length===4);assert.equal(hidden.material,original);s.view.render();
 s.queue.slice(2).forEach(q=>q.resolve());await tick();await tick();assert.notEqual(hidden.material,original);
 s.models.stop();console.log('Passed: test_hidden_models_compile_lazily_after_level_gate');
}
{
 const s=asyncRig(),work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);s.queue.forEach(q=>q.resolve());await work;
 const previous=s.mesh.material;let disposed=0;for(const m of s.owned)m.addEventListener('dispose',()=>disposed++);
 for(let i=0;i<60;i++){await s.models.warm();assert.equal(s.mesh.material,previous);s.view.render();}
 assert.equal(s.queue.length,2,'60 unchanged clock ticks compile nothing');assert.equal(disposed,0);s.models.stop();
 console.log('Passed: test_time_look_keeps_ready_clones_for_unchanged_light_state');
}
{
 const s=asyncRig(),work=s.models.update(['a']);await waitFor(()=>s.queue.length===2);
 const next=s.models.update(['a'],{key:'atlas',lights:{a:{grid:'replacement',gridLayout:layout.hash}}});
 await tick();assert.equal(s.queue.length,2,'grid inputs retain linking clones');
 s.queue.forEach(q=>q.resolve());await Promise.all([work,next]);const installed=s.mesh.material;
 let disposed=0;for(const m of s.owned)m.addEventListener('dispose',()=>disposed++);
 await s.models.update(['a'],{key:'atlas',lights:{a:{grid:'third',gridLayout:layout.hash}}});
 assert.equal(s.mesh.material,installed);assert.equal(s.queue.length,2);assert.equal(disposed,0,'grid and tint data never retire programs');
 s.models.stop();console.log('Passed: test_grid_uniform_changes_retain_pending_and_installed_programs');
}
"""


def runtime_and_household():
    import test_twin_bake_runtime_js as R
    B = R.B
    driver = R.DRIVER[:R.DRIVER.index('let passed = 0, ran = 0')]
    driver += r"""
const {lightSource}=await import(file('static/twin/bake/reach.js'));
const {MODEL_LIGHT_LAYOUT:ML}=await import(file('static/twin/bake/model_bricks.js'));
const {tintSum}=await import(file('static/twin/bake/lightmap_material.js'));
const ctx=await context('high',null,null,{poll:0});
try {
 const source=lightSource(ctx.view.plan,k1).source;
 const model=new THREE.Mesh(new THREE.BoxGeometry(.6,.6,.6),new THREE.MeshStandardMaterial());
 model.geometry.userData.bakeExcluded=true;model.userData.pieceId='wiring-proof';
 model.position.copy(source);model.position.y-=1;ctx.view.scene.add(model);
 await until(()=>ctx.controller.fresh().length===4&&!ctx.controller.state().baking&&ctx.controller.models?.stats().bricks===1,'model controller mounts through loadPages');
 const m=ctx.controller.models,t=m.textures,row=0,w=t.mvSize.z;
 const off=((Math.floor(row/w)*ML.EMITTER_ROWS+ML.EMITTER_ROW_COLOR_SCALE)*w+row%w)*4;
 ctx.controller.light('k1',[255,128,64],.5);
 const color=tintSum([{rgb:[255,128,64],intensity:.5}],true),scale=t.lamps.image.data[off+3];
 for(const [i,c] of [color.r,color.g,color.b].entries()) assert.ok(Math.abs(t.lamps.image.data[off+i]-c*scale)<1e-4,'runtime forwards exactly its linear tint');
 ctx.controller.light('k1',[255,128,64],0);
 assert.deepEqual(Array.from(t.lamps.image.data.slice(off,off+3)),[0,0,0],'mode-hidden zero clears models');
 const builds=m.stats().builds;await ctx.controller.refresh();assert.equal(m.stats().builds,builds,'unchanged pages do no model work');
 console.log('Passed: test_runtime_forwards_tints_and_unchanged_poll');
 // Full household layout/structure, with the three controlled placements used
 // for model-grid checks (the historical fixture has no authored item assets).
 const house=gen.buildTwin(job.household,job.kit,'high');await house.ready;
 const scene=new THREE.Scene();scene.add(house.root);
 const vertexCounts=[];
 for(let i=0;i<3;i++){
  const segments=[38,53,64][i],geometry=new THREE.BoxGeometry(.6,.6,.6,segments,segments,segments).toNonIndexed();
  geometry.userData.bakeExcluded=true;vertexCounts.push(geometry.attributes.position.count);
  const copy=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial());
  copy.userData={pieceId:'fixture-'+i,snapRanges:[{start:0,count:geometry.attributes.position.count,pieceId:'fixture-'+i,buildingId:'pool-house',kind:'item'}]};
  copy.position.copy(source).add(new THREE.Vector3(i*.5,-1,0));scene.add(copy);
 }
 const {mountModelLighting}=await import(file('static/twin/bake/model_lighting.js'));
 const {gridLayout}=await import(file('static/twin/bake/grid_layout.js'));
 const {encodeGridChunk}=await import(file('static/twin/bake/grid_chunk.js'));
 const layout=gridLayout(job.household),indices=Uint32Array.from({length:layout.count},(_,i)=>i),grids=new Map();
 const lights=[k1,k2,h1,c1],manifest={key:'household',lights:{}};
 for(const light of lights){
  manifest.lights[light.device]={grid:light.device,gridLayout:layout.hash,fill:[.1,.1,.1]};
  grids.set(light.device,await encodeGridChunk({layoutHash:layout.hash,device:light.device,emitters:1,indices,values:new Uint8Array(layout.count).fill(254)}));
 }
 const host=new EventTarget(),view={scene,plan:job.household,renderer3:{domElement:{parentElement:host}},render(){}};
 const bench=mountModelLighting(view,{manifest,layout,fresh:lights.map(l=>l.device),tints:new Map(),lights,
  api:async path=>new Response(grids.get(path.split('/').at(-1).slice(0,-4)))});
 await bench.update(lights.map(l=>l.device));
 assert.equal(bench.stats().bricks,3);assert.equal(bench.stats().builds,1);
 const first=bench.stats(),attrs=[];scene.traverse(o=>{if(o.geometry?.attributes.mvBrick)attrs.push([o,o.geometry.attributes.mvBrick,o.geometry.attributes.mvBrick.version]);});
 const extra={...k2,device:'dense-extra'};lights.push(extra);
 manifest.lights[extra.device]={grid:extra.device,gridLayout:layout.hash,fill:[.1,.1,.1]};
 grids.set(extra.device,await encodeGridChunk({layoutHash:layout.hash,device:extra.device,emitters:1,indices,values:new Uint8Array(layout.count).fill(254)}));
 await bench.update(lights.map(l=>l.device),manifest,lights);
 const lampOnly=bench.stats();assert.equal(lampOnly.builds,2);assert.equal(lampOnly.collections,first.collections);
 for(const [o,a,version] of attrs){
  assert.equal(o.geometry.attributes.mvBrick,a,'lamp change retains GL attribute');
  assert.equal(a.version-version,0,'lamp change uploads no mvBrick buffers across 300k vertices');
 }
 host.dispatchEvent(new Event('twinrebuilt'));
 const geometry=bench.stats();assert.equal(geometry.builds,3);assert.equal(geometry.collections,first.collections+1);
 for(const [o,a] of attrs)assert.equal(o.geometry.attributes.mvBrick,a,'geometry event reuses compatible GL attribute');
 console.log('Dense household model-light budget: '+JSON.stringify({vertexCounts,totalVertices:vertexCounts.reduce((a,b)=>a+b,0),
  firstBuildMs:first.buildMs,lampOnlyMs:lampOnly.buildMs,twinrebuiltMs:geometry.buildMs,collections:[first.collections,lampOnly.collections,geometry.collections],
  bricks:geometry.bricks,emitters:geometry.emitters,bricksSize:geometry.bricksSize,lampsSize:geometry.lampsSize,bytes:geometry.bytes,
  gridPoints:layout.count,visibility:'synthetic all-visible; real household layout/structure, dense generated model geometry'}));
 bench.stop();console.log('Passed: test_household_build_budget');
 let poolRefreshes=0;const held=[];
 const wall=await context('low',ctx.server,null,{poll:0,
  view:{live:{layout:()=>liveLayout([k1,k2,h1,c1]),refresh:async()=>{poolRefreshes++;}}},
  api:(path,init,request)=>path.includes('/grid/')&&(!init?.method||init.method==='GET')?
   new Promise(resolve=>held.push({resolve,path,init,request})):request(path,init)});
 try {
  const copy=model.clone();copy.geometry=model.geometry.clone();wall.view.scene.add(copy);
  wall.controller.light('k1',[255,128,64],.5);
  await until(()=>wall.controller.fresh().length===4&&held.length>0&&poolRefreshes>0,'wall/pool freshness does not wait for grids');
  assert.equal(wall.controller.models.textures,null);
  for(const row of held)row.resolve(await row.request(row.path,row.init));
  await until(()=>wall.controller.models.stats().emitters===4,'deferred grids install');
  const t=wall.controller.models.textures,c=tintSum([{rgb:[255,128,64],intensity:.5}],true);
  const off=ML.EMITTER_ROW_COLOR_SCALE*t.mvSize.z*4,scale=t.lamps.image.data[off+3];
  assert.ok(Math.abs(t.lamps.image.data[off]-c.r*scale)<1e-4,'tint replay is retained before rows exist');
  console.log('Passed: test_runtime_pool_and_replay_do_not_wait_for_grids');
  const update=wall.controller.models.update,error=console.error,reported=[];
  try {
   wall.controller.models.update=async()=>{throw new Error('injected model update rejection');};
   console.error=(...args)=>reported.push(args.map(arg=>arg?.message||String(arg)).join(' '));
   wall.view.live.layout=()=>liveLayout([{...k1,at:[k1.at[0]+1,...k1.at.slice(1)]},k2,h1,c1]);
   await wall.controller.refresh();await Promise.resolve();
   assert.ok(reported.some(message=>message.includes('injected model update rejection')),'preparation/update rejections are reported');
   assert.ok(wall.controller.fresh().includes('h1'),'model failure does not block unaffected wall freshness');
  }finally{wall.controller.models.update=update;console.error=error;}
  console.log('Passed: test_runtime_reports_background_update_rejection');
 }finally{for(const row of held)row.resolve(new Response('',{status:404}));wall.controller.stop();}
} finally {ctx.controller.stop();}
const group=await context('high',null,[{...k1,device:'member-a'},{...k1,device:'member-b'}],{poll:0});
try {
 const {source}=lightSource(group.view.plan,k1);
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(.6,.6,.6),new THREE.MeshStandardMaterial());
 mesh.geometry.userData.bakeExcluded=true;mesh.userData.pieceId='group-copy';mesh.position.copy(source);mesh.position.y-=1;
 group.view.scene.add(mesh);
 await until(()=>!group.controller.state().baking&&group.controller.models?.stats().emitters===1,'shared slot is baked and has an emitter');
 group.controller.light('member-a',[255,0,0],.5);group.controller.light('member-b',[0,0,255],.25);
 const t=group.controller.models.textures,off=ML.EMITTER_ROW_COLOR_SCALE*t.mvSize.z*4,scale=t.lamps.image.data[off+3];
 const expected=tintSum([{rgb:[255,0,0],intensity:.5},{rgb:[0,0,255],intensity:.25}],true);
 assert.ok(Math.abs(t.lamps.image.data[off]-expected.r*scale)<1e-4);
 assert.ok(Math.abs(t.lamps.image.data[off+2]-expected.b*scale)<1e-4,'group slot gets the summed tint');
 group.controller.light('member-a',[255,0,0],0);
 assert.equal(t.lamps.image.data[off],0);assert.ok(t.lamps.image.data[off+2]>0,'clearing one member preserves its neighbour');
 console.log('Passed: test_runtime_group_slot_tint');
}finally{group.controller.stop();}
const editor=await context('high',null,null,{mode:'manual',display:false,poll:0});
try {
 await until(()=>editor.host.textContent.includes('Lighting'),'inspect-only initializes');
 assert.equal(editor.controller.models,null,'editor never mounts model lighting');
 console.log('Passed: test_editor_inspect_only_has_no_model_controller');
}finally{editor.controller.stop();}
process.exit(0);
"""
    plan = B.household_pool_house()
    job = {'root': ROOT.as_posix(), 'plan': plan, 'household': B.twin_store.current(),
           'kit': {**B.tl.kit('modern_farmhouse'), 'manifest': {}}, 'layout': B.LAYOUT,
           'pool': B.POOL, 'kitchen': B.KITCHEN, 'hall': B.HALL, 'changing': B.CHANGING}
    with tempfile.TemporaryDirectory(prefix='chauffeur_model_runtime_') as directory:
        script, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        script.write_text(driver, encoding='utf-8')
        data.write_text(json.dumps(job), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(script), str(data)], capture_output=True,
                                text=True, encoding='utf-8', timeout=180)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


def run():
    with tempfile.TemporaryDirectory(prefix='chauffeur_model_lighting_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': {}}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    runtime_and_household()


if __name__ == '__main__':
    run()
