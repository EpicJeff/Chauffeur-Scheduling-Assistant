"""Alpha controls, preview and actual glTF import event paths under node."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE = await import('three');
const loaded = [];
THREE.TextureLoader.prototype.load = function(url, done) {
  loaded.push(url); const t = new THREE.Texture({width: 2, height: 2}); queueMicrotask(() => done(t)); return t;
};
const {mountProperties, defaults} = await import(file('static/twin/library_page/properties.js'));
const {createPreview} = await import(file('static/twin/library_page/preview.js'));
const {readGltfMaterials} = await import(file('static/twin/library_page/gltf_import.js'));
const {slotForFilename} = await import(file('static/twin/library_page/texture_slots.js'));
const {mountLibraryPage} = await import(file('static/twin/library_page/page.js'));
const clone = x => structuredClone(x), pause = ms => new Promise(r => setTimeout(r, ms));
const record = (mode = 'opaque', source = 'user') => ({id: 'material-alpha', name: 'Alpha', source,
  revision: 1, maps: {}, params: {...clone(defaults), alpha_mode: mode, opacity: 1, alpha_cutoff: .5}});
const field = (host, key, type = 'range') => host.querySelector(`[data-param="${key}"][type="${type}"]`);
const modeChoice = host => host.querySelector('[data-param="alpha_mode"]');
const edit = async (input, type, value) => { assert.ok(input, 'control exists'); input.value = value; await fire(input, type); };
function properties(entry = record()) {
  const host = document.createElement('aside'), changes = [], uploads = [], clears = [];
  const handlers = {change: x => changes.push(x), replaceMap: (...args) => uploads.push(args),
    clearMap: x => clears.push(x), uploadTextures() {}, signal: new AbortController().signal};
  document.body.append(host);
  const mounted = mountProperties(host, entry, handlers);
  return {host, changes, uploads, clears, mounted, remount: next => mountProperties(host, next, handlers)};
}
await test('mode_choice_shows_the_right_slider', async () => {
  const c = properties(), entry = record();
  assert.ok(modeChoice(c.host), 'mode control found');
  const visible = key => !!field(c.host, key) && shown(field(c.host, key));
  assert.equal(visible('opacity'), false); assert.equal(visible('alpha_cutoff'), false);
  await edit(modeChoice(c.host), 'change', 'blend');
  assert.deepEqual(c.changes, [{params: {alpha_mode: 'blend'}}]);
  entry.params.alpha_mode = 'blend'; c.remount(entry);
  assert.equal(visible('opacity'), true); assert.equal(visible('alpha_cutoff'), false);
  entry.params.alpha_mode = 'cutout'; c.remount(entry);
  assert.equal(visible('opacity'), false); assert.equal(visible('alpha_cutoff'), true);
  assert.equal(field(c.host, 'alpha_cutoff').min, '0.01');
  assert.equal(field(c.host, 'alpha_cutoff').max, '1'); assert.equal(field(c.host, 'alpha_cutoff').step, '0.01');
});
await test('mode_and_slider_visibility_sync_without_remount', async () => {
  const c = properties(); c.mounted.sync(record('blend'));
  assert.equal(modeChoice(c.host).value, 'blend'); assert.ok(shown(field(c.host, 'opacity')));
  c.mounted.sync(record('cutout')); assert.ok(shown(field(c.host, 'alpha_cutoff')));
  assert.equal(shown(field(c.host, 'opacity')), false);
});
await test('sliders_send_numbers_and_number_changes_clamp', async () => {
  for (const [mode, key, min] of [['blend', 'opacity', 0], ['cutout', 'alpha_cutoff', .01]]) {
    const c = properties(record(mode));
    await edit(field(c.host, key), 'input', '0.35');
    assert.deepEqual(c.changes.pop(), {params: {[key]: .35}});
    for (const [raw, expected] of [['-1', min], ['5', 1]]) {
      await edit(field(c.host, key, 'number'), 'change', raw);
      assert.deepEqual(c.changes.pop(), {params: {[key]: expected}});
    }
    for (const raw of ['', 'no number']) await edit(field(c.host, key, 'number'), 'input', raw);
    assert.equal(c.changes.length, 0);
  }
});
await test('opacity_slot_uploads_and_clears', async () => {
  const c = properties(), row = c.host.querySelector('[data-slot="opacity"]');
  assert.ok(row, 'Opacity map slot'); const input = row.querySelector('input[type="file"]');
  const blob = new File(['mask'], 'leaf_alpha.png', {type: 'image/png'}); input.files = [blob];
  await fire(input, 'change'); await click(row.querySelector('[data-action="clear"]'));
  assert.deepEqual(c.uploads, [['opacity', blob]]); assert.deepEqual(c.clears, ['opacity']);
});
await test('derived_opacity_is_explained_and_manual_map_is_not', async () => {
  const entry = record('cutout'); entry.opacity_derived = true; entry.maps.opacity = 'maps/mask.png';
  const c = properties(entry), row = c.host.querySelector('[data-slot="opacity"]');
  assert.ok(row); assert.match(row.textContent, /From the base colour.s transparency/);
  assert.ok(row.querySelector('img').src.endsWith('maps/mask.png'));
  c.mounted.sync({...entry, opacity_derived: false});
  assert.doesNotMatch(row.textContent, /From the base colour.s transparency/);
});
await test('opaque_opacity_map_note_tracks_mode_and_map_presence', async () => {
  const entry = record(); entry.maps.opacity = 'maps/mask.png';
  const c = properties(entry), row = c.host.querySelector('[data-slot="opacity"]');
  const note = () => row.querySelectorAll('p').find(p => p.textContent === 'Not used while the mode is Opaque');
  assert.ok(note()); assert.equal(note().className, c.host.querySelector('[data-slot="height"] p').className);
  assert.ok(shown(note()));
  for (const mode of ['cutout', 'blend']) {
    c.mounted.sync({...entry, params: {...entry.params, alpha_mode: mode}});
    assert.ok(!note() || !shown(note()));
  }
  c.mounted.sync(entry); assert.ok(shown(note()));
  c.mounted.sync({...entry, maps: {}}); assert.ok(!note() || !shown(note()));
  c.mounted.sync({...entry, maps: {}, previewMaps: {opacity: 'blob:mask'}}); assert.ok(shown(note()));
});
await test('read_only_builtin_shows_no_controls', async () => {
  const c = properties(record('blend', 'builtin'));
  assert.equal(c.host.querySelectorAll('input,select,button').length, 0);
  assert.match(c.host.textContent, /Blend/); assert.match(c.host.textContent, /Duplicate to edit/);
});
function gltf(mode, extra = {}) {
  return new File([JSON.stringify({asset: {version: '2.0'}, materials: [{name: 'Leaf',
    ...(mode ? {alphaMode: mode} : {}), ...extra}]})], 'leaf.gltf');
}
await test('gltf_mask_blend_opaque_map_to_modes', async () => {
  const [mask] = await readGltfMaterials([gltf('MASK', {alphaCutoff: .3})]);
  assert.equal(mask.params.alpha_mode, 'cutout'); assert.equal(mask.params.alpha_cutoff, .3);
  assert.equal('opacity' in mask.params, false);
  const [blend] = await readGltfMaterials([gltf('BLEND', {pbrMetallicRoughness: {baseColorFactor: [1,1,1,.5]}})]);
  assert.equal(blend.params.alpha_mode, 'blend'); assert.equal(blend.params.opacity, .5);
  assert.equal('alpha_cutoff' in blend.params, false);
  for (const mode of ['OPAQUE', undefined]) {
    const [out] = await readGltfMaterials([gltf(mode)]);
    assert.equal(out.params.alpha_mode, 'opaque'); assert.equal('opacity' in out.params, false);
  }
  const [defaultMask] = await readGltfMaterials([gltf('MASK')]); assert.equal(defaultMask.params.alpha_cutoff, .5);
  const [defaultBlend] = await readGltfMaterials([gltf('BLEND')]); assert.equal(defaultBlend.params.opacity, 1);
});
await test('filename_suffixes_route_to_opacity', async () => {
  for (const suffix of ['opacity', 'alpha', 'mask'])
    for (const name of [`leaf_${suffix}.png`, `leaf-${suffix.toUpperCase()}_2k.webp`])
      assert.deepEqual(slotForFilename(name), {slot: 'opacity'});
  assert.deepEqual(slotForFilename('leaf_diff.png'), {slot: 'base_color'});
  assert.deepEqual(slotForFilename('leaf_nor_dx_2k.png'), {slot: 'normal', convention: 'dx'});
});
let drawn;
const render = Renderer.prototype.render;
Renderer.prototype.render = function(scene, camera) {
  scene.traverse(n => { if (n.userData.librarySample) drawn = n; }); return render.call(this, scene, camera);
};
await test('read_only_lattice_mode_matches_the_kit_preview', async () => {
  const previous = window.twinKit;
  window.twinKit = {materials: {screen: {asset: 'material-alpha', pattern: 'lattice', color: '#ffffff'}}, manifest: {}};
  try {
    const c = properties(record('opaque', 'builtin'));
    const row = c.host.querySelectorAll('label').find(label => label.textContent.startsWith('Alpha mode'));
    assert.equal(row.querySelector('output').textContent, 'Cutout');
    assert.equal(c.host.querySelectorAll('input,select,button').length, 0);
    const p = createPreview(document.createElement('canvas'));
    try { p.setMaterial(record('opaque', 'builtin')); tick(); assert.equal(drawn.material.userData.alphaMode, 'cutout'); }
    finally { p.dispose(); }
  } finally { window.twinKit = previous; }
});
await test('preview_material_follows_mode', async () => {
  const p = createPreview(document.createElement('canvas')), entry = record('blend');
  p.setMaterial(entry); tick(); const first = drawn.material;
  assert.equal(first.transparent, true); assert.equal(first.depthWrite, false);
  p.setMaterial({...entry, params: {...entry.params, opacity: .35}}); tick();
  assert.equal(drawn.material, first); assert.equal(first.opacity, .35);
  let disposed = 0; first.addEventListener('dispose', () => disposed++);
  p.setMaterial({...entry, params: {...entry.params, alpha_mode: 'opaque'}}); tick();
  assert.notEqual(drawn.material, first); assert.equal(disposed, 1); assert.equal(drawn.material.transparent, false);
  p.setMaterial(record('cutout')); tick(); const cutout = drawn.material;
  p.setMaterial({...record('cutout'), params: {...entry.params, alpha_mode: 'cutout', alpha_cutoff: .3}}); tick();
  assert.equal(drawn.material, cutout); assert.equal(cutout.alphaTest, .3); p.dispose();
});
await test('local_opacity_map_attaches_and_tiles_in_preview', async () => {
  const p = createPreview(document.createElement('canvas')), entry = record('cutout');
  p.setMaterial({...entry, previewMaps: {opacity: 'blob:mask'} }); await pause(5); tick();
  assert.ok(drawn.material.alphaMap); assert.equal(drawn.material.alphaMap.colorSpace, THREE.NoColorSpace);
  p.setMaterial({...entry, previewMaps: {opacity: 'blob:mask'}}, {...entry.params, tile_ft: [8, 2]}); tick();
  assert.deepEqual(drawn.material.alphaMap.repeat.toArray(), [1/8, 1/2]); p.dispose();
});
async function pageSetup(resetFailure) {
  const host = document.createElement('main'), calls = [], records = new Map(), alerts = []; document.body.append(host);
  window.showGlobalAlert = text => { if (!resetFailure) throw Error(text); alerts.push(text); }; window.promptConfirm = async () => true;
  const api = async (path, method = 'GET', body) => {
    calls.push({path, method, body});
    if (path === 'materials') {
      if (method === 'GET') return {materials: [...records.values()].map(clone)};
      const row = {...record(body.params?.alpha_mode), id: 'material-import', source: 'gltf'};
      row.params = {...row.params, ...body.params}; records.set(row.id, row); return clone(row);
    }
    if (method === resetFailure) throw Error('Transparency reset rejected');
    const [, id,, slot] = path.split('/'), row = records.get(id);
    if (method === 'POST' && slot) {
      row.maps[slot] = 'maps/base.png';
      if (slot === 'base_color') {
        row.maps.opacity = 'maps/derived.png'; row.opacity_derived = true;
        if (row.params.alpha_mode === 'opaque') row.params.alpha_mode = 'cutout';
      }
    }
    if (method === 'DELETE' && slot) { delete row.maps[slot]; row.opacity_derived = false; }
    if (method === 'PATCH') row.params = {...row.params, ...body.params};
    return clone(row);
  };
  location.search = ''; const page = mountLibraryPage(host, {api}); await page.ready;
  return {host, calls, records, alerts, page};
}
function texturedGltf(mode, baseColorTexture = {index: 0}) {
  // Image bytes pass through without browser decoding, as in the real importer.
  return new File([JSON.stringify({asset: {version: '2.0'}, images: [{uri: 'leaf.png'}], textures: [{source: 0}],
    materials: [{alphaMode: mode, alphaCutoff: .3, pbrMetallicRoughness: {
      baseColorTexture, baseColorFactor: [1,1,1,.5]}}]})], 'leaf.gltf');
}
await test('page_import_restores_opaque_after_rgba_upload_and_removes_derived_mask', async () => {
  const c = await pageSetup(), input = c.host.querySelector('[data-gltf-files]');
  input.files = [texturedGltf('OPAQUE'), new File([new Uint8Array([137,80,78,71,13,10,26,10])], 'leaf.png')];
  await fire(input, 'change'); const row = c.records.get('material-import');
  assert.equal(row.params.alpha_mode, 'opaque'); assert.equal('opacity' in row.maps, false);
  const writes = c.calls.filter(x => x.method !== 'GET');
  assert.deepEqual(writes.map(x => [x.method, x.path]), [
    ['POST', 'materials'], ['POST', 'materials/material-import/maps/base_color'],
    ['DELETE', 'materials/material-import/maps/opacity'], ['PATCH', 'materials/material-import']]);
  assert.equal(writes.at(-1).body.params.alpha_mode, 'opaque'); c.page.stop(); c.host.remove();
});
for (const failure of ['DELETE', 'PATCH']) await test('page_import_keeps_counts_and_problems_when_reset_fails_' + failure, async () => {
  const c = await pageSetup(failure), input = c.host.querySelector('[data-gltf-files]');
  try {
    input.files = [texturedGltf('OPAQUE', {index: 0, texCoord: 1}),
      new File([new Uint8Array([137,80,78,71,13,10,26,10])], 'leaf.png')];
    await assert.doesNotReject(() => fire(input, 'change'));
    assert.equal(c.host.querySelector('[role="status"]').textContent, 'glTF import: 1 maps uploaded, 0 failed');
    // showGlobalAlert replaces its current message, so both reports must share one alert.
    assert.equal(c.alerts.length, 1);
    assert.ok(c.alerts[0].includes("The texture's transparency could not be turned off and the material is still set to Cutout."));
    assert.match(c.alerts[0], /Not everything in the glTF carried over:[\s\S]*second UV set/);
    assert.equal(c.records.get('material-import').params.alpha_mode, 'cutout');
    assert.equal(modeChoice(c.host).value, 'cutout'); assert.equal(input.value, '');
  } finally { c.page.stop(); c.host.remove(); }
});
await test('alpha_number_typing_survives_sync_and_saves_only_valid_values', async () => {
  for (const [mode, key, typed] of [['MASK', 'alpha_cutoff', '0.3'], ['BLEND', 'opacity', '0.4']]) {
    const c = await pageSetup(), picker = c.host.querySelector('[data-gltf-files]');
    try {
      picker.files = [gltf(mode)]; await fire(picker, 'change');
      const input = field(c.host, key, 'number'); input.focus();
      for (const raw of ['', '0', '0.', typed]) {
        await edit(input, 'input', raw); assert.equal(input.value, raw, 'typing is preserved');
        await pause(340); assert.equal(input.value, raw, 'server sync preserves focused text');
      }
      assert.equal(c.records.get('material-import').params[key], Number(typed));
      const values = c.calls.filter(call => call.method === 'PATCH').map(call => call.body.params[key]);
      assert.ok(values.includes(Number(typed))); assert.ok(values.every(value => value >= (key === 'alpha_cutoff' ? .01 : 0)));
      input.blur(); await edit(input, 'change', '5'); assert.equal(input.value, '1');
      await edit(input, 'change', '-1'); assert.equal(input.value, key === 'alpha_cutoff' ? '0.01' : '0');
    } finally { c.page.stop(); c.host.remove(); }
  }
});
await test('page_mode_change_updates_slider_and_saves_then_import_preserves_mask_and_blend', async () => {
  for (const [mode, expected] of [['MASK', 'cutout'], ['BLEND', 'blend']]) {
    const c = await pageSetup(), input = c.host.querySelector('[data-gltf-files]');
    input.files = [texturedGltf(mode), new File([new Uint8Array([137,80,78,71,13,10,26,10])], 'leaf.png')];
    await fire(input, 'change'); const row = c.records.get('material-import');
    assert.equal(row.params.alpha_mode, expected); assert.ok(row.maps.opacity);
    assert.ok(c.host.querySelector('[data-slot="opacity"] img').src);
    await edit(modeChoice(c.host), 'change', 'blend');
    assert.ok(shown(field(c.host, 'opacity'))); await edit(field(c.host, 'opacity'), 'input', '.4');
    assert.equal(drawn.material.opacity, .4); await pause(340); assert.equal(row.params.opacity, .4);
    c.page.stop(); c.host.remove();
  }
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
