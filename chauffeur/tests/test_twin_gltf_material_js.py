"""glTF material import on the Library page: the real gltf_import.js under node.

Fixtures are generated here: tiny PNGs (zlib + crc32), a .glb with its PNGs in
the binary chunk, and a .gltf whose textures and .bin arrive as sibling files.
The page tests mount the real page.js with a stub Library API.

Run: python tests/test_twin_gltf_material_js.py
"""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const zlib = await import('node:zlib');
// Browsers have ProgressEvent; three's FileLoader raises one while reading a .bin.
globalThis.ProgressEvent ??= class extends Event { constructor(type, init = {}) { super(type); Object.assign(this, init); } };
const THREE = await import('three');
THREE.TextureLoader.prototype.load = function (url, done) { const t = new THREE.Texture({width: 32, height: 32}); queueMicrotask(() => done(t)); return t; };
const {readGltfMaterials} = await import(file('static/twin/library_page/gltf_import.js'));
const {mountLibraryPage} = await import(file('static/twin/library_page/page.js'));
const pause = ms => new Promise(r => setTimeout(r, ms)), clone = x => structuredClone(x);
const until = async fn => { for (let i = 0; i < 400 && !fn(); i++) await pause(5); assert.ok(fn(), 'timed out waiting'); };

function png(r, g, b) {
  const chunk = (type, data) => {
    const t = Buffer.from(type), len = Buffer.alloc(4), crc = Buffer.alloc(4);
    len.writeUInt32BE(data.length); crc.writeUInt32BE(zlib.crc32(Buffer.concat([t, data])));
    return Buffer.concat([len, t, data, crc]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(1, 0); ihdr.writeUInt32BE(1, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(Buffer.from([0, r, g, b]))), chunk('IEND', Buffer.alloc(0))]);
}
const pad = (bytes, fill = 0) => Buffer.concat([bytes, Buffer.alloc((4 - bytes.length % 4) % 4, fill)]);
// Pack byte arrays into one buffer; returns {bin, views} for bufferViews.
function pack(parts) {
  const views = []; let offset = 0;
  const bin = Buffer.concat(parts.map(part => { const padded = pad(Buffer.from(part)); views.push({buffer: 0, byteOffset: offset, byteLength: part.length}); offset += padded.length; return padded; }));
  return {bin, views};
}
function glb(json, bin) {
  const j = pad(Buffer.from(JSON.stringify(json)), 0x20), b = pad(bin);
  const chunk = (type, data) => { const h = Buffer.alloc(8); h.writeUInt32LE(data.length, 0); h.writeUInt32LE(type, 4); return Buffer.concat([h, data]); };
  const header = Buffer.alloc(12); header.write('glTF', 0); header.writeUInt32LE(2, 4); header.writeUInt32LE(12 + 8 + j.length + 8 + b.length, 8);
  return Buffer.concat([header, chunk(0x4E4F534A, j), chunk(0x004E4942, b)]);
}
const bytes = async blob => Buffer.from(await blob.arrayBuffer());
const same = async (blob, expected, label) => { assert.ok(blob instanceof Blob, label + ' is a Blob'); assert.ok((await bytes(blob)).equals(Buffer.from(expected)), label + ' bytes'); };

const BASE = png(200, 120, 90), ORM = png(255, 140, 20), NORMAL = png(128, 128, 255), OAK = png(160, 110, 60), WALNUT = png(90, 60, 40);
function brickGlb() {
  const {bin, views} = pack([BASE, ORM, NORMAL]);
  return glb({
    asset: {version: '2.0'},
    // Draco geometry must not stop a material import: meshes are never decoded.
    extensionsUsed: ['KHR_draco_mesh_compression'], extensionsRequired: ['KHR_draco_mesh_compression'],
    buffers: [{byteLength: bin.length}], bufferViews: views,
    images: [0, 1, 2].map(i => ({bufferView: i, mimeType: 'image/png'})),
    textures: [{source: 0}, {source: 1}, {source: 2}, {source: 1}],
    materials: [{name: 'Brick wall',
      pbrMetallicRoughness: {baseColorFactor: [0.5, 0.25, 1, 1], baseColorTexture: {index: 0},
        metallicRoughnessTexture: {index: 1}, roughnessFactor: 0.6, metallicFactor: 0.2},
      normalTexture: {index: 2, scale: 0.75}, occlusionTexture: {index: 3, strength: 0.5}}],
  }, bin);
}
function twoGlb() {
  const {bin, views} = pack([OAK, WALNUT]);
  return glb({asset: {version: '2.0'}, buffers: [{byteLength: bin.length}], bufferViews: views,
    images: [{bufferView: 0, mimeType: 'image/png'}, {bufferView: 1, mimeType: 'image/png'}],
    textures: [{source: 0}, {source: 1}],
    materials: [{name: 'Oak', pbrMetallicRoughness: {baseColorTexture: {index: 0}}},
      {name: 'Walnut', pbrMetallicRoughness: {baseColorTexture: {index: 1}, roughnessFactor: 0.4}}]}, bin);
}
const glbFile = (buffer, name = 'brick.glb') => new File([buffer], name, {type: 'model/gltf-binary'});

