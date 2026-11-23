// Roof envelope -> exposed downhill edges -> immutable GPU instances. All plan
// queries and downward rays happen on rebuild, never in update(). No lit patch.
import * as THREE from 'three';
import { roofMesh, planes } from '../twin_roof.js';
import { buildingBase, groundAt, inPolygon, segmentIntersection, poolDatum } from '../twin_ground.js';
import { allPorches } from '../twin_generator.js';
import { resolveSurfaceMaterial } from '../surface_material.js';
import { collectHardSurfaces } from './precipitation.js';
import { collectCapSurfaces } from './wet_caps.js';

const FT=.3048, EPS=2e-4;
const clamp=x=>Number.isFinite(x)?Math.max(0,Math.min(1,x)):0;
const smooth=(a,b,x)=>{const t=clamp((x-a)/(b-a));return t*t*(3-2*t);};
const LOD_NEAR=8,LOD_FAR=42;
const hash=n=>{n=Math.imul(n^(n>>>16),0x45d9f3b);n=Math.imul(n^(n>>>16),0x45d9f3b);return ((n^(n>>>16))>>>0)/4294967296;};
function buildingFrame(plan,b) {
  const a=(b.rotation||0)*Math.PI/180,c=Math.cos(a),s=Math.sin(a),p=b.position||[0,0],base=buildingBase(plan,b);
  return {b,base,
    world:([x,y,z])=>[(p[0]+c*x-s*y)*FT,(base+z)*FT,-(p[1]+s*x+c*y)*FT],
    local:([x,,z])=>{const u=x/FT-p[0],v=-z/FT-p[1];return [c*u+s*v,-s*u+c*v];}};
}

// Use the same material inheritance as the roof builder. Its procedural
// standing seams are on a 1.5 ft grid. Imported materials may expose pitch_m.
function eavePattern(plan,b,s,edge,kit={}) {
  const level=b.levels?.find(l=>l.id===s.level)||[...(b.levels||[])].sort((a,c)=>c.elevation-a.elevation).find(l=>l.elevation+.5<s.plate);
  const {ref,source}=resolveSurfaceMaterial(plan,{role:'roof',building:b,level,kit,
    ref:s.plane_materials?.[String(edge)],parents:[s.material,s.materials?.roof]});
  const entry=(kit.manifest||{})[source.id]||(kit.manifest||{})[ref.id];
  const pitch=entry?.params?.pitch_m ?? entry?.pitch_m ?? kit.materials?.[ref.id]?.pitch_m;
  const pan=source.id==='standing_seam';
  return {pan,pitch:Number.isFinite(pitch)&&pitch>=.03&&pitch<=1?pitch:pan?1.5*FT:null};
}
export function eavePitch(plan,b,s,edge,kit={}) {return eavePattern(plan,b,s,edge,kit).pitch;}

