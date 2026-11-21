import * as THREE from 'three';
import { modelDirection } from './look.js';
import { groundAt, inPolygon, buildingBase, buildingFootprint } from '../twin_ground.js';
import { heightAt } from '../twin_roof.js';
import { allPorches } from '../twin_generator.js';
import { pathSurfacePolygons } from '../path_shapes.js';
import { yardPaverLayout } from '../paver_path.js';
import { paverSettings } from '../paver_layout.js';
import { weatherExtinction } from './weather.js';
import { createSkyCover, HEIGHT_NONE } from './sky_cover.js';

const FT=.3048, BOX=[128,96,128], LIFE=.3;
const RAIN={low:3000,medium:4000,high:8000,max:12000};
const ATTEMPTS={low:120,medium:240,high:400,max:560};
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
export function wrappedPosition(seed,travel,anchor,box=BOX,out=[]) {
  for(let i=0;i<3;i++){const size=box[i];out[i]=anchor[i]+(((seed[i]*size+travel[i]-anchor[i])%size+size)%size)-size/2;}
  return out;
}

// A bounded, analytic downward sample: feet in the plan, metres at the draw.
// Terraces shape the ground; they are lawn, not hard receiving slabs. Paving
// on a pad is represented by hardscape, exactly as it is in buildYard.
export function collectHardSurfaces(plan={}) {
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
  return hard;
}

const waterPolygons=site=>[site.pool?.polygon,...(site.pool?.features||[]).filter(f=>f.kind==='spa').map(f=>f.polygon)].filter(Boolean);

// Keep the cover grid's origin and cell size: expanding it cannot shift the
// rain's existing nearest-texel eave boundary. R retains the old cover height;
// G is the highest hardscape top (including the pad/grade underneath), metres.
export function bakeWetGroundField(plan={},cover=createSkyCover(plan),hard=collectHardSurfaces(plan)) {
  const f=cover.heightField(),cell=f.cell||.3;
  let [x0,z0,x1,z1]=f.bounds;
  for(const h of hard){
    x0=Math.min(x0,h.bounds[0]*FT);z0=Math.min(z0,-h.bounds[3]*FT);
    x1=Math.max(x1,h.bounds[2]*FT);z1=Math.max(z1,-h.bounds[1]*FT);
  }
  x0=f.bounds[0]+Math.floor((x0-f.bounds[0])/cell)*cell;
  z0=f.bounds[1]+Math.floor((z0-f.bounds[1])/cell)*cell;
  const width=Math.max(1,Math.ceil((x1-x0)/cell)),height=Math.max(1,Math.ceil((z1-z0)/cell));
  const data=new Float32Array(width*height*2).fill(HEIGHT_NONE),site=plan.site||{};
  const excluded=[...waterPolygons(site),...(site.beds||[]).map(b=>b.polygon).filter(Boolean)];
  // Copy, rather than resample, the old cover texels bit-for-bit.
  const ox=Math.round((f.bounds[0]-x0)/cell),oz=Math.round((f.bounds[1]-z0)/cell);
  for(let j=0;j<f.height;j++)for(let i=0;i<f.width;i++)data[((j+oz)*width+i+ox)*2]=f.data[j*f.width+i];
  for(const h of hard){
    const i0=Math.max(0,Math.floor((h.bounds[0]*FT-x0)/cell)),i1=Math.min(width-1,Math.floor((h.bounds[2]*FT-x0)/cell));
    const j0=Math.max(0,Math.floor((-h.bounds[3]*FT-z0)/cell)),j1=Math.min(height-1,Math.floor((-h.bounds[1]*FT-z0)/cell));
    for(let j=j0;j<=j1;j++)for(let i=i0;i<=i1;i++){
      const x=(x0+(i+.5)*cell)/FT,y=-(z0+(j+.5)*cell)/FT;
      if(!inPolygon(h.polygon,x,y)||excluded.some(p=>inPolygon(p,x,y)))continue;
      const top=((h.flat??groundAt(plan,x,y))+h.elevation)*FT,index=(j*width+i)*2+1;
      data[index]=Math.max(data[index],top);
    }
  }
  return {cell,width,height,bounds:[x0,z0,x0+width*cell,z0+height*cell],data};
}

