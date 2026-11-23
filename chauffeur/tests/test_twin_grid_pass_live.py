"""Chromium GPU test for the light-visibility grid accumulator (grid_pass.js).

Verifies that createGridAccumulator matches a CPU BVH reference using the exact
same 16 jittered samples and depth bias test (step(reached - 0.02, stored)),
handles fractional weighted visibility normalization, and isolates multiple emitters.

Run from chauffeur/: python tests/test_twin_grid_pass_live.py
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

SCENE = r"""
async () => {
  const THREE = await import('three'), B = window.chfBase;
  const { FT } = await import(B + 'static/twin/twin_light_math.js');
  const { gridLayout, gridPoints, pointsInRange } = await import(B + 'static/twin/bake/grid_layout.js');
  const { legacySamples } = await import(B + 'static/twin/bake/fixture_terms.js');
  const { buildOccluderBVH } = await import(B + 'static/twin/live/cone_occluder.js');
  const { createGridAccumulator } = await import(B + 'static/twin/bake/grid_pass.js');

  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setSize(64, 64);
  renderer.toneMapping = THREE.NoToneMapping;

  // Room: 12 x 10 x 8 ft, divided cleanly in half by a wall at x = 6 ft.
  const rect = [[0, 0], [12, 0], [12, 10], [0, 10]];
  const plan = {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house', position: [0, 0], rotation: 0, base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 8 }],
      walls: [],
      rooms: [{ id: 'room', level: 'L1', polygon: rect }],
    }],
    site: { lot: [[-5, -5], [20, -5], [20, 20], [-5, 20]] },
  };
  const lampPos = new THREE.Vector3(2.5 * FT, 4.0 * FT, -5.0 * FT);
  const range = 20 * FT;
  const far = Math.max(range * 2, 30);

  const layout = gridLayout(plan, [{ source: lampPos, range, outdoor: false }]);
  const points = gridPoints(layout);
  const indices = pointsInRange(layout, points, lampPos, range);

  // Full dividing wall at x = 6.0 ft (0.4 ft thick), extending past room bounds on y and z.
  const wall = new THREE.Mesh(
    new THREE.BoxGeometry(0.4 * FT, 12 * FT, 14 * FT),
    new THREE.MeshStandardMaterial({ name: 'wall' })
  );
  wall.position.set(6.0 * FT, 4.0 * FT, -5.0 * FT);
  wall.updateMatrixWorld(true);

  const blockerScene = new THREE.Scene();
  blockerScene.add(wall);
  blockerScene.updateMatrixWorld(true);

  // Exact shadow cube setup from bake_pass.js:186-194
  const shadow = new THREE.WebGLCubeRenderTarget(512, {
    type: THREE.HalfFloatType,
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
  });
  const cube = new THREE.CubeCamera(0.02, far, shadow);
  cube.coordinateSystem = THREE.WebGLCoordinateSystem;
  cube.updateCoordinateSystem();

  const worldVertex = `varying vec3 wp;
void main() { wp = (modelMatrix * vec4(position, 1.0)).xyz;
gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0); }`;
  const depth = new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    vertexShader: worldVertex,
    uniforms: { source: { value: lampPos.clone() }, farPlane: { value: far } },
    fragmentShader: `uniform vec3 source; uniform float farPlane; varying vec3 wp;
void main(){gl_FragColor = vec4(vec3(length(wp-source)/farPlane),1.0);}`,
  });
  blockerScene.overrideMaterial = depth;

  const renderShadow = src => {
    cube.position.copy(src);
    depth.uniforms.source.value.copy(src);
    renderer.autoClear = true;
    renderer.setClearColor(0xffffff, 1);
    cube.updateMatrixWorld(true);
    for (let face = 0; face < 6; face++) {
      renderer.setRenderTarget(shadow, face);
      renderer.render(blockerScene, cube.children[face]);
    }
    renderer.setRenderTarget(null);
  };

  const bvh = buildOccluderBVH([wall]);
  const cpuRef = (sampleList, emitterCount) => {
    const out = new Uint8Array(indices.length * emitterCount);
    const wSums = new Float64Array(emitterCount);
    for (const s of sampleList) wSums[s.emitter] += s.weight;
    const sums = new Float64Array(indices.length * emitterCount);
    for (const s of sampleList) {
      for (let i = 0; i < indices.length; i++) {
        const pIdx = indices[i];
        const px = points[pIdx * 3], py = points[pIdx * 3 + 1], pz = points[pIdx * 3 + 2];
        const dx = px - s.source.x, dy = py - s.source.y, dz = pz - s.source.z;
        const reached = Math.hypot(dx, dy, dz);
        let stored = far;
        if (reached > 1e-5) {
          const inv = 1 / reached;
          stored = bvh.castRay(s.source.x, s.source.y, s.source.z, dx * inv, dy * inv, dz * inv, 0.02, far);
        }
        if (stored >= reached - 0.02) sums[i * emitterCount + s.emitter] += s.weight;
      }
    }
    for (let i = 0; i < indices.length; i++) {
      for (let e = 0; e < emitterCount; e++) {
        const w = wSums[e];
        out[i * emitterCount + e] = w > 0 ? Math.round(Math.min(1, Math.max(0, sums[i * emitterCount + e] / w)) * 254) : 0;
      }
    }
    return out;
  };

  // --- 1. Single emitter: 16 jittered samples, wall between lamp and half the points ---
  const samples = legacySamples(lampPos, range);
  const acc = createGridAccumulator(renderer, points, indices, 1);
  for (const s of samples) {
    renderShadow(s.source);
    acc.sample(shadow.texture, s.source, far, s.emitter, s.weight);
  }
  const gpu = acc.read();
  acc.dispose();
  const cpu = cpuRef(samples, 1);

  let maxDiff = 0, fullLit = 0, fullDark = 0;
  for (let i = 0; i < indices.length; i++) {
    const d = Math.abs(gpu[i] - cpu[i]);
    if (d > maxDiff) maxDiff = d;
    if (gpu[i] === 254) fullLit++;
    if (gpu[i] === 0) fullDark++;
  }

  // --- 2. Partial visibility & unnormalized uneven weights (16 samples split across the wall) ---
  const weightedSamples = Array.from({ length: 16 }, (_, i) => ({
    source: new THREE.Vector3((i < 11 ? 2.0 + i * 0.25 : 7.0 + (i - 11) * 0.25) * FT, 4.0 * FT, -5.0 * FT),
    emitter: 0,
    weight: i + 1, // sum = 136; west = 66, east = 70
  }));
  const accW = createGridAccumulator(renderer, points, indices, 1);
  for (const s of weightedSamples) {
    renderShadow(s.source);
    accW.sample(shadow.texture, s.source, far, s.emitter, s.weight);
  }
  const gpuW = accW.read();
  accW.dispose();
  const cpuW = cpuRef(weightedSamples, 1);
  let maxDiffW = 0;
  for (let i = 0; i < indices.length; i++) {
    const d = Math.abs(gpuW[i] - cpuW[i]);
    if (d > maxDiffW) maxDiffW = d;
  }

  // --- 3. Multi-emitter (2 emitters on opposite sides of the wall) ---
  const eastPos = new THREE.Vector3(9.5 * FT, 4.0 * FT, -5.0 * FT);
  const multiSamples = [
    ...legacySamples(lampPos, range),
    ...legacySamples(eastPos, range).map(s => ({ ...s, emitter: 1 })),
  ];
  const acc2 = createGridAccumulator(renderer, points, indices, 2);
  for (const s of multiSamples) {
    renderShadow(s.source);
    acc2.sample(shadow.texture, s.source, far, s.emitter, s.weight);
  }
  const gpu2 = acc2.read();
  acc2.dispose();
  const cpu2 = cpuRef(multiSamples, 2);
  let maxDiff2 = 0;
  for (let i = 0; i < gpu2.length; i++) {
    const d = Math.abs(gpu2[i] - cpu2[i]);
    if (d > maxDiff2) maxDiff2 = d;
  }

  // --- 4. Empty accumulator edge case ---
  const accEmpty = createGridAccumulator(renderer, points, new Uint32Array(0), 1);
  accEmpty.sample(shadow.texture, lampPos, far, 0, 1);
  const emptyLen = accEmpty.read().length;
  accEmpty.dispose();

  const findPoint = (xFt, yFt, zFt) => {
    for (let i = 0; i < indices.length; i++) {
      const pIdx = indices[i];
      if (Math.abs(points[pIdx * 3] / FT - xFt) < 0.1 &&
          Math.abs(-points[pIdx * 3 + 2] / FT - yFt) < 0.1 &&
          Math.abs(points[pIdx * 3 + 1] / FT - zFt) < 0.1) return i;
    }
    return -1;
  };
  const westI = findPoint(1.5, 4.5, 4.5);
  const eastI = findPoint(10.5, 4.5, 4.5);

  const gl = renderer.getContext();
  const glErr = gl.getError();

  depth.dispose();
  shadow.dispose();
  wall.geometry.dispose();
  wall.material.dispose();
  renderer.dispose();

  return {
    count: indices.length,
    gpuLength: gpu.length,
    maxDiff,
    fullLit,
    fullDark,
    westSingle: gpu[westI],
    eastSingle: gpu[eastI],
    maxDiffW,
    westWeighted: [gpuW[westI], cpuW[westI]],
    eastWeighted: [gpuW[eastI], cpuW[eastI]],
    maxDiff2,
    westMulti: [gpu2[westI * 2], gpu2[westI * 2 + 1]],
    eastMulti: [gpu2[eastI * 2], gpu2[eastI * 2 + 1]],
    emptyLen,
    glErr,
  };
}
"""


def run():
    served = L.serve()
    L.reset()
    failures = []
    errors = []
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1200, 'height': 800})
        page.on('console', lambda m: errors.append(m.text[:400]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        L.H.signed_in(page)
        L.open_twin(page, served, query='tier=high&test=1')
        result = page.evaluate(SCENE)
    print('MEASURED', json.dumps(result))

    def check(name, fn):
        try:
            fn()
            print('  ok   ' + name)
        except AssertionError as error:
            failures.append(name)
            print('  FAIL ' + name + ' ' + str(error)[:600])
            traceback.print_exc(limit=1)

    def test_accumulator_matches_cpu():
        assert not errors, f'console errors: {errors[:3]}'
        assert result['glErr'] == 0, f'GL error: {result["glErr"]}'
        assert result['gpuLength'] == result['count'] and result['count'] == 960, result
        assert result['fullLit'] == 480 and result['fullDark'] == 480, f'half visible (480) and half behind wall (480): {result}'
        assert result['westSingle'] == 254, f'fully visible point gives 254: {result}'
        assert result['eastSingle'] == 0, f'point fully behind wall gives 0: {result}'
        assert result['maxDiff'] <= 2, f'GPU accumulator differs from CPU reference by > 2/254: {result}'

    def test_partial_visibility_and_weights():
        assert result['maxDiffW'] <= 2, f'weighted fractional visibility mismatch: {result}'
        assert 100 < result['westWeighted'][0] < 150, f'expected intermediate west visibility: {result}'
        assert 100 < result['eastWeighted'][0] < 150, f'expected intermediate east visibility: {result}'

    def test_multi_emitter_and_empty():
        assert result['maxDiff2'] <= 2, f'2-emitter mismatch: {result}'
        assert result['westMulti'] == [254, 0], f'west point sees emitter 0 (254) not 1 (0): {result}'
        assert result['eastMulti'] == [0, 254], f'east point sees emitter 1 (254) not 0 (0): {result}'
        assert result['emptyLen'] == 0, result

    for name, fn in (
        ('test_accumulator_matches_cpu', test_accumulator_matches_cpu),
        ('test_partial_visibility_and_weights', test_partial_visibility_and_weights),
        ('test_multi_emitter_and_empty', test_multi_emitter_and_empty),
    ):
        check(name, fn)
    print(f'{3 - len(failures)}/3 passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run())
