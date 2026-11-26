"""Executed Node proof for per-copy model selection and the bake-source handoff."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT
from twin_editor_dom import run_node
from test_twin_bake_editor_source_js import DRIVER as EDITOR_DRIVER
from test_twin_bake_runtime_js import DRIVER as RUNTIME_DRIVER

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {modelOccluderMeshes} = await import(file('static/twin/bake/model_occluder_meshes.js'));
const {occluders, renderPage} = await import(file('static/twin/bake/bake_pass.js'));
const {mergeGeometries} = await import(file('static/vendor/three-r187/addons/utils/BufferGeometryUtils.js'));
const {registerBakeSource, bakeModelRoot, prepareBakeModels, releaseBakeSource} = await import(file('static/twin/bake/source.js'));
const source = new THREE.Vector3(), opaque = new THREE.MeshStandardMaterial();
const box = (x, y=0, z=0) => new THREE.BoxGeometry(.5,.5,.5).toNonIndexed().translate(x,y,z);
const furniture = (id, extra={}) => ({id,kind:'chair',at:[0,0],...extra});
const plan = {site:{furniture:['near','far','inside','off','clear','lod','fallback'].map(id=>furniture(id,
  id==='off'?{casts_shadow:false}:{}))}};
const owner = id => ({kind:'furniture',pieceId:id});
function merged(ids, xs, material=opaque) {
  const g=mergeGeometries(xs.map(x=>box(x)));g.userData.bakeExcluded=true;
  const m=new THREE.Mesh(g,material);m.userData.merged=true;
  m.userData.snapRanges=ids.map((id,i)=>({...owner(id),start:i*36,count:36}));return m;
}
const ids = meshes => meshes.map(m=>m.userData.modelCopyId).sort();
const tests = {
 test_model_occluder_selection() {
  const root=new THREE.Group(), batch=merged(['near','far','inside','off'],[2,30,0,3]);root.add(batch);
  root.add(merged(['clear'],[4],new THREE.MeshStandardMaterial({transparent:true,opacity:.5})));
  const lod=new THREE.LOD();
  for(const [i,x] of [2,3,4].entries()) {
   const m=new THREE.Mesh(box(x),opaque);m.geometry.userData.bakeExcluded=true;
   Object.assign(m.userData,owner('lod'),{modelLod:true});m.name=`level-${i}`;lod.addLevel(m,i*10);
  }
  lod.levels[1].object.visible=false;root.add(lod);
  const fallback=new THREE.LOD(), only=new THREE.Mesh(box(-2),opaque);
  only.geometry.userData.bakeExcluded=true;Object.assign(only.userData,owner('fallback'),{modelLod:true});
  fallback.addLevel(only,0);root.add(fallback);
  const got=modelOccluderMeshes(root,plan,source,6);
  assert.deepEqual(ids(got),['furniture:fallback','furniture:lod','furniture:near']);
  const near=got.find(m=>m.userData.pieceId==='near'), mid=got.find(m=>m.userData.pieceId==='lod');
  assert.deepEqual(near.geometry.drawRange,{start:0,count:36});
  assert.deepEqual(mid.geometry.drawRange,{start:0,count:36});
  assert.equal(mid.geometry.attributes.position,lod.levels[1].object.geometry.attributes.position,'only mid LOD');
  assert.equal(near.geometry.attributes.position,batch.geometry.attributes.position,'shared buffers');
  assert.deepEqual(batch.geometry.drawRange,{start:0,count:Infinity},'drawn batch unchanged');
  assert.equal(near.matrixAutoUpdate,false);assert.deepEqual(near.matrix.elements,batch.matrixWorld.elements);
  assert.equal(modelOccluderMeshes(root,plan,source,6)[0].geometry,got[0].geometry,'reuse range shells');
 },
 test_world_bounds_indices_and_per_copy_ranges() {
  const root=new THREE.Group(),m=merged(['far','near'],[30,2]);root.add(m);
  let got=modelOccluderMeshes(root,plan,source,6);
  assert.deepEqual(got[0].geometry.drawRange,{start:36,count:36});
  root.position.x=20;assert.equal(modelOccluderMeshes(root,plan,source,6).length,0,'refresh world matrices');
  root.position.x=-20;got=modelOccluderMeshes(root,plan,source,10);
  assert.deepEqual(ids(got),['furniture:far'],'bounds, not the placement point, reach the sphere');
  const indexed=new THREE.Mesh(new THREE.BoxGeometry(.5,.5,.5),opaque);
  indexed.position.x=2;indexed.geometry.userData.bakeExcluded=true;Object.assign(indexed.userData,owner('near'));
  const group=new THREE.Group();group.add(indexed);
  assert.deepEqual(modelOccluderMeshes(group,plan,source,6)[0].geometry.drawRange,{start:0,count:36});
  let disposed=0;const shell=modelOccluderMeshes(group,plan,source,6)[0].geometry;
  shell.addEventListener('dispose',()=>disposed++);indexed.geometry.dispose();assert.equal(disposed,1);
 },
 test_material_rules_and_whole_copy_containment() {
  const root=new THREE.Group();
  for(const material of [new THREE.MeshStandardMaterial({alphaTest:.1}),
   new THREE.MeshStandardMaterial({name:'glass'}),new THREE.MeshStandardMaterial({name:'fixture'}),[opaque]])
   root.add(merged(['near'],[2],material));
  const m=merged(['near'],[2]);m.geometry.userData.bakeExcluded=false;root.add(m);
  assert.equal(modelOccluderMeshes(root,plan,source,6).length,0);
  const solid=new THREE.MeshStandardMaterial({transparent:true});solid.userData.viewingOpaque=true;
  root.add(merged(['near'],[2],solid));assert.deepEqual(ids(modelOccluderMeshes(root,plan,source,6)),['furniture:near']);
  const shade=new THREE.Group();shade.add(merged(['inside'],[-.5]),merged(['inside'],[.5]));
  assert.equal(modelOccluderMeshes(shade,plan,source,6).length,0,'union bounds of a copy across materials contain lamp');
  const glassShade=new THREE.Group();glassShade.add(merged(['inside'],[.5]),
   merged(['inside'],[0],new THREE.MeshStandardMaterial({transparent:true})));
  assert.equal(modelOccluderMeshes(glassShade,plan,source,6).length,0,'containment uses the complete model bounds');
 },
 test_items_openings_and_root_integration() {
  const p={buildings:[{id:'b',items:[{id:'same',asset:'chair',host:{ground:true,at:[0,0]},casts_shadow:false}],
   openings:[{id:'door',model:'door'}]},{id:'other',items:[{id:'same',asset:'chair',host:{ground:true,at:[0,0]}}]}]};
  const models=new THREE.Group();
  for(const [buildingId,kind,pieceId] of [['b','item','same'],['other','item','same'],['b','opening','door']]) {
   const m=merged([pieceId],[2]);m.userData.snapRanges[0]={start:0,count:36,buildingId,kind,pieceId};models.add(m);
  }
  assert.deepEqual(ids(modelOccluderMeshes(models,p,source,6)),['item:other:same','opening:b:door']);
  const scene=new THREE.Scene(),neutral=new THREE.Group(),wall=new THREE.Mesh(box(4),opaque);
  wall.userData.merged=true;neutral.add(wall);
  const blockers=occluders({scene,plan:p,bake:{occlusionRoot:()=>neutral,modelRoot:()=>models}},source,6);
  assert.equal(blockers.children.length,3,'neutral structure plus the separate model root');
  assert.deepEqual(modelOccluderMeshes(null,p,source,6),[]);
 },
 async test_lazy_model_source_waits_and_releases() {
  const root=new THREE.Group(),models=new THREE.Group();let resolve,ready=false,started=0;
  const loaded=new Promise(r=>resolve=r);
  registerBakeSource(root,()=>new THREE.Group(),{
   modelReady:async()=>{started++;await loaded;ready=true;},modelRoot:()=>ready?models:null,
   dispose:()=>{ready=false;}
  });
  assert.equal(bakeModelRoot(root),null);
  const pending=prepareBakeModels(root);assert.equal(started,1);assert.equal(bakeModelRoot(root),null);
  resolve();await pending;assert.equal(bakeModelRoot(root),models);
  releaseBakeSource(root);assert.equal(bakeModelRoot(root),null);
  assert.equal(bakeModelRoot(new THREE.Group()),null,'unregistered sources have no model root');
 },
 async test_render_page_waits_before_building_shadow_cubes() {
  const scene=new THREE.Scene(),models=new THREE.Group();let ready=false,faces=0,waited=0,resolve;
  const loading=new Promise(r=>resolve=r);
  const view={scene,plan,bake:{modelRoot:()=>ready?models:null,
   modelReady:async()=>{waited++;await loading;models.add(merged(['near'],[2]));ready=true;}}};
  const renderer={xr:{enabled:false},toneMapping:THREE.NoToneMapping,autoClear:true,
   target:null,color:new THREE.Color(),alpha:1,
   getRenderTarget(){return this.target;},getClearColor(c){return c.copy(this.color);},getClearAlpha(){return this.alpha;},
   setRenderTarget(t){this.target=t;},setClearColor(c,a){this.color.set(c);this.alpha=a;},clear(){},
   render(s,c){if(s.overrideMaterial?.uniforms?.farPlane&&c.isPerspectiveCamera){
    assert.equal(ready,true);assert.deepEqual(ids(s.children),['furniture:near']);
    assert.deepEqual(s.children[0].geometry.drawRange,{start:0,count:36});faces++;
   }},readRenderTargetPixels(t,x,y,w,h,raw){raw.fill(THREE.DataUtils.toHalfFloat(1));}};
  const pending=renderPage(view,renderer,[],4,{absolute:true,at:[0,0,0],range:6/.3048},
   {room:{page:4}},{room:{charts:[]}});
  await Promise.resolve();assert.equal(waited,1);assert.equal(faces,0,'no depth cube before imports settle');
  resolve();const bytes=await pending;assert.equal(bytes.length,64);assert.equal(faces,16*6);
 }
};
let passed=0;for(const [name,test] of Object.entries(tests)){await test();console.log(`Passed: ${name}`);passed++;}
console.log(`${passed}/${Object.keys(tests).length} passed`);
"""

