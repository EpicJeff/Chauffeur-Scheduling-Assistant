import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { FT } from '../twin_light_math.js';
import { paletteColour, validPalette } from './light_colours.js';

export const fixturePoint = p => new THREE.Vector3(p[0] * FT, p[2] * FT, -p[1] * FT);
export const facingNormal = facing => Array.isArray(facing) ? [...facing] : facing === 'up' ? [0,0,1] : facing === 'out' ? [0,-1,0] : [0,0,-1];
const materials = new Map();
function materialFor(key, channels, vertexColors = false) {
  if (!materials.has(key)) materials.set(key, {refs: 0, material: new THREE.MeshBasicMaterial({
    color: new THREE.Color(...channels.map(v => v / 255)), toneMapped: false, side: THREE.DoubleSide, vertexColors})});
  const entry = materials.get(key); entry.refs++; return entry.material;
}

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
    const start = i * total / count, end = (i + 1) * total / count;
    let walked = 0;
    // A boundary corner belongs to the piece starting there, exactly once.
    const inside = path.filter((p, j) => { if (j) walked += lengths[j - 1]; return j > 0 && j < path.length - 1 && walked >= start && walked < end; });
    return {t: (i + .5) / count, path: [a.clone(), ...inside, b.clone()], position: sample((i + .5) * total / count), width: total / count,
      height: emitter.width_in / 12 * FT, rotation: fixtureRotation(emitter, b.sub(a))};
  });
}

export function createFixtureGlow(scene, emitter) {
  let geometry;
  const sections = [];
  if (emitter.shape === 'line') {
    const radius = emitter.width_in / 24 * FT, parts = [];
    let offset = 0;
    for (const piece of linePieces(emitter)) {
      const points = piece.path;
      points.slice(1).forEach((p, i) => {
        if (!p.equals(points[i])) parts.push(new THREE.TubeGeometry(new THREE.LineCurve3(points[i], p), 1, radius, 8, false));
        if (i < points.length - 2) parts.push(new THREE.SphereGeometry(radius, 8, 4).translate(p.x, p.y, p.z));
      });
      const end = parts.reduce((sum, part) => sum + part.attributes.position.count, 0);
      sections.push({start: offset, end, t: piece.t}); offset = end;
    }
    geometry = parts.length ? mergeGeometries(parts) : new THREE.BufferGeometry();
    for (const part of parts) part.dispose();
  } else geometry = new THREE.PlaneGeometry(emitter.size_ft[0] * FT, emitter.size_ft[1] * FT);
  let bucket = '0,0,0', paletteKey = '';
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
    update(rgb, brightness, shown, palette) {
      mesh.visible = !!shown && brightness > 0;
      if (!mesh.visible) return;
      const multicolour = emitter.shape === 'line' && validPalette(palette) && palette.length > 1;
      const nextPalette = multicolour ? JSON.stringify(palette) : '';
      if (multicolour && nextPalette !== paletteKey) {
        if (!geometry.attributes.color) geometry.setAttribute('color',
          new THREE.Float32BufferAttribute(new Float32Array(geometry.attributes.position.count * 3), 3));
        const colors = geometry.attributes.color;
        for (const section of sections) {
          const color = new THREE.Color().setRGB(...paletteColour(palette, section.t).map(v => v / 255), THREE.SRGBColorSpace);
          for (let i = section.start; i < section.end; i++) colors.setXYZ(i, color.r, color.g, color.b);
        }
        colors.needsUpdate = true;
      }
      paletteKey = nextPalette;
      const color = new THREE.Color().setRGB(...(multicolour ? [255, 255, 255] : rgb).map(v => v / 255), THREE.SRGBColorSpace).multiplyScalar(brightness);
      const channels = color.toArray().map(v => Math.round(v * 255));
      const key = (multicolour ? 'palette:' : '') + channels.join(',');
      if (key === bucket) return;
      release();
      mesh.material = materialFor(key, channels, multicolour); bucket = key;
    },
    stop() { mesh.removeFromParent(); geometry.dispose(); release(); },
  };
}
