import * as THREE from '../../vendor/three-r187/three.module.js';
import { FT, CANDELA, lightRange, LAMP_HEIGHT } from '../twin_light_math.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { fingerprint } from './geometry_key.js';
import { emitterSamples, rectPieces, coneWindow } from './fixture_terms.js';

// Match the live lamp's bulb height and range, including the ceiling inset.
export function lightSource(plan, light) {
  if (light.emitters?.length === 1 && ['point','spot'].includes(light.emitters[0].shape))
    return {source: new THREE.Vector3(...light.emitters[0].position), range: light.emitters[0].range * FT};
  if (light.emitters) {
    const samples = emitterSamples(light.emitters), source = new THREE.Vector3();
    for (const s of samples) source.addScaledVector(s.source, 1 / samples.length);
    return {source, range: Math.max(...samples.map(s => s.source.distanceTo(source) + s.range))};
  }
  // Object lamps (fire pits, lamp furniture) carry their world position: modes.js range.
  if (light.absolute) return { source: new THREE.Vector3(light.at[0] * FT, light.at[2] * FT, -light.at[1] * FT),
    range: (light.range ?? 18) * FT };
  // A yard-room light: its z is height above the local ground, its span the yard room's.
  if (light.yard) {
    const r = plan.site?.yard_rooms?.find(r => r.id === light.room);
    const span = r?.polygon?.length ? Math.max(...[0, 1].map(k => Math.max(...r.polygon.map(p => p[k])) - Math.min(...r.polygon.map(p => p[k]))), 1) : 10;
    const range = lightRange({ at: light.at }, null, null, r, span) * FT;
    return { source: new THREE.Vector3(light.at[0] * FT, (light.at[2] + groundAt(plan, light.at[0], light.at[1])) * FT, -light.at[1] * FT), range };
  }
  const b = plan.buildings?.find(b => b.id === light.building), l = b?.levels?.find(l => l.id === light.level);
  const r = b?.rooms?.find(r => r.id === light.room), floor = (b?.base || 0) + (l?.elevation || 0) + (r?.floor_offset_ft || 0);
  const standing = !!l && light.at[2] <= floor + .1;
  const z = standing ? floor + LAMP_HEIGHT : light.at[2];
  const span = r ? Math.max(...[0, 1].map(k => Math.max(...r.polygon.map(p => p[k])) - Math.min(...r.polygon.map(p => p[k]))), 1) : 10;
  const range = lightRange({ at: [light.at[0], light.at[1], z] }, b, l, r, span) * FT;
  const source = new THREE.Vector3(light.at[0] * FT,
    (z + buildingGround(plan, b)) * FT, -light.at[1] * FT);
  if (l && !standing && light.at[2] >= (b?.base || 0) + l.elevation + l.ceiling - .1) source.y -= .2 * FT;
  return { source, range };
}

const cached = new WeakMap();
const inverses = new WeakMap();
// The ground point under a heightfield chart closest to the light: the light clamped into the
// chart's tile, at the authored ground height there. From the plan, never from the tiered
// grid, so every tier computes the same reach (atlas.js).
function fieldClosest(chart, plan, source, out) {
  let inverse = inverses.get(chart.mesh);
  if (!inverse) { inverse = chart.mesh.matrixWorld.clone().invert(); inverses.set(chart.mesh, inverse); }
  // The field is [x0, lotY0, x1, lotY1] in the mesh's feet (lot y = -z).
  const local = out.copy(source).applyMatrix4(inverse), [u0, v0, u1, v1] = chart.field;
  const x = Math.min(u1, Math.max(u0, local.x)), y = Math.min(v1, Math.max(v0, -local.z));
  return out.set(x, groundAt(plan, x, y), -y).applyMatrix4(chart.mesh.matrixWorld);
}
const reaches = new WeakMap();
// Geometry is retained for live material edits, but both triangle colour input
// and per-light physical freshness must be recomputed for the affected layout.
export function invalidateMaterialReach(layout, ids) {
  const changed = new Set(ids);
  let used = false;
  for (const chart of layout.charts) if ([chart.mesh, ...(chart.proxies || []).map(p => p.mesh)]
    .some(mesh => changed.has(mesh.material.userData.materialId))) {
    cached.delete(chart); used = true;
  }
  if (used) reaches.delete(layout);
  return used;
}
const materialInput = mesh => [mesh.material.color?.toArray(), mesh.material.userData.materialId || null,
  mesh.material.userData.materialRevision ?? null];
