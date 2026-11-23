"""Task 3: gutter/downspout geometry, surface kind, stream suppression & pours (Node)."""
import json
import os
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const crypto = await import('node:crypto');
const THREE = await import('three');
const { buildTwin, buildingKey, _gutterPlacementStats } = await import(file('static/twin/twin_generator.js'));
const G = await import(file('static/twin/gutters.js'));
const E = await import(file('static/twin/sky/eave_streams.js'));
const { eaveRunoff } = await import(file('static/twin/sky/roof_water.js'));
const { KINDS, kindRow } = await import(file('static/twin/surface_kinds.js'));
const { BAKE_GENERATOR_VERSION } = await import(file('static/twin/bake/key_inputs.js'));
const { buildAtlas } = await import(file('static/twin/bake/atlas.js'));
const { releaseBakeSource } = await import(file('static/twin/bake/source.js'));

const FT = 0.3048;
const clone = structuredClone;
const near = (a, b, e = 1e-3) => assert.ok(Math.abs(a - b) < e, `${a} != ${b} (eps ${e})`);
const rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];

function house(length = 30, kind = 'gable', poly = rect(0, 0, length, 20), overhang = 1) {
  const b = {
    id: 'b', position: [0, 0], base: 0, rotation: 0,
    levels: [{ id: 'L1', elevation: 0, ceiling: 10, outline: poly }],
    rooms: [],
    walls: poly.map((a, i) => ({
      id: 'w' + i, from: a, to: poly[(i + 1) % poly.length],
      exterior: true, height: 10, thickness: 0.5, level: 'L1',
    })),
    openings: [],
    roof: { sections: [], extensions: [] },
    roofs: [],
  };
  const p = { units: 'ft', buildings: [b], site: {} };
  addRoof(p, 'r', [0, 0, length, 20], kind, { overhang });
  return p;
}

function addRoof(p, id, bounds, kind = 'hip', extra = {}) {
  const s = {
    id, roof: id, kind, ridge: 'x', pitch: 6, plate: 10, overhang: 1, level: 'L1', rect: bounds,
    plane_edges: { y0: 0, x1: 1, y1: 2, x0: 3 }, ...extra,
  };
  const low = s.low_side;
  const settings = ['y0', 'x1', 'y1', 'x0'].map(side =>
    kind === 'shed' ? (side === low ? 'sloped' : 'gable')
      : kind === 'gable' && side[0] === s.ridge ? 'gable' : 'sloped');
  const r = {
    id, area: rect(...bounds), overhang: s.overhang,
    edges: settings.map(setting => ({ setting, gutter: setting === 'sloped' })),
  };
  s.gutters = Object.fromEntries(['y0', 'x1', 'y1', 'x0'].filter((_, i) => settings[i] === 'sloped').map(side => [side, true]));
  p.buildings[0].roofs.push(r);
  p.buildings[0].roof.sections.push(s);
  return s;
}

function geometryDigest(root) {
  root.updateMatrixWorld(true);
  let triangles = 0;
  const h = crypto.createHash('sha256');
  const meshes = [];
  root.traverse(o => {
    if (!o.isMesh || !o.geometry?.attributes?.position) return;
    if (o.layers.isEnabled(31)) return;
    meshes.push(o);
  });
  for (const m of meshes) {
    const g = m.geometry;
    const pos = g.attributes.position;
    const idx = g.index;
    triangles += idx ? idx.count / 3 : pos.count / 3;
    const arr = new Float32Array(pos.array.buffer, pos.array.byteOffset, pos.array.byteLength / 4);
    h.update(Buffer.from(arr.buffer, arr.byteOffset, arr.byteLength));
    if (idx) h.update(Buffer.from(idx.array.buffer, idx.array.byteOffset, idx.array.byteLength));
  }
  return { meshes: meshes.length, triangles, posHash: h.digest('hex') };
}

function gutterTriangles(root) {
  root.updateMatrixWorld(true);
  const tris = [];
  const taggedMeshes = [];
  const v = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  root.traverse(o => {
    if (!o.isMesh || o.layers.isEnabled(31) || !o.geometry?.attributes?.position) return;
    const pos = o.geometry.attributes.position;
    const ranges = o.userData.snapRanges;
    const hasGutterRange = Array.isArray(ranges) && ranges.some(r => r.surfaceKind === 'gutter');
    if (o.userData.surfaceKind === 'gutter' || hasGutterRange) {
      taggedMeshes.push(o);
      const emitRange = (start, count) => {
        for (let i = start; i < start + count; i += 3) {
          for (let k = 0; k < 3; k++) v[k].fromBufferAttribute(pos, i + k).applyMatrix4(o.matrixWorld);
          tris.push(v.map(p => [p.x, p.y, p.z]));
        }
      };
      if (hasGutterRange) {
        for (const r of ranges) if (r.surfaceKind === 'gutter') emitRange(r.start, r.count);
      } else {
        emitRange(0, pos.count);
      }
    }
  });
  return { tris, taggedMeshes };
}

const disposeTwin = twin => {
  for (const g of Object.values(twin.groups)) {
    if (g?.traverse) g.traverse(o => o.geometry?.dispose?.());
    else if (g && typeof g === 'object') for (const sub of Object.values(g)) sub?.traverse?.(o => o.geometry?.dispose?.());
  }
};

// Baseline captured from base commit before Task 3 edits on household-2026-11-09.json
const EXPECTED_HOUSEHOLD_TRIS = 67978;
const EXPECTED_HOUSEHOLD_HASH = 'ba229fe1cb8a11951a92d25779ecd88c46e6506826af93d3ceacb577de75d94f';
const EXPECTED_STREAM_COUNT = 1088;
const EXPECTED_STREAM_HASH = '2b02e0aacdb8dc31f2ffc5d59bbe32771e087fa41dea365a1679a69bc2869535';

await test('test_no_gutters_identical_geometry', async () => {
  const twin = buildTwin(clone(input.plan), input.kit, 'high');
  await twin.ready;
  try {
    const d = geometryDigest(twin.root);
    assert.equal(d.triangles, EXPECTED_HOUSEHOLD_TRIS, `triangles ${d.triangles} != ${EXPECTED_HOUSEHOLD_TRIS}`);
    assert.equal(d.posHash, EXPECTED_HOUSEHOLD_HASH, `posHash ${d.posHash} != ${EXPECTED_HOUSEHOLD_HASH}`);
    const { taggedMeshes } = gutterTriangles(twin.root);
    assert.equal(taggedMeshes.length, 0, 'no gutter meshes when gutters are off');
  } finally { disposeTwin(twin); }
});