export function extractEaves(plan={},roofs=new Map(),kit={}) {
  const frames=(plan.buildings||[]).map(b=>buildingFrame(plan,b)),result=[],seen=new Set();
  for(const frame of frames){
    const {b}=frame,sections=roofs?.get(b.id)?.sections||b.roof?.sections||[];
    if(!sections.length)continue;
    const envelope=roofs?.get(b.id)||{...roofMesh(sections),sections},groups=new Map();
    for(let t=0;t<envelope.section.length;t++){
      const index=envelope.section[t],s=sections[index];
      if(!s||s.kind==='flat')continue;
      const face=planes(s).find(p=>p.side===envelope.side[t]);
      if(!face||Math.hypot(face[0],face[1])<EPS)continue;
      const triangle=[0,3,6].map(i=>Array.from(envelope.positions.slice(t*9+i,t*9+i+3)));
      for(let i=0;i<3;i++){
        const a=triangle[i],d=triangle[(i+1)%3];
        if(Math.abs(a[2]-d[2])>EPS)continue; // rakes / hips / valleys
        for(let axis=0;axis<2;axis++)for(const sign of [-1,1]){
          const end=s.rect[axis+(sign>0?2:0)]+sign*(s.overhang||0),along=1-axis;
          if(Math.abs(a[axis]-end)>EPS||Math.abs(d[axis]-end)>EPS||face[axis]*sign>=-EPS)continue;
          const lo=Math.min(a[along],d[along]),hi=Math.max(a[along],d[along]);
          if(hi-lo<EPS)continue;
          const key=`${index}:${axis}:${sign}:${a[2].toFixed(4)}`;
          if(!groups.has(key))groups.set(key,{index,s,edge:envelope.edge?.[t],axis,along,sign,end,z:a[2],ranges:[]});
          groups.get(key).ranges.push([lo,hi]);
        }
      }
    }
    for(const g of groups.values()){
      const merged=[];
      for(const r of g.ranges.sort((a,b)=>a[0]-b[0])){
        const prev=merged.at(-1);if(prev&&r[0]<=prev[1]+EPS)prev[1]=Math.max(prev[1],r[1]);else merged.push([...r]);
      }
      for(const [lo,hi] of merged){
        const local=u=>{const p=[0,0,g.z];p[g.axis]=g.end;p[g.along]=u;return p;};
        const a=frame.world(local(lo)),b=frame.world(local(hi));
        const key=[a,b].map(p=>p.map(v=>v.toFixed(4)).join(',')).sort().join(':');
        if(seen.has(key))continue;seen.add(key);
        const n=[0,0,0];n[g.axis]=g.sign;
        const origin=frame.world([0,0,0]),tip=frame.world(n);
        result.push({a,b,outward:[tip[0]-origin[0],0,tip[2]-origin[2]],building:frame.b.id,
          section:g.index,kind:g.s.kind,gridStart:lo*FT,
          ...eavePattern(plan,frame.b,g.s,g.edge,kit)});
      }
    }
    // Coverings outside the section envelope (wall awnings / continuations)
    // retain their actual top triangles before batching. Horizontal downhill
    // edges only: triangle diagonals, high wall edges and rakes cannot qualify.
    for(const attachment of envelope.eaveAttachments||[]){
      const p=attachment.positions;
      for(let t=0;t<p.length;t+=9){
        const tri=[0,3,6].map(i=>new THREE.Vector3(...p.slice(t+i,t+i+3)));
        const normal=new THREE.Vector3().crossVectors(tri[1].clone().sub(tri[0]),tri[2].clone().sub(tri[0]));
        if(normal.z<EPS||Math.hypot(normal.x,normal.y)<EPS)continue;
        const gx=-normal.x/normal.z,gy=-normal.y/normal.z;
        for(let i=0;i<3;i++){
          const a=tri[i],b=tri[(i+1)%3],dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy);
          if(Math.abs(a.z-b.z)>EPS||len<EPS||(gx*dy-gy*dx)/len>=-EPS)continue;
          const start=frame.world(a.toArray()),end=frame.world(b.toArray()),o=frame.world([a.x+dy/len,a.y-dx/len,a.z]);
          const key=[start,end].map(p=>p.map(v=>v.toFixed(4)).join(',')).sort().join(':');if(seen.has(key))continue;seen.add(key);
          const s=sections[attachment.section];
          const pattern=eavePattern(plan,frame.b,s,null,kit),{pitch}=pattern;
          result.push({a:start,b:end,outward:[o[0]-start[0],0,o[2]-start[2]],building:frame.b.id,section:attachment.section,
            kind:'attachment',gridStart:pitch===null?0:-pitch*.5,...pattern});
        }
      }
    }
  }
  return clipExposedEdges(result,frames,roofs);
}

