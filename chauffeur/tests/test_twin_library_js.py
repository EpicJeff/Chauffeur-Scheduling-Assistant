"""Run optional-asset readiness and late-callback regressions under Node.

Run from chauffeur/: python tests/test_twin_library_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


DRIVER = r"""
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import {readFileSync} from 'node:fs';
const job = JSON.parse(process.argv[2]);
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === '@dgreenheck/ez-tree') return {url: 'test:tree', shortCircuit: true};
    if (spec === 'three') return {url: pathToFileURL(path.join(job.vendor, 'three.module.js')).href, shortCircuit: true};
    if (spec.startsWith('three/addons/')) return {url: pathToFileURL(path.join(job.vendor, 'addons', spec.slice(13))).href, shortCircuit: true};
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    if (url === 'test:tree') return {format: 'module', shortCircuit: true, source: 'export class Tree {}'};
    // Expose the actual vendored shadow renderer to a CPU-only renderer stub.
    // The implementation is unmodified; exercise depth/distance selection.
    if (url === pathToFileURL(path.join(job.vendor, 'three.module.js')).href)
      return {...next(url, {...ctx, format: 'module'}), format: 'module',
        source: readFileSync(new URL(url), 'utf8') + '\nexport { WebGLShadowMap };'};
    if (url.startsWith('file:') && url.endsWith('.js')) return {...next(url, {...ctx, format: 'module'}), format: 'module'};
    return next(url, ctx);
  },
});
globalThis.window = {chfBase: '/', location: {href: 'http://localhost/'}};
const THREE = await import('three');
const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
const {HDRLoader} = await import('three/addons/loaders/HDRLoader.js');
const lib = await import(pathToFileURL(path.join(job.twin, 'twin_library.js')).href);
const {buildTwin} = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const {buildYard} = await import(pathToFileURL(path.join(job.twin, 'twin_yard.js')).href);
const timers = new Map(); let nextTimer = 0, now = 0;
globalThis.setTimeout = (fn, ms) => {timers.set(++nextTimer, {fn, at: now + ms}); return nextTimer;};
globalThis.clearTimeout = id => timers.delete(id);
const flush = async () => {for (let i = 0; i < 50; i++) await Promise.resolve();};
const advance = async ms => {
  const end = now + ms;
  while (true) {
    const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) break;
    const [id, timer] = due; now = timer.at; timers.delete(id); timer.fn(); await flush();
  }
  now = end; await flush();
};
const requests = [];
THREE.TextureLoader.prototype.load = function(url, success, progress, error) {
  const texture = new THREE.Texture();
  requests.push({url, texture, success, error}); return texture;
};
const files = {'test_diff_1k.jpg': '', 'test_nor_gl_1k.jpg': '', 'test_rough_1k.jpg': ''};
const materialKit = id => ({materials: {floor: {asset: id, color: '#123456'}}, manifest: {[id]: {kind: 'material', files}}});
const modelKit = id => ({manifest: {[id]: {kind: 'model', files: {[id + '.gltf']: ''}}}});
const takeRequests = () => requests.splice(0);
const clean = () => assert.equal(timers.size, 0, 'no asset deadline leaks');
const cube = () => new THREE.Group().add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1).translate(0, .5, 0),
  new THREE.MeshStandardMaterial({map: new THREE.Texture()})));
let passed = 0;
const ok = label => {clean(); ++passed; console.log('  ok ' + label);};

const normalKit = materialKit('normal');
const normal = lib.kitMaterial('floor', normalKit, 'high'), normalRequests = takeRequests();
normalRequests.forEach(r => r.success(r.texture)); await normal.userData.ready;
assert.equal(normal.map.source, normalRequests[0].texture.source);
const normalMap = normal.map;
normal.dispose();
const cachedMaterial = lib.kitMaterial('floor', normalKit, 'high'); await cachedMaterial.userData.ready;
assert.equal(takeRequests().length, 0); assert.ok(cachedMaterial.map);
assert.notEqual(cachedMaterial.map, normalMap, 'a scene owns its copies of cached textures');
ok('material success caches images and clears its deadline');