await test('test_gutter_follows_run_with_mitres_and_end_caps', async () => {
  // Hip roof with 2 adjacent guttered edges (y0 and x1) -> 1 open run with a 90 deg corner mitre and 2 free end caps.
  const p = house(30, 'hip', rect(0, 0, 30, 20), 1);
  p.buildings[0].roofs[0].edges[2].gutter = false;
  p.buildings[0].roofs[0].edges[3].gutter = false;
  delete p.buildings[0].roof.sections[0].gutters.y1;
  delete p.buildings[0].roof.sections[0].gutters.x0;
  // Also build an identical unguttered copy to confirm draw count does not grow.
  const pOff = clone(p);
  pOff.buildings[0].roofs[0].edges.forEach(e => e.gutter = false);
  pOff.buildings[0].roof.sections[0].gutters = {};

  const twinOff = buildTwin(pOff, input.kit, 'high'); await twinOff.ready;
  const twinOn = buildTwin(p, input.kit, 'high'); await twinOn.ready;
  try {
    const roofDraws = root => {
      let n = 0;
      root.getObjectByName('roof').traverse(o => { if (o.isMesh && !o.layers.isEnabled(31)) n++; });
      return n;
    };
    assert.equal(roofDraws(twinOn.root), roofDraws(twinOff.root), 'gutters merge into fascia/trim batch with 0 extra draws');
    const { tris, taggedMeshes } = gutterTriangles(twinOn.root);
    assert.ok(taggedMeshes.length > 0, 'gutter mesh tagged with userData.surfaceKind="gutter"');
    assert.ok(tris.length > 20, `expected gutter + downspout triangles, got ${tris.length}`);

    const runs = G.gutterRuns(p, twinOn.roofSurfaces);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].segments.length, 2);
    const eaveY = runs[0].segments[0].a[1]; // world metres
    const pts = tris.flat();
    // Top of gutter is level with roof edge (within 1 cm), never significantly above it.
    const maxY = Math.max(...pts.map(pt => pt[1]));
    assert.ok(Math.abs(maxY - eaveY) < 0.015, `gutter top ${maxY} should match eave ${eaveY}`);

    // Mitre corner at (x = 31 ft, y = -1 ft) in plan -> world X = 31*FT, Z = +1*FT.
    // Outward 5 in (5/12 ft) along BOTH +X and +Z meets at (31 + 0.012 + 5/12, -1 - 0.012 - 5/12) in plan.
    const mitreX = (31 + 0.012 + 5 / 12) * FT;
    const mitreZ = (1 + 0.012 + 5 / 12) * FT;
    const hasMitreLip = pts.some(pt => Math.abs(pt[0] - mitreX) < 0.015 && Math.abs(pt[2] - mitreZ) < 0.015 && Math.abs(pt[1] - eaveY) < 0.015);
    assert.ok(hasMitreLip, `missing 45-degree mitred outer corner vertex near (${mitreX.toFixed(3)}, ${eaveY.toFixed(3)}, ${mitreZ.toFixed(3)})`);

    // End caps: at x = -1*FT (free end of y0) and z = -21*FT (free end of x1), there must be triangles
    // whose normal points along the run tangent (-X at start of y0, -Z at end of x1).
    const startX = -1 * FT, endZ = -21 * FT;
    const triNormal = t => {
      const a = new THREE.Vector3(...t[0]), b = new THREE.Vector3(...t[1]), c = new THREE.Vector3(...t[2]);
      return new THREE.Vector3().crossVectors(b.sub(a), c.sub(a)).normalize();
    };
    const startCaps = tris.filter(t => t.every(pt => Math.abs(pt[0] - startX) < 0.01 && pt[1] <= eaveY + 0.01 && pt[1] >= eaveY - 0.15) && Math.abs(triNormal(t).x) > 0.95);
    const endCaps = tris.filter(t => t.every(pt => Math.abs(pt[2] - endZ) < 0.01 && pt[1] <= eaveY + 0.01 && pt[1] >= eaveY - 0.15) && Math.abs(triNormal(t).z) > 0.95);
    assert.ok(startCaps.length >= 3, `expected flat end cap at run start, got ${startCaps.length} tris`);
    assert.ok(endCaps.length >= 3, `expected flat end cap at run end, got ${endCaps.length} tris`);

    // Open top: no horizontal triangles at eaveY spanning across the gutter top.
    const topFaces = tris.filter(t => t.every(pt => Math.abs(pt[1] - eaveY) < 0.005) && Math.abs(triNormal(t).y) > 0.9);
    assert.equal(topFaces.length, 0, 'gutter must be open on top (no top face)');
  } finally { disposeTwin(twinOff); disposeTwin(twinOn); }
});

await test('test_downspout_path_and_kickout', async () => {
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1.5);
  const twin = buildTwin(p, input.kit, 'high'); await twin.ready;
  try {
    const runs = G.gutterRuns(p, twin.roofSurfaces);
    const spouts = G.downspouts(p, runs);
    assert.ok(spouts.length >= 2);
    const { tris } = gutterTriangles(twin.root);
    const pts = tris.flat();

    for (const s of spouts) {
      assert.equal(s.mount, 'wall');
      // Vertices must exist near every waypoint along path (offset elbows, wall drop, kick-out).
      for (const wp of s.path) {
        const dMin = Math.min(...pts.map(pt => Math.hypot(pt[0] - wp[0], pt[1] - wp[1], pt[2] - wp[2])));
        assert.ok(dMin < 0.08, `no downspout vertex near path node ${wp.map(v => v.toFixed(3))} (min dist ${dMin.toFixed(4)} m)`);
      }
      // Check kick-out last segment runs along outlet.dir out to outlet.at.
      const prev = s.path.at(-2), out = s.outlet.at;
      const segVec = [out[0] - prev[0], 0, out[2] - prev[2]];
      const segLen = Math.hypot(...segVec);
      assert.ok(segLen > 0.5, 'kick-out segment should have length');
      const dotDir = (segVec[0] * s.outlet.dir[0] + segVec[2] * s.outlet.dir[2]) / segLen;
      assert.ok(dotDir > 0.99, `kick-out segment does not align with outlet.dir: dot=${dotDir}`);

      // Verify 2x3 in cross-section on vertical drop (slice triangles at mid-wall height) with 3 in side along wall.
      const wallBot = s.path.at(-2);
      const midY = (s.top[1] + wallBot[1]) / 2;
      const slicePts = [];
      for (const tri of tris) {
        const ys = tri.map(pt => pt[1]);
        if (Math.min(...ys) > midY || Math.max(...ys) < midY) continue;
        for (let k = 0; k < 3; k++) {
          const a = tri[k], b = tri[(k + 1) % 3];
          if ((a[1] - midY) * (b[1] - midY) <= 0 && Math.abs(b[1] - a[1]) > 1e-6) {
            const f = (midY - a[1]) / (b[1] - a[1]);
            const ix = a[0] + (b[0] - a[0]) * f, iz = a[2] + (b[2] - a[2]) * f;
            if (Math.hypot(ix - wallBot[0], iz - wallBot[2]) < 0.2) slicePts.push([ix, midY, iz]);
          }
        }
      }
      assert.ok(slicePts.length >= 4, 'vertical wall drop cross-section present at mid-wall');
      // For y0/y1 eaves, wall runs along X (3 in = 0.0762 m) and outward is +/-Z (2 in = 0.0508 m).
      const spanX = Math.max(...slicePts.map(pt => pt[0])) - Math.min(...slicePts.map(pt => pt[0]));
      const spanZ = Math.max(...slicePts.map(pt => pt[2])) - Math.min(...slicePts.map(pt => pt[2]));
      near(spanX, 3 / 12 * FT, 0.008);
      near(spanZ, 2 / 12 * FT, 0.008);
    }
  } finally { disposeTwin(twin); }
});

