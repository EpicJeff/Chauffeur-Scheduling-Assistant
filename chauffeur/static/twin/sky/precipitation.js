import * as THREE from 'three';
import { modelDirection } from './look.js';
import { groundAt, inPolygon, buildingBase, buildingFootprint } from '../twin_ground.js';
import { heightAt } from '../twin_roof.js';
import { allPorches } from '../twin_generator.js';
import { pathSurfacePolygons } from '../path_shapes.js';
import { yardPaverLayout } from '../paver_path.js';
import { paverSettings } from '../paver_layout.js';

const FT=.3048, BOX=[128,96,128], LIFE=.42;
const RAIN={low:1500,medium:4000,high:8000,max:12000};
const ATTEMPTS={low:24,medium:48,high:72,max:96};
const clamp=(x,a=0,b=1)=>Number.isFinite(x)?Math.max(a,Math.min(b,x)):a;
const finite=(x,fallback=0)=>Number.isFinite(x)?x:fallback;
export function precipitationCounts(tier,weather={}) {
  const n=RAIN[tier]||RAIN.high,r=weather.neutral?0:clamp(weather.rate),kind=weather.precip;
  return {rain:Math.floor(n*r*(kind==='rain'?1:kind==='mix'?.5:0)),
    snow:Math.floor(n*.5*r*(kind==='snow'?1:kind==='mix'?.5:0)),
    hail:Math.floor(n*.3*r*(kind==='hail'?1:0))};
}
export function precipitationVelocity(kind,weather={},bearing=180,reduced=false) {
  const speed=clamp(weather.windMps,0,60),[x,,z]=modelDirection(finite(weather.windToDeg,90)*Math.PI/180,0,finite(bearing,180));
  const factor=reduced?.35:1;
  return [speed?x*speed*factor:0,-({rain:14,snow:.9,hail:18}[kind]||14)*factor,speed?z*speed*factor:0];
}
// CPU reference for the vertex shader's world-anchored toroidal box.
export function wrappedPosition(seed,travel,anchor) {
  return BOX.map((size,i)=>anchor[i]+(((seed[i]*size+travel[i]-anchor[i])%size+size)%size)-size/2);
}

