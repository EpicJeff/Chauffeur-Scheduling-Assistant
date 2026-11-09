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
const job = JSON.parse(process.argv[2]);
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === 'three') return {url: pathToFileURL(path.join(job.vendor, 'three.module.js')).href, shortCircuit: true};
    if (spec.startsWith('three/addons/')) return {url: pathToFileURL(path.join(job.vendor, 'addons', spec.slice(13))).href, shortCircuit: true};
    return next(spec, ctx);
  },
  load(url, ctx, next) {
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
const timers = new Map(); let nextTimer = 0;
globalThis.setTimeout = (fn, ms) => {timers.set(++nextTimer, {fn, ms}); return nextTimer;};
globalThis.clearTimeout = id => timers.delete(id);
const flush = async () => {for (let i = 0; i < 30; i++) await Promise.resolve();};
const expire = async () => {
  for (const [id, {fn, ms}] of [...timers]) {
    assert.ok(ms > 0 && ms < 60000, 'asset deadline is independent of the browser test timeout');
    timers.delete(id); fn();
  }
  await flush();
};
const requests = [];
THREE.TextureLoader.prototype.load = function(url, success, progress, error) {
  const texture = new THREE.Texture();
  requests.push({texture, success, error}); return texture;
};
const files = {'test_diff_1k.jpg': '', 'test_nor_gl_1k.jpg': '', 'test_rough_1k.jpg': ''};
const kit = {materials: {floor: {asset: 'test', color: '#123456'}}, manifest: {test: {kind: 'material', files}}};
const takeRequests = () => requests.splice(0);
const clean = () => assert.equal(timers.size, 0, 'no asset deadline leaks');

const normal = lib.kitMaterial('floor', kit, 'high'), normalRequests = takeRequests();
normalRequests.forEach(r => r.success(r.texture)); await normal.userData.ready;
assert.equal(normal.map, normalRequests[0].texture); clean();
console.log('  ok material success clears its deadline');

const building = {id: 'house', levels: [{id: 'L1', elevation: 0, ceiling: 9}], walls: [],
  rooms: [{id: 'room', level: 'L1', polygon: [[0,0],[10,0],[10,10],[0,10]], floor_material: {id: 'test', color: '#123456'}}]};
const twin = buildTwin({buildings: [building], site: {}, materials: {}}, kit, 'high');
let ready = false; twin.ready.then(() => {ready = true;}); await flush();
assert.equal(ready, false, 'real generator waits for the stalled surface images');
const stalled = takeRequests(); assert.ok(stalled.length);
await expire(); assert.equal(ready, true, 'plain-colour geometry becomes ready after asset failure');
assert.ok(twin.pieceBounds.has('house:room'));
for (const material of twin.materials.values()) if (material.name === 'floor') {
  assert.equal(material.map, null); assert.equal(material.color.getHexString(), '123456');
}
stalled.forEach(r => r.success(r.texture)); await flush();
for (const material of twin.materials.values()) assert.ok(!material.map, 'late callback cannot revive expired maps');
lib.disposeObject(twin.root); clean();
console.log('  ok generator readiness survives stalled per-room images and late callbacks');

const failed = lib.kitMaterial('floor', kit, 'high'), failedRequests = takeRequests();
failedRequests[0].error(); await failed.userData.ready;
assert.equal(failed.map, null); clean();
console.log('  ok one image failure settles the entire material, including stalled siblings');

const disposed = lib.kitMaterial('floor', kit, 'high'), disposedRequests = takeRequests();
disposed.dispose(); await disposed.userData.ready;
disposedRequests.forEach(r => r.success(r.texture));
assert.equal(disposed.map, null); clean();
console.log('  ok disposal settles pending material readiness without reviving maps');

const modelKit = {manifest: {chair: {kind: 'model', files: {'chair.gltf': ''}}}};
let modelResolve, modelSignal;
GLTFLoader.prototype.loadAsync = function() {
  modelSignal = this.manager.abortController.signal;
  return new Promise(resolve => {modelResolve = resolve;});
};
const modelPending = lib.loadModel('chair', modelKit); await flush(); await expire();
assert.equal(await modelPending, null); assert.equal(modelSignal.aborted, true);
const mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial({map: new THREE.Texture()}));
let released = 0;
[mesh.geometry, mesh.material, mesh.material.map].forEach(o => o.addEventListener('dispose', () => released++));
modelResolve({scene: new THREE.Group().add(mesh)}); await flush();
assert.equal(released, 3); clean();
console.log('  ok stalled model aborts, falls back, and disposes a late response');

const itemBuilding = {...building, items: [{id: 'chair', asset: 'chair', host: {floor: 'room', u: .5, v: .5}}],
  fixtures: [{id: 'chair', kind: 'bench', level: 'L1', rect: [4,4,6,6], height: 2}]};
const itemTwin = buildTwin({buildings: [itemBuilding], materials: {}}, modelKit, 'high');
let itemReady = false; itemTwin.ready.then(() => {itemReady = true;}); await flush();
assert.equal(itemReady, false); await expire(); assert.equal(itemReady, true);
assert.equal(itemTwin.pieceBounds.get('house:chair').box.max.y, 2, 'timed-out model retains its procedural fixture');
lib.disposeObject(itemTwin.root); clean();
console.log('  ok generator registers a fixture fallback after a stalled hosted model');

GLTFLoader.prototype.loadAsync = async () => {throw new Error('offline');};
assert.equal(await lib.loadModel('chair', modelKit), null); clean();
console.log('  ok rejected model falls back and clears its deadline');

let skyResolve, skySignal;
HDRLoader.prototype.loadAsync = function() {
  skySignal = this.manager.abortController.signal;
  return new Promise(resolve => {skyResolve = resolve;});
};
const skyPending = lib.loadSky({manifest: {sky: {kind: 'hdri', files: {'sky.hdr': ''}}}});
await flush(); await expire(); assert.equal(await skyPending, null); assert.equal(skySignal.aborted, true);
let skyReleased = false;
const sky = new THREE.Texture(); sky.addEventListener('dispose', () => {skyReleased = true;});
skyResolve(sky); await flush(); assert.equal(skyReleased, true); clean();
console.log('  ok stalled sky aborts and disposes a late response');

GLTFLoader.prototype.loadAsync = async () => ({scene: new THREE.Group().add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial()))});
assert.ok((await lib.loadModel('chair', modelKit)).isGroup); clean();
console.log('  ok successful model loads remain available');
console.log('9/9 passed');
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