const graniteKit={materials:{granite:{asset:'table_granite',color:'#3b3d40',roughness:.22}},manifest:{table_granite:{kind:'material',files}}};
const granite=lib.kitMaterial('granite',graniteKit,'high'),graniteRequests=takeRequests();
assert.equal(granite.color.getHexString(),'3b3d40');assert.equal(granite.roughness,.22);
graniteRequests.forEach(r=>r.success(r.texture));await granite.userData.ready;
assert.ok(granite.map&&granite.normalMap&&granite.roughnessMap);
assert.equal(granite.color.getHexString(),'3b3d40','loaded granite texture keeps charcoal tint');
assert.equal(granite.roughness,.22,'loaded roughness map retains low base roughness');
granite.dispose();ok('granite keeps charcoal colour and sheen with actual texture callbacks');

// Feature slots retain their explicit tint after real texture callbacks and share
// one instance across target roles/rebuild caches, without changing defines.
const slotKit={materials:{siding:{asset:'slot_finish',color:'#abcdef'}},manifest:{slot_finish:{kind:'material',files}}};
const slotCache=new Map(),slotRole=r=>{if(!slotCache.has(r))slotCache.set(r,lib.kitMaterial(r,slotKit,'high'));return slotCache.get(r);};
const slotRef={id:'slot_finish',color:'#234567'};
const slotMaterial=lib.materialSlot(slotRef,'siding',slotKit,'high',slotCache,slotRole);
const slotRequests=takeRequests();assert.ok(slotRequests.length);slotRequests.forEach(r=>r.success(r.texture));await slotMaterial.userData.ready;
assert.equal(slotMaterial.color.getHexString(),'234567','explicit slot tint survives texture completion');
assert.ok(slotMaterial.map&&slotMaterial.normalMap&&slotMaterial.roughnessMap);
const slotVersion=slotMaterial.version,slotProgram=slotMaterial.customProgramCacheKey();
assert.equal(lib.materialSlot({...slotRef},'trim',slotKit,'high',slotCache,slotRole),slotMaterial);
assert.equal(slotMaterial.version,slotVersion);assert.equal(slotMaterial.customProgramCacheKey(),slotProgram);
assert.equal(takeRequests().length,0);slotMaterial.dispose();ok('shared material slot caches and loaded tint');

const latticeKit={materials:{lattice:{asset:'lattice',pattern:'lattice',color:'#f4f3ef'}},manifest:{}};
const latticeCache=new Map(),latticeRole=r=>{if(!latticeCache.has(r))latticeCache.set(r,lib.kitMaterial(r,latticeKit,'high'));return latticeCache.get(r);};
const lattice=lib.materialSlot(null,'lattice',latticeKit,'high',latticeCache,latticeRole);
assert.equal(takeRequests().length,0,'generated lattice fetches no asset');
assert.ok(lattice.alphaMap.isDataTexture);assert.equal(lattice.alphaTest,.5);assert.equal(lattice.side,THREE.DoubleSide);assert.equal(lattice.transparent,false);
assert.equal(lattice.alphaMap.wrapS,THREE.RepeatWrapping);assert.equal(lattice.alphaMap.wrapT,THREE.RepeatWrapping);
assert.ok(Math.abs(lattice.alphaMap.repeat.x-1/(Math.SQRT2*4/12))<1e-9,'physical four-inch pitch perpendicular to strips');
const image=lattice.alphaMap.image,mask=(u,v)=>image.data[((Math.floor(v*image.height)%image.height+image.height)%image.height*image.width+(Math.floor(u*image.width)%image.width+image.width)%image.width)*4+1];
assert.equal(mask(0,0),255,'crossing is painted');assert.equal(mask(.5,0),0,'diamond centre is a hole');
assert.equal(mask(.25,.25),255);assert.equal(mask(.25,.75),255,'both 45-degree families');
const solidPixels=Array.from({length:image.width*image.height},(_,i)=>image.data[i*4+1]).filter(v=>v>0).length;
const fraction=solidPixels/(image.width*image.height),expected=1-(1-1.5/4)**2;
assert.ok(Math.abs(fraction-expected)<.02,'1.5-inch painted strips on four-inch centres');
const latticeVersion=lattice.version,latticeProgram=lattice.customProgramCacheKey();
for(const ref of [{id:'lattice'},{id:'lattice',color:'#f4f3ef'},{id:'lattice',color:'#f4f3ef'}])
 assert.equal(lib.materialSlot(ref,'siding',latticeKit,'high',latticeCache,latticeRole),lattice,'default and chooser references share one material');
