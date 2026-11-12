"""Execute the real chunker, vendored GLTFLoader, merger and tier selection in Node."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_twin_drag_js import DRIVER as BASE

DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE = await import(three);
const objects = await import(file('static/twin/objects.js'));
const {uploadFiles} = await import(file('static/twin/editor/imports.js'));
const {request} = await import(file('static/twin/editor/api.js'));
const {loadModel,rememberImport,disposeObject} = await import(file('static/twin/twin_library.js'));
const {GLTFLoader} = await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
const nativeFetch = globalThis.fetch;
const ok = text => console.log('ok '+text);
const near = (a,b) => assert.ok(Math.abs(a-b)<.0001,`${a} near ${b}`);

const f = new Blob([new Uint8Array(6*1048576)]);f.name='car.zip';
const calls=[], accepted=[], progress=[];let cancelled=false;
const send = async (path, method, body) => {
  calls.push([path,method,body?.size]);
  if(path==='imports/uploads') {assert.equal(body.size,6*1048576);return {upload_id:'abc',chunk_bytes:4*1048576};}
  if(method==='DELETE') {cancelled=true;return {};}
  if(path.endsWith('/finish')) return {id:'import-test'};
  if(body.size>1048576) throw Object.assign(new Error('Proxy 413'),{status:413});
  accepted.push([Number(path.split('/').at(-1)),body.size]);return {};
};
assert.equal((await uploadFiles([f],text=>progress.push(text),null,send)).id,'import-test');
assert.deepEqual(calls.filter(c=>c[1]==='PUT').slice(0,3).map(c=>c[2]),[4*1048576,2*1048576,1048576]);
assert.deepEqual(accepted.map(c=>c[0]),[0,1,2,3,4,5]);assert.equal(cancelled,false);
assert.ok(progress.includes('Uploading 6 of 6 MB…'));assert.equal(progress.at(-1),'Preparing model…');
ok('chunker halves 413 without skipping bytes or indexes and reports progress');
const rejected=[];
await assert.rejects(uploadFiles([f],()=>{},null,async (path,method,body)=>{
 if(path==='imports/uploads')return {upload_id:'tiny',chunk_bytes:4*1048576};
 if(method==='DELETE'){rejected.push('cancel');return {};}
 rejected.push(body.size);throw Object.assign(new Error('413'),{status:413});
}),/256 KB/);
assert.deepEqual(rejected,[4194304,2097152,1048576,524288,262144,'cancel']);
const abort = new AbortController();abort.abort();
await assert.rejects(uploadFiles([f],()=>{},abort.signal,send),/cancelled/);assert.equal(cancelled,true);
ok('minimum chunk refusal and cancellation clean up their staged upload');
window.chfBase='/ingress/';
globalThis.fetch=async (_url,options)=>{assert.equal(options.headers['Content-Type'],'application/octet-stream');assert.ok(options.body instanceof Blob);return new Response('too large',{status:413});};
await assert.rejects(request('imports/uploads/a/0','PUT',f),error=>error.status===413);
globalThis.fetch=nativeFetch;
ok('real API wrapper sends binary blobs and preserves the ingress 413 status');

const source=new THREE.Group(), materials=Array.from({length:5},(_,i)=>new THREE.MeshStandardMaterial({color:i+1}));
source.position.set(2,3,4);source.rotation.y=.3;
for(let i=0;i<40;i++){
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,2,3),materials[i%5]);
 if(i%3) {const size=i%2?3:4;mesh.geometry.setAttribute('color',new THREE.Float32BufferAttribute(new Float32Array(mesh.geometry.attributes.position.count*size).fill(1),size));}
 mesh.position.set(i%8,Math.floor(i/8),i/10);mesh.rotation.z=i/80;
 if(i%2)mesh.scale.x=-1;
 source.add(mesh);
}
const beforeBox=new THREE.Box3().setFromObject(source), beforeBudget=objects.modelBudget(source,{resizeTextures:false});
const merged=objects.mergeByMaterial(source), afterBox=new THREE.Box3().setFromObject(merged);
let meshes=0;merged.traverse(o=>{if(o.isMesh){++meshes;assert.ok(materials.includes(o.material));}});
assert.equal(meshes,5);assert.equal(objects.modelBudget(merged,{resizeTextures:false}).triangles,beforeBudget.triangles);
beforeBox.min.toArray().forEach((v,i)=>near(v,afterBox.min.toArray()[i]));beforeBox.max.toArray().forEach((v,i)=>near(v,afterBox.max.toArray()[i]));
ok('40 transformed meshes over 5 materials merge to 5 with identical bounds and triangles');

// Exercise all five requested extensions through the actual r187 parser.
globalThis.ProgressEvent=class{constructor(type,values){Object.assign(this,values);}};
globalThis.self=globalThis;
const extensions={KHR_materials_specular:{specularFactor:.6},KHR_texture_transform:{},
 KHR_materials_transmission:{transmissionFactor:.75},KHR_materials_clearcoat:{clearcoatFactor:.8},
 KHR_materials_emissive_strength:{emissiveStrength:2}};
const vertices=new Float32Array([0,0,0,1,0,0,0,2,0]);
const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],
 meshes:[{primitives:[{attributes:{POSITION:0},material:0}]}],
 buffers:[{uri:'data:application/octet-stream;base64,'+Buffer.from(vertices.buffer).toString('base64'),byteLength:36}],
 bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[0,0,0],max:[1,2,0]}],
 extensionsUsed:Object.keys(extensions),materials:[{extensions,emissiveFactor:[1,0,0]}]};
// A tiny embedded texture makes texture-transform run, rather than just list it.
const manager=new THREE.LoadingManager();const textureLoader={load(_url,onLoad){const t=new THREE.Texture();onLoad?.(t);return t;}};
manager.addHandler(/fixture.png/,textureLoader);
doc.images=[{uri:'fixture.png'}];doc.textures=[{source:0}];
doc.materials[0].pbrMetallicRoughness={baseColorTexture:{index:0,extensions:{KHR_texture_transform:{offset:[.2,.3],scale:[.5,.6],rotation:.1}}}};
const loaded=await new GLTFLoader(manager).parseAsync(JSON.stringify(doc),'');
const original=loaded.scene.children[0].material;
near(original.specularIntensity,.6);near(original.clearcoat,.8);near(original.transmission,.75);near(original.emissiveIntensity,2);near(original.map.offset.x,.2);
const plain=objects.singlePassMaterial(original);
assert.equal(plain.type,'MeshStandardMaterial');assert.equal(plain.transmission,undefined);assert.ok(plain.transparent);near(plain.opacity,.25);assert.equal(plain.map,original.map);
near(plain.emissiveIntensity,2);near(plain.map.offset.y,.3);
const physical=new THREE.MeshPhysicalMaterial({clearcoat:.4});assert.equal(objects.singlePassMaterial(physical),physical);
ok('all five KHR extensions load; only transmission converts to transparent standard material');

// Use the actual model loader, including cache and metadata shortcut.
window.location={href:'http://house.test/ingress/house/editor'};
delete doc.images;delete doc.textures;delete doc.materials[0].pbrMetallicRoughness;
let fetches=0;globalThis.fetch=async input=>{const url=typeof input==='string'?input:input.url;if(url.startsWith('data:'))return nativeFetch(input);++fetches;return new Response(JSON.stringify(doc),{status:200});};
const asset='import-'+'5'.repeat(32);rememberImport({id:asset,model:'car.gltf',files:{'car.gltf':true},triangles:570138,kind:'other',size:[1,2,3]});
const low=await loadModel(asset,{},undefined,{tier:'low'});assert.ok(low.userData.heavyStandIn);assert.equal(fetches,0);
const medium=await loadModel(asset,{},undefined,{tier:'medium'});assert.ok(medium);assert.equal(medium.userData.heavyStandIn,undefined);assert.ok(fetches>0);
let mat;medium.traverse(o=>{if(o.isMesh)mat=o.material;});assert.equal(mat.type,'MeshStandardMaterial');near(mat.opacity,.25);
const high=await loadModel(asset,{},undefined,{tier:'high'});assert.equal(high.userData.heavyStandIn,undefined);
const small='import-'+'6'.repeat(32);rememberImport({id:small,model:'small.gltf',files:{'small.gltf':true},triangles:300000,kind:'other',size:[1,2,3]});
assert.equal((await loadModel(small,{},undefined,{tier:'low'})).userData.heavyStandIn,undefined);
const bounds=new THREE.Box3().setFromObject(low).getSize(new THREE.Vector3());bounds.toArray().forEach((v,i)=>near(v,[1,2,3][i]));
const carContext={scale(){},stroke(){},beginPath(){},arc(){}};
document.createElement=()=>({getContext:()=>carContext});
const car=objects.heavyStandIn([2,1,4],'car');assert.equal(car.children.length,2);assert.ok(car.children[1].material.map);
for(const item of [low,medium,high,car])disposeObject(item);
ok('Low selects the footprint stand-in only above 300k; Medium/High keep full model; car uses twin icon');
"""


def run():
    with tempfile.TemporaryDirectory(prefix='chunks_node_') as temp:
        driver, config = Path(temp) / 'driver.mjs', Path(temp) / 'config.json'
        driver.write_text(DRIVER, encoding='utf-8')
        config.write_text(json.dumps({'root': ROOT.as_posix()}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(config)], capture_output=True, text=True, timeout=180)
        print(result.stdout, end='')
        if result.returncode: raise AssertionError(result.stderr)


if __name__ == '__main__': run()
