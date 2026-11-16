import * as THREE from 'three';
import { groundAt, inPolygon, edgeDistance, segmentIntersection } from '../twin_ground.js';
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
export function effectLanding(plan, point, bodies = waterBodies(plan), normal = null) {
  if (normal) {
    // A fall off a rim lands where it is thrown, never in the basin behind the rim.
    const step = sign => [point[0] + sign * normal[0] * .75, point[1] + sign * normal[1] * .75];
    const into = bodies.find(body => inPolygon(body.polygon, ...step(1)));
    if (into) return {height: into.height, body: into};
    bodies = bodies.filter(body => !inPolygon(body.polygon, ...step(-1)));
  }
  for (const body of bodies) if (inPolygon(body.polygon, ...point) || body.polygon.some((p,i) =>
    edgeDistance(point, p, body.polygon[(i + 1) % body.polygon.length]) <= 3)) return {height: body.height, body};
  return {height: groundAt(plan, ...point), body: null};
}

export function waterAim(plan, point, radius, bodies = waterBodies(plan)) {
  const distance = body => inPolygon(body.polygon, ...point) ? 0 : Math.min(...body.polygon.map((p,i) => edgeDistance(point, p, body.polygon[(i+1)%body.polygon.length])));
  const body = bodies.map((body,i) => ({body,i,d:distance(body)})).filter(row => row.d <= radius).sort((a,b) => a.d-b.d || a.i-b.i)[0]?.body;
  let centre = body?.polygon.reduce((sum,p) => sum.map((v,k) => v+p[k]/body.polygon.length), [0,0]);
  if (body && !inPolygon(body.polygon, ...centre)) {
    const points = body.polygon.map(p => new THREE.Vector2(...p));
    const triangle = THREE.ShapeUtils.triangulateShape(points, [])[0];
    centre = [0,1].map(k => triangle.reduce((sum,i) => sum+body.polygon[i][k]/3, 0));
  }
  if (!centre) centre = (plan.site?.lot || [[0,0]]).reduce((sum,p,_,rows) => sum.map((v,k) => v+p[k]/rows.length), [0,0]);
  const length = Math.hypot(centre[0]-point[0], centre[1]-point[1]);
  const normal = length > .001 ? [(centre[0]-point[0])/length, (centre[1]-point[1])/length] : [1,0];
  return {body, origin: point, normal};
}

export function spaAim(plan, point, bodies = waterBodies(plan)) {
  const body=effectLanding(plan,point,bodies).body;
  return waterAim(plan,point,3,body?[body]:[]);
}

// Intersect the aim ray with the polygon, keeping the landing inside even on
// a concave body. Both the visual and its moving ripple use this same point.
export function waterReach(aim, size) {
  const {body, origin: p, normal: n} = aim;
  let reach = size;
  if (body) {
    const cuts = [0], cross = (a,b) => a[0]*b[1]-a[1]*b[0];
    body.polygon.forEach((a,i) => {
      const b=body.polygon[(i+1)%body.polygon.length], edge=[b[0]-a[0],b[1]-a[1]], delta=[a[0]-p[0],a[1]-p[1]], denominator=cross(n,edge);
      if (Math.abs(denominator)<1e-8) return;
      const t=cross(delta,edge)/denominator, u=cross(delta,n)/denominator;
      if(t>=0 && u>=0 && u<=1)cuts.push(t);
    });
    cuts.sort((a,b)=>a-b);
    for(let i=1;i<cuts.length;i++) {
      const low=cuts[i-1],high=cuts[i],mid=(low+high)/2;
      if(high-low<.001 || !inPolygon(body.polygon,p[0]+n[0]*mid,p[1]+n[1]*mid))continue;
      const margin=Math.min(.4,(high-low)/4);
      reach=Math.max(low+margin,Math.min(high-margin,size));break;
    }
  }
  return [p[0]+n[0]*reach,p[1]+n[1]*reach,body?.height ?? 0];
}