await test('test_hang_stub_has_no_kickout', async () => {
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1);
  p.buildings[0].roof.sections[0].plate = 22; // walls stop at 10 ft -> mount: 'hang'
  const twin = buildTwin(p, input.kit, 'high'); await twin.ready;
  try {
    const runs = G.gutterRuns(p, twin.roofSurfaces);
    const spouts = G.downspouts(p, runs);
    assert.ok(spouts.length >= 2);
    assert.ok(spouts.every(s => s.mount === 'hang' && s.flags.includes('hang') && s.flags.includes('stub')));
    const { tris } = gutterTriangles(twin.root);
    const pts = tris.flat();
    const minY = Math.min(...pts.map(pt => pt[1]));
    const lowestOutletY = Math.min(...spouts.map(s => s.outlet.at[1]));
    // No wall drop down toward ground; everything stays up near the eave/stub.
    assert.ok(minY >= lowestOutletY - 0.06, `hang stub must not drop below outlet (${minY} vs ${lowestOutletY})`);
    // Stub vertices exist right at the outlet.
    for (const s of spouts) {
      const stubPts = pts.filter(pt => Math.abs(pt[1] - s.outlet.at[1]) < 0.05 && Math.hypot(pt[0] - s.outlet.at[0], pt[2] - s.outlet.at[2]) < 0.1);
      assert.ok(stubPts.length >= 4, 'hang stub geometry exists at outlet');
    }
  } finally { disposeTwin(twin); }
});

await test('test_surface_kind_defaults_to_trim', async () => {
  const row = kindRow('gutter');
  assert.ok(row, 'gutter surface kind must exist in KINDS');
  assert.equal(row.scope, 'building');
  assert.deepEqual(row.fallback, { role: 'trim' });
  assert.equal(row.item, null);

  // Default: gutter uses same material as trim/fascia.
  const p = house(30, 'gable');
  const twinDefault = buildTwin(p, input.kit, 'high'); await twinDefault.ready;
  try {
    const { taggedMeshes } = gutterTriangles(twinDefault.root);
    assert.ok(taggedMeshes.length > 0);
    const trimMat = twinDefault.materials.get('trim');
    assert.ok(trimMat, 'trim material exists');
    assert.equal(taggedMeshes[0].material, trimMat, 'gutter defaults to trim/fascia material');
  } finally { disposeTwin(twinDefault); }

  // Custom override: building.materials.gutter overrides gutter without changing trim/fascia.
  const pCustom = clone(p);
  pCustom.buildings[0].materials = { gutter: { id: 'black_metal' } };
  const twinCustom = buildTwin(pCustom, input.kit, 'high'); await twinCustom.ready;
  try {
    const { taggedMeshes } = gutterTriangles(twinCustom.root);
    assert.ok(taggedMeshes.length > 0);
    const trimMat = twinCustom.materials.get('trim');
    assert.notEqual(taggedMeshes[0].material, trimMat, 'gutter override produces its own material');
    assert.equal(taggedMeshes[0].material.color.getHexString(), '1b1c1e', 'black_metal finish applied to gutter');
  } finally { disposeTwin(twinCustom); }
});

await test('test_guttered_edges_shed_no_streams', async () => {
  // 1) Roof section: gutter y0 only, leave y1 unguttered.
  const p = house(30, 'gable');
  p.buildings[0].roofs[0].edges[2].gutter = false;
  delete p.buildings[0].roof.sections[0].gutters.y1;
  const res = E.eaveInstances(p, new Map(), input.kit);
  assert.ok(res.eaves.every(e => e.side !== 'y0'), 'guttered edge y0 must shed no stream eaves');
  assert.ok(res.eaves.some(e => e.side === 'y1'), 'unguttered edge y1 must still stream');
  const streamOnly = res.instances.filter(i => !i.pour);
  assert.ok(streamOnly.length > 0 && streamOnly.every(i => i.eave.side === 'y1'), 'only y1 emits eave stream instances');

  // 2) Porch gutter: porch roof eaves shed no streams when porch.gutter = true.
  const pPorch = house(30, 'gable');
  pPorch.buildings[0].roof.sections = [];
  pPorch.buildings[0].roofs = [];
  const ps = addRoof(pPorch, 'porchroof', [0, -8, 30, 0], 'shed', { low_side: 'y0', plate: 8, pitch: 3, overhang: 1 });
  ps.gutters = {};
  pPorch.buildings[0].roofs[0].edges.forEach(e => e.gutter = false);
  pPorch.buildings[0].porches = [{ id: 'p', gutter: true, polygon: rect(0, -8, 30, 0), floor: 0, columns: [{ at: [0, -8], size: 0.5 }, { at: [30, -8], size: 0.5 }] }];
  const porchRes = E.eaveInstances(pPorch, new Map(), input.kit);
  assert.equal(porchRes.eaves.length, 0, 'guttered porch sheds no eave streams');
  assert.equal(porchRes.instances.filter(i => !i.pour).length, 0);

  // 3) Awning gutter: awning attachment sheds no streams when awning.gutter = true.
  const pAw = house(30, 'gable');
  pAw.buildings[0].roof.extensions = [{ id: 'aw', kind: 'awning', section: 'r', wall: 'w0', x0: 5, x1: 15, depth: 3, eave: 8, pitch: 3, gutter: true }];
  const twinAw = buildTwin(pAw, input.kit, 'high'); await twinAw.ready;
  try {
    const awRes = E.eaveInstances(pAw, twinAw.roofSurfaces, input.kit);
    assert.equal(awRes.eaves.filter(e => e.kind === 'attachment').length, 0, 'guttered awning sheds no streams');
    assert.equal(awRes.instances.filter(i => !i.pour).length, 0, 'all guttered house+awning has 0 eave streams');
    assert.ok(awRes.instances.filter(i => i.pour).length >= 3, 'house + awning downspouts emit pours');
  } finally { disposeTwin(twinAw); }
});

await test('test_unguttered_roof_stream_instances_unchanged', async () => {
  const twin = buildTwin(clone(input.plan), input.kit, 'high'); await twin.ready;
  try {
    const res = E.eaveInstances(clone(input.plan), twin.roofSurfaces, input.kit);
    assert.equal(res.eaves.length, 26);
    assert.equal(res.instances.length, EXPECTED_STREAM_COUNT);
    const eh = crypto.createHash('sha256');
    eh.update(JSON.stringify(res.instances.map(i => [i.top, i.bottom, i.landing, i.seed, i.rank, i.eaveS, i.cellStep, i.sheetCap, i.angle])));
    assert.equal(eh.digest('hex'), EXPECTED_STREAM_HASH, 'unguttered household stream instances must be identical');
  } finally { disposeTwin(twin); }
});