# Mount the actual editor/controller/provider path with real glTF imports. Only
# DOM, GPU and transport are doubled; source selection is production code.
MOUNTED_PREFIX = EDITOR_DRIVER[:EDITOR_DRIVER.index('const plan=input.plan')].replace(
    'if(globalThis.__holdYard && !args[3]?.bakeSource)',
    "if(args[3]?.modelSource){globalThis.__modelYardAttempts=(globalThis.__modelYardAttempts||0)+1;if(globalThis.__failModelYard)throw new Error();}if(globalThis.__holdYard && !args[3]?.bakeSource)")
MOUNTED = MOUNTED_PREFIX + r"""
const {rememberImport}=await import(file('static/twin/twin_library.js'));
const {modelOccluderMeshes}=await import(file('static/twin/bake/model_occluder_meshes.js'));
window.location={href:'http://house.test/house/editor'};window.chfBase='../';
globalThis.ProgressEvent=class {constructor(type,values){this.type=type;Object.assign(this,values);}};
const asset='import-'+'c'.repeat(32),vertices=new Float32Array([-1,0,-1,1,0,-1,0,2,1]);
const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],
 meshes:[{primitives:[{attributes:{POSITION:0}}]}],buffers:[{uri:'mesh.bin',byteLength:36}],
 bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-1,0,-1],max:[1,2,1]}]};
rememberImport({id:asset,model:'model.gltf',files:{'model.gltf':true,'mesh.bin':true,'mid.bin':true,'far.bin':true,'lod1.glb':true,'lod2.glb':true},
 lods:input.onlyLod2?[{name:'lod2.glb'}]:[{name:'lod1.glb'},{name:'lod2.glb'}],triangles:400000,size:[2,2,2]});
globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url;
 if(url.includes('materials/manifest'))return new Response('{"revision":0,"entries":{}}');
 const repeats=url.includes('mid.bin')||url.includes('lod1.glb')?2:url.includes('far.bin')||url.includes('lod2.glb')?3:1;
 const data=new Float32Array(Array.from({length:repeats},()=>Array.from(vertices)).flat()),model=structuredClone(doc);
 model.buffers[0]={uri:repeats===2?'mid.bin':repeats===3?'far.bin':'mesh.bin',byteLength:data.byteLength};
 model.bufferViews[0].byteLength=data.byteLength;model.accessors[0].count=data.length/3;
 return new Response(url.endsWith('.bin')?Buffer.from(data.buffer):JSON.stringify(model),{status:200});
};
const rect=[[0,0],[12,0],[12,12],[0,12]],plan={buildings:[{id:'b',position:[10,20],rotation:25,
 levels:[{id:'l',elevation:0,ceiling:8,outline:rect}],walls:[{id:'w',level:'l',from:[0,0],to:[12,0],thickness:.5,height:8}],
 rooms:[{id:'r',level:'l',polygon:rect}],roof:{sections:[]},
 openings:[{id:'door',kind:'door',model:asset,wall:'w',at:6,width:3,head:7,sill:0}],
 items:[{id:'chair',asset,host:{floor:'r',u:.5,v:.5}}]}],
 site:{furniture:[{id:'yard-chair',asset,at:[30,30]}]}};
const kit={materials:{},manifest:{}};
const editor=await mountTwin(host(true),{plan,kit,tier:input.editorTier||'high',bake:{api:async()=>new Promise(()=>{})}});
try {
 if(!input.failYard)await test('mounted_editor_models_'+(input.onlyLod2?'only_lod2':input.editorTier||'high'),async()=>{
  assert.ok(editor.bake,'real controller mounted');
  assert.equal(editor.bake.modelRoot(),null,'physical model source is lazy');
  const drawn=editor.scene.children.find(isBakeRoot),neutral=bakeSource(drawn);
  let neutralModels=0;neutral.traverse(m=>{if(m.geometry?.userData.bakeExcluded)neutralModels++;});
  assert.equal(neutralModels,0,'neutral atlas topology has no models');
  const yard=editor.scene.getObjectByName('yard'),original=[];
  yard.traverse(m=>{if(m.isMesh&&m.geometry?.userData.bakeExcluded)original.push(m);});
  assert.ok(original.length,'actual yard import');
  const before=new THREE.Box3();original.forEach(m=>before.union(new THREE.Box3().setFromObject(m)));
  let releases=0;original.forEach(m=>m.geometry.addEventListener('dispose',()=>releases++));
  const shown=original.map(m=>m.material);
  original.forEach(m=>{m.material=m.material.clone();m.material.transparent=true;m.material.opacity=.1;});
  await editor.bake.modelReady();
  const modelRoot=editor.bake.modelRoot();assert.ok(modelRoot);assert.equal(modelRoot.parent,null,'never drawn');
  const lods=[];modelRoot.traverse(o=>{if(o.isLOD)lods.push(o);});
  const midOwners=new Set();for(const lod of lods)lod.levels[1]?.object.traverse(m=>{if(m.isMesh)midOwners.add(m.userData.pieceId);});
  assert.deepEqual([...midOwners].sort(),input.onlyLod2?[]:['chair','door','yard-chair'],'only real mid LODs enter the source');
  const meshes=modelOccluderMeshes(modelRoot,plan,new THREE.Vector3(100,100,100),1000);
  assert.deepEqual([...new Set(meshes.map(m=>m.userData.modelCopyId))].sort(),
   ['furniture:yard-chair','item:b:chair','opening:b:door']);
  assert.ok(meshes.every(m=>m.geometry.drawRange.count===(input.onlyLod2?3:6)),
   'full mesh without lod1; actual lod1 with it, including low editor tier');
  const yardBlockers=meshes.filter(m=>m.userData.modelCopyId==='furniture:yard-chair'),after=new THREE.Box3();
  yardBlockers.forEach(m=>{m.updateMatrixWorld(true);after.union(new THREE.Box3().setFromObject(m));});
  assert.ok(after.min.distanceTo(before.min)<1e-5&&after.max.distanceTo(before.max)<1e-5,'yard world transform survives house scale');
  assert.equal(yardBlockers[0].material.transparent,false,'authored yard material, not its editor fade');
  editor.bake.stop();assert.equal(releases,0,'stopping a bake preserves the drawn yard buffers');
  original.forEach((m,i)=>m.material=shown[i]);
 });
 if(input.failYard)await test('yard_model_failure_keeps_pages_working_and_can_retry',async()=>{
  const {renderPage}=await import(file('static/twin/bake/bake_pass.js'));
  const warnings=[],warn=console.warn;console.warn=(...args)=>warnings.push(args);globalThis.__failModelYard=true;
  let faces=0;
  const renderer={xr:{enabled:false},toneMapping:THREE.NoToneMapping,autoClear:true,target:null,color:new THREE.Color(),alpha:1,
   getRenderTarget(){return this.target;},getClearColor(c){return c.copy(this.color);},getClearAlpha(){return this.alpha;},
   setRenderTarget(t){this.target=t;},setClearColor(c,a){this.color.set(c);this.alpha=a;},clear(){},
   render(s,c){if(s.overrideMaterial?.uniforms?.farPlane&&c.isPerspectiveCamera)faces++;},
   readRenderTargetPixels(t,x,y,w,h,raw){raw.fill(THREE.DataUtils.toHalfFloat(1));}};
  const view={scene:editor.scene,plan,bake:{modelReady:()=>editor.bake.modelReady(),modelRoot:()=>editor.bake.modelRoot()}};
  const page=()=>renderPage(view,renderer,[],4,{absolute:true,at:[0,0,6],range:30},{room:{page:4}},{room:{charts:[]}});
  const copyIds=()=>[...new Set(modelOccluderMeshes(editor.bake.modelRoot(),plan,new THREE.Vector3(100,100,100),1000)
   .map(m=>m.userData.modelCopyId))].sort();
  try {
   for(let i=0;i<2;i++)assert.equal((await page()).length,64,'page completes despite yard failure');
   assert.equal(globalThis.__modelYardAttempts,2,'failed job cleared between pages');assert.equal(warnings.length,1,'warn once');
   assert.deepEqual(copyIds(),['item:b:chair','opening:b:door'],'house models still occlude');
   globalThis.__failModelYard=false;await page();assert.equal(globalThis.__modelYardAttempts,3);
   assert.ok(copyIds().includes('furniture:yard-chair'),'retry restores yard occluders');
   await page();assert.equal(globalThis.__modelYardAttempts,3,'successful source reused');assert.equal(faces,4*16*6);
  }finally{console.warn=warn;globalThis.__failModelYard=false;}
 });
} finally {editor.dispose();}
finish();
"""