function clipExposedEdges(edges,frames,roofs) {
  // Split at every projected covering/wall boundary, then test every open
  // interval. One midpoint for an entire edge misses partial abutments.
  const roofsWorld=[],walls=[];
  for(const frame of frames){
    const snapshot=roofs?.get(frame.b.id)||roofMesh(frame.b.roof?.sections||[]),positions=snapshot.coverPositions||snapshot.positions;
    for(let t=0;t<positions.length;t+=9){
      const p=[0,3,6].map(i=>frame.world(Array.from(positions.slice(t+i,t+i+3))));
      roofsWorld.push({polygon:p.map(v=>[v[0],v[2]]),p:p.map(v=>new THREE.Vector3(...v)),top:Math.max(...p.map(v=>v[1]))});
    }
    for(const level of frame.b.levels||[])if(level.outline?.length>=3)walls.push({polygon:level.outline.map(p=>{
      const v=frame.world([...p,0]);return [v[0],v[2]];}),bottom:(frame.base+level.elevation)*FT,top:(frame.base+level.elevation+level.ceiling)*FT});
  }
  const result=[],ray=new THREE.Ray(new THREE.Vector3(),new THREE.Vector3(0,-1,0)),hit=new THREE.Vector3();
  for(const edge of edges){
    const length=Math.hypot(edge.b[0]-edge.a[0],edge.b[2]-edge.a[2]),n=Math.hypot(...edge.outward);
    const a=[edge.a[0]+edge.outward[0]/n*.012,edge.a[2]+edge.outward[2]/n*.012];
    const b=[edge.b[0]+edge.outward[0]/n*.012,edge.b[2]+edge.outward[2]/n*.012];
    const cutters=[...roofsWorld.filter(t=>t.top>=edge.a[1]-.003),...walls.filter(t=>t.bottom<edge.a[1]&&t.top>edge.a[1]+.003)],cuts=[0,1];
    for(const c of cutters)for(let i=0;i<c.polygon.length;i++){
      const p=segmentIntersection(a,b,c.polygon[i],c.polygon[(i+1)%c.polygon.length]);
      if(p)cuts.push(Math.hypot(p[0]-a[0],p[1]-a[1])/length);
    }
    cuts.sort((a,b)=>a-b);
    let open=null;
    const flush=()=>{if(open){const start=edge.a.map((v,i)=>v+(edge.b[i]-v)*open[0]),end=edge.a.map((v,i)=>v+(edge.b[i]-v)*open[1]);
      result.push({...edge,a:start,b:end,gridStart:edge.gridStart+open[0]*length});open=null;}};
    for(let i=0;i+1<cuts.length;i++){
      if((cuts[i+1]-cuts[i])*length<1e-5)continue;
      const t=(cuts[i]+cuts[i+1])/2,x=a[0]+(b[0]-a[0])*t,z=a[1]+(b[1]-a[1])*t;
      ray.origin.set(x,edge.a[1]+10000,z);
      const blocked=cutters.some(c=>c.p?ray.intersectTriangle(...c.p,false,hit)&&hit.y>=edge.a[1]-.003:inPolygon(c.polygon,x,z));
      if(blocked)flush();else if(open)open[1]=cuts[i+1];else open=[cuts[i],cuts[i+1]];
    }
    flush();
  }
  return result;
}

// Static down-rays against the actual triangulated roof envelope, plus the
// authored deck/paving and terrain receivers used by precipitation. The ray
// starts just outside the lip, so it cannot hit its own fascia/underside.
export function createEaveLandingSampler(plan={},roofs=new Map()) {
  const triangles=[],decks=[],hard=collectHardSurfaces(plan),caps=collectCapSurfaces(plan);
  for(const b of plan.buildings||[]){
    const f=buildingFrame(plan,b),roof=roofs?.get(b.id)||roofMesh(b.roof?.sections||[]);
    const positions=[...(roof.coverPositions||roof.positions),...(roof.slabPositions||[])];
    for(let t=0;t<positions.length;t+=9){
      const p=[0,3,6].map(i=>new THREE.Vector3(...f.world(positions.slice(t+i,t+i+3))));
      triangles.push({p,x0:Math.min(...p.map(v=>v.x)),x1:Math.max(...p.map(v=>v.x)),z0:Math.min(...p.map(v=>v.z)),z1:Math.max(...p.map(v=>v.z))});
    }
    for(const p of allPorches(b))if(p.polygon?.length>=3){
      const room=b.rooms?.find(r=>r.kind==='porch'&&r.level===(p.level||b.levels?.[0]?.id)&&inPolygon(r.polygon,...p.polygon[0]));
      decks.push({frame:f,polygon:p.polygon,height:(f.base+(p.floor||0)+(room?.floor_offset_ft||0))*FT});
    }
  }
  const ray=new THREE.Ray(new THREE.Vector3(),new THREE.Vector3(0,-1,0)),hit=new THREE.Vector3();
  return top=>{
    const [x,y,z]=top,px=x/FT,py=-z/FT;let height=groundAt(plan,px,py)*FT,kind='ground';
    const offer=(h,k)=>{if(h<y-.005&&h>=height){height=h;kind=k;}};
    for(const h of hard)if(inPolygon(h.polygon,px,py))offer(((h.flat??groundAt(plan,px,py))+h.elevation)*FT,'hardscape');
    for(const cap of caps)if(inPolygon(cap.polygon,px,py)&&!(cap.holes||[]).some(p=>inPolygon(p,px,py)))offer(cap.top*FT,'cap');
    for(const bed of plan.site?.beds||[])if(bed.polygon&&inPolygon(bed.polygon,px,py))offer((groundAt(plan,px,py)+(bed.elevation||0)+.12)*FT,'bed');
    const pool=plan.site?.pool;
    if(pool?.polygon&&inPolygon(pool.polygon,px,py))offer((poolDatum(plan,pool)-.25)*FT,'water');
    for(const d of decks){const p=d.frame.local(top);if(inPolygon(d.polygon,...p))offer(d.height,'deck');}
    ray.origin.set(x,y-.005,z);
    for(const t of triangles)if(x>=t.x0&&x<=t.x1&&z>=t.z0&&z<=t.z1
      &&ray.intersectTriangle(...t.p,false,hit))offer(hit.y,'roof');
    return {height,kind};
  };
}