const record = (id = 'material-test', source = 'user') => ({id, name: id, source, revision: 1, maps: {},
  params: {tint: '#ffffff', roughness: null, metalness: null, normal_scale: 1, normal_convention: 'gl', ao_intensity: 1, tile_ft: [4, 4], rotation_deg: 0, random_offset: false}});
async function setup(hooks = {}) {
  const host = document.createElement('main'); document.body.append(host);
  const records = new Map([['material-test', record()]]), calls = [], alerts = [], choices = [], inputs = [];
  window.showGlobalAlert = text => alerts.push(text); window.promptConfirm = async () => true;
  window.promptInput = async (...args) => { inputs.push(args); return null; };
  window.promptChoice = async (...args) => { choices.push(args); return hooks.choose ? hooks.choose(...args) : null; };
  for (const name of ['alert', 'confirm', 'prompt']) window[name] = () => { throw Error('browser dialog'); };
  const api = async (path, method = 'GET', body) => {
    calls.push({path, method, body: body instanceof Blob ? body : clone(body)});
    if (path === 'materials') {
      if (method === 'GET') return {materials: [...records.values()]};
      const made = {...record('material-gltf' + records.size, body.source), name: body.name};
      made.params = {...made.params, ...body.params}; records.set(made.id, made); return clone(made);
    }
    const [, id, , slot] = path.split('/'); let saved = records.get(id);
    if (method === 'POST' && slot) { await hooks.upload?.(slot, body); saved.maps[slot] = 'maps/' + slot + '-server.png'; saved.revision++; }
    if (method === 'PATCH') { saved = {...saved, ...body, maps: {...saved.maps, ...body.maps}, params: {...saved.params, ...body.params}, revision: saved.revision + 1}; records.set(id, saved); }
    return clone(saved);
  };
  location.search = '?material=material-test';
  const page = mountLibraryPage(host, {api}); await page.ready; tick();
  const input = host.querySelector('[data-gltf-files]');
  const choose = async files => { input.files = files; await fire(input, 'change'); };
  return {host, page, calls, alerts, choices, inputs, records, input, choose,
    status: () => host.querySelector('[role="status"]').textContent, stop() { page.stop(); host.remove(); }};
}
const writes = c => c.calls.filter(x => x.method !== 'GET');

