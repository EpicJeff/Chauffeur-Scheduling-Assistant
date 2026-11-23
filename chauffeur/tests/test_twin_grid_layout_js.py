"""Node CPU tests for light-visibility grid layout, inside-solid mask, and chunk codec.

Run from chauffeur/: python tests/test_twin_grid_layout_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
import { gunzipSync } from 'node:zlib';
import { randomFillSync } from 'node:crypto';

const THREE = await import(three);
const { FT } = await import(file('static/twin/twin_light_math.js'));
const { groundAt } = await import(file('static/twin/twin_ground.js'));
const { buildOccluderBVH } = await import(file('static/twin/live/cone_occluder.js'));
const { gridLayout, gridPoints, pointsInRange, insideMask } = await import(file('static/twin/bake/grid_layout.js'));
const { encodeGridChunk, decodeGridChunk, MAX_CHUNK_BYTES } = await import(file('static/twin/bake/grid_chunk.js'));

const near = (a, b, eps = 1e-4, msg = '') =>
  assert.ok(Math.abs(a - b) <= eps, `${msg}: expected ${b}, got ${a}`);

function basePlan() {
  const rect = [[0, 0], [10, 0], [10, 12], [0, 12]];
  return {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house',
      position: [0, 0],
      rotation: 0,
      base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 9, outline: rect }],
      walls: [],
      rooms: [{ id: 'living', level: 'L1', polygon: rect }],
      openings: [],
      roof: { sections: [] },
      items: [{ id: 'sofa', asset: 'sofa-1', at: [5, 5, 0], rotation: 0 }],
    }],
    site: {
      lot: [[-20, -20], [40, -20], [40, 40], [-20, 40]],
      terraces: [],
      furniture: [{ id: 'chair', asset: 'chair-1', at: [20, 20], rotation: 0 }],
    },
  };
}

// 1. test_room_grid_dims
{
  const plan = basePlan();
  const lamp = { source: { x: 5 * FT, y: 8 * FT, z: -6 * FT }, range: 15 * FT, outdoor: false };
  const layout = gridLayout(plan, [lamp]);
  assert.equal(layout.blocks.length, 1, 'one room block');
  const b = layout.blocks[0];
  assert.equal(b.kind, 'room');
  assert.equal(b.atlasRoom, 0);
  assert.equal(b.building, 'house');
  assert.equal(b.level, 'L1');
  assert.equal(b.first, 0);
  near(b.spacing, FT, 1e-6, 'indoor spacing is 1 ft');
  assert.deepEqual(b.dims, [10, 12, 9], '10 x 12 x 9 room dims');
  assert.equal(layout.count, 10 * 12 * 9);

  const pts = gridPoints(layout);
  assert.equal(pts.length, layout.count * 3);
  const v = new THREE.Vector3();
  const [nx, ny, nz] = b.dims;
  for (let iz = 0; iz < nz; iz++) {
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const idx = b.first + (iz * ny + iy) * nx + ix;
        const wx = pts[idx * 3], wy = pts[idx * 3 + 1], wz = pts[idx * 3 + 2];
        near(wx, (ix + 0.5) * FT, 1e-5, `x at (${ix},${iy},${iz})`);
        near(wy, (iz + 0.5) * FT, 1e-5, `y at (${ix},${iy},${iz})`);
        near(wz, -(iy + 0.5) * FT, 1e-5, `z at (${ix},${iy},${iz})`);
        v.set(wx, wy, wz).applyMatrix4(b.toLocal);
        near(v.x, ix + 0.5, 1e-4, 'toLocal x');
        near(v.y, iy + 0.5, 1e-4, 'toLocal y');
        near(v.z, iz + 0.5, 1e-4, 'toLocal z');
      }
    }
  }

  // Rotated & translated building with non-zero base
  const rotPlan = basePlan();
  rotPlan.buildings[0].position = [10, 4];
  rotPlan.buildings[0].rotation = 90;
  rotPlan.buildings[0].base = 2;
  // Local (5, 6, 8) rotated 90 deg CCW -> (-6, 5) + (10, 4) = (4, 9), height = 10
  const rotLamp = { source: { x: 4 * FT, y: 10 * FT, z: -9 * FT }, range: 15 * FT, outdoor: false };
  const rotLayout = gridLayout(rotPlan, [rotLamp]);
  assert.equal(rotLayout.blocks.length, 1);
  assert.deepEqual(rotLayout.blocks[0].dims, [10, 12, 9]);
  const rotPts = gridPoints(rotLayout);
  // Local (0.5, 0.5, 0.5) -> rotated (-0.5, 0.5) + (10, 4) = (9.5, 4.5), y = 2.5
  near(rotPts[0], 9.5 * FT, 1e-4, 'rotated x0');
  near(rotPts[1], 2.5 * FT, 1e-4, 'rotated y0');
  near(rotPts[2], -4.5 * FT, 1e-4, 'rotated z0');
  v.set(rotPts[0], rotPts[1], rotPts[2]).applyMatrix4(rotLayout.blocks[0].toLocal);
  near(v.x, 0.5, 1e-4, 'rotated toLocal x');
  near(v.y, 0.5, 1e-4, 'rotated toLocal y');
  near(v.z, 0.5, 1e-4, 'rotated toLocal z');
  console.log('Passed: test_room_grid_dims');
}

// 2. test_room_without_lamp_has_no_block
{
  const plan = basePlan();
  plan.buildings[0].rooms.push({
    id: 'far_room',
    level: 'L1',
    polygon: [[50, 0], [60, 0], [60, 10], [50, 10]],
  });
  const lamp = { source: { x: 5 * FT, y: 5 * FT, z: -6 * FT }, range: 15 * FT, outdoor: false };
  const layout = gridLayout(plan, [lamp]);
  assert.equal(layout.blocks.length, 1, 'only the lit room gets a block');
  assert.equal(layout.blocks[0].atlasRoom, 0);

  const empty = gridLayout(plan, []);
  assert.equal(empty.blocks.length, 0, 'no lamps -> no blocks');
  assert.equal(empty.count, 0);
  console.log('Passed: test_room_without_lamp_has_no_block');
}

// 3. test_yard_grid_follows_ground
{
  const plan = basePlan();
  plan.buildings = [];
  plan.site.lot = [[0, 0], [30, 0], [30, 30], [0, 30]];
  plan.site.terraces = [{
    id: 'slope_pad',
    polygon: [[14, 0], [30, 0], [30, 30], [14, 30]],
    height: -4,
    blend: 12,
    edges: [0, 1, 2, 3].map(() => ({ edge: 'slope' })),
  }];
  const yLamp = { source: { x: 12 * FT, y: 4 * FT, z: -15 * FT }, range: 12 * FT, outdoor: true };
  const layout = gridLayout(plan, [yLamp]);
  const yardBlocks = layout.blocks.filter(b => b.kind === 'yard');
  assert.ok(yardBlocks.length >= 1, 'yard lamp produces yard block');
  const yb = yardBlocks[0];
  near(yb.spacing, 2 * FT, 1e-6, 'yard spacing is 2 ft');
  const [nx, ny, nz] = yb.dims;
  assert.equal(nz, 5, 'yard has 5 vertical layers (1, 3, 5, 7, 9 ft)');
  assert.ok(yb.ground instanceof Float32Array, 'yard block has Float32Array ground');
  assert.equal(yb.ground.length, nx * ny);

  const pts = gridPoints(layout);
  let minG = Infinity, maxG = -Infinity;
  const expectedFt = [1, 3, 5, 7, 9];
  for (let iy = 0; iy < ny; iy++) {
    for (let ix = 0; ix < nx; ix++) {
      const gM = yb.ground[iy * nx + ix];
      if (gM < minG) minG = gM;
      if (gM > maxG) maxG = gM;
      for (let iz = 0; iz < nz; iz++) {
        const idx = yb.first + (iz * ny + iy) * nx + ix;
        const wx = pts[idx * 3], wy = pts[idx * 3 + 1], wz = pts[idx * 3 + 2];
        const lx = wx / FT, ly = -wz / FT;
        const groundFt = groundAt(plan, lx, ly);
        near(gM, groundFt * FT, 1e-4, 'ground array matches groundAt');
        near(wy / FT - groundFt, expectedFt[iz], 1e-4, `yard height above ground at iz=${iz}`);
      }
    }
  }
  assert.ok(maxG - minG > 1 * FT, `sloped lot actually slopes across yard grid (${minG}..${maxG})`);

  // Verify pointsInRange matches brute-force distance check
  const inRange = pointsInRange(layout, pts, yLamp.source, yLamp.range);
  assert.ok(inRange instanceof Uint32Array);
  const brute = [];
  for (let i = 0; i < layout.count; i++) {
    const dx = pts[i * 3] - yLamp.source.x;
    const dy = pts[i * 3 + 1] - yLamp.source.y;
    const dz = pts[i * 3 + 2] - yLamp.source.z;
    if (dx * dx + dy * dy + dz * dz < yLamp.range * yLamp.range) brute.push(i);
  }
  assert.deepEqual([...inRange], brute, 'pointsInRange matches brute force');
  console.log('Passed: test_yard_grid_follows_ground');
}

// 4. test_layout_hash_stable
{
  const planA = basePlan();
  const planB = structuredClone(planA);
  // Move placed building item and site furniture
  planB.buildings[0].items[0].at = [8, 9, 0];
  planB.site.furniture[0].at = [25, 10];
  const lamps = [
    { source: { x: 5 * FT, y: 8 * FT, z: -6 * FT }, range: 15 * FT, outdoor: false },
    { source: { x: 25 * FT, y: 6 * FT, z: -25 * FT }, range: 12 * FT, outdoor: true },
  ];
  const layoutA = gridLayout(planA, lamps);
  const layoutA2 = gridLayout(planA, [...lamps].reverse());
  const layoutB = gridLayout(planB, lamps);
  assert.equal(typeof layoutA.hash, 'string');
  assert.ok(layoutA.hash.length >= 16);
  assert.equal(layoutA.hash, layoutA2.hash, 'same input (even reordered lamps) gives same hash');
  assert.equal(layoutA.hash, layoutB.hash, 'moving placed items does not change layout hash');

  const planC = structuredClone(planA);
  planC.buildings[0].rooms[0].polygon = [[0, 0], [11, 0], [11, 12], [0, 12]];
  const layoutC = gridLayout(planC, lamps);
  assert.notEqual(layoutA.hash, layoutC.hash, 'changing room polygon changes layout hash');
  console.log('Passed: test_layout_hash_stable');
}

// 5. test_inside_mask
{
  // Room A: 10 x 12 x 9 ft with an L-shaped cutout, solid walls + a closed 1 m box inside.
  // Room B: 3 x 3 x 9 ft closet surrounded by solid walls, floor and ceiling.
  const lPoly = [[0, 0], [10, 0], [10, 6], [6, 6], [6, 12], [0, 12]];
  const closetPoly = [[12, 0], [15, 0], [15, 3], [12, 3]];
  const plan = {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house',
      position: [0, 0],
      rotation: 0,
      base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 9 }],
      walls: [],
      rooms: [
        { id: 'main', level: 'L1', polygon: lPoly },
        { id: 'closet', level: 'L1', polygon: closetPoly },
      ],
    }],
    site: { lot: [[-5, -5], [25, -5], [25, 25], [-5, 25]] },
  };
  const lamps = [
    { source: { x: 3 * FT, y: 5 * FT, z: -3 * FT }, range: 20 * FT, outdoor: false },
    { source: { x: 13.5 * FT, y: 5 * FT, z: -1.5 * FT }, range: 10 * FT, outdoor: false },
  ];
  const layout = gridLayout(plan, lamps);
  assert.equal(layout.blocks.length, 2);
  const pts = gridPoints(layout);

  const meshes = [];
  const addBox = (cx, cy, cz, sx, sy, sz) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), new THREE.MeshStandardMaterial());
    m.position.set(cx, cy, cz);
    m.updateMatrixWorld(true);
    meshes.push(m);
  };
  // Closed 1 m x 1 m x 1 m solid box centered at world (2.5*FT, 2.5*FT, -2.5*FT)
  // Grid point (2, 2, 2) is at exact centre (2.5*FT, 2.5*FT, -2.5*FT) -> MUST be 1
  addBox(2.5 * FT, 2.5 * FT, -2.5 * FT, 1.0, 1.0, 1.0);

  // Build thick solid enclosure around the 3 x 3 ft closet: x in [12, 15] ft, y in [0, 3] ft, z in [0, 9] ft
  const t = 0.5 * FT;
  const cx = 13.5 * FT, cy = 4.5 * FT, cz = -1.5 * FT;
  addBox(12 * FT - t / 2, cy, cz, t, 9 * FT, 3 * FT + 2 * t); // west wall
  addBox(15 * FT + t / 2, cy, cz, t, 9 * FT, 3 * FT + 2 * t); // east wall
  addBox(cx, cy, 0 * FT + t / 2, 3 * FT, 9 * FT, t);           // south wall (plan y=0 -> z=0)
  addBox(cx, cy, -3 * FT - t / 2, 3 * FT, 9 * FT, t);          // north wall (plan y=3 -> z=-3)
  addBox(cx, -t / 2, cz, 3 * FT + 2 * t, t, 3 * FT + 2 * t);   // floor slab
  addBox(cx, 9 * FT + t / 2, cz, 3 * FT + 2 * t, t, 3 * FT + 2 * t); // ceiling slab

  const bvh = buildOccluderBVH(meshes);
  const mask = insideMask(pts, bvh, layout);
  assert.ok(mask instanceof Uint8Array);
  assert.equal(mask.length, layout.count);

  const mainBlock = layout.blocks[0];
  const closetBlock = layout.blocks[1];
  const idxOf = (blk, ix, iy, iz) => blk.first + (iz * blk.dims[1] + iy) * blk.dims[0] + ix;

  // Inside the closed 1 m box -> invalid (1)
  assert.equal(mask[idxOf(mainBlock, 2, 2, 2)], 1, 'point inside closed 1 m box is 1');
  // Open room air (e.g., ix=8, iy=2, iz=4 -> x=8.5 ft, y=2.5 ft, z=4.5 ft) -> valid (0)
  assert.equal(mask[idxOf(mainBlock, 8, 2, 4)], 0, 'point in open room air is 0');
  // Outside the L polygon (e.g., ix=8, iy=9, iz=4 -> x=8.5 ft, y=9.5 ft is in the cutout) -> invalid (1)
  assert.equal(mask[idxOf(mainBlock, 8, 9, 4)], 1, 'point outside L room polygon is 1');
  // Inside the 3 x 3 ft closet with walls -> ALL interior points must be 0
  for (let iz = 0; iz < closetBlock.dims[2]; iz++) {
    for (let iy = 0; iy < closetBlock.dims[1]; iy++) {
      for (let ix = 0; ix < closetBlock.dims[0]; ix++) {
        assert.equal(mask[idxOf(closetBlock, ix, iy, iz)], 0,
          `closet point (${ix},${iy},${iz}) inside 3x3 ft walled closet is 0`);
      }
    }
  }
  console.log('Passed: test_inside_mask');
}

// 6. test_chunk_roundtrip
{
  const original = {
    layoutHash: 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
    device: 'light.living_cans',
    emitters: 3,
    indices: new Uint32Array([0, 5, 42, 1024, 65537]),
    values: new Uint8Array([
      254, 128, 0,
      255, 255, 255,
      10, 200, 127,
      0, 0, 254,
      1, 2, 253,
    ]),
  };
  const encoded = await encodeGridChunk(original);
  assert.ok(encoded instanceof Uint8Array, 'encoded is Uint8Array');
  assert.equal(encoded[0], 0x1f, 'gzip magic byte 0');
  assert.equal(encoded[1], 0x8b, 'gzip magic byte 1');
  const raw = gunzipSync(encoded);
  assert.equal(Buffer.from(raw.subarray(0, 4)).toString('ascii'), 'MVG1', 'MVG1 magic inside gzip');

  const decoded = await decodeGridChunk(encoded);
  assert.equal(decoded.layoutHash, original.layoutHash);
  assert.equal(decoded.device, original.device);
  assert.equal(decoded.emitters, original.emitters);
  assert.ok(decoded.indices instanceof Uint32Array);
  assert.ok(decoded.values instanceof Uint8Array);
  assert.deepEqual([...decoded.indices], [...original.indices]);
  assert.deepEqual([...decoded.values], [...original.values]);

  // Empty chunk roundtrip
  const emptyOrig = {
    layoutHash: '0'.repeat(32),
    device: 'light.empty',
    emitters: 1,
    indices: new Uint32Array(0),
    values: new Uint8Array(0),
  };
  const emptyDec = await decodeGridChunk(await encodeGridChunk(emptyOrig));
  assert.equal(emptyDec.indices.length, 0);
  assert.equal(emptyDec.values.length, 0);
  assert.equal(emptyDec.device, 'light.empty');

  // Corrupt magic rejects
  await assert.rejects(() => decodeGridChunk(new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7])), /Invalid|MVG1|chunk/i);

  // Over-cap (8 MiB) compressed upload rejects on encode and decode
  assert.equal(MAX_CHUNK_BYTES, 8 * 1024 * 1024, 'MAX_CHUNK_BYTES is 8 MiB');
  const overCount = 1_100_000;
  const overIndices = new Uint32Array(overCount);
  for (let i = 0; i < overCount; i++) overIndices[i] = i;
  const overValues = randomFillSync(new Uint8Array(overCount * 8)); // ~8.8 MB incompressible -> > 8 MiB gzipped
  await assert.rejects(
    () => encodeGridChunk({
      layoutHash: original.layoutHash,
      device: 'light.over_cap',
      emitters: 8,
      indices: overIndices,
      values: overValues,
    }),
    /size limit/i,
    'encodeGridChunk rejects compressed chunk over 8 MiB',
  );
  await assert.rejects(
    () => decodeGridChunk(new Uint8Array(MAX_CHUNK_BYTES + 1)),
    /size limit/i,
    'decodeGridChunk rejects input over 8 MiB',
  );
  console.log('Passed: test_chunk_roundtrip');
}
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_grid_layout_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
