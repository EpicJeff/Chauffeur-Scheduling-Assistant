"""Actual meshoptimizer reductions, immutable sources, and real THREE.LOD choices."""
import json
from pathlib import Path
import sys
import tempfile

from twin_live_node_rig import run


DRIVER = r'''
const {MeshoptSimplifier} = await import(file('static/vendor/meshoptimizer-1.3.0/meshopt_simplifier.js'));
const lods = await import(file('static/twin/model_lods.js'));
const {simplifyGeometry, makeLod, tierModel, lodLevel, idle,
  LOD_RATIOS, LOD_TEXTURE_SIZES, LOD_MAX_ERROR, LOD_SMALL_TRIANGLES,
  LOD_NEAR_RADII, LOD_FAR_RADII, LOD_HYSTERESIS} = lods;
assert.deepEqual(LOD_RATIOS, [.25, .05]);
assert.deepEqual(LOD_TEXTURE_SIZES, [1024, 512]);
assert.equal(LOD_SMALL_TRIANGLES, 1000);
assert.equal(LOD_MAX_ERROR, .01);
assert.equal(LOD_NEAR_RADII, 8); assert.equal(LOD_FAR_RADII, 24);
assert.equal(LOD_HYSTERESIS, .1);
await MeshoptSimplifier.ready;
const triangles = g => (g.index?.count || g.attributes.position.count) / 3;
const attrs = g => Object.fromEntries(Object.entries(g.attributes).map(([k,a]) => [k, Array.from(a.array)]));
const sphere = new THREE.SphereGeometry(2, 224, 224), original = attrs(sphere), originalIndex = Array.from(sphere.index.array);
sphere.computeBoundingBox();
assert.ok(triangles(sphere) >= 99000 && triangles(sphere) <= 101000);
const reductions = [];
for (const ratio of LOD_RATIOS) {
  const result = await simplifyGeometry(sphere, ratio), count = triangles(result);
  assert.ok(count <= triangles(sphere) * ratio * 1.10, `ratio ${ratio}: got ${count} of ${triangles(sphere)}`);
  assert.ok(count >= triangles(sphere) * ratio * .80, `ratio ${ratio}: unexpected over-reduction ${count}`);
  const size = sphere.boundingBox.getSize(new THREE.Vector3());
  for (const axis of ['x','y','z']) for (const edge of ['min','max'])
    assert.ok(Math.abs(result.boundingBox[edge][axis] - sphere.boundingBox[edge][axis]) <= size[axis] * .02,
      `${ratio} bounding ${edge}.${axis} differs by over 2%`);
  assert.ok([...result.attributes.normal.array].every(Number.isFinite), 'normals stay finite');
  assert.ok([...result.attributes.uv.array].every(Number.isFinite), 'UVs stay finite');
  assert.ok(result.attributes.position.count < sphere.attributes.position.count * .5, 'unused vertices are removed');
  reductions.push(count); result.dispose();
}
assert.deepEqual(attrs(sphere), original); assert.deepEqual(Array.from(sphere.index.array), originalIndex);
console.log(`ok real MeshoptSimplifier: ${triangles(sphere)} -> ${reductions.join(' / ')} triangles, bounds within 2%, finite normals/UVs, source unchanged`);

const small = new THREE.BoxGeometry(2,1,4), smallAttrs = attrs(small), smallIndex = Array.from(small.index.array);
for (const ratio of LOD_RATIOS) {
  const result = await simplifyGeometry(small, ratio);
  assert.notEqual(result, small); assert.equal(triangles(result), 12);
  assert.deepEqual(attrs(result), smallAttrs); assert.deepEqual(Array.from(result.index.array), smallIndex);
  result.dispose();
}
console.log('ok small meshes retain every vertex, attribute and triangle in both versions');

// A real Texture clone shares THREE.Source. The derived canvas must not replace
// LOD0's source image, including when two mesh/material slots share one texture.
globalThis.requestIdleCallback = fn => setTimeout(fn, 0);
globalThis.cancelIdleCallback = clearTimeout;
const image = {width:4096, height:2048}, texture = new THREE.Texture(image);
const material = new THREE.MeshStandardMaterial({map:texture, normalMap:texture});
const source = new THREE.Group();
source.add(new THREE.Mesh(small, material), new THREE.Mesh(small, material));
source.children[1].position.x = 10;
const derived = [];
for (const level of [1,2]) {
  const result = await makeLod(source, level);
  const a = result.children[0], b = result.children[1], limit = LOD_TEXTURE_SIZES[level-1];
  assert.equal(a.material, b.material, 'shared material is cloned once per version');
  assert.equal(a.material.type, material.type, 'switch retains the same material type');
  assert.notEqual(a.material, material); assert.notEqual(a.material.map, texture);
  assert.equal(a.material.map, a.material.normalMap, 'shared map remains shared within the version');
  assert.equal(a.material.map.image.width, limit); assert.equal(a.material.map.image.height, limit/2);
  assert.notEqual(a.material.map.source, texture.source, 'derived textures own their source');
  assert.equal(texture.image, image, 'the original source image identity is untouched');
  assert.equal(texture.image.width,4096); assert.equal(texture.image.height,2048);
  assert.deepEqual(attrs(small),smallAttrs); assert.equal(triangles(a.geometry),12);
  assert.equal(b.position.x,10); derived.push(result);
}
console.log('ok LOD1/2 resample to 1024/512, original texture stays 4096, materials retain types and sharing');

function level() { return new THREE.Mesh(new THREE.BoxGeometry(2,2,2), material); }
const levels = [level(),level(),level()], high = tierModel(levels,'high');
assert.ok(high.isLOD);
const radius = new THREE.Box3().setFromObject(levels[0]).getBoundingSphere(new THREE.Sphere()).radius;
assert.equal(high.levels[1].distance,radius*LOD_NEAR_RADII);
assert.equal(high.levels[2].distance,radius*LOD_FAR_RADII);
const camera = new THREE.PerspectiveCamera();
function update(model,distance) { camera.position.set(distance,0,0); camera.updateMatrixWorld(true); model.updateMatrixWorld(true); model.update(camera); return model.getCurrentLevel(); }
assert.equal(update(high, radius),0);
assert.equal(update(high, radius*LOD_NEAR_RADII*1.2),1);
assert.equal(update(high, radius*LOD_FAR_RADII*1.2),2);
assert.equal(update(high, radius),0);
assert.equal(update(high, radius*LOD_FAR_RADII*1.2),2);
for(const row of high.levels) assert.equal(row.object.material,material,'LOD switching never replaces materials');
for(const [tier,distance,index] of [['low',0,2],['medium',radius,0],['medium',radius*100,1],['high',radius,0],['high',radius*12,1],['high',radius*30,2]])
  assert.equal(lodLevel(tier,distance,radius),index);
const medium = tierModel([level(),level(),level()],'medium');
assert.equal(medium.levels.length,2); assert.equal(update(medium,radius*100),1);
const lowLevels=[level(),level(),level()]; assert.equal(tierModel(lowLevels,'low'),lowLevels[2]);
console.log('ok tier choices use radius constants, actual THREE.LOD switches near/mid/far twice with unchanged material objects/types');

const controller = new AbortController(); controller.abort();
await assert.rejects(makeLod(source,1,controller.signal), e=>e.cancelled === true);
assert.throws(()=>idle(controller.signal),e=>e.cancelled === true);
let sourceDisposals=0; small.addEventListener('dispose',()=>sourceDisposals++);
const inFlight = new AbortController();
globalThis.requestIdleCallback = fn => setTimeout(fn,1000);
const interrupted = makeLod(source,1,inFlight.signal); inFlight.abort();
await assert.rejects(interrupted,e=>e.cancelled === true);
assert.equal(sourceDisposals,0); assert.equal(source.children[0].geometry,small);
assert.equal(source.children[0].material,material); assert.equal(texture.image,image);
console.log('ok pre-abort and idle cancellation preserve original geometry, materials and image');

// Exercise the actual imported model cache and clone path with embedded glTF.
const {rememberImport,loadModel} = await import(file('static/twin/twin_library.js'));
window.location={href:'http://house.test/house/editor'};window.chfBase='../';
globalThis.ProgressEvent ||= class { constructor(type,values) { Object.assign(this,values); } };
const positions=new Float32Array([-1,0,0,1,0,0,0,2,1]);
const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0},material:0}]}],
 buffers:[{uri:'data:application/octet-stream;base64,'+Buffer.from(positions.buffer).toString('base64'),byteLength:positions.byteLength}],
 bufferViews:[{buffer:0,byteLength:positions.byteLength}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-1,0,0],max:[1,2,1]}],materials:[{pbrMetallicRoughness:{baseColorFactor:[1,1,1,1]}}]};
const nativeFetch=globalThis.fetch;let requests=0;
globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url;
 if(url.startsWith('data:')||url.startsWith('blob:'))return nativeFetch(input);
 requests++;return new Response(JSON.stringify(doc));
};
const id='import-'+'b'.repeat(32);rememberImport({id,kind:'car',model:'car.gltf',files:{'car.gltf':true}});
const [carA,carB]=await Promise.all([loadModel(id,{},undefined,{shared:true}),loadModel(id,{},undefined,{shared:true})]);
assert.ok(carA&&carB);assert.notEqual(carA,carB);assert.equal(requests,1);
let meshA,meshB;carA.traverse(o=>{if(o.isMesh)meshA=o;});carB.traverse(o=>{if(o.isMesh)meshB=o;});
assert.notEqual(meshA,meshB);assert.equal(meshA.geometry,meshB.geometry);assert.equal(meshA.material,meshB.material);
carA.position.set(5,0,10);carA.rotation.y=.7;assert.equal(carB.position.x,0);assert.equal(carB.rotation.y,0);
console.log('ok two cars load one import once, clone scene transforms, share actual geometry and material objects');
const partial='import-'+'c'.repeat(32);rememberImport({id:partial,kind:'car',model:'car.gltf',triangles:570138,size:[2,2,1],lods:[{name:'lod1.glb'}],files:{'car.gltf':true,'lod1.glb':true}});
requests=0;const standIn=await loadModel(partial,{},undefined,{tier:'low'});
assert.equal(standIn.userData.heavyStandIn,true);assert.equal(requests,0,'a missing LOD2 never downloads the original on Low');
const farOnly=tierModel([level(),null,level()],'high');
assert.equal(farOnly.levels.length,2);assert.equal(update(farOnly,radius*100),1);
console.log('ok partial LOD sets keep Low stand-in and High can use an available far version');

// The real building path must retain THREE.LOD's hierarchy rather than flatten
// all three versions into a static batch (which would draw them together).
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const buildingPlan=structuredClone(config.flat), buildingKit=config.kit;
const building=buildingPlan.buildings.find(b=>b.openings.some(o=>o.wall&&o.state!=='ghost'));
const opening=building.openings.find(o=>o.wall&&o.state!=='ghost');
const room=building.rooms.find(r=>r.state!=='ghost');
const lodId='import-'+'c'.repeat(32);
rememberImport({id:lodId,kind:'car',model:'original.gltf',files:{'original.gltf':true,'lod1.glb':true,'lod2.glb':true},
 lods:[{name:'lod1.glb',triangles:1,bytes:1},{name:'lod2.glb',triangles:1,bytes:1}]});
const derivedDoc=structuredClone(doc);derivedDoc.nodes[0].translation=[0,0,-.5];
function binaryModel(json){
 const raw=Buffer.from(JSON.stringify(json));const size=(raw.length+3)&~3;
 const bytes=Buffer.alloc(size+20,32);bytes.write('glTF');bytes.writeUInt32LE(2,4);bytes.writeUInt32LE(bytes.length,8);
 bytes.writeUInt32LE(size,12);bytes.writeUInt32LE(0x4e4f534a,16);raw.copy(bytes,20);return bytes;
}
const binary=binaryModel(derivedDoc), lodFetched=[];
globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url;
 if(url.startsWith('data:')||url.startsWith('blob:'))return nativeFetch(input);
 lodFetched.push(url);return new Response(url.includes('.glb')?binary:JSON.stringify(doc));
};
opening.model=lodId;
building.items ||= [];
building.items.push({id:'lod-floor-car',asset:lodId,object_kind:'car',state:'settled',host:{floor:room.id,u:.5,v:.5}});
const openingSize=[opening.width,opening.head,opening.sill];
const built=buildTwin(buildingPlan,buildingKit,'high',{viewing:true});await built.ready;
const retained=[];built.root.traverse(o=>{if(o.isLOD)retained.push(o);});
assert.equal(retained.length,3,'full/cut opening domains and floor item retain separate LOD hierarchies');
for(const pieceId of [opening.id,'lod-floor-car']){
 const key=`${building.id}:${pieceId}`, meshes=built.pieces.get(key);
 assert.equal(meshes?.length,pieceId===opening.id?6:3,`${key} registers all three model levels in each viewing domain`);
 assert.ok(built.pieceBounds.has(key),`${key} retains bounds`);
 assert.ok(built.pickObjects.has(key),`${key} retains its selectable proxy`);
 for(const mesh of meshes){
  let ancestor=mesh.parent;while(ancestor&&!ancestor.isLOD)ancestor=ancestor.parent;
  assert.ok(ancestor,`${key} mesh stays beneath THREE.LOD through mergeStatic`);
  assert.equal(mesh.userData.modelLod,true);
 }
}
assert.deepEqual([opening.width,opening.head,opening.sill],openingSize);
assert.equal(lodFetched.filter(u=>u.includes('original.gltf')).length,1);
assert.equal(lodFetched.filter(u=>u.includes('lod1.glb')).length,1);
assert.equal(lodFetched.filter(u=>u.includes('lod2.glb')).length,1);
built.root.updateMatrixWorld(true);
for(const model of retained){
 const at=new THREE.Vector3().setFromMatrixPosition(model.matrixWorld), far=model.levels[2].distance*2;
 camera.position.copy(at).add(new THREE.Vector3(far,0,0));camera.updateMatrixWorld(true);model.update(camera);
 assert.equal(model.getCurrentLevel(),2);
 assert.equal(model.levels[0].object.visible,false);assert.equal(model.levels[1].object.visible,false);assert.equal(model.levels[2].object.visible,true);
 let shownMeshes=0;model.traverseVisible(o=>{if(o.isMesh)shownMeshes++;});assert.equal(shownMeshes,1);
}
console.log('ok actual buildTwin retains opening/item LOD subtrees, selective level visibility, piece identity/bounds/proxies, and one fetch per GLB');
assert.deepEqual(escaped,[]); assert.deepEqual(domErrors,[]);
'''


if __name__ == '__main__':
    # Rig scratch artifacts stay inside this worktree and are removed by run().
    tempfile.tempdir = str(Path(__file__).resolve().parents[2])
    app = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(app))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((app / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text())
    kit = json.loads((app / 'twin_kits/modern_farmhouse.json').read_text())
    kit['manifest'] = {}
    sys.exit(run(DRIVER, {'flat': flatten(assemble(fixture)[0]), 'kit': kit}, prefix='.model_lods_', timeout=280))