function waterLine(body, a, b) {
  const dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
  if(length<1e-8)return inPolygon(body.polygon,...a)?[a,b]:null;
  const cuts=[0,1];
  body.polygon.forEach((p,i)=>{
    const hit=segmentIntersection(a,b,p,body.polygon[(i+1)%body.polygon.length]);
    if(hit)cuts.push(((hit[0]-a[0])*dx+(hit[1]-a[1])*dy)/length);
  });
  cuts.sort((a,b)=>a-b);let result=null,span=0;
  for(let i=1;i<cuts.length;i++){
    const lo=cuts[i-1],hi=cuts[i],mid=(lo+hi)/2;
    if(hi-lo>span && inPolygon(body.polygon,a[0]+dx*mid,a[1]+dy*mid)){
      result=[[a[0]+dx*lo,a[1]+dy*lo],[a[0]+dx*hi,a[1]+dy*hi]];span=hi-lo;
    }
  }
  return result;
}

export function rippleSources(plan) {
  const bodies = waterBodies(plan).map(b => ({...b, sources: []}));
  for (const f of plan.effect_fixtures || []) {
    if (f.orphaned || !['waterfall', 'fountain', 'bubbler', 'spa_jet', 'deck_jet', 'sheer'].includes(f.type)) continue;
    const resolved = resolveFixture(f, plan);
    if (['spa_jet','deck_jet'].includes(f.type)) {
      const aim=f.type==='spa_jet'?spaAim(plan,resolved.at,bodies):waterAim(plan,resolved.at,12,bodies);
      if(aim.body)aim.body.sources.push({fixture:f,aim:{...aim,body:{id:aim.body.id,polygon:aim.body.polygon,height:aim.body.height}},a:resolved.at.slice(0,2),b:resolved.at.slice(0,2)});
    } else if (!['waterfall','sheer'].includes(f.type)) {
      const body = bodies.find(b => inPolygon(b.polygon, ...resolved.at));
      if (body) body.sources.push({fixture: f, a: resolved.at.slice(0,2), b: resolved.at.slice(0,2)});
    } else for (let i = 1; i < resolved.path.length; i++) {
      const a = resolved.path[i - 1], b = resolved.path[i], mid = a.map((v,k) => (v + b[k]) / 2);
      const normal = ['out','in'].includes(f.facing) ? resolved.normal
        : resolveFixture({...f, path: [a,b], ref: 'absolute', facing: 'out'}, plan).normal;
      const body = effectLanding(plan, mid, bodies, normal).body;
      if (!body) continue;
      if (f.drop_ft != null && Math.abs(mid[2] - f.drop_ft - body.height) > .1) continue;
      if(f.type==='sheer') {
        const sizes=[f.size_min??.5,f.size_max??3],offset=(p,size)=>p.slice(0,2).map((v,k)=>v+normal[k]*size);
        const sweep=[offset(a,sizes[0]),offset(b,sizes[0]),offset(b,sizes[1]),offset(a,sizes[1])];
        if(!sweep.some(p=>inPolygon(body.polygon,...p)) && !body.polygon.some(p=>inPolygon(sweep,...p)) && !sweep.some((p,i)=>waterLine(body,p,sweep[(i+1)%sweep.length])))continue;
      }
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
      if(source.aim) {
        const p=waterReach(source.aim,pose.size);uniforms.rippleLines.value[i].set(p[0],p[1],p[0],p[1]);return;
      }
      const flow = source.normal ? f.type==='sheer' ? pose.size : (.08 + pose.size * .6) * (1 - Math.exp(-6)) : 0;
      const offset = source.normal?.map(v => v * flow) || [0,0];
      uniforms.rippleLines.value[i].set(source.a[0]+offset[0], source.a[1]+offset[1], source.b[0]+offset[0], source.b[1]+offset[1]);
      if(f.type==='sheer') {
        const line=waterLine(body,source.a.map((v,k)=>v+offset[k]),source.b.map((v,k)=>v+offset[k]));
        if(line)uniforms.rippleLines.value[i].set(...line[0],...line[1]);else uniforms.rippleStrength.value[i]=0;
      }
    });
  }
}
