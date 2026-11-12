import * as THREE from '../../vendor/three-r187/three.module.js';
import { FT, lightRange, LAMP_HEIGHT } from '../twin_light_math.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { fingerprint } from './fingerprint.js';

// Match the live lamp's bulb height and range, including the ceiling inset.
export function lightSource(plan, light) {
  const b = plan.buildings?.find(b => b.id === light.building), l = b?.levels?.find(l => l.id === light.level);
  const r = b?.rooms?.find(r => r.id === light.room), floor = (b?.base || 0) + (l?.elevation || 0);
  const standing = !!l && light.at[2] <= floor + .1;
  const z = standing ? floor + LAMP_HEIGHT : light.at[2];
  const span = r ? Math.max(...[0, 1].map(k => Math.max(...r.polygon.map(p => p[k])) - Math.min(...r.polygon.map(p => p[k]))), 1) : 10;
  const range = lightRange({ at: [light.at[0], light.at[1], z] }, b, l, r, span) * FT;
  const source = new THREE.Vector3(light.at[0] * FT,
    (z + buildingGround(plan, b)) * FT, -light.at[1] * FT);
  if (l && !standing && light.at[2] >= floor + l.ceiling - .1) source.y -= .2 * FT;
  return { source, range };
}

const cached = new WeakMap();
const reaches = new WeakMap();
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
  data={faces,bounds,surface:new TextEncoder().encode(JSON.stringify([chart.mesh.material.color?.toArray(),chart.density]))};
  cached.set(chart, data); return data;
}

export function reachLights(layout, lights) {
  if (!layout.plan) return lights;
  if (!reaches.has(layout)) reaches.set(layout, new Map());
  const saved = reaches.get(layout);
  // Coincident fixtures have identical physical reach. Retain only current
  // device results, so dragging a lamp does not grow a position-history cache.
  const positions=new Map([...saved.values()].map(hit=>[hit.input,hit.result]));
  const devices=new Set(lights.map(l=>l.device));
  for (const device of saved.keys()) if (!devices.has(device)) saved.delete(device);
  const closest = new THREE.Vector3(), coords=new Float64Array(9);
  return lights.map(light => {
    if (!light.at) return light;
    if (light.reach && light.receivers) return light;
    const input = JSON.stringify([light.building, light.level, light.room, light.at]);
    const hit = positions.get(input);
    if (hit) { saved.set(light.device,{input,result:hit}); return { ...light, ...hit }; }
    const { source, range } = lightSource(layout.plan, light), receivers = new Set(), geometry = [];
    const receivingCharts = [], distances = {}, scores={}, chartKeys={};
    const delta=new THREE.Vector3(), limit=(range+.15*FT)**2, range4=range**4;
    for (const c of layout.charts) {
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
        score=Math.max(score,Math.max(0,1-d*d/range4)**2/Math.max(d,.01)*cosine);
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
