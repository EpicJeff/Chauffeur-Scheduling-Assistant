"""Task 6: awning support shapes geometry, contact, placement and batching."""
import os
from pathlib import Path
import sys

os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

from twin_editor_dom import PRELUDE, run_node  # noqa: E402

DRIVER = PRELUDE + r"""
const THREE = await import('three');
const { SUPPORT_KINDS, isSupported, supportPoints, supportGeometry, supportFrame, roofPoint } =
  await import(file('static/twin/roof_supports.js'));
const { sectionHeight } = await import(file('static/twin/twin_roof.js'));
const G = await import(file('static/twin/twin_generator.js'));
const { disposeObject } = await import(file('static/twin/twin_library.js'));
const { releaseBakeSource } = await import(file('static/twin/bake/source.js'));

const LIMITS = { bracket: 12, corbel: 400, brace: 60, cable: 24, post: 24 };

function triCount(g) {
  return (g.index ? g.index.count : g.attributes.position.count) / 3;
}

function hasInvalidNumbers(g) {
  for (const name of ['position', 'normal', 'uv']) {
    const a = g.attributes[name];
    if (!a) return true;
    for (let i = 0; i < a.array.length; i++) if (!Number.isFinite(a.array[i])) return true;
  }
  return false;
}

function inspectGeometry(g, label) {
  assert.ok(!hasInvalidNumbers(g), `${label}: no NaN or non-finite attributes`);
  const pos = g.attributes.position, norm = g.attributes.normal, uv = g.attributes.uv;
  const idx = g.index;
  const count = idx ? idx.count : pos.count;
  assert.ok(count >= 3 && count % 3 === 0, `${label}: valid triangle index count`);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const ab = new THREE.Vector3(), ac = new THREE.Vector3(), faceN = new THREE.Vector3(), vn = new THREE.Vector3();
  let signedVol = 0, minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
  for (let i = 0; i < count; i += 3) {
    const i0 = idx ? idx.getX(i) : i, i1 = idx ? idx.getX(i + 1) : i + 1, i2 = idx ? idx.getX(i + 2) : i + 2;
    a.fromBufferAttribute(pos, i0); b.fromBufferAttribute(pos, i1); c.fromBufferAttribute(pos, i2);
    ab.subVectors(b, a); ac.subVectors(c, a);
    faceN.crossVectors(ab, ac);
    const area2 = faceN.length();
    assert.ok(area2 > 1e-7, `${label}: zero-area triangle at ${i / 3} (area2=${area2})`);
    faceN.divideScalar(area2);
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
  assert.ok(signedVol > 1e-6, `${label}: closed outward volume (${signedVol})`);
  return { triangles: count / 3, signedVol, uvSpan: [maxU - minU, maxV - minV] };
}

function vertices(g) {
  const pos = g.attributes.position, out = [];
  for (let i = 0; i < pos.count; i++) out.push([pos.getX(i), pos.getY(i), pos.getZ(i)]);
  return out;
}

function makeAwning(kind, extra = {}) {
  const area = extra.area || [[0, 0], [12, 0], [12, 4], [0, 4]];
  const rect = extra.rect || [
    Math.min(...area.map(p => p[0])), Math.min(...area.map(p => p[1])),
    Math.max(...area.map(p => p[0])), Math.max(...area.map(p => p[1])),
  ];
  return {
    id: 'aw-' + kind, roof: 'aw-' + kind, level: 'L1', kind: 'shed',
    low_side: 'y0', pitch: 3, plate: 7, overhang: 0, thickness_ft: 0.3, fascia: false,
    area, rect,
    edges: area.map((_, i) => ({ setting: i === 0 ? 'sloped' : 'gable', pitch: 3, overhang_ft: 0 })),
    host: { wall: 'w2', edge: 2 },
    support: { kind, count: 2, inset_ft: 0.6 },
    ...extra,
  };
}

function todaysBracketGeometry(roof, points) {
  const { origin, outward, tangent, depth } = supportFrame(roof);
  const run = Math.min(3, depth * 0.8), rise = run * 2.6 / 3;
  const slope = (roof.pitch || 0) / 12;
  const bracketMid = roof.plate + depth * slope - run * slope
    - (roof.thickness_ft ?? 0.25) - 0.15 - 0.04 - rise / 2;
  const frame = new THREE.Matrix4().makeBasis(
    new THREE.Vector3(tangent[0], 0, -tangent[1]),
    new THREE.Vector3(0, 1, 0),
    new THREE.Vector3(outward[0], 0, -outward[1])
  ).setPosition(origin[0], 0, -origin[1]);
  return points.map((point, i) => {
    const u = (point.at[0] - origin[0]) * tangent[0] + (point.at[1] - origin[1]) * tangent[1];
    const geometry = new THREE.BoxGeometry(0.3, 0.3, run), p = geometry.attributes.position;
    for (let j = 0; j < p.count; j++) p.setY(j, p.getY(j) + rise / run * p.getZ(j));
    geometry.computeVertexNormals();
    geometry.translate(u, bracketMid, run / 2).applyMatrix4(frame);
    return { geometry, slot: 'support', part: point.id || `support:${i}` };
  });
}

function slabTopAt(roof, x, y) {
  const z = sectionHeight(roof, x, y);
  if (z !== null) return z;
  const { origin, outward, depth } = supportFrame(roof);
  const w = (x - origin[0]) * outward[0] + (y - origin[1]) * outward[1];
  return roof.plate + (depth - w) * ((roof.pitch || 0) / 12);
}

function assertContact(roof, part, kind, { groundAt, wallTopAt, wallW = 0 } = {}) {
  const { origin, outward } = supportFrame(roof);
  const thickness = roof.thickness_ft ?? 0.25;
  const pts = vertices(part.geometry);
  let minWallGap = Infinity, minSlabUnderGap = Infinity, maxSlabPen = -Infinity;
  let minSlabTopGap = Infinity, maxBelowTop = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [vx, vy, vz] of pts) {
    const px = vx, py = -vz;
    const w = (px - origin[0]) * outward[0] + (py - origin[1]) * outward[1];
    const topZ = slabTopAt(roof, px, py);
    const botZ = topZ - thickness;
    minWallGap = Math.min(minWallGap, Math.abs(w - wallW));
    minSlabUnderGap = Math.min(minSlabUnderGap, Math.abs(vy - botZ));
    maxSlabPen = Math.max(maxSlabPen, vy - botZ);
    minSlabTopGap = Math.min(minSlabTopGap, Math.abs(vy - topZ));
    maxBelowTop = Math.max(maxBelowTop, topZ - vy);
    minY = Math.min(minY, vy);
    maxY = Math.max(maxY, vy);
  }
  if (kind === 'corbel' || kind === 'brace') {
    assert.ok(minWallGap <= 0.02, `${kind}: touches wall within 0.02 ft (got ${minWallGap})`);
    assert.ok(minSlabUnderGap <= 0.02, `${kind}: touches slab underside within 0.02 ft (got ${minSlabUnderGap})`);
    assert.ok(maxSlabPen <= 0.02, `${kind}: never penetrates slab (max pen ${maxSlabPen})`);
  } else if (kind === 'cable') {
    assert.ok(minWallGap <= 0.02, `cable: touches wall within 0.02 ft (got ${minWallGap})`);
    assert.ok(minSlabTopGap <= 0.02, `cable: outer end touches slab top within 0.02 ft (got ${minSlabTopGap})`);
    assert.ok(maxBelowTop <= 0.02, `cable: never penetrates slab (below top ${maxBelowTop})`);
    if (typeof wallTopAt === 'function') {
      const wt = wallTopAt(origin[0], origin[1]);
      if (Number.isFinite(wt) && wt > roof.plate + 1) {
        assert.ok(maxY <= wt + 0.02, `cable: anchor stays below wall top (${maxY} <= ${wt})`);
      }
    }
  } else if (kind === 'post') {
    assert.ok(minSlabUnderGap <= 0.02, `post: top touches slab underside within 0.02 ft (got ${minSlabUnderGap})`);
    assert.ok(maxSlabPen <= 0.02, `post: never penetrates slab (max pen ${maxSlabPen})`);
    if (typeof groundAt === 'function') {
      const meanX = pts.reduce((n, p) => n + p[0], 0) / pts.length;
      const meanY = pts.reduce((n, p) => n + -p[2], 0) / pts.length;
      const g = groundAt(meanX, meanY);
      assert.ok(Math.abs(minY - g) <= 0.02, `post: base touches groundAt (${minY} vs ${g})`);
    }
  }
}

await test('contract_placement_and_at_overrides', () => {
  const awning = makeAwning('corbel');
  const pts = supportPoints(awning);
  assert.equal(pts.length, 2);
  assert.deepEqual(pts.map(p => p.at), [[0.6, 0], [11.4, 0]]);
  const override = makeAwning('post', { support: { kind: 'post', count: 2, at: { '0': [0, 0], '1': [6, 0] } } });
  assert.deepEqual(supportPoints(override).map(p => p.at), [[0, 0], [6, 0]]);
});

await test('all_five_kinds_limits_hygiene_slots_and_parts', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  const trisByShape = {};
  for (const [label, kind, style] of [
    ['bracket', 'bracket', undefined],
    ['corbel_scroll', 'corbel', 'scroll'],
    ['corbel_plain', 'corbel', 'plain'],
    ['brace', 'brace', undefined],
    ['cable', 'cable', undefined],
    ['post', 'post', undefined],
  ]) {
    const roof = makeAwning(kind, { support: { kind, count: 2, inset_ft: 0.6, ...(style ? { style } : {}) } });
    const points = supportPoints(roof);
    const parts = supportGeometry(roof, points, ctx);
    assert.equal(parts.length, 2, `${label}: one entry per point`);
    assert.deepEqual(parts.map(p => p.part), ['support:0', 'support:1']);
    const expectedSlot = kind === 'post' ? 'column' : 'support';
    assert.ok(parts.every(p => p.slot === expectedSlot), `${label}: slot is ${expectedSlot}`);
    for (const part of parts) {
      const info = inspectGeometry(part.geometry, label);
      assert.ok(info.triangles <= LIMITS[kind], `${label}: ${info.triangles} <= ${LIMITS[kind]}`);
      if (kind === 'post') assert.ok(Math.max(...info.uvSpan) > 2, 'post UVs are in feet');
      if (kind === 'brace' || kind === 'corbel') assert.ok(Math.max(...info.uvSpan) > 1.2, `${label} UVs are in feet`);
      assertContact(roof, part, kind, ctx);
    }
    trisByShape[label] = triCount(parts[0].geometry);
  }
  console.log('SUPPORT_TRIANGLES ' + JSON.stringify(trisByShape));
});

await test('bracket_is_vertex_for_vertex_identical_to_baseline', () => {
  const roof = makeAwning('bracket');
  const points = supportPoints(roof);
  const actual = supportGeometry(roof, points, { THREE, groundAt: () => 0, wallTopAt: () => 12 });
  const expected = todaysBracketGeometry(roof, points);
  assert.equal(actual.length, expected.length);
  for (let i = 0; i < expected.length; i++) {
    assert.equal(actual[i].slot, expected[i].slot);
    assert.equal(actual[i].part, expected[i].part);
    for (const attr of ['position', 'normal', 'uv']) {
      assert.deepEqual(
        Array.from(actual[i].geometry.attributes[attr].array),
        Array.from(expected[i].geometry.attributes[attr].array),
        `bracket[${i}].${attr} exact match`
      );
    }
    assert.deepEqual(
      Array.from(actual[i].geometry.index.array),
      Array.from(expected[i].geometry.index.array),
      `bracket[${i}].index exact match`
    );
  }
});

await test('all_four_host_sides_contact_and_orientation', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  const area = [[0, 0], [10, 0], [10, 6], [0, 6]];
  const sides = [
    { edge: 0, low_side: 'y1' },
    { edge: 1, low_side: 'x0' },
    { edge: 2, low_side: 'y0' },
    { edge: 3, low_side: 'x1' },
  ];
  for (const { edge, low_side } of sides) {
    for (const kind of ['bracket', 'corbel', 'brace', 'cable', 'post']) {
      const roof = makeAwning(kind, {
        area, rect: [0, 0, 10, 6], low_side,
        host: { wall: 'w' + edge, edge },
        edges: area.map((_, i) => ({ setting: i === (edge + 2) % 4 ? 'sloped' : 'gable', pitch: 3, overhang_ft: 0 })),
      });
      const points = supportPoints(roof);
      const parts = supportGeometry(roof, points, ctx);
      assert.equal(parts.length, 2, `side ${edge} ${kind}`);
      for (const part of parts) {
        inspectGeometry(part.geometry, `side-${edge}-${kind}`);
        assertContact(roof, part, kind, ctx);
      }
    }
  }
});

await test('rotated_roof_frame_follows_wall_and_slab', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  const roof_frame = { origin: [5, 2], angle: 0.65 };
  for (const kind of ['bracket', 'corbel', 'brace', 'cable', 'post']) {
    const roof = makeAwning(kind, { roof_frame });
    const points = supportPoints(roof);
    const parts = supportGeometry(roof, points, ctx);
    assert.equal(parts.length, 2);
    for (const part of parts) {
      inspectGeometry(part.geometry, `rotated-${kind}`);
      assertContact(roof, part, kind, ctx);
    }
  }
});

await test('counts_zero_one_and_forty', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  for (const kind of ['bracket', 'corbel', 'brace', 'cable', 'post']) {
    for (const count of [0, 1, 40]) {
      const roof = makeAwning(kind, { support: { kind, count, inset_ft: 0.4 } });
      const points = supportPoints(roof);
      const parts = supportGeometry(roof, points, ctx);
      assert.equal(parts.length, count, `${kind} count=${count}`);
      if (count > 0) {
        assert.equal(parts[0].part, 'support:0');
        assert.equal(parts[count - 1].part, `support:${count - 1}`);
        inspectGeometry(parts[0].geometry, `${kind}-count-${count}`);
      }
    }
  }
});

await test('at_overrides_and_sloped_ground_for_posts', () => {
  const groundAt = (x, y) => -1.5 + 0.25 * x - 0.1 * y;
  const ctx = { THREE, groundAt, wallTopAt: () => 12 };
  const roof = makeAwning('post', {
    support: { kind: 'post', count: 2, size_ft: 0.5, at: { '0': [2, 0], '1': [10, 0.5] } },
  });
  const points = supportPoints(roof);
  const parts = supportGeometry(roof, points, ctx);
  assert.equal(parts.length, 2);
  const mins = parts.map(p => Math.min(...vertices(p.geometry).map(v => v[1])));
  assert.ok(Math.abs(mins[0] - groundAt(2, 0)) <= 0.02, `post 0 ground ${mins[0]} vs ${groundAt(2, 0)}`);
  assert.ok(Math.abs(mins[1] - groundAt(10, 0.5)) <= 0.02, `post 1 ground ${mins[1]} vs ${groundAt(10, 0.5)}`);
  assert.ok(mins[1] - mins[0] > 1.5, 'posts follow sloped terrain independently');
  for (const part of parts) {
    inspectGeometry(part.geometry, 'sloped-post');
    assertContact(roof, part, 'post', ctx);
  }
});

await test('concave_area_wall_contact_and_unhosted_fallback', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 12 };
  // L-shaped awning: edge 0 at y=0 (x in [0, 8]), steps out at y=4 (x in [8, 20]), outer edge at y=10.
  const lArea = [[0, 0], [8, 0], [8, 4], [20, 4], [20, 10], [0, 10]];
  for (const kind of ['corbel', 'brace', 'cable', 'post']) {
    const roof = makeAwning(kind, {
      area: lArea, rect: [0, 0, 20, 10], low_side: 'y1', pitch: 2,
      host: { wall: 'w0', edge: 0 },
      edges: lArea.map(() => ({ setting: 'sloped', pitch: 2, overhang_ft: 0 })),
      support: { kind, count: 2, inset_ft: 2 },
    });
    const points = supportPoints(roof);
    const parts = supportGeometry(roof, points, ctx);
    assert.equal(parts.length, 2);
    // Point 0 is at x=18 (over the y=4 stepped wing -> wallW = 4), Point 1 is at x=2 (over y=0 -> wallW = 0).
    for (let i = 0; i < 2; i++) {
      inspectGeometry(parts[i].geometry, `concave-${kind}-${i}`);
      const expectedWallW = points[i].at[0] > 8 ? 4 : 0;
      assertContact(roof, parts[i], kind, { ...ctx, wallW: expectedWallW });
    }
  }
  // Roof with NO host wall: still draws sensibly from the high edge.
  for (const kind of ['bracket', 'corbel', 'brace', 'cable', 'post']) {
    const unhosted = makeAwning(kind, { host: undefined });
    delete unhosted.host;
    const points = supportPoints(unhosted);
    const parts = supportGeometry(unhosted, points, ctx);
    assert.equal(parts.length, 2, `unhosted ${kind}`);
    for (const part of parts) {
      inspectGeometry(part.geometry, `unhosted-${kind}`);
      assertContact(unhosted, part, kind, ctx);
    }
  }
});

await test('generator_merges_all_support_kinds_with_zero_extra_draws_and_grounds_posts', async () => {
  const rect = (a, b, c, d) => [[a, b], [c, b], [c, d], [a, d]];
  const outline = rect(0, 0, 50, 20);
  const kit = () => ({
    materials: Object.fromEntries(['floor', 'patio_concrete', 'siding', 'interior_wall', 'roof', 'trim',
      'window_frame', 'door', 'porch_ceiling', 'base', 'lattice', 'counter', 'stainless', 'lawn', 'paving', 'ceiling']
      .map(k => [k, { asset: k, color: '#bbccee' }])),
    manifest: {},
  });
  function basePlan() {
    return {
      schema: 2, units: 'ft', materials: {},
      site: { terraces: [{ polygon: rect(-10, -14, 24, -2), height: -1.5, blend: 0 }] },
      buildings: [{
        id: 'b', position: [0, 0], base: 0, rotation: 0,
        levels: [{ id: 'L1', elevation: 0, ceiling: 11, outline }],
        walls: outline.map((from, i) => ({
          id: 'w' + i, from, to: outline[(i + 1) % 4], level: 'L1', height: 11, thickness: 0.5, exterior: true,
        })),
        rooms: [{ id: 'r0', level: 'L1', polygon: outline, state: 'settled' }],
        openings: [],
        porches: [{ id: 'p0', polygon: rect(26, -6, 48, 0), floor: 0.6, columns: [] }],
        lights: [], fixtures: [], stairs: [], items: [], anchors: [],
        roof: {
          sections: [{ id: 'main', roof: 'main', level: 'L1', kind: 'gable', ridge: 'x', rect: [0, 0, 50, 20], plate: 11, pitch: 4, overhang: 1 }],
          extensions: [], flags: [],
        },
        roofs: [],
      }],
    };
  }
  function addTenAwnings(plan) {
    const b = plan.buildings[0];
    const kinds = ['bracket', 'corbel', 'brace', 'cable', 'post'];
    kinds.forEach((kind, k) => {
      // Front wall (w0, y=0, awning extends to y=-4) and back wall (w2, y=20, awning extends to y=24)
      for (const side of [0, 1]) {
        const x0 = 2 + k * 9.5, x1 = x0 + 7.5;
        const y0 = side === 0 ? -4 : 20, y1 = side === 0 ? 0 : 24;
        const id = `aw-${kind}-${side}`;
        const sec = {
          id, roof: id, level: 'L1', kind: 'shed',
          low_side: side === 0 ? 'y0' : 'y1', pitch: kind === 'cable' ? 0 : 3, plate: 7.5,
          overhang: 0, thickness_ft: 0.3, fascia: false,
          rect: [x0, y0, x1, y1], area: rect(x0, y0, x1, y1),
          edges: rect(x0, y0, x1, y1).map((_, i) => ({
            setting: i === (side === 0 ? 0 : 2) ? 'sloped' : 'gable',
            pitch: kind === 'cable' ? 0 : 3, overhang_ft: 0,
          })),
          host: { wall: side === 0 ? 'w0' : 'w2', edge: side === 0 ? 2 : 0 },
          support: { kind, count: 2, inset_ft: 0.6, ...(kind === 'corbel' && side === 1 ? { style: 'plain' } : {}) },
        };
        b.roof.sections.push(sec);
      }
    });
    return plan;
  }
  const measure = async plan => {
    const t0 = performance.now();
    const out = G.buildTwin(structuredClone(plan), kit(), 'high', { viewing: true });
    await out.ready;
    const ms = performance.now() - t0;
    out.root.updateMatrixWorld(true);
    let draws = 0, triangles = 0, supportedDraws = 0, supportedTris = 0;
    const matKeys = new Set();
    out.root.traverseVisible(m => {
      if (!m.isMesh || m.layers.isEnabled(31)) return;
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      if (!mats.some(x => x.visible)) return;
      const d = Array.isArray(m.material) ? m.geometry.groups.filter(g => m.material[g.materialIndex]?.visible).length : 1;
      const t = (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3 * (m.isInstancedMesh ? m.count : 1);
      draws += d; triangles += t;
      for (const x of mats) matKeys.add(JSON.stringify([
        x.name, x.userData?.materialKey ?? null, x.transparent, x.alphaTest, x.opacity, x.side, x.depthWrite, x.depthTest, x.color?.getHexString() ?? null,
      ]));
      if (m.parent?.userData?.supportedRoof) { supportedDraws += d; supportedTris += t; }
    });
    return { out, ms, draws, triangles, supportedDraws, supportedTris, materials: matKeys };
  };
  const before = await measure(basePlan());
  const withBracketsOnly = basePlan();
  addTenAwnings(withBracketsOnly);
  for (const s of withBracketsOnly.buildings[0].roof.sections) if (s.support) s.support.kind = 'bracket';
  const bracketsOnly = await measure(withBracketsOnly);
  const after = await measure(addTenAwnings(basePlan()));

  // All 10 awnings (2 per kind) share the exact same supported-roof group draws as 10 bracket awnings: 0 extra draws, 0 new materials.
  assert.equal(after.draws, bracketsOnly.draws, '0 extra draws compared to bracket-only awnings');
  assert.equal(after.supportedDraws, bracketsOnly.supportedDraws, 'same supported-roof group draws');
  assert.ok(after.supportedDraws <= 3, `supported group draws ${after.supportedDraws} <= 3`);
  for (const k of after.materials) assert.ok(before.materials.has(k), `no new material created: ${k}`);

  // Verify post on front porch (x in [40, 47.5], y=-4) lands on porch floor (0.6 ft),
  // and post on back yard (y=24) lands on yard ground (0 ft), while a post on the terrace lands at -1.5 ft.
  const pickFrontPost = after.out.pickObjects.get('b:aw-post-0');
  const postParts = (pickFrontPost?.userData?.partObjects || []).filter(p => (p.object.userData.part || '').startsWith('support:'));
  assert.equal(postParts.length, 2, 'post awning exposes 2 pickable support parts');
  const postFrontMinY = Math.min(...vertices(postParts[0].object.geometry).map(v => v[1]));
  assert.ok(Math.abs(postFrontMinY - 0.6) <= 0.02, `post over porch lands on porch floor 0.6 (got ${postFrontMinY})`);

  // Verify footprint wall face offset places wall-mounted supports on the exterior face (not buried).
  const fpPlan = basePlan();
  fpPlan.buildings[0].walls[0].footprint = [[0, -0.25], [50, -0.25], [50, 0.25], [0, 0.25]];
  addTenAwnings(fpPlan);
  const fpBuilt = await measure(fpPlan);
  for (const id of ['b:aw-cable-0', 'b:aw-brace-0', 'b:aw-corbel-0']) {
    const pick = fpBuilt.out.pickObjects.get(id);
    const sup = (pick?.userData?.partObjects || []).find(p => p.object.userData.part === 'support:0');
    assert.ok(sup, `${id}: support:0 pickable`);
    const minZ = Math.min(...vertices(sup.object.geometry).map(v => v[2]));
    // Front wall w0 is at y=0 (Three.js z=0), exterior footprint face at y=-0.25 (Three.js z=+0.25).
    assert.ok(Math.abs(minZ - 0.25) <= 0.02, `${id}: starts flush at footprint face z=0.25 (got ${minZ})`);
  }
  releaseBakeSource(fpBuilt.out.root);
  disposeObject(fpBuilt.out.root);

  console.log('HOUSE_COST_10_AWNINGS ' + JSON.stringify({
    before: { draws: before.draws, triangles: before.triangles, build_ms: +before.ms.toFixed(1) },
    brackets_only: { draws: bracketsOnly.draws, triangles: bracketsOnly.triangles, supportedDraws: bracketsOnly.supportedDraws, build_ms: +bracketsOnly.ms.toFixed(1) },
    all_kinds: { draws: after.draws, triangles: after.triangles, supportedDraws: after.supportedDraws, build_ms: +after.ms.toFixed(1) },
  }));

  for (const b of [before, bracketsOnly, after]) {
    releaseBakeSource(b.out.root);
    disposeObject(b.out.root);
  }
});

await test('gable_perpendicular_ridge_and_x_side_hosted_shed_shear_within_0_02', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 14 };
  // Scenario A: gable with ridge 'y' at pitch 6, host edge 2, three supports (middle straddles ridge).
  for (const kind of ['corbel', 'brace']) {
    const gable = makeAwning(kind, {
      kind: 'gable', ridge: 'y', pitch: 6, plate: 7, thickness_ft: 0.3,
      area: [[0, 0], [12, 0], [12, 4], [0, 4]], rect: [0, 0, 12, 4],
      host: { wall: 'w2', edge: 2 },
      support: { kind, count: 3, inset_ft: 1.0 },
    });
    const parts = supportGeometry(gable, supportPoints(gable), ctx);
    assert.equal(parts.length, 3, `gable ${kind}: 3 parts`);
    for (let i = 0; i < parts.length; i++) {
      inspectGeometry(parts[i].geometry, `gable-${kind}-${i}`);
      assertContact(gable, parts[i], kind, ctx);
    }
  }
  // Scenario B: shed with low_side y0 hosted on an x-side wall (edge 1 and edge 3).
  for (const edge of [1, 3]) {
    for (const kind of ['corbel', 'brace']) {
      const xShed = makeAwning(kind, {
        kind: 'shed', low_side: 'y0', pitch: 3, plate: 7, thickness_ft: 0.3,
        area: [[0, 0], [10, 0], [10, 6], [0, 6]], rect: [0, 0, 10, 6],
        host: { wall: 'w' + edge, edge },
        support: { kind, count: 2, inset_ft: 1.0 },
      });
      const parts = supportGeometry(xShed, supportPoints(xShed), ctx);
      assert.equal(parts.length, 2, `x-side-${edge}-${kind}`);
      for (const part of parts) {
        inspectGeometry(part.geometry, `x-side-${edge}-${kind}`);
        assertContact(xShed, part, kind, ctx);
      }
    }
  }
});

await test('cable_clamps_under_wall_top_and_uses_short_tie_when_low_or_unwalled', () => {
  // Slab top at wall: plate 7 + depth 3.9 * (3/12) = 7.975 ft.
  const roof = makeAwning('cable', {
    area: [[0, 0], [12, 0], [12, 3.9], [0, 3.9]], rect: [0, 0, 12, 3.9],
    plate: 7, pitch: 3, thickness_ft: 0.3,
  });
  const pts = supportPoints(roof);
  const yTopWall = 7 + 3.9 * 3 / 12; // 7.975
  for (const wallTop of [8.0, 8.3, null]) {
    const ctx = { THREE, groundAt: () => 0, wallTopAt: () => wallTop };
    const parts = supportGeometry(roof, pts, ctx);
    assert.equal(parts.length, 2, `cable wallTop=${wallTop}: 2 parts`);
    for (const part of parts) {
      const info = inspectGeometry(part.geometry, `cable-low-${wallTop}`);
      assert.ok(info.triangles <= 24, `cable wallTop=${wallTop}: <= 24 tris`);
      const ys = vertices(part.geometry).map(v => v[1]);
      const maxY = Math.max(...ys);
      assert.ok(maxY <= yTopWall + 0.12, `cable wallTop=${wallTop}: short tie stays near slab top (got ${maxY})`);
      if (wallTop !== null) assert.ok(maxY <= wallTop + 0.05, `cable wallTop=${wallTop}: does not float above wall (${maxY})`);
      assertContact(roof, part, 'cable', ctx);
    }
  }
  // Adequate wall height (9.0 -> 1.025 ft room >= 0.75) clamps anchor cleanly below 9.0.
  const ctxOk = { THREE, groundAt: () => 0, wallTopAt: () => 9.0 };
  const tallParts = supportGeometry(roof, pts, ctxOk);
  for (const part of tallParts) {
    inspectGeometry(part.geometry, 'cable-wallTop-9');
    const maxY = Math.max(...vertices(part.geometry).map(v => v[1]));
    assert.ok(maxY > yTopWall + 0.5 && maxY <= 9.0, `cable wallTop=9.0: angled anchor clamped below 9.0 (got ${maxY})`);
    assertContact(roof, part, 'cable', ctxOk);
  }
});

await test('minor_fixes_size_clamp_post_inset_high_ground_stub_and_brace_tail', () => {
  const ctx = { THREE, groundAt: () => 0, wallTopAt: () => 14 };
  // Size clamp: 3.5 clamps to 3.0 (not default 0.5).
  const p3 = supportGeometry(makeAwning('corbel', { support: { kind: 'corbel', count: 1, size_ft: 3.0 } }), supportPoints(makeAwning('corbel', { support: { kind: 'corbel', count: 1, size_ft: 3.0 } })), ctx)[0];
  const p35 = supportGeometry(makeAwning('corbel', { support: { kind: 'corbel', count: 1, size_ft: 3.5 } }), supportPoints(makeAwning('corbel', { support: { kind: 'corbel', count: 1, size_ft: 3.5 } })), ctx)[0];
  const widthOf = g => { const xs = vertices(g).map(v => v[0]); return Math.max(...xs) - Math.min(...xs); };
  assert.ok(Math.abs(widthOf(p35.geometry) - widthOf(p3.geometry)) < 1e-4, 'size 3.5 clamps to 3.0');

  // Post inset on zero-overhang roof: does not stick past outer edge y=0 (Three.js z=0).
  const postRoof = makeAwning('post', { overhang: 0 });
  const postParts = supportGeometry(postRoof, supportPoints(postRoof), ctx);
  for (const part of postParts) {
    const maxZ = Math.max(...vertices(part.geometry).map(v => v[2]));
    assert.ok(maxZ <= 0.01, `zero-overhang post stays under slab edge (maxZ=${maxZ})`);
  }

  // Post with ground above slab still renders a valid stub (not dropped).
  const highCtx = { THREE, groundAt: () => 12, wallTopAt: () => 14 };
  const stubs = supportGeometry(postRoof, supportPoints(postRoof), highCtx);
  assert.equal(stubs.length, 2, 'high-ground post returns 2 stubs instead of dropping supports');
  for (const s of stubs) inspectGeometry(s.geometry, 'high-ground-stub');

  // Brace default timber is heavier (~0.45 ft) and post continues below diagonal.
  const braceRoof = makeAwning('brace');
  const bracePart = supportGeometry(braceRoof, supportPoints(braceRoof), ctx)[0];
  const bWidth = widthOf(bracePart.geometry);
  assert.ok(bWidth >= 0.40 && bWidth <= 0.50, `default brace timber width ~0.45 ft (got ${bWidth})`);
});

finish();
"""


def main():
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output.strip())
    return 1 if code is None else code


if __name__ == '__main__':
    raise SystemExit(main())
