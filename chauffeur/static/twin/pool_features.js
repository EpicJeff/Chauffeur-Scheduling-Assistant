import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { polygon, addMesh } from './twin_generator.js';
import { inPolygon, edgeDistance, segmentIntersection } from './twin_ground.js';

const area = p => p.reduce((s, a, i) => { const b = p[(i + 1) % p.length]; return s + a[0] * b[1] - a[1] * b[0]; }, 0);
const cross = (a, b, p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
const clean = p => p.filter((q, i) => Math.hypot(...q.map((v, j) => v - p[(i + p.length - 1) % p.length][j])) > 1e-8);
export function clipHalf(poly, a, b, sign = 1) {
  const out = [];
  poly.forEach((p, i) => {
    const q = poly[(i + 1) % poly.length], s = sign * cross(a, b, p), t = sign * cross(a, b, q);
    if (s >= -1e-9) out.push(p);
    if (s * t < -1e-18) out.push(p.map((v, j) => v + (q[j] - v) * s / (s - t)));
  });
  const result = clean(out);
  return result.length >= 3 && Math.abs(area(result)) > 1e-8 ? result : [];
}

function triangles(outline, holes = []) {
  const points = [outline, ...holes].flat();
  return THREE.ShapeUtils.triangulateShape(outline.map(p => new THREE.Vector2(...p)), holes.map(h => h.map(p => new THREE.Vector2(...p))))
    .map(ids => ids.map(i => points[i]));
}

// Triangulate first: both the pool and the cutters can be concave, cross the
// boundary, or overlap one another. Each convex subtraction keeps disjoint pieces.
export function cutPolygons(outline, cutters, holes = []) {
  let parts = triangles(outline, holes);
  for (const cutter of cutters) for (const tri of triangles(cutter)) {
    const sign = Math.sign(area(tri));
    parts = parts.flatMap(part => {
      let rest = part; const kept = [];
      for (let i = 0; i < 3 && rest.length; i++) {
        const a = tri[i], b = tri[(i + 1) % 3], outside = clipHalf(rest, a, b, -sign);
        if (outside.length) kept.push(outside);
        rest = clipHalf(rest, a, b, sign);
      }
      return rest.length ? kept : [part];
    });
  }
  return parts;
}

export function cutSurface(outline, cutters, z0, z1 = z0, holes = []) {
  const geometries = cutPolygons(outline, cutters, holes).map(p => polygon(p, z0, z1));
  if (!geometries.length) return new THREE.BufferGeometry()
    .setAttribute('position', new THREE.Float32BufferAttribute([], 3))
    .setAttribute('normal', new THREE.Float32BufferAttribute([], 3))
    .setAttribute('uv', new THREE.Float32BufferAttribute([], 2));
  const result = mergeGeometries(geometries);
  geometries.forEach(g => g.dispose());
  return result;
}

export function offsetOutline(poly, distance) {
  const sign = Math.sign(area(poly));
  const normal = (a, b) => { const l = Math.hypot(b[0] - a[0], b[1] - a[1]); return [sign * (b[1] - a[1]) / l, -sign * (b[0] - a[0]) / l]; };
  return poly.map((p, i) => {
    const a = normal(poly[(i + poly.length - 1) % poly.length], p), b = normal(p, poly[(i + 1) % poly.length]);
    const f = distance / Math.max(.1, 1 + a[0] * b[0] + a[1] * b[1]);
    return p.map((v, j) => v + (a[j] + b[j]) * f);
  });
}

function basinOutline(poly) {
  // A fixed liner width can invert a small spa or bridge a narrow concave
  // neck. Keep the authored footprint; thin the liner until it fits inside.
  for (let width = .3; ; width /= 2) {
    const inner = offsetOutline(poly, -width);
    const fits = Math.sign(area(inner)) === Math.sign(area(poly)) && Math.abs(area(inner)) < Math.abs(area(poly))
      && inner.every((a, i) => inPolygon(poly, ...a)
        && !poly.some((b, j) => segmentIntersection(a, inner[(i + 1) % inner.length], b, poly[(j + 1) % poly.length]))
        && !inner.some((b, j) => j > i + 1 && !(i === 0 && j === inner.length - 1)
          && segmentIntersection(a, inner[(i + 1) % inner.length], b, inner[(j + 1) % inner.length])));
    if (fits || width < 1e-8) return inner;
  }
}

function sharedSegments(spa, pool) {
  const result = [];
  spa.forEach((a, i) => {
    const b = spa[(i + 1) % spa.length], ts = [0, 1];
    pool.forEach((c, j) => {
      const d = pool[(j + 1) % pool.length], den = cross([0, 0], b.map((v, k) => v - a[k]), d.map((v, k) => v - c[k]));
      if (Math.abs(den) < 1e-9) return;
      const t = cross(a, c, d) / den, u = cross(a, c, b) / den;
      if (t > 0 && t < 1 && u >= 0 && u <= 1) ts.push(t);
    });
    ts.sort((x, y) => x - y);
    const at = t => a.map((v, j) => v + t * (b[j] - v));
    for (let j = 1; j < ts.length; j++) {
      if (ts[j] - ts[j - 1] < 1e-8) continue;
      const p = at((ts[j - 1] + ts[j]) / 2);
      if (inPolygon(pool, ...p) || pool.some((c, k) => edgeDistance(p, c, pool[(k + 1) % pool.length]) < 1e-7))
        result.push([at(ts[j - 1]), at(ts[j])]);
    }
  });
  return result;
}

export function buildPoolFeatures(group, pool, height, { mat, plain, water, copingRole = 'paving' }) {
  const interior = slot => slot ? mat('paving', slot) : plain('pool tile', '#5fa8c4', { roughness: .35 });
  const tile = interior(pool.materials?.interior), depth = pool.depth ?? 5;
  const spas = (pool.features || []).filter(f => f.kind === 'spa').map(f => f.polygon);
  const slab = (poly, top) => spas.length ? cutSurface(poly, spas, height - depth, top) : polygon(poly, height - depth, top);
  for (const f of pool.features || []) {
    const poly = f.polygon;
    if (f.kind === 'ledge') {
      addMesh(group, slab(poly, height - .25 - (f.depth_in ?? 10) / 12), tile);
    } else if (f.kind === 'steps') {
      const a = poly[f.entry_edge ?? 0], b = poly[((f.entry_edge ?? 0) + 1) % poly.length];
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]), sign = Math.sign(area(poly));
      const n = [-sign * (b[1] - a[1]) / l, sign * (b[0] - a[0]) / l];
      const distances = poly.map(p => (p[0] - a[0]) * n[0] + (p[1] - a[1]) * n[1]);
      const low = Math.min(...distances), high = Math.max(...distances), count = f.treads ?? 3;
      // Clip triangulated pieces into bands; a concave outline can have several
      // disconnected pieces in a band. Each tread drops exactly one riser.
      for (let i = 0; i < count; i++) {
        const start = a.map((v, j) => v + n[j] * (low + (high - low) * i / count));
        const end = a.map((v, j) => v + n[j] * (low + (high - low) * (i + 1) / count));
        const slabs = [];
        for (let part of triangles(poly)) {
          part = clipHalf(part, start, [start[0] + n[1], start[1] - n[0]]);
          part = clipHalf(part, end, [end[0] - n[1], end[1] + n[0]]);
          if (part.length) slabs.push(slab(part, height - depth * (i + 1) / (count + 1)));
        }
        const geometry = mergeGeometries(slabs);
        if (geometry) addMesh(group, geometry, tile);
        slabs.forEach(g => g.dispose());
      }
    } else if (f.kind === 'spa') {
      const raised = (f.mode ?? 'raised') === 'raised', rise = raised ? (f.raise_in ?? 12) / 12 : 0;
      const wallTop = height + .3 + rise, copingTop = height + .45 + rise;
      const waterHeight = raised ? copingTop - 2 / 12 : height - .25;
      const floor = waterHeight - (f.depth_in ?? 36) / 12, inner = basinOutline(poly);
      const spaTile = interior(f.materials?.interior || pool.materials?.interior);
      addMesh(group, polygon(inner, floor - .2, floor), spaTile);
      // Separate outer wall and tile liner, so wall slots never paint the basin.
      const wall = f.materials?.wall ? mat('base', f.materials.wall) : mat('base');
      poly.forEach((a, i) => {
        const j = (i + 1) % poly.length, b = poly[j], c = inner[j], d = inner[i];
        const middleA = a.map((v, k) => (v + d[k]) / 2), middleB = b.map((v, k) => (v + c[k]) / 2);
        addMesh(group, polygon([a, b, middleB, middleA], floor, wallTop), wall);
        addMesh(group, polygon([middleA, middleB, c, d], floor, wallTop), spaTile);
      });
      const copingSlot = f.materials?.coping || pool.materials?.coping;
      addMesh(group, polygon(poly, wallTop, copingTop, [inner]), mat(copingRole, copingSlot));
      addMesh(group, polygon(inner, waterHeight), water);
      if (raised && (f.spillover ?? true)) for (const [a, b] of sharedSegments(poly, pool.polygon)) {
        const n = [(b[1] - a[1]), -(b[0] - a[0])], l = Math.hypot(...n), sign = Math.sign(area(poly));
        const strip = [a, b, b.map((v, j) => v + sign * n[j] / l * .025), a.map((v, j) => v + sign * n[j] / l * .025)];
        addMesh(group, polygon(strip, height - .25, waterHeight), water);
      }
    }
  }
}
