import * as THREE from '../../vendor/three-r187/three.module.js';
import { FT } from '../twin_light_math.js';

export const fixturePoint = p => new THREE.Vector3(p[0] * FT, p[2] * FT, -p[1] * FT);
export const facingNormal = facing => Array.isArray(facing) ? [...facing] : facing === 'up' ? [0,0,1] : facing === 'out' ? [0,-1,0] : [0,0,-1];
export function fixtureRotation(emitter, along) {
  let normal = emitter.normal || facingNormal(emitter.facing);
  if (along && ['out', 'in'].includes(emitter.facing) && Math.hypot(along.x, along.z) > 1e-10) {
    const sign = emitter.facing === 'out' ? 1 : -1;
    normal = [-sign * along.z, -sign * along.x, 0];
  }
  const z = new THREE.Vector3(-normal[0], -normal[2], normal[1]).normalize();
  let x = along?.clone() || new THREE.Vector3(1, 0, 0);
  x.addScaledVector(z, -x.dot(z));
  if (x.lengthSq() < 1e-10) x = new THREE.Vector3(0, 1, 0).addScaledVector(z, -z.y);
  if (x.lengthSq() < 1e-10) x.set(0, 0, 1);
  x.normalize();
  if (!along) x.applyAxisAngle(z.clone().negate(), (emitter.rotation_deg || 0) * Math.PI / 180);
  const y = new THREE.Vector3().crossVectors(z, x).normalize();
  return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
}

export function linePieces(emitter) {
  const path = emitter.path.map(fixturePoint), lengths = path.slice(1).map((p, i) => p.distanceTo(path[i]));
  const total = lengths.reduce((a, b) => a + b, 0);
  if (total <= 0) return [];
  const count = Math.min(4, Math.max(1, Math.ceil(total / (4 * FT))));
  const sample = distance => {
    let offset = 0;
    for (let i = 0; i < lengths.length; i++) {
      if (distance <= offset + lengths[i] || i === lengths.length - 1)
        return path[i].clone().lerp(path[i + 1], lengths[i] ? (distance - offset) / lengths[i] : 0);
      offset += lengths[i];
    }
  };
  return Array.from({length: count}, (_, i) => {
    const a = sample(i * total / count), b = sample((i + 1) * total / count);
    return {position: sample((i + .5) * total / count), width: total / count,
      height: emitter.width_in / 12 * FT, rotation: fixtureRotation(emitter, b.sub(a))};
  });
}

