import * as THREE from 'three';
import { groundAt, inPolygon, edgeDistance } from '../twin_ground.js';
import { resolveFixture } from '../live/emitters.js';
import { effectTarget } from './driver.js';

export function waterBodies(plan) {
  const pool = plan.site?.pool;
  if (!pool?.polygon || pool.polygon.length < 3) return [];
  const base = groundAt(plan, ...pool.polygon[0]) + (pool.elevation || 0);
  return [...(pool.features || []).filter(f => f.kind === 'spa' && f.polygon?.length >= 3).reverse().map(f => ({
    id: f.id, polygon: f.polygon, height: (f.mode || 'raised') === 'raised' ? base + .45 + (f.raise_in ?? 12) / 12 - 2 / 12 : base - .25,
  })), {id: pool.id || 'pool:0', polygon: pool.polygon, height: base - .25}];
}

// The waterfall visual and surface response must agree about the receiving water.
export function effectLanding(plan, point, bodies = waterBodies(plan)) {
  for (const body of bodies) if (inPolygon(body.polygon, ...point) || body.polygon.some((p,i) =>
    edgeDistance(point, p, body.polygon[(i + 1) % body.polygon.length]) <= 3)) return {height: body.height, body};
  return {height: groundAt(plan, ...point), body: null};
}

export function rippleSources(plan) {
  const bodies = waterBodies(plan).map(b => ({...b, sources: []}));
  for (const f of plan.effect_fixtures || []) {
    if (f.orphaned || !['waterfall', 'fountain', 'bubbler'].includes(f.type)) continue;
    const resolved = resolveFixture(f, plan);
    if (f.type !== 'waterfall') {
      const body = bodies.find(b => inPolygon(b.polygon, ...resolved.at));
      if (body) body.sources.push({fixture: f, a: resolved.at.slice(0,2), b: resolved.at.slice(0,2)});
    } else for (let i = 1; i < resolved.path.length; i++) {
      const a = resolved.path[i - 1], b = resolved.path[i], mid = a.map((v,k) => (v + b[k]) / 2);
      const body = effectLanding(plan, mid, bodies).body;
      if (!body) continue;
      if (f.drop_ft != null && Math.abs(mid[2] - f.drop_ft - body.height) > .1) continue;
      const normal = ['out','in'].includes(f.facing) ? resolved.normal
        : resolveFixture({...f, path: [a,b], ref: 'absolute', facing: 'out'}, plan).normal;
      body.sources.push({fixture: f, a: a.slice(0,2), b: b.slice(0,2), normal});
    }
  }
  for (const body of bodies) {
    const centre = body.polygon.reduce((s,p) => s.map((v,k) => v + p[k] / body.polygon.length), [0,0]);
    const distance = s => edgeDistance(centre, s.a, s.b);
    body.sources.sort((a,b) => distance(a) - distance(b));
    body.sources = body.sources.slice(0,8);
  }
  return bodies.filter(b => b.sources.length);
}

// Only receiving water gets a clone and shader hook. All its Library maps,
// slot identity and earlier shader hooks remain in place; no extra surface draw.
export function rippleMaterial(source, body) {
  const material = source.clone(), before = source.onBeforeCompile;
  const key = source.customProgramCacheKey();
  const uniforms = {rippleTime: {value: 0}, rippleLines: {value: Array.from({length: 8}, () => new THREE.Vector4())},
    rippleStrength: {value: Array(8).fill(0)}};
  Object.defineProperty(material.userData, 'ripples', {value: uniforms});
  material.onBeforeCompile = (shader, renderer) => {
    before.call(material, shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = 'varying vec2 vRipplePoint;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nvRipplePoint = vec2(position.x, -position.z);');
    shader.fragmentShader = `varying vec2 vRipplePoint;
uniform float rippleTime; uniform vec4 rippleLines[8]; uniform float rippleStrength[8];
` + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
normal = normalize(normal + mat3(viewMatrix) * vec3(rippleSlope.x, 0.0, -rippleSlope.y));`);
    shader.fragmentShader = shader.fragmentShader.replace('#include <color_fragment>', `#include <color_fragment>
// Foam takes scene lighting with the water instead of glowing at night.
vec2 rippleSlope = vec2(0.0); float sourceFoam = 0.0;
for (int i = 0; i < 8; i++) {
  vec2 a = rippleLines[i].xy, run = rippleLines[i].zw - a;
  vec2 delta = vRipplePoint - a - run * clamp(dot(vRipplePoint - a, run) / max(dot(run, run), .0001), 0.0, 1.0);
  float d = length(delta), phase = d * 9.0 - rippleTime * 4.5;
  float fade = exp(-d * .65) * smoothstep(0.0, .16, d);
  float wave = (sin(phase) + .28 * sin(phase * 1.73 + .8)) * (1.0 - smoothstep(.5, 3.14, fwidth(phase)));
  rippleSlope += delta / max(d, .01) * wave * fade * rippleStrength[i] * .24;
  sourceFoam += exp(-d * d * 10.0) * (.65 + .35 * sin(phase * 1.7)) * rippleStrength[i];
}
diffuseColor.rgb = mix(diffuseColor.rgb, vec3(.92,.97,.98), min(.65, sourceFoam * .5));`);
  };
  material.customProgramCacheKey = () => key + '|water-ripples-1';
  // Three's clone omits shader hooks. Viewing, selection and the bake all
  // clone surfaces; each must retain this body's shared live uniforms.
  const clone = material.clone;
  material.clone = function() {
    const target = clone.call(this);
    target.onBeforeCompile = this.onBeforeCompile;
    target.customProgramCacheKey = this.customProgramCacheKey;
    target.clone = this.clone;
    return target;
  };
  return {material, body, uniforms};
}

export function updateRipples(rows, fixtures, seconds, tier) {
  for (const {body, uniforms} of rows) {
    uniforms.rippleTime.value = tier === 'low' ? 0 : seconds;
    body.sources.forEach((source,i) => {
      const f = source.fixture, pose = fixtures.find(r => r.fixture.id === f.id) || {...effectTarget(f), opacity: 0};
      uniforms.rippleStrength.value[i] = pose.active ? pose.opacity * (.25 + .75 * pose.t) : 0;
      const flow = source.normal ? (.08 + pose.size * .6) * (1 - Math.exp(-6)) : 0;
      const offset = source.normal?.map(v => v * flow) || [0,0];
      uniforms.rippleLines.value[i].set(source.a[0]+offset[0], source.a[1]+offset[1], source.b[0]+offset[0], source.b[1]+offset[1]);
    });
  }
}
