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

// Inset each edge by its own width. An edge of width 0 keeps its place, so the
// basin runs right up to it.
function insetOutline(poly, widths) {
  const sign = Math.sign(area(poly));
  const lines = poly.map((a, i) => {
    const b = poly[(i + 1) % poly.length], d = [b[0] - a[0], b[1] - a[1]], l = Math.hypot(...d);
    return { p: [a[0] - sign * d[1] / l * widths[i], a[1] + sign * d[0] / l * widths[i]], d };
  });
  return poly.map((_, i) => {
    const before = lines[(i + poly.length - 1) % poly.length], after = lines[i];
    const den = before.d[0] * after.d[1] - before.d[1] * after.d[0];
    if (Math.abs(den) < 1e-9) return after.p;
    const t = ((after.p[0] - before.p[0]) * after.d[1] - (after.p[1] - before.p[1]) * after.d[0]) / den;
    return [before.p[0] + before.d[0] * t, before.p[1] + before.d[1] * t];
  });
}
// A kept edge leaves basin corners on the outline, so only a true crossing counts there.
function crossing(a, b, c, d) {
  const s = cross(a, b, c), t = cross(a, b, d), u = cross(c, d, a), v = cross(c, d, b);
  return s * t < -1e-12 && u * v < -1e-12;
}
const onEdge = (a, b, outline) => outline.some((c, i) => {
  const d = outline[(i + 1) % outline.length];
  return edgeDistance(a, c, d) < .05 && edgeDistance(b, c, d) < .05;
});