await test('test_pours_follow_runoff_and_share', async () => {
  // 40 ft gable: each run gets 2 downspouts (share 0.5); 30 ft gable gets 1 downspout per run (share 1.0).
  const p1 = house(30, 'gable');
  const p2 = house(40, 'gable');
  const res1 = E.eaveInstances(p1, new Map(), input.kit);
  const res2 = E.eaveInstances(p2, new Map(), input.kit);
  const pours1 = res1.instances.filter(i => i.pour);
  const pours2 = res2.instances.filter(i => i.pour);
  assert.equal(pours1.length, 2);
  assert.equal(pours2.length, 4);

  // Kick-out pour shape: falls ~0.4 ft, lands ~0.3 ft forward along outlet.dir.
  for (const pr of pours1) {
    near(pr.share, 1.0, 1e-4);
    near(pr.top[1] - pr.bottom, 0.4 * FT, 0.05);
    near(pr.pourForward, 0.3 * FT, 0.03);
    assert.ok(Math.abs(Math.hypot(...pr.pourDir) - 1) < 1e-4);
  }
  // Share scaling: share=1.0 pour has strictly larger width and share magnitude than share=0.5 pour.
  assert.ok(pours1[0].pourWidth > pours2[0].pourWidth, `share=1 width (${pours1[0].pourWidth}) > share=0.5 width (${pours2[0].pourWidth})`);
  assert.ok(pours1[0].share > pours2[0].share);

  // Hang/stub pour uses landing sampler for full-height fall to receiving surface.
  const pHang = house(30, 'gable');
  pHang.buildings[0].roof.sections[0].plate = 22;
  const hangPours = E.eaveInstances(pHang, new Map(), input.kit).instances.filter(i => i.pour);
  assert.ok(hangPours.length >= 2);
  for (const pr of hangPours) {
    assert.ok(pr.top[1] - pr.bottom > 5.0, `hang stub pour must fall full height to ground, got ${(pr.top[1] - pr.bottom).toFixed(2)} m`);
  }

  // lands: 'roof' gets a short pour onto the lower roof.
  const pUpper = house(30, 'gable');
  const b = pUpper.buildings[0];
  b.roof.sections[0].plate = 20;
  b.levels.push({ id: 'L2', elevation: 10, ceiling: 10, outline: rect(0, 0, 30, 20) });
  b.walls.push(...b.walls.map(w => ({ ...clone(w), id: w.id + 'up', level: 'L2' })));
  b.roof.sections[0].level = 'L2';
  addRoof(pUpper, 'lower', [-5, -8, 35, -0.1], 'flat', { plate: 7, overhang: 0 });
  const roofPours = E.eaveInstances(pUpper, new Map(), input.kit).instances.filter(i => i.pour && i.lands === 'roof');
  assert.ok(roofPours.length >= 1, 'expected roof-landing pour');
  assert.ok(roofPours[0].bottom >= 7 * FT - 0.05 && roofPours[0].top[1] - roofPours[0].bottom < 0.6, 'short pour onto lower roof');

  // Driven by eaveFlow via eaveRunoff: at eaveRunoff === 0 there is NO pour; at heavy rain pours run.
  const scene = new THREE.Scene();
  const sys = E.createEaveStreams(scene, { tier: 'high' });
  sys.setPlan(p1, new Map(), input.kit);
  assert.ok(sys.streams && sys.mist, 'pour uses existing streams and mist meshes');
  assert.equal(sys.streams.material.vertexShader, sys.mist.material.vertexShader, 'same program');
  assert.equal(sys.streams.material.fragmentShader, sys.mist.material.fragmentShader, 'same program');
  assert.ok(!sys.streams.material.fragmentShader.includes('sampler'), 'no new sampler');

  const dryRunoff = eaveRunoff({ flow: 1, wet: 0.1 }); // wet < 0.25 -> eaveRunoff === 0
  assert.equal(dryRunoff, 0);
  sys.update({ flow: dryRunoff, wet: 0.1 }, 10);
  assert.equal(sys.group.visible, false, 'no pour when eaveRunoff is 0');
  assert.equal(sys.streams.geometry.instanceCount, 0, '0 pour instances drawn when eaveRunoff is 0');

  const wetRunoff = eaveRunoff({ flow: 1, wet: 1 });
  assert.equal(wetRunoff, 1);
  sys.update({ flow: wetRunoff, wet: 1 }, 11);
  assert.equal(sys.group.visible, true, 'pours visible when eaveRunoff > 0');
  assert.equal(sys.streams.geometry.instanceCount, 2, 'all 2 downspouts pour');
  sys.dispose();
});

await test('test_drains_to_runs_get_no_pour', async () => {
  const p = house(30, 'gable');
  // Suppress downspouts on edge 0 -> edge 0 run gets drainsTo pointing to edge 2's downspout.
  p.buildings[0].roofs[0].edges[0].downspouts = [];
  p.buildings[0].roof.sections[0].downspouts = { y0: [] };
  const runs = G.gutterRuns(p);
  const spouts = G.downspouts(p, runs);
  assert.equal(runs.length, 2);
  assert.equal(spouts.length, 1);
  assert.ok(runs.some(r => r.drainsTo === spouts[0].id), 'orphan run drainsTo receiving spout');

  const res = E.eaveInstances(p, new Map(), input.kit);
  const pours = res.instances.filter(i => i.pour);
  assert.equal(pours.length, 1, 'drainsTo run gets no pour of its own');
  assert.equal(pours[0].spout.id, spouts[0].id);
  near(pours[0].share, 1.0, 1e-4);
});

await test('test_generator_version_bumped', async () => {
  assert.equal(BAKE_GENERATOR_VERSION, 'gutters-1');
});

await test('test_two_building_garage_under_eave_pipe_and_pour_agree', async () => {
  // Reproduces review I-1: a separate flat-roofed garage building under the house's y0 eave.
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1);
  const b = p.buildings[0];
  b.levels.push({ id: 'L2', elevation: 10, ceiling: 10, outline: rect(0, 0, 30, 20) });
  b.walls.push(...b.walls.map(w => ({ ...clone(w), id: w.id + '_L2', level: 'L2' })));
  b.roof.sections[0].plate = 20;
  b.roof.sections[0].level = 'L2';

  const gPoly = rect(0, 0, 40, 14);
  const garage = {
    id: 'garage', position: [-5, -14], base: 0, rotation: 0,
    levels: [{ id: 'G1', elevation: 0, ceiling: 7, outline: gPoly }],
    rooms: [],
    walls: gPoly.map((a, i) => ({
      id: 'gw' + i, from: a, to: gPoly[(i + 1) % 4],
      exterior: true, height: 7, thickness: 0.5, level: 'G1',
    })),
    openings: [],
    roof: {
      sections: [{
        id: 'gr', roof: 'gr', kind: 'flat', ridge: 'x', pitch: 0, plate: 7, overhang: 0, level: 'G1',
        rect: [0, 0, 40, 14], plane_edges: { y0: 0, x1: 1, y1: 2, x0: 3 },
      }],
      extensions: [],
    },
    roofs: [{
      id: 'gr', area: gPoly, overhang: 0,
      edges: [0, 1, 2, 3].map(() => ({ setting: 'gable', gutter: false })),
    }],
  };
  p.buildings.push(garage);

  _gutterPlacementStats.clearCache();
  const twin = buildTwin(p, input.kit, 'high');
  await twin.ready;
  try {
    const res = E.eaveInstances(p, twin.roofSurfaces, input.kit, twin.gutters);
    const roofSpout = twin.gutters.spouts.find(s => s.outlet.lands === 'roof');
    assert.ok(roofSpout, 'house y0 downspout must land on neighbouring garage roof');
    const roofPour = res.pours.find(pr => pr.spout.id === roofSpout.id);
    assert.ok(roofPour, 'matching roof-landing pour must exist');
    assert.equal(roofPour.lands, 'roof');

    // Drawn pipe outlet in twin.root must agree with pour top within 0.05 m (both at garage roof ~7.4 ft, not ground!).
    const { tris } = gutterTriangles(twin.root);
    const nearOutlet = tris.flat().filter(pt =>
      Math.hypot(pt[0] - roofPour.top[0], pt[2] - roofPour.top[2]) < 0.15
    );
    assert.ok(nearOutlet.length >= 4, 'drawn pipe vertices exist at garage-roof outlet');
    const drawnMinY = Math.min(...nearOutlet.map(pt => pt[1]));
    const drawnMaxNearOutletY = Math.min(...nearOutlet.map(pt => Math.abs(pt[1] - roofPour.top[1])));
    assert.ok(drawnMaxNearOutletY < 0.05, `drawn pipe outlet must match pour top within 0.05 m (gap=${drawnMaxNearOutletY.toFixed(4)} m)`);
    assert.ok(drawnMinY >= 7 * FT - 0.05, `drawn pipe must stop at garage roof (~${(7*FT).toFixed(2)} m), not plunge to ground (minY=${drawnMinY.toFixed(3)} m)`);
  } finally { disposeTwin(twin); }
});

