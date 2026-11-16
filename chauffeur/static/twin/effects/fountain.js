import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { effectMesh, splashRing, waterMaterial } from './water_material.js';

export function buildFountain() {
  const group = new THREE.Group();
  const core = [[.07,0],[.07,.3],[.06,.7],[.09,.94],[.13,1]].map(p => new THREE.Vector2(...p));
  const skirt = Array.from({length:25}, (_, i) => { const t=i/24; return new THREE.Vector2(.13+.87*t,1-t*t); });
  const parts = [core, skirt].map((profile, part) => {
    const geometry = new THREE.LatheGeometry(profile, 48), count = geometry.attributes.position.count;
    // The shader reads the skirt from the spare outward channel.
    const mark = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) mark[i * 3 + 1] = part;
    geometry.setAttribute('outward', new THREE.Float32BufferAttribute(mark, 3));
    return geometry;
  });
  const body = effectMesh(mergeGeometries(parts), waterMaterial(0)); parts.forEach(g => g.dispose());
  const ring = splashRing(); ring.position.y = .015; group.add(body, ring);
  return {group, pose(size) {
    const reach = .1 + size * .15;
    body.scale.set(reach, size, reach);
    ring.scale.set(reach * 1.25, 1, reach * 1.25);
  }};
}