// A bounded, analytic downward sample: feet in the plan, metres at the draw.
// Terraces shape the ground; they are lawn, not hard receiving slabs. Paving
// on a pad is represented by hardscape, exactly as it is in buildYard.
export function createSplashSampler(plan={},roofs=new Map()) {
  const site=plan.site||{},hard=[];
  const add=(polygon,elevation,flat=null)=>{
    if(!(polygon?.length>=3))return;
    hard.push({polygon,elevation,flat,bounds:[Math.min(...polygon.map(p=>p[0])),Math.min(...polygon.map(p=>p[1])),
      Math.max(...polygon.map(p=>p[0])),Math.max(...polygon.map(p=>p[1]))]});
  };
  for(const h of site.hardscape||[]){
    const layout=h.kind==='path'?yardPaverLayout(h):null;
    if(layout){
      const level=paverSettings(h)?.lay==='level';
      for(const p of layout.pavers)add(p.polygon,finite(h.elevation)+1/12,level?groundAt(plan,...p.centre):null);
    }else for(const p of h.kind==='path'?pathSurfacePolygons(h):[h.polygon])add(p,finite(h.elevation)+.3);
  }
  const water=[site.pool?.polygon,...(site.pool?.features||[]).filter(f=>f.kind==='spa').map(f=>f.polygon)].filter(Boolean);
  const beds=(site.beds||[]).map(b=>b.polygon).filter(Boolean);
  const buildings=(plan.buildings||[]).map(b=>{
    const angle=finite(b.rotation)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),pos=b.position||[0,0];
    return {b,c,s,pos,base:buildingBase(plan,b),footprint:buildingFootprint(b),porches:allPorches(b),sections:roofs?.get(b.id)?.sections||[]};
  });
  return (worldX,worldZ)=>{
    if(!Number.isFinite(worldX)||!Number.isFinite(worldZ))return null;
    const x=worldX/FT,y=-worldZ/FT;
    let best=null,blocked=false,roofTop=-Infinity;
    const offer=(height,kind,normal=[0,1,0])=>{
      if(Number.isFinite(height)&&normal[1]>.55&&(!best||height>best.height))best={height,kind,normal};
    };
    for(const {b,c,s,pos,base,footprint,porches,sections} of buildings){
      const dx=x-pos[0],dy=y-pos[1],u=dx*c+dy*s,v=-dx*s+dy*c;
      if(inPolygon(footprint,u,v))blocked=true;
      for(const p of porches)if(p.polygon&&inPolygon(p.polygon,u,v)){
        const room=(b.rooms||[]).find(r=>r.kind==='porch'&&r.state!=='ghost'&&r.level===(p.level||b.levels?.[0]?.id)&&inPolygon(r.polygon,u,v));
        offer(base+finite(p.floor)+finite(room?.floor_offset_ft),'deck');
      }
      const h=heightAt(sections,u,v);
      if(h!==null){
        roofTop=Math.max(roofTop,base+h);
        // Analytic roof envelope, including overhangs and raised/rotated buildings.
        const e=.01,hx=heightAt(sections,u+e,v)??h,hy=heightAt(sections,u,v+e)??h;
        const a=(hx-h)/e,d=(hy-h)/e,n=new THREE.Vector3(-a*c+d*s,1,a*s+d*c).normalize();
        offer(base+h,'roof',n.toArray());
      }
    }
    if(!blocked&&!water.some(p=>inPolygon(p,x,y))&&!beds.some(p=>inPolygon(p,x,y))){
      for(const h of hard)if(x>=h.bounds[0]&&y>=h.bounds[1]&&x<=h.bounds[2]&&y<=h.bounds[3]&&inPolygon(h.polygon,x,y)){
        const g=h.flat??groundAt(plan,x,y),e=.05,gx=h.flat===null?(groundAt(plan,x+e,y)-g)/e:0,gy=h.flat===null?(groundAt(plan,x,y+e)-g)/e:0;
        offer(g+h.elevation,'hardscape',new THREE.Vector3(-gx,1,gy).normalize().toArray());
      }
    }
    return best&&best.height>=roofTop-1e-6?{kind:best.kind,normal:best.normal,position:[worldX,best.height*FT+.006,worldZ]}:null;
  };
}