await test('test_site_path_edit_invalidates_building_key_and_moves_kickout', async () => {
  // Reproduces review I-2: adding/editing a walkway under a kick-out must change buildingKey and rebuild geometry.
  _gutterPlacementStats.clearCache();
  const p1 = house(30, 'gable', rect(0, 0, 30, 20), 1);
  const key1 = buildingKey(p1, p1.buildings[0], input.kit, 'high');
  const twin1 = buildTwin(p1, input.kit, 'high');
  await twin1.ready;
  try {
    const s1 = twin1.gutters.spouts[0];
    assert.ok(s1 && s1.mount === 'wall');
    const ox = s1.outlet.at[0] / FT, oy = -s1.outlet.at[2] / FT;

    // Place a narrow path directly across s1's landing spot so the kick-out must turn aside.
    const p2 = clone(p1);
    p2.site = {
      hardscape: [{
        id: 'walk1', kind: 'path', width: 2.5,
        points: [[ox, oy - 6], [ox, oy + 2]],
      }],
    };
    const key2 = buildingKey(p2, p2.buildings[0], input.kit, 'high');
    assert.notEqual(key2, key1, 'site path edit under kick-out must change buildingKey');

    const twin2 = buildTwin(p2, input.kit, 'high', { previous: twin1 });
    await twin2.ready;
    try {
      assert.ok(twin2.buildingsRebuilt.includes('b'), 'building with moved kick-out must be rebuilt, not reused');
      const s2 = twin2.gutters.spouts.find(s => s.id === s1.id);
      assert.ok(s2, 'matching spout exists after rebuild');
      const shift = Math.hypot(s2.outlet.at[0] - s1.outlet.at[0], s2.outlet.at[2] - s1.outlet.at[2]);
      assert.ok(shift > 0.2, `kick-out must turn off the path (shift=${shift.toFixed(3)} m)`);

      // Drawn geometry and pour must both sit at the moved kick-out outlet.
      const res2 = E.eaveInstances(p2, twin2.roofSurfaces, input.kit, twin2.gutters);
      const pour2 = res2.pours.find(pr => pr.spout.id === s2.id);
      assert.ok(pour2);
      const { tris } = gutterTriangles(twin2.root);
      const minDist = Math.min(...tris.flat().map(pt =>
        Math.hypot(pt[0] - pour2.top[0], pt[1] - pour2.top[1], pt[2] - pour2.top[2])
      ));
      assert.ok(minDist < 0.06, `drawn kick-out must match turned pour position (dist=${minDist.toFixed(4)} m)`);
    } finally { disposeTwin(twin2); }
  } finally { disposeTwin(twin1); }
});

await test('test_single_placement_per_build_and_zero_per_frame', async () => {
  _gutterPlacementStats.clearCache();
  E._eaveGutterStats.reset();
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1);
  const twin1 = buildTwin(p, input.kit, 'high');
  await twin1.ready;
  assert.equal(_gutterPlacementStats.calls, 1, 'exactly 1 placement call on initial buildTwin');

  const scene = new THREE.Scene();
  const sys = E.createEaveStreams(scene, { tier: 'high' });
  sys.setPlan(p, twin1.roofSurfaces, input.kit, twin1.gutters);
  for (let frame = 1; frame <= 10; frame++) sys.update({ flow: 1, wet: 1 }, frame);
  assert.equal(_gutterPlacementStats.calls, 1, '0 extra placement calls during setPlan + 10 frames');
  assert.equal(E._eaveGutterStats.fallbackCalls, 0, 'eaves.setPlan uses twin.gutters with 0 fallback calls');

  // Material-only edit hits memo cache -> 0 new placement calls.
  const pMat = clone(p);
  pMat.buildings[0].materials = { gutter: { id: 'black_metal' } };
  const twin2 = buildTwin(pMat, input.kit, 'high', { previous: twin1 });
  await twin2.ready;
  assert.equal(_gutterPlacementStats.calls, 1, 'material-only edit hits placement memo cache (0 new calls)');
  assert.ok(_gutterPlacementStats.hits >= 1, 'memo cache recorded a hit');

  // Bake rebuild reuses placement -> 0 third pass!
  const atlas = buildAtlas(twin2.root, pMat, { room: { density: 4, page: 2048, gutter: 2 } });
  assert.ok(atlas.room.charts.length > 0);
  assert.equal(_gutterPlacementStats.calls, 1, 'bake source rebuild makes 0 additional placement calls');

  sys.dispose();
  releaseBakeSource(twin2.root);
  disposeTwin(twin1);
  disposeTwin(twin2);
});

await test('test_downspout_sweeps_path_directly_without_inside_stub', async () => {
  // Verify our renderer side of I-4: sweeps directly from path[0] with zero geometry above path[0],
  // and when given a gutter-bottom path that drops below the soffit before elbowing, clears the soffit cleanly.
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1.5);
  const eaveY = 9.25, gutterBotY = eaveY - G.GUTTER.profileIn / 12, soffitY = eaveY - G.GUTTER.fasciaFt;
  const x0 = 0.25, yFascia = -1.5, yTrough = yFascia - (G.GUTTER.fasciaProudFt + G.GUTTER.profileIn / 24), yWall = -0.08;
  const toW = (x, y, z) => [x * FT, z * FT, -y * FT];
  const runs = [{
    id: 'b:r:0', building: 'b', length: 33, corners: [],
    segments: [{
      roof: 'r', edge: 0, porch: null,
      a: toW(-1.5, yFascia, eaveY), b: toW(31.5, yFascia, eaveY), outward: [0, -1],
    }],
  }];
  const contractPath = [
    toW(x0, yTrough, gutterBotY),
    toW(x0, yTrough, Math.min(gutterBotY, soffitY) - G.GUTTER.soffitClearIn / 12),
    toW(x0, yWall, Math.min(gutterBotY, soffitY) - G.GUTTER.soffitClearIn / 12 - (yWall - yTrough)),
    toW(x0, yWall, 0.4),
    toW(x0, yWall - 3, 0.4),
  ];
  const spouts = [{
    id: 'b:r:0:0', run: 'b:r:0', edge: { roof: 'r', edge: 0, porch: null, fraction: 0.05 },
    top: contractPath[0], mount: 'wall', path: contractPath,
    outlet: { at: contractPath.at(-1), dir: [0, 0, 1], lands: 'grass' }, share: 1, source: 'auto', flags: [],
  }];
  const twin = buildTwin(p, input.kit, 'high', { gutters: { runs, spouts } });
  await twin.ready;
  try {
    const { tris } = gutterTriangles(twin.root);
    const inOverhangAboveSoffit = tris.filter(t => t.some(pt => {
      const planY = -pt[2] / FT, planZ = pt[1] / FT;
      return planY > yFascia + 0.01 && planY < -0.01 && planZ > soffitY + 0.005;
    }));
    assert.equal(inOverhangAboveSoffit.length, 0, 'no swept pipe geometry above soffit between fascia and wall');
    const pipeTopNear = tris.flat().filter(pt => {
      const planX = pt[0] / FT, planY = -pt[2] / FT, planZ = pt[1] / FT;
      return Math.abs(planX - x0) < 0.2 && Math.abs(planY - yTrough) < 0.2 && Math.abs(planZ - gutterBotY) < 0.02;
    });
    assert.ok(pipeTopNear.length >= 4, 'downspout top meets gutter bottom cleanly');
  } finally { disposeTwin(twin); }
});