INPUTS_DRIVER = PREFIX + r"""
const parts=await import(file('static/twin/model_parts.js'));
const models=await import(file('static/twin/bake/model_occluders.js'));
const {placedCopies,occluderHash,MODEL_REACH_MARGIN_M}=models;
const {lightSource}=await import(file('static/twin/bake/reach.js'));
const {lightKey,bakeLayout}=await import(file('static/twin/bake/baker.js'));
const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
const input=JSON.parse(readFileSync(process.argv[2]));
const plan=structuredClone(input.household),asset='import-'+'d'.repeat(32),main=plan.buildings[0],pool=plan.buildings[1];
for(const b of [main,pool])b.items=[{id:'bake-model',asset,host:{floor:b.rooms[0].id,u:.5,v:.5}}];
pool.openings[0].model=asset;
const lamps=plan.buildings.flatMap(b=>b.rooms.map(r=>{
 const a=(b.rotation||0)*Math.PI/180,p=b.position||[0,0],l=b.levels.find(l=>l.id===r.level);
 const x=r.polygon.reduce((s,v)=>s+v[0],0)/r.polygon.length,y=r.polygon.reduce((s,v)=>s+v[1],0)/r.polygon.length;
 return {device:b.id+':'+r.id,building:b.id,level:r.level,room:r.id,
 at:[p[0]+Math.cos(a)*x-Math.sin(a)*y,p[1]+Math.sin(a)*x+Math.cos(a)*y,(b.base||0)+(l.elevation||0)+6]};
}));
const materials={oak:{id:'oak',params:{}},walnut:{id:'walnut',params:{}},glass:{id:'glass',params:{alpha_mode:'blend'}}};
const record=()=>({parts:[{key:'Wood',has_uv:true,opaque:true}],lod_percent:[100,25,5],lods:[{name:'lod1.glb',percent:25,revision:1}]});
const inputs=records=>c=>parts.occluderInputs(records[c.asset],c.model_materials,materials);
const keys=(records={},callback=inputs(records))=>Object.fromEntries(lamps.map(l=>{
 const {source,range}=lightSource(plan,l),occluders=occluderHash(placedCopies(plan),source,range,...(callback===null?[]:[callback]));
 return [l.device,{occluders,key:lightKey({key:'household-receivers'},{...l,reach:'household-receivers',occluders},{bank:0,channel:0})}];
}));
const affected=copies=>lamps.filter(l=>{const {source,range}=lightSource(plan,l);
 return copies.some(c=>c.at.reduce((s,v,i)=>s+(v-source.getComponent(i))**2,0)<=(range+MODEL_REACH_MARGIN_M)**2);
}).map(l=>l.device).sort();
const changed=(a,b)=>Object.keys(a).filter(id=>a[id].key!==b[id].key).sort();
const checkChange=(records,copies)=>{
 const expected=affected(copies);assert.ok(expected.length&&expected.length<lamps.length,'both near and far lamps');
 assert.deepEqual(changed(keys(),keys(records)),expected);
};
const tests={
 hash_unchanged_without_inputs(){
  assert.deepEqual(keys({},null),input.golden,'33 household lamp keys captured before the implementation; no inputs argument');
  assert.deepEqual(keys({},()=>''),input.golden);
  assert.deepEqual(keys({[asset]:{}}),input.golden);
  assert.deepEqual(keys({[asset]:record()}),input.golden,'merely regenerated mid stays legacy');
  assert.deepEqual(keys({},()=>undefined),input.golden);
 },
 fix_stales_only_near_lamps(){
  for(const fix of [{turn:90},{height_m:.8},{width_m:1.2}])checkChange({[asset]:{...record(),fix}},placedCopies(plan));
 },
 mid_revision_stales(){
  const r=record();r.lods[0].revision=2;checkChange({[asset]:r},placedCopies(plan));
  const p=record();p.lod_percent[1]=40;checkChange({[asset]:p},placedCopies(plan));
 },
 glass_override_stales(){
  main.items[0].model_materials={Wood:{material:'glass'}};
  try{checkChange({[asset]:record()},placedCopies(plan).filter(c=>c.id==='item:'+main.id+':bake-model'));}
  finally{delete main.items[0].model_materials;}
 },
 colour_override_keeps_keys(){
  const before=authoredGeometry(plan);
  for(const material of ['oak','walnut'])for(const texture of ['real','model']){
   const r={...record(),materials:{Wood:{material,texture,tiles:4}},lod_percent:[60,25,2]};
   assert.deepEqual(keys({[asset]:r}),input.golden);
   main.items[0].model_materials={Wood:{material,texture,tiles:3}};
   assert.equal(authoredGeometry(plan),before);assert.deepEqual(keys({[asset]:r}),input.golden);
   delete main.items[0].model_materials;
  }
  const r={...record(),materials:{Wood:{material:'glass'}}};
  main.items[0].model_materials={Wood:{material:'original'}};
  try{assert.equal(inputs({[asset]:r})(placedCopies(plan).find(c=>c.id==='item:'+main.id+':bake-model')),'');}
  finally{delete main.items[0].model_materials;}
 },
 opening_model_in_hash(){
  const o=pool.openings[0],id='opening:'+pool.id+':'+o.id;
  const c=placedCopies(plan).find(c=>c.id===id);assert.ok(c,'opening appears in placedCopies');
  assert.equal(c.asset,asset);assert.deepEqual(c.scale,[1,1,1]);
  o.model_materials={Wood:{material:'glass'}};
  try{checkChange({[asset]:record()},[c]);}finally{delete o.model_materials;}
 },
 opening_centres_use_shared_floor_reference(){
  const p={buildings:[{id:'b',position:[10,20],rotation:90,base:0,
   levels:[{id:'l',elevation:2}],walls:[{id:'w',level:'l',from:[0,0],to:[10,0],thickness:.5}],
   rooms:[{id:'r',level:'l',polygon:[[0,-2],[10,-2],[10,2],[0,2]],floor_offset_ft:-1}],
   openings:[{id:'o',wall:'w',at:4,width:2,sill:1,head:7,model:asset,casts_shadow:false}],
   roof:{sections:[{id:'g',kind:'gable',ridge:'x',rect:[0,0,10,8],plate:10}]}}]};
  const c=placedCopies(p)[0];
  assert.deepEqual(c.at,[10*.3048,5*.3048,-24*.3048]);assert.deepEqual(c.rot,[0,90,0]);assert.equal(c.castsShadow,false);
  const opening=p.buildings[0].openings[0];delete opening.head;opening.height=6;
  assert.deepEqual(placedCopies(p)[0].at,c.at,'height-only openings keep the same shared floor offset');
  p.buildings[0].openings=[{id:'g',section:'g',gable:'rear',y:3,sill:1,head:3,model:asset}];
  const g=placedCopies(p)[0];assert.ok(g);assert.deepEqual(g.at,[7*.3048,12*.3048,-30*.3048]);
  p.buildings[0].openings=[{id:'missing',wall:'missing',model:asset}];assert.deepEqual(placedCopies(p),[]);
 },
 async model_records_loader_falls_back(){
  assert.equal(typeof models.modelRecords,'function');let count=0;
  const loaded=await models.modelRecords(async path=>{count++;assert.equal(path,'api/house/models');
   return new Response(JSON.stringify({models:[{id:asset,...record()}]}));});
  assert.equal(count,1);assert.deepEqual(loaded[asset],{id:asset,...record()});
  assert.deepEqual(await models.modelRecords(async()=>new Response('',{status:404})),{});
  for(const api of [async()=>new Response('',{status:500}),
   async()=>{throw new TypeError('offline');},async()=>new Response('bad json'),async()=>new Response('{}')])
   assert.equal(await models.modelRecords(api),null,'unavailable is distinct from a missing route');
  await assert.rejects(models.modelRecords(async()=>new Response('',{status:401})),{status:401});
  await assert.rejects(models.modelRecords(async()=>{throw Object.assign(new Error('auth'),{status:401});}),{status:401});
 },
 async bake_layout_uses_record_and_copy_inputs(){
  const THREE=await import(three),{buildTwin}=await import(file('static/twin/twin_generator.js'));
  const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
  const p=structuredClone(plan);p.buildings=[p.buildings[1]];delete p.site;
  const receivers=structuredClone(p);receivers.buildings[0].items=[];
  for(const o of receivers.buildings[0].openings)delete o.model;
  const built=buildTwin(receivers,kit,'low',{viewing:true});await built.ready;built.root.updateMatrixWorld(true);
  const layout={room:{density:1,page:256,gutter:2}},atlas=buildAtlas(built.root,p,layout),ls=lamps.filter(l=>l.building===pool.id);
  const a=bakeLayout(atlas,layout,ls),r={...record(),fix:{turn:90}};
  const b=bakeLayout(atlas,layout,ls,null,{}, {[asset]:r},materials);
  assert.ok(Object.keys(a.entries).length);
  for(const l of b.lights){const {source,range}=lightSource(p,l);
   assert.equal(l.occluders,occluderHash(placedCopies(p),source,range,inputs({[asset]:r})));
   if(b.entries[l.device]){assert.notEqual(b.entries[l.device].key,a.entries[l.device].key);
    assert.equal(b.entries[l.device].grid,a.entries[l.device].grid);
    assert.equal(b.entries[l.device].occluders,l.occluders,'editor evidence persists with each entry');}
  }
 }
};
let failed=0;for(const [name,test] of Object.entries(tests)){
 try{await test();console.log('Passed: '+name);}catch(e){failed++;console.error('FAIL '+name,e.stack);}
}if(failed)process.exit(1);
"""