await test('glb_maps_and_factors', async () => {
  const [material, ...rest] = await readGltfMaterials([glbFile(brickGlb())]);
  assert.equal(rest.length, 0); assert.equal(material.name, 'Brick wall');
  // Occlusion shares the metallic-roughness image, so it is one packed ORM map.
  assert.deepEqual(Object.keys(material.maps), ['base_color', 'normal', 'orm']);
  await same(material.maps.base_color, BASE, 'base_color'); await same(material.maps.orm, ORM, 'orm'); await same(material.maps.normal, NORMAL, 'normal');
  // baseColorFactor is linear; the tint is the sRGB hex the colour picker shows.
  assert.deepEqual(material.params, {tint: '#bc89ff', roughness: 0.6, metalness: 0.2, normal_scale: 0.75, normal_convention: 'gl', ao_intensity: 0.5});
  assert.deepEqual(material.problems, []);

  const c = await setup();
  assert.ok(c.input, 'Import glTF file input'); assert.match(c.input.accept, /\.glb/); assert.match(c.input.accept, /\.gltf/); assert.ok(c.input.multiple);
  await c.choose([glbFile(brickGlb())]);
  await until(() => /glTF import/.test(c.status()));
  const w = writes(c);
  assert.deepEqual(w[0], {path: 'materials', method: 'POST', body: {name: 'Brick wall', source: 'gltf', params: material.params}});
  assert.deepEqual(w.slice(1).map(x => [x.method, x.path]), [['POST', 'materials/material-gltf1/maps/base_color'],
    ['POST', 'materials/material-gltf1/maps/normal'], ['POST', 'materials/material-gltf1/maps/orm']]);
  await same(w[1].body, BASE, 'uploaded base'); await same(w[3].body, ORM, 'uploaded orm');
  assert.equal(c.status(), 'glTF import: 3 maps uploaded, 0 failed');
  assert.equal(c.host.querySelector('[data-field="name"]').value, 'Brick wall');
  assert.equal(c.host.querySelector('[data-material="material-gltf1"]').getAttribute('aria-pressed'), 'true');
  assert.deepEqual(c.alerts, []); assert.equal(c.choices.length, 0); assert.equal(c.input.value, '');

  // A .glb dropped on Properties imports instead of asking which texture slot it fills.
  const before = c.calls.length;
  await fire(c.host.querySelector('.library-properties'), 'drop', {dataTransfer: {files: [glbFile(brickGlb())], types: ['Files']}});
  await until(() => c.calls.slice(before).filter(x => x.path.includes('/maps/')).length === 3 && /glTF import/.test(c.status()));
  assert.equal(c.calls.slice(before).find(x => x.method === 'POST').body.source, 'gltf'); assert.equal(c.inputs.length, 0);
  c.stop();
});

await test('multiple_materials_ask_which', async () => {
  const found = await readGltfMaterials([glbFile(twoGlb(), 'woods.glb')]);
  assert.deepEqual(found.map(m => m.name), ['Oak', 'Walnut']);
  await same(found[1].maps.base_color, WALNUT, 'walnut');
  // glTF defaults: a material with no factors is rough 1 and fully metallic.
  assert.deepEqual(found[0].params, {tint: '#ffffff', roughness: 1, metalness: 1, normal_scale: 1, normal_convention: 'gl', ao_intensity: 1});

  const c = await setup({choose: (title, message, options) => options[1].value});
  await c.choose([glbFile(twoGlb(), 'woods.glb')]);
  await until(() => /glTF import/.test(c.status()));
  assert.equal(c.choices.length, 1);
  assert.match(c.choices[0][1], /woods\.glb has 2 materials/);
  assert.deepEqual(c.choices[0][2].map(o => o.label), ['Oak', 'Walnut']);
  const w = writes(c); assert.equal(w[0].body.name, 'Walnut'); assert.equal(w[0].body.params.roughness, 0.4);
  assert.deepEqual(w.slice(1).map(x => x.path.split('/').at(-1)), ['base_color']); await same(w[1].body, WALNUT, 'chosen map');
  c.stop();

  // Cancelling the choice creates nothing.
  const d = await setup();
  await d.choose([glbFile(twoGlb(), 'woods.glb')]);
  await until(() => d.status() === 'glTF import cancelled');
  assert.equal(d.choices.length, 1); assert.deepEqual(writes(d), []); assert.deepEqual(d.alerts, []);
  d.stop();
});

