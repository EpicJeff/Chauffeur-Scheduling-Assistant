import * as THREE from 'three';
import { groundAt, buildingBase, segmentIntersection } from './twin_ground.js';
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
  const ground = terrainGeometry(plan, points, 'high', { skirts: true, retainWallSkirts: true });
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


export const POST_SLAB_FT = 4 / 12;
export const PORCH_BEAM_FT = 8 / 12;
export function porchFoundation(value = {}) {
  return { type: 'posts', lip_in: 1, post_in: 6, post_shape: 'square', spacing_ft: 8,
    skirt: 'lattice', ...value, materials: { posts: null, skirt: null,
      solid: value.material ? { id: porchFoundationRole(value.material) } : null, ...value.materials } };
}
const worldPoint = (building, p) => {
  const a = (building.rotation || 0) * Math.PI / 180, pos = building.position || [0, 0];
  return [pos[0] + Math.cos(a) * p[0] - Math.sin(a) * p[1], pos[1] + Math.sin(a) * p[0] + Math.cos(a) * p[1]];
};
export function porchOnGrade(plan, building, porch, floor, base = buildingBase(plan, building)) {
  return porch.polygon.every(p => Math.abs(base + floor - groundAt(plan, ...worldPoint(building, p))) <= 9 / 12 + 1e-8);
}

function merged(parts) {
  if (!parts.length) return null;
  const plain = parts.map(g => g.index ? g.toNonIndexed() : g);
  const result = mergeGeometries(plain);
  for (const g of new Set([...parts, ...plain])) g.dispose();
  return result;
}
// Clip a convex panel interval to a diagonal strip. Both families of strips
// are closed prisms, with real air between them (also seen by bake rays).
function clip(poly, distance) {
  const out = [];
  poly.forEach((p, i) => {
    const q = poly[(i + 1) % poly.length], a = distance(p), b = distance(q);
    if (a >= -1e-9) out.push(p);
    if ((a > 0 && b < 0) || (a < 0 && b > 0)) out.push(p.map((v, k) => v + (q[k] - v) * a / (a - b)));
  });
  return out;
}
function panelPrism(poly, a, unit, depth, offset = 0) {
  const shape = new THREE.Shape(poly.map(p => new THREE.Vector2(...p)));
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, steps: 1 });
  const x = new THREE.Vector3(unit[0], 0, -unit[1]), y = new THREE.Vector3(0, 1, 0);
  const z = new THREE.Vector3().crossVectors(x, y);
  return g.translate(0, 0, offset - depth / 2).applyMatrix4(new THREE.Matrix4().makeBasis(x, y, z).setPosition(a[0], 0, -a[1]));
}

// Geometry is authored once, in building-local feet, independent of render tier.
// Return the layout too so the shelf/tests can describe the actual construction.
export function porchSupportGeometry(plan, building, porch, floor, base = buildingBase(plan, building)) {
  const f = porchFoundation(porch.foundation), width = f.post_in / 12;
  const slabBottom = floor - POST_SLAB_FT, beamBottom = slabBottom - PORCH_BEAM_FT;
  // Lip is to the outer post faces; the corner centres sit half a post farther in.
  const outline = insetPorch(porch.polygon, f.lip_in / 12 + width / 2);
  const posts = [], spans = [], supports = [], skirts = [];
  const ground = p => groundAt(plan, ...worldPoint(building, p)) - base;
  outline.forEach((a, edge) => {
    const b = outline[(edge + 1) % outline.length], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (length < 1e-8) return;
    const unit = b.map((v, i) => (v - a[i]) / length), count = Math.max(1, Math.ceil(length / f.spacing_ft));
    const along = t => a.map((v, i) => v + unit[i] * t);
    const beam = new THREE.BoxGeometry(length + width, PORCH_BEAM_FT, width);
    beam.rotateY(Math.atan2(unit[1], unit[0])).translate((a[0] + b[0]) / 2, (slabBottom + beamBottom) / 2, -(a[1] + b[1]) / 2);
    supports.push(beam);
    for (let j = 0; j < count; j++) {
      const at = along(length * j / count), bottom = Math.min(slabBottom, ground(at));
      posts.push({ at, bottom, top: slabBottom, edge });
      if (bottom < slabBottom - 1e-8) {
        const g = f.post_shape === 'round' ? new THREE.CylinderGeometry(width / 2, width / 2, slabBottom - bottom, 16)
          : new THREE.BoxGeometry(width, slabBottom - bottom, width);
        supports.push(g.translate(at[0], (bottom + slabBottom) / 2, -at[1]));
      }
      const lo = length * j / count + width / 2, hi = length * (j + 1) / count - width / 2;
      if (hi <= lo) continue;
      spans.push({ edge, from: along(lo), to: along(hi), top: beamBottom });
      if (f.type !== 'enclosed') continue;
      const wa = worldPoint(building, a), wb = worldPoint(building, b), cuts = [lo, hi];
      for (let u = lo + 1; u < hi; u++) cuts.push(u);
      for (const pad of plan.site?.terraces || []) pad.polygon.forEach((c, i) => {
        const hit = segmentIntersection(wa, wb, c, pad.polygon[(i + 1) % pad.polygon.length]);
        if (hit) { const u = Math.hypot(hit[0] - wa[0], hit[1] - wa[1]); if (u > lo && u < hi) cuts.push(u); }
      });
      cuts.sort((a, b) => a - b);
      for (let k = 0; k + 1 < cuts.length; k++) {
        const u0 = cuts[k], u1 = cuts[k + 1], epsilon = Math.min(1e-7, (u1 - u0) / 10);
        if (u1 - u0 < 1e-8) continue;
        const bottom0 = Math.min(beamBottom, ground(along(u0 + epsilon))), bottom1 = Math.min(beamBottom, ground(along(u1 - epsilon)));
        if (Math.min(bottom0, bottom1) >= beamBottom - 1e-8) continue;
        const panel = [[u0, bottom0], [u1, bottom1], [u1, beamBottom], [u0, beamBottom]];
        if (f.skirt === 'panel') skirts.push(panelPrism(panel, a, unit, .5 / 12));
        else for (const sign of [-1, 1]) {
          const values = panel.map(([u, h]) => h + sign * u), spacing = .5, strip = 1 / 12;
          for (let n = Math.floor(Math.min(...values) / spacing); n <= Math.ceil(Math.max(...values) / spacing); n++) {
            const low = n * spacing, high = low + strip;
            let band = clip(panel, ([u, h]) => h + sign * u - low);
            band = clip(band, ([u, h]) => high - h - sign * u);
            const area = band.reduce((sum, p, i) => { const q = band[(i + 1) % band.length]; return sum + p[0] * q[1] - p[1] * q[0]; }, 0);
            if (band.length >= 3 && Math.abs(area) > 1e-8) skirts.push(panelPrism(band, a, unit, .5 / 12, sign * .25 / 12));
          }
        }
      }
    }
  });
  return { supports: merged(supports), skirt: merged(skirts), posts, spans, outline, slabBottom, beamBottom };
}