await test('test_downspout_meets_gutter_bottom_and_clears_soffit', async () => {
  // Contract test for I-4 (passes now that Codex's gutters.js path update has merged).
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1.5);
  _gutterPlacementStats.clearCache();
  const twin = buildTwin(p, input.kit, 'high');
  await twin.ready;
  try {
    const s = twin.gutters.spouts.find(v => v.mount === 'wall' && v.edge.edge === 0);
    assert.ok(s, 'wall downspout on y0 eave exists');
    const run = twin.gutters.runs.find(r => r.id === s.run);
    const eaveY = run.segments[0].a[1] / FT; // 10 - 1.5 * 6/12 = 9.25 ft at overhang lip
    const gutterBotY = eaveY - G.GUTTER.profileIn / 12; // 8.8333 ft
    const soffitY = eaveY - G.GUTTER.fasciaFt;          // 8.90 ft
    const fasciaY = -1.5;
    const topZ = s.path[0][1] / FT;
    const topPlanY = -s.path[0][2] / FT;
    assert.ok(
      Math.abs(topZ - gutterBotY) <= 0.01,
      `downspout path[0] height ${topZ.toFixed(4)} ft should meet gutter bottom ${gutterBotY.toFixed(4)} ft`
    );
    assert.ok(
      topPlanY <= fasciaY - G.GUTTER.fasciaProudFt + 1e-3 && topPlanY >= fasciaY - G.GUTTER.fasciaProudFt - G.GUTTER.profileIn / 12 - 1e-3,
      `downspout path[0] planY=${topPlanY.toFixed(4)} ft must lie inside gutter trough`
    );
    assert.ok(
      s.path[1][1] / FT <= Math.min(gutterBotY, soffitY) - G.GUTTER.soffitClearIn / 12 + 1e-3,
      `downspout path[1] must drop at least ${G.GUTTER.soffitClearIn} in below gutter/soffit`
    );
    for (let i = 0; i + 1 < s.path.length; i++) {
      const a = s.path[i], bPt = s.path[i + 1];
      for (const frac of [0.1, 0.5, 0.9]) {
        const py = -(a[2] + (bPt[2] - a[2]) * frac) / FT;
        const pz = (a[1] + (bPt[1] - a[1]) * frac) / FT;
        if (py > fasciaY + 0.01 && py < -0.01) {
          assert.ok(pz <= soffitY + 1e-3, `pipe segment ${i} at planY=${py.toFixed(3)} lies above soffit (${pz.toFixed(3)} > ${soffitY.toFixed(3)} ft)`);
        }
      }
    }
    // Also verify the swept rendered mesh itself has no vertices above the soffit between fascia and wall.
    const { tris } = gutterTriangles(twin.root);
    const overhangViolations = tris.filter(t => t.some(pt => {
      const py = -pt[2] / FT, pz = pt[1] / FT;
      return py > fasciaY + 0.02 && py < -0.02 && pz > soffitY + 0.005;
    }));
    assert.equal(overhangViolations.length, 0, 'rendered downspout geometry must clear soffit between fascia and wall');
  } finally { disposeTwin(twin); }
});

await test('test_auto_foundation_offset_and_room_footprint_invalidate_memo', async () => {
  // Ruling 1 (I-1): raising foundation.offset_ft from 0 to 2 on an auto-foundation building must move runs & geometry by +2 ft.
  _gutterPlacementStats.clearCache();
  const p1 = house(30, 'hip', rect(0, 0, 30, 20), 1);
  p1.site = { terraces: [{ id: 't1', polygon: rect(-10, -10, 40, 30), height: 1, blend: 2 }] };
  p1.buildings[0].foundation = { mode: 'auto', offset_ft: 0 };
  const twin1 = buildTwin(p1, input.kit, 'high');
  await twin1.ready;
  const callsAfter1 = _gutterPlacementStats.calls;
  const y1Run = twin1.gutters.runs[0].segments[0].a[1] / FT;
  const y1Drawn = Math.max(...gutterTriangles(twin1.root).tris.flat().map(pt => pt[1])) / FT;

  const p2 = clone(p1);
  p2.buildings[0].foundation.offset_ft = 2;
  const twin2 = buildTwin(p2, input.kit, 'high', { previous: twin1 });
  await twin2.ready;
  try {
    assert.equal(_gutterPlacementStats.calls, callsAfter1 + 1, 'foundation.offset_ft edit must miss placement memo');
    const y2Run = twin2.gutters.runs[0].segments[0].a[1] / FT;
    const y2Drawn = Math.max(...gutterTriangles(twin2.root).tris.flat().map(pt => pt[1])) / FT;
    near(y2Run - y1Run, 2.0, 1e-3);
    near(y2Drawn - y1Drawn, 2.0, 0.02);
  } finally { disposeTwin(twin1); disposeTwin(twin2); }

  // Non-porch room polygon edit on an auto-foundation building without level.outline must also invalidate memo.
  _gutterPlacementStats.clearCache();
  const r1 = house(20, 'gable', rect(0, 0, 20, 16), 1);
  delete r1.buildings[0].levels[0].outline;
  r1.buildings[0].rooms = [{ id: 'living', name: 'Living', level: 'L1', polygon: rect(0, 0, 20, 16) }];
  r1.buildings[0].foundation = { mode: 'auto', offset_ft: 0 };
  r1.site = { terraces: [{ id: 't2', polygon: rect(25, -5, 40, 20), height: 2, blend: 0 }] };
  const twA = buildTwin(r1, input.kit, 'high'); await twA.ready;
  const yA = twA.gutters.runs[0].segments[0].a[1] / FT;
  const r2 = clone(r1);
  r2.buildings[0].rooms[0].polygon = rect(0, 0, 30, 16); // overlaps the 2 ft terrace
  const twB = buildTwin(r2, input.kit, 'high', { previous: twA }); await twB.ready;
  try {
    const yB = twB.gutters.runs[0].segments[0].a[1] / FT;
    near(yB - yA, 2.0, 1e-3);
  } finally { disposeTwin(twA); disposeTwin(twB); }
});

