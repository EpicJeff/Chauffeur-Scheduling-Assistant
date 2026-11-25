"""Closed-in box awning underside/ends geometry and arched brace tests."""
import os
from pathlib import Path
import sys

os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

from twin_editor_dom import PRELUDE, run_node  # noqa: E402

DRIVER = PRELUDE + r"""
const { createHash } = await import('node:crypto');
const THREE = await import('three');
const { prepareUnderside, undersideGeometry, undersideCeilingHeight } = await import(file('static/twin/roof_underside.js'));
const { supportPoints, supportGeometry, supportFrame, roofPoint } = await import(file('static/twin/roof_supports.js'));
const { sectionHeight } = await import(file('static/twin/twin_roof.js'));
const { gutterPlacement } = await import(file('static/twin/gutters.js'));
const { ROOF_THICKNESS, FASCIA } = await import(file('static/twin/trim_dims.js'));
const G = await import(file('static/twin/twin_generator.js'));
const { disposeObject } = await import(file('static/twin/twin_library.js'));
const { releaseBakeSource } = await import(file('static/twin/bake/source.js'));

const rect = (a, b, c, d) => [[a, b], [c, b], [c, d], [a, d]];

function triCount(g) {
  return (g.index ? g.index.count : g.attributes.position.count) / 3;
}

function vertices(g) {
  const pos = g.attributes.position, out = [];
  for (let i = 0; i < pos.count; i++) out.push([pos.getX(i), pos.getY(i), pos.getZ(i)]);
  return out;
}

function inspectSurface(g, label, { closed = false, expectedNormal = null } = {}) {
  for (const name of ['position', 'normal', 'uv']) {
    const a = g.attributes[name];
    assert.ok(a, `${label}: missing ${name}`);
    for (let i = 0; i < a.array.length; i++) assert.ok(Number.isFinite(a.array[i]), `${label}: non-finite ${name}`);
  }
  const pos = g.attributes.position, norm = g.attributes.normal, uv = g.attributes.uv, idx = g.index;
  const count = idx ? idx.count : pos.count;
  assert.ok(count >= 3 && count % 3 === 0, `${label}: valid triangle count (${count})`);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const ab = new THREE.Vector3(), ac = new THREE.Vector3(), faceN = new THREE.Vector3(), vn = new THREE.Vector3();
  let signedVol = 0, minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
  for (let i = 0; i < count; i += 3) {
    const i0 = idx ? idx.getX(i) : i, i1 = idx ? idx.getX(i + 1) : i + 1, i2 = idx ? idx.getX(i + 2) : i + 2;
    a.fromBufferAttribute(pos, i0); b.fromBufferAttribute(pos, i1); c.fromBufferAttribute(pos, i2);
    ab.subVectors(b, a); ac.subVectors(c, a);
    faceN.crossVectors(ab, ac);
    const area2 = faceN.length();
    assert.ok(area2 > 1e-7, `${label}: degenerate triangle at ${i / 3} (area2=${area2})`);
    faceN.divideScalar(area2);
    if (expectedNormal) {
      const dot = faceN.x * expectedNormal[0] + faceN.y * expectedNormal[1] + faceN.z * expectedNormal[2];
      assert.ok(dot > 0.99, `${label}: face normal [${faceN.toArray()}] mismatches expected [${expectedNormal}] (dot=${dot})`);
    }
    for (const k of [i0, i1, i2]) {
      vn.fromBufferAttribute(norm, k);
      const len = vn.length();
      assert.ok(Math.abs(len - 1) < 1e-3, `${label}: non-unit normal (${len})`);
      assert.ok(vn.dot(faceN) > 0.2, `${label}: normal opposes winding (${vn.dot(faceN)})`);
      minU = Math.min(minU, uv.getX(k)); maxU = Math.max(maxU, uv.getX(k));
      minV = Math.min(minV, uv.getY(k)); maxV = Math.max(maxV, uv.getY(k));
    }
    signedVol += a.dot(b.clone().cross(c)) / 6;
  }
  if (closed) assert.ok(signedVol > 1e-6, `${label}: closed outward volume (${signedVol})`);
  return { triangles: count / 3, signedVol, uvSpan: [maxU - minU, maxV - minV] };
}

function hashRoot(root) {
  root.updateMatrixWorld(true);
  const rows = [];
  root.traverse(o => {
    if (!o.isMesh || o.layers.isEnabled(31)) return;
    const h = a => a ? createHash('sha256').update(new Uint8Array(a.buffer, a.byteOffset, a.byteLength)).digest('hex') : null;
    const g = o.geometry;
    rows.push([
      o.parent?.name || '', o.material?.name || '', o.material?.color?.getHexString?.() || '',
      h(g.attributes.position?.array), h(g.attributes.normal?.array), h(g.attributes.uv?.array), h(g.index?.array),
    ]);
  });
  return createHash('sha256').update(JSON.stringify(rows)).digest('hex');
}

function kit() {
  return {
    materials: Object.fromEntries(['floor', 'patio_concrete', 'siding', 'interior_wall', 'roof', 'trim',
      'window_frame', 'door', 'porch_ceiling', 'base', 'lattice', 'counter', 'stainless', 'lawn', 'paving', 'ceiling']
      .map(k => [k, { asset: k, color: '#bbccee' }])),
    manifest: {},
  };
}

function makeAwning(extra = {}) {
  const area = extra.area || rect(0, 0, 10, 4);
  const box = extra.rect || [
    Math.min(...area.map(p => p[0])), Math.min(...area.map(p => p[1])),
    Math.max(...area.map(p => p[0])), Math.max(...area.map(p => p[1])),
  ];
  return {
    id: 'aw-box', roof: 'aw-box', level: 'L1', kind: 'shed',
    low_side: 'y0', pitch: 3, plate: 7.5, overhang: 0, thickness_ft: 0.3, fascia: true,
    area, rect: box,
    edges: area.map((_, i) => ({ setting: i === 0 ? 'sloped' : 'gable', pitch: 3, overhang_ft: 0 })),
    host: { wall: 'w0', edge: 2 },
    support: { kind: 'brace', style: 'arched', count: 2, inset_ft: 0.8 },
    ...extra,
  };
}

function housePlan(awnings = [], { withFootprint = false } = {}) {
  const outline = rect(0, 0, 40, 20);
  const walls = outline.map((from, i) => {
    const to = outline[(i + 1) % 4];
    const w = { id: 'w' + i, from, to, level: 'L1', height: 11, thickness: 0.5, exterior: true };
    if (withFootprint) {
      const dx = to[0] - from[0], dy = to[1] - from[1], len = Math.hypot(dx, dy);
      const nx = dy / len * 0.25, ny = -dx / len * 0.25;
      w.footprint = [
        [from[0] + nx, from[1] + ny], [to[0] + nx, to[1] + ny],
        [to[0] - nx, to[1] - ny], [from[0] - nx, from[1] - ny],
      ];
    }
    return w;
  });
  return {
    schema: 2, units: 'ft', materials: {}, site: {},
    buildings: [{
      id: 'b', position: [0, 0], base: 0, rotation: 0,
      levels: [{ id: 'L1', elevation: 0, ceiling: 11, outline }],
      walls,
      rooms: [{ id: 'r0', level: 'L1', polygon: outline, state: 'settled' }],
      openings: [], porches: [], lights: [], fixtures: [], stairs: [], items: [], anchors: [],
      roof: {
        sections: [
          { id: 'main', roof: 'main', level: 'L1', kind: 'gable', ridge: 'x', rect: [0, 0, 40, 20], plate: 11, pitch: 4, overhang: 1 },
          ...awnings,
        ],
        extensions: [], flags: [],
      },
      roofs: [],
    }],
  };
}

function pointOnTri2D(p, a, b, c) {
  const v0x = c[0] - a[0], v0y = c[1] - a[1];
  const v1x = b[0] - a[0], v1y = b[1] - a[1];
  const v2x = p[0] - a[0], v2y = p[1] - a[1];
  const d00 = v0x * v0x + v0y * v0y, d01 = v0x * v1x + v0y * v1y, d02 = v0x * v2x + v0y * v2y;
  const d11 = v1x * v1x + v1y * v1y, d12 = v1x * v2x + v1y * v2y;
  const inv = d00 * d11 - d01 * d01;
  if (Math.abs(inv) < 1e-12) return false;
  const u = (d11 * d02 - d01 * d12) / inv, v = (d00 * d12 - d01 * d02) / inv;
  return u > 1e-4 && v > 1e-4 && u + v < 1 - 1e-4;
}

function coplanarOverlapCount(geoA, geoB) {
  const tris = g => {
    const p = g.attributes.position, idx = g.index, n = idx ? idx.count : p.count, out = [];
    for (let i = 0; i < n; i += 3) {
      const pts = [0, 1, 2].map(k => {
        const j = idx ? idx.getX(i + k) : i + k;
        return new THREE.Vector3(p.getX(j), p.getY(j), p.getZ(j));
      });
      const norm = new THREE.Vector3().crossVectors(pts[1].clone().sub(pts[0]), pts[2].clone().sub(pts[0]));
      const area2 = norm.length();
      if (area2 < 1e-8) continue;
      norm.divideScalar(area2);
      const d = norm.dot(pts[0]);
      out.push({ pts, norm, d });
    }
    return out;
  };
  const ta = tris(geoA), tb = tris(geoB);
  let overlaps = 0;
  for (const a of ta) for (const b of tb) {
    if (Math.abs(a.norm.dot(b.norm)) < 0.999) continue;
    const sign = a.norm.dot(b.norm) > 0 ? 1 : -1;
    if (Math.abs(a.d - sign * b.d) > 1e-4) continue;
    // Project onto dominant plane and test interior centroids + edge midpoints
    const ax = Math.abs(a.norm.x), ay = Math.abs(a.norm.y), az = Math.abs(a.norm.z);
    const proj = v => ax >= ay && ax >= az ? [v.y, v.z] : ay >= az ? [v.x, v.z] : [v.x, v.y];
    const pa = a.pts.map(proj), pb = b.pts.map(proj);
    const centA = [(pa[0][0] + pa[1][0] + pa[2][0]) / 3, (pa[0][1] + pa[1][1] + pa[2][1]) / 3];
    const centB = [(pb[0][0] + pb[1][0] + pb[2][0]) / 3, (pb[0][1] + pb[1][1] + pb[2][1]) / 3];
    if (pointOnTri2D(centA, pb[0], pb[1], pb[2]) || pointOnTri2D(centB, pa[0], pa[1], pa[2])) overlaps++;
  }
  return overlaps;
}

await test('absent_fields_byte_identical_hash', async () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 11 };
  // Walled roof or absent/exposed fields produce []
  assert.deepEqual(undersideGeometry({ id: 'w', kind: 'shed', low_side: 'y0', pitch: 3, plate: 8, rect: [0, 0, 10, 4] }, ctx), []);
  assert.deepEqual(undersideGeometry(makeAwning(), ctx), []);
  assert.deepEqual(undersideGeometry(makeAwning({ ends: {}, underside: { kind: 'exposed' } }), ctx), []);

  // Full generator build: absent fields vs explicit exposed + empty ends must be byte-identical
  const awBase = makeAwning({ area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0], support: { kind: 'brace', count: 2, inset_ft: 0.8 } });
  const awExposed = makeAwning({
    area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0],
    support: { kind: 'brace', count: 2, inset_ft: 0.8 },
    ends: {}, underside: { kind: 'exposed' },
  });
  const outA = G.buildTwin(housePlan([awBase]), kit(), 'high', { viewing: true });
  await outA.ready;
  const hA = hashRoot(outA.root);
  const outB = G.buildTwin(housePlan([awExposed]), kit(), 'high', { viewing: true });
  await outB.ready;
  const hB = hashRoot(outB.root);
  assert.equal(hB, hA, 'explicit exposed + empty ends is byte-identical to absent fields');
  for (const o of [outA, outB]) { releaseBakeSource(o.root); disposeObject(o.root); }
});

await test('shed_gable_flat_and_all_four_host_sides', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };

  // 1. Shed across all 4 host sides with flat drop 0.5 and both ends closed
  const sides = [
    { edge: 0, low_side: 'y1', eaveN: [0, 0, -1], endIndices: [1, 3] },
    { edge: 1, low_side: 'x0', eaveN: [-1, 0, 0], endIndices: [0, 2] },
    { edge: 2, low_side: 'y0', eaveN: [0, 0, 1],  endIndices: [1, 3] },
    { edge: 3, low_side: 'x1', eaveN: [1, 0, 0],  endIndices: [0, 2] },
  ];
  for (const { edge, low_side, eaveN, endIndices } of sides) {
    const area = rect(0, 0, 10, 4);
    const ends = Object.fromEntries(endIndices.map(i => [String(i), 'closed']));
    const roof = makeAwning({
      area, rect: [0, 0, 10, 4], low_side, pitch: 3, plate: 7.5, thickness_ft: 0.3,
      host: { wall: 'w' + edge, edge },
      edges: area.map((_, i) => ({ setting: i === (edge + 2) % 4 ? 'sloped' : 'gable', pitch: 3, overhang_ft: 0 })),
      ends, underside: { kind: 'flat', drop_ft: 0.5 },
    });
    const parts = undersideGeometry(roof, ctx);
    const byPart = Object.fromEntries(parts.map(p => [p.part, p]));
    assert.ok(byPart['underside'], `shed side ${edge}: underside present`);
    assert.equal(byPart['underside'].slot, 'underside');
    const ceilInfo = inspectSurface(byPart['underside'].geometry, `shed-${edge}-ceil`, { expectedNormal: [0, -1, 0] });
    assert.ok(Math.max(...ceilInfo.uvSpan) >= 9.5, 'ceiling UVs in feet');
    const ceilYs = vertices(byPart['underside'].geometry).map(v => v[1]);
    assert.ok(ceilYs.every(y => Math.abs(y - (7.5 - 0.3 - 0.5)) < 1e-4), `shed side ${edge}: ceiling at 6.7`);

    assert.ok(byPart['underside:front'], `shed side ${edge}: underside:front present`);
    assert.equal(byPart['underside:front'].slot, 'fascia');
    inspectSurface(byPart['underside:front'].geometry, `shed-${edge}-front`, { expectedNormal: eaveN });

    for (const ei of endIndices) {
      const endParts = parts.filter(p => p.part === `end:${ei}`);
      assert.ok(endParts.length >= 1, `shed side ${edge}: end:${ei} present`);
      assert.ok(endParts.some(p => p.slot === 'fascia'), `shed side ${edge}: end:${ei} has fascia frame`);
      const totalEndTris = endParts.reduce((n, p) => n + triCount(p.geometry), 0);
      assert.ok(totalEndTris <= 60, `shed side ${edge}: end:${ei} ${totalEndTris} <= 60 tris`);
      for (const ep of endParts) inspectSurface(ep.geometry, `shed-${edge}-end-${ei}-${ep.slot}`);
    }
  }

  // 2. Gable roof (ridge 'y', host edge 2): front gable end is edge 0 (siding), eaves are edges 1 & 3
  const gable = makeAwning({
    kind: 'gable', ridge: 'y', low_side: undefined, pitch: 6, plate: 7.5, thickness_ft: 0.3,
    area: rect(0, 0, 10, 4), rect: [0, 0, 10, 4],
    host: { wall: 'w2', edge: 2 },
    edges: [0, 1, 2, 3].map(i => ({ setting: (i === 1 || i === 3) ? 'sloped' : 'gable', pitch: 6, overhang_ft: 0 })),
    ends: { '0': 'closed', '1': 'closed', '2': 'closed' }, // 1 is sloped eave (ignored), 2 is host (ignored)
    underside: { kind: 'flat', drop_ft: 0.5 },
  });
  const gParts = undersideGeometry(gable, ctx);
  const gByPart = Object.fromEntries(gParts.map(p => [p.part, p]));
  assert.ok(gByPart['underside'], 'gable: ceiling present');
  assert.ok(gByPart['underside:front'], 'gable: front along both eaves present');
  assert.ok(gByPart['end:0'], 'gable: front gable end present');
  assert.equal(gByPart['end:0'].slot, 'siding', 'gable end uses siding slot');
  assert.ok(!gByPart['end:1'], 'gable: sloped eave edge ignored in ends');
  assert.ok(!gByPart['end:2'], 'gable: host edge ignored in ends');
  inspectSurface(gByPart['end:0'].geometry, 'gable-end-0', { expectedNormal: [0, 0, 1] });
  // Peak of gable end should reach plate + (span/2)*(6/12) - thickness = 7.5 + 2.5 - 0.3 = 9.7
  const gEndMaxY = Math.max(...vertices(gByPart['end:0'].geometry).map(v => v[1]));
  assert.ok(Math.abs(gEndMaxY - 9.7) < 1e-4, `gable end peak reaches 9.7 (got ${gEndMaxY})`);

  // 3. Flat roof with drop 0.5 and closed ends
  const flat = makeAwning({
    kind: 'flat', low_side: undefined, pitch: 0, plate: 7.8, thickness_ft: 0.3,
    area: rect(0, 0, 10, 4), rect: [0, 0, 10, 4],
    host: { wall: 'w2', edge: 2 },
    edges: [0, 1, 2, 3].map(() => ({ setting: 'gable', pitch: 0, overhang_ft: 0 })),
    ends: { '1': 'closed', '3': 'closed' },
    underside: { kind: 'flat', drop_ft: 0.5 },
  });
  const fParts = undersideGeometry(flat, ctx);
  const fByPart = Object.fromEntries(fParts.map(p => [p.part, p]));
  assert.ok(fByPart['underside'], 'flat: ceiling present');
  assert.ok(fByPart['underside:front'], 'flat: front present for drop 0.5');
  assert.ok(fByPart['end:1'] && fByPart['end:3'], 'flat: both closed ends present');
  inspectSurface(fByPart['underside'].geometry, 'flat-ceil', { expectedNormal: [0, -1, 0] });
  inspectSurface(fByPart['underside:front'].geometry, 'flat-front', { expectedNormal: [0, 0, 1] });
  inspectSurface(fByPart['end:1'].geometry, 'flat-end-1', { expectedNormal: [1, 0, 0] });
  inspectSurface(fByPart['end:3'].geometry, 'flat-end-3', { expectedNormal: [-1, 0, 0] });
});

await test('drop_0_0_5_3_and_closed_one_both_none_and_exposed_ends', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  // Drop 0, 0.5, 3
  for (const drop of [0, 0.5, 3]) {
    const roof = makeAwning({
      ends: { '1': 'closed', '3': 'closed' },
      underside: { kind: 'flat', drop_ft: drop },
    });
    const parts = undersideGeometry(roof, ctx);
    const byPart = Object.fromEntries(parts.map(p => [p.part, p]));
    assert.ok(byPart['underside'], `drop=${drop}: ceiling present`);
    const expectedY = 7.5 - 0.3 - drop;
    const ys = vertices(byPart['underside'].geometry).map(v => v[1]);
    assert.ok(ys.every(y => Math.abs(y - expectedY) < 1e-4), `drop=${drop}: ceiling at ${expectedY}`);
    if (drop === 0) {
      assert.ok(!byPart['underside:front'], 'drop=0: no underside:front');
    } else {
      assert.ok(byPart['underside:front'], `drop=${drop}: underside:front present`);
      const fYs = vertices(byPart['underside:front'].geometry).map(v => v[1]);
      assert.ok(Math.abs(Math.min(...fYs) - expectedY) < 1e-4, `drop=${drop}: front reaches ceiling ${expectedY}`);
      assert.ok(Math.max(...fYs) >= 7.5 - FASCIA.depthFt - 1e-4, `drop=${drop}: front meets fascia bottom / miter top`);
    }
  }
  // Drop clamps at 3
  assert.ok(Math.abs(undersideCeilingHeight(makeAwning({ underside: { kind: 'flat', drop_ft: 8 } }), ctx) - (7.5 - 0.3 - 3)) < 1e-4);

  // Closed on no ends, one end, both ends
  for (const [label, ends, expectEnds] of [
    ['none', {}, []],
    ['one', { '1': 'closed' }, ['end:1']],
    ['both', { '1': 'closed', '3': 'closed' }, ['end:1', 'end:3']],
  ]) {
    const parts = undersideGeometry(makeAwning({ ends, underside: { kind: 'flat', drop_ft: 0.5 } }), ctx);
    const endNames = [...new Set(parts.filter(p => p.part.startsWith('end:')).map(p => p.part))].sort();
    assert.deepEqual(endNames, expectEnds, `ends=${label}`);
  }

  // Exposed underside with closed ends: ends reach down to lowest eave level, no ceiling/front
  const expParts = undersideGeometry(makeAwning({ ends: { '1': 'closed', '3': 'closed' }, underside: { kind: 'exposed' } }), ctx);
  assert.deepEqual([...new Set(expParts.map(p => p.part))].sort(), ['end:1', 'end:3'], 'exposed with closed ends emits only ends');
  for (const ei of ['1', '3']) {
    const grp = expParts.filter(p => p.part === `end:${ei}`);
    const allYs = grp.flatMap(p => vertices(p.geometry).map(v => v[1]));
    for (const p of grp) inspectSurface(p.geometry, 'exposed-' + p.part + '-' + p.slot);
    assert.ok(Math.abs(Math.min(...allYs) - (7.5 - 0.3)) < 1e-4, 'exposed end bottom at lowest eave slab underside');
    assert.ok(Math.max(...allYs) >= 7.5 + 4 * 0.25 - FASCIA.depthFt - 1e-4, 'exposed end reaches slab underside / rake top');
  }
});

await test('rotated_frame_concave_area_per_edge_overhang_and_wall_face_stop', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12, wallFaceAt: () => 0.25 };

  // 1. Rotated roof_frame
  const angle = 0.65;
  const rotRoof = makeAwning({
    roof_frame: { origin: [5, 2], angle },
    ends: { '1': 'closed', '3': 'closed' },
    underside: { kind: 'flat', drop_ft: 0.5 },
  });
  const rParts = undersideGeometry(rotRoof, ctx);
  const rByPart = Object.fromEntries(rParts.map(p => [p.part, p]));
  inspectSurface(rByPart['underside'].geometry, 'rot-ceil', { expectedNormal: [0, -1, 0] });
  const rotFrontPlanN = [Math.sin(angle), -Math.cos(angle)]; // rotated (0, -1)
  inspectSurface(rByPart['underside:front'].geometry, 'rot-front', { expectedNormal: [rotFrontPlanN[0], 0, -rotFrontPlanN[1]] });
  for (const p of rParts) inspectSurface(p.geometry, 'rot-' + p.part);

  // 2. Per-edge overhang + wallFaceAt stops ceiling & ends at wall exterior face (y = 4 - 0.25 = 3.75)
  const ohRoof = makeAwning({
    overhang: 0,
    edges: [
      { setting: 'sloped', pitch: 3, overhang_ft: 0.6 },
      { setting: 'gable', pitch: 3, overhang_ft: 0.4 },
      { setting: 'gable', pitch: 3, overhang_ft: 0.0 },
      { setting: 'gable', pitch: 3, overhang_ft: 0.2 },
    ],
    ends: { '1': 'closed', '3': 'closed' },
    underside: { kind: 'flat', drop_ft: 0.5 },
  });
  const ohParts = undersideGeometry(ohRoof, ctx);
  const ceilPts = vertices(ohParts.find(p => p.part === 'underside').geometry);
  const minX = Math.min(...ceilPts.map(v => v[0])), maxX = Math.max(...ceilPts.map(v => v[0]));
  const planYs = ceilPts.map(v => -v[2]);
  assert.ok(Math.abs(minX - (-0.2 - FASCIA.proudFt)) < 1e-4, `ceiling includes left overhang + framed end fascia plane (got ${minX})`);
  assert.ok(Math.abs(maxX - (10.4 + FASCIA.proudFt)) < 1e-4, `ceiling includes right overhang + framed end fascia plane (got ${maxX})`);
  assert.ok(Math.abs(Math.max(...planYs) - 3.75) < 1e-4, `ceiling stops at wall face y=3.75 (got ${Math.max(...planYs)})`);
  assert.ok(Math.abs(Math.min(...planYs) - (-0.6 - FASCIA.proudFt)) < 1e-4, `ceiling includes front overhang + fascia plane (got ${Math.min(...planYs)})`);
  // Lowest slab underside at y = -0.6: plate 7.5 - 0.6*(3/12) - 0.3 = 7.05; drop 0.5 -> ceiling 6.55
  assert.ok(Math.abs(ceilPts[0][1] - 6.55) < 1e-4, `ceiling reflects overhang slope drop (6.55 vs ${ceilPts[0][1]})`);

  // 3. Concave L-shaped area
  const lArea = [[0, 0], [8, 0], [8, 4], [20, 4], [20, 10], [0, 10]];
  const lRoof = makeAwning({
    area: lArea, rect: [0, 0, 20, 10], low_side: 'y1', pitch: 2, plate: 7.5, thickness_ft: 0.3,
    host: { wall: 'w0', edge: 0 },
    edges: lArea.map((_, i) => ({ setting: i === 4 ? 'sloped' : 'gable', pitch: 2, overhang_ft: 0 })),
    ends: { '3': 'closed', '5': 'closed' },
    underside: { kind: 'flat', drop_ft: 0.5 },
  });
  const lParts = undersideGeometry(lRoof, { THREE, groundAt: () => 0, wallTopAt: () => 12 });
  assert.ok(lParts.find(p => p.part === 'underside'), 'concave: ceiling present');
  assert.ok(lParts.find(p => p.part === 'underside:front'), 'concave: front present');
  assert.ok(lParts.find(p => p.part === 'end:3') && lParts.find(p => p.part === 'end:5'), 'concave: closed ends present');
  for (const p of lParts) inspectSurface(p.geometry, 'concave-' + p.part);
});

await test('watertight_corners_and_no_coplanar_overlap_in_generator', async () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 11 };
  // Test watertight corners between ceiling, front, and closed ends for both fascia:true and fascia:false
  for (const fascia of [true, false]) {
    const roof = makeAwning({
      fascia, thickness_ft: 0.3,
      ends: { '1': 'closed', '3': 'closed' },
      underside: { kind: 'flat', drop_ft: 0.5 },
    });
    const parts = undersideGeometry(roof, ctx);
    const ceilV = vertices(parts.find(p => p.part === 'underside').geometry);
    const frontV = vertices(parts.find(p => p.part === 'underside:front').geometry);
    const end1V = parts.filter(p => p.part === 'end:1').flatMap(p => vertices(p.geometry));
    const end3V = parts.filter(p => p.part === 'end:3').flatMap(p => vertices(p.geometry));

    const minDist = (listA, listB) => {
      let best = Infinity;
      for (const a of listA) for (const b of listB) {
        const d = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
        if (d < best) best = d;
      }
      return best;
    };
    assert.ok(minDist(ceilV, frontV) <= 0.01, `fascia=${fascia}: ceiling-front corner gap <= 0.01`);
    assert.ok(minDist(ceilV, end1V) <= 0.01, `fascia=${fascia}: ceiling-end1 corner gap <= 0.01`);
    assert.ok(minDist(ceilV, end3V) <= 0.01, `fascia=${fascia}: ceiling-end3 corner gap <= 0.01`);
    assert.ok(minDist(frontV, end1V) <= 0.01, `fascia=${fascia}: front-end1 corner gap <= 0.01`);
    assert.ok(minDist(frontV, end3V) <= 0.01, `fascia=${fascia}: front-end3 corner gap <= 0.01`);

    // Check every front bottom corner vertex is matched within 0.01 by ceiling and corresponding end
    const ceilY = Math.min(...ceilV.map(v => v[1]));
    for (const v of frontV.filter(p => Math.abs(p[1] - ceilY) < 1e-4)) {
      assert.ok(minDist([v], ceilV) <= 0.01, `fascia=${fascia}: front bottom corner touches ceiling`);
      const side = v[0] > 5 ? end1V : end3V;
      assert.ok(minDist([v], side) <= 0.01, `fascia=${fascia}: front bottom corner touches end`);
    }
  }

  // Full buildTwin coplanar overlap checks:
  // A) Shed box awning (drop 0.5, fascia:true, closed both ends)
  // B) Flat box awning (drop 0, fascia:true AND fascia:false) -> must NOT overlap slab underside!
  for (const [label, aw] of [
    ['shed_drop_0_5', makeAwning({
      id: 'aw-1', roof: 'aw-1', area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0],
      ends: { '1': 'closed', '3': 'closed' }, underside: { kind: 'flat', drop_ft: 0.5 },
    })],
    ['flat_drop_0_fascia', makeAwning({
      id: 'aw-2', roof: 'aw-2', kind: 'flat', low_side: undefined, pitch: 0, fascia: true,
      area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0],
      edges: [0, 1, 2, 3].map(() => ({ setting: 'gable', pitch: 0, overhang_ft: 0 })),
      underside: { kind: 'flat', drop_ft: 0 },
    })],
    ['flat_drop_0_bare', makeAwning({
      id: 'aw-3', roof: 'aw-3', kind: 'flat', low_side: undefined, pitch: 0, fascia: false,
      area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0],
      edges: [0, 1, 2, 3].map(() => ({ setting: 'gable', pitch: 0, overhang_ft: 0 })),
      underside: { kind: 'flat', drop_ft: 0 },
    })],
  ]) {
    const out = G.buildTwin(housePlan([aw], { withFootprint: true }), kit(), 'high', { viewing: true });
    await out.ready;
    const pick = out.pickObjects.get('b:' + aw.id);
    assert.ok(pick, `${label}: pickable`);
    const parts = (pick.userData.partObjects || []).map(p => p.object);
    const boxParts = parts.filter(o => ['underside', 'underside:front'].includes(o.userData.part) || (o.userData.part || '').startsWith('end:'));
    assert.ok(boxParts.length >= 1, `${label}: box parts tagged on pick proxy`);
    // Check no coplanar overlap between any box part and any other mesh of the same awning
    const otherMeshes = [];
    out.root.traverse(o => {
      if (!o.isMesh || o.layers.isEnabled(31)) return;
      if (o.parent?.userData?.supportedRoof) otherMeshes.push(o);
    });
    for (let i = 0; i < boxParts.length; i++) {
      for (let j = i + 1; j < boxParts.length; j++) {
        assert.equal(coplanarOverlapCount(boxParts[i].geometry, boxParts[j].geometry), 0,
          `${label}: no overlap between ${boxParts[i].userData.part} and ${boxParts[j].userData.part}`);
      }
    }
    // Also check flat drop 0 has no duplicate coplanar underside triangles inside the merged supported group
    if (label.startsWith('flat_drop_0')) {
      const ceilY = 7.5 - 0.3;
      let downTrisAtCeil = 0;
      for (const m of otherMeshes) {
        const p = m.geometry.attributes.position, n = m.geometry.attributes.normal;
        for (let i = 0; i < p.count; i += 3) {
          if (n.getY(i) < -0.9 && Math.abs(p.getY(i) - ceilY) < 1e-3) downTrisAtCeil++;
        }
      }
      assert.equal(downTrisAtCeil, 2, `${label}: exactly 2 downward triangles at ceiling (no duplicate slab underside), got ${downTrisAtCeil}`);
    }
    releaseBakeSource(out.root); disposeObject(out.root);
  }
});

await test('support_contact_with_ceiling_cable_on_top_and_not_rain_cover', async () => {
  // Build one house with 4 box awnings (arched brace, plain brace, post, cable) with flat ceiling drop 0.5
  const kinds = [
    { id: 'aw-arched', x0: 2, x1: 10, support: { kind: 'brace', style: 'arched', count: 2, inset_ft: 0.8 } },
    { id: 'aw-corbel', x0: 12, x1: 20, support: { kind: 'corbel', style: 'scroll', count: 2, inset_ft: 0.8 } },
    { id: 'aw-post',   x0: 22, x1: 30, support: { kind: 'post', count: 2, inset_ft: 0.8 } },
    { id: 'aw-cable',  x0: 32, x1: 38, support: { kind: 'cable', count: 2, inset_ft: 0.8 } },
  ];
  const makeList = withBox => kinds.map(k => makeAwning({
    id: k.id, roof: k.id,
    area: rect(k.x0, -3.5, k.x1, 0), rect: [k.x0, -3.5, k.x1, 0],
    plate: 7.5, pitch: 3, thickness_ft: 0.3, fascia: true,
    support: k.support,
    ...(withBox ? { ends: { '1': 'closed', '3': 'closed' }, underside: { kind: 'flat', drop_ft: 0.5 } } : {}),
  }));

  const outPlain = G.buildTwin(housePlan(makeList(false), { withFootprint: true }), kit(), 'high', { viewing: true });
  await outPlain.ready;
  const outBox = G.buildTwin(housePlan(makeList(true), { withFootprint: true }), kit(), 'high', { viewing: true });
  await outBox.ready;

  const ceilingY = 7.5 - 0.3 - 0.5; // 6.7
  // Arched brace, corbel, and post tops must seat at ceilingY (6.7), NOT up at the sloped slab (7.2..8.075)
  for (const id of ['aw-arched', 'aw-corbel', 'aw-post']) {
    const pick = outBox.pickObjects.get('b:' + id);
    const sup = (pick.userData.partObjects || []).find(p => p.object.userData.part === 'support:0');
    assert.ok(sup, `${id}: support:0 present`);
    const maxY = Math.max(...vertices(sup.object.geometry).map(v => v[1]));
    assert.ok(Math.abs(maxY - ceilingY) <= 0.02, `${id}: support top touches flat ceiling ${ceilingY} (got ${maxY})`);
  }
  // Cable must still attach on TOP of the roof slab (eave top 7.5, wall top 8.375, anchor > 8.375)
  const cablePick = outBox.pickObjects.get('b:aw-cable');
  const cableSup = (cablePick.userData.partObjects || []).find(p => p.object.userData.part === 'support:0');
  const cableYs = vertices(cableSup.object.geometry).map(v => v[1]);
  assert.ok(Math.min(...cableYs) >= 7.45, `cable stays on top of slab (minY=${Math.min(...cableYs)})`);
  assert.ok(Math.max(...cableYs) > 8.5, `cable wall anchor above slab top (maxY=${Math.max(...cableYs)})`);

  // Rain cover: coverPositions must be identical with vs without box underside/ends!
  const covPlain = outPlain.roofSurfaces.get('b').coverPositions;
  const covBox = outBox.roofSurfaces.get('b').coverPositions;
  assert.equal(covBox.length, covPlain.length, `rain cover triangle count unchanged (${covBox.length} vs ${covPlain.length})`);
  assert.deepEqual(Array.from(covBox), Array.from(covPlain), 'underside and closed ends are not captured as rain cover');

  // Draws: merged into existing supported group per level & material (0 extra draws since roof, fascia/trim, soffit already exist)
  const countSupportedDraws = root => {
    let draws = 0;
    root.traverseVisible(m => {
      if (!m.isMesh || m.layers.isEnabled(31)) return;
      if (m.parent?.userData?.supportedRoof) draws++;
    });
    return draws;
  };
  assert.ok(countSupportedDraws(outBox.root) <= countSupportedDraws(outPlain.root) + 1,
    `at most 1 added draw per level (${countSupportedDraws(outBox.root)} vs ${countSupportedDraws(outPlain.root)})`);

  for (const o of [outPlain, outBox]) { releaseBakeSource(o.root); disposeObject(o.root); }
});

await test('arched_brace_limits_contact_and_plain_brace_unchanged', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };

  // Plain brace baseline stability check
  const plainRoof = makeAwning({ support: { kind: 'brace', count: 2, inset_ft: 0.8 } });
  const plainParts = supportGeometry(plainRoof, supportPoints(plainRoof), ctx);
  assert.equal(plainParts.length, 2);
  assert.equal(triCount(plainParts[0].geometry), 36, 'plain brace stays 36 tris (3 hexahedra)');
  inspectSurface(plainParts[0].geometry, 'plain-brace', { closed: true });

  // Arched brace: default size 0.45 ft, <= 160 tris, closed manifold, UVs in feet, contact on flat ceiling and sloped slab
  for (const [label, extra, ceilingAt] of [
    ['sloped_default', {}, null],
    ['flat_ceiling_0_5', { underside: { kind: 'flat', drop_ft: 0.5 } }, 6.7],
    ['rotated', { roof_frame: { origin: [5, 2], angle: 0.65 } }, null],
  ]) {
    const roof = makeAwning({ support: { kind: 'brace', style: 'arched', count: 2, inset_ft: 0.8 }, ...extra });
    const runCtx = ceilingAt !== null ? { ...ctx, slabBottomAt: () => ceilingAt } : ctx;
    const parts = supportGeometry(roof, supportPoints(roof), runCtx);
    assert.equal(parts.length, 2, `${label}: 2 arched brackets`);
    for (const part of parts) {
      const info = inspectSurface(part.geometry, `arched-${label}`, { closed: true });
      assert.ok(info.triangles <= 160, `${label}: ${info.triangles} <= 160 triangles`);
      assert.ok(Math.max(...info.uvSpan) > 1.2, `${label}: UVs in feet`);
      const { origin, outward, tangent } = supportFrame(roof);
      const pts = vertices(part.geometry);
      const us = pts.map(([vx, , vz]) => (vx - origin[0]) * tangent[0] + (-vz - origin[1]) * tangent[1]);
      const ws = pts.map(([vx, , vz]) => (vx - origin[0]) * outward[0] + (-vz - origin[1]) * outward[1]);
      const width = Math.max(...us) - Math.min(...us);
      assert.ok(Math.abs(width - 0.45) < 0.02, `${label}: default arched brace width ~0.45 ft (got ${width})`);
      assert.ok(Math.min(...ws) <= 0.02 && Math.min(...ws) >= -0.02, `${label}: touches wall w=0 (got ${Math.min(...ws)})`);
      let minGap = Infinity, maxPen = -Infinity;
      const { depth } = supportFrame(roof);
      for (const [vx, vy, vz] of pts) {
        const px = vx, py = -vz;
        const rawTop = sectionHeight(roof, px, py);
        const w = (px - origin[0]) * outward[0] + (py - origin[1]) * outward[1];
        const top = rawTop !== null ? rawTop : roof.plate + (depth - w) * ((roof.pitch || 0) / 12);
        const bot = ceilingAt !== null ? ceilingAt : (top - roof.thickness_ft);
        minGap = Math.min(minGap, Math.abs(vy - bot));
        maxPen = Math.max(maxPen, vy - bot);
      }
      assert.ok(minGap <= 0.02, `${label}: touches surface above within 0.02 ft (got ${minGap})`);
      assert.ok(maxPen <= 0.02, `${label}: never penetrates above (got ${maxPen})`);
    }
  }

  // All 4 host sides for arched brace
  for (const [edge, low_side] of [[0, 'y1'], [1, 'x0'], [2, 'y0'], [3, 'x1']]) {
    const roof = makeAwning({
      area: rect(0, 0, 10, 6), rect: [0, 0, 10, 6], low_side,
      host: { wall: 'w' + edge, edge },
      support: { kind: 'brace', style: 'arched', count: 2, inset_ft: 0.8 },
    });
    const parts = supportGeometry(roof, supportPoints(roof), ctx);
    assert.equal(parts.length, 2);
    for (const part of parts) {
      const info = inspectSurface(part.geometry, `arched-side-${edge}`, { closed: true });
      assert.ok(info.triangles <= 160);
    }
  }
  console.log('ARCHED_BRACE_TRIS ' + triCount(supportGeometry(
    makeAwning({ support: { kind: 'brace', style: 'arched', count: 1 } }),
    supportPoints(makeAwning({ support: { kind: 'brace', style: 'arched', count: 1 } })), ctx
  )[0].geometry));
});

await test('fix1_section_edges_win_over_record_edges_and_prepare_runs_once', async () => {
  // Section has overhang_ft: 0 on eave edge 0; record has overhang_ft: 1.0 on eave edge 0.
  // supportGeometry (post) MUST follow section.edges (overhang 0 -> inset under y=-4),
  // while undersideGeometry uses record.edges (overhang 1.0 -> extends to y=-5).
  const secEdges = [
    { setting: 'sloped', pitch: 3, overhang_ft: 0.0 },
    { setting: 'gable', pitch: 3, overhang_ft: 0.0 },
    { setting: 'gable', pitch: 3, overhang_ft: 0.0 },
    { setting: 'gable', pitch: 3, overhang_ft: 0.0 },
  ];
  const recEdges = secEdges.map((e, i) => ({ ...e, overhang_ft: i === 0 ? 1.0 : 0.0 }));
  const awSec = makeAwning({
    id: 'aw-edge-diff', roof: 'aw-edge-diff',
    area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0],
    edges: secEdges,
    support: { kind: 'post', count: 2, inset_ft: 1.0, size_ft: 0.5 },
    ends: { '1': 'closed', '3': 'closed' },
    underside: { kind: 'flat', drop_ft: 0.5 },
  });
  const plan = housePlan([awSec]);
  plan.buildings[0].roofs = [{ ...awSec, edges: recEdges }];
  const out = G.buildTwin(plan, kit(), 'high', { viewing: true });
  await out.ready;
  const pick = out.pickObjects.get('b:aw-edge-diff');
  const post0 = (pick.userData.partObjects || []).find(p => p.object.userData.part === 'support:0');
  const ceil0 = (pick.userData.partObjects || []).find(p => p.object.userData.part === 'underside');
  assert.ok(post0 && ceil0, 'both post and underside present');
  // Post uses section.edges (overhang 0): Three.js max Z must be <= 4.01 (plan y >= -4.01)
  const postMaxZ = Math.max(...vertices(post0.object.geometry).map(v => v[2]));
  assert.ok(postMaxZ <= 4.01, `post respects section.edges overhang 0 (maxZ=${postMaxZ})`);
  // Underside uses record.edges (overhang 1.0): Three.js max Z reaches ~5.01 (plan y = -5.01)
  const ceilMaxZ = Math.max(...vertices(ceil0.object.geometry).map(v => v[2]));
  assert.ok(ceilMaxZ >= 4.95, `underside uses record.edges overhang 1.0 (maxZ=${ceilMaxZ})`);
  releaseBakeSource(out.root); disposeObject(out.root);

  // Verify prepareUnderside reuse via _prepared produces identical output without re-running
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  const roof = makeAwning({ ends: { '1': 'closed', '3': 'closed' }, underside: { kind: 'flat', drop_ft: 0.5 } });
  const prep = prepareUnderside(roof, ctx);
  assert.ok(prep && Number.isFinite(prep.ceilingZ));
  const a = undersideGeometry(roof, ctx);
  const b = undersideGeometry(roof, { ...ctx, _prepared: prep });
  assert.equal(a.length, b.length);
  for (let i = 0; i < a.length; i++) {
    assert.deepEqual(Array.from(a[i].geometry.attributes.position.array), Array.from(b[i].geometry.attributes.position.array));
  }
});

await test('fix1_visible_backs_only_when_cavity_open_no_coplanar_fighting', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  const normalDirs = g => {
    const n = g.attributes.normal, out = [];
    for (let i = 0; i < n.count; i += 3) out.push([n.getX(i), n.getY(i), n.getZ(i)]);
    return out;
  };
  // 1. Fully closed box (flat ceiling + both ends closed): ceiling has ONLY downward normals (no upward back), ends have NO inward back
  const closed = undersideGeometry(makeAwning({ ends: { '1': 'closed', '3': 'closed' }, underside: { kind: 'flat', drop_ft: 0.5 } }), ctx);
  const closedCeilN = normalDirs(closed.find(p => p.part === 'underside').geometry);
  assert.ok(closedCeilN.every(n => n[1] < -0.99), 'fully closed box ceiling has only downward faces');
  const closedEnd1N = closed.filter(p => p.part === 'end:1').flatMap(p => normalDirs(p.geometry));
  assert.ok(!closedEnd1N.some(n => n[0] < -0.99), 'fully closed box end:1 has no inward back face');

  // 2. Open end with flat ceiling (only end:1 closed, end:3 open): ceiling gets upward back copy at +0.01 ft, zero coplanar overlap
  const openEnd = undersideGeometry(makeAwning({ ends: { '1': 'closed' }, underside: { kind: 'flat', drop_ft: 0.5 } }), ctx);
  const openCeilGeo = openEnd.find(p => p.part === 'underside').geometry;
  const openCeilN = normalDirs(openCeilGeo);
  assert.ok(openCeilN.some(n => n[1] < -0.99) && openCeilN.some(n => n[1] > 0.99), 'open-end ceiling has both downward and upward copies');
  const openCeilYs = [...new Set(vertices(openCeilGeo).map(v => +v[1].toFixed(4)))].sort((a, b) => a - b);
  assert.equal(openCeilYs.length, 2, 'ceiling copies separated vertically');
  assert.ok(openCeilYs[1] - openCeilYs[0] > 0.005 && openCeilYs[1] - openCeilYs[0] < 0.02, `ceiling back offset in (0.005, 0.02) ft (got ${openCeilYs[1] - openCeilYs[0]})`);

  // 3. Exposed underside with closed ends: each closed end gets inward back copy offset < 0.02 ft
  const exposed = undersideGeometry(makeAwning({ ends: { '1': 'closed', '3': 'closed' }, underside: { kind: 'exposed' } }), ctx);
  const expEnd1N = exposed.filter(p => p.part === 'end:1').flatMap(p => normalDirs(p.geometry));
  assert.ok(expEnd1N.some(n => n[0] > 0.99) && expEnd1N.some(n => n[0] < -0.99), 'exposed shed end:1 has outward and inward copies');
  // Also check exposed gable end gets inward copy
  const expGable = undersideGeometry(makeAwning({
    kind: 'gable', ridge: 'y', low_side: undefined, pitch: 6,
    edges: [0, 1, 2, 3].map(i => ({ setting: (i === 1 || i === 3) ? 'sloped' : 'gable', pitch: 6, overhang_ft: 0 })),
    ends: { '0': 'closed' }, underside: { kind: 'exposed' },
  }), ctx);
  const gN = normalDirs(expGable.find(p => p.part === 'end:0').geometry);
  assert.ok(gN.some(n => n[2] > 0.99) && gN.some(n => n[2] < -0.99), 'exposed gable end:0 has outward and inward copies');
});

await test('fix1_shed_recessed_frame_batten_fallback_and_corner_miter', () => {
  const ctxSiding = { THREE, groundAt: () => 0, wallTopAt: () => 12, sidingIsBatten: false };
  const ctxBatten = { THREE, groundAt: () => 0, wallTopAt: () => 12, sidingIsBatten: true };
  const roof = makeAwning({
    pitch: 4.5, plate: 7.75, thickness_ft: 0.25, fascia: true,
    area: rect(0, 0, 12, 3), rect: [0, 0, 12, 3],
    ends: { '1': 'closed', '3': 'closed' },
    underside: { kind: 'flat', drop_ft: 0.45 },
  });

  // Non-batten siding: frame in fascia, recessed panel in siding (0.08 ft behind frame)
  const partsS = undersideGeometry(roof, ctxSiding);
  const end1Frame = partsS.find(p => p.part === 'end:1' && p.slot === 'fascia');
  const end1Panel = partsS.find(p => p.part === 'end:1' && p.slot === 'siding');
  assert.ok(end1Frame && end1Panel, 'non-batten shed end emits fascia frame + siding recessed panel');
  const totalTris = triCount(end1Frame.geometry) + triCount(end1Panel.geometry);
  assert.ok(totalTris <= 60, `framed shed end ${totalTris} <= 60 tris`);
  const frameMaxX = Math.max(...vertices(end1Frame.geometry).map(v => v[0]));
  const panelXs = vertices(end1Panel.geometry).map(v => v[0]);
  assert.ok(panelXs.every(x => Math.abs((frameMaxX - x) - 0.15) < 1e-4), `panel recessed 0.15 ft behind frame (${frameMaxX} vs ${panelXs[0]})`);

  // Corner miter: front face and end frame meet at exact (12 + 0.01, -0.01) from ceilingZ to zTop with 0 step
  const frontPts = vertices(partsS.find(p => p.part === 'underside:front').geometry);
  const framePts = vertices(end1Frame.geometry);
  const frontMaxX = Math.max(...frontPts.map(v => v[0]));
  assert.ok(Math.abs(frontMaxX - (12 + FASCIA.proudFt)) < 1e-4, `front face reaches corner x=${12 + FASCIA.proudFt} (got ${frontMaxX})`);
  assert.ok(Math.abs(frameMaxX - frontMaxX) < 1e-4, 'end bottom board meets front face at corner with zero step');
  const frontTopCorner = frontPts.filter(v => Math.abs(v[0] - frontMaxX) < 1e-4 && Math.abs(v[1] - 7.75) < 1e-4);
  const frameTopCorner = framePts.filter(v => Math.abs(v[0] - frameMaxX) < 1e-4 && Math.abs(v[2] - FASCIA.proudFt) < 1e-4 && Math.abs(v[1] - 7.75) < 1e-4);
  assert.ok(frontTopCorner.length > 0 && frameTopCorner.length > 0, 'both front and side corner miters reach slab top 7.75');

  // Batten siding fallback: panel falls back to fascia slot (merged into single fascia part)
  const partsB = undersideGeometry(roof, ctxBatten);
  const bEnd1 = partsB.filter(p => p.part === 'end:1');
  assert.equal(bEnd1.length, 1, 'batten siding merges shed end panel into fascia slot');
  assert.equal(bEnd1[0].slot, 'fascia');
  assert.ok(triCount(bEnd1[0].geometry) <= 60);
});

await test('fix1_gutter_front_drop_0_0_5_1_5_probe', async () => {
  const results = {};
  for (const drop of [0, 0.5, 1.5]) {
    const aw = makeAwning({
      id: 'aw-gut', roof: 'aw-gut',
      area: rect(6, -3, 18, 0), rect: [6, -3, 18, 0],
      plate: 7.75, pitch: 4, thickness_ft: 0.25, fascia: true,
      gutters: { y0: true },
      edges: [
        { setting: 'sloped', pitch: 4, overhang_ft: 0, gutter: true },
        { setting: 'gable', pitch: 4, overhang_ft: 0 },
        { setting: 'gable', pitch: 4, overhang_ft: 0 },
        { setting: 'gable', pitch: 4, overhang_ft: 0 },
      ],
      ends: { '1': 'closed', '3': 'closed' },
      underside: { kind: 'flat', drop_ft: drop },
    });
    const plan = housePlan([aw]);
    plan.buildings[0].roofs = [aw];
    const placement = gutterPlacement(plan);
    const awRun = placement.runs.find(r => r.segments.some(s => s.roof === 'aw-gut'));
    assert.ok(awRun, `drop=${drop}: gutter run generated on front eave`);
    const awSpouts = placement.spouts.filter(s => s.run === awRun.id);
    assert.ok(awSpouts.length >= 1, `drop=${drop}: downspout generated`);
    // Convert downspout path points from world metres back to building plan feet
    const FT = 0.3048;
    const ceilingZ = 7.75 - 0.25 - drop;
    const pathFt = awSpouts[0].path.map(p => [p[0] / FT, -p[2] / FT, p[1] / FT]);
    // Check if any downspout segment crosses the front face plane (y = -3.01) at height z > ceilingZ
    const frontY = -3.0 - FASCIA.proudFt;
    let intersectsFront = false, crossZ = null;
    for (let i = 0; i + 1 < pathFt.length; i++) {
      const a = pathFt[i], b = pathFt[i + 1];
      if ((a[1] - frontY) * (b[1] - frontY) <= 0 && Math.abs(b[1] - a[1]) > 1e-6) {
        const t = (frontY - a[1]) / (b[1] - a[1]);
        const z = a[2] + t * (b[2] - a[2]);
        crossZ = +z.toFixed(3);
        if (z + 0.125 > ceilingZ && z - 0.125 < 7.75) intersectsFront = true;
      }
    }
    results[String(drop)] = { ceilingZ: +ceilingZ.toFixed(3), crossZ, intersectsFront, mount: awSpouts[0].mount };
  }
  console.log('GUTTER_DROP_PROBE ' + JSON.stringify(results));
  assert.equal(results['0'].intersectsFront, false, 'drop=0 clears front face');
});

await test('fix2_recess_0_15_area_45_pct_reveals_and_two_sided_pitch_1_3_6_12', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 14, sidingIsBatten: false };
  const geoArea = g => {
    const p = g.attributes.position, a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    let sum = 0;
    for (let i = 0; i < p.count; i += 3) {
      a.fromBufferAttribute(p, i); b.fromBufferAttribute(p, i + 1); c.fromBufferAttribute(p, i + 2);
      sum += b.clone().sub(a).cross(c.clone().sub(a)).length() * 0.5;
    }
    return sum;
  };
  // 1. Both fixtures: 103-proportioned (3 ft, pitch 6, drop 0.6) and original (2.8 ft, pitch 4.5, drop 0.42)
  for (const [label, depth, pitch, drop] of [
    ['photo_103', 3.0, 6.0, 0.6],
    ['original', 2.8, 4.5, 0.42],
  ]) {
    const roof = makeAwning({
      pitch, plate: 7.75, thickness_ft: 0.25, fascia: true,
      area: rect(0, 0, 12, depth), rect: [0, 0, 12, depth],
      ends: { '1': 'closed', '3': 'closed' },
      underside: { kind: 'flat', drop_ft: drop },
    });
    const parts = undersideGeometry(roof, ctx);
    const frame = parts.find(p => p.part === 'end:1' && p.slot === 'fascia');
    const panel = parts.find(p => p.part === 'end:1' && p.slot === 'siding');
    assert.ok(frame && panel, `${label}: frame and recessed panel present`);
    const totalTris = triCount(frame.geometry) + triCount(panel.geometry);
    assert.ok(totalTris <= 60, `${label}: ${totalTris} <= 60 tris`);
    const hFront = 0.25 + drop, hWall = hFront + depth * (pitch / 12);
    const endArea = depth * (hFront + hWall) * 0.5;
    const panelArea = geoArea(panel.geometry);
    const ratio = panelArea / endArea;
    assert.ok(ratio >= 0.45, `${label}: panel keeps >= 45% of end area (got ${(ratio * 100).toFixed(1)}%)`);
    // Verify 0.15 ft recess depth and all 3 reveal normals present (bottom +Y, front -Z/wall, sloped top -Y)
    const fMaxX = Math.max(...vertices(frame.geometry).map(v => v[0]));
    const pXs = vertices(panel.geometry).map(v => v[0]);
    assert.ok(pXs.every(x => Math.abs((fMaxX - x) - 0.15) < 1e-4), `${label}: 0.15 ft recess`);
    const fNorm = frame.geometry.attributes.normal;
    let hasBottomSill = false, hasTopReveal = false, hasFrontJamb = false;
    for (let i = 0; i < fNorm.count; i += 3) {
      const ny = fNorm.getY(i), nz = fNorm.getZ(i);
      if (ny > 0.99) hasBottomSill = true;
      if (ny < -0.5) hasTopReveal = true;
      if (Math.abs(ny) < 0.01 && Math.abs(nz) > 0.99) hasFrontJamb = true;
    }
    assert.ok(hasBottomSill && hasTopReveal && hasFrontJamb, `${label}: all 3 watertight reveals present`);
  }

  // 2. Two-sided check at pitch 1, 3, 6, 12: no coplanar or crossing faces between panel, inward copy, and slab
  for (const pitch of [1, 3, 6, 12]) {
    for (const underKind of ['exposed', 'flat']) {
      const roof = makeAwning({
        pitch, plate: 7.75, thickness_ft: 0.25, fascia: true,
        area: rect(0, 0, 12, 3), rect: [0, 0, 12, 3],
        ends: { '1': 'closed', '3': 'closed' },
        underside: underKind === 'flat' ? { kind: 'flat', drop_ft: 0.6 } : { kind: 'exposed' },
      });
      const parts = undersideGeometry(roof, ctx);
      const endParts = parts.filter(p => p.part === 'end:1');
      assert.ok(endParts.length >= 1, `pitch=${pitch} ${underKind}: end:1 built`);
      const totalTris = endParts.reduce((n, p) => n + triCount(p.geometry), 0);
      assert.ok(totalTris <= 60, `pitch=${pitch} ${underKind}: ${totalTris} <= 60 tris`);
      // No coplanar overlap between frame and panel parts
      if (endParts.length === 2) {
        assert.equal(coplanarOverlapCount(endParts[0].geometry, endParts[1].geometry), 0,
          `pitch=${pitch} ${underKind}: zero coplanar overlap between frame and panel`);
      }
      // Every recessed panel & inward copy vertex must stay strictly at or below slabBot(x, y)
      const panel = endParts.find(p => p.slot === 'siding');
      if (panel) {
        for (const [vx, vy, vz] of vertices(panel.geometry)) {
          const py = -vz;
          const slabBot = 7.75 + py * (pitch / 12) - 0.25;
          assert.ok(vy <= slabBot + 1e-4, `pitch=${pitch} ${underKind}: panel vertex ${vy} <= slabBot ${slabBot}`);
        }
      }
      // Check inward copy separation from panel when exposed
      if (underKind === 'exposed') {
        const frame = endParts.find(p => p.slot === 'fascia');
        const p = frame.geometry.attributes.position, n = frame.geometry.attributes.normal;
        const inXs = [];
        for (let i = 0; i < p.count; i += 3) {
          if (n.getX(i) < -0.99) {
            for (let k = 0; k < 3; k++) {
              inXs.push(p.getX(i + k));
              const py = -p.getZ(i + k);
              const slabBot = 7.75 + py * (pitch / 12) - 0.25;
              assert.ok(p.getY(i + k) <= slabBot + 1e-4, `pitch=${pitch} exposed: inward copy ${p.getY(i + k)} <= slabBot ${slabBot}`);
            }
          }
        }
        assert.ok(inXs.length >= 3, `pitch=${pitch} exposed: inward copy present`);
        if (panel) {
          const panelX = vertices(panel.geometry)[0][0];
          assert.ok(inXs.every(x => Math.abs((panelX - x) - 0.01) < 1e-4), `pitch=${pitch} exposed: inward copy offset 0.01 ft behind panel`);
        }
      }
    }
  }
});

await test('slab_underside_and_rake_boards_follow_the_drawn_edges', async () => {
  // Large downward sloped faces are the slab underside; frame reveals are far smaller.
  const measure = out => {
    let slab = 0, boards = 0;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
    out.root.traverse(o => {
      if (!o.isMesh || o.layers.isEnabled(31) || !o.parent?.userData?.supportedRoof) return;
      const p = o.geometry.attributes.position, idx = o.geometry.index;
      for (let i = 0; i < (idx ? idx.count : p.count); i += 3) {
        [a, b, c].forEach((v, k) => v.fromBufferAttribute(p, idx ? idx.getX(i + k) : i + k));
        n.copy(b).sub(a).cross(c.clone().sub(a));
        const area = n.length() / 2; n.normalize();
        if (n.y < -0.9 && n.y > -0.995 && area > 3) slab++;
        if (Math.abs(n.y) < 0.01 && Math.abs(Math.abs(n.z) - 1) < 0.01 && area > 0.5) boards++;
      }
    });
    return { slab, boards };
  };
  const build = async aw => { const out = G.buildTwin(housePlan([aw]), kit(), 'high', { viewing: true });
    await out.ready; const result = measure(out); releaseBakeSource(out.root); disposeObject(out.root); return result; };
  // L-shaped shed: edge 5 stays open, so the sky must not show through the roof.
  const area = [[4, -6], [16, -6], [16, -3], [12, -3], [12, 0], [4, 0]];
  const L = ends => makeAwning({ area, rect: [4, -6, 16, 0], host: { wall: 'w0', edge: 4 },
    edges: area.map((_, i) => ({ setting: i === 0 ? 'sloped' : 'gable', pitch: 3, overhang_ft: 0 })),
    underside: { kind: 'flat', drop_ft: 0.5 }, ends });
  const closed = { '1': 'closed', '2': 'closed', '3': 'closed' };
  assert.ok((await build(L(closed))).slab > 0, 'an open sixth edge keeps the slab underside');
  // The high back edge of an unhosted shed is not a framed end and keeps its board.
  const outside = { area: rect(4, -4, 14, 0), rect: [4, -4, 14, 0] };
  const free = ends => makeAwning({ ...outside, host: undefined, underside: { kind: 'flat', drop_ft: 0.5 }, ends });
  const open = await build(free({})), back = await build(free({ '2': 'closed' }));
  assert.ok(open.boards > 0, 'the open roof draws boards');
  assert.ok(back.boards >= open.boards, `closing the back edge keeps its board (${open.boards} then ${back.boards})`);
  // A hosted box closed at both ends hides the slab; half open does not.
  const boxed = ends => makeAwning({ ...outside, underside: { kind: 'flat', drop_ft: 0.5 }, ends });
  assert.equal((await build(boxed({ '1': 'closed', '3': 'closed' }))).slab, 0, 'a fully closed box hides the slab underside');
  assert.ok((await build(boxed({ '1': 'closed' }))).slab > 0, 'a half-open box keeps it');
});

finish();
"""


def main():
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output.strip())
    return 1 if code is None else code


if __name__ == '__main__':
    raise SystemExit(main())
