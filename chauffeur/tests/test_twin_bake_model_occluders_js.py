"""Executed Node proof for per-copy model selection and the bake-source handoff."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT
from twin_editor_dom import run_node
from test_twin_bake_editor_source_js import DRIVER as EDITOR_DRIVER

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


def run():
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
