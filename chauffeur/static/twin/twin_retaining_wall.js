import * as THREE from 'three';
import { groundAt, segmentIntersection } from './twin_ground.js';
import { TERRAIN_STEP_FT } from './twin_terrain_mesh.js';

export const retainingWallRole = material => ({ stone: 'base', block: 'retaining_block', concrete: 'patio_concrete', brick: 'porch_brick', timber: 'retaining_timber' }[material] || 'base');

// Authored solids always use the high terrain sampling step on every tier so
// their receiver topology and bake UVs do not depend on the viewing device.
export function retainingWallGeometry(plan, pad, edge) {
  const positions = [], uvs = [], wall = pad.edges?.[edge]?.wall;
  const emit = (...vertices) => vertices.forEach(([p, h, u, v]) => { positions.push(p[0], h, -p[1]); uvs.push(u, v); });
  const quad = (a, b, c, d, cap = false) => {
    const dx = b[0][0] - a[0][0], dy = b[0][1] - a[0][1], length = Math.hypot(dx, dy);
    const mapped = [a, b, c, d].map(([p, h]) => [p, h, cap ? p[0] : (p[0] * dx + p[1] * dy) / length, cap ? -p[1] : h]);
    emit(mapped[0], mapped[1], mapped[2], mapped[0], mapped[2], mapped[3]);
  };
  if (wall && pad.edges[edge].edge === 'sharp') {
    const a = pad.polygon[edge], b = pad.polygon[(edge + 1) % pad.polygon.length];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const left = [-(b[1] - a[1]) / length, (b[0] - a[0]) / length];
    const inward = Math.sign(pad.polygon.reduce((area, p, i) => {
      const q = pad.polygon[(i + 1) % pad.polygon.length]; return area + p[0] * q[1] - p[1] * q[0];
    }, 0));
    const point = t => a.map((v, j) => v + (b[j] - v) * t);
    const sides = t => [-1, 1].map(sign => groundAt(plan, ...point(t).map((v, j) => v + sign * left[j] * 1e-5)));
    const cuts = [0, 1];
    for (let d = TERRAIN_STEP_FT; d < length; d += TERRAIN_STEP_FT) cuts.push(d / length);
    // Layer boundaries get their own one-sided samples, rather than a ramp
    // bridging a discontinuity in the lot surface.
    for (const layer of plan.site?.terraces || []) layer.polygon.forEach((c, i) => {
      const hit = segmentIntersection(a, b, c, layer.polygon[(i + 1) % layer.polygon.length]);
      if (hit) cuts.push(Math.hypot(hit[0] - a[0], hit[1] - a[1]) / length);
    });
    cuts.sort((a, b) => a - b);
    // If a blended layer passes through this pad's height, the body changes
    // side exactly at the crossing, rather than twisting across a grid cell.
    const crossings = [], difference = t => { const [right, left] = sides(t); return left - right; };
    for (let i = 0; i + 1 < cuts.length; i++) {
      let lo = cuts[i], hi = cuts[i + 1]; if (hi - lo < 1e-8) continue;
      const epsilon = Math.min(1e-7, (hi - lo) * 1e-5), first = difference(lo + epsilon);
      if (first * difference(hi - epsilon) >= 0) continue;
      for (let j = 0; j < 32; j++) {
        const mid = (lo + hi) / 2;
        if (first * difference(mid) > 0) lo = mid; else hi = mid;
      }
      crossings.push((lo + hi) / 2);
    }
    cuts.push(...crossings); cuts.sort((a, b) => a - b);
    for (let i = 0; i + 1 < cuts.length; i++) {
      const lo = cuts[i], hi = cuts[i + 1]; if (hi - lo < 1e-8) continue;
      const epsilon = Math.min(1e-7, (hi - lo) * 1e-5);
      const middle = sides((lo + hi) / 2);
      // With equal ground (a curb), keep the body on the pad's inside.
      const sign = Math.abs(middle[1] - middle[0]) < 1e-9 ? inward : middle[1] > middle[0] ? 1 : -1;
      const thickness = (wall.thickness_in ?? 8) / 12, above = (wall.above_in ?? 0) / 12;
      const p = point(lo), q = point(hi), back = p => p.map((v, j) => v + sign * left[j] * thickness);
      const atP = sides(lo + epsilon), atQ = sides(hi - epsilon);
      const low = [Math.min(...atP) - .5, Math.min(...atQ) - .5];
      const high = [Math.max(...atP) + above, Math.max(...atQ) + above];
      let ring = [[p, 0], [q, 1], [back(q), 1], [back(p), 0]];
      if (sign < 0) ring.reverse();
      const lower = ring.map(([p, j]) => [p, low[j]]);
      const upper = ring.map(([p, j]) => [p, high[j]]);
      for (let j = 0; j < 4; j++) { const k = (j + 1) % 4; quad(lower[j], lower[k], upper[k], upper[j]); }
      quad(...upper, true); quad(...[...lower].reverse(), true);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.computeVertexNormals(); return geometry;
}
