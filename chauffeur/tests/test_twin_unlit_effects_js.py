"""Unlit keeps every effect fixture drivable (owner, 2026-11-18: Unlit broke the viewport).

The bubbler's column is a lit-water MeshStandardMaterial that carries its driver
uniforms on `material.uniforms`. Unlit swaps it for a matcap; the driver kept
writing `mesh.material.uniforms.fall` and the first frame threw, stopping the
render loop. Run from chauffeur/: python tests/test_twin_unlit_effects_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {createUnlit} = await import(file('static/twin/unlit.js'));
const builders = await import(file('static/twin/effects/bubbler.js'));
// The real bubbler, swapped to the studio view, posed and driven like a frame.
const built = builders.buildBubbler(), effectRoot = new THREE.Group(); effectRoot.add(built.group);
const unlit = createUnlit(); unlit.apply(effectRoot);
const swappedAway = built.group.children.filter(m => m.material.isMeshMatcapMaterial);
assert.ok(swappedAway.length > 0, 'the lit column is swapped to the studio material');
built.pose(1.5);
for (const mesh of built.group.children) {
  const u = mesh.material.uniforms;
  assert.ok(u && u.time, 'every effect mesh keeps its driver uniforms in Unlit');
  u.time.value = 3; if (u.strength) u.strength.value = .5; if (u.opacity) u.opacity.value = 1;
}
// The swapped material shares the very uniform objects its hook compiles into the shader.
const column = built.group.children.find(m => m.material.isMeshMatcapMaterial && m.material.uniforms.fall);
assert.ok(column, 'the column keeps fall');
assert.equal(column.material.uniforms.fall.value, 1.5, 'pose reaches the uniform the shader reads');
unlit.restore();
assert.equal(built.group.children.find(m => m.material.uniforms?.fall).material.uniforms.fall.value, 1.5);
console.log('ok unlit_keeps_effect_uniforms');
"""


def run():
    directory = Path(tempfile.mkdtemp(prefix='unlit_effects_'))
    try:
        driver = directory / 'driver.mjs'
        driver.write_text(DRIVER, encoding='utf-8')
        data = directory / 'input.json'
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'terrainCases': []}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == '__main__':
    run()
