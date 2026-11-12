import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { groundAt, inPolygon, segmentIntersection } from './twin_ground.js';

// Split grid cells at polygon edges before sampling. Each side owns its edge
// vertices, so a sharp edge never becomes an interpolated diagonal ramp.
function split(poly, a, b) {
  const side = p => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
  const result = [[], []];
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length], s = side(p), t = side(q);
    if (s >= -1e-8) result[0].push(p);
    if (s <= 1e-8) result[1].push(p);
    if (s * t < -1e-16) {
      const point = p.map((v, j) => v + (q[j] - v) * s / (s - t));
      result.forEach(r => r.push(point));
    }
  }
  return result.filter(r => r.length >= 3);
}
const centre = poly => [0, 1].map(i => poly.reduce((n, p) => n + p[i], 0) / poly.length);
export function terrainGeometry(plan, outline, tier = 'high', { holes = [], offset = 0, skirts = false } = {}) {
  const pads = plan.site?.terraces || [], step = tier === 'low' ? 2 : 1;
  const all = [outline, ...holes, ...pads.map(p => p.polygon)];
  const edges = all.flatMap(poly => poly.map((a, i) => [a, poly[(i + 1) % poly.length]]));
  const xs = outline.map(p => p[0]), ys = outline.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const positions = [], uvs = [], indices = [], vertices = new Map();
  const vertex = (p, h) => {
    const key = [p[0], p[1], h].map(v => v.toFixed(7)).join(':');
    if (!vertices.has(key)) { vertices.set(key, positions.length / 3); positions.push(p[0], h, -p[1]); uvs.push(p[0], -p[1]); }
    return vertices.get(key);
  };
  const face = points => {
    const ids = points.map(([p, h]) => vertex(p, h));
    for (let i = 1; i + 1 < ids.length; i++) indices.push(ids[0], ids[i], ids[i + 1]);
  };
  for (let x = x0; x < x1 - 1e-8; x += step) for (let y = y0; y < y1 - 1e-8; y += step) {
    const xx = Math.min(x1, x + step), yy = Math.min(y1, y + step);
    let parts = [[[x, y], [xx, y], [xx, yy], [x, yy]]];
    for (const [a, b] of edges) {
      if (Math.max(a[0], b[0]) < x || Math.min(a[0], b[0]) > xx || Math.max(a[1], b[1]) < y || Math.min(a[1], b[1]) > yy) continue;
      parts = parts.flatMap(poly => split(poly, a, b));
    }
    for (const poly of parts) {
      const c = centre(poly);
      if (!inPolygon(outline, ...c) || holes.some(h => inPolygon(h, ...c))) continue;
      face(poly.map(p => {
        const inward = p.map((v, i) => v + (c[i] - v) * 1e-7);
        return [p, groundAt(plan, ...inward) + offset];
      }));
    }
  }
  if (skirts) for (const pad of pads) pad.polygon.forEach((a, i) => {
    if ((pad.edges?.[i]?.edge ?? 'slope') !== 'sharp' && pad.blend !== 0) return;
    const b = pad.polygon[(i + 1) % pad.polygon.length], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const n = [(b[1] - a[1]) / length * 1e-5, -(b[0] - a[0]) / length * 1e-5];
    for (let d = 0; d < length; d += step) {
      const p = a.map((v, j) => v + (b[j] - v) * d / length), q = a.map((v, j) => v + (b[j] - v) * Math.min(length, d + step) / length);
      const l = r => groundAt(plan, r[0] + n[0], r[1] + n[1]) + offset;
      const h = r => groundAt(plan, r[0] - n[0], r[1] - n[1]) + offset;
      if (inPolygon(outline, ...centre([p, q])) && !holes.some(hole => inPolygon(hole, ...centre([p, q])))) {
        face([[p, l(p)], [q, l(q)], [q, h(q)], [p, h(p)]]);
      }
    }
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices); geometry.computeVertexNormals(); return geometry;
}

// Change only position/normal buffers on yard slabs; preserve texture UVs.
export function drapeGeometry(geometry, plan, offset = 0) {
  const p = geometry.attributes.position;
  for (let i = 0; i < p.count; i++) p.setY(i, p.getY(i) + groundAt(plan, p.getX(i), -p.getZ(i)) + offset);
  p.needsUpdate = true; geometry.computeVertexNormals(); return geometry;
}

export function terrainSlabGeometry(plan, outline, tier, bottom, top, holes = []) {
  // Patios and beds receive baked light. Their topology/UVs must be identical
  // on every tier; only the much larger, unbaked lawn uses the tiered grid.
  const surface = terrainGeometry(plan, outline, 'high', { holes, offset: top, skirts: true });
  const positions = [], uv = [], step = 1;
  const emit = (...points) => { for (const p of points) { positions.push(p[0], p[2], -p[1]); uv.push(p[0], p[2]); } };
  for (const [index, poly] of [outline, ...holes].entries()) {
    const area = poly.reduce((n, p, i) => n + p[0] * poly[(i + 1) % poly.length][1] - p[1] * poly[(i + 1) % poly.length][0], 0);
    const boundary = (area > 0) !== (index > 0) ? poly : [...poly].reverse();
    boundary.forEach((a, i) => {
      const b = boundary[(i + 1) % boundary.length], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const cuts = [0, 1];
      for (let d = step; d < length; d += step) cuts.push(d / length);
      for (const pad of plan.site?.terraces || []) pad.polygon.forEach((c, j) => {
        const p = segmentIntersection(a, b, c, pad.polygon[(j + 1) % pad.polygon.length]);
        if (p) cuts.push(Math.hypot(p[0] - a[0], p[1] - a[1]) / length);
      });
      cuts.sort((a, b) => a - b);
      for (let j = 0; j + 1 < cuts.length; j++) {
        const lo = cuts[j], hi = cuts[j + 1]; if (hi - lo < 1e-8) continue;
        const point = t => a.map((v, k) => v + (b[k] - v) * t);
        const p = point(lo), q = point(hi), h0 = groundAt(plan, ...point(lo + (hi - lo) * 1e-7)), h1 = groundAt(plan, ...point(hi - (hi - lo) * 1e-7));
        const p0 = [...p, h0 + bottom], p1 = [...p, h0 + top], q0 = [...q, h1 + bottom], q1 = [...q, h1 + top];
        emit(p0, q1, q0, p0, p1, q1);
      }
    });
  }
  const sides = new THREE.BufferGeometry();
  sides.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  sides.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); sides.computeVertexNormals();
  const unindexed = surface.toNonIndexed(), result = mergeGeometries([unindexed, sides]);
  surface.dispose(); unindexed.dispose(); sides.dispose(); return result;
}

export function tintGrade(geometry, enabled) {
  const p = geometry.attributes.position, colors = [];
  for (let i = 0; i < p.count; i++) {
    const t = Math.max(0, Math.min(1, .5 + p.getY(i) / 20));
    // Blue to orange, with luminance change; no red/green distinction.
    colors.push(.35 + .5 * t, .55 + .1 * t, .85 - .5 * t);
  }
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(enabled ? colors : new Array(p.count * 3).fill(1), 3));
}
