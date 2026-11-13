import * as THREE from 'three';
import { groundAt, segmentIntersection } from './twin_ground.js';
import { terrainGeometry } from './twin_terrain_mesh.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

export const PORCH_SLAB_FT = .25;
export const porchFoundationRole = material => ({ stone: 'base', brick: 'porch_brick', concrete: 'patio_concrete' }[material] || 'base');

// Intersect inward-offset edge lines. Mitres preserve the requested lip on
// angled and concave outlines, in either winding (not a centroid scale).
export function insetPorch(poly, lip) {
  poly = poly.filter((p, i) => Math.hypot(p[0] - poly[(i + poly.length - 1) % poly.length][0], p[1] - poly[(i + poly.length - 1) % poly.length][1]) > 1e-9);
  if (poly.length < 3) return [];
  const area = poly.reduce((sum, p, i) => { const q = poly[(i + 1) % poly.length]; return sum + p[0] * q[1] - p[1] * q[0]; }, 0);
  const ring = area > 0 ? poly : [...poly].reverse();
  if (!lip) return ring.map(p => [...p]);
  const lines = ring.map((p, i) => {
    const q = ring[(i + 1) % ring.length], dx = q[0] - p[0], dy = q[1] - p[1], length = Math.hypot(dx, dy);
    return { p: [p[0] - dy / length * lip, p[1] + dx / length * lip], d: [dx / length, dy / length] };
  });
  return lines.map((line, i) => {
    const prev = lines[(i + lines.length - 1) % lines.length], [dx, dy] = prev.d, [ex, ey] = line.d;
    const den = dx * ey - dy * ex;
    if (Math.abs(den) < 1e-9) return line.p;
    const t = ((line.p[0] - prev.p[0]) * ey - (line.p[1] - prev.p[1]) * ex) / den;
    return [prev.p[0] + dx * t, prev.p[1] + dy * t];
  });
}

export function porchPlinthGeometry(plan, building, porch, top, base) {
  const outline = insetPorch(porch.polygon, (porch.foundation?.lip_in ?? 1) / 12);
  const angle = (building.rotation || 0) * Math.PI / 180, pos = building.position || [0, 0];
  const world = p => [pos[0] + Math.cos(angle) * p[0] - Math.sin(angle) * p[1], pos[1] + Math.sin(angle) * p[0] + Math.cos(angle) * p[1]];
  const points = outline.map(world), positions = [], uvs = [];
  const emit = (...vertices) => vertices.forEach(([p, h, u]) => { positions.push(p[0], h, -p[1]); uvs.push(u, h); });
  outline.forEach((a, i) => {
    const b = outline[(i + 1) % outline.length], wa = points[i], wb = points[(i + 1) % points.length];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]), cuts = [0, 1];
    for (let d = 1; d < length; d++) cuts.push(d / length);
    // Split at every layer boundary. Each interval samples from its own side
    // of a sharp step: two heights at one x/y give a vertical skirt, no ramp.
    for (const pad of plan.site?.terraces || []) pad.polygon.forEach((c, j) => {
      const hit = segmentIntersection(wa, wb, c, pad.polygon[(j + 1) % pad.polygon.length]);
      if (hit) cuts.push(Math.hypot(hit[0] - wa[0], hit[1] - wa[1]) / length);
    });
    cuts.sort((a, b) => a - b);
    const point = t => a.map((v, k) => v + (b[k] - v) * t);
    const bottom = t => Math.min(top, groundAt(plan, ...world(point(t))) - base);
    for (let j = 0; j + 1 < cuts.length; j++) {
      const lo = cuts[j], hi = cuts[j + 1]; if (hi - lo < 1e-8) continue;
      const p = point(lo), q = point(hi), epsilon = Math.min(1e-7, (hi - lo) * 1e-5);
      const p0 = [p, bottom(lo + epsilon), lo * length], q0 = [q, bottom(hi - epsilon), hi * length];
      const p1 = [p, top, lo * length], q1 = [q, top, hi * length];
      // insetPorch is CCW in lot XY; mapping Y to -Z makes this order outward.
      emit(p0, q0, q1, p0, q1, p1);
    }
  });
  const sides = new THREE.BufferGeometry();
  sides.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  sides.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2)); sides.computeVertexNormals();
  const cap = new THREE.ShapeGeometry(new THREE.Shape(outline.map(p => new THREE.Vector2(...p))))
    .rotateX(-Math.PI / 2).translate(0, top, 0);
  // Close the underside against the same layered terrain, including its step
  // skirts. All tiers use this same authored tessellation for baked lighting.
  const ground = terrainGeometry(plan, points, 'high', { skirts: true });
  const gp = ground.attributes.position;
  for (let i = 0; i < gp.count; i++) gp.setY(i, Math.min(base + top, gp.getY(i)));
  const index = ground.index;
  for (let i = 0; i < index.count; i += 3) { const a = index.getX(i); index.setX(i, index.getX(i + 2)); index.setX(i + 2, a); }
  ground.translate(-pos[0], -base, pos[1]).rotateY(-angle); ground.computeVertexNormals();
  const capPlain = cap.index ? cap.toNonIndexed() : cap, groundPlain = ground.toNonIndexed();
  const result = mergeGeometries([capPlain, sides, groundPlain]);
  for (const geometry of new Set([cap, capPlain, ground, groundPlain, sides])) geometry.dispose();
  return result;
}
