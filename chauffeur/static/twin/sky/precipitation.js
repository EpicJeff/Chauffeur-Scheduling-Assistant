import * as THREE from 'three';
import { groundAt, inPolygon, edgeDistance, buildingBase, buildingFootprint, poolDatum } from '../twin_ground.js';
import { heightAt } from '../twin_roof.js';
import { allPorches } from '../twin_generator.js';
import { pathSurfacePolygons } from '../path_shapes.js';
import { yardPaverLayout } from '../paver_path.js';
import { paverSettings } from '../paver_layout.js';
import { standingWaterAt } from './weather_surface.js';
import { weatherExtinction } from './weather.js';
import { createSkyCover, HEIGHT_NONE } from './sky_cover.js';
import { collectCapSurfaces, createCapBaker } from './wet_caps.js';
import { SPLASH_VARIANTS, splashProjectedPixels, splashGeometry, splashVertex, splashFragment } from './splash_shapes.js';

const FT=.3048, BOX=[128,96,128];
const RAIN={low:3000,medium:4000,high:8000,max:12000};
const KINDS=['rain','snow','hail'], DEFAULT_COLOUR=[.6,.7,.8];
const ATTEMPTS={low:120,medium:240,high:400,max:560};
const SPLASH_SIGMA={low:.30,medium:.42,high:.55,max:.65};
const FOCUS_RAYS=[[0,-.6],[-.6,-.6],[.6,-.6],[0,0],[-.6,0],[.6,0]];
const clamp=(x,a=0,b=1)=>Number.isFinite(x)?Math.max(a,Math.min(b,x)):a;
const finite=(x,fallback=0)=>Number.isFinite(x)?x:fallback;
export function precipitationCounts(tier,weather={},out={}) {
  const n=RAIN[tier]||RAIN.high,r=weather.neutral?0:clamp(weather.rate),kind=weather.precip;
  out.rain=Math.floor(n*r*(kind==='rain'?1:kind==='mix'?.5:0));
  out.snow=Math.floor(n*.5*r*(kind==='snow'?1:kind==='mix'?.5:0));
  out.hail=Math.floor(n*.3*r*(kind==='hail'?1:0));return out;
}
export function precipitationVelocity(kind,weather={},bearing=180,reduced=false,out=[]) {
  const speed=clamp(weather.windMps,0,60),angle=(finite(weather.windToDeg,90)-finite(bearing,180))*Math.PI/180+Math.PI;
  const x=Math.sin(angle),z=-Math.cos(angle);
  const factor=reduced?.35:1;
  out[0]=speed?x*speed*factor:0;out[1]=-(kind==='snow'?.9:kind==='hail'?18:14)*factor;out[2]=speed?z*speed*factor:0;return out;
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
// Ordinary mulch is at +.12 ft, below +.3 ft paving. Only an authored raised
// bed which actually covers this slab can cut its receiver (also level pavers).
const raisedBeds=(site,h)=>(site.beds||[]).filter(b=>b.polygon?.length>=3&&
  (h.flat!==null||finite(b.elevation)+.12>h.elevation));
const bedAbove=(plan,b,h,x,y)=>groundAt(plan,x,y)+finite(b.elevation)+.12>(h.flat??groundAt(plan,x,y))+h.elevation;

// Keep the cover grid's origin and cell size: expanding it cannot shift the
// rain's existing nearest-texel eave boundary. R retains the old cover height;
// G is the highest hardscape top (including the pad/grade underneath), metres.
export function bakeWetGroundField(plan={},cover=createSkyCover(plan),hard=collectHardSurfaces(plan),caps=collectCapSurfaces(plan)) {
  const f=cover.heightField(),cell=f.cell||.3;
  let [x0,z0,x1,z1]=f.bounds;
  for(const c of caps){
    x0=Math.min(x0,c.bounds[0]*FT-.3);z0=Math.min(z0,-c.bounds[3]*FT-.3);
    x1=Math.max(x1,c.bounds[2]*FT+.3);z1=Math.max(z1,-c.bounds[1]*FT+.3);
  }
  for(const h of hard){
    x0=Math.min(x0,h.bounds[0]*FT);z0=Math.min(z0,-h.bounds[3]*FT);
    x1=Math.max(x1,h.bounds[2]*FT);z1=Math.max(z1,-h.bounds[1]*FT);
  }
  x0=f.bounds[0]+Math.floor((x0-f.bounds[0])/cell)*cell;
  z0=f.bounds[1]+Math.floor((z0-f.bounds[1])/cell)*cell;
  const width=Math.max(1,Math.ceil((x1-x0)/cell)),height=Math.max(1,Math.ceil((z1-z0)/cell));
  const data=new Float32Array(width*height*2).fill(HEIGHT_NONE),site=plan.site||{};
  const excluded=waterPolygons(site);
  // Copy, rather than resample, the old cover texels bit-for-bit.
  const ox=Math.round((f.bounds[0]-x0)/cell),oz=Math.round((f.bounds[1]-z0)/cell);
  for(let j=0;j<f.height;j++)for(let i=0;i<f.width;i++)data[((j+oz)*width+i+ox)*2]=f.data[j*f.width+i];
  for(const h of hard){
    const beds=raisedBeds(site,h);
    const i0=Math.max(0,Math.floor((h.bounds[0]*FT-x0)/cell)),i1=Math.min(width-1,Math.floor((h.bounds[2]*FT-x0)/cell));
    const j0=Math.max(0,Math.floor((-h.bounds[3]*FT-z0)/cell)),j1=Math.min(height-1,Math.floor((-h.bounds[1]*FT-z0)/cell));
    for(let j=j0;j<=j1;j++)for(let i=i0;i<=i1;i++){
      const x=(x0+(i+.5)*cell)/FT,y=-(z0+(j+.5)*cell)/FT;
      if(!inPolygon(h.polygon,x,y)||excluded.some(p=>inPolygon(p,x,y))||beds.some(b=>inPolygon(b.polygon,x,y)&&bedAbove(plan,b,h,x,y)))continue;
      const top=((h.flat??groundAt(plan,x,y))+h.elevation)*FT,index=(j*width+i)*2+1;
      data[index]=Math.max(data[index],top);
    }
  }
  return {cell,width,height,bounds:[x0,z0,x0+width*cell,z0+height*cell],data};
}

function polygonEdgeDistance(poly,x,y) {
  let best=Infinity;
  for(let i=0;i<poly.length;i++){
    const a=poly[i],b=poly[(i+1)%poly.length];
    const d=edgeDistance([x,y],a,b);
    if(d<best)best=d;
  }
  return best;
}

// Incremental builder for the smooth signed-distance + dilated-height SSR field.
// Matches bakeWetGroundField's exact world bounds at finer resolution with
// LinearFilter so curved walkways, straight edges and rotated roof drip lines
// never stair-step on 0.3 m nearest-neighbour texels.
// R: signed distance outside sky cover (m, clamped [-1,1]; <0 covered, >0 open)
// G: signed distance inside hardscape minus pool/spa (m, clamped [-1,1]; >0 inside)
// B: dilated cover ceiling height (m; valid across the drip line, HEIGHT_NONE far out)
// A: dilated hardscape top height (m; valid across polygon edges, HEIGHT_NONE far out)
// Hardscape is rasterized first; cover SDF runs only on cells near hardscape
// (where SSR can ever accept a pixel), avoiding ~90% of empty-lot work.
export function createWetSurfaceBaker(plan={},cover=createSkyCover(plan),hard=collectHardSurfaces(plan),{cell=.15,caps=collectCapSurfaces(plan)}={}) {
  const f=cover.heightField(),baseCell=f.cell||.3;
  let [x0,z0,x1,z1]=f.bounds;
  for(const c of caps){
    x0=Math.min(x0,c.bounds[0]*FT-.3);z0=Math.min(z0,-c.bounds[3]*FT-.3);
    x1=Math.max(x1,c.bounds[2]*FT+.3);z1=Math.max(z1,-c.bounds[1]*FT+.3);
  }
  for(const h of hard){
    x0=Math.min(x0,h.bounds[0]*FT);z0=Math.min(z0,-h.bounds[3]*FT);
    x1=Math.max(x1,h.bounds[2]*FT);z1=Math.max(z1,-h.bounds[1]*FT);
  }
  x0=f.bounds[0]+Math.floor((x0-f.bounds[0])/baseCell)*baseCell;
  z0=f.bounds[1]+Math.floor((z0-f.bounds[1])/baseCell)*baseCell;
  const spanX=Math.max(1,Math.ceil((x1-x0)/baseCell))*baseCell;
  const spanZ=Math.max(1,Math.ceil((z1-z0)/baseCell))*baseCell;
  const width=Math.max(1,Math.round(spanX/cell)),height=Math.max(1,Math.round(spanZ/cell));
  const actualCellX=spanX/width,actualCellZ=spanZ/height;
  const data=new Float32Array(width*height*4);
  for(let k=0;k<data.length;k+=4){data[k]=1;data[k+1]=-1;data[k+2]=HEIGHT_NONE;data[k+3]=HEIGHT_NONE;}
  const site=plan.site||{},margin=.6,marginFt=margin/FT;
  const excluded=waterPolygons(site).map(polygon=>({
    polygon,bounds:[Math.min(...polygon.map(p=>p[0])),Math.min(...polygon.map(p=>p[1])),
      Math.max(...polygon.map(p=>p[0])),Math.max(...polygon.map(p=>p[1]))],
  }));
  const hardBoxes=hard.map(h=>({
    h,excluded:[...excluded,...raisedBeds(site,h).map(b=>({polygon:b.polygon,bed:b,bounds:[Math.min(...b.polygon.map(p=>p[0])),Math.min(...b.polygon.map(p=>p[1])),Math.max(...b.polygon.map(p=>p[0])),Math.max(...b.polygon.map(p=>p[1]))]}))],
    i0:Math.max(0,Math.floor((h.bounds[0]*FT-margin-x0)/actualCellX)),
    i1:Math.min(width-1,Math.floor((h.bounds[2]*FT+margin-x0)/actualCellX)),
    j0:Math.max(0,Math.floor((-h.bounds[3]*FT-margin-z0)/actualCellZ)),
    j1:Math.min(height-1,Math.floor((-h.bounds[1]*FT+margin-z0)/actualCellZ)),
  }));
  const cb=cover.bounds,hasCover=!!(cb&&Number.isFinite(cb.x0)&&cover.coverSignedDistance);
  const ci0=hasCover?Math.max(0,Math.floor((cb.x0-1-x0)/actualCellX)):0;
  const ci1=hasCover?Math.min(width-1,Math.floor((cb.x1+1-x0)/actualCellX)):-1;
  const cj0=hasCover?Math.max(0,Math.floor((cb.z0-1-z0)/actualCellZ)):0;
  const cj1=hasCover?Math.min(height-1,Math.floor((cb.z1+1-z0)/actualCellZ)):-1;
  let phase=0,hIdx=0,row=hardBoxes[0]?.j0??0,done=false;
  const result={cell:actualCellX,width,height,bounds:[x0,z0,x0+spanX,z0+spanZ],data};
  const capBaker=createCapBaker(caps,result);
  result.caps=capBaker.result;
  function step(budgetMs=Infinity) {
    if(done)return true;
    const deadline=Number.isFinite(budgetMs)?performance.now()+Math.max(0,budgetMs):Infinity;
    while(phase===0){
      if(hIdx>=hardBoxes.length){phase=1;row=cj0;break;}
      const box=hardBoxes[hIdx],{h,i0,i1,j1}=box;
      while(row<=j1){
        const y=-(z0+(row+.5)*actualCellZ)/FT;
        for(let i=i0;i<=i1;i++){
          const x=(x0+(i+.5)*actualCellX)/FT;
          const insideH=inPolygon(h.polygon,x,y);
          const d=Math.min(1,polygonEdgeDistance(h.polygon,x,y)*FT);
          let signed=insideH?d:-d;
          if(signed>-margin){
            for(const ex of box.excluded){
              if(x<ex.bounds[0]-marginFt||x>ex.bounds[2]+marginFt||y<ex.bounds[1]-marginFt||y>ex.bounds[3]+marginFt)continue;
              if(ex.bed&&!bedAbove(plan,ex.bed,h,x,y))continue;
              const inEx=inPolygon(ex.polygon,x,y),dEx=Math.min(1,polygonEdgeDistance(ex.polygon,x,y)*FT);
              signed=Math.min(signed,inEx?-dEx:dEx);
            }
          }
          const idx=(row*width+i)*4;
          if(signed>data[idx+1]){
            data[idx+1]=signed;
            if(signed>-.45)data[idx+3]=((h.flat??groundAt(plan,x,y))+h.elevation)*FT;
          }
        }
        row++;
        if(performance.now()>=deadline)return false;
      }
      hIdx++;row=hardBoxes[hIdx]?.j0??0;
    }
    if(phase===1){
      if(!capBaker.step(Number.isFinite(deadline)?Math.max(0,deadline-performance.now()):Infinity))return false;
      phase=2;
    }
    if(phase===2){
      if(!hasCover||ci0>ci1||cj0>cj1){done=true;return true;}
      while(row<=cj1){
        const wz=z0+(row+.5)*actualCellZ;
        for(let i=ci0;i<=ci1;i++){
          const idx=(row*width+i)*4;
          if(data[idx+1]<=-.45&&result.caps.data[(row*width+i)*2]<=-.3)continue;
          const wx=x0+(i+.5)*actualCellX;
          const res=cover.coverSignedDistance(wx,wz);
          data[idx]=res.distance;data[idx+2]=res.top;
        }
        row++;
        if(performance.now()>=deadline)return false;
      }
      done=true;
    }
    return true;
  }
  return {step,finish(){step(Infinity);return result;},get done(){return done;},result};
}

export function bakeWetSurfaceField(plan={},cover=createSkyCover(plan),hard=collectHardSurfaces(plan),options={}) {
  return createWetSurfaceBaker(plan,cover,hard,options).finish();
}

function packHalfFloatRGBA(data) {
  const half=new Uint16Array(data.length);
  for(let i=0;i<data.length;i++)half[i]=THREE.DataUtils.toHalfFloat(data[i]);
  return half;
}

export function createSplashSampler(plan={},roofs=new Map(),cover=createSkyCover(plan,roofs)) {
  const site=plan.site||{},hard=collectHardSurfaces(plan);
  const water=waterPolygons(site).map(polygon=>{
    const pool=site.pool,base=poolDatum(plan,pool);let height=base-.25;
    for(const f of pool.features||[])if(f.kind==='spa'&&f.polygon===polygon){
      height=(f.mode??'raised')==='raised'?base+.45+(f.raise_in??12)/12-2/12:height;
    }
    return {polygon,height};
  });
  const beds=(site.beds||[]).map(b=>b.polygon).filter(Boolean);
  const buildings=(plan.buildings||[]).map(b=>{
    const angle=finite(b.rotation)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),pos=b.position||[0,0];
    return {b,c,s,pos,base:buildingBase(plan,b),footprint:buildingFootprint(b),porches:allPorches(b),sections:roofs?.get(b.id)?.sections||[]};
  });
  const normalScratch=new THREE.Vector3();
  let bestHeight,bestKind,bestX,bestY,bestZ;
  const offer=(height,kind,nx=0,ny=1,nz=0)=>{
    if(Number.isFinite(height)&&ny>.55&&height>bestHeight){bestHeight=height;bestKind=kind;bestX=nx;bestY=ny;bestZ=nz;}
  };
  return (worldX,worldZ,out)=>{
    if(!Number.isFinite(worldX)||!Number.isFinite(worldZ))return null;
    const x=worldX/FT,y=-worldZ/FT;
    let blocked=false,roofTop=-Infinity;bestHeight=-Infinity;
    for(const {b,c,s,pos,base,footprint,porches,sections} of buildings){
      const dx=x-pos[0],dy=y-pos[1],u=dx*c+dy*s,v=-dx*s+dy*c;
      if(inPolygon(footprint,u,v))blocked=true;
      for(const p of porches)if(p.polygon&&inPolygon(p.polygon,u,v)){
        let room;for(const r of b.rooms||[])if(r.kind==='porch'&&r.state!=='ghost'&&r.level===(p.level||b.levels?.[0]?.id)&&inPolygon(r.polygon,u,v)){room=r;break;}
        offer(base+finite(p.floor)+finite(room?.floor_offset_ft),'deck');
      }
      const h=heightAt(sections,u,v);
      if(h!==null){
        roofTop=Math.max(roofTop,base+h);
        // Analytic roof envelope, including overhangs and raised/rotated buildings.
        const e=.01,hx=heightAt(sections,u+e,v)??h,hy=heightAt(sections,u,v+e)??h;
        const a=(hx-h)/e,d=(hy-h)/e,n=normalScratch.set(-a*c+d*s,1,a*s+d*c).normalize();
        offer(base+h,'roof',n.x,n.y,n.z);
      }
    }
    let excluded=false;
    for(const w of water)if(inPolygon(w.polygon,x,y)){
      excluded=true;if(!blocked)offer(w.height,'water');
    }
    if(!excluded)for(const p of beds)if(inPolygon(p,x,y)){excluded=true;break;}
    if(!blocked&&!excluded){
      for(const h of hard)if(x>=h.bounds[0]&&y>=h.bounds[1]&&x<=h.bounds[2]&&y<=h.bounds[3]&&inPolygon(h.polygon,x,y)){
        const g=h.flat??groundAt(plan,x,y),e=.05,gx=h.flat===null?(groundAt(plan,x+e,y)-g)/e:0,gy=h.flat===null?(groundAt(plan,x,y+e)-g)/e:0;
        const n=normalScratch.set(-gx,1,gy).normalize();offer(g+h.elevation,'hardscape',n.x,n.y,n.z);
      }
    }
    if(bestHeight===-Infinity||bestHeight<roofTop-1e-6)return null;
    const h=bestHeight*FT+.006;
    if(cover.blocked(worldX,h,worldZ))return null;
    const hit=out||{kind:null,normal:[0,1,0],position:[0,0,0]};hit.kind=bestKind;
    hit.normal[0]=bestX;hit.normal[1]=bestY;hit.normal[2]=bestZ;
    hit.position[0]=worldX;hit.position[1]=h;hit.position[2]=worldZ;return hit;
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
float precipitationSegment(float depth) {
  return min(.7,max(.02,depth*.35));
}
bool precipitationVisibleDepth(float depth,float kind) {
  return depth>=(kind<.5?.08:3.5);
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
  if(distance(world,cameraPosition)<(precipKind<.5?.06:3.0)){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  // Radial distance misses drops beside the eye plane. Cull by forward depth
  // too. Rain shortens its physical segment near the eye, so both endpoints
  // stay in front of it; close views no longer need the old 3.5 m dead zone.
  if(!precipitationVisibleDepth(-eye.z,precipKind)){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
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
  float segment=precipitationSegment(-eye.z);
  vec4 head=projectionMatrix*(eye+vec4(fall*segment*.5,0.0));
  vec4 tail=projectionMatrix*(eye-vec4(fall*segment*.5,0.0));
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
float precipitationFade(float nearStart,float nearEnd,float boxWeight){
  float d=distance(particleWorld,cameraPosition);
  float radius=max(precipRadius,.0001);
  float haze=smoothstep(radius,radius*1.35,distance(particleWorld.xz,precipCentre));
  float halfExtent=max(precipBox.x*.5,.0001);
  float edge=distance(particleWorld.xz,precipAnchor.xz);
  return mix(1.0,1.0-smoothstep(halfExtent*.8,halfExtent,edge),boxWeight) * smoothstep(nearStart,nearEnd,d)*(1.0-haze)*exp(-max(precipFog,0.0)*d);
}
vec3 precipSafe(vec3 c){return vec3(c.r>=0.0?min(c.r,4096.0):0.0,c.g>=0.0?min(c.g,4096.0):0.0,c.b>=0.0?min(c.b,4096.0):0.0);}
`;
const fragmentShader=fragmentCommon+`
uniform float precipKind,precipRate;
void main(){
  if(distance(particleWorld,cameraPosition)<(precipKind<.5?.06:3.0))discard;
  vec2 p=particleUv*2.0-1.0;
  float alpha=precipKind<.5?(1.0-smoothstep(.3,1.0,abs(p.x)))*(1.0-abs(p.y))*mix(.35,.85,precipRate):
    (1.0-smoothstep(.5,1.0,length(p)))*.8;
  alpha*=precipitationFade(precipKind<.5?.06:3.0,precipKind<.5?.12:3.5,1.0);
  if(alpha<.001)discard;
  // Hemisphere colour has unit peak; lift rain just above the overcast sky.
  gl_FragColor=vec4(precipSafe(precipColour*(precipKind<.5?1.2:1.0)),clamp(alpha,0.0,1.0));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

function geometry() {
  const g=new THREE.InstancedBufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([-.5,-.5,0,.5,-.5,0,.5,.5,0,-.5,.5,0],3));
  g.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,1],2));g.setIndex([0,1,2,0,2,3]);g.instanceCount=0;
  return g;
}
export function createPrecipitation(scene,{tier='high',random=Math.random,debugClock=()=>performance.now()/1000}={}) {
  const group=new THREE.Group();group.name='weather-precipitation';scene.add(group);
  // No domain ownership, picking layer or effect fixture: editor hide/lock does
  // not classify these. Extras excludes the whole group from every capture.
  const uniforms={precipAnchor:{value:new THREE.Vector3()},precipBox:{value:new THREE.Vector3(36,25,36)},precipColour:{value:new THREE.Vector3(.6,.7,.8)},
    precipViewport:{value:new THREE.Vector2(1280,720)},precipRate:{value:0},
    precipCentre:{value:new THREE.Vector2()},precipRadius:{value:100},precipFog:{value:0},
    precipClock:{value:0},splashTime:{value:0},
    touchLight:{value:new THREE.Vector3(1,1,1)},splashEnvironment:{value:null},splashEnvironmentGain:{value:1},
    splashSunDirection:{value:new THREE.Vector3(0,1,0)},splashSunColour:{value:new THREE.Color(1,1,1)},splashSunVisibility:{value:1},
    precipCover:{value:null},precipEdge:{value:null},precipCaps:{value:null},precipCoverBounds:{value:new THREE.Vector4(0,0,1,1)},precipCutaway:{value:0}};
  let coverTexture=null,edgeTexture=null,capsTexture=null,coverFor=null,edgeFor=null,edgeBaker=null,edgeIdle=null,capSources=null;
  const cancelEdgeIdle=()=>{if(edgeIdle!==null){globalThis.cancelIdleCallback?.(edgeIdle);edgeIdle=null;}};
  const getCaps=()=>capSources??(capSources=collectCapSurfaces(plan));
  function uploadEdge(e){
    edgeTexture?.dispose();
    capsTexture?.dispose();
    // RGBA16F (HalfFloatType) is mandatorily filterable in WebGL2 without
    // OES_texture_float_linear; -1e4 is exact and heights retain ~2 mm accuracy.
    edgeTexture=new THREE.DataTexture(packHalfFloatRGBA(e.data),e.width,e.height,THREE.RGBAFormat,THREE.HalfFloatType);
    edgeTexture.minFilter=edgeTexture.magFilter=THREE.LinearFilter;edgeTexture.generateMipmaps=false;edgeTexture.needsUpdate=true;
    capsTexture=new THREE.DataTexture(packHalfFloatRGBA(e.caps.data),e.width,e.height,THREE.RGFormat,THREE.HalfFloatType);
    capsTexture.minFilter=capsTexture.magFilter=THREE.LinearFilter;capsTexture.generateMipmaps=false;capsTexture.needsUpdate=true;
    uniforms.precipCaps.value=capsTexture;
    uniforms.precipEdge.value=edgeTexture;uniforms.precipCoverBounds.value.fromArray(e.bounds);edgeFor=cover;edgeBaker=null;
  }
  function scheduleEdgeIdle(){
    if(disposed||edgeFor===cover||edgeIdle!==null||typeof globalThis.requestIdleCallback!=='function')return;
    edgeIdle=globalThis.requestIdleCallback(deadline=>{
      edgeIdle=null;
      if(disposed||edgeFor===cover)return;
      if(!edgeBaker)edgeBaker=createWetSurfaceBaker(plan,cover,collectHardSurfaces(plan),{caps:getCaps()});
      const budget=Math.max(1,Math.min(6,deadline?.timeRemaining?.()??4));
      if(edgeBaker.step(budget))uploadEdge(edgeBaker.result);
      else scheduleEdgeIdle();
    },{timeout:500});
  }
  // Bake once per plan/cover while falling OR still wet after the rain stops.
  // In a browser, the finer SSR SDF field runs off-frame via requestIdleCallback
  // (or at most 2 ms per wet frame) so it never hitches a live frame.
  function bakeCover(syncEdge=false){
    const hard=coverFor!==cover||(edgeFor!==cover&&!edgeBaker)?collectHardSurfaces(plan):null;
    if(coverFor!==cover){
      coverFor=cover;
      const f=bakeWetGroundField(plan,cover,hard,getCaps());
      coverTexture?.dispose();
      coverTexture=new THREE.DataTexture(f.data,f.width,f.height,THREE.RGFormat,THREE.FloatType);
      coverTexture.minFilter=coverTexture.magFilter=THREE.NearestFilter;coverTexture.generateMipmaps=false;coverTexture.needsUpdate=true;
      uniforms.precipCover.value=coverTexture;uniforms.precipCoverBounds.value.fromArray(f.bounds);
    }
    if(edgeFor!==cover){
      if(!edgeBaker)edgeBaker=createWetSurfaceBaker(plan,cover,hard,{caps:getCaps()});
      const budget=syncEdge||typeof globalThis.requestIdleCallback!=='function'?Infinity:2;
      if(edgeBaker.step(budget)){cancelEdgeIdle();uploadEdge(edgeBaker.result);}
      else scheduleEdgeIdle();
    }
  }
  const objects={},travels={},countScratch={},velocityScratch=[0,0,0],noWeather={};let last=null,clock=0,disposed=false,sample=()=>null,plan={},cover=createSkyCover(),credit=0,wasRaining=false;
  bakeCover(true);
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
  // Three independent 64-slot rings retain the old total cap of 192. A slot
  // belongs to exactly one draw, rather than submitting all slots in all meshes.
  const splashes=SPLASH_VARIANTS.map((variant,index)=>{
    const capacity=64,data={};
    for(const [name,size] of [['splashPosition',3],['splashNormal',3],['splashBorn',1],['splashShape',3],['splashWater',1]]){
      const array=new Float32Array(capacity*size);if(name==='splashBorn')array.fill(-1e6);
      data[name]=new THREE.InstancedBufferAttribute(array,size);
    }
    const lods=[0,1].map(lod=>{
      const g=splashGeometry(variant,tier,lod);
      for(const name in data)g.setAttribute(name,new THREE.InstancedBufferAttribute(new Float32Array(capacity*data[name].itemSize),data[name].itemSize).setUsage(THREE.DynamicDrawUsage));
      const name=(index?'splash-'+variant:'splash')+(lod?'-far':'');
      return mesh(name,g,splashVertex,fragmentCommon+splashFragment,{splashBeadCount:{value:g.userData.droplets}});
    });
    return {object:lods[0],lods,data,cursor:0,count:0};
  });
  function clearSplashes(){
    for(const ring of splashes){
      ring.data.splashBorn.array.fill(-1e6);ring.cursor=ring.count=0;
      for(const object of ring.lods){object.visible=false;object.geometry.instanceCount=0;}
    }
  }
  // Gaussian importance sampling concentrates the same birth budget in the
  // closest visible patch. A screen-ray tail reaches the rest of the frustum.
  // No rays, matrices, hits or geometry are allocated in update().
  const focus=new THREE.Vector3(),ray=new THREE.Vector3(),origin=new THREE.Vector3(),projected=new THREE.Vector3(),eyePoint=new THREE.Vector3();
  const lastWorld=new THREE.Matrix4(),lastProjection=new THREE.Matrix4();
  const hitScratch={kind:null,normal:[0,1,0],position:[0,0,0]};
  let focusReady=false,focusValid=false,lastViewport=0,lastCutaway=-1,debug=null,lastHidden=false,splashWeather=noWeather,lastCamera=null;
  function eligible(hit,camera,pixels=true){
    if(!hit||uniforms.precipCutaway.value>.5&&Number.isFinite(cover.coverTop(hit.position[0],hit.position[2])))return false;
    eyePoint.fromArray(hit.position).applyMatrix4(camera.matrixWorldInverse);
    const depth=-eyePoint.z;
    if(depth<.03)return false;
    if(pixels&&.04*.7*Math.abs(camera.projectionMatrix.elements[5])*uniforms.precipViewport.value.y*.5/(camera.isOrthographicCamera?1:depth)<2)return false;
    projected.fromArray(hit.position).project(camera);
    return Math.abs(projected.x)<1&&Math.abs(projected.y)<1&&projected.z>=-1&&projected.z<=1;
  }
  function groundRay(x,y,camera){
    if(camera.isOrthographicCamera){origin.set(x,y,-1).unproject(camera);camera.getWorldDirection(ray);}
    else {origin.copy(camera.position);ray.set(x,y,.5).unproject(camera).sub(origin).normalize();}
    if(ray.y>=-.001)return null;
    let height=groundAt(plan,camera.position.x/FT,-camera.position.z/FT)*FT,hit;
    // Correct the ground-plane intersection to actual deck/roof/grade height.
    for(let pass=0;pass<3;pass++){
      const t=(height-origin.y)/ray.y;if(t<=0)return null;
      hit=sample(origin.x+ray.x*t,origin.z+ray.z*t,hitScratch);
      if(!hit)return null;
      if(Math.abs(hit.position[1]-height)<.005)return hit;
      height=hit.position[1];
    }
    return hit;
  }
  function findFocus(camera){
    camera.updateMatrixWorld();
    const viewport=uniforms.precipViewport.value.y;
    if(focusReady&&lastViewport===viewport&&lastCutaway===uniforms.precipCutaway.value&&lastWorld.equals(camera.matrixWorld)&&lastProjection.equals(camera.projectionMatrix))return focusValid;
    focusReady=true;focusValid=false;lastViewport=viewport;lastCutaway=uniforms.precipCutaway.value;lastWorld.copy(camera.matrixWorld);lastProjection.copy(camera.projectionMatrix);
    let nearest=Infinity;
    for(const point of FOCUS_RAYS){
      const hit=groundRay(point[0],point[1],camera);
      if(!eligible(hit,camera))continue;
      const d=camera.position.distanceToSquared(eyePoint.fromArray(hit.position));
      if(d<nearest){nearest=d;focus.fromArray(hit.position);focusValid=true;}
    }
    return focusValid;
  }
  function putSplash(hit,birth,variant=-1){
    const standing=hit.kind==='water'||(hit.kind==='hardscape'||hit.kind==='deck')&&standingWaterAt(hit.position[0],hit.position[2],hit.normal[1],splashWeather)>.5;
    if(variant<0){const roll=clamp(random());variant=standing?Math.min(2,Math.floor(roll*3)):(roll<.5?0:2);}
    if(variant===1&&!standing)return false;
    const ring=splashes[variant],attrs=ring.data,i=ring.cursor;
    attrs.splashWater.setX(i,standing?1:0);
    attrs.splashPosition.array.set(hit.position,i*3);attrs.splashNormal.array.set(hit.normal,i*3);attrs.splashBorn.array[i]=birth;
    attrs.splashShape.setXYZ(i,clamp(random())*Math.PI*2,.7+.6*clamp(random()),.12+.18*clamp(random()));
    ring.cursor=(i+1)%64;ring.count=Math.min(64,ring.count+1);return true;
  }
  function showSplashes(time,hidden=false){
    lastCamera?.updateMatrixWorld();
    const view=lastCamera?.matrixWorldInverse.elements,projection=lastCamera?.projectionMatrix.elements;
    for(const ring of splashes){
      const data=ring.data,born=data.splashBorn.array,shape=data.splashShape.array,positions=data.splashPosition.array;
      for(const object of ring.lods)object.geometry.instanceCount=0;
      if(!hidden)for(let i=0;i<ring.count;i++){
        if(time<born[i]||time-born[i]>shape[i*3+2])continue;
        const depth=view?-(view[2]*positions[i*3]+view[6]*positions[i*3+1]+view[10]*positions[i*3+2]+view[14]):1;
        const pixels=projection?splashProjectedPixels(depth,shape[i*3+1],projection[5],uniforms.precipViewport.value.y,lastCamera.isOrthographicCamera):Infinity;
        const object=ring.lods[pixels>=24?0:1],g=object.geometry,slot=g.instanceCount++;
        // Partition existing live slots, never duplicate an impact between
        // LODs. Fixed draw buffers avoid slice/subarray allocation each frame.
        for(const name in data){
          const source=data[name],target=g.attributes[name],size=source.itemSize;
          for(let k=0;k<size;k++)target.array[slot*size+k]=source.array[i*size+k];
        }
      }
      for(const object of ring.lods){
        object.visible=object.geometry.instanceCount>0;
        if(object.visible)for(const name in data)object.geometry.attributes[name].needsUpdate=true;
      }
    }
  }
  const api={group,objects,uniforms,splashes,
    debugSplashes(value){
      if(disposed)return 0;
      clearSplashes();credit=0;debug=null;
      if(value===null){uniforms.splashTime.value=finite(debugClock(),last??0);return 0;}
      if(!Array.isArray(value?.at)||value.at.length!==3||!value.at.every(Number.isFinite))throw new Error('debugSplashes requires at:[x,y,z]');
      const variant=value.variant==null?-1:SPLASH_VARIANTS.indexOf(value.variant);
      if(variant<0&&value.variant!=null)throw new Error('Unknown splash variant');
      const birth=finite(debugClock(),last??0),radius=clamp(value.radius,0,100),count=Math.floor(clamp(value.count??1,0,variant<0?192:64));
      debug={birth,freezeAge:Number.isFinite(value.freezeAge)?clamp(value.freezeAge,0,.3):null};
      bakeCover();
      for(let i=0;i<count;i++){
        const a=clamp(random())*Math.PI*2,r=Math.sqrt(clamp(random()))*radius;
        hitScratch.position[0]=value.at[0]+Math.cos(a)*r;hitScratch.position[1]=value.at[1]+.006;hitScratch.position[2]=value.at[2]+Math.sin(a)*r;
        hitScratch.normal[0]=hitScratch.normal[2]=0;hitScratch.normal[1]=1;
        if(cover.blocked(...hitScratch.position)||uniforms.precipCutaway.value>.5&&Number.isFinite(cover.coverTop(hitScratch.position[0],hitScratch.position[2])))continue;
        const receiver=sample(hitScratch.position[0],hitScratch.position[2]);
        hitScratch.kind=receiver?.kind||null;
        let v=variant;
        if(v<0){
          const standing=hitScratch.kind==='water'||(hitScratch.kind==='hardscape'||hitScratch.kind==='deck')&&standingWaterAt(hitScratch.position[0],hitScratch.position[2],1,splashWeather)>.5;
          const roll=clamp(random());v=standing?Math.min(2,Math.floor(roll*3)):(roll<.5?0:2);
          if(splashes[v].count===64)v=v===0?2:0;
          if(splashes[v].count===64&&standing)v=1;
          if(splashes[v].count===64)continue;
        }
        putSplash(hitScratch,birth,v);
      }
      uniforms.splashTime.value=birth+(debug.freezeAge??0);showSplashes(uniforms.splashTime.value,lastHidden);
      return splashes[0].count+splashes[1].count+splashes[2].count;
    },
    setStage({centre,radius}){if(centre?.every(Number.isFinite))uniforms.precipCentre.value.fromArray(centre);if(Number.isFinite(radius)&&radius>0)uniforms.precipRadius.value=radius;},
    setPlan(value,roofs,skyCover){capSources=null;plan=value;cover=skyCover||createSkyCover(plan,roofs);coverFor=null;edgeFor=null;edgeBaker=null;cancelEdgeIdle();edgeTexture?.dispose();edgeTexture=null;uniforms.precipEdge.value=null;capsTexture?.dispose();capsTexture=null;uniforms.precipCaps.value=null;sample=createSplashSampler(plan,roofs,cover);clearSplashes();credit=0;focusReady=false;debug=null;scheduleEdgeIdle();},
    update(now,weather,camera,{target=camera.position,bearing=180,level='house',unlit=false,colour=DEFAULT_COLOUR,light,sunDirection,sunColour,sunVisibility=1,environment=scene.environment,environmentGain=scene.environmentIntensity ?? 1,reduced=motion?.matches}={}){
      if(disposed)return;
      splashWeather=weather||noWeather;lastCamera=camera;
      now=finite(now);const dt=last===null?0:clamp(now-last,0,1);last=now;clock+=dt*(reduced?.35:1);
      uniforms.precipClock.value=clock;uniforms.splashTime.value=debug&&debug.freezeAge!==null?debug.birth+debug.freezeAge:now;uniforms.precipFog.value=weatherExtinction(weather);
      uniforms.precipRate.value=clamp(weather?.rate);
      if(colour)for(let i=0;i<3;i++)uniforms.precipColour.value.setComponent(i,clamp(colour[i],.015,1));
      if(light)uniforms.touchLight.value.fromArray(light);
      if(sunDirection)uniforms.splashSunDirection.value.copy(sunDirection);
      if(sunColour)uniforms.splashSunColour.value.copy(sunColour);
      uniforms.splashSunVisibility.value=clamp(sunVisibility);
      uniforms.splashEnvironment.value=environment;
      uniforms.splashEnvironmentGain.value=Math.max(0,finite(environmentGain));
      const localRain=weather?.precip==='rain'||weather?.precip==='mix';
      const halfExtent=clamp(.75*camera.position.distanceTo(target),localRain?1:18,64);
      const bottom=finite(groundAt(plan,target.x/FT,-target.z/FT))*FT;
      const top=localRain?Math.max(bottom+1,25*clamp(halfExtent*halfExtent/324),camera.position.y+clamp(halfExtent*.4,.8,8))
        :Math.max(bottom+.0001,25,camera.position.y+8);
      uniforms.precipBox.value.set(halfExtent*2,top-bottom,halfExtent*2);
      uniforms.precipAnchor.value.copy(camera.position);uniforms.precipAnchor.value.y=(bottom+top)*.5;
      // Owner 2026-11-19: rain shows whenever the camera is outside, in any orbit
      // view, room or floor focus included; drops under a roof are culled on the GPU.
      const indoors=Number.isFinite(cover.coverTop?.(camera.position.x,camera.position.z))
        &&camera.position.y<cover.coverTop(camera.position.x,camera.position.z);
      const hidden=unlit||indoors;lastHidden=hidden;
      uniforms.precipCutaway.value=level==='house'?0:1;
      const counts=precipitationCounts(tier,hidden?noWeather:weather,countScratch);
      if(counts.rain||counts.snow||counts.hail||(!weather?.neutral&&(weather?.wetness>0||weather?.puddles>0)))bakeCover();
      for(const kind of KINDS){
        const o=objects[kind],velocity=precipitationVelocity(kind,weather,bearing,reduced,velocityScratch);
        o.geometry.instanceCount=counts[kind];o.visible=counts[kind]>0;
        o.material.uniforms.precipVelocity.value.fromArray(velocity);
        travels[kind].addScaledVector(o.material.uniforms.precipVelocity.value,dt);
        for(let axis=0;axis<3;axis++){const size=uniforms.precipBox.value.getComponent(axis),v=travels[kind].getComponent(axis);travels[kind].setComponent(axis,((v%size)+size)%size);}
      }
      if(debug){showSplashes(uniforms.splashTime.value,hidden);return;}
      const raining=counts.rain>0;
      if(!raining){
        if(wasRaining)clearSplashes();
        wasRaining=false;credit=0;return;
      }
      wasRaining=true;
      const focused=findFocus(camera);
      credit=Math.min(12,credit+dt*(ATTEMPTS[tier]||72)*Math.pow(clamp(weather.rate),1.3));
      while(credit>=1){
        credit--;
        const near=clamp(random())<.85,u=clamp(random()),v=clamp(random());
        let hit;
        if(near&&focused){
          const radius=Math.sqrt(-2*Math.log(Math.max(1e-6,1-u)))*(SPLASH_SIGMA[tier]||.55),angle=v*Math.PI*2;
          hit=sample(focus.x+Math.cos(angle)*radius,focus.z+Math.sin(angle)*radius,hitScratch);
        }else hit=groundRay(u*2-1,v*2-1,camera);
        if(eligible(hit,camera))putSplash(hit,now);
      }
      showSplashes(now);
    },
    dispose(){if(disposed)return;disposed=true;cancelEdgeIdle();edgeBaker=null;group.removeFromParent();coverTexture?.dispose();edgeTexture?.dispose();capsTexture?.dispose();for(const o of Object.values(objects)){o.geometry.dispose();o.material.dispose();}},
  };
  return api;
}