assert.equal(lattice.version,latticeVersion);assert.equal(lattice.customProgramCacheKey(),latticeProgram);
const tinted=lib.materialSlot({id:'lattice',color:'#123456'},'lattice',latticeKit,'high',latticeCache,latticeRole);
assert.equal(tinted.color.getHexString(),'123456');assert.equal(tinted.alphaTest,.5);assert.equal(tinted.side,THREE.DoubleSide);
assert.equal(lib.materialSlot({id:'lattice',color:'#123456'},'siding',latticeKit,'high',latticeCache,latticeRole),tinted);
assert.equal(tinted.customProgramCacheKey(),latticeProgram,'tint does not change shader variant');
assert.equal(takeRequests().length,0);ok('procedural lattice size, holes, alpha cutout, tint and cached material/program');

const drawn=[],noop=()=>{};
const shadowRenderer={getRenderTarget:()=>null,getActiveCubeFace:()=>0,getActiveMipmapLevel:()=>0,localClippingEnabled:false,
 properties:{get:()=>({})},setRenderTarget:noop,clear:noop,renderBufferDirect:(c,s,g,m,o)=>drawn.push(m),
 state:{setBlending:noop,setScissorTest:noop,viewport:noop,buffers:{color:{setClear:noop},depth:{getReversed:()=>false,setTest:noop}}}};
const shadowMap=new THREE.WebGLShadowMap(shadowRenderer,{update:o=>o.geometry},{maxTextureSize:4096});shadowMap.enabled=true;
const shadowScene=new THREE.Scene(),shadowCamera=new THREE.PerspectiveCamera();shadowCamera.updateMatrixWorld();
const {mergeStatic}=await import(pathToFileURL(path.join(job.twin,'twin_generator.js')).href);
for(let i=0;i<2;i++){
 const group=new THREE.Group();shadowScene.add(group);group.add(new THREE.Mesh(new THREE.PlaneGeometry(1,1),lattice));
 mergeStatic(group);group.children[0].frustumCulled=false;
 assert.ok(group.children[0].castShadow,'merged Lattice casts realtime shadows');
}
shadowScene.updateMatrixWorld(true);
for(const light of [new THREE.DirectionalLight(),new THREE.PointLight()]){
 light.position.set(0,2,0);light.updateMatrixWorld();light.target?.updateMatrixWorld();drawn.length=0;
 shadowMap.render([light],shadowScene,shadowCamera);assert.ok(drawn.length>=2,'actual shadow renderer drew the cutouts');
 for(const m of drawn){
  assert.equal(m.alphaMap,lattice.alphaMap);assert.equal(m.alphaTest,lattice.alphaTest);assert.equal(m.side,THREE.DoubleSide);
  assert.equal(m.isMeshDistanceMaterial,light.isPointLight||undefined);
 }
 const first=drawn[0];assert.ok(drawn.every(m=>m===first),'two meshes share one native shadow material');
 drawn.length=0;shadowMap.render([light],shadowScene,shadowCamera);
 assert.ok(drawn.length>=2&&drawn.every(m=>m===first),'shadow material is reused on subsequent renders');
}
ok('vendored r187 directional depth and point distance shadows retain alpha holes after merging');

const building = {id: 'house', levels: [{id: 'L1', elevation: 0, ceiling: 9}], walls: [],
  rooms: [{id: 'room', level: 'L1', polygon: [[0,0],[10,0],[10,10],[0,10]], floor_material: {id: 'slow_finish', color: '#123456'}}]};
const slowKit = materialKit('slow_finish');
const twin = buildTwin({buildings: [building], site: {}, materials: {}}, slowKit, 'high');
let ready = false; twin.ready.then(() => {ready = true;}); await flush();
assert.equal(ready, false, 'real generator waits for the stalled surface images');
const stalled = takeRequests(); assert.ok(stalled.length);
await advance(15000); assert.equal(ready, true, 'plain geometry is ready at 15 seconds');
assert.ok(twin.pieceBounds.has('house:room'));
const slowMaterial = [...twin.materials.values()].find(m => m.name === 'floor' && m.color.getHexString() === '123456');
assert.equal(slowMaterial.map, null);
await advance(5000); stalled.forEach(r => r.success(r.texture)); await flush();
assert.ok(slowMaterial.map, 'a texture arriving at 20 seconds applies to the existing material');
assert.equal(slowMaterial.map.source, stalled[0].texture.source);
assert.equal(slowMaterial.color.getHexString(), 'ffffff');
lib.disposeObject(twin.root);
ok('generator becomes ready at 15 seconds and applies its late finish at 20 seconds');