await test('test_outlet_blocked_hole_and_spill_no_nan_or_zero_area', async () => {
  // Ruling 4: jammed gutter above lower roof -> outlet-blocked hole collar only (no pipe sweep), short spill, no NaN/zero-area tris.
  _gutterPlacementStats.clearCache();
  const p = house(20, 'gable', rect(0, 0, 20, 16), 1);
  const b = p.buildings[0];
  // Remove y1 gutter so only y0 is tested; place y0 eave at 10 - 0.5 = 9.5 ft right above a lower flat roof at 9.25 ft.
  b.roofs[0].edges[2].gutter = false;
  delete b.roof.sections[0].gutters.y1;
  b.roof.sections[0].plate = 10;
  // Remove walls reaching below y0 so it falls back to hang/stub right over the flat roof at 9.25 ft.
  b.levels[0].elevation = 10;
  b.levels[0].ceiling = 10;
  b.roof.sections[0].plate = 20;
  b.roof.sections[0].pitch = 6; // eave at 20 - 0.5 = 19.5 ft, gutterBottom = 19.083 ft
  // Add a lower flat roof spanning directly underneath y0 at plate 19.2 ft (above gutterBottom -> outlet-blocked!).
  b.roof.sections.push({
    id: 'low', roof: 'low', kind: 'flat', ridge: 'x', pitch: 0, plate: 19.2, overhang: 0, level: 'L1',
    rect: [-4, -8, 24, 0], plane_edges: { y0: 0, x1: 1, y1: 2, x0: 3 },
  });
  b.roofs.push({
    id: 'low', area: rect(-4, -8, 24, 0), overhang: 0,
    edges: [0, 1, 2, 3].map(() => ({ setting: 'gable', gutter: false })),
  });
  const twin = buildTwin(p, input.kit, 'high');
  await twin.ready;
  try {
    const blocked = twin.gutters.spouts.find(s => (s.flags || []).includes('outlet-blocked'));
    assert.ok(blocked, `expected an outlet-blocked spout, got: ${JSON.stringify(twin.gutters.spouts.map(s => s.flags))}`);
    assert.deepEqual(blocked.path[0], blocked.path[1], 'outlet-blocked path has two identical points');

    const { tris } = gutterTriangles(twin.root);
    assert.ok(tris.length > 0, 'gutter + outlet hole geometry emitted');
    for (const tri of tris) {
      for (const pt of tri) assert.ok(pt.every(Number.isFinite), `NaN/Inf vertex found: ${pt}`);
      const a = new THREE.Vector3(...tri[0]), bPt = new THREE.Vector3(...tri[1]), c = new THREE.Vector3(...tri[2]);
      const area = bPt.clone().sub(a).cross(c.clone().sub(a)).length() * 0.5;
      assert.ok(area > 1e-9, `zero-area triangle found (area=${area})`);
    }
    // Outlet hole collar exists right at blocked.top, and NO pipe sweeps down below gutterBottom - 0.04*FT.
    const run = twin.gutters.runs.find(r => r.id === blocked.run);
    const gutterBotM = run.segments[0].a[1] - (G.GUTTER.profileIn / 12) * FT;
    const floorLimit = Math.min(gutterBotM, blocked.top[1]) - 0.04 * FT;
    const nearHole = tris.flat().filter(pt =>
      Math.hypot(pt[0] - blocked.top[0], pt[2] - blocked.top[2]) < 0.15 && Math.abs(pt[1] - blocked.top[1]) < 0.03
    );
    assert.ok(nearHole.length >= 8, `expected outlet hole collar geometry near blocked.top, got ${nearHole.length} verts`);
    const belowHole = tris.flat().filter(pt =>
      Math.hypot(pt[0] - blocked.top[0], pt[2] - blocked.top[2]) < 0.15 && pt[1] < floorLimit
    );
    assert.equal(belowHole.length, 0, 'outlet-blocked must not emit a downward pipe sweep');

    // Pour is a short spill onto the receiving lower roof (finite, positive fall, stays above lower roof).
    const res = E.eaveInstances(p, twin.roofSurfaces, input.kit, twin.gutters);
    const spill = res.pours.find(pr => pr.spout.id === blocked.id);
    assert.ok(spill, 'outlet-blocked emits a short spill pour');
    assert.ok(spill.top.every(Number.isFinite) && Number.isFinite(spill.bottom), 'spill coordinates are finite');
    assert.ok(spill.top[1] > spill.bottom && spill.top[1] - spill.bottom <= 0.6 * FT,
      `spill fall should be short (${((spill.top[1] - spill.bottom) / FT).toFixed(3)} ft)`);
  } finally { disposeTwin(twin); }
});

await test('test_merged_fascia_batch_not_tagged_gutter_at_mesh_level', async () => {
  // M-1: merged fascia + gutter batch must NOT be tagged gutter at mesh level; only gutter snapRanges carry surfaceKind='gutter'.
  const p = house(30, 'gable');
  const twinDef = buildTwin(p, input.kit, 'high');
  await twinDef.ready;
  try {
    let foundMerged = 0;
    twinDef.root.traverse(o => {
      if (!o.isMesh || o.layers.isEnabled(31)) return;
      const ranges = o.userData.snapRanges || [];
      const gutterRanges = ranges.filter(r => r.surfaceKind === 'gutter');
      if (!gutterRanges.length) return;
      foundMerged++;
      const nonGutterRanges = ranges.filter(r => r.surfaceKind !== 'gutter');
      assert.ok(nonGutterRanges.length > 0, 'default gutter merges with fascia/trim batch');
      assert.notEqual(o.userData.surfaceKind, 'gutter', 'merged fascia+gutter mesh must NOT be tagged gutter at mesh level');
    });
    assert.equal(foundMerged, 1, 'found 1 merged fascia+gutter batch');
  } finally { disposeTwin(twinDef); }

  // Custom gutter material lives in its own bucket -> mesh-level tag is allowed because EVERY entry is gutter.
  const pCust = clone(p);
  pCust.buildings[0].materials = { gutter: { id: 'black_metal' } };
  const twinCust = buildTwin(pCust, input.kit, 'high');
  await twinCust.ready;
  try {
    let foundGutterOnly = 0;
    twinCust.root.traverse(o => {
      if (!o.isMesh || o.layers.isEnabled(31)) return;
      const ranges = o.userData.snapRanges || [];
      if (!ranges.some(r => r.surfaceKind === 'gutter')) return;
      foundGutterOnly++;
      assert.ok(ranges.every(r => r.surfaceKind === 'gutter'), 'custom gutter batch contains only gutter ranges');
      assert.equal(o.userData.surfaceKind, 'gutter', 'gutter-only mesh carries mesh-level surfaceKind=gutter');
    });
    assert.equal(foundGutterOnly, 1);
  } finally { disposeTwin(twinCust); }
});