# Execute the real runtime's private editorFreshness through mountBake, and the
# real viewer controller against pages produced by the baker's existing fakes.
FRESHNESS_DRIVER = RUNTIME_DRIVER[:RUNTIME_DRIVER.index('let passed = 0, ran = 0')] + r"""
{
globalThis.fetch=async()=>new Response('',{status:404});
const asset='import-'+'e'.repeat(32),plan=structuredClone(job.plan),pool=plan.buildings.find(b=>b.id===job.pool);
pool.items=[{id:'one',asset,host:{floor:job.kitchen,u:.3,v:.3}},
 {id:'two',asset,host:{floor:job.kitchen,u:.7,v:.7}}];
pool.openings[0].model=asset;
let records=[{id:asset,parts:[{key:'Wood',has_uv:true,opaque:true}]}],reads=0;
const api=(path,init,next)=>path==='api/house/models'
 ?(reads++,Promise.resolve(new Response(JSON.stringify({models:records})))):next(path,init);
const placed=[k1,h1,{...k1,device:'far',at:[30,35,6]}];
const first=await context('high',null,placed,{plan,api,poll:0});let editor,viewer;
try{
 await until(()=>first.controller.state().done===3&&!first.controller.state().baking,'initial published bake');
 assert.equal(reads,1,'one catalog fetch shared by runtime and baker per bake');
 const server=first.server,key=first.controller.state().key;first.controller.stop();
 const legacy=structuredClone(server.manifests.get(key));
 assert.ok(Object.values(legacy.lights).every(e=>typeof e.occluders==='string'),'stored hash for the cheap editor check');
 records=[{...records[0],fix:{turn:90}}];
 editor=await context('high',server,placed,{plan,api,mode:'manual',display:false,poll:0});
 viewer=await context('high',server,placed,{plan,api,mode:'readonly',poll:0});
 await editor.controller.refresh();await viewer.controller.refresh();
 assert.equal(editor.controller.state().total,3);assert.equal(viewer.controller.state().key,key);
 const expected=viewer.controller.state().stale.slice().sort();
 assert.ok(expected.length&&expected.length<3,'fix affects only near lamps');
 assert.deepEqual(editor.controller.state().stale.slice().sort(),expected);
 console.log('Passed: editor_freshness_matches_viewer');
 // A catalog edit under an unchanged bake manifest must refresh both controllers.
 records=[{id:asset,parts:[{key:'Wood',has_uv:true,opaque:true}]}];
 await editor.controller.refresh();await viewer.controller.refresh();
 assert.deepEqual(editor.controller.state().stale,[]);assert.deepEqual(viewer.controller.state().stale,[]);
 console.log('Passed: catalog_refresh_without_manifest_change');
 // Legacy manifests had no explicit hash: empty new inputs still preserve freshness.
 const old=structuredClone(legacy);for(const e of Object.values(old.lights))delete e.occluders;
 server.manifests.set(key,old);await editor.controller.refresh();
 assert.deepEqual(editor.controller.state().stale,[]);
 records=[{...records[0],fix:{turn:90}}];await editor.controller.refresh();
 assert.deepEqual(editor.controller.state().stale.slice().sort(),expected);
 console.log('Passed: legacy_editor_hash_fallback');
 records=[{id:asset,parts:[{key:'Wood',has_uv:true,opaque:true}]}];
 const wrong=structuredClone(legacy);for(const e of Object.values(wrong.lights))e.gridLayout='wrong-layout';
 server.manifests.set(key,wrong);await editor.controller.refresh();
 assert.match(editor.host.textContent,/Lighting grid out of date: 2 lights/);
 assert.deepEqual(editor.controller.state().stale,[],'grid mismatch does not discard valid pages');
 console.log('Passed: editor_checks_grid_layout');
}finally{first.controller.stop();editor?.controller.stop();viewer?.controller.stop();}
}
process.exit(0);
"""


