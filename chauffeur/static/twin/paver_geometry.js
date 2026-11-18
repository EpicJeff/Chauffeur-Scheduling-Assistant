import * as THREE from 'three';
import { groundAt } from './twin_ground.js';
import { paverSettings } from './paver_layout.js';

// One merged prism per stone. The top carries exactly one tile of the material
// (`tileFt`, the feet its maps repeat over), so the texture fits each stone from
// edge to edge (owner, 2026-11-18); a cut stone shows its share of that tile.
// `lay: 'ground'` tilts each stone onto the ground under its corners; 'level'
// sets it flat at the ground under its centre.
export function paverGeometry(plan, path, layout, tileFt = [4, 4]) {
  const positions = [], uvs = [], level = paverSettings(path)?.lay === 'level', lift = path.elevation || 0;
  for (const p of layout.pavers) {
    const poly = p.polygon, n = poly.length, flat = groundAt(plan, ...p.centre);
    const ground = q => (level ? flat : groundAt(plan, ...q)) + lift;
    // Offset each convex edge inward; clipped pavers retain their actual outline.
    const centre = poly.reduce((a, q) => a.map((v, k) => v + q[k]/n), [0, 0]);
    const normals = poly.map((a, i) => { const b = poly[(i+1)%n], d = Math.hypot(b[0]-a[0], b[1]-a[1]); return [(a[1]-b[1])/d, (b[0]-a[0])/d]; });
    const bevel = Math.min(.25/12, ...normals.map((v, i) => (v[0]*(centre[0]-poly[i][0])+v[1]*(centre[1]-poly[i][1]))/3));
    const inset = poly.map((a, i) => {
      const u = normals[(i+n-1)%n], v = normals[i], d = 1 + u[0]*v[0] + u[1]*v[1];
      return a.map((x, k) => x + bevel*(u[k]+v[k])/Math.max(1e-8, d));
    });
    // Stone-local 0..1 across the whole (uncut) stone, scaled to one tile.
    const c = Math.cos(p.angle), s = Math.sin(p.angle), [length, width] = p.size || [1, 1];
    const tileUv = q => {
      const dx = q[0]-p.centre[0], dy = q[1]-p.centre[1];
      return [((dx*c + dy*s)/length + .5)*tileFt[0], ((-dx*s + dy*c)/width + .5)*tileFt[1]];
    };
    const vertex = (q, y, uv) => ({ at: [q[0], y, -q[1]], uv });
    const triangle = (...vs) => { for (const v of vs) { positions.push(...v.at); uvs.push(...v.uv); } };
    const upper = inset.map(q => vertex(q, ground(q) + 1/12, tileUv(q)));
    for (let i = 1; i < n - 1; i++) triangle(upper[0], upper[i], upper[i+1]);
    // Sides run the material along the edge and up the face, in feet. No
    // bottom face: the stone stands in the ground and it is never seen.
    let run = 0;
    for (let i = 0; i < n; i++) {
      const j = (i+1)%n, a = poly[i], b = poly[j], edge = Math.hypot(b[0]-a[0], b[1]-a[1]);
      const lower = [vertex(a, ground(a) - 2/12, [run, 0]), vertex(b, ground(b) - 2/12, [run+edge, 0])];
      const shoulder = [vertex(a, ground(a) + 1/12 - bevel, [run, 3/12 - bevel]), vertex(b, ground(b) + 1/12 - bevel, [run+edge, 3/12 - bevel])];
      const top = [vertex(inset[i], ground(inset[i]) + 1/12, [run, 3/12]), vertex(inset[j], ground(inset[j]) + 1/12, [run+edge, 3/12])];
      triangle(lower[0], lower[1], shoulder[1]); triangle(lower[0], shoulder[1], shoulder[0]);
      triangle(shoulder[0], shoulder[1], top[1]); triangle(shoulder[0], top[1], top[0]);
      run += edge;
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs,2));
  geometry.computeVertexNormals(); geometry.userData.paverPath = true;
  return geometry;
}