await test('test_gutter_honours_section_and_level_finish_overrides', async () => {
  // M-2: gutters honour per-section and per-level finish overrides just like fascia.
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1);
  const b = p.buildings[0];
  // Add a second level and second roof section on L2.
  b.levels.push({ id: 'L2', elevation: 10, ceiling: 10, outline: rect(0, 0, 14, 20) });
  const l2Poly = rect(0, 0, 14, 20);
  b.walls.push(...l2Poly.map((a, i) => ({
    id: 'w2_' + i, from: a, to: l2Poly[(i + 1) % 4], exterior: true, height: 10, thickness: 0.5, level: 'L2',
  })));
  addRoof(p, 'r2', [0, 0, 14, 20], 'gable', { plate: 20, overhang: 1, level: 'L2' });

  // Case A: per-section override on r2 only.
  const pSec = clone(p);
  pSec.buildings[0].roof.sections[1].materials = { gutter: { id: 'black_metal' } };
  assert.notEqual(
    buildingKey(pSec, pSec.buildings[0], input.kit, 'high'),
    buildingKey(p, p.buildings[0], input.kit, 'high'),
    'per-section gutter material override invalidates buildingKey'
  );
  const twinSec = buildTwin(pSec, input.kit, 'high');
  await twinSec.ready;
  try {
    const { taggedMeshes } = gutterTriangles(twinSec.root);
    const mats = new Set(taggedMeshes.map(m => m.material.color.getHexString()));
    assert.ok(mats.has('1b1c1e'), 'section override applied black_metal to r2 gutters');
    assert.ok(taggedMeshes.some(m => m.material === twinSec.materials.get('trim')), 'r1 gutters still inherit default trim');
  } finally { disposeTwin(twinSec); }

  // Case B: per-level override on L2 only.
  const pLvl = clone(p);
  pLvl.buildings[0].levels[1].materials = { gutter: { id: 'black_metal' } };
  assert.notEqual(
    buildingKey(pLvl, pLvl.buildings[0], input.kit, 'high'),
    buildingKey(p, p.buildings[0], input.kit, 'high'),
    'per-level gutter material override invalidates buildingKey'
  );
  const twinLvl = buildTwin(pLvl, input.kit, 'high');
  await twinLvl.ready;
  try {
    const { taggedMeshes } = gutterTriangles(twinLvl.root);
    const mats = new Set(taggedMeshes.map(m => m.material.color.getHexString()));
    assert.ok(mats.has('1b1c1e'), 'level override applied black_metal to L2 gutters');
    assert.ok(taggedMeshes.some(m => m.material === twinLvl.materials.get('trim')), 'L1 gutters still inherit default trim');
  } finally { disposeTwin(twinLvl); }
});

await test('test_gutter_inner_and_outer_share_lightmap_chart', async () => {
  // M-3: inner and outer gutter faces share one lightmap chart (identical uv3 & lmRoom, halved charts).
  const p = house(30, 'gable', rect(0, 0, 30, 20), 1);
  const twin = buildTwin(p, input.kit, 'high');
  await twin.ready;
  try {
    const atlas = buildAtlas(twin.root, p, { room: { density: 4, page: 2048, gutter: 2 } });
    // Find the merged roof mesh with gutter snapRanges.
    let roofMesh = null;
    twin.root.traverse(o => {
      if (o.isMesh && !o.layers.isEnabled(31) && (o.userData.snapRanges || []).some(r => r.surfaceKind === 'gutter'))
        roofMesh = o;
    });
    assert.ok(roofMesh, 'roof mesh with gutter snapRanges exists');
    const g = roofMesh.geometry;
    const pos = g.attributes.position, uv3 = g.attributes.uv3, lmRoom = g.attributes.lmRoom, lmPage = g.attributes.lmLightPage;
    assert.ok(uv3 && lmRoom && lmPage, 'atlas wrote uv3, lmRoom and lmLightPage');

    const gutterRanges = roofMesh.userData.snapRanges.filter(r => r.surfaceKind === 'gutter');
    const isGutterFace = f => gutterRanges.some(r => f * 3 >= r.start && f * 3 < r.start + r.count);
    const vKey = i => [pos.getX(i), pos.getY(i), pos.getZ(i)].map(x => Math.round(x * 1e4)).join(',');

    // Group gutter triangles by sorted vertex keys to find exact back-to-back outer/inner pairs.
    const byTri = new Map();
    for (let f = 0; f < pos.count / 3; f++) {
      if (!isGutterFace(f)) continue;
      const tk = [vKey(3 * f), vKey(3 * f + 1), vKey(3 * f + 2)].sort().join('|');
      if (!byTri.has(tk)) byTri.set(tk, []);
      byTri.get(tk).push(f);
    }
    let pairedCount = 0;
    for (const group of byTri.values()) {
      if (group.length !== 2) continue;
      pairedCount++;
      const [f0, f1] = group;
      assert.ok(lmRoom.getX(3 * f0) >= 0 && lmRoom.getX(3 * f1) >= 0, 'both faces have valid lmRoom');
      assert.equal(lmRoom.getX(3 * f0), lmRoom.getX(3 * f1), 'inner & outer twins share lmRoom');
      assert.equal(lmPage.getX(3 * f0), lmPage.getX(3 * f1), 'inner & outer twins share lmLightPage');
      // For each shared vertex key, uv3 must match verbatim!
      const uvMap = f => new Map([0, 1, 2].map(k => [vKey(3 * f + k), [uv3.getX(3 * f + k), uv3.getY(3 * f + k)]]));
      const m0 = uvMap(f0), m1 = uvMap(f1);
      for (const [vk, [u0, v0]] of m0) {
        const [u1, v1] = m1.get(vk);
        assert.ok(Math.abs(u0 - u1) < 1e-6 && Math.abs(v0 - v1) < 1e-6, `twin uv3 mismatch: (${u0},${v0}) vs (${u1},${v1})`);
      }
    }
    assert.ok(pairedCount >= 20, `expected >= 20 back-to-back gutter triangle pairs, got ${pairedCount}`);

    // Confirm EVERY back-to-back gutter shell pair has one face in a chart and its twin in proxies (0 extra charts for inner faces).
    const hostFaces = new Set(atlas.room.charts.filter(c => c.mesh === roofMesh).flatMap(c => c.faces));
    const proxyFaces = new Set(atlas.room.charts.flatMap(c => (c.proxies || []).filter(pr => pr.mesh === roofMesh).flatMap(pr => pr.faces)));
    let sharedTwinCharts = 0;
    for (const group of byTri.values()) {
      if (group.length !== 2) continue;
      const [f0, f1] = group;
      // Neither pair may put both faces into chart.faces (which would allocate 2 charts for one thin wall).
      assert.ok(!(hostFaces.has(f0) && hostFaces.has(f1)), `back-to-back gutter faces ${f0},${f1} must not both own separate charts`);
      assert.ok(proxyFaces.has(f0) || proxyFaces.has(f1), `at least one face of back-to-back pair ${f0},${f1} must be a proxy`);
      sharedTwinCharts++;
    }
    assert.equal(sharedTwinCharts, pairedCount, 'every back-to-back gutter triangle pair shares one lightmap chart');
  } finally {
    releaseBakeSource(twin.root);
    disposeTwin(twin);
  }
});

finish();
"""

if __name__ == '__main__':
    os.environ.pop('HA_BASE_URL', None)
    sys.path.insert(0, str(ROOT))
    from services import twin_surface_kinds
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    plan = flatten(assemble(fixture)[0])
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit}, timeout=180)
    print(output)
    # Also verify Python surface kind table has gutter in sync.
    row = next((r for r in twin_surface_kinds.KINDS if r['kind'] == 'gutter'), None)
    assert row is not None, 'gutter missing from services/twin_surface_kinds.py'
    assert row['scope'] == 'building' and row['fallback'] == {'role': 'trim'} and row['item'] is None, row
    sys.exit(1 if code is None else code)
