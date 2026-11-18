import * as THREE from 'three';
import { groundAt } from './twin_ground.js';

export function paverGeometry(plan, path, layout) {
  const positions = [], uvs = [];
  let seed = 0;
  for (const c of String(path.id || '')) seed = Math.imul(seed, 31) + c.charCodeAt(0) | 0;
  const hash = n => { n = Math.imul(n ^ n >>> 16, 0x21f0aaad); return ((n ^ n >>> 15) >>> 0) / 4294967296 * 64; };
  for (const p of layout.pavers) {
    const poly = p.polygon, n = poly.length, top = groundAt(plan, ...p.centre) + (path.elevation || 0) + 1/12;
    // Offset each convex edge inward; clipped pavers retain their actual outline.
    const centre = poly.reduce((a, q) => a.map((v, k) => v + q[k]/n), [0, 0]);
    const normals = poly.map((a, i) => { const b = poly[(i+1)%n], d = Math.hypot(b[0]-a[0], b[1]-a[1]); return [(a[1]-b[1])/d, (b[0]-a[0])/d]; });
    const bevel = Math.min(.25/12, ...normals.map((v, i) => (v[0]*(centre[0]-poly[i][0])+v[1]*(centre[1]-poly[i][1]))/3));
    const inset = poly.map((a, i) => {
      const u = normals[(i+n-1)%n], v = normals[i], d = 1 + u[0]*v[0] + u[1]*v[1];
      return a.map((x, k) => x + bevel*(u[k]+v[k])/Math.max(1e-8, d));
    });
    const offset = [hash(seed ^ Math.imul(p.index+1, 73856093)), hash(seed ^ Math.imul(p.index+1, 19349663))];
    const vertex = (q, y) => [q[0], y, -q[1]];
    const triangle = (a, b, c) => { for (const v of [a,b,c]) { positions.push(...v); uvs.push(v[0]+offset[0], v[2]+offset[1]); } };
    const lower = poly.map(q => vertex(q, top-3/12)), shoulder = poly.map(q => vertex(q, top-bevel)), upper = inset.map(q => vertex(q, top));
    for (let i=1;i<n-1;i++) { triangle(upper[0],upper[i],upper[i+1]); triangle(lower[0],lower[i+1],lower[i]); }
    for (let i=0;i<n;i++) {
      const j=(i+1)%n;
      triangle(lower[i],lower[j],shoulder[j]); triangle(lower[i],shoulder[j],shoulder[i]);
      triangle(shoulder[i],shoulder[j],upper[j]); triangle(shoulder[i],upper[j],upper[i]);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs,2));
  geometry.computeVertexNormals(); geometry.userData.paverPath = true;
  return geometry;
}
