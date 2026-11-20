"""One scene walk and world-matrix pass per frame; static viewer locals. Mounted twin under Node (no GPU).

Owner trace 2026-11-20 (v2.499.953, live house, idle camera): three's per-render
updateMatrixWorld was 13% of every frame, because a frame renders the scene five
or more times (mirror, AO, beauty, transparent, shadow faces). twin_view's
render() now updates once and turns the scene's auto update off for its passes.

Run from chauffeur/: python tests/test_twin_frame_matrices_js.py
"""
import json
from pathlib import Path
import sys
from test_twin_yard_reuse_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
// The renderer double recomputes matrices on every render; three does that
// only while scene.matrixWorldAutoUpdate is on. Mimic r187 here, including
// what fooled the v2.499.954 gate: info.render.frame rises on EVERY render
// call, then the scene's onBeforeRender runs.
Renderer.prototype.render=function(scene,camera){
 this.info.render.frame=(this.info.render.frame||0)+1;
 if(scene.matrixWorldAutoUpdate)scene.updateMatrixWorld();
 scene.onBeforeRender?.(this,scene,camera);};
const {mountTwin}=await import(file('static/twin/twin_view.js'));
await test('one world-matrix pass per frame; the passes reuse it',async()=>{
 const view=await mountTwin(new Element(),{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false});
 try {
  const scene=view.scene,renderer=view.renderer3;let updates=0;
  const update=scene.updateMatrixWorld.bind(scene);scene.updateMatrixWorld=force=>{updates++;return update(force);};
  const flags=[],draw=renderer.render;renderer.render=function(s,c){if(s===scene)flags.push(s.matrixWorldAutoUpdate);return draw.call(this,s,c);};
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());scene.add(mesh);mesh.position.set(3,4,5);
  view.render();
  assert.ok(flags.length>=1,'the frame rendered the scene');
  assert.ok(flags.every(f=>f===false),'no pass recomputes matrices: '+JSON.stringify(flags));
  assert.equal(updates,1,'one update for the whole frame');
  assert.equal(scene.matrixWorldAutoUpdate,true,'restored after the frame');
  assert.deepEqual(new THREE.Vector3().setFromMatrixPosition(mesh.matrixWorld).toArray(),[3,4,5],'a moved object is current in the frame');
  // The environment installers walk the scene once per twin frame, however many
  // passes render it (each pass bumps three's own frame counter).
  let walks=0;const traverse=scene.traverse.bind(scene);
  scene.traverse=cb=>{walks++;return traverse(cb);};
  view.render();const perFrame=walks;
  assert.equal(perFrame,1,'one shared walk across installers, wind, seasons and post');
  for(let i=0;i<4;i++)renderer.render(scene,view.camera||new THREE.PerspectiveCamera());
  assert.equal(walks,perFrame,'later passes of the same frame do not walk again');
  view.render();assert.equal(walks,2*perFrame,'the next frame walks again');
  scene.traverse=traverse;
  // A pass that throws still restores the flag.
  renderer.render=()=>{throw new Error('pass failed');};
  assert.throws(()=>view.render());assert.equal(scene.matrixWorldAutoUpdate,true,'restored after a failed pass');
 } finally {view.dispose();}
});
const {frameObjects,startEnvironmentFrame,installStageHaze}=await import(file('static/twin/sky/stage_haze.js'));
const {installCloudShadow}=await import(file('static/twin/sky/cloud_shadow.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
const {installPlantWind}=await import(file('static/twin/sky/wind.js'));
const {installSeasons}=await import(file('static/twin/sky/seasons.js'));
const {createCloudUniforms}=await import(file('static/twin/sky/clouds.js'));
await test('shared pre-order includes hidden branches; mutations land next frame; roots stay fresh',()=>{
 const scene=new THREE.Scene(),a=new THREE.Group(),b=new THREE.Group(),c=new THREE.Group();
 scene.add(a,b);a.add(c);a.visible=false;
 let walks=0;const traverse=scene.traverse.bind(scene);scene.traverse=cb=>{walks++;traverse(cb);};
 const fresh=()=>{const list=[];traverse(o=>list.push(o));return list;};
 assert.deepEqual(frameObjects(scene),fresh());assert.deepEqual(frameObjects(scene),fresh());assert.equal(walks,2,'uncounted scenes walk every time');
 startEnvironmentFrame(scene);const snapshot=frameObjects(scene);assert.deepEqual(snapshot,fresh());assert.equal(walks,3);
 const late=new THREE.Group();a.add(late);b.removeFromParent();
 assert.equal(frameObjects(scene),snapshot);assert.ok(!snapshot.includes(late));assert.ok(snapshot.includes(b));
 assert.deepEqual(frameObjects(a),[a,c,late],'a subtree has no scene snapshot');
 assert.deepEqual(frameObjects(scene,{fresh:true}),fresh(),'explicit warm-up can bypass the scene snapshot');
 startEnvironmentFrame(scene);assert.deepEqual(frameObjects(scene),fresh());assert.ok(frameObjects(scene).includes(late));assert.ok(!frameObjects(scene).includes(b));
 const other=new THREE.Scene();other.add(new THREE.Group());assert.deepEqual(frameObjects(other),other.children.length?[other,...other.children]:[other]);
});
await test('all five installers match the old explicit traverse, including arrays, hidden objects and shadow pairs',()=>{
 function fixture(){
  const scene=new THREE.Scene(),hidden=new THREE.Group();hidden.visible=false;scene.add(hidden);
  const mats=[new THREE.MeshStandardMaterial(),new THREE.MeshLambertMaterial(),new THREE.MeshPhongMaterial(),new THREE.MeshToonMaterial(),new THREE.MeshBasicMaterial(),new THREE.ShaderMaterial({uniforms:{light:{value:1}}})];
  mats[0].userData={seasonFoliage:true,plantWind:'leaves'};mats[1].userData={seasonLawn:true};mats[2].userData={waterSurface:true};mats[3].userData={underwater:true};mats[4].fog=false;
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(),mats);mesh.castShadow=true;hidden.add(mesh);
  const own=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial({name:'roof'}));own.visible=false;scene.add(own);
  const installers=[installStageHaze(scene,{horizon:()=>new THREE.Color(.1,.2,.3)}),installCloudShadow(scene,{uniforms:createCloudUniforms()}),installWeatherSurface(scene),installPlantWind(scene),installSeasons(scene)];
  return {scene,installers,mesh};
 }
 const old=fixture(),shared=fixture();
 const census=scene=>{const out=[];scene.traverse(o=>{for(const m of [...[].concat(o.material||[]),o.customDepthMaterial,o.customDistanceMaterial].filter(Boolean))out.push([m.type,m.customProgramCacheKey(),m.defaultAttributeValues,!!o.customDepthMaterial,!!o.customDistanceMaterial]);});return out;};
 try{
  // Explicit prepare(root) is the original fresh-traverse reference path.
  old.installers.forEach(i=>i.prepare(old.scene));
  let walks=0;const traverse=shared.scene.traverse.bind(shared.scene);shared.scene.traverse=cb=>{walks++;return traverse(cb);};
  startEnvironmentFrame(shared.scene);shared.installers[3].update(1,{windMps:5},180);shared.installers[4].update({presence:.5,autumn:.7,spring:.1,dormancy:.4});
  shared.scene.onBeforeRender({getRenderTarget:()=>null,toneMappingExposure:1});
  assert.equal(walks,1);assert.deepEqual(census(shared.scene),census(old.scene));
  const late=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());shared.mesh.add(late);
  shared.installers.forEach(i=>i.prepare());assert.equal(late.material.customProgramCacheKey().includes('|stage-haze-1'),false,'mid-frame additions wait');
  startEnvironmentFrame(shared.scene);shared.installers.forEach(i=>i.prepare());assert.ok(late.material.customProgramCacheKey().includes('|stage-haze-1'));
  const subtree=new THREE.Group(),inside=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()),outside=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());subtree.add(inside);shared.scene.add(subtree,outside);
  let subtreeWalks=0;const subtreeTraverse=subtree.traverse.bind(subtree);subtree.traverse=cb=>{subtreeWalks++;return subtreeTraverse(cb);};
  shared.installers.forEach(i=>i.prepare(subtree));assert.equal(subtreeWalks,5,'every explicit subtree prepare walks');
  assert.ok(inside.material.customProgramCacheKey().includes('|stage-haze-1'));assert.ok(!outside.material.customProgramCacheKey().includes('|stage-haze-1'));
  shared.installers.forEach(i=>i.prepare(shared.scene));assert.ok(outside.material.customProgramCacheKey().includes('|stage-haze-1'),'explicit scene root also bypasses cache');
 }finally{for(const f of [old,shared])f.installers.reverse().forEach(i=>i.dispose());}
});
const {assertStaticMatrices}=await import(file('static/twin/static_matrices.js'));
await test('viewer freezes adopted house/yard; editor stays automatic; parent transforms propagate; stale locals are caught',async()=>{
 for(const editor of [false,true]){
  const host=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(host);}
  const view=await mountTwin(host,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false});
  try{
   const statics=[];view.groups.roof.traverse(o=>{if(o.isMesh)statics.push(o);});
   const yard=view.scene.getObjectByName('yard');assert.ok(yard);yard.traverse(o=>{if(o.isMesh)statics.push(o);});assert.ok(statics.length>0);
   for(const o of statics)assert.equal(o.matrixAutoUpdate,editor,o.name);
   if(editor)continue;
   assertStaticMatrices(view.scene);
   const mesh=statics[0],before=mesh.matrixWorld.clone(),local=mesh.matrix.clone(),parent=mesh.parent;
   // Legitimate explicit edit of a static parent refreshes only its local matrix.
   parent.position.x+=3;parent.updateMatrix();view.render();assert.ok(!mesh.matrixWorld.equals(before));assert.deepEqual(mesh.matrix,local);
   const expected=new THREE.Matrix4().multiplyMatrices(parent.matrixWorld,local);assert.ok(mesh.matrixWorld.equals(expected));assertStaticMatrices(view.scene);
   let composes=0;const update=mesh.updateMatrix.bind(mesh);mesh.updateMatrix=()=>{composes++;return update();};view.render();assert.equal(composes,0,'no local recomposition per frame');
   mesh.position.x+=1;assert.throws(()=>assertStaticMatrices(view.scene),/Moved static twin object/);mesh.updateMatrix();assertStaticMatrices(view.scene);
   // Re-adoption refreshes static transforms and preserves ownership on reuse.
   await view.rebuild(structuredClone(view.plan));assertStaticMatrices(view.scene);
  }finally{view.dispose();}
 }
});
await test('garage, car, camera, sky, effects and live lights remain automatic in a frozen viewer',async()=>{
 const plan=structuredClone(input.plan),b=plan.buildings[0],wall=b.walls[0];
 b.openings.push({id:'matrix-garage',kind:'garage',wall:wall.id,level:wall.level,at:2,width:4,sill:0,head:7});
 plan.effect_fixtures=[{id:'matrix-fountain',type:'fountain',at:[1,1,0],strength:.5}];
 const view=await mountTwin(new Element(),{plan,kit:{materials:{}},tier:'high',bake:false});
 try{
  let garage;view.scene.traverse(o=>{if(o.userData.garageOpening)garage=o;});assert.ok(garage);assert.equal(garage.matrixAutoUpdate,true);
  const {garagePose}=await import(file('static/twin/garage_door.js'));const closed=garage.matrix.clone();garagePose(garage,true);view.render();assert.ok(!garage.matrix.equals(closed));
  const {placeCarModel}=await import(file('static/twin/live/cars.js'));
  const car=placeCarModel(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()),{at:[1,2],width:6,depth:12});view.scene.add(car);
  const sky=view.scene.getObjectByName('sky-bodies');assert.ok(sky);
  const effects=view.scene.getObjectByName('effect-fixtures');assert.ok(effects);effects.traverse(o=>assert.equal(o.matrixAutoUpdate,true));
  const {createRealLights}=await import(file('static/twin/live/real_lights.js'));
  const lightPool=createRealLights(view);const lamps=view.scene.children.filter(o=>o.isPointLight||o.isSpotLight||o.isRectAreaLight);assert.ok(lamps.length>0);
  for(const o of [car,view.camera,sky,view.scene.getObjectByName('real-sun'),effects.children[0].children[0],...lamps]){
   assert.equal(o.matrixAutoUpdate,true);const before=o.matrix.clone();o.position.x+=2;view.render();o.updateMatrixWorld();assert.ok(!o.matrix.equals(before),o.name||o.type);
  }
  assertStaticMatrices(view.scene);
  lightPool.stop();
 }finally{view.dispose();}
});
await test('reused viewer plants refresh frozen local matrices on immediate and deferred yard adoption',async()=>{
 const plan=structuredClone(input.plan);plan.site||={};plan.site.planting=[{id:'matrix-tree',preset:'oak',at:[1,1],height:10,seed:1}];
 const host=new Element(),view=await mountTwin(host,{plan,kit:{materials:{}},tier:'high',bake:false});
 try{
  const tree=()=>view.scene.getObjectByName('yard').children.find(o=>o.userData.pieceId==='matrix-tree');
  const original=tree();assert.ok(original);assert.equal(original.matrixAutoUpdate,false);
  for(const yardLater of [false,true]){
   const next=structuredClone(view.plan);next.site.planting[0].at[0]+=3;
   const adopted=yardLater?new Promise((resolve,reject)=>{host.addEventListener('twinyardrebuilt',resolve,{once:true});host.addEventListener('twinerror',e=>reject(e.detail),{once:true});}):null;
   await view.rebuild(next,{yardLater});if(adopted)await adopted;
   assert.equal(tree(),original,'reuse preserves the actual tree');assert.equal(original.matrixAutoUpdate,false);view.render();assertStaticMatrices(view.scene);
   assert.equal(original.matrix.elements[12],next.site.planting[0].at[0]);
   const expected=original.position.clone().applyMatrix4(original.parent.matrixWorld);
   assert.ok(new THREE.Vector3().setFromMatrixPosition(original.matrixWorld).distanceTo(expected)<1e-9);
  }
 }finally{view.dispose();}
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