await test('gltf_with_sibling_textures', async () => {
  const BIN_BASE = png(10, 20, 30), MR = png(0, 200, 50), AO = png(180, 180, 180), DATA_NORMAL = png(127, 127, 254);
  const {bin, views} = pack([BIN_BASE]);
  const json = {asset: {version: '2.0'},
    buffers: [{uri: 'scene.bin', byteLength: bin.length}], bufferViews: views,
    images: [{bufferView: 0, mimeType: 'image/png'}, {uri: 'textures/Brick%20Rough.png'}, {uri: 'brick_ao.png'},
      {uri: 'data:image/png;base64,' + DATA_NORMAL.toString('base64')}, {uri: 'http://example.invalid/steal.png'}, {uri: 'missing.png'}],
    textures: [0, 1, 2, 3, 4, 5].map(source => ({source})),
    materials: [
      {name: 'Brick', pbrMetallicRoughness: {baseColorTexture: {index: 0}, metallicRoughnessTexture: {index: 1}},
        normalTexture: {index: 3}, occlusionTexture: {index: 2, strength: 0.8}},
      {name: 'Lost', pbrMetallicRoughness: {baseColorTexture: {index: 4}}, normalTexture: {index: 5}}]};
  const fetched = [], realFetch = globalThis.fetch;
  globalThis.fetch = (input, ...rest) => { fetched.push(String(input.url || input)); return realFetch(input, ...rest); };
  let found;
  try {
    // Order does not matter, and the model is found among its siblings.
    found = await readGltfMaterials([new File([MR], 'Brick Rough.png'), new File([bin], 'scene.bin'),
      new File([JSON.stringify(json)], 'brick.gltf'), new File([AO], 'brick_ao.png')]);
  } finally { globalThis.fetch = realFetch; }
  assert.ok(!fetched.some(url => /^https?:/i.test(url)), 'never fetches a remote URI: ' + fetched.join(', '));
  const [brick, lost] = found;
  // Separate occlusion: the MR image fills roughness (G) and metalness (B); R is never read as AO.
  assert.deepEqual(Object.keys(brick.maps), ['base_color', 'normal', 'roughness', 'metalness', 'ao']);
  await same(brick.maps.base_color, BIN_BASE, 'bin base'); await same(brick.maps.roughness, MR, 'roughness');
  await same(brick.maps.metalness, MR, 'metalness'); await same(brick.maps.ao, AO, 'ao'); await same(brick.maps.normal, DATA_NORMAL, 'data normal');
  assert.equal(brick.params.ao_intensity, 0.8); assert.deepEqual(brick.problems, []);
  assert.deepEqual(lost.maps, {});
  assert.equal(lost.problems.length, 2);
  assert.match(lost.problems[0], /Base colour/); assert.match(lost.problems[0], /steal\.png/);
  assert.match(lost.problems[1], /Normal/); assert.match(lost.problems[1], /missing\.png/);
});

await test('refusals_are_reported_not_uploaded', async () => {
  await assert.rejects(readGltfMaterials([new File([BASE], 'brick_diff.png')]), /Choose a \.glb or \.gltf file/);
  await assert.rejects(readGltfMaterials([glbFile(brickGlb(), 'a.glb'), glbFile(brickGlb(), 'b.glb')]), /one \.glb or \.gltf/);
  await assert.rejects(readGltfMaterials([glbFile(brickGlb())], {maxModelBytes: 64}), /larger than/);
  await assert.rejects(readGltfMaterials([new File(['{"asset":'], 'bad.gltf')]), /could not be read/);
  // Images: an over-cap image and bytes that are not PNG, JPEG or WebP become per-map problems.
  const {bin, views} = pack([BASE, Buffer.from('<script>alert(1)</script>')]);
  const odd = glb({asset: {version: '2.0'}, buffers: [{byteLength: bin.length}], bufferViews: views,
    images: [{bufferView: 0, mimeType: 'image/png'}, {bufferView: 1, mimeType: 'image/png'}], textures: [{source: 0}, {source: 1}],
    materials: [{name: 'Odd', pbrMetallicRoughness: {baseColorTexture: {index: 0}}, normalTexture: {index: 1}}]}, bin);
  const [small] = await readGltfMaterials([glbFile(odd)], {maxImageBytes: 16});
  assert.deepEqual(small.maps, {}); assert.match(small.problems[0], /larger than/);
  const [material] = await readGltfMaterials([glbFile(odd)]);
  assert.deepEqual(Object.keys(material.maps), ['base_color']); assert.match(material.problems[0], /not a PNG, JPEG or WebP/);

  // The page imports what it can and says what it skipped; a broken file creates nothing.
  const c = await setup();
  await c.choose([glbFile(odd)]);
  await until(() => /glTF import/.test(c.status()));
  assert.deepEqual(writes(c).map(x => x.path.split('/').at(-1)), ['materials', 'base_color']);
  assert.equal(c.alerts.length, 1); assert.match(c.alerts[0], /Normal/);
  await c.choose([new File(['nope'], 'broken.glb')]);
  await until(() => c.alerts.length === 2);
  assert.equal(writes(c).length, 2); assert.equal(c.status(), 'glTF import failed');
  c.stop();
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