# Count calls to the real layout implementation; renderer/transport stay the
# existing doubles. This catches catalog-only rebuilds without replacing logic.
FIX_ROUND_PREFIX = RUNTIME_DRIVER[:RUNTIME_DRIVER.index('let passed = 0, ran = 0')].replace(
    "if (!worker) return { ...loaded, format: 'module' };", r"""
    if (!worker && bare.endsWith('/bake/baker.js')) {
      const source=typeof loaded.source==='string'?loaded.source:new TextDecoder().decode(loaded.source);
      return {...loaded,format:'module',source:source.replace('export function bakeLayout(', 'function bakeLayoutImpl(')+
        '\nexport function bakeLayout(...args){(globalThis.__catalogLayouts ||= []).push(args[5]);return bakeLayoutImpl(...args);}'};
    }
    if (!worker) return { ...loaded, format: 'module' };
""")
FIX_ROUND_DRIVER = FIX_ROUND_PREFIX + r"""
{
globalThis.fetch=async()=>new Response('',{status:404});
const asset='import-'+'f'.repeat(32),plan=structuredClone(job.plan),b=plan.buildings.find(b=>b.id===job.pool);
b.items=[{id:'fixed',asset,host:{floor:job.kitchen,u:.5,v:.5}}];
const fixed={id:asset,revision:1,fix:{turn:90},parts:[{key:'Wood',has_uv:true,opaque:true}]};
let records=[fixed],status=200,reads=0;
const api=(path,init,next)=>path==='api/house/models'
 ?(reads++,Promise.resolve(new Response(status===200?JSON.stringify({models:records}):'',{status}))):next(path,init);
const placed=[k1,h1];let failed=0;
const check=async(name,fn)=>{for(const [map,saved] of storedMaps){map.clear();for(const [k,v] of saved)map.set(k,structuredClone(v));}
 try{await fn();console.log('Passed: '+name);}catch(e){failed++;console.error('FAIL '+name,e.stack);}};
const first=await context('high',null,placed,{plan,api,poll:0});
await until(()=>first.controller.state().done===2&&!first.controller.state().baking,'published fixed-model bake');
const server=first.server,key=first.controller.state().key,baseline=structuredClone(server.manifests.get(key));
const storedMaps=[server.manifests,server.pages,server.grids,server.etags].map(map=>[map,new Map(structuredClone([...map]))]);
first.controller.stop();
await check('initialize_fetches_snapshot_in_all_modes',async()=>{
 assert.equal(reads,1,'auto initialize and run share one catalog read');
 assert.ok(__catalogLayouts.length&&__catalogLayouts.every(r=>r?.[asset]?.fix?.turn===90),
  'auto initialization must use the fetched snapshot too');
});
async function panel(extra={}){
 const c=await context('high',server,placed,{plan,api,poll:0,mode:'readonly',...extra});
 await c.controller.refresh();return c;
}
await check('catalog_blip_keeps_snapshot',async()=>{
 const c=await panel();try{
  assert.deepEqual(c.controller.fresh().sort(),['h1','k1']);const before=c.controller.held();status=500;
  await c.controller.refresh();assert.deepEqual(c.controller.fresh().sort(),['h1','k1']);
  assert.deepEqual(c.controller.state().stale,[]);assert.deepEqual(c.controller.held().ids,before.ids);
  assert.deepEqual(c.controller.held().versions,before.versions,'no blanking/upload of the held baked textures');
 }finally{status=200;c.controller.stop();}
});
await check('colour_edit_no_recheck',async()=>{
 const c=await panel();try{
  let calls=server.calls.length;await c.controller.refresh();
  const routinePages=server.calls.slice(calls).filter(c=>c.path.endsWith('.png')).map(c=>[c.path,c.inm,c.full]);
  const layouts=__catalogLayouts.length;calls=server.calls.length;
  records=[{...fixed,revision:2,materials:{Wood:{material:'walnut',texture:'model',tiles:3}}}];
  await c.controller.refresh();assert.equal(__catalogLayouts.length,layouts,'opaque colour/texture edits do not rebuild bakeLayout');
  assert.deepEqual(server.calls.slice(calls).filter(c=>c.path.endsWith('.png')).map(c=>[c.path,c.inm,c.full]),routinePages,
   'no extra page validation beyond the existing conditional poll');
  assert.deepEqual(c.controller.state().stale,[]);
  records=[{...records[0],revision:3,fix:{turn:180}}];await c.controller.refresh();
  assert.ok(__catalogLayouts.length>layouts,'turn changes rebuild the exact keys');assert.ok(c.controller.state().stale.length);
 }finally{records=[fixed];c.controller.stop();}
});
await check('bake_refuses_without_catalog',async()=>{
 const c=await panel({mode:'manual',display:false});const error=console.error;console.error=()=>{};
 try{
  status=500;const writes=server.writes().length;await c.controller.start();
  assert.match(c.controller.state().error||'',/model.*(catalog|record)|catalog/i);
  assert.ok(c.controller.state().retryAt,'usual retryable bake error');
  assert.equal(server.writes().length,writes,'no pages, grids or manifest published with a guessed snapshot');
 }finally{status=200;console.error=error;c.controller.stop();}
});
await check('catalog_401_pauses_auth',async()=>{
 const c=await panel({mode:'manual',display:false});const error=console.error;console.error=()=>{};
 try{
  status=401;const writes=server.writes().length;await c.controller.start();
  assert.ok(c.controller.state().paused);assert.match(c.controller.state().error||'',/HTTP 401/);
  assert.match(c.host.textContent,/signed this tab out.*Resume/);assert.equal(c.controller.state().retryAt,null);
  assert.equal(server.writes().length,writes);
 }finally{status=200;console.error=error;c.controller.stop();}
});
await check('one_catalog_read_manual_and_readonly',async()=>{
 for(const mode of ['manual','readonly']){
  reads=0;const c=await panel({mode,display:mode!=='manual'});
  try{
   assert.equal(reads,1,mode+' initialization reads once');
   assert.deepEqual(c.controller.state().stale,[],'initial freshness uses fixed record');
   if(mode==='manual'){
    reads=0;await c.controller.now();assert.equal(reads,1,'one fresh snapshot for a pressed manual bake');
    assert.deepEqual(c.controller.state().stale,[]);
    for(const [id,e] of Object.entries(server.manifests.get(key).lights))assert.equal(e.key,baseline.lights[id].key);
   }
  }finally{c.controller.stop();}
 }
});
if(failed)process.exit(1);
}
process.exit(0);
"""