export function eaveInstances(plan={},roofs=new Map(),kit={}) {
  const eaves=extractEaves(plan,roofs,kit),sample=createEaveLandingSampler(plan,roofs),instances=[];
  let serial=1;
  for(const e of eaves){
    const dx=e.b[0]-e.a[0],dz=e.b[2]-e.a[2],length=Math.hypot(dx,dz),n=Math.hypot(...e.outward);
    // A standing-seam pan sheds across its whole edge, not just at its seam.
    // Subdivide its actual pitch into ~9 cm cells, jittered within each pan.
    // Corrugated/exposed trough pitch stays exact. Unknown profiles reserve a
    // dense irregular curtain; GPU/instance-count thinning supplies light rain.
    const step=e.pan?e.pitch/Math.max(2,Math.ceil(e.pitch/.1)):e.pitch;
    let grid=step?Math.ceil((e.gridStart+.0001)/step)*step-e.gridStart:.035+hash(serial)*.035;
    for(;grid<length-.02;grid+=step||(.065+.05*hash(++serial))){
      const distance=grid+(e.pan?(hash(serial+71)-.5)*step*.3:0);
      if(distance<=.015||distance>=length-.015){serial++;continue;}
      const u=distance/length,top=[e.a[0]+dx*u+e.outward[0]/n*.012,e.a[1],e.a[2]+dz*u+e.outward[2]/n*.012];
      const landing=sample(top);
      if(top[1]-landing.height<.08)continue;
      const seed=hash(++serial);
      instances.push({top,bottom:landing.height,landing:landing.kind,seed,rank:hash(serial+17389),eave:e});
    }
  }
  // Prefix thinning removes actual vertex work on Low; hash order spreads it
  // over every edge rather than taking only the first side of the first house.
  // Activation order is independent of visual seed, so Low is not restricted
  // to the same thin/dim/early-phase streams.
  instances.sort((a,b)=>a.rank-b.rank);
  return {eaves,instances};
}