const failed = lib.kitMaterial('floor', materialKit('failed'), 'high'), failedRequests = takeRequests();
failedRequests[0].error(); await failed.userData.ready;
failedRequests.slice(1).forEach(r => r.success(r.texture)); await flush();
assert.equal(failed.map, null); assert.equal(failed.normalMap, null); assert.equal(failed.roughnessMap, null);
assert.equal(failed.color.getHexString(), '123456');
ok('an actual image error keeps the entire material plain, including late siblings');

const disposed = lib.kitMaterial('floor', materialKit('disposed'), 'high'), disposedRequests = takeRequests();
disposed.dispose(); await disposed.userData.ready;
await advance(20000); disposedRequests.forEach(r => r.success(r.texture)); await flush();
assert.equal(disposed.map, null);
const disposedCache = lib.kitMaterial('floor', materialKit('disposed'), 'high'); await disposedCache.userData.ready;
assert.ok(disposedCache.map); assert.equal(takeRequests().length, 0);
ok('disposal settles readiness and a late image only applies to a live material');

let modelResolve, modelSignal, fetches = 0;
GLTFLoader.prototype.loadAsync = function() {
  ++fetches; modelSignal = this.manager.abortController.signal;
  assert.equal(timers.size, 0, 'the request is issued before its deadline starts');
  return new Promise(resolve => {modelResolve = resolve;});
};
let lateModel;
const chairKit = modelKit('slow_chair');
const modelPending = lib.loadModel('slow_chair', chairKit, model => {lateModel = model;});
await flush(); await advance(15000);
assert.equal(await modelPending, null); assert.equal(modelSignal.aborted, false);
await advance(5000); const source = cube(); let released = 0;
[source.children[0].geometry, source.children[0].material, source.children[0].material.map]
  .forEach(o => o.addEventListener('dispose', () => released++));
modelResolve({scene: source}); await flush();
assert.ok(lateModel?.isGroup); assert.equal(released, 1, 'only the imported material is replaced during standardization');
lib.disposeObject(lateModel);
const cachedModel = await lib.loadModel('slow_chair', chairKit);
assert.ok(cachedModel?.isGroup); assert.equal(fetches, 1, 'the 20-second model is reused without a new fetch');
assert.notEqual(cachedModel.children[0].geometry, source.children[0].geometry);
assert.notEqual(cachedModel.children[0].material.map, source.children[0].material.map);
lib.disposeObject(cachedModel);
ok('a model at 20 seconds is delivered late, cached, and survives disposal of a previous scene');

const itemBuilding = {...building, rooms: [{...building.rooms[0], floor_material: undefined}],
  items: [{id: 'chair', asset: 'hosted_chair', host: {floor: 'room', u: .5, v: .5}}],
  fixtures: [{id: 'chair', kind: 'bench', level: 'L1', rect: [4,4,6,6], height: 2}]};
const hostedKit = modelKit('hosted_chair');
const itemTwin = buildTwin({buildings: [itemBuilding], materials: {}}, hostedKit, 'high');
let itemReady = false; itemTwin.ready.then(() => {itemReady = true;}); await flush();
assert.equal(itemReady, false); await advance(15000); assert.equal(itemReady, true);
assert.equal(itemTwin.pieceBounds.get('house:chair').box.max.y, 2, 'deadline retains the procedural fixture');
await advance(5000); modelResolve({scene: cube()}); await flush();
assert.ok(Math.abs(itemTwin.pieceBounds.get('house:chair').box.max.y - 1 / .3048) < .001,
  'late model replaces the fallback and updates its bounds');
assert.equal(itemTwin.pickObjects.get('house:chair').userData.kind, 'item');
const afterLateBuild = buildTwin({buildings: [itemBuilding], materials: {}}, hostedKit, 'high');
await afterLateBuild.ready;
assert.equal(fetches, 2, 'the next build uses the cached hosted model');
lib.disposeObject(itemTwin.root); lib.disposeObject(afterLateBuild.root);
ok('a late hosted model replaces the existing fallback and is used by the next build');