OUTAGE_DRIVER = FIX_ROUND_PREFIX + r"""
{
globalThis.fetch=async()=>new Response('',{status:404});
const asset='import-'+'a'.repeat(32),plan=structuredClone(job.plan),b=plan.buildings.find(b=>b.id===job.pool);
b.items=[{id:'fixed',asset,host:{floor:job.kitchen,u:.5,v:.5}}];
const pos=[(b.position?.[0]||0)+200,b.position?.[1]||0],rect=[[0,0],[10,0],[10,10],[0,10]];
plan.buildings.push({id:'legacy-building',position:pos,rotation:0,base:0,
 levels:[{id:'L1',elevation:0,ceiling:8,outline:rect}],walls:[],
 rooms:[{id:'legacy-room',level:'L1',polygon:rect}],openings:[],roof:{sections:[]}});
const fixed={id:asset,fix:{turn:90},parts:[{key:'Wood',has_uv:true,opaque:true}]};
let status=200,reads=0;
const api=(path,init,next)=>{
 if(path!=='api/house/models')return next(path,init);
 reads++;return status==='offline'?Promise.reject(new TypeError('catalog offline')):
  Promise.resolve(new Response(status===200?JSON.stringify({models:[fixed]}):'',{status}));
};
const placed=[k1,h1,{device:'legacy',building:'legacy-building',level:'L1',room:'legacy-room',at:[pos[0]+5,pos[1]+5,6]}];
const first=await context('high',null,placed,{plan,api,poll:0});
await until(()=>first.controller.fresh().length===3&&!first.controller.state().baking,'mixed legacy and fixed-model bake');
const server=first.server,key=first.controller.state().key,baseline=structuredClone(server.manifests.get(key));
const storedMaps=[server.manifests,server.pages,server.grids,server.etags].map(map=>[map,new Map(structuredClone([...map]))]);
first.controller.stop();let failed=0;
async function check(name,fn){
 for(const [map,saved] of storedMaps){map.clear();for(const [k,v] of saved)map.set(k,structuredClone(v));}
 try{await fn();console.log('Passed: '+name);}catch(e){failed++;console.error('FAIL '+name,e.stack);}
 finally{status=200;}
}
await check('mount_during_catalog_outage_stays_lit',async()=>{
 for(const mode of ['readonly','manual'])for(const failure of [500,'offline']){
  status=failure;reads=0;const errors=[],log=console.error;console.error=(...args)=>errors.push(args);
  const c=await context('high',server,placed,{plan,api,poll:0,mode,display:mode!=='manual'});
  try{
   await c.controller.refresh();assert.equal(reads,1);
   assert.equal(c.controller.state().error,null);assert.equal(errors.length,0,'catalog-only outage is silent at mount');
   assert.deepEqual(c.controller.fresh(),['legacy'],'unaffected legacy lamp stays baked');
   assert.deepEqual(c.controller.state().stale.slice().sort(),['h1','k1'],'unknown new inputs stay stale');
   assert.ok(!c.host.textContent.includes('Could not read baked lighting'));
   if(mode==='readonly')assert.ok(c.controller.held(),'legacy pages are loaded into the viewer');
   status=200;await c.controller.refresh();assert.equal(reads,2);
   assert.deepEqual(c.controller.fresh().sort(),['h1','k1','legacy'],'first successful poll adopts the fixed record');
  }finally{console.error=log;c.controller.stop();}
 }
});
await check('press_after_unconfirmed_mount_refetches',async()=>{
 status=500;reads=0;
 // One genuinely stale stored lamp ensures the press exercises publication.
 server.manifests.get(key).lights.k1.key='0'.repeat(32);
 const c=await context('high',server,placed,{plan,api,poll:0,mode:'manual',display:false});
 try{
  await c.controller.refresh();assert.equal(reads,1);assert.equal(c.controller.state().error,null);
  const layouts=__catalogLayouts.length,writes=server.writes().length;
  status=200;await c.controller.start();assert.equal(reads,2,'one unconfirmed mount read and one confirmed press read');
  assert.equal(c.controller.state().error,null);assert.equal(c.controller.state().done,3);
  assert.ok(server.writes().length>writes,'stale lamp was actually baked and published');
  const used=__catalogLayouts.slice(layouts);assert.ok(used.length);
  assert.ok(used.every(r=>r?.[asset]?.fix?.turn===90),'no pressed layout uses the unconfirmed empty map');
  for(const [id,e] of Object.entries(server.manifests.get(key).lights))assert.equal(e.key,baseline.lights[id].key);
 }finally{c.controller.stop();}
});
await check('press_with_catalog_404_bakes',async()=>{
 status=500;reads=0;const c=await context('high',server,placed,{plan,api,poll:0,mode:'manual',display:false});
 try{
  await c.controller.refresh();assert.equal(reads,1);assert.equal(c.controller.state().error,null);
  status=404;const writes=server.writes().length;await c.controller.start();
  assert.equal(reads,2);assert.equal(c.controller.state().error,null);assert.equal(c.controller.state().done,3);
  assert.ok(server.writes().length>writes,'old server completes the legacy bake');
  const {placedCopies,occluderHash}=await import(file('static/twin/bake/model_occluders.js'));
  const {lightSource}=await import(file('static/twin/bake/reach.js'));
  for(const l of placed){const {source,range}=lightSource(plan,l),e=server.manifests.get(key).lights[l.device];
   assert.equal(e.occluders,occluderHash(placedCopies(plan),source,range));
   assert.equal(e.key,c.controller.packing().entries[l.device].key);
  }
  assert.notEqual(server.manifests.get(key).lights.k1.key,baseline.lights.k1.key,'fixed-model key reverted to legacy identity');
 }finally{c.controller.stop();}
});
if(failed)process.exit(1);
}
process.exit(0);
"""


