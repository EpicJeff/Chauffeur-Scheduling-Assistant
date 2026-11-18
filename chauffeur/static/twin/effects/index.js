import * as THREE from 'three';
import { resolveFixture, emission } from '../live/emitters.js';
import { inPolygon } from '../twin_ground.js';
import { effectLanding, waterBodies } from './water_ripples.js';
import { createEffectDriver, effectTarget } from './driver.js';
import { buildFountain } from './fountain.js';
import { buildBubbler } from './bubbler.js';
import { buildFire } from './fire.js';
import { buildWaterfall } from './waterfall.js';
import { buildSpaJet } from './spa_jet.js';
import { buildDeckJet } from './deck_jet.js';
import { buildSheer } from './sheer.js';
import { buildVapour } from './vapour.js';

const world=p=>new THREE.Vector3(p[0],p[2],-p[1]);
const midpoint=path=>{
  let half=path.slice(1).reduce((s,p,i)=>s+Math.hypot(...p.map((v,k)=>v-path[i][k])),0)/2;
  for(let i=1;i<path.length;i++) {
    const a=path[i-1],b=path[i],d=Math.hypot(...b.map((v,k)=>v-a[k]));
    if(half<=d)return a.map((v,k)=>v+(b[k]-v)*half/d);half-=d;
  }
  return [...path[0]];
};

function landing(plan, point, normal) {
  return effectLanding(plan, point, undefined, normal).height;
}

// The light entities with a lamp in this body of water, below or at its surface.
function waterLamps(plan, body) {
  if (!body) return [];
  return Object.entries(plan.light_fixtures || {}).filter(([, rows]) => (Array.isArray(rows) ? rows : []).some(row => {
    const r = resolveFixture(row, plan), at = r.at || r.path?.[0];
    return at && inPolygon(body.polygon, at[0], at[1]) && at[2] <= body.height + .5;
  })).map(([entity]) => entity);
}
// Steam, foam and falling water over a lit pool are lit from beneath by its lamps:
// their colour at their brightness.
const GLOW = .45;
const WET = ['steam', 'waterfall', 'sheer', 'fountain', 'bubbler', 'spa_jet', 'deck_jet'];
const bodyAt = (plan, point) => point && waterBodies(plan).find(b => inPolygon(b.polygon, point[0], point[1]));
function lampGlow(entities, states, stale, target) {
  target.setRGB(0, 0, 0);
  for (const entity of entities) {
    const lamp = emission(stale ? null : states[entity], entity.split('.')[0]);
    if (!lamp.on) continue;
    const [r, g, b] = lamp.rgb.map(v => v / 255 * lamp.brightness * GLOW);
    target.setRGB(Math.max(target.r, r), Math.max(target.g, g), Math.max(target.b, b));
  }
  return target;
}

export function buildEffects(plan, {tier='high',editor=false}={}) {
  if(!plan.effect_fixtures?.length)return null;
  const group=new THREE.Group(),fixtures=[];
  group.name='effect-fixtures';group.userData.noOcclusion=true;group.userData.effectFixtures=true;
  for(const fixture of plan.effect_fixtures) {
    if(fixture.orphaned)continue;
    const placement={...fixture};
    const resolved=resolveFixture(placement,plan),position=resolved.at||midpoint(resolved.path);
    const origin=resolved.at||resolved.path[0],local=p=>p.map((v,k)=>v-origin[k]);
    // Where the water stands or lands: a line falls out from its lip.
    let built,wet=resolved.at;
    if(fixture.type==='fountain')built=buildFountain();
    else if(fixture.type==='bubbler')built=buildBubbler();
    else if(fixture.type==='fire')built=buildFire({...resolved,...(resolved.path?{path:resolved.path.map(local)}:{at:[0,0,0]})});
    else if(fixture.type==='spa_jet')built=buildSpaJet(plan,origin);
    else if(fixture.type==='deck_jet')built=buildDeckJet(plan,origin);
    else if(['steam','mist'].includes(fixture.type))built=buildVapour({...resolved,...(resolved.path?{path:resolved.path.map(local)}:{})},{plan,origin,mist:fixture.type==='mist'});
    else {
      const path=resolved.path;
      const normals=path.map((p,i)=>{
        const a=path[Math.max(0,i-1)],b=path[Math.min(path.length-1,i+1)],d=Math.hypot(b[0]-a[0],b[1]-a[1])||1;
        if(['out','in'].includes(fixture.facing))return resolved.normal;
        // Down/up choose the host's outside in plan, keeping the vertical fall.
        return resolveFixture({...placement,path:[a,b],facing:'out'},plan).normal||[(b[1]-a[1])/d,-(b[0]-a[0])/d,0];
      });
      const drops=path.map((p,i)=>fixture.drop_ft??Math.max(.1,p[2]-landing(plan,p,normals[i])));
      built=(fixture.type==='sheer'?buildSheer:buildWaterfall)({...resolved,path:path.map(local)},{normals,drops});
      const m=midpoint(path),n=normals[Math.floor(normals.length/2)]||[0,0,0];
      wet=[.6,1.2,2].map(d=>[m[0]+n[0]*d,m[1]+n[1]*d]).find(p=>bodyAt(plan,p))||null;
    }
    built.group.position.copy(world(origin));group.add(built.group);
    const driver=createEffectDriver(fixture,{low:tier==='low'});
    const lamps=!WET.includes(fixture.type)?[]:waterLamps(plan,fixture.type==='steam'?built.body:bodyAt(plan,wet));
    fixtures.push({fixture,group:built.group,position:[...position],...(resolved.path?{path:resolved.path.map(p=>[...p])}:{}),driver,built,lamps});
  }
  const update=(states={},stale=false,seconds=0,light=1)=>{
    for(const row of fixtures) {
      const f=row.fixture;
      const pose=editor?row.driver.update({},false,seconds):row.driver.update(states,stale,seconds);
      // The editor previews the authored strength, regardless of HA links.
      if(editor)Object.assign(pose,effectTarget({...f,entity:null,sensor:null}),{opacity:1});
      Object.assign(row,pose);row.group.visible=pose.opacity>0;row.built.pose(pose.size);
      for(const mesh of row.group.children) {
        const u=mesh.material.uniforms;
        u.time.value=tier==='low'?0:seconds;
        if(u.strength)u.strength.value=pose.t;
        if(u.opacity)u.opacity.value=pose.opacity;
        if(u.light)u.light.value=light;
        // The editor previews without live states, so its steam takes no lamp light.
        if(u.glow)lampGlow(editor?[]:row.lamps,states,stale,u.glow.value);
      }
    }
  };
  update({},false,0);
  return {group,fixtures,update};
}
