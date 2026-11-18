import * as THREE from 'three';
import { effectMesh, splashRing } from './water_material.js';
import { columnMaterial } from './sheet_material.js';

// A bubbler is a narrow column of aerated water, lit like the pool and mostly
// white with bubbles, turbulence climbing it; it boils white at the foot,
// where foam spreads out across the water.
export function buildBubbler() {
  const group = new THREE.Group();
  // Tip first, so uv.y runs 0 at the tip to 1 at the foot.
  const profile = [[0,1],[.2,.992],[.38,.965],[.52,.92],[.63,.86],[.72,.78],[.8,.68],[.86,.56],[.9,.44],
    [.94,.32],[.98,.2],[1.04,.1],[1.14,.04],[1.3,0]].map(p => new THREE.Vector2(...p));
  const curve = new THREE.SplineCurve(profile).getPoints(40);
  for (const p of curve) p.set(Math.max(0, p.x), Math.min(1, Math.max(0, p.y)));
  curve[0].set(0, 1); curve[40].y = 0;
  const body = effectMesh(new THREE.LatheGeometry(curve, 48), columnMaterial());
  const ring = splashRing(4, .18); ring.position.y=.015; group.add(body,ring);
  return {group, pose(size) {
    // More flow lifts the column; the nozzle sets its width, so that barely grows.
    const reach=.12+size*.03;
    body.scale.set(reach,size,reach); body.material.uniforms.fall.value=size;
    ring.scale.set(reach*4.5,1,reach*4.5);
  }};
}
