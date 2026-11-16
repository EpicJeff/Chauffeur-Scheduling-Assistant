import * as THREE from 'three';
import { effectMesh, splashRing, waterMaterial } from './water_material.js';

export function buildBubbler() {
  const group = new THREE.Group();
  const profile = Array.from({length:25}, (_, i) => {const a=i/24*Math.PI/2;return new THREE.Vector2(Math.sin(a),Math.cos(a));});
  const body = effectMesh(new THREE.LatheGeometry(profile, 48), waterMaterial(1));
  const ring = splashRing(); ring.position.y=.015; group.add(body,ring);
  return {group, pose(size) {
    const reach=.25+size*.45;
    body.scale.set(reach,size,reach);
    ring.scale.set(reach*1.35,1,reach*1.35);
  }};
}