const deadBuilding = {...itemBuilding, items: [{...itemBuilding.items[0], asset: 'disposed_chair'}]};
const deadTwin = buildTwin({buildings: [deadBuilding], materials: {}}, modelKit('disposed_chair'), 'high');
await flush(); await advance(15000); await deadTwin.ready; lib.disposeObject(deadTwin.root);
const deadObjects = deadTwin.root.children.length, deadBounds = deadTwin.pieceBounds.get('house:chair').box.clone();
let disposedLateGeometry = 0;
const deadSource = cube(), deadGeometry = deadSource.children[0].geometry;
deadGeometry.clone = function() {
  const out = THREE.BufferGeometry.prototype.clone.call(this);
  out.addEventListener('dispose', () => ++disposedLateGeometry); return out;
};
modelResolve({scene: deadSource}); await flush();
assert.equal(deadTwin.root.children.length, deadObjects);
assert.ok(deadTwin.pieceBounds.get('house:chair').box.equals(deadBounds), 'a late model cannot update a disposed scene');
assert.equal(disposedLateGeometry, 1, 'the disposed scene releases its copy of the late model');
ok('a disposed generator ignores a late hosted model');

const yardKit = modelKit('yard_chair'), yardFetches = fetches;
const yardPlan = {buildings: [], site: {furniture: [
  {asset: 'yard_chair', at: [5, 5]}, {asset: 'yard_chair', at: [10, 5]},
]}};
let yard;
const yardPending = buildYard(yardPlan, yardKit, 'low').then(value => {yard = value;});
await flush(); await advance(15000); await yardPending;
assert.equal(fetches, yardFetches + 1, 'placements share one request');
const yardSource = cube(); yardSource.children[0].material.name = 'late_yard_model';
await advance(5000); modelResolve({scene: yardSource}); await flush();
const yardMeshes = [];
yard.group.traverse(o => {if (o.isMesh && o.material.name === 'late_yard_model') yardMeshes.push(o);});
assert.equal(yardMeshes.length, 2, 'both late yard placements are applied');
const cachedYard = await buildYard(yardPlan, yardKit, 'low');
const cachedYardMeshes = [];
cachedYard.group.traverse(o => {if (o.isMesh && o.material.name === 'late_yard_model') cachedYardMeshes.push(o);});
assert.equal(cachedYardMeshes.length, 1, 'cached instances retain shared-material batching');
assert.equal(fetches, yardFetches + 1);
lib.disposeObject(yard.group); lib.disposeObject(cachedYard.group);
ok('late yard furniture is applied and subsequent builds reuse and batch it');

GLTFLoader.prototype.loadAsync = async () => {throw new Error('offline');};
assert.equal(await lib.loadModel('offline_chair', modelKit('offline_chair')), null);
ok('a rejected model falls back and clears its deadline');

let skyResolve, skySignal, skyFetches = 0, lateSky;
HDRLoader.prototype.loadAsync = function() {
  ++skyFetches; skySignal = this.manager.abortController.signal;
  return new Promise(resolve => {skyResolve = resolve;});
};
const skyKit = {manifest: {slow_sky: {kind: 'hdri', files: {'sky.hdr': ''}}}};
const skyPending = lib.loadSky(skyKit, texture => {lateSky = texture;});
await flush(); await advance(15000); assert.equal(await skyPending, null); assert.equal(skySignal.aborted, false);
await advance(5000); const sky = new THREE.Texture(); skyResolve(sky); await flush();
assert.ok(lateSky?.isTexture); lateSky.dispose();
const cachedSky = await lib.loadSky(skyKit); assert.ok(cachedSky?.isTexture); assert.equal(skyFetches, 1);
assert.notEqual(cachedSky, lateSky);
ok('a late sky is delivered and cached without aborting its request');

GLTFLoader.prototype.loadAsync = async () => ({scene: cube()});
assert.ok((await lib.loadModel('fast_chair', modelKit('fast_chair'))).isGroup);
ok('successful model loads remain available');
console.log(`${passed}/${passed} passed`);

"""


if __name__ == '__main__':
    node = shutil.which('node')
    if not node:
        print('  skip node is not available')
        raise SystemExit(0)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='twin_library_js_') as scratch:
        driver = Path(scratch) / 'driver.mjs'
        driver.write_text(DRIVER, encoding='utf-8')
        result = subprocess.run([node, str(driver), json.dumps({
            'vendor': str(root / 'static/vendor/three-r187'), 'twin': str(root / 'static/twin'),
        })], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        raise SystemExit(result.returncode)