// Scalar shape functions are also exercised directly from the actual shader
// source by the Node regression tests; no separately maintained look model.
const waterShape=`
float eaveWidth(float fall,float time,float seed,float flow){
  float thickness=.35+1.45*fract(seed*31.73);
  float swell=.78+.22*sin(fall*7.1-time*2.4+seed*67.);
  return mix(.0018,.0085,flow)*thickness*swell;
}
float eaveWobble(float fall,float time,float seed){
  return sin(fall*2.4-time*.85+seed*60.)*.012+sin(fall*5.7-time*1.7+seed*31.)*.003;
}
float eavePresence(float fall,float fallLength,float time,float seed,float flow){
  float strength=fract(seed*19.19);
  if(flow<.26){
    float frequency=.12+flow*1.5;
    float age=fract(time*frequency+seed*17.)/frequency;
    return 1.-smoothstep(.008,.028,abs(fall-4.9*age*age));
  }
  float phase=fract((fall-time*(1.4+seed*1.8))/(.18+.32*seed)+seed*40.);
  float duty=mix(.16,.84,flow)*mix(.55,1.,strength);
  duty*=1.-smoothstep(.18,1.,fall/max(fallLength,.01))*(1.-strength)*mix(.75,.18,flow);
  float broken=1.-smoothstep(duty,duty+.08,phase);
  float continuous=smoothstep(.65,.98,flow)*smoothstep(.55,.93,strength);
  continuous*=1.-smoothstep(.35,1.,fall/max(fallLength,.01))*(1.-strength)*.8;
  return mix(broken,1.,continuous);
}
float eaveGlint(float fall,float time,float seed){
  float wave=.5+.5*sin(fall*11.3-time*4.1+seed*91.);
  return smoothstep(.45,.98,wave)*(.3+.7*fract(seed*47.13));
}
float eaveOpacity(float across,float glint,float flow){
  float q=abs(across);
  float rim=smoothstep(.12,.72,q)*(1.-smoothstep(.72,1.,q));
  // Clear cylindrical centre, soft grazing edges and travelling highlights.
  return (.012+.19*rim*(.25+glint)+.075*glint)*(1.-smoothstep(.8,1.,q))*mix(.55,1.,flow);
}
float eaveSpray(float across,float height,float time,float seed,float flow){
  float skew=across+.13*sin(height*7.+seed*33.+time*4.);
  float edge=1.-smoothstep(.5,1.,abs(skew));
  float ceiling=.3+.3*fract(seed*11.)+.13*sin(across*11.+time*7.+seed*39.);
  float top=1.-smoothstep(ceiling-.18,ceiling+.16,height);
  float patches=smoothstep(.15,.7,.5+.5*sin(across*15.+height*9.-time*6.+seed*87.));
  float pulse=.35+.65*(1.-fract(time*(2.7+seed*3.)+seed*23.));
  return smoothstep(0.,.12,height)*edge*top*patches*pulse*mix(.02,.065,flow)*smoothstep(.26,.8,flow);
}
float eaveSprayHeight(float seed,float flow){return (.025+flow*.065)*(.7+seed*.6);}
float eaveSprayWidth(float seed,float flow){return (.18+flow*.2)*(.7+seed*.6);}
float eaveNearFade(float distanceM,float depth){
  return smoothstep(.45,1.25,distanceM)*smoothstep(.12,.5,depth);
}
`;
const vertexShader=waterShape+`
attribute vec4 eaveTop;attribute float eaveBottom,eaveRank;
uniform float eaveTime,eaveFlow,eaveMist,eaveDensity;
varying vec2 waterUv;varying vec3 waterWorld;varying float waterSeed,waterLength,waterDepth;
void main(){
  waterUv=uv;waterSeed=eaveTop.w;waterLength=eaveTop.y-eaveBottom;
  float d=distance(cameraPosition,eaveTop.xyz);
  float density=(1.0-smoothstep(8.0,42.0,d))*eaveDensity;
  if(eaveRank>density){gl_Position=vec4(2.,2.,2.,1.);return;}
  vec3 world=eaveTop.xyz;
  vec3 right=vec3(viewMatrix[0][0],0.,viewMatrix[2][0]);right=normalize(right+vec3(.00001,0.,0.));
  if(eaveMist>.5){
    float pulse=fract(eaveTime*(2.7+waterSeed*3.)+waterSeed*23.);
    world.y=eaveBottom+.008+uv.y*eaveSprayHeight(waterSeed,eaveFlow);
    world+=right*((uv.x-.5)*eaveSprayWidth(waterSeed,eaveFlow)+(pulse-.5)*.035);
  }else{
    float fall=uv.y*waterLength;
    world.y=eaveTop.y-fall;
    float wobble=eaveWobble(fall,eaveTime,waterSeed)*smoothstep(0.,.2,fall);
    world+=right*((uv.x-.5)*eaveWidth(fall,eaveTime,waterSeed,eaveFlow)+wobble);
  }
  waterWorld=world;
  vec4 eye=viewMatrix*vec4(world,1.);waterDepth=-eye.z;
  gl_Position=projectionMatrix*eye;
  // Whole-instance GPU frustum rejection; no per-frame CPU instance visits.
  vec4 topClip=projectionMatrix*viewMatrix*vec4(eaveTop.xyz,1.);
  vec4 lowClip=projectionMatrix*viewMatrix*vec4(eaveTop.x,eaveBottom,eaveTop.z,1.);
  if((topClip.x < -topClip.w&&lowClip.x < -lowClip.w)||(topClip.x > topClip.w&&lowClip.x > lowClip.w)
    ||(topClip.y < -topClip.w&&lowClip.y < -lowClip.w)||(topClip.y > topClip.w&&lowClip.y > lowClip.w)
    ||(topClip.w<0.&&lowClip.w<0.))gl_Position=vec4(2.,2.,2.,1.);
}`;
const fragmentShader=waterShape+`
uniform float eaveTime,eaveFlow,eaveWet,eaveMist,eaveFog;
uniform vec3 eaveColour;
uniform vec4 eaveLamps[4];uniform vec3 eaveLampColours[4];
varying vec2 waterUv;varying vec3 waterWorld;varying float waterSeed,waterLength,waterDepth;
void main(){
  float nearFade=eaveNearFade(distance(waterWorld,cameraPosition),waterDepth);
  if(nearFade<.001)discard;
  float alpha,glint=0.;
  if(eaveMist>.5){
    alpha=eaveSpray(waterUv.x*2.-1.,waterUv.y,eaveTime,waterSeed,eaveFlow);
  }else{
    float fall=waterUv.y*waterLength;
    glint=eaveGlint(fall,eaveTime,waterSeed);
    alpha=eavePresence(fall,waterLength,eaveTime,waterSeed,eaveFlow)
      *eaveOpacity(waterUv.x*2.-1.,glint,eaveFlow);
    alpha*=smoothstep(0.,.015,waterUv.y)*(1.-smoothstep(.985,1.,waterUv.y));
  }
  alpha*=nearFade*min(1.,eaveWet*5.)*exp(-eaveFog*distance(waterWorld,cameraPosition));
  if(alpha<.001)discard;
  vec3 illumination=eaveColour;
  for(int i=0;i<4;i++){
    vec3 delta=waterWorld-eaveLamps[i].xyz;
    illumination+=eaveLampColours[i]*eaveLamps[i].w/(1.+dot(delta,delta));
  }
  gl_FragColor=vec4(illumination*(eaveMist>.5?1.05:.65+1.8*glint),alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

function geometry(instances,segments) {
  const g=new THREE.InstancedBufferGeometry(),vertices=[],uv=[],indices=[];
  for(let j=0;j<=segments;j++)for(let i=0;i<2;i++){vertices.push(i-.5,j/segments,0);uv.push(i,j/segments);}
  for(let j=0;j<segments;j++){const k=j*2;indices.push(k,k+1,k+3,k,k+3,k+2);}
  g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.setIndex(indices);
  g.setAttribute('eaveTop',new THREE.InstancedBufferAttribute(new Float32Array(instances.flatMap(i=>[...i.top,i.seed])),4));
  g.setAttribute('eaveBottom',new THREE.InstancedBufferAttribute(new Float32Array(instances.map(i=>i.bottom)),1));
  g.setAttribute('eaveRank',new THREE.InstancedBufferAttribute(new Float32Array(instances.map((_,i)=>(i+.5)/instances.length)),1));
  const box=new THREE.Box3();for(const i of instances){box.expandByPoint(new THREE.Vector3(...i.top));box.expandByPoint(new THREE.Vector3(i.top[0],i.bottom,i.top[2]));}
  if(instances.length){box.expandByScalar(.5);g.boundingBox=box;g.boundingSphere=box.getBoundingSphere(new THREE.Sphere());}
  g.instanceCount=instances.length;return g;
}

export function createEaveStreams(scene,{tier='high',colour=null}={}) {
  const group=new THREE.Group();group.name='weather-eave-streams';group.visible=false;scene.add(group);
  const uniforms={eaveTime:{value:0},eaveFlow:{value:0},eaveWet:{value:0},eaveFog:{value:0},eaveDensity:{value:0},
    eaveColour:colour||{value:new THREE.Vector3(.6,.7,.8)},
    eaveLamps:{value:Array.from({length:4},()=>new THREE.Vector4())},
    eaveLampColours:{value:Array.from({length:4},()=>new THREE.Color())}};
  const materials=[0,1].map(kind=>new THREE.ShaderMaterial({name:'EaveWater',vertexShader,fragmentShader,
    uniforms:{...uniforms,eaveMist:{value:kind}},transparent:true,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true}));
  let data={eaves:[],instances:[]},streams=null,mist=null,disposed=false,maximum=0;
  let lastFlow=null,lastTime=null,decliningAt=null,lastDecline=-Infinity;
  const clear=()=>{for(const o of [streams,mist])if(o){o.geometry.dispose();group.remove(o);}streams=mist=null;group.visible=false;};
  return {group,uniforms,get data(){return data;},get streams(){return streams;},get mist(){return mist;},
    setPlan(plan={},roofs=new Map(),kit={}){
      if(disposed)return;clear();data=eaveInstances(plan||{},roofs,kit);
      const count=Math.floor(data.instances.length*(tier==='low'?.35:tier==='medium'?.65:1));
      maximum=count;
      if(!count)return;
      const selected=data.instances.slice(0,count);
      streams=new THREE.Mesh(geometry(selected,12),materials[0]);mist=new THREE.Mesh(geometry(selected,1),materials[1]);
      streams.name='eave-streams';mist.name='eave-mist';
      group.add(streams,mist);
    },
    update({flow=0,wet=0}={},seconds=0,{camera=null,target=null,level='house',unlit=false,neutral=false,fog=0,light=null,lamps=[]}={}){
      if(disposed)return;
      flow=clamp(flow);wet=clamp(wet);
      const now=Number.isFinite(seconds)?seconds:0,observedFlow=flow;
      // The merged roof reservoir drains for ~10 minutes. The free eave loses
      // its coherent columns much sooner. Detect sustained falling input in
      // constant time; a single rain-rate step followed by a steady value does
      // not keep drying, and any renewed/increased flow cancels the latch.
      if(lastTime!==null&&now<lastTime||flow<=.002||lastFlow!==null&&flow>lastFlow+1e-5){decliningAt=null;lastDecline=-Infinity;}
      else if(lastFlow!==null&&flow<lastFlow-1e-7){if(decliningAt===null)decliningAt=now;lastDecline=now;}
      else if(now-lastDecline>.8)decliningAt=null;
      if(decliningAt!==null)flow*=Math.exp(-Math.max(0,now-decliningAt)/25);
      lastFlow=observedFlow;lastTime=now;
      const demand=flow>.002&&wet>0?.35+.65*smooth(.08,.85,flow):0;
      uniforms.eaveTime.value=now%4096;uniforms.eaveDensity.value=demand;
      uniforms.eaveFlow.value=flow;uniforms.eaveWet.value=wet;uniforms.eaveFog.value=Math.max(0,Number.isFinite(fog)?fog:0);
      const steep=camera&&target&&(camera.position.y-target.y)/Math.max(.001,camera.position.distanceTo(target))>.94;
      let density=1;
      if(camera&&streams)density=1-smooth(LOD_NEAR,LOD_FAR,streams.geometry.boundingBox.distanceToPoint(camera.position));
      if(streams){
        streams.geometry.instanceCount=Math.ceil(maximum*density*demand);
        mist.geometry.instanceCount=flow>.26?Math.ceil(maximum*density*demand*.5):0;
        mist.visible=mist.geometry.instanceCount>0;
      }
      group.visible=!!streams&&density>0&&!unlit&&!neutral&&level==='house'&&!steep&&flow>.002&&wet>0;
      if(!group.visible)return;
      if(light)uniforms.eaveColour.value.fromArray(light);
      // Bounded light input only, independent of the number of water instances.
      // It includes baked lamps (moving water cannot use their static atlas).
      let count=0;
      for(const lamp of (typeof lamps==='function'?lamps():lamps)||[]){
        if(!(lamp.intensity>0)||!lamp.at||!lamp.rgb)continue;
        const p=uniforms.eaveLamps.value[count];p.set(lamp.at[0]*FT,lamp.at[2]*FT,-lamp.at[1]*FT,clamp(lamp.intensity)*2);
        uniforms.eaveLampColours.value[count].setRGB(lamp.rgb[0]/255,lamp.rgb[1]/255,lamp.rgb[2]/255,THREE.SRGBColorSpace);
        if(++count===4)break;
      }
      for(;count<4;count++)uniforms.eaveLamps.value[count].w=0;
    },
    dispose(){if(disposed)return;disposed=true;clear();for(const m of materials)m.dispose();group.removeFromParent();},
  };
}