def run():
    payload = {'root': ROOT.as_posix(), 'flat': {}, 'kit': {'manifest': {}},
               'household': json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')),
               'golden': json.loads((ROOT / 'tests/fixtures/twin_model/model-bake-keys-legacy.json').read_text(encoding='utf-8'))}
    code, out = run_node(INPUTS_DRIVER, payload, timeout=120)
    print(out, end='')
    if code:
        raise AssertionError('Model occluder inputs tests failed')
    import test_twin_baker_js as B
    job = {'root': ROOT.as_posix(), 'plan': B.household_pool_house(),
           'kit': {**B.tl.kit('modern_farmhouse'), 'manifest': {}}, 'layout': B.LAYOUT,
           'pool': B.POOL, 'kitchen': B.KITCHEN, 'hall': B.HALL, 'changing': B.CHANGING}
    code, out = run_node(FRESHNESS_DRIVER, job, timeout=180)
    print(out, end='')
    if code:
        raise AssertionError('Editor/viewer model freshness tests failed')
    code, out = run_node(FIX_ROUND_DRIVER, job, timeout=180)
    print(out, end='')
    if code:
        raise AssertionError('Fix round 1 catalog regressions failed')
    code, out = run_node(OUTAGE_DRIVER, job, timeout=180)
    print(out, end='')
    if code:
        raise AssertionError('Fix round 2 mount outage regressions failed')
    with tempfile.TemporaryDirectory(prefix='chauffeur_model_occluders_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': {'manifest': {}}}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    failed = []
    for case in [{}, {'onlyLod2': True}, {'editorTier': 'low'}, {'failYard': True}]:
        code, out = run_node(MOUNTED, {'root': ROOT.as_posix(), **case}, timeout=120)
        print(out, end='')
        if code:
            failed.append(case)
    if failed:
        raise AssertionError(f'Mounted editor model-source tests failed: {failed}')


if __name__ == '__main__':
    run()