const surfaceInput = chart => JSON.stringify([materialInput(chart.mesh), chart.density,
  ...(chart.proxies || []).map(p => materialInput(p.mesh))]);
function triangles(chart) {
  let data = cached.get(chart);
  if (data) return data;
  const pos = chart.mesh.geometry.attributes.position;
  const bounds=new THREE.Box3();
  const faces = chart.faces.map(f => {
    const t=new THREE.Triangle(...[0, 1, 2].map(k =>
      new THREE.Vector3().fromBufferAttribute(pos, f * 3 + k).applyMatrix4(chart.mesh.matrixWorld)));
    t.normal=t.getNormal(new THREE.Vector3());
    bounds.expandByPoint(t.a);bounds.expandByPoint(t.b);bounds.expandByPoint(t.c);
    return t;
  });
  data={faces,bounds,surface:new TextEncoder().encode(surfaceInput(chart))};
  cached.set(chart, data); return data;
}

export function reachLights(layout, lights, outer = true) {
  if (!layout.plan) return lights;
  if (!reaches.has(layout)) reaches.set(layout, new Map());
  const saved = reaches.get(layout);
  // Only the complete, outer device list can retire a cached group. A nested
  // emitter sweep must not delete its siblings (or the legacy lamps).
  const prune = () => {
    if (!outer) return;
    const devices = new Set(lights.map(l => l.device));
    for (const device of saved.keys()) if (!devices.has(device)) saved.delete(device);
  };
  if (lights.some(l => l.emitters)) {
    const result = lights.map(light => {
      if (!light.emitters) return reachLights(layout, [light], false)[0];
      if (light.reach && light.receivers) return light;
      const input = JSON.stringify(['group', light.signature]);
      const previous = saved.get(light.device);
      if (previous?.input === input) return {...light, ...previous.result};
      const samples = emitterSamples(light.emitters);
      // Reach is a conservative envelope per emitter/piece, never per jitter or
      // surface sample. The piece half-diagonal contains every stratified sample.
      const probes = light.emitters.flatMap((e, i) => {
        const first = samples.find(s => s.emitter === i);
        return e.shape === 'point' || e.shape === 'spot'
          ? [{...first, source: first.origin, weight: 1, padding: .15 * FT}]
          : rectPieces(e).map(p => ({...first, source: p.position, normal: p.normal, piece: p,
            cd: p.luminance * p.width * p.height, weight: 1, padding: Math.hypot(p.width, p.height) / 2}));
      });
      const inputs = probes.map((s, i) => ({device: light.device + ':reach:' + i, absolute: true,
        at: [s.source.x / FT, -s.source.z / FT, s.source.y / FT], range: s.range / FT, probe: s}));
      const hits = reachLights(layout, inputs, false), receivers = new Set(), charts = new Set(), scores = {}, distances = {}, chartKeys = {};
      const hash = fingerprint();hash.add(light.signature);
      hits.forEach(hit => {
        hash.add(hit.reach);
        hit.receivers.forEach(r => receivers.add(r));
        for (const chart of hit.receivingCharts) {
          charts.add(chart);scores[chart] = (scores[chart] || 0) + hit.scores[chart];
          distances[chart] = Math.min(distances[chart] ?? Infinity, hit.distances[chart]);chartKeys[chart] = hit.chartKeys[chart];
        }
      });
      const result = {receivers: [...receivers].sort((a,b) => a-b), receivingCharts: [...charts].sort((a,b) => a-b),
        scores, distances, chartKeys, reach: hash.key(), range: lightSource(layout.plan, light).range};
      saved.set(light.device, {input, result});
      return {...light, ...result};
    });
    prune();return result;
  }
  // Coincident fixtures have identical physical reach. Retain only current
  // device results, so dragging a lamp does not grow a position-history cache.
  const positions=new Map([...saved.values()].map(hit=>[hit.input,hit.result]));
  prune();
  const closest = new THREE.Vector3(), coords=new Float64Array(9);
  return lights.map(light => {
    if (!light.at) return light;
    if (light.reach && light.receivers) return light;
    const input = JSON.stringify([light.building, light.level, light.room, light.at, ...(light.absolute ? [true, light.range] : []),
      ...(light.probe ? [light.probe, light.signature] : [])]);
    const hit = positions.get(input);
    if (hit) { saved.set(light.device,{input,result:hit}); return { ...light, ...hit }; }
    const { source, range } = lightSource(layout.plan, light), receivers = new Set(), geometry = [];
    const receivingCharts = [], distances = {}, scores={}, chartKeys={};
    const probe=light.probe;
    const delta=new THREE.Vector3(), limit=(range+(probe?.padding ?? .15*FT))**2, range4=range**4;
    const physicalScore = (point, normal, d, cosine) => {
      let score = Math.max(0,1-d*d/range4)**2/Math.max(d,.01)*cosine;
      if (probe) {
        const direction=delta.copy(source).sub(point).normalize();
        const facing=probe.normal.lengthSq() ? Math.max(0,-probe.normal.dot(direction)) : 1;
        const cone=probe.outer > -1 ? coneWindow(-probe.axis.dot(direction),probe.outer,probe.inner) : 1;
        score *= probe.cd / CANDELA * facing * cone;
      }
      return score;
    };
    for (const c of layout.charts) {
      // A heightfield is lit from above: its bounds give the distance, and its tier-free
      // chart key stands for its triangles (walking a graded grid per light is the cost).
      if (c.heightfield) {
        const d = fieldClosest(c, layout.plan, source, closest).distanceToSquared(source);
        if (d > limit) continue;
        receivers.add(c.room); geometry.push(c.key + surfaceInput(c));
        distances[c.id] = d; receivingCharts.push(c.id); chartKeys[c.id] = c.key;
        const normal=new THREE.Vector3(0,1,0);
        scores[c.id] = physicalScore(closest,normal,d,1);
        continue;
      }
      const data=triangles(c);
      data.bounds.clampPoint(source,closest);
      if (closest.distanceToSquared(source)>limit) continue;
      let distance = Infinity, score=0;
      for (const t of data.faces) {
        t.closestPointToPoint(source, closest);
        const d=closest.distanceToSquared(source);
        distance = Math.min(distance, d);
        delta.copy(source).sub(closest);
        const cosine=d>1e-12 ? Math.max(0,t.normal.dot(delta)/Math.sqrt(d)) : 1;
        const value=physicalScore(closest,t.normal,d,cosine);
        score=Math.max(score,value);
        // The soft-shadow emitter has a 0.15 ft radius.
        if (d > limit) continue;
        receivers.add(c.room);
        if (!t.key) {
          const h=fingerprint();
          t.a.toArray(coords,0);t.b.toArray(coords,3);t.c.toArray(coords,6);
          h.add(coords);h.add(data.surface);t.key=h.key();
        }
        geometry.push(t.key);
      }
      distances[c.id] = distance;
      if (distance <= limit) {
        receivingCharts.push(c.id);scores[c.id]=score;chartKeys[c.id]=c.key;
      }
    }
    // Sort by geometry rather than atlas indices: far-away edits can repack the
    // global atlas, but cannot change this light's physical freshness key.
    const hash=fingerprint();hash.add(JSON.stringify([source.toArray(),range]));
    for (const key of geometry.sort()) hash.add(key);
    const reach=hash.key();
    const result = { receivers: [...receivers].sort((a, b) => a - b), receivingCharts,
      distances, scores, chartKeys, range, reach };
    saved.set(light.device, { input, result });
    positions.set(input,result);
    return { ...light, ...result };
  });
}