function basinOutline(poly, requestedWidth = .3, kept = null) {
  // A fixed liner or bench width can invert a small spa or bridge a narrow
  // concave neck. Thin the inset until its outline fits inside.
  const meets = kept ? crossing : segmentIntersection;
  for (let width = requestedWidth; ; width /= 2) {
    const inner = kept ? insetOutline(poly, kept.map(k => k ? 0 : width)) : offsetOutline(poly, -width);
    const fits = Math.sign(area(inner)) === Math.sign(area(poly)) && Math.abs(area(inner)) < Math.abs(area(poly))
      && inner.every((a, i) => inPolygon(poly, ...a)
        && !poly.some((b, j) => meets(a, inner[(i + 1) % inner.length], b, poly[(j + 1) % poly.length]))
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

// The band of tile at the water's edge: from 3 in below the pool water to the coping.
export const WATERLINE_BELOW = .25;
export const waterlineMaterial = (slot, { mat, plain }) => slot ? mat('paving', slot)
  : plain('waterline tile', '#2f6f96', { roughness: .25 });

const touches = (a, b) => [[a, b], [b, a]].some(([p, q]) => p.some(v => inPolygon(q, ...v)
  || q.some((c, i) => edgeDistance(v, c, q[(i + 1) % q.length]) < .1)));

export function buildPoolFeatures(group, pool, height, { mat, plain, water, copingRole = 'paving', spaWater = () => water }) {
  const interior = slot => slot ? mat('paving', slot) : plain('pool tile', '#5fa8c4', { roughness: .35 });
  const tile = interior(pool.materials?.interior), depth = pool.depth ?? 5;
  const poolWater = height - .25, ledgeTop = f => poolWater - (f.depth_in ?? 10) / 12;
  const ledges = (pool.features || []).filter(f => f.kind === 'ledge');
  const spas = (pool.features || []).filter(f => f.kind === 'spa').map(f => f.polygon);
  const slab = (poly, top) => spas.length ? cutSurface(poly, spas, height - depth, top) : polygon(poly, height - depth, top);
  for (const f of pool.features || []) {
    const featureMesh = (geometry, material, waterBody = pool.id || 'pool:0') => {
      const mesh = addMesh(group, geometry, material);
      Object.assign(mesh.userData, {kind:f.kind, pieceId:f.id, parentPieceId:pool.id || 'pool:0', waterBody}); return mesh;
    };
    const poly = f.polygon;
    if (f.kind === 'ledge') {
      featureMesh(slab(poly, ledgeTop(f)), tile);
    } else if (f.kind === 'steps') {
      const a = poly[f.entry_edge ?? 0], b = poly[((f.entry_edge ?? 0) + 1) % poly.length];
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]), sign = Math.sign(area(poly));
      const n = [-sign * (b[1] - a[1]) / l, sign * (b[0] - a[0]) / l];
      const distances = poly.map(p => (p[0] - a[0]) * n[0] + (p[1] - a[1]) * n[1]);
      const low = Math.min(...distances), high = Math.max(...distances), count = f.treads ?? 3;
      // Steps beside a tanning ledge start level with it, so the two read as one landing.
      const beside = ledges.filter(l => touches(poly, l.polygon)).map(ledgeTop);
      const treadTop = beside.length
        ? i => Math.max(...beside) - (Math.max(...beside) - (height - depth)) * i / count
        : i => height - depth * (i + 1) / (count + 1);
      // Clip triangulated pieces into bands; a concave outline can have several
      // disconnected pieces in a band. Each tread drops exactly one riser.
      for (let i = 0; i < count; i++) {
        const start = a.map((v, j) => v + n[j] * (low + (high - low) * i / count));
        const end = a.map((v, j) => v + n[j] * (low + (high - low) * (i + 1) / count));
        const slabs = [];
        for (let part of triangles(poly)) {
          part = clipHalf(part, start, [start[0] + n[1], start[1] - n[0]]);
          part = clipHalf(part, end, [end[0] - n[1], end[1] + n[0]]);
          if (part.length) slabs.push(slab(part, treadTop(i)));
        }
        const geometry = mergeGeometries(slabs);
        if (geometry) featureMesh(geometry, tile);
        slabs.forEach(g => g.dispose());
      }
    } else if (f.kind === 'spa') {
      const raised = (f.mode ?? 'raised') === 'raised', rise = raised ? (f.raise_in ?? 12) / 12 : 0;
      const wallTop = height + .3 + rise, copingTop = height + .45 + rise;
      const waterHeight = raised ? copingTop - 2 / 12 : height - .25;
      // The wall and its coping are as wide as the pool's coping. Where a flush spa's edge lies
      // on the pool's edge it has neither: the pool's own wall and coping stand there already.
      const wallWidth = (pool.coping ?? 1) > 0 ? pool.coping ?? 1 : .3;
      const shared = poly.map((a, i) => !raised && onEdge(a, poly[(i + 1) % poly.length], pool.polygon || []));
      const floor = waterHeight - (f.depth_in ?? 36) / 12, inner = basinOutline(poly, wallWidth, shared.some(Boolean) ? shared : null);
      const poolFloor = height - depth, wallBottom = Math.min(floor, poolFloor);
      const spaTile = interior(f.materials?.interior || pool.materials?.interior);
      featureMesh(polygon(inner, floor > poolFloor ? poolFloor : floor - .2, floor), spaTile, f.id);
      const benchWidth = (f.bench_width_in ?? 18) / 12, seatTop = waterHeight - (f.bench_in ?? 18) / 12;
      if (benchWidth > 0 && seatTop > floor) {
        const footwell = basinOutline(inner, benchWidth);
        featureMesh(polygon(inner, floor, seatTop, [footwell]), spaTile, f.id);
      }
      // Separate outer wall and tile liner, so wall slots never paint the basin.
      // Under the pool water the outer wall is the pool's own finish. Above it a raised spa
      // shows its cladding; a flush spa's wall ends at the pool edge, so it carries the
      // pool's waterline tile instead.
      const band = waterlineMaterial(f.materials?.waterline || pool.materials?.waterline, { mat, plain });
      const above = raised ? (f.materials?.wall ? mat('base', f.materials.wall) : mat('base'))
        : waterlineMaterial(pool.materials?.waterline, { mat, plain });
      const split = Math.min(wallTop, Math.max(wallBottom, raised ? poolWater : poolWater - WATERLINE_BELOW));
      const bandLow = Math.min(wallTop, Math.max(floor, waterHeight - WATERLINE_BELOW));
      poly.forEach((a, i) => {
        if (shared[i]) return;
        const j = (i + 1) % poly.length, b = poly[j], c = inner[j], d = inner[i];
        const middleA = a.map((v, k) => (v + d[k]) / 2), middleB = b.map((v, k) => (v + c[k]) / 2);
        if (split > wallBottom) featureMesh(polygon([a, b, middleB, middleA], wallBottom, split), tile);
        if (wallTop > split) featureMesh(polygon([a, b, middleB, middleA], split, wallTop), above);
        if (bandLow > floor) featureMesh(polygon([middleA, middleB, c, d], floor, bandLow), spaTile, f.id);
        if (wallTop > bandLow) featureMesh(polygon([middleA, middleB, c, d], bandLow, wallTop), band, f.id);
      });
      const copingSlot = f.materials?.coping || pool.materials?.coping;
      if (!shared.some(Boolean)) featureMesh(polygon(poly, wallTop, copingTop, [inner]), mat(copingRole, copingSlot));
      else if (!shared.every(Boolean)) {
        // One mitred piece per walled edge: a ring whose hole touches its outline cannot be cut.
        const pieces = poly.flatMap((a, i) => shared[i] ? []
          : [polygon([a, poly[(i + 1) % poly.length], inner[(i + 1) % poly.length], inner[i]], wallTop, copingTop)]);
        featureMesh(mergeGeometries(pieces), mat(copingRole, copingSlot));
        pieces.forEach(g => g.dispose());
      }
      const waterMaterial = spaWater(f);
      const waterMesh = geometry => {
        const object = addMesh(group, geometry, waterMaterial);
        Object.assign(object.userData, { kind: 'spa', pieceId: f.id, parentPieceId:pool.id || 'pool:0', part: 'water' });
        return object;
      };
      waterMesh(polygon(inner, waterHeight));
      if (raised && (f.spillover ?? true)) for (const [a, b] of sharedSegments(poly, pool.polygon)) {
        const n = [(b[1] - a[1]), -(b[0] - a[0])], l = Math.hypot(...n), sign = Math.sign(area(poly));
        const strip = [a, b, b.map((v, j) => v + sign * n[j] / l * .025), a.map((v, j) => v + sign * n[j] / l * .025)];
        waterMesh(polygon(strip, height - .25, waterHeight));
      }
    }
  }
}
