"""Models mode contract: part keys, override resolution, fix maths, part UVs, occluder inputs."""
from pathlib import Path
import sys
import tempfile

from twin_live_node_rig import run


DRIVER = r'''
const m = await import(file('static/twin/model_parts.js'));
const near = (a, b, eps = 1e-5) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);

// keys_for_duplicates_and_unnamed
assert.deepEqual(m.partKeys(['Wood', null, 'Wood', '', 'Metal', 'Wood']),
  ['Wood', 'unnamed', 'Wood~2', 'unnamed~2', 'Metal', 'Wood~3']);
console.log('ok keys_for_duplicates_and_unnamed');

// resolution_order
const wood = { key: 'Wood', has_uv: true };
assert.deepEqual(m.resolvePart(wood, { Wood: { material: 'oak', texture: 'model', tiles: 3 } }, {}),
  { source: 'model', material: 'oak', texture: 'model', tiles: 3 });
assert.deepEqual(m.resolvePart(wood, { Wood: { material: 'oak' } }, { Wood: { material: 'original' } }),
  { source: 'copy', material: null, texture: 'real', tiles: 1 });
assert.deepEqual(m.resolvePart(wood, { Wood: { material: 'oak', texture: 'model', tiles: 3 } }, { Wood: { material: 'walnut' } }),
  { source: 'copy', material: 'walnut', texture: 'real', tiles: 1 });
assert.deepEqual(m.resolvePart(wood, {}, {}), { source: 'original', material: null, texture: 'real', tiles: 1 });
console.log('ok resolution_order');

// no_uv_forces_real
assert.equal(m.resolvePart({ key: 'Wood', has_uv: false }, { Wood: { material: 'oak', texture: 'model', tiles: 2 } }).texture, 'real');
console.log('ok no_uv_forces_real');

// fix_maths
near(m.fixScale({ height_m: 0.9 }, [2, 0.45, 1]), 2);
near(m.fixScale({ width_m: 1 }, [2, 1, 1]), 0.5);
assert.equal(m.fixScale({}, [2, 1, 1]), 1);
assert.equal(m.fixScale(undefined, [2, 1, 1]), 1);
near(m.fixTurnRadians({ turn: 90 }), Math.PI / 2);
assert.equal(m.fixTurnRadians({ turn: 45 }), 0);
console.log('ok fix_maths');

// model_uv_tiles
assert.deepEqual(Array.from(m.modelUv(new Float32Array([0, 0, 1, 1]), 3, [2, 2])), [0, 0, 6, 6]);
console.log('ok model_uv_tiles');

// box_uv_feet: a 1 m quad facing +z spans 3.28084 ft in u and v
const quad = new Float32Array([0,0,0, 1,0,0, 1,1,0, 0,1,0]), nz = new Float32Array([0,0,1, 0,0,1, 0,0,1, 0,0,1]);
const uv = m.boxUvFeet(quad, nz, 1);
near(uv[2] - uv[0], 3.28084); near(uv[5] - uv[3], 3.28084);
const top = m.boxUvFeet(new Float32Array([0,0,0, 2,0,1]), new Float32Array([0,1,0, 0,1,0]), 0.5);
near(top[2], 3.28084); near(top[3], 3.28084 * 0.5);
console.log('ok box_uv_feet');

// shadow_cast_cases
assert.equal(m.materialCastsShadow({ id: 'oak', params: {} }), true);
assert.equal(m.materialCastsShadow({ id: 'tulle', params: { alpha_mode: 'blend', opacity: 0.5 } }), false);
assert.equal(m.materialCastsShadow({ id: 'leaf', params: { alpha_mode: 'cutout' } }), false);
assert.equal(m.materialCastsShadow({ id: 'glass', params: {} }), false);
console.log('ok shadow_cast_cases');

// occluder_inputs_neutral, including legacy and regenerated records
assert.equal(m.occluderInputs({}), '');
assert.equal(m.occluderInputs({ lods: [{ name: 'lod1.glb', triangles: 10 }, { name: 'lod2.glb', triangles: 2 }] }), '');
assert.equal(m.occluderInputs({ lod_percent: [100, 25, 5], lods: [{ name: 'lod1.glb', percent: 25, revision: 1 }],
  parts: [{ key: 'Wood', opaque: true }, { key: 'Glass', opaque: false }] }), '');
console.log('ok occluder_inputs_neutral');

// occluder_inputs_change_only_on_three
const lib = { oak: { id: 'oak', params: {} }, walnut: { id: 'walnut', params: {} }, glass: { id: 'glass', params: {} } };
const base = () => ({ lod_percent: [100, 25, 5], lods: [{ name: 'lod1.glb', percent: 25, revision: 1 }],
  parts: [{ key: 'Wood', has_uv: true, opaque: true }, { key: 'Glass', has_uv: true, opaque: false }],
  materials: { Wood: { material: 'oak', texture: 'real' } }, fix: { turn: 0 } });
const inputsKey = (r, copy = {}) => m.occluderInputs(r, copy, lib);
const k0 = inputsKey(base());
const changes = {
  turn: r => { r.fix.turn = 90; },
  height: r => { r.fix.height_m = 0.8; },
  midRevision: r => { r.lods[0].revision = 2; },
  midPercent: r => { r.lod_percent = [100, 40, 5]; r.lods[0].percent = 40; },
  glass: r => { r.materials.Wood.material = 'glass'; },
};
for (const [name, change] of Object.entries(changes)) { const r = base(); change(r); assert.notEqual(inputsKey(r), k0, name); }
const same = {
  walnut: r => { r.materials.Wood.material = 'walnut'; },
  textureMode: r => { r.materials.Wood.texture = 'model'; },
  tiles: r => { r.materials.Wood = { material: 'oak', texture: 'model', tiles: 4 }; },
  fullAndFar: r => { r.lod_percent = [60, 25, 2]; },
};
for (const [name, change] of Object.entries(same)) { const r = base(); change(r); assert.equal(inputsKey(r), k0, name); }
// The real page manifest has no entries for the code-side looks (glass,
// screen, water, chain_link); an override to one still stales the lamp.
{
  const pageLib = { oak: { id: 'oak', params: {} }, walnut: { id: 'walnut', params: {} } };
  const pageKey = (r, copy = {}) => m.occluderInputs(r, copy, pageLib);
  const p0 = pageKey(base());
  for (const look of ['glass', 'screen', 'water', 'chain_link']) {
    const r = base(); r.materials.Wood.material = look;
    assert.notEqual(pageKey(r), p0, `override to built-in ${look} changes the shadow input`);
    assert.notEqual(pageKey(base(), { Wood: { material: look } }), p0, `per-copy ${look} changes the shadow input`);
  }
  const metal = base(); metal.materials.Wood.material = 'black_metal';
  assert.equal(pageKey(metal), p0, 'opaque built-in look keeps the key');
  const kinds = await import(file('static/twin/surface_kinds.js'));
  assert.deepEqual([...m.SHADOWLESS_BUILTIN_LOOKS].sort(),
    Object.keys(kinds.BUILTIN_LOOKS).filter(id => kinds.builtinAlphaMode(id) !== 'opaque').sort(),
    'shadowless list matches surface_kinds');
  console.log('ok builtin_looks_resolve_without_manifest');
}
assert.notEqual(inputsKey(base(), { Wood: { material: 'glass' } }), k0, 'copy glass override');
assert.equal(inputsKey(base(), { Wood: { material: 'original' } }), k0, 'copy original (opaque) override');
console.log('ok occluder_inputs_change_only_on_three');
'''


if __name__ == '__main__':
    tempfile.tempdir = str(Path(__file__).resolve().parents[2])
    sys.exit(run(DRIVER, {}, prefix='.model_parts_', timeout=60))
