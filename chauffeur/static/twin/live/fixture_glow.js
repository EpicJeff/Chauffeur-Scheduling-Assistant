import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { FT } from '../twin_light_math.js';

import { fixturePoint, fixtureRotation } from './fixture_geometry.js';
export { fixturePoint, fixtureRotation, facingNormal, linePieces } from './fixture_geometry.js';
const materials = new Map();
function materialFor(key, channels) {
  if (!materials.has(key)) materials.set(key, {refs: 0, material: new THREE.MeshBasicMaterial({
    color: new THREE.Color(...channels.map(v => v / 255)), toneMapped: false, side: THREE.DoubleSide})});
  const entry = materials.get(key); entry.refs++; return entry.material;
}

export function createFixtureGlow(scene, emitter) {
  let geometry;
  if (emitter.shape === 'line') {
    const points = emitter.path.map(fixturePoint), radius = emitter.width_in / 24 * FT, parts = [];
    points.slice(1).forEach((p, i) => {
      if (!p.equals(points[i])) parts.push(new THREE.TubeGeometry(new THREE.LineCurve3(points[i], p), 1, radius, 8, false));
      if (i < points.length - 2) parts.push(new THREE.SphereGeometry(radius, 8, 4).translate(p.x, p.y, p.z));
    });
    geometry = parts.length ? mergeGeometries(parts) : new THREE.BufferGeometry();
    for (const part of parts) part.dispose();
  } else geometry = new THREE.PlaneGeometry(emitter.size_ft[0] * FT, emitter.size_ft[1] * FT);
  let bucket = '0,0,0';
  const mesh = new THREE.Mesh(geometry, materialFor(bucket, [0, 0, 0])); mesh.visible = false; mesh.userData.fixtureGlow = emitter.fixture_id;
  if (emitter.shape === 'area') { mesh.position.copy(fixturePoint(emitter.at)); mesh.quaternion.copy(fixtureRotation(emitter)); }
  scene.add(mesh);
  function release() {
    if (!bucket) return;
    const entry = materials.get(bucket);
    if (--entry.refs === 0) { entry.material.dispose(); materials.delete(bucket); }
    bucket = null;
  }
  return {
    mesh,
    update(rgb, brightness, shown) {
      mesh.visible = !!shown && brightness > 0;
      if (!mesh.visible) return;
      const color = new THREE.Color().setRGB(...rgb.map(v => v / 255), THREE.SRGBColorSpace).multiplyScalar(brightness);
      const channels = color.toArray().map(v => Math.round(v * 255));
      const key = channels.join(',');
      if (key === bucket) return;
      release();
      mesh.material = materialFor(key, channels); bucket = key;
    },
    stop() { mesh.removeFromParent(); geometry.dispose(); release(); },
  };
}
