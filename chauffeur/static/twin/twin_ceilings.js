import * as THREE from 'three';
import { clipHalf, cutPolygons } from './pool_features.js';

// Clip the room to the actual downward faces of its supporting slabs/roof.
// Nearer slabs claim their footprint first; stair holes and partial storeys
// leave the remainder for the roof. Each patch stays in its support's domain.
export function ceilingPatches(room, supports) {
  const covered = [], patches = new Map();
  for (const { group, positions } of supports) {
    const output = patches.get(group) || [];
    for (let i = 0; i < positions.length; i += 9) {
      const tri = [0, 3, 6].map(j => positions.slice(i + j, i + j + 3));
      const [a, b, c] = tri;
      const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
      if (Math.abs(cross) < 1e-8) continue;
      const height = p => {
        const u = ((p[0] - a[0]) * (c[1] - a[1]) - (p[1] - a[1]) * (c[0] - a[0])) / cross;
        const v = ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) / cross;
        return a[2] + u * (b[2] - a[2]) + v * (c[2] - a[2]) - .02;
      };
      for (let poly of cutPolygons(room.polygon, covered)) {
        for (let j = 0; j < 3 && poly.length; j++) poly = clipHalf(poly, tri[j], tri[(j + 1) % 3], Math.sign(cross));
        if (!poly.length) continue;
        covered.push(poly);
        if (THREE.ShapeUtils.isClockWise(poly.map(p => new THREE.Vector2(...p)))) poly.reverse();
        for (let j = 1; j + 1 < poly.length; j++)
          for (const p of [poly[0], poly[j + 1], poly[j]]) output.push(p[0], p[1], height(p));
      }
    }
    if (output.length) patches.set(group, output);
  }
  return patches;
}
