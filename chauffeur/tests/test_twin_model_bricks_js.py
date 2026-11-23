"""Node CPU tests for per-copy visibility bricks, emitter selection, and model light textures.

Run from chauffeur/: python tests/test_twin_model_bricks_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const { FT, CANDELA } = await import(file('static/twin/twin_light_math.js'));
const { gridLayout, gridPoints } = await import(file('static/twin/bake/grid_layout.js'));
const { tintSum } = await import(file('static/twin/bake/lightmap_material.js'));
const {
  MODEL_LIGHT_LAYOUT,
  emitterTable,
  sampleGrid,
  chooseEmitters,
  buildBrick,
  createModelLightTextures,
  fillFor,
} = await import(file('static/twin/bake/model_bricks.js'));

const near = (a, b, eps = 1e-4, msg = '') =>
  assert.ok(Math.abs(a - b) <= eps, `${msg}: expected ${b}, got ${a}`);

function makeSimpleRoomPlan() {
  const rect = [[0, 0], [10, 0], [10, 10], [0, 10]];
  return {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house', position: [0, 0], rotation: 0, base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 8 }],
      walls: [],
      rooms: [{ id: 'room', level: 'L1', polygon: rect }],
    }],
    site: { lot: [[-5, -5], [20, -5], [20, 20], [-5, 20]], terraces: [] },
  };
}

// 1. test_sample_grid_skips_invalid (plus yard slope, L-room cutout, and stacked-level half-open z)
{
  const plan = makeSimpleRoomPlan();
  const lampPos = { x: 5 * FT, y: 4 * FT, z: -5 * FT };
  const layout = gridLayout(plan, [{ source: lampPos, range: 20 * FT, outdoor: false }]);
  const block = layout.blocks[0];
  const [nx, ny, nz] = block.dims;
  const indices = new Uint32Array(layout.count);
  for (let i = 0; i < layout.count; i++) indices[i] = i;

  const idxOf = (ix, iy, iz) => block.first + (iz * ny + iy) * nx + ix;

  // Point at exact midpoint between cells (2..3, 2..3, 2..3) -> (3.0*FT, 3.0*FT, -3.0*FT)
  const pMid = new THREE.Vector3(3.0 * FT, 3.0 * FT, -3.0 * FT);
  const vals1 = new Uint8Array(layout.count).fill(254);
  vals1[idxOf(2, 2, 2)] = 255; // one of the 8 corners is invalid
  const grid1 = { layout, chunks: new Map([['light.a', { emitters: 1, indices, values: vals1 }]]) };
  near(sampleGrid(grid1, pMid, 'light.a#0'), 1.0, 1e-6, 'one corner 255 and seven at 254 gives 1.0');

  // All 8 corners at 255 -> null
  const valsAll = new Uint8Array(layout.count).fill(254);
  for (let dz = 2; dz <= 3; dz++) for (let dy = 2; dy <= 3; dy++) for (let dx = 2; dx <= 3; dx++) {
    valsAll[idxOf(dx, dy, dz)] = 255;
  }
  const gridAll = { layout, chunks: new Map([['light.a', { emitters: 1, indices, values: valsAll }]]) };
  assert.equal(sampleGrid(gridAll, pMid, 'light.a#0'), null, 'all 8 corners at 255 gives null');

  // Outside any block -> null
  assert.equal(sampleGrid(grid1, new THREE.Vector3(50 * FT, 4 * FT, -50 * FT), 'light.a#0'), null, 'no block gives null');

  // Stacked levels: shared plane z = 8 ft belongs strictly to L2 ([0, nz) half-open)
  const twoStory = makeSimpleRoomPlan();
  twoStory.buildings[0].levels.push({ id: 'L2', elevation: 8, ceiling: 8 });
  twoStory.buildings[0].rooms.push({ id: 'upper', level: 'L2', polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] });
  const twoLayout = gridLayout(twoStory, [
    { source: { x: 5 * FT, y: 4 * FT, z: -5 * FT }, range: 20 * FT, outdoor: false },
    { source: { x: 5 * FT, y: 12 * FT, z: -5 * FT }, range: 20 * FT, outdoor: false },
  ]);
  assert.equal(twoLayout.blocks.filter(b=>b.kind==='room').length, 2);
  const bL1 = twoLayout.blocks[0], bL2 = twoLayout.blocks[1];
  const twoIdx = new Uint32Array(twoLayout.count);
  const twoVals = new Uint8Array(twoLayout.count);
  for (let i = 0; i < twoLayout.count; i++) twoIdx[i] = i;
  twoVals.fill(50, bL1.first, bL1.first + bL1.dims[0] * bL1.dims[1] * bL1.dims[2]);
  twoVals.fill(200, bL2.first, bL2.first + bL2.dims[0] * bL2.dims[1] * bL2.dims[2]);
  const twoGrid = { layout: twoLayout, chunks: new Map([['light.stack', { emitters: 1, indices: twoIdx, values: twoVals }]]) };
  near(sampleGrid(twoGrid, new THREE.Vector3(5 * FT, 8 * FT, -5 * FT), 'light.stack#0'), 200 / 254, 1e-4,
    'shared plane z=8 ft claimed by upper level (half-open [0, nz))');

  // Yard block: sloped ground subtraction
  const yardPlan = {
    generatorVersion: 'test',
    materials: {},
    buildings: [],
    site: {
      lot: [[0, 0], [20, 0], [20, 20], [0, 20]],
      terraces: [{
        id: 'slope',
        polygon: [[10, 0], [20, 0], [20, 20], [10, 20]],
        height: 4,
        blend: 10,
        edges: [0, 1, 2, 3].map(() => ({ edge: 'slope' })),
      }],
    },
  };
  const yLamp = { source: { x: 10 * FT, y: 6 * FT, z: -10 * FT }, range: 14 * FT, outdoor: true };
  const yLayout = gridLayout(yardPlan, [yLamp]);
  const yb = yLayout.blocks.find(b => b.kind === 'yard');
  assert.ok(yb, 'yard block exists');
  const [ynx, yny, ynz] = yb.dims;
  const yIdx = new Uint32Array(yLayout.count);
  const yVals = new Uint8Array(yLayout.count);
  for (let i = 0; i < yLayout.count; i++) yIdx[i] = i;
  for (let iz = 0; iz < ynz; iz++) {
    const v = iz === 0 ? 0 : iz === 1 ? 127 : 254;
    for (let iy = 0; iy < yny; iy++) {
      for (let ix = 0; ix < ynx; ix++) {
        yVals[yb.first + (iz * yny + iy) * ynx + ix] = v;
      }
    }
  }
  const yGrid = { layout: yLayout, chunks: new Map([['light.yard', { emitters: 1, indices: yIdx, values: yVals }]]) };
  const gA = yb.ground[1 * ynx + 1], gB = yb.ground[1 * ynx + 2];
  const gMid = 0.5 * (gA + gB);
  const yPts = gridPoints(yLayout);
  const iA = yb.first + (0 * yny + 1) * ynx + 1;
  const iB = yb.first + (0 * yny + 1) * ynx + 2;
  const pYard = new THREE.Vector3(
    0.5 * (yPts[iA * 3] + yPts[iB * 3]),
    gMid + 2.0 * FT,
    0.5 * (yPts[iA * 3 + 2] + yPts[iB * 3 + 2]),
  );
  near(sampleGrid(yGrid, pYard, 'light.yard#0'), 0.25, 1e-2, 'yard sampling subtracts bilinear ground height');

  // Yard point in L-shaped room cutout samples yard block
  const lPlan = {
    generatorVersion: 'test',
    materials: {},
    buildings: [{
      id: 'house', position: [0, 0], rotation: 0, base: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 8 }],
      walls: [],
      rooms: [{ id: 'lroom', level: 'L1', polygon: [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]] }],
    }],
    site: { lot: [[0, 0], [20, 0], [20, 20], [0, 20]], terraces: [] },
  };
  const lLayout = gridLayout(lPlan, [
    { source: { x: 2 * FT, y: 4 * FT, z: -2 * FT }, range: 15 * FT, outdoor: false },
    { source: { x: 8 * FT, y: 4 * FT, z: -8 * FT }, range: 10 * FT, outdoor: true },
  ]);
  const lIdx = new Uint32Array(lLayout.count);
  const lVals = new Uint8Array(lLayout.count);
  const rBlk = lLayout.blocks.find(b => b.kind === 'room');
  const yBlk = lLayout.blocks.find(b => b.kind === 'yard');
  for (let i = 0; i < lLayout.count; i++) lIdx[i] = i;
  lVals.fill(255, rBlk.first, rBlk.first + rBlk.dims[0] * rBlk.dims[1] * rBlk.dims[2]);
  lVals.fill(200, yBlk.first, yBlk.first + yBlk.dims[0] * yBlk.dims[1] * yBlk.dims[2]);
  const lGrid = { layout: lLayout, chunks: new Map([['light.patio', { emitters: 1, indices: lIdx, values: lVals }]]) };
  near(sampleGrid(lGrid, new THREE.Vector3(8 * FT, 3 * FT, -8 * FT), 'light.patio#0'), 200 / 254, 1e-4,
    'yard point in L-room cutout samples yard block');
  console.log('Passed: test_sample_grid_skips_invalid');
}

// 2. test_choose_emitters_folds_then_drops (plus cone/facing ranking, null centre fallback, GPU slot scales)
{
  const plan = makeSimpleRoomPlan();
  const centre = new THREE.Vector3(5 * FT, 3 * FT, -5 * FT);
  const layout = gridLayout(plan, [{ source: centre, range: 20 * FT, outdoor: false }]);
  const indices = new Uint32Array(layout.count);
  for (let i = 0; i < layout.count; i++) indices[i] = i;

  const chunks = new Map();
  chunks.set('light.cans', { emitters: 6, indices, values: new Uint8Array(layout.count * 6).fill(254) });
  for (const name of ['light.s1', 'light.s2', 'light.s3', 'light.s4']) {
    chunks.set(name, { emitters: 1, indices, values: new Uint8Array(layout.count).fill(254) });
  }
  const grid = { layout, chunks };

  const mkEmitter = (device, index, distFt, outputScale, extra = {}) => ({
    id: `${device}#${index}`,
    device,
    index,
    column: index,
    shape: 0,
    position: new THREE.Vector3((5 + distFt) * FT, 3 * FT, -5 * FT),
    range: 20 * FT,
    axis: new THREE.Vector3(0, -1, 0),
    cosOuter: -1,
    cosInner: -1,
    halfSize: [0, 0],
    rotation: new THREE.Quaternion(),
    outputScale,
    ...extra,
  });

  const table = [
    mkEmitter('light.cans', 0, 1.0, 20),
    mkEmitter('light.cans', 1, 2.0, 20),
    mkEmitter('light.cans', 2, 3.0, 20),
    mkEmitter('light.cans', 3, 4.0, 20),
    mkEmitter('light.cans', 4, 5.0, 20),
    mkEmitter('light.cans', 5, 6.0, 20),
    mkEmitter('light.s1', 0, 1.2, 50),
    mkEmitter('light.s2', 0, 1.4, 50),
    mkEmitter('light.s3', 0, 1.6, 50),
    mkEmitter('light.s4', 0, 1.8, 50),
  ];
  const origScales = table.map(e => e.outputScale);
  const totalBefore = origScales.reduce((a, b) => a + b, 0);

  const chosen = chooseEmitters(centre, table, grid, 8);
  assert.ok(chosen.ids.length <= 8, `kept at most 8 (got ${chosen.ids.length})`);
  assert.ok(chosen.folded > 0, `folded > 0 (got ${chosen.folded})`);
  assert.equal(chosen.dropped, 0, 'folding alone fits 6+4 into 8 with 0 dropped');
  assert.ok(chosen.ids.includes('light.cans#0'), 'strongest emitter of folded device is kept');
  const totalAfter = chosen.emitters.reduce((sum, e) => sum + e.outputScale, 0);
  near(totalAfter, totalBefore, 1e-6, 'total outputScale is conserved after folding');
  assert.deepEqual(table.map(e => e.outputScale), origScales, 'input table is not mutated');

  // Verify chooseEmitters returns table `rows` and writeBrick accepts `chosen` directly
  assert.deepEqual(chosen.rows, chosen.ids.map(id => table.findIndex(e => e.id === id)),
    'chooseEmitters rows match table positions');
  const canSlot = chosen.ids.indexOf('light.cans#0');
  const expectedRatio = chosen.emitters[canSlot].outputScale / 20; // (20 + 20 + 20) / 20 = 3.0
  near(chosen.scales[canSlot], expectedRatio, 1e-6, 'folded slot scale equals summed output ratio');
  const tex = createModelLightTextures({ maxBricks: 2, maxEmitters: table.length });
  tex.writeBrick(0, new Uint8Array(1000), chosen, new THREE.Color(0, 0, 0), null);
  const L = MODEL_LIGHT_LAYOUT, W = tex.mvSize.z, firstBrick = tex.mvSize.w;
  const scaleRow = canSlot < 4 ? L.BRICK_ROW_SCALES_0 : L.BRICK_ROW_SCALES_1;
  const scaleCh = canSlot & 3;
  const off = ((firstBrick + scaleRow) * W + 0) * 4 + scaleCh;
  near(tex.lamps.image.data[off], expectedRatio, 1e-5, 'GPU brick slot scale row carries folded ratio');
  // Unfolded slot has scale 1
  const s1Slot = chosen.ids.indexOf('light.s1#0');
  const s1Row = s1Slot < 4 ? L.BRICK_ROW_SCALES_0 : L.BRICK_ROW_SCALES_1;
  near(tex.lamps.image.data[((firstBrick + s1Row) * W + 0) * 4 + (s1Slot & 3)], 1.0, 1e-5, 'unfolded slot scale is 1');
  tex.dispose();

  // 6 cans + 10 single lamps -> fold all 5 weaker cans first, then drop 3
  const bigTable = [...table];
  for (let k = 5; k <= 10; k++) {
    const dev = `light.s${k}`;
    chunks.set(dev, { emitters: 1, indices, values: new Uint8Array(layout.count).fill(254) });
    bigTable.push(mkEmitter(dev, 0, 2.0 + k * 0.2, 40));
  }
  const chosenBig = chooseEmitters(centre, bigTable, grid, 8);
  assert.equal(chosenBig.ids.length, 8);
  assert.equal(chosenBig.folded, 5);
  assert.equal(chosenBig.dropped, 3);
  const strongestCan = chosenBig.emitters.find(e => e.id === 'light.cans#0');
  near(strongestCan.outputScale, 120, 1e-6);

  // Spot aimed away from copy ranks below a weaker point lamp beside it
  chunks.set('light.spot_away', { emitters: 1, indices, values: new Uint8Array(layout.count).fill(254) });
  chunks.set('light.weak_pt', { emitters: 1, indices, values: new Uint8Array(layout.count).fill(254) });
  const copyBox = new THREE.Box3(
    new THREE.Vector3(4.5 * FT, 2.5 * FT, -5.5 * FT),
    new THREE.Vector3(5.5 * FT, 3.5 * FT, -4.5 * FT),
  );
  const coneTable = [
    // Very bright spot right next to the copy (x=4 ft) aimed AWAY (-x)
    mkEmitter('light.spot_away', 0, -1.0, 500, {
      shape: 1,
      axis: new THREE.Vector3(-1, 0, 0),
      cosOuter: Math.cos(30 * Math.PI / 180),
      cosInner: Math.cos(20 * Math.PI / 180),
    }),
    // Weak point lamp beside the copy
    mkEmitter('light.weak_pt', 0, 2.0, 10, { shape: 0 }),
  ];
  const coneChosen = chooseEmitters(copyBox, coneTable, grid, 8);
  assert.deepEqual(coneChosen.ids, ['light.weak_pt#0'], 'spot aimed away ranks below (zero) weaker point lamp beside copy');

  // Spot aimed TOWARD a box corner (not centre) still ranks via best of centre+corners
  chunks.set('light.rect_away', { emitters: 1, indices, values: new Uint8Array(layout.count).fill(254) });
  const rectAwayTable = [
    mkEmitter('light.rect_away', 0, -1.0, 500, {
      shape: 2,
      axis: new THREE.Vector3(-1, 0, 0), // facing away from copy
      halfSize: [0.3, 0.3],
    }),
    mkEmitter('light.weak_pt', 0, 2.0, 10, { shape: 0 }),
  ];
  const rectChosen = chooseEmitters(copyBox, rectAwayTable, grid, 8);
  assert.deepEqual(rectChosen.ids, ['light.weak_pt#0'], 'rect facing away ranks below weaker point lamp');

  // Null centre visibility falls back to max over box corners
  const block = layout.blocks[0];
  const [nx, ny] = block.dims;
  const idxOf = (ix, iy, iz) => block.first + (iz * ny + iy) * nx + ix;
  const nullCentreVals = new Uint8Array(layout.count).fill(254);
  // Invalidate all 8 grid corners surrounding centre (5, 3, -5) -> cells [4..5, 4..5, 2..3]
  for (let iz = 2; iz <= 3; iz++) for (let iy = 4; iy <= 5; iy++) for (let ix = 4; ix <= 5; ix++) {
    nullCentreVals[idxOf(ix, iy, iz)] = 255;
  }
  const ncGrid = { layout, chunks: new Map([['light.weak_pt', { emitters: 1, indices, values: nullCentreVals }]]) };
  const bigCopyBox = new THREE.Box3(
    new THREE.Vector3(3 * FT, 1 * FT, -7 * FT),
    new THREE.Vector3(7 * FT, 5 * FT, -3 * FT),
  );
  assert.equal(sampleGrid(ncGrid, bigCopyBox.getCenter(new THREE.Vector3()), 'light.weak_pt#0'), null,
    'sanity: centre visibility is null');
  const ncChosen = chooseEmitters(bigCopyBox, [coneTable[1]], ncGrid, 8);
  assert.deepEqual(ncChosen.ids, ['light.weak_pt#0'], 'null centre visibility falls back to valid box corners');

  console.log('Passed: test_choose_emitters_folds_then_drops');
}

// 3. test_brick_layout (two 5-wide slabs: x = (e >> 2) * 5 + ix, channel = e & 3; spatially varying to guard slab vs interleaved)
{
  const plan = makeSimpleRoomPlan();
  const lampPos = { x: 5 * FT, y: 4 * FT, z: -5 * FT };
  const layout = gridLayout(plan, [{ source: lampPos, range: 20 * FT, outdoor: false }]);
  const block = layout.blocks[0];
  const [nx, ny, nz] = block.dims;
  const idxOf = (ix, iy, iz) => block.first + (iz * ny + iy) * nx + ix;
  const indices = new Uint32Array(layout.count);
  for (let i = 0; i < layout.count; i++) indices[i] = i;

  // Spatially varying values: f(e, ix) = 10 + e * 24 + ix * 4 (unique per (e, ix) in 0..7 x 0..4).
  const valFor = (e, ix) => 10 + e * 24 + ix * 4;
  const values = new Uint8Array(layout.count * 8);
  for (let iz = 0; iz < nz; iz++) {
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const gIdx = idxOf(ix, iy, iz);
        for (let e = 0; e < 8; e++) {
          values[gIdx * 8 + e] = valFor(e, Math.min(4, ix));
        }
      }
    }
  }
  const grid = { layout, chunks: new Map([['light.eight', { emitters: 8, indices, values }]]) };
  const ids = Array.from({ length: 8 }, (_, e) => `light.eight#${e}`);
  // Align box [0.5..4.5] ft to exact grid centres ix = 0, 1, 2, 3, 4
  const box = new THREE.Box3(
    new THREE.Vector3(0.5 * FT, 0.5 * FT, -4.5 * FT),
    new THREE.Vector3(4.5 * FT, 4.5 * FT, -0.5 * FT),
  );
  const brick = buildBrick(grid, box, ids);
  assert.ok(brick instanceof Uint8Array);
  assert.equal(brick.length, 5 * 5 * 5 * 8);

  // Slab layout assertions (would fail under old interleaved x = 2*ix + (e>>2)):
  // Point (2, 2, 2) emitter 5 -> texel ((5>>2)*5 + 2, 2, 2) = (7, 2, 2) ch 1 -> valFor(5, 2) = 138
  // (under old interleaved, texel 7 would be ix=3, e=5 -> 142!)
  const offE5 = ((2 * 5 + 2) * 10 + 7) * 4 + 1;
  assert.equal(brick[offE5], valFor(5, 2), 'texel (7, 2, 2) ch 1 holds emitter 5 of ix=2 (slab, not interleaved)');
  // Point (2, 2, 2) emitter 1 -> texel ((1>>2)*5 + 2, 2, 2) = (2, 2, 2) ch 1 -> valFor(1, 2) = 42
  // (under old interleaved, texel 2 would be ix=1, e=1 -> 38!)
  const offE1 = ((2 * 5 + 2) * 10 + 2) * 4 + 1;
  assert.equal(brick[offE1], valFor(1, 2), 'texel (2, 2, 2) ch 1 holds emitter 1 of ix=2 (slab, not interleaved)');
  // Texel (5, 2, 2) ch 1 is emitter 5 of ix=0 (130), NOT emitter 5 of ix=2 (138)
  const offSlab1Start = ((2 * 5 + 2) * 10 + 5) * 4 + 1;
  assert.equal(brick[offSlab1Start], valFor(5, 0), 'texel (5, 2, 2) ch 1 holds emitter 5 of ix=0');

  // Null sample fills from nearest valid brick point
  const valsNull = new Uint8Array(layout.count).fill(180);
  for (let iz = 0; iz <= 2; iz++) for (let iy = 0; iy <= 2; iy++) for (let ix = 0; ix <= 2; ix++) {
    valsNull[idxOf(ix, iy, iz)] = 255;
  }
  const gridNull = { layout, chunks: new Map([['light.n', { emitters: 1, indices, values: valsNull }]]) };
  const cornerBox = new THREE.Box3(
    new THREE.Vector3(0.5 * FT, 0.5 * FT, -4.5 * FT),
    new THREE.Vector3(4.5 * FT, 4.5 * FT, -0.5 * FT),
  );
  const brickNull = buildBrick(gridNull, cornerBox, ['light.n#0']);
  const cornerTexel = ((4 * 5 + 0) * 10 + 0) * 4 + 0;
  assert.equal(brickNull[cornerTexel], 180, 'null brick point filled from nearest valid brick point');

  // All-null brick fills with 0
  const gridEmpty = { layout, chunks: new Map([['light.z', { emitters: 1, indices, values: new Uint8Array(layout.count).fill(255) }]]) };
  const brickZero = buildBrick(gridEmpty, box, ['light.z#0']);
  assert.ok(brickZero.every(v => v === 0), 'all-null brick fills with 0');
  console.log('Passed: test_brick_layout');
}

// 4. test_palette_line_excluded (explicit paletteLines Set + bent L-shaped strip -> 2 records + legacy via lightSource)
{
  const plan = makeSimpleRoomPlan();
  const lights = [
    // Line lamp with NO palette field on emitters, but listed in explicit paletteLines Set -> MUST be excluded
    {
      device: 'light.rgb_strip',
      entity: 'light.rgb_strip',
      emitters: [{
        shape: 'line',
        entity_id: 'light.rgb_strip',
        path: [[1, 1, 7], [5, 1, 7]],
        width_in: 2,
        range: 18,
        output_lm: 800,
        output_fraction: 1,
        position: [3 * FT, 7 * FT, -1 * FT],
      }],
    },
    // Bent L-shaped strip (two 4 ft legs = 8 ft -> linePieces yields 2 pieces) -> 2 records sharing column 0
    {
      device: 'light.l_strip',
      entity: 'light.l_strip',
      emitters: [{
        shape: 'line',
        entity_id: 'light.l_strip',
        path: [[1, 1, 7], [5, 1, 7], [5, 5, 7]],
        width_in: 2,
        facing: 'down',
        range: 18,
        output_lm: 800,
        output_fraction: 1,
      }],
    },
    // Stale lamp -> excluded
    { device: 'light.stale', at: [5, 5, 7], absolute: true, range: 18 },
    // Fresh lamp without manifest grid -> excluded
    { device: 'light.no_grid', at: [5, 5, 7], absolute: true, range: 18 },
    // Fresh legacy marker lamp (resolved through lightSource(plan, light)) -> included
    { device: 'light.legacy', building: 'house', level: 'L1', room: 'room', at: [5, 5, 7] },
    // Fresh spot + rect fixture -> 2 emitters
    {
      device: 'light.combo',
      entity: 'light.combo',
      emitters: [
        {
          shape: 'spot', entity_id: 'light.combo', at: [3, 3, 8], aim: [3, 3, 0],
          cone_deg: 60, softness: 0.3, range: 16, output_lm: 600, output_fraction: 0.5,
          position: [3 * FT, 8 * FT, -3 * FT],
        },
        {
          shape: 'area', entity_id: 'light.combo', at: [7, 7, 8], facing: 'down',
          size_ft: [2, 1], rotation_deg: 0, range: 16, output_lm: 600, output_fraction: 0.5,
          position: [7 * FT, 8 * FT, -7 * FT],
        },
      ],
    },
  ];
  const freshIds = new Set(['light.rgb_strip', 'light.l_strip', 'light.no_grid', 'light.legacy', 'light.combo']);
  const manifest = {
    lights: {
      'light.rgb_strip': { grid: 'g1' },
      'light.l_strip': { grid: 'g2' },
      'light.stale': { grid: 'g3' },
      'light.no_grid': {},
      'light.legacy': { grid: 'g4' },
      'light.combo': { grid: 'g5' },
    },
  };
  const paletteLines = new Set(['light.rgb_strip']);
  const table = emitterTable(lights, freshIds, manifest, { paletteLines, plan });
  const ids = table.map(e => e.id);
  assert.ok(!ids.some(id => id.startsWith('light.rgb_strip')), 'explicit paletteLines set excludes strip even without palette on emitter');
  assert.ok(!ids.some(id => id.startsWith('light.stale')), 'stale lamp excluded');
  assert.ok(!ids.some(id => id.startsWith('light.no_grid')), 'lamp without manifest grid excluded');

  // Bent L-shaped strip -> 2 records sharing column 0 whose segments follow the two legs
  const lPieces = table.filter(e => e.device === 'light.l_strip');
  assert.equal(lPieces.length, 2, 'L-shaped strip yields 2 records');
  assert.equal(lPieces[0].column, 0);
  assert.equal(lPieces[1].column, 0);
  assert.equal(lPieces[0].shape, 3);
  assert.equal(lPieces[1].shape, 3);
  // Leg 0 midpoint: (3, 1, 7) ft -> world (3*FT, 7*FT, -1*FT), dir along +X
  near(lPieces[0].position.x, 3 * FT, 1e-4, 'L piece 0 x');
  near(lPieces[0].position.z, -1 * FT, 1e-4, 'L piece 0 z');
  const u0 = new THREE.Vector3(1, 0, 0).applyQuaternion(lPieces[0].rotation);
  near(Math.abs(u0.x), 1, 1e-4, 'L piece 0 runs along X');
  // Leg 1 midpoint: (5, 3, 7) ft -> world (5*FT, 7*FT, -3*FT), dir along Z
  near(lPieces[1].position.x, 5 * FT, 1e-4, 'L piece 1 x');
  near(lPieces[1].position.z, -3 * FT, 1e-4, 'L piece 1 z');
  const u1 = new THREE.Vector3(1, 0, 0).applyQuaternion(lPieces[1].rotation);
  near(Math.abs(u1.z), 1, 1e-4, 'L piece 1 runs along Z');
  // Output split by piece length (equal 4 ft legs -> 50/50 sum = 800 / PI)
  near(lPieces[0].outputScale + lPieces[1].outputScale, 800 / Math.PI, 1e-4, 'L strip total outputScale conserved');
  near(lPieces[0].outputScale, lPieces[1].outputScale, 1e-4, 'equal legs split outputScale equally');

  const legacyRec = table.find(e => e.device === 'light.legacy');
  assert.equal(legacyRec.shape, 0);
  assert.equal(legacyRec.column, 0);
  near(legacyRec.outputScale, CANDELA, 1e-5);
  assert.ok(legacyRec.range > 0, 'legacy range resolved via lightSource');

  const spotRec = table.find(e => e.id === 'light.combo#0');
  assert.equal(spotRec.shape, 1);
  assert.equal(spotRec.column, 0);
  near(spotRec.axis.y, -1, 1e-5);
  near(spotRec.cosOuter, Math.cos(30 * Math.PI / 180), 1e-5);
  near(spotRec.cosInner, Math.cos(21 * Math.PI / 180), 1e-5);

  const rectRec = table.find(e => e.id === 'light.combo#1');
  assert.equal(rectRec.shape, 2);
  assert.equal(rectRec.column, 1);
  near(rectRec.halfSize[0], 1 * FT, 1e-4);
  near(rectRec.halfSize[1], 0.5 * FT, 1e-4);

  // Explicit `row` test: two single-emitter lights + a two-piece strip produce distinct rows matching table positions
  const rowLights = [
    { device: 'light.one', at: [2, 2, 7], absolute: true, range: 18 },
    { device: 'light.two', at: [8, 2, 7], absolute: true, range: 18 },
    lights[1], // light.l_strip (2 pieces)
  ];
  const rowFresh = new Set(['light.one', 'light.two', 'light.l_strip']);
  const rowManifest = { lights: { 'light.one': { grid: 'g1' }, 'light.two': { grid: 'g2' }, 'light.l_strip': { grid: 'g3' } } };
  const rowTable = emitterTable(rowLights, rowFresh, rowManifest, { plan });
  assert.equal(rowTable.length, 4, '2 single-emitter lights + 2-piece strip = 4 table records');
  assert.deepEqual(rowTable.map(r => r.row), [0, 1, 2, 3], 'distinct rows match exact table positions');
  assert.deepEqual(rowTable.map(r => r.column), [0, 0, 0, 0], 'chunk columns are per-light (distinct from table row)');
  console.log('Passed: test_palette_line_excluded');
}

// 5. test_fill_matches_lightmap_sum (with freshIds required)
{
  const manifest = {
    lights: {
      'light.a': { fill: [0.15, 0.02] },
      'light.b': { fill: [0.08, 0.25] },
      'light.stale': { fill: [0.4, 0.4] },
      'light.off': { fill: [0.5, 0.5] },
    },
  };
  const tints = new Map([
    ['light.a', { rgb: [255, 180, 100], intensity: 0.8 }],
    ['light.b', { rgb: [120, 200, 255], intensity: 0.5 }],
    ['light.stale', { rgb: [255, 255, 255], intensity: 1.0 }],
    ['light.off', { rgb: [255, 255, 255], intensity: 0 }],
  ]);
  const freshIds = new Set(['light.a', 'light.b', 'light.off']);

  // Missing freshIds must throw
  assert.throws(() => fillFor(manifest, 0, tints), /freshIds/i, 'fillFor throws when freshIds omitted');

  const got = fillFor(manifest, 0, tints, freshIds);
  const expected = new THREE.Color(0, 0, 0)
    .add(tintSum([tints.get('light.a')]).multiplyScalar(0.15))
    .add(tintSum([tints.get('light.b')]).multiplyScalar(0.08));
  near(got.r, expected.r, 1e-6, 'fill r matches lightmap sum (excludes stale)');
  near(got.g, expected.g, 1e-6, 'fill g matches lightmap sum');
  near(got.b, expected.b, 1e-6, 'fill b matches lightmap sum');

  const linearTints = new Map([
    ['light.a', tintSum([tints.get('light.a')])],
    ['light.b', tintSum([tints.get('light.b')])],
  ]);
  const gotLinear = fillFor(manifest, 0, linearTints, freshIds);
  near(gotLinear.r, expected.r, 1e-6);
  near(gotLinear.g, expected.g, 1e-6);
  near(gotLinear.b, expected.b, 1e-6);

  const none = fillFor(manifest, 99, tints, freshIds);
  assert.deepEqual([none.r, none.g, none.b], [0, 0, 0]);
  console.log('Passed: test_fill_matches_lightmap_sum');
}

// 6. test_textures_grow_preserves_bricks (plus writeBrick validation & scale rows preservation)
{
  const tex = createModelLightTextures({ maxBricks: 2, maxEmitters: 4 });
  assert.ok(tex.bricks instanceof THREE.Data3DTexture);
  assert.equal(tex.bricks.minFilter, THREE.LinearFilter);
  assert.equal(tex.bricks.magFilter, THREE.LinearFilter);
  assert.equal(tex.bricks.wrapS, THREE.ClampToEdgeWrapping);
  assert.equal(tex.bricks.wrapT, THREE.ClampToEdgeWrapping);
  assert.equal(tex.bricks.wrapR, THREE.ClampToEdgeWrapping);
  assert.equal(tex.bricks.image.width, 10);
  assert.equal(tex.bricks.image.height, 5);
  assert.equal(tex.bricks.image.depth, 10);
  assert.ok(tex.lamps instanceof THREE.DataTexture);
  assert.equal(tex.lamps.type, THREE.FloatType);
  assert.equal(tex.lamps.minFilter, THREE.NearestFilter);
  assert.equal(tex.lamps.magFilter, THREE.NearestFilter);
  assert.equal(tex.mvSize.x, 4);
  assert.equal(tex.mvSize.y, 2);

  // writeBrick rejects non-integer emitter indices
  assert.throws(() => tex.writeBrick(0, new Uint8Array(1000), [1.5]), TypeError, 'non-integer float throws');
  assert.throws(() => tex.writeBrick(0, new Uint8Array(1000), ['0']), TypeError, 'string index throws');
  assert.throws(() => tex.writeBrick(0, new Uint8Array(1000), [NaN]), TypeError, 'NaN index throws');

  const emitterRec = {
    id: 'light.a#0', device: 'light.a', index: 0, column: 0, shape: 1,
    position: new THREE.Vector3(1.5, 2.5, -3.5), range: 6.0,
    axis: new THREE.Vector3(0, -1, 0), cosOuter: 0.866, cosInner: 0.933,
    halfSize: [0, 0], rotation: new THREE.Quaternion(), outputScale: 42.5,
  };
  tex.writeEmitter(2, emitterRec);
  tex.setTint(2, new THREE.Color(0.5, 0.25, 0.1));

  const brickData0 = new Uint8Array(1000).map((_, k) => (k * 7) % 255);
  const brickData1 = new Uint8Array(1000).map((_, k) => (k * 13 + 3) % 255);
  const box0 = new THREE.Box3(new THREE.Vector3(1, 0, -2), new THREE.Vector3(3, 2, 0));
  const fill0 = new THREE.Color(0.1, 0.2, 0.3);
  const fill1 = new THREE.Color(0.4, 0.5, 0.6);
  // Missing id (-1) in the middle: slots [2, -1, 0] with scales [2.5, 9.9, 1.5]
  // must compact contiguously into slots 0..1 -> rows [2, 0], scales [2.5, 1.5], count = 2,
  // and brick visibility channel 2 must compact into channel 1.
  const midData = new Uint8Array(1000);
  for (let iz = 0; iz < 5; iz++) for (let iy = 0; iy < 5; iy++) for (let ix = 0; ix < 5; ix++) {
    const base = ((iz * 5 + iy) * 10 + ix) * 4;
    midData[base + 0] = 111; // original slot 0
    midData[base + 1] = 222; // original slot 1 (skipped -1)
    midData[base + 2] = 77;  // original slot 2 -> must compact into slot 1
  }
  tex.writeBrick(0, midData, [2, -1, 0], fill0, box0, [2.5, 9.9, 1.5]);
  tex.writeBrick(1, brickData1, [2], fill1);

  const grown = tex.grow(8);
  assert.notEqual(grown.bricks, tex.bricks, 'grow returns a new Data3DTexture');
  assert.notEqual(grown.lamps, tex.lamps, 'grow returns a new lamps DataTexture');
  assert.equal(grown.bricks.image.depth, 5 * 8);
  assert.equal(grown.mvSize.y, 8);
  assert.equal(grown.mvSize.x, 4);

  // Brick 0 compacted channels preserved across grow (slot 0 = 111, slot 1 = 77 from old slot 2, slot 2 = 0)
  const sampleBase = ((2 * 5 + 2) * 10 + 2) * 4;
  assert.equal(grown.bricks.image.data[sampleBase + 0], 111, 'compacted brick slot 0 bytes preserved');
  assert.equal(grown.bricks.image.data[sampleBase + 1], 77, 'middle -1 compacted original slot 2 into brick slot 1');
  assert.equal(grown.bricks.image.data[sampleBase + 2], 0, 'unused brick slot 2 zeroed after compaction');
  assert.deepEqual([...grown.bricks.image.data.subarray(1000, 2000)], [...brickData1], 'brick 1 bytes preserved');

  const readLamps = (t, x, y) => {
    const off = (y * t.image.width + x) * 4;
    return [t.image.data[off], t.image.data[off + 1], t.image.data[off + 2], t.image.data[off + 3]];
  };
  const W = grown.mvSize.z, firstBrick = grown.mvSize.w;
  const L = MODEL_LIGHT_LAYOUT;
  assert.equal(L.BRICK_ROWS, 7);

  const ex = 2 % W, ey0 = Math.floor(2 / W) * L.EMITTER_ROWS;
  const ePos = readLamps(grown.lamps, ex, ey0 + L.EMITTER_ROW_POS_RANGE);
  const eCol = readLamps(grown.lamps, ex, ey0 + L.EMITTER_ROW_COLOR_SCALE);
  near(ePos[0], 1.5, 1e-5); near(ePos[3], 6.0, 1e-5);
  near(eCol[0], 0.5 * 42.5, 1e-4); near(eCol[1], 0.25 * 42.5, 1e-4); near(eCol[3], 42.5, 1e-4);

  const bx = 0 % W, by0 = firstBrick + Math.floor(0 / W) * L.BRICK_ROWS;
  const bEmit = readLamps(grown.lamps, bx, by0 + L.BRICK_ROW_EMITTERS);
  const bMeta = readLamps(grown.lamps, bx, by0 + L.BRICK_ROW_META);
  const bFill = readLamps(grown.lamps, bx, by0 + L.BRICK_ROW_FILL);
  const bMin = readLamps(grown.lamps, bx, by0 + L.BRICK_ROW_BOX_MIN);
  const bInv = readLamps(grown.lamps, bx, by0 + L.BRICK_ROW_BOX_INV);
  const bS0 = readLamps(grown.lamps, bx, by0 + L.BRICK_ROW_SCALES_0);
  assert.equal(bEmit[0], (2 + 1) + (0 + 1) * L.EMITTER_PACK_STRIDE, 'compacted slots 0..1 hold rows [2, 0]');
  assert.equal(bEmit[1], 0, 'slot 2..3 empty after compaction');
  assert.equal(bMeta[0], 2, 'brick 0 count is 2 (slots 0..1 valid)');
  assert.equal(bMeta[1], 0, 'brick 0 zOffset preserved');
  near(bFill[0], 0.1, 1e-5); near(bFill[1], 0.2, 1e-5); near(bFill[2], 0.3, 1e-5);
  near(bMin[0], 1, 1e-5); near(bInv[0], 0.5, 1e-5);
  near(bS0[0], 2.5, 1e-5, 'compacted slot 0 scale is 2.5');
  near(bS0[1], 1.5, 1e-5, 'compacted slot 1 scale is 1.5 (moved from original index 2)');
  near(bS0[2], 1.0, 1e-5, 'unused slot 2 scale defaults to 1.0');

  const b1x = 1 % W, b1y0 = firstBrick + Math.floor(1 / W) * L.BRICK_ROWS;
  assert.equal(readLamps(grown.lamps, b1x, b1y0 + L.BRICK_ROW_META)[1], 5, 'brick 1 zOffset is 5');

  grown.setTint(2, new THREE.Color(1, 0, 0));
  const eColAfter = readLamps(grown.lamps, ex, ey0 + L.EMITTER_ROW_COLOR_SCALE);
  near(eColAfter[0], 42.5, 1e-4, 'setTint after grow uses preserved outputScale');
  near(eColAfter[1], 0, 1e-5);

  tex.dispose();
  grown.dispose();
  console.log('Passed: test_textures_grow_preserves_bricks');
}
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_model_bricks_') as directory:
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
