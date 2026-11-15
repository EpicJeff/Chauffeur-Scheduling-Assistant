import * as THREE from '../../vendor/three-r187/three.module.js';
import { FT, CANDELA } from '../twin_light_math.js';
import { fixturePoint, fixtureRotation, linePieces } from '../live/fixture_geometry.js';
import { lightSource } from './reach.js';
import { TIERS } from '../twin_tiers.js';

export const kindOf = emitters => emitters.length > 1 ? 3 : emitters[0].shape === 'spot' ? 1
  : ['line', 'area'].includes(emitters[0].shape) ? 2 : 0;
export const reachWindow = (d, reach) => reach > 0 ? Math.max(0, 1 - (d / reach) ** 4) ** 2 * (d < reach ? 1 : 0) : 0;
export function coneWindow(cosine, outer, inner) {
  const t = inner === outer ? +(cosine >= outer) : Math.max(0, Math.min(1, (cosine - outer) / (inner - outer)));
  return t * t * (3 - 2 * t);
}
export function rectPieces(e) {
  const rows = e.shape === 'line' ? linePieces(e) : [{position: fixturePoint(e.at),
    width: e.size_ft[0] * FT, height: e.size_ft[1] * FT, rotation: fixtureRotation(e)}];
  const area = rows.reduce((s, p) => s + p.width * p.height, 0);
  const luminance = area ? e.output_lm * e.output_fraction / (Math.PI * area) : 0;
  return rows.map(p => ({...p, luminance,
    u: new THREE.Vector3(p.width / 2, 0, 0).applyQuaternion(p.rotation),
    v: new THREE.Vector3(0, p.height / 2, 0).applyQuaternion(p.rotation),
    normal: new THREE.Vector3(0, 0, -1).applyQuaternion(p.rotation)}));
}
export function rectClosest(p, point) {
  const delta = point.clone().sub(p.position);
  return p.position.clone().addScaledVector(p.u, Math.max(-1, Math.min(1, delta.dot(p.u) / p.u.lengthSq())))
    .addScaledVector(p.v, Math.max(-1, Math.min(1, delta.dot(p.v) / p.v.lengthSq())));
}
export function exactRects(lights, tier) {
  return new Set(lights.filter(l => l.kind === 2).sort((a, b) =>
    (b.emitters[0].output_lm - a.emitters[0].output_lm) || (a.device < b.device ? -1 : a.device > b.device ? 1 : 0))
    .slice(0, (TIERS[tier] || TIERS.low).bakedRects).map(l => l.device));
}
const jitter = (source, range, cd, emitter) => Array.from({length: 16}, (_, i) => {
  const z = 1 - 2 * (i + .5) / 16, a = i * 2.3999632297, radius = Math.sqrt(1 - z * z) * .15 * FT;
  return {source: source.clone().add(new THREE.Vector3(Math.cos(a) * radius, z * .15 * FT, Math.sin(a) * radius)),
    origin: source, range, cd, weight: 1 / 16, emitter, normal: new THREE.Vector3(), axis: new THREE.Vector3(), outer: -1, inner: -1};
});
// source is supplied by reach.js for legacy lamps, preserving its exact arithmetic.
export function emitterSamples(emitters) {
  return emitters.flatMap((e, emitter) => {
    if (e.shape === 'point' || e.shape === 'spot') {
      const cone = e.cone_deg * Math.PI / 360;
      const cd = e.output_lm * e.output_fraction / (e.shape === 'point' ? 4 * Math.PI : 2 * Math.PI * (1 - Math.cos(cone)));
      const samples = jitter(new THREE.Vector3(...e.position), e.range * FT, cd, emitter);
      if (e.shape === 'spot') for (const s of samples) {
        s.axis.copy(fixturePoint(e.aim)).sub(s.origin).normalize();s.outer = Math.cos(cone);s.inner = Math.cos(cone * (1 - e.softness));
      }
      return samples;
    }
    const pieces = rectPieces(e), area = pieces.reduce((sum, p) => sum + p.width * p.height, 0);
    const extent = e.shape === 'line' ? pieces.reduce((s, p) => s + p.width, 0) / (1.5 * FT) : area / (1.5 * FT) ** 2;
    const count = Math.min(48, Math.max(16, Math.ceil(extent)));
    // Allocate a whole number of strata per piece. The last takes the remainder.
    let used = 0;
    return pieces.flatMap((p, index) => {
      const n = index === pieces.length - 1 ? count - used : Math.max(1, Math.round(count * p.width * p.height / area));used += n;
      const nx = Math.max(1, Math.min(n, Math.round(Math.sqrt(n * p.width / p.height)))), ny = Math.ceil(n / nx);
      return Array.from({length: n}, (_, i) => ({source: p.position.clone()
        .addScaledVector(p.u, 2 * ((i % nx + .5) / nx) - 1)
        .addScaledVector(p.v, 2 * ((Math.floor(i / nx) + .5) / ny) - 1), origin: p.position,
      range: e.range * FT, cd: p.luminance * p.width * p.height, weight: 1 / n,
      visibilityWeight: p.width * p.height / area / n, normal: p.normal, axis: new THREE.Vector3(), outer: -1, inner: -1, emitter, piece: p}));
    });
  });
}
export function legacySamples(source, range) { return jitter(source, range, CANDELA, 0); }
export function bakeSamples(plan, light) {
  if (light.emitters) return emitterSamples(light.emitters);
  const {source, range} = lightSource(plan, light);return legacySamples(source, range);
}
export const decodeIrradiance = (value, scale) => value * value * scale;
export function sampleValue(samples, point, normal, visible, kind, scale) {
  let visibility = 0, irradiance = 0;
  for (const s of samples) {
    const delta = s.source.clone().sub(point), d = delta.length(), direction = delta.clone().divideScalar(Math.max(d, 1e-4));
    const distance = s.piece ? rectClosest(s.piece, point).distanceTo(point) : d;
    const cutoff = reachWindow(distance, s.range);
    if (!cutoff) continue;
    const facing = s.normal.lengthSq() ? Math.max(0, -s.normal.dot(direction)) : 1;
    const cone = s.outer > -1 ? coneWindow(-s.axis.dot(direction), s.outer, s.inner) : 1;
    const seen = visible(s) * (facing > 0 ? 1 : 0);
    visibility += seen * (s.visibilityWeight ?? s.weight);
    irradiance += s.cd * s.weight * facing * cone * cutoff / Math.max(d * d, .01) * Math.max(0, normal.dot(direction)) * seen;
  }
  return {value: kind === 3 ? Math.sqrt(Math.min(1, irradiance / scale)) : visibility, irradiance};
}
function edge(a, b) {
  const x = a.dot(b), y = Math.abs(x), v = (.8543985 + (.4965155 + .0145206 * y) * y) / (3.417594 + (4.1616724 + y) * y);
  return new THREE.Vector3().crossVectors(a, b).multiplyScalar(x > 0 ? v : .5 / Math.sqrt(Math.max(1 - x * x, 1e-7)) - v);
}
// Identity LTC polygon integral, matching three's LTC_Evaluate without a table.
export function rectIrradiance(p, point, normal, exact = true, range = 18 * FT) {
  const toward = p.position.clone().sub(point), d = toward.length();
  if (p.normal.dot(toward) >= 0) return 0;
  const cutoff = reachWindow(rectClosest(p, point).distanceTo(point), range);
  if (!exact) return p.luminance * p.width * p.height * Math.max(0, normal.dot(toward) / d)
    * Math.max(0, -p.normal.dot(toward) / d) * cutoff / Math.max(d * d, .01);
  const coords = [[1,-1],[-1,-1],[-1,1],[1,1]].map(([u,v]) => toward.clone().addScaledVector(p.u,u).addScaledVector(p.v,v).normalize());
  const f = coords.reduce((sum, a, i) => sum.add(edge(a, coords[(i + 1) % 4])), new THREE.Vector3());
  const len = f.length(), result = Math.max(0, (len * len - f.dot(normal)) / (len + 1));
  return p.luminance * Math.PI * result * cutoff;
}