const vertexShader=`
attribute vec3 precipSeed;
uniform vec3 precipAnchor,precipTravel,precipVelocity;
uniform float precipKind,precipClock;
varying vec2 particleUv;varying vec3 particleWorld;
void main(){
  vec3 box=vec3(128.0,96.0,128.0);
  vec3 world=precipAnchor+mod(precipSeed*box+precipTravel-precipAnchor,box)-box*.5;
  if(precipKind>0.5&&precipKind<1.5){
    world.x+=.16*sin(precipClock*1.7+precipSeed.z*30.0);
    world.z+=.12*sin(precipClock*1.3+precipSeed.x*30.0);
  }
  particleWorld=world;particleUv=uv;
  vec4 eye=viewMatrix*vec4(world,1.0);
  vec2 direction=(mat3(viewMatrix)*precipVelocity).xy;
  direction=length(direction)>1e-5?direction/max(length(direction),1e-5):vec2(0.0,-1.0);
  vec2 side=vec2(-direction.y,direction.x);
  vec2 size=precipKind<.5?vec2(.018,.7):precipKind<1.5?vec2(.10,.10):vec2(.045,.045);
  eye.xy+=side*position.x*size.x+direction*position.y*size.y;
  gl_Position=projectionMatrix*eye;
}`;
const fragmentCommon=`
uniform vec3 precipColour;uniform vec2 precipCentre;
uniform float precipRadius,precipFog;
varying vec2 particleUv;varying vec3 particleWorld;
float precipitationFade(){
  float d=distance(particleWorld,cameraPosition);
  float radius=max(precipRadius*(1.0-.85*precipFog),.0001);
  float haze=smoothstep(radius,radius*1.35,distance(particleWorld.xz,precipCentre));
  return (1.0-smoothstep(40.0,64.0,d)) * smoothstep(.8,1.8,d)*(1.0-haze);
}
vec3 precipSafe(vec3 c){return vec3(c.r>=0.0?min(c.r,4096.0):0.0,c.g>=0.0?min(c.g,4096.0):0.0,c.b>=0.0?min(c.b,4096.0):0.0);}
`;
const fragmentShader=fragmentCommon+`
uniform float precipKind;
void main(){
  vec2 p=particleUv*2.0-1.0;
  float alpha=precipKind<.5?(1.0-smoothstep(.3,1.0,abs(p.x)))*(1.0-abs(p.y))*.5:
    (1.0-smoothstep(.5,1.0,length(p)))*.8;
  alpha*=precipitationFade();
  if(alpha<.001)discard;
  gl_FragColor=vec4(precipSafe(precipColour),clamp(alpha,0.0,1.0));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
const splashVertex=`
attribute vec3 splashPosition,splashNormal;attribute float splashBorn;
uniform float splashTime;
varying float splashAge;varying vec2 particleUv;varying vec3 particleWorld;
void main(){
  splashAge=splashTime-splashBorn;particleUv=uv;
  vec3 n=splashNormal;
  vec3 tangent=normalize(cross(n,vec3(0.0,0.0,1.0)));
  vec3 bitangent=cross(n,tangent);
  float radius=.025+.22*clamp(splashAge/0.42,0.0,1.0);
  particleWorld=splashPosition+(tangent*position.x+bitangent*position.y)*radius*2.0;
  gl_Position=projectionMatrix*viewMatrix*vec4(particleWorld,1.0);
}`;
const splashFragment=fragmentCommon+`
varying float splashAge;
void main(){
  if(splashAge<0.0||splashAge>0.42)discard;
  float ring=1.0-smoothstep(.05,.18,abs(length(particleUv*2.0-1.0)-.78));
  float alpha=ring*(1.0-splashAge/0.42)*.45*precipitationFade();
  if(alpha<.001)discard;
  gl_FragColor=vec4(precipSafe(precipColour),clamp(alpha,0.0,1.0));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

function geometry() {
  const g=new THREE.InstancedBufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([-.5,-.5,0,.5,-.5,0,.5,.5,0,-.5,.5,0],3));
  g.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,1],2));g.setIndex([0,1,2,0,2,3]);g.instanceCount=0;
  return g;
}
export function createPrecipitation(scene,{tier='high',random=Math.random}={}) {
  const group=new THREE.Group();group.name='weather-precipitation';scene.add(group);
  // No domain ownership, picking layer or effect fixture: editor hide/lock does
  // not classify these. Extras excludes the whole group from every capture.
  const uniforms={precipAnchor:{value:new THREE.Vector3()},precipColour:{value:new THREE.Vector3(.6,.7,.8)},
    precipCentre:{value:new THREE.Vector2()},precipRadius:{value:100},precipFog:{value:0},
    precipClock:{value:0},splashTime:{value:0}};
  const objects={},travels={};let last=null,clock=0,disposed=false,sample=()=>null,credit=0,cursor=0,wasRaining=false;
  const motion=globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)');
  function mesh(name,g,vs,fs,own={}) {
    const material=new THREE.ShaderMaterial({name:'weather-'+name,uniforms:{...uniforms,...own},vertexShader:vs,fragmentShader:fs,
      transparent:true,depthWrite:false,depthTest:true,side:THREE.DoubleSide,lights:false,fog:false});
    const o=new THREE.Mesh(g,material);o.name='weather-'+name;o.frustumCulled=false;o.visible=false;
    o.raycast=()=>{};o.castShadow=o.receiveShadow=false;o.renderOrder=20;
    objects[name]=o;group.add(o);return o;
  }
  for(const [index,kind] of ['rain','snow','hail'].entries()){
    const count=precipitationCounts(tier,{precip:kind,rate:1})[kind],g=geometry(),seeds=new Float32Array(count*3);
    for(let i=0;i<seeds.length;i++)seeds[i]=clamp(random());
    g.setAttribute('precipSeed',new THREE.InstancedBufferAttribute(seeds,3));
    travels[kind]=new THREE.Vector3();
    mesh(kind,g,vertexShader,fragmentShader,{precipKind:{value:index},precipTravel:{value:travels[kind]},precipVelocity:{value:new THREE.Vector3()}});
  }
  const capacity=64,sg=geometry(),positions=new Float32Array(capacity*3),normals=new Float32Array(capacity*3),born=new Float32Array(capacity).fill(-1e6);
  for(let i=0;i<capacity;i++)normals[i*3+1]=1;
  for(const [name,array,size] of [['splashPosition',positions,3],['splashNormal',normals,3],['splashBorn',born,1]])
    sg.setAttribute(name,new THREE.InstancedBufferAttribute(array,size).setUsage(THREE.DynamicDrawUsage));
  mesh('splash',sg,splashVertex,splashFragment);
  const api={group,objects,uniforms,
    setStage({centre,radius}){if(centre?.every(Number.isFinite))uniforms.precipCentre.value.fromArray(centre);if(Number.isFinite(radius)&&radius>0)uniforms.precipRadius.value=radius;},
    setPlan(plan,roofs){sample=createSplashSampler(plan,roofs);born.fill(-1e6);sg.attributes.splashBorn.needsUpdate=true;credit=0;},
    update(now,weather,camera,{bearing=180,unlit=false,colour=[.6,.7,.8],reduced=motion?.matches}={}){
      if(disposed)return;
      now=finite(now);const dt=last===null?0:clamp(now-last,0,1);last=now;clock+=dt*(reduced?.35:1);
      uniforms.precipClock.value=clock;uniforms.splashTime.value=now;uniforms.precipFog.value=clamp(weather?.fog);
      if(colour?.every(Number.isFinite))uniforms.precipColour.value.fromArray(colour.map(c=>clamp(c,.015,1)));
      uniforms.precipAnchor.value.copy(camera.position);
      const counts=precipitationCounts(tier,unlit?{}:weather);
      for(const kind of ['rain','snow','hail']){
        const o=objects[kind],velocity=precipitationVelocity(kind,weather,bearing,reduced);
        o.geometry.instanceCount=counts[kind];o.visible=counts[kind]>0;
        o.material.uniforms.precipVelocity.value.fromArray(velocity);
        travels[kind].addScaledVector(o.material.uniforms.precipVelocity.value,dt);
        for(const axis of ['x','y','z']){const size=BOX[{x:0,y:1,z:2}[axis]];travels[kind][axis]=((travels[kind][axis]%size)+size)%size;}
      }
      const raining=counts.rain>0;
      if(!raining){
        if(wasRaining){born.fill(-1e6);sg.attributes.splashBorn.needsUpdate=true;}
        wasRaining=false;credit=0;objects.splash.visible=false;sg.instanceCount=0;return;
      }
      wasRaining=true;
      credit=Math.min(12,credit+dt*(ATTEMPTS[tier]||72)*clamp(weather.rate));
      let changed=false;
      while(credit>=1){
        credit--;const angle=clamp(random())*Math.PI*2,radius=Math.sqrt(clamp(random()))*48;
        const hit=sample(camera.position.x+Math.cos(angle)*radius,camera.position.z+Math.sin(angle)*radius);
        if(!hit)continue;
        positions.set(hit.position,cursor*3);normals.set(hit.normal,cursor*3);born[cursor]=now;cursor=(cursor+1)%capacity;changed=true;
      }
      if(changed)for(const attr of Object.values(sg.attributes))if(attr.isInstancedBufferAttribute)attr.needsUpdate=true;
      objects.splash.visible=born.some(t=>now-t>=0&&now-t<=LIFE);sg.instanceCount=objects.splash.visible?capacity:0;
    },
    dispose(){if(disposed)return;disposed=true;group.removeFromParent();for(const o of Object.values(objects)){o.geometry.dispose();o.material.dispose();}},
  };
  return api;
}