export function createSplashSampler(plan={},roofs=new Map(),cover=createSkyCover(plan,roofs)) {
  const site=plan.site||{},hard=collectHardSurfaces(plan);
  const water=waterPolygons(site);
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
    const hit=best&&best.height>=roofTop-1e-6?{kind:best.kind,normal:best.normal,position:[worldX,best.height*FT+.006,worldZ]}:null;
    return hit&&!cover.blocked(...hit.position)?hit:null;
  };
}

const vertexShader=`
attribute vec3 precipSeed;
uniform vec3 precipAnchor,precipBox,precipTravel,precipVelocity;
uniform float precipKind,precipClock,precipRate;
uniform vec2 precipViewport;
// Covered height per ground point (sky_cover heightField), nearest texel.
uniform sampler2D precipCover;uniform vec4 precipCoverBounds;uniform float precipCutaway;
bool precipitationCovered(vec3 world) {
  vec2 uv=(world.xz-precipCoverBounds.xy)/max(precipCoverBounds.zw-precipCoverBounds.xy,vec2(.0001));
  if(any(lessThan(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0))))return false;
  float top=texture2D(precipCover,uv).r;
  // A floor or room cutaway hides the roof: rain above it would read as rain indoors.
  return world.y<top||precipCutaway>.5&&top>-9999.0;
}
varying vec2 particleUv;varying vec3 particleWorld;
float precipitationWidth(float pixels,float kind) {
  return kind<.5?clamp(pixels,1.25,2.5):pixels;
}
float precipitationLength(float pixels,float kind,float rate) {
  return kind<.5?min(96.0,mix(max(pixels,1.25),max(pixels,mix(6.0,10.0,clamp((rate-.45)/.55,0.0,1.0))),smoothstep(0.0,4.0,pixels))):pixels;
}
bool precipitationVisibleDepth(float depth) {
  return depth>=3.5;
}
void main(){
  vec3 box=max(precipBox,vec3(.0001));
  vec3 world=precipAnchor+mod(precipSeed*box+precipTravel-precipAnchor,box)-box*.5;
  if(precipKind>0.5&&precipKind<1.5){
    world.x+=.16*sin(precipClock*1.7+precipSeed.z*30.0);
    world.z+=.12*sin(precipClock*1.3+precipSeed.x*30.0);
  }
  if(precipitationCovered(world)){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  particleWorld=world;particleUv=uv;
  vec4 eye=viewMatrix*vec4(world,1.0);
  // Never expand a near-camera drop into a large foreground smear.
  if(distance(world,cameraPosition)<3.0){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  // Radial distance misses drops beside the eye plane. Cull by forward depth
  // too; .35 m reserves both physical streak endpoints before projection.
  if(!precipitationVisibleDepth(-eye.z)){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  vec2 size=precipKind<.5?vec2(.018,.7):precipKind<1.5?vec2(.10,.10):vec2(.045,.045);
  if(precipKind>=.5){
    // Snow and hail keep their physical billboard sizes, even looking down
    // the fall axis. Only rain uses the projected streak and pixel floors.
    vec2 direction=(mat3(viewMatrix)*precipVelocity).xy;
    direction=length(direction)>1e-5?direction/max(length(direction),1e-5):vec2(0.0,-1.0);
    vec2 side=vec2(-direction.y,direction.x);
    eye.xy+=side*position.x*size.x+direction*position.y*size.y;
    gl_Position=projectionMatrix*eye;return;
  }
  gl_Position=projectionMatrix*eye;
  vec2 viewport=max(precipViewport,vec2(1.0));
  vec3 fall=mat3(viewMatrix)*precipVelocity;
  fall=length(fall)>1e-5?fall/max(length(fall),1e-5):vec3(0.0,-1.0,0.0);
  vec4 head=projectionMatrix*(eye+vec4(fall*size.y*.5,0.0));
  vec4 tail=projectionMatrix*(eye-vec4(fall*size.y*.5,0.0));
  vec2 projected=(head.xy/max(abs(head.w),.0001)-tail.xy/max(abs(tail.w),.0001))*viewport*.5;
  float projectedLength=length(projected);
  vec2 direction=projectedLength>1e-5?projected/max(projectedLength,1e-5):vec2(0.0,-1.0);
  vec2 side=vec2(-direction.y,direction.x);
  float streakLength=precipitationLength(projectedLength,precipKind,precipRate);
  // Width and length are independent drawing-buffer pixel floors along the
  // projected fall direction, including perspective and viewport aspect.
  vec2 pixelSide=(projectionMatrix*vec4(side*size.x,0.0,0.0)).xy*viewport*.5;
  float sideLength=max(length(pixelSide),.0001);
  float width=sideLength/max(abs(gl_Position.w),.0001);
  width=precipitationWidth(width,precipKind);
  gl_Position.xy+=(direction*position.y*streakLength+side*position.x*width)*2.0/viewport*gl_Position.w;
}`;
const fragmentCommon=`
uniform vec3 precipColour;uniform vec2 precipCentre;
uniform vec3 precipAnchor,precipBox;
uniform float precipRadius,precipFog;
varying vec2 particleUv;varying vec3 particleWorld;
float precipitationFade(){
  float d=distance(particleWorld,cameraPosition);
  float radius=max(precipRadius,.0001);
  float haze=smoothstep(radius,radius*1.35,distance(particleWorld.xz,precipCentre));
  float halfExtent=max(precipBox.x*.5,.0001);
  float edge=distance(particleWorld.xz,precipAnchor.xz);
  return (1.0-smoothstep(halfExtent*.8,halfExtent,edge)) * smoothstep(3.0,3.5,d)*(1.0-haze)*exp(-max(precipFog,0.0)*d);
}
vec3 precipSafe(vec3 c){return vec3(c.r>=0.0?min(c.r,4096.0):0.0,c.g>=0.0?min(c.g,4096.0):0.0,c.b>=0.0?min(c.b,4096.0):0.0);}
`;
const fragmentShader=fragmentCommon+`
uniform float precipKind,precipRate;
void main(){
  if(distance(particleWorld,cameraPosition)<3.0)discard;
  vec2 p=particleUv*2.0-1.0;
  float alpha=precipKind<.5?(1.0-smoothstep(.3,1.0,abs(p.x)))*(1.0-abs(p.y))*mix(.35,.85,precipRate):
    (1.0-smoothstep(.5,1.0,length(p)))*.8;
  alpha*=precipitationFade();
  if(alpha<.001)discard;
  // Hemisphere colour has unit peak; lift rain just above the overcast sky.
  gl_FragColor=vec4(precipSafe(precipColour*(precipKind<.5?1.2:1.0)),clamp(alpha,0.0,1.0));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;
const splashVertex=`
attribute vec3 splashPosition,splashNormal;attribute float splashBorn;
uniform sampler2D precipCover;uniform vec4 precipCoverBounds;uniform float precipCutaway;
bool precipitationCovered(vec3 world) {
  vec2 uv=(world.xz-precipCoverBounds.xy)/max(precipCoverBounds.zw-precipCoverBounds.xy,vec2(.0001));
  if(any(lessThan(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0))))return false;
  float top=texture2D(precipCover,uv).r;
  // A floor or room cutaway hides the roof: rain above it would read as rain indoors.
  return world.y<top||precipCutaway>.5&&top>-9999.0;
}
uniform float splashTime;
varying float splashAge;varying vec2 particleUv;varying vec3 particleWorld;
bool splashVisible(float age,float depth) {
  return age>=0.0&&age<=0.3&&depth>=1.5;
}
void main(){
  splashAge=splashTime-splashBorn;particleUv=uv;
  vec4 eye=viewMatrix*vec4(splashPosition,1.0);
  // Expired slots used to rasterize their entire quad before fragment discard.
  if(!splashVisible(splashAge,-eye.z)||precipCutaway>.5&&precipitationCovered(splashPosition+vec3(0.0,1e4,0.0))){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  // A splash crown a few centimetres tall, facing the camera (owner reference
  // photo 2026-11-19), not a flat ring: rings belong to standing water.
  float grow=smoothstep(0.0,.06,splashAge);
  vec2 size=vec2(.05+.03*grow,.015+.04*grow);
  particleWorld=splashPosition+splashNormal*size.y*.5;
  vec4 centre=viewMatrix*vec4(particleWorld,1.0);
  centre.xy+=position.xy*size*2.0;
  gl_Position=projectionMatrix*centre;
}`;
const splashFragment=fragmentCommon+`
varying float splashAge;
uniform float splashTime;
void main(){
  float splashBorn=splashTime-splashAge;
  if(splashAge<0.0||splashAge>0.3)discard;
  vec2 p=particleUv*2.0-1.0;
  // Cup wall widening upward, then droplets thrown above the rim.
  float width=mix(.3,.9,clamp((p.y+1.0)*.5,0.0,1.0));
  float wall=(1.0-smoothstep(.06,.16,abs(abs(p.x)-width)))*(1.0-smoothstep(.1,.3,p.y));
  float drops=0.0;
  for(int i=0;i<5;i++){
    float x=-.8+.4*float(i),y=.45+.35*fract(sin(float(i)*12.9898+splashBorn*78.233)*43758.5453);
    drops=max(drops,1.0-smoothstep(.07,.13,length(p-vec2(x,y))));
  }
  float alpha=max(wall,drops)*(1.0-smoothstep(.12,.3,splashAge))*.7*precipitationFade();
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
  const uniforms={precipAnchor:{value:new THREE.Vector3()},precipBox:{value:new THREE.Vector3(36,25,36)},precipColour:{value:new THREE.Vector3(.6,.7,.8)},
    precipViewport:{value:new THREE.Vector2(1,1)},precipRate:{value:0},
    precipCentre:{value:new THREE.Vector2()},precipRadius:{value:100},precipFog:{value:0},
    precipClock:{value:0},splashTime:{value:0},
    precipCover:{value:null},precipCoverBounds:{value:new THREE.Vector4(0,0,1,1)},precipCutaway:{value:0}};
  let coverTexture=null,coverFor=null;
  // Bake once per plan/cover while falling OR still wet after the rain stops.
  function bakeCover(){
    if(coverFor===cover)return;coverFor=cover;
    const f=bakeWetGroundField(plan,cover);
    coverTexture?.dispose();
    coverTexture=new THREE.DataTexture(f.data,f.width,f.height,THREE.RGFormat,THREE.FloatType);
    coverTexture.minFilter=coverTexture.magFilter=THREE.NearestFilter;coverTexture.generateMipmaps=false;coverTexture.needsUpdate=true;
    uniforms.precipCover.value=coverTexture;uniforms.precipCoverBounds.value.fromArray(f.bounds);
  }
  const objects={},travels={};let last=null,clock=0,disposed=false,sample=()=>null,plan={},cover=createSkyCover(),credit=0,cursor=0,wasRaining=false;
  bakeCover();
  const motion=globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)');
  function mesh(name,g,vs,fs,own={}) {
    const material=new THREE.ShaderMaterial({name:'weather-'+name,uniforms:{...uniforms,...own},vertexShader:vs,fragmentShader:fs,
      transparent:true,depthWrite:false,depthTest:true,side:THREE.DoubleSide,lights:false,fog:false});
    const o=new THREE.Mesh(g,material);o.name='weather-'+name;o.frustumCulled=false;o.visible=false;
    o.onBeforeRender=renderer=>renderer.getDrawingBufferSize(uniforms.precipViewport.value);
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
  const capacity=192,sg=geometry(),positions=new Float32Array(capacity*3),normals=new Float32Array(capacity*3),born=new Float32Array(capacity).fill(-1e6);
  for(let i=0;i<capacity;i++)normals[i*3+1]=1;
  for(const [name,array,size] of [['splashPosition',positions,3],['splashNormal',normals,3],['splashBorn',born,1]])
    sg.setAttribute(name,new THREE.InstancedBufferAttribute(array,size).setUsage(THREE.DynamicDrawUsage));
  mesh('splash',sg,splashVertex,splashFragment);
  const api={group,objects,uniforms,
    setStage({centre,radius}){if(centre?.every(Number.isFinite))uniforms.precipCentre.value.fromArray(centre);if(Number.isFinite(radius)&&radius>0)uniforms.precipRadius.value=radius;},
    setPlan(value,roofs,skyCover){plan=value;cover=skyCover||createSkyCover(plan,roofs);coverFor=null;sample=createSplashSampler(plan,roofs,cover);born.fill(-1e6);sg.attributes.splashBorn.needsUpdate=true;credit=0;},
    update(now,weather,camera,{target=camera.position,bearing=180,level='house',unlit=false,colour=[.6,.7,.8],reduced=motion?.matches}={}){
      if(disposed)return;
      now=finite(now);const dt=last===null?0:clamp(now-last,0,1);last=now;clock+=dt*(reduced?.35:1);
      uniforms.precipClock.value=clock;uniforms.splashTime.value=now;uniforms.precipFog.value=weatherExtinction(weather);
      uniforms.precipRate.value=clamp(weather?.rate);
      if(colour?.every(Number.isFinite))uniforms.precipColour.value.fromArray(colour.map(c=>clamp(c,.015,1)));
      const halfExtent=clamp(.75*camera.position.distanceTo(target),18,64);
      const bottom=finite(groundAt(plan,target.x/FT,-target.z/FT))*FT;
      const top=Math.max(bottom+.0001,25,camera.position.y+8);
      uniforms.precipBox.value.set(halfExtent*2,top-bottom,halfExtent*2);
      uniforms.precipAnchor.value.copy(target).lerp(camera.position,.35);uniforms.precipAnchor.value.y=(bottom+top)*.5;
      // Owner 2026-11-19: rain shows whenever the camera is outside, in any orbit
      // view, room or floor focus included; drops under a roof are culled on the GPU.
      const indoors=Number.isFinite(cover.coverTop?.(camera.position.x,camera.position.z))
        &&camera.position.y<cover.coverTop(camera.position.x,camera.position.z);
      const hidden=unlit||indoors;
      uniforms.precipCutaway.value=level==='house'?0:1;
      const counts=precipitationCounts(tier,hidden?{}:weather);
      if(counts.rain||counts.snow||counts.hail||(!weather?.neutral&&(weather?.wetness>0||weather?.puddles>0)))bakeCover();
      for(const kind of ['rain','snow','hail']){
        const o=objects[kind],velocity=precipitationVelocity(kind,weather,bearing,reduced);
        o.geometry.instanceCount=counts[kind];o.visible=counts[kind]>0;
        o.material.uniforms.precipVelocity.value.fromArray(velocity);
        travels[kind].addScaledVector(o.material.uniforms.precipVelocity.value,dt);
        for(const axis of ['x','y','z']){const size=uniforms.precipBox.value[axis];travels[kind][axis]=((travels[kind][axis]%size)+size)%size;}
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
        credit--;const angle=clamp(random())*Math.PI*2,radius=Math.sqrt(clamp(random()))*16;
        const hit=sample(camera.position.x+Math.cos(angle)*radius,camera.position.z+Math.sin(angle)*radius);
        if(!hit)continue;
        positions.set(hit.position,cursor*3);normals.set(hit.normal,cursor*3);born[cursor]=now;cursor=(cursor+1)%capacity;changed=true;
      }
      if(changed)for(const attr of Object.values(sg.attributes))if(attr.isInstancedBufferAttribute)attr.needsUpdate=true;
      objects.splash.visible=born.some(t=>now-t>=0&&now-t<=LIFE);sg.instanceCount=objects.splash.visible?capacity:0;
    },
    dispose(){if(disposed)return;disposed=true;group.removeFromParent();coverTexture?.dispose();for(const o of Object.values(objects)){o.geometry.dispose();o.material.dispose();}},
  };
  return api;
}
